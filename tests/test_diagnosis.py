"""Diagnosis local contracts, without compiler, provider or artifact execution."""

import inspect

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import (
    BundleProvenance, DiagnosisCertainty, DiagnosisEvidenceBundle,
    DiagnosisHypothesis, DiagnosisMode, DiagnosisRoute, DiagnosisRoutingDecision,
    DiagnosisRoutingReason, EvidenceItem, EvidenceKind, EvidenceOwner, EvidenceRef,
    EvidenceSourceState, FailureDiagnosis, FailureFamily, PeerProvenance,
    SubjectProvenance, route_run_diagnosis, summarize_patch,
)
from tests.test_failure_analysis import make_run


SHA = "a" * 64


def item_data(**changes):
    return dict(evidence_id="subject-source", kind="production_source", owner="subject",
                artifact_sha256=SHA, path="app.py", source_state="candidate",
                start_line=41, end_line=42, content="  first\nsecond\n") | changes


def peer_data():
    return dict(peer_run_id="peer", peer_patch_sha256=SHA,
                peer_candidate_snapshot_sha256=SHA, peer_evaluation_log_sha256=SHA)


def bundle_data(mode="blind", **changes):
    subject = {name: SHA for name in SubjectProvenance.model_fields}
    data = dict(schema_version=1, bundle_id="bundle", bundle_sha256=SHA, mode=mode,
                task_id="task", subject_run_id="subject", benchmark_definition_sha256=SHA,
                task_fingerprint_sha256=SHA, base_commit="base", official_evaluation_passed=False,
                agent_status="completed", peer_run_id=None, source_snapshot_policy="test-policy",
                evidence_items=[item_data()], provenance=dict(subject=subject, peer=None))
    if mode == "contrastive":
        data["peer_run_id"] = "peer"
        data["provenance"]["peer"] = peer_data()
        data["evidence_items"].append(item_data(evidence_id="peer-source", owner="peer", kind="peer_source"))
    return data | changes


def hypothesis_data(rank=1, **changes):
    return dict(rank=rank, failure_family="incorrect_local_logic", mechanism_summary="A bounded hypothesis.",
                evidence_refs=[dict(evidence_id="subject-source", start_line=41, end_line=41)],
                counterevidence_refs=[], certainty="low") | changes


def diagnosis_data(**changes):
    return dict(schema_version=1, diagnosis_id="diagnosis", bundle_sha256=SHA, mode="blind",
                subject_run_id="subject", abstain=False, abstention_reason=None,
                hypotheses=[hypothesis_data()], recommendation=None) | changes


@pytest.mark.parametrize("passed", [False, True])
@pytest.mark.parametrize("status,route,reason", [
    (AgentRunStatus.COMPLETED, "semantic_diagnosis", "semantic_failure"),
    (AgentRunStatus.COMMAND_FAILED, "operational_only", "agent_command_failed"),
    (AgentRunStatus.TIMED_OUT, "operational_only", "agent_timed_out"),
])
def test_routing_all_outcome_status_combinations(passed, status, route, reason):
    run = make_run(agent_status=status, evaluation_passed=passed)
    before = run.model_dump()
    expected = dict(run_id=run.run_id, route="unavailable" if passed else route,
                    reason="official_pass" if passed else reason)
    assert route_run_diagnosis(run).model_dump(mode="json") == expected
    assert route_run_diagnosis(run).model_dump(mode="json") == expected
    assert run.model_dump() == before


@pytest.mark.parametrize("status", list(AgentRunStatus))
def test_router_never_reads_patch_or_other_evidence(status, monkeypatch):
    run = make_run(agent_status=status, evaluation_passed=False)
    expected = route_run_diagnosis(run)
    run.patch_summary = summarize_patch("")
    assert route_run_diagnosis(run) == expected
    original = type(run).__getattribute__
    def guarded(self, name):
        if name in {"patch_summary", "evaluation_evidence", "artifacts", "provenance"}:
            pytest.fail(f"Router read forbidden evidence: {name}")
        return original(self, name)
    monkeypatch.setattr(type(run), "__getattribute__", guarded)
    assert route_run_diagnosis(run) == expected
    assert list(inspect.signature(route_run_diagnosis).parameters) == ["run"]


def test_routing_decision_rejects_contradiction_and_extra_state():
    with pytest.raises(ValidationError):
        DiagnosisRoutingDecision(run_id="run", route="semantic_diagnosis", reason="official_pass")
    with pytest.raises(ValidationError):
        DiagnosisRoutingDecision(run_id="run", route="unavailable", reason="official_pass", peer="peer")


