"""Agent adapter for non-interactive host Codex CLI execution."""

from math import isfinite
import os
from pathlib import Path
import signal
import subprocess
from time import perf_counter, sleep

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)


class CodexAdapter:
    """Execute an effective prompt using the audited Codex CLI policy."""

    _TERMINATION_GRACE_SECONDS = 0.1
    _FORCE_KILL_WAIT_SECONDS = 1.0
    _GROUP_EXIT_POLL_SECONDS = 0.01

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

        timeout_seconds = self._validate_timeout(request.timeout_seconds)

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
            process = subprocess.Popen(
                arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Codex agent execution: {error}"
            ) from error

        try:
            stdout, stderr = process.communicate(
                input=request.prompt,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return self._handle_timeout(process, started)
        except OSError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to manage Codex agent execution: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        exit_code = process.returncode
        try:
            if self._process_group_exists(process.pid):
                self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to clean up Codex process group: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        return AgentRunResult(
            status=(
                AgentRunStatus.COMPLETED
                if exit_code == 0
                else AgentRunStatus.COMMAND_FAILED
            ),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=perf_counter() - started,
        )

    def _handle_timeout(
        self, process: subprocess.Popen[str], started: float
    ) -> AgentRunResult:
        try:
            stdout, stderr = self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to terminate timed-out Codex process group: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        return AgentRunResult(
            status=AgentRunStatus.TIMED_OUT,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=perf_counter() - started,
        )

    def _terminate_process_group(
        self, process: subprocess.Popen[str]
    ) -> tuple[str, str]:
        process_group_id = process.pid
        self._signal_process_group(process_group_id, signal.SIGTERM)
        graceful_deadline = perf_counter() + self._TERMINATION_GRACE_SECONDS

        try:
            stdout, stderr = process.communicate(
                timeout=max(graceful_deadline - perf_counter(), 0)
            )
        except subprocess.TimeoutExpired:
            return self._force_kill_and_reap(process, process_group_id)
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to reap Codex process after SIGTERM: {error}"
            ) from error

        if self._wait_for_process_group_exit(
            process_group_id, graceful_deadline
        ):
            return stdout, stderr
        return self._force_kill_and_reap(process, process_group_id)

    def _force_kill_and_reap(
        self,
        process: subprocess.Popen[str],
        process_group_id: int,
    ) -> tuple[str, str]:
        deadline = perf_counter() + self._FORCE_KILL_WAIT_SECONDS
        try:
            self._signal_process_group(process_group_id, signal.SIGKILL)
            stdout, stderr = process.communicate(
                timeout=max(deadline - perf_counter(), 0)
            )
        except subprocess.TimeoutExpired as error:
            raise AgentInfrastructureError(
                "Codex process could not be reaped after SIGKILL"
            ) from error
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to force-kill Codex process group: {error}"
            ) from error

        if not self._wait_for_process_group_exit(process_group_id, deadline):
            raise AgentInfrastructureError(
                "Codex process group still exists after SIGKILL"
            )
        return stdout, stderr

    def _force_cleanup(self, process: subprocess.Popen[str]) -> str | None:
        try:
            self._force_kill_and_reap(process, process.pid)
        except AgentInfrastructureError as error:
            return str(error)
        return None

    def _wait_for_process_group_exit(
        self, process_group_id: int, deadline: float
    ) -> bool:
        while self._process_group_exists(process_group_id):
            if perf_counter() >= deadline:
                return False
            sleep(self._GROUP_EXIT_POLL_SECONDS)
        return True

    @staticmethod
    def _signal_process_group(process_group_id: int, signal_number: int) -> None:
        try:
            os.killpg(process_group_id, signal_number)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to signal Codex process group {process_group_id}: {error}"
            ) from error

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to inspect Codex process group {process_group_id}: {error}"
            ) from error
        return True

    @staticmethod
    def _validate_timeout(timeout_seconds: float | None) -> float | None:
        if timeout_seconds is None:
            return None
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise AgentSetupError(
                "Codex agent timeout must be a finite positive number"
            )
        return float(timeout_seconds)

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
