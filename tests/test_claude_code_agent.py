import json
import os
from pathlib import Path
import signal
import secrets
import subprocess
import sys
from textwrap import dedent
import time

import pytest

from patchbench.agents import ClaudeCodeAdapter
from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)


LOG = "PATCHBENCH_TEST_CLAUDE_LOG"
VERSION_MODE = "PATCHBENCH_TEST_CLAUDE_VERSION_MODE"
VERSION_OUTPUT = "PATCHBENCH_TEST_CLAUDE_VERSION_OUTPUT"
VERSION_SLEEP = "PATCHBENCH_TEST_CLAUDE_VERSION_SLEEP"
DELETE_AFTER_VERSION = "PATCHBENCH_TEST_CLAUDE_DELETE_AFTER_VERSION"
HELP_MODE = "PATCHBENCH_TEST_CLAUDE_HELP_MODE"
HELP_SLEEP = "PATCHBENCH_TEST_CLAUDE_HELP_SLEEP"
DELETE_AFTER_HELP = "PATCHBENCH_TEST_CLAUDE_DELETE_AFTER_HELP"
EXIT_CODE = "PATCHBENCH_TEST_CLAUDE_EXIT_CODE"
SLEEP = "PATCHBENCH_TEST_CLAUDE_SLEEP"
IGNORE_TERM = "PATCHBENCH_TEST_CLAUDE_IGNORE_TERM"
PRE_TIMEOUT_OUTPUT = "PATCHBENCH_TEST_CLAUDE_PRE_TIMEOUT_OUTPUT"
CHILD_SENTINEL = "PATCHBENCH_TEST_CLAUDE_CHILD_SENTINEL"
CHILD_STARTED = "PATCHBENCH_TEST_CLAUDE_CHILD_STARTED"
API_KEY = "ANTHROPIC_API_KEY"
DUMMY_API_KEY = "  dummy-test-secret-never-log  "
AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
DUMMY_AUTH_TOKEN = "  dummy-relay-token-never-log  "
RELAY_BASE_URL = "https://ai.ailink1.com"
GENERIC_BEHAVIORAL_OVERRIDES = {
    "API_TIMEOUT_MS",
    "BASH_DEFAULT_TIMEOUT_MS",
    "BASH_MAX_OUTPUT_LENGTH",
    "BASH_MAX_TIMEOUT_MS",
    "MAX_THINKING_TOKENS",
    "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS",
    "FALLBACK_FOR_ALL_PRIMARY_MODELS",
}
TOOL_NAMESPACE_OVERRIDES = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    "CLAUDE_CODE_FORCE_SESSION_PERSISTENCE",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    "CLAUDE_CODE_MAX_RETRIES",
    "CLAUDE_CODE_RETRY_WATCHDOG",
    "CLAUDE_ENV_FILE",
}


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    executable = tmp_path / "fake-claude"
    log = tmp_path / "invocations.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n" + dedent(f'''\
        import json
        import os
        from pathlib import Path
        import signal
        import subprocess
        import sys
        import time

        arguments = sys.argv[1:]
        prompt = sys.stdin.read() if "-p" in arguments else None
        record = {{"arguments": arguments, "prompt": prompt, "cwd": os.getcwd()}}
        record["environment"] = {{
            "api_key_present": bool(os.environ.get("{API_KEY}")),
            "auth_token_present": bool(os.environ.get("{AUTH_TOKEN}")),
            "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
            "path": os.environ.get("PATH"),
            "generic_overrides_present": sorted(
                name
                for name in {sorted(GENERIC_BEHAVIORAL_OVERRIDES)!r}
                if name in os.environ
            ),
            "tool_namespace_overrides_present": sorted(
                name
                for name in {sorted(TOOL_NAMESPACE_OVERRIDES)!r}
                if name in os.environ
            ),
            "auto_connect_ide": os.environ.get("CLAUDE_CODE_AUTO_CONNECT_IDE"),
            "auto_memory": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY"),
            "disable_updates": os.environ.get("DISABLE_UPDATES"),
            "subprocess_env_scrub": os.environ.get(
                "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"
            ),
            "nonessential_traffic": os.environ.get(
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
            ),
        }}
        with Path(os.environ["{LOG}"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\\n")

        if arguments == ["--version"]:
            time.sleep(float(os.environ.get("{VERSION_SLEEP}", "0")))
            mode = os.environ.get("{VERSION_MODE}")
            if mode == "nonzero":
                print("version failed", file=sys.stderr)
                raise SystemExit(4)
            if mode != "blank":
                print(os.environ.get("{VERSION_OUTPUT}", "2.1.259 (Claude Code)"))
            if os.environ.get("{DELETE_AFTER_VERSION}") == "1":
                Path(sys.argv[0]).unlink()
            raise SystemExit(0)

        if arguments == ["--help"]:
            time.sleep(float(os.environ.get("{HELP_SLEEP}", "0")))
            mode = os.environ.get("{HELP_MODE}")
            if mode == "nonzero":
                print("help failed", file=sys.stderr)
                raise SystemExit(5)
            if mode != "missing-allowed-tools":
                print("--allowedTools, --allowed-tools <tools...>")
            if os.environ.get("{DELETE_AFTER_HELP}") == "1":
                Path(sys.argv[0]).unlink()
            raise SystemExit(0)

        if "-p" in arguments:
            if os.environ.get("{IGNORE_TERM}") == "1":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            sentinel = os.environ.get("{CHILD_SENTINEL}")
            if sentinel:
                subprocess.Popen(
                    [sys.executable, "-c",
                     "import sys,time; from pathlib import Path; time.sleep(1); "
                     "Path(sys.argv[1]).write_text('survived')", sentinel],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                Path(os.environ["{CHILD_STARTED}"]).write_text("started")
            if os.environ.get("{PRE_TIMEOUT_OUTPUT}") == "1":
                print('{{"partial":true}}', flush=True)
                print("diagnostic before timeout", file=sys.stderr, flush=True)
            time.sleep(float(os.environ.get("{SLEEP}", "0")))
            print('{{"result":"done"}}')
            print("claude diagnostic", file=sys.stderr)
            raise SystemExit(int(os.environ.get("{EXIT_CODE}", "0")))

        raise SystemExit(64)
        '''),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv(LOG, str(log))
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    return executable, log


