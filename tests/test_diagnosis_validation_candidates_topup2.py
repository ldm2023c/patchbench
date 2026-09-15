"""D6.3a Top-up2 observational-equivalence and isolation invariants."""

import hashlib
import json
from pathlib import Path

from patchbench.agents.base import AgentRunStatus
from patchbench.application.diagnosis_peer import (
    select_contrastive_peer, verify_contrastive_peer_selection,
)
from patchbench.domain import DiagnosisEvidenceBundle, DiagnosisRoute, route_run_diagnosis
from patchbench.storage.filesystem import FilesystemArtifactStore
import scripts.prepare_diagnosis_validation_candidates as candidate_module
from scripts.prepare_diagnosis_validation_candidates import (
    ALL_IDS, OPERATIONAL_IDS, SEMANTIC_IDS, TOPUP2_SEMANTIC_IDS,
    _HIDDEN_AMBIGUITY_PATHS, _HIDDEN_CONTROL_PATHS,
    prepare_diagnosis_validation_candidates, verify_candidate_authoring_isolation,
    verify_diagnosis_validation_candidates,
)


ROOT = Path("fixtures/diagnosis_validation/v1_candidates")
GOLD_ROOT = Path("fixtures/diagnosis_validation/v1_human_gold_drafts")
PRE_TOPUP2_TREE_SHA256 = "e6a48d8f787693bcba535957852e82b8abb32e1637d07d4165141a94305d833d"
LOCKED_GOLD_TREE_SHA256 = "8c3ac1a280e7d8ea8d4ba0f892194a0141bf0f9ad55e5254541504ea3ef0c43d"


def _tree_entries(root, names=None):
    paths = (sorted(root.rglob("*")) if names is None else
             [path for name in names for path in sorted((root / name).rglob("*"))])
    return [(path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
            for path in paths if path.is_file()]


def _entries_sha256(entries):
    material = json.dumps(entries, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def test_topup2_pool_and_private_role_mix_are_exact():
    assert TOPUP2_SEMANTIC_IDS == tuple(f"semantic-{index:02d}" for index in range(22, 30))
    assert SEMANTIC_IDS == tuple(f"semantic-{index:02d}" for index in range(1, 30))
    assert ALL_IDS == SEMANTIC_IDS + OPERATIONAL_IDS
    assert len(_HIDDEN_AMBIGUITY_PATHS) == 5
    assert len(_HIDDEN_CONTROL_PATHS) == 3
    assert set(_HIDDEN_AMBIGUITY_PATHS).isdisjoint(_HIDDEN_CONTROL_PATHS)
    assert set(_HIDDEN_AMBIGUITY_PATHS) | set(_HIDDEN_CONTROL_PATHS) == set(
        TOPUP2_SEMANTIC_IDS)
    assert sum(paths[0][1] != paths[1][1]
               for paths in _HIDDEN_AMBIGUITY_PATHS.values()) >= 4
    assert all(paths[0] == paths[1] for paths in _HIDDEN_CONTROL_PATHS.values())


def test_all_pre_topup2_candidate_assets_remain_byte_exact():
    protected = [
        *(f"semantic-{index:02d}" for index in range(1, 22)),
        *(f"_support/semantic-{index:02d}" for index in range(1, 22)),
        *OPERATIONAL_IDS,
    ]
    entries = _tree_entries(ROOT, protected)
    assert len(entries) == 416
    assert _entries_sha256(entries) == PRE_TOPUP2_TREE_SHA256


def test_locked_human_gold_tree_remains_byte_exact():
    entries = _tree_entries(GOLD_ROOT)
    assert len(entries) == 18
    assert _entries_sha256(entries) == LOCKED_GOLD_TREE_SHA256


def test_topup2_generation_runs_exact_private_verifiers(tmp_path, monkeypatch):
    ambiguity_calls = []
    control_calls = []
    original_ambiguity = candidate_module._verify_observational_equivalence
    original_control = candidate_module._verify_identifiable_control

    def verify_ambiguity(*args, **kwargs):
        ambiguity_calls.append(args[1])
        return original_ambiguity(*args, **kwargs)

    def verify_control(*args, **kwargs):
        control_calls.append(args[1])
        return original_control(*args, **kwargs)

    monkeypatch.setattr(candidate_module, "_verify_observational_equivalence", verify_ambiguity)
    monkeypatch.setattr(candidate_module, "_verify_identifiable_control", verify_control)
    prepare_diagnosis_validation_candidates(tmp_path / "generated")
    assert set(ambiguity_calls) == set(_HIDDEN_AMBIGUITY_PATHS)
    assert len(ambiguity_calls) == 5
    assert set(control_calls) == set(_HIDDEN_CONTROL_PATHS)
    assert len(control_calls) == 3


def test_all_topup2_candidates_reuse_d2_and_d5_boundaries():
    identities = verify_diagnosis_validation_candidates(ROOT)
    assert set(TOPUP2_SEMANTIC_IDS).issubset(identities)
    for case_id in TOPUP2_SEMANTIC_IDS:
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
        assert verified_peer.evaluation_passed


def test_all_29_semantic_subject_identities_are_unique():
    identities = [json.loads((ROOT / case_id / "candidate.json").read_bytes())[
        "subject_evidence_sha256"] for case_id in SEMANTIC_IDS]
    assert len(identities) == len(set(identities)) == 29


def test_topup2_human_packets_do_not_expose_private_construction_state():
    forbidden_keys = {
        "hidden_runtime_world", "hidden_selector", "hidden_causal_path",
        "alternative_hypothesis", "intended_construction_role",
        "intended_failure_family", "ambiguity_marker", "abstention_marker",
        "intended_abstention_status", "peer_run_id", "peer_experiment_id",
        "peer_run_index", "peer_selection_path", "peer_artifact_store_path",
        "preferred_family", "acceptable_families", "should_abstain",
        "required_evidence", "forbidden_claims",
    }
    forbidden_text = (
        "hidden runtime", "hidden selector", "hidden causal", "world_a", "world_b",
        "ambiguity-targeted", "control-targeted", "alternative hypothesis",
    )
    for case_id in TOPUP2_SEMANTIC_IDS:
        root = ROOT / case_id
        assert {path.name for path in root.iterdir()} == {
            "base", "blind-bundle.json", "candidate.json", "task.yaml"}
        metadata = json.loads((root / "candidate.json").read_bytes())
        assert not forbidden_keys.intersection(metadata)
        assert all(token not in path.read_text(encoding="utf-8").lower()
                   for path in root.rglob("*") if path.is_file()
                   for token in forbidden_text)
        assert (ROOT / "_support" / case_id / "results").is_dir()
