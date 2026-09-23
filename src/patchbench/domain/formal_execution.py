"""Strict execution ledgers for the PatchBench V1.3 formal study."""

from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import DomainModel, Sha256Hex


SafeId = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=False, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
)]
Remediation = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=False, min_length=1, max_length=500,
)]


class FormalStudyStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    RETRY_REQUIRED = "retry_required"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class FormalSlotStatus(str, Enum):
    PENDING = "pending"
    ATTEMPT_IN_PROGRESS = "attempt_in_progress"
    RETRY_REQUIRED = "retry_required"
    CANONICAL_OBSERVED = "canonical_observed"
    UNRESOLVED_INFRASTRUCTURE = "unresolved_infrastructure"
    BLOCKED = "blocked"


class FormalAttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    CANONICAL_OBSERVED = "canonical_observed"
    RETRYABLE_INFRASTRUCTURE_FAILURE = "retryable_infrastructure_failure"
    UNRESOLVED_INFRASTRUCTURE = "unresolved_infrastructure"
    BLOCKED = "blocked"


class FormalFailureCategory(str, Enum):
    AGENT_SETUP = "agent_setup"
    AGENT_INFRASTRUCTURE = "agent_infrastructure"
    REPOSITORY_INFRASTRUCTURE = "repository_infrastructure"
    DOCKER_INFRASTRUCTURE = "docker_infrastructure"
    ARTIFACT_INFRASTRUCTURE_BEFORE_CANONICAL_RUN = (
        "artifact_infrastructure_before_canonical_run"
    )
    NETWORK_PROVIDER_TRANSPORT_SAME_ROUTE = "network_provider_transport_same_route"
    EVALUATION_INFRASTRUCTURE = "evaluation_infrastructure"
    FROZEN_INPUT_INTEGRITY = "frozen_input_integrity"
    EVIDENCE_INTEGRITY = "evidence_integrity"
    INTERRUPTED_ATTEMPT_UNCERTAIN = "interrupted_attempt_uncertain"
    UNEXPECTED = "unexpected"


class V13FormalAttemptRecord(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    slot_id: SafeId
    attempt_index: Annotated[int, Field(strict=True, ge=1, le=2)]
    status: FormalAttemptStatus
    formal_preregistration_sha256: Sha256Hex
    config_id: SafeId
    task_id: SafeId
    remediation: Remediation | None = None
    failure_category: FormalFailureCategory | None = None
    canonical_run_id: SafeId | None = None
    agent_status: AgentRunStatus | None = None
    evaluation_passed: bool | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (self.attempt_index == 1) != (self.remediation is None):
            raise ValueError("only attempt 2 requires an explicit remediation")
        canonical = (self.canonical_run_id, self.agent_status, self.evaluation_passed)
        if self.status is FormalAttemptStatus.IN_PROGRESS:
            if self.failure_category is not None or any(v is not None for v in canonical):
                raise ValueError("in-progress attempt cannot contain an outcome")
        elif self.status is FormalAttemptStatus.CANONICAL_OBSERVED:
            if self.failure_category is not None or any(v is None for v in canonical):
                raise ValueError("canonical attempt requires complete canonical outcome")
        else:
            if self.failure_category is None or any(v is not None for v in canonical):
                raise ValueError("failed attempt requires only a stable failure category")
        return self


class V13FormalSlotExecution(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    ordinal: Annotated[int, Field(strict=True, ge=1, le=108)]
    slot_id: SafeId
    repetition_index: Annotated[int, Field(strict=True, ge=1, le=3)]
    task_id: SafeId
    config_id: SafeId
    status: FormalSlotStatus
    attempts: tuple[Annotated[int, Field(strict=True, ge=1, le=2)], ...] = ()
    canonical_attempt_index: Annotated[int, Field(strict=True, ge=1, le=2)] | None = None
    canonical_run_id: SafeId | None = None
    canonical_agent_status: AgentRunStatus | None = None
    canonical_evaluation_passed: bool | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.attempts not in ((), (1,), (1, 2)):
            raise ValueError("formal attempts must be an ordered prefix of attempts 1 and 2")
        canonical = (self.canonical_attempt_index, self.canonical_run_id,
                     self.canonical_agent_status, self.canonical_evaluation_passed)
        if self.status is FormalSlotStatus.PENDING:
            if self.attempts or any(v is not None for v in canonical):
                raise ValueError("pending slot cannot contain attempt outcomes")
        elif self.status is FormalSlotStatus.CANONICAL_OBSERVED:
            if any(v is None for v in canonical):
                raise ValueError("canonical slot requires complete canonical outcome")
            if self.canonical_attempt_index not in self.attempts:
                raise ValueError("canonical attempt must belong to the slot")
        elif any(v is not None for v in canonical):
            raise ValueError("noncanonical slot cannot contain canonical fields")
        elif not self.attempts:
            raise ValueError("non-pending slot requires an attempt")
        if self.status is FormalSlotStatus.RETRY_REQUIRED and self.attempts != (1,):
            raise ValueError("retry-required slot must have only attempt 1")
        if (self.status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
                and self.attempts != (1, 2)):
            raise ValueError("unresolved slot requires both attempts")
        return self


class V13FormalStudyLedger(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    study_id: SafeId
    formal_preregistration_sha256: Sha256Hex
    planned_slot_count: Annotated[int, Field(strict=True, ge=108, le=108)] = 108
    status: FormalStudyStatus
    slots: tuple[V13FormalSlotExecution, ...] = Field(min_length=108, max_length=108)

    @model_validator(mode="after")
    def validate_study(self) -> Self:
        if tuple(slot.ordinal for slot in self.slots) != tuple(range(1, 109)):
            raise ValueError("study slots must have ordinals 1 through 108")
        if len({slot.slot_id for slot in self.slots}) != 108:
            raise ValueError("study slot IDs must be unique")
        nonterminal = {
            FormalSlotStatus.PENDING, FormalSlotStatus.ATTEMPT_IN_PROGRESS,
            FormalSlotStatus.RETRY_REQUIRED, FormalSlotStatus.BLOCKED,
        }
        first_nonterminal = next(
            (i for i, slot in enumerate(self.slots) if slot.status in nonterminal),
            None,
        )
        if first_nonterminal is not None and any(
            slot.status is not FormalSlotStatus.PENDING
            for slot in self.slots[first_nonterminal + 1:]
        ):
            raise ValueError("later slots cannot pass an earlier nonterminal slot")
        statuses = {slot.status for slot in self.slots}
        terminal = {
            FormalSlotStatus.CANONICAL_OBSERVED,
            FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE,
        }
        if statuses == {FormalSlotStatus.PENDING}:
            expected_status = FormalStudyStatus.READY
        elif statuses <= terminal:
            expected_status = FormalStudyStatus.COMPLETED
        elif FormalSlotStatus.BLOCKED in statuses:
            expected_status = FormalStudyStatus.BLOCKED
        elif FormalSlotStatus.RETRY_REQUIRED in statuses:
            expected_status = FormalStudyStatus.RETRY_REQUIRED
        else:
            expected_status = FormalStudyStatus.RUNNING
        if self.status is not expected_status:
            raise ValueError("study status differs from slot states")
        return self
