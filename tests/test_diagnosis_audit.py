"""Auditor checks structural integrity, never semantic truth."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from patchbench.domain import (
    DiagnosisAuditIssue, DiagnosisAuditResult, DiagnosisEvidenceBundle, DiagnosisMode, FailureDiagnosis,
    audit_failure_diagnosis, canonical_json_bytes, compute_bundle_sha256, compute_diagnosis_sha256,
)
from tests.test_diagnosis import bundle_data, diagnosis_data, hypothesis_data, item_data


def audit_inputs(*, mode="blind", items=None, **diagnosis_changes):
    data = bundle_data(mode=mode)
    if items is not None:
        data["evidence_items"] = items
    bundle = DiagnosisEvidenceBundle(**data)
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    diagnosis = FailureDiagnosis(**diagnosis_data(**(dict(mode=mode,
        bundle_sha256=bundle.bundle_sha256) | diagnosis_changes)))
    return bundle, diagnosis


def test_valid_absurd_claim_passes_and_inputs_are_immutable():
    bundle, diagnosis = audit_inputs(hypotheses=[hypothesis_data(
        mechanism_summary="The moon caused the software failure.")])
    before = (bundle.model_dump(), diagnosis.model_dump())
    first = audit_failure_diagnosis(bundle, diagnosis)
    assert first.passed and first.issues == []
    assert first == audit_failure_diagnosis(bundle, diagnosis)
    assert before == (bundle.model_dump(), diagnosis.model_dump())


def test_valid_abstention_passes():
    bundle, diagnosis = audit_inputs(abstain=True, abstention_reason="Insufficient evidence.", hypotheses=[])
    assert audit_failure_diagnosis(bundle, diagnosis).passed


@pytest.mark.parametrize("role", ["evidence_refs", "counterevidence_refs"])
@pytest.mark.parametrize("empty,start,end,code", [
    (False, 42, 44, None), (False, 41, 45, None),
    (False, 40, 42, "evidence_range_out_of_bounds"),
    (False, 44, 46, "evidence_range_out_of_bounds"),
    (False, None, None, "null_range_for_nonempty_evidence"),
    (True, None, None, None), (True, 1, 1, "range_for_empty_evidence"),
])
def test_artifact_relative_ranges_and_zero_lines(role, empty, start, end, code):
    item = item_data(content="" if empty else "a\nb\nc\nd\ne\n",
                     start_line=None if empty else 41, end_line=None if empty else 45)
    valid = dict(evidence_id="subject-source", start_line=None if empty else 41,
                 end_line=None if empty else 41)
    hypothesis = hypothesis_data(evidence_refs=[valid])
    hypothesis[role] = [dict(evidence_id="subject-source", start_line=start, end_line=end)]
    bundle, diagnosis = audit_inputs(items=[item], hypotheses=[hypothesis])
    result = audit_failure_diagnosis(bundle, diagnosis)
    assert [issue.code.value for issue in result.issues] == ([] if code is None else [code])
    if code:
        issue = result.issues[0]
        assert issue.reference_role.value == role.removesuffix("_refs")
        assert (issue.hypothesis_rank, issue.reference_index, issue.evidence_id) == (1, 0, "subject-source")


@pytest.mark.parametrize("role", ["evidence_refs", "counterevidence_refs"])
def test_missing_evidence(role):
    bundle, diagnosis = audit_inputs(hypotheses=[hypothesis_data(**{
        role: [dict(evidence_id="DOES_NOT_EXIST", start_line=1, end_line=1)]})])
    assert [i.code.value for i in audit_failure_diagnosis(bundle, diagnosis).issues] == ["evidence_not_found"]


@pytest.mark.parametrize("changes,code", [
    ({"bundle_sha256": "b" * 64}, "diagnosis_bundle_hash_mismatch"),
    ({"mode": "contrastive"}, "mode_mismatch"),
    ({"subject_run_id": "other"}, "subject_run_mismatch"),
])
def test_linkage(changes, code):
    bundle, diagnosis = audit_inputs()
    diagnosis = FailureDiagnosis(**(diagnosis.model_dump() | changes))
    assert [i.code.value for i in audit_failure_diagnosis(bundle, diagnosis).issues] == [code]


@pytest.mark.parametrize("owner,kind", [("subject", "peer_source"), ("benchmark", "peer_patch"),
    ("subject", "peer_evaluation"), ("peer", "production_source")])
def test_peer_ownership_mismatch(owner, kind):
    data = bundle_data(mode="contrastive")
    data["evidence_items"].append(item_data(evidence_id="bad", owner=owner, kind=kind))
    bundle, diagnosis = audit_inputs(mode="contrastive", items=data["evidence_items"])
    result = audit_failure_diagnosis(bundle, diagnosis)
    assert [i.code.value for i in result.issues] == ["evidence_ownership_mismatch"]
    assert result.issues[0].evidence_id == "bad"


@pytest.mark.parametrize("owner", ["subject", "benchmark"])
def test_nonpeer_ownership_remains_flexible(owner):
    bundle, diagnosis = audit_inputs(items=[item_data(owner=owner)])
    assert audit_failure_diagnosis(bundle, diagnosis).passed


def test_issue_order_is_complete_deterministic_and_nonmutating():
    items = bundle_data(mode="contrastive")["evidence_items"]
    items.append(item_data(evidence_id="bad", owner="peer"))
    missing = dict(evidence_id="missing", start_line=None, end_line=None)
    out = dict(evidence_id="subject-source", start_line=1, end_line=1)
    bundle, diagnosis = audit_inputs(mode="contrastive", items=items, hypotheses=[
        hypothesis_data(evidence_refs=[missing, out], counterevidence_refs=[out, missing]),
        hypothesis_data(rank=2, evidence_refs=[missing])])
    bundle.bundle_sha256 = "c" * 64
    diagnosis.mode = DiagnosisMode.BLIND
    diagnosis.subject_run_id = "different"
    before = (bundle.model_dump(), diagnosis.model_dump())
    result = audit_failure_diagnosis(bundle, diagnosis)
    assert [i.code.value for i in result.issues] == ["bundle_hash_mismatch",
        "diagnosis_bundle_hash_mismatch", "mode_mismatch", "subject_run_mismatch",
        "evidence_ownership_mismatch", "evidence_not_found", "evidence_range_out_of_bounds",
        "evidence_range_out_of_bounds", "evidence_not_found", "evidence_not_found"]
    assert [(i.hypothesis_rank, i.reference_role.value, i.reference_index) for i in result.issues[5:]] == [
        (1, "evidence", 0), (1, "evidence", 1), (1, "counterevidence", 0),
        (1, "counterevidence", 1), (2, "evidence", 0)]
    assert result == audit_failure_diagnosis(bundle, diagnosis)
    assert before == (bundle.model_dump(), diagnosis.model_dump())
    assert result.bundle_sha256 == "c" * 64
    assert result.computed_bundle_sha256 == compute_bundle_sha256(bundle)


def test_hashes_match_independent_complete_canonical_serialization():
    bundle, diagnosis = audit_inputs(recommendation="雪")
    def independent(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    data = bundle.model_dump(mode="json")
    data.pop("bundle_sha256")
    assert compute_bundle_sha256(bundle) == hashlib.sha256(independent(data)).hexdigest()
    assert compute_diagnosis_sha256(diagnosis) == hashlib.sha256(independent(diagnosis.model_dump(mode="json"))).hexdigest()
    assert canonical_json_bytes({"雪": [1], "a": 2}) == b'{"a":2,"\xe9\x9b\xaa":[1]}'
    bundle.bundle_sha256 = "d" * 64
    assert compute_bundle_sha256(bundle) == hashlib.sha256(independent(data)).hexdigest()
    diagnosis.recommendation = "changed"
    assert compute_diagnosis_sha256(diagnosis) != hashlib.sha256(independent(
        diagnosis_data(bundle_sha256=compute_bundle_sha256(bundle), recommendation="雪"))).hexdigest()


@pytest.mark.parametrize("changes", [{"passed": False}, {"passed": 1}, {"schema_version": True},
    {"schema_version": 2}, {"schema_version": "1"}, {"extra": "no"},
    {"issues": [dict(code="evidence_not_found", detail="Missing.")]}])
def test_audit_result_invariants(changes):
    bundle, diagnosis = audit_inputs()
    result = audit_failure_diagnosis(bundle, diagnosis)
    with pytest.raises(ValidationError):
        DiagnosisAuditResult(**(result.model_dump() | changes))


@pytest.mark.parametrize("changes", [{"code": "semantic_error"}, {"detail": " "},
    {"reference_index": -1}, {"reference_index": True}, {"hypothesis_rank": 0}, {"extra": 1}])
def test_issue_strict_contract(changes):
    with pytest.raises(ValidationError):
        DiagnosisAuditIssue(**(dict(code="evidence_not_found", detail="Missing.") | changes))
