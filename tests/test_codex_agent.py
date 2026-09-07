import json
import os
from pathlib import Path
import signal
import sys
from textwrap import dedent
import time

import pytest

from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.agents.codex import CodexAdapter


_LOG_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_LOG"
_EXIT_CODE_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_EXIT_CODE"
_AUTH_FAILURE_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_AUTH_FAILURE"
_DELETE_AFTER_LOGIN_ENVIRONMENT_VARIABLE = (
    "PATCHBENCH_TEST_CODEX_DELETE_AFTER_LOGIN"
)
_EXEC_SLEEP_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_EXEC_SLEEP"
_CHILD_SENTINEL_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_CHILD_SENTINEL"
_CHILD_STARTED_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_CHILD_STARTED"
_GRACEFUL_MARKER_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_GRACEFUL_MARKER"
_IGNORE_TERMINATION_ENVIRONMENT_VARIABLE = (
    "PATCHBENCH_TEST_CODEX_IGNORE_TERMINATION"
)
_PRE_TIMEOUT_OUTPUT_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_PRE_TIMEOUT_OUTPUT"
_EXIT_AFTER_CHILD_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_EXIT_AFTER_CHILD"


@pytest.fixture
def fake_codex(tmp_path, monkeypatch) -> tuple[Path, Path]:
    executable = tmp_path / "fake-codex"
    invocation_log = tmp_path / "invocations.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        + dedent(
            f'''\
            import json
            import os
            from pathlib import Path
            import signal
            import subprocess
            import sys
            import time

            arguments = sys.argv[1:]
            prompt = sys.stdin.read() if arguments[:1] == ["exec"] else None
            record = {{"arguments": arguments, "prompt": prompt}}
            with Path(os.environ["{_LOG_ENVIRONMENT_VARIABLE}"]).open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(json.dumps(record) + "\\n")

            if arguments == ["--version"]:
                print("codex-cli 0.152.0")
                raise SystemExit(0)

            if arguments == ["login", "status"]:
                if os.environ.get("{_AUTH_FAILURE_ENVIRONMENT_VARIABLE}") == "1":
                    print("not logged in", file=sys.stderr)
                    raise SystemExit(5)
                if os.environ.get("{_DELETE_AFTER_LOGIN_ENVIRONMENT_VARIABLE}") == "1":
                    Path(sys.argv[0]).unlink()
                print("Logged in using ChatGPT")
                raise SystemExit(0)

            if arguments[:1] == ["exec"]:
                graceful_marker = os.environ.get(
                    "{_GRACEFUL_MARKER_ENVIRONMENT_VARIABLE}"
                )
                if graceful_marker is not None:
                    def terminate_gracefully(signal_number, frame):
                        Path(graceful_marker).write_text(
                            "terminated", encoding="utf-8"
                        )
                        raise SystemExit(0)

                    signal.signal(signal.SIGTERM, terminate_gracefully)
                elif os.environ.get(
                    "{_IGNORE_TERMINATION_ENVIRONMENT_VARIABLE}"
                ) == "1":
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)

                child_sentinel = os.environ.get(
                    "{_CHILD_SENTINEL_ENVIRONMENT_VARIABLE}"
                )
                if child_sentinel is not None:
                    child_code = (
                        "import sys, time; from pathlib import Path; "
                        "time.sleep(0.3); "
                        "Path(sys.argv[1]).write_text('survived', encoding='utf-8')"
                    )
                    subprocess.Popen(
                        [sys.executable, "-c", child_code, child_sentinel],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    child_started = os.environ.get(
                        "{_CHILD_STARTED_ENVIRONMENT_VARIABLE}"
                    )
                    if child_started is not None:
                        Path(child_started).write_text("started", encoding="utf-8")
                    if os.environ.get(
                        "{_EXIT_AFTER_CHILD_ENVIRONMENT_VARIABLE}"
                    ) == "1":
                        print('{{"type":"fake.result"}}')
                        print("fake diagnostic", file=sys.stderr)
                        raise SystemExit(
                            int(
                                os.environ.get(
                                    "{_EXIT_CODE_ENVIRONMENT_VARIABLE}", "0"
                                )
                            )
                        )

                if os.environ.get(
                    "{_PRE_TIMEOUT_OUTPUT_ENVIRONMENT_VARIABLE}"
                ) == "1":
                    print("stdout before timeout", flush=True)
                    print("stderr before timeout", file=sys.stderr, flush=True)

                time.sleep(
                    float(
                        os.environ.get("{_EXEC_SLEEP_ENVIRONMENT_VARIABLE}", "0")
                    )
                )
                print('{{"type":"fake.result"}}')
                print("fake diagnostic", file=sys.stderr)
                raise SystemExit(
                    int(os.environ.get("{_EXIT_CODE_ENVIRONMENT_VARIABLE}", "0"))
                )

            print("unexpected fake Codex invocation", file=sys.stderr)
            raise SystemExit(64)
            '''
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv(_LOG_ENVIRONMENT_VARIABLE, str(invocation_log))
    return executable, invocation_log


