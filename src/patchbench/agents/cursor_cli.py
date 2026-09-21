"""Agent adapter for isolated non-interactive Cursor CLI execution."""

import json
from math import isfinite
import os
from pathlib import Path
import shlex
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


_CLI_CONFIG = {
    "version": 1,
    "editor": {"vimMode": False},
    "permissions": {
        "allow": ["Read(**)", "Write(**)", "Shell(*)"],
        "deny": ["WebFetch(*)", "Mcp(*:*)"],
    },
    "notifications": False,
    "hints": False,
    "suggestNextPrompt": False,
    "attribution": {
        "attributeCommitsToAgent": False,
        "attributePRsToAgent": False,
    },
}

_POLICY_HOOK_SOURCE = '''#!/usr/bin/env python3
import json
import sys


def emit(response):
    print(json.dumps(response, sort_keys=True, separators=(",", ":")))


def deny():
    return {"permission": "deny", "user_message": "Blocked by PatchBench policy."}


try:
    request = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    emit(deny())
    raise SystemExit(1)

if not isinstance(request, dict):
    emit(deny())
    raise SystemExit(1)

tool_name = request.get("tool_name")
tool_input = request.get("tool_input")
if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
    emit(deny())
    raise SystemExit(1)

if tool_name in {"WebSearch", "Task"}:
    emit(deny())
elif tool_name == "Shell":
    command = tool_input.get("command")
    if not isinstance(command, str):
        emit(deny())
    else:
        updated_input = dict(tool_input)
        updated_input["command"] = (
            "unset CURSOR_API_KEY CURSOR_AUTH_TOKEN; " + command
        )
        emit({"permission": "allow", "updated_input": updated_input})
else:
    emit(deny())
'''


