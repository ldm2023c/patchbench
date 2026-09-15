"""Run the frozen Diagnosis Validation V1 suite with an injected provider."""

from enum import Enum
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from patchbench.application.diagnosis_execution import (
    DiagnosisExecutionError,
    execute_blind_diagnosis,
    execute_contrastive_diagnosis,
)
from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_suite import verify_diagnosis_validation_freeze
from patchbench.domain.diagnosis import DiagnosisEvidenceBundle, DiagnosisMode
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from patchbench.domain.diagnosis_validation_run import (
    DiagnosisValidationRunRecord,
    DiagnosisValidationRunSlot,
    DiagnosisValidationRunSlotResult,
)
from patchbench.providers.base import DiagnosisProvider
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


class DiagnosisValidationRunReason(str, Enum):
    INVALID_FREEZE = "invalid_freeze"
    RUN_ALREADY_EXISTS = "run_already_exists"
    INVALID_PLAN = "invalid_plan"


class DiagnosisValidationRunError(RuntimeError):
    def __init__(self, reason: DiagnosisValidationRunReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _bundle(root: Path, case_id: str, mode: DiagnosisMode) -> DiagnosisEvidenceBundle:
    name = "blind-bundle.json" if mode is DiagnosisMode.BLIND else "contrastive-bundle.json"
    try:
        return DiagnosisEvidenceBundle.model_validate_json(
            (root / "cases" / case_id / name).read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_FREEZE,
            f"{case_id} {mode.value} bundle is invalid",
        ) from error


def build_diagnosis_validation_run_plan(
    validation_root: Path,
) -> list[DiagnosisValidationRunSlot]:
    root = Path(validation_root)
    plan = []
    for case_id in SEMANTIC_CASE_IDS:
        for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE):
            bundle = _bundle(root, case_id, mode)
            plan.append(DiagnosisValidationRunSlot(
                case_id=case_id,
                mode=mode,
                frozen_bundle_sha256=bundle.bundle_sha256,
            ))
    return plan


def _pending_slots(plan: list[DiagnosisValidationRunSlot]) -> list[DiagnosisValidationRunSlotResult]:
    return [DiagnosisValidationRunSlotResult(
        **slot.model_dump(mode="json"),
        status="pending",
    ) for slot in plan]


def _write_ledger(path: Path, record: DiagnosisValidationRunRecord) -> None:
    path.write_bytes(_disk_json_bytes(record))


def _record(
    *,
    run_id: str,
    freeze_manifest_sha256: str,
    frozen_suite_sha256: str,
    provider: DiagnosisProvider,
    external_policy: DiagnosisExternalLLMPolicy,
    plan: list[DiagnosisValidationRunSlot],
    slots: list[DiagnosisValidationRunSlotResult],
) -> DiagnosisValidationRunRecord:
    return DiagnosisValidationRunRecord(
        run_id=run_id,
        freeze_manifest_sha256=freeze_manifest_sha256,
        frozen_suite_sha256=frozen_suite_sha256,
        provider_settings=provider.settings,
        external_policy=external_policy,
        plan=plan,
        slots=slots,
    )


def run_frozen_diagnosis_validation(
    *,
    validation_root: Path,
    candidate_root: Path,
    results_root: Path,
    run_id: str,
    provider: DiagnosisProvider,
    external_policy: DiagnosisExternalLLMPolicy,
) -> DiagnosisValidationRunRecord:
    """Execute the exact 13 x 2 frozen plan with one provider attempt per slot."""
    validation_root = Path(validation_root)
    candidate_root = Path(candidate_root)
    results_root = Path(results_root)
    try:
        manifest = verify_diagnosis_validation_freeze(validation_root, candidate_root)
    except Exception as error:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_FREEZE,
            "frozen validation suite failed verification",
        ) from error

    plan = build_diagnosis_validation_run_plan(validation_root)
    expected = [(case_id, mode) for case_id in SEMANTIC_CASE_IDS
                for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)]
    if [(slot.case_id, slot.mode) for slot in plan] != expected or len(plan) != 26:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_PLAN,
            "frozen execution plan differs from accepted V1 order",
        )

    run_root = results_root / "diagnosis-validation-v1" / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.RUN_ALREADY_EXISTS,
            f"run root already exists or cannot be created: {run_root}",
        ) from error

    slots = _pending_slots(plan)
    freeze_sha = hashlib.sha256((validation_root / "freeze-manifest.json").read_bytes()).hexdigest()
    record_path = run_root / "run.json"
    output_store = FilesystemArtifactStore(run_root)
    _write_ledger(record_path, _record(run_id=run_id, freeze_manifest_sha256=freeze_sha,
        frozen_suite_sha256=manifest.suite_sha256, provider=provider,
        external_policy=external_policy, plan=plan, slots=slots))

    for index, slot in enumerate(plan):
        bundle = _bundle(validation_root, slot.case_id, slot.mode)
        try:
            if slot.mode is DiagnosisMode.BLIND:
                result = execute_blind_diagnosis(
                    bundle,
                    provider=provider,
                    external_policy=external_policy,
                    artifact_store=output_store,
                )
            else:
                result = execute_contrastive_diagnosis(
                    bundle,
                    provider=provider,
                    external_policy=external_policy,
                    peer_artifact_store=FilesystemArtifactStore(
                        candidate_root / "_support" / slot.case_id / "results"),
                    output_artifact_store=output_store,
                )
            slots[index] = DiagnosisValidationRunSlotResult(
                **slot.model_dump(mode="json"),
                status="completed",
                diagnosis_id=result.diagnosis.diagnosis_id,
                execution_sha256=result.execution_record.execution_sha256,
            )
        except DiagnosisExecutionError as error:
            slots[index] = DiagnosisValidationRunSlotResult(
                **slot.model_dump(mode="json"),
                status="failed",
                failure_reason=error.reason.value,
            )
            final = _record(run_id=run_id, freeze_manifest_sha256=freeze_sha,
                frozen_suite_sha256=manifest.suite_sha256, provider=provider,
                external_policy=external_policy, plan=plan, slots=slots)
            _write_ledger(record_path, final)
            return final
        except ArtifactStoreError as error:
            slots[index] = DiagnosisValidationRunSlotResult(
                **slot.model_dump(mode="json"),
                status="failed",
                failure_reason="artifact_store_failed",
            )
            final = _record(run_id=run_id, freeze_manifest_sha256=freeze_sha,
                frozen_suite_sha256=manifest.suite_sha256, provider=provider,
                external_policy=external_policy, plan=plan, slots=slots)
            _write_ledger(record_path, final)
            return final
        _write_ledger(record_path, _record(run_id=run_id, freeze_manifest_sha256=freeze_sha,
            frozen_suite_sha256=manifest.suite_sha256, provider=provider,
            external_policy=external_policy, plan=plan, slots=slots))

    return DiagnosisValidationRunRecord.model_validate_json(record_path.read_bytes())
