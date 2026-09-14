"""Deterministic aggregate and paired-comparison contracts for D6.1 scores."""

from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_validation import SemanticDiagnosisScore
from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex


class MetricRatio(DomainModel):
    """Exact counts plus their derived rate; an empty denominator has no rate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: int = Field(strict=True, ge=0)
    denominator: int = Field(strict=True, ge=0)
    rate: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if self.rate != expected:
            raise ValueError("metric rate must be derived exactly from its counts")
        return self


class MetricMean(DomainModel):
    """A macro mean and the number of equally weighted contributing cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contributing_case_count: int = Field(strict=True, ge=0)
    value: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def validate_empty_mean(self) -> Self:
        if (self.contributing_case_count == 0) != (self.value is None):
            raise ValueError("empty macro means require None and nonempty means require a value")
        return self


class DiagnosisRouteAggregate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_count: int = Field(strict=True, ge=1)
    correct_count: int = Field(strict=True, ge=0)
    accuracy: MetricRatio

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (self.accuracy.numerator != self.correct_count
                or self.accuracy.denominator != self.case_count):
            raise ValueError("route accuracy must agree with aggregate counts")
        return self


class SemanticDiagnosisAggregate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    mode: DiagnosisMode
    case_count: int = Field(strict=True, ge=1)
    non_abstention_gold_case_count: int = Field(strict=True, ge=0)
    abstention_gold_case_count: int = Field(strict=True, ge=0)
    preferred_top1_accuracy: MetricRatio
    top1_acceptable_accuracy: MetricRatio
    topk_acceptable_accuracy: MetricRatio
    evidence_micro_coverage: MetricRatio
    evidence_macro_coverage: MetricMean
    abstention_accuracy: MetricRatio
    abstention_recall: MetricRatio
    unnecessary_abstention_rate: MetricRatio
    audit_pass_rate: MetricRatio
    invalid_citation_case_rate: MetricRatio
    invalid_citation_issue_count: int = Field(strict=True, ge=0)
    overclaim_review_coverage: MetricRatio
    overclaim_violation_rate: MetricRatio

    @model_validator(mode="after")
    def validate_denominators(self) -> Self:
        non_abstain = self.non_abstention_gold_case_count
        abstain = self.abstention_gold_case_count
        if non_abstain + abstain != self.case_count:
            raise ValueError("semantic gold subgroup counts must equal case count")
        if any(metric.denominator != non_abstain for metric in (
            self.preferred_top1_accuracy,
            self.top1_acceptable_accuracy,
            self.topk_acceptable_accuracy,
            self.unnecessary_abstention_rate,
        )):
            raise ValueError("family and unnecessary-abstention denominators are invalid")
        if self.evidence_macro_coverage.contributing_case_count != non_abstain:
            raise ValueError("evidence macro case count must include every non-abstention gold case")
        if (self.evidence_micro_coverage.denominator == 0) != (non_abstain == 0):
            raise ValueError("evidence micro denominator must reflect gold applicability")
        if self.abstention_recall.denominator != abstain:
            raise ValueError("abstention recall denominator is invalid")
        if any(metric.denominator != self.case_count for metric in (
            self.abstention_accuracy,
            self.audit_pass_rate,
            self.invalid_citation_case_rate,
        )):
            raise ValueError("all-case semantic metric denominator is invalid")
        return self


