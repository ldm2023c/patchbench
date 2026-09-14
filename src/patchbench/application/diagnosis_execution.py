"""One Blind inference attempt over an already compiled Bundle; no repair or retries."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from patchbench.application.diagnosis_prompt import (
    render_blind_diagnosis_prompt, blind_diagnosis_output_schema_v1, provider_input_bytes,
)
from patchbench.domain.diagnosis import DiagnosisEvidenceBundle, DiagnosisMode, FailureDiagnosis
from patchbench.domain.diagnosis_audit import DiagnosisAuditResult, audit_failure_diagnosis
from patchbench.domain.diagnosis_integrity import canonical_json_bytes, compute_bundle_sha256
from patchbench.domain.diagnosis_execution import (
    DiagnosisExternalLLMPolicy, DiagnosisInferencePayload, DiagnosisProviderProvenance,
    DiagnosisExecutionRecord, compute_execution_sha256, generate_diagnosis_id, inference_payload_sha256,
)
from patchbench.providers.base import (
    DiagnosisProvider, DiagnosisProviderRequest, DiagnosisProviderError,
    DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError,
)
from patchbench.storage.filesystem import FilesystemArtifactStore


class DiagnosisExecutionReason(str, Enum):
    NOT_BLIND_BUNDLE = "not_blind_bundle"
    BUNDLE_INTEGRITY_FAILED = "bundle_integrity_failed"
    EXTERNAL_LLM_NOT_ALLOWED = "external_llm_not_allowed"
    PROMPT_TOO_LARGE = "prompt_too_large"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_REFUSED = "provider_refused"
    PROVIDER_INCOMPLETE = "provider_incomplete"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"


class DiagnosisExecutionError(RuntimeError):
    def __init__(self, reason: DiagnosisExecutionReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class DiagnosisExecution:
    diagnosis: FailureDiagnosis
    audit: DiagnosisAuditResult
    execution_record: DiagnosisExecutionRecord
    artifact_directory: Path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def execute_blind_diagnosis(
    bundle: DiagnosisEvidenceBundle, *, provider: DiagnosisProvider,
    external_policy: DiagnosisExternalLLMPolicy, artifact_store: FilesystemArtifactStore,
) -> DiagnosisExecution:
    if bundle.mode is not DiagnosisMode.BLIND:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.NOT_BLIND_BUNDLE)
    if compute_bundle_sha256(bundle) != bundle.bundle_sha256:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.BUNDLE_INTEGRITY_FAILED)
    if not external_policy.external_llm_allowed:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.EXTERNAL_LLM_NOT_ALLOWED)
    prompt = render_blind_diagnosis_prompt(bundle)
    schema = blind_diagnosis_output_schema_v1()
    schema_bytes = canonical_json_bytes(schema)
    input_bytes = provider_input_bytes(prompt, schema)
    if input_bytes > external_policy.max_provider_input_bytes:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.PROMPT_TOO_LARGE)
    request = DiagnosisProviderRequest(prompt.instructions, prompt.input_text, schema_bytes.decode("utf-8"))
    try:
        settings = provider.settings
        response = provider.infer(request)
    except DiagnosisProviderRefusalError:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.PROVIDER_REFUSED) from None
    except DiagnosisProviderIncompleteError:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.PROVIDER_INCOMPLETE) from None
    except DiagnosisProviderError:
        raise DiagnosisExecutionError(DiagnosisExecutionReason.PROVIDER_FAILED) from None
    try:
        # Parse one complete document; no extraction, repair, or duplicate-key ambiguity.
        json.loads(response.output_text, object_pairs_hook=_unique_object)
        payload = DiagnosisInferencePayload.model_validate_json(response.output_text, strict=True)
        payload_sha = inference_payload_sha256(payload)
        provenance = DiagnosisProviderProvenance(**settings.model_dump(),
            **response.model_dump(exclude={"output_text"}), prompt_template_version=prompt.template_version,
            prompt_sha256=prompt.prompt_sha256, response_schema_sha256=hashlib.sha256(schema_bytes).hexdigest(),
            provider_input_bytes=input_bytes, max_provider_input_bytes=external_policy.max_provider_input_bytes)
        diagnosis_id = generate_diagnosis_id(bundle.bundle_sha256, payload_sha, provenance)
        diagnosis = FailureDiagnosis(schema_version=1, diagnosis_id=diagnosis_id,
            bundle_sha256=bundle.bundle_sha256, mode=bundle.mode, subject_run_id=bundle.subject_run_id,
            **payload.model_dump())
    except (ValueError, ValidationError):
        raise DiagnosisExecutionError(DiagnosisExecutionReason.INVALID_PROVIDER_OUTPUT) from None
    audit = audit_failure_diagnosis(bundle, diagnosis)
    execution = DiagnosisExecutionRecord(diagnosis_id=diagnosis_id, bundle_sha256=bundle.bundle_sha256,
        diagnosis_sha256=audit.diagnosis_sha256, audit_passed=audit.passed,
        inference_payload_sha256=payload_sha, provider=provenance, execution_sha256="0" * 64)
    execution.execution_sha256 = compute_execution_sha256(execution)
    directory = artifact_store.save_diagnosis_execution_artifacts(bundle, diagnosis, audit, execution)
    return DiagnosisExecution(diagnosis, audit, execution, directory)
