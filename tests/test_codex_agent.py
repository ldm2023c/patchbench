import json
import os
from pathlib import Path, PurePosixPath
import secrets
import signal
import subprocess
import sys
from textwrap import dedent
import time

import pytest

import patchbench.agents.codex as codex_module
from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentRunRequest,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.agents.codex import CodexAdapter
from scripts.prepare_pilot_fixtures import template_files
from scripts.v13_candidate_manifest import load_candidate_manifest


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
_VERSION_SLEEP_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_VERSION_SLEEP"
_VERSION_OUTPUT_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_VERSION_OUTPUT"
_LOGIN_SLEEP_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_LOGIN_SLEEP"
_HELP_SLEEP_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_HELP_SLEEP"
_HELP_MODE_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_HELP_MODE"
_DELETE_AFTER_HELP_ENVIRONMENT_VARIABLE = "PATCHBENCH_TEST_CODEX_DELETE_AFTER_HELP"
_API_KEY = "OPENAI_API_KEY"
_DUMMY_API_KEY = "  dummy-codex-relay-secret-never-log  "
_RELAY_BASE_URL = "https://ai.ailink1.com/v1"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CODEX_EXTERNAL_CONTEXT_COMPONENTS = {
    ".agents",
    ".claude-plugin",
    ".codex-plugin",
}
_AMBIENT_RELAY_VARIABLES = {
    "CODEX_CONFIG",
    "CODEX_PROFILE",
    "OPENAI_BASE_URL",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
}
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
            prompt = (
                sys.stdin.read()
                if arguments[:1] == ["exec"] and "--help" not in arguments
                else None
            )
            record = {{"arguments": arguments, "prompt": prompt}}
            codex_home = os.environ.get("CODEX_HOME")
            if codex_home is not None:
                record["relay_environment"] = {{
                    "api_key_present": bool(os.environ.get("{_API_KEY}")),
                    "home": os.environ.get("HOME"),
                    "home_exists": Path(os.environ["HOME"]).is_dir(),
                    "home_entries": sorted(
                        path.name for path in Path(os.environ["HOME"]).iterdir()
                    ),
                    "codex_home": codex_home,
                    "codex_home_exists": Path(codex_home).is_dir(),
                    "codex_home_entries": sorted(
                        path.name for path in Path(codex_home).iterdir()
                    ),
                    "ambient_present": sorted(
                        name for name in {sorted(_AMBIENT_RELAY_VARIABLES)!r}
                        if name in os.environ
                    ),
                }}
            with Path(os.environ["{_LOG_ENVIRONMENT_VARIABLE}"]).open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(json.dumps(record) + "\\n")

            if arguments == ["--version"]:
                time.sleep(float(os.environ.get(
                    "{_VERSION_SLEEP_ENVIRONMENT_VARIABLE}", "0"
                )))
                sys.stdout.write(os.environ.get(
                    "{_VERSION_OUTPUT_ENVIRONMENT_VARIABLE}",
                    "codex-cli 0.152.0\\n",
                ))
                raise SystemExit(0)

            if arguments == ["login", "status"]:
                time.sleep(float(os.environ.get(
                    "{_LOGIN_SLEEP_ENVIRONMENT_VARIABLE}", "0"
                )))
                if os.environ.get("{_AUTH_FAILURE_ENVIRONMENT_VARIABLE}") == "1":
                    print("not logged in", file=sys.stderr)
                    raise SystemExit(5)
                if os.environ.get("{_DELETE_AFTER_LOGIN_ENVIRONMENT_VARIABLE}") == "1":
                    Path(sys.argv[0]).unlink()
                print("Logged in using ChatGPT")
                raise SystemExit(0)

            if arguments == ["exec", "--help"]:
                time.sleep(float(os.environ.get(
                    "{_HELP_SLEEP_ENVIRONMENT_VARIABLE}", "0"
                )))
                mode = os.environ.get("{_HELP_MODE_ENVIRONMENT_VARIABLE}")
                if mode == "nonzero":
                    print("help failed", file=sys.stderr)
                    raise SystemExit(6)
                flags = list({_REQUIRED_EXEC_HELP_FLAGS!r})
                if mode == "missing":
                    flags.remove("--ignore-rules")
                print("\\n".join(flags))
                if os.environ.get("{_DELETE_AFTER_HELP_ENVIRONMENT_VARIABLE}") == "1":
                    Path(sys.argv[0]).unlink()
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
                        "time.sleep(1); "
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


