"""Exact Blind augmentation, historical PASS evidence and fail-closed compilation."""

import hashlib
import json

import pytest

from patchbench.application.diagnosis_evidence import compile_diagnosis_evidence, _snapshot_hash
from patchbench.application.diagnosis_contrastive import compile_contrastive_diagnosis_evidence, ContrastiveCompilationError
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis import DiagnosisSourcePolicy
from tests.test_diagnosis_peer import peer_world, historical, select, change_record
from tests.helpers import git


def compile_peer(case, blind=None, selection=None, **changes):
    if blind is None:
        blind = compile_diagnosis_evidence(**case)
    if selection is None:
        selection = select(case)
    kwargs = {key: value for key, value in case.items() if key not in {"run_id", "benchmark_definition_sha256"}}
    return compile_contrastive_diagnosis_evidence(blind, selection, **(kwargs | changes))


def test_exact_blind_prefix_full_peer_source_and_determinism(peer_world):
    case = peer_world
    blind = compile_diagnosis_evidence(**case)
    before = blind.model_dump(mode="json")
    bundle = compile_peer(case, blind)
    again = compile_peer(case, blind)
    assert bundle == again
    assert canonical_json_bytes(bundle.model_dump(mode="json")) == canonical_json_bytes(again.model_dump(mode="json"))
    assert bundle.evidence_items[:len(blind.evidence_items)] == blind.evidence_items
    assert [i.model_dump() for i in bundle.evidence_items[:len(blind.evidence_items)]] == [i.model_dump() for i in blind.evidence_items]
    assert bundle.provenance.subject == blind.provenance.subject
    assert blind.model_dump(mode="json") == before
    added = bundle.evidence_items[len(blind.evidence_items):]
    assert [i.evidence_id for i in added] == ["P001", "P002", "P003", "P004"]
    assert [i.kind.value for i in added] == ["peer_evaluation", "peer_patch", "peer_source", "peer_source"]
    assert all(i.owner.value == "peer" for i in added)
    assert [(i.path, i.content) for i in added[2:]] == [("src/a.py", "a = 3\n"), ("src/b.py", "b = 2\n")]
    store = case["artifact_store"]
    assert added[0].content == store.load_run_test_log("z-passA")
    assert added[1].content == store.load_run_patch("z-passA")
    assert bundle.provenance.peer.peer_patch_sha256 == hashlib.sha256(added[1].content.encode()).hexdigest()
    assert bundle.provenance.peer.peer_evaluation_log_sha256 == hashlib.sha256(added[0].content.encode()).hexdigest()
    assert bundle.provenance.peer.peer_candidate_snapshot_sha256 == _snapshot_hash({i.path: i.content.encode() for i in added[2:]})
    assert compute_bundle_sha256(bundle) == bundle.bundle_sha256
    assert bundle.mode.value == "contrastive" and bundle.peer_run_id == "z-passA"
    assert not list(case["repository_manager"].workspace_root.iterdir())
    # Deep copy prevents subsequent mutation of a Contrastive item changing Blind evidence.
    bundle.evidence_items[0].content = "changed"
    assert blind.model_dump(mode="json") == before


@pytest.mark.parametrize("name,damage", [("patch.diff", "missing"), ("patch.diff", "tampered"),
    ("test.log", "missing"), ("test.log", "tampered")])
def test_first_peer_raw_failure_never_falls_back(peer_world, monkeypatch, name, damage):
    case = peer_world
    blind = compile_diagnosis_evidence(**case)
    path = case["artifact_store"].results_root / "z-passA" / name
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"tampered\n")
    selection = select(case)
    assert selection.peer_run_id == "z-passA"
    store = case["artifact_store"]
    reads = []
    original = store.load_run_record
    def guarded(run_id):
        reads.append(run_id)
        assert run_id != "a-passB"
        return original(run_id)
    monkeypatch.setattr(store, "load_run_record", guarded)
    with pytest.raises(ContrastiveCompilationError):
        compile_peer(case, blind, selection)
    assert "a-passB" not in reads
    assert not (store.results_root / "diagnoses").exists()


