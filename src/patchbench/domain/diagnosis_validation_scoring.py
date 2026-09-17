"""Immutable scoring orchestration artifacts for Diagnosis Validation V1."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.diagnosis import DiagnosisMode, FailureDiagnosis
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from patchbench.domain.diagnosis_validation import (
    DiagnosisOverclaimReview,
    ForbiddenClaim,
    SemanticDiagnosisScore,
)
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex

SafeIdentifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)]


def _validate_safe_direct_child(value: str) -> str:
    if (not value or value in (".", "..") or value != value.strip()
            or value.startswith("/") or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("identifier must be a safe direct-child name")
    return value


class DiagnosisValidationScoredSlot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    mode: DiagnosisMode
    run_id: SafeIdentifier
    diagnosis_id: NonEmptyString
    execution_sha256: Sha256Hex
    bundle_sha256: Sha256Hex
    gold_sha256: Sha256Hex
    preliminary_score: SemanticDiagnosisScore

    _run_id = field_validator("run_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_score_linkage(self) -> Self:
        if (self.preliminary_score.mode is not self.mode
                or self.preliminary_score.diagnosis_id != self.diagnosis_id
                or self.preliminary_score.gold_sha256 != self.gold_sha256):
            raise ValueError("preliminary score must link to slot identity")
        return self


class DiagnosisValidationScoredCase(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    case_id: NonEmptyString
    blind: DiagnosisValidationScoredSlot
    contrastive: DiagnosisValidationScoredSlot

    @model_validator(mode="after")
    def validate_modes_and_cases(self) -> Self:
        if self.blind.mode is not DiagnosisMode.BLIND:
            raise ValueError("blind slot must use Blind mode")
        if self.contrastive.mode is not DiagnosisMode.CONTRASTIVE:
            raise ValueError("contrastive slot must use Contrastive mode")
        if (self.blind.preliminary_score.case_id != self.case_id
                or self.contrastive.preliminary_score.case_id != self.case_id):
            raise ValueError("slot scores must link to the collected case")
        return self


class DiagnosisValidationScoringPreparation(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    preparation_id: SafeIdentifier
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    collection_id: SafeIdentifier
    collection_sha256: Sha256Hex
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    gold_lock_suite_sha256: Sha256Hex
    cases: list[DiagnosisValidationScoredCase] = Field(min_length=13, max_length=13)
    preparation_sha256: Sha256Hex | None = None

    _preparation_id = field_validator("preparation_id")(_validate_safe_direct_child)
    _collection_id = field_validator("collection_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_preparation(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("scored case IDs must be unique")
        if self.preparation_sha256 is not None and self.preparation_sha256 != compute_diagnosis_validation_preparation_sha256(self):
            raise ValueError("preparation_sha256 mismatch")
        return self


class DiagnosisValidationOverclaimPacketItem(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    case_id: NonEmptyString
    mode: DiagnosisMode
    diagnosis_id: NonEmptyString
    gold_sha256: Sha256Hex
    forbidden_claims: list[ForbiddenClaim] = Field(min_length=1)
    diagnosis: FailureDiagnosis

    @model_validator(mode="after")
    def validate_linkage(self) -> Self:
        if self.diagnosis.diagnosis_id != self.diagnosis_id or self.diagnosis.mode is not self.mode:
            raise ValueError("packet item Diagnosis must match item identity")
        claim_ids = [claim.claim_id for claim in self.forbidden_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("packet item forbidden claims must be unique")
        return self


class DiagnosisValidationOverclaimReviewPacket(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    preparation_id: SafeIdentifier
    preparation_sha256: Sha256Hex
    collection_id: SafeIdentifier
    collection_sha256: Sha256Hex
    items: list[DiagnosisValidationOverclaimPacketItem]
    packet_sha256: Sha256Hex | None = None

    _preparation_id = field_validator("preparation_id")(_validate_safe_direct_child)
    _collection_id = field_validator("collection_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_packet(self) -> Self:
        identities = [(item.case_id, item.mode, item.diagnosis_id) for item in self.items]
        if len(identities) != len(set(identities)):
            raise ValueError("packet review items must be unique")
        if self.packet_sha256 is not None and self.packet_sha256 != compute_diagnosis_validation_review_packet_sha256(self):
            raise ValueError("packet_sha256 mismatch")
        return self


class DiagnosisValidationOverclaimReviewSet(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    preparation_id: SafeIdentifier
    preparation_sha256: Sha256Hex
    reviews: list[DiagnosisOverclaimReview]

    _preparation_id = field_validator("preparation_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_review_identities(self) -> Self:
        identities = [(review.case_id, review.diagnosis_id) for review in self.reviews]
        if len(identities) != len(set(identities)):
            raise ValueError("overclaim reviews must be unique by case and Diagnosis")
        return self


class DiagnosisValidationFinalScores(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    score_id: SafeIdentifier
    suite_id: Literal["diagnosis-validation-v1"] = "diagnosis-validation-v1"
    preparation_id: SafeIdentifier
    preparation_sha256: Sha256Hex
    collection_id: SafeIdentifier
    collection_sha256: Sha256Hex
    freeze_manifest_sha256: Sha256Hex
    frozen_suite_sha256: Sha256Hex
    gold_lock_suite_sha256: Sha256Hex
    scores: list[SemanticDiagnosisScore] = Field(min_length=26, max_length=26)
    score_sha256: Sha256Hex | None = None

    _score_id = field_validator("score_id")(_validate_safe_direct_child)
    _preparation_id = field_validator("preparation_id")(_validate_safe_direct_child)
    _collection_id = field_validator("collection_id")(_validate_safe_direct_child)

    @model_validator(mode="after")
    def validate_scores(self) -> Self:
        identities = [(score.case_id, score.mode, score.diagnosis_id) for score in self.scores]
        if len(identities) != len(set(identities)):
            raise ValueError("final scores must be unique by case, mode, and Diagnosis")
        if self.score_sha256 is not None and self.score_sha256 != compute_diagnosis_validation_final_scores_sha256(self):
            raise ValueError("score_sha256 mismatch")
        return self


def compute_diagnosis_validation_preparation_sha256(
    preparation: DiagnosisValidationScoringPreparation,
) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(
        preparation.model_dump(mode="json", exclude={"preparation_sha256"})
    )).hexdigest()


def compute_diagnosis_validation_review_packet_sha256(
    packet: DiagnosisValidationOverclaimReviewPacket,
) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(
        packet.model_dump(mode="json", exclude={"packet_sha256"})
    )).hexdigest()


def compute_diagnosis_validation_final_scores_sha256(
    scores: DiagnosisValidationFinalScores,
) -> Sha256Hex:
    return hashlib.sha256(canonical_json_bytes(
        scores.model_dump(mode="json", exclude={"score_sha256"})
    )).hexdigest()
