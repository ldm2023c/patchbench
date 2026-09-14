"""D6.1 human-gold contracts, subject identity, and grounding boundaries."""

import hashlib

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError,
    compute_subject_evidence_sha256,
    score_diagnosis_route,
    score_semantic_diagnosis,
)
from patchbench.domain import (
    DiagnosisEvidenceBundle,
    DiagnosisGoldCase,
    DiagnosisOverclaimReview,
    FailureDiagnosis,
    ForbiddenClaim,
    GoldEvidenceLocator,
    GoldEvidenceRequirement,
    SemanticDiagnosisGold,
    canonical_json_bytes,
    compute_bundle_sha256,
)
from tests.test_diagnosis import SHA, bundle_data, diagnosis_data, hypothesis_data, item_data
from tests.test_failure_analysis import make_run


SHA_B = "b" * 64
SHA_C = "c" * 64


def make_bundle(mode="blind", items=None, **changes):
    data = bundle_data(mode=mode)
    if items is not None:
        data["evidence_items"] = items + (data["evidence_items"][1:] if mode == "contrastive" else [])
    data.update(changes)
    bundle = DiagnosisEvidenceBundle(**data)
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    return bundle


def make_diagnosis(bundle, **changes):
    data = diagnosis_data(bundle_sha256=bundle.bundle_sha256, mode=bundle.mode.value,
                          subject_run_id=bundle.subject_run_id)
    data.update(changes)
    return FailureDiagnosis(**data)


_DEFAULT = object()


def locator(item, start_line=_DEFAULT, end_line=_DEFAULT, **changes):
    data = dict(owner=item.owner, kind=item.kind, artifact_sha256=item.artifact_sha256,
                path=item.path, source_state=item.source_state,
                start_line=item.start_line if start_line is _DEFAULT else start_line,
                end_line=item.end_line if end_line is _DEFAULT else end_line)
    data.update(changes)
    return GoldEvidenceLocator(**data)


def requirement(item, requirement_id="required", **locator_changes):
    return GoldEvidenceRequirement(requirement_id=requirement_id, description="Required fact.",
        acceptable_locators=[locator(item, **locator_changes)])


def semantic_case(bundle, *, preferred="incorrect_local_logic", acceptable=None,
                  required=None, forbidden=None, case_id="case"):
    return DiagnosisGoldCase(case_id=case_id, expected_route="semantic_diagnosis",
        subject_evidence_sha256=compute_subject_evidence_sha256(bundle),
        semantic_gold=SemanticDiagnosisGold(should_abstain=False, preferred_family=preferred,
            acceptable_families=acceptable or [preferred],
            required_evidence=required or [requirement(bundle.evidence_items[0])],
            forbidden_claims=forbidden or []))


def test_subject_identity_exact_material_and_determinism_without_mutation():
    bundle = make_bundle()
    before = bundle.model_dump()
    expected = dict(schema_version=bundle.schema_version, task_id=bundle.task_id,
        benchmark_definition_sha256=bundle.benchmark_definition_sha256,
        task_fingerprint_sha256=bundle.task_fingerprint_sha256, base_commit=bundle.base_commit,
        source_snapshot_policy=bundle.source_snapshot_policy,
        subject_provenance=bundle.provenance.subject.model_dump(mode="json"))
    expected_sha = hashlib.sha256(canonical_json_bytes(expected)).hexdigest()
    assert compute_subject_evidence_sha256(bundle) == expected_sha
    assert compute_subject_evidence_sha256(bundle) == expected_sha
    assert bundle.model_dump() == before


def test_subject_identity_blind_contrastive_and_excluded_fields():
    blind = make_bundle()
    contrastive = make_bundle("contrastive")
    contrastive.bundle_id = "other-bundle"
    contrastive.subject_run_id = "other-subject-run"
    contrastive.peer_run_id = contrastive.provenance.peer.peer_run_id = "other-peer"
    contrastive.provenance.peer.peer_experiment_id = "other-experiment"
    contrastive.provenance.peer.peer_run_index = 99
    contrastive.evidence_items[-1].content = "peer changed\n"
    contrastive.evidence_items[-1].start_line = contrastive.evidence_items[-1].end_line = 1
    contrastive.bundle_sha256 = "f" * 64
    assert compute_subject_evidence_sha256(blind) == compute_subject_evidence_sha256(contrastive)