def _assert_codex_external_context_paths_are_neutral(paths) -> None:
    for path_text in paths:
        path = PurePosixPath(path_text)
        assert not any(
            component.casefold() in _CODEX_EXTERNAL_CONTEXT_COMPONENTS
            for component in path.parts
        ), path_text


def _relay_overrides() -> list[str]:
    return [
        'model_provider="patchbench_relay"',
        'model_providers.patchbench_relay.name="PatchBench Ailink Relay"',
        'model_providers.patchbench_relay.base_url="https://ai.ailink1.com/v1"',
        'model_providers.patchbench_relay.env_key="OPENAI_API_KEY"',
        'model_providers.patchbench_relay.wire_api="responses"',
        "model_providers.patchbench_relay.requires_openai_auth=false",
        "model_providers.patchbench_relay.supports_standalone_web_search=false",
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
    ]


def _relay_arguments(workspace: Path, model: str = "gpt-5.5") -> list[str]:
    arguments = [
        "exec",
        "-C",
        str(workspace.resolve()),
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
    ]
    for override in _relay_overrides():
        arguments.extend(("-c", override))
    arguments.extend(("--json", "-m", model, "-"))
    return arguments


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
        "https://ai.ailink1.com/v1?provider=codex",
        "https://ai.ailink1.com/v1#fragment",
        "https://user@ai.ailink1.com/v1",
        1,
    ],
)
def test_codex_adapter_rejects_noncanonical_relay_base_url(relay_base_url):
    with pytest.raises(AgentSetupError, match="relay base URL"):
        CodexAdapter(model="gpt-5.5", relay_base_url=relay_base_url)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_codex_relay_requires_nonblank_api_key(
    tmp_path, monkeypatch, fake_codex, value
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if value is None:
        monkeypatch.delenv(_API_KEY, raising=False)
    else:
        monkeypatch.setenv(_API_KEY, value)

    with pytest.raises(AgentSetupError, match="relay authentication"):
        CodexAdapter(
            model="gpt-5.5",
            executable=executable,
            relay_base_url=_RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt"))

    assert not invocation_log.exists()


def test_codex_relay_exact_invocation_and_isolated_environment(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt = "修复 exactly this.\nKeep $HOME and `code`.\n"
    real_codex_home = tmp_path / "real-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    for name in _AMBIENT_RELAY_VARIABLES:
        monkeypatch.setenv(name, "ambient-relay-value")
    parent_environment = os.environ.copy()
    observed_model_environment = None
    original_popen = subprocess.Popen

    def inspect_popen(*args, **kwargs):
        nonlocal observed_model_environment
        arguments = args[0]
        if len(arguments) > 1 and arguments[1] == "exec" and "--help" not in arguments:
            observed_model_environment = kwargs.get("env")
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", inspect_popen)
    adapter = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    )
    result = adapter.run(AgentRunRequest(workspace, prompt))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == '{"type":"fake.result"}\n'
    assert result.stderr == "fake diagnostic\n"
    assert adapter.model == "gpt-5.5"
    assert adapter.relay_base_url == _RELAY_BASE_URL
    assert adapter.cli_version == "codex-cli 0.152.0"
    assert observed_model_environment is not None
    assert secrets.compare_digest(
        observed_model_environment[_API_KEY], _DUMMY_API_KEY
    )
    assert _AMBIENT_RELAY_VARIABLES.isdisjoint(observed_model_environment)
    assert observed_model_environment["PATH"] == parent_environment["PATH"]
    assert os.environ == parent_environment

    records = _read_invocations(invocation_log)
    assert [record["arguments"] for record in records] == [
        ["--version"],
        ["exec", "--help"],
        _relay_arguments(workspace),
    ]
    assert records[2]["prompt"] == prompt
    assert all(record["relay_environment"]["codex_home_exists"] for record in records)
    assert all(record["relay_environment"]["codex_home_entries"] == [] for record in records)
    assert all(record["relay_environment"]["home_exists"] for record in records)
    assert all(
        record["relay_environment"]["home_entries"] == [".codex"]
        for record in records
    )
    assert all(record["relay_environment"]["ambient_present"] == [] for record in records)
    assert records[0]["relay_environment"]["api_key_present"] is False
    assert records[1]["relay_environment"]["api_key_present"] is False
    assert records[2]["relay_environment"]["api_key_present"] is True
    isolated_home = Path(records[0]["relay_environment"]["home"])
    codex_home = Path(records[0]["relay_environment"]["codex_home"])
    assert codex_home != real_codex_home
    assert codex_home.parent == isolated_home
    assert not isolated_home.is_relative_to(workspace.resolve())
    assert not isolated_home.exists()
    serialized = invocation_log.read_text(encoding="utf-8")
    assert _DUMMY_API_KEY not in serialized
    assert _DUMMY_API_KEY not in result.stdout + result.stderr
    assert _DUMMY_API_KEY not in records[2]["arguments"]


def test_codex_relay_isolates_real_user_discovery_roots(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_home = tmp_path / "real-home"
    personal_files = {
        ".agents/skills/example/SKILL.md": "personal skill",
        ".agents/plugins/marketplace.json": "{}",
        ".claude-plugin/marketplace.json": "{}",
        ".codex/config.toml": 'model = "personal-model"',
    }
    for relative_path, content in personal_files.items():
        path = real_home / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_home / ".codex"))
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)

    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt"))

    assert result.status is AgentRunStatus.COMPLETED
    records = _read_invocations(invocation_log)
    temporary_homes = {
        record["relay_environment"]["home"] for record in records
    }
    assert len(temporary_homes) == 1
    temporary_home = Path(temporary_homes.pop())
    assert temporary_home != real_home
    assert all(
        Path(record["relay_environment"]["codex_home"]).parent == temporary_home
        for record in records
    )
    assert all(
        record["relay_environment"]["home_entries"] == [".codex"]
        for record in records
    )
    assert all(
        record["relay_environment"]["codex_home_entries"] == []
        for record in records
    )
    assert not (temporary_home / ".agents").exists()
    assert not (temporary_home / ".claude-plugin").exists()
    assert not temporary_home.exists()
    assert os.environ["HOME"] == str(real_home)
    assert os.environ["CODEX_HOME"] == str(real_home / ".codex")
    assert all((real_home / path).is_file() for path in personal_files)


