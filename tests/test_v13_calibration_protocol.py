import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import (
    V13CalibrationProtocol,
    compute_agent_configuration_manifest_sha256,
    compute_v13_calibration_protocol_sha256,
)
from patchbench.domain.benchmark import compute_benchmark_candidate_sha256
from scripts.v13_calibration_protocol import (
    ACCEPTED_M3_CANDIDATE_SHA256,
    ACCEPTED_M8_AGENT_MANIFEST_SHA256,
    CALIBRATION_PROTOCOL_PATH,
    CALIBRATION_TASK_PATH,
    EXPECTED_CALIBRATION_BASE_COMMIT,
    EXPECTED_CALIBRATION_TASK_ID,
    EXPECTED_CALIBRATION_TASK_SHA256,
    EXPECTED_CONFIG_IDS,
    CalibrationProtocolIntegrityError,
    build_calibration_protocol,
    deterministic_protocol_json,
    load_agent_manifest,
    load_calibration_protocol,
    load_candidate_manifest,
    verify_calibration_protocol,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_SHA256 = "d3034417aae0f1c821a4fe6dfa522c5a412e13d60b591696a7682b153153bb5f"
PROTOCOL_BYTE_SHA256 = "5a70acae41ece3915e4b5e1f30b894212ba365a737864e940afdaf8ac52e0b36"


def checked_protocol() -> V13CalibrationProtocol:
    return load_calibration_protocol(PROJECT_ROOT)


def copy_protocol_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tasks" / "reliability").mkdir(parents=True)
    (root / "tasks" / "example").mkdir(parents=True)
    for relative in (
        "tasks/reliability/v1.3-candidate.json",
        "tasks/reliability/v1.3-agent-configurations.json",
        "tasks/reliability/v1.3-calibration-protocol.json",
        "tasks/example/task.yaml",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, target)
    return root


def test_checked_calibration_protocol_validates_and_matches_builder_output():
    protocol = checked_protocol()
    expected = build_calibration_protocol(PROJECT_ROOT)

    assert verify_calibration_protocol(protocol, PROJECT_ROOT) == protocol
    assert protocol == expected
    assert compute_v13_calibration_protocol_sha256(protocol) == PROTOCOL_SHA256
    assert deterministic_protocol_json(protocol) == (
        PROJECT_ROOT / CALIBRATION_PROTOCOL_PATH
    ).read_text(encoding="utf-8")
    assert hashlib.sha256(
        (PROJECT_ROOT / CALIBRATION_PROTOCOL_PATH).read_bytes()
    ).hexdigest() == PROTOCOL_BYTE_SHA256


def test_calibration_task_identity_is_exact_and_excluded_from_candidate():
    protocol = checked_protocol()
    task_path = PROJECT_ROOT / CALIBRATION_TASK_PATH
    candidate = load_candidate_manifest(PROJECT_ROOT)

    assert protocol.calibration_task_spec_path == "tasks/example/task.yaml"
    assert hashlib.sha256(task_path.read_bytes()).hexdigest() == (
        EXPECTED_CALIBRATION_TASK_SHA256
    )
    assert protocol.calibration_task_spec_sha256 == EXPECTED_CALIBRATION_TASK_SHA256
    assert protocol.calibration_task_id == EXPECTED_CALIBRATION_TASK_ID
    assert protocol.calibration_base_commit == EXPECTED_CALIBRATION_BASE_COMMIT
    assert EXPECTED_CALIBRATION_TASK_ID not in {task.task_id for task in candidate.tasks}
    assert compute_benchmark_candidate_sha256(candidate) == ACCEPTED_M3_CANDIDATE_SHA256


def test_ordered_config_set_matches_selected_m8_manifest():
    protocol = checked_protocol()
    manifest = load_agent_manifest(PROJECT_ROOT)

    assert protocol.m8_agent_manifest_sha256 == ACCEPTED_M8_AGENT_MANIFEST_SHA256
    assert compute_agent_configuration_manifest_sha256(manifest) == (
        ACCEPTED_M8_AGENT_MANIFEST_SHA256
    )
    assert protocol.ordered_agent_config_ids == EXPECTED_CONFIG_IDS
    assert tuple(configuration.config_id for configuration in manifest.configurations) == (
        EXPECTED_CONFIG_IDS
    )
    assert "claude_code" not in {
        configuration.toolchain.value for configuration in manifest.configurations
    }


def test_execution_shape_and_runtime_admission_rules_are_frozen():
    protocol = checked_protocol()

    assert protocol.evaluation_backend == "docker"
    assert protocol.runs_per_configuration == 1
    assert protocol.admitted_agent_statuses == (AgentRunStatus.COMPLETED,)
    assert protocol.evaluation_pass_required is False
    assert protocol.within_batch_retry_policy == "no_retry"
    assert protocol.all_configurations_required_for_batch_acceptance is True


def test_retry_remediation_and_evidence_retention_rules_are_frozen():
    protocol = checked_protocol()

    assert protocol.failed_batch_rerun_policy == (
        "new_batch_after_environment_only_remediation"
    )
    assert protocol.environment_only_remediation_required is True
    assert protocol.failed_batch_evidence_retention_required is True
    assert protocol.allowed_environment_remediation == (
        "authentication availability",
        "required frozen CLI installation/version",
        "Docker availability",
        "host/process/environment setup that does not change frozen study semantics",
    )
    assert "M8 Agent manifest" in protocol.forbidden_semantic_remediation
    assert "formal study design" in protocol.forbidden_semantic_remediation


def test_formal_study_contamination_boundary_is_frozen():
    protocol = checked_protocol()

    assert protocol.formal_benchmark_task_execution_forbidden is True
    assert protocol.formal_study_tuning_from_calibration_forbidden is True
    assert protocol.calibration_outcome_must_not_influence_task_selection is True
    assert protocol.calibration_outcome_must_not_influence_agent_selection is True
    assert protocol.calibration_outcome_must_not_influence_model_timeout_or_endpoint is True
    assert protocol.calibration_outcome_must_not_influence_prompt_or_retry_policy is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evaluation_backend", "host"),
        ("runs_per_configuration", 2),
        ("admitted_agent_statuses", ("completed", "timed_out")),
        ("evaluation_pass_required", True),
        ("within_batch_retry_policy", "retry_failed_slots"),
        ("failed_batch_rerun_policy", "rerun_failed_slots"),
        ("failed_batch_evidence_retention_required", False),
        ("formal_benchmark_task_execution_forbidden", False),
        ("formal_study_tuning_from_calibration_forbidden", False),
    ],
)
def test_invalid_protocol_rule_values_reject(field, value):
    data = checked_protocol().model_dump(mode="json")
    data[field] = value

    with pytest.raises(ValidationError):
        V13CalibrationProtocol.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("calibration_task_spec_sha256", "0" * 64),
        ("calibration_base_commit", "1" * 40),
        ("ordered_agent_config_ids", ("codex-gpt-5.5-relay",)),
        ("allowed_environment_remediation", ("Docker availability",)),
        ("forbidden_semantic_remediation", ("M8 Agent manifest",)),
    ],
)
def test_protocol_hash_changes_when_material_frozen_fields_change(field, value):
    baseline = checked_protocol()
    mutated = baseline.model_copy(update={field: value})

    assert compute_v13_calibration_protocol_sha256(mutated) != (
        compute_v13_calibration_protocol_sha256(baseline)
    )


