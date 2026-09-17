"""Immutable final metrics artifact for Diagnosis Validation V1."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.diagnosis_metrics import BlindContrastiveComparison, DiagnosisRouteAggregate
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from patchbench.domain.diagnosis_validation import DiagnosisRouteScore
from patchbench.domain.models import DomainModel, Sha256Hex

SafeIdentifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


def _validate_safe_direct_child(value: str) -> str:
    if (not value or value in (".", "..") or value != value.strip()
            or value.startswith("/") or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("identifier must be a safe direct-child name")
    return value


class DiagnosisValidationFinalResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    result_id: SafeIdentifier
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"

    semantic_score_id: SafeIdentifier
    semantic_score_sha256: Sha256Hex
    preparation_id: SafeIdentifier
    preparation_sha256: Sha256Hex
    collection_id: SafeIdentifier
    collection_sha256: Sha256Hex
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    gold_lock_suite_sha256: Sha256Hex

    operational_scores: list[DiagnosisRouteScore] = Field(min_length=2, max_length=2)
    operational_aggregate: DiagnosisRouteAggregate
    semantic_comparison: BlindContrastiveComparison

    result_sha256: Sha256Hex | None = None

    _result_id = field_validator("result_id")(_validate_safe_direct_child)
    _semantic_score_id = field_validator("semantic_score_id")(_validate_safe_direct_child)
    _preparation_id = field_validator("preparation_id")(_validate_safe_direct_child)
    _collection_id = field_validator("collection_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        case_ids = [score.case_id for score in self.operational_scores]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("operational case IDs must be unique")
        if self.operational_aggregate.case_count != 2:
            raise ValueError("operational aggregate must cover exactly two cases")
        if self.operational_aggregate.correct_count != sum(score.correct for score in self.operational_scores):
            raise ValueError("operational aggregate correct count differs from scores")
        if self.semantic_comparison.pair_count != 13:
            raise ValueError("semantic comparison must cover exactly thirteen pairs")
        if self.semantic_comparison.blind_aggregate.case_count != 13:
            raise ValueError("Blind semantic aggregate must cover exactly thirteen cases")
        if self.semantic_comparison.contrastive_aggregate.case_count != 13:
            raise ValueError("Contrastive semantic aggregate must cover exactly thirteen cases")
        if self.result_sha256 is not None and self.result_sha256 != compute_diagnosis_validation_result_sha256(self):
            raise ValueError("result_sha256 mismatch")
        return self


def compute_diagnosis_validation_result_sha256(result: DiagnosisValidationFinalResult) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(
        result.model_dump(mode="json", exclude={"result_sha256"})
    )).hexdigest()
