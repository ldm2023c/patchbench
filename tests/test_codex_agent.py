import json
from pathlib import Path
import sys
from textwrap import dedent

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


def test_codex_adapter_rejects_timeout_before_preflight(
    tmp_path, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(AgentSetupError, match="timeouts are not supported"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "Fix the task.", timeout_seconds=30)
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
