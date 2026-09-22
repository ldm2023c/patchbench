"""M10B calibration execution and immutable evidence tests."""

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.application import v13_calibration as calibration
from patchbench.application.v13_agent_execution import (
    FrozenAgentResolutionError,
    resolve_v13_agent_config,
)
from patchbench.domain import (
    AgentIdentityBinding,
    CalibrationBatchStatus,
    CalibrationFailureReason,
    CalibrationSlotStatus,
    EvaluationEvidence,
    ExperimentAggregate,
    ExperimentRecord,
    RunProvenance,
    RunRecord,
    RunStatus,
    V13CalibrationBatch,
    V13CalibrationSlot,
    compute_v13_calibration_protocol_sha256,
)
from patchbench.domain.models import AgentExecutionMetadata
from patchbench.repository.git_repository import RepositoryError
from patchbench.storage.filesystem import FilesystemArtifactStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_IDS = (
    "codex-gpt-5.5-relay",
    "cursor-claude-4.6-sonnet-medium",
    "grok-build-grok-4.5-relay",
)
ZERO_SHA = "0" * 64


class FakeSandbox:
    pass


def _copy_checked_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for relative in (
        calibration.PROTOCOL_PATH,
        calibration.CANDIDATE_PATH,
        Path("tasks/reliability/v1.3-agent-configurations.json"),
        Path("tasks/example/task.yaml"),
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, target)
    return root


def _write_run(
    results_root: Path,
    config_id: str,
    *,
    agent_status: AgentRunStatus = AgentRunStatus.COMPLETED,
    evaluation_passed: bool = True,
    identity_binding: AgentIdentityBinding | None = None,
) -> ExperimentRecord:
    plan = resolve_v13_agent_config(
        config_id, evaluation_backend="docker", project_root=PROJECT_ROOT
    )
    binding = identity_binding or plan.identity_binding
    run_id = f"run-{config_id}"
    store = FilesystemArtifactStore(results_root)
    paths = store.create_paths(run_id)
    record = RunRecord(
        run_id=run_id,
        task_id="example_bug",
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=1.0,
        agent=AgentExecutionMetadata(
            name=plan.experiment_configuration.agent_name,
            backend="host",
            status=agent_status,
            exit_code=(0 if agent_status is AgentRunStatus.COMPLETED else 1),
            duration_seconds=0.5,
            timeout_seconds=plan.experiment_configuration.agent_timeout_seconds,
            requested_model=plan.experiment_configuration.requested_model,
            identity_binding=binding,
        ),
        artifacts=paths,
        provenance=RunProvenance(
            base_commit_used="4ed891e6144bdb78941160726ada95fa7a710f3c",
            task_fingerprint_sha256=ZERO_SHA,
            evaluation_command="pytest",
            evaluation_timeout_seconds=10,
            evaluation_backend="docker",
        ),
        patch_summary={
            "patch_sha256": ZERO_SHA,
            "patch_bytes": 0,
            "changed_file_count": 0,
            "text_added_lines": 0,
            "text_deleted_lines": 0,
            "files": [],
        },
        evaluation_evidence=EvaluationEvidence(
            test_log_sha256=ZERO_SHA,
            exit_code=0 if evaluation_passed else 1,
            passed=evaluation_passed,
            duration_seconds=0.1,
            framework="unknown",
            tests_run=None,
            failure_count=None,
            error_count=None,
            failing_cases=[],
            output_tail=[],
        ),
    )
    paths.metadata.write_text(
        json.dumps(record.model_dump(mode="json")), encoding="utf-8"
    )
    for path in (paths.prompt, paths.agent_log, paths.agent_stderr_log,
                 paths.test_log, paths.patch):
        path.write_text("", encoding="utf-8")
    return ExperimentRecord(
        experiment_id=f"experiment-{config_id}",
        task_id="example_bug",
        requested_runs=1,
        run_ids=[run_id],
        configuration=plan.experiment_configuration,
        aggregate=ExperimentAggregate(
            run_count=1,
            evaluation_pass_count=int(evaluation_passed),
            evaluation_fail_count=int(not evaluation_passed),
            evaluation_pass_rate=float(evaluation_passed),
            agent_command_failure_count=int(agent_status is AgentRunStatus.COMMAND_FAILED),
            agent_timeout_count=int(agent_status is AgentRunStatus.TIMED_OUT),
            total_duration_seconds=1.0,
            mean_duration_seconds=1.0,
            min_duration_seconds=1.0,
            max_duration_seconds=1.0,
        ),
        duration_seconds=1.0,
    )


