"""Domain models for PatchBench."""

from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from patchbench.agents.base import AgentRunStatus


NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False,
                      min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class DomainModel(BaseModel):
    """Shared validation behavior for PatchBench domain models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RepositoryConfig(DomainModel):
    """Source repository required by a task."""

    type: Literal["local"]
    path: NonEmptyString
    base_commit: NonEmptyString


class TaskPromptConfig(DomainModel):
    """Instructions presented to a coding agent."""

    prompt: NonEmptyString


class EvaluationConfig(DomainModel):
    """Command and time limit used to evaluate a task."""

    command: NonEmptyString
    timeout_seconds: int = Field(gt=0)


class TaskMetadata(DomainModel):
    """Optional descriptive information about a task."""

    language: NonEmptyString | None = None


class TaskSpec(DomainModel):
    """A complete, versioned PatchBench task definition."""

    schema_version: Literal[1]
    id: NonEmptyString
    repository: RepositoryConfig
    task: TaskPromptConfig
    evaluation: EvaluationConfig
    metadata: TaskMetadata = Field(default_factory=TaskMetadata)


class RunStatus(str, Enum):
    """Final outcome of a completed local Run."""

    PASSED = "passed"
    FAILED = "failed"


class AgentExecutionMetadata(DomainModel):
    """Reliability-relevant facts for one host agent execution."""

    name: NonEmptyString
    backend: Literal["host"]
    status: AgentRunStatus
    exit_code: int | None
    duration_seconds: float = Field(ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    requested_model: NonEmptyString | None = None


class ExperimentConfiguration(DomainModel):
    """Frozen execution configuration shared by an Experiment's Runs."""

    agent_name: NonEmptyString
    requested_model: NonEmptyString | None = None
    agent_timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    evaluation_backend: Literal["host", "docker"]


class ExperimentAggregate(DomainModel):
    """Reliability metrics calculated from completed Runs."""

    run_count: int = Field(ge=1)
    evaluation_pass_count: int = Field(ge=0)
    evaluation_fail_count: int = Field(ge=0)
    evaluation_pass_rate: float = Field(ge=0, le=1)
    agent_command_failure_count: int = Field(ge=0)
    agent_timeout_count: int = Field(ge=0)
    total_duration_seconds: float = Field(ge=0)
    mean_duration_seconds: float = Field(ge=0)
    min_duration_seconds: float = Field(ge=0)
    max_duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """Ensure aggregate counts are consistent with the Run count."""

        if self.evaluation_pass_count + self.evaluation_fail_count != self.run_count:
            raise ValueError("evaluation pass and fail counts must equal run_count")
        if self.agent_command_failure_count > self.run_count:
            raise ValueError("agent_command_failure_count must not exceed run_count")
        if self.agent_timeout_count > self.run_count:
            raise ValueError("agent_timeout_count must not exceed run_count")
        return self


class EvaluationResult(DomainModel):
    """Normalized result from executing a task evaluation command."""

    exit_code: int
    passed: bool
    duration_seconds: float = Field(ge=0)
    stdout: str
    stderr: str


class ArtifactPaths(DomainModel):
    """Filesystem locations persisted for one Run."""

    directory: Path
    metadata: Path
    prompt: Path
    agent_log: Path
    agent_stderr_log: Path
    test_log: Path
    patch: Path


class RunProvenance(DomainModel):
    """Frozen task and evaluation configuration used by a newly executed Run."""

    base_commit_used: NonEmptyString
    task_fingerprint_sha256: Sha256Hex
    evaluation_command: NonEmptyString
    evaluation_timeout_seconds: int = Field(gt=0)
    evaluation_backend: Literal["host", "docker"]


