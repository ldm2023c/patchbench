"""Canonical same-cell PASS selection from one persisted Experiment, never a scan."""

from enum import Enum
from typing import Annotated

from pydantic import ConfigDict, Field

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.diagnosis import DiagnosisRoute, route_run_diagnosis
from patchbench.domain.models import DomainModel, NonEmptyString, RunRecord, RunStatus, ExperimentRecord
from patchbench.storage.filesystem import FilesystemArtifactStore, ArtifactStoreError


class ContrastivePeerSelection(DomainModel):
    """peer_run_index is the zero-based persisted Experiment list position."""
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    subject_run_id: NonEmptyString
    peer_experiment_id: NonEmptyString
    peer_run_id: NonEmptyString
    peer_run_index: Annotated[int, Field(strict=True, ge=0)]


class DiagnosisPeerReason(str, Enum):
    SUBJECT_NOT_SEMANTIC = "subject_not_semantic"
    SUBJECT_EVIDENCE_MISSING = "subject_evidence_missing"
    SUBJECT_CELL_MISMATCH = "subject_cell_mismatch"
    PEER_EXPERIMENT_MISMATCH = "peer_experiment_mismatch"
    PEER_RUN_EVIDENCE_MISSING = "peer_run_evidence_missing"
    NO_SAME_CELL_PASS = "no_same_cell_pass"


class DiagnosisPeerError(ValueError):
    def __init__(self, reason: DiagnosisPeerReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _require_evidence(run: RunRecord, reason: DiagnosisPeerReason) -> None:
    if run.provenance is None or run.patch_summary is None or run.evaluation_evidence is None:
        raise DiagnosisPeerError(reason, "Run requires provenance and both evidence summaries")
    if (run.status is RunStatus.PASSED) != run.evaluation_passed:
        raise DiagnosisPeerError(reason, "Run status disagrees with official evaluation outcome")


def _experiment_cell(run: RunRecord, experiment: ExperimentRecord) -> bool:
    config = experiment.configuration
    return (run.task_id == experiment.task_id and run.agent.name == config.agent_name
            and run.agent.requested_model == config.requested_model
            and run.agent.timeout_seconds == config.agent_timeout_seconds
            and run.provenance is not None
            and run.provenance.evaluation_backend == config.evaluation_backend)


def _same_cell(subject: RunRecord, peer: RunRecord) -> bool:
    return (subject.task_id == peer.task_id
            and all(getattr(subject.agent, name) == getattr(peer.agent, name)
                    for name in ("name", "backend", "requested_model", "timeout_seconds"))
            and subject.provenance == peer.provenance)


def _load_context(subject_run_id: str, experiment_id: str, store: FilesystemArtifactStore):
    try:
        subject = store.load_run_record(subject_run_id)
    except ArtifactStoreError as error:
        raise DiagnosisPeerError(DiagnosisPeerReason.SUBJECT_EVIDENCE_MISSING, "Unable to load subject") from error
    if route_run_diagnosis(subject).route is not DiagnosisRoute.SEMANTIC_DIAGNOSIS:
        raise DiagnosisPeerError(DiagnosisPeerReason.SUBJECT_NOT_SEMANTIC, "Subject must be FAIL and COMPLETED")
    _require_evidence(subject, DiagnosisPeerReason.SUBJECT_EVIDENCE_MISSING)
    try:
        experiment = store.load_experiment_record(experiment_id)
    except ArtifactStoreError as error:
        raise DiagnosisPeerError(DiagnosisPeerReason.PEER_EXPERIMENT_MISMATCH, "Unable to load peer Experiment") from error
    if not _experiment_cell(subject, experiment):
        raise DiagnosisPeerError(DiagnosisPeerReason.SUBJECT_CELL_MISMATCH, "Subject differs from Experiment configuration")
    return subject, experiment


def _load_cell_run(run_id, subject, experiment, store):
    try:
        run = store.load_run_record(run_id)
    except ArtifactStoreError as error:
        raise DiagnosisPeerError(DiagnosisPeerReason.PEER_RUN_EVIDENCE_MISSING, "Unable to load Experiment Run") from error
    _require_evidence(run, DiagnosisPeerReason.PEER_RUN_EVIDENCE_MISSING)
    if not _experiment_cell(run, experiment) or not _same_cell(subject, run):
        raise DiagnosisPeerError(DiagnosisPeerReason.PEER_EXPERIMENT_MISMATCH, "Experiment Run differs from frozen cell")
    return run


def _eligible(run, subject_run_id):
    return (run.run_id != subject_run_id and run.status is RunStatus.PASSED
            and run.evaluation_passed and run.agent.status is AgentRunStatus.COMPLETED)


def select_contrastive_peer(subject_run_id: str, peer_experiment_id: str, *,
                            artifact_store: FilesystemArtifactStore) -> ContrastivePeerSelection:
    subject, experiment = _load_context(subject_run_id, peer_experiment_id, artifact_store)
    for index, run_id in enumerate(experiment.run_ids):
        run = _load_cell_run(run_id, subject, experiment, artifact_store)
        if _eligible(run, subject_run_id):
            return ContrastivePeerSelection(subject_run_id=subject_run_id, peer_experiment_id=peer_experiment_id,
                                            peer_run_id=run_id, peer_run_index=index)
    raise DiagnosisPeerError(DiagnosisPeerReason.NO_SAME_CELL_PASS, "Experiment has no eligible PASS peer")


def verify_contrastive_peer_selection(selection: ContrastivePeerSelection, *,
                                     artifact_store: FilesystemArtifactStore) -> tuple[RunRecord, RunRecord]:
    """Recheck the frozen selection, failing on drift rather than choosing a replacement."""
    subject, experiment = _load_context(selection.subject_run_id, selection.peer_experiment_id, artifact_store)
    index = selection.peer_run_index
    if index >= len(experiment.run_ids) or experiment.run_ids[index] != selection.peer_run_id:
        raise DiagnosisPeerError(DiagnosisPeerReason.PEER_EXPERIMENT_MISMATCH, "Selected position/identity changed")
    for position, run_id in enumerate(experiment.run_ids[:index + 1]):
        run = _load_cell_run(run_id, subject, experiment, artifact_store)
        if _eligible(run, subject.run_id):
            if position == index:
                return subject, run
            raise DiagnosisPeerError(DiagnosisPeerReason.PEER_EXPERIMENT_MISMATCH, "Selection is not the first eligible PASS")
    raise DiagnosisPeerError(DiagnosisPeerReason.PEER_EXPERIMENT_MISMATCH, "Selected peer is no longer eligible")