def _runner(outcomes=None, calls=None):
    outcomes = outcomes or {}
    calls = calls if calls is not None else []

    def run(task_path, **kwargs):
        config_id = kwargs["config_id"]
        calls.append((config_id, kwargs))
        outcome = outcomes.get(config_id, (AgentRunStatus.COMPLETED, True))
        if isinstance(outcome, BaseException):
            raise outcome
        status, passed = outcome
        return _write_run(
            kwargs["results_root"], config_id,
            agent_status=status, evaluation_passed=passed,
        )
    return run


def _run(tmp_path: Path, *, runner=None, batch_id="batch-1", **kwargs):
    return calibration.run_v13_calibration_batch(
        batch_id=batch_id,
        project_root=PROJECT_ROOT,
        results_namespace=tmp_path / "calibration",
        workspace_root=tmp_path / "workspaces",
        sandbox=FakeSandbox(),
        experiment_runner=runner or _runner(),
        **kwargs,
    )


def test_frozen_protocol_verifies_with_exact_semantic_sha():
    verified = calibration.verify_v13_calibration_protocol(PROJECT_ROOT)
    assert compute_v13_calibration_protocol_sha256(verified.protocol) == (
        calibration.ACCEPTED_PROTOCOL_SHA256
    )
    assert tuple(plan.configuration.config_id for plan in verified.plans) == CONFIG_IDS


def test_m3_drift_rejects_before_resolution(tmp_path):
    root = _copy_checked_inputs(tmp_path)
    candidate = root / calibration.CANDIDATE_PATH
    candidate.write_text(candidate.read_text().replace("atomic_batch", "atomic_batch_x", 1))
    called = False
    def resolver(*args, **kwargs):
        nonlocal called
        called = True
    with pytest.raises(calibration.CalibrationIntegrityError, match="M3 candidate"):
        calibration.verify_v13_calibration_protocol(root, resolver=resolver)
    assert called is False


def test_task_byte_drift_rejects(tmp_path):
    root = _copy_checked_inputs(tmp_path)
    with (root / "tasks/example/task.yaml").open("a") as stream:
        stream.write("\n")
    with pytest.raises(calibration.CalibrationIntegrityError, match="TaskSpec byte"):
        calibration.verify_v13_calibration_protocol(root)


def test_m9_resolution_failure_rejects():
    def resolver(*args, **kwargs):
        raise FrozenAgentResolutionError("drift")
    with pytest.raises(calibration.CalibrationIntegrityError, match="M9"):
        calibration.verify_v13_calibration_protocol(PROJECT_ROOT, resolver=resolver)


def test_protocol_config_order_must_equal_m8_order(tmp_path, monkeypatch):
    root = _copy_checked_inputs(tmp_path)
    path = root / calibration.PROTOCOL_PATH
    data = json.loads(path.read_text())
    data["ordered_agent_config_ids"] = list(reversed(data["ordered_agent_config_ids"]))
    path.write_text(json.dumps(data))
    protocol = calibration._load_json_model(path, calibration.V13CalibrationProtocol, "test")
    monkeypatch.setattr(
        calibration, "ACCEPTED_PROTOCOL_SHA256",
        compute_v13_calibration_protocol_sha256(protocol),
    )
    monkeypatch.setattr(
        calibration, "ACCEPTED_PROTOCOL_BYTE_SHA256",
        calibration._sha256_file(path),
    )
    with pytest.raises(calibration.CalibrationIntegrityError, match="manifest/order"):
        calibration.verify_v13_calibration_protocol(root)


