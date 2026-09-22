"""Build and verify the compact PatchBench V1.3 calibration evidence freeze."""

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

from patchbench.agents.base import AgentRunStatus
from patchbench.application.v13_agent_execution import resolve_v13_agent_config
from patchbench.application.v13_calibration import (
    ACCEPTED_M3_CANDIDATE_SHA256,
    ACCEPTED_M8_AGENT_MANIFEST_SHA256,
    ACCEPTED_PROTOCOL_SHA256,
    verify_v13_calibration_protocol,
)
from patchbench.domain import CalibrationBatchStatus, CalibrationSlotStatus
from patchbench.domain.calibration_evidence import (
    V13CalibrationEvidenceFreeze,
    V13CalibrationEvidenceSlot,
    compute_experiment_semantic_sha256,
    compute_run_semantic_sha256,
    compute_v13_calibration_batch_sha256,
    compute_v13_calibration_evidence_freeze_sha256,
)
from patchbench.domain.calibration_run import V13CalibrationBatch
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


FREEZE_PATH = Path("evidence/v1.3/calibration/calibration-001-freeze.json")
DEFAULT_SOURCE = Path("results/v1.3-calibration/calibration-001")
ACCEPTED_BATCH_ID = "calibration-001"
ACCEPTED_FREEZE_SHA256 = "5f93900dde3fdb15a5e0b7cf8663658ce40682d0f8bdd1a324ed4081e6e0710b"
ACCEPTED_FREEZE_BYTE_SHA256 = "e34d58b9f367c19e214db787b9cfa0ebe1ce53a98a4d6d41906d85a85efdf2d8"


class CalibrationEvidenceIntegrityError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise CalibrationEvidenceIntegrityError(f"unable to read {label}") from error


def _load_batch(source: Path) -> tuple[V13CalibrationBatch, bytes]:
    raw = _read_bytes(source / "batch.json", "source batch ledger")
    try:
        return V13CalibrationBatch.model_validate_json(raw), raw
    except ValidationError as error:
        raise CalibrationEvidenceIntegrityError("invalid source batch ledger") from error


