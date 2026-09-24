"""Compact cryptographic evidence for the completed V1.3 formal study."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.benchmark import BenchmarkCapability, DesignedDifficulty
from patchbench.domain.formal_execution import (
    FormalAttemptStatus, FormalFailureCategory, FormalSlotStatus,
)
from patchbench.domain.models import AgentIdentityBinding, DomainModel, Sha256Hex


CanonicalId = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=False, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
)]


class V13FormalAttemptEvidence(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    attempt_index: Annotated[int, Field(strict=True, ge=1, le=2)]
    status: FormalAttemptStatus
    remediation: str | None = None
    failure_category: FormalFailureCategory | None = None
    attempt_json_sha256: Sha256Hex
    attempt_semantic_sha256: Sha256Hex
    canonical_run_id: str | None = None
    agent_status: AgentRunStatus | None = None
    evaluation_passed: bool | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if (self.attempt_index == 1) != (self.remediation is None):
            raise ValueError("only attempt 2 carries explicit remediation")
        canonical = (self.canonical_run_id, self.agent_status, self.evaluation_passed)
        if self.status is FormalAttemptStatus.CANONICAL_OBSERVED:
            if self.failure_category is not None or any(value is None for value in canonical):
                raise ValueError("canonical attempt evidence is incomplete")
        elif self.status in {
                FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE,
                FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE,
        }:
            if self.failure_category is None or any(value is not None for value in canonical):
                raise ValueError("infrastructure attempt evidence is inconsistent")
        else:
            raise ValueError("formal freeze cannot contain nonterminal or blocked attempts")
        return self


class V13FormalRunEvidence(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    run_id: CanonicalId
    agent_status: AgentRunStatus
    evaluation_passed: bool
    identity_binding: AgentIdentityBinding
    run_semantic_sha256: Sha256Hex
    metadata_sha256: Sha256Hex
    prompt_sha256: Sha256Hex
    agent_stdout_sha256: Sha256Hex
    agent_stderr_sha256: Sha256Hex
    test_log_sha256: Sha256Hex
    patch_sha256: Sha256Hex


class V13FormalSlotEvidence(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    ordinal: Annotated[int, Field(strict=True, ge=1, le=108)]
    slot_id: CanonicalId
    repetition_index: Annotated[int, Field(strict=True, ge=1, le=3)]
    task_id: CanonicalId
    config_id: CanonicalId
    primary_capability: BenchmarkCapability
    designed_difficulty: DesignedDifficulty
    source_slot_status: Literal[
        FormalSlotStatus.CANONICAL_OBSERVED,
        FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE,
    ]
    attempts: tuple[V13FormalAttemptEvidence, ...] = Field(min_length=1, max_length=2)
    canonical_attempt_index: Annotated[int, Field(strict=True, ge=1, le=2)] | None
    canonical_run: V13FormalRunEvidence | None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        indexes = tuple(item.attempt_index for item in self.attempts)
        if indexes not in ((1,), (1, 2)):
            raise ValueError("formal evidence attempts must be an ordered prefix")
        if len(self.attempts) == 2 and (
                self.attempts[0].status
                is not FormalAttemptStatus.RETRYABLE_INFRASTRUCTURE_FAILURE
                or self.attempts[1].status not in {
                    FormalAttemptStatus.CANONICAL_OBSERVED,
                    FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE,
                }):
            raise ValueError("attempt 2 requires a retryable attempt 1")
        if self.source_slot_status is FormalSlotStatus.CANONICAL_OBSERVED:
            if (self.canonical_run is None
                    or self.canonical_attempt_index != indexes[-1]
                    or self.canonical_run.identity_binding.config_id != self.config_id):
                raise ValueError("canonical slot requires its exact canonical evidence")
            attempt = self.attempts[self.canonical_attempt_index - 1]
            if (attempt.status is not FormalAttemptStatus.CANONICAL_OBSERVED
                    or attempt.canonical_run_id != self.canonical_run.run_id
                    or attempt.agent_status is not self.canonical_run.agent_status
                    or attempt.evaluation_passed != self.canonical_run.evaluation_passed):
                raise ValueError("canonical attempt and Run evidence differ")
        elif (self.canonical_attempt_index is not None or self.canonical_run is not None
              or len(self.attempts) != 2
              or self.attempts[1].status
              is not FormalAttemptStatus.UNRESOLVED_INFRASTRUCTURE):
            raise ValueError("unresolved slot must preserve two failed attempts")
        return self


class V13FormalEvidenceFreeze(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    freeze_id: Literal["patchbench-v1.3-formal-results"]
    study_id: Literal["patchbench-v1.3-formal"]
    formal_preregistration_sha256: Sha256Hex
    design_sha256: Sha256Hex
    candidate_sha256: Sha256Hex
    agent_manifest_sha256: Sha256Hex
    execution_harness_commit: Literal["c735b112770060cb1dd367406c5b764f673ce6ba"]
    source_study_status: Literal["completed"]
    source_study_json_sha256: Sha256Hex
    source_study_semantic_sha256: Sha256Hex
    planned_slot_count: Literal[108]
    canonical_slot_count: Annotated[int, Field(strict=True, ge=0, le=108)]
    unresolved_infrastructure_slot_count: Annotated[int, Field(strict=True, ge=0, le=108)]
    slots: tuple[V13FormalSlotEvidence, ...] = Field(min_length=108, max_length=108)

    @model_validator(mode="after")
    def validate_slots(self) -> Self:
        if tuple(slot.ordinal for slot in self.slots) != tuple(range(1, 109)):
            raise ValueError("formal evidence slots must preserve exact ordinal order")
        if len({slot.slot_id for slot in self.slots}) != 108:
            raise ValueError("formal evidence slot IDs must be unique")
        canonical = sum(
            slot.source_slot_status is FormalSlotStatus.CANONICAL_OBSERVED
            for slot in self.slots
        )
        unresolved = sum(
            slot.source_slot_status is FormalSlotStatus.UNRESOLVED_INFRASTRUCTURE
            for slot in self.slots
        )
        if (canonical != self.canonical_slot_count
                or unresolved != self.unresolved_infrastructure_slot_count
                or canonical + unresolved != self.planned_slot_count):
            raise ValueError("formal evidence outcome counts differ from slots")
        return self


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_v13_formal_study_sha256(study) -> str:
    return hashlib.sha256(canonical_json_bytes(study.model_dump(mode="json"))).hexdigest()


def compute_v13_formal_attempt_sha256(attempt) -> str:
    return hashlib.sha256(canonical_json_bytes(attempt.model_dump(mode="json"))).hexdigest()


def compute_v13_formal_evidence_freeze_sha256(
    freeze: V13FormalEvidenceFreeze,
) -> str:
    return hashlib.sha256(canonical_json_bytes(freeze.model_dump(mode="json"))).hexdigest()
