import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from textwrap import dedent
import time

import pytest

import patchbench.agents.cursor_cli as cursor_cli_module
from patchbench.agents import CursorCliAdapter
from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)


LOG = "PATCHBENCH_TEST_CURSOR_LOG"
VERSION_MODE = "PATCHBENCH_TEST_CURSOR_VERSION_MODE"
HELP_MODE = "PATCHBENCH_TEST_CURSOR_HELP_MODE"
MODELS_MODE = "PATCHBENCH_TEST_CURSOR_MODELS_MODE"
MODELS_OUTPUT = "PATCHBENCH_TEST_CURSOR_MODELS_OUTPUT"
VERSION_SLEEP = "PATCHBENCH_TEST_CURSOR_VERSION_SLEEP"
HELP_SLEEP = "PATCHBENCH_TEST_CURSOR_HELP_SLEEP"
MODELS_SLEEP = "PATCHBENCH_TEST_CURSOR_MODELS_SLEEP"
DELETE_AFTER_MODELS = "PATCHBENCH_TEST_CURSOR_DELETE_AFTER_MODELS"
EXIT_CODE = "PATCHBENCH_TEST_CURSOR_EXIT_CODE"
SLEEP = "PATCHBENCH_TEST_CURSOR_SLEEP"
IGNORE_TERM = "PATCHBENCH_TEST_CURSOR_IGNORE_TERM"
PRE_TIMEOUT_OUTPUT = "PATCHBENCH_TEST_CURSOR_PRE_TIMEOUT_OUTPUT"
CHILD_SENTINEL = "PATCHBENCH_TEST_CURSOR_CHILD_SENTINEL"
CHILD_STARTED = "PATCHBENCH_TEST_CURSOR_CHILD_STARTED"
API_KEY = "CURSOR_API_KEY"
DUMMY_API_KEY = "  dummy-cursor-secret-never-log  "
ENDPOINT = "https://api2.cursor.sh"
MODEL = "claude-4.6-sonnet-medium"
REALISTIC_MODELS_OUTPUT = """Available models

auto - Auto (default)
claude-4.6-sonnet-medium - Claude Sonnet 4.6 1M
claude-4.6-sonnet-medium-thinking - Claude Sonnet 4.6 1M Thinking

Tip: use --model <id> to switch."""
AMBIENT_CURSOR_VARIABLES = {
    "CURSOR_AUTH_TOKEN",
    "CURSOR_API_ENDPOINT",
    "CURSOR_API_URL",
    "CURSOR_AGENT_MODEL",
    "CURSOR_RULES",
}
REQUIRED_HELP_FLAGS = (
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


@pytest.fixture
def fake_cursor(tmp_path, monkeypatch):
    executable = tmp_path / "fake-agent"
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
        home = Path(os.environ["HOME"])
        config_dir = Path(os.environ["CURSOR_CONFIG_DIR"])
        config_path = config_dir / "cli-config.json"
        hooks_path = config_dir / "hooks.json"
        policy_path = config_dir / "hooks" / "patchbench_policy.py"
        record = {{
            "arguments": arguments,
            "cwd": os.getcwd(),
            "environment": {{
                "api_key_present": bool(os.environ.get("{API_KEY}")),
                "auth_token_present": bool(os.environ.get("CURSOR_AUTH_TOKEN")),
                "home": str(home),
                "config_dir": str(config_dir),
                "xdg_config_present": "XDG_CONFIG_HOME" in os.environ,
                "ambient_cursor_present": sorted(
                    name for name in {sorted(AMBIENT_CURSOR_VARIABLES)!r}
                    if name in os.environ
                ),
                "path": os.environ.get("PATH"),
            }},
            "state": {{
                "entries": sorted(
                    str(path.relative_to(home)) for path in home.rglob("*")
                ),
                "config": config_path.read_text(encoding="utf-8"),
                "hooks": hooks_path.read_text(encoding="utf-8"),
                "policy": policy_path.read_text(encoding="utf-8"),
                "policy_executable": os.access(policy_path, os.X_OK),
            }},
        }}
        with Path(os.environ["{LOG}"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\\n")

        if arguments == ["--disable-auto-update", "--version"]:
            time.sleep(float(os.environ.get("{VERSION_SLEEP}", "0")))
            mode = os.environ.get("{VERSION_MODE}")
            if mode == "nonzero":
                raise SystemExit(4)
            if mode == "blank":
                raise SystemExit(0)
            if mode == "padded":
                print(" 2026.09.18-test ")
            else:
                print("2026.09.18-test")
            raise SystemExit(0)

        if arguments == ["--disable-auto-update", "--help"]:
            time.sleep(float(os.environ.get("{HELP_SLEEP}", "0")))
            mode = os.environ.get("{HELP_MODE}")
            if mode == "nonzero":
                raise SystemExit(5)
            flags = list({list(REQUIRED_HELP_FLAGS)!r})
            if mode == "missing":
                flags.remove("--sandbox")
            print("\\n".join(flags))
            raise SystemExit(0)

        model_list_arguments = [
            "--disable-auto-update", "--endpoint", "{ENDPOINT}", "--list-models"
        ]
        if arguments == model_list_arguments:
            time.sleep(float(os.environ.get("{MODELS_SLEEP}", "0")))
            if os.environ.get("{MODELS_MODE}") == "nonzero":
                raise SystemExit(6)
            print(os.environ.get("{MODELS_OUTPUT}", {REALISTIC_MODELS_OUTPUT!r}))
            if os.environ.get("{DELETE_AFTER_MODELS}") == "1":
                Path(sys.argv[0]).unlink()
            raise SystemExit(0)

        if "--print" in arguments:
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
            print("cursor diagnostic", file=sys.stderr)
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


def model_arguments(workspace, prompt="repair this"):
    return [
        "--disable-auto-update",
        "--print",
        "--output-format",
        "json",
        "--model",
        MODEL,
        "--endpoint",
        ENDPOINT,
        "--workspace",
        str(workspace.resolve()),
        "--sandbox",
        "enabled",
        "--force",
        "--trust",
        prompt,
    ]


def expected_cli_config():
    return {
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


def assert_temporary_state_removed(log):
    records = invocations(log)
    assert records
    assert all(not Path(item["environment"]["home"]).exists() for item in records)


def test_exact_invocation_fresh_state_config_and_credential_boundary(
    tmp_path, monkeypatch, fake_cursor
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    operator_home = tmp_path / "operator-home"
    operator_cursor = operator_home / ".cursor"
    operator_cursor.mkdir(parents=True)
    (operator_cursor / "session.json").write_text("personal-session\n")
    monkeypatch.setenv("HOME", str(operator_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in AMBIENT_CURSOR_VARIABLES:
        monkeypatch.setenv(name, "ambient-cursor-value")
    original_path = os.environ["PATH"]
    parent_environment = os.environ.copy()
    prompt = "修复问题。 Keep $HOME and `code`."
    observed_environments = []
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        observed_environments.append(kwargs.get("env"))
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)

    adapter = CursorCliAdapter(model=MODEL, executable=executable)
    agent: Agent = adapter
    result = agent.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"result":"done"}\n'
    assert result.stderr == "cursor diagnostic\n"
    assert adapter.model == MODEL
    assert adapter.executable == str(executable)
    assert adapter.endpoint == ENDPOINT
    assert adapter.cli_version == "2026.09.18-test"
    assert os.environ == parent_environment
    assert [API_KEY in environment for environment in observed_environments] == [
        False, False, True, True
    ]
    assert all(
        secrets.compare_digest(environment[API_KEY], DUMMY_API_KEY)
        for environment in observed_environments[2:]
    )

    records = invocations(log)
    assert [item["arguments"] for item in records] == [
        ["--disable-auto-update", "--version"],
        ["--disable-auto-update", "--help"],
        ["--disable-auto-update", "--endpoint", ENDPOINT, "--list-models"],
        model_arguments(workspace, prompt),
    ]
    homes = {item["environment"]["home"] for item in records}
    config_dirs = {item["environment"]["config_dir"] for item in records}
    assert len(homes) == 1
    assert len(config_dirs) == 1
    fresh_home = Path(next(iter(homes)))
    fresh_config = Path(next(iter(config_dirs)))
    assert fresh_home != operator_home
    assert fresh_config == fresh_home / ".cursor"
    assert workspace.resolve() not in fresh_home.parents
    assert all(item["environment"]["path"] == original_path for item in records)
    assert all(not item["environment"]["xdg_config_present"] for item in records)
    assert all(not item["environment"]["ambient_cursor_present"] for item in records)
    assert [item["environment"]["api_key_present"] for item in records] == [
        False, False, True, True
    ]
    assert all(not item["environment"]["auth_token_present"] for item in records)
    expected_config_text = json.dumps(
        expected_cli_config(), indent=2, ensure_ascii=False, allow_nan=False
    ) + "\n"
    assert all(item["state"]["config"] == expected_config_text for item in records)
    assert all(item["state"]["policy_executable"] for item in records)
    hooks = json.loads(records[0]["state"]["hooks"])
    hook_entry = hooks["hooks"]["preToolUse"][0]
    assert hooks["version"] == 1
    assert hook_entry == {
        "command": str(fresh_config / "hooks" / "patchbench_policy.py"),
        "matcher": "^(Shell|WebSearch|Task)$",
        "failClosed": True,
    }
    assert not fresh_home.exists()
    assert (operator_cursor / "session.json").read_text() == "personal-session\n"
    serialized = log.read_text()
    assert DUMMY_API_KEY not in serialized
    assert DUMMY_API_KEY not in result.stdout + result.stderr
    assert all(DUMMY_API_KEY not in argument for item in records
               for argument in item["arguments"])


def test_each_run_uses_different_temporary_state(tmp_path, fake_cursor):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CursorCliAdapter(model=MODEL, executable=executable)

    adapter.run(AgentRunRequest(workspace, "first"))
    adapter.run(AgentRunRequest(workspace, "second"))

    records = invocations(log)
    first_home = records[0]["environment"]["home"]
    second_home = records[4]["environment"]["home"]
    assert {item["environment"]["home"] for item in records[:4]} == {first_home}
    assert {item["environment"]["home"] for item in records[4:]} == {second_home}
    assert first_home != second_home
    assert_temporary_state_removed(log)


@pytest.mark.parametrize("model", ["", "   ", " model", "model ", "two words", 1])
def test_rejects_invalid_model(model):
    with pytest.raises(AgentSetupError, match="model"):
        CursorCliAdapter(model=model)


def test_rejects_blank_executable():
    with pytest.raises(AgentSetupError, match="executable"):
        CursorCliAdapter(model=MODEL, executable="   ")


def test_accepts_canonical_https_endpoint_with_path_and_port():
    adapter = CursorCliAdapter(
        model=MODEL, endpoint="https://api2.cursor.sh:8443/v1"
    )
    assert adapter.endpoint == "https://api2.cursor.sh:8443/v1"


@pytest.mark.parametrize(
    "endpoint",
    [
        "", " ", " https://api2.cursor.sh", "https://api2.cursor.sh ",
        "http://api2.cursor.sh", "HTTPS://api2.cursor.sh",
        "https://api2.cursor.sh/",
        "https://api2.cursor.sh?x=1", "https://api2.cursor.sh#x",
        "https://user@api2.cursor.sh", "https://api2.cursor.sh:99999", 1,
    ],
)
def test_rejects_invalid_endpoint(endpoint):
    with pytest.raises(AgentSetupError, match="endpoint"):
        CursorCliAdapter(model=MODEL, endpoint=endpoint)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_api_key_is_private_setup_error(
    tmp_path, monkeypatch, fake_cursor, value
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if value is None:
        monkeypatch.delenv(API_KEY, raising=False)
    else:
        monkeypatch.setenv(API_KEY, value)
    with pytest.raises(AgentSetupError, match="authentication") as raised:
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert DUMMY_API_KEY not in str(raised.value)
    assert not log.exists()


def test_missing_executable_error_does_not_disclose_api_key(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    adapter = CursorCliAdapter(model=MODEL, executable=tmp_path / "missing")
    with pytest.raises(AgentSetupError, match="version preflight") as raised:
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert DUMMY_API_KEY not in str(raised.value)


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_rejects_invalid_workspace_before_setup(tmp_path, fake_cursor, kind):
    executable, log = fake_cursor
    workspace = tmp_path / kind
    if kind == "file":
        workspace.write_text("file")
    with pytest.raises(AgentSetupError, match="workspace"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert not log.exists()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "1"])
def test_rejects_invalid_timeout_before_setup(tmp_path, fake_cursor, timeout):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(AgentSetupError, match="finite positive"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=timeout)
        )
    assert not log.exists()


@pytest.mark.parametrize(
    "models_output,accepted",
    [
        (REALISTIC_MODELS_OUTPUT, True),
        ("auto - Auto (default)", False),
        (f"prefix-{MODEL} - Other", False),
        (f"{MODEL}-thinking - Claude Sonnet 4.6 1M Thinking", False),
        (f" {MODEL} - Claude Sonnet 4.6 1M", False),
        ("Claude Sonnet 4.6 1M", False),
        ("Available models\n\nTip: use --model <id> to switch.", False),
        (
            "Available models\n\n"
            "auto - Auto (default)\n"
            "gpt-5 - GPT-5\n"
            f"{MODEL} - Display prose is not parsed\n"
            "other-model - Other\n\n"
            "Tip: use --model <id> to switch.",
            True,
        ),
    ],
)
def test_requested_model_requires_exact_available_id_line(
    tmp_path, monkeypatch, fake_cursor, models_output, accepted
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(MODELS_OUTPUT, models_output)
    adapter = CursorCliAdapter(model=MODEL, executable=executable)
    if accepted:
        result = adapter.run(AgentRunRequest(workspace, "prompt"))
        assert result.status is AgentRunStatus.COMPLETED
    else:
        with pytest.raises(AgentSetupError, match="requested model is unavailable"):
            adapter.run(AgentRunRequest(workspace, "prompt"))
    assert_temporary_state_removed(log)


def test_model_list_parser_rejects_whitespace_and_control_in_candidate_id():
    parse = CursorCliAdapter._parse_available_model_ids
    assert parse("model id - Display") == set()
    assert parse("model\tid - Display") == set()
    assert parse("model\x1fid - Display") == set()


@pytest.mark.parametrize(
    "tool_input,expected_permission",
    [
        ({"tool_name": "WebSearch", "tool_input": {"query": "x"}}, "deny"),
        ({"tool_name": "Task", "tool_input": {"prompt": "x"}}, "deny"),
        ({"tool_name": "Read", "tool_input": {"path": "x"}}, "deny"),
        ({"tool_name": "Shell", "tool_input": {}}, "deny"),
    ],
)
def test_policy_hook_denies_bounded_and_invalid_tools(
    tmp_path, tool_input, expected_permission
):
    hook = tmp_path / "hook.py"
    hook.write_text(cursor_cli_module._POLICY_HOOK_SOURCE)
    result = subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(tool_input),
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "permission": expected_permission,
        "user_message": "Blocked by PatchBench policy.",
    }


@pytest.mark.parametrize(
    "original_command",
    [
        "echo hello",
        "printf '%s\\n' \"hello world\"",
        "printf x | grep x",
        "printf x > out.txt",
        "cd src && pytest -q",
        "[[ -f file ]] && echo yes",
        "printf x\nprintf y",
    ],
)
def test_policy_hook_sanitizes_shell_without_changing_command_semantics(
    tmp_path, original_command
):
    hook = tmp_path / "hook.py"
    hook.write_text(cursor_cli_module._POLICY_HOOK_SOURCE)
    original_input = {
        "command": original_command,
        "timeout": 10,
        "description": "preserve this field",
        "metadata": {"nested": [1, True, None]},
    }
    request = {
        "tool_name": "Shell",
        "tool_input": original_input,
    }
    result = subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(request),
        text=True, capture_output=True, check=False,
    )
    response = json.loads(result.stdout)
    assert result.returncode == 0
    assert result.stderr == ""
    assert response["permission"] == "allow"
    expected_command = (
        "unset CURSOR_API_KEY CURSOR_AUTH_TOKEN; " + original_command
    )
    assert response["updated_input"] == {
        **original_input,
        "command": expected_command,
    }
    assert response["updated_input"]["command"] == expected_command
    assert "/bin/sh" not in response["updated_input"]["command"]
    assert "/bin/bash" not in response["updated_input"]["command"]
    assert DUMMY_API_KEY not in response["updated_input"]["command"]


@pytest.mark.parametrize("payload", ["{", "[]", "null", '{"tool_name":"Shell"}'])
def test_policy_hook_fails_closed_on_malformed_request(tmp_path, payload):
    hook = tmp_path / "hook.py"
    hook.write_text(cursor_cli_module._POLICY_HOOK_SOURCE)
    result = subprocess.run(
        [sys.executable, str(hook)], input=payload,
        text=True, capture_output=True, check=False,
    )
    assert json.loads(result.stdout)["permission"] == "deny"
    assert result.stderr == ""
    if payload in {"{", "[]", "null", '{"tool_name":"Shell"}'}:
        assert result.returncode != 0


@pytest.mark.parametrize(
    "mode_variable,mode_value,match",
    [
        (VERSION_MODE, "nonzero", "version preflight failed"),
        (VERSION_MODE, "blank", "canonical version"),
        (VERSION_MODE, "padded", "canonical version"),
        (HELP_MODE, "nonzero", "help preflight failed"),
        (HELP_MODE, "missing", "required flags"),
        (MODELS_MODE, "nonzero", "model-list preflight failed"),
    ],
)
def test_preflight_failures_are_setup_errors_and_remove_state(
    tmp_path, monkeypatch, fake_cursor, mode_variable, mode_value, match
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(mode_variable, mode_value)
    with pytest.raises(AgentSetupError, match=match):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert_temporary_state_removed(log)


def test_execution_start_failure_is_infrastructure_error_and_removes_state(
    tmp_path, monkeypatch, fake_cursor
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(DELETE_AFTER_MODELS, "1")
    with pytest.raises(AgentInfrastructureError, match="start Cursor CLI"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert_temporary_state_removed(log)


def test_nonzero_execution_maps_to_command_failed_and_removes_state(
    tmp_path, monkeypatch, fake_cursor
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(EXIT_CODE, "7")
    result = CursorCliAdapter(model=MODEL, executable=executable).run(
        AgentRunRequest(workspace, "prompt")
    )
    assert result.status is AgentRunStatus.COMMAND_FAILED
    assert result.exit_code == 7
    assert_temporary_state_removed(log)


def test_one_deadline_covers_preflight_and_model(tmp_path, monkeypatch, fake_cursor):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.1")
    monkeypatch.setenv(HELP_SLEEP, "0.1")
    monkeypatch.setenv(MODELS_SLEEP, "0.1")
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(PRE_TIMEOUT_OUTPUT, "1")
    result = CursorCliAdapter(model=MODEL, executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.8)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == '{"partial":true}\n'
    assert_temporary_state_removed(log)


def test_preflight_timeout_is_setup_error(tmp_path, monkeypatch, fake_cursor):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(MODELS_SLEEP, "1")
    with pytest.raises(AgentSetupError, match="model-list preflight exceeded"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=0.3)
        )
    assert_temporary_state_removed(log)


def test_timeout_uses_sigkill_fallback(tmp_path, monkeypatch, fake_cursor):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(IGNORE_TERM, "1")
    result = CursorCliAdapter(model=MODEL, executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.5)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert_temporary_state_removed(log)


@pytest.mark.parametrize("model_sleep,timeout", [(0, None), (1, 0.5)])
def test_process_group_cleanup_stops_descendant(
    tmp_path, monkeypatch, fake_cursor, model_sleep, timeout
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "survived"
    started = tmp_path / "child-started"
    monkeypatch.setenv(SLEEP, str(model_sleep))
    monkeypatch.setenv(CHILD_SENTINEL, str(sentinel))
    monkeypatch.setenv(CHILD_STARTED, str(started))
    result = CursorCliAdapter(model=MODEL, executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=timeout)
    )
    assert result.status in {AgentRunStatus.COMPLETED, AgentRunStatus.TIMED_OUT}
    assert started.read_text() == "started"
    time.sleep(1.1)
    assert not sentinel.exists()
    assert_temporary_state_removed(log)


def test_cleanup_failure_is_infrastructure_error(tmp_path, monkeypatch, fake_cursor):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CursorCliAdapter(model=MODEL, executable=executable)
    monkeypatch.setattr(adapter, "_process_group_exists", lambda process_id: True)

    def fail_cleanup(process):
        raise AgentInfrastructureError("simulated cleanup failure")

    monkeypatch.setattr(adapter, "_terminate_process_group", fail_cleanup)
    monkeypatch.setattr(adapter, "_force_cleanup", lambda process: "forced failure")
    with pytest.raises(AgentInfrastructureError, match="clean up Cursor CLI"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert_temporary_state_removed(log)


def test_temporary_state_creation_failure_is_infrastructure_error(
    tmp_path, monkeypatch, fake_cursor
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail_creation(**kwargs):
        raise OSError("simulated state failure")

    monkeypatch.setattr(cursor_cli_module, "TemporaryDirectory", fail_creation)
    with pytest.raises(AgentInfrastructureError, match="isolated Cursor CLI state"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert not log.exists()


def test_temporary_state_inside_workspace_is_rejected_and_removed(
    tmp_path, monkeypatch, fake_cursor
):
    executable, log = fake_cursor
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    created_home = None

    def create_inside_workspace(**kwargs):
        nonlocal created_home
        temporary_directory = tempfile.TemporaryDirectory(
            dir=workspace, **kwargs
        )
        created_home = Path(temporary_directory.name)
        return temporary_directory

    monkeypatch.setattr(
        cursor_cli_module, "TemporaryDirectory", create_inside_workspace
    )
    with pytest.raises(AgentInfrastructureError, match="inside the workspace"):
        CursorCliAdapter(model=MODEL, executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert created_home is not None
    assert not created_home.exists()
    assert not log.exists()
