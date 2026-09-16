"""Immutable selected successful shards for Diagnosis Validation V1."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy, DiagnosisProviderSettings
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex

SafeIdentifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


def _validate_safe_direct_child(value: str) -> str:
    if (not value or value in (".", "..") or value != value.strip()
            or value.startswith("/") or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("identifier must be a safe direct-child name")
    return value


class DiagnosisValidationCollectedSlot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    mode: DiagnosisMode
    diagnosis_id: NonEmptyString
    execution_sha256: Sha256Hex
    frozen_bundle_sha256: Sha256Hex


class DiagnosisValidationCollectedCase(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    case_id: NonEmptyString
    run_id: SafeIdentifier
    blind: DiagnosisValidationCollectedSlot
    contrastive: DiagnosisValidationCollectedSlot

    _run_id = field_validator("run_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_modes(self) -> Self:
        if self.blind.mode is not DiagnosisMode.BLIND:
            raise ValueError("blind slot must have Blind mode")
        if self.contrastive.mode is not DiagnosisMode.CONTRASTIVE:
            raise ValueError("contrastive slot must have Contrastive mode")
        return self


class DiagnosisValidationCollection(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    collection_id: SafeIdentifier
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    provider_settings: DiagnosisProviderSettings
    external_policy: DiagnosisExternalLLMPolicy
    cases: list[DiagnosisValidationCollectedCase] = Field(min_length=13, max_length=13)
    collection_sha256: Sha256Hex | None = None

    _collection_id = field_validator("collection_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_collection(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("collected case IDs must be unique")
        run_ids = [case.run_id for case in self.cases]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("selected run IDs must be unique")
        if self.collection_sha256 is not None and self.collection_sha256 != compute_diagnosis_validation_collection_sha256(self):
            raise ValueError("collection_sha256 mismatch")
        return self


def compute_diagnosis_validation_collection_sha256(collection: DiagnosisValidationCollection) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(
        collection.model_dump(mode="json", exclude={"collection_sha256"})
    )).hexdigest()
