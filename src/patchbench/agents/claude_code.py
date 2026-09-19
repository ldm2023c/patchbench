"""Agent adapter for isolated non-interactive Claude Code CLI execution."""

from math import isfinite
import os
from pathlib import Path
import re
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


class ClaudeCodeAdapter:
    """Execute one prompt using a fixed, bounded Claude Code invocation."""

    _TERMINATION_GRACE_SECONDS = 0.1
    _FORCE_KILL_WAIT_SECONDS = 1.0
    _GROUP_EXIT_POLL_SECONDS = 0.01
    _ALLOWED_TOOLS = "Read,Edit,Bash"
    _DISALLOWED_MCP_TOOLS = "mcp__*"
    _MINIMUM_CLAUDE_CODE_VERSION = (2, 1, 259)
    _VERSION_PATTERN = re.compile(
        r"(?<![0-9])([0-9]+)\.([0-9]+)\.([0-9]+)(?![0-9])"
    )
    _BEHAVIORAL_ENVIRONMENT_OVERRIDES = frozenset(
        {
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_EXTRA_BODY",
            "MAX_THINKING_TOKENS",
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
            "CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT",
            "CLAUDE_CODE_SHELL",
            "CLAUDE_CODE_SHELL_PREFIX",
            "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS",
            "CLAUDE_CODE_MAX_TURNS",
            "FALLBACK_FOR_ALL_PRIMARY_MODELS",
        }
    )
    _NON_DIRECT_AUTHENTICATION_OVERRIDES = frozenset(
        {
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_BEDROCK_BASE_URL",
            "ANTHROPIC_CUSTOM_HEADERS",
            "ANTHROPIC_FOUNDRY_BASE_URL",
            "ANTHROPIC_VERTEX_BASE_URL",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_FOUNDRY",
            "CLAUDE_CODE_USE_VERTEX",
        }
    )

    def __init__(
        self,
        *,
        model: str,
        executable: str | Path = "claude",
    ) -> None:
        if (
            not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() for character in model)
        ):
            raise AgentSetupError("Claude Code model must be a non-empty identifier")
        executable_text = str(executable)
        if not executable_text.strip():
            raise AgentSetupError("Claude Code executable must not be empty")
        self._model = model
        self._executable = executable_text
        self._cli_version: str | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def executable(self) -> str:
        return self._executable

    @property
    def cli_version(self) -> str | None:
        return self._cli_version

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run Claude Code in the supplied PatchBench workspace."""
        timeout_seconds = self._validate_timeout(request.timeout_seconds)
        workspace = self._resolve_workspace(request.workspace)
        child_environment = self._preflight()
        arguments = [
            self._executable,
            "-p",
            "--bare",
            "--no-session-persistence",
            "--model",
            self._model,
            "--output-format",
            "json",
            "--no-chrome",
            "--tools",
            self._ALLOWED_TOOLS,
            "--disallowedTools",
            self._DISALLOWED_MCP_TOOLS,
            "--permission-mode",
            "bypassPermissions",
            "--permission-prompts",
            "none",
        ]
        started = perf_counter()
        try:
            process = subprocess.Popen(
                arguments,
                cwd=workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
                env=child_environment,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Claude Code agent execution: {error}"
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
            message = f"Unable to manage Claude Code agent execution: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        exit_code = process.returncode
        try:
            if self._process_group_exists(process.pid):
                self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to clean up Claude Code process group: {error}"
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
            message = f"Unable to terminate timed-out Claude Code process group: {error}"
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
                f"Unable to reap Claude Code process after SIGTERM: {error}"
            ) from error
        if self._wait_for_process_group_exit(process_group_id, graceful_deadline):
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
                "Claude Code process could not be reaped after SIGKILL"
            ) from error
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to force-kill Claude Code process group: {error}"
            ) from error
        if not self._wait_for_process_group_exit(process_group_id, deadline):
            raise AgentInfrastructureError(
                "Claude Code process group still exists after SIGKILL"
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
                f"Unable to signal Claude Code process group {process_group_id}: {error}"
            ) from error

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to inspect Claude Code process group {process_group_id}: {error}"
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
                "Claude Code agent timeout must be a finite positive number"
            )
        return float(timeout_seconds)

    def _preflight(self) -> dict[str, str]:
        version = self._run_setup_command(["--version"], "version")
        if version.returncode != 0:
            raise AgentSetupError(
                f"Claude Code version preflight failed with exit code {version.returncode}"
            )
        cli_version = version.stdout.rstrip("\r\n")
        if (
            not cli_version
            or cli_version != cli_version.strip()
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in cli_version
            )
        ):
            raise AgentSetupError(
                "Claude Code version preflight returned no canonical version"
            )
        parsed_versions = self._VERSION_PATTERN.findall(cli_version)
        if len(parsed_versions) != 1:
            raise AgentSetupError(
                "Claude Code version preflight returned an unparseable version"
            )
        parsed_version = tuple(int(component) for component in parsed_versions[0])
        if parsed_version < self._MINIMUM_CLAUDE_CODE_VERSION:
            minimum = ".".join(map(str, self._MINIMUM_CLAUDE_CODE_VERSION))
            raise AgentSetupError(
                f"Claude Code {minimum} or later is required by the fixed invocation"
            )

        child_environment = os.environ.copy()
        if not child_environment.get("ANTHROPIC_API_KEY"):
            raise AgentSetupError(
                "Claude bare-mode Anthropic API authentication is unavailable"
            )
        removed_variables = (
            self._BEHAVIORAL_ENVIRONMENT_OVERRIDES
            | self._NON_DIRECT_AUTHENTICATION_OVERRIDES
        )
        for variable in removed_variables:
            child_environment.pop(variable, None)
        child_environment["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        child_environment["DISABLE_UPDATES"] = "1"
        self._cli_version = cli_version
        return child_environment

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
                f"Claude Code executable '{self._executable}' is unavailable during "
                f"{description} preflight: {error}"
            ) from error

    @staticmethod
    def _resolve_workspace(workspace: Path) -> Path:
        candidate = Path(workspace).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise AgentSetupError(
                "Claude Code workspace does not exist or cannot be resolved: "
                f"{candidate} ({error})"
            ) from error
        if not resolved.is_dir():
            raise AgentSetupError(
                f"Claude Code workspace is not a directory: {resolved}"
            )
        return resolved
