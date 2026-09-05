"""Minimal sandbox lifecycle contract for Milestone 2.1."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SandboxHandle:
    """Opaque identifier for a created sandbox."""

    identifier: str

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("Sandbox identifier must not be empty")


class Sandbox(Protocol):
    """Contract for creating and destroying one sandbox."""

    def create(self) -> SandboxHandle:
        """Create a sandbox and return its handle."""

    def destroy(self, handle: SandboxHandle) -> None:
        """Destroy the sandbox identified by the handle."""


@contextmanager
def sandbox_scope(sandbox: Sandbox) -> Iterator[SandboxHandle]:
    """Create a sandbox and guarantee a destroy attempt on scope exit."""

    handle = sandbox.create()
    try:
        yield handle
    finally:
        sandbox.destroy(handle)
