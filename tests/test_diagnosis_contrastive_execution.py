"""D5 shares D4 execution and persistence, using fake providers only."""

import json

import pytest
from pydantic import ValidationError

from patchbench.application.diagnosis_execution import execute_contrastive_diagnosis, execute_blind_diagnosis, DiagnosisExecutionError
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy, DiagnosisProviderProvenance, generate_diagnosis_id
from patchbench.application.diagnosis_prompt import blind_diagnosis_output_schema_v1
from patchbench.storage.filesystem import FilesystemArtifactStore
from patchbench.providers.base import DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError, DiagnosisProviderRequestError
from tests.test_diagnosis import hypothesis_data
from tests.test_diagnosis_execution import FakeProvider, semantic_payload, execute, invalid_payloads
from tests.test_diagnosis_audit import audit_inputs
from tests.test_diagnosis_contrastive_prompt import comparison_bundle
from tests.test_diagnosis_peer import peer_world, historical, save_experiment, change_record, write_record
from tests.test_diagnosis_contrastive_evidence import compile_peer
from patchbench.domain.diagnosis_integrity import compute_bundle_sha256


def run_contrastive(case, provider=None, bundle=None, *, allowed=True, limit=100000):
    return execute_contrastive_diagnosis(bundle or compile_peer(case), provider=provider or FakeProvider(),
        external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=allowed, max_provider_input_bytes=limit),
        peer_artifact_store=case["artifact_store"], output_artifact_store=case["artifact_store"])


@pytest.mark.parametrize("wrong_mode", ["blind", "contrastive"])
def test_wrong_executor_mode_no_provider_call(tmp_path, peer_world, wrong_mode):
    provider = FakeProvider()
    with pytest.raises(DiagnosisExecutionError) as caught:
        if wrong_mode == "blind":
            run_contrastive(peer_world, provider, audit_inputs()[0])
        else:
            execute_blind_diagnosis(comparison_bundle(), provider=provider,
                external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=True, max_provider_input_bytes=100000),
                artifact_store=FilesystemArtifactStore(tmp_path))
    assert caught.value.reason.value == ("not_contrastive_bundle" if wrong_mode == "blind" else "not_blind_bundle")
    assert provider.calls == [] and not (peer_world["artifact_store"].results_root / "diagnoses").exists()


@pytest.mark.parametrize("gate", ["bundle_integrity_failed", "external_llm_not_allowed", "prompt_too_large"])
def test_contrastive_preflight_no_call(peer_world, gate):
    bundle = compile_peer(peer_world)
    if gate == "bundle_integrity_failed":
        bundle.bundle_sha256 = "0" * 64
    provider = FakeProvider()
    with pytest.raises(DiagnosisExecutionError) as caught:
        run_contrastive(peer_world, provider, bundle, allowed=gate != "external_llm_not_allowed",
                       limit=1 if gate == "prompt_too_large" else 100000)
    assert caught.value.reason.value == gate and provider.calls == []
    assert not (peer_world["artifact_store"].results_root / "diagnoses").exists()


@pytest.mark.parametrize("ref,passed", [(dict(evidence_id="P003", start_line=1, end_line=1), True),
    (dict(evidence_id="P001", start_line=1, end_line=1), True),
    (dict(evidence_id="P999", start_line=1, end_line=1), False),
    (dict(evidence_id="P002", start_line=40, end_line=46), False)])
def test_peer_citations_pass_or_fail_and_persist_unchanged(peer_world, ref, passed):
    provider = FakeProvider(semantic_payload() | {"hypotheses": [hypothesis_data(evidence_refs=[ref])]})
    result = run_contrastive(peer_world, provider)
    assert result.diagnosis.mode.value == "contrastive"
    assert result.audit.passed is passed
    assert result.diagnosis.hypotheses[0].evidence_refs[0].model_dump() == ref
    assert len(provider.calls) == 1
    assert json.loads(provider.calls[0].output_schema_json) == blind_diagnosis_output_schema_v1()
    assert {p.name for p in result.artifact_directory.iterdir()} == {"bundle.json", "diagnosis.json", "audit.json", "execution.json"}
    loaded = peer_world["artifact_store"].load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)
    assert loaded[1:] == (result.diagnosis, result.audit, result.execution_record)
    peer = loaded[0].provenance.peer
    assert (peer.peer_experiment_id, peer.peer_run_index, peer.peer_run_id) == ("peers", 1, "z-passA")
    persisted_peer = json.loads((result.artifact_directory / "bundle.json").read_bytes())["provenance"]["peer"]
    assert persisted_peer == peer.model_dump(mode="json")


def test_contrastive_execution_separates_peer_read_store_from_output_write_store(tmp_path, peer_world):
    provider = FakeProvider()
    result = execute_contrastive_diagnosis(compile_peer(peer_world), provider=provider,
        external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=True, max_provider_input_bytes=100000),
        peer_artifact_store=peer_world["artifact_store"],
        output_artifact_store=FilesystemArtifactStore(tmp_path / "runtime"))
    assert len(provider.calls) == 1
    assert result.artifact_directory.is_relative_to((tmp_path / "runtime").resolve())
    assert not (peer_world["artifact_store"].results_root / "diagnoses").exists()


@pytest.mark.parametrize("payload", list(invalid_payloads()))
def test_invalid_outputs_still_rejected_without_repair(peer_world, payload):
    provider = FakeProvider(payload)
    with pytest.raises(DiagnosisExecutionError) as caught:
        run_contrastive(peer_world, provider)
    assert caught.value.reason.value == "invalid_provider_output"
    assert len(provider.calls) == 1 and not (peer_world["artifact_store"].results_root / "diagnoses").exists()


