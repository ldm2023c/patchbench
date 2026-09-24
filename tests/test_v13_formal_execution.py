"""Provider-free tests for the PatchBench V1.3 formal execution harness."""

import json
from pathlib import Path
import threading

import pytest

from patchbench.agents.base import (
    AgentInfrastructureError, AgentProviderTransportError,
    AgentRunStatus, AgentSetupError,
)
from patchbench.application import v13_formal_execution as execution
from patchbench.application.v13_agent_execution import resolve_v13_agent_config
from patchbench.domain import (
    AgentExecutionMetadata, EvaluationResult, ExperimentAggregate,
    ExperimentRecord, FormalAttemptStatus, FormalFailureCategory,
    FormalSlotStatus, FormalStudyStatus, RunProvenance, RunRecord, RunStatus,
    render_evaluation_log, summarize_evaluation_log, summarize_patch,
)
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.sandbox.docker import DockerSandboxError
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore
from scripts.v13_formal_preregistration import verify_preregistration


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeSandbox:
    pass


def _initialize(tmp_path: Path):
    results = tmp_path / "formal"
    ledger = execution.initialize_formal_study(
        project_root=PROJECT_ROOT, results_root=results
    )
    return results, ledger


def _write_canonical_run(
    results_root: Path,
    config_id: str,
    task_path: Path,
    *,
    agent_status: AgentRunStatus = AgentRunStatus.COMPLETED,
    evaluation_passed: bool = True,
    suffix: str = "one",
) -> ExperimentRecord:
    prereg = verify_preregistration(PROJECT_ROOT)
    # The runner's task path uniquely selects the current preregistered task.
    from patchbench.config.task_loader import load_task
    from patchbench.domain.provenance import compute_task_fingerprint
    task = load_task(task_path)
    slot = next(item for item in prereg.slots
                if item.config_id == config_id and item.task_id == task.id)
    plan = resolve_v13_agent_config(
        config_id, evaluation_backend="docker", project_root=PROJECT_ROOT
    )
    run_id = f"synthetic-{slot.ordinal:03d}-{suffix}"
    store = FilesystemArtifactStore(results_root)
    paths = store.create_paths(run_id)
    patch = ""
    result = EvaluationResult(
        exit_code=0 if evaluation_passed else 1,
        passed=evaluation_passed,
        duration_seconds=0.2,
        stdout="synthetic tests\n",
        stderr="" if evaluation_passed else "synthetic failure\n",
    )
    test_log = render_evaluation_log(result, task.evaluation.command)
    record = RunRecord(
        run_id=run_id,
        task_id=task.id,
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=1.0,
        agent=AgentExecutionMetadata(
            name=plan.experiment_configuration.agent_name,
            backend="host", status=agent_status,
            exit_code=(0 if agent_status is AgentRunStatus.COMPLETED else None),
            duration_seconds=0.5,
            timeout_seconds=plan.experiment_configuration.agent_timeout_seconds,
            requested_model=plan.experiment_configuration.requested_model,
            identity_binding=plan.identity_binding,
        ),
        artifacts=paths,
        provenance=RunProvenance(
            base_commit_used=slot.resolved_base_commit,
            task_fingerprint_sha256=compute_task_fingerprint(
                task, base_commit_used=slot.resolved_base_commit
            ),
            evaluation_command=task.evaluation.command,
            evaluation_timeout_seconds=task.evaluation.timeout_seconds,
            evaluation_backend="docker",
        ),
        patch_summary=summarize_patch(patch),
        evaluation_evidence=summarize_evaluation_log(test_log),
    )
    paths.metadata.write_text(json.dumps(record.model_dump(mode="json"), indent=2) + "\n")
    paths.prompt.write_text(task.task.prompt)
    paths.agent_log.write_text("synthetic stdout\n")
    paths.agent_stderr_log.write_text("")
    paths.test_log.write_text(test_log)
    paths.patch.write_text(patch)
    return ExperimentRecord(
        experiment_id=f"experiment-{slot.ordinal:03d}-{suffix}",
        task_id=task.id, requested_runs=1, run_ids=[run_id],
        configuration=plan.experiment_configuration,
        aggregate=ExperimentAggregate(
            run_count=1, evaluation_pass_count=int(evaluation_passed),
            evaluation_fail_count=int(not evaluation_passed),
            evaluation_pass_rate=float(evaluation_passed),
            agent_command_failure_count=int(agent_status is AgentRunStatus.COMMAND_FAILED),
            agent_timeout_count=int(agent_status is AgentRunStatus.TIMED_OUT),
            total_duration_seconds=1.0, mean_duration_seconds=1.0,
            min_duration_seconds=1.0, max_duration_seconds=1.0,
        ),
        duration_seconds=1.0,
    )


