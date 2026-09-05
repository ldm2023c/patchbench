"""Sandbox lifecycle abstractions and implementations."""

from patchbench.sandbox.base import Sandbox, SandboxHandle, sandbox_scope
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError

__all__ = [
    "DockerSandbox",
    "DockerSandboxError",
    "Sandbox",
    "SandboxHandle",
    "sandbox_scope",
]