class PairTransition(str, Enum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"


class PairedDiagnosisDelta(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    case_id: NonEmptyString
    subject_evidence_sha256: Sha256Hex
    blind_diagnosis_id: NonEmptyString
    contrastive_diagnosis_id: NonEmptyString
    preferred_top1_change: PairTransition | None
    top1_acceptable_change: PairTransition | None
    topk_acceptable_change: PairTransition | None
    abstention_correct_change: PairTransition
    required_evidence_change: PairTransition | None
    required_evidence_satisfied_delta: int | None = Field(default=None, strict=True)
    audit_pass_change: PairTransition

    @model_validator(mode="after")
    def validate_applicability(self) -> Self:
        family = (self.preferred_top1_change, self.top1_acceptable_change,
                  self.topk_acceptable_change)
        if any(value is None for value in family) != all(value is None for value in family):
            raise ValueError("paired family transitions must be jointly applicable")
        evidence_values = (self.required_evidence_change,
                           self.required_evidence_satisfied_delta)
        if any(value is None for value in evidence_values) != all(
                value is None for value in evidence_values):
            raise ValueError("paired evidence transition and delta must be jointly applicable")
        if all(value is None for value in family) != all(
                value is None for value in evidence_values):
            raise ValueError("paired family and evidence applicability must agree")
        if self.required_evidence_satisfied_delta is not None:
            expected = (
                PairTransition.IMPROVED
                if self.required_evidence_satisfied_delta > 0
                else PairTransition.REGRESSED
                if self.required_evidence_satisfied_delta < 0
                else PairTransition.UNCHANGED
            )
            if self.required_evidence_change is not expected:
                raise ValueError("required evidence transition must agree with its delta")
        return self


class PairTransitionSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    applicable_pairs: int = Field(strict=True, ge=0)
    improved: int = Field(strict=True, ge=0)
    unchanged: int = Field(strict=True, ge=0)
    regressed: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.improved + self.unchanged + self.regressed != self.applicable_pairs:
            raise ValueError("transition counts must equal applicable pairs")
        return self


class RequiredEvidenceTransitionSummary(PairTransitionSummary):
    total_satisfied_delta: int = Field(strict=True)


class BlindContrastiveComparison(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    blind_aggregate: SemanticDiagnosisAggregate
    contrastive_aggregate: SemanticDiagnosisAggregate
    pair_count: int = Field(strict=True, ge=1)
    pairs: list[PairedDiagnosisDelta] = Field(min_length=1)
    preferred_top1_transitions: PairTransitionSummary
    top1_acceptable_transitions: PairTransitionSummary
    topk_acceptable_transitions: PairTransitionSummary
    abstention_correct_transitions: PairTransitionSummary
    required_evidence_transitions: RequiredEvidenceTransitionSummary
    audit_pass_transitions: PairTransitionSummary

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        if self.blind_aggregate.mode is not DiagnosisMode.BLIND:
            raise ValueError("blind aggregate must have Blind mode")
        if self.contrastive_aggregate.mode is not DiagnosisMode.CONTRASTIVE:
            raise ValueError("contrastive aggregate must have Contrastive mode")
        if (len(self.pairs) != self.pair_count
                or self.blind_aggregate.case_count != self.pair_count
                or self.contrastive_aggregate.case_count != self.pair_count):
            raise ValueError("pair and mode-aggregate counts must agree")
        ids = [pair.case_id for pair in self.pairs]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("paired cases must be unique and sorted by case ID")
        transition_fields = (
            ("preferred_top1_change", self.preferred_top1_transitions),
            ("top1_acceptable_change", self.top1_acceptable_transitions),
            ("topk_acceptable_change", self.topk_acceptable_transitions),
            ("abstention_correct_change", self.abstention_correct_transitions),
            ("audit_pass_change", self.audit_pass_transitions),
        )
        for field, summary in transition_fields:
            values = [getattr(pair, field) for pair in self.pairs
                      if getattr(pair, field) is not None]
            expected = (
                len(values),
                values.count(PairTransition.IMPROVED),
                values.count(PairTransition.UNCHANGED),
                values.count(PairTransition.REGRESSED),
            )
            actual = (summary.applicable_pairs, summary.improved,
                      summary.unchanged, summary.regressed)
            if actual != expected:
                raise ValueError(f"{field} transition summary differs from paired records")
        evidence_values = [pair.required_evidence_change for pair in self.pairs
                           if pair.required_evidence_change is not None]
        expected_evidence = (
            len(evidence_values),
            evidence_values.count(PairTransition.IMPROVED),
            evidence_values.count(PairTransition.UNCHANGED),
            evidence_values.count(PairTransition.REGRESSED),
            sum(pair.required_evidence_satisfied_delta or 0 for pair in self.pairs),
        )
        actual_evidence = (
            self.required_evidence_transitions.applicable_pairs,
            self.required_evidence_transitions.improved,
            self.required_evidence_transitions.unchanged,
            self.required_evidence_transitions.regressed,
            self.required_evidence_transitions.total_satisfied_delta,
        )
        if actual_evidence != expected_evidence:
            raise ValueError("required evidence transition summary differs from paired records")
        return self
