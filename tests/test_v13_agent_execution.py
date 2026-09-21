import json
from pathlib import Path

import pytest

import patchbench.application.v13_agent_execution as v13_execution
from patchbench.agents import CodexAdapter, CursorCliAdapter, GrokBuildAdapter
from patchbench.domain import (
    AgentConfigurationManifest,
    AgentConfigurationOption,
    AgentIdentityBinding,
    AgentToolchain,
    ExperimentAggregate,
    ExperimentRecord,
    compute_agent_configuration_manifest_sha256,
    compute_agent_configuration_sha256,
)
from patchbench.application.v13_agent_execution import (
    ACCEPTED_M8_AGENT_MANIFEST_SHA256,
    FrozenAgentResolutionError,
    _derive_v13_agent_execution_plan,
    load_v13_agent_manifest,
    resolve_v13_agent_config,
    run_v13_agent_experiment,
)


EXPECTED = {
    "codex-gpt-5.5-relay": {
        "toolchain": AgentToolchain.CODEX,
        "agent_name": "codex",
        "model": "gpt-5.5",
        "timeout": 600,
        "runtime": "codex-cli 0.153.4",
        "config_sha": "36e25acabc2589ac75c80f514ff9066274751584f425c9c5b3f85e994a090cb0",
        "options": {"relay_base_url": "https://ai.ailink1.com/v1"},
        "adapter": CodexAdapter,
    },
    "cursor-claude-4.6-sonnet-medium": {
        "toolchain": AgentToolchain.CURSOR_CLI,
        "agent_name": "cursor_cli",
        "model": "claude-4.6-sonnet-medium",
        "timeout": 600,
        "runtime": "2026.09.18-9a7762b",
        "config_sha": "04db98cadc7b642bd85b4fdac1d19901f38b91cde9835c319b014203c47f5a21",
        "options": {"endpoint": "https://api2.cursor.sh"},
        "adapter": CursorCliAdapter,
    },
    "grok-build-grok-4.5-relay": {
        "toolchain": AgentToolchain.GROK_BUILD,
        "agent_name": "grok_build",
        "model": "grok-4.5",
        "timeout": 600,
        "runtime": "grok 1.0.34 (3736acbc8658)",
        "config_sha": "e30b70a175e20fd893fd1ea8689a35339d3bd795ba2e2bb271979ed111e5a838",
        "options": {
            "relay_base_url": "https://ai.ailink1.com/v1",
            "relay_context_window": 500000,
        },
        "adapter": GrokBuildAdapter,
    },
}


def checked_manifest() -> AgentConfigurationManifest:
    return load_v13_agent_manifest(Path.cwd())


def test_accepted_manifest_loads_with_exact_semantic_sha():
    manifest = checked_manifest()

    assert compute_agent_configuration_manifest_sha256(manifest) == (
        ACCEPTED_M8_AGENT_MANIFEST_SHA256
    )
    assert tuple(EXPECTED) == tuple(config.config_id for config in manifest.configurations)


@pytest.mark.parametrize("config_id", tuple(EXPECTED))
def test_all_frozen_config_ids_resolve_exact_execution_plan(config_id):
    expected = EXPECTED[config_id]

    plan = resolve_v13_agent_config(config_id, evaluation_backend="host")

    assert plan.configuration.config_id == config_id
    assert plan.configuration.toolchain is expected["toolchain"]
    assert plan.configuration.requested_model == expected["model"]
    assert plan.configuration.agent_timeout_seconds == expected["timeout"]
    assert {option.name: option.value for option in plan.configuration.toolchain_options} == (
        expected["options"]
    )
    assert plan.runtime_identity.cli_version == expected["runtime"]
    assert plan.runtime_identity.agent_config_sha256 == expected["config_sha"]
    assert compute_agent_configuration_sha256(plan.configuration) == expected["config_sha"]
    assert plan.identity_binding == AgentIdentityBinding(
        manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        config_id=config_id,
        config_sha256=expected["config_sha"],
    )
    assert plan.experiment_configuration.agent_name == expected["agent_name"]
    assert plan.experiment_configuration.requested_model == expected["model"]
    assert plan.experiment_configuration.agent_timeout_seconds == expected["timeout"]
    assert plan.experiment_configuration.evaluation_backend == "host"
    assert plan.experiment_configuration.identity_binding == plan.identity_binding

    first = plan.agent_factory()
    second = plan.agent_factory()
    assert first is not second
    assert isinstance(first, expected["adapter"])
    assert first.model == expected["model"]
    assert first.expected_cli_version == expected["runtime"]
    if isinstance(first, CodexAdapter):
        assert first.relay_base_url == expected["options"]["relay_base_url"]
    elif isinstance(first, CursorCliAdapter):
        assert first.endpoint == expected["options"]["endpoint"]
    elif isinstance(first, GrokBuildAdapter):
        assert first.relay_base_url == expected["options"]["relay_base_url"]
        assert first.relay_context_window == expected["options"]["relay_context_window"]
    else:  # pragma: no cover
        pytest.fail(f"unexpected adapter {type(first)}")


