"""Minimal Docker-backed sandbox lifecycle."""

import subprocess

from patchbench.sandbox.base import SandboxHandle


class DockerSandboxError(RuntimeError):
    """Raised when the Docker CLI or daemon cannot complete an operation."""


class DockerSandbox:
    """Create and destroy a stable, unprivileged Docker container."""

    label = "patchbench.sandbox=true"

    def __init__(self, image: str = "python:3.12-slim") -> None:
        self.image = image

    def create(self) -> SandboxHandle:
        """Verify Docker and start a container that remains running."""

        self._run("version", "--format", "{{.Server.Version}}")
        completed = self._run(
            "run",
            "--detach",
            "--label",
            self.label,
            "--",
            self.image,
            "python",
            "-c",
            "import time; time.sleep(31536000)",
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
