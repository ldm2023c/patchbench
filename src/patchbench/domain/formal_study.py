"""Frozen PatchBench V1.3 formal-study preregistration contracts."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from patchbench.domain.models import DomainModel, Sha256Hex


CanonicalId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False,
                      pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
GitSha = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=False,
                           pattern=r"^[0-9a-f]{40}$"),
]
ExactText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=False, min_length=1)
]


class V13FormalSlot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    ordinal: Annotated[int, Field(strict=True, ge=1, le=108)]
    slot_id: CanonicalId
    repetition_index: Annotated[int, Field(strict=True, ge=1, le=3)]
    task_id: CanonicalId
    task_spec_sha256: Sha256Hex
    task_fingerprint_sha256: Sha256Hex
    resolved_base_commit: GitSha
    config_id: CanonicalId
    config_sha256: Sha256Hex


class V13FormalRetryPolicy(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    max_attempts_per_slot: Literal[2]
    max_retries_per_slot: Literal[1]
    retry_requires_no_canonical_run_record: Literal[True]
    retry_eligible_failure_categories: tuple[Literal[
        "agent_setup", "agent_infrastructure", "repository_infrastructure",
        "docker_infrastructure", "artifact_infrastructure_before_canonical_run",
        "network_provider_transport_same_route"
    ], ...]
    canonical_run_disables_retry: Literal[True]
    canonical_agent_statuses_not_retryable: tuple[
        Literal["completed", "command_failed", "timed_out"], ...
    ]
    evaluator_failure_not_retryable: Literal[True]
    evaluation_infrastructure_error_not_retryable: Literal[True]
    empty_patch_not_retryable: Literal[True]
    incorrect_semantic_repair_not_retryable: Literal[True]
    frozen_task_integrity_failure_not_retryable: Literal[True]
    retry_preserves_slot_identity: Literal[True]
    retry_identity_fields: tuple[Literal[
        "slot_id", "task", "base_commit", "task_spec", "config_id", "m8_binding",
        "requested_model", "timeout", "provider_endpoint_or_relay", "evaluator",
        "backend", "repetition"
    ], ...]
    retry_does_not_add_planned_slot: Literal[True]
    no_fallback_agent: Literal[True]
    no_substitute_task: Literal[True]
    no_replacement_slot: Literal[True]
    exhausted_infrastructure_slot_remains_in_denominator: Literal[True]
    first_attempt_evidence_retained: Literal[True]
    explicit_environment_remediation_required: Literal[True]
    allowed_environment_remediation: tuple[ExactText, ...] = Field(min_length=1)
    forbidden_semantic_remediation: tuple[ExactText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_statuses(self) -> Self:
        if self.canonical_agent_statuses_not_retryable != (
            "completed", "command_failed", "timed_out"
        ):
            raise ValueError("all canonical Agent outcomes must disable retry")
        if self.retry_eligible_failure_categories != (
            "agent_setup", "agent_infrastructure", "repository_infrastructure",
            "docker_infrastructure", "artifact_infrastructure_before_canonical_run",
            "network_provider_transport_same_route",
        ):
            raise ValueError("retry eligibility categories must be complete and ordered")
        if self.retry_identity_fields != (
            "slot_id", "task", "base_commit", "task_spec", "config_id", "m8_binding",
            "requested_model", "timeout", "provider_endpoint_or_relay", "evaluator",
            "backend", "repetition",
        ):
            raise ValueError("retry must preserve every frozen slot identity field")
        return self


class V13FormalMetricPolicy(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    end_to_end_success_condition: Literal["canonical_completed_and_evaluator_pass"]
    end_to_end_denominator: Literal["all_planned_slots_in_stratum"]
    unresolved_infrastructure_is_end_to_end_failure: Literal[True]
    completed_semantic_repair_numerator: Literal["canonical_completed_and_evaluator_pass"]
    completed_semantic_repair_denominator: Literal["canonical_completed_slots"]
    completed_semantic_repair_is_conditional: Literal[True]
    operational_completion_numerator: Literal["canonical_completed_slots"]
    operational_completion_denominator: Literal["all_planned_slots_in_stratum"]
    operational_completion_is_descriptive: Literal[True]
    retry_reporting_required: tuple[Literal[
        "slots_requiring_retry", "retry_reasons", "slots_resolving_on_retry",
        "slots_unresolved_after_retry"
    ], ...]
    reporting_strata: tuple[Literal[
        "overall", "agent_configuration", "primary_capability",
        "designed_difficulty", "task"
    ], ...]
    m1_m3_design_labels_authoritative: Literal[True]
    no_weighted_composite_agent_score: Literal[True]
    no_post_hoc_best_agent_rule: Literal[True]
    no_outcome_based_task_removal: Literal[True]
    no_outcome_based_agent_removal: Literal[True]
    no_difficulty_relabeling: Literal[True]
    no_failure_denominator_exclusion: Literal[True]
    no_cherry_picked_repetitions: Literal[True]
    no_replacement_runs_beyond_retry: Literal[True]
    no_performance_based_stopping: Literal[True]

    @model_validator(mode="after")
    def validate_reporting_contract(self) -> Self:
        if self.retry_reporting_required != (
            "slots_requiring_retry", "retry_reasons", "slots_resolving_on_retry",
            "slots_unresolved_after_retry",
        ):
            raise ValueError("retry reporting fields must be complete and ordered")
        if self.reporting_strata != (
            "overall", "agent_configuration", "primary_capability",
            "designed_difficulty", "task",
        ):
            raise ValueError("formal reporting strata must be complete and ordered")
        return self


class V13FormalPreregistration(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    study_id: Literal["patchbench-v1.3-formal"]
    design_sha256: Sha256Hex
    candidate_sha256: Sha256Hex
    agent_manifest_sha256: Sha256Hex
    calibration_protocol_sha256: Sha256Hex
    calibration_evidence_freeze_sha256: Sha256Hex
    accepted_calibration_batch_id: Literal["calibration-001"]
    evaluation_backend: Literal["docker"]
    repetitions_per_cell: Literal[3]
    planned_slot_count: Literal[108]
    task_order: tuple[CanonicalId, ...] = Field(min_length=12, max_length=12)
    base_agent_order: tuple[CanonicalId, ...] = Field(min_length=3, max_length=3)
    agent_order_by_repetition: tuple[tuple[CanonicalId, ...], ...] = Field(
        min_length=3, max_length=3
    )
    execution_order_policy: Literal["repetition_then_m3_task_then_rotated_agent"]
    formal_results_namespace: Literal["results/v1.3-formal"]
    calibration_outcome_must_not_influence_formal_design: Literal[True]
    calibration_outcome_excluded_from: tuple[Literal[
        "task_selection", "agent_selection", "model_selection", "timeout",
        "endpoint_or_relay", "task_order", "repetition_count", "retry_policy",
        "metric_definitions"
    ], ...]
    retry_policy: V13FormalRetryPolicy
    metrics_policy: V13FormalMetricPolicy
    slots: tuple[V13FormalSlot, ...] = Field(min_length=108, max_length=108)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.calibration_outcome_excluded_from != (
            "task_selection", "agent_selection", "model_selection", "timeout",
            "endpoint_or_relay", "task_order", "repetition_count", "retry_policy",
            "metric_definitions",
        ):
            raise ValueError("calibration outcome exclusion boundary must be complete")
        if len(set(self.task_order)) != 12 or len(set(self.base_agent_order)) != 3:
            raise ValueError("formal task and Agent identities must be unique")
        expected_rotations = tuple(
            self.base_agent_order[index:] + self.base_agent_order[:index]
            for index in range(3)
        )
        if self.agent_order_by_repetition != expected_rotations:
            raise ValueError("formal Agent order must use the frozen Latin rotation")
        if tuple(slot.ordinal for slot in self.slots) != tuple(range(1, 109)):
            raise ValueError("formal slot ordinals must be exactly 1 through 108")
        if len({slot.slot_id for slot in self.slots}) != 108:
            raise ValueError("formal slot IDs must be unique")
        identities = []
        for repetition, order in enumerate(self.agent_order_by_repetition, start=1):
            for task_id in self.task_order:
                identities.extend((repetition, task_id, config_id) for config_id in order)
        actual = [(slot.repetition_index, slot.task_id, slot.config_id)
                  for slot in self.slots]
        if actual != identities:
            raise ValueError("formal slots violate preregistered execution order")
        if "example_bug" in self.task_order:
            raise ValueError("calibration task cannot enter the formal study")
        if any("claude-code" in config_id for config_id in self.base_agent_order):
            raise ValueError("Claude Code is not a selected formal configuration")
        return self


def compute_v13_formal_preregistration_sha256(
    preregistration: V13FormalPreregistration,
) -> str:
    payload = json.dumps(
        preregistration.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