def invocations(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_claude_adapter_preserves_prompt_workspace_output_and_exact_policy(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt = "修复这个问题。\nKeep literal $HOME and `code`.\n"
    original_path = os.environ["PATH"]
    for variable in GENERIC_BEHAVIORAL_OVERRIDES:
        monkeypatch.setenv(variable, "ambient-override")
    for variable in TOOL_NAMESPACE_OVERRIDES:
        monkeypatch.setenv(variable, "ambient-tool-override")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")
    monkeypatch.setenv("CLAUDE_CODE_AUTO_CONNECT_IDE", "true")
    monkeypatch.setenv("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", "0")
    monkeypatch.setenv("DISABLE_UPDATES", "0")
    observed_popen_environment = None
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        nonlocal observed_popen_environment
        observed_popen_environment = kwargs.get("env")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    agent: Agent = adapter
    result = agent.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"result":"done"}\n'
    assert result.stderr == "claude diagnostic\n"
    assert DUMMY_API_KEY not in result.stdout
    assert DUMMY_API_KEY not in result.stderr
    assert adapter.model == "model-a"
    assert adapter.executable == str(executable)
    assert adapter.cli_version == "2.1.259 (Claude Code)"
    assert observed_popen_environment is not None
    assert API_KEY in observed_popen_environment
    assert secrets.compare_digest(observed_popen_environment[API_KEY], DUMMY_API_KEY)
    assert observed_popen_environment["PATH"] == original_path
    assert GENERIC_BEHAVIORAL_OVERRIDES.isdisjoint(observed_popen_environment)
    assert TOOL_NAMESPACE_OVERRIDES.isdisjoint(
        observed_popen_environment
    )
    assert observed_popen_environment["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert observed_popen_environment["CLAUDE_CODE_AUTO_CONNECT_IDE"] == "false"
    assert observed_popen_environment["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert observed_popen_environment["DISABLE_UPDATES"] == "1"
    assert all(
        os.environ[name] == "ambient-override"
        for name in GENERIC_BEHAVIORAL_OVERRIDES
    )
    assert all(
        os.environ[name] == "ambient-tool-override"
        for name in TOOL_NAMESPACE_OVERRIDES
    )
    assert os.environ["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "0"
    assert os.environ["CLAUDE_CODE_AUTO_CONNECT_IDE"] == "true"
    assert os.environ["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "0"
    assert os.environ["DISABLE_UPDATES"] == "0"
    assert secrets.compare_digest(os.environ[API_KEY], DUMMY_API_KEY)
    records = invocations(log)
    assert DUMMY_API_KEY not in log.read_text()
    assert [record["arguments"] for record in records[:2]] == [
        ["--version"],
        ["--help"],
    ]
    assert records[0]["environment"] == {
        "api_key_present": False,
        "auth_token_present": False,
        "base_url": None,
        "path": original_path,
        "generic_overrides_present": [],
        "tool_namespace_overrides_present": [],
        "auto_connect_ide": "false",
        "auto_memory": "1",
        "disable_updates": "1",
        "subprocess_env_scrub": "1",
        "nonessential_traffic": None,
    }
    assert records[1]["environment"] == records[0]["environment"]
    execution = records[2]
    assert execution == {
        "arguments": [
            "-p", "--bare", "--no-session-persistence", "--model", "model-a",
            "--output-format", "json", "--no-chrome", "--tools", "Read,Edit,Bash",
            "--allowedTools", "Read", "Edit", "Bash",
            "--disallowedTools", "mcp__*", "--permission-mode", "default",
            "--permission-prompts", "none",
        ],
        "prompt": prompt,
        "cwd": str(workspace.resolve()),
        "environment": {
            "api_key_present": True,
            "auth_token_present": False,
            "base_url": None,
            "path": original_path,
            "generic_overrides_present": [],
            "tool_namespace_overrides_present": [],
            "auto_connect_ide": "false",
            "auto_memory": "1",
            "disable_updates": "1",
            "subprocess_env_scrub": "1",
            "nonessential_traffic": None,
        },
    }
    forbidden = {
        "--resume", "--continue", "--worktree", "--fallback-model", "--settings",
        "--plugin-dir", "--agents", "--append-system-prompt", "--system-prompt",
    }
    assert forbidden.isdisjoint(execution["arguments"])
    assert DUMMY_API_KEY not in execution["arguments"]


def test_claude_permission_contract_preapproves_only_bounded_tools(
    tmp_path, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt")
    )
    arguments = invocations(log)[-1]["arguments"]

    assert arguments[arguments.index("--tools") + 1] == "Read,Edit,Bash"
    allowed_tools_index = arguments.index("--allowedTools")
    allowed_tools = []
    for argument in arguments[allowed_tools_index + 1:]:
        if argument.startswith("--"):
            break
        allowed_tools.append(argument)
    assert allowed_tools == ["Read", "Edit", "Bash"]
    assert "Read,Edit,Bash" not in allowed_tools
    assert arguments[arguments.index("--disallowedTools") + 1] == "mcp__*"
    assert arguments[arguments.index("--permission-mode") + 1] == "default"
    assert arguments[arguments.index("--permission-prompts") + 1] == "none"
    assert "bypassPermissions" not in arguments
    assert "--dangerously-skip-permissions" not in arguments


@pytest.mark.parametrize(
    "relay_base_url",
    [
        "",
        "   ",
        " https://ai.ailink1.com",
        "https://ai.ailink1.com ",
        "http://ai.ailink1.com",
        "HTTPS://ai.ailink1.com",
        "https://ai.ailink1.com/",
        "https://ai.ailink1.com?",
        "https://ai.ailink1.com#",
        "https://ai.ailink1.com?route=claude",
        "https://ai.ailink1.com#fragment",
        "https://user@ai.ailink1.com",
        1,
    ],
)
def test_claude_adapter_rejects_noncanonical_relay_base_url(relay_base_url):
    with pytest.raises(AgentSetupError, match="relay base URL"):
        ClaudeCodeAdapter(model="model-a", relay_base_url=relay_base_url)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_claude_relay_requires_nonblank_auth_token(
    tmp_path, monkeypatch, fake_claude, value
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    if value is None:
        monkeypatch.delenv(AUTH_TOKEN, raising=False)
    else:
        monkeypatch.setenv(AUTH_TOKEN, value)

    with pytest.raises(AgentSetupError, match="relay.*authentication") as raised:
        ClaudeCodeAdapter(
            model="claude-sonnet-4-6",
            executable=executable,
            relay_base_url=RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt"))

    assert DUMMY_API_KEY not in str(raised.value)
    assert not log.exists()


def test_claude_relay_uses_explicit_endpoint_and_token_without_ambient_leakage(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt = "Relay prompt: 修复。\nKeep $HOME literal.\n"
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    monkeypatch.setenv(AUTH_TOKEN, DUMMY_AUTH_TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ambient.invalid")
    monkeypatch.setenv("ANTHROPIC_MODEL", "ambient-model")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "0")
    parent_environment = os.environ.copy()
    observed_model_environment = None
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        nonlocal observed_model_environment
        observed_model_environment = kwargs.get("env")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)
    adapter = ClaudeCodeAdapter(
        model="claude-sonnet-4-6",
        executable=executable,
        relay_base_url=RELAY_BASE_URL,
    )
    result = adapter.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert adapter.relay_base_url == RELAY_BASE_URL
    assert observed_model_environment is not None
    assert API_KEY not in observed_model_environment
    assert secrets.compare_digest(
        observed_model_environment[AUTH_TOKEN], DUMMY_AUTH_TOKEN
    )
    assert observed_model_environment["ANTHROPIC_BASE_URL"] == RELAY_BASE_URL
    assert observed_model_environment[
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
    ] == "1"
    assert observed_model_environment["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert "ANTHROPIC_MODEL" not in observed_model_environment
    assert os.environ == parent_environment

    records = invocations(log)
    assert [record["arguments"] for record in records[:2]] == [
        ["--version"],
        ["--help"],
    ]
    assert all(
        record["environment"]["api_key_present"] is False
        and record["environment"]["auth_token_present"] is False
        and record["environment"]["base_url"] is None
        for record in records[:2]
    )
    execution = records[2]
    assert execution["arguments"] == [
        "-p", "--bare", "--no-session-persistence", "--model",
        "claude-sonnet-4-6", "--output-format", "json", "--no-chrome",
        "--tools", "Read,Edit,Bash", "--allowedTools", "Read", "Edit", "Bash",
        "--disallowedTools", "mcp__*", "--permission-mode", "default",
        "--permission-prompts", "none",
    ]
    assert execution["prompt"] == prompt
    assert execution["environment"]["api_key_present"] is False
    assert execution["environment"]["auth_token_present"] is True
    assert execution["environment"]["base_url"] == RELAY_BASE_URL
    assert execution["environment"]["nonessential_traffic"] == "1"
    serialized = log.read_text(encoding="utf-8")
    assert DUMMY_API_KEY not in serialized
    assert DUMMY_AUTH_TOKEN not in serialized
    assert DUMMY_API_KEY not in result.stdout + result.stderr
    assert DUMMY_AUTH_TOKEN not in result.stdout + result.stderr
    assert DUMMY_API_KEY not in execution["arguments"]
    assert DUMMY_AUTH_TOKEN not in execution["arguments"]


def test_claude_relay_error_does_not_disclose_token(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(AUTH_TOKEN, DUMMY_AUTH_TOKEN)
    monkeypatch.setenv(DELETE_AFTER_HELP, "1")
    adapter = ClaudeCodeAdapter(
        model="claude-sonnet-4-6",
        executable=executable,
        relay_base_url=RELAY_BASE_URL,
    )

    with pytest.raises(AgentInfrastructureError, match="start Claude Code") as raised:
        adapter.run(AgentRunRequest(workspace, "prompt"))

    assert DUMMY_AUTH_TOKEN not in str(raised.value)
    assert DUMMY_AUTH_TOKEN not in log.read_text(encoding="utf-8")


def test_claude_adapter_maps_nonzero_execution_to_command_failed(
    tmp_path, monkeypatch, fake_claude
):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(EXIT_CODE, "7")
    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "Attempt repair")
    )
    assert result.status is AgentRunStatus.COMMAND_FAILED
    assert result.exit_code == 7
    assert result.stdout == '{"result":"done"}\n'
    assert result.stderr == "claude diagnostic\n"


@pytest.mark.parametrize("model", ["", "   ", " model", "model ", "two words", 1])
def test_claude_adapter_rejects_invalid_model(model):
    with pytest.raises(AgentSetupError, match="model"):
        ClaudeCodeAdapter(model=model)


def test_claude_adapter_rejects_blank_executable():
    with pytest.raises(AgentSetupError, match="executable"):
        ClaudeCodeAdapter(model="model-a", executable="   ")


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_claude_adapter_rejects_invalid_workspace_before_preflight(
    tmp_path, fake_claude, kind
):
    executable, log = fake_claude
    workspace = tmp_path / kind
    if kind == "file":
        workspace.write_text("file")
    with pytest.raises(AgentSetupError, match="workspace"):
        ClaudeCodeAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert not log.exists()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "1"])
def test_claude_adapter_rejects_invalid_timeout_before_preflight(
    tmp_path, fake_claude, timeout
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(AgentSetupError, match="finite positive"):
        ClaudeCodeAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=timeout)
        )
    assert not log.exists()


def test_missing_executable_is_setup_error(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    adapter = ClaudeCodeAdapter(model="model-a", executable=tmp_path / "missing")
    with pytest.raises(AgentSetupError, match="version preflight"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None


@pytest.mark.parametrize(
    "mode,match",
    [("nonzero", "exit code 4"), ("blank", "canonical version")],
)
def test_version_preflight_failures_are_setup_errors(
    tmp_path, monkeypatch, fake_claude, mode, match
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_MODE, mode)
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match=match):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None
    assert [item["arguments"] for item in invocations(log)] == [["--version"]]


@pytest.mark.parametrize(
    "mode,match",
    [
        ("nonzero", "help preflight failed with exit code 5"),
        ("missing-allowed-tools", "required flags are unavailable"),
    ],
)
def test_help_preflight_requires_allowed_tools_support(
    tmp_path, monkeypatch, fake_claude, mode, match
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(HELP_MODE, mode)
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match=match):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None
    assert [item["arguments"] for item in invocations(log)] == [
        ["--version"],
        ["--help"],
    ]


def test_help_preflight_is_bounded_by_agent_timeout(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(HELP_SLEEP, "1")
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match="help preflight exceeded"):
        adapter.run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=0.5)
        )
    assert adapter.cli_version is None
    assert [item["arguments"] for item in invocations(log)] == [
        ["--version"],
        ["--help"],
    ]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_api_key_is_private_setup_error(
    tmp_path, monkeypatch, fake_claude, value
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if value is None:
        monkeypatch.delenv(API_KEY, raising=False)
    else:
        monkeypatch.setenv(API_KEY, value)
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match="authentication is unavailable") as raised:
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert DUMMY_API_KEY not in str(raised.value)
    assert adapter.cli_version is None
    assert not log.exists()


@pytest.mark.parametrize(
    "version,accepted",
    [
        ("2.1.258", False),
        ("2.1.259", True),
        ("2.1.999", True),
        ("2.2.0", True),
        ("3.0.0", True),
        ("Claude Code 2.1.260 (native)", True),
        ("not-a-version", False),
    ],
)
def test_required_cli_version_gate(
    tmp_path, monkeypatch, fake_claude, version, accepted
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_OUTPUT, version)
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    if accepted:
        result = adapter.run(AgentRunRequest(workspace, "prompt"))
        assert result.status is AgentRunStatus.COMPLETED
        assert adapter.cli_version == version
    else:
        with pytest.raises(AgentSetupError, match="version|required"):
            adapter.run(AgentRunRequest(workspace, "prompt"))
        assert adapter.cli_version is None
    assert invocations(log)[0]["arguments"] == ["--version"]


def test_execution_start_failure_after_preflight_is_infrastructure_error(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(DELETE_AFTER_HELP, "1")
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentInfrastructureError, match="start Claude Code"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version == "2.1.259 (Claude Code)"
    assert [item["arguments"] for item in invocations(log)] == [
        ["--version"],
        ["--help"],
    ]


def test_version_preflight_is_bounded_by_agent_timeout(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.2")
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)

    with pytest.raises(AgentSetupError, match="version preflight exceeded"):
        adapter.run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=0.05)
        )

    assert adapter.cli_version is None
    assert [item["arguments"] for item in invocations(log)] == [["--version"]]


def test_version_preflight_consumes_model_timeout_budget(
    tmp_path, monkeypatch, fake_claude
):
    executable, log = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.15")
    monkeypatch.setenv(HELP_SLEEP, "0.15")
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(PRE_TIMEOUT_OUTPUT, "1")

    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=1.2)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == '{"partial":true}\n'
    assert [item["arguments"] for item in invocations(log)] == [
        ["--version"],
        ["--help"],
        [
            "-p", "--bare", "--no-session-persistence", "--model", "model-a",
            "--output-format", "json", "--no-chrome", "--tools", "Read,Edit,Bash",
            "--allowedTools", "Read", "Edit", "Bash", "--disallowedTools", "mcp__*",
            "--permission-mode", "default",
            "--permission-prompts", "none",
        ],
    ]


def test_none_timeout_allows_preflight_and_execution_without_deadline(
    tmp_path, monkeypatch, fake_claude
):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.03")
    monkeypatch.setenv(HELP_SLEEP, "0.03")
    monkeypatch.setenv(SLEEP, "0.03")

    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=None)
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.duration_seconds >= 0.08


