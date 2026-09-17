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

# D6-R4 deterministic collection scoring orchestration.

import json
import shutil
from pathlib import Path

from patchbench.application.diagnosis_gold_lock import SEMANTIC_CASE_IDS
from patchbench.application.diagnosis_validation import compute_diagnosis_gold_sha256
from patchbench.application.diagnosis_validation_scoring import (
    DiagnosisValidationScoringError,
    _review_lookup,
    finalize_diagnosis_validation_scoring,
    prepare_diagnosis_validation_scoring,
)
from patchbench.domain.diagnosis import DiagnosisMode
from patchbench.domain.diagnosis_validation import DiagnosisGoldCase
from patchbench.domain.diagnosis_validation_collection import (
    DiagnosisValidationCollection,
    compute_diagnosis_validation_collection_sha256,
)
from patchbench.domain.diagnosis_validation_scoring import (
    DiagnosisValidationFinalScores,
    DiagnosisValidationOverclaimReviewPacket,
    DiagnosisValidationOverclaimReviewSet,
    DiagnosisValidationScoringPreparation,
    compute_diagnosis_validation_final_scores_sha256,
    compute_diagnosis_validation_preparation_sha256,
)
from tests.test_diagnosis_validation_collection import (
    CANDIDATES,
    VALIDATION,
    collect as collect_shards,
    make_successful_shards,
)


def _json_bytes(value) -> bytes:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


@pytest.fixture(scope="module")
def d6r4_base(tmp_path_factory):
    root = tmp_path_factory.mktemp("d6r4-base")
    results, selections, provider_calls = make_successful_shards(root)
    collection = collect_shards(root, results, selections, collection_id="collection")
    return {"results": results, "collection": collection, "provider_calls": provider_calls}


@pytest.fixture
def d6r4_results(tmp_path, d6r4_base):
    target = tmp_path / "results"
    shutil.copytree(d6r4_base["results"], target)
    return target


def _prepare(results, preparation_id="prep"):
    return prepare_diagnosis_validation_scoring(
        validation_root=VALIDATION,
        candidate_root=CANDIDATES,
        results_root=results,
        collection_id="collection",
        preparation_id=preparation_id,
    )


def _review_payload(packet, *, preparation_sha=None, reviews=None):
    return {
        "schema_version": 1,
        "preparation_id": packet.preparation_id,
        "preparation_sha256": preparation_sha or packet.preparation_sha256,
        "reviews": reviews if reviews is not None else [
            {
                "schema_version": 1,
                "case_id": item.case_id,
                "diagnosis_id": item.diagnosis_id,
                "violated_claim_ids": [],
            }
            for item in packet.items
        ],
    }


