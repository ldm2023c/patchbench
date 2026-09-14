"""D6.1 deterministic family, evidence, audit, and human-review scoring."""

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_validation import DiagnosisValidationError, score_semantic_diagnosis
from patchbench.domain import (
    DiagnosisOverclaimReview,
    ForbiddenClaim,
    GoldEvidenceRequirement,
)
from tests.test_diagnosis import hypothesis_data, item_data
from tests.test_diagnosis_validation import (
    locator,
    make_bundle,
    make_diagnosis,
    requirement,
    semantic_case,
)


def score_for_families(families, *, preferred="incorrect_local_logic",
                       acceptable=None, abstain=False, should_abstain=False):
    bundle = make_bundle()
    if should_abstain:
        from patchbench.domain import DiagnosisGoldCase, SemanticDiagnosisGold
        from patchbench.application.diagnosis_validation import compute_subject_evidence_sha256
        gold = DiagnosisGoldCase(case_id="case", expected_route="semantic_diagnosis",
            subject_evidence_sha256=compute_subject_evidence_sha256(bundle),
            semantic_gold=SemanticDiagnosisGold(should_abstain=True))
    else:
        gold = semantic_case(bundle, preferred=preferred, acceptable=acceptable or [preferred])
    if abstain:
        diagnosis = make_diagnosis(bundle, abstain=True, abstention_reason="Insufficient.", hypotheses=[])
    else:
        hypotheses = [hypothesis_data(rank=index + 1, failure_family=family)
                      for index, family in enumerate(families)]
        diagnosis = make_diagnosis(bundle, hypotheses=hypotheses)
    return score_semantic_diagnosis(bundle, diagnosis, gold)


def test_family_top1_topk_and_no_match():
    preferred = score_for_families(["incorrect_local_logic"])
    assert (preferred.preferred_top1_match, preferred.top1_acceptable_match,
            preferred.topk_acceptable_match) == (True, True, True)
    acceptable = score_for_families(["regression_introduced"],
        acceptable=["incorrect_local_logic", "regression_introduced"])
    assert (acceptable.preferred_top1_match, acceptable.top1_acceptable_match,
            acceptable.topk_acceptable_match) == (False, True, True)
    later = score_for_families(["regression_introduced", "incorrect_local_logic"])
    assert (later.preferred_top1_match, later.top1_acceptable_match,
            later.topk_acceptable_match) == (False, False, True)
    none = score_for_families(["regression_introduced"])
    assert (none.preferred_top1_match, none.top1_acceptable_match,
            none.topk_acceptable_match) == (False, False, False)


def test_abstention_scoring_and_nonapplicable_family_fields():
    wrong_abstain = score_for_families([], abstain=True)
    assert wrong_abstain.predicted_abstain and not wrong_abstain.abstention_correct
    assert (wrong_abstain.preferred_top1_match, wrong_abstain.top1_acceptable_match,
            wrong_abstain.topk_acceptable_match) == (False, False, False)
    assert (wrong_abstain.required_evidence_satisfied,
            wrong_abstain.required_evidence_total) == (0, 1)

    correct = score_for_families([], abstain=True, should_abstain=True)
    assert correct.abstention_correct
    assert (correct.preferred_top1_match, correct.top1_acceptable_match,
            correct.topk_acceptable_match) == (None, None, None)
    assert (correct.required_evidence_satisfied, correct.required_evidence_total) == (None, None)
    wrong_nonabstain = score_for_families(["incorrect_local_logic"], should_abstain=True)
    assert not wrong_nonabstain.abstention_correct
    assert wrong_nonabstain.preferred_top1_match is None


def test_required_span_exact_cover_partial_and_duplicate_refs():
    bundle = make_bundle()
    item = bundle.evidence_items[0]
    req = requirement(item, start_line=42, end_line=42)
    gold = semantic_case(bundle, required=[req])
    for start, end, expected in [(42, 42, 1), (41, 42, 1), (41, 41, 0)]:
        ref = dict(evidence_id=item.evidence_id, start_line=start, end_line=end)
        diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[ref, ref])])
        result = score_semantic_diagnosis(bundle, diagnosis, gold)
        assert (result.required_evidence_satisfied, result.required_evidence_total) == (expected, 1)


def test_alternative_any_hypothesis_and_counterevidence_exclusion():
    first = item_data(evidence_id="first")
    second = item_data(evidence_id="second", artifact_sha256="b" * 64, path="other.py")
    bundle = make_bundle(items=[first, second])
    req = GoldEvidenceRequirement(requirement_id="either", description="same fact",
        acceptable_locators=[locator(bundle.evidence_items[0]), locator(bundle.evidence_items[1])])
    gold = semantic_case(bundle, required=[req])
    second_ref = dict(evidence_id="second", start_line=41, end_line=42)
    hypotheses = [hypothesis_data(counterevidence_refs=[second_ref]),
                  hypothesis_data(rank=2, failure_family="regression_introduced",
                                  evidence_refs=[second_ref])]
    score = score_semantic_diagnosis(bundle, make_diagnosis(bundle, hypotheses=hypotheses), gold)
    assert score.required_evidence_satisfied == 1
    counter_only = make_diagnosis(bundle, hypotheses=[hypothesis_data(
        evidence_refs=[dict(evidence_id="first", start_line=41, end_line=41)],
        counterevidence_refs=[second_ref])])
    assert score_semantic_diagnosis(bundle, counter_only, gold).required_evidence_satisfied == 0


