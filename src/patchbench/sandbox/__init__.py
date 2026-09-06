"""Sandbox lifecycle abstractions and implementations."""

from patchbench.sandbox.base import (
    Sandbox,
    SandboxExecResult,
    SandboxHandle,
    SandboxResourceLimits,
    sandbox_scope,
)
from patchbench.sandbox.docker import (
    DockerSandbox,
    DockerSandboxError,
    DockerSandboxTimeoutError,
)

__all__ = [
    "DockerSandbox",
    "DockerSandboxError",
    "DockerSandboxTimeoutError",
    "Sandbox",
    "SandboxExecResult",
    "SandboxHandle",
    "SandboxResourceLimits",
    "sandbox_scope",
]
