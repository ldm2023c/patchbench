"""D6.3b-1 final selection and pre-Contrastive Gold lock."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_gold_lock import (
    DiagnosisGoldLockError, OPERATIONAL_CASE_IDS, SELECTED_CASE_IDS,
    SEMANTIC_CASE_IDS, build_diagnosis_gold_lock, verify_diagnosis_gold_lock,
)
from patchbench.application.diagnosis_validation import (
    compute_diagnosis_gold_sha256, compute_subject_evidence_sha256,
    validate_semantic_gold_evidence,
)
from patchbench.domain import (
    DiagnosisEvidenceBundle, DiagnosisGoldCase, DiagnosisGoldLockCase,
    DiagnosisGoldLockManifest, DiagnosisGoldLockSuite, FrozenValidationFile,
    compute_bundle_sha256, compute_diagnosis_gold_lock_suite_sha256,
)


CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")
GOLD = Path("fixtures/diagnosis_validation/v1_human_gold_drafts")
AUTHORING_RECORD = GOLD / "human-gold-authoring-record.md"
SHA = "a" * 64
GOLD_TREE_SHA256 = "b214dfc8184a92e1de1926e3a6121f48b0d7d56fba2859d57319dacc5b507726"


def tree_identity(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def rewrite_manifest(root):
    suite = DiagnosisGoldLockSuite.model_validate_json((root / "suite.json").read_bytes())
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()
                       and item.name != "gold-lock-manifest.json"):
        raw = path.read_bytes()
        entries.append(FrozenValidationFile(
            path=path.relative_to(root).as_posix(),
            sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw)))
    manifest = DiagnosisGoldLockManifest(
        suite_sha256=compute_diagnosis_gold_lock_suite_sha256(suite),
        selected_case_ids=list(SELECTED_CASE_IDS), files=entries)
    (root / "gold-lock-manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False,
                   sort_keys=True, indent=2) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def locked_tree(tmp_path_factory):
    root = tmp_path_factory.mktemp("diagnosis-gold-lock") / "v1"
    build_diagnosis_gold_lock(CANDIDATES, GOLD, AUTHORING_RECORD, root)
    return root


def test_checked_gold_lock_has_exact_selection_composition_and_identity(locked_tree):
    suite = verify_diagnosis_gold_lock(locked_tree)
    assert tuple(case.case_id for case in suite.cases) == SELECTED_CASE_IDS
    assert len(SEMANTIC_CASE_IDS) == 13
    assert len(OPERATIONAL_CASE_IDS) == 2
    golds = {
        case.case_id: DiagnosisGoldCase.model_validate_json(
            (locked_tree / (case.gold_path or case.route_gold_path)).read_bytes())
        for case in suite.cases
    }
    semantic_gold = [golds[case_id].semantic_gold for case_id in SEMANTIC_CASE_IDS]
    assert sum(not gold.should_abstain for gold in semantic_gold) == 10
    assert sum(gold.should_abstain for gold in semantic_gold) == 3
    assert Counter(gold.preferred_family for gold in semantic_gold if not gold.should_abstain) == {
        "incorrect_local_logic": 2,
        "incomplete_cross_file_repair": 2,
        "partial_contract_handling": 2,
        "state_consistency_violation": 2,
        "regression_introduced": 2,
    }
    assert len({case.subject_evidence_sha256 for case in suite.cases[:13]}) == 13


def test_semantic_sources_are_byte_exact_and_d61_validated(locked_tree):
    suite = verify_diagnosis_gold_lock(locked_tree)
    for case in suite.cases[:13]:
        candidate = json.loads((CANDIDATES / case.case_id / "candidate.json").read_bytes())
        locked_bundle = locked_tree / case.blind_bundle_path
        source_bundle = CANDIDATES / case.case_id / "blind-bundle.json"
        locked_gold = locked_tree / case.gold_path
        source_gold = GOLD / case.case_id / "gold.json"
        assert locked_bundle.read_bytes() == source_bundle.read_bytes()
        assert locked_gold.read_bytes() == source_gold.read_bytes()
        bundle = DiagnosisEvidenceBundle.model_validate_json(locked_bundle.read_bytes())
        gold = DiagnosisGoldCase.model_validate_json(locked_gold.read_bytes())
        assert compute_bundle_sha256(bundle) == candidate["blind_bundle_sha256"]
        assert compute_subject_evidence_sha256(bundle) == candidate["subject_evidence_sha256"]
        assert gold.subject_evidence_sha256 == candidate["subject_evidence_sha256"]
        assert compute_diagnosis_gold_sha256(gold) == case.gold_sha256
        validate_semantic_gold_evidence(bundle, gold)
        assert all(locator.owner.value != "peer"
                   for requirement in gold.semantic_gold.required_evidence
                   for locator in requirement.acceptable_locators)
        if gold.semantic_gold.should_abstain:
            assert gold.semantic_gold.preferred_family is None
            assert gold.semantic_gold.acceptable_families == []
            assert gold.semantic_gold.required_evidence == []


def test_operational_sources_are_byte_exact_and_routes_are_locked(locked_tree):
    suite = verify_diagnosis_gold_lock(locked_tree)
    operational = suite.cases[13:]
    assert {case.expected_routing_reason.value for case in operational} == {
        "agent_command_failed", "agent_timed_out"}
    for case in operational:
        assert (locked_tree / case.run_record_path).read_bytes() == (
            CANDIDATES / case.case_id / "run-record.json").read_bytes()
        assert (locked_tree / case.route_gold_path).read_bytes() == (
            CANDIDATES / case.case_id / "route-gold.json").read_bytes()


def test_lock_tree_has_no_unselected_case_or_contrastive_metadata(locked_tree):
    suite_raw = (locked_tree / "suite.json").read_text(encoding="utf-8")
    manifest_raw = (locked_tree / "gold-lock-manifest.json").read_text(encoding="utf-8")
    suite = json.loads(suite_raw)
    manifest = json.loads(manifest_raw)
    suite_keys = {key for case in suite["cases"] for key in case}
    assert {path.name for path in (locked_tree / "cases").iterdir()} == set(SELECTED_CASE_IDS)
    assert not {f"semantic-{index:02d}" for index in range(18, 22)}.intersection(
        path.name for path in (locked_tree / "cases").iterdir())
    assert not any("contrastive" in key or key.startswith("peer_") for key in suite_keys)
    assert "_support" not in suite_raw
    assert not any("contrastive" in item["path"] or "peer_" in item["path"]
                   for item in manifest["files"])
    assert "_support" not in manifest_raw
    assert not (locked_tree / "freeze-manifest.json").exists()


def test_gold_tree_remains_byte_exact():
    entries = sorted(tree_identity(GOLD).items())
    digest = hashlib.sha256(json.dumps(
        entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert len(entries) == 26
    assert digest == GOLD_TREE_SHA256


def test_candidate_pool_has_no_worktree_mutation():
    path = CANDIDATES.as_posix()
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", path], check=False)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", path],
        check=True, capture_output=True, text=True)
    assert changed.returncode == 0
    assert untracked.stdout == ""


def test_two_clean_builds_equal_each_other(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    build_diagnosis_gold_lock(CANDIDATES, GOLD, AUTHORING_RECORD, first)
    build_diagnosis_gold_lock(CANDIDATES, GOLD, AUTHORING_RECORD, second)
    assert tree_identity(first) == tree_identity(second)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "extra_directory", "tampered", "symlink"],
)
def test_tree_tampering_and_unsafe_entries_are_rejected(tmp_path, locked_tree, mutation):
    copied = tmp_path / "lock"
    shutil.copytree(locked_tree, copied)
    target = copied / "cases/semantic-01/gold.json"
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (copied / "extra.json").write_text("{}")
    elif mutation == "extra_directory":
        (copied / "extra-directory").mkdir()
    elif mutation == "tampered":
        target.write_bytes(target.read_bytes() + b" ")
    else:
        link_target = tmp_path / "target"
        link_target.write_text("x")
        (copied / "link").symlink_to(link_target)
    with pytest.raises(DiagnosisGoldLockError):
        verify_diagnosis_gold_lock(copied)


def test_coherently_relinked_missing_case_file_is_rejected(tmp_path, locked_tree):
    copied = tmp_path / "lock"
    shutil.copytree(locked_tree, copied)
    suite_path = copied / "suite.json"
    raw = json.loads(suite_path.read_bytes())
    raw["cases"][0]["gold_path"] = "cases/semantic-01/missing.json"
    suite_path.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    rewrite_manifest(copied)
    with pytest.raises(DiagnosisGoldLockError, match="missing_file"):
        verify_diagnosis_gold_lock(copied)


def test_nonregular_file_is_rejected(tmp_path, locked_tree):
    copied = tmp_path / "lock"
    shutil.copytree(locked_tree, copied)
    os.mkfifo(copied / "fifo")
    with pytest.raises(DiagnosisGoldLockError, match="non-regular"):
        verify_diagnosis_gold_lock(copied)


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a\\b",
                                   "a//b", "a/./b", " path", "path ", "a:b"])
def test_gold_lock_paths_reject_without_normalization(path):
    with pytest.raises(ValidationError):
        FrozenValidationFile(path=path, sha256=SHA, byte_length=0)


def test_manifest_rejects_duplicate_paths_and_self_reference():
    entry = FrozenValidationFile(path="suite.json", sha256=SHA, byte_length=1)
    with pytest.raises(ValidationError):
        DiagnosisGoldLockManifest(suite_sha256=SHA, selected_case_ids=["case"],
                                  files=[entry, entry])
    with pytest.raises(ValidationError):
        DiagnosisGoldLockManifest(suite_sha256=SHA, selected_case_ids=["case"], files=[
            entry, FrozenValidationFile(
                path="gold-lock-manifest.json", sha256=SHA, byte_length=1)])


def test_relinked_suite_tampering_is_rejected_by_case_validation(tmp_path, locked_tree):
    copied = tmp_path / "lock"
    shutil.copytree(locked_tree, copied)
    suite_path = copied / "suite.json"
    raw = json.loads(suite_path.read_bytes())
    raw["cases"][0]["subject_evidence_sha256"] = "f" * 64
    suite_path.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    rewrite_manifest(copied)
    with pytest.raises(DiagnosisGoldLockError, match="invalid_case"):
        verify_diagnosis_gold_lock(copied)


def test_authoring_record_hash_disagreement_fails_without_output(tmp_path):
    record = tmp_path / "record.md"
    text = AUTHORING_RECORD.read_text(encoding="utf-8")
    source_hash = compute_diagnosis_gold_sha256(DiagnosisGoldCase.model_validate_json(
        (GOLD / SEMANTIC_CASE_IDS[0] / "gold.json").read_bytes()))
    record.write_text(text.replace(source_hash, "f" * 64, 1), encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(DiagnosisGoldLockError, match="authoring_record_mismatch"):
        build_diagnosis_gold_lock(CANDIDATES, GOLD, record, output)
    assert not output.exists()