def test_formal_task_contamination_rejects(tmp_path, monkeypatch):
    root = _copy_checked_inputs(tmp_path)
    candidate_path = root / calibration.CANDIDATE_PATH
    candidate = json.loads(candidate_path.read_text())
    candidate["tasks"][0]["task_id"] = "example_bug"
    candidate_path.write_text(json.dumps(candidate))
    parsed = calibration._load_json_model(
        candidate_path, calibration.BenchmarkCandidateManifest, "test"
    )
    candidate_sha = calibration.compute_benchmark_candidate_sha256(parsed)
    protocol_path = root / calibration.PROTOCOL_PATH
    protocol_data = json.loads(protocol_path.read_text())
    protocol_data["m3_candidate_sha256"] = candidate_sha
    protocol_path.write_text(json.dumps(protocol_data))
    parsed_protocol = calibration._load_json_model(
        protocol_path, calibration.V13CalibrationProtocol, "test"
    )
    monkeypatch.setattr(calibration, "ACCEPTED_M3_CANDIDATE_SHA256", candidate_sha)
    monkeypatch.setattr(
        calibration, "ACCEPTED_PROTOCOL_SHA256",
        compute_v13_calibration_protocol_sha256(parsed_protocol),
    )
    monkeypatch.setattr(
        calibration, "ACCEPTED_PROTOCOL_BYTE_SHA256",
        calibration._sha256_file(protocol_path),
    )
    with pytest.raises(calibration.CalibrationIntegrityError, match="contaminates"):
        calibration.verify_v13_calibration_protocol(root)


@pytest.mark.parametrize("batch_id", ["", ".", "..", "a/b", "/absolute", " padded"])
def test_unsafe_batch_id_rejects_without_creating_namespace(tmp_path, batch_id):
    namespace = tmp_path / "calibration"
    with pytest.raises(calibration.CalibrationHistoryError, match="unsafe"):
        _run(tmp_path, batch_id=batch_id)
    assert not namespace.exists()


def test_exactly_one_m9_call_per_config_in_frozen_order(tmp_path):
    calls = []
    batch = _run(tmp_path, runner=_runner(calls=calls))
    assert [item[0] for item in calls] == list(CONFIG_IDS)
    for _, kwargs in calls:
        assert kwargs["requested_runs"] == 1
        assert kwargs["evaluation_backend"] == "docker"
        assert kwargs["sandbox"].__class__ is FakeSandbox
    assert batch.status is CalibrationBatchStatus.ACCEPTED
    assert all(slot.status is CalibrationSlotStatus.RUNTIME_ADMITTED for slot in batch.slots)


@pytest.mark.parametrize("passed", [True, False])
def test_completed_is_admitted_regardless_of_evaluator_result(tmp_path, passed):
    outcomes = {config_id: (AgentRunStatus.COMPLETED, passed) for config_id in CONFIG_IDS}
    batch = _run(tmp_path, runner=_runner(outcomes))
    assert batch.status is CalibrationBatchStatus.ACCEPTED
    assert [slot.evaluation_passed for slot in batch.slots] == [passed] * 3


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (AgentRunStatus.COMMAND_FAILED, CalibrationFailureReason.AGENT_COMMAND_FAILED),
        (AgentRunStatus.TIMED_OUT, CalibrationFailureReason.AGENT_TIMED_OUT),
    ],
)
def test_returned_noncompleted_run_is_not_admitted(tmp_path, status, reason):
    outcomes = {CONFIG_IDS[1]: (status, False)}
    batch = _run(tmp_path, runner=_runner(outcomes))
    assert batch.status is CalibrationBatchStatus.COMPLETED_NOT_ADMITTED
    slot = batch.slots[1]
    assert slot.failure_reason is reason
    assert slot.run_id is not None and slot.experiment_id is not None


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AgentSetupError("secret-free"), CalibrationFailureReason.AGENT_SETUP_FAILED),
        (AgentInfrastructureError("secret-free"), CalibrationFailureReason.AGENT_INFRASTRUCTURE_FAILED),
        (RepositoryError("secret-free"), CalibrationFailureReason.REPOSITORY_FAILED),
    ],
)
def test_known_operational_failure_has_no_fabricated_ids_and_continues(
    tmp_path, error, reason
):
    calls = []
    batch = _run(
        tmp_path,
        runner=_runner({CONFIG_IDS[0]: error}, calls),
    )
    assert [item[0] for item in calls] == list(CONFIG_IDS)
    assert batch.status is CalibrationBatchStatus.COMPLETED_NOT_ADMITTED
    failed = batch.slots[0]
    assert failed.failure_reason is reason
    assert failed.run_id is None and failed.experiment_id is None
    assert not (tmp_path / "calibration/batch-1/artifacts" / f"run-{CONFIG_IDS[0]}").exists()