def test_semantic_drift_fails_verification(tmp_path):
    root = copy_protocol_inputs(tmp_path)
    path = root / CALIBRATION_PROTOCOL_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["evaluation_pass_required"] = True
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CalibrationProtocolIntegrityError, match="Unable to load"):
        protocol = load_calibration_protocol(root)
        verify_calibration_protocol(protocol, root)


def test_valid_semantic_drift_fails_verification(tmp_path):
    root = copy_protocol_inputs(tmp_path)
    path = root / CALIBRATION_PROTOCOL_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["allowed_environment_remediation"] = ["Docker availability"]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    protocol = load_calibration_protocol(root)
    with pytest.raises(CalibrationProtocolIntegrityError, match="semantic mismatch"):
        verify_calibration_protocol(protocol, root)


def test_byte_only_serialization_drift_fails_verification(tmp_path):
    root = copy_protocol_inputs(tmp_path)
    path = root / CALIBRATION_PROTOCOL_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    protocol = load_calibration_protocol(root)
    with pytest.raises(CalibrationProtocolIntegrityError, match="byte serialization"):
        verify_calibration_protocol(protocol, root)


def test_builder_rejects_example_bug_in_candidate_task_set(tmp_path):
    root = copy_protocol_inputs(tmp_path)
    path = root / "tasks/reliability/v1.3-candidate.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["tasks"][0]["task_id"] = "example_bug"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CalibrationProtocolIntegrityError, match="M3 candidate SHA mismatch"):
        build_calibration_protocol(root)


def test_script_check_succeeds():
    result = subprocess.run(
        [".venv/bin/python", "scripts/v13_calibration_protocol.py", "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == f"calibration_protocol_sha256={PROTOCOL_SHA256}"
