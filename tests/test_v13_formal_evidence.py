"""Provider-free tests for the V1.3 formal evidence freeze."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.application import v13_formal_execution as execution
from patchbench.application.v13_agent_execution import resolve_v13_agent_config
from patchbench.config.task_loader import load_task
from patchbench.domain import (
    AgentExecutionMetadata, EvaluationResult, FormalAttemptStatus,
    FormalFailureCategory, FormalSlotStatus, RunProvenance, RunRecord, RunStatus,
    compute_task_fingerprint, render_evaluation_log, summarize_evaluation_log,
    summarize_patch,
)
from patchbench.domain.calibration_evidence import compute_run_semantic_sha256
from patchbench.domain.formal_evidence import (
    V13FormalEvidenceFreeze, compute_v13_formal_attempt_sha256,
    compute_v13_formal_evidence_freeze_sha256, compute_v13_formal_study_sha256,
)
from patchbench.storage.filesystem import FilesystemArtifactStore
from scripts import v13_formal_evidence as evidence
from scripts.v13_formal_preregistration import verify_preregistration


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_run(artifacts: Path, planned, task_path: Path) -> RunRecord:
    task = load_task(task_path)
    plan = resolve_v13_agent_config(
        planned.config_id, evaluation_backend="docker", project_root=PROJECT_ROOT
    )
    run_id = f"synthetic-{planned.ordinal:03d}"
    paths = FilesystemArtifactStore(artifacts).create_paths(run_id)
    result = EvaluationResult(
        exit_code=0, passed=True, duration_seconds=0.1,
        stdout="synthetic pass\n", stderr="",
    )
    test_log = render_evaluation_log(result, task.evaluation.command)
    record = RunRecord(
        run_id=run_id, task_id=task.id, status=RunStatus.PASSED,
        evaluation_passed=True, duration_seconds=1.0,
        agent=AgentExecutionMetadata(
            name=plan.experiment_configuration.agent_name, backend="host",
            status=AgentRunStatus.COMPLETED, exit_code=0, duration_seconds=0.5,
            timeout_seconds=plan.experiment_configuration.agent_timeout_seconds,
            requested_model=plan.experiment_configuration.requested_model,
            identity_binding=plan.identity_binding,
        ),
        artifacts=paths,
        provenance=RunProvenance(
            base_commit_used=planned.resolved_base_commit,
            task_fingerprint_sha256=compute_task_fingerprint(
                task, base_commit_used=planned.resolved_base_commit
            ),
            evaluation_command=task.evaluation.command,
            evaluation_timeout_seconds=task.evaluation.timeout_seconds,
            evaluation_backend="docker",
        ),
        patch_summary=summarize_patch(""),
        evaluation_evidence=summarize_evaluation_log(test_log),
    )
    paths.metadata.write_text(json.dumps(record.model_dump(mode="json"), indent=2) + "\n")
    paths.prompt.write_text(task.task.prompt)
    paths.agent_log.write_text("synthetic stdout\n")
    paths.agent_stderr_log.write_text("")
    paths.test_log.write_text(test_log)
    paths.patch.write_text("")
    return record


@pytest.fixture(scope="module")
def synthetic_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("formal-source") / "formal"
    prereg = verify_preregistration(PROJECT_ROOT)
    ledger = execution.initialize_formal_study(
        project_root=PROJECT_ROOT, results_root=root
    )
    for index, planned in enumerate(prereg.slots):
        ledger, attempt, attempt_dir = execution._create_attempt(
            root, ledger, index, attempt_index=1, remediation=None
        )
        if index in {0, 1}:
            category = (FormalFailureCategory.AGENT_SETUP if index == 0
                        else FormalFailureCategory.DOCKER_INFRASTRUCTURE)
            ledger = execution._record_retryable(root, ledger, index, attempt, category)
            ledger, attempt, attempt_dir = execution._create_attempt(
                root, ledger, index, attempt_index=2,
                remediation="Docker availability",
            )
            if index == 1:
                ledger = execution._record_retryable(
                    root, ledger, index, attempt, category
                )
                continue
        candidate = next(
            item for item in json.loads(
                (PROJECT_ROOT / "tasks/reliability/v1.3-candidate.json").read_text()
            )["tasks"] if item["task_id"] == planned.task_id
        )
        run = _write_run(attempt_dir / "artifacts", planned,
                         PROJECT_ROOT / candidate["task_spec_path"])
        ledger = execution._terminalize_canonical(
            root, ledger, index, attempt, run
        )
    assert ledger.status.value == "completed"
    return root


def _copy_source(synthetic_source: Path, tmp_path: Path) -> Path:
    target = tmp_path / "formal"
    shutil.copytree(synthetic_source, target)
    for metadata in target.glob("slots/*/attempt-*/artifacts/*/metadata.json"):
        run_root = metadata.parent.resolve()
        data = json.loads(metadata.read_text())
        data["artifacts"] = {
            "directory": str(run_root),
            "metadata": str(run_root / "metadata.json"),
            "prompt": str(run_root / "prompt.txt"),
            "agent_log": str(run_root / "agent.log"),
            "agent_stderr_log": str(run_root / "agent.stderr.log"),
            "test_log": str(run_root / "test.log"),
            "patch": str(run_root / "patch.diff"),
        }
        metadata.write_text(json.dumps(data, indent=2) + "\n")
    return target


def test_source_builder_freezes_order_labels_histories_and_hashes(synthetic_source):
    freeze = evidence.build_formal_evidence_freeze(
        synthetic_source, project_root=PROJECT_ROOT
    )
    prereg = verify_preregistration(PROJECT_ROOT)
    assert freeze.canonical_slot_count == 107
    assert freeze.unresolved_infrastructure_slot_count == 1
    assert tuple(slot.slot_id for slot in freeze.slots) == tuple(
        slot.slot_id for slot in prereg.slots
    )
    assert len(freeze.slots[0].attempts) == 2
    assert freeze.slots[0].attempts[0].failure_category is FormalFailureCategory.AGENT_SETUP
    assert freeze.slots[1].source_slot_status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
    assert freeze.slots[1].canonical_run is None
    raw = (synthetic_source / "study.json").read_bytes()
    assert freeze.source_study_json_sha256 == hashlib.sha256(raw).hexdigest()
    checked_study = execution._load_study(synthetic_source, prereg)
    assert freeze.source_study_semantic_sha256 == compute_v13_formal_study_sha256(
        checked_study
    )
    assert freeze.formal_preregistration_sha256 == evidence.ACCEPTED_PREREGISTRATION_SHA256
    assert freeze.design_sha256 == prereg.design_sha256
    assert freeze.candidate_sha256 == prereg.candidate_sha256
    assert freeze.agent_manifest_sha256 == prereg.agent_manifest_sha256
    profiles = {
        item["task_id"]: item
        for item in json.loads(
            (PROJECT_ROOT / "tasks/reliability/v1.3-design.json").read_text()
        )["tasks"]
    }
    assert all(
        slot.primary_capability.value == profiles[slot.task_id]["primary_capability"]
        and slot.designed_difficulty.value == profiles[slot.task_id]["designed_difficulty"]
        for slot in freeze.slots
    )
    run = freeze.slots[0].canonical_run
    assert run is not None
    attempt = freeze.slots[0].attempts[1]
    attempt_raw = (synthetic_source / "slots" / freeze.slots[0].slot_id
                   / "attempt-02/attempt.json").read_bytes()
    assert attempt.attempt_json_sha256 == hashlib.sha256(attempt_raw).hexdigest()
    source_attempt = execution._load_attempt(
        synthetic_source / "slots" / freeze.slots[0].slot_id / "attempt-02"
    )
    assert attempt.attempt_semantic_sha256 == compute_v13_formal_attempt_sha256(
        source_attempt
    )
    run_root = (synthetic_source / "slots" / freeze.slots[0].slot_id
                / "attempt-02/artifacts" / run.run_id)
    assert run.metadata_sha256 == hashlib.sha256(
        (run_root / "metadata.json").read_bytes()
    ).hexdigest()
    assert run.prompt_sha256 == hashlib.sha256((run_root / "prompt.txt").read_bytes()).hexdigest()
    assert run.agent_stdout_sha256 == hashlib.sha256(
        (run_root / "agent.log").read_bytes()
    ).hexdigest()
    assert run.agent_stderr_sha256 == hashlib.sha256(
        (run_root / "agent.stderr.log").read_bytes()
    ).hexdigest()
    assert run.test_log_sha256 == hashlib.sha256((run_root / "test.log").read_bytes()).hexdigest()
    assert run.patch_sha256 == hashlib.sha256((run_root / "patch.diff").read_bytes()).hexdigest()
    serialized = evidence.deterministic_json(freeze)
    assert "/home/" not in serialized
    assert "synthetic stdout" not in serialized
    assert "API_KEY" not in serialized


def test_semantic_hash_is_deterministic_and_run_hash_excludes_paths(synthetic_source):
    first = evidence.build_formal_evidence_freeze(synthetic_source, project_root=PROJECT_ROOT)
    second = V13FormalEvidenceFreeze.model_validate_json(evidence.deterministic_json(first))
    assert compute_v13_formal_evidence_freeze_sha256(first) == \
        compute_v13_formal_evidence_freeze_sha256(second)
    slot = first.slots[2]
    attempt = synthetic_source / "slots" / slot.slot_id / "attempt-01/artifacts"
    run = FilesystemArtifactStore(attempt).load_run_record(slot.canonical_run.run_id)
    moved = run.model_copy(update={
        "artifacts": run.artifacts.model_copy(update={"directory": Path("/different")})
    })
    assert compute_run_semantic_sha256(run) == compute_run_semantic_sha256(moved)


@pytest.mark.parametrize("mutation", [
    "study", "slot_order", "non_completed", "missing_slot", "extra_slot",
    "attempt_identity", "missing_run",
    "multiple_runs", "patch", "test_log", "prompt", "symlink", "attempt_03",
    "run_task", "base_commit", "fingerprint", "binding", "evaluation",
])
def test_source_drift_fails_closed(synthetic_source, tmp_path, mutation):
    source = _copy_source(synthetic_source, tmp_path)
    study = json.loads((source / "study.json").read_text())
    first = study["slots"][2]
    slot_dir = source / "slots" / first["slot_id"]
    attempt = slot_dir / "attempt-01"
    run_id = first["canonical_run_id"]
    run_dir = attempt / "artifacts" / run_id
    if mutation == "study":
        study["formal_preregistration_sha256"] = "0" * 64
        (source / "study.json").write_text(json.dumps(study))
    elif mutation == "slot_order":
        study["slots"][0], study["slots"][1] = study["slots"][1], study["slots"][0]
        (source / "study.json").write_text(json.dumps(study))
    elif mutation == "non_completed":
        study["status"] = "running"
        (source / "study.json").write_text(json.dumps(study))
    elif mutation == "missing_slot":
        shutil.rmtree(slot_dir)
    elif mutation == "extra_slot":
        (source / "slots/extra").mkdir()
    elif mutation == "attempt_identity":
        data = json.loads((attempt / "attempt.json").read_text())
        data["task_id"] = "wrong"
        (attempt / "attempt.json").write_text(json.dumps(data))
    elif mutation == "missing_run":
        shutil.rmtree(run_dir)
    elif mutation == "multiple_runs":
        shutil.copytree(run_dir, attempt / "artifacts/second")
    elif mutation in {"patch", "test_log", "prompt"}:
        name = {"patch": "patch.diff", "test_log": "test.log", "prompt": "prompt.txt"}[mutation]
        (run_dir / name).write_text((run_dir / name).read_text() + "drift")
    elif mutation == "symlink":
        path = run_dir / "prompt.txt"
        path.unlink()
        path.symlink_to(tmp_path / "outside")
    elif mutation == "attempt_03":
        (slot_dir / "attempt-03").mkdir()
    else:
        metadata = run_dir / "metadata.json"
        data = json.loads(metadata.read_text())
        if mutation == "run_task":
            data["task_id"] = "wrong"
        elif mutation == "base_commit":
            data["provenance"]["base_commit_used"] = "0" * 40
        elif mutation == "fingerprint":
            data["provenance"]["task_fingerprint_sha256"] = "0" * 64
        elif mutation == "binding":
            data["agent"]["identity_binding"]["config_sha256"] = "0" * 64
        else:
            data["evaluation_evidence"]["passed"] = False
        metadata.write_text(json.dumps(data))
    with pytest.raises(Exception):
        evidence.build_formal_evidence_freeze(source, project_root=PROJECT_ROOT)


def test_checked_freeze_is_strict_and_byte_hash_is_exact():
    freeze = evidence.verify_checked_freeze(PROJECT_ROOT)
    path = PROJECT_ROOT / evidence.FREEZE_PATH
    assert hashlib.sha256(path.read_bytes()).hexdigest() == \
        evidence.ACCEPTED_FORMAL_FREEZE_BYTE_SHA256
    data = freeze.model_dump(mode="json")
    data["unexpected"] = True
    with pytest.raises(Exception):
        V13FormalEvidenceFreeze.model_validate(data)


def test_normal_checked_verification_does_not_read_live_results(monkeypatch):
    original = Path.read_bytes
    def guarded(path):
        assert "results/v1.3-formal" not in path.as_posix()
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    evidence.verify_checked_freeze(PROJECT_ROOT)


def test_check_source_detects_drift(synthetic_source, tmp_path, monkeypatch):
    checked = evidence.build_formal_evidence_freeze(
        synthetic_source, project_root=PROJECT_ROOT
    )
    source = _copy_source(synthetic_source, tmp_path)
    monkeypatch.setattr(evidence, "verify_checked_freeze", lambda root: checked)
    (source / "study.json").write_text("{}")
    with pytest.raises(Exception):
        evidence.verify_source_against_checked_freeze(source, project_root=PROJECT_ROOT)