def test_timeout_returns_output_and_terminates_process(
    tmp_path, monkeypatch, fake_claude
):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(PRE_TIMEOUT_OUTPUT, "1")
    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.7)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == '{"partial":true}\n'
    assert result.stderr == "diagnostic before timeout\n"


def test_timeout_uses_sigkill_fallback(tmp_path, monkeypatch, fake_claude):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(IGNORE_TERM, "1")
    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.7)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None


def test_timeout_stops_descendant_process(tmp_path, monkeypatch, fake_claude):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "survived"
    started = tmp_path / "child-started"
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(CHILD_SENTINEL, str(sentinel))
    monkeypatch.setenv(CHILD_STARTED, str(started))
    result = ClaudeCodeAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.7)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert started.read_text() == "started"
    time.sleep(1.1)
    assert not sentinel.exists()


def test_cleanup_failure_is_infrastructure_error(
    tmp_path, monkeypatch, fake_claude
):
    executable, _ = fake_claude
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = ClaudeCodeAdapter(model="model-a", executable=executable)
    monkeypatch.setattr(adapter, "_process_group_exists", lambda process_id: True)

    def fail_cleanup(process):
        raise AgentInfrastructureError("simulated cleanup failure")

    monkeypatch.setattr(adapter, "_terminate_process_group", fail_cleanup)
    monkeypatch.setattr(adapter, "_force_cleanup", lambda process: "forced cleanup failed")
    with pytest.raises(AgentInfrastructureError, match="clean up Claude Code process group"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
