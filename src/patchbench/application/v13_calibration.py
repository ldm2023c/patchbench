"""Execute the frozen PatchBench V1.3 calibration protocol."""

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
    AgentInfrastructureError,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.application.v13_agent_execution import (
    FrozenAgentExecutionPlan,
    FrozenAgentResolutionError,
    load_v13_agent_manifest,
    resolve_v13_agent_config,
    run_v13_agent_experiment,
)
from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain import (
    CalibrationBatchStatus,
    CalibrationFailureReason,
    CalibrationSlotStatus,
    V13CalibrationBatch,
    V13CalibrationProtocol,
    V13CalibrationSlot,
    compute_v13_calibration_protocol_sha256,
    compute_agent_configuration_manifest_sha256,
)
from patchbench.domain.benchmark import (
    BenchmarkCandidateManifest,
    compute_benchmark_candidate_sha256,
)
from patchbench.domain.models import ExperimentRecord, RunRecord
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import RepositoryError
from patchbench.sandbox.base import Sandbox
from patchbench.sandbox.docker import DockerSandboxError
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


ACCEPTED_PROTOCOL_SHA256 = "1347188de4d5cd3e25fb4f4444a60e7c0994dd4b020cb514bf369479d4794eff"
ACCEPTED_PROTOCOL_BYTE_SHA256 = "2a81a974b1d8be7c19f3a32eb1d882ddd1d61c215a0f444670ab0b39c2214bf8"
ACCEPTED_M3_CANDIDATE_SHA256 = "a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043"
ACCEPTED_M8_AGENT_MANIFEST_SHA256 = "6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965"
PROTOCOL_PATH = Path("tasks/reliability/v1.3-calibration-protocol.json")
CANDIDATE_PATH = Path("tasks/reliability/v1.3-candidate.json")
DEFAULT_CALIBRATION_RESULTS_PATH = Path("results/v1.3-calibration")


class CalibrationIntegrityError(RuntimeError):
    """Frozen inputs or persisted calibration evidence failed verification."""


class CalibrationHistoryError(CalibrationIntegrityError):
    """Existing calibration batches do not form an eligible linear history."""


@dataclass(frozen=True)
class VerifiedCalibrationProtocol:
    protocol: V13CalibrationProtocol
    task_path: Path
    plans: tuple[FrozenAgentExecutionPlan, ...]


ExperimentRunner = Callable[..., ExperimentRecord]
Resolver = Callable[..., FrozenAgentExecutionPlan]


