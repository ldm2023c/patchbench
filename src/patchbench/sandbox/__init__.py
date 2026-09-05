"""Sandbox lifecycle abstractions and implementations."""

from patchbench.sandbox.base import (
    Sandbox,
    SandboxExecResult,
    SandboxHandle,
    sandbox_scope,
)
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError

__all__ = [
    "DockerSandbox",
    "DockerSandboxError",
    "Sandbox",
    "SandboxExecResult",
    "SandboxHandle",
    "sandbox_scope",
]