def test_one_ref_can_satisfy_independent_requirements():
    bundle = make_bundle()
    item = bundle.evidence_items[0]
    gold = semantic_case(bundle, required=[
        requirement(item, requirement_id="one", start_line=41, end_line=41),
        requirement(item, requirement_id="two", start_line=42, end_line=42),
    ])
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[dict(
        evidence_id=item.evidence_id, start_line=41, end_line=42)])])
    score = score_semantic_diagnosis(bundle, diagnosis, gold)
    assert (score.required_evidence_satisfied, score.required_evidence_total) == (2, 2)


def test_peer_citation_never_satisfies_subject_gold():
    bundle = make_bundle("contrastive")
    gold = semantic_case(bundle)
    peer_ref = dict(evidence_id="peer-source", start_line=41, end_line=42)
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[peer_ref])])
    assert score_semantic_diagnosis(bundle, diagnosis, gold).required_evidence_satisfied == 0


def test_correct_family_and_required_evidence_survive_additional_invalid_citation():
    bundle = make_bundle()
    valid = dict(evidence_id="subject-source", start_line=41, end_line=42)
    invalid = dict(evidence_id="missing", start_line=1, end_line=1)
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[valid, invalid])])
    score = score_semantic_diagnosis(bundle, diagnosis, semantic_case(bundle))
    assert score.preferred_top1_match and score.top1_acceptable_match
    assert (score.required_evidence_satisfied, score.required_evidence_total) == (1, 1)
    assert not score.audit_passed and score.audit_issue_count == 1
    assert score.invalid_citation_issue_count == 1


def test_invalid_citation_never_satisfies_required_evidence():
    bundle = make_bundle()
    required = requirement(bundle.evidence_items[0], start_line=41, end_line=42)
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[dict(
        evidence_id="subject-source", start_line=40, end_line=42)])])
    score = score_semantic_diagnosis(bundle, diagnosis, semantic_case(bundle, required=[required]))
    assert score.required_evidence_satisfied == 0
    assert not score.audit_passed and score.invalid_citation_issue_count == 1


def test_wrong_evidence_item_never_satisfies_required_locator():
    items = [item_data(evidence_id="required"),
             item_data(evidence_id="other", artifact_sha256="b" * 64, path="other.py")]
    bundle = make_bundle(items=items)
    gold = semantic_case(bundle, required=[requirement(bundle.evidence_items[0])])
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=[dict(
        evidence_id="other", start_line=41, end_line=42)])])
    score = score_semantic_diagnosis(bundle, diagnosis, gold)
    assert score.audit_passed and score.required_evidence_satisfied == 0


def test_overclaim_not_applicable_and_unreviewed_are_distinct():
    bundle = make_bundle()
    diagnosis = make_diagnosis(bundle)
    plain = score_semantic_diagnosis(bundle, diagnosis, semantic_case(bundle))
    assert (plain.overclaim_applicable, plain.overclaim_reviewed,
            plain.overclaim_violation, plain.violated_claim_ids) == (False, False, None, [])
    claims = [ForbiddenClaim(claim_id="causal", description="Claims proven causality.")]
    unreviewed = score_semantic_diagnosis(bundle, diagnosis, semantic_case(bundle, forbidden=claims))
    assert (unreviewed.overclaim_applicable, unreviewed.overclaim_reviewed,
            unreviewed.overclaim_violation) == (True, False, None)


def test_human_overclaim_clear_and_violation():
    bundle = make_bundle()
    diagnosis = make_diagnosis(bundle)
    claims = [ForbiddenClaim(claim_id="causal", description="Claims proven causality.")]
    gold = semantic_case(bundle, forbidden=claims)
    clear = DiagnosisOverclaimReview(case_id=gold.case_id,
        diagnosis_id=diagnosis.diagnosis_id, violated_claim_ids=[])
    result = score_semantic_diagnosis(bundle, diagnosis, gold, overclaim_review=clear)
    assert result.overclaim_reviewed and result.overclaim_violation is False
    violation = clear.model_copy(update={"violated_claim_ids": ["causal"]})
    result = score_semantic_diagnosis(bundle, diagnosis, gold, overclaim_review=violation)
    assert result.overclaim_violation is True and result.violated_claim_ids == ["causal"]


@pytest.mark.parametrize("change", ["unknown", "case", "diagnosis", "not_applicable"])
def test_overclaim_review_errors(change):
    bundle = make_bundle()
    diagnosis = make_diagnosis(bundle)
    claims = [] if change == "not_applicable" else [ForbiddenClaim(
        claim_id="known", description="Known claim.")]
    gold = semantic_case(bundle, forbidden=claims)
    review = DiagnosisOverclaimReview(
        case_id="wrong" if change == "case" else gold.case_id,
        diagnosis_id="wrong" if change == "diagnosis" else diagnosis.diagnosis_id,
        violated_claim_ids=["unknown"] if change == "unknown" else [],
    )
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, diagnosis, gold, overclaim_review=review)
    assert caught.value.reason.value == "overclaim_review_invalid"


@pytest.mark.parametrize("changes", [
    {"required_evidence_satisfied": 2},
    {"required_evidence_total": None},
    {"preferred_top1_match": None},
    {"audit_passed": False},
    {"invalid_citation_issue_count": 2},
    {"overclaim_applicable": False, "overclaim_reviewed": True},
    {"overclaim_applicable": True, "overclaim_reviewed": False,
     "overclaim_violation": False},
])
def test_semantic_score_rejects_contradictory_result_states(changes):
    result = score_for_families(["incorrect_local_logic"])
    with pytest.raises(ValidationError):
        type(result)(**(result.model_dump() | changes))