@pytest.mark.parametrize("change", [
    "canonical_patch_sha256", "base_source_snapshot_sha256",
    "candidate_source_snapshot_sha256", "evaluation_log_sha256",
    "task_contract_sha256", "frozen_tests_snapshot_sha256", "source_snapshot_policy",
    "task_id", "benchmark_definition_sha256", "task_fingerprint_sha256", "base_commit",
])
def test_each_subject_identity_change_changes_hash(change):
    original = make_bundle()
    data = original.model_dump(mode="json")
    data["bundle_sha256"] = SHA
    if change == "benchmark_definition_sha256":
        data[change] = SHA_B
        data["provenance"]["subject"][change] = SHA_B
    elif change in type(original.provenance.subject).model_fields:
        data["provenance"]["subject"][change] = SHA_B
    else:
        data[change] = SHA_B if change.endswith("sha256") else "changed"
    changed = DiagnosisEvidenceBundle(**data)
    assert compute_subject_evidence_sha256(changed) != compute_subject_evidence_sha256(original)


@pytest.mark.parametrize("data", [
    dict(case_id="case", expected_route="semantic_diagnosis"),
    dict(case_id="case", expected_route="semantic_diagnosis", subject_evidence_sha256=SHA),
    dict(case_id="case", expected_route="unavailable", subject_evidence_sha256=SHA),
])
def test_gold_route_fields_are_exclusive(data):
    with pytest.raises(ValidationError):
        DiagnosisGoldCase(**data)


def valid_semantic_gold(**changes):
    item = make_bundle().evidence_items[0]
    data = dict(should_abstain=False, preferred_family="incorrect_local_logic",
        acceptable_families=["incorrect_local_logic"], required_evidence=[requirement(item)],
        forbidden_claims=[])
    data.update(changes)
    return SemanticDiagnosisGold(**data)


@pytest.mark.parametrize("changes", [
    {"preferred_family": None}, {"acceptable_families": []},
    {"acceptable_families": ["regression_introduced"]}, {"required_evidence": []},
    {"acceptable_families": ["incorrect_local_logic", "incorrect_local_logic"]},
])
def test_nonabstention_gold_invariants(changes):
    with pytest.raises(ValidationError):
        valid_semantic_gold(**changes)


@pytest.mark.parametrize("changes", [
    {"preferred_family": "incorrect_local_logic"},
    {"acceptable_families": ["incorrect_local_logic"]},
    {"required_evidence": [requirement(make_bundle().evidence_items[0])]},
])
def test_abstention_gold_forbids_family_and_required_evidence(changes):
    with pytest.raises(ValidationError):
        SemanticDiagnosisGold(should_abstain=True, **changes)
    assert SemanticDiagnosisGold(should_abstain=True,
        forbidden_claims=[ForbiddenClaim(claim_id="claim", description="Do not claim this.")])


def test_gold_nested_ids_and_locators_are_strict():
    item = make_bundle().evidence_items[0]
    req = requirement(item)
    with pytest.raises(ValidationError):
        GoldEvidenceRequirement(requirement_id="r", description="d",
            acceptable_locators=[req.acceptable_locators[0], req.acceptable_locators[0]])
    with pytest.raises(ValidationError):
        valid_semantic_gold(required_evidence=[req, req])
    claim = ForbiddenClaim(claim_id="c", description="claim")
    with pytest.raises(ValidationError):
        valid_semantic_gold(forbidden_claims=[claim, claim])
    for changes in ({"owner": "peer"}, {"kind": "peer_source"},
                    {"start_line": None, "end_line": 42}, {"start_line": 43, "end_line": 42}):
        with pytest.raises(ValidationError):
            locator(item, **changes)


def test_locator_resolves_subject_benchmark_patch_and_evaluation_without_id():
    items = [
        item_data(evidence_id="source"),
        item_data(evidence_id="test", owner="benchmark", kind="frozen_test",
                  artifact_sha256=SHA_B, path="test_app.py", source_state="frozen"),
        item_data(evidence_id="patch", kind="canonical_patch", artifact_sha256=SHA_C,
                  path=None, source_state="candidate"),
        item_data(evidence_id="log", kind="evaluation_output", artifact_sha256="d" * 64,
                  path=None, source_state="candidate"),
    ]
    bundle = make_bundle(items=items)
    required = [requirement(item, requirement_id=f"r{index}")
                for index, item in enumerate(bundle.evidence_items)]
    gold = semantic_case(bundle, required=required)
    refs = [dict(evidence_id=item.evidence_id, start_line=41, end_line=42)
            for item in bundle.evidence_items]
    diagnosis = make_diagnosis(bundle, hypotheses=[hypothesis_data(evidence_refs=refs)])
    score = score_semantic_diagnosis(bundle, diagnosis, gold)
    assert score.required_evidence_satisfied == score.required_evidence_total == 4


@pytest.mark.parametrize("change,reason", [
    ({"artifact_sha256": SHA_B}, "gold_evidence_not_found"),
    ({"path": "wrong.py"}, "gold_evidence_not_found"),
    ({"source_state": "base"}, "gold_evidence_not_found"),
    ({"start_line": 40, "end_line": 41}, "gold_evidence_range_invalid"),
])
def test_stale_gold_locator_fails_closed(change, reason):
    bundle = make_bundle()
    gold = semantic_case(bundle, required=[GoldEvidenceRequirement(requirement_id="r",
        description="d", acceptable_locators=[locator(bundle.evidence_items[0], **change)])])
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, make_diagnosis(bundle), gold)
    assert caught.value.reason.value == reason


