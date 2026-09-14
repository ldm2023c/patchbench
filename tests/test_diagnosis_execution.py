"""Provider-independent Blind execution; fake inference only."""

import json

import pytest

from patchbench.application.diagnosis_execution import execute_blind_diagnosis, DiagnosisExecutionError
from patchbench.application.diagnosis_prompt import render_blind_diagnosis_prompt, blind_diagnosis_output_schema_v1, provider_input_bytes
from patchbench.domain.diagnosis_execution import DiagnosisExternalLLMPolicy, DiagnosisProviderSettings, DiagnosisProviderUsage
from patchbench.providers.base import (DiagnosisProviderResponse, DiagnosisProviderRequestError,
    DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError)
from patchbench.storage.filesystem import FilesystemArtifactStore
from tests.test_diagnosis import hypothesis_data
from tests.test_diagnosis_audit import audit_inputs


def semantic_payload():
    return dict(abstain=False, abstention_reason=None, hypotheses=[hypothesis_data()], recommendation=None)


class FakeProvider:
    settings = DiagnosisProviderSettings(provider_name="fake", api_surface="test", requested_model="test-model",
        reasoning_effort="low", max_output_tokens=1000, timeout_seconds=10.0)

    def __init__(self, payload=None, response_id="response-1", error=None):
        self.text = json.dumps(semantic_payload() if payload is None else payload) if not isinstance(payload, str) else payload
        self.response_id = response_id
        self.error = error
        self.calls = []

    def infer(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return DiagnosisProviderResponse(response_id=self.response_id, returned_model="returned-test-model",
            output_text=self.text, usage=DiagnosisProviderUsage(input_tokens=10, output_tokens=20, reasoning_tokens=5, total_tokens=30),
            duration_seconds=0.5, client_name="fake-client", client_version="1")


def execute(tmp_path, provider=None, bundle=None, limit=100000, allowed=True):
    if bundle is None:
        bundle, _ = audit_inputs()
    return execute_blind_diagnosis(bundle, provider=provider or FakeProvider(),
        external_policy=DiagnosisExternalLLMPolicy(external_llm_allowed=allowed, max_provider_input_bytes=limit),
        artifact_store=FilesystemArtifactStore(tmp_path))


@pytest.mark.parametrize("gate", ["not_blind_bundle", "bundle_integrity_failed", "external_llm_not_allowed", "prompt_too_large"])
def test_preflight_never_calls_provider(tmp_path, gate):
    bundle, _ = audit_inputs(mode="contrastive" if gate == "not_blind_bundle" else "blind")
    if gate == "bundle_integrity_failed":
        bundle.bundle_sha256 = "0" * 64
    provider = FakeProvider()
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute(tmp_path, provider, bundle, limit=1 if gate == "prompt_too_large" else 100000,
                allowed=gate != "external_llm_not_allowed")
    assert caught.value.reason.value == gate
    assert provider.calls == [] and not (tmp_path / "diagnoses").exists()


def test_exact_byte_gate_and_owned_fields(tmp_path):
    bundle, _ = audit_inputs()
    limit = provider_input_bytes(render_blind_diagnosis_prompt(bundle), blind_diagnosis_output_schema_v1())
    provider = FakeProvider()
    result = execute(tmp_path, provider, bundle, limit=limit)
    assert len(provider.calls) == 1
    assert result.audit.passed
    assert result.diagnosis.diagnosis_id.startswith("diag-") and len(result.diagnosis.diagnosis_id) == 69
    assert result.diagnosis.bundle_sha256 == bundle.bundle_sha256
    assert result.diagnosis.subject_run_id == bundle.subject_run_id
    assert result.diagnosis.mode == bundle.mode and result.diagnosis.schema_version == 1
    assert result.execution_record.provider.provider_input_bytes == limit
    assert set(provider.calls[0].__dict__) == {"instructions", "input_text", "output_schema_json"}
    denied = FakeProvider()
    with pytest.raises(DiagnosisExecutionError):
        execute(tmp_path / "small", denied, bundle, limit=limit-1)
    assert denied.calls == []


def invalid_payloads():
    for key in ["diagnosis_id", "bundle_sha256", "mode", "subject_run_id", "schema_version", "unexpected"]:
        yield semantic_payload() | {key: "forbidden"}
    yield "{"
    yield "```json\n{}\n```"
    yield '{} {}'
    yield '{"abstain":true,"abstain":false}'
    for key, value in [("failure_family", "unknown"), ("certainty", "certain"), ("rank", 2)]:
        yield semantic_payload() | {"hypotheses": [hypothesis_data(**{key: value})]}
    yield semantic_payload() | {"abstain": True, "abstention_reason": "insufficient"}
    yield semantic_payload() | {"hypotheses": []}
    yield semantic_payload() | {"hypotheses": [hypothesis_data(evidence_refs=[dict(
        evidence_id="subject-source", start_line=None, end_line=41)])]}
    yield semantic_payload() | {"abstain": 0}


@pytest.mark.parametrize("payload", list(invalid_payloads()))
def test_invalid_output_never_repaired_or_persisted(tmp_path, payload):
    provider = FakeProvider(payload)
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute(tmp_path, provider)
    assert caught.value.reason.value == "invalid_provider_output"
    assert len(provider.calls) == 1
    assert not (tmp_path / "diagnoses").exists()


@pytest.mark.parametrize("error,reason", [(DiagnosisProviderRefusalError("refusal"), "provider_refused"),
    (DiagnosisProviderIncompleteError("incomplete"), "provider_incomplete"),
    (DiagnosisProviderRequestError("request failure"), "provider_failed")])
def test_provider_errors_no_retry_no_persistence(tmp_path, error, reason):
    provider = FakeProvider(error=error)
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute(tmp_path, provider)
    assert caught.value.reason.value == reason
    assert len(provider.calls) == 1 and not (tmp_path / "diagnoses").exists()


def test_semantic_abstention_is_a_completed_attempt(tmp_path):
    result = execute(tmp_path, FakeProvider(dict(abstain=True, abstention_reason="Evidence is insufficient.",
        hypotheses=[], recommendation=None)))
    assert result.diagnosis.abstain and result.audit.passed
    assert len(list(result.artifact_directory.iterdir())) == 4


@pytest.mark.parametrize("reference", [dict(evidence_id="DOES_NOT_EXIST", start_line=1, end_line=1),
    dict(evidence_id="subject-source", start_line=1, end_line=99)])
def test_audit_fail_persists_without_repair(tmp_path, reference):
    provider = FakeProvider(semantic_payload() | {"hypotheses": [hypothesis_data(evidence_refs=[reference])]})
    result = execute(tmp_path, provider)
    assert not result.audit.passed and not result.execution_record.audit_passed
    assert result.diagnosis.hypotheses[0].evidence_refs[0].model_dump() == reference
    assert len(provider.calls) == 1
    assert FilesystemArtifactStore(tmp_path).load_diagnosis_execution_artifacts(result.diagnosis.diagnosis_id)[2] == result.audit


def test_identity_and_normalized_semantic_hash(tmp_path):
    payload = semantic_payload()
    first = execute(tmp_path / "first", FakeProvider(json.dumps(payload)))
    second = execute(tmp_path / "second", FakeProvider(json.dumps(payload, indent=4, sort_keys=True)))
    assert first.diagnosis == second.diagnosis
    assert first.execution_record == second.execution_record
    third = execute(tmp_path / "third", FakeProvider(payload, response_id="response-2"))
    assert third.diagnosis.diagnosis_id != first.diagnosis.diagnosis_id
    assert third.execution_record.inference_payload_sha256 == first.execution_record.inference_payload_sha256


def test_missing_required_counterevidence_is_not_filled_in(tmp_path):
    payload = semantic_payload()
    payload["hypotheses"][0].pop("counterevidence_refs")
    provider = FakeProvider(payload)
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute(tmp_path, provider)
    assert caught.value.reason.value == "invalid_provider_output"
    assert len(provider.calls) == 1 and not (tmp_path / "diagnoses").exists()