def test_unknown_config_and_claude_code_selection_reject():
    with pytest.raises(FrozenAgentResolutionError, match="Unknown frozen"):
        resolve_v13_agent_config("does-not-exist", evaluation_backend="host")
    with pytest.raises(FrozenAgentResolutionError, match="Unknown frozen"):
        resolve_v13_agent_config("claude-code-claude-sonnet-4-6", evaluation_backend="host")


def test_no_runtime_fallback_occurs_for_claude_fallback_record():
    manifest = checked_manifest()
    assert manifest.fallback_provenance[0].selected_replacement_config_id == (
        "cursor-claude-4.6-sonnet-medium"
    )

    with pytest.raises(FrozenAgentResolutionError, match="Unknown frozen"):
        resolve_v13_agent_config(
            manifest.fallback_provenance[0].intended_model,
            evaluation_backend="host",
        )


def test_semantically_drifted_manifest_rejects(tmp_path):
    source = Path("tasks/reliability/v1.3-agent-configurations.json")
    target = tmp_path / source
    target.parent.mkdir(parents=True)
    manifest = checked_manifest()
    drifted_config = manifest.configurations[0].model_copy(
        update={"requested_model": "gpt-5.5-drift"}
    )
    drifted_runtime = manifest.runtime_identities[0].model_copy(
        update={
            "agent_config_sha256": compute_agent_configuration_sha256(
                drifted_config
            )
        }
    )
    manifest = manifest.model_copy(
        update={
            "configurations": (drifted_config, *manifest.configurations[1:]),
            "runtime_identities": (drifted_runtime, *manifest.runtime_identities[1:]),
        }
    )
    target.write_text(
        json.dumps(manifest.model_dump(mode="json")), encoding="utf-8"
    )

    with pytest.raises(FrozenAgentResolutionError, match="semantic SHA mismatch"):
        resolve_v13_agent_config(
            "codex-gpt-5.5-relay",
            evaluation_backend="host",
            project_root=tmp_path,
        )


def test_missing_runtime_identity_rejects():
    manifest = checked_manifest()
    manifest = manifest.model_copy(update={"runtime_identities": manifest.runtime_identities[1:]})

    with pytest.raises(FrozenAgentResolutionError, match="exactly one runtime identity"):
        _derive_v13_agent_execution_plan(
            manifest,
            config_id="codex-gpt-5.5-relay",
            evaluation_backend="host",
            manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        )


def test_runtime_config_linkage_rejects():
    manifest = checked_manifest()
    bad_runtime = manifest.runtime_identities[0].model_copy(
        update={"agent_config_sha256": "0" * 64}
    )
    manifest = manifest.model_copy(
        update={"runtime_identities": (bad_runtime, *manifest.runtime_identities[1:])}
    )

    with pytest.raises(FrozenAgentResolutionError, match="configuration SHA mismatch"):
        _derive_v13_agent_execution_plan(
            manifest,
            config_id="codex-gpt-5.5-relay",
            evaluation_backend="host",
            manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        )


