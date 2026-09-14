"""Synthetic filesystem attacks against the future D6.3 freeze verifier."""

import hashlib
import json
import os

import pytest

from patchbench.application.diagnosis_suite import DiagnosisSuiteError, verify_diagnosis_validation_suite
from patchbench.application.diagnosis_validation import compute_diagnosis_gold_sha256, compute_subject_evidence_sha256
from patchbench.domain import (
    DiagnosisValidationFreezeManifest, DiagnosisValidationSuite,
    DiagnosisValidationSuiteCase, DiagnosisValidationSuiteCaseFile,
    FrozenValidationFile, canonical_json_bytes, compute_diagnosis_validation_suite_sha256,
)
from tests.test_diagnosis_validation import make_bundle, semantic_case


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(model.model_dump(mode="json")))


def rewrite_manifest(root, *, suite_sha=None, mutate_file=None):
    suite = DiagnosisValidationSuite.model_validate_json((root / "suite.json").read_bytes())
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()
                       and item.name != "freeze-manifest.json"):
        raw = path.read_bytes()
        entry = FrozenValidationFile(path=path.relative_to(root).as_posix(), sha256=sha(raw),
                                     byte_length=len(raw))
        entries.append(mutate_file(entry) if mutate_file else entry)
    manifest = DiagnosisValidationFreezeManifest(suite_path="suite.json",
        suite_sha256=suite_sha or compute_diagnosis_validation_suite_sha256(suite), files=entries)
    write_json(root / "freeze-manifest.json", manifest)


@pytest.fixture
def frozen_tree(tmp_path):
    root = tmp_path / "suite"
    blind, contrastive = make_bundle(), make_bundle("contrastive")
    gold = semantic_case(blind, case_id="case")
    case = DiagnosisValidationSuiteCase(case_id="case", expected_route="semantic_diagnosis",
        gold_path="cases/gold.json", gold_sha256=compute_diagnosis_gold_sha256(gold),
        subject_evidence_sha256=compute_subject_evidence_sha256(blind),
        blind_bundle_path="cases/blind.json", blind_bundle_sha256=blind.bundle_sha256,
        contrastive_bundle_path="cases/contrastive.json",
        contrastive_bundle_sha256=contrastive.bundle_sha256)
    write_json(root / "cases/gold.json", gold)
    write_json(root / "cases/blind.json", blind)
    write_json(root / "cases/contrastive.json", contrastive)
    write_json(root / "cases/case.json", case)
    case_raw = (root / "cases/case.json").read_bytes()
    suite = DiagnosisValidationSuite(suite_id="synthetic", case_files=[
        DiagnosisValidationSuiteCaseFile(case_id="case", path="cases/case.json",
                                          sha256=sha(case_raw))])
    write_json(root / "suite.json", suite)
    rewrite_manifest(root)
    return root


def test_valid_manifest_and_deterministic_manifest_order(frozen_tree):
    assert verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False).suite_id == "synthetic"
    before = (frozen_tree / "freeze-manifest.json").read_bytes()
    rewrite_manifest(frozen_tree)
    assert (frozen_tree / "freeze-manifest.json").read_bytes() == before
    manifest = DiagnosisValidationFreezeManifest.model_validate_json(before)
    assert [item.path for item in manifest.files] == sorted(item.path for item in manifest.files)


def test_missing_and_extra_files_rejected(frozen_tree):
    (frozen_tree / "cases/gold.json").unlink()
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "missing_file"


def test_unexpected_extra_file_rejected(frozen_tree):
    (frozen_tree / "extra.txt").write_text("extra")
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "extra_file"


def test_modified_bytes_wrong_length_and_wrong_sha_rejected(frozen_tree):
    path = frozen_tree / "cases/gold.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "file_length_mismatch"

    path.write_bytes(path.read_bytes()[:-1])
    def wrong_length(item):
        return item.model_copy(update={"byte_length": item.byte_length + 1}) if item.path == "cases/gold.json" else item
    rewrite_manifest(frozen_tree, mutate_file=wrong_length)
    with pytest.raises(DiagnosisSuiteError, match="file_length_mismatch"):
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)

    def wrong_sha(item):
        return item.model_copy(update={"sha256": "f" * 64}) if item.path == "cases/gold.json" else item
    rewrite_manifest(frozen_tree, mutate_file=wrong_sha)
    with pytest.raises(DiagnosisSuiteError, match="file_hash_mismatch"):
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)


def test_symlink_and_nonregular_file_rejected(frozen_tree, tmp_path):
    target = tmp_path / "target"; target.write_text("x")
    (frozen_tree / "link").symlink_to(target)
    with pytest.raises(DiagnosisSuiteError, match="symlink"):
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    (frozen_tree / "link").unlink()
    fifo = frozen_tree / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(DiagnosisSuiteError, match="non-regular"):
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)


def test_suite_sha_and_case_file_sha_rejected(frozen_tree):
    rewrite_manifest(frozen_tree, suite_sha="f" * 64)
    with pytest.raises(DiagnosisSuiteError, match="suite_sha256|suite hash|suite_sha|suite.json") as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "suite_hash_mismatch"

    suite_path = frozen_tree / "suite.json"
    raw = json.loads(suite_path.read_bytes())
    raw["case_files"][0]["sha256"] = "f" * 64
    suite_path.write_bytes(canonical_json_bytes(raw))
    rewrite_manifest(frozen_tree)
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "case_file_hash_mismatch"


def test_duplicate_case_id_and_declared_case_mismatch_rejected(frozen_tree):
    suite_path = frozen_tree / "suite.json"
    raw = json.loads(suite_path.read_bytes())
    raw["case_files"].append(dict(raw["case_files"][0], path="cases/other.json"))
    (frozen_tree / "cases/other.json").write_bytes((frozen_tree / "cases/case.json").read_bytes())
    suite_path.write_bytes(canonical_json_bytes(raw))
    # Cannot form a typed manifest suite hash; the parser must fail closed first.
    old = DiagnosisValidationFreezeManifest.model_validate_json(
        (frozen_tree / "freeze-manifest.json").read_bytes())
    entries=[]
    for path in sorted(p for p in frozen_tree.rglob("*") if p.is_file() and p.name != "freeze-manifest.json"):
        data=path.read_bytes(); entries.append(FrozenValidationFile(path=path.relative_to(frozen_tree).as_posix(),sha256=sha(data),byte_length=len(data)))
    write_json(frozen_tree / "freeze-manifest.json", DiagnosisValidationFreezeManifest(
        suite_path="suite.json", suite_sha256=old.suite_sha256, files=entries))
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "invalid_json"


def test_case_file_declared_id_mismatch_rejected(frozen_tree):
    case_path = frozen_tree / "cases/case.json"
    raw = json.loads(case_path.read_bytes()); raw["case_id"] = "other"
    case_path.write_bytes(canonical_json_bytes(raw))
    suite_path = frozen_tree / "suite.json"
    suite_raw = json.loads(suite_path.read_bytes())
    suite_raw["case_files"][0]["sha256"] = sha(case_path.read_bytes())
    suite_path.write_bytes(canonical_json_bytes(suite_raw))
    rewrite_manifest(frozen_tree)
    with pytest.raises(DiagnosisSuiteError) as caught:
        verify_diagnosis_validation_suite(frozen_tree, enforce_v1_composition=False)
    assert caught.value.reason.value == "case_id_mismatch"
