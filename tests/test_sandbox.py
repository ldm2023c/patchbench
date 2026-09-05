import subprocess

import pytest

from patchbench.sandbox.base import SandboxHandle, sandbox_scope
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError


class RecordingSandbox:
    def __init__(self) -> None:
        self.events: list[str] = []

    def create(self) -> SandboxHandle:
        self.events.append("create")
        return SandboxHandle(identifier="sandbox-123")

    def destroy(self, handle: SandboxHandle) -> None:
        self.events.append(f"destroy:{handle.identifier}")


def test_sandbox_scope_destroys_after_normal_exit() -> None:
    sandbox = RecordingSandbox()

    with sandbox_scope(sandbox) as handle:
        assert handle.identifier == "sandbox-123"

    assert sandbox.events == ["create", "destroy:sandbox-123"]


def test_sandbox_scope_destroys_after_exception() -> None:
    sandbox = RecordingSandbox()

    with pytest.raises(RuntimeError, match="scope failed"):
        with sandbox_scope(sandbox):
            raise RuntimeError("scope failed")

    assert sandbox.events == ["create", "destroy:sandbox-123"]


def test_destroy_accepts_an_already_absent_container(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["docker", "rm"],
        returncode=1,
        stdout="",
        stderr="Error response from daemon: No such container: missing",
    )
    monkeypatch.setattr(DockerSandbox, "_run_unchecked", lambda *args: completed)

    DockerSandbox().destroy(SandboxHandle(identifier="missing"))


def test_unexpected_destroy_error_is_reported(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["docker", "rm"],
        returncode=1,
        stdout="",
        stderr="permission denied",
    )
    monkeypatch.setattr(DockerSandbox, "_run_unchecked", lambda *args: completed)

    with pytest.raises(DockerSandboxError, match="permission denied"):
        DockerSandbox().destroy(SandboxHandle(identifier="container-123"))


def test_create_destroys_container_when_running_state_validation_fails(
    monkeypatch,
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "29.7.2\n", ""),
            subprocess.CompletedProcess([], 0, "container-123\n", ""),
            subprocess.CompletedProcess([], 0, "false\n", ""),
            subprocess.CompletedProcess([], 0, "container-123\n", ""),
        ]
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(*arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return next(responses)

    sandbox = DockerSandbox()
    monkeypatch.setattr(sandbox, "_run_unchecked", fake_run)

    with pytest.raises(DockerSandboxError, match="did not remain running"):
        sandbox.create()

    assert calls[-1] == ("rm", "--force", "container-123")


def test_docker_cli_os_error_is_converted_to_sandbox_error(monkeypatch) -> None:
    def missing_docker(*args, **kwargs):
        raise FileNotFoundError("docker executable not found")

    monkeypatch.setattr(subprocess, "run", missing_docker)

    with pytest.raises(
        DockerSandboxError, match="Docker CLI is unavailable.*executable not found"
    ):
        DockerSandbox().create()
