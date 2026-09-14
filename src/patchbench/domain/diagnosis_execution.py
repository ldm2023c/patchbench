"""D4 completed inference contracts and deterministic identity; no provider I/O."""

import hashlib
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from patchbench.domain.models import DomainModel, NonEmptyString, Sha256Hex
from patchbench.domain.diagnosis import DiagnosisHypothesis, EvidenceRef, FailureDiagnosis
from patchbench.domain.diagnosis_integrity import canonical_json_bytes

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
TokenCount = Annotated[int, Field(strict=True, ge=0)]
PositiveSeconds = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Duration = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
StrictBool = Annotated[bool, Field(strict=True)]
DiagnosisPromptTemplateVersion = Literal["blind-diagnosis-v1", "contrastive-diagnosis-v1"]


class DiagnosisExternalLLMPolicy(DomainModel):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    external_llm_allowed: StrictBool = False
    max_provider_input_bytes: PositiveInt


class DiagnosisInferenceHypothesis(DiagnosisHypothesis):
    """Require every provider schema field without changing D1 defaults."""
    counterevidence_refs: list[EvidenceRef]


class DiagnosisInferencePayload(DomainModel):
    """Only semantic output; FailureDiagnosis owns final cross-field validation."""
    abstain: StrictBool
    abstention_reason: NonEmptyString | None
    hypotheses: list[DiagnosisInferenceHypothesis] = Field(max_length=3)
    recommendation: NonEmptyString | None


class DiagnosisProviderUsage(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    reasoning_tokens: TokenCount | None = None
    total_tokens: TokenCount | None = None


class DiagnosisProviderSettings(DomainModel):
    """Public runtime settings, never credentials or filesystem capabilities."""
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    provider_name: NonEmptyString
    api_surface: NonEmptyString
    requested_model: NonEmptyString
    reasoning_effort: NonEmptyString
    max_output_tokens: PositiveInt
    timeout_seconds: PositiveSeconds
    store_requested: StrictBool = False
    tool_choice: Literal["none"] = "none"
    truncation: Literal["disabled"] = "disabled"
    max_retries: Annotated[int, Field(strict=True, ge=0, le=0)] = 0


class DiagnosisProviderProvenance(DiagnosisProviderSettings):
    """Requested/returned model names are observations, not immutable weights."""
    returned_model: NonEmptyString
    response_id: NonEmptyString
    client_name: NonEmptyString
    client_version: NonEmptyString
    usage: DiagnosisProviderUsage
    duration_seconds: Duration
    prompt_template_version: DiagnosisPromptTemplateVersion
    prompt_sha256: Sha256Hex
    response_schema_sha256: Sha256Hex
    provider_input_bytes: PositiveInt
    max_provider_input_bytes: PositiveInt


class DiagnosisExecutionRecord(DomainModel):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    diagnosis_id: NonEmptyString
    bundle_sha256: Sha256Hex
    diagnosis_sha256: Sha256Hex
    audit_passed: StrictBool
    inference_payload_sha256: Sha256Hex
    provider: DiagnosisProviderProvenance
    execution_sha256: Sha256Hex


def compute_execution_sha256(execution: DiagnosisExecutionRecord) -> str:
    return hashlib.sha256(canonical_json_bytes(
        execution.model_dump(mode="json", exclude={"execution_sha256"})
    )).hexdigest()


def inference_payload_sha256(payload: DiagnosisInferencePayload) -> str:
    return hashlib.sha256(canonical_json_bytes(payload.model_dump(mode="json"))).hexdigest()


def diagnosis_payload(diagnosis: FailureDiagnosis) -> DiagnosisInferencePayload:
    return DiagnosisInferencePayload.model_validate(diagnosis.model_dump(include={
        "abstain", "abstention_reason", "hypotheses", "recommendation"}))


def generate_diagnosis_id(bundle_sha256: str, payload_sha256: str,
                          provider: DiagnosisProviderProvenance) -> str:
    identity = provider.model_dump(mode="json", include={"provider_name", "response_id",
        "requested_model", "returned_model", "prompt_template_version", "prompt_sha256",
        "response_schema_sha256"})
    identity.update(bundle_sha256=bundle_sha256, inference_payload_sha256=payload_sha256)
    return "diag-" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