def _runner(*, status=AgentRunStatus.COMPLETED, passed=True, calls=None,
            experiment_mutation=None, artifact_mutation=None, raise_after=None):
    calls = calls if calls is not None else []
    def run(task_path, **kwargs):
        calls.append(kwargs["config_id"])
        experiment = _write_canonical_run(
            kwargs["results_root"], kwargs["config_id"], Path(task_path),
            agent_status=status, evaluation_passed=passed,
        )
        if artifact_mutation:
            artifact_mutation(kwargs["results_root"], experiment.run_ids[0])
        if raise_after:
            raise raise_after
        if experiment_mutation:
            experiment = experiment_mutation(experiment)
        return experiment
    return run


def _run_next(results: Path, runner):
    return execution.run_next_formal_attempt(
        project_root=PROJECT_ROOT, results_root=results,
        workspace_root=results.parent / "workspaces", sandbox=FakeSandbox(),
        runner=runner,
    )


def test_init_verifies_and_creates_exact_pending_plan_without_runner(tmp_path):
    results, ledger = _initialize(tmp_path)
    prereg = verify_preregistration(PROJECT_ROOT)
    assert results == tmp_path / "formal"
    assert ledger.status is FormalStudyStatus.READY
    assert len(ledger.slots) == 108
    assert all(slot.status is FormalSlotStatus.PENDING for slot in ledger.slots)
    assert [(s.ordinal, s.slot_id, s.task_id, s.config_id) for s in ledger.slots] == [
        (s.ordinal, s.slot_id, s.task_id, s.config_id) for s in prereg.slots
    ]
    assert list(results.iterdir()) == [results / "slots", results / "study.json"] or set(
        p.name for p in results.iterdir()) == {"slots", "study.json"}


def test_default_formal_namespace_is_frozen():
    assert execution.DEFAULT_FORMAL_RESULTS_PATH.as_posix() == "results/v1.3-formal"


def test_second_init_rejects_without_reset(tmp_path):
    results, _ = _initialize(tmp_path)
    with pytest.raises(execution.FormalExecutionStateError, match="already exists"):
        execution.initialize_formal_study(
            project_root=PROJECT_ROOT, results_root=results
        )


def test_preregistration_failure_prevents_namespace_creation(tmp_path, monkeypatch):
    results = tmp_path / "formal"
    monkeypatch.setattr(execution, "verify_preregistration",
                        lambda root: (_ for _ in ()).throw(RuntimeError("drift")))
    with pytest.raises(RuntimeError, match="drift"):
        execution.initialize_formal_study(project_root=PROJECT_ROOT, results_root=results)
    assert not results.exists()


@pytest.mark.parametrize(("status", "passed"), [
    (AgentRunStatus.COMPLETED, True),
    (AgentRunStatus.COMPLETED, False),
    (AgentRunStatus.COMMAND_FAILED, False),
    (AgentRunStatus.TIMED_OUT, False),
])
def test_complete_canonical_evidence_terminalizes_without_retry(tmp_path, status, passed):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, _runner(status=status, passed=passed))
    slot = ledger.slots[0]
    assert slot.status is FormalSlotStatus.CANONICAL_OBSERVED
    assert slot.canonical_agent_status is status
    assert slot.canonical_evaluation_passed is passed
    assert slot.attempts == (1,)
    attempt = execution._load_attempt(results / "slots" / slot.slot_id / "attempt-01")
    assert attempt.status is FormalAttemptStatus.CANONICAL_OBSERVED