def test_candidate_fixtures_have_no_codex_external_context_paths() -> None:
    candidate = load_candidate_manifest(_PROJECT_ROOT)
    assert len(candidate.tasks) == 12
    for task in candidate.tasks:
        fixture = _PROJECT_ROOT / "fixtures/reliability" / task.task_id
        tracked_template = {
            path.relative_to(fixture).as_posix()
            for path in template_files(fixture)
        }
        assert tracked_template
        _assert_codex_external_context_paths_are_neutral(tracked_template)


@pytest.mark.parametrize(
    "path",
    [
        "src/agents.py",
        "docs/skills_notes.md",
        "docs/plugin_notes.md",
        "README.md",
    ],
)
def test_codex_external_context_hygiene_allows_ordinary_paths(path) -> None:
    _assert_codex_external_context_paths_are_neutral({path})


@pytest.mark.parametrize(
    "path",
    [
        ".agents/skills/test/SKILL.md",
        ".agents/plugins/marketplace.json",
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
    ],
)
def test_codex_external_context_hygiene_rejects_discovery_roots(path) -> None:
    with pytest.raises(AssertionError, match=path.split("/")[0]):
        _assert_codex_external_context_paths_are_neutral({path})


def test_codex_relay_removes_temporary_home_after_command_failure(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_EXIT_CODE_ENVIRONMENT_VARIABLE, "7")
    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt"))

    assert result.status is AgentRunStatus.COMMAND_FAILED
    home = Path(_read_invocations(invocation_log)[0]["relay_environment"]["codex_home"])
    assert not home.exists()


