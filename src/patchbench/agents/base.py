"""Application-facing contract for coding-agent execution."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class AgentRunStatus(str, Enum):
    """Reliability-relevant outcome after agent execution has started."""

    COMPLETED = "completed"
    COMMAND_FAILED = "command_failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class AgentRunRequest:
    """Inputs required by an agent to operate on an existing workspace."""

    workspace: Path
    prompt: str
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class AgentRunResult:
    """Captured outcome of an agent execution that genuinely started."""

    status: AgentRunStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float


class AgentSetupError(RuntimeError):
    """Raised when invalid setup prevents an agent execution from starting."""


class AgentInfrastructureError(RuntimeError):
    """Raised when PatchBench cannot safely start or manage agent execution."""


class Agent(Protocol):
    """Structural contract implemented by coding-agent adapters."""

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Execute against the request workspace and return the captured outcome."""