def _write_review(tmp_path, packet, **kwargs):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(_review_payload(packet, **kwargs), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _finalize(results, review_file, score_id="score"):
    return finalize_diagnosis_validation_scoring(
        validation_root=VALIDATION,
        candidate_root=CANDIDATES,
        results_root=results,
        preparation_id="prep",
        review_file=review_file,
        score_id=score_id,
    )


def _collection_path(results):
    return results / "diagnosis-validation-v1/collections/collection/collection.json"


def _rewrite_collection(results, raw):
    raw = dict(raw)
    raw["collection_sha256"] = None
    collection = DiagnosisValidationCollection.model_validate(raw)
    collection = DiagnosisValidationCollection.model_validate(collection.model_dump(mode="json") | {
        "collection_sha256": compute_diagnosis_validation_collection_sha256(collection)
    })
    _collection_path(results).write_bytes(_json_bytes(collection))
    return collection


def _assert_reason(caught, reason):
    assert caught.value.reason.value == reason


def test_d6r4_prepare_creates_26_preliminary_scores_and_review_packet(d6r4_results, d6r4_base):
    preparation, packet = _prepare(d6r4_results)
    assert d6r4_base["provider_calls"] == 26
    assert [case.case_id for case in preparation.cases] == list(SEMANTIC_CASE_IDS)
    assert [(case.case_id, case.blind.preliminary_score.mode, case.contrastive.preliminary_score.mode)
            for case in preparation.cases] == [
                (case_id, DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)
                for case_id in SEMANTIC_CASE_IDS
            ]
    scores = [slot.preliminary_score for case in preparation.cases for slot in (case.blind, case.contrastive)]
    assert len(scores) == 26
    assert all(score.overclaim_reviewed is False for score in scores)
    loaded = DiagnosisValidationScoringPreparation.model_validate_json(
        (d6r4_results / "diagnosis-validation-v1/scoring-preparations/prep/preparation.json").read_bytes())
    assert loaded == preparation
    packet_loaded = DiagnosisValidationOverclaimReviewPacket.model_validate_json(
        (d6r4_results / "diagnosis-validation-v1/scoring-preparations/prep/overclaim-review-packet.json").read_bytes())
    assert packet_loaded == packet
    expected_cases = []
    for case_id in SEMANTIC_CASE_IDS:
        gold = DiagnosisGoldCase.model_validate_json((VALIDATION / f"cases/{case_id}/gold.json").read_bytes())
        if gold.semantic_gold.forbidden_claims:
            expected_cases.extend([case_id, case_id])
    assert [item.case_id for item in packet.items] == expected_cases
    assert [item.mode for item in packet.items] == [mode for _ in range(len(expected_cases) // 2)
                                                    for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)]
    with pytest.raises(ValidationError):
        DiagnosisValidationOverclaimReviewSet.model_validate(packet.model_dump(mode="json"))


def test_d6r4_collection_hash_tamper_is_rejected(d6r4_results):
    raw = json.loads(_collection_path(d6r4_results).read_text(encoding="utf-8"))
    raw["cases"][0]["run_id"] = "other-run"
    _collection_path(d6r4_results).write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results)
    _assert_reason(caught, "missing_or_invalid_collection")


def test_d6r4_collection_order_and_frozen_identity_mismatch_are_rejected(d6r4_results):
    raw = json.loads(_collection_path(d6r4_results).read_text(encoding="utf-8"))
    raw["cases"][0], raw["cases"][1] = raw["cases"][1], raw["cases"][0]
    _rewrite_collection(d6r4_results, raw)
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results)
    _assert_reason(caught, "collection_identity_mismatch")

    shutil.rmtree(d6r4_results)


def test_d6r4_collection_frozen_identity_mismatch_is_rejected(d6r4_results):
    raw = json.loads(_collection_path(d6r4_results).read_text(encoding="utf-8"))
    raw["freeze_manifest_sha256"] = "0" * 64
    _rewrite_collection(d6r4_results, raw)
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results)
    _assert_reason(caught, "collection_identity_mismatch")


def test_d6r4_gold_content_mismatch_is_rejected(tmp_path, d6r4_results):
    validation = tmp_path / "validation"
    shutil.copytree(VALIDATION, validation)
    gold_path = validation / "cases/semantic-01/gold.json"
    raw = json.loads(gold_path.read_text(encoding="utf-8"))
    raw["semantic_gold"]["required_evidence"][0]["description"] = "tampered"
    gold_path.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        prepare_diagnosis_validation_scoring(validation_root=validation, candidate_root=CANDIDATES,
            results_root=d6r4_results, collection_id="collection", preparation_id="prep")
    _assert_reason(caught, "invalid_frozen_gold_lock")


def test_d6r4_diagnosis_artifact_missing_tampered_and_linkage_mismatch_are_rejected(d6r4_results):
    raw = json.loads(_collection_path(d6r4_results).read_text(encoding="utf-8"))
    diagnosis_id = raw["cases"][0]["blind"]["diagnosis_id"]
    run_id = raw["cases"][0]["run_id"]
    execution = d6r4_results / "diagnosis-validation-v1" / run_id / "diagnoses" / diagnosis_id / "execution.json"
    execution.unlink()
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results)
    _assert_reason(caught, "diagnosis_artifact_mismatch")


def test_d6r4_selected_diagnosis_linkage_mismatch_is_rejected(d6r4_results):
    raw = json.loads(_collection_path(d6r4_results).read_text(encoding="utf-8"))
    raw["cases"][0]["blind"]["diagnosis_id"] = "diag-missing"
    _rewrite_collection(d6r4_results, raw)
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results)
    _assert_reason(caught, "diagnosis_artifact_mismatch")