@pytest.mark.parametrize("content,start,end", [
    ("one", 1, 1), ("one\n", 1, 1), ("one\ntwo", 41, 42),
    ("one\ntwo\n", 41, 42), ("\n", 8, 8), ("one\n\n", 8, 9),
    ("  one  ", 1, 1), ("one\r\ntwo\r\n", 4, 5), ("one\u2028two", 1, 1),
])
def test_evidence_exact_content_and_line_coordinates(content, start, end):
    item = EvidenceItem(**item_data(content=content, start_line=start, end_line=end))
    assert item.content == content
    assert EvidenceItem.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize("changes", [
    {"artifact_sha256": "bad"}, {"artifact_sha256": "A" * 64},
    {"artifact_sha256": " " + SHA}, {"evidence_id": "  "},
    {"start_line": 0}, {"end_line": 40}, {"end_line": 43},
    {"start_line": True}, {"end_line": 42.0}, {"content": ""},
    {"content": "one"}, {"content": 12}, {"source_state": "unknown"},
])
def test_invalid_evidence_items(changes):
    with pytest.raises(ValidationError):
        EvidenceItem(**item_data(**changes))


def test_optional_path_and_source_state():
    item = EvidenceItem(**item_data(path=None, source_state=None))
    assert item.path is item.source_state is None


def test_empty_canonical_patch_item_and_reference_roundtrip():
    item = EvidenceItem(**item_data(evidence_id="empty-patch", kind="canonical_patch",
        content="", start_line=None, end_line=None))
    assert item.content == ""
    assert item.start_line is item.end_line is None
    assert EvidenceItem.model_validate_json(item.model_dump_json()) == item
    reference = EvidenceRef(evidence_id="empty-patch", start_line=None, end_line=None)
    assert EvidenceRef.model_validate_json(reference.model_dump_json()) == reference
    bundle = DiagnosisEvidenceBundle(**bundle_data(evidence_items=[item]))
    assert bundle.evidence_items[0].content == ""


@pytest.mark.parametrize("content,start,end", [
    ("", 1, 1), ("x", None, None),
    ("", None, 1), ("", 1, None),
    ("x", None, 1), ("x", 1, None),
])
def test_evidence_item_rejects_inconsistent_empty_coordinates(content, start, end):
    with pytest.raises(ValidationError):
        EvidenceItem(**item_data(content=content, start_line=start, end_line=end))


@pytest.mark.parametrize("start,end", [(None, 1), (1, None)])
def test_evidence_ref_rejects_mixed_nullable_coordinates(start, end):
    with pytest.raises(ValidationError):
        EvidenceRef(evidence_id="empty-patch", start_line=start, end_line=end)


@pytest.mark.parametrize("mode", ["blind", "contrastive"])
@pytest.mark.parametrize("status", list(AgentRunStatus))
def test_semantic_bundle_requires_completed_agent(mode, status):
    data = bundle_data(mode, agent_status=status)
    if status is AgentRunStatus.COMPLETED:
        assert DiagnosisEvidenceBundle(**data).agent_status is status
    else:
        with pytest.raises(ValidationError, match="COMPLETED"):
            DiagnosisEvidenceBundle(**data)


@pytest.mark.parametrize("start,end", [(0, 1), (1, 0), (3, 2), (True, 1), (1, "2")])
def test_evidence_ref_local_ranges(start, end):
    with pytest.raises(ValidationError):
        EvidenceRef(evidence_id="evidence", start_line=start, end_line=end)


@pytest.mark.parametrize("mode", ["blind", "contrastive"])
def test_valid_bundle_and_json_roundtrip(mode):
    bundle = DiagnosisEvidenceBundle(**bundle_data(mode))
    assert DiagnosisEvidenceBundle.model_validate_json(bundle.model_dump_json()) == bundle
    assert bundle.bundle_sha256 == SHA  # Format validation, not hash construction.


@pytest.mark.parametrize("contamination", ["identity", "provenance", "owner", "peer_source", "peer_patch", "peer_evaluation"])
def test_blind_rejects_all_peer_contamination(contamination):
    data = bundle_data()
    if contamination == "identity":
        data["peer_run_id"] = "peer"
    elif contamination == "provenance":
        data["provenance"]["peer"] = peer_data()
    elif contamination == "owner":
        data["evidence_items"][0]["owner"] = "peer"
    else:
        data["evidence_items"][0]["kind"] = contamination
    with pytest.raises(ValidationError, match="blind"):
        DiagnosisEvidenceBundle(**data)


@pytest.mark.parametrize("problem", ["null_peer", "same_peer", "no_provenance", "no_evidence", "wrong_provenance_id"])
def test_contrastive_requires_local_peer_consistency(problem):
    data = bundle_data("contrastive")
    if problem == "null_peer":
        data["peer_run_id"] = None
    elif problem == "same_peer":
        data["peer_run_id"] = "subject"
    elif problem == "no_provenance":
        data["provenance"]["peer"] = None
    elif problem == "no_evidence":
        data["evidence_items"] = data["evidence_items"][:1]
    else:
        data["provenance"]["peer"]["peer_run_id"] = "different"
    with pytest.raises(ValidationError):
        DiagnosisEvidenceBundle(**data)


