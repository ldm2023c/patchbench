"""M12 calibration evidence freeze tests."""

import json
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from patchbench.domain import V13CalibrationEvidenceFreeze
from scripts import v13_calibration_evidence as evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "results/v1.3-calibration/calibration-001"


def _copy_source(tmp_path: Path) -> Path:
    target = tmp_path / "calibration" / "calibration-001"
    shutil.copytree(SOURCE, target)
    return target


def _mutate_batch(source: Path, update) -> None:
    path = source / "batch.json"
    data = json.loads(path.read_text())
    update(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_checked_freeze_hashes_and_actual_source_match():
    checked = evidence.verify_checked_freeze()
    rebuilt = evidence.build_calibration_evidence_freeze(SOURCE)
    assert checked == rebuilt
    assert evidence.compute_v13_calibration_evidence_freeze_sha256(checked) == (
        evidence.ACCEPTED_FREEZE_SHA256
    )
    assert evidence._sha256_bytes((PROJECT_ROOT / evidence.FREEZE_PATH).read_bytes()) == (
        evidence.ACCEPTED_FREEZE_BYTE_SHA256
    )


def test_freeze_is_strict_immutable_and_contains_no_local_paths_or_raw_logs():
    freeze = evidence.load_checked_freeze()
    with pytest.raises(ValidationError):
        V13CalibrationEvidenceFreeze.model_validate(
            freeze.model_dump(mode="json") | {"extra": True}
        )
    with pytest.raises(ValidationError):
        freeze.source_batch_id = "changed"
    raw = (PROJECT_ROOT / evidence.FREEZE_PATH).read_text()
    assert "/home/" not in raw
    assert "agent.log" not in raw
    assert "API_KEY" not in raw and "AUTH_TOKEN" not in raw


@pytest.mark.parametrize(
    "update",
    [
        lambda data: data.update(batch_id="other"),
        lambda data: data.update(status="completed_not_admitted"),
        lambda data: data.update(previous_batch_id="earlier", environment_remediation="x"),
        lambda data: data.update(protocol_sha256="0" * 64),
        lambda data: data.update(m3_candidate_sha256="0" * 64),
        lambda data: data.update(m8_agent_manifest_sha256="0" * 64),
        lambda data: data.update(ordered_agent_config_ids=data["ordered_agent_config_ids"][:2]),
        lambda data: data["slots"].__setitem__(0, data["slots"][0] | {"status": "runtime_not_admitted", "failure_reason": "agent_setup_failed", "experiment_id": None, "run_id": None, "agent_status": None, "evaluation_passed": None, "identity_binding": None}),
        lambda data: data["slots"][0]["identity_binding"].update(config_sha256="0" * 64),
        lambda data: data["slots"][0].update(agent_status="timed_out"),
    ],
)
def test_source_batch_contract_drift_rejects(tmp_path, update):
    source = _copy_source(tmp_path)
    _mutate_batch(source, update)
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError):
        evidence.build_calibration_evidence_freeze(source)


def test_evaluator_fail_is_valid_in_admitted_freeze_model():
    freeze = evidence.load_checked_freeze()
    data = freeze.model_dump(mode="json")
    data["slots"][0]["evaluation_passed"] = False
    changed = V13CalibrationEvidenceFreeze.model_validate(data)
    assert changed.slots[0].evaluation_passed is False


def test_source_builder_allows_completed_evaluator_fail(tmp_path):
    source = _copy_source(tmp_path)
    run_id = "438771549e304899b2c9cf46be058392"
    experiment_id = "393127b73d474c1aaeac054d3a55d048"
    _mutate_batch(
        source, lambda data: data["slots"][0].update(evaluation_passed=False)
    )
    run_path = source / "artifacts" / run_id / "metadata.json"
    run = json.loads(run_path.read_text())
    run["status"] = "failed"
    run["evaluation_passed"] = False
    run["evaluation_evidence"]["passed"] = False
    run["evaluation_evidence"]["exit_code"] = 1
    test_path = source / "artifacts" / run_id / "test.log"
    test_path.write_text("synthetic evaluator failure\n")
    run["evaluation_evidence"]["test_log_sha256"] = evidence._sha256_bytes(
        test_path.read_bytes()
    )
    run_path.write_text(json.dumps(run))
    experiment_path = source / "artifacts/experiments" / experiment_id / "metadata.json"
    experiment = json.loads(experiment_path.read_text())
    experiment["aggregate"].update(
        evaluation_pass_count=0, evaluation_fail_count=1, evaluation_pass_rate=0.0
    )
    experiment_path.write_text(json.dumps(experiment))
    rebuilt = evidence.build_calibration_evidence_freeze(source)
    assert rebuilt.slots[0].agent_status.value == "completed"
    assert rebuilt.slots[0].evaluation_passed is False


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("artifacts/438771549e304899b2c9cf46be058392/metadata.json", "Run/Experiment"),
        ("artifacts/experiments/393127b73d474c1aaeac054d3a55d048/metadata.json", "Run/Experiment"),
    ],
)
def test_missing_run_or_experiment_rejects(tmp_path, relative, message):
    source = _copy_source(tmp_path)
    (source / relative).unlink()
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match=message):
        evidence.build_calibration_evidence_freeze(source)


def test_experiment_run_linkage_mismatch_rejects(tmp_path):
    source = _copy_source(tmp_path)
    path = source / "artifacts/experiments/393127b73d474c1aaeac054d3a55d048/metadata.json"
    data = json.loads(path.read_text())
    data["run_ids"] = ["f950366eb74c4f3b975c88e1fbaacb03"]
    path.write_text(json.dumps(data))
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="linkage"):
        evidence.build_calibration_evidence_freeze(source)


@pytest.mark.parametrize("field", ["task_id", "provenance"])
def test_task_or_backend_mismatch_rejects(tmp_path, field):
    source = _copy_source(tmp_path)
    path = source / "artifacts/438771549e304899b2c9cf46be058392/metadata.json"
    data = json.loads(path.read_text())
    if field == "task_id":
        data[field] = "other"
    else:
        data[field]["evaluation_backend"] = "host"
    path.write_text(json.dumps(data))
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="linkage"):
        evidence.build_calibration_evidence_freeze(source)


@pytest.mark.parametrize(
    ("filename", "message"),
    [("patch.diff", "patch hash"), ("test.log", "test-log hash")],
)
def test_raw_evidence_hash_mismatch_rejects(tmp_path, filename, message):
    source = _copy_source(tmp_path)
    path = source / "artifacts/438771549e304899b2c9cf46be058392" / filename
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match=message):
        evidence.build_calibration_evidence_freeze(source)


def test_source_batch_byte_mutation_changes_freeze_identity(tmp_path):
    source = _copy_source(tmp_path)
    (source / "batch.json").write_bytes((source / "batch.json").read_bytes() + b"\n")
    rebuilt = evidence.build_calibration_evidence_freeze(source)
    assert rebuilt.source_batch_json_sha256 != evidence.load_checked_freeze().source_batch_json_sha256
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="differs"):
        evidence.verify_source_against_checked_freeze(source)


def test_extra_later_batch_rejects(tmp_path):
    source = _copy_source(tmp_path)
    (source.parent / "calibration-002").mkdir()
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="extra"):
        evidence.build_calibration_evidence_freeze(source)