def _read_invocations(invocation_log: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    ]


def test_codex_adapter_preserves_success_output_prompt_and_policy(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt = "Fix exactly this.\nDo not rewrite it: $HOME\n"
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "0.01")
    adapter = CodexAdapter(model="test-model", executable=executable)
    agent: Agent = adapter

    result = agent.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"type":"fake.result"}\n'
    assert result.stderr == "fake diagnostic\n"
    assert result.duration_seconds > 0
    assert adapter.model == "test-model"
    assert adapter.executable == str(executable)
    assert adapter.cli_version == "codex-cli 0.152.0"

    invocations = _read_invocations(invocation_log)
    assert invocations[:2] == [
        {"arguments": ["--version"], "prompt": None},
        {"arguments": ["login", "status"], "prompt": None},
    ]
    execution = invocations[2]
    assert execution["arguments"] == [
        "exec",
        "-C",
        str(workspace.resolve()),
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--json",
        "-m",
        "test-model",
        "-",
    ]
    assert execution["prompt"] == prompt
    assert {
        "--ignore-rules",
        "--search",
        "--add-dir",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "danger-full-access",
    }.isdisjoint(execution["arguments"])


def test_codex_adapter_maps_nonzero_execution_to_command_failed(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_EXIT_CODE_ENVIRONMENT_VARIABLE, "7")

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Attempt the task.")
    )

    assert result.status is AgentRunStatus.COMMAND_FAILED
    assert result.exit_code == 7
    assert result.stdout == '{"type":"fake.result"}\n'
    assert result.stderr == "fake diagnostic\n"
    assert result.duration_seconds >= 0


def test_codex_adapter_missing_executable_is_a_setup_error(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CodexAdapter(
        model="test-model", executable=tmp_path / "missing-codex"
    )

    with pytest.raises(AgentSetupError, match="version preflight"):
        adapter.run(AgentRunRequest(workspace, "Fix the task."))


def test_codex_adapter_failed_authentication_is_a_setup_error(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_AUTH_FAILURE_ENVIRONMENT_VARIABLE, "1")

    with pytest.raises(AgentSetupError, match="login status preflight"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "Fix the task.")
        )

    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
    ]


@pytest.mark.parametrize("model", ["", "   ", "invalid model"])
def test_codex_adapter_rejects_invalid_model(model) -> None:
    with pytest.raises(AgentSetupError, match="model"):
        CodexAdapter(model=model)


@pytest.mark.parametrize("workspace_kind", ["missing", "file"])
def test_codex_adapter_rejects_invalid_workspace_before_preflight(
    tmp_path, fake_codex, workspace_kind
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / workspace_kind
    if workspace_kind == "file":
        workspace.write_text("not a directory", encoding="utf-8")

    with pytest.raises(AgentSetupError, match="workspace"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "Fix the task.")
        )

    assert not invocation_log.exists()


@pytest.mark.parametrize(
    "timeout_seconds",
    [0, -1, float("inf"), float("nan"), True, "1"],
)
def test_codex_adapter_rejects_invalid_timeout_before_preflight(
    tmp_path, fake_codex, timeout_seconds
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(AgentSetupError, match="finite positive number"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(
                workspace,
                "Fix the task.",
                timeout_seconds=timeout_seconds,
            )
        )

    assert not invocation_log.exists()


def test_codex_adapter_actual_exec_start_failure_is_infrastructure_error(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_DELETE_AFTER_LOGIN_ENVIRONMENT_VARIABLE, "1")
    adapter = CodexAdapter(model="test-model", executable=executable)

    with pytest.raises(AgentInfrastructureError, match="start Codex agent") as raised:
        adapter.run(AgentRunRequest(workspace, "Fix the task."))

    assert isinstance(raised.value.__cause__, FileNotFoundError)
    assert adapter.cli_version == "codex-cli 0.152.0"
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
    ]


