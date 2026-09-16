"""Collect explicitly selected successful Diagnosis validation shards."""

from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Mapping

from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_suite import verify_diagnosis_validation_freeze
from patchbench.application.diagnosis_validation_run import build_diagnosis_validation_run_plan
from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_validation_collection import (
    DiagnosisValidationCollectedCase,
    DiagnosisValidationCollectedSlot,
    DiagnosisValidationCollection,
    compute_diagnosis_validation_collection_sha256,
)
from patchbench.domain.diagnosis_validation_run import DiagnosisValidationRunRecord
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore


class DiagnosisValidationCollectionReason(str, Enum):
    INVALID_COLLECTION_ID = "invalid_collection_id"
    INVALID_SELECTION = "invalid_selection"
    MISSING_SELECTED_RUN = "missing_selected_run"
    INVALID_RUN_LEDGER = "invalid_run_ledger"
    RUN_CASE_MISMATCH = "run_case_mismatch"
    INCOMPLETE_SHARD = "incomplete_shard"
    FROZEN_IDENTITY_MISMATCH = "frozen_identity_mismatch"
    PROVIDER_CONFIGURATION_MISMATCH = "provider_configuration_mismatch"
    EXTERNAL_POLICY_MISMATCH = "external_policy_mismatch"
    FROZEN_BUNDLE_PLAN_MISMATCH = "frozen_bundle_plan_mismatch"
    DIAGNOSIS_ARTIFACT_MISMATCH = "diagnosis_artifact_mismatch"
    COLLECTION_ALREADY_EXISTS = "collection_already_exists"


class DiagnosisValidationCollectionError(RuntimeError):
    def __init__(self, reason: DiagnosisValidationCollectionReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _disk_json_bytes(value) -> bytes:
    return json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _safe_direct_child(value: str, reason: DiagnosisValidationCollectionReason) -> str:
    if (not isinstance(value, str) or not value or value in (".", "..")
            or value != value.strip() or value.startswith("/")
            or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise DiagnosisValidationCollectionError(reason, "unsafe direct-child identifier")
    return value


def parse_case_selection(text: str) -> tuple[str, str]:
    if "=" not in text or text.count("=") != 1:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_SELECTION,
            "selection must use case_id=run_id syntax",
        )
    case_id, run_id = text.split("=", 1)
    if not case_id or not run_id:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_SELECTION,
            "selection case_id and run_id must be non-empty",
        )
    _safe_direct_child(run_id, DiagnosisValidationCollectionReason.INVALID_SELECTION)
    return case_id, run_id


def _collection_root(results_root: Path, collection_id: str) -> Path:
    _safe_direct_child(collection_id, DiagnosisValidationCollectionReason.INVALID_COLLECTION_ID)
    namespace = Path(results_root) / "diagnosis-validation-v1" / "collections"
    root = namespace / collection_id
    if root.resolve(strict=False).parent != namespace.resolve(strict=False):
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_COLLECTION_ID,
            "collection_id must resolve to one direct child of collections namespace",
        )
    return root


def _load_run_record(run_root: Path, run_id: str) -> DiagnosisValidationRunRecord:
    path = run_root / "run.json"
    try:
        record = DiagnosisValidationRunRecord.model_validate_json(path.read_bytes())
    except FileNotFoundError as error:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.MISSING_SELECTED_RUN,
            f"missing selected run: {run_id}",
        ) from error
    except (OSError, UnicodeError, ValidationError) as error:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_RUN_LEDGER,
            f"invalid selected run ledger: {run_id}",
        ) from error
    if record.run_id != run_id:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_RUN_LEDGER,
            "run ledger ID differs from explicit selection",
        )
    return record


def _completed_slot(record: DiagnosisValidationRunRecord, index: int, mode: DiagnosisMode):
    slot = record.slots[index]
    plan = record.plan[index]
    if (slot.mode is not mode or plan.mode is not mode or slot.case_id != plan.case_id
            or slot.status != "completed" or slot.failure_reason is not None
            or slot.diagnosis_id is None or slot.execution_sha256 is None):
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INCOMPLETE_SHARD,
            "selected run must contain completed Blind and Contrastive slots",
        )
    return slot


def _verify_execution_artifact(run_root: Path, slot, provider_settings, external_policy):
    try:
        bundle, diagnosis, audit, execution = FilesystemArtifactStore(run_root).load_diagnosis_execution_artifacts(slot.diagnosis_id)
    except ArtifactStoreError as error:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "selected Diagnosis execution artifact failed integrity validation",
        ) from error
    if (diagnosis.diagnosis_id != slot.diagnosis_id
            or execution.execution_sha256 != slot.execution_sha256
            or execution.diagnosis_id != slot.diagnosis_id
            or bundle.bundle_sha256 != slot.frozen_bundle_sha256
            or bundle.mode is not slot.mode):
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "selected Diagnosis execution artifact differs from run ledger",
        )
    provider = execution.provider
    if (provider.provider_name != provider_settings.provider_name
            or provider.api_surface != provider_settings.api_surface
            or provider.requested_model != provider_settings.requested_model
            or provider.reasoning_effort != provider_settings.reasoning_effort
            or provider.max_output_tokens != provider_settings.max_output_tokens
            or provider.timeout_seconds != provider_settings.timeout_seconds
            or provider.store_requested != provider_settings.store_requested
            or provider.tool_choice != provider_settings.tool_choice
            or provider.truncation != provider_settings.truncation
            or provider.max_retries != provider_settings.max_retries):
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "execution provider settings differ from run ledger",
        )
    if provider.max_provider_input_bytes != external_policy.max_provider_input_bytes:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.DIAGNOSIS_ARTIFACT_MISMATCH,
            "execution byte policy differs from run ledger",
        )


