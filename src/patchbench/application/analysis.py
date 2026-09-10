"""Read-only integrity checking and composition of persisted Experiment evidence."""

from pydantic import ValidationError

from patchbench.domain.analysis import ExperimentAnalysis, RunEvidence
from patchbench.domain.aggregation import aggregate_runs
from patchbench.domain.comparison import compare_pass_fail_runs
from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.domain.evaluation_evidence import summarize_evaluation_log
from patchbench.domain.failure import FailureCategory, classify_run_failure
from patchbench.domain.models import RunStatus
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.storage.filesystem import FilesystemArtifactStore


class AnalysisError(ValueError):
    """Persisted Experiment inputs are inconsistent or cannot be verified."""


def analyze_experiment(
    experiment_id: str, *, artifact_store: FilesystemArtifactStore,
) -> ExperimentAnalysis:
    experiment = artifact_store.load_experiment_record(experiment_id)
    configuration = experiment.configuration
    children, patches, evidence = [], [], []
    for run_id in experiment.run_ids:
        run = artifact_store.load_run_record(run_id)
        raw_patch = artifact_store.load_run_patch(run_id)
        raw_log = artifact_store.load_run_test_log(run_id)
        try:
            patch = summarize_patch(raw_patch)
            evaluation = summarize_evaluation_log(raw_log)
        except (EvidenceParsingError, ValidationError) as error:
            raise AnalysisError(f"Run '{run_id}' raw evidence: {error}") from error
        if run.patch_summary is not None and run.patch_summary != patch:
            raise AnalysisError(f"Run '{run_id}' patch summary differs from raw artifact")
        if run.evaluation_evidence is not None and run.evaluation_evidence != evaluation:
            raise AnalysisError(f"Run '{run_id}' evaluation evidence differs from raw artifact")
        if evaluation.passed != run.evaluation_passed:
            raise AnalysisError(f"Run '{run_id}' evaluation outcome differs from raw log")
        expected_status = RunStatus.PASSED if run.evaluation_passed else RunStatus.FAILED
        if run.status != expected_status:
            raise AnalysisError(f"Run '{run_id}' status disagrees with evaluation outcome")
        for field, actual, expected in (
            ("task_id", run.task_id, experiment.task_id),
            ("agent name", run.agent.name, configuration.agent_name),
            ("requested model", run.agent.requested_model, configuration.requested_model),
            ("agent timeout", run.agent.timeout_seconds, configuration.agent_timeout_seconds),
        ):
            if actual != expected:
                raise AnalysisError(f"Run '{run_id}' {field} disagrees with Experiment")
        if (run.provenance is not None
                and run.provenance.evaluation_backend != configuration.evaluation_backend):
            raise AnalysisError(f"Run '{run_id}' evaluation backend disagrees with Experiment")
        children.append(run)
        patches.append(raw_patch)
        evidence.append(RunEvidence(
            run_id=run_id, evaluation_passed=run.evaluation_passed,
            agent_status=run.agent.status, duration_seconds=run.duration_seconds,
            failure_categories=classify_run_failure(run, patch_text=raw_patch).categories,
            patch=patch, evaluation=evaluation,
        ))
    aggregate = aggregate_runs(children)
    if aggregate != experiment.aggregate:
        raise AnalysisError("Experiment aggregate differs from recomputed child aggregate")
    provenance = children[0].provenance
    if any(child.provenance != provenance for child in children):
        raise AnalysisError("Experiment has mixed or conflicting Run provenance")
    first_pass = next((i for i, run in enumerate(children) if run.evaluation_passed), None)
    first_fail = next((i for i, run in enumerate(children) if not run.evaluation_passed), None)
    pair = None
    if first_pass is not None and first_fail is not None:
        pair = compare_pass_fail_runs(
            children[first_pass], children[first_fail],
            pass_patch_text=patches[first_pass], fail_patch_text=patches[first_fail],
        )
    return ExperimentAnalysis(
        experiment_id=experiment.experiment_id, task_id=experiment.task_id,
        configuration=configuration, aggregate=aggregate, provenance=provenance,
        exact_patch_variant_count=len({run.patch.patch_sha256 for run in evidence}),
        failure_category_counts={
            category.value: sum(category in run.failure_categories for run in evidence)
            for category in FailureCategory
        },
        runs=evidence, example_pair=pair,
    )