@pytest.mark.parametrize("error,reason", [(DiagnosisProviderRefusalError(), "provider_refused"),
    (DiagnosisProviderIncompleteError(), "provider_incomplete"), (DiagnosisProviderRequestError(), "provider_failed")])
def test_provider_errors_unchanged(peer_world, error, reason):
    provider = FakeProvider(error=error)
    with pytest.raises(DiagnosisExecutionError) as caught:
        run_contrastive(peer_world, provider)
    assert caught.value.reason.value == reason
    assert len(provider.calls) == 1 and not (peer_world["artifact_store"].results_root / "diagnoses").exists()


def test_blind_identity_and_artifact_compatibility_and_distinct_contrastive_identity(tmp_path, peer_world):
    blind = execute(tmp_path / "blind")
    assert blind.diagnosis.diagnosis_id == "diag-6d17d3b3c6f2b3f7e95b46d1d1f52e6ecf014005e78b6ba722170d4f2d4ada5f"
    assert blind.execution_record.execution_sha256 == "b44429a0414c4a6b838d94e31cb2a86662cbb3552d1f3011091732d2770a3af1"
    assert FilesystemArtifactStore(tmp_path / "blind").load_diagnosis_execution_artifacts(blind.diagnosis.diagnosis_id)[3] == blind.execution_record
    contrastive = run_contrastive(peer_world)
    assert contrastive.execution_record.provider.prompt_template_version == "contrastive-diagnosis-v1"
    assert contrastive.execution_record.inference_payload_sha256 == blind.execution_record.inference_payload_sha256
    assert contrastive.diagnosis.diagnosis_id != blind.diagnosis.diagnosis_id
    # Isolate prompt/template identity while holding Bundle/payload/response identity fixed.
    assert generate_diagnosis_id(blind.execution_record.bundle_sha256, blind.execution_record.inference_payload_sha256,
        contrastive.execution_record.provider) != blind.diagnosis.diagnosis_id
    old_data = blind.execution_record.provider.model_dump(mode="json")
    assert DiagnosisProviderProvenance.model_validate(old_data) == blind.execution_record.provider
    with pytest.raises(ValidationError):
        DiagnosisProviderProvenance.model_validate(old_data | {"prompt_template_version": "unknown-v1"})


def test_forged_locally_valid_bundle_never_renders_or_calls_provider(tmp_path, monkeypatch):
    import patchbench.application.diagnosis_execution as execution_module
    bundle = comparison_bundle()
    assert compute_bundle_sha256(bundle) == bundle.bundle_sha256
    provider = FakeProvider()
    monkeypatch.setattr(execution_module, "render_contrastive_diagnosis_prompt",
                        lambda *args: pytest.fail("Unverified peer must not reach renderer"))
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute_contrastive_diagnosis(bundle, provider=provider,
            external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=True, max_provider_input_bytes=100000),
            artifact_store=FilesystemArtifactStore(tmp_path))
    assert caught.value.reason.value == "contrastive_peer_verification_failed"
    assert provider.calls == [] and not (tmp_path / "diagnoses").exists()


@pytest.mark.parametrize("drift", ["experiment_id", "index", "peer_id", "ordering", "earlier_pass", "eligibility"])
def test_stale_or_forged_selection_fails_before_render_and_provider(peer_world, monkeypatch, drift):
    import patchbench.application.diagnosis_execution as execution_module
    bundle = compile_peer(peer_world)
    store = peer_world["artifact_store"]
    if drift == "experiment_id":
        bundle.provenance.peer.peer_experiment_id = "missing-experiment"
    elif drift == "index":
        bundle.provenance.peer.peer_run_index = 2
    elif drift == "peer_id":
        bundle.peer_run_id = bundle.provenance.peer.peer_run_id = "a-passB"
    elif drift == "ordering":
        save_experiment(store, ["fail1", "a-passB", "z-passA"])
    elif drift == "earlier_pass":
        # Keep the recorded index and ID intact, but make an earlier position PASS.
        earlier = store.load_run_record("a-passB")
        earlier.run_id = "fail1"
        write_record(store, earlier)
    else:
        change_record(store, "z-passA", "agent", "status", "command_failed")
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    # Each forged-provenance case remains locally schema-valid with a valid SHA.
    type(bundle).model_validate(bundle.model_dump())
    provider = FakeProvider()
    monkeypatch.setattr(execution_module, "render_contrastive_diagnosis_prompt",
                        lambda *args: pytest.fail("Stale selection must not reach renderer"))
    with pytest.raises(DiagnosisExecutionError) as caught:
        run_contrastive(peer_world, provider, bundle)
    assert caught.value.reason.value == "contrastive_peer_verification_failed"
    assert provider.calls == [] and not (store.results_root / "diagnoses").exists()


def test_disagreeing_peer_identity_rejected_even_after_hash_recomputed(peer_world):
    bundle = compile_peer(peer_world)
    bundle.peer_run_id = "a-passB"
    bundle.bundle_sha256 = compute_bundle_sha256(bundle)
    provider = FakeProvider()
    with pytest.raises(DiagnosisExecutionError) as caught:
        run_contrastive(peer_world, provider, bundle)
    assert caught.value.reason.value == "contrastive_peer_verification_failed"
    assert provider.calls == []
