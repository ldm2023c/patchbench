"""Sandbox lifecycle and command-execution contract for Milestone 2.2."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
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


class Sandbox(Protocol):
    """Contract for one sandbox lifecycle and explicit command execution."""

    def create(self, workspace: Path | None = None) -> SandboxHandle:
        """Create a sandbox and return its handle."""

    def exec(
        self, handle: SandboxHandle, command: Sequence[str]
    ) -> SandboxExecResult:
        """Execute an argv-style command inside a running sandbox."""

    def destroy(self, handle: SandboxHandle) -> None:
        """Destroy the sandbox identified by the handle."""


@contextmanager
def sandbox_scope(
    sandbox: Sandbox, *, workspace: Path | None = None
) -> Iterator[SandboxHandle]:
    """Create a sandbox and guarantee a destroy attempt on scope exit."""

    handle = sandbox.create(workspace)
    try:
        yield handle
    finally:
        sandbox.destroy(handle)
