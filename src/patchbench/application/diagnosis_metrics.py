"""Offline aggregation and exact Blind/Contrastive pairing of D6.1 scores."""

from collections.abc import Sequence
from enum import Enum
from fractions import Fraction

from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_metrics import (
    BlindContrastiveComparison,
    DiagnosisRouteAggregate,
    MetricMean,
    MetricRatio,
    PairedDiagnosisDelta,
    PairTransition,
    PairTransitionSummary,
    RequiredEvidenceTransitionSummary,
    SemanticDiagnosisAggregate,
)
from patchbench.domain.diagnosis_validation import DiagnosisRouteScore, SemanticDiagnosisScore


class DiagnosisMetricsReason(str, Enum):
    EMPTY_INPUT = "empty_input"
    DUPLICATE_CASE_ID = "duplicate_case_id"
    MIXED_MODE = "mixed_mode"
    WRONG_MODE = "wrong_mode"
    INVALID_APPLICABILITY = "invalid_applicability"
    PAIR_CASE_SET_MISMATCH = "pair_case_set_mismatch"
    PAIR_SUBJECT_MISMATCH = "pair_subject_mismatch"
    PAIR_APPLICABILITY_MISMATCH = "pair_applicability_mismatch"
    PAIR_EVIDENCE_TOTAL_MISMATCH = "pair_evidence_total_mismatch"
    PAIR_OVERCLAIM_APPLICABILITY_MISMATCH = "pair_overclaim_applicability_mismatch"


class DiagnosisMetricsError(ValueError):
    def __init__(self, reason: DiagnosisMetricsReason, detail: str):
        self.reason = reason
        super().__init__(f"{reason.value}: {detail}")


def _ratio(numerator: int, denominator: int) -> MetricRatio:
    return MetricRatio(numerator=numerator, denominator=denominator,
                       rate=None if denominator == 0 else numerator / denominator)


def _unique_by_case(scores, *, context: str):
    if not scores:
        raise DiagnosisMetricsError(DiagnosisMetricsReason.EMPTY_INPUT,
                                    f"{context} requires at least one score")
    by_case = {score.case_id: score for score in scores}
    if len(by_case) != len(scores):
        raise DiagnosisMetricsError(DiagnosisMetricsReason.DUPLICATE_CASE_ID,
                                    f"{context} case IDs must be unique")
    return by_case


def _semantic_applicable(score: SemanticDiagnosisScore) -> bool:
    family = (score.preferred_top1_match, score.top1_acceptable_match,
              score.topk_acceptable_match)
    evidence = (score.required_evidence_satisfied, score.required_evidence_total)
    family_all = all(value is not None for value in family)
    family_none = all(value is None for value in family)
    evidence_all = all(value is not None for value in evidence)
    evidence_none = all(value is None for value in evidence)
    if not ((family_all or family_none) and (evidence_all or evidence_none)
            and family_all == evidence_all):
        raise DiagnosisMetricsError(
            DiagnosisMetricsReason.INVALID_APPLICABILITY,
            f"case {score.case_id!r} has contradictory family/evidence applicability",
        )
    if evidence_all and (score.required_evidence_total <= 0
                         or score.required_evidence_satisfied > score.required_evidence_total):
        raise DiagnosisMetricsError(
            DiagnosisMetricsReason.INVALID_APPLICABILITY,
            f"case {score.case_id!r} has invalid required-evidence counts",
        )
    return family_all


def aggregate_route_scores(scores: Sequence[DiagnosisRouteScore]) -> DiagnosisRouteAggregate:
    values = tuple(scores)
    _unique_by_case(values, context="route aggregation")
    correct = sum(score.correct for score in values)
    return DiagnosisRouteAggregate(case_count=len(values), correct_count=correct,
                                   accuracy=_ratio(correct, len(values)))


