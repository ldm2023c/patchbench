"""Immutable adjudication of the original V1.3 Codex HTTP 429 incident."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.formal_evidence import canonical_json_bytes
from patchbench.domain.models import DomainModel, Sha256Hex


CanonicalId = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=False, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
)]
GitSha = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=False, pattern=r"^[0-9a-f]{40}$",
)]


class V13FormalIncidentRun(DomainModel):
    """Compact frozen evidence for one positively adjudicated original Run."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    ordinal: Annotated[int, Field(strict=True, ge=1, le=108)]
    slot_id: CanonicalId
    repetition_index: Annotated[int, Field(strict=True, ge=1, le=3)]
    task_id: CanonicalId
    config_id: Literal["codex-gpt-5.5-relay"]
    run_id: CanonicalId
    original_agent_status: Literal[AgentRunStatus.COMMAND_FAILED]
    original_evaluation_passed: bool
    agent_stdout_sha256: Sha256Hex
    incident_kind: Literal["codex_structured_http_429"]
    structured_event_types_seen: tuple[Literal["error", "turn.failed"], ...] = (
        Field(min_length=1, max_length=2)
    )

    @model_validator(mode="after")
    def validate_event_types(self) -> Self:
        expected = tuple(
            item for item in ("error", "turn.failed")
            if item in self.structured_event_types_seen
        )
        if self.structured_event_types_seen != expected:
            raise ValueError("incident event types must be unique and canonically ordered")
        return self


class V13FormalIncidentFreeze(DomainModel):
    """Checked incident evidence linked to the immutable original formal study."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Literal[1] = 1
    incident_id: Literal["patchbench-v1.3-original-codex-429"]
    original_study_id: Literal["patchbench-v1.3-formal"]
    original_formal_preregistration_sha256: Sha256Hex
    original_formal_evidence_freeze_sha256: Sha256Hex
    original_formal_analysis_sha256: Sha256Hex
    original_execution_harness_commit: GitSha
    provider_failure_remediation_commit: GitSha
    original_codex_planned_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    original_codex_completed_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    original_codex_command_failed_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    original_codex_timed_out_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    structured_429_adjudicated_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    unadjudicated_command_failed_slots: Annotated[int, Field(strict=True, ge=0, le=108)]
    adjudicated_runs: tuple[V13FormalIncidentRun, ...]
    unadjudicated_command_failed_run_ids: tuple[CanonicalId, ...]
    comparative_capability_interpretation_status: Literal["infrastructure_confounded"]
    original_study_remains_as_run_operational_evidence: Literal[True]

    @model_validator(mode="after")
    def validate_population(self) -> Self:
        if (
            self.original_codex_completed_slots
            + self.original_codex_command_failed_slots
            + self.original_codex_timed_out_slots
            != self.original_codex_planned_slots
        ):
            raise ValueError("Codex outcome counts must cover the planned population")
        if (
            self.structured_429_adjudicated_slots != len(self.adjudicated_runs)
            or self.unadjudicated_command_failed_slots
            != len(self.unadjudicated_command_failed_run_ids)
            or self.structured_429_adjudicated_slots
            + self.unadjudicated_command_failed_slots
            != self.original_codex_command_failed_slots
        ):
            raise ValueError("incident counts must partition Codex command failures")
        if len({item.run_id for item in self.adjudicated_runs}) != len(
            self.adjudicated_runs
        ):
            raise ValueError("adjudicated Run IDs must be unique")
        if tuple(item.ordinal for item in self.adjudicated_runs) != tuple(
            sorted(item.ordinal for item in self.adjudicated_runs)
        ):
            raise ValueError("adjudicated Runs must preserve original ordinal order")
        if len(set(self.unadjudicated_command_failed_run_ids)) != len(
            self.unadjudicated_command_failed_run_ids
        ):
            raise ValueError("unadjudicated Run IDs must be unique")
        return self


def compute_v13_formal_incident_freeze_sha256(
    freeze: V13FormalIncidentFreeze,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(freeze.model_dump(mode="json"))
    ).hexdigest()
