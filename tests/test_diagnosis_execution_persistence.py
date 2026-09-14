"""Four-file create-only execution integrity; no live provider calls."""

import json
from pathlib import Path

import pytest

from patchbench.domain.diagnosis_execution import DiagnosisExecutionRecord, compute_execution_sha256
from patchbench.storage.filesystem import FilesystemArtifactStore, ArtifactStoreError
from tests.test_diagnosis_execution import execute
from tests.test_diagnosis_audit import audit_inputs


def test_four_file_roundtrip_and_duplicate_immutability(tmp_path):
    result = execute(tmp_path)
    store = FilesystemArtifactStore(tmp_path)
    values = store.load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)
    assert values[1:] == (result.diagnosis, result.audit, result.execution_record)
    before = {p.name: p.read_bytes() for p in result.artifact_directory.iterdir()}
    assert set(before) == {"bundle.json", "diagnosis.json", "audit.json", "execution.json"}
    assert before["execution.json"] == (json.dumps(result.execution_record.model_dump(mode="json"),
        ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_execution_artifacts(*values)
    assert before == {p.name: p.read_bytes() for p in result.artifact_directory.iterdir()}


@pytest.mark.parametrize("parts,value", [
    (("provider", "returned_model"), "changed"), (("provider", "response_id"), "changed"),
    (("provider", "prompt_sha256"), "a" * 64), (("provider", "usage", "input_tokens"), 123),
    (("audit_passed",), False), (("diagnosis_sha256",), "b" * 64), (("execution_sha256",), "c" * 64),
    (("bundle_sha256",), "d" * 64), (("diagnosis_id",), "other"), (("inference_payload_sha256",), "e" * 64),
])
def test_execution_unilateral_tampering_detected(tmp_path, parts, value):
    result = execute(tmp_path)
    path = result.artifact_directory / "execution.json"
    data = json.loads(path.read_bytes())
    target = data
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    DiagnosisExecutionRecord.model_validate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ArtifactStoreError):
        FilesystemArtifactStore(tmp_path).load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)


@pytest.mark.parametrize("field,value", [("audit_passed", False), ("diagnosis_sha256", "a" * 64),
    ("bundle_sha256", "b" * 64), ("diagnosis_id", "other"), ("inference_payload_sha256", "c" * 64)])
def test_save_rejects_linkage_even_with_recomputed_execution_hash(tmp_path, field, value):
    result = execute(tmp_path / "valid")
    bundle, _ = audit_inputs()
    record = DiagnosisExecutionRecord(**(result.execution_record.model_dump() | {field: value}))
    record.execution_sha256 = compute_execution_sha256(record)
    store = FilesystemArtifactStore(tmp_path / "invalid")
    with pytest.raises(ArtifactStoreError):
        store.save_diagnosis_execution_artifacts(bundle, result.diagnosis, result.audit, record)
    assert not store.results_root.exists()


@pytest.mark.parametrize("name", ["bundle.json", "diagnosis.json", "audit.json", "execution.json"])
def test_four_file_partial_write_cleanup(tmp_path, monkeypatch, name):
    original = Path.write_text
    def fail(path, *args, **kwargs):
        if path.name == name:
            raise OSError("injected write failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(ArtifactStoreError):
        execute(tmp_path)
    assert list((tmp_path / "diagnoses").iterdir()) == []


@pytest.mark.parametrize("damage", [None, b"{", b"{}", b"\xff"])
def test_missing_or_invalid_execution(tmp_path, damage):
    result = execute(tmp_path)
    path = result.artifact_directory / "execution.json"
    if damage is None:
        path.unlink()
    else:
        path.write_bytes(damage)
    with pytest.raises(ArtifactStoreError):
        FilesystemArtifactStore(tmp_path).load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)


def test_execution_hash_covers_complete_record_except_itself(tmp_path):
    import hashlib
    result = execute(tmp_path)
    data = result.execution_record.model_dump(mode="json")
    declared = data.pop("execution_sha256")
    independently_canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(independently_canonical).hexdigest() == declared
    result.execution_record.execution_sha256 = "0" * 64
    assert compute_execution_sha256(result.execution_record) == declared


@pytest.mark.parametrize("name", ["bundle", "diagnosis", "audit"])
def test_d4_load_rechecks_original_three_artifacts(tmp_path, name):
    result = execute(tmp_path)
    path = result.artifact_directory / f"{name}.json"
    data = json.loads(path.read_bytes())
    if name == "bundle":
        data["source_snapshot_policy"] = "changed"
    elif name == "diagnosis":
        data["recommendation"] = "changed"
    else:
        data["diagnosis_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ArtifactStoreError):
        FilesystemArtifactStore(tmp_path).load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)
