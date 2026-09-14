"""Synchronous tool-less Responses adapter; one SDK call, with retries disabled."""

from importlib.metadata import version
import json
from time import perf_counter

from openai import OpenAI
from pydantic import ValidationError

from patchbench.domain.diagnosis_execution import DiagnosisProviderSettings, DiagnosisProviderUsage
from patchbench.providers.base import (
    DiagnosisProviderRequest, DiagnosisProviderResponse, DiagnosisProviderSetupError,
    DiagnosisProviderRequestError, DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError,
)

# Adapter-supported SDK efforts; compatibility with a particular model is server-side.
_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


class OpenAIDiagnosisProvider:
    def __init__(self, *, model: str, reasoning_effort: str,
                 max_output_tokens: int, timeout_seconds: float) -> None:
        try:
            if reasoning_effort not in _REASONING_EFFORTS:
                raise ValueError("Unsupported reasoning effort")
            self._settings = DiagnosisProviderSettings(provider_name="openai", api_surface="responses",
                requested_model=model, reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds)
        except (ValueError, ValidationError):
            raise DiagnosisProviderSetupError("Invalid OpenAI Diagnosis configuration") from None

    @property
    def settings(self) -> DiagnosisProviderSettings:
        return self._settings

    def infer(self, request: DiagnosisProviderRequest) -> DiagnosisProviderResponse:
        config = self.settings
        try:
            # Lazy setup: credential discovery cannot happen before application gates.
            client = OpenAI(max_retries=0, timeout=config.timeout_seconds)
        except Exception:
            raise DiagnosisProviderSetupError("Unable to initialize OpenAI client") from None
        try:
            with client:
                started = perf_counter()
                response = client.responses.create(
                    model=config.requested_model, instructions=request.instructions, input=request.input_text,
                    background=False, store=False, tools=[], tool_choice="none", truncation="disabled",
                    max_output_tokens=config.max_output_tokens, reasoning={"effort": config.reasoning_effort},
                    text={"format": {"type": "json_schema", "name": "blind_diagnosis_v1",
                                     "schema": json.loads(request.output_schema_json), "strict": True}},
                    timeout=config.timeout_seconds, stream=False,
                )
                duration = perf_counter() - started
        except Exception:
            # Never include SDK errors, prompts, credentials or raw response bodies.
            raise DiagnosisProviderRequestError("OpenAI Responses request failed") from None

        for item in response.output:
            if item.type == "message" and any(part.type == "refusal" for part in item.content):
                raise DiagnosisProviderRefusalError("OpenAI refused Diagnosis inference")
        if (response.status in {"incomplete", "in_progress", "queued"}
                or response.incomplete_details is not None
                or any(item.type == "message" and item.status != "completed" for item in response.output)):
            raise DiagnosisProviderIncompleteError("OpenAI Diagnosis response is incomplete")
        if response.status != "completed" or response.error is not None:
            raise DiagnosisProviderRequestError("OpenAI Diagnosis response did not complete successfully")
        if any(item.type not in {"message", "reasoning"} for item in response.output):
            raise DiagnosisProviderRequestError("Unexpected output in tool-less Diagnosis response")
        if not response.output_text:
            raise DiagnosisProviderRequestError("OpenAI Diagnosis response contains no output text")
        usage = response.usage
        try:
            return DiagnosisProviderResponse(response_id=response.id, returned_model=response.model,
                output_text=response.output_text,
                usage=DiagnosisProviderUsage(input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    reasoning_tokens=getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None)),
                duration_seconds=duration, client_name="openai-python", client_version=version("openai"))
        except (ValueError, ValidationError):
            raise DiagnosisProviderRequestError("Invalid OpenAI response observations") from None