def build_calibration_evidence_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13CalibrationEvidenceFreeze:
    source = Path(source_results).resolve()
    root = Path(project_root).resolve()
    if source.name != ACCEPTED_BATCH_ID or not source.is_dir():
        raise CalibrationEvidenceIntegrityError("source must be calibration-001")
    try:
        sibling_batches = sorted(
            path.name for path in source.parent.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
    except OSError as error:
        raise CalibrationEvidenceIntegrityError("unable to inspect calibration namespace") from error
    if sibling_batches != [ACCEPTED_BATCH_ID]:
        raise CalibrationEvidenceIntegrityError("later or extra calibration batch exists")

    verified = verify_v13_calibration_protocol(root)
    batch, batch_bytes = _load_batch(source)
    protocol = verified.protocol
    if (batch.batch_id != ACCEPTED_BATCH_ID
            or batch.status is not CalibrationBatchStatus.ACCEPTED
            or batch.previous_batch_id is not None
            or batch.environment_remediation is not None
            or batch.protocol_sha256 != ACCEPTED_PROTOCOL_SHA256
            or batch.m3_candidate_sha256 != ACCEPTED_M3_CANDIDATE_SHA256
            or batch.m8_agent_manifest_sha256 != ACCEPTED_M8_AGENT_MANIFEST_SHA256
            or batch.calibration_task_id != "example_bug"
            or batch.ordered_agent_config_ids != protocol.ordered_agent_config_ids
            or len(batch.slots) != 3):
        raise CalibrationEvidenceIntegrityError("source batch identity/status mismatch")

    store = FilesystemArtifactStore(source / "artifacts")
    frozen_slots = []
    for slot in batch.slots:
        if (slot.status is not CalibrationSlotStatus.RUNTIME_ADMITTED
                or slot.agent_status is not AgentRunStatus.COMPLETED
                or slot.experiment_id is None or slot.run_id is None
                or slot.identity_binding is None):
            raise CalibrationEvidenceIntegrityError("source slot is not runtime-admitted")
        plan = resolve_v13_agent_config(
            slot.config_id, evaluation_backend="docker", project_root=root
        )
        if slot.identity_binding != plan.identity_binding:
            raise CalibrationEvidenceIntegrityError("source slot M8/M9 binding mismatch")
        try:
            run = store.load_run_record(slot.run_id)
            experiment = store.load_experiment_record(slot.experiment_id)
        except ArtifactStoreError as error:
            raise CalibrationEvidenceIntegrityError("missing or invalid Run/Experiment") from error
        expected = plan.experiment_configuration
        if (experiment.experiment_id != slot.experiment_id
                or experiment.task_id != "example_bug"
                or experiment.requested_runs != 1
                or experiment.run_ids != [slot.run_id]
                or experiment.configuration != expected
                or run.run_id != slot.run_id
                or run.task_id != "example_bug"
                or run.agent.status is not AgentRunStatus.COMPLETED
                or run.agent.identity_binding != slot.identity_binding
                or run.agent.name != expected.agent_name
                or run.agent.requested_model != expected.requested_model
                or run.agent.timeout_seconds != expected.agent_timeout_seconds
                or run.evaluation_passed != slot.evaluation_passed
                or run.provenance is None
                or run.provenance.evaluation_backend != "docker"
                or run.provenance.base_commit_used != protocol.calibration_base_commit
                or run.patch_summary is None
                or run.evaluation_evidence is None):
            raise CalibrationEvidenceIntegrityError("Run/Experiment linkage mismatch")

        run_root = source / "artifacts" / slot.run_id
        prompt = _read_bytes(run_root / "prompt.txt", "prompt evidence")
        stdout = _read_bytes(run_root / "agent.log", "Agent stdout evidence")
        stderr = _read_bytes(run_root / "agent.stderr.log", "Agent stderr evidence")
        test_log = _read_bytes(run_root / "test.log", "test-log evidence")
        patch = _read_bytes(run_root / "patch.diff", "patch evidence")
        patch_sha = _sha256_bytes(patch)
        test_sha = _sha256_bytes(test_log)
        if patch_sha != run.patch_summary.patch_sha256:
            raise CalibrationEvidenceIntegrityError("raw patch hash mismatch")
        if test_sha != run.evaluation_evidence.test_log_sha256:
            raise CalibrationEvidenceIntegrityError("raw test-log hash mismatch")
        frozen_slots.append(V13CalibrationEvidenceSlot(
            config_id=slot.config_id,
            experiment_id=slot.experiment_id,
            run_id=slot.run_id,
            agent_status=slot.agent_status,
            evaluation_passed=slot.evaluation_passed,
            identity_binding=slot.identity_binding,
            run_semantic_sha256=compute_run_semantic_sha256(run),
            experiment_semantic_sha256=compute_experiment_semantic_sha256(experiment),
            prompt_sha256=_sha256_bytes(prompt),
            agent_stdout_sha256=_sha256_bytes(stdout),
            agent_stderr_sha256=_sha256_bytes(stderr),
            test_log_sha256=test_sha,
            patch_sha256=patch_sha,
        ))
    return V13CalibrationEvidenceFreeze(
        freeze_id="patchbench-v1.3-calibration-001",
        source_batch_id=batch.batch_id,
        source_batch_status=batch.status,
        source_batch_json_sha256=_sha256_bytes(batch_bytes),
        source_batch_semantic_sha256=compute_v13_calibration_batch_sha256(batch),
        calibration_protocol_sha256=batch.protocol_sha256,
        m3_candidate_sha256=batch.m3_candidate_sha256,
        m8_agent_manifest_sha256=batch.m8_agent_manifest_sha256,
        calibration_task_id=batch.calibration_task_id,
        ordered_agent_config_ids=batch.ordered_agent_config_ids,
        slots=tuple(frozen_slots),
    )


def deterministic_json(freeze: V13CalibrationEvidenceFreeze) -> str:
    return json.dumps(freeze.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_checked_freeze(project_root: Path = PROJECT_ROOT) -> V13CalibrationEvidenceFreeze:
    try:
        return V13CalibrationEvidenceFreeze.model_validate_json(
            (project_root / FREEZE_PATH).read_bytes()
        )
    except (OSError, ValidationError) as error:
        raise CalibrationEvidenceIntegrityError("invalid checked calibration freeze") from error


def verify_checked_freeze(project_root: Path = PROJECT_ROOT) -> V13CalibrationEvidenceFreeze:
    path = project_root / FREEZE_PATH
    freeze = load_checked_freeze(project_root)
    semantic_sha = compute_v13_calibration_evidence_freeze_sha256(freeze)
    byte_sha = _sha256_bytes(_read_bytes(path, "checked calibration freeze"))
    if semantic_sha != ACCEPTED_FREEZE_SHA256:
        raise CalibrationEvidenceIntegrityError("calibration freeze semantic SHA mismatch")
    if byte_sha != ACCEPTED_FREEZE_BYTE_SHA256:
        raise CalibrationEvidenceIntegrityError("calibration freeze artifact byte SHA mismatch")
    if (freeze.calibration_protocol_sha256 != ACCEPTED_PROTOCOL_SHA256
            or freeze.m3_candidate_sha256 != ACCEPTED_M3_CANDIDATE_SHA256
            or freeze.m8_agent_manifest_sha256 != ACCEPTED_M8_AGENT_MANIFEST_SHA256):
        raise CalibrationEvidenceIntegrityError("calibration freeze frozen-link mismatch")
    return freeze


def verify_source_against_checked_freeze(
    source_results: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> V13CalibrationEvidenceFreeze:
    freeze = verify_checked_freeze(project_root)
    if freeze != build_calibration_evidence_freeze(
        source_results, project_root=project_root
    ):
        raise CalibrationEvidenceIntegrityError("source evidence differs from freeze")
    return freeze


def write_freeze(freeze: V13CalibrationEvidenceFreeze, project_root: Path) -> None:
    path = project_root / FREEZE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deterministic_json(freeze), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-source", action="store_true")
    parser.add_argument("--source-results", type=Path, default=PROJECT_ROOT / DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        if args.write:
            freeze = build_calibration_evidence_freeze(args.source_results)
            write_freeze(freeze, PROJECT_ROOT)
        elif args.check_source:
            freeze = verify_source_against_checked_freeze(args.source_results)
        else:
            freeze = verify_checked_freeze()
    except CalibrationEvidenceIntegrityError as error:
        raise SystemExit(f"Calibration evidence integrity failure: {error}") from None
    print(f"calibration_evidence_freeze_sha256={compute_v13_calibration_evidence_freeze_sha256(freeze)}")


if __name__ == "__main__":
    main()