def test_each_codex_relay_run_uses_a_fresh_temporary_home(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    adapter = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    )
    adapter.run(AgentRunRequest(workspace, "first"))
    adapter.run(AgentRunRequest(workspace, "second"))

    homes = [
        record["relay_environment"]["codex_home"]
        for record in _read_invocations(invocation_log)
        if record["arguments"] == _relay_arguments(workspace)
    ]
    assert len(homes) == 2
    assert homes[0] != homes[1]
    assert all(not Path(home).exists() for home in homes)


@pytest.mark.parametrize("mode", ["nonzero", "missing"])
def test_codex_relay_help_failure_removes_temporary_home(
    tmp_path, monkeypatch, fake_codex, mode
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_HELP_MODE_ENVIRONMENT_VARIABLE, mode)
    with pytest.raises(AgentSetupError, match="exec help|required relay flags"):
        CodexAdapter(
            model="gpt-5.5",
            executable=executable,
            relay_base_url=_RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt"))

    records = _read_invocations(invocation_log)
    assert [record["arguments"] for record in records] == [
        ["--version"],
        ["exec", "--help"],
    ]
    assert all(record["relay_environment"]["api_key_present"] is False for record in records)
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


def test_codex_relay_start_error_removes_home_without_disclosing_secret(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_DELETE_AFTER_HELP_ENVIRONMENT_VARIABLE, "1")
    with pytest.raises(AgentInfrastructureError, match="start Codex agent") as raised:
        CodexAdapter(
            model="gpt-5.5",
            executable=executable,
            relay_base_url=_RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt"))

    records = _read_invocations(invocation_log)
    assert _DUMMY_API_KEY not in str(raised.value)
    assert _DUMMY_API_KEY not in invocation_log.read_text(encoding="utf-8")
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


def test_codex_relay_temporary_home_creation_failure_is_infrastructure_error(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)

    def fail_temporary_home(*args, **kwargs):
        raise OSError("simulated temporary home failure")

    monkeypatch.setattr(codex_module, "TemporaryDirectory", fail_temporary_home)
    with pytest.raises(AgentInfrastructureError, match="isolated Codex home"):
        CodexAdapter(
            model="gpt-5.5",
            executable=executable,
            relay_base_url=_RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt"))
    assert not invocation_log.exists()


def test_codex_version_preflight_is_bounded_by_full_deadline(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_VERSION_SLEEP_ENVIRONMENT_VARIABLE, "1.0")
    with pytest.raises(AgentSetupError, match="version preflight exceeded"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=0.3)
        )
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"]
    ]


def test_codex_direct_login_preflight_is_bounded_by_full_deadline(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_LOGIN_SLEEP_ENVIRONMENT_VARIABLE, "0.2")
    with pytest.raises(AgentSetupError, match="login status preflight exceeded"):
        CodexAdapter(model="test-model", executable=executable).run(
            AgentRunRequest(workspace, "prompt", timeout_seconds=0.15)
        )
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
    ]


def test_codex_relay_help_preflight_is_bounded_and_removes_home(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_HELP_SLEEP_ENVIRONMENT_VARIABLE, "1.0")
    with pytest.raises(AgentSetupError, match="exec help preflight exceeded"):
        CodexAdapter(
            model="gpt-5.5",
            executable=executable,
            relay_base_url=_RELAY_BASE_URL,
        ).run(AgentRunRequest(workspace, "prompt", timeout_seconds=0.3))
    records = _read_invocations(invocation_log)
    assert [record["arguments"] for record in records] == [
        ["--version"],
        ["exec", "--help"],
    ]
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


def test_codex_relay_preflight_consumes_model_timeout_budget(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_VERSION_SLEEP_ENVIRONMENT_VARIABLE, "0.15")
    monkeypatch.setenv(_HELP_SLEEP_ENVIRONMENT_VARIABLE, "0.15")
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setenv(_PRE_TIMEOUT_OUTPUT_ENVIRONMENT_VARIABLE, "1")
    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt", timeout_seconds=1.2))

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == "stdout before timeout\n"
    records = _read_invocations(invocation_log)
    assert records[-1]["arguments"] == _relay_arguments(workspace)
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


