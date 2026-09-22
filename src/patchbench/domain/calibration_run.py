"""Measured records for PatchBench V1.3 calibration batches."""

from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.models import AgentIdentityBinding, DomainModel, Sha256Hex


SafeBatchId = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=False, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ),
]
SafeReason = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, pattern=r"^[a-z][a-z0-9_]*$"),
]
ExactText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=1, max_length=500),
]


class CalibrationBatchStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED_NOT_ADMITTED = "completed_not_admitted"
    ACCEPTED = "accepted"
    ABORTED = "aborted"


class CalibrationSlotStatus(str, Enum):
    PENDING = "pending"
    RUNTIME_ADMITTED = "runtime_admitted"
    RUNTIME_NOT_ADMITTED = "runtime_not_admitted"


class CalibrationFailureReason(str, Enum):
    AGENT_COMMAND_FAILED = "agent_command_failed"
    AGENT_TIMED_OUT = "agent_timed_out"
    AGENT_SETUP_FAILED = "agent_setup_failed"
    AGENT_INFRASTRUCTURE_FAILED = "agent_infrastructure_failed"
    REPOSITORY_FAILED = "repository_failed"
    EVALUATION_INFRASTRUCTURE_FAILED = "evaluation_infrastructure_failed"
    ARTIFACT_STORE_FAILED = "artifact_store_failed"
    EVIDENCE_INTEGRITY_FAILED = "evidence_integrity_failed"


class V13CalibrationSlot(DomainModel):
    """One frozen configuration's measured result within a calibration batch."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    config_id: SafeBatchId
    status: CalibrationSlotStatus
    experiment_id: SafeBatchId | None = None
    run_id: SafeBatchId | None = None
    agent_status: AgentRunStatus | None = None
    evaluation_passed: bool | None = None
    identity_binding: AgentIdentityBinding | None = None
    failure_reason: CalibrationFailureReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        measured = (
            self.experiment_id,
            self.run_id,
            self.agent_status,
            self.evaluation_passed,
            self.identity_binding,
        )
        if self.status is CalibrationSlotStatus.PENDING:
            if any(value is not None for value in (*measured, self.failure_reason)):
                raise ValueError("pending calibration slot must not contain outcome fields")
        elif self.status is CalibrationSlotStatus.RUNTIME_ADMITTED:
            if any(value is None for value in measured):
                raise ValueError("runtime-admitted slot requires complete measured evidence")
            if self.agent_status is not AgentRunStatus.COMPLETED:
                raise ValueError("runtime-admitted slot requires COMPLETED Agent status")
            if self.failure_reason is not None:
                raise ValueError("runtime-admitted slot must not contain failure_reason")
        else:
            if self.failure_reason is None:
                raise ValueError("runtime-not-admitted slot requires failure_reason")
            if (self.agent_status is AgentRunStatus.COMPLETED
                    and self.failure_reason not in {
                        CalibrationFailureReason.ARTIFACT_STORE_FAILED,
                        CalibrationFailureReason.EVIDENCE_INTEGRITY_FAILED,
                    }):
                raise ValueError(
                    "COMPLETED Agent status may be non-admitted only when its "
                    "required evidence cannot be trusted"
                )
            linked = (self.experiment_id, self.run_id, self.agent_status,
                      self.evaluation_passed, self.identity_binding)
            if any(value is not None for value in linked) and any(
                value is None for value in linked
            ):
                raise ValueError("measured runtime failure requires complete Run linkage")
        return self


class V13CalibrationBatch(DomainModel):
    """Immutable-at-terminal ledger for one three-configuration calibration attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    batch_id: SafeBatchId
    protocol_sha256: Sha256Hex
    calibration_task_id: SafeBatchId
    calibration_task_spec_sha256: Sha256Hex
    m3_candidate_sha256: Sha256Hex
    m8_agent_manifest_sha256: Sha256Hex
    ordered_agent_config_ids: tuple[SafeBatchId, ...] = Field(min_length=1)
    previous_batch_id: SafeBatchId | None = None
    environment_remediation: ExactText | None = None
    status: CalibrationBatchStatus
    slots: tuple[V13CalibrationSlot, ...] = Field(min_length=1)

    @field_validator("batch_id", "previous_batch_id")
    @classmethod
    def reject_dot_ids(cls, value: str | None) -> str | None:
        if value in {".", ".."}:
            raise ValueError("batch identifiers must be safe direct-child names")
        return value

    @model_validator(mode="after")
    def validate_batch_state(self) -> Self:
        if len(set(self.ordered_agent_config_ids)) != len(self.ordered_agent_config_ids):
            raise ValueError("ordered calibration configuration IDs must be unique")
        if tuple(slot.config_id for slot in self.slots) != self.ordered_agent_config_ids:
            raise ValueError("calibration slots must exactly match frozen configuration order")
        if (self.previous_batch_id is None) != (self.environment_remediation is None):
            raise ValueError("predecessor and remediation must be supplied together")
        pending = [slot.status is CalibrationSlotStatus.PENDING for slot in self.slots]
        admitted = [
            slot.status is CalibrationSlotStatus.RUNTIME_ADMITTED for slot in self.slots
        ]
        if self.status is CalibrationBatchStatus.IN_PROGRESS:
            if not any(pending):
                raise ValueError("in-progress calibration batch requires a pending slot")
        elif any(pending):
            if self.status is not CalibrationBatchStatus.ABORTED:
                raise ValueError("only an aborted terminal batch may retain pending slots")
        elif self.status is CalibrationBatchStatus.ACCEPTED:
            if not all(admitted):
                raise ValueError("accepted calibration batch requires all slots admitted")
        elif self.status is CalibrationBatchStatus.COMPLETED_NOT_ADMITTED:
            if all(admitted):
                raise ValueError("completed-not-admitted batch requires a failed slot")
        return self