def aggregate_semantic_scores(
    scores: Sequence[SemanticDiagnosisScore],
) -> SemanticDiagnosisAggregate:
    values = tuple(scores)
    _unique_by_case(values, context="semantic aggregation")
    modes = {score.mode for score in values}
    if len(modes) != 1:
        raise DiagnosisMetricsError(DiagnosisMetricsReason.MIXED_MODE,
                                    "semantic aggregation requires exactly one mode")
    mode = next(iter(modes))
    applicable = [_semantic_applicable(score) for score in values]
    non_abstention = [score for score, applies in zip(values, applicable) if applies]
    abstention = [score for score, applies in zip(values, applicable) if not applies]

    non_count = len(non_abstention)
    abstain_count = len(abstention)
    preferred = sum(score.preferred_top1_match for score in non_abstention)
    top1 = sum(score.top1_acceptable_match for score in non_abstention)
    topk = sum(score.topk_acceptable_match for score in non_abstention)

    evidence_satisfied = sum(score.required_evidence_satisfied for score in non_abstention)
    evidence_total = sum(score.required_evidence_total for score in non_abstention)
    macro_fraction = sum(
        (Fraction(score.required_evidence_satisfied, score.required_evidence_total)
         for score in non_abstention),
        start=Fraction(0, 1),
    )
    macro_value = None if non_count == 0 else float(macro_fraction / non_count)

    case_count = len(values)
    abstention_correct = sum(score.abstention_correct for score in values)
    abstention_recalled = sum(score.predicted_abstain for score in abstention)
    unnecessary = sum(score.predicted_abstain for score in non_abstention)
    audit_passed = sum(score.audit_passed for score in values)
    invalid_cases = sum(score.invalid_citation_issue_count > 0 for score in values)
    invalid_issues = sum(score.invalid_citation_issue_count for score in values)
    overclaim_applicable = [score for score in values if score.overclaim_applicable]
    overclaim_reviewed = [score for score in overclaim_applicable if score.overclaim_reviewed]
    overclaim_violations = sum(score.overclaim_violation is True
                               for score in overclaim_reviewed)

    return SemanticDiagnosisAggregate(
        mode=mode,
        case_count=case_count,
        non_abstention_gold_case_count=non_count,
        abstention_gold_case_count=abstain_count,
        preferred_top1_accuracy=_ratio(preferred, non_count),
        top1_acceptable_accuracy=_ratio(top1, non_count),
        topk_acceptable_accuracy=_ratio(topk, non_count),
        evidence_micro_coverage=_ratio(evidence_satisfied, evidence_total),
        evidence_macro_coverage=MetricMean(
            contributing_case_count=non_count, value=macro_value),
        abstention_accuracy=_ratio(abstention_correct, case_count),
        abstention_recall=_ratio(abstention_recalled, abstain_count),
        unnecessary_abstention_rate=_ratio(unnecessary, non_count),
        audit_pass_rate=_ratio(audit_passed, case_count),
        invalid_citation_case_rate=_ratio(invalid_cases, case_count),
        invalid_citation_issue_count=invalid_issues,
        overclaim_review_coverage=_ratio(len(overclaim_reviewed),
                                         len(overclaim_applicable)),
        overclaim_violation_rate=_ratio(overclaim_violations,
                                        len(overclaim_reviewed)),
    )


def _bool_transition(before: bool, after: bool) -> PairTransition:
    if before == after:
        return PairTransition.UNCHANGED
    return PairTransition.IMPROVED if after else PairTransition.REGRESSED


def _count_transition(before: int, after: int) -> PairTransition:
    if before == after:
        return PairTransition.UNCHANGED
    return PairTransition.IMPROVED if after > before else PairTransition.REGRESSED


def _summarize(transitions) -> PairTransitionSummary:
    values = [value for value in transitions if value is not None]
    return PairTransitionSummary(
        applicable_pairs=len(values),
        improved=values.count(PairTransition.IMPROVED),
        unchanged=values.count(PairTransition.UNCHANGED),
        regressed=values.count(PairTransition.REGRESSED),
    )


def _require_mode(scores, mode: DiagnosisMode, side: str):
    if any(score.mode is not mode for score in scores):
        raise DiagnosisMetricsError(DiagnosisMetricsReason.WRONG_MODE,
                                    f"{side} scores must all use {mode.value} mode")