def test_codex_adapter_returns_timed_out_after_stopping_process(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setenv(_PRE_TIMEOUT_OUTPUT_ENVIRONMENT_VARIABLE, "1")
    started = time.monotonic()

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Wait for timeout.", timeout_seconds=0.1)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == "stdout before timeout\n"
    assert result.stderr == "stderr before timeout\n"
    assert result.duration_seconds >= 0.1
    assert time.monotonic() - started < 1


def test_codex_adapter_timeout_stops_child_before_delayed_workspace_write(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "child-survived.txt"
    child_started = tmp_path / "child-started.txt"
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setenv(_CHILD_SENTINEL_ENVIRONMENT_VARIABLE, str(sentinel))
    monkeypatch.setenv(_CHILD_STARTED_ENVIRONMENT_VARIABLE, str(child_started))

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Spawn a child.", timeout_seconds=0.15)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(0.5)
    assert not sentinel.exists()


def test_codex_adapter_normal_completion_stops_background_child(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "normal-child-survived.txt"
    child_started = tmp_path / "normal-child-started.txt"
    monkeypatch.setenv(_CHILD_SENTINEL_ENVIRONMENT_VARIABLE, str(sentinel))
    monkeypatch.setenv(_CHILD_STARTED_ENVIRONMENT_VARIABLE, str(child_started))
    monkeypatch.setenv(_EXIT_AFTER_CHILD_ENVIRONMENT_VARIABLE, "1")

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Spawn a background child.")
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"type":"fake.result"}\n'
    assert result.stderr == "fake diagnostic\n"
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(0.5)
    assert not sentinel.exists()


def test_codex_adapter_normal_probe_os_error_is_infrastructure_error(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "probe-child-survived.txt"
    child_started = tmp_path / "probe-child-started.txt"
    monkeypatch.setenv(_CHILD_SENTINEL_ENVIRONMENT_VARIABLE, str(sentinel))
    monkeypatch.setenv(_CHILD_STARTED_ENVIRONMENT_VARIABLE, str(child_started))
    monkeypatch.setenv(_EXIT_AFTER_CHILD_ENVIRONMENT_VARIABLE, "1")
    real_killpg = os.killpg
    probe_failed = False

    def fail_first_probe(process_group_id: int, signal_number: int) -> None:
        nonlocal probe_failed
        if signal_number == 0 and not probe_failed:
            probe_failed = True
            raise PermissionError("simulated process-group probe failure")
        real_killpg(process_group_id, signal_number)

    monkeypatch.setattr(os, "killpg", fail_first_probe)

    with pytest.raises(AgentInfrastructureError, match="clean up Codex process group"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "Trigger a probe failure.")
        )

    assert probe_failed
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(0.5)
    assert not sentinel.exists()


def test_codex_adapter_reaps_gracefully_terminated_process(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = tmp_path / "graceful-termination.txt"
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setenv(_GRACEFUL_MARKER_ENVIRONMENT_VARIABLE, str(marker))

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Exit on SIGTERM.", timeout_seconds=0.15)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert marker.read_text(encoding="utf-8") == "terminated"


def test_codex_adapter_force_kills_process_that_ignores_sigterm(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "2")
    monkeypatch.setenv(_IGNORE_TERMINATION_ENVIRONMENT_VARIABLE, "1")
    real_killpg = os.killpg
    signal_calls: list[tuple[int, int]] = []

    def record_signal(process_group_id: int, signal_number: int) -> None:
        signal_calls.append((process_group_id, signal_number))
        real_killpg(process_group_id, signal_number)

    monkeypatch.setattr(os, "killpg", record_signal)
    started = time.monotonic()

    result = CodexAdapter(model="test-model", executable=executable).run(
        AgentRunRequest(workspace, "Ignore SIGTERM.", timeout_seconds=0.15)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert time.monotonic() - started < 1
    assert any(signal_number == signal.SIGTERM for _, signal_number in signal_calls)
    assert any(signal_number == signal.SIGKILL for _, signal_number in signal_calls)
    assert len({process_group_id for process_group_id, _ in signal_calls}) == 1


def test_codex_adapter_raises_when_timeout_signal_management_fails(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    real_killpg = os.killpg
    signal_calls: list[tuple[int, int]] = []

    def fail_first_signal(process_group_id: int, signal_number: int) -> None:
        signal_calls.append((process_group_id, signal_number))
        if len(signal_calls) == 1:
            raise PermissionError("simulated signal failure")
        real_killpg(process_group_id, signal_number)

    monkeypatch.setattr(os, "killpg", fail_first_signal)

    with pytest.raises(
        AgentInfrastructureError, match="terminate timed-out Codex process group"
    ):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "Fail termination.", timeout_seconds=0.1)
        )

    assert signal_calls[0][1] == signal.SIGTERM
    assert any(signal_number == signal.SIGKILL for _, signal_number in signal_calls)
    assert len({process_group_id for process_group_id, _ in signal_calls}) == 1
