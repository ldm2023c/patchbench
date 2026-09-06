"""Sandbox lifecycle and bounded command-execution contract."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SandboxHandle:
    """Opaque identifier for a created sandbox."""

    identifier: str

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("Sandbox identifier must not be empty")


@dataclass(frozen=True)
class SandboxExecResult:
    """Captured result of one command executed inside a sandbox."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SandboxResourceLimits:
    """Implementation-independent resource limits for one sandbox."""

    cpus: float | None = None
    memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.cpus is not None and (
            isinstance(self.cpus, bool)
            or not isinstance(self.cpus, (int, float))
            or not isfinite(self.cpus)
            or self.cpus <= 0
        ):
            raise ValueError("Sandbox CPU limit must be a finite positive number")
        if self.memory_bytes is not None and (
            isinstance(self.memory_bytes, bool)
            or not isinstance(self.memory_bytes, int)
            or self.memory_bytes <= 0
        ):
            raise ValueError("Sandbox memory limit must be a positive integer")


class Sandbox(Protocol):
    """Contract for one sandbox lifecycle and explicit command execution."""

    def create(
        self,
        workspace: Path | None = None,
        resource_limits: SandboxResourceLimits | None = None,
    ) -> SandboxHandle:
        """Create a sandbox and return its handle."""

    def exec(
        self,
        handle: SandboxHandle,
        command: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> SandboxExecResult:
        """Execute an argv-style command inside a running sandbox."""

    def destroy(self, handle: SandboxHandle) -> None:
        """Destroy the sandbox identified by the handle."""


@contextmanager
def sandbox_scope(
    sandbox: Sandbox,
    *,
    workspace: Path | None = None,
    resource_limits: SandboxResourceLimits | None = None,
) -> Iterator[SandboxHandle]:
    """Create a sandbox and guarantee a destroy attempt on scope exit."""

    handle = sandbox.create(workspace, resource_limits)
    try:
        yield handle
    finally:
        sandbox.destroy(handle)
