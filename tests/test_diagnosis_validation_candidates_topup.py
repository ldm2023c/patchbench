"""D6.3a top-up pool invariants without encoding future Human Gold."""

import hashlib
import json
from pathlib import Path

from patchbench.agents.base import AgentRunStatus
from patchbench.application.diagnosis_peer import (
    select_contrastive_peer, verify_contrastive_peer_selection,
)
from patchbench.domain import DiagnosisEvidenceBundle, DiagnosisRoute, route_run_diagnosis
from patchbench.storage.filesystem import FilesystemArtifactStore
from scripts.prepare_diagnosis_validation_candidates import (
    ALL_IDS, LEGACY_SEMANTIC_IDS, OPERATIONAL_IDS, SEMANTIC_IDS,
    TOPUP_SEMANTIC_IDS, _HIDDEN_CROSS_FILE_PATHS, _HIDDEN_DUAL_REPAIRS,
    verify_candidate_authoring_isolation, verify_diagnosis_validation_candidates,
)


ROOT = Path("fixtures/diagnosis_validation/v1_candidates")
LEGACY_PROTECTED_TREE_SHA256 = "dd81c68b4dde5ef399dfe06c6911714be117e79ae9b7ff894f9282bdea658b6a"


def _tree_entries(names):
    entries = []
    for name in names:
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file():
                entries.append((path.relative_to(ROOT).as_posix(),
                                hashlib.sha256(path.read_bytes()).hexdigest()))
    return entries


def _entries_sha256(entries):
    material = json.dumps(entries, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def test_topup_ids_and_aggregate_machine_construction_contract_are_exact():
    assert TOPUP_SEMANTIC_IDS == tuple(f"semantic-{index:02d}" for index in range(16, 22))
    assert SEMANTIC_IDS == tuple(f"semantic-{index:02d}" for index in range(1, 22))
    assert ALL_IDS == SEMANTIC_IDS + OPERATIONAL_IDS
    assert len(_HIDDEN_CROSS_FILE_PATHS) == 2
    assert len(_HIDDEN_DUAL_REPAIRS) == 4
    assert set(_HIDDEN_CROSS_FILE_PATHS) | set(_HIDDEN_DUAL_REPAIRS) == set(TOPUP_SEMANTIC_IDS)


def test_pre_topup_candidate_assets_remain_byte_exact():
    protected = [*LEGACY_SEMANTIC_IDS,
                 *(f"_support/{case_id}" for case_id in LEGACY_SEMANTIC_IDS),
                 *OPERATIONAL_IDS]
    assert len(_tree_entries(protected)) == 294
    assert _entries_sha256(_tree_entries(protected)) == LEGACY_PROTECTED_TREE_SHA256


def test_all_new_candidates_reuse_blind_d2_and_canonical_d5_boundaries():
    identities = verify_diagnosis_validation_candidates(ROOT)
    assert set(TOPUP_SEMANTIC_IDS).issubset(identities)
    for case_id in TOPUP_SEMANTIC_IDS:
        verify_candidate_authoring_isolation(ROOT, case_id)
        metadata = json.loads((ROOT / case_id / "candidate.json").read_bytes())
        bundle = DiagnosisEvidenceBundle.model_validate_json(
            (ROOT / case_id / "blind-bundle.json").read_bytes())
        store = FilesystemArtifactStore(ROOT / "_support" / case_id / "results")
        subject = store.load_run_record(metadata["subject_run_id"])
        assert subject.agent.status is AgentRunStatus.COMPLETED
        assert not subject.evaluation_passed
        assert route_run_diagnosis(subject).route is DiagnosisRoute.SEMANTIC_DIAGNOSIS
        assert bundle.mode.value == "blind"
        assert bundle.bundle_sha256 == metadata["blind_bundle_sha256"]
        selection = select_contrastive_peer(
            subject.run_id, f"{case_id}-peers", artifact_store=store)
        verified_subject, verified_peer = verify_contrastive_peer_selection(
            selection, artifact_store=store)
        assert verified_subject.run_id == subject.run_id
        assert verified_peer.run_id == f"{case_id}-peer"


def test_all_semantic_subject_identities_are_unique_after_topup():
    identities = [json.loads((ROOT / case_id / "candidate.json").read_bytes())[
        "subject_evidence_sha256"] for case_id in SEMANTIC_IDS]
    assert len(identities) == len(set(identities)) == 21


def test_new_human_packets_contain_no_construction_role_or_peer_linkage():
    forbidden_keys = {
        "intended_construction_role", "intended_failure_family", "ambiguity_marker",
        "abstention_marker", "intended_abstention_status", "peer_run_id",
        "peer_experiment_id", "peer_run_index", "peer_selection_path",
        "peer_artifact_store_path", "preferred_family", "acceptable_families",
        "should_abstain", "required_evidence", "forbidden_claims",
    }
    forbidden_text = ("cross-file-targeted", "ambiguity-targeted",
                      "intended family", "intended abstention")
    for case_id in TOPUP_SEMANTIC_IDS:
        root = ROOT / case_id
        assert {path.name for path in root.iterdir()} == {
            "base", "blind-bundle.json", "candidate.json", "task.yaml"}
        metadata = json.loads((root / "candidate.json").read_bytes())
        assert not forbidden_keys.intersection(metadata)
        assert all(token not in path.read_text(encoding="utf-8")
                   for path in root.rglob("*") if path.is_file()
                   for token in forbidden_text)
        assert (ROOT / "_support" / case_id / "results").is_dir()
