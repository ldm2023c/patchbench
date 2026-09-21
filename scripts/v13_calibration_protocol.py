"""Build and verify the PatchBench V1.3 calibration protocol freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.config.task_loader import TaskLoadError, load_task
from patchbench.domain import (
    AgentConfigurationManifest,
    V13CalibrationProtocol,
    compute_agent_configuration_manifest_sha256,
    compute_v13_calibration_protocol_sha256,
)
from patchbench.domain.benchmark import (
    BenchmarkCandidateManifest,
    compute_benchmark_candidate_sha256,
)


CALIBRATION_PROTOCOL_PATH = Path("tasks/reliability/v1.3-calibration-protocol.json")
CANDIDATE_PATH = Path("tasks/reliability/v1.3-candidate.json")
AGENT_MANIFEST_PATH = Path("tasks/reliability/v1.3-agent-configurations.json")
CALIBRATION_TASK_PATH = Path("tasks/example/task.yaml")

ACCEPTED_M3_CANDIDATE_SHA256 = "a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043"
ACCEPTED_M8_AGENT_MANIFEST_SHA256 = "6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965"
EXPECTED_CALIBRATION_TASK_SHA256 = "ed6ade930729082332dc0101f98332c20d844698e33d7a07f9052d43ea73b609"
EXPECTED_CALIBRATION_TASK_ID = "example_bug"
EXPECTED_CALIBRATION_BASE_COMMIT = "4ed891e6144bdb78941160726ada95fa7a710f3c"
EXPECTED_CONFIG_IDS = (
    "codex-gpt-5.5-relay",
    "cursor-claude-4.6-sonnet-medium",
    "grok-build-grok-4.5-relay",
)


class CalibrationProtocolIntegrityError(RuntimeError):
    """Checked-in calibration protocol does not match frozen M10A truth."""


def _load_json_model(path: Path, model_type, category: str):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CalibrationProtocolIntegrityError(
            f"Unable to load {category} '{path}': {error}"
        ) from error


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise CalibrationProtocolIntegrityError(
            f"Unable to hash '{path}': {error}"
        ) from error


def load_candidate_manifest(
    project_root: Path = PROJECT_ROOT,
) -> BenchmarkCandidateManifest:
    return _load_json_model(
        project_root / CANDIDATE_PATH,
        BenchmarkCandidateManifest,
        "V1.3 candidate manifest",
    )


def load_agent_manifest(
    project_root: Path = PROJECT_ROOT,
) -> AgentConfigurationManifest:
    return _load_json_model(
        project_root / AGENT_MANIFEST_PATH,
        AgentConfigurationManifest,
        "V1.3 Agent manifest",
    )


def load_calibration_protocol(
    project_root: Path = PROJECT_ROOT,
) -> V13CalibrationProtocol:
    return _load_json_model(
        project_root / CALIBRATION_PROTOCOL_PATH,
        V13CalibrationProtocol,
        "V1.3 calibration protocol",
    )


def build_calibration_protocol(
    project_root: Path = PROJECT_ROOT,
) -> V13CalibrationProtocol:
    candidate = load_candidate_manifest(project_root)
    candidate_sha = compute_benchmark_candidate_sha256(candidate)
    if candidate_sha != ACCEPTED_M3_CANDIDATE_SHA256:
        raise CalibrationProtocolIntegrityError(
            "M3 candidate SHA mismatch: expected "
            f"{ACCEPTED_M3_CANDIDATE_SHA256}, found {candidate_sha}"
        )
    formal_task_ids = {task.task_id for task in candidate.tasks}
    if EXPECTED_CALIBRATION_TASK_ID in formal_task_ids:
        raise CalibrationProtocolIntegrityError(
            "calibration task must not be part of the M3 candidate task set"
        )

    agent_manifest = load_agent_manifest(project_root)
    agent_manifest_sha = compute_agent_configuration_manifest_sha256(agent_manifest)
    if agent_manifest_sha != ACCEPTED_M8_AGENT_MANIFEST_SHA256:
        raise CalibrationProtocolIntegrityError(
            "M8 Agent manifest SHA mismatch: expected "
            f"{ACCEPTED_M8_AGENT_MANIFEST_SHA256}, found {agent_manifest_sha}"
        )
    config_ids = tuple(
        configuration.config_id for configuration in agent_manifest.configurations
    )
    if config_ids != EXPECTED_CONFIG_IDS:
        raise CalibrationProtocolIntegrityError(
            "selected calibration config IDs do not match frozen M8 manifest order"
        )

    task_path = project_root / CALIBRATION_TASK_PATH
    task_sha = _sha256_file(task_path)
    if task_sha != EXPECTED_CALIBRATION_TASK_SHA256:
        raise CalibrationProtocolIntegrityError(
            "calibration TaskSpec SHA mismatch: expected "
            f"{EXPECTED_CALIBRATION_TASK_SHA256}, found {task_sha}"
        )
    try:
        task = load_task(task_path)
    except TaskLoadError as error:
        raise CalibrationProtocolIntegrityError(
            f"calibration TaskSpec failed to load: {error}"
        ) from error
    if task.id != EXPECTED_CALIBRATION_TASK_ID:
        raise CalibrationProtocolIntegrityError(
            "calibration TaskSpec ID mismatch: expected "
            f"{EXPECTED_CALIBRATION_TASK_ID}, found {task.id}"
        )
    if task.repository.base_commit != EXPECTED_CALIBRATION_BASE_COMMIT:
        raise CalibrationProtocolIntegrityError(
            "calibration TaskSpec base commit mismatch: expected "
            f"{EXPECTED_CALIBRATION_BASE_COMMIT}, found {task.repository.base_commit}"
        )

    return V13CalibrationProtocol(
        schema_version=1,
        protocol_id="patchbench-v1.3-calibration-protocol",
        m3_candidate_sha256=candidate_sha,
        m8_agent_manifest_sha256=agent_manifest_sha,
        calibration_task_spec_path=CALIBRATION_TASK_PATH.as_posix(),
        calibration_task_spec_sha256=task_sha,
        calibration_task_id=task.id,
        calibration_base_commit=task.repository.base_commit,
        evaluation_backend="docker",
        ordered_agent_config_ids=config_ids,
        runs_per_configuration=1,
        admitted_agent_statuses=("completed",),
        evaluation_pass_required=False,
        within_batch_retry_policy="no_retry",
        failed_batch_rerun_policy="new_batch_after_environment_only_remediation",
        environment_only_remediation_required=True,
        failed_batch_evidence_retention_required=True,
        all_configurations_required_for_batch_acceptance=True,
        formal_benchmark_task_execution_forbidden=True,
        formal_study_tuning_from_calibration_forbidden=True,
        calibration_outcome_must_not_influence_task_selection=True,
        calibration_outcome_must_not_influence_agent_selection=True,
        calibration_outcome_must_not_influence_model_timeout_or_endpoint=True,
        calibration_outcome_must_not_influence_prompt_or_retry_policy=True,
        allowed_environment_remediation=(
            "authentication availability",
            "required frozen CLI installation/version",
            "Docker availability",
            "host/process/environment setup that does not change frozen study semantics",
        ),
        forbidden_semantic_remediation=(
            "M3 candidate tasks",
            "M4 execution policy",
            "M8 Agent manifest",
            "model names",
            "Agent timeout",
            "provider endpoint / relay route",
            "Grok context window",
            "M9 trusted execution semantics",
            "calibration task or prompt",
            "formal study design",
        ),
    )


def deterministic_protocol_json(protocol: V13CalibrationProtocol) -> str:
    return json.dumps(
        protocol.model_dump(mode="json"), indent=2, ensure_ascii=False
    ) + "\n"


def write_calibration_protocol(
    protocol: V13CalibrationProtocol,
    project_root: Path = PROJECT_ROOT,
) -> None:
    (project_root / CALIBRATION_PROTOCOL_PATH).write_text(
        deterministic_protocol_json(protocol), encoding="utf-8"
    )


def verify_calibration_protocol(
    protocol: V13CalibrationProtocol,
    project_root: Path = PROJECT_ROOT,
) -> V13CalibrationProtocol:
    expected = build_calibration_protocol(project_root)
    if protocol != expected:
        raise CalibrationProtocolIntegrityError(
            "calibration protocol semantic mismatch"
        )
    path = project_root / CALIBRATION_PROTOCOL_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CalibrationProtocolIntegrityError(
            f"Unable to read checked calibration protocol bytes: {error}"
        ) from error
    if raw != deterministic_protocol_json(expected):
        raise CalibrationProtocolIntegrityError(
            "calibration protocol JSON byte serialization mismatch"
        )
    return protocol


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify checked protocol")
    mode.add_argument("--write", action="store_true", help="rewrite checked protocol")
    arguments = parser.parse_args()
    try:
        if arguments.write:
            protocol = build_calibration_protocol()
            write_calibration_protocol(protocol)
        else:
            protocol = load_calibration_protocol()
            verify_calibration_protocol(protocol)
    except CalibrationProtocolIntegrityError as error:
        raise SystemExit(f"Calibration protocol integrity failure: {error}") from error
    print(
        "calibration_protocol_sha256="
        f"{compute_v13_calibration_protocol_sha256(protocol)}"
    )


if __name__ == "__main__":
    main()