def test_codex_relay_none_timeout_allows_preflight_and_model(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, _ = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_VERSION_SLEEP_ENVIRONMENT_VARIABLE, "0.02")
    monkeypatch.setenv(_HELP_SLEEP_ENVIRONMENT_VARIABLE, "0.02")
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "0.02")
    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt", timeout_seconds=None))
    assert result.status is AgentRunStatus.COMPLETED
    assert result.duration_seconds >= 0.05


def test_codex_relay_timeout_stops_child_before_home_cleanup(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "relay-timeout-child-survived.txt"
    child_started = tmp_path / "relay-timeout-child-started.txt"
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_EXEC_SLEEP_ENVIRONMENT_VARIABLE, "1")
    monkeypatch.setenv(_CHILD_SENTINEL_ENVIRONMENT_VARIABLE, str(sentinel))
    monkeypatch.setenv(_CHILD_STARTED_ENVIRONMENT_VARIABLE, str(child_started))
    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt", timeout_seconds=0.6))

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(1.1)
    assert not sentinel.exists()
    records = _read_invocations(invocation_log)
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


def test_codex_relay_normal_completion_stops_descendant_before_home_cleanup(
    tmp_path, monkeypatch, fake_codex
) -> None:
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "relay-normal-child-survived.txt"
    child_started = tmp_path / "relay-normal-child-started.txt"
    monkeypatch.setenv(_API_KEY, _DUMMY_API_KEY)
    monkeypatch.setenv(_CHILD_SENTINEL_ENVIRONMENT_VARIABLE, str(sentinel))
    monkeypatch.setenv(_CHILD_STARTED_ENVIRONMENT_VARIABLE, str(child_started))
    monkeypatch.setenv(_EXIT_AFTER_CHILD_ENVIRONMENT_VARIABLE, "1")
    result = CodexAdapter(
        model="gpt-5.5",
        executable=executable,
        relay_base_url=_RELAY_BASE_URL,
    ).run(AgentRunRequest(workspace, "prompt"))

    assert result.status is AgentRunStatus.COMPLETED
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(1.1)
    assert not sentinel.exists()
    records = _read_invocations(invocation_log)
    assert not Path(records[0]["relay_environment"]["codex_home"]).exists()


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
        AgentRunRequest(workspace, "Wait for timeout.", timeout_seconds=0.5)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert result.stdout == "stdout before timeout\n"
    assert result.stderr == "stderr before timeout\n"
    assert result.duration_seconds >= 0.1
    assert time.monotonic() - started < 2


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
        AgentRunRequest(workspace, "Spawn a child.", timeout_seconds=0.5)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert child_started.read_text(encoding="utf-8") == "started"
    time.sleep(1.1)
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
    time.sleep(1.1)
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
    time.sleep(1.1)
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
        AgentRunRequest(workspace, "Exit on SIGTERM.", timeout_seconds=0.5)
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
        AgentRunRequest(workspace, "Ignore SIGTERM.", timeout_seconds=0.5)
    )

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.exit_code is None
    assert time.monotonic() - started < 2
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
            AgentRunRequest(workspace, "Fail termination.", timeout_seconds=0.5)
        )

    assert signal_calls[0][1] == signal.SIGTERM
    assert any(signal_number == signal.SIGKILL for _, signal_number in signal_calls)
    assert len({process_group_id for process_group_id, _ in signal_calls}) == 1


def test_codex_expected_cli_version_exact_match_allows_run(tmp_path, fake_codex):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    adapter = CodexAdapter(
        model="test-model",
        executable=executable,
        expected_cli_version="codex-cli 0.152.0",
    )
    result = adapter.run(AgentRunRequest(workspace, "fix"))

    assert result.status is AgentRunStatus.COMPLETED
    assert adapter.expected_cli_version == "codex-cli 0.152.0"
    assert adapter.cli_version == "codex-cli 0.152.0"
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
        ["exec", "-C", str(workspace.resolve()), "--sandbox", "workspace-write",
         "--ephemeral", "--ignore-user-config", "--json", "-m", "test-model", "-"],
    ]