def test_returned_experiment_and_run_linkage_are_persisted(tmp_path):
    batch = _run(tmp_path)
    root = tmp_path / "calibration/batch-1/artifacts"
    for slot in batch.slots:
        run = FilesystemArtifactStore(root).load_run_record(slot.run_id)
        experiment = FilesystemArtifactStore(root).load_experiment_record(slot.experiment_id)
        assert experiment.run_ids == [run.run_id]
        assert run.agent.identity_binding == slot.identity_binding


def test_identity_mismatch_aborts_and_stops_later_slots(tmp_path):
    calls = []
    def runner(task_path, **kwargs):
        calls.append(kwargs["config_id"])
        wrong = AgentIdentityBinding(
            manifest_sha256=ZERO_SHA, config_id=kwargs["config_id"], config_sha256=ZERO_SHA
        )
        return _write_run(kwargs["results_root"], kwargs["config_id"], identity_binding=wrong)
    with pytest.raises(calibration.CalibrationIntegrityError, match="Run evidence"):
        _run(tmp_path, runner=runner)
    assert calls == [CONFIG_IDS[0]]
    ledger = calibration.load_v13_calibration_batch(tmp_path / "calibration/batch-1")
    assert ledger.status is CalibrationBatchStatus.ABORTED
    assert ledger.slots[0].failure_reason is CalibrationFailureReason.EVIDENCE_INTEGRITY_FAILED


def test_unexpected_error_marks_aborted_and_is_reraised(tmp_path):
    calls = []
    with pytest.raises(ValueError, match="bug"):
        _run(tmp_path, runner=_runner({CONFIG_IDS[0]: ValueError("bug")}, calls))
    assert [item[0] for item in calls] == [CONFIG_IDS[0]]
    ledger = calibration.load_v13_calibration_batch(tmp_path / "calibration/batch-1")
    assert ledger.status is CalibrationBatchStatus.ABORTED


def test_existing_batch_id_is_create_only(tmp_path):
    _run(tmp_path)
    original = (tmp_path / "calibration/batch-1/batch.json").read_bytes()
    with pytest.raises(calibration.CalibrationHistoryError):
        _run(tmp_path)
    assert (tmp_path / "calibration/batch-1/batch.json").read_bytes() == original


def test_accepted_batch_blocks_every_later_batch(tmp_path):
    _run(tmp_path)
    with pytest.raises(calibration.CalibrationHistoryError, match="accepted"):
        _run(
            tmp_path, batch_id="batch-2", previous_batch_id="batch-1",
            remediation="authentication availability",
        )


def test_second_batch_requires_exact_tip_and_allowed_remediation(tmp_path):
    failure = {CONFIG_IDS[0]: AgentSetupError("unavailable")}
    _run(tmp_path, runner=_runner(failure))
    with pytest.raises(calibration.CalibrationHistoryError, match="exact chain tip"):
        _run(tmp_path, batch_id="batch-2", remediation="authentication availability")
    with pytest.raises(calibration.CalibrationHistoryError, match="not allowed"):
        _run(
            tmp_path, batch_id="batch-2", previous_batch_id="batch-1",
            remediation="change model",
        )
    batch = _run(
        tmp_path, batch_id="batch-2", previous_batch_id="batch-1",
        remediation="authentication availability",
    )
    assert batch.status is CalibrationBatchStatus.ACCEPTED
    assert batch.previous_batch_id == "batch-1"


def test_initial_batch_rejects_predecessor_and_remediation(tmp_path):
    with pytest.raises(calibration.CalibrationHistoryError, match="first"):
        _run(
            tmp_path, previous_batch_id="old",
            remediation="authentication availability",
        )


def _write_ledger(namespace: Path, record: V13CalibrationBatch):
    directory = namespace / record.batch_id
    directory.mkdir(parents=True)
    (directory / "batch.json").write_text(
        json.dumps(record.model_dump(mode="json")), encoding="utf-8"
    )


