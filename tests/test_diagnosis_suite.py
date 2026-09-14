"""D6.3 final-suite contracts, composition, and semantic binding."""

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_suite import (
    DiagnosisSuiteError,
    verify_diagnosis_validation_v1_composition,
    verify_semantic_validation_case,
)
from patchbench.application.diagnosis_validation import (
    compute_diagnosis_gold_sha256, compute_subject_evidence_sha256,
)
from patchbench.domain import (
    DiagnosisGoldCase, DiagnosisValidationFreezeManifest, DiagnosisValidationSuite, DiagnosisValidationSuiteCase,
    DiagnosisValidationSuiteCaseFile, FrozenValidationFile, SemanticDiagnosisGold,
    compute_bundle_sha256, compute_diagnosis_validation_suite_sha256,
)
from tests.test_diagnosis_validation import make_bundle, semantic_case


SHA = "a" * 64


def semantic_suite_case(case_id: str, gold: DiagnosisGoldCase | None = None):
    gold = gold or DiagnosisGoldCase(case_id=case_id, expected_route="semantic_diagnosis",
        subject_evidence_sha256=SHA, semantic_gold=SemanticDiagnosisGold(should_abstain=True))
    return DiagnosisValidationSuiteCase(case_id=case_id, expected_route="semantic_diagnosis",
        gold_path=f"cases/{case_id}/gold.json", gold_sha256=compute_diagnosis_gold_sha256(gold),
        subject_evidence_sha256=gold.subject_evidence_sha256,
        blind_bundle_path=f"cases/{case_id}/blind.json", blind_bundle_sha256=SHA,
        contrastive_bundle_path=f"cases/{case_id}/contrastive.json",
        contrastive_bundle_sha256=SHA,
        peer_selection_path=f"cases/{case_id}/selection.json", peer_selection_sha256=SHA,
        peer_artifact_store_path=f"support/{case_id}/results"), gold


def operational_suite_case(case_id: str, reason: str):
    gold = DiagnosisGoldCase(case_id=case_id, expected_route="operational_only")
    return DiagnosisValidationSuiteCase(case_id=case_id, expected_route="operational_only",
        gold_path=f"cases/{case_id}/gold.json", gold_sha256=compute_diagnosis_gold_sha256(gold),
        expected_routing_reason=reason, run_record_path=f"cases/{case_id}/run.json",
        run_record_sha256=SHA), gold


def valid_composition():
    family_names = ["incorrect_local_logic", "incomplete_cross_file_repair",
        "partial_contract_handling", "state_consistency_violation", "regression_introduced"]
    cases, golds = [], {}
    bundle = make_bundle()
    for index, family in enumerate(family_names * 2, 1):
        case_id = f"semantic-{index:02d}"
        gold = semantic_case(bundle, case_id=case_id, preferred=family)
        case, _ = semantic_suite_case(case_id, gold)
        cases.append(case); golds[case_id] = gold
    for index in range(11, 14):
        case_id = f"semantic-{index:02d}"
        gold = DiagnosisGoldCase(case_id=case_id, expected_route="semantic_diagnosis",
            subject_evidence_sha256=SHA, semantic_gold=SemanticDiagnosisGold(should_abstain=True))
        case, _ = semantic_suite_case(case_id, gold)
        cases.append(case); golds[case_id] = gold
    for case_id, reason in [("operational-01", "agent_command_failed"),
                            ("operational-02", "agent_timed_out")]:
        case, gold = operational_suite_case(case_id, reason)
        cases.append(case); golds[case_id] = gold
    return cases, golds


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a\\b",
                                   "a//b", "a/./b", " path", "path ", "a:b"])
def test_frozen_paths_reject_without_normalization(path):
    with pytest.raises(ValidationError):
        FrozenValidationFile(path=path, sha256=SHA, byte_length=0)