def compare_blind_contrastive(
    blind_scores: Sequence[SemanticDiagnosisScore],
    contrastive_scores: Sequence[SemanticDiagnosisScore],
) -> BlindContrastiveComparison:
    blind_values = tuple(blind_scores)
    contrastive_values = tuple(contrastive_scores)
    blind_by_case = _unique_by_case(blind_values, context="Blind pairing")
    contrastive_by_case = _unique_by_case(contrastive_values, context="Contrastive pairing")
    _require_mode(blind_values, DiagnosisMode.BLIND, "Blind")
    _require_mode(contrastive_values, DiagnosisMode.CONTRASTIVE, "Contrastive")
    if set(blind_by_case) != set(contrastive_by_case):
        raise DiagnosisMetricsError(DiagnosisMetricsReason.PAIR_CASE_SET_MISMATCH,
                                    "Blind and Contrastive case sets must match exactly")

    pairs = []
    for case_id in sorted(blind_by_case):
        blind = blind_by_case[case_id]
        contrastive = contrastive_by_case[case_id]
        if blind.subject_evidence_sha256 != contrastive.subject_evidence_sha256:
            raise DiagnosisMetricsError(DiagnosisMetricsReason.PAIR_SUBJECT_MISMATCH,
                                        f"case {case_id!r} subject identities differ")
        blind_applicable = _semantic_applicable(blind)
        contrastive_applicable = _semantic_applicable(contrastive)
        if blind_applicable != contrastive_applicable:
            raise DiagnosisMetricsError(DiagnosisMetricsReason.PAIR_APPLICABILITY_MISMATCH,
                                        f"case {case_id!r} gold applicability differs")
        if blind.required_evidence_total != contrastive.required_evidence_total:
            raise DiagnosisMetricsError(DiagnosisMetricsReason.PAIR_EVIDENCE_TOTAL_MISMATCH,
                                        f"case {case_id!r} required-evidence totals differ")
        if blind.overclaim_applicable != contrastive.overclaim_applicable:
            raise DiagnosisMetricsError(
                DiagnosisMetricsReason.PAIR_OVERCLAIM_APPLICABILITY_MISMATCH,
                f"case {case_id!r} overclaim applicability differs",
            )

        if blind_applicable:
            preferred_change = _bool_transition(
                blind.preferred_top1_match, contrastive.preferred_top1_match)
            top1_change = _bool_transition(
                blind.top1_acceptable_match, contrastive.top1_acceptable_match)
            topk_change = _bool_transition(
                blind.topk_acceptable_match, contrastive.topk_acceptable_match)
            evidence_delta = (contrastive.required_evidence_satisfied
                              - blind.required_evidence_satisfied)
            evidence_change = _count_transition(
                blind.required_evidence_satisfied,
                contrastive.required_evidence_satisfied,
            )
        else:
            preferred_change = top1_change = topk_change = None
            evidence_delta = evidence_change = None
        pairs.append(PairedDiagnosisDelta(
            case_id=case_id,
            subject_evidence_sha256=blind.subject_evidence_sha256,
            blind_diagnosis_id=blind.diagnosis_id,
            contrastive_diagnosis_id=contrastive.diagnosis_id,
            preferred_top1_change=preferred_change,
            top1_acceptable_change=top1_change,
            topk_acceptable_change=topk_change,
            abstention_correct_change=_bool_transition(
                blind.abstention_correct, contrastive.abstention_correct),
            required_evidence_change=evidence_change,
            required_evidence_satisfied_delta=evidence_delta,
            audit_pass_change=_bool_transition(blind.audit_passed,
                                               contrastive.audit_passed),
        ))

    evidence_summary = _summarize(pair.required_evidence_change for pair in pairs)
    return BlindContrastiveComparison(
        blind_aggregate=aggregate_semantic_scores(blind_values),
        contrastive_aggregate=aggregate_semantic_scores(contrastive_values),
        pair_count=len(pairs),
        pairs=pairs,
        preferred_top1_transitions=_summarize(
            pair.preferred_top1_change for pair in pairs),
        top1_acceptable_transitions=_summarize(
            pair.top1_acceptable_change for pair in pairs),
        topk_acceptable_transitions=_summarize(
            pair.topk_acceptable_change for pair in pairs),
        abstention_correct_transitions=_summarize(
            pair.abstention_correct_change for pair in pairs),
        required_evidence_transitions=RequiredEvidenceTransitionSummary(
            **evidence_summary.model_dump(),
            total_satisfied_delta=sum(
                pair.required_evidence_satisfied_delta or 0 for pair in pairs),
        ),
        audit_pass_transitions=_summarize(pair.audit_pass_change for pair in pairs),
    )

