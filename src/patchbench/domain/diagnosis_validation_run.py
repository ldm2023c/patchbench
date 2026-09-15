"""Frozen Diagnosis validation provider-run ledger contracts."""

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

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
    frozen_bundle_path: NonEmptyString
    frozen_bundle_sha256: Sha256Hex


class DiagnosisValidationRunSlotResult(DiagnosisValidationRunSlot):
    status: Literal["pending", "completed", "failed"]
    diagnosis_id: NonEmptyString | None = None
    execution_sha256: Sha256Hex | None = None
    failure_reason: SafeReason | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status == "pending":
            if any(value is not None for value in (
                self.diagnosis_id, self.execution_sha256, self.failure_reason,
            )):
                raise ValueError("pending slot must not contain result fields")
        elif self.status == "completed":
            if self.diagnosis_id is None or self.execution_sha256 is None:
                raise ValueError("completed slot requires diagnosis_id and execution_sha256")
            if self.failure_reason is not None:
                raise ValueError("completed slot must not contain failure_reason")
        elif self.status == "failed":
            if self.failure_reason is None:
                raise ValueError("failed slot requires failure_reason")
            if self.diagnosis_id is not None or self.execution_sha256 is not None:
                raise ValueError("failed slot must not contain success fields")
        return self


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

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if (not value or value in (".", "..") or value != value.strip()
                or value.startswith("/") or "/" in value or "\\" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("run_id must be a safe direct-child identifier")
        return value

    @model_validator(mode="after")
    def validate_plan_slots(self) -> Self:
        if len(self.plan) != 26 or len(self.slots) != 26:
            raise ValueError("diagnosis validation run requires exactly 26 slots")
        for planned, actual in zip(self.plan, self.slots, strict=True):
            if (planned.case_id != actual.case_id or planned.mode is not actual.mode
                    or planned.frozen_bundle_path != actual.frozen_bundle_path
                    or planned.frozen_bundle_sha256 != actual.frozen_bundle_sha256):
                raise ValueError("run slot result must match plan identity")
        return self
