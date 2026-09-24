"""Execution-admission contract for the frozen V1.3 Replication-01 study."""

import hashlib
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from patchbench.domain.formal_evidence import canonical_json_bytes
from patchbench.domain.formal_incident import GitSha
from patchbench.domain.models import DomainModel, Sha256Hex


class V13FormalReplicationExecutionSource(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    path: Literal[
        "src/patchbench/application/v13_formal_execution.py",
        "src/patchbench/application/v13_formal_replication_execution.py",
        "scripts/run_v13_formal_replication.py",
    ]
    byte_sha256: Sha256Hex


class V13FormalReplicationExecutionAdmission(DomainModel):
    """Future M18B approval of one exact reviewed replication harness."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Literal[1] = 1
    admission_id: Literal["patchbench-v1.3-replication-01-execution-admission"]
    replication_id: Literal["patchbench-v1.3-replication-01"]
    study_id: Literal["patchbench-v1.3-formal-replication-01"]
    results_namespace: Literal["results/v1.3-formal-replication-01"]
    replication_preregistration_sha256: Sha256Hex
    provider_failure_remediation_commit: GitSha
    execution_harness_commit: GitSha
    agent_manifest_sha256: Sha256Hex
    evaluation_backend: Literal["docker"]
    execution_sources: tuple[V13FormalReplicationExecutionSource, ...] = Field(
        min_length=3, max_length=3
    )

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        expected = (
            "scripts/run_v13_formal_replication.py",
            "src/patchbench/application/v13_formal_execution.py",
            "src/patchbench/application/v13_formal_replication_execution.py",
        )
        if tuple(item.path for item in self.execution_sources) != expected:
            raise ValueError("execution sources must be complete and canonically ordered")
        return self


def compute_v13_formal_replication_execution_admission_sha256(
    admission: V13FormalReplicationExecutionAdmission,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(admission.model_dump(mode="json"))
    ).hexdigest()
