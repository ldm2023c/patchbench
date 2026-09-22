"""Compact cryptographic freeze of accepted V1.3 calibration evidence."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.calibration_run import CalibrationBatchStatus
from patchbench.domain.models import AgentIdentityBinding, DomainModel, Sha256Hex


CanonicalId = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False,
                      pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]


class V13CalibrationEvidenceSlot(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    config_id: CanonicalId
    experiment_id: CanonicalId
    run_id: CanonicalId
    agent_status: Literal[AgentRunStatus.COMPLETED]
    evaluation_passed: bool
    identity_binding: AgentIdentityBinding
    run_semantic_sha256: Sha256Hex
    experiment_semantic_sha256: Sha256Hex
    prompt_sha256: Sha256Hex
    agent_stdout_sha256: Sha256Hex
    agent_stderr_sha256: Sha256Hex
    test_log_sha256: Sha256Hex
    patch_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.identity_binding.config_id != self.config_id:
            raise ValueError("calibration freeze slot binding config ID mismatch")
        return self


class V13CalibrationEvidenceFreeze(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    freeze_id: Literal["patchbench-v1.3-calibration-001"]
    source_batch_id: Literal["calibration-001"]
    source_batch_status: Literal[CalibrationBatchStatus.ACCEPTED]
    source_batch_json_sha256: Sha256Hex
    source_batch_semantic_sha256: Sha256Hex
    calibration_protocol_sha256: Sha256Hex
    m3_candidate_sha256: Sha256Hex
    m8_agent_manifest_sha256: Sha256Hex
    calibration_task_id: Literal["example_bug"]
    ordered_agent_config_ids: tuple[CanonicalId, ...] = Field(min_length=3, max_length=3)
    slots: tuple[V13CalibrationEvidenceSlot, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_slots(self) -> Self:
        slot_ids = tuple(slot.config_id for slot in self.slots)
        if slot_ids != self.ordered_agent_config_ids:
            raise ValueError("calibration freeze slots must match frozen config order")
        if len(set(slot_ids)) != 3:
            raise ValueError("calibration freeze requires three unique configurations")
        if any(slot.identity_binding.manifest_sha256 != self.m8_agent_manifest_sha256
               for slot in self.slots):
            raise ValueError("calibration freeze binding manifest SHA mismatch")
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_v13_calibration_batch_sha256(batch) -> str:
    """Hash all validated batch semantics using canonical JSON."""
    return hashlib.sha256(_canonical_json_bytes(batch.model_dump(mode="json"))).hexdigest()


def compute_run_semantic_sha256(run) -> str:
    """Hash validated Run semantics without machine-local artifact locators."""
    payload = run.model_dump(mode="json", exclude={"artifacts"})
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def compute_experiment_semantic_sha256(experiment) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(experiment.model_dump(mode="json"))
    ).hexdigest()


def compute_v13_calibration_evidence_freeze_sha256(
    freeze: V13CalibrationEvidenceFreeze,
) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(freeze.model_dump(mode="json"))
    ).hexdigest()
