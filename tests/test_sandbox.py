import subprocess
from pathlib import Path

import pytest

from patchbench.sandbox.base import SandboxHandle, sandbox_scope
from patchbench.sandbox.docker import DockerSandbox, DockerSandboxError


class RecordingSandbox:
    def __init__(self) -> None:
        self.events: list[str] = []

    def create(self, workspace: Path | None = None) -> SandboxHandle:
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


def test_create_constructs_single_fixed_workspace_mount(tmp_path, monkeypatch) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "29.7.2\n", ""),
            subprocess.CompletedProcess([], 0, "container-123\n", ""),
            subprocess.CompletedProcess([], 0, "true\n", ""),
        ]
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(*arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return next(responses)

    sandbox = DockerSandbox()
    monkeypatch.setattr(sandbox, "_run_unchecked", fake_run)

    handle = sandbox.create(tmp_path)

    assert handle.identifier == "container-123"
    assert calls[1] == (
        "run",
        "--detach",
        "--label",
        DockerSandbox.label,
        "--mount",
        f"type=bind,source={tmp_path.resolve()},target=/workspace",
        "--",
        "python:3.12-slim",
        "python",
        "-c",
        "import time; time.sleep(31536000)",
    )


def test_create_rejects_nonexistent_workspace(tmp_path) -> None:
    with pytest.raises(DockerSandboxError, match="does not exist"):
        DockerSandbox().create(tmp_path / "missing")


def test_create_rejects_workspace_that_is_not_a_directory(tmp_path) -> None:
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(DockerSandboxError, match="not a directory"):
        DockerSandbox().create(workspace_file)


def test_exec_uses_argv_and_returns_nonzero_command_result(monkeypatch) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess(
                args=[],
                returncode=7,
                stdout="captured stdout\n",
                stderr="Error response from daemon: application output\n",
            ),
            subprocess.CompletedProcess([], 0, "true\n", ""),
        ]
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(*arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return next(responses)

    sandbox = DockerSandbox()
    monkeypatch.setattr(sandbox, "_run_unchecked", fake_run)

    result = sandbox.exec(
        SandboxHandle(identifier="container-123"),
        ["python", "-c", "raise SystemExit(7)"],
    )

    assert calls == [
        (
            "exec",
            "--workdir",
            "/workspace",
            "container-123",
            "python",
            "-c",
            "raise SystemExit(7)",
        ),
        (
            "container",
            "inspect",
            "--format",
            "{{.State.Running}}",
            "container-123",
        ),
    ]
    assert result.exit_code == 7
    assert result.stdout == "captured stdout\n"
    assert result.stderr == "Error response from daemon: application output\n"


def test_exec_reports_stopped_container_as_infrastructure_error(monkeypatch) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 1, "", "command failed\n"),
            subprocess.CompletedProcess([], 0, "false\n", ""),
        ]
    )

    sandbox = DockerSandbox()
    monkeypatch.setattr(sandbox, "_run_unchecked", lambda *args: next(responses))

    with pytest.raises(DockerSandboxError, match="container-123 is not running"):
        sandbox.exec(
            SandboxHandle(identifier="container-123"),
            ["python", "-c", "raise SystemExit(1)"],
        )
