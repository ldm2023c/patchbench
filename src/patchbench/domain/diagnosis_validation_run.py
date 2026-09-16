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

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_selected_case_ids(cls, data):
        if not (isinstance(data, dict) and "selected_case_ids" not in data
                and isinstance(data.get("plan"), list) and len(data["plan"]) == 26):
            return data
        selected = []
        for index in range(0, 26, 2):
            blind = data["plan"][index]
            contrastive = data["plan"][index + 1]
            if not (isinstance(blind, dict) and isinstance(contrastive, dict)
                    and blind.get("case_id") == contrastive.get("case_id")
                    and blind.get("mode") == DiagnosisMode.BLIND.value
                    and contrastive.get("mode") == DiagnosisMode.CONTRASTIVE.value):
                return data
            selected.append(blind.get("case_id"))
        data = dict(data)
        data["selected_case_ids"] = selected
        return data

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    run_id: NonEmptyString
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    provider_settings: DiagnosisProviderSettings
    external_policy: DiagnosisExternalLLMPolicy
    selected_case_ids: list[NonEmptyString] = Field(min_length=1, max_length=13)
    plan: list[DiagnosisValidationRunSlot] = Field(min_length=2, max_length=26)
    slots: list[DiagnosisValidationRunSlotResult] = Field(min_length=2, max_length=26)

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
        if not 1 <= len(self.selected_case_ids) <= 13:
            raise ValueError("diagnosis validation run requires 1 to 13 selected cases")
        if len(set(self.selected_case_ids)) != len(self.selected_case_ids):
            raise ValueError("selected case IDs must be unique")
        if len(self.plan) != 2 * len(self.selected_case_ids) or len(self.slots) != len(self.plan):
            raise ValueError("plan and slots must contain one Blind/Contrastive pair per selected case")
        for index, case_id in enumerate(self.selected_case_ids):
            blind = self.plan[2 * index]
            contrastive = self.plan[2 * index + 1]
            if (blind.case_id != case_id or contrastive.case_id != case_id
                    or blind.mode is not DiagnosisMode.BLIND
                    or contrastive.mode is not DiagnosisMode.CONTRASTIVE):
                raise ValueError("each selected case must have exactly Blind then Contrastive slots")
        for planned, actual in zip(self.plan, self.slots, strict=True):
            if (planned.case_id != actual.case_id or planned.mode is not actual.mode
                    or planned.frozen_bundle_path != actual.frozen_bundle_path
                    or planned.frozen_bundle_sha256 != actual.frozen_bundle_sha256):
                raise ValueError("run slot result must match plan identity")
        return self