class CursorCliAdapter:
    """Execute one prompt using a fixed, isolated Cursor CLI invocation."""

    _TERMINATION_GRACE_SECONDS = 0.1
    _FORCE_KILL_WAIT_SECONDS = 1.0
    _GROUP_EXIT_POLL_SECONDS = 0.01
    _DISABLE_UPDATE_FLAG = "--disable-auto-update"
    _REQUIRED_HELP_FLAGS = (
        "--print",
        "--output-format",
        "--model",
        "--list-models",
        "--force",
        "--sandbox",
        "--trust",
        "--workspace",
        "--endpoint",
    )

    def __init__(
        self,
        *,
        model: str,
        executable: str | Path = "agent",
        endpoint: str = "https://api2.cursor.sh",
    ) -> None:
        if (
            not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() for character in model)
        ):
            raise AgentSetupError("Cursor CLI model must be a non-empty identifier")
        executable_text = str(executable)
        if not executable_text.strip():
            raise AgentSetupError("Cursor CLI executable must not be empty")
        self._model = model
        self._executable = executable_text
        self._endpoint = self._validate_endpoint(endpoint)
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
    def endpoint(self) -> str:
        return self._endpoint

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run Cursor CLI in the supplied PatchBench workspace."""
        timeout_seconds = self._validate_timeout(request.timeout_seconds)
        workspace = self._resolve_workspace(request.workspace)
        started = perf_counter()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        api_key = self._capture_api_key()
        try:
            with TemporaryDirectory(prefix="patchbench-cursor-cli-") as temporary:
                isolated_home = Path(temporary).resolve(strict=True)
                if isolated_home == workspace or workspace in isolated_home.parents:
                    raise AgentInfrastructureError(
                        "Isolated Cursor CLI home was created inside the workspace"
                    )
                cursor_config = isolated_home / ".cursor"
                hooks_directory = cursor_config / "hooks"
                hooks_directory.mkdir(parents=True)
                hook_path = hooks_directory / "patchbench_policy.py"
                self._write_cli_config(cursor_config / "cli-config.json")
                self._write_policy_hook(hook_path)
                self._write_hooks_config(cursor_config / "hooks.json", hook_path)
                preflight_environment = self._build_sanitized_environment(
                    isolated_home, cursor_config
                )
                authenticated_environment = preflight_environment.copy()
                authenticated_environment["CURSOR_API_KEY"] = api_key
                self._preflight(
                    deadline,
                    static_environment=preflight_environment,
                    authenticated_environment=authenticated_environment,
                )
                return self._run_model(
                    request,
                    workspace=workspace,
                    started=started,
                    deadline=deadline,
                    environment=authenticated_environment,
                )
        except (AgentSetupError, AgentInfrastructureError):
            raise
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to manage isolated Cursor CLI state: {error}"
            ) from error

    def _run_model(
        self,
        request: AgentRunRequest,
        *,
        workspace: Path,
        started: float,
        deadline: float | None,
        environment: dict[str, str],
    ) -> AgentRunResult:
        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            raise AgentSetupError("Cursor CLI preflight exceeded the agent timeout")
        arguments = [
            self._executable,
            self._DISABLE_UPDATE_FLAG,
            "--print",
            "--output-format",
            "json",
            "--model",
            self._model,
            "--endpoint",
            self._endpoint,
            "--workspace",
            str(workspace),
            "--sandbox",
            "enabled",
            "--force",
            "--trust",
            request.prompt,
        ]
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
                env=environment,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Cursor CLI agent execution: {error}"
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
            message = f"Unable to manage Cursor CLI agent execution: {error}"
            if cleanup_detail is not None:
                message += f"; cleanup also failed: {cleanup_detail}"
            raise AgentInfrastructureError(message) from error

        exit_code = process.returncode
        try:
            if self._process_group_exists(process.pid):
                self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to clean up Cursor CLI process group: {error}"
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

    def _preflight(
        self,
        deadline: float | None,
        *,
        static_environment: dict[str, str],
        authenticated_environment: dict[str, str],
    ) -> None:
        version = self._run_setup_command(
            [self._DISABLE_UPDATE_FLAG, "--version"],
            "version",
            timeout=self._remaining_timeout(deadline),
            environment=static_environment,
        )
        if version.returncode != 0:
            raise AgentSetupError(
                "Cursor CLI version preflight failed with exit code "
                f"{version.returncode}"
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
                "Cursor CLI version preflight returned no canonical version"
            )

        help_result = self._run_setup_command(
            [self._DISABLE_UPDATE_FLAG, "--help"],
            "help",
            timeout=self._remaining_timeout(deadline),
            environment=static_environment,
        )
        if help_result.returncode != 0:
            raise AgentSetupError(
                "Cursor CLI help preflight failed with exit code "
                f"{help_result.returncode}"
            )
        missing_flags = tuple(
            flag for flag in self._REQUIRED_HELP_FLAGS
            if flag not in help_result.stdout
        )
        if missing_flags:
            raise AgentSetupError(
                "Cursor CLI required flags are unavailable: "
                + ", ".join(missing_flags)
            )

        models = self._run_setup_command(
            [
                self._DISABLE_UPDATE_FLAG,
                "--endpoint",
                self._endpoint,
                "--list-models",
            ],
            "model-list",
            timeout=self._remaining_timeout(deadline),
            environment=authenticated_environment,
        )
        if models.returncode != 0:
            raise AgentSetupError(
                "Cursor CLI model-list preflight failed with exit code "
                f"{models.returncode}"
            )
        available_models = set(models.stdout.splitlines())
        if self._model not in available_models:
            raise AgentSetupError(
                "Cursor CLI requested model is unavailable in the authenticated "
                "model list"
            )
        self._cli_version = cli_version

    def _run_setup_command(
        self,
        arguments: list[str],
        description: str,
        *,
        timeout: float | None,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        if timeout is not None and timeout <= 0:
            raise AgentSetupError(
                f"Cursor CLI {description} preflight exceeded the agent timeout"
            )
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
                f"Cursor CLI {description} preflight exceeded the agent timeout"
            ) from error
        except OSError as error:
            raise AgentSetupError(
                f"Cursor CLI executable '{self._executable}' is unavailable during "
                f"{description} preflight: {error}"
            ) from error

    @staticmethod
    def _write_cli_config(path: Path) -> None:
        path.write_text(
            json.dumps(_CLI_CONFIG, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_policy_hook(path: Path) -> None:
        path.write_text(_POLICY_HOOK_SOURCE, encoding="utf-8")
        path.chmod(0o700)

    @staticmethod
    def _write_hooks_config(path: Path, hook_path: Path) -> None:
        config = {
            "version": 1,
            "hooks": {
                "preToolUse": [
                    {
                        "command": shlex.quote(str(hook_path)),
                        "matcher": "^(Shell|WebSearch|Task)$",
                        "failClosed": True,
                    }
                ]
            },
        }
        path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _build_sanitized_environment(
        isolated_home: Path, cursor_config: Path
    ) -> dict[str, str]:
        environment = os.environ.copy()
        for variable in tuple(environment):
            if variable.startswith("CURSOR_"):
                environment.pop(variable)
        environment.pop("XDG_CONFIG_HOME", None)
        environment["HOME"] = str(isolated_home)
        environment["CURSOR_CONFIG_DIR"] = str(cursor_config)
        return environment

    @staticmethod
    def _capture_api_key() -> str:
        api_key = os.environ.get("CURSOR_API_KEY")
        if api_key is None or not api_key.strip():
            raise AgentSetupError("Cursor CLI API-key authentication is unavailable")
        return api_key

    @staticmethod
    def _validate_endpoint(value: str) -> str:
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
                "Cursor CLI endpoint must be canonical HTTPS without a trailing slash"
            )
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise AgentSetupError("Cursor CLI endpoint is invalid") from error
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
                "Cursor CLI endpoint must be canonical HTTPS without credentials, "
                "query, fragment, or a trailing slash"
            )
        return value

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
                "Cursor CLI agent timeout must be a finite positive number"
            )
        return float(timeout_seconds)

    @staticmethod
    def _resolve_workspace(workspace: Path) -> Path:
        candidate = Path(workspace).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise AgentSetupError(
                "Cursor CLI workspace does not exist or cannot be resolved: "
                f"{candidate} ({error})"
            ) from error
        if not resolved.is_dir():
            raise AgentSetupError(
                f"Cursor CLI workspace is not a directory: {resolved}"
            )
        return resolved

    def _handle_timeout(
        self, process: subprocess.Popen[str], started: float
    ) -> AgentRunResult:
        try:
            stdout, stderr = self._terminate_process_group(process)
        except AgentInfrastructureError as error:
            cleanup_detail = self._force_cleanup(process)
            message = f"Unable to terminate timed-out Cursor CLI process group: {error}"
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
                f"Unable to reap Cursor CLI process after SIGTERM: {error}"
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
                "Cursor CLI process could not be reaped after SIGKILL"
            ) from error
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to force-kill Cursor CLI process group: {error}"
            ) from error
        if not self._wait_for_process_group_exit(process_group_id, deadline):
            raise AgentInfrastructureError(
                "Cursor CLI process group still exists after SIGKILL"
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
                f"Unable to signal Cursor CLI process group {process_group_id}: {error}"
            ) from error

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise AgentInfrastructureError(
                "Unable to inspect Cursor CLI process group "
                f"{process_group_id}: {error}"
            ) from error
        return True

    @staticmethod
    def _remaining_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - perf_counter()
