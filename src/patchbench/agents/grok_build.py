"""Agent adapter for isolated non-interactive Grok Build CLI execution."""

import json
from math import isfinite
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
from urllib.parse import urlsplit

from patchbench.agents.base import (
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)


class GrokBuildAdapter:
    """Execute one prompt using a fixed, bounded Grok Build invocation."""

    _TERMINATION_GRACE_SECONDS = 0.1
    _FORCE_KILL_WAIT_SECONDS = 1.0
    _GROUP_EXIT_POLL_SECONDS = 0.01
    _ALLOWED_TOOLS = "read_file,grep,list_dir,search_replace,run_terminal_cmd"
    _DISALLOWED_TOOLS = "search_tool,use_tool,Agent,web_search,web_fetch"
    _TOOL_ENVIRONMENT_PREFIXES = ("GROK_", "XAI_")
    _PARSER_VERIFIED_FLAGS = ("--no-auto-update", "--no-memory")
    _REQUIRED_HELP_FLAGS = (
        "-p",
        "--cwd",
        "--model",
        "--output-format",
        "--always-approve",
        "--tools",
        "--disallowed-tools",
        "--verbatim",
        "--no-plan",
        "--no-subagents",
        "--disable-web-search",
    )
    _SHELL_ENVIRONMENT_POLICY = json.dumps(
        {
            "features": {
                "remote_fetch": False,
            },
            "shell_environment_policy": {
                "ignore_default_excludes": False,
                "inherit": "core",
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    def __init__(
        self,
        *,
        model: str,
        executable: str | Path = "grok",
        relay_base_url: str | None = None,
        relay_context_window: int | None = None,
    ) -> None:
        if (
            not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() for character in model)
        ):
            raise AgentSetupError("Grok Build model must be a non-empty identifier")
        executable_text = str(executable)
        if not executable_text.strip():
            raise AgentSetupError("Grok Build executable must not be empty")
        self._model = model
        self._executable = executable_text
        self._relay_base_url = self._validate_relay_base_url(relay_base_url)
        self._relay_context_window = self._validate_relay_context_window(
            relay_context_window,
            relay_enabled=self._relay_base_url is not None,
        )
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

    @property
    def relay_base_url(self) -> str | None:
        return self._relay_base_url

    @property
    def relay_context_window(self) -> int | None:
        return self._relay_context_window

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run Grok Build in the supplied PatchBench workspace."""
        timeout_seconds = self._validate_timeout(request.timeout_seconds)
        workspace = self._resolve_workspace(request.workspace)
        started = perf_counter()
        deadline = (
            None if timeout_seconds is None else started + timeout_seconds
        )
        api_key = self._capture_api_key()
        try:
            with TemporaryDirectory(prefix="patchbench-grok-build-") as temporary:
                isolated_home = Path(temporary).resolve()
                if isolated_home.is_relative_to(workspace):
                    raise AgentInfrastructureError(
                        "Isolated Grok Build home was created inside the workspace"
                    )
                grok_home = isolated_home / ".grok"
                grok_home.mkdir()
                if self._relay_base_url is not None:
                    self._write_relay_config(grok_home / "config.toml")
                preflight_environment = self._build_sanitized_environment(
                    isolated_home,
                    grok_home,
                )
                self._preflight(deadline, preflight_environment)
                return self._run_model(
                    request,
                    workspace=workspace,
                    started=started,
                    deadline=deadline,
                    api_key=api_key,
                    environment=preflight_environment,
                )
        except (AgentSetupError, AgentInfrastructureError):
            raise
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to manage isolated Grok Build home: {error}"
            ) from error

    def _run_model(
        self,
        request: AgentRunRequest,
        *,
        workspace: Path,
        started: float,
        deadline: float | None,
        api_key: str,
        environment: dict[str, str],
    ) -> AgentRunResult:
        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            raise AgentSetupError("Grok Build preflight exceeded the agent timeout")
        arguments = [
            self._executable,
            "--no-auto-update",
            "-p",
            request.prompt,
            "--verbatim",
            "--cwd",
            str(workspace),
            "--model",
            self._model,
            "--output-format",
            "json",
            "--always-approve",
            "--tools",
            self._ALLOWED_TOOLS,
            "--disallowed-tools",
            self._DISALLOWED_TOOLS,
            "--no-plan",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
        ]
        model_environment = environment.copy()
        model_environment["XAI_API_KEY"] = api_key
        try:
            process = subprocess.Popen(
                arguments,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
                env=model_environment,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Grok Build agent execution: {error}"
            ) from error

        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            return self._handle_timeout(process, started)
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            return self._handle_timeout(process, started)
        except OSError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to manage Grok Build agent execution: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        exit_code = process.returncode
        try:
            if self._process_group_exists(process.pid):
                self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to clean up Grok Build process group: {error}"
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
            message = f"Unable to terminate timed-out Grok Build process group: {error}"
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
                f"Unable to reap Grok Build process after SIGTERM: {error}"
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
                "Grok Build process could not be reaped after SIGKILL"
            ) from error
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to force-kill Grok Build process group: {error}"
            ) from error
        if not self._wait_for_process_group_exit(process_group_id, deadline):
            raise AgentInfrastructureError(
                "Grok Build process group still exists after SIGKILL"
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
                f"Unable to signal Grok Build process group {process_group_id}: {error}"
            ) from error

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to inspect Grok Build process group {process_group_id}: {error}"
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
                "Grok Build agent timeout must be a finite positive number"
            )
        return float(timeout_seconds)

    def _preflight(
        self,
        deadline: float | None,
        child_environment: dict[str, str],
    ) -> None:
        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            raise AgentSetupError(
                "Grok Build version preflight exceeded the agent timeout"
            )
        version = self._run_setup_command(
            [*self._PARSER_VERIFIED_FLAGS, "--version"],
            "version",
            timeout=remaining,
            environment=child_environment,
        )
        if version.returncode != 0:
            raise AgentSetupError(
                f"Grok Build version preflight failed with exit code {version.returncode}"
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
                "Grok Build version preflight returned no canonical version"
            )
        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            raise AgentSetupError(
                "Grok Build help preflight exceeded the agent timeout"
            )
        help_result = self._run_setup_command(
            ["--help"],
            "help",
            timeout=remaining,
            environment=child_environment,
        )
        if help_result.returncode != 0:
            raise AgentSetupError(
                "Grok Build help preflight failed with exit code "
                f"{help_result.returncode}"
            )
        missing_flags = tuple(
            flag for flag in self._REQUIRED_HELP_FLAGS
            if flag not in help_result.stdout
        )
        if missing_flags:
            raise AgentSetupError(
                "Grok Build required flags are unavailable: "
                + ", ".join(missing_flags)
            )
        self._cli_version = cli_version

    @staticmethod
    def _capture_api_key() -> str:
        api_key = os.environ.get("XAI_API_KEY")
        if api_key is None or not api_key.strip():
            raise AgentSetupError(
                "Grok Build direct xAI API authentication is unavailable"
            )
        return api_key

    def _write_relay_config(self, path: Path) -> None:
        assert self._relay_base_url is not None
        model = json.dumps(self._model, ensure_ascii=False)
        base_url = json.dumps(self._relay_base_url, ensure_ascii=False)
        lines = [
            "[models]",
            f"default = {model}",
            "",
            f"[model.{model}]",
            f"model = {model}",
            f"base_url = {base_url}",
            'env_key = "XAI_API_KEY"',
            'api_backend = "responses"',
            "supports_backend_search = false",
        ]
        if self._relay_context_window is not None:
            lines.append(f"context_window = {self._relay_context_window}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _validate_relay_base_url(value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(character.isspace() for character in value)
            or not value.startswith("https://")
            or value.endswith("/")
            or "?" in value
            or "#" in value
        ):
            raise AgentSetupError(
                "Grok Build relay base URL must be canonical HTTPS without a trailing slash"
            )
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise AgentSetupError("Grok Build relay base URL is invalid") from error
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise AgentSetupError(
                "Grok Build relay base URL must be canonical HTTPS without query or fragment"
            )
        return value

    @staticmethod
    def _validate_relay_context_window(
        value: int | None, *, relay_enabled: bool
    ) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AgentSetupError(
                "Grok Build relay context window must be a positive integer"
            )
        if not relay_enabled:
            raise AgentSetupError(
                "Grok Build relay context window requires a relay base URL"
            )
        return value

    def _build_sanitized_environment(
        self,
        isolated_home: Path,
        grok_home: Path,
    ) -> dict[str, str]:
        child_environment = os.environ.copy()
        for variable in tuple(child_environment):
            if variable.startswith(self._TOOL_ENVIRONMENT_PREFIXES):
                child_environment.pop(variable)
        child_environment.update(
            {
                "HOME": str(isolated_home),
                "GROK_CONFIG": self._SHELL_ENVIRONMENT_POLICY,
                "GROK_DISABLE_AUTOUPDATER": "1",
                "GROK_FEEDBACK_ENABLED": "0",
                "GROK_HOME": str(grok_home),
                "GROK_MEMORY": "0",
                "GROK_SUBAGENTS": "0",
                "GROK_TELEMETRY_ENABLED": "0",
                "GROK_TELEMETRY_MIXPANEL_ENABLED": "0",
                "GROK_TELEMETRY_TRACE_UPLOAD": "0",
                "GROK_WEB_FETCH": "0",
                "GROK_WORKFLOWS": "0",
            }
        )
        return child_environment

    def _run_setup_command(
        self,
        arguments: list[str],
        description: str,
        *,
        timeout: float | None,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self._executable, *arguments],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentSetupError(
                f"Grok Build {description} preflight exceeded the agent timeout"
            ) from error
        except OSError as error:
            raise AgentSetupError(
                f"Grok Build executable '{self._executable}' is unavailable during "
                f"{description} preflight: {error}"
            ) from error

    @staticmethod
    def _remaining_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - perf_counter()

    @staticmethod
    def _resolve_workspace(workspace: Path) -> Path:
        candidate = Path(workspace).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise AgentSetupError(
                "Grok Build workspace does not exist or cannot be resolved: "
                f"{candidate} ({error})"
            ) from error
        if not resolved.is_dir():
            raise AgentSetupError(
                f"Grok Build workspace is not a directory: {resolved}"
            )
        return resolved