def collect_diagnosis_validation_shards(
    *,
    validation_root: Path,
    candidate_root: Path,
    results_root: Path,
    collection_id: str,
    selections: Mapping[str, str],
) -> DiagnosisValidationCollection:
    manifest = verify_diagnosis_validation_freeze(Path(validation_root), Path(candidate_root))
    freeze_sha = hashlib.sha256((Path(validation_root) / "freeze-manifest.json").read_bytes()).hexdigest()
    expected_cases = list(SEMANTIC_CASE_IDS)
    if set(selections) != set(expected_cases) or len(selections) != 13:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_SELECTION,
            "selection must contain exactly every accepted semantic case",
        )
    if len(set(selections.values())) != len(selections):
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.INVALID_SELECTION,
            "selected run IDs must be unique",
        )
    for run_id in selections.values():
        _safe_direct_child(run_id, DiagnosisValidationCollectionReason.INVALID_SELECTION)

    collection_root = _collection_root(Path(results_root), collection_id)
    if collection_root.exists():
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.COLLECTION_ALREADY_EXISTS,
            "collection directory already exists",
        )

    canonical_plan = build_diagnosis_validation_run_plan(Path(validation_root))
    plan_by_case = {case_id: canonical_plan[index * 2:index * 2 + 2]
                    for index, case_id in enumerate(expected_cases)}
    baseline_provider = None
    baseline_policy = None
    cases = []
    for case_id in expected_cases:
        run_id = selections[case_id]
        run_root = Path(results_root) / "diagnosis-validation-v1" / run_id
        record = _load_run_record(run_root, run_id)
        if record.selected_case_ids != [case_id] or len(record.plan) != 2 or len(record.slots) != 2:
            raise DiagnosisValidationCollectionError(
                DiagnosisValidationCollectionReason.RUN_CASE_MISMATCH,
                "selected run must be a single-case shard for the selected case",
            )
        if record.freeze_manifest_sha256 != freeze_sha or record.frozen_suite_sha256 != manifest.suite_sha256:
            raise DiagnosisValidationCollectionError(
                DiagnosisValidationCollectionReason.FROZEN_IDENTITY_MISMATCH,
                "selected run frozen identity differs from current verified suite",
            )
        if baseline_provider is None:
            baseline_provider = record.provider_settings
            baseline_policy = record.external_policy
        elif record.provider_settings != baseline_provider:
            raise DiagnosisValidationCollectionError(
                DiagnosisValidationCollectionReason.PROVIDER_CONFIGURATION_MISMATCH,
                "selected run provider settings differ",
            )
        elif record.external_policy != baseline_policy:
            raise DiagnosisValidationCollectionError(
                DiagnosisValidationCollectionReason.EXTERNAL_POLICY_MISMATCH,
                "selected run external policy differs",
            )
        expected_pair = plan_by_case[case_id]
        if [(slot.case_id, slot.mode, slot.frozen_bundle_sha256) for slot in record.plan] != [
            (slot.case_id, slot.mode, slot.frozen_bundle_sha256) for slot in expected_pair
        ]:
            raise DiagnosisValidationCollectionError(
                DiagnosisValidationCollectionReason.FROZEN_BUNDLE_PLAN_MISMATCH,
                "selected run plan differs from canonical frozen plan",
            )
        blind = _completed_slot(record, 0, DiagnosisMode.BLIND)
        contrastive = _completed_slot(record, 1, DiagnosisMode.CONTRASTIVE)
        _verify_execution_artifact(run_root, blind, record.provider_settings, record.external_policy)
        _verify_execution_artifact(run_root, contrastive, record.provider_settings, record.external_policy)
        cases.append(DiagnosisValidationCollectedCase(
            case_id=case_id,
            run_id=run_id,
            blind=DiagnosisValidationCollectedSlot(
                mode=DiagnosisMode.BLIND,
                diagnosis_id=blind.diagnosis_id,
                execution_sha256=blind.execution_sha256,
                frozen_bundle_sha256=blind.frozen_bundle_sha256,
            ),
            contrastive=DiagnosisValidationCollectedSlot(
                mode=DiagnosisMode.CONTRASTIVE,
                diagnosis_id=contrastive.diagnosis_id,
                execution_sha256=contrastive.execution_sha256,
                frozen_bundle_sha256=contrastive.frozen_bundle_sha256,
            ),
        ))

    collection = DiagnosisValidationCollection(
        collection_id=collection_id,
        freeze_manifest_sha256=freeze_sha,
        frozen_suite_sha256=manifest.suite_sha256,
        provider_settings=baseline_provider,
        external_policy=baseline_policy,
        cases=cases,
    )
    collection = DiagnosisValidationCollection.model_validate(
        collection.model_dump(mode="json") | {
            "collection_sha256": compute_diagnosis_validation_collection_sha256(collection)
        }
    )
    try:
        collection_root.mkdir(parents=True, exist_ok=False)
        (collection_root / "collection.json").write_bytes(_disk_json_bytes(collection))
    except OSError as error:
        raise DiagnosisValidationCollectionError(
            DiagnosisValidationCollectionReason.COLLECTION_ALREADY_EXISTS,
            "unable to create collection directory or write collection",
        ) from error
    return collection