def _load_json_model(path: Path, model_type, label: str):
    try:
        return model_type.model_validate_json(path.read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise CalibrationIntegrityError(f"invalid {label}") from error


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise CalibrationIntegrityError("unable to hash frozen calibration input") from error


def verify_v13_calibration_protocol(
    project_root: Path,
    *,
    resolver: Resolver = resolve_v13_agent_config,
) -> VerifiedCalibrationProtocol:
    """Independently verify all checked inputs without starting an Agent process."""

    root = Path(project_root).resolve()
    protocol_path = root / PROTOCOL_PATH
    protocol = _load_json_model(
        protocol_path, V13CalibrationProtocol, "V1.3 calibration protocol"
    )
    if _sha256_file(protocol_path) != ACCEPTED_PROTOCOL_BYTE_SHA256:
        raise CalibrationIntegrityError("calibration protocol artifact byte SHA mismatch")
    protocol_sha = compute_v13_calibration_protocol_sha256(protocol)
    if protocol_sha != ACCEPTED_PROTOCOL_SHA256:
        raise CalibrationIntegrityError("calibration protocol semantic SHA mismatch")

    candidate = _load_json_model(
        root / CANDIDATE_PATH, BenchmarkCandidateManifest, "M3 candidate manifest"
    )
    candidate_sha = compute_benchmark_candidate_sha256(candidate)
    if (candidate_sha != ACCEPTED_M3_CANDIDATE_SHA256
            or candidate_sha != protocol.m3_candidate_sha256):
        raise CalibrationIntegrityError("M3 candidate semantic SHA mismatch")
    if protocol.calibration_task_id in {task.task_id for task in candidate.tasks}:
        raise CalibrationIntegrityError("calibration task contaminates formal M3 candidate")

    task_path = root / protocol.calibration_task_spec_path
    if _sha256_file(task_path) != protocol.calibration_task_spec_sha256:
        raise CalibrationIntegrityError("calibration TaskSpec byte SHA mismatch")
    try:
        task = load_task(task_path)
    except TaskLoadError as error:
        raise CalibrationIntegrityError("invalid calibration TaskSpec") from error
    if (task.id != protocol.calibration_task_id
            or task.repository.base_commit != protocol.calibration_base_commit):
        raise CalibrationIntegrityError("calibration TaskSpec identity mismatch")
    if protocol.evaluation_backend != "docker" or protocol.runs_per_configuration != 1:
        raise CalibrationIntegrityError("calibration execution shape is not frozen")

    try:
        agent_manifest = load_v13_agent_manifest(root)
    except FrozenAgentResolutionError as error:
        raise CalibrationIntegrityError("invalid M8 Agent manifest") from error
    agent_manifest_sha = compute_agent_configuration_manifest_sha256(agent_manifest)
    manifest_config_ids = tuple(item.config_id for item in agent_manifest.configurations)
    if (agent_manifest_sha != ACCEPTED_M8_AGENT_MANIFEST_SHA256
            or agent_manifest_sha != protocol.m8_agent_manifest_sha256
            or manifest_config_ids != protocol.ordered_agent_config_ids):
        raise CalibrationIntegrityError("M8 Agent manifest/order mismatch")

    plans = []
    for config_id in protocol.ordered_agent_config_ids:
        try:
            plan = resolver(
                config_id, evaluation_backend="docker", project_root=root
            )
        except FrozenAgentResolutionError as error:
            raise CalibrationIntegrityError("M9 frozen Agent resolution failed") from error
        binding = plan.identity_binding
        if (binding.manifest_sha256 != ACCEPTED_M8_AGENT_MANIFEST_SHA256
                or binding.manifest_sha256 != protocol.m8_agent_manifest_sha256
                or binding.config_id != config_id
                or plan.configuration.config_id != config_id
                or plan.experiment_configuration.identity_binding != binding
                or plan.experiment_configuration.evaluation_backend != "docker"):
            raise CalibrationIntegrityError("M8/M9 Agent binding mismatch")
        plans.append(plan)
    return VerifiedCalibrationProtocol(protocol, task_path, tuple(plans))


def _batch_directory(namespace: Path, batch_id: str) -> Path:
    try:
        # Domain validation supplies the syntax check; this proves containment too.
        candidate = (namespace / batch_id).resolve()
    except (OSError, RuntimeError) as error:
        raise CalibrationHistoryError("unable to resolve calibration batch path") from error
    if candidate.parent != namespace.resolve() or candidate.name != batch_id:
        raise CalibrationHistoryError("unsafe calibration batch ID")
    return candidate


def _load_history(namespace: Path) -> tuple[V13CalibrationBatch, ...]:
    if not namespace.exists():
        return ()
    if not namespace.is_dir():
        raise CalibrationHistoryError("calibration namespace is not a directory")
    records = []
    try:
        entries = sorted(namespace.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise CalibrationHistoryError("unable to inspect calibration history") from error
    for entry in entries:
        if not entry.is_dir() or entry.is_symlink():
            raise CalibrationHistoryError("calibration namespace contains invalid evidence")
        try:
            record = V13CalibrationBatch.model_validate_json(
                (entry / "batch.json").read_bytes()
            )
        except (OSError, UnicodeError, ValidationError) as error:
            raise CalibrationHistoryError("invalid calibration batch ledger") from error
        if record.batch_id != entry.name:
            raise CalibrationHistoryError("batch directory and ledger IDs differ")
        records.append(record)
    return tuple(records)


def _validate_history(
    records: tuple[V13CalibrationBatch, ...],
    *,
    previous_batch_id: str | None,
    remediation: str | None,
    protocol: V13CalibrationProtocol,
) -> None:
    for record in records:
        if (record.protocol_sha256 != ACCEPTED_PROTOCOL_SHA256
                or record.calibration_task_id != protocol.calibration_task_id
                or record.calibration_task_spec_sha256
                != protocol.calibration_task_spec_sha256
                or record.m3_candidate_sha256 != protocol.m3_candidate_sha256
                or record.m8_agent_manifest_sha256 != protocol.m8_agent_manifest_sha256
                or record.ordered_agent_config_ids != protocol.ordered_agent_config_ids):
            raise CalibrationHistoryError(
                "calibration history differs from the frozen protocol"
            )
        if (record.environment_remediation is not None
                and record.environment_remediation
                not in protocol.allowed_environment_remediation):
            raise CalibrationHistoryError(
                "calibration history contains disallowed remediation"
            )
    if not records:
        if previous_batch_id is not None or remediation is not None:
            raise CalibrationHistoryError("first calibration batch cannot have a predecessor")
        return
    by_id = {record.batch_id: record for record in records}
    if len(by_id) != len(records):
        raise CalibrationHistoryError("duplicate calibration batch IDs")
    roots = [record for record in records if record.previous_batch_id is None]
    if len(roots) != 1:
        raise CalibrationHistoryError("calibration history must have exactly one root")
    children: dict[str, list[V13CalibrationBatch]] = {key: [] for key in by_id}
    for record in records:
        if record.previous_batch_id is not None:
            if record.previous_batch_id not in by_id:
                raise CalibrationHistoryError("calibration predecessor is missing")
            children[record.previous_batch_id].append(record)
    if any(len(items) > 1 for items in children.values()):
        raise CalibrationHistoryError("calibration history contains a fork")
    chain = []
    current = roots[0]
    seen = set()
    while True:
        if current.batch_id in seen:
            raise CalibrationHistoryError("calibration history contains a cycle")
        seen.add(current.batch_id)
        chain.append(current)
        next_items = children[current.batch_id]
        if not next_items:
            break
        current = next_items[0]
    if len(chain) != len(records):
        raise CalibrationHistoryError("calibration history is disconnected")
    if any(record.status is CalibrationBatchStatus.ACCEPTED for record in chain):
        raise CalibrationHistoryError("an accepted calibration batch already exists")
    if any(record.status in {
        CalibrationBatchStatus.IN_PROGRESS, CalibrationBatchStatus.ABORTED,
    } for record in chain):
        raise CalibrationHistoryError("incomplete or aborted calibration evidence blocks execution")
    tip = chain[-1]
    if tip.status is not CalibrationBatchStatus.COMPLETED_NOT_ADMITTED:
        raise CalibrationHistoryError("calibration chain tip is not eligible for a new batch")
    if previous_batch_id != tip.batch_id:
        raise CalibrationHistoryError("new batch must reference the exact chain tip")
    if remediation not in protocol.allowed_environment_remediation:
        raise CalibrationHistoryError("remediation is not allowed by the frozen protocol")


def _write_ledger(path: Path, record: V13CalibrationBatch) -> None:
    temporary = path.with_name(".batch.json.tmp")
    try:
        temporary.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    except OSError as error:
        raise ArtifactStoreError("unable to persist calibration batch ledger") from error


def _record(
    verified: VerifiedCalibrationProtocol,
    *,
    batch_id: str,
    previous_batch_id: str | None,
    remediation: str | None,
    status: CalibrationBatchStatus,
    slots: tuple[V13CalibrationSlot, ...],
) -> V13CalibrationBatch:
    protocol = verified.protocol
    return V13CalibrationBatch(
        batch_id=batch_id,
        protocol_sha256=ACCEPTED_PROTOCOL_SHA256,
        calibration_task_id=protocol.calibration_task_id,
        calibration_task_spec_sha256=protocol.calibration_task_spec_sha256,
        m3_candidate_sha256=protocol.m3_candidate_sha256,
        m8_agent_manifest_sha256=protocol.m8_agent_manifest_sha256,
        ordered_agent_config_ids=protocol.ordered_agent_config_ids,
        previous_batch_id=previous_batch_id,
        environment_remediation=remediation,
        status=status,
        slots=slots,
    )


def _failure_slot(config_id: str, reason: CalibrationFailureReason) -> V13CalibrationSlot:
    return V13CalibrationSlot(
        config_id=config_id,
        status=CalibrationSlotStatus.RUNTIME_NOT_ADMITTED,
        failure_reason=reason,
    )


def _verify_returned_experiment(
    experiment: ExperimentRecord,
    *,
    plan: FrozenAgentExecutionPlan,
    verified: VerifiedCalibrationProtocol,
    store: FilesystemArtifactStore,
) -> RunRecord:
    protocol = verified.protocol
    expected = plan.experiment_configuration
    if (experiment.task_id != protocol.calibration_task_id
            or experiment.requested_runs != 1
            or len(experiment.run_ids) != 1
            or experiment.configuration != expected):
        raise CalibrationIntegrityError("returned Experiment violates frozen execution plan")
    run = store.load_run_record(experiment.run_ids[0])
    if (run.task_id != protocol.calibration_task_id
            or run.provenance is None
            or run.provenance.base_commit_used != protocol.calibration_base_commit
            or run.provenance.evaluation_backend != "docker"
            or run.agent.identity_binding != experiment.configuration.identity_binding
            or run.agent.identity_binding != plan.identity_binding
            or run.agent.name != expected.agent_name
            or run.agent.requested_model != expected.requested_model
            or run.agent.timeout_seconds != expected.agent_timeout_seconds
            or run.evaluation_evidence is None
            or run.evaluation_evidence.passed != run.evaluation_passed):
        raise CalibrationIntegrityError("persisted Run evidence violates frozen execution plan")
    return run


def _measured_slot(
    config_id: str,
    experiment: ExperimentRecord,
    run: RunRecord,
) -> V13CalibrationSlot:
    admitted = run.agent.status is AgentRunStatus.COMPLETED
    reason = None
    if run.agent.status is AgentRunStatus.COMMAND_FAILED:
        reason = CalibrationFailureReason.AGENT_COMMAND_FAILED
    elif run.agent.status is AgentRunStatus.TIMED_OUT:
        reason = CalibrationFailureReason.AGENT_TIMED_OUT
    return V13CalibrationSlot(
        config_id=config_id,
        status=(CalibrationSlotStatus.RUNTIME_ADMITTED if admitted
                else CalibrationSlotStatus.RUNTIME_NOT_ADMITTED),
        experiment_id=experiment.experiment_id,
        run_id=run.run_id,
        agent_status=run.agent.status,
        evaluation_passed=run.evaluation_passed,
        identity_binding=run.agent.identity_binding,
        failure_reason=reason,
    )


_OPERATIONAL_FAILURES: tuple[tuple[type[BaseException], CalibrationFailureReason], ...] = (
    (AgentSetupError, CalibrationFailureReason.AGENT_SETUP_FAILED),
    (AgentInfrastructureError, CalibrationFailureReason.AGENT_INFRASTRUCTURE_FAILED),
    (RepositoryError, CalibrationFailureReason.REPOSITORY_FAILED),
    (DockerSandboxError, CalibrationFailureReason.EVALUATION_INFRASTRUCTURE_FAILED),
    (EvaluationError, CalibrationFailureReason.EVALUATION_INFRASTRUCTURE_FAILED),
    (ArtifactStoreError, CalibrationFailureReason.ARTIFACT_STORE_FAILED),
)


def _operational_reason(error: BaseException) -> CalibrationFailureReason | None:
    for error_type, reason in _OPERATIONAL_FAILURES:
        if isinstance(error, error_type):
            return reason
    return None


@contextmanager
def _exclusive_history_lock(namespace: Path):
    """Serialize history inspection and batch execution across operator processes."""
    lock_path = namespace.parent / f".{namespace.name}.lock"
    try:
        namespace.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    except OSError as error:
        raise ArtifactStoreError("unable to lock calibration history") from error
    try:
        yield
    finally:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def run_v13_calibration_batch(
    *,
    batch_id: str,
    project_root: Path,
    results_namespace: Path | None = None,
    workspace_root: Path | None = None,
    previous_batch_id: str | None = None,
    remediation: str | None = None,
    sandbox: Sandbox,
    resolver: Resolver = resolve_v13_agent_config,
    experiment_runner: ExperimentRunner = run_v13_agent_experiment,
) -> V13CalibrationBatch:
    """Execute one create-only, non-resumable calibration batch."""

    root = Path(project_root).resolve()
    namespace = (root / DEFAULT_CALIBRATION_RESULTS_PATH if results_namespace is None
                 else Path(results_namespace)).resolve()
    with _exclusive_history_lock(namespace):
        return _run_v13_calibration_batch_locked(
            batch_id=batch_id,
            project_root=root,
            results_namespace=namespace,
            workspace_root=workspace_root,
            previous_batch_id=previous_batch_id,
            remediation=remediation,
            sandbox=sandbox,
            resolver=resolver,
            experiment_runner=experiment_runner,
        )


def _run_v13_calibration_batch_locked(
    *,
    batch_id: str,
    project_root: Path,
    results_namespace: Path,
    workspace_root: Path | None,
    previous_batch_id: str | None,
    remediation: str | None,
    sandbox: Sandbox,
    resolver: Resolver,
    experiment_runner: ExperimentRunner,
) -> V13CalibrationBatch:
    """Run one batch while holding the exclusive calibration-history lock."""

    # Validate the ID before any directory is created.
    try:
        V13CalibrationBatch(
            batch_id=batch_id,
            protocol_sha256="0" * 64,
            calibration_task_id="placeholder",
            calibration_task_spec_sha256="0" * 64,
            m3_candidate_sha256="0" * 64,
            m8_agent_manifest_sha256="0" * 64,
            ordered_agent_config_ids=("placeholder",),
            status="in_progress",
            slots=(V13CalibrationSlot(config_id="placeholder", status="pending"),),
        )
    except ValidationError as error:
        raise CalibrationHistoryError("unsafe calibration batch ID") from error

    root = Path(project_root).resolve()
    verified = verify_v13_calibration_protocol(root, resolver=resolver)
    namespace = Path(results_namespace).resolve()
    history = _load_history(namespace)
    _validate_history(
        history,
        previous_batch_id=previous_batch_id,
        remediation=remediation,
        protocol=verified.protocol,
    )
    batch_root = _batch_directory(namespace, batch_id)
    if batch_root.exists():
        raise CalibrationHistoryError("calibration batch ID already exists")
    try:
        batch_root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise ArtifactStoreError("unable to create calibration batch directory") from error
    artifacts_root = batch_root / "artifacts"
    try:
        artifacts_root.mkdir()
    except OSError as error:
        raise ArtifactStoreError("unable to create calibration artifact namespace") from error

    slots = tuple(
        V13CalibrationSlot(config_id=config_id, status="pending")
        for config_id in verified.protocol.ordered_agent_config_ids
    )
    ledger_path = batch_root / "batch.json"
    current = _record(
        verified,
        batch_id=batch_id,
        previous_batch_id=previous_batch_id,
        remediation=remediation,
        status=CalibrationBatchStatus.IN_PROGRESS,
        slots=slots,
    )
    _write_ledger(ledger_path, current)

    completed_slots: list[V13CalibrationSlot] = []
    store = FilesystemArtifactStore(artifacts_root)
    try:
        for index, (config_id, plan) in enumerate(zip(
            verified.protocol.ordered_agent_config_ids, verified.plans, strict=True
        )):
            try:
                experiment = experiment_runner(
                    verified.task_path,
                    config_id=config_id,
                    requested_runs=1,
                    evaluation_backend="docker",
                    project_root=root,
                    workspace_root=workspace_root,
                    results_root=artifacts_root,
                    sandbox=sandbox,
                )
            except Exception as error:
                reason = _operational_reason(error)
                if reason is None:
                    raise
                completed_slots.append(_failure_slot(config_id, reason))
            else:
                try:
                    run = _verify_returned_experiment(
                        experiment, plan=plan, verified=verified, store=store
                    )
                except CalibrationIntegrityError:
                    completed_slots.append(_failure_slot(
                        config_id, CalibrationFailureReason.EVIDENCE_INTEGRITY_FAILED
                    ))
                    raise
                try:
                    store.save_experiment(experiment)
                except ArtifactStoreError:
                    completed_slots.append(V13CalibrationSlot(
                        config_id=config_id,
                        status=CalibrationSlotStatus.RUNTIME_NOT_ADMITTED,
                        experiment_id=experiment.experiment_id,
                        run_id=run.run_id,
                        agent_status=run.agent.status,
                        evaluation_passed=run.evaluation_passed,
                        identity_binding=run.agent.identity_binding,
                        failure_reason=CalibrationFailureReason.ARTIFACT_STORE_FAILED,
                    ))
                else:
                    completed_slots.append(_measured_slot(config_id, experiment, run))
            remaining = slots[index + 1:]
            current = _record(
                verified,
                batch_id=batch_id,
                previous_batch_id=previous_batch_id,
                remediation=remediation,
                status=(CalibrationBatchStatus.IN_PROGRESS if remaining
                        else CalibrationBatchStatus.ACCEPTED),
                slots=tuple(completed_slots) + remaining,
            ) if remaining else _record(
                verified,
                batch_id=batch_id,
                previous_batch_id=previous_batch_id,
                remediation=remediation,
                status=(CalibrationBatchStatus.ACCEPTED if all(
                    slot.status is CalibrationSlotStatus.RUNTIME_ADMITTED
                    for slot in completed_slots
                ) else CalibrationBatchStatus.COMPLETED_NOT_ADMITTED),
                slots=tuple(completed_slots),
            )
            _write_ledger(ledger_path, current)
    except Exception:
        aborted = _record(
            verified,
            batch_id=batch_id,
            previous_batch_id=previous_batch_id,
            remediation=remediation,
            status=CalibrationBatchStatus.ABORTED,
            slots=tuple(completed_slots) + slots[len(completed_slots):],
        )
        try:
            _write_ledger(ledger_path, aborted)
        except ArtifactStoreError:
            pass
        raise
    return current


def load_v13_calibration_batch(batch_root: Path) -> V13CalibrationBatch:
    """Load a terminal or active batch ledger for operator inspection."""
    try:
        return V13CalibrationBatch.model_validate_json((batch_root / "batch.json").read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise CalibrationIntegrityError("invalid calibration batch ledger") from error