def test_run_next_advances_strictly_one_slot_at_a_time(tmp_path):
    results, _ = _initialize(tmp_path)
    calls = []
    first = _run_next(results, _runner(calls=calls))
    second = _run_next(results, _runner(calls=calls))
    assert first.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert first.slots[1].status is FormalSlotStatus.PENDING
    assert second.slots[1].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert calls == [first.slots[0].config_id, second.slots[1].config_id]


@pytest.mark.parametrize("error", [
    AgentSetupError("safe"), AgentInfrastructureError("safe"),
    RepositoryError("safe"), DockerSandboxError("safe"),
    ArtifactStoreError("safe"),
])
def test_typed_initial_failure_requires_explicit_retry_and_blocks_progress(tmp_path, error):
    results, _ = _initialize(tmp_path)
    calls = []
    def failing(*args, **kwargs):
        calls.append(kwargs["config_id"])
        raise error
    ledger = _run_next(results, failing)
    assert ledger.status is FormalStudyStatus.RETRY_REQUIRED
    assert ledger.slots[0].status is FormalSlotStatus.RETRY_REQUIRED
    assert ledger.slots[0].attempts == (1,)
    assert not (results / "slots" / ledger.slots[0].slot_id / "attempt-02").exists()
    with pytest.raises(execution.FormalExecutionStateError, match="does not permit"):
        _run_next(results, _runner(calls=calls))
    assert len(calls) == 1


def test_provider_transport_failure_requires_same_route_retry(tmp_path):
    results, _ = _initialize(tmp_path)
    calls = []

    def failing(*args, **kwargs):
        calls.append(kwargs["config_id"])
        raise AgentProviderTransportError("safe")

    ledger = _run_next(results, failing)
    slot = ledger.slots[0]
    attempt_path = results / "slots" / slot.slot_id / "attempt-01"
    attempt = execution._load_attempt(attempt_path)

    assert ledger.status is FormalStudyStatus.RETRY_REQUIRED
    assert slot.status is FormalSlotStatus.RETRY_REQUIRED
    assert slot.canonical_run_id is None
    assert slot.canonical_agent_status is None
    assert slot.canonical_evaluation_passed is None
    assert attempt.status is FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
    assert (
        attempt.failure_category
        is FormalFailureCategory.NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE
    )
    assert attempt.canonical_run_id is None
    assert attempt.agent_status is None
    assert attempt.evaluation_passed is None
    assert list((attempt_path / "artifacts").iterdir()) == []
    with pytest.raises(execution.FormalExecutionStateError, match="does not permit"):
        _run_next(results, _runner(calls=calls))
    assert len(calls) == 1


def test_provider_transport_retry_succeeds_with_same_frozen_slot(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        AgentProviderTransportError("safe")
    ))
    original = ledger.slots[0]

    ledger = execution.retry_formal_slot(
        project_root=PROJECT_ROOT,
        results_root=results,
        slot_id=original.slot_id,
        remediation=(
            "network/provider transport availability without changing provider route"
        ),
        sandbox=FakeSandbox(),
        runner=_runner(),
    )
    retried = ledger.slots[0]

    assert (
        retried.ordinal,
        retried.slot_id,
        retried.task_id,
        retried.config_id,
        retried.repetition_index,
    ) == (
        original.ordinal,
        original.slot_id,
        original.task_id,
        original.config_id,
        original.repetition_index,
    )
    assert retried.status is FormalSlotStatus.CANONICAL_OBSERVED
    assert retried.attempts == (1, 2)
    first = execution._load_attempt(
        results / "slots" / retried.slot_id / "attempt-01"
    )
    second = execution._load_attempt(
        results / "slots" / retried.slot_id / "attempt-02"
    )
    assert first.status is FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
    assert second.status is FormalAttemptStatus.CANONICAL_OBSERVED