@pytest.mark.parametrize(
    ("config_id", "options", "message"),
    [
        ("codex-gpt-5.5-relay", (), "missing required"),
        (
            "codex-gpt-5.5-relay",
            (AgentConfigurationOption(name="relay_base_url", value="https://ai.ailink1.com/v1"),
             AgentConfigurationOption(name="unexpected", value="x")),
            "unexpected option",
        ),
        (
            "cursor-claude-4.6-sonnet-medium",
            (AgentConfigurationOption(name="endpoint", value=1),),
            "must be a string",
        ),
        (
            "grok-build-grok-4.5-relay",
            (AgentConfigurationOption(name="relay_base_url", value="https://ai.ailink1.com/v1"),
             AgentConfigurationOption(name="relay_context_window", value="500000")),
            "positive integer",
        ),
    ],
)
def test_toolchain_option_contract_rejects_missing_unexpected_or_wrong_type(
    config_id, options, message
):
    manifest = checked_manifest()
    configurations = []
    for configuration in manifest.configurations:
        if configuration.config_id == config_id:
            configuration = configuration.model_copy(update={"toolchain_options": options})
        configurations.append(configuration)
    manifest = manifest.model_copy(update={"configurations": tuple(configurations)})

    with pytest.raises(FrozenAgentResolutionError, match=message):
        _derive_v13_agent_execution_plan(
            manifest,
            config_id=config_id,
            evaluation_backend="host",
            manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        ).agent_factory()


def test_unsupported_selected_toolchain_rejects():
    manifest = checked_manifest()
    bad_config = manifest.configurations[0].model_copy(
        update={"toolchain": AgentToolchain.CLAUDE_CODE}
    )
    bad_runtime = manifest.runtime_identities[0].model_copy(
        update={"toolchain": AgentToolchain.CLAUDE_CODE}
    )
    manifest = manifest.model_copy(
        update={
            "configurations": (bad_config, *manifest.configurations[1:]),
            "runtime_identities": (bad_runtime, *manifest.runtime_identities[1:]),
        }
    )

    with pytest.raises(FrozenAgentResolutionError, match="Unsupported"):
        _derive_v13_agent_execution_plan(
            manifest,
            config_id="codex-gpt-5.5-relay",
            evaluation_backend="host",
            manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        ).agent_factory()


def test_run_v13_agent_experiment_passes_exact_frozen_configuration(monkeypatch, tmp_path):
    captured = {}

    def fake_run_experiment(
        task_path,
        *,
        requested_runs,
        configuration,
        agent_factory,
        workspace_root=None,
        results_root=None,
        sandbox=None,
    ):
        captured["task_path"] = task_path
        captured["requested_runs"] = requested_runs
        captured["configuration"] = configuration
        captured["agents"] = (agent_factory(), agent_factory())
        captured["workspace_root"] = workspace_root
        captured["results_root"] = results_root
        captured["sandbox"] = sandbox
        binding = configuration.identity_binding
        assert binding is not None
        child_bindings = (binding, binding)
        captured["child_bindings"] = child_bindings
        return ExperimentRecord(
            experiment_id="experiment",
            task_id="task",
            requested_runs=requested_runs,
            run_ids=["run-1", "run-2"],
            configuration=configuration,
            aggregate=ExperimentAggregate(
                run_count=2,
                evaluation_pass_count=2,
                evaluation_fail_count=0,
                evaluation_pass_rate=1.0,
                agent_command_failure_count=0,
                agent_timeout_count=0,
                total_duration_seconds=2.0,
                mean_duration_seconds=1.0,
                min_duration_seconds=1.0,
                max_duration_seconds=1.0,
            ),
            duration_seconds=2.0,
        )

    monkeypatch.setattr(v13_execution, "run_experiment", fake_run_experiment)

    record = run_v13_agent_experiment(
        tmp_path / "task.yaml",
        config_id="cursor-claude-4.6-sonnet-medium",
        requested_runs=2,
        evaluation_backend="docker",
        workspace_root=tmp_path / "workspaces",
        results_root=tmp_path / "results",
        sandbox=object(),  # type: ignore[arg-type]
    )

    configuration = captured["configuration"]
    assert record.configuration == configuration
    assert configuration.agent_name == "cursor_cli"
    assert configuration.requested_model == "claude-4.6-sonnet-medium"
    assert configuration.agent_timeout_seconds == 600
    assert configuration.evaluation_backend == "docker"
    assert configuration.identity_binding == AgentIdentityBinding(
        manifest_sha256=ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        config_id="cursor-claude-4.6-sonnet-medium",
        config_sha256=EXPECTED["cursor-claude-4.6-sonnet-medium"]["config_sha"],
    )
    assert captured["child_bindings"] == (
        configuration.identity_binding,
        configuration.identity_binding,
    )
    assert captured["agents"][0] is not captured["agents"][1]
    assert all(isinstance(agent, CursorCliAdapter) for agent in captured["agents"])
