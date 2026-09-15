"""Controlled draft candidate pool, D2 Blind evidence, and D5 readiness."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.domain import DiagnosisEvidenceBundle, DiagnosisRoute, route_run_diagnosis
from patchbench.storage.filesystem import FilesystemArtifactStore
from scripts.prepare_diagnosis_validation_candidates import (
    ALL_IDS, OPERATIONAL_IDS, SEMANTIC_IDS, CandidateVerificationError,
    prepare_diagnosis_validation_candidates, verify_candidate_authoring_isolation,
    verify_diagnosis_validation_candidates,
)


ROOT = Path("fixtures/diagnosis_validation/v1_candidates")


def tree_identity(root: Path):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_checked_candidate_pool_is_exact_and_fully_verified():
    identities = verify_diagnosis_validation_candidates(ROOT)
    assert tuple(identities) == ALL_IDS
    assert len(set(identities[case_id] for case_id in SEMANTIC_IDS)) == 29
    inventory = json.loads((ROOT / "candidate-inventory.json").read_bytes())
    assert [item["candidate_id"] for item in inventory["candidates"]] == list(ALL_IDS)
    assert sum(item["expected_route"] == "semantic_diagnosis"
               for item in inventory["candidates"]) == 29
    assert sum(item["expected_route"] == "operational_only"
               for item in inventory["candidates"]) == 2
    subject_hashes = {
        json.loads((ROOT / case_id / "candidate.json").read_bytes())["subject_evidence_sha256"]
        for case_id in SEMANTIC_IDS
    }
    assert len(subject_hashes) == 29


def test_semantic_authoring_assets_are_blind_fail_completed_without_gold_answers():
    forbidden = {"preferred_family", "acceptable_families", "should_abstain",
                 "required_evidence", "forbidden_claims", "intended construction family"}
    for case_id in SEMANTIC_IDS:
        case_root = ROOT / case_id
        bundle = DiagnosisEvidenceBundle.model_validate_json(
            (case_root / "blind-bundle.json").read_bytes())
        metadata = json.loads((case_root / "candidate.json").read_bytes())
        run = FilesystemArtifactStore(ROOT / "_support" / case_id / "results").load_run_record(
            metadata["subject_run_id"])
        assert route_run_diagnosis(run).route is DiagnosisRoute.SEMANTIC_DIAGNOSIS
        assert run.agent.status is AgentRunStatus.COMPLETED
        assert not run.evaluation_passed
        assert bundle.mode.value == "blind"
        assert not bundle.official_evaluation_passed
        assert all(item.owner.value != "peer" for item in bundle.evidence_items)
        assert not any("contrastive" in path.name.lower() for path in case_root.rglob("*"))
        assert not any(path.name in {"gold.json", "semantic-gold.json"}
                       for path in case_root.rglob("*"))
        metadata_text = (case_root / "candidate.json").read_text()
        assert all(value not in metadata_text for value in forbidden)
        verify_candidate_authoring_isolation(ROOT, case_id)


def test_human_authoring_directories_are_isolated_from_machine_peer_support():
    for case_id in SEMANTIC_IDS:
        authoring = ROOT / case_id
        assert {path.name for path in authoring.iterdir()} == {
            "base", "blind-bundle.json", "candidate.json", "task.yaml"}
        metadata = json.loads((authoring / "candidate.json").read_bytes())
        assert not {"peer_run_id", "peer_experiment_id", "peer_run_index",
                    "peer_selection_path", "peer_artifact_store_path"}.intersection(metadata)
        support = ROOT / "_support" / case_id / "results"
        assert (support / f"{case_id}-subject/metadata.json").is_file()
        assert (support / f"{case_id}-peer/patch.diff").is_file()
        assert (support / f"experiments/{case_id}-peers/metadata.json").is_file()
    assert not any("contrastive" in path.name.lower() for path in ROOT.rglob("*"))
    assert not any(path.name in {"gold.json", "semantic-gold.json"} for path in ROOT.rglob("*"))
    readme = (ROOT / "README.md").read_text()
    for text in ("inspect only", "Blind Bundle", "Do not", "_support/",
                 "generator", "candidate-construction tests", "identity locked"):
        assert text in readme


@pytest.mark.parametrize("exposure", ["peer_linkage", "peer_patch", "experiment",
                                      "contrastive_bundle", "semantic_answer"])
def test_authoring_isolation_rejects_post_gold_exposure(tmp_path, exposure):
    copied = tmp_path / "candidates"
    shutil.copytree(ROOT, copied)
    case_root = copied / "semantic-01"
    if exposure in {"peer_linkage", "semantic_answer"}:
        path = case_root / "candidate.json"
        metadata = json.loads(path.read_bytes())
        metadata["peer_run_id" if exposure == "peer_linkage" else "preferred_family"] = (
            "semantic-01-peer" if exposure == "peer_linkage" else "incorrect_local_logic")
        path.write_text(json.dumps(metadata))
    elif exposure == "peer_patch":
        (case_root / "peer.patch").write_text("peer evidence")
    elif exposure == "experiment":
        (case_root / "experiment.json").write_text("{}")
    else:
        (case_root / "contrastive-bundle.json").write_text("{}")
    with pytest.raises(CandidateVerificationError):
        verify_candidate_authoring_isolation(copied, "semantic-01")


def test_operational_candidates_have_exact_controlled_routes():
    expected = {"operational-01": "agent_command_failed",
                "operational-02": "agent_timed_out"}
    for case_id in OPERATIONAL_IDS:
        run = next((ROOT / case_id).glob("run-record.json"))
        from patchbench.domain import RunRecord
        decision = route_run_diagnosis(RunRecord.model_validate_json(run.read_bytes()))
        assert decision.route.value == "operational_only"
        assert decision.reason.value == expected[case_id]


def test_candidate_generation_is_byte_deterministic(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    prepare_diagnosis_validation_candidates(first)
    prepare_diagnosis_validation_candidates(second)
    assert tree_identity(first) == tree_identity(second)
    assert tree_identity(first) == tree_identity(ROOT)
    assert verify_diagnosis_validation_candidates(first) == verify_diagnosis_validation_candidates(second)


def test_candidate_verifier_fails_on_bundle_tampering(tmp_path):
    copied = tmp_path / "candidates"
    shutil.copytree(ROOT, copied)
    path = copied / "semantic-01/blind-bundle.json"
    raw = json.loads(path.read_bytes())
    raw["bundle_sha256"] = "f" * 64
    path.write_text(json.dumps(raw))
    with pytest.raises(CandidateVerificationError):
        verify_diagnosis_validation_candidates(copied)


def test_candidate_area_is_draft_and_has_no_final_freeze_manifest():
    assert "not a frozen validation suite" in (ROOT / "README.md").read_text()
    assert not (ROOT / "freeze-manifest.json").exists()
    assert not Path("validation/diagnosis/v1/freeze-manifest.json").exists()
