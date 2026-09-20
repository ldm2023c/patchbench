import json
import os
from pathlib import Path, PurePosixPath
import secrets
import signal
import subprocess
import sys
from textwrap import dedent
import time
import tomllib

import pytest

import patchbench.agents.grok_build as grok_build_module
from patchbench.agents import GrokBuildAdapter
from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)
from scripts.prepare_pilot_fixtures import template_files
from scripts.v13_candidate_manifest import load_candidate_manifest


LOG = "PATCHBENCH_TEST_GROK_LOG"
VERSION_MODE = "PATCHBENCH_TEST_GROK_VERSION_MODE"
HELP_MODE = "PATCHBENCH_TEST_GROK_HELP_MODE"
VERSION_SLEEP = "PATCHBENCH_TEST_GROK_VERSION_SLEEP"
HELP_SLEEP = "PATCHBENCH_TEST_GROK_HELP_SLEEP"
DELETE_AFTER_HELP = "PATCHBENCH_TEST_GROK_DELETE_AFTER_HELP"
EXIT_CODE = "PATCHBENCH_TEST_GROK_EXIT_CODE"
SLEEP = "PATCHBENCH_TEST_GROK_SLEEP"
IGNORE_TERM = "PATCHBENCH_TEST_GROK_IGNORE_TERM"
PRE_TIMEOUT_OUTPUT = "PATCHBENCH_TEST_GROK_PRE_TIMEOUT_OUTPUT"
CHILD_SENTINEL = "PATCHBENCH_TEST_GROK_CHILD_SENTINEL"
CHILD_STARTED = "PATCHBENCH_TEST_GROK_CHILD_STARTED"
API_KEY = "XAI_API_KEY"
DUMMY_API_KEY = "  dummy-xai-secret-never-log  "
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROK_PROJECT_RULE_COMPONENTS = {
    "agent.md",
    "agents.md",
    "claude.md",
    "claude.local.md",
    ".grok",
    ".claude",
    ".cursor",
    ".envrc",
    ".mcp.json",
}
AMBIENT_TOOL_VARIABLES = {
    "GROK_CONFIG_FILE",
    "GROK_MODEL",
    "GROK_MODELS_BASE_URL",
    "GROK_MODELS_LIST_URL",
    "GROK_CLI_CHAT_PROXY_BASE_URL",
    "GROK_RULES",
    "XAI_BASE_URL",
    "XAI_MODEL",
}
CONTROL_VALUES = {
    "GROK_DISABLE_AUTOUPDATER": "1",
    "GROK_FEEDBACK_ENABLED": "0",
    "GROK_MEMORY": "0",
    "GROK_SUBAGENTS": "0",
    "GROK_TELEMETRY_ENABLED": "0",
    "GROK_TELEMETRY_MIXPANEL_ENABLED": "0",
    "GROK_TELEMETRY_TRACE_UPLOAD": "0",
    "GROK_WEB_FETCH": "0",
    "GROK_WORKFLOWS": "0",
}
REQUIRED_HELP_FLAGS = (
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
VERSION_ARGUMENTS = ["--no-auto-update", "--no-memory", "--version"]


@pytest.fixture
def fake_grok(tmp_path, monkeypatch):
    executable = tmp_path / "fake-grok"
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
        model_config_path = Path(os.environ["GROK_HOME"]) / "config.toml"
        record = {{
            "arguments": arguments,
            "cwd": os.getcwd(),
            "environment": {{
                "api_key_present": bool(os.environ.get("{API_KEY}")),
                "home": os.environ.get("HOME"),
                "home_exists": Path(os.environ["HOME"]).is_dir(),
                "grok_home": os.environ.get("GROK_HOME"),
                "grok_home_exists": Path(os.environ["GROK_HOME"]).is_dir(),
                "grok_config": os.environ.get("GROK_CONFIG"),
                "model_config_exists": model_config_path.is_file(),
                "model_config": (
                    model_config_path.read_text(encoding="utf-8")
                    if model_config_path.is_file() else None
                ),
                "ambient_present": sorted(
                    name for name in {sorted(AMBIENT_TOOL_VARIABLES)!r}
                    if name in os.environ
                ),
                "controls": {{
                    name: os.environ.get(name)
                    for name in {sorted(CONTROL_VALUES)!r}
                }},
                "path": os.environ.get("PATH"),
            }},
        }}
        with Path(os.environ["{LOG}"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\\n")

        if arguments == {VERSION_ARGUMENTS!r}:
            time.sleep(float(os.environ.get("{VERSION_SLEEP}", "0")))
            mode = os.environ.get("{VERSION_MODE}")
            if mode in {{"nonzero", "reject-no-auto-update", "reject-no-memory"}}:
                print("version failed", file=sys.stderr)
                raise SystemExit(4)
            if mode != "blank":
                print("grok build 0.9.0 (test)")
            raise SystemExit(0)

        if arguments == ["--help"]:
            time.sleep(float(os.environ.get("{HELP_SLEEP}", "0")))
            mode = os.environ.get("{HELP_MODE}")
            if mode == "nonzero":
                print("help failed", file=sys.stderr)
                raise SystemExit(5)
            flags = list({list(REQUIRED_HELP_FLAGS)!r})
            if mode == "missing":
                flags.remove("--disable-web-search")
            if mode == "missing-verbatim":
                flags.remove("--verbatim")
            print("\\n".join(flags))
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
            print("grok diagnostic", file=sys.stderr)
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


def assert_grok_project_rules_are_neutral(paths):
    for path_text in paths:
        path = PurePosixPath(path_text)
        assert not any(
            component.casefold() in GROK_PROJECT_RULE_COMPONENTS
            for component in path.parts
        ), path_text


def model_arguments(
    workspace,
    prompt="修复这个问题。\nKeep $HOME and `code`.\n",
    model="model-a",
):
    return [
        "--no-auto-update",
        "-p",
        prompt,
        "--verbatim",
        "--cwd",
        str(workspace.resolve()),
        "--model",
        model,
        "--output-format",
        "json",
        "--always-approve",
        "--tools",
        "read_file,grep,list_dir,search_replace,run_terminal_cmd",
        "--disallowed-tools",
        "search_tool,use_tool,Agent,web_search,web_fetch",
        "--no-plan",
        "--no-subagents",
        "--no-memory",
        "--disable-web-search",
    ]


def relay_config_text(context_window=500000):
    lines = [
        "[models]",
        'default = "grok-4.5"',
        "",
        '[model."grok-4.5"]',
        'model = "grok-4.5"',
        'base_url = "https://ai.ailink1.com/v1"',
        'env_key = "XAI_API_KEY"',
        'api_backend = "responses"',
        "supports_backend_search = false",
    ]
    if context_window is not None:
        lines.append(f"context_window = {context_window}")
    return "\n".join(lines) + "\n"


def test_grok_adapter_exact_invocation_and_isolated_environment(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_home = tmp_path / "real-home"
    real_grok_home = tmp_path / "real-grok-home"
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("GROK_HOME", str(real_grok_home))
    monkeypatch.setenv("GROK_CONFIG", "ambient-config")
    for name in AMBIENT_TOOL_VARIABLES:
        monkeypatch.setenv(name, "ambient-tool-value")
    for name in CONTROL_VALUES:
        monkeypatch.setenv(name, "ambient-control-value")
    original_path = os.environ["PATH"]
    observed_model_environment = None
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        nonlocal observed_model_environment
        if "-p" in args[0]:
            observed_model_environment = kwargs.get("env")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)
    prompt = "修复这个问题。\nKeep $HOME and `code`.\n"
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    agent: Agent = adapter
    result = agent.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"result":"done"}\n'
    assert result.stderr == "grok diagnostic\n"
    assert adapter.model == "model-a"
    assert adapter.executable == str(executable)
    assert adapter.cli_version == "grok build 0.9.0 (test)"
    assert observed_model_environment is not None
    assert secrets.compare_digest(observed_model_environment[API_KEY], DUMMY_API_KEY)
    assert DUMMY_API_KEY not in observed_model_environment["GROK_CONFIG"]
    expected_policy = {
        "features": {
            "remote_fetch": False,
        },
        "shell_environment_policy": {
            "ignore_default_excludes": False,
            "inherit": "core",
        }
    }
    policy_text = observed_model_environment["GROK_CONFIG"]
    policy = json.loads(policy_text)
    assert policy == expected_policy
    assert policy_text == json.dumps(
        expected_policy,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert observed_model_environment["PATH"] == original_path
    assert AMBIENT_TOOL_VARIABLES.isdisjoint(observed_model_environment)
    assert {name: observed_model_environment[name] for name in CONTROL_VALUES} == (
        CONTROL_VALUES
    )
    assert os.environ["HOME"] == str(real_home)
    assert os.environ["GROK_HOME"] == str(real_grok_home)
    assert os.environ["GROK_CONFIG"] == "ambient-config"
    assert secrets.compare_digest(os.environ[API_KEY], DUMMY_API_KEY)
    assert os.environ["GROK_DISABLE_AUTOUPDATER"] == "ambient-control-value"
    assert all(
        os.environ[name] == "ambient-tool-value"
        for name in AMBIENT_TOOL_VARIABLES
    )

    records = invocations(log)
    assert [record["arguments"] for record in records] == [
        VERSION_ARGUMENTS,
        ["--help"],
        model_arguments(workspace, prompt),
    ]
    assert DUMMY_API_KEY not in log.read_text()
    assert all(
        record["environment"]["ambient_present"] == [] for record in records
    )
    assert all(
        record["environment"]["controls"] == CONTROL_VALUES
        for record in records
    )
    assert all(record["environment"]["home_exists"] for record in records)
    assert all(record["environment"]["grok_home_exists"] for record in records)
    assert all(
        record["environment"]["model_config_exists"] is False
        for record in records
    )
    assert all(
        record["environment"]["model_config"] is None for record in records
    )
    assert all(
        json.loads(record["environment"]["grok_config"]) == policy
        for record in records
    )
    assert records[0]["environment"]["api_key_present"] is False
    assert records[1]["environment"]["api_key_present"] is False
    execution = records[2]
    assert execution["environment"]["api_key_present"] is True
    assert execution["cwd"] == str(workspace.resolve())
    assert execution["arguments"][2] == prompt
    isolated_home = Path(execution["environment"]["home"])
    grok_home = Path(execution["environment"]["grok_home"])
    assert isolated_home != real_home
    assert not isolated_home.is_relative_to(workspace.resolve())
    assert grok_home.parent == isolated_home
    assert not isolated_home.exists()
    assert prompt in execution["arguments"]
    assert DUMMY_API_KEY not in execution["arguments"]
    forbidden = {
        "--resume", "--continue", "--session-id", "--worktree", "--ref",
        "--rules", "--system-prompt-override", "--plugin-dir",
    }
    assert forbidden.isdisjoint(execution["arguments"])


@pytest.mark.parametrize(
    "relay_base_url",
    [
        "",
        "   ",
        " https://ai.ailink1.com/v1",
        "https://ai.ailink1.com/v1 ",
        "http://ai.ailink1.com/v1",
        "HTTPS://ai.ailink1.com/v1",
        "https://ai.ailink1.com/v1/",
        "https://ai.ailink1.com/v1?",
        "https://ai.ailink1.com/v1#",
        "https://ai.ailink1.com/v1?model=grok",
        "https://ai.ailink1.com/v1#fragment",
        "https://user@ai.ailink1.com/v1",
        1,
    ],
)
def test_rejects_noncanonical_relay_base_url(relay_base_url):
    with pytest.raises(AgentSetupError, match="relay base URL"):
        GrokBuildAdapter(model="model-a", relay_base_url=relay_base_url)


@pytest.mark.parametrize("context_window", [0, -1, True, 1.5, "500000"])
def test_rejects_invalid_relay_context_window(context_window):
    with pytest.raises(AgentSetupError, match="context window"):
        GrokBuildAdapter(
            model="model-a",
            relay_base_url="https://ai.ailink1.com/v1",
            relay_context_window=context_window,
        )


def test_rejects_relay_context_window_without_relay_base_url():
    with pytest.raises(AgentSetupError, match="requires a relay base URL"):
        GrokBuildAdapter(model="model-a", relay_context_window=500000)


def test_grok_relay_uses_owned_config_and_ignores_ambient_routes(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_home = tmp_path / "real-home"
    real_grok_home = tmp_path / "real-grok-home"
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("GROK_HOME", str(real_grok_home))
    monkeypatch.setenv("GROK_CONFIG", "ambient-config")
    for name in AMBIENT_TOOL_VARIABLES:
        monkeypatch.setenv(name, "https://ambient.invalid")
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    parent_environment = os.environ.copy()
    observed_model_environment = None
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        nonlocal observed_model_environment
        if "-p" in args[0]:
            observed_model_environment = kwargs.get("env")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)
    adapter = GrokBuildAdapter(
        model="grok-4.5",
        executable=executable,
        relay_base_url="https://ai.ailink1.com/v1",
        relay_context_window=500000,
    )
    result = adapter.run(AgentRunRequest(workspace, "relay prompt"))

    assert result.status is AgentRunStatus.COMPLETED
    assert adapter.relay_base_url == "https://ai.ailink1.com/v1"
    assert adapter.relay_context_window == 500000
    assert observed_model_environment is not None
    assert secrets.compare_digest(observed_model_environment[API_KEY], DUMMY_API_KEY)
    assert AMBIENT_TOOL_VARIABLES.isdisjoint(observed_model_environment)
    assert json.loads(observed_model_environment["GROK_CONFIG"]) == {
        "features": {"remote_fetch": False},
        "shell_environment_policy": {
            "ignore_default_excludes": False,
            "inherit": "core",
        },
    }
    assert os.environ == parent_environment

    records = invocations(log)
    assert [record["arguments"] for record in records] == [
        VERSION_ARGUMENTS,
        ["--help"],
        model_arguments(workspace, "relay prompt", model="grok-4.5"),
    ]
    expected_config = relay_config_text()
    assert all(
        record["environment"]["model_config_exists"] is True
        for record in records
    )
    assert all(
        record["environment"]["model_config"] == expected_config
        for record in records
    )
    parsed = tomllib.loads(expected_config)
    assert parsed == {
        "models": {"default": "grok-4.5"},
        "model": {
            "grok-4.5": {
                "model": "grok-4.5",
                "base_url": "https://ai.ailink1.com/v1",
                "env_key": "XAI_API_KEY",
                "api_backend": "responses",
                "supports_backend_search": False,
                "context_window": 500000,
            }
        },
    }
    assert DUMMY_API_KEY not in expected_config
    assert DUMMY_API_KEY not in log.read_text(encoding="utf-8")
    isolated_home = Path(records[0]["environment"]["home"])
    assert not isolated_home.exists()


def test_grok_relay_omits_context_window_unless_configured(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(EXIT_CODE, "7")
    result = GrokBuildAdapter(
        model="grok-4.5",
        executable=executable,
        relay_base_url="https://ai.ailink1.com/v1",
    ).run(AgentRunRequest(workspace, "prompt"))

    assert result.status is AgentRunStatus.COMMAND_FAILED
    records = invocations(log)
    assert all(
        record["environment"]["model_config"] == relay_config_text(None)
        for record in records
    )
    assert "context_window" not in tomllib.loads(relay_config_text(None))["model"][
        "grok-4.5"
    ]
    assert not Path(records[0]["environment"]["home"]).exists()


def test_grok_relay_removes_temporary_config_after_preflight_error(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(HELP_MODE, "nonzero")
    with pytest.raises(AgentSetupError, match="help preflight"):
        GrokBuildAdapter(
            model="grok-4.5",
            executable=executable,
            relay_base_url="https://ai.ailink1.com/v1",
        ).run(AgentRunRequest(workspace, "prompt"))

    records = invocations(log)
    assert all(record["environment"]["model_config_exists"] for record in records)
    assert not Path(records[0]["environment"]["home"]).exists()


def test_grok_relay_removes_temporary_config_after_timeout(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    result = GrokBuildAdapter(
        model="grok-4.5",
        executable=executable,
        relay_base_url="https://ai.ailink1.com/v1",
    ).run(AgentRunRequest(workspace, "prompt", timeout_seconds=0.5))

    assert result.status is AgentRunStatus.TIMED_OUT
    records = invocations(log)
    assert records[-1]["environment"]["model_config_exists"] is True
    assert not Path(records[-1]["environment"]["home"]).exists()


def test_candidate_fixtures_have_no_grok_project_rule_paths():
    candidate = load_candidate_manifest(PROJECT_ROOT)
    assert len(candidate.tasks) == 12
    for task in candidate.tasks:
        fixture = PROJECT_ROOT / "fixtures/reliability" / task.task_id
        tracked_template = {
            path.relative_to(fixture).as_posix()
            for path in template_files(fixture)
        }
        assert tracked_template
        assert_grok_project_rules_are_neutral(tracked_template)


@pytest.mark.parametrize(
    "path",
    [
        "src/agent.py",
        "docs/claude_notes.md",
        "docs/envrc_notes.md",
        "README.md",
    ],
)
def test_grok_project_rule_hygiene_allows_non_rule_paths(path):
    assert_grok_project_rules_are_neutral({path})


@pytest.mark.parametrize(
    "path",
    [
        "AGENT.md",
        "AGENTS.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".grok/config.toml",
        ".claude/settings.json",
        ".cursor/rules/example.mdc",
        ".envrc",
        ".mcp.json",
    ],
)
def test_grok_project_rule_hygiene_rejects_recognized_paths(path):
    with pytest.raises(AssertionError, match=path.split("/")[0]):
        assert_grok_project_rules_are_neutral({path})


def test_each_run_uses_a_fresh_temporary_home(tmp_path, fake_grok):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    adapter.run(AgentRunRequest(workspace, "first"))
    adapter.run(AgentRunRequest(workspace, "second"))
    homes = [
        record["environment"]["home"]
        for record in invocations(log)
        if "-p" in record["arguments"]
    ]
    assert len(homes) == 2
    assert homes[0] != homes[1]
    assert all(not Path(home).exists() for home in homes)


def test_nonzero_model_execution_maps_to_command_failed(
    tmp_path, monkeypatch, fake_grok
):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(EXIT_CODE, "7")
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt")
    )
    assert result.status is AgentRunStatus.COMMAND_FAILED
    assert result.exit_code == 7


@pytest.mark.parametrize("model", ["", "   ", " model", "model ", "two words", 1])
def test_rejects_invalid_model(model):
    with pytest.raises(AgentSetupError, match="model"):
        GrokBuildAdapter(model=model)


def test_rejects_blank_executable():
    with pytest.raises(AgentSetupError, match="executable"):
        GrokBuildAdapter(model="model-a", executable="   ")


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_rejects_invalid_workspace_before_setup(tmp_path, fake_grok, kind):
    executable, log = fake_grok
    workspace = tmp_path / kind
    if kind == "file":
        workspace.write_text("file")
    with pytest.raises(AgentSetupError, match="workspace"):
        GrokBuildAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert not log.exists()


@pytest.mark.parametrize(
    "timeout", [0, -1, float("inf"), float("nan"), True, "1"]
)
def test_rejects_invalid_timeout_before_setup(tmp_path, fake_grok, timeout):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(AgentSetupError, match="finite positive"):
        GrokBuildAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=timeout)
        )
    assert not log.exists()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_api_key_is_private_setup_error(
    tmp_path, monkeypatch, fake_grok, value
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if value is None:
        monkeypatch.delenv(API_KEY, raising=False)
    else:
        monkeypatch.setenv(API_KEY, value)
    with pytest.raises(
        AgentSetupError, match="authentication is unavailable"
    ) as raised:
        GrokBuildAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert DUMMY_API_KEY not in str(raised.value)
    assert not log.exists()


def test_missing_executable_is_setup_error(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(API_KEY, DUMMY_API_KEY)
    adapter = GrokBuildAdapter(model="model-a", executable=tmp_path / "missing")
    with pytest.raises(AgentSetupError, match="version preflight"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None


def test_temporary_home_creation_failure_is_infrastructure_error(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail_temporary_home(*args, **kwargs):
        raise OSError("simulated temporary home failure")

    monkeypatch.setattr(
        grok_build_module,
        "TemporaryDirectory",
        fail_temporary_home,
    )
    with pytest.raises(AgentInfrastructureError, match="isolated Grok Build home"):
        GrokBuildAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt")
        )
    assert not log.exists()


@pytest.mark.parametrize(
    "mode,match",
    [
        ("nonzero", "exit code 4"),
        ("reject-no-auto-update", "exit code 4"),
        ("reject-no-memory", "exit code 4"),
        ("blank", "canonical version"),
    ],
)
def test_version_preflight_failures_are_setup_errors(
    tmp_path, monkeypatch, fake_grok, mode, match
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_MODE, mode)
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match=match):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None
    assert [item["arguments"] for item in invocations(log)] == [VERSION_ARGUMENTS]
    assert not Path(invocations(log)[0]["environment"]["home"]).exists()


@pytest.mark.parametrize(
    "mode,match",
    [
        ("nonzero", "exit code 5"),
        ("missing", "required flags"),
        ("missing-verbatim", "required flags"),
    ],
)
def test_help_preflight_failures_are_setup_errors(
    tmp_path, monkeypatch, fake_grok, mode, match
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(HELP_MODE, mode)
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentSetupError, match=match):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version is None
    records = invocations(log)
    assert [item["arguments"] for item in records] == [
        VERSION_ARGUMENTS,
        ["--help"],
    ]
    assert not Path(records[0]["environment"]["home"]).exists()


def test_execution_start_failure_after_preflight_is_infrastructure_error(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(DELETE_AFTER_HELP, "1")
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    with pytest.raises(AgentInfrastructureError, match="start Grok Build"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
    assert adapter.cli_version == "grok build 0.9.0 (test)"
    records = invocations(log)
    assert [item["arguments"] for item in records] == [
        VERSION_ARGUMENTS,
        ["--help"],
    ]
    assert not Path(records[0]["environment"]["home"]).exists()


@pytest.mark.parametrize(
    "sleep_variable,timeout_seconds,expected_invocations,match",
    [
        (VERSION_SLEEP, 0.05, [VERSION_ARGUMENTS], "version preflight exceeded"),
        (
            HELP_SLEEP,
            0.15,
            [VERSION_ARGUMENTS, ["--help"]],
            "help preflight exceeded",
        ),
    ],
)
def test_preflight_is_bounded_by_agent_timeout(
    tmp_path, monkeypatch, fake_grok, sleep_variable, timeout_seconds,
    expected_invocations, match
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(sleep_variable, "0.2")
    with pytest.raises(AgentSetupError, match=match):
        GrokBuildAdapter(model="model-a", executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=timeout_seconds)
        )
    assert [item["arguments"] for item in invocations(log)] == expected_invocations


def test_preflight_consumes_model_timeout_budget(tmp_path, monkeypatch, fake_grok):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.25")
    monkeypatch.setenv(SLEEP, "0.5")
    monkeypatch.setenv(PRE_TIMEOUT_OUTPUT, "1")
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.65)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == '{"partial":true}\n'
    assert [item["arguments"] for item in invocations(log)][-1] == model_arguments(
        workspace, "prompt"
    )


def test_none_timeout_allows_preflight_and_execution(
    tmp_path, monkeypatch, fake_grok
):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(VERSION_SLEEP, "0.02")
    monkeypatch.setenv(HELP_SLEEP, "0.02")
    monkeypatch.setenv(SLEEP, "0.02")
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=None)
    )
    assert result.status is AgentRunStatus.COMPLETED
    assert result.duration_seconds >= 0.05


def test_timeout_returns_output_and_removes_temporary_home(
    tmp_path, monkeypatch, fake_grok
):
    executable, log = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(PRE_TIMEOUT_OUTPUT, "1")
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.5)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == '{"partial":true}\n'
    assert result.stderr == "diagnostic before timeout\n"
    assert not Path(invocations(log)[-1]["environment"]["home"]).exists()


def test_timeout_uses_sigkill_fallback(tmp_path, monkeypatch, fake_grok):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(IGNORE_TERM, "1")
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.5)
    )
    assert result.status is AgentRunStatus.TIMED_OUT


def test_timeout_stops_descendant_process(tmp_path, monkeypatch, fake_grok):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "survived"
    started = tmp_path / "child-started"
    monkeypatch.setenv(SLEEP, "1")
    monkeypatch.setenv(CHILD_SENTINEL, str(sentinel))
    monkeypatch.setenv(CHILD_STARTED, str(started))
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt", timeout_seconds=0.5)
    )
    assert result.status is AgentRunStatus.TIMED_OUT
    assert started.read_text() == "started"
    time.sleep(1.1)
    assert not sentinel.exists()