@pytest.mark.parametrize("field", ["base_source_snapshot_sha256", "frozen_tests_snapshot_sha256"])
def test_shared_byte_hash_mismatch_rejected(peer_world, field):
    blind = compile_diagnosis_evidence(**peer_world)
    setattr(blind.provenance.subject, field, "a" * 64)
    blind.bundle_sha256 = compute_bundle_sha256(blind)
    with pytest.raises(ContrastiveCompilationError) as caught:
        compile_peer(peer_world, blind)
    assert caught.value.reason.value == "peer_cell_mismatch"
    assert not list(peer_world["repository_manager"].workspace_root.iterdir())


def test_tampered_blind_rejected_before_peer_access(peer_world, monkeypatch):
    blind = compile_diagnosis_evidence(**peer_world)
    selection = select(peer_world)
    blind.bundle_sha256 = "0" * 64
    monkeypatch.setattr(peer_world["artifact_store"], "load_run_record", lambda *a: pytest.fail("Invalid Blind must fail first"))
    with pytest.raises(ContrastiveCompilationError) as caught:
        compile_peer(peer_world, blind, selection)
    assert caught.value.reason.value == "invalid_blind_bundle"


@pytest.mark.parametrize("change", ["summary", "pass_boolean", "status"])
def test_peer_metadata_tamper_rejected(peer_world, change):
    blind = compile_diagnosis_evidence(**peer_world)
    selection = select(peer_world)
    if change == "summary":
        change_record(peer_world["artifact_store"], "z-passA", "patch_summary", "patch_sha256", "0" * 64)
    elif change == "pass_boolean":
        change_record(peer_world["artifact_store"], "z-passA", None, "evaluation_passed", False)
    else:
        change_record(peer_world["artifact_store"], "z-passA", None, "status", "failed")
    with pytest.raises(ContrastiveCompilationError):
        compile_peer(peer_world, blind, selection)


def test_exact_task_policy_and_selection_context(peer_world):
    blind = compile_diagnosis_evidence(**peer_world)
    selection = select(peer_world)
    with pytest.raises(ContrastiveCompilationError):
        compile_peer(peer_world, blind, selection, source_policy=DiagnosisSourcePolicy(production_roots=["."]))
    later = selection.model_copy(update={"peer_run_id": "a-passB", "peer_run_index": 2})
    with pytest.raises(ContrastiveCompilationError):
        compile_peer(peer_world, blind, later)
    peer_world["task_path"].write_bytes(peer_world["task_path"].read_bytes() + b"\n")
    with pytest.raises(ContrastiveCompilationError) as caught:
        compile_peer(peer_world, blind, selection)
    assert caught.value.reason.value == "task_contract_mismatch"


def test_exact_final_size_gate(peer_world):
    blind = compile_diagnosis_evidence(**peer_world)
    bundle = compile_peer(peer_world, blind)
    size = len(canonical_json_bytes(bundle.model_dump(mode="json")))
    assert compile_peer(peer_world, blind, max_bundle_json_bytes=size) == bundle
    with pytest.raises(ContrastiveCompilationError) as caught:
        compile_peer(peer_world, blind, max_bundle_json_bytes=size-1)
    assert caught.value.reason.value == "bundle_too_large"


def test_historical_base_ignores_current_head(peer_world):
    blind = compile_diagnosis_evidence(**peer_world)
    expected = compile_peer(peer_world, blind)
    repo = peer_world["task_path"].parent / "repo"
    (repo / "src/b.py").write_bytes(b"future\n")
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "future")
    assert compile_peer(peer_world, blind) == expected


def test_patch_roundtrip_failure_is_typed_and_cleans_up(peer_world, monkeypatch):
    blind = compile_diagnosis_evidence(**peer_world)
    monkeypatch.setattr(peer_world["repository_manager"], "capture_diff", lambda *a: "")
    with pytest.raises(ContrastiveCompilationError) as caught:
        compile_peer(peer_world, blind)
    assert caught.value.reason.value == "peer_reconstruction_failed"
    assert not list(peer_world["repository_manager"].workspace_root.iterdir())


def test_identity_binds_exact_blind_bundle(peer_world):
    blind = compile_diagnosis_evidence(**peer_world)
    first = compile_peer(peer_world, blind)
    blind.bundle_id = "different-blind-identity"
    blind.bundle_sha256 = compute_bundle_sha256(blind)
    assert compile_peer(peer_world, blind).bundle_id != first.bundle_id