def test_d6r4_unsafe_existing_and_write_failed_preparation(d6r4_results, monkeypatch):
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        prepare_diagnosis_validation_scoring(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=d6r4_results, collection_id="collection", preparation_id="../bad")
    _assert_reason(caught, "invalid_preparation_id")

    _prepare(d6r4_results, preparation_id="once")
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _prepare(d6r4_results, preparation_id="once")
    _assert_reason(caught, "scoring_preparation_already_exists")

    root = d6r4_results / "diagnosis-validation-v1/scoring-preparations/retry"
    original_write = Path.write_bytes

    def fail_write(path, data):
        if path == root / "preparation.json":
            raise OSError("injected")
        return original_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", fail_write)
        with pytest.raises(DiagnosisValidationScoringError) as caught:
            _prepare(d6r4_results, preparation_id="retry")
    _assert_reason(caught, "preparation_persistence_failed")
    assert not root.exists()
    _prepare(d6r4_results, preparation_id="retry")
    assert (root / "preparation.json").exists()


def test_d6r4_finalize_happy_path_reviews_all_applicable_scores(d6r4_results, tmp_path):
    preparation, packet = _prepare(d6r4_results)
    review = _write_review(tmp_path, packet)
    scores = _finalize(d6r4_results, review)
    assert len(scores.scores) == 26
    assert [score.case_id for score in scores.scores] == [case_id for case_id in SEMANTIC_CASE_IDS for _ in (0, 1)]
    assert [score.mode for score in scores.scores] == [mode for _ in SEMANTIC_CASE_IDS
                                                       for mode in (DiagnosisMode.BLIND, DiagnosisMode.CONTRASTIVE)]
    applicable = [score for score in scores.scores if score.overclaim_applicable]
    nonapplicable = [score for score in scores.scores if not score.overclaim_applicable]
    assert applicable and all(score.overclaim_reviewed and score.overclaim_violation is False for score in applicable)
    assert all(not score.overclaim_reviewed and score.overclaim_violation is None for score in nonapplicable)
    loaded = DiagnosisValidationFinalScores.model_validate_json(
        (d6r4_results / "diagnosis-validation-v1/semantic-scores/score/scores.json").read_bytes())
    assert loaded == scores
    assert scores.preparation_sha256 == preparation.preparation_sha256


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "missing_review"),
    ("extra", "extra_review"),
    ("duplicate", "duplicate_review"),
    ("wrong_diagnosis", "missing_review"),
    ("unknown_claim", "review_linkage_mismatch"),
    ("wrong_preparation_sha", "invalid_review_set"),
])
def test_d6r4_finalize_review_validation_errors(d6r4_results, tmp_path, mutation, reason):
    preparation, packet = _prepare(d6r4_results)
    reviews = _review_payload(packet)["reviews"]
    if mutation == "missing":
        reviews = reviews[1:]
    elif mutation == "extra":
        reviews.append({"schema_version": 1, "case_id": "semantic-01", "diagnosis_id": "diag-extra", "violated_claim_ids": []})
    elif mutation == "duplicate":
        reviews.append(dict(reviews[0]))
    elif mutation == "wrong_diagnosis":
        reviews[0] = dict(reviews[0]) | {"diagnosis_id": "diag-wrong"}
    elif mutation == "unknown_claim":
        reviews[0] = dict(reviews[0]) | {"violated_claim_ids": ["unknown-claim"]}
    prep_sha = "0" * 64 if mutation == "wrong_preparation_sha" else None
    review = _write_review(tmp_path, packet, preparation_sha=prep_sha, reviews=reviews)
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _finalize(d6r4_results, review)
    _assert_reason(caught, reason)


def test_d6r4_review_for_case_without_forbidden_claims_is_extra(d6r4_results, tmp_path):
    preparation, packet = _prepare(d6r4_results)
    gold_by_case = {
        case_id: DiagnosisGoldCase.model_validate_json((VALIDATION / f"cases/{case_id}/gold.json").read_bytes())
        for case_id in SEMANTIC_CASE_IDS
    }
    first = preparation.cases[0].blind
    gold = gold_by_case[preparation.cases[0].case_id]
    gold_by_case[gold.case_id] = gold.model_copy(update={
        "semantic_gold": gold.semantic_gold.model_copy(update={"forbidden_claims": []})
    })
    review_set = DiagnosisValidationOverclaimReviewSet.model_validate(_review_payload(packet))
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _review_lookup(review_set, preparation, gold_by_case)
    _assert_reason(caught, "extra_review")
    assert first.diagnosis_id in str(caught.value)