class PatchFileSummary(DomainModel):
    """Exact identity and observable changes of one Git diff section."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: NonEmptyString
    role: Literal["non_test", "test", "generated"]
    change_type: Literal["added", "modified", "deleted", "renamed", "copied"]
    binary: bool
    added_lines: int | None
    deleted_lines: int | None
    diff_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_line_counts(self) -> Self:
        counts = (self.added_lines, self.deleted_lines)
        if self.binary:
            if counts != (None, None):
                raise ValueError("binary files must have null line counts")
        elif any(count is None or count < 0 for count in counts):
            raise ValueError("text files require nonnegative line counts")
        return self


class PatchSummary(DomainModel):
    """Exact patch identity and totals over per-file evidence."""

    patch_sha256: Sha256Hex
    patch_bytes: int = Field(ge=0)
    changed_file_count: int = Field(ge=0)
    text_added_lines: int = Field(ge=0)
    text_deleted_lines: int = Field(ge=0)
    files: list[PatchFileSummary]

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.changed_file_count != len(self.files):
            raise ValueError("changed_file_count must equal len(files)")
        if self.text_added_lines != sum(f.added_lines for f in self.files if not f.binary):
            raise ValueError("text_added_lines must equal text file total")
        if self.text_deleted_lines != sum(f.deleted_lines for f in self.files if not f.binary):
            raise ValueError("text_deleted_lines must equal text file total")
        return self


class EvaluationCaseEvidence(DomainModel):
    """A directly reported unittest failure or error identifier."""

    name: NonEmptyString
    outcome: Literal["fail", "error"]


class EvaluationEvidence(DomainModel):
    """Deterministic observations from a canonical evaluation log."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    test_log_sha256: Sha256Hex
    exit_code: int
    passed: bool
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    framework: Literal["unittest", "unknown"]
    tests_run: int | None
    failure_count: int | None
    error_count: int | None
    failing_cases: list[EvaluationCaseEvidence]
    output_tail: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        if self.passed != (self.exit_code == 0):
            raise ValueError("passed must agree with exit_code")
        counts = (self.tests_run, self.failure_count, self.error_count)
        if self.framework == "unknown":
            if counts != (None, None, None) or self.failing_cases:
                raise ValueError("unknown framework must not claim unittest results")
        elif any(count is None or count < 0 for count in counts):
            raise ValueError("unittest requires nonnegative counts")
        if any(not line.strip() for line in self.output_tail):
            raise ValueError("output_tail must contain non-empty lines")
        return self


class RunRecord(DomainModel):
    """Summary of one completed PatchBench Run."""

    run_id: NonEmptyString
    task_id: NonEmptyString
    status: RunStatus
    evaluation_passed: bool
    duration_seconds: float = Field(ge=0)
    agent: AgentExecutionMetadata
    artifacts: ArtifactPaths
    provenance: RunProvenance | None = None
    patch_summary: PatchSummary | None = None
    evaluation_evidence: EvaluationEvidence | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if (self.patch_summary is None) != (self.evaluation_evidence is None):
            raise ValueError("patch and evaluation evidence must both be present or absent")
        if (self.evaluation_evidence is not None
                and self.evaluation_evidence.passed != self.evaluation_passed):
            raise ValueError("evaluation evidence must agree with Run outcome")
        return self


class ReplayRecord(DomainModel):
    """Summary of one completed historical-patch Replay."""

    replay_id: NonEmptyString
    source_run_id: NonEmptyString
    task_id: NonEmptyString
    base_commit_used: NonEmptyString
    evaluation_backend: Literal["host", "docker"]
    source_evaluation_passed: bool
    replay_evaluation_passed: bool
    outcome_matches: bool
    duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome_match(self) -> Self:
        """Ensure the persisted verdict agrees with both evaluation outcomes."""

        expected = self.source_evaluation_passed == self.replay_evaluation_passed
        if self.outcome_matches != expected:
            raise ValueError("outcome_matches must agree with evaluation outcomes")
        return self


class ExperimentRecord(DomainModel):
    """Summary of one fully completed repeated Experiment."""

    experiment_id: NonEmptyString
    task_id: NonEmptyString
    requested_runs: int = Field(ge=1, strict=True)
    run_ids: list[NonEmptyString] = Field(min_length=1)
    configuration: ExperimentConfiguration
    aggregate: ExperimentAggregate
    duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_run_cardinality(self) -> Self:
        """Ensure every requested completed Run has one unique identifier."""

        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("run_ids must contain unique IDs")
        if self.requested_runs != len(self.run_ids):
            raise ValueError("requested_runs must equal the number of run_ids")
        if self.requested_runs != self.aggregate.run_count:
            raise ValueError("requested_runs must equal aggregate.run_count")
        return self
