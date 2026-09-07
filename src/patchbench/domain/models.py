"""Domain models for PatchBench task definitions."""

from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from patchbench.agents.base import AgentRunStatus


NonEmptyString = Annotated[str, Field(min_length=1)]


class DomainModel(BaseModel):
    """Shared validation behavior for task domain models."""

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