def test_d6r4_finalize_recomputes_from_artifacts_not_preliminary_score_mutation(d6r4_results, tmp_path):
    preparation, packet = _prepare(d6r4_results)
    raw = preparation.model_dump(mode="json")
    raw["cases"][0]["blind"]["preliminary_score"]["predicted_abstain"] = not raw["cases"][0]["blind"]["preliminary_score"]["predicted_abstain"]
    mutated = DiagnosisValidationScoringPreparation.model_validate(raw | {"preparation_sha256": None})
    mutated = DiagnosisValidationScoringPreparation.model_validate(mutated.model_dump(mode="json") | {
        "preparation_sha256": compute_diagnosis_validation_preparation_sha256(mutated)
    })
    prep_path = d6r4_results / "diagnosis-validation-v1/scoring-preparations/prep/preparation.json"
    prep_path.write_bytes(_json_bytes(mutated))
    review = _write_review(tmp_path, packet, preparation_sha=mutated.preparation_sha256)
    scores = _finalize(d6r4_results, review)
    assert scores.scores[0].predicted_abstain != raw["cases"][0]["blind"]["preliminary_score"]["predicted_abstain"]


def test_d6r4_score_id_existing_and_write_failure_are_rejected_and_retryable(d6r4_results, tmp_path, monkeypatch):
    _preparation, packet = _prepare(d6r4_results)
    review = _write_review(tmp_path, packet)
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        finalize_diagnosis_validation_scoring(validation_root=VALIDATION, candidate_root=CANDIDATES,
            results_root=d6r4_results, preparation_id="prep", review_file=review, score_id="../bad")
    _assert_reason(caught, "score_id_invalid")

    _finalize(d6r4_results, review, score_id="once")
    with pytest.raises(DiagnosisValidationScoringError) as caught:
        _finalize(d6r4_results, review, score_id="once")
    _assert_reason(caught, "score_already_exists")

    root = d6r4_results / "diagnosis-validation-v1/semantic-scores/retry"
    original_write = Path.write_bytes

    def fail_write(path, data):
        if path == root / "scores.json":
            raise OSError("injected")
        return original_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", fail_write)
        with pytest.raises(DiagnosisValidationScoringError) as caught:
            _finalize(d6r4_results, review, score_id="retry")
    _assert_reason(caught, "score_persistence_failed")
    assert not root.exists()
    _finalize(d6r4_results, review, score_id="retry")
    assert (root / "scores.json").exists()


def test_d6r4_domain_hashes_reject_preparation_and_final_score_tampering(d6r4_results, tmp_path):
    preparation, packet = _prepare(d6r4_results)
    raw = preparation.model_dump(mode="json")
    raw["cases"][0]["case_id"] = "semantic-x"
    with pytest.raises(ValidationError):
        DiagnosisValidationScoringPreparation.model_validate(raw)

    scores = _finalize(d6r4_results, _write_review(tmp_path, packet))
    raw_scores = scores.model_dump(mode="json")
    raw_scores["scores"][0]["diagnosis_id"] = "diag-tampered"
    with pytest.raises(ValidationError):
        DiagnosisValidationFinalScores.model_validate(raw_scores)


def test_d6r4_review_packet_binds_frozen_claims_and_exact_diagnosis(d6r4_results):
    _preparation, packet = _prepare(d6r4_results)
    for item in packet.items:
        gold = DiagnosisGoldCase.model_validate_json((VALIDATION / f"cases/{item.case_id}/gold.json").read_bytes())
        assert item.gold_sha256 == compute_diagnosis_gold_sha256(gold)
        assert [claim.claim_id for claim in item.forbidden_claims] == [
            claim.claim_id for claim in gold.semantic_gold.forbidden_claims
        ]
        assert item.diagnosis.diagnosis_id == item.diagnosis_id
        assert item.diagnosis.mode is item.mode
