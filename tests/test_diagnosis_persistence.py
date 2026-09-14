"""Immutable Diagnosis attempts and save/load integrity verification."""

import json
from pathlib import Path

import pytest

from patchbench.domain import FailureDiagnosis, audit_failure_diagnosis
from patchbench.storage.filesystem import ArtifactStoreError, FilesystemArtifactStore
from tests.test_diagnosis import hypothesis_data
from tests.test_diagnosis_audit import audit_inputs


def artifacts(failed=False, **changes):
    if failed:
        changes["hypotheses"] = [hypothesis_data(evidence_refs=[dict(
            evidence_id="DOES_NOT_EXIST", start_line=1, end_line=1)])]
    bundle, diagnosis = audit_inputs(**changes)
    return bundle, diagnosis, audit_failure_diagnosis(bundle, diagnosis)


def disk_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failed", [False, True])
def test_roundtrip_exact_three_files_and_pretty_utf8(tmp_path, failed):
    store = FilesystemArtifactStore(tmp_path / "results")
    values = artifacts(failed, recommendation="雪")
    before = [v.model_dump() for v in values]
    directory = store.save_diagnosis_artifacts(*values)
    assert directory == store.results_root / "diagnoses" / "diagnosis"
    assert {p.name for p in directory.iterdir()} == {"bundle.json", "diagnosis.json", "audit.json"}
    for name, model in zip(("bundle", "diagnosis", "audit"), values):
        assert (directory / f"{name}.json").read_bytes() == (json.dumps(
            model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    loaded = store.load_diagnosis_artifacts("diagnosis")
    assert loaded == values
    assert loaded[2].passed is (not failed)
    assert [v.model_dump() for v in values] == before


@pytest.mark.parametrize("identifier", ["../x", "/x", "a/b", "a\\b", ".", "..", "", "-x", "_x",
    ".x", "a:b", "a\nb", "a ", "雪"])
def test_unsafe_ids_rejected_for_load_and_save(tmp_path, identifier):
    store = FilesystemArtifactStore(tmp_path / "results")
    with pytest.raises(ArtifactStoreError):
        store.load_diagnosis_artifacts(identifier)
    bundle, diagnosis, audit = artifacts()
    # Assignment preserves the exact unsafe locator, including whitespace that
    # NonEmptyString would otherwise strip during initial domain construction.
    diagnosis.diagnosis_id = identifier
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_artifacts(bundle, diagnosis, audit)
    assert not store.results_root.exists()


@pytest.mark.parametrize("identifier", ["A", "0", "D3.attempt_1-2"])
def test_portable_safe_ids(tmp_path, identifier):
    store = FilesystemArtifactStore(tmp_path)
    values = artifacts(diagnosis_id=identifier)
    store.save_diagnosis_artifacts(*values)
    assert store.load_diagnosis_artifacts(identifier) == values


def test_duplicate_never_overwrites_and_existing_run_artifacts_unchanged(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    paths = store.create_paths("historical-run")
    paths.metadata.write_bytes(b'{"historical":true}\n')
    paths.patch.write_bytes(b"exact patch\r\n")
    before_run = disk_bytes(paths.directory)
    store.save_diagnosis_artifacts(*artifacts())
    before = disk_bytes(tmp_path)
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_artifacts(*artifacts(recommendation="changed"))
    assert disk_bytes(tmp_path) == before
    assert disk_bytes(paths.directory) == before_run


def test_save_rejects_fabricated_pass_audit(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    bundle, diagnosis, failed = artifacts(True)
    fabricated = type(failed)(**(failed.model_dump() | {"passed": True, "issues": []}))
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_artifacts(bundle, diagnosis, fabricated)
    assert not (tmp_path / "diagnoses").exists()


@pytest.mark.parametrize("name,change", [
    ("bundle", lambda d: d.update(source_snapshot_policy="tampered")),
    ("diagnosis", lambda d: d["hypotheses"][0].update(mechanism_summary="The moon caused the software failure.")),
    ("diagnosis", lambda d: d.update(recommendation="new advice")),
    ("diagnosis", lambda d: d["hypotheses"][0]["evidence_refs"][0].update(end_line=42)),
    ("audit", lambda d: d.update(computed_bundle_sha256="b" * 64)),
    ("audit", lambda d: d.update(diagnosis_sha256="c" * 64)),
    ("audit", lambda d: d.update(passed=False, issues=[dict(code="evidence_not_found", detail="Fabricated.")])),
])
def test_schema_valid_tampering_detected(tmp_path, name, change):
    store = FilesystemArtifactStore(tmp_path)
    values = artifacts()
    directory = store.save_diagnosis_artifacts(*values)
    unchanged = {p.name: p.read_bytes() for p in directory.iterdir() if p.stem != name}
    path = directory / f"{name}.json"
    data = json.loads(path.read_bytes())
    change(data)
    # Explicitly prove tampering still satisfies the individual schema.
    model = dict(zip(("bundle", "diagnosis", "audit"), values))[name]
    type(model).model_validate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    if name == "diagnosis":
        changed = FailureDiagnosis.model_validate(data)
        result = audit_failure_diagnosis(values[0], changed)
        assert result.passed  # citations can stay valid while Diagnosis hash changes
        assert result.diagnosis_sha256 != values[2].diagnosis_sha256
    with pytest.raises(ArtifactStoreError):
        store.load_diagnosis_artifacts("diagnosis")
    assert {p.name: p.read_bytes() for p in directory.iterdir() if p.stem != name} == unchanged


@pytest.mark.parametrize("name", ["bundle", "diagnosis", "audit"])
@pytest.mark.parametrize("damage", ["missing", "invalid-json", "invalid-schema", "invalid-utf8"])
def test_missing_or_invalid_artifacts(tmp_path, name, damage):
    store = FilesystemArtifactStore(tmp_path)
    directory = store.save_diagnosis_artifacts(*artifacts())
    path = directory / f"{name}.json"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes({"invalid-json": b"{", "invalid-schema": b"{}", "invalid-utf8": b"\xff"}[damage])
    with pytest.raises(ArtifactStoreError):
        store.load_diagnosis_artifacts("diagnosis")


@pytest.mark.parametrize("name", ["bundle.json", "diagnosis.json", "audit.json"])
def test_write_failure_removes_new_directory(tmp_path, monkeypatch, name):
    store = FilesystemArtifactStore(tmp_path)
    original = Path.write_text
    def fail(path, *args, **kwargs):
        if path.name == name:
            raise OSError("injected write failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(ArtifactStoreError, match="injected write failure"):
        store.save_diagnosis_artifacts(*artifacts())
    assert not (tmp_path / "diagnoses" / "diagnosis").exists()


def test_requested_id_must_match_even_with_consistently_recomputed_audit(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    directory = store.save_diagnosis_artifacts(*artifacts())
    bundle, diagnosis, audit = artifacts(diagnosis_id="other")
    (directory / "diagnosis.json").write_text(diagnosis.model_dump_json())
    (directory / "audit.json").write_text(audit.model_dump_json())
    with pytest.raises(ArtifactStoreError, match="requested ID"):
        store.load_diagnosis_artifacts("diagnosis")


def test_symlink_directory_does_not_redirect_namespace(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "results")
    outside = tmp_path / "outside"
    outside.mkdir()
    store.results_root.mkdir()
    try:
        (store.results_root / "diagnoses").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlinks unavailable: {error}")
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_artifacts(*artifacts())
    with pytest.raises(ArtifactStoreError):
        store.load_diagnosis_artifacts("diagnosis")
    assert list(outside.iterdir()) == []
