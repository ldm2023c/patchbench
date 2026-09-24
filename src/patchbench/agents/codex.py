"""Agent adapter for non-interactive host Codex CLI execution."""

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
    AgentProviderTransportError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.agents.structured_provider_failure import (
    has_codex_structured_http_429,
)


class CodexAdapter:
    """Execute an effective prompt using the audited Codex CLI policy."""

    _TERMINATION_GRACE_SECONDS = 0.1
    _FORCE_KILL_WAIT_SECONDS = 1.0
    _GROUP_EXIT_POLL_SECONDS = 0.01
    _RELAY_ENVIRONMENT_PREFIXES = ("CODEX_", "OPENAI_")
    _REQUIRED_EXEC_HELP_FLAGS = (
        "--cd",
        "--sandbox",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--model",
        "--config",
    )

    def __init__(
        self,
        *,
        model: str,
        executable: str | Path = "codex",
        relay_base_url: str | None = None,
        expected_cli_version: str | None = None,
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
        self._relay_base_url = self._validate_relay_base_url(relay_base_url)
        self._expected_cli_version = self._validate_expected_cli_version(
            expected_cli_version
        )
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

    @property
    def relay_base_url(self) -> str | None:
        """Return the explicit relay route, if relay mode is configured."""

        return self._relay_base_url

    @property
    def expected_cli_version(self) -> str | None:
        """Return the exact CLI version required during preflight, if any."""

        return self._expected_cli_version

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run Codex against an existing workspace and capture its raw result."""

        timeout_seconds = self._validate_timeout(request.timeout_seconds)
        workspace = self._resolve_workspace(request.workspace)
        started = perf_counter()
        deadline = None if timeout_seconds is None else started + timeout_seconds

        if self._relay_base_url is None:
            self._preflight(deadline, environment=None, relay_mode=False)
            return self._run_model(
                request,
                workspace=workspace,
                started=started,
                deadline=deadline,
                environment=None,
            )

        api_key = self._capture_relay_api_key()
        try:
            with TemporaryDirectory(prefix="patchbench-codex-") as temporary:
                isolated_home = Path(temporary).resolve()
                if isolated_home.is_relative_to(workspace):
                    raise AgentInfrastructureError(
                        "Isolated Codex home was created inside the workspace"
                    )
                codex_home = isolated_home / ".codex"
                codex_home.mkdir()
                preflight_environment = self._build_relay_environment(
                    isolated_home,
                    codex_home,
                )
                self._preflight(
                    deadline,
                    environment=preflight_environment,
                    relay_mode=True,
                )
                model_environment = preflight_environment.copy()
                model_environment["OPENAI_API_KEY"] = api_key
                return self._run_model(
                    request,
                    workspace=workspace,
                    started=started,
                    deadline=deadline,
                    environment=model_environment,
                )
        except (AgentSetupError, AgentInfrastructureError):
            raise
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to manage isolated Codex home: {error}"
            ) from error

    def _run_model(
        self,
        request: AgentRunRequest,
        *,
        workspace: Path,
        started: float,
        deadline: float | None,
        environment: dict[str, str] | None,
    ) -> AgentRunResult:
        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            raise AgentSetupError("Codex preflight exceeded the agent timeout")
        arguments = [
            self._executable,
            "exec",
            "-C",
            str(workspace),
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
        ]
        if self._relay_base_url is not None:
            arguments.append("--ignore-rules")
            for override in self._relay_config_overrides():
                arguments.extend(("-c", override))
        arguments.extend(("--json", "-m", self._model, "-"))

        try:
            process = subprocess.Popen(
                arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
                env=environment,
            )
        except OSError as error:
            raise AgentInfrastructureError(
                f"Unable to start Codex agent execution: {error}"
            ) from error

        remaining = self._remaining_timeout(deadline)
        if remaining is not None and remaining <= 0:
            return self._handle_timeout(process, started)
        try:
            stdout, stderr = process.communicate(
                input=request.prompt,
                timeout=remaining,
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

        if exit_code != 0 and has_codex_structured_http_429(stdout):
            raise AgentProviderTransportError(
                "Codex structured provider rate-limit failure (HTTP 429)"
            )

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

    def _preflight(
        self,
        deadline: float | None,
        *,
        environment: dict[str, str] | None,
        relay_mode: bool,
    ) -> None:
        version = self._run_setup_command(
            ["--version"],
            "version",
            timeout=self._remaining_timeout(deadline),
            environment=environment,
        )
        if version.returncode != 0:
            raise self._setup_command_error(version, "version")

        cli_version = version.stdout.rstrip("\r\n")
        if not cli_version:
            raise AgentSetupError("Codex version preflight returned no version")
        self._validate_observed_cli_version(cli_version)

        if (
            self._expected_cli_version is not None
            and cli_version != self._expected_cli_version
        ):
            raise AgentSetupError(
                "Codex CLI version mismatch: expected "
                f"{self._expected_cli_version!r}, observed {cli_version!r}"
            )

        if relay_mode:
            help_result = self._run_setup_command(
                ["exec", "--help"],
                "exec help",
                timeout=self._remaining_timeout(deadline),
                environment=environment,
            )
            if help_result.returncode != 0:
                raise self._setup_command_error(help_result, "exec help")
            missing_flags = tuple(
                flag
                for flag in self._REQUIRED_EXEC_HELP_FLAGS
                if flag not in help_result.stdout
            )
            if missing_flags:
                raise AgentSetupError(
                    "Codex required relay flags are unavailable: "
                    + ", ".join(missing_flags)
                )
        else:
            login_status = self._run_setup_command(
                ["login", "status"],
                "login status",
                timeout=self._remaining_timeout(deadline),
                environment=None,
            )
            if login_status.returncode != 0:
                raise self._setup_command_error(login_status, "login status")
        self._cli_version = cli_version

    def _run_setup_command(
        self,
        arguments: list[str],
        description: str,
        *,
        timeout: float | None,
        environment: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        if timeout is not None and timeout <= 0:
            raise AgentSetupError(
                f"Codex {description} preflight exceeded the agent timeout"
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
                f"Codex {description} preflight exceeded the agent timeout"
            ) from error
        except OSError as error:
            raise AgentSetupError(
                f"Codex executable '{self._executable}' is unavailable during "
                f"{description} preflight: {error}"
            ) from error

    def _relay_config_overrides(self) -> tuple[str, ...]:
        assert self._relay_base_url is not None
        return (
            'model_provider="patchbench_relay"',
            'model_providers.patchbench_relay.name="PatchBench Ailink Relay"',
            "model_providers.patchbench_relay.base_url="
            + self._toml_string(self._relay_base_url),
            'model_providers.patchbench_relay.env_key="OPENAI_API_KEY"',
            'model_providers.patchbench_relay.wire_api="responses"',
            "model_providers.patchbench_relay.requires_openai_auth=false",
            "model_providers.patchbench_relay."
            "supports_standalone_web_search=false",
            'web_search="disabled"',
            "features.apps=false",
            "features.goals=false",
            "features.hooks=false",
            "features.memories=false",
            "features.multi_agent=false",
            "features.remote_plugin=false",
            "features.shell_snapshot=false",
            "features.skill_mcp_dependency_install=false",
            "check_for_update_on_startup=false",
            'shell_environment_policy.inherit="core"',
            "shell_environment_policy.ignore_default_excludes=false",
        )

    @staticmethod
    def _toml_string(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _capture_relay_api_key() -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key is None or not api_key.strip():
            raise AgentSetupError("Codex relay authentication is unavailable")
        return api_key

    def _build_relay_environment(
        self,
        isolated_home: Path,
        codex_home: Path,
    ) -> dict[str, str]:
        environment = os.environ.copy()
        for variable in tuple(environment):
            if variable.startswith(self._RELAY_ENVIRONMENT_PREFIXES):
                environment.pop(variable)
        environment["HOME"] = str(isolated_home)
        environment["CODEX_HOME"] = str(codex_home)
        return environment

    @staticmethod
    def _validate_expected_cli_version(value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise AgentSetupError(
                "Codex expected CLI version must be nonblank canonical text"
            )
        return value

    @staticmethod
    def _validate_observed_cli_version(value: str) -> None:
        if (
            value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise AgentSetupError(
                "Codex version preflight returned no canonical version"
            )

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
                "Codex relay base URL must be canonical HTTPS without a trailing slash"
            )
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise AgentSetupError("Codex relay base URL is invalid") from error
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
                "Codex relay base URL must be canonical HTTPS without query or fragment"
            )
        return value

    @staticmethod
    def _remaining_timeout(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - perf_counter()

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
