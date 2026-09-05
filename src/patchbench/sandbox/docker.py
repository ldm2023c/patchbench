"""Docker-backed sandbox lifecycle and command-execution implementation."""

from collections.abc import Sequence
from pathlib import Path
import subprocess

from patchbench.sandbox.base import SandboxExecResult, SandboxHandle


class DockerSandboxError(RuntimeError):
    """Raised when the Docker CLI or daemon cannot complete an operation."""


class DockerSandbox:
    """Create, use, and destroy a stable Docker container."""

    label = "patchbench.sandbox=true"
    workspace_path = "/workspace"

    def __init__(self, image: str = "python:3.12-slim") -> None:
        self.image = image

    def create(self, workspace: Path | None = None) -> SandboxHandle:
        """Verify Docker and start a container that remains running."""

        workspace_path = self._resolve_workspace(workspace)
        self._run("version", "--format", "{{.Server.Version}}")
        run_arguments = [
            "run",
            "--detach",
            "--label",
            self.label,
        ]
        if workspace_path is not None:
            run_arguments.extend(
                [
                    "--mount",
                    f"type=bind,source={workspace_path},target={self.workspace_path}",
                ]
            )
        run_arguments.extend(
            [
                "--",
                self.image,
                "python",
                "-c",
                "import time; time.sleep(31536000)",
            ]
        )
        completed = self._run(
            *run_arguments,
        )
        container_id = completed.stdout.strip()
        if not container_id:
            raise DockerSandboxError("Docker created a container without returning its ID")

        handle = SandboxHandle(identifier=container_id)
        try:
            running = self._run(
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_id,
            ).stdout.strip()
        except DockerSandboxError:
            self.destroy(handle)
            raise

        if running != "true":
            self.destroy(handle)
            raise DockerSandboxError(
                f"Docker container {container_id} did not remain running"
            )
        return handle

    def exec(
        self, handle: SandboxHandle, command: Sequence[str]
    ) -> SandboxExecResult:
        """Execute an explicit argv command in the fixed workspace directory."""

        if isinstance(command, (str, bytes)) or not command:
            raise ValueError("Sandbox command must be a non-empty argv sequence")
        if not all(isinstance(argument, str) for argument in command):
            raise TypeError("Every sandbox command argument must be a string")

        completed = self._run_unchecked(
            "exec",
            "--workdir",
            self.workspace_path,
            handle.identifier,
            *command,
        )
        if completed.returncode != 0:
            running = self._run(
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                handle.identifier,
            ).stdout.strip()
            if running != "true":
                raise DockerSandboxError(
                    f"Docker container {handle.identifier} is not running after "
                    "command execution"
                )
        return SandboxExecResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def destroy(self, handle: SandboxHandle) -> None:
        """Force-remove a container; an already absent container is acceptable."""

        completed = self._run_unchecked("rm", "--force", handle.identifier)
        if completed.returncode == 0:
            return
        if "No such container" in completed.stderr:
            return
        raise self._command_error(completed, "rm", "--force", handle.identifier)

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = self._run_unchecked(*arguments)
        if completed.returncode != 0:
            raise self._command_error(completed, *arguments)
        return completed

    @staticmethod
    def _resolve_workspace(workspace: Path | None) -> Path | None:
        if workspace is None:
            return None

        candidate = Path(workspace).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise DockerSandboxError(
                f"Docker sandbox workspace does not exist or cannot be resolved: "
                f"{candidate} ({error})"
            ) from error
        if not resolved.is_dir():
            raise DockerSandboxError(
                f"Docker sandbox workspace is not a directory: {resolved}"
            )
        return resolved

    @staticmethod
    def _run_unchecked(*arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["docker", *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise DockerSandboxError(f"Docker CLI is unavailable: {error}") from error

    @staticmethod
    def _command_error(
        completed: subprocess.CompletedProcess[str], *arguments: str
    ) -> DockerSandboxError:
        command = " ".join(("docker", *arguments))
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        return DockerSandboxError(
            f"Docker command failed with exit code {completed.returncode}: "
            f"{command}\n{detail}"
        )
