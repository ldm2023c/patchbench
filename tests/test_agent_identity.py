"""V1.3 M4 Agent execution-policy and semantic identity contracts."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.domain import (
    AgentConfigurationIdentity,
    AgentConfigurationManifest,
    AgentConfigurationOption,
    AgentExecutionPolicy,
    AgentRuntimeIdentity,
    AgentToolchain,
    compute_agent_configuration_sha256,
    compute_agent_execution_policy_sha256,
)
from scripts.prepare_pilot_fixtures import template_files
from scripts.v13_candidate_manifest import load_candidate_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "tasks/reliability/v1.3-agent-policy.json"
EXPECTED_AGENT_POLICY_SHA256 = "c17f5e7ff825e8fbc455c3a649b1288083aea4580bcdccd1c78c8a707c50eb00"


def policy_data():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def policy():
    return AgentExecutionPolicy.model_validate(policy_data())


def configuration_data(**changes):
    data = {
        "schema_version": 1,
        "config_id": "codex-primary",
        "toolchain": "codex",
        "requested_model": "model-a",
        "agent_timeout_seconds": 600,
        "execution_policy_sha256": EXPECTED_AGENT_POLICY_SHA256,
        "toolchain_options": [
            {"name": "reasoning_effort", "value": "high"},
            {"name": "structured_output", "value": True},
        ],
    }
    data.update(changes)
    return data


def config(**changes):
    return AgentConfigurationIdentity.model_validate(configuration_data(**changes))


def test_checked_policy_validates_and_has_anchored_semantic_identity(policy):
    assert policy.schema_version == 1
    assert policy.policy_id == "isolated-headless-v1"
    assert compute_agent_execution_policy_sha256(policy) == EXPECTED_AGENT_POLICY_SHA256
    raw = POLICY_PATH.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert json.dumps(policy.model_dump(mode="json"), indent=2).encode() + b"\n" == raw
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == EXPECTED_AGENT_POLICY_SHA256


def test_policy_semantic_change_changes_hash(policy):
    changed = policy_data()
    changed["process_tree_cleanup"] = False
    changed_policy = AgentExecutionPolicy.model_validate(changed)
    assert compute_agent_execution_policy_sha256(changed_policy) != compute_agent_execution_policy_sha256(policy)


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"schema_version": "1"},
        {"headless_execution": 1},
        {"extensions": {"mcp": "required_where_supported"}},
    ],
)
def test_policy_rejects_extra_or_wrongly_typed_fields(change):
    data = policy_data()
    data.update(change)
    with pytest.raises(ValidationError):
        AgentExecutionPolicy.model_validate(data)


def test_recognized_toolchains_are_exact():
    assert tuple(toolchain.value for toolchain in AgentToolchain) == (
        "codex", "claude_code", "grok_build", "cursor_cli"
    )


def test_valid_agent_configuration_and_scalar_options():
    identity = config(toolchain_options=[
        {"name": "attempt_limit", "value": 3},
        {"name": "reasoning_effort", "value": "high"},
        {"name": "structured_output", "value": True},
    ])
    assert identity.toolchain is AgentToolchain.CODEX
    assert [option.value for option in identity.toolchain_options] == [3, "high", True]


@pytest.mark.parametrize("config_id", ["", " padded", "UPPER", "contains space"])
def test_configuration_rejects_invalid_config_id(config_id):
    with pytest.raises(ValidationError):
        config(config_id=config_id)


def test_configuration_rejects_unknown_toolchain():
    with pytest.raises(ValidationError):
        config(toolchain="other")


@pytest.mark.parametrize("model", ["", " model-a", "model-a ", "\n"])
def test_configuration_rejects_blank_or_padded_model(model):
    with pytest.raises(ValidationError):
        config(requested_model=model)


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), "600"])
def test_configuration_rejects_invalid_timeout(timeout):
    with pytest.raises(ValidationError):
        config(agent_timeout_seconds=timeout)


def test_configuration_rejects_malformed_policy_sha():
    with pytest.raises(ValidationError):
        config(execution_policy_sha256="bad")


def test_configuration_rejects_duplicate_or_noncanonical_options():
    duplicate = [{"name": "mode", "value": "a"}, {"name": "mode", "value": "b"}]
    reversed_options = [
        {"name": "structured_output", "value": True},
        {"name": "reasoning_effort", "value": "high"},
    ]
    with pytest.raises(ValidationError, match="unique"):
        config(toolchain_options=duplicate)
    with pytest.raises(ValidationError, match="canonical name order"):
        config(toolchain_options=reversed_options)


@pytest.mark.parametrize("value", [None, 1.5, ["high"], {"level": "high"}])
def test_configuration_rejects_unsupported_option_value_shapes(value):
    with pytest.raises(ValidationError):
        config(toolchain_options=[{"name": "reasoning_effort", "value": value}])


def test_configuration_rejects_extra_fields_and_secret_options():
    with pytest.raises(ValidationError):
        config(extra=True)
    with pytest.raises(ValidationError, match="credentials and secrets"):
        config(toolchain_options=[{"name": "api_key", "value": "secret-value"}])


def test_configuration_hash_is_stable_and_sensitive_to_all_semantics():
    baseline = config()
    baseline_hash = compute_agent_configuration_sha256(baseline)
    assert compute_agent_configuration_sha256(
        AgentConfigurationIdentity.model_validate(baseline.model_dump(mode="json"))
    ) == baseline_hash
    reversed_input = dict(reversed(list(configuration_data().items())))
    assert compute_agent_configuration_sha256(
        AgentConfigurationIdentity.model_validate(reversed_input)
    ) == baseline_hash
    canonical = json.dumps(
        baseline.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == baseline_hash
    changes = [
        {"config_id": "codex-secondary"},
        {"toolchain": "claude_code"},
        {"requested_model": "model-b"},
        {"agent_timeout_seconds": 601},
        {"execution_policy_sha256": "b" * 64},
        {"toolchain_options": [{"name": "reasoning_effort", "value": "low"}]},
        {"toolchain_options": [{"name": "other_option", "value": "high"}]},
    ]
    assert all(compute_agent_configuration_sha256(config(**change)) != baseline_hash for change in changes)
    assert not any("path" in name or "host" in name or "credential" in name
                   for name in AgentConfigurationIdentity.model_fields)


def test_configuration_manifest_requires_one_policy_and_canonical_unique_ids():
    first = config(config_id="claude-primary", toolchain="claude_code", toolchain_options=[])
    second = config()
    manifest = AgentConfigurationManifest(
        schema_version=1,
        policy_sha256=EXPECTED_AGENT_POLICY_SHA256,
        configurations=(first, second),
    )
    assert manifest.configurations == (first, second)
    with pytest.raises(ValidationError, match="unique"):
        AgentConfigurationManifest(
            schema_version=1,
            policy_sha256=EXPECTED_AGENT_POLICY_SHA256,
            configurations=(first, first),
        )
    with pytest.raises(ValidationError, match="canonical config ID order"):
        AgentConfigurationManifest(
            schema_version=1,
            policy_sha256=EXPECTED_AGENT_POLICY_SHA256,
            configurations=(second, first),
        )
    wrong_policy = config(config_id="other", execution_policy_sha256="b" * 64)
    with pytest.raises(ValidationError, match="manifest policy"):
        AgentConfigurationManifest(
            schema_version=1,
            policy_sha256=EXPECTED_AGENT_POLICY_SHA256,
            configurations=(wrong_policy,),
        )


def test_runtime_identity_validates_observed_cli_version_and_config_sha():
    identity = config()
    runtime = AgentRuntimeIdentity(
        schema_version=1,
        agent_config_id=identity.config_id,
        agent_config_sha256=compute_agent_configuration_sha256(identity),
        toolchain=identity.toolchain,
        cli_version="tool 1.2.3 (build abc)",
    )
    assert runtime.cli_version == "tool 1.2.3 (build abc)"
    for change in (
        {"agent_config_sha256": "bad"},
        {"cli_version": ""},
        {"cli_version": " padded"},
        {"extra": True},
    ):
        with pytest.raises(ValidationError):
            AgentRuntimeIdentity.model_validate(runtime.model_dump(mode="json") | change)


def test_candidate_fixtures_have_no_tool_specific_instruction_paths():
    prohibited = {
        "agents.md", "agents.override.md", "claude.md", ".claude", ".cursor",
        ".grok", ".codex", ".mcp.json",
    }
    candidate = load_candidate_manifest(PROJECT_ROOT)
    assert len(candidate.tasks) == 12
    for task in candidate.tasks:
        fixture = PROJECT_ROOT / "fixtures/reliability" / task.task_id
        tracked_template = {
            path.relative_to(fixture).as_posix() for path in template_files(fixture)
        }
        assert tracked_template
        for path in fixture.rglob("*"):
            relative = path.relative_to(fixture)
            assert not any(component.casefold() in prohibited for component in relative.parts), (
                task.task_id, relative
            )