def test_suite_hash_is_complete_deterministic_and_nonmutating():
    suite = DiagnosisValidationSuite(suite_id="diagnosis-v1", case_files=[
        DiagnosisValidationSuiteCaseFile(case_id="a", path="cases/a.json", sha256=SHA)])
    before = suite.model_dump()
    assert compute_diagnosis_validation_suite_sha256(suite) == compute_diagnosis_validation_suite_sha256(
        DiagnosisValidationSuite.model_validate(suite.model_dump()))
    changed = suite.model_copy(update={"suite_id": "other"})
    assert compute_diagnosis_validation_suite_sha256(changed) != compute_diagnosis_validation_suite_sha256(suite)
    assert suite.model_dump() == before


def test_manifest_rejects_duplicate_paths_and_self_reference():
    entry = FrozenValidationFile(path="suite.json", sha256=SHA, byte_length=1)
    with pytest.raises(ValidationError):
        DiagnosisValidationFreezeManifest(suite_path="suite.json", suite_sha256=SHA,
                                           files=[entry, entry])
    with pytest.raises(ValidationError):
        DiagnosisValidationFreezeManifest(suite_path="suite.json", suite_sha256=SHA,
            files=[FrozenValidationFile(path="freeze-manifest.json", sha256=SHA, byte_length=1), entry])


def test_case_fields_are_route_exclusive_and_unavailable_rejected():
    case, _ = operational_suite_case("op", "agent_command_failed")
    with pytest.raises(ValidationError):
        DiagnosisValidationSuiteCase(**(case.model_dump() | {"subject_evidence_sha256": SHA}))
    with pytest.raises(ValidationError):
        DiagnosisValidationSuiteCase(case_id="pass", expected_route="unavailable",
                                     gold_path="gold.json", gold_sha256=SHA)


def test_exact_v1_composition_passes():
    cases, golds = valid_composition()
    verify_diagnosis_validation_v1_composition(cases, golds)


@pytest.mark.parametrize("count", [12, 14, 16])
def test_wrong_total_is_rejected(count):
    cases, golds = valid_composition()
    cases = cases[:count] if count < 15 else cases + [cases[0].model_copy(update={"case_id": "extra"})]
    golds = {case.case_id: golds.get(case.case_id, next(iter(golds.values()))) for case in cases}
    with pytest.raises(DiagnosisSuiteError):
        verify_diagnosis_validation_v1_composition(cases, golds)


def test_wrong_family_abstention_and_operational_composition_rejected():
    for mutation in ("family", "abstention", "reason"):
        cases, golds = valid_composition()
        if mutation == "family":
            old = golds["semantic-01"]
            raw = old.model_dump(mode="json")
            raw["semantic_gold"]["preferred_family"] = "other_semantic_failure"
            raw["semantic_gold"]["acceptable_families"] = ["other_semantic_failure"]
            golds["semantic-01"] = DiagnosisGoldCase.model_validate(raw)
            cases[0] = cases[0].model_copy(update={"gold_sha256": compute_diagnosis_gold_sha256(golds["semantic-01"])})
        elif mutation == "abstention":
            gold = DiagnosisGoldCase(case_id="semantic-10", expected_route="semantic_diagnosis",
                subject_evidence_sha256=SHA, semantic_gold=SemanticDiagnosisGold(should_abstain=True))
            golds["semantic-10"] = gold
            cases[9] = cases[9].model_copy(update={"gold_sha256": compute_diagnosis_gold_sha256(gold),
                                                   "subject_evidence_sha256": SHA})
        else:
            cases[-1] = cases[-1].model_copy(update={"expected_routing_reason": "agent_command_failed"})
        with pytest.raises(DiagnosisSuiteError):
            verify_diagnosis_validation_v1_composition(cases, golds)


@pytest.mark.parametrize("abstention_count", [2, 4])
def test_exactly_three_abstention_cases_required(abstention_count):
    cases, golds = valid_composition()
    if abstention_count == 2:
        replacement = semantic_case(make_bundle(), case_id="semantic-13",
                                    preferred="incorrect_local_logic")
        index = 12
    else:
        replacement = DiagnosisGoldCase(case_id="semantic-10", expected_route="semantic_diagnosis",
            subject_evidence_sha256=SHA, semantic_gold=SemanticDiagnosisGold(should_abstain=True))
        index = 9
    golds[replacement.case_id] = replacement
    cases[index] = cases[index].model_copy(update={
        "gold_sha256": compute_diagnosis_gold_sha256(replacement),
        "subject_evidence_sha256": replacement.subject_evidence_sha256})
    with pytest.raises(DiagnosisSuiteError):
        verify_diagnosis_validation_v1_composition(cases, golds)


