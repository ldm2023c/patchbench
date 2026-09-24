"""Frozen preregistration contract for PatchBench V1.3 Replication-01."""

import hashlib
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from patchbench.domain.formal_evidence import canonical_json_bytes
from patchbench.domain.formal_incident import GitSha
from patchbench.domain.formal_study import (
    CanonicalId,
    V13FormalMetricPolicy,
    V13FormalRetryPolicy,
    V13FormalSlot,
)
from patchbench.domain.models import DomainModel, Sha256Hex


class V13FormalReplicationSlot(V13FormalSlot):
    """One fresh future execution slot belonging only to Replication-01."""

    replication_index: Literal[1]


class V13FormalReplicationPreregistration(DomainModel):
    """Complete immutable design for the independent V1.3 replication."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Literal[1] = 1
    replication_id: Literal["patchbench-v1.3-replication-01"]
    study_id: Literal["patchbench-v1.3-formal-replication-01"]
    formal_results_namespace: Literal["results/v1.3-formal-replication-01"]
    original_study_id: Literal["patchbench-v1.3-formal"]
    original_results_namespace: Literal["results/v1.3-formal"]
    design_sha256: Sha256Hex
    candidate_sha256: Sha256Hex
    agent_manifest_sha256: Sha256Hex
    original_formal_preregistration_sha256: Sha256Hex
    original_formal_evidence_freeze_sha256: Sha256Hex
    original_formal_analysis_sha256: Sha256Hex
    formal_incident_freeze_sha256: Sha256Hex
    provider_failure_remediation_commit: GitSha
    replication_reason: Literal[
        "original comparative capability interpretation was infrastructure-confounded "
        "by positively adjudicated Codex same-route HTTP 429 failures that were "
        "canonicalized by the pre-M16 harness"
    ]
    evaluation_backend: Literal["docker"]
    repetitions_per_cell: Literal[3]
    planned_slot_count: Literal[108]
    task_order: tuple[CanonicalId, ...] = Field(min_length=12, max_length=12)
    base_agent_order: tuple[CanonicalId, ...] = Field(min_length=3, max_length=3)
    agent_order_by_repetition: tuple[tuple[CanonicalId, ...], ...] = Field(
        min_length=3, max_length=3
    )
    execution_order_policy: Literal["repetition_then_m3_task_then_rotated_agent"]
    execution_admission_required_before_replication: Literal[True]
    future_execution_harness_commit_status: Literal["not_yet_frozen"]
    required_provider_failure_remediation_commit: GitSha
    structured_codex_http_429_requires_typed_provider_transport_failure: Literal[True]
    structured_codex_http_429_forbids_canonical_run: Literal[True]
    structured_codex_http_429_failure_category: Literal[
        "network_provider_transport_same_route"
    ]
    provider_route_must_remain_unchanged: Literal[True]
    patchbench_automatic_retry_forbidden: Literal[True]
    original_outcomes_must_not_influence_replication_design: Literal[True]
    original_outcomes_excluded_from: tuple[Literal[
        "task_selection", "task_modification", "agent_selection", "model_selection",
        "timeout", "provider_route", "task_order", "agent_order",
        "repetition_count", "retry_policy", "metric_definitions",
        "difficulty_labels", "capability_labels", "evaluator_definitions",
    ], ...]
    only_permitted_original_study_consequence: Literal[
        "independent_full_replication_under_corrected_provider_failure_classification"
    ]
    all_replication_observations_require_fresh_execution: Literal[True]
    original_runs_are_replication_observations: Literal[False]
    original_results_replaced_by_replication: Literal[False]
    original_and_replication_primary_metrics_pooled: Literal[False]
    replication_primary_metrics_source: Literal["replication_01_only"]
    original_study_reporting_role: Literal[
        "as_run_operational_study_and_discovered_infrastructure_incident"
    ]
    cross_study_comparison_role: Literal["descriptive_sensitivity_only"]
    no_performance_based_stopping: Literal[True]
    retry_policy: V13FormalRetryPolicy
    metrics_policy: V13FormalMetricPolicy
    slots: tuple[V13FormalReplicationSlot, ...] = Field(min_length=108, max_length=108)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        exclusions = (
            "task_selection", "task_modification", "agent_selection",
            "model_selection", "timeout", "provider_route", "task_order",
            "agent_order", "repetition_count", "retry_policy",
            "metric_definitions", "difficulty_labels", "capability_labels",
            "evaluator_definitions",
        )
        if self.original_outcomes_excluded_from != exclusions:
            raise ValueError("original-outcome exclusion boundary must be exact")
        if self.provider_failure_remediation_commit != \
                self.required_provider_failure_remediation_commit:
            raise ValueError("provider remediation links must agree")
        if len(set(self.task_order)) != 12 or len(set(self.base_agent_order)) != 3:
            raise ValueError("replication task and Agent identities must be unique")
        rotations = tuple(
            self.base_agent_order[index:] + self.base_agent_order[:index]
            for index in range(3)
        )
        if self.agent_order_by_repetition != rotations:
            raise ValueError("replication must preserve the Latin rotation")
        if tuple(slot.ordinal for slot in self.slots) != tuple(range(1, 109)):
            raise ValueError("replication ordinals must be exactly 1 through 108")
        if len({slot.slot_id for slot in self.slots}) != 108 or any(
            not slot.slot_id.startswith("rep01-r") for slot in self.slots
        ):
            raise ValueError("replication slot IDs must be unique and replication-specific")
        identities = []
        for repetition, order in enumerate(self.agent_order_by_repetition, start=1):
            for task_id in self.task_order:
                identities.extend((repetition, task_id, config_id) for config_id in order)
        if [(slot.repetition_index, slot.task_id, slot.config_id)
                for slot in self.slots] != identities:
            raise ValueError("replication slots violate the frozen execution order")
        if any(slot.replication_index != 1 for slot in self.slots):
            raise ValueError("all slots must belong to Replication-01")
        if "example_bug" in self.task_order:
            raise ValueError("calibration task cannot enter the replication")
        return self


def compute_v13_formal_replication_preregistration_sha256(
    preregistration: V13FormalReplicationPreregistration,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(preregistration.model_dump(mode="json"))
    ).hexdigest()