def test_second_provider_transport_failure_is_unresolved_then_next_advances(tmp_path):
    results, _ = _initialize(tmp_path)
    fail = lambda *a, **k: (_ for _ in ()).throw(
        AgentProviderTransportError("safe")
    )
    ledger = _run_next(results, fail)
    slot_id = ledger.slots[0].slot_id

    ledger = execution.retry_formal_slot(
        project_root=PROJECT_ROOT,
        results_root=results,
        slot_id=slot_id,
        remediation=(
            "network/provider transport availability without changing provider route"
        ),
        sandbox=FakeSandbox(),
        runner=fail,
    )

    assert ledger.slots[0].status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
    assert ledger.slots[0].attempts == (1, 2)
    second = execution._load_attempt(
        results / "slots" / slot_id / "attempt-02"
    )
    assert second.status is FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE
    assert (
        second.failure_category
        is FormalFailureCategory.NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE
    )
    with pytest.raises(execution.FormalExecutionStateError):
        execution.retry_formal_slot(
            project_root=PROJECT_ROOT,
            results_root=results,
            slot_id=slot_id,
            remediation=(
                "network/provider transport availability without changing provider route"
            ),
            sandbox=FakeSandbox(),
            runner=_runner(),
        )
    advanced = _run_next(results, _runner())
    assert advanced.slots[1].status is FormalSlotStatus.CANONICAL_OBSERVED


@pytest.mark.parametrize(
    ("error", "expected_category"),
    [
        (AgentInfrastructureError("safe"), FormalFailureCategory.AGENT_INFRASTRUCTURE),
        (AgentSetupError("safe"), FormalFailureCategory.AGENT_SETUP),
    ],
)
def test_generic_agent_failures_keep_existing_categories(
    tmp_path, error, expected_category
):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(
        results, lambda *a, **k: (_ for _ in ()).throw(error)
    )
    attempt = execution._load_attempt(
        results / "slots" / ledger.slots[0].slot_id / "attempt-01"
    )
    assert attempt.failure_category is expected_category


def test_explicit_allowed_retry_uses_attempt_two_and_same_slot(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *args, **kwargs: (_ for _ in ()).throw(
        AgentSetupError("safe")
    ))
    slot_id = ledger.slots[0].slot_id
    ledger = execution.retry_formal_slot(
        project_root=PROJECT_ROOT, results_root=results, slot_id=slot_id,
        remediation="authentication availability", sandbox=FakeSandbox(),
        runner=_runner(),
    )
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert ledger.slots[0].attempts == (1, 2)
    assert ledger.slots[0].canonical_attempt_index == 2
    attempt = execution._load_attempt(results / "slots" / slot_id / "attempt-02")
    assert attempt.remediation == "authentication availability"


@pytest.mark.parametrize(("slot_id", "remediation"), [
    ("wrong-slot", "authentication availability"),
    (None, "change model"),
    (None, None),
])
def test_retry_rejects_wrong_slot_or_remediation(tmp_path, slot_id, remediation):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        AgentSetupError("safe")
    ))
    with pytest.raises(execution.FormalExecutionStateError):
        execution.retry_formal_slot(
            project_root=PROJECT_ROOT, results_root=results,
            slot_id=slot_id or ledger.slots[0].slot_id,
            remediation=remediation, sandbox=FakeSandbox(), runner=_runner(),
        )


def test_attempt_two_retryable_failure_is_terminal_unresolved_then_next_advances(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        DockerSandboxError("safe")
    ))
    slot_id = ledger.slots[0].slot_id
    ledger = execution.retry_formal_slot(
        project_root=PROJECT_ROOT, results_root=results, slot_id=slot_id,
        remediation="Docker availability", sandbox=FakeSandbox(),
        runner=lambda *a, **k: (_ for _ in ()).throw(DockerSandboxError("safe")),
    )
    assert ledger.slots[0].status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
    assert ledger.slots[0].attempts == (1, 2)
    assert len(ledger.slots) == 108
    next_ledger = _run_next(results, _runner())
    assert next_ledger.slots[1].status is FormalSlotStatus.CANONICAL_OBSERVED


@pytest.mark.parametrize("error", [EvaluationError("safe"), ValueError("bug")])
def test_nonretryable_exception_blocks_study(tmp_path, error):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(error))
    assert ledger.status is FormalStudyStatus.BLOCKED
    assert ledger.slots[0].status is FormalSlotStatus.BLOCKED
    with pytest.raises(execution.FormalExecutionStateError, match="does not permit"):
        _run_next(results, _runner())


