"""D6.2 aggregate metrics consume D6.1 scores without reinterpretation."""

from itertools import permutations

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_metrics import (
    DiagnosisMetricsError,
    aggregate_route_scores,
    aggregate_semantic_scores,
)
from patchbench.domain import (
    DiagnosisRouteScore,
    MetricRatio,
    SemanticDiagnosisScore,
)


SHA = "a" * 64


def semantic_score(case_id, *, mode="blind", should_abstain=False,
                   predicted_abstain=None, preferred=True, top1=True, topk=True,
                   satisfied=1, total=1, audit_passed=True, invalid_issues=0,
                   overclaim_applicable=False, overclaim_reviewed=False,
                   overclaim_violation=None):
    if predicted_abstain is None:
        predicted_abstain = should_abstain
    if should_abstain:
        preferred = top1 = topk = satisfied = total = None
    issue_count = invalid_issues + int(not audit_passed and invalid_issues == 0)
    violated = ["claim"] if overclaim_violation else []
    return SemanticDiagnosisScore(
        case_id=case_id,
        gold_sha256=SHA,
        subject_evidence_sha256=SHA,
        diagnosis_id=f"diag-{mode}-{case_id}",
        mode=mode,
        predicted_abstain=predicted_abstain,
        abstention_correct=predicted_abstain == should_abstain,
        preferred_top1_match=preferred,
        top1_acceptable_match=top1,
        topk_acceptable_match=topk,
        required_evidence_satisfied=satisfied,
        required_evidence_total=total,
        audit_passed=audit_passed,
        audit_issue_count=issue_count,
        invalid_citation_issue_count=invalid_issues,
        overclaim_applicable=overclaim_applicable,
        overclaim_reviewed=overclaim_reviewed,
        overclaim_violation=overclaim_violation,
        violated_claim_ids=violated,
    )


def route_score(case_id, correct=True):
    return DiagnosisRouteScore(case_id=case_id, run_id=f"run-{case_id}",
        gold_sha256=SHA,
        expected_route="semantic_diagnosis" if correct else "unavailable",
        actual_route="semantic_diagnosis", actual_reason="semantic_failure", correct=correct)


@pytest.mark.parametrize("numerator,denominator,rate", [
    (0, 0, None), (0, 2, 0.0), (1, 2, 0.5), (2, 2, 1.0),
])
def test_metric_ratio_exact_contract(numerator, denominator, rate):
    assert MetricRatio(numerator=numerator, denominator=denominator, rate=rate).rate == rate


@pytest.mark.parametrize("values", [
    dict(numerator=1, denominator=0, rate=None),
    dict(numerator=2, denominator=1, rate=2.0),
    dict(numerator=1, denominator=2, rate=None),
    dict(numerator=0, denominator=0, rate=0.0),
    dict(numerator=True, denominator=1, rate=1.0),
    dict(numerator=1, denominator=2, rate="0.5"),
])
def test_metric_ratio_rejects_inconsistent_or_empty_zero_performance(values):
    with pytest.raises(ValidationError):
        MetricRatio(**values)


def test_route_aggregate_all_correct_and_mixed():
    all_correct = aggregate_route_scores([route_score("a"), route_score("b")])
    assert (all_correct.case_count, all_correct.correct_count,
            all_correct.accuracy.rate) == (2, 2, 1.0)
    mixed = aggregate_route_scores([route_score("a"), route_score("b", False)])
    assert (mixed.correct_count, mixed.accuracy.numerator,
            mixed.accuracy.denominator, mixed.accuracy.rate) == (1, 1, 2, 0.5)


@pytest.mark.parametrize("scores,reason", [
    ([], "empty_input"),
    ([route_score("a"), route_score("a")], "duplicate_case_id"),
])
def test_route_aggregate_rejects_empty_and_duplicates(scores, reason):
    with pytest.raises(DiagnosisMetricsError) as caught:
        aggregate_route_scores(scores)
    assert caught.value.reason.value == reason