def _batch_record(batch_id, status, *, predecessor=None, remediation=None):
    admitted = status is CalibrationBatchStatus.ACCEPTED
    slots = tuple(V13CalibrationSlot(
        config_id=config_id,
        status=(CalibrationSlotStatus.RUNTIME_ADMITTED if admitted
                else CalibrationSlotStatus.RUNTIME_NOT_ADMITTED),
        experiment_id=f"exp-{index}", run_id=f"run-{index}",
        agent_status=(AgentRunStatus.COMPLETED if admitted else AgentRunStatus.TIMED_OUT),
        evaluation_passed=False,
        identity_binding=resolve_v13_agent_config(
            config_id, evaluation_backend="docker", project_root=PROJECT_ROOT
        ).identity_binding,
        failure_reason=(None if admitted else CalibrationFailureReason.AGENT_TIMED_OUT),
    ) for index, config_id in enumerate(CONFIG_IDS))
    if status in {CalibrationBatchStatus.IN_PROGRESS, CalibrationBatchStatus.ABORTED}:
        slots = (V13CalibrationSlot(config_id=CONFIG_IDS[0], status="pending"),) + slots[1:]
    return V13CalibrationBatch(
        batch_id=batch_id,
        protocol_sha256=calibration.ACCEPTED_PROTOCOL_SHA256,
        calibration_task_id="example_bug",
        calibration_task_spec_sha256="ed6ade930729082332dc0101f98332c20d844698e33d7a07f9052d43ea73b609",
        m3_candidate_sha256=calibration.ACCEPTED_M3_CANDIDATE_SHA256,
        m8_agent_manifest_sha256=calibration.ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        ordered_agent_config_ids=CONFIG_IDS,
        previous_batch_id=predecessor,
        environment_remediation=remediation,
        status=status,
        slots=slots,
    )


@pytest.mark.parametrize("status", [CalibrationBatchStatus.IN_PROGRESS, CalibrationBatchStatus.ABORTED])
def test_incomplete_or_aborted_history_blocks_new_batch(tmp_path, status):
    namespace = tmp_path / "calibration"
    _write_ledger(namespace, _batch_record("batch-1", status))
    with pytest.raises(calibration.CalibrationHistoryError, match="blocks"):
        _run(tmp_path, batch_id="batch-2")


def test_corrupt_ledger_blocks_new_batch(tmp_path):
    path = tmp_path / "calibration/batch-1"
    path.mkdir(parents=True)
    (path / "batch.json").write_text("not-json")
    with pytest.raises(calibration.CalibrationHistoryError, match="invalid"):
        _run(tmp_path, batch_id="batch-2")


def test_multiple_roots_and_forks_are_rejected(tmp_path):
    namespace = tmp_path / "calibration"
    _write_ledger(namespace, _batch_record("root-1", CalibrationBatchStatus.COMPLETED_NOT_ADMITTED))
    _write_ledger(namespace, _batch_record("root-2", CalibrationBatchStatus.COMPLETED_NOT_ADMITTED))
    with pytest.raises(calibration.CalibrationHistoryError, match="one root"):
        _run(tmp_path, batch_id="next")


def test_two_children_of_one_predecessor_are_rejected_as_fork(tmp_path):
    namespace = tmp_path / "calibration"
    remediation = "authentication availability"
    _write_ledger(namespace, _batch_record(
        "root", CalibrationBatchStatus.COMPLETED_NOT_ADMITTED
    ))
    _write_ledger(namespace, _batch_record(
        "child-a", CalibrationBatchStatus.COMPLETED_NOT_ADMITTED,
        predecessor="root", remediation=remediation,
    ))
    _write_ledger(namespace, _batch_record(
        "child-b", CalibrationBatchStatus.COMPLETED_NOT_ADMITTED,
        predecessor="root", remediation=remediation,
    ))
    with pytest.raises(calibration.CalibrationHistoryError, match="fork"):
        _run(
            tmp_path, batch_id="next", previous_batch_id="child-a",
            remediation=remediation,
        )


def test_batch_and_slot_models_forbid_extra_and_invalid_states():
    with pytest.raises(ValidationError):
        V13CalibrationSlot(config_id="config", status="pending", extra="no")
    with pytest.raises(ValidationError):
        V13CalibrationSlot(
            config_id="config", status="runtime_admitted",
            failure_reason="agent_setup_failed",
        )