@pytest.mark.parametrize("mutation", [
    lambda e: e.model_dump(mode="json"),
    lambda e: e.model_copy(update={"task_id": "wrong"}),
    lambda e: e.model_copy(update={"run_ids": e.run_ids + ["second"]}),
    lambda e: e.model_copy(update={"run_ids": ["different"]}),
    lambda e: e.model_copy(update={
        "configuration": e.configuration.model_copy(update={"requested_model": "wrong"})
    }),
])
def test_returned_experiment_mismatch_blocks_even_with_run(tmp_path, mutation):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, _runner(experiment_mutation=mutation))
    assert ledger.status is FormalStudyStatus.BLOCKED
    assert ledger.slots[0].status is FormalSlotStatus.BLOCKED


@pytest.mark.parametrize(
    "raised_error",
    [
        ArtifactStoreError("after Run"),
        AgentProviderTransportError("after Run"),
    ],
)
def test_exception_after_complete_run_reconciles_canonical_and_forbids_retry(
    tmp_path, raised_error
):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, _runner(raise_after=raised_error))
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    with pytest.raises(execution.FormalExecutionStateError):
        execution.retry_formal_slot(
            project_root=PROJECT_ROOT, results_root=results,
            slot_id=ledger.slots[0].slot_id,
            remediation="authentication availability", sandbox=FakeSandbox(),
            runner=_runner(),
        )


def _start_interrupted_attempt(results: Path):
    prereg = verify_preregistration(PROJECT_ROOT)
    ledger = execution._load_study(results, prereg)
    return execution._create_attempt(
        results, ledger, 0, attempt_index=1, remediation=None
    )


def test_restart_reconciles_orphan_canonical_without_runner_call(tmp_path):
    results, _ = _initialize(tmp_path)
    _, _, attempt_dir = _start_interrupted_attempt(results)
    slot = verify_preregistration(PROJECT_ROOT).slots[0]
    _write_canonical_run(attempt_dir / "artifacts", slot.config_id,
                         PROJECT_ROOT / "tasks/reliability/env_config/task.yaml")
    calls = []
    ledger = _run_next(results, _runner(calls=calls))
    assert ledger.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert calls == []


def test_restart_without_run_blocks_without_runner_call(tmp_path):
    results, _ = _initialize(tmp_path)
    _start_interrupted_attempt(results)
    calls = []
    ledger = _run_next(results, _runner(calls=calls))
    assert ledger.status is FormalStudyStatus.BLOCKED
    attempt = execution._load_attempt(
        results / "slots" / ledger.slots[0].slot_id / "attempt-01"
    )
    assert attempt.failure_category is FormalFailureCategory.INTERRUPTED_ATTEMPT_UNCERTAIN
    assert calls == []


def test_restart_with_partial_run_blocks_evidence_integrity(tmp_path):
    results, _ = _initialize(tmp_path)
    _, _, attempt_dir = _start_interrupted_attempt(results)
    partial = attempt_dir / "artifacts/partial"
    partial.mkdir()
    (partial / "metadata.json").write_text("{}")
    ledger = _run_next(results, _runner())
    attempt = execution._load_attempt(
        results / "slots" / ledger.slots[0].slot_id / "attempt-01"
    )
    assert attempt.failure_category is FormalFailureCategory.EVIDENCE_INTEGRITY


@pytest.mark.parametrize("filename", ["patch.diff", "test.log", "prompt.txt"])
def test_representative_canonical_raw_evidence_drift_blocks(tmp_path, filename):
    results, _ = _initialize(tmp_path)
    def mutate(root, run_id):
        path = root / run_id / filename
        path.write_text(path.read_text() + "drift")
    ledger = _run_next(results, _runner(artifact_mutation=mutate))
    assert ledger.status is FormalStudyStatus.BLOCKED


