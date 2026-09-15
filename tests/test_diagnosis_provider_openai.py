"""Mocked SDK only: no environment credential or network required."""

from importlib.metadata import version
import inspect
import json
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError
from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText, ResponseOutputRefusal, ResponseUsage
from openai.resources.responses import Responses

from patchbench.providers.openai import OpenAIDiagnosisProvider
from patchbench.providers.base import (DiagnosisProviderRequest, DiagnosisProviderSetupError,
    DiagnosisProviderRequestError, DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError)
from patchbench.application.diagnosis_prompt import blind_diagnosis_output_schema_v1
from patchbench.domain.diagnosis_integrity import canonical_json_bytes
from tests.test_diagnosis_execution import semantic_payload, execute


def sdk_response(*, status="completed", text=None, refusal=False, message_status="completed", usage=True):
    content = [ResponseOutputRefusal(type="refusal", refusal="declined")] if refusal else [
        ResponseOutputText(type="output_text", annotations=[], text=json.dumps(semantic_payload()) if text is None else text)]
    return Response.model_construct(id="resp-test", model="returned-model", status=status,
        output=[ResponseOutputMessage(id="msg", type="message", role="assistant", status=message_status, content=content)],
        incomplete_details=None, error=None,
        usage=ResponseUsage(input_tokens=100, output_tokens=50, total_tokens=150,
            input_tokens_details=dict(cached_tokens=0, cache_write_tokens=0),
            output_tokens_details=dict(reasoning_tokens=20)) if usage else None)


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.create.return_value = sdk_response()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("patchbench.providers.openai.OpenAI", factory)
    return factory, client


def provider(**changes):
    return OpenAIDiagnosisProvider(**(dict(model="requested-model", reasoning_effort="low",
        max_output_tokens=2000, timeout_seconds=12.5) | changes))


def request():
    return DiagnosisProviderRequest("instructions", "evidence", canonical_json_bytes(
        blind_diagnosis_output_schema_v1()).decode("utf-8"))


def test_exact_request_and_observations(sdk):
    factory, client = sdk
    adapter = provider()
    factory.assert_not_called()
    result = adapter.infer(request())
    factory.assert_called_once_with(max_retries=0, timeout=12.5)
    client.responses.create.assert_called_once_with(model="requested-model", instructions="instructions", input="evidence",
        store=False, tools=[], tool_choice="none", truncation="disabled", max_output_tokens=2000,
        reasoning={"effort": "low"}, text={"format": {"type": "json_schema", "name": "blind_diagnosis_v1",
            "schema": blind_diagnosis_output_schema_v1(), "strict": True}}, timeout=12.5, stream=False)
    # Bind outgoing kwargs against the installed official synchronous SDK signature.
    inspect.signature(Responses.create).bind(None, **client.responses.create.call_args.kwargs)
    assert result.response_id == "resp-test" and result.returned_model == "returned-model"
    assert result.client_name == "openai-python" and result.client_version == version("openai")
    assert result.usage.model_dump() == dict(input_tokens=100, output_tokens=50, reasoning_tokens=20, total_tokens=150)
    assert result.duration_seconds >= 0
    assert json.loads(result.output_text) == semantic_payload()
    client.__exit__.assert_called_once()


@pytest.mark.parametrize("response,error", [
    (sdk_response(refusal=True), DiagnosisProviderRefusalError),
    (sdk_response(status="incomplete", text="{"), DiagnosisProviderIncompleteError),
    (sdk_response(message_status="incomplete"), DiagnosisProviderIncompleteError),
    (sdk_response(status="failed"), DiagnosisProviderRequestError),
    (sdk_response(text=""), DiagnosisProviderRequestError),
])
def test_response_failures(sdk, response, error):
    _, client = sdk
    client.responses.create.return_value = response
    with pytest.raises(error):
        provider().infer(request())
    assert client.responses.create.call_count == 1


def test_sdk_exception_is_typed_and_does_not_expose_error_content(sdk):
    _, client = sdk
    client.responses.create.side_effect = APIConnectionError(request=MagicMock(), message="private prompt contents")
    with pytest.raises(DiagnosisProviderRequestError) as caught:
        provider().infer(request())
    assert "private prompt" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert client.responses.create.call_count == 1


def test_setup_failure_is_typed(sdk):
    factory, client = sdk
    factory.side_effect = RuntimeError("sensitive setup detail")
    with pytest.raises(DiagnosisProviderSetupError) as caught:
        provider().infer(request())
    assert "sensitive" not in str(caught.value)
    client.responses.create.assert_not_called()


@pytest.mark.parametrize("changes", [{"model": " "}, {"reasoning_effort": "invalid"},
    {"max_output_tokens": 0}, {"max_output_tokens": True}, {"timeout_seconds": 0.0},
    {"timeout_seconds": float("inf")}, {"timeout_seconds": float("nan")}, {"timeout_seconds": True}])
def test_configuration_validation(sdk, changes):
    with pytest.raises(DiagnosisProviderSetupError):
        provider(**changes)
    sdk[0].assert_not_called()


def test_usage_may_be_absent(sdk):
    sdk[1].responses.create.return_value = sdk_response(usage=False)
    assert all(value is None for value in provider().infer(request()).usage.model_dump().values())


def test_adapter_leaves_invalid_json_to_application(sdk, tmp_path):
    sdk[1].responses.create.return_value = sdk_response(text="not JSON")
    assert provider().infer(request()).output_text == "not JSON"
    from patchbench.application.diagnosis_execution import DiagnosisExecutionError
    with pytest.raises(DiagnosisExecutionError) as caught:
        execute(tmp_path, provider())
    assert caught.value.reason.value == "invalid_provider_output"
    assert not (tmp_path / "diagnoses").exists()


def test_completed_openai_provenance_and_no_raw_response(sdk, tmp_path):
    result = execute(tmp_path, provider())
    provenance = result.execution_record.provider
    assert provenance.provider_name == "openai" and provenance.api_surface == "responses"
    assert provenance.client_name == "openai-python" and provenance.client_version == version("openai")
    assert provenance.store_requested is False and provenance.tool_choice == "none"
    assert provenance.truncation == "disabled" and provenance.max_retries == 0
    assert provenance.requested_model == "requested-model" and provenance.returned_model == "returned-model"
    data = json.loads((result.artifact_directory / "execution.json").read_bytes())
    assert "output_text" not in data["provider"]
    assert "api_key" not in data["provider"]


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_nonfinal_status_is_not_parsed(sdk, status):
    sdk[1].responses.create.return_value = sdk_response(status=status, text="{partial")
    with pytest.raises(DiagnosisProviderIncompleteError):
        provider().infer(request())
    assert sdk[1].responses.create.call_count == 1


def test_incomplete_details_and_absent_message_output(sdk):
    response = sdk_response()
    response.incomplete_details = {"reason": "max_output_tokens"}
    sdk[1].responses.create.return_value = response
    with pytest.raises(DiagnosisProviderIncompleteError):
        provider().infer(request())
    response = sdk_response()
    response.output = []
    sdk[1].responses.create.return_value = response
    with pytest.raises(DiagnosisProviderRequestError):
        provider().infer(request())


def test_permission_gate_prevents_client_initialization(sdk, tmp_path):
    from patchbench.application.diagnosis_execution import DiagnosisExecutionError
    with pytest.raises(DiagnosisExecutionError):
        execute(tmp_path, provider(), allowed=False)
    sdk[0].assert_not_called()
