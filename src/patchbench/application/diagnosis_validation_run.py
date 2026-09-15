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
from patchbench.domain.diagnosis import DiagnosisEvidenceBundle, DiagnosisMode, DiagnosisRoute
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
from patchbench.domain.diagnosis_gold_lock import DiagnosisGoldLockCase, DiagnosisGoldLockSuite
from patchbench.domain.diagnosis_validation_run import (
    DiagnosisValidationRunRecord,
    DiagnosisValidationRunSlot,
    DiagnosisValidationRunSlotResult,
)
from patchbench.providers.base import DiagnosisProvider
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


class DiagnosisValidationRunReason(str, Enum):
    INVALID_FREEZE = "invalid_freeze"
    INVALID_RUN_ID = "invalid_run_id"
    RUN_ALREADY_EXISTS = "run_already_exists"
    INVALID_PLAN = "invalid_plan"


class DiagnosisValidationRunError(RuntimeError):
    def __init__(self, reason: DiagnosisValidationRunReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _disk_json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _parse_model(model, path: Path, label: str):
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_FREEZE,
            f"{label} is invalid",
        ) from error


def _bundle(root: Path, path: str, case_id: str, mode: DiagnosisMode) -> DiagnosisEvidenceBundle:
    bundle = _parse_model(DiagnosisEvidenceBundle, root / path, f"{case_id} {mode.value} bundle")
    if bundle.mode is not mode or bundle.bundle_sha256 is None:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_FREEZE,
            f"{case_id} {mode.value} bundle identity is invalid",
        )
    return bundle


def _suite_cases(root: Path) -> list[DiagnosisGoldLockCase]:
    suite = _parse_model(DiagnosisGoldLockSuite, root / "suite.json", "frozen suite")
    return list(suite.cases)


def build_diagnosis_validation_run_plan(
    validation_root: Path,
) -> list[DiagnosisValidationRunSlot]:
    root = Path(validation_root)
    semantic_cases = [
        case for case in _suite_cases(root)
        if case.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS
    ]
    if len(semantic_cases) != 13:
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_PLAN,
            "frozen suite must declare exactly 13 semantic diagnosis cases",
        )

    plan = []
    for case in semantic_cases:
        contrastive_path = f"cases/{case.case_id}/contrastive-bundle.json"
        contrastive_bundle = _bundle(root, contrastive_path, case.case_id, DiagnosisMode.CONTRASTIVE)
        bundle_specs = (
            (DiagnosisMode.BLIND, case.blind_bundle_path, case.blind_bundle_sha256),
            (DiagnosisMode.CONTRASTIVE, contrastive_path, contrastive_bundle.bundle_sha256),
        )
        for mode, bundle_path, expected_sha in bundle_specs:
            if bundle_path is None or expected_sha is None:
                raise DiagnosisValidationRunError(
                    DiagnosisValidationRunReason.INVALID_PLAN,
                    f"{case.case_id} is missing {mode.value} bundle identity",
                )
            bundle = _bundle(root, bundle_path, case.case_id, mode)
            if bundle.bundle_sha256 != expected_sha:
                raise DiagnosisValidationRunError(
                    DiagnosisValidationRunReason.INVALID_PLAN,
                    f"{case.case_id} {mode.value} bundle SHA differs from frozen suite case",
                )
            plan.append(DiagnosisValidationRunSlot(
                case_id=case.case_id,
                mode=mode,
                frozen_bundle_path=bundle_path,
                frozen_bundle_sha256=expected_sha,
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


def _safe_run_root(results_root: Path, run_id: str) -> Path:
    if (not isinstance(run_id, str) or not run_id or run_id in (".", "..")
            or run_id != run_id.strip() or run_id.startswith("/")
            or "/" in run_id or "\\" in run_id
            or any(ord(char) < 32 or ord(char) == 127 for char in run_id)):
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_RUN_ID,
            "run_id must be a safe direct-child identifier",
        )
    namespace = results_root / "diagnosis-validation-v1"
    run_root = namespace / run_id
    if run_root.resolve(strict=False).parent != namespace.resolve(strict=False):
        raise DiagnosisValidationRunError(
            DiagnosisValidationRunReason.INVALID_RUN_ID,
            "run_id must resolve to one direct child of the validation run namespace",
        )
    return run_root


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

    run_root = _safe_run_root(results_root, run_id)
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
        bundle = _bundle(validation_root, slot.frozen_bundle_path, slot.case_id, slot.mode)
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