@pytest.mark.parametrize(("section", "field", "value"), [
    ("root", "task_id", "wrong"),
    ("provenance", "base_commit_used", "0" * 40),
    ("provenance", "task_fingerprint_sha256", "0" * 64),
    ("provenance", "evaluation_command", "wrong"),
    ("provenance", "evaluation_timeout_seconds", 1),
    ("provenance", "evaluation_backend", "host"),
    ("agent", "name", "wrong"),
    ("agent", "requested_model", "wrong"),
    ("agent", "timeout_seconds", 1.0),
    ("binding", "manifest_sha256", "0" * 64),
    ("binding", "config_id", "wrong-config"),
    ("binding", "config_sha256", "0" * 64),
    ("evaluation", "passed", False),
])
def test_canonical_metadata_identity_drift_blocks(tmp_path, section, field, value):
    results, _ = _initialize(tmp_path)
    def mutate(root, run_id):
        path = root / run_id / "metadata.json"
        data = json.loads(path.read_text())
        if section == "root":
            data[field] = value
        elif section == "binding":
            data["agent"]["identity_binding"][field] = value
        elif section == "evaluation":
            data["evaluation_evidence"][field] = value
        else:
            data[section][field] = value
        path.write_text(json.dumps(data))
    ledger = _run_next(results, _runner(artifact_mutation=mutate))
    assert ledger.status is FormalStudyStatus.BLOCKED


def test_frozen_input_resolution_drift_blocks_before_runner(tmp_path):
    results, _ = _initialize(tmp_path)
    calls = []
    def bad_resolver(*args, **kwargs):
        raise execution.FrozenAgentResolutionError("drift")
    ledger = execution.run_next_formal_attempt(
        project_root=PROJECT_ROOT, results_root=results,
        sandbox=FakeSandbox(), resolver=bad_resolver,
        runner=_runner(calls=calls),
    )
    assert ledger.status is FormalStudyStatus.BLOCKED
    attempt = execution._load_attempt(
        results / "slots" / ledger.slots[0].slot_id / "attempt-01"
    )
    assert attempt.failure_category is FormalFailureCategory.FROZEN_INPUT_INTEGRITY
    assert calls == []


def test_attempt_ledger_path_identity_mismatch_rejects(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        AgentSetupError("safe")
    ))
    path = results / "slots" / ledger.slots[0].slot_id / "attempt-01/attempt.json"
    data = json.loads(path.read_text())
    data["config_id"] = "wrong-config"
    path.write_text(json.dumps(data))
    with pytest.raises(execution.FormalExecutionIntegrityError, match="identity"):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)


def test_multiple_run_candidates_block(tmp_path):
    results, _ = _initialize(tmp_path)
    def runner(task_path, **kwargs):
        first = _write_canonical_run(kwargs["results_root"], kwargs["config_id"], Path(task_path))
        _write_canonical_run(kwargs["results_root"], kwargs["config_id"], Path(task_path), suffix="two")
        return first
    ledger = _run_next(results, runner)
    assert ledger.status is FormalStudyStatus.BLOCKED


def test_status_and_check_are_read_only_and_report_next_slot(tmp_path):
    results, original = _initialize(tmp_path)
    before = (results / "study.json").read_bytes()
    assert execution.check_formal_study(
        project_root=PROJECT_ROOT, results_root=results
    ) == original
    summary = execution.formal_study_status(
        project_root=PROJECT_ROOT, results_root=results
    )
    assert summary.terminal_slots == 0 and summary.canonical_slots == 0
    assert summary.next_planned_slot == original.slots[0].slot_id
    assert (results / "study.json").read_bytes() == before


def test_exclusive_lock_prevents_second_path_from_starting_same_slot(tmp_path):
    results, _ = _initialize(tmp_path)
    runner_called = threading.Event()
    finished = threading.Event()
    def runner(task_path, **kwargs):
        runner_called.set()
        return _write_canonical_run(
            kwargs["results_root"], kwargs["config_id"], Path(task_path)
        )
    def execute():
        _run_next(results, runner)
        finished.set()
    with execution._exclusive_lock(results):
        thread = threading.Thread(target=execute)
        thread.start()
        assert runner_called.wait(0.1) is False
        assert finished.is_set() is False
    thread.join(timeout=5)
    assert runner_called.is_set() and finished.is_set()


def test_symlink_slot_and_attempt_03_are_rejected(tmp_path):
    results, ledger = _initialize(tmp_path)
    slot = results / "slots" / ledger.slots[0].slot_id
    slot.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(execution.FormalExecutionIntegrityError):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)
    slot.unlink()
    slot.mkdir()
    (slot / "attempt-03").mkdir()
    with pytest.raises(execution.FormalExecutionIntegrityError):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)


