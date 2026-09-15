"""D6.3b-2 two-phase Contrastive fairness review and freeze finalization."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from patchbench.application.diagnosis_gold_lock import (
    SEMANTIC_CASE_IDS,
    build_diagnosis_gold_lock,
)
from patchbench.application.diagnosis_suite import (
    DiagnosisSuiteError,
    finalize_diagnosis_validation_freeze,
    prepare_contrastive_fairness_review,
    verify_contrastive_fairness_review,
    verify_diagnosis_validation_freeze,
)
from patchbench.application.diagnosis_validation import (
    compute_diagnosis_gold_sha256,
    compute_subject_evidence_sha256,
    validate_semantic_gold_evidence,
)
from patchbench.domain import (
    ContrastiveFairnessReview,
    DiagnosisEvidenceBundle,
    DiagnosisGoldCase,
    DiagnosisGoldLockManifest,
    EvidenceOwner,
    compute_bundle_sha256,
)


CANDIDATES = Path("fixtures/diagnosis_validation/v1_candidates")
GOLD = Path("fixtures/diagnosis_validation/v1_human_gold_drafts")
AUTHORING_RECORD = GOLD / "human-gold-authoring-record.md"
PHASE_A = Path("validation/diagnosis/v1")


@pytest.fixture(scope="module")
def prepared_tree(tmp_path_factory):
    root = tmp_path_factory.mktemp("diagnosis-two-phase") / "v1"
    build_diagnosis_gold_lock(CANDIDATES, GOLD, AUTHORING_RECORD, root)
    prepare_contrastive_fairness_review(root, CANDIDATES)
    return root


def tree_identity(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def load_review(root: Path) -> ContrastiveFairnessReview:
    return ContrastiveFairnessReview.model_validate_json(
        (root / "contrastive-fairness-review.json").read_bytes())


def write_review(root: Path, review: ContrastiveFairnessReview) -> None:
    (root / "contrastive-fairness-review.json").write_text(
        json.dumps(review.model_dump(mode="json"), ensure_ascii=False,
                   sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def confirm_all(root: Path, *, except_index: int | None = None, rejected: bool = False) -> None:
    review = load_review(root)
    cases = []
    for index, case in enumerate(review.cases):
        status = "confirmed"
        if except_index is not None and index == except_index:
            status = "rejected" if rejected else "pending"
        cases.append(case.model_copy(update={"human_fairness_status": status}))
    write_review(root, review.model_copy(update={"cases": cases}))


def protected_head_identity() -> dict[str, str]:
    manifest = DiagnosisGoldLockManifest.model_validate_json(
        subprocess.check_output([
            "git", "show", "HEAD:validation/diagnosis/v1/gold-lock-manifest.json"]))
    result = {"gold-lock-manifest.json": hashlib.sha256(
        subprocess.check_output([
            "git", "show", "HEAD:validation/diagnosis/v1/gold-lock-manifest.json"]))
        .hexdigest()}
    for item in manifest.files:
        raw = subprocess.check_output([
            "git", "show", f"HEAD:validation/diagnosis/v1/{item.path}"])
        result[item.path] = hashlib.sha256(raw).hexdigest()
    return result


def test_checked_phase_a_tree_has_pending_review_and_no_freeze_manifest():
    review = verify_contrastive_fairness_review(PHASE_A, CANDIDATES)
    assert [case.case_id for case in review.cases] == list(SEMANTIC_CASE_IDS)
    assert {case.human_fairness_status for case in review.cases} == {"pending"}
    assert all(case.machine_integrity_passed for case in review.cases)
    assert len(list(PHASE_A.glob("cases/semantic-*/contrastive-bundle.json"))) == 13
    assert (PHASE_A / "contrastive-fairness-review.md").exists()
    assert not (PHASE_A / "freeze-manifest.json").exists()


def test_phase_a_contains_no_raw_copied_support_or_final_case_records():
    paths = [path.relative_to(PHASE_A).as_posix() for path in PHASE_A.rglob("*")]
    assert not any(path == "support" or path.startswith("support/") for path in paths)
    assert not any("_support" in path for path in paths)
    assert not any(path.endswith("/metadata.json") for path in paths)
    assert not any(path.endswith("/patch.diff") for path in paths)
    assert not any(path.endswith("/test.log") for path in paths)
    assert not any(path.endswith("/case.json") for path in paths)
    for case_id in SEMANTIC_CASE_IDS:
        assert {path.name for path in (PHASE_A / "cases" / case_id).iterdir()} == {
            "blind-bundle.json", "contrastive-bundle.json", "gold.json"}
    assert {path.name for path in (PHASE_A / "cases/operational-01").iterdir()} == {
        "route-gold.json", "run-record.json"}


def test_pre_contrastive_locked_files_remain_byte_identical_to_head():
    current = tree_identity(PHASE_A)
    for path, digest in protected_head_identity().items():
        assert current[path] == digest


def test_phase_a_determinism_and_preparation_never_auto_confirms(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        build_diagnosis_gold_lock(CANDIDATES, GOLD, AUTHORING_RECORD, root)
        prepare_contrastive_fairness_review(root, CANDIDATES)
    assert tree_identity(first) == tree_identity(second)
    assert {case.human_fairness_status for case in load_review(first).cases} == {"pending"}
    assert not (first / "freeze-manifest.json").exists()


def test_contrastive_bundles_preserve_locked_subject_gold_fairness(prepared_tree):
    review = verify_contrastive_fairness_review(prepared_tree, CANDIDATES)
    for case in review.cases:
        blind = DiagnosisEvidenceBundle.model_validate_json(
            (prepared_tree / f"cases/{case.case_id}/blind-bundle.json").read_bytes())
        contrastive = DiagnosisEvidenceBundle.model_validate_json(
            (prepared_tree / f"cases/{case.case_id}/contrastive-bundle.json").read_bytes())
        gold = DiagnosisGoldCase.model_validate_json(
            (prepared_tree / f"cases/{case.case_id}/gold.json").read_bytes())
        assert contrastive.mode.value == "contrastive"
        assert compute_bundle_sha256(contrastive) == contrastive.bundle_sha256
        assert compute_subject_evidence_sha256(contrastive) == compute_subject_evidence_sha256(blind)
        assert validate_semantic_gold_evidence(blind, gold) is None
        assert validate_semantic_gold_evidence(contrastive, gold) is None
        assert compute_diagnosis_gold_sha256(gold) == case.locked_gold_sha256
        assert any(item.owner is EvidenceOwner.PEER for item in contrastive.evidence_items)


def test_pending_partial_and_rejected_reviews_cannot_finalize(prepared_tree, tmp_path):
    for mutation, reason in [("pending", "human_fairness_pending"),
                             ("partial", "human_fairness_pending"),
                             ("rejected", "human_fairness_rejected")]:
        copied = tmp_path / mutation
        shutil.copytree(prepared_tree, copied)
        if mutation == "partial":
            confirm_all(copied, except_index=0)
        elif mutation == "rejected":
            confirm_all(copied, except_index=0, rejected=True)
        with pytest.raises(DiagnosisSuiteError) as caught:
            finalize_diagnosis_validation_freeze(copied, CANDIDATES)
        assert caught.value.reason.value == reason
        assert not (copied / "freeze-manifest.json").exists()


def test_all_confirmed_can_finalize_and_is_deterministic(prepared_tree, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    shutil.copytree(prepared_tree, first)
    shutil.copytree(prepared_tree, second)
    confirm_all(first)
    confirm_all(second)
    manifest = finalize_diagnosis_validation_freeze(first, CANDIDATES)
    finalize_diagnosis_validation_freeze(second, CANDIDATES)
    assert tree_identity(first) == tree_identity(second)
    assert verify_diagnosis_validation_freeze(first, CANDIDATES) == manifest
    assert len(manifest.files) + 1 == sum(1 for path in first.rglob("*") if path.is_file())
    assert not any(item.path.startswith("support/") or "_support" in item.path
                   for item in manifest.files)


def test_source_support_drift_fails_verification(prepared_tree, tmp_path):
    copied = tmp_path / "suite"
    support = tmp_path / "support"
    shutil.copytree(prepared_tree, copied)
    shutil.copytree(CANDIDATES, support)
    path = support / "_support/semantic-01/results/semantic-01-peer/test.log"
    path.write_bytes(path.read_bytes() + b"drift\n")
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_contrastive_fairness_review(copied, support)
    assert caught.value.reason.value == "invalid_case"


def test_contrastive_and_fairness_artifact_tampering_fail(prepared_tree, tmp_path):
    copied = tmp_path / "suite"
    shutil.copytree(prepared_tree, copied)
    bundle_path = copied / "cases/semantic-01/contrastive-bundle.json"
    bundle = DiagnosisEvidenceBundle.model_validate_json(bundle_path.read_bytes())
    bundle.peer_run_id = "other-peer"
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    bundle_path.write_text(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False,
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(DiagnosisSuiteError):
        verify_contrastive_fairness_review(copied, CANDIDATES)

    copied = tmp_path / "review"
    shutil.copytree(prepared_tree, copied)
    review = load_review(copied)
    changed = review.cases[0].model_copy(update={"locked_gold_sha256": "f" * 64})
    write_review(copied, review.model_copy(update={"cases": [changed, *review.cases[1:]]}))
    with pytest.raises(DiagnosisSuiteError):
        verify_contrastive_fairness_review(copied, CANDIDATES)