def aggregate_fixture():
    return [
        semantic_score("a", preferred=True, top1=True, topk=True,
                       satisfied=1, total=2, audit_passed=False, invalid_issues=2,
                       overclaim_applicable=True, overclaim_reviewed=True,
                       overclaim_violation=True),
        semantic_score("b", predicted_abstain=True, preferred=False, top1=False,
                       topk=False, satisfied=0, total=4,
                       overclaim_applicable=True),
        semantic_score("c", should_abstain=True, predicted_abstain=True),
        semantic_score("d", should_abstain=True, predicted_abstain=False,
                       audit_passed=False),
    ]


def test_semantic_family_evidence_and_abstention_denominators():
    result = aggregate_semantic_scores(aggregate_fixture())
    assert result.mode.value == "blind" and result.case_count == 4
    assert (result.non_abstention_gold_case_count,
            result.abstention_gold_case_count) == (2, 2)
    assert result.preferred_top1_accuracy == MetricRatio(
        numerator=1, denominator=2, rate=0.5)
    assert result.top1_acceptable_accuracy.denominator == 2
    assert result.topk_acceptable_accuracy.denominator == 2
    assert result.evidence_micro_coverage == MetricRatio(
        numerator=1, denominator=6, rate=1 / 6)
    assert result.evidence_macro_coverage.contributing_case_count == 2
    assert result.evidence_macro_coverage.value == 0.25
    assert result.abstention_accuracy == MetricRatio(
        numerator=2, denominator=4, rate=0.5)
    assert result.abstention_recall == MetricRatio(
        numerator=1, denominator=2, rate=0.5)
    assert result.unnecessary_abstention_rate == MetricRatio(
        numerator=1, denominator=2, rate=0.5)


def test_audit_and_overclaim_metrics_keep_fail_and_unreviewed_cases():
    result = aggregate_semantic_scores(aggregate_fixture())
    assert result.audit_pass_rate == MetricRatio(numerator=2, denominator=4, rate=0.5)
    assert result.invalid_citation_case_rate == MetricRatio(
        numerator=1, denominator=4, rate=0.25)
    assert result.invalid_citation_issue_count == 2
    assert result.overclaim_review_coverage == MetricRatio(
        numerator=1, denominator=2, rate=0.5)
    assert result.overclaim_violation_rate == MetricRatio(
        numerator=1, denominator=1, rate=1.0)


def test_empty_semantic_subgroups_have_none_rates():
    non_abstain = aggregate_semantic_scores([semantic_score("a")])
    assert non_abstain.abstention_recall == MetricRatio(
        numerator=0, denominator=0, rate=None)
    assert non_abstain.overclaim_review_coverage.rate is None
    assert non_abstain.overclaim_violation_rate.rate is None
    abstain = aggregate_semantic_scores([semantic_score("a", should_abstain=True)])
    assert abstain.preferred_top1_accuracy.rate is None
    assert abstain.evidence_micro_coverage.rate is None
    assert abstain.evidence_macro_coverage.value is None
    assert abstain.unnecessary_abstention_rate.rate is None


def test_aggregate_is_order_independent_and_does_not_mutate():
    scores = aggregate_fixture()
    before = [score.model_dump() for score in scores]
    expected = aggregate_semantic_scores(scores)
    assert all(aggregate_semantic_scores(order) == expected
               for order in permutations(scores))
    assert before == [score.model_dump() for score in scores]


@pytest.mark.parametrize("scores,reason", [
    ([], "empty_input"),
    ([semantic_score("a"), semantic_score("a")], "duplicate_case_id"),
    ([semantic_score("a"), semantic_score("b", mode="contrastive")], "mixed_mode"),
])
def test_semantic_aggregate_rejects_invalid_collection(scores, reason):
    with pytest.raises(DiagnosisMetricsError) as caught:
        aggregate_semantic_scores(scores)
    assert caught.value.reason.value == reason


@pytest.mark.parametrize("changes", [
    {"preferred_top1_match": None},
    {"required_evidence_total": None},
    {"required_evidence_satisfied": 0, "required_evidence_total": 0},
])
def test_semantic_aggregate_rejects_contradictory_applicability(changes):
    malformed = semantic_score("a").model_copy(update=changes)
    with pytest.raises(DiagnosisMetricsError) as caught:
        aggregate_semantic_scores([malformed])
    assert caught.value.reason.value == "invalid_applicability"