@pytest.mark.parametrize("changes", [
    {"official_evaluation_passed": True}, {"official_evaluation_passed": 0},
    {"evidence_items": []}, {"evidence_items": [item_data(), item_data()]},
    {"bundle_id": " "}, {"task_id": ""}, {"subject_run_id": ""},
    {"bundle_sha256": "invalid"}, {"task_fingerprint_sha256": "invalid"},
    {"benchmark_definition_sha256": "b" * 64}, {"source_snapshot_policy": " "},
    {"diagnosis_eligibility": True},
])
def test_bundle_common_invariants(changes):
    with pytest.raises(ValidationError):
        DiagnosisEvidenceBundle(**bundle_data(**changes))


@pytest.mark.parametrize("model,data", [(SubjectProvenance, {name: SHA for name in SubjectProvenance.model_fields}),
                                        (PeerProvenance, peer_data())])
def test_provenance_hashes_and_unknown_fields(model, data):
    for field in data:
        if field.endswith("sha256"):
            with pytest.raises(ValidationError):
                model(**(data | {field: "invalid"}))
    with pytest.raises(ValidationError):
        model(**(data | {"unknown": "value"}))
    assert BundleProvenance(subject={name: SHA for name in SubjectProvenance.model_fields}).peer is None


@pytest.mark.parametrize("model,factory", [(DiagnosisEvidenceBundle, bundle_data), (FailureDiagnosis, diagnosis_data)])
@pytest.mark.parametrize("version", [0, 2, True, 1.0, "1"])
def test_schema_version_is_strict_one(model, factory, version):
    with pytest.raises(ValidationError):
        model(**factory(schema_version=version))


def test_locked_enum_surfaces():
    assert [v.value for v in FailureFamily] == [
        "incorrect_local_logic", "incomplete_cross_file_repair", "partial_contract_handling",
        "state_consistency_violation", "regression_introduced", "ineffective_or_test_focused_repair",
        "other_semantic_failure",
    ]
    assert [v.value for v in DiagnosisCertainty] == ["low", "medium", "high"]
    assert [v.value for v in DiagnosisMode] == ["blind", "contrastive"]
    assert [v.value for v in DiagnosisRoute] == ["semantic_diagnosis", "operational_only", "unavailable"]
    assert [v.value for v in DiagnosisRoutingReason] == ["semantic_failure", "agent_command_failed", "agent_timed_out", "official_pass"]
    assert [v.value for v in EvidenceOwner] == ["subject", "peer", "benchmark"]
    assert [v.value for v in EvidenceSourceState] == ["base", "candidate", "frozen"]
    assert [v.value for v in EvidenceKind] == ["task_contract", "production_source", "canonical_patch", "frozen_test",
        "evaluation_output", "evaluation_case", "operational_fact", "peer_source", "peer_patch", "peer_evaluation"]


@pytest.mark.parametrize("changes", [
    {"rank": 0}, {"rank": 4}, {"rank": True}, {"rank": 1.0},
    {"evidence_refs": []}, {"mechanism_summary": " "},
    {"failure_family": "insufficient_evidence"}, {"failure_family": "quota"},
    {"failure_family": "test_failed"}, {"certainty": "certain"}, {"certainty": 0.9},
])
def test_hypothesis_invalid_states(changes):
    with pytest.raises(ValidationError):
        DiagnosisHypothesis(**hypothesis_data(**changes))


@pytest.mark.parametrize("count", [1, 2, 3])
def test_valid_ranked_diagnosis(count):
    diagnosis = FailureDiagnosis(**diagnosis_data(hypotheses=[hypothesis_data(i) for i in range(1, count + 1)]))
    assert FailureDiagnosis.model_validate_json(diagnosis.model_dump_json()) == diagnosis
    assert len(diagnosis.hypotheses) == count  # Repeated families are permitted.


def test_valid_abstention_with_optional_suggestion():
    diagnosis = FailureDiagnosis(**diagnosis_data(abstain=True, abstention_reason="Insufficient evidence.",
        hypotheses=[], recommendation="Collect more evidence."))
    assert diagnosis.abstain and not diagnosis.hypotheses


@pytest.mark.parametrize("changes", [
    {"abstain": True, "abstention_reason": "Reason"},
    {"abstain": True, "hypotheses": [], "abstention_reason": None},
    {"abstain": True, "hypotheses": [], "abstention_reason": " "},
    {"hypotheses": []}, {"abstention_reason": "Reason"},
    {"abstain": "false"},
])
def test_abstention_invalid_states(changes):
    with pytest.raises(ValidationError):
        FailureDiagnosis(**diagnosis_data(**changes))


@pytest.mark.parametrize("ranks", [[2], [1, 3], [1, 1], [3, 2, 1], [1, 2, 3, 3]])
def test_diagnosis_rejects_invalid_ranks(ranks):
    with pytest.raises(ValidationError):
        FailureDiagnosis(**diagnosis_data(hypotheses=[hypothesis_data(i) for i in ranks]))


@pytest.mark.parametrize("field", ["root_cause", "official_root_cause", "corrected_verdict", "official_verdict",
                                  "score", "new_score", "confidence_probability", "observed_facts"])
def test_diagnosis_structural_firewall(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        FailureDiagnosis.model_validate(diagnosis_data(**{field: "forbidden"}))
