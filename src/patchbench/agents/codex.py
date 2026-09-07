"""Agent adapter for non-interactive host Codex CLI execution."""

from pathlib import Path
import subprocess
from time import perf_counter

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)


class CodexAdapter:
    """Execute an effective prompt using the audited Codex CLI policy."""

    def __init__(
        self,
        *,
        model: str,
        executable: str | Path = "codex",
    ) -> None:
        if (
            not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() for character in model)
        ):
            raise AgentSetupError("Codex model must be a non-empty identifier")

        executable_text = str(executable)
        if not executable_text.strip():
            raise AgentSetupError("Codex executable must not be empty")

        self._model = model
        self._executable = executable_text
        self._cli_version: str | None = None

    @property
    def model(self) -> str:
        """Return the explicitly requested model identifier."""

        return self._model

    @property
    def executable(self) -> str:
        """Return the configured executable name or path."""

        return self._executable

    @property
    def cli_version(self) -> str | None:
        """Return the CLI version observed by the latest successful preflight."""

        return self._cli_version

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run Codex against an existing workspace and capture its raw result."""

        if request.timeout_seconds is not None:
            raise AgentSetupError(
                "Codex agent timeouts are not supported until Milestone 3.3"
            )

        workspace = self._resolve_workspace(request.workspace)
        self._preflight()
        arguments = [
            self._executable,
            "exec",
            "-C",
            str(workspace),
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--json",
            "-m",
            self._model,
            "-",
        ]

        started = perf_counter()
        try:
            completed = subprocess.run(
                arguments,
                input=request.prompt,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Codex agent execution: {error}"
            ) from error
        duration = perf_counter() - started

        return AgentRunResult(
            status=(
                AgentRunStatus.COMPLETED
                if completed.returncode == 0
                else AgentRunStatus.COMMAND_FAILED
            ),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )

    def _preflight(self) -> None:
        version = self._run_setup_command(["--version"], "version")
        if version.returncode != 0:
            raise self._setup_command_error(version, "version")

        cli_version = version.stdout.strip()
        if not cli_version:
            raise AgentSetupError("Codex version preflight returned no version")

        login_status = self._run_setup_command(["login", "status"], "login status")
        if login_status.returncode != 0:
            raise self._setup_command_error(login_status, "login status")
        self._cli_version = cli_version

    def _run_setup_command(
        self, arguments: list[str], description: str
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self._executable, *arguments],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except OSError as error:
            raise AgentSetupError(
                f"Codex executable '{self._executable}' is unavailable during "
                f"{description} preflight: {error}"
            ) from error

    @staticmethod
    def _setup_command_error(
        completed: subprocess.CompletedProcess[str], description: str
    ) -> AgentSetupError:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        return AgentSetupError(
            f"Codex {description} preflight failed with exit code "
            f"{completed.returncode}: {detail}"
        )

    @staticmethod
    def _resolve_workspace(workspace: Path) -> Path:
        candidate = Path(workspace).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise AgentSetupError(
                f"Codex workspace does not exist or cannot be resolved: "
                f"{candidate} ({error})"
            ) from error
        if not resolved.is_dir():
            raise AgentSetupError(f"Codex workspace is not a directory: {resolved}")
        return resolved
