"""Safe execution harness for the frozen PatchBench V1.3 formal study."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path

from pydantic import ValidationError

from patchbench.agents.base import (
    AgentInfrastructureError, AgentRunStatus, AgentSetupError,
)
from patchbench.application.v13_agent_execution import (
    FrozenAgentExecutionPlan, FrozenAgentResolutionError,
    resolve_v13_agent_config, run_v13_agent_experiment,
)
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain import (
    FormalAttemptStatus, FormalFailureCategory, FormalSlotStatus,
    FormalStudyStatus, V13FormalAttemptRecord,
    V13FormalSlot, V13FormalSlotExecution, V13FormalStudyLedger,
    compute_benchmark_candidate_sha256, compute_task_fingerprint,
    summarize_evaluation_log, summarize_patch,
)
from patchbench.domain.benchmark import BenchmarkCandidateManifest
from patchbench.domain.models import ExperimentRecord, RunRecord, TaskSpec
from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.sandbox.base import Sandbox
from patchbench.sandbox.docker import DockerSandboxError
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore
from scripts.v13_formal_preregistration import (
    ACCEPTED_AGENT_MANIFEST_SHA256, ACCEPTED_CANDIDATE_SHA256,
    ACCEPTED_PREREGISTRATION_SHA256, CANDIDATE_PATH,
    verify_preregistration,
)


DEFAULT_FORMAL_RESULTS_PATH = Path("results/v1.3-formal")
STUDY_LEDGER_NAME = "study.json"


class FormalExecutionIntegrityError(RuntimeError):
    """Frozen input, ledger, or canonical evidence failed verification."""


class FormalExecutionStateError(RuntimeError):
    """Requested operator transition is not allowed in the current state."""


@dataclass(frozen=True)
class FormalSlotInputs:
    slot: V13FormalSlot
    task_path: Path
    task: TaskSpec
    plan: FrozenAgentExecutionPlan


@dataclass(frozen=True)
class FormalStudyStatusSummary:
    status: FormalStudyStatus
    terminal_slots: int
    canonical_slots: int
    unresolved_infrastructure_slots: int
    retry_required_slot: str | None
    blocked_slot: str | None
    next_planned_slot: str | None


Runner = Callable[..., ExperimentRecord]
Resolver = Callable[..., FrozenAgentExecutionPlan]


def _deterministic_json(model) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2) + "\n"


def _atomic_write(path: Path, model) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(_deterministic_json(model), encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as error:
        raise ArtifactStoreError("unable to persist formal execution ledger") from error


@contextmanager
def _exclusive_lock(namespace: Path):
    lock_path = namespace.parent / f".{namespace.name}.lock"
    try:
        namespace.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError as error:
        raise ArtifactStoreError("unable to lock formal study namespace") from error
    try:
        yield
    finally:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def _namespace(project_root: Path, results_root: Path | None) -> Path:
    return (project_root / DEFAULT_FORMAL_RESULTS_PATH if results_root is None
            else Path(results_root)).resolve()


def _load_model(path: Path, model_type, label: str):
    try:
        return model_type.model_validate_json(path.read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise FormalExecutionIntegrityError(f"invalid {label}") from error


def _initial_ledger(preregistration) -> V13FormalStudyLedger:
    return V13FormalStudyLedger(
        study_id=preregistration.study_id,
        formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        status=FormalStudyStatus.READY,
        slots=tuple(V13FormalSlotExecution(
            ordinal=slot.ordinal, slot_id=slot.slot_id,
            repetition_index=slot.repetition_index, task_id=slot.task_id,
            config_id=slot.config_id, status=FormalSlotStatus.PENDING,
        ) for slot in preregistration.slots),
    )


def initialize_formal_study(
    *, project_root: Path, results_root: Path | None = None,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    namespace = _namespace(root, results_root)
    with _exclusive_lock(namespace):
        preregistration = verify_preregistration(root)
        if namespace.exists():
            raise FormalExecutionStateError("formal study namespace already exists")
        ledger = _initial_ledger(preregistration)
        try:
            namespace.mkdir(parents=True, exist_ok=False)
            (namespace / "slots").mkdir()
            (namespace / STUDY_LEDGER_NAME).write_text(
                _deterministic_json(ledger), encoding="utf-8", newline="\n"
            )
        except OSError as error:
            raise ArtifactStoreError("unable to initialize formal study") from error
        return ledger


def _load_study(namespace: Path, preregistration) -> V13FormalStudyLedger:
    if not namespace.is_dir() or namespace.is_symlink():
        raise FormalExecutionIntegrityError("formal namespace is missing or unsafe")
    try:
        names = {path.name for path in namespace.iterdir()}
    except OSError as error:
        raise FormalExecutionIntegrityError("unable to inspect formal namespace") from error
    if names != {STUDY_LEDGER_NAME, "slots"}:
        raise FormalExecutionIntegrityError("formal namespace contains unexpected evidence")
    ledger = _load_model(
        namespace / STUDY_LEDGER_NAME, V13FormalStudyLedger, "formal study ledger"
    )
    expected = _initial_ledger(preregistration)
    if (ledger.study_id != expected.study_id
            or ledger.formal_preregistration_sha256 != ACCEPTED_PREREGISTRATION_SHA256
            or ledger.planned_slot_count != 108
            or tuple((s.ordinal, s.slot_id, s.repetition_index, s.task_id, s.config_id)
                     for s in ledger.slots)
            != tuple((s.ordinal, s.slot_id, s.repetition_index, s.task_id, s.config_id)
                     for s in expected.slots)):
        raise FormalExecutionIntegrityError("study ledger differs from preregistration")
    return ledger


def _slot_directory(namespace: Path, slot_id: str) -> Path:
    slots_root = (namespace / "slots").resolve()
    candidate = (slots_root / slot_id).resolve()
    if candidate.parent != slots_root or candidate.name != slot_id:
        raise FormalExecutionIntegrityError("unsafe formal slot path")
    return candidate


def _attempt_directory(namespace: Path, slot_id: str, attempt_index: int) -> Path:
    return _slot_directory(namespace, slot_id) / f"attempt-{attempt_index:02d}"


def _load_attempt(path: Path) -> V13FormalAttemptRecord:
    record = _load_model(path / "attempt.json", V13FormalAttemptRecord,
                         "formal attempt ledger")
    expected_name = f"attempt-{record.attempt_index:02d}"
    if path.name != expected_name or path.parent.name != record.slot_id:
        raise FormalExecutionIntegrityError("attempt ledger identity differs from path")
    return record


def _load_candidate(project_root: Path) -> BenchmarkCandidateManifest:
    candidate = _load_model(
        project_root / CANDIDATE_PATH, BenchmarkCandidateManifest, "M3 candidate"
    )
    if compute_benchmark_candidate_sha256(candidate) != ACCEPTED_CANDIDATE_SHA256:
        raise FormalExecutionIntegrityError("M3 candidate SHA mismatch")
    return candidate


def _verify_slot_inputs(
    project_root: Path,
    preregistration,
    slot: V13FormalSlot,
    *, resolver: Resolver,
) -> FormalSlotInputs:
    candidate = _load_candidate(project_root)
    matches = [item for item in candidate.tasks if item.task_id == slot.task_id]
    if len(matches) != 1:
        raise FormalExecutionIntegrityError("formal task is absent or duplicated in M3")
    frozen_task = matches[0]
    if (slot.task_spec_sha256 != frozen_task.task_spec_sha256
            or slot.task_fingerprint_sha256 != frozen_task.task_fingerprint_sha256
            or slot.resolved_base_commit != frozen_task.resolved_base_commit):
        raise FormalExecutionIntegrityError("formal slot task identity differs from M3")
    task_path = project_root / frozen_task.task_spec_path
    try:
        task_bytes = task_path.read_bytes()
    except OSError as error:
        raise FormalExecutionIntegrityError("unable to read formal TaskSpec") from error
    if hashlib.sha256(task_bytes).hexdigest() != frozen_task.task_spec_sha256:
        raise FormalExecutionIntegrityError("formal TaskSpec byte SHA mismatch")
    try:
        task = load_task(task_path)
    except TaskLoadError as error:
        raise FormalExecutionIntegrityError("invalid formal TaskSpec") from error
    if (task.id != slot.task_id
            or task.repository.base_commit != slot.resolved_base_commit
            or compute_task_fingerprint(task, base_commit_used=slot.resolved_base_commit)
            != slot.task_fingerprint_sha256):
        raise FormalExecutionIntegrityError("formal TaskSpec identity mismatch")
    try:
        plan = resolver(
            slot.config_id, evaluation_backend="docker", project_root=project_root
        )
    except FrozenAgentResolutionError as error:
        raise FormalExecutionIntegrityError("M9 formal Agent resolution failed") from error
    if (plan.configuration.config_id != slot.config_id
            or plan.identity_binding.manifest_sha256 != ACCEPTED_AGENT_MANIFEST_SHA256
            or plan.identity_binding.config_id != slot.config_id
            or plan.identity_binding.config_sha256 != slot.config_sha256
            or plan.experiment_configuration.identity_binding != plan.identity_binding
            or plan.experiment_configuration.evaluation_backend != "docker"):
        raise FormalExecutionIntegrityError("formal M8/M9 Agent identity mismatch")
    return FormalSlotInputs(slot=slot, task_path=task_path, task=task, plan=plan)


def _candidate_run_ids(artifacts_root: Path) -> tuple[str, ...]:
    if not artifacts_root.is_dir() or artifacts_root.is_symlink():
        raise FormalExecutionIntegrityError("attempt artifacts namespace is missing or unsafe")
    ids = []
    for entry in artifacts_root.iterdir():
        if entry.name == "experiments" and entry.is_dir() and not entry.is_symlink():
            continue
        if (not entry.is_dir() or entry.is_symlink()
                or not (entry / "metadata.json").is_file()):
            raise FormalExecutionIntegrityError("partial or unexpected Run evidence")
        ids.append(entry.name)
    if len(ids) > 1:
        raise FormalExecutionIntegrityError("multiple candidate Runs in one attempt")
    return tuple(ids)


def _validate_canonical_run(
    artifacts_root: Path, inputs: FormalSlotInputs,
) -> RunRecord | None:
    run_ids = _candidate_run_ids(artifacts_root)
    if not run_ids:
        return None
    run_id = run_ids[0]
    store = FilesystemArtifactStore(artifacts_root)
    try:
        run = store.load_run_record(run_id)
    except ArtifactStoreError as error:
        raise FormalExecutionIntegrityError("invalid canonical Run metadata") from error
    run_root = artifacts_root / run_id
    expected_files = {
        "metadata.json", "prompt.txt", "agent.log", "agent.stderr.log",
        "test.log", "patch.diff",
    }
    try:
        if ({path.name for path in run_root.iterdir()} != expected_files
                or any(not (run_root / name).is_file()
                       or (run_root / name).is_symlink()
                       for name in expected_files)):
            raise FormalExecutionIntegrityError("canonical Run files are incomplete")
        prompt = (run_root / "prompt.txt").read_text(encoding="utf-8")
        patch = (run_root / "patch.diff").read_text(encoding="utf-8")
        test_log = (run_root / "test.log").read_text(encoding="utf-8")
        (run_root / "agent.log").read_bytes()
        (run_root / "agent.stderr.log").read_bytes()
    except (OSError, UnicodeError) as error:
        raise FormalExecutionIntegrityError("unable to read canonical Run files") from error
    expected_paths = {
        "directory": run_root.resolve(),
        "metadata": (run_root / "metadata.json").resolve(),
        "prompt": (run_root / "prompt.txt").resolve(),
        "agent_log": (run_root / "agent.log").resolve(),
        "agent_stderr_log": (run_root / "agent.stderr.log").resolve(),
        "test_log": (run_root / "test.log").resolve(),
        "patch": (run_root / "patch.diff").resolve(),
    }
    if any(Path(getattr(run.artifacts, name)).resolve() != value
           for name, value in expected_paths.items()):
        raise FormalExecutionIntegrityError("Run artifact locators escape attempt namespace")
    task = inputs.task
    plan = inputs.plan
    try:
        recomputed_patch = summarize_patch(patch)
        recomputed_evaluation = summarize_evaluation_log(test_log)
    except EvidenceParsingError as error:
        raise FormalExecutionIntegrityError("canonical raw evidence is malformed") from error
    if (run.task_id != inputs.slot.task_id
            or run.provenance is None
            or run.provenance.base_commit_used != inputs.slot.resolved_base_commit
            or run.provenance.task_fingerprint_sha256
            != inputs.slot.task_fingerprint_sha256
            or run.provenance.evaluation_backend != "docker"
            or run.provenance.evaluation_command != task.evaluation.command
            or run.provenance.evaluation_timeout_seconds != task.evaluation.timeout_seconds
            or run.agent.identity_binding != plan.identity_binding
            or run.agent.name != plan.experiment_configuration.agent_name
            or run.agent.requested_model != plan.experiment_configuration.requested_model
            or run.agent.timeout_seconds
            != plan.experiment_configuration.agent_timeout_seconds
            or run.agent.status not in set(AgentRunStatus)
            or run.patch_summary is None
            or run.evaluation_evidence is None
            or run.evaluation_evidence.passed != run.evaluation_passed
            or recomputed_patch != run.patch_summary
            or recomputed_evaluation != run.evaluation_evidence
            or prompt != task.task.prompt):
        raise FormalExecutionIntegrityError("canonical Run evidence/linkage mismatch")
    return run


def _validate_returned_experiment(
    experiment: ExperimentRecord, run: RunRecord, inputs: FormalSlotInputs,
) -> None:
    if (not isinstance(experiment, ExperimentRecord)
            or experiment.requested_runs != 1
            or experiment.task_id != inputs.slot.task_id
            or experiment.run_ids != [run.run_id]
            or experiment.configuration != inputs.plan.experiment_configuration):
        raise FormalExecutionIntegrityError("returned Experiment linkage mismatch")


def _replace_slot(
    ledger: V13FormalStudyLedger, index: int, slot: V13FormalSlotExecution,
    *, status: FormalStudyStatus,
) -> V13FormalStudyLedger:
    slots = list(ledger.slots)
    slots[index] = slot
    return ledger.model_copy(update={"status": status, "slots": tuple(slots)})


def _study_status_after_terminal(slots, index: int) -> FormalStudyStatus:
    terminal = {FormalSlotStatus.CANONICAL_OBSERVED,
                FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE}
    return (FormalStudyStatus.COMPLETED if all(s.status in terminal for s in slots)
            else FormalStudyStatus.RUNNING)


def _terminalize_canonical(
    namespace: Path, ledger: V13FormalStudyLedger, index: int,
    attempt: V13FormalAttemptRecord, run: RunRecord,
) -> V13FormalStudyLedger:
    attempt = attempt.model_copy(update={
        "status": FormalAttemptStatus.CANONICAL_OBSERVED,
        "canonical_run_id": run.run_id, "agent_status": run.agent.status,
        "evaluation_passed": run.evaluation_passed,
    })
    attempt_path = _attempt_directory(
        namespace, attempt.slot_id, attempt.attempt_index
    ) / "attempt.json"
    _atomic_write(attempt_path, attempt)
    old = ledger.slots[index]
    slot = old.model_copy(update={
        "status": FormalSlotStatus.CANONICAL_OBSERVED,
        "canonical_attempt_index": attempt.attempt_index,
        "canonical_run_id": run.run_id,
        "canonical_agent_status": run.agent.status,
        "canonical_evaluation_passed": run.evaluation_passed,
    })
    slots = list(ledger.slots)
    slots[index] = slot
    status = _study_status_after_terminal(slots, index)
    ledger = ledger.model_copy(update={"status": status, "slots": tuple(slots)})
    _atomic_write(namespace / STUDY_LEDGER_NAME, ledger)
    return ledger


_RETRYABLE = (
    (AgentSetupError, FormalFailureCategory.AGENT_SETUP),
    (AgentInfrastructureError, FormalFailureCategory.AGENT_INFRASTRUCTURE),
    (RepositoryError, FormalFailureCategory.REPOSITORY_INFRASTRUCTURE),
    (DockerSandboxError, FormalFailureCategory.DOCKER_INFRASTRUCTURE),
    (ArtifactStoreError,
     FormalFailureCategory.ARTIFACT_INFRASTRUCTURE_BEFORE_CANONICAL_RUN),
)
_RETRYABLE_CATEGORIES = frozenset(category for _, category in _RETRYABLE) | {
    FormalFailureCategory.NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE,
}


def _retryable_category(error: BaseException) -> FormalFailureCategory | None:
    for error_type, category in _RETRYABLE:
        if isinstance(error, error_type):
            return category
    return None


def _block(
    namespace: Path, ledger: V13FormalStudyLedger, index: int,
    attempt: V13FormalAttemptRecord, category: FormalFailureCategory,
) -> V13FormalStudyLedger:
    attempt = attempt.model_copy(update={
        "status": FormalAttemptStatus.BLOCKED, "failure_category": category,
    })
    _atomic_write(_attempt_directory(namespace, attempt.slot_id,
                                     attempt.attempt_index) / "attempt.json", attempt)
    slot = ledger.slots[index].model_copy(update={"status": FormalSlotStatus.BLOCKED})
    ledger = _replace_slot(ledger, index, slot, status=FormalStudyStatus.BLOCKED)
    _atomic_write(namespace / STUDY_LEDGER_NAME, ledger)
    return ledger


def _record_retryable(
    namespace: Path, ledger: V13FormalStudyLedger, index: int,
    attempt: V13FormalAttemptRecord, category: FormalFailureCategory,
) -> V13FormalStudyLedger:
    second = attempt.attempt_index == 2
    attempt = attempt.model_copy(update={
        "status": (FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE if second
                   else FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE),
        "failure_category": category,
    })
    _atomic_write(_attempt_directory(namespace, attempt.slot_id,
                                     attempt.attempt_index) / "attempt.json", attempt)
    slot = ledger.slots[index].model_copy(update={
        "status": (FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE if second
                   else FormalSlotStatus.RETRY_REQUIRED),
    })
    slots = list(ledger.slots)
    slots[index] = slot
    status = (_study_status_after_terminal(slots, index) if second
              else FormalStudyStatus.RETRY_REQUIRED)
    ledger = ledger.model_copy(update={"status": status, "slots": tuple(slots)})
    _atomic_write(namespace / STUDY_LEDGER_NAME, ledger)
    return ledger


def _audit_filesystem(
    project_root: Path, namespace: Path, preregistration,
    ledger: V13FormalStudyLedger, *, resolver: Resolver,
    allow_reconcilable_in_progress: bool = False,
) -> None:
    slots_root = namespace / "slots"
    if not slots_root.is_dir() or slots_root.is_symlink():
        raise FormalExecutionIntegrityError("formal slots namespace is unsafe")
    by_id = {slot.slot_id: slot for slot in ledger.slots}
    entries = tuple(slots_root.iterdir())
    expected_slot_directories = {slot.slot_id for slot in ledger.slots if slot.attempts}
    if {entry.name for entry in entries} != expected_slot_directories:
        raise FormalExecutionIntegrityError("slot directories differ from ledger")
    for entry in entries:
        if entry.name not in by_id or not entry.is_dir() or entry.is_symlink():
            raise FormalExecutionIntegrityError("unexpected or symlinked slot directory")
        slot = by_id[entry.name]
        names = {path.name for path in entry.iterdir()}
        expected = {f"attempt-{index:02d}" for index in slot.attempts}
        if names != expected:
            raise FormalExecutionIntegrityError("attempt directories differ from ledger")
        attempt_records = {}
        for name in names:
            path = entry / name
            if not path.is_dir() or path.is_symlink() or name not in {"attempt-01", "attempt-02"}:
                raise FormalExecutionIntegrityError("unsafe or unexpected attempt directory")
            attempt = _load_attempt(path)
            attempt_records[attempt.attempt_index] = attempt
            if (attempt.slot_id != slot.slot_id
                    or attempt.attempt_index not in slot.attempts
                    or attempt.formal_preregistration_sha256
                    != ACCEPTED_PREREGISTRATION_SHA256
                    or attempt.config_id != slot.config_id
                    or attempt.task_id != slot.task_id):
                raise FormalExecutionIntegrityError("attempt identity differs from study ledger")
            if (attempt.attempt_index == 2
                    and attempt.remediation not in
                    preregistration.retry_policy.allowed_environment_remediation):
                raise FormalExecutionIntegrityError("attempt remediation is not frozen")
            try:
                child_names = {child.name for child in path.iterdir()}
            except OSError as error:
                raise FormalExecutionIntegrityError("unable to inspect attempt") from error
            if child_names != {"attempt.json", "artifacts"}:
                raise FormalExecutionIntegrityError("attempt namespace contains unexpected evidence")
            artifacts = path / "artifacts"
            if not artifacts.is_dir() or artifacts.is_symlink():
                raise FormalExecutionIntegrityError("attempt artifacts namespace is unsafe")
            if attempt.status is FormalAttemptStatus.CANONICAL_OBSERVED:
                inputs = _verify_slot_inputs(
                    project_root, preregistration,
                    preregistration.slots[slot.ordinal - 1], resolver=resolver,
                )
                run = _validate_canonical_run(artifacts, inputs)
                reconcilable = (
                    allow_reconcilable_in_progress
                    and slot.status is FormalSlotStatus.ATTEMPT_IN_PROGRESS
                    and attempt.attempt_index == slot.attempts[-1]
                )
                if (run is None or (not reconcilable and (
                        slot.status is not FormalSlotStatus.CANONICAL_OBSERVED
                        or slot.canonical_attempt_index != attempt.attempt_index
                        or slot.canonical_run_id != run.run_id
                        or slot.canonical_agent_status is not run.agent.status
                        or slot.canonical_evaluation_passed != run.evaluation_passed))):
                    raise FormalExecutionIntegrityError(
                        "canonical attempt and study ledger differ"
                    )
            elif attempt.status in {
                    FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE,
                    FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE,
            }:
                if attempt.failure_category not in _RETRYABLE_CATEGORIES:
                    raise FormalExecutionIntegrityError(
                        "infrastructure attempt has a nonretryable category"
                    )
                if tuple(artifacts.iterdir()):
                    raise FormalExecutionIntegrityError(
                        "infrastructure failure contains unexpected Run evidence"
                    )
        if slot.status is FormalSlotStatus.ATTEMPT_IN_PROGRESS:
            latest_status = attempt_records[slot.attempts[-1]].status
            if (latest_status is not FormalAttemptStatus.IN_PROGRESS
                    and not (allow_reconcilable_in_progress
                             and latest_status is FormalAttemptStatus.CANONICAL_OBSERVED)):
                raise FormalExecutionIntegrityError("in-progress slot/attempt mismatch")
        elif slot.status is FormalSlotStatus.RETRY_REQUIRED:
            if attempt_records[1].status is not FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE:
                raise FormalExecutionIntegrityError("retry-required slot/attempt mismatch")
        elif slot.status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE:
            if attempt_records[2].status is not FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE:
                raise FormalExecutionIntegrityError("unresolved slot/attempt mismatch")
        elif slot.status is FormalSlotStatus.BLOCKED:
            if attempt_records[slot.attempts[-1]].status is not FormalAttemptStatus.BLOCKED:
                raise FormalExecutionIntegrityError("blocked slot/attempt mismatch")
        if (slot.attempts == (1, 2)
                and attempt_records[1].status
                is not FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE):
            raise FormalExecutionIntegrityError("attempt 2 lacks a retry-eligible attempt 1")


def _reconcile_in_progress(
    project_root: Path, namespace: Path, preregistration,
    ledger: V13FormalStudyLedger, *, resolver: Resolver,
) -> tuple[V13FormalStudyLedger, bool]:
    active = [i for i, slot in enumerate(ledger.slots)
              if slot.status is FormalSlotStatus.ATTEMPT_IN_PROGRESS]
    if not active:
        return ledger, False
    if len(active) != 1:
        raise FormalExecutionIntegrityError("multiple in-progress formal slots")
    index = active[0]
    slot_record = ledger.slots[index]
    attempt_index = slot_record.attempts[-1]
    attempt_path = _attempt_directory(namespace, slot_record.slot_id, attempt_index)
    attempt = _load_attempt(attempt_path)
    if attempt.status not in {
            FormalAttemptStatus.IN_PROGRESS,
            FormalAttemptStatus.CANONICAL_OBSERVED,
    }:
        raise FormalExecutionIntegrityError("in-progress slot/attempt state mismatch")
    try:
        inputs = _verify_slot_inputs(
            project_root, preregistration, preregistration.slots[index], resolver=resolver
        )
    except FormalExecutionIntegrityError:
        return _block(namespace, ledger, index, attempt,
                      FormalFailureCategory.FROZEN_INPUT_INTEGRITY), True
    try:
        run = _validate_canonical_run(attempt_path / "artifacts", inputs)
    except FormalExecutionIntegrityError:
        return _block(namespace, ledger, index, attempt,
                      FormalFailureCategory.EVIDENCE_INTEGRITY), True
    if run is not None:
        return _terminalize_canonical(namespace, ledger, index, attempt, run), True
    return _block(namespace, ledger, index, attempt,
                  FormalFailureCategory.INTERRUPTED_ATTEMPT_UNCERTAIN), True


def _create_attempt(
    namespace: Path, ledger: V13FormalStudyLedger, index: int,
    *, attempt_index: int, remediation: str | None,
) -> tuple[V13FormalStudyLedger, V13FormalAttemptRecord, Path]:
    slot = ledger.slots[index]
    slot_dir = _slot_directory(namespace, slot.slot_id)
    attempt_dir = _attempt_directory(namespace, slot.slot_id, attempt_index)
    try:
        slot_dir.mkdir(exist_ok=attempt_index == 2)
        attempt_dir.mkdir(exist_ok=False)
        (attempt_dir / "artifacts").mkdir()
    except OSError as error:
        raise ArtifactStoreError("unable to create formal attempt namespace") from error
    attempt = V13FormalAttemptRecord(
        slot_id=slot.slot_id, attempt_index=attempt_index,
        status=FormalAttemptStatus.IN_PROGRESS,
        formal_preregistration_sha256=ACCEPTED_PREREGISTRATION_SHA256,
        config_id=slot.config_id, task_id=slot.task_id, remediation=remediation,
    )
    (attempt_dir / "attempt.json").write_text(
        _deterministic_json(attempt), encoding="utf-8", newline="\n"
    )
    slot = slot.model_copy(update={
        "status": FormalSlotStatus.ATTEMPT_IN_PROGRESS,
        "attempts": slot.attempts + (attempt_index,),
    })
    ledger = _replace_slot(ledger, index, slot, status=FormalStudyStatus.RUNNING)
    _atomic_write(namespace / STUDY_LEDGER_NAME, ledger)
    return ledger, attempt, attempt_dir


def _execute_attempt(
    project_root: Path, namespace: Path, preregistration,
    ledger: V13FormalStudyLedger, index: int,
    *, attempt_index: int, remediation: str | None, sandbox: Sandbox,
    resolver: Resolver, runner: Runner, workspace_root: Path | None,
) -> V13FormalStudyLedger:
    ledger, attempt, attempt_dir = _create_attempt(
        namespace, ledger, index, attempt_index=attempt_index,
        remediation=remediation,
    )
    artifacts_root = attempt_dir / "artifacts"
    try:
        inputs = _verify_slot_inputs(
            project_root, preregistration, preregistration.slots[index], resolver=resolver
        )
    except FormalExecutionIntegrityError:
        return _block(namespace, ledger, index, attempt,
                      FormalFailureCategory.FROZEN_INPUT_INTEGRITY)
    try:
        experiment = runner(
            inputs.task_path, config_id=inputs.slot.config_id, requested_runs=1,
            evaluation_backend="docker", project_root=project_root,
            workspace_root=workspace_root, results_root=artifacts_root,
            sandbox=sandbox,
        )
    except Exception as error:
        try:
            run = _validate_canonical_run(artifacts_root, inputs)
        except FormalExecutionIntegrityError:
            return _block(namespace, ledger, index, attempt,
                          FormalFailureCategory.EVIDENCE_INTEGRITY)
        if run is not None:
            return _terminalize_canonical(namespace, ledger, index, attempt, run)
        category = _retryable_category(error)
        if category is not None:
            return _record_retryable(namespace, ledger, index, attempt, category)
        if isinstance(error, EvaluationError):
            category = FormalFailureCategory.EVALUATION_INFRASTRUCTURE
        elif isinstance(error, FormalExecutionIntegrityError):
            category = FormalFailureCategory.EVIDENCE_INTEGRITY
        else:
            category = FormalFailureCategory.UNEXPECTED
        return _block(namespace, ledger, index, attempt, category)
    try:
        run = _validate_canonical_run(artifacts_root, inputs)
        if run is None:
            raise FormalExecutionIntegrityError("runner returned without canonical Run")
        _validate_returned_experiment(experiment, run, inputs)
    except FormalExecutionIntegrityError:
        return _block(namespace, ledger, index, attempt,
                      FormalFailureCategory.EVIDENCE_INTEGRITY)
    return _terminalize_canonical(namespace, ledger, index, attempt, run)


def _prepare_mutation(
    project_root: Path, namespace: Path, *, resolver: Resolver,
) -> tuple[object, V13FormalStudyLedger, bool]:
    preregistration = verify_preregistration(project_root)
    ledger = _load_study(namespace, preregistration)
    _audit_filesystem(
        project_root, namespace, preregistration, ledger, resolver=resolver,
        allow_reconcilable_in_progress=True,
    )
    ledger, reconciled = _reconcile_in_progress(
        project_root, namespace, preregistration, ledger, resolver=resolver
    )
    return preregistration, ledger, reconciled


def run_next_formal_attempt(
    *, project_root: Path, sandbox: Sandbox,
    results_root: Path | None = None, workspace_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
    runner: Runner = run_v13_agent_experiment,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    namespace = _namespace(root, results_root)
    with _exclusive_lock(namespace):
        preregistration, ledger, reconciled = _prepare_mutation(
            root, namespace, resolver=resolver
        )
        if reconciled:
            return ledger
        if ledger.status in {FormalStudyStatus.COMPLETED, FormalStudyStatus.BLOCKED,
                           FormalStudyStatus.RETRY_REQUIRED}:
            raise FormalExecutionStateError(
                f"study status {ledger.status.value} does not permit run-next"
            )
        index = next((i for i, slot in enumerate(ledger.slots)
                      if slot.status is FormalSlotStatus.PENDING), None)
        if index is None:
            raise FormalExecutionStateError("no pending formal slot")
        return _execute_attempt(
            root, namespace, preregistration, ledger, index,
            attempt_index=1, remediation=None, sandbox=sandbox,
            resolver=resolver, runner=runner, workspace_root=workspace_root,
        )


def retry_formal_slot(
    *, project_root: Path, slot_id: str, remediation: str, sandbox: Sandbox,
    results_root: Path | None = None, workspace_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
    runner: Runner = run_v13_agent_experiment,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    namespace = _namespace(root, results_root)
    with _exclusive_lock(namespace):
        preregistration, ledger, reconciled = _prepare_mutation(
            root, namespace, resolver=resolver
        )
        if reconciled:
            return ledger
        if ledger.status is not FormalStudyStatus.RETRY_REQUIRED:
            raise FormalExecutionStateError("study does not require a retry")
        index = next(i for i, slot in enumerate(ledger.slots)
                     if slot.status is FormalSlotStatus.RETRY_REQUIRED)
        slot = ledger.slots[index]
        if slot.slot_id != slot_id:
            raise FormalExecutionStateError("retry must target the exact earliest slot")
        if remediation not in preregistration.retry_policy.allowed_environment_remediation:
            raise FormalExecutionStateError("remediation is not allow-listed")
        if slot.attempts != (1,) or _attempt_directory(
                namespace, slot.slot_id, 2).exists():
            raise FormalExecutionStateError("attempt 2 already exists or history is invalid")
        first = _load_attempt(_attempt_directory(namespace, slot.slot_id, 1))
        if (first.status is not FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
                or first.failure_category not in _RETRYABLE_CATEGORIES):
            raise FormalExecutionStateError("attempt 1 is not retry-eligible")
        return _execute_attempt(
            root, namespace, preregistration, ledger, index,
            attempt_index=2, remediation=remediation, sandbox=sandbox,
            resolver=resolver, runner=runner, workspace_root=workspace_root,
        )


def check_formal_study(
    *, project_root: Path, results_root: Path | None = None,
    resolver: Resolver = resolve_v13_agent_config,
) -> V13FormalStudyLedger:
    root = Path(project_root).resolve()
    preregistration = verify_preregistration(root)
    namespace = _namespace(root, results_root)
    ledger = _load_study(namespace, preregistration)
    _audit_filesystem(root, namespace, preregistration, ledger, resolver=resolver)
    return ledger


def formal_study_status(
    *, project_root: Path, results_root: Path | None = None,
) -> FormalStudyStatusSummary:
    ledger = check_formal_study(project_root=project_root, results_root=results_root)
    terminal = {FormalSlotStatus.CANONICAL_OBSERVED,
                FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE}
    retry = next((s.slot_id for s in ledger.slots
                  if s.status is FormalSlotStatus.RETRY_REQUIRED), None)
    blocked = next((s.slot_id for s in ledger.slots
                    if s.status is FormalSlotStatus.BLOCKED), None)
    next_slot = next((s.slot_id for s in ledger.slots
                      if s.status is FormalSlotStatus.PENDING), None)
    return FormalStudyStatusSummary(
        status=ledger.status,
        terminal_slots=sum(s.status in terminal for s in ledger.slots),
        canonical_slots=sum(s.status is FormalSlotStatus.CANONICAL_OBSERVED
                            for s in ledger.slots),
        unresolved_infrastructure_slots=sum(
            s.status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
            for s in ledger.slots
        ),
        retry_required_slot=retry, blocked_slot=blocked,
        next_planned_slot=next_slot,
    )