def test_ambiguous_and_stale_alternative_locators_fail_closed():
    first = item_data(evidence_id="first")
    second = item_data(evidence_id="second")
    bundle = make_bundle(items=[first, second])
    gold = semantic_case(bundle, required=[requirement(bundle.evidence_items[0])])
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, make_diagnosis(bundle), gold)
    assert caught.value.reason.value == "gold_evidence_ambiguous"

    bundle = make_bundle()
    good = locator(bundle.evidence_items[0])
    stale = good.model_copy(update={"artifact_sha256": SHA_B})
    req = GoldEvidenceRequirement(requirement_id="r", description="d",
                                  acceptable_locators=[good, stale])
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, make_diagnosis(bundle), semantic_case(bundle, required=[req]))
    assert caught.value.reason.value == "gold_evidence_not_found"


def test_zero_line_locator_and_same_locator_across_modes():
    empty = item_data(evidence_id="empty", owner="benchmark", kind="evaluation_case",
                      artifact_sha256=SHA_B, path=None, source_state="frozen",
                      start_line=None, end_line=None, content="")
    blind = make_bundle(items=[empty])
    contrastive = make_bundle("contrastive", items=[empty])
    req = requirement(blind.evidence_items[0])
    blind_gold = semantic_case(blind, required=[req])
    contrastive_gold = blind_gold.model_copy(update={
        "subject_evidence_sha256": compute_subject_evidence_sha256(contrastive)})
    ref = dict(evidence_id="empty", start_line=None, end_line=None)
    assert score_semantic_diagnosis(blind, make_diagnosis(blind,
        hypotheses=[hypothesis_data(evidence_refs=[ref])]), blind_gold).required_evidence_satisfied == 1
    assert score_semantic_diagnosis(contrastive, make_diagnosis(contrastive,
        hypotheses=[hypothesis_data(evidence_refs=[ref])]), contrastive_gold).required_evidence_satisfied == 1


def test_preconditions_reject_wrong_bundle_diagnosis_and_subject():
    bundle = make_bundle()
    gold = semantic_case(bundle)
    bundle.bundle_sha256 = SHA_B
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, make_diagnosis(bundle), gold)
    assert caught.value.reason.value == "bundle_integrity_failed"
    bundle = make_bundle()
    diagnosis = make_diagnosis(bundle)
    diagnosis.subject_run_id = "wrong"
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, diagnosis, semantic_case(bundle))
    assert caught.value.reason.value == "diagnosis_linkage_failed"
    wrong_gold = semantic_case(bundle).model_copy(update={"subject_evidence_sha256": SHA_B})
    with pytest.raises(DiagnosisValidationError) as caught:
        score_semantic_diagnosis(bundle, make_diagnosis(bundle), wrong_gold)
    assert caught.value.reason.value == "subject_evidence_mismatch"


@pytest.mark.parametrize("passed,status,expected", [
    (True, "completed", "unavailable"), (False, "command_failed", "operational_only"),
    (False, "timed_out", "operational_only"), (False, "completed", "semantic_diagnosis"),
])
def test_route_scoring_reuses_d1_router(passed, status, expected, monkeypatch):
    run = make_run(evaluation_passed=passed, agent_status=status)
    gold = DiagnosisGoldCase(case_id="route", expected_route=expected,
        **({"subject_evidence_sha256": SHA, "semantic_gold": valid_semantic_gold()}
           if expected == "semantic_diagnosis" else {}))
    import patchbench.application.diagnosis_validation as module
    calls = []
    original = module.route_run_diagnosis
    monkeypatch.setattr(module, "route_run_diagnosis", lambda value: calls.append(value) or original(value))
    score = score_diagnosis_route(run, gold)
    assert score.actual_route.value == expected and score.correct and calls == [run]
    wrong = DiagnosisGoldCase(case_id="wrong", expected_route="unavailable")
    assert score_diagnosis_route(run, wrong).correct == (expected == "unavailable")


def test_overclaim_review_shape_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        DiagnosisOverclaimReview(case_id="case", diagnosis_id="diagnosis",
                                 violated_claim_ids=["claim", "claim"])


def test_scoring_does_not_mutate_inputs():
    bundle = make_bundle()
    diagnosis = make_diagnosis(bundle)
    gold = semantic_case(bundle)
    before = (bundle.model_dump(), diagnosis.model_dump(), gold.model_dump())
    score_semantic_diagnosis(bundle, diagnosis, gold)
    assert before == (bundle.model_dump(), diagnosis.model_dump(), gold.model_dump())