@pytest.mark.parametrize("family", ["ineffective_or_test_focused_repair", "other_semantic_failure"])
def test_excluded_preferred_families_rejected(family):
    cases, golds = valid_composition()
    gold = semantic_case(make_bundle(), case_id="semantic-01", preferred=family)
    golds[gold.case_id] = gold
    cases[0] = cases[0].model_copy(update={"gold_sha256": compute_diagnosis_gold_sha256(gold),
                                           "subject_evidence_sha256": gold.subject_evidence_sha256})
    with pytest.raises(DiagnosisSuiteError):
        verify_diagnosis_validation_v1_composition(cases, golds)


def test_semantic_verification_binds_gold_subject_bundle_mode_and_grounding():
    blind = make_bundle()
    gold = semantic_case(blind, case_id="case")
    case = DiagnosisValidationSuiteCase(case_id="case", expected_route="semantic_diagnosis",
        gold_path="gold.json", gold_sha256=compute_diagnosis_gold_sha256(gold),
        subject_evidence_sha256=compute_subject_evidence_sha256(blind),
        blind_bundle_path="blind.json", blind_bundle_sha256=blind.bundle_sha256,
        contrastive_bundle_path="contrastive.json", contrastive_bundle_sha256=SHA,
        peer_selection_path="selection.json", peer_selection_sha256=SHA,
        peer_artifact_store_path="support/results")
    verify_semantic_validation_case(case, gold, blind)
    variants = [
        case.model_copy(update={"gold_sha256": SHA}),
        case.model_copy(update={"subject_evidence_sha256": SHA}),
        case.model_copy(update={"blind_bundle_sha256": SHA}),
    ]
    for invalid in variants:
        with pytest.raises(DiagnosisSuiteError):
            verify_semantic_validation_case(invalid, gold, blind)
    tampered = blind.model_copy(deep=True)
    tampered.evidence_items[0].content += "changed\n"
    tampered.evidence_items[0].end_line += 1
    with pytest.raises(DiagnosisSuiteError):
        verify_semantic_validation_case(case, gold, tampered)
    contrastive = make_bundle("contrastive")
    with pytest.raises(DiagnosisSuiteError):
        verify_semantic_validation_case(case, gold, contrastive)


def test_semantic_verification_rejects_stale_gold_and_peer_evidence_in_blind():
    blind = make_bundle()
    gold = semantic_case(blind, case_id="case")
    case = DiagnosisValidationSuiteCase(case_id="case", expected_route="semantic_diagnosis",
        gold_path="gold.json", gold_sha256=compute_diagnosis_gold_sha256(gold),
        subject_evidence_sha256=compute_subject_evidence_sha256(blind),
        blind_bundle_path="blind.json", blind_bundle_sha256=blind.bundle_sha256,
        contrastive_bundle_path="contrastive.json", contrastive_bundle_sha256=SHA,
        peer_selection_path="selection.json", peer_selection_sha256=SHA,
        peer_artifact_store_path="support/results")
    raw = gold.model_dump(mode="json")
    raw["semantic_gold"]["required_evidence"][0]["acceptable_locators"][0]["path"] = "stale.py"
    stale = DiagnosisGoldCase.model_validate(raw)
    stale_case = case.model_copy(update={"gold_sha256": compute_diagnosis_gold_sha256(stale)})
    with pytest.raises(DiagnosisSuiteError):
        verify_semantic_validation_case(stale_case, stale, blind)

    peer_item = make_bundle("contrastive").evidence_items[-1]
    peer_blind = blind.model_copy(deep=True)
    peer_blind.evidence_items.append(peer_item)
    peer_blind.bundle_sha256 = compute_bundle_sha256(peer_blind)
    peer_case = case.model_copy(update={"blind_bundle_sha256": peer_blind.bundle_sha256})
    with pytest.raises(DiagnosisSuiteError):
        verify_semantic_validation_case(peer_case, gold, peer_blind)
