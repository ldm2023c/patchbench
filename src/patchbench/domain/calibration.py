"""Frozen PatchBench V1.3 calibration protocol identity."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import DomainModel, Sha256Hex


CanonicalId = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=False, pattern=r"^[a-z][a-z0-9_.-]*$"
    ),
]
ExactText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=1, max_length=500),
]
RelativePathText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=1, max_length=300),
]
GitSha1Hex = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$"),
]


class V13CalibrationProtocol(DomainModel):
    """Semantic contract for the pre-study V1.3 calibration protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    protocol_id: Literal["patchbench-v1.3-calibration-protocol"]
    m3_candidate_sha256: Sha256Hex
    m8_agent_manifest_sha256: Sha256Hex
    calibration_task_spec_path: RelativePathText
    calibration_task_spec_sha256: Sha256Hex
    calibration_task_id: CanonicalId
    calibration_base_commit: GitSha1Hex
    evaluation_backend: Literal["docker"]
    ordered_agent_config_ids: tuple[CanonicalId, ...] = Field(min_length=1)
    runs_per_configuration: Literal[1]
    admitted_agent_statuses: tuple[AgentRunStatus, ...]
    evaluation_pass_required: StrictBool
    within_batch_retry_policy: Literal["no_retry"]
    failed_batch_rerun_policy: Literal["new_batch_after_environment_only_remediation"]
    environment_only_remediation_required: StrictBool
    failed_batch_evidence_retention_required: StrictBool
    all_configurations_required_for_batch_acceptance: StrictBool
    formal_benchmark_task_execution_forbidden: StrictBool
    formal_study_tuning_from_calibration_forbidden: StrictBool
    calibration_outcome_must_not_influence_task_selection: StrictBool
    calibration_outcome_must_not_influence_agent_selection: StrictBool
    calibration_outcome_must_not_influence_model_timeout_or_endpoint: StrictBool
    calibration_outcome_must_not_influence_prompt_or_retry_policy: StrictBool
    allowed_environment_remediation: tuple[ExactText, ...] = Field(min_length=1)
    forbidden_semantic_remediation: tuple[ExactText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_protocol_rules(self) -> Self:
        if self.ordered_agent_config_ids != tuple(sorted(self.ordered_agent_config_ids)):
            raise ValueError("calibration config IDs must follow frozen manifest order")
        if len(self.ordered_agent_config_ids) != len(set(self.ordered_agent_config_ids)):
            raise ValueError("calibration config IDs must be unique")
        if self.admitted_agent_statuses != (AgentRunStatus.COMPLETED,):
            raise ValueError("only COMPLETED Agent status is calibration-admitted")
        if self.evaluation_pass_required is not False:
            raise ValueError("calibration admission must not require evaluator PASS")
        if self.environment_only_remediation_required is not True:
            raise ValueError("failed calibration reruns require environment-only remediation")
        if self.failed_batch_evidence_retention_required is not True:
            raise ValueError("failed calibration evidence must be retained")
        if self.all_configurations_required_for_batch_acceptance is not True:
            raise ValueError("all selected configurations are required for batch acceptance")
        contamination_flags = (
            self.formal_benchmark_task_execution_forbidden,
            self.formal_study_tuning_from_calibration_forbidden,
            self.calibration_outcome_must_not_influence_task_selection,
            self.calibration_outcome_must_not_influence_agent_selection,
            self.calibration_outcome_must_not_influence_model_timeout_or_endpoint,
            self.calibration_outcome_must_not_influence_prompt_or_retry_policy,
        )
        if any(flag is not True for flag in contamination_flags):
            raise ValueError("calibration must not tune or contaminate the formal study")
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_v13_calibration_protocol_sha256(
    protocol: V13CalibrationProtocol,
) -> str:
    """Hash every validated semantic calibration-protocol field."""
    return hashlib.sha256(
        _canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