def test_codex_expected_cli_version_mismatch_stops_before_login_or_model(
    tmp_path, fake_codex
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CodexAdapter(
        model="test-model",
        executable=executable,
        expected_cli_version="codex-cli 0.153.4",
    )

    with pytest.raises(AgentSetupError, match="version mismatch"):
        adapter.run(AgentRunRequest(workspace, "fix"))

    assert adapter.cli_version is None
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
    ]


@pytest.mark.parametrize("expected", ["", " codex-cli 0.152.0", "codex-cli 0.152.0\n", 123])
def test_codex_rejects_invalid_expected_cli_version(expected):
    with pytest.raises(AgentSetupError, match="expected CLI version"):
        CodexAdapter(model="test-model", expected_cli_version=expected)  # type: ignore[arg-type]


def test_codex_expected_frozen_cli_version_exact_newline_succeeds(
    tmp_path, monkeypatch, fake_codex
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(
        _VERSION_OUTPUT_ENVIRONMENT_VARIABLE, "codex-cli 0.153.4\n"
    )

    adapter = CodexAdapter(
        model="test-model",
        executable=executable,
        expected_cli_version="codex-cli 0.153.4",
    )
    result = adapter.run(AgentRunRequest(workspace, "fix"))

    assert result.status is AgentRunStatus.COMPLETED
    assert adapter.cli_version == "codex-cli 0.153.4"
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
        ["exec", "-C", str(workspace.resolve()), "--sandbox", "workspace-write",
         "--ephemeral", "--ignore-user-config", "--json", "-m", "test-model", "-"],
    ]


def test_codex_expected_frozen_cli_version_mismatch_stops_before_later_preflight(
    tmp_path, monkeypatch, fake_codex
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(
        _VERSION_OUTPUT_ENVIRONMENT_VARIABLE, "codex-cli 0.153.5\n"
    )
    adapter = CodexAdapter(
        model="test-model",
        executable=executable,
        expected_cli_version="codex-cli 0.153.4",
    )

    with pytest.raises(AgentSetupError, match="version mismatch"):
        adapter.run(AgentRunRequest(workspace, "fix"))

    assert adapter.cli_version is None
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
    ]


@pytest.mark.parametrize(
    "observed",
    [
        " codex-cli 0.153.4\n",
        "codex-cli 0.153.4 \n",
        "codex-cli 0.153.4\x1f\n",
    ],
)
def test_codex_observed_cli_version_must_be_canonical_text(
    tmp_path, monkeypatch, fake_codex, observed
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(_VERSION_OUTPUT_ENVIRONMENT_VARIABLE, observed)
    adapter = CodexAdapter(
        model="test-model",
        executable=executable,
        expected_cli_version="codex-cli 0.153.4",
    )

    with pytest.raises(AgentSetupError, match="canonical version"):
        adapter.run(AgentRunRequest(workspace, "fix"))

    assert adapter.cli_version is None
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
    ]


def test_codex_legacy_expected_cli_version_none_accepts_canonical_observed_version(
    tmp_path, monkeypatch, fake_codex
):
    executable, invocation_log = fake_codex
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(
        _VERSION_OUTPUT_ENVIRONMENT_VARIABLE, "codex-cli 0.153.4\n"
    )
    adapter = CodexAdapter(model="test-model", executable=executable)

    result = adapter.run(AgentRunRequest(workspace, "fix"))

    assert result.status is AgentRunStatus.COMPLETED
    assert adapter.expected_cli_version is None
    assert adapter.cli_version == "codex-cli 0.153.4"
    assert [record["arguments"] for record in _read_invocations(invocation_log)] == [
        ["--version"],
        ["login", "status"],
        ["exec", "-C", str(workspace.resolve()), "--sandbox", "workspace-write",
         "--ephemeral", "--ignore-user-config", "--json", "-m", "test-model", "-"],
    ]