def test_normal_exit_stops_leftover_descendant(tmp_path, monkeypatch, fake_grok):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "survived"
    started = tmp_path / "child-started"
    monkeypatch.setenv(CHILD_SENTINEL, str(sentinel))
    monkeypatch.setenv(CHILD_STARTED, str(started))
    result = GrokBuildAdapter(model="model-a", executable=executable).run(
        AgentRunRequest(workspace, "prompt")
    )
    assert result.status is AgentRunStatus.COMPLETED
    assert started.read_text() == "started"
    time.sleep(1.1)
    assert not sentinel.exists()


def test_cleanup_failure_is_infrastructure_error(tmp_path, monkeypatch, fake_grok):
    executable, _ = fake_grok
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = GrokBuildAdapter(model="model-a", executable=executable)
    monkeypatch.setattr(adapter, "_process_group_exists", lambda process_id: True)

    def fail_cleanup(process):
        raise AgentInfrastructureError("simulated cleanup failure")

    monkeypatch.setattr(adapter, "_terminate_process_group", fail_cleanup)
    monkeypatch.setattr(adapter, "_force_cleanup", lambda process: "forced cleanup failed")
    with pytest.raises(AgentInfrastructureError, match="clean up Grok Build"):
        adapter.run(AgentRunRequest(workspace, "prompt"))
