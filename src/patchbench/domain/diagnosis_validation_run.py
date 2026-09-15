"""Frozen Diagnosis validation provider-run ledger contracts."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_execution import (
    DiagnosisExternalLLMPolicy,
    DiagnosisProviderSettings,
)
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex


SafeReason = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


class DiagnosisValidationRunSlot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    case_id: NonEmptyString
    mode: DiagnosisMode
    frozen_bundle_sha256: Sha256Hex


class DiagnosisValidationRunSlotResult(DiagnosisValidationRunSlot):
    status: Literal["pending", "completed", "failed"]
    diagnosis_id: NonEmptyString | None = None
    execution_sha256: Sha256Hex | None = None
    failure_reason: SafeReason | None = None


class DiagnosisValidationRunRecord(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    run_id: NonEmptyString
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    provider_settings: DiagnosisProviderSettings
    external_policy: DiagnosisExternalLLMPolicy
    plan: list[DiagnosisValidationRunSlot] = Field(min_length=26, max_length=26)
    slots: list[DiagnosisValidationRunSlotResult] = Field(min_length=26, max_length=26)