def test_study_status_cannot_hide_retry_required_slot(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        AgentSetupError("safe")
    ))
    path = results / "study.json"
    data = json.loads(path.read_text())
    data["status"] = FormalStudyStatus.RUNNING.value
    path.write_text(json.dumps(data))
    with pytest.raises(execution.FormalExecutionIntegrityError, match="study ledger"):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)


def test_missing_slot_directory_is_rejected(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, _runner())
    slot_dir = results / "slots" / ledger.slots[0].slot_id
    slot_dir.rename(tmp_path / "removed-slot")
    with pytest.raises(execution.FormalExecutionIntegrityError, match="slot directories"):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)


def test_attempt_two_remediation_drift_is_rejected(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger = _run_next(results, lambda *a, **k: (_ for _ in ()).throw(
        AgentSetupError("safe")
    ))
    ledger = execution.retry_formal_slot(
        project_root=PROJECT_ROOT, results_root=results,
        slot_id=ledger.slots[0].slot_id,
        remediation="authentication availability", sandbox=FakeSandbox(),
        runner=_runner(),
    )
    path = (results / "slots" / ledger.slots[0].slot_id
            / "attempt-02" / "attempt.json")
    data = json.loads(path.read_text())
    data["remediation"] = "semantic change"
    path.write_text(json.dumps(data))
    with pytest.raises(execution.FormalExecutionIntegrityError, match="remediation"):
        execution.check_formal_study(project_root=PROJECT_ROOT, results_root=results)


def test_raw_run_file_symlink_is_rejected(tmp_path):
    results, _ = _initialize(tmp_path)
    outside = tmp_path / "outside-prompt.txt"
    outside.write_text("outside")

    def mutate(root, run_id):
        prompt = root / run_id / "prompt.txt"
        prompt.unlink()
        prompt.symlink_to(outside)

    ledger = _run_next(results, _runner(artifact_mutation=mutate))
    assert ledger.status is FormalStudyStatus.BLOCKED
    assert ledger.slots[0].status is FormalSlotStatus.BLOCKED


def test_restart_recovers_when_attempt_terminalized_before_study_ledger(tmp_path):
    results, _ = _initialize(tmp_path)
    ledger, attempt, attempt_dir = _start_interrupted_attempt(results)
    slot = verify_preregistration(PROJECT_ROOT).slots[0]
    experiment = _write_canonical_run(
        attempt_dir / "artifacts", slot.config_id,
        PROJECT_ROOT / "tasks/reliability/env_config/task.yaml",
    )
    run = FilesystemArtifactStore(attempt_dir / "artifacts").load_run_record(
        experiment.run_ids[0]
    )
    terminal_attempt = attempt.model_copy(update={
        "status": FormalAttemptStatus.CANONICAL_OBSERVED,
        "canonical_run_id": run.run_id,
        "agent_status": run.agent.status,
        "evaluation_passed": run.evaluation_passed,
    })
    execution._atomic_write(attempt_dir / "attempt.json", terminal_attempt)
    calls = []
    recovered = _run_next(results, _runner(calls=calls))
    assert ledger.slots[0].status is FormalSlotStatus.ATTEMPT_IN_PROGRESS
    assert recovered.slots[0].status is FormalSlotStatus.CANONICAL_OBSERVED
    assert calls == []


def test_completed_study_refuses_more_execution(tmp_path, monkeypatch):
    results, initial = _initialize(tmp_path)
    data = initial.model_dump(mode="json")
    data["status"] = FormalStudyStatus.COMPLETED.value
    for index, slot in enumerate(data["slots"], start=1):
        slot.update({
            "status": FormalSlotStatus.CANONICAL_OBSERVED.value,
            "attempts": [1],
            "canonical_attempt_index": 1,
            "canonical_run_id": f"synthetic-{index:03d}",
            "canonical_agent_status": AgentRunStatus.COMPLETED.value,
            "canonical_evaluation_passed": True,
        })
    completed = execution.V13FormalStudyLedger.model_validate(data)
    preregistration = verify_preregistration(PROJECT_ROOT)
    monkeypatch.setattr(
        execution, "_prepare_mutation",
        lambda *a, **k: (preregistration, completed, False),
    )
    calls = []
    with pytest.raises(execution.FormalExecutionStateError, match="completed"):
        _run_next(results, _runner(calls=calls))
    assert calls == []
