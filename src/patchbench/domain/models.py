"""Domain models for PatchBench."""

from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patchbench.agents.base import AgentRunStatus


NonEmptyString = Annotated[str, Field(min_length=1)]


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


class RunRecord(DomainModel):
    """Summary of one completed PatchBench Run."""

    run_id: NonEmptyString
    task_id: NonEmptyString
    status: RunStatus
    evaluation_passed: bool
    duration_seconds: float = Field(ge=0)
    agent: AgentExecutionMetadata
    artifacts: ArtifactPaths


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
