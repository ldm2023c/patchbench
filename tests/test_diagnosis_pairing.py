"""D6.2 exact case pairing and inspectable Blind/Contrastive transitions."""

import pytest

from patchbench.application.diagnosis_metrics import (
    DiagnosisMetricsError,
    aggregate_semantic_scores,
    compare_blind_contrastive,
)
from tests.test_diagnosis_metrics import SHA, semantic_score


def with_mode(score, mode):
    return type(score).model_validate(score.model_dump() | {
        "mode": mode,
        "diagnosis_id": f"diag-{mode}-{score.case_id}",
    })


def pair_fixture():
    blind = [
        semantic_score("c", preferred=True, top1=True, topk=True,
                       satisfied=1, total=2, audit_passed=True),
        semantic_score("a", preferred=False, top1=False, topk=False,
                       satisfied=0, total=2, audit_passed=False),
        semantic_score("b", preferred=True, top1=True, topk=True,
                       satisfied=2, total=2, audit_passed=True,
                       overclaim_applicable=True),
        semantic_score("d", should_abstain=True, predicted_abstain=True,
                       audit_passed=False),
    ]
    contrastive = [
        with_mode(semantic_score("b", preferred=False, top1=False, topk=False,
                                 satisfied=1, total=2, audit_passed=True,
                                 overclaim_applicable=True), "contrastive"),
        with_mode(semantic_score("d", should_abstain=True, predicted_abstain=False,
                                 audit_passed=True), "contrastive"),
        with_mode(semantic_score("a", preferred=True, top1=True, topk=True,
                                 satisfied=1, total=2, audit_passed=True), "contrastive"),
        with_mode(semantic_score("c", preferred=True, top1=True, topk=True,
                                 satisfied=1, total=2, audit_passed=False), "contrastive"),
    ]
    return blind, contrastive


def test_pairing_by_case_not_position_sorted_and_immutable():
    blind, contrastive = pair_fixture()
    before = ([score.model_dump() for score in blind],
              [score.model_dump() for score in contrastive])
    result = compare_blind_contrastive(blind, contrastive)
    assert [pair.case_id for pair in result.pairs] == ["a", "b", "c", "d"]
    assert result.pair_count == 4
    assert result.blind_aggregate == aggregate_semantic_scores(blind)
    assert result.contrastive_aggregate == aggregate_semantic_scores(contrastive)
    assert before == ([score.model_dump() for score in blind],
                      [score.model_dump() for score in contrastive])
    assert compare_blind_contrastive(list(reversed(blind)),
        [contrastive[2], contrastive[0], contrastive[3], contrastive[1]]) == result


def test_boolean_and_nonapplicable_transitions():
    result = compare_blind_contrastive(*pair_fixture())
    pairs = {pair.case_id: pair for pair in result.pairs}
    assert pairs["a"].preferred_top1_change.value == "improved"
    assert pairs["b"].preferred_top1_change.value == "regressed"
    assert pairs["c"].preferred_top1_change.value == "unchanged"
    assert pairs["d"].preferred_top1_change is None
    assert pairs["d"].top1_acceptable_change is None
    assert pairs["d"].topk_acceptable_change is None
    assert pairs["d"].required_evidence_change is None
    assert pairs["d"].required_evidence_satisfied_delta is None
    assert pairs["d"].abstention_correct_change.value == "regressed"


def test_evidence_and_audit_transitions_and_summaries():
    result = compare_blind_contrastive(*pair_fixture())
    pairs = {pair.case_id: pair for pair in result.pairs}
    assert (pairs["a"].required_evidence_change.value,
            pairs["a"].required_evidence_satisfied_delta) == ("improved", 1)
    assert (pairs["b"].required_evidence_change.value,
            pairs["b"].required_evidence_satisfied_delta) == ("regressed", -1)
    assert (pairs["c"].required_evidence_change.value,
            pairs["c"].required_evidence_satisfied_delta) == ("unchanged", 0)
    assert pairs["a"].audit_pass_change.value == "improved"
    assert pairs["c"].audit_pass_change.value == "regressed"
    assert pairs["b"].audit_pass_change.value == "unchanged"
    assert result.preferred_top1_transitions.model_dump() == dict(
        applicable_pairs=3, improved=1, unchanged=1, regressed=1)
    assert result.abstention_correct_transitions.applicable_pairs == 4
    assert result.audit_pass_transitions.model_dump() == dict(
        applicable_pairs=4, improved=2, unchanged=1, regressed=1)
    assert result.required_evidence_transitions.model_dump() == dict(
        applicable_pairs=3, improved=1, unchanged=1, regressed=1,
        total_satisfied_delta=0)
    for summary in (
        result.preferred_top1_transitions, result.top1_acceptable_transitions,
        result.topk_acceptable_transitions, result.abstention_correct_transitions,
        result.required_evidence_transitions, result.audit_pass_transitions,
    ):
        assert summary.improved + summary.unchanged + summary.regressed == summary.applicable_pairs


def assert_pair_error(blind, contrastive, reason):
    with pytest.raises(DiagnosisMetricsError) as caught:
        compare_blind_contrastive(blind, contrastive)
    assert caught.value.reason.value == reason


def test_pairing_rejects_empty_missing_extra_and_duplicates():
    blind, contrastive = pair_fixture()
    assert_pair_error([], contrastive, "empty_input")
    assert_pair_error(blind, contrastive[:-1], "pair_case_set_mismatch")
    assert_pair_error(blind, contrastive + [with_mode(semantic_score("extra"), "contrastive")],
                      "pair_case_set_mismatch")
    assert_pair_error(blind + [blind[0]], contrastive, "duplicate_case_id")
    assert_pair_error(blind, contrastive + [contrastive[0]], "duplicate_case_id")


def test_pairing_rejects_wrong_modes():
    blind, contrastive = pair_fixture()
    assert_pair_error([with_mode(blind[0], "contrastive")] + blind[1:], contrastive,
                      "wrong_mode")
    assert_pair_error(blind, [with_mode(contrastive[0], "blind")] + contrastive[1:],
                      "wrong_mode")


@pytest.mark.parametrize("change,reason", [
    ({"subject_evidence_sha256": "b" * 64}, "pair_subject_mismatch"),
    ({"preferred_top1_match": None, "top1_acceptable_match": None,
      "topk_acceptable_match": None, "required_evidence_satisfied": None,
      "required_evidence_total": None}, "pair_applicability_mismatch"),
    ({"required_evidence_total": 3}, "pair_evidence_total_mismatch"),
    ({"overclaim_applicable": True}, "pair_overclaim_applicability_mismatch"),
])
def test_pairing_rejects_cross_mode_gold_mismatch(change, reason):
    blind = [semantic_score("case")]
    contrastive = [with_mode(semantic_score("case"), "contrastive").model_copy(update=change)]
    assert_pair_error(blind, contrastive, reason)


def test_pairing_rejects_internal_applicability_contradiction():
    blind = [semantic_score("case")]
    malformed = with_mode(semantic_score("case"), "contrastive").model_copy(
        update={"preferred_top1_match": None})
    assert_pair_error(blind, [malformed], "invalid_applicability")