def test_compiled_peer_bundle_executes_with_fake_provider(peer_world):
    from patchbench.application.diagnosis_execution import execute_contrastive_diagnosis
    from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy
    from tests.test_diagnosis_execution import FakeProvider, semantic_payload
    from tests.test_diagnosis import hypothesis_data
    bundle = compile_peer(peer_world)
    provider = FakeProvider(semantic_payload() | {"hypotheses": [hypothesis_data(evidence_refs=[dict(
        evidence_id="P003", start_line=1, end_line=1)])]})
    store = peer_world["artifact_store"]
    result = execute_contrastive_diagnosis(bundle, provider=provider,
        external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=True, max_provider_input_bytes=1000000),
        artifact_store=store)
    assert result.audit.passed and len(provider.calls) == 1
    assert store.load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)[0] == bundle


def test_peer_raw_absolute_path_text_is_preserved_and_agent_logs_unread(peer_world, monkeypatch):
    from pathlib import Path
    from patchbench.domain.patch_evidence import summarize_patch
    from tests.test_diagnosis_peer import write_record
    from patchbench.config.task_loader import load_task
    blind = compile_diagnosis_evidence(**peer_world)
    manager = peer_world["repository_manager"]
    task = load_task(peer_world["task_path"])
    raw = b'LOCATION = "/home/example/project/file.py"\n'
    with manager.workspace(task.repository, "absolute-text-fixture") as workspace:
        (workspace.path / "src/a.py").write_bytes(raw)
        patch = manager.capture_diff(workspace)
    store = peer_world["artifact_store"]
    record = store.load_run_record("z-passA")
    record.artifacts.patch.write_bytes(patch.encode())
    record.patch_summary = summarize_patch(patch)
    write_record(store, record)
    original = Path.read_bytes
    def guard(path):
        if path.name in {"agent.log", "agent.stderr.log"}:
            pytest.fail("Agent narrative must not be read")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guard)
    result = compile_peer(peer_world, blind)
    source = next(i for i in result.evidence_items if i.kind.value == "peer_source" and i.path == "src/a.py")
    assert source.content.encode("utf-8") == raw
    structured = result.model_dump(mode="json")
    for item in structured["evidence_items"]:
        item.pop("content")
    assert str(peer_world["task_path"].parent).encode() not in canonical_json_bytes(structured)


def test_bundle_identity_binds_experiment_and_position(peer_world):
    from patchbench.application.diagnosis_peer import select_contrastive_peer
    from tests.test_diagnosis_peer import save_experiment
    blind = compile_diagnosis_evidence(**peer_world)
    store = peer_world["artifact_store"]
    first_selection = select(peer_world)
    first = compile_peer(peer_world, blind, first_selection)
    alternate = store.load_experiment_record("peers").model_copy(update={"experiment_id": "other-peers"})
    store.save_experiment(alternate)
    second_selection = select_contrastive_peer("subject", "other-peers", artifact_store=store)
    second = compile_peer(peer_world, blind, second_selection)
    save_experiment(store, ["z-passA", "fail1", "a-passB"])
    third_selection = select(peer_world)
    third = compile_peer(peer_world, blind, third_selection)
    assert len({first.bundle_id, second.bundle_id, third.bundle_id}) == 3
    assert first.evidence_items == second.evidence_items == third.evidence_items
    for bundle, selection in [(first, first_selection), (second, second_selection), (third, third_selection)]:
        assert bundle.provenance.peer.peer_experiment_id == selection.peer_experiment_id
        assert bundle.provenance.peer.peer_run_index == selection.peer_run_index
        assert bundle.provenance.peer.peer_run_id == selection.peer_run_id
        identity = dict(schema_version=1, mode="contrastive", subject_run_id=blind.subject_run_id,
            peer_run_id=selection.peer_run_id, peer_experiment_id=selection.peer_experiment_id,
            peer_run_index=selection.peer_run_index, blind_bundle_sha256=blind.bundle_sha256,
            benchmark_definition_sha256=blind.benchmark_definition_sha256,
            task_fingerprint_sha256=blind.task_fingerprint_sha256, source_snapshot_policy=blind.source_snapshot_policy)
        raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        assert bundle.bundle_id == "contrastive-" + hashlib.sha256(raw).hexdigest()
