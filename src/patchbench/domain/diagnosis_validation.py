"""Human-authored Diagnosis gold and deterministic per-case score contracts."""

from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from patchbench.domain.diagnosis import (
    DiagnosisMode,
    DiagnosisRoute,
    DiagnosisRoutingReason,
    EvidenceKind,
    EvidenceOwner,
    EvidenceSourceState,
    FailureFamily,
)
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex


class GoldEvidenceLocator(DomainModel):
    """Stable subject/benchmark evidence coordinates, independent of Bundle IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    owner: EvidenceOwner
    kind: EvidenceKind
    artifact_sha256: Sha256Hex
    path: NonEmptyString | None = None
    source_state: EvidenceSourceState | None = None
    start_line: int | None = Field(default=None, strict=True, ge=1)
    end_line: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def validate_subject_evidence(self) -> Self:
        peer_kinds = {
            EvidenceKind.PEER_SOURCE,
            EvidenceKind.PEER_PATCH,
            EvidenceKind.PEER_EVALUATION,
        }
        if self.owner is EvidenceOwner.PEER or self.kind in peer_kinds:
            raise ValueError("gold evidence must be subject/benchmark grounded")
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("gold evidence coordinates must both be present or absent")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be at least start_line")
        return self


class GoldEvidenceRequirement(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: NonEmptyString
    description: NonEmptyString
    acceptable_locators: list[GoldEvidenceLocator] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_locators(self) -> Self:
        identities = [locator.model_dump_json() for locator in self.acceptable_locators]
        if len(identities) != len(set(identities)):
            raise ValueError("acceptable evidence locators must be unique")
        return self


class ForbiddenClaim(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: NonEmptyString
    description: NonEmptyString


class SemanticDiagnosisGold(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    should_abstain: Annotated[bool, Field(strict=True)]
    preferred_family: FailureFamily | None = None
    acceptable_families: list[FailureFamily] = Field(default_factory=list)
    required_evidence: list[GoldEvidenceRequirement] = Field(default_factory=list)
    forbidden_claims: list[ForbiddenClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantic_gold(self) -> Self:
        if len(self.acceptable_families) != len(set(self.acceptable_families)):
            raise ValueError("acceptable families must be unique")
        requirement_ids = [item.requirement_id for item in self.required_evidence]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("required evidence IDs must be unique")
        claim_ids = [item.claim_id for item in self.forbidden_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("forbidden claim IDs must be unique")

        if self.should_abstain:
            if (self.preferred_family is not None or self.acceptable_families
                    or self.required_evidence):
                raise ValueError("abstention gold cannot define family or required evidence")
        elif (self.preferred_family is None or not self.acceptable_families
              or self.preferred_family not in self.acceptable_families
              or not self.required_evidence):
            raise ValueError(
                "non-abstention gold requires an acceptable preferred family and required evidence"
            )
        return self


class DiagnosisGoldCase(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: NonEmptyString
    expected_route: DiagnosisRoute
    subject_evidence_sha256: Sha256Hex | None = None
    semantic_gold: SemanticDiagnosisGold | None = None

    @model_validator(mode="after")
    def validate_route_gold(self) -> Self:
        semantic = self.expected_route is DiagnosisRoute.SEMANTIC_DIAGNOSIS
        if semantic != (self.subject_evidence_sha256 is not None and self.semantic_gold is not None):
            raise ValueError("semantic route requires subject identity and semantic gold exclusively")
        if not semantic and (self.subject_evidence_sha256 is not None or self.semantic_gold is not None):
            raise ValueError("nonsemantic route cannot define semantic gold")
        return self


class DiagnosisOverclaimReview(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: NonEmptyString
    diagnosis_id: NonEmptyString
    violated_claim_ids: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        if len(self.violated_claim_ids) != len(set(self.violated_claim_ids)):
            raise ValueError("violated claim IDs must be unique")
        return self


class DiagnosisRouteScore(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: NonEmptyString
    gold_sha256: Sha256Hex
    run_id: NonEmptyString
    expected_route: DiagnosisRoute
    actual_route: DiagnosisRoute
    actual_reason: DiagnosisRoutingReason
    correct: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        reason_routes = {
            DiagnosisRoutingReason.SEMANTIC_FAILURE: DiagnosisRoute.SEMANTIC_DIAGNOSIS,
            DiagnosisRoutingReason.AGENT_COMMAND_FAILED: DiagnosisRoute.OPERATIONAL_ONLY,
            DiagnosisRoutingReason.AGENT_TIMED_OUT: DiagnosisRoute.OPERATIONAL_ONLY,
            DiagnosisRoutingReason.OFFICIAL_PASS: DiagnosisRoute.UNAVAILABLE,
        }
        if self.actual_route is not reason_routes[self.actual_reason]:
            raise ValueError("actual route must agree with routing reason")
        if self.correct != (self.actual_route is self.expected_route):
            raise ValueError("correct must agree with expected and actual routes")
        return self


class SemanticDiagnosisScore(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: NonEmptyString
    gold_sha256: Sha256Hex
    subject_evidence_sha256: Sha256Hex
    diagnosis_id: NonEmptyString
    mode: DiagnosisMode
    predicted_abstain: Annotated[bool, Field(strict=True)]
    abstention_correct: Annotated[bool, Field(strict=True)]
    preferred_top1_match: Annotated[bool, Field(strict=True)] | None
    top1_acceptable_match: Annotated[bool, Field(strict=True)] | None
    topk_acceptable_match: Annotated[bool, Field(strict=True)] | None
    required_evidence_satisfied: int | None = Field(strict=True, ge=0)
    required_evidence_total: int | None = Field(strict=True, ge=0)
    audit_passed: Annotated[bool, Field(strict=True)]
    audit_issue_count: int = Field(strict=True, ge=0)
    invalid_citation_issue_count: int = Field(strict=True, ge=0)
    overclaim_applicable: Annotated[bool, Field(strict=True)]
    overclaim_reviewed: Annotated[bool, Field(strict=True)]
    overclaim_violation: Annotated[bool, Field(strict=True)] | None
    violated_claim_ids: list[NonEmptyString]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        family_values = (
            self.preferred_top1_match,
            self.top1_acceptable_match,
            self.topk_acceptable_match,
        )
        if any(value is None for value in family_values) != all(
                value is None for value in family_values):
            raise ValueError("family score fields must be jointly applicable")
        if (self.required_evidence_satisfied is None) != (self.required_evidence_total is None):
            raise ValueError("required evidence counts must be jointly applicable")
        if (self.required_evidence_satisfied is not None
                and self.required_evidence_satisfied > self.required_evidence_total):
            raise ValueError("required evidence satisfied cannot exceed total")
        if self.audit_passed != (self.audit_issue_count == 0):
            raise ValueError("audit result must agree with issue count")
        if self.invalid_citation_issue_count > self.audit_issue_count:
            raise ValueError("invalid citation issues cannot exceed all audit issues")
        if not self.overclaim_applicable:
            valid_overclaim = (
                not self.overclaim_reviewed
                and self.overclaim_violation is None
                and not self.violated_claim_ids
            )
        elif not self.overclaim_reviewed:
            valid_overclaim = self.overclaim_violation is None and not self.violated_claim_ids
        else:
            valid_overclaim = self.overclaim_violation == bool(self.violated_claim_ids)
        if not valid_overclaim:
            raise ValueError("overclaim fields describe an inconsistent review state")
        return self
