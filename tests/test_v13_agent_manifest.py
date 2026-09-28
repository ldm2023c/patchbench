"""V1.3 M8 final three-Agent semantic configuration manifest tests."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.domain import (
    AgentConfigurationIdentity,
    AgentConfigurationManifest,
    AgentToolchain,
    compute_agent_configuration_manifest_sha256,
    compute_agent_configuration_sha256,
    compute_agent_execution_policy_sha256,
)
from scripts.v13_agent_manifest import (
    AGENT_MANIFEST_PATH,
    AgentManifestIntegrityError,
    build_agent_configuration_manifest,
    deterministic_manifest_json,
    load_agent_configuration_manifest,
    verify_agent_configuration_manifest,
)
from scripts.v13_candidate_manifest import load_candidate_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / AGENT_MANIFEST_PATH
POLICY_SHA256 = "c17f5e7ff825e8fbc455c3a649b1288083aea4580bcdccd1c78c8a707c50eb00"
CANDIDATE_SHA256 = "a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043"
AGENT_MANIFEST_SHA256 = "6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965"
EXPECTED_CONFIG_IDS = (
    "codex-gpt-5.5-relay",
    "cursor-claude-4.6-sonnet-medium",
    "grok-build-grok-4.5-relay",
)
EXPECTED_TOOLCHAINS_MODELS = {
    "codex-gpt-5.5-relay": ("codex", "gpt-5.5"),
    "cursor-claude-4.6-sonnet-medium": (
        "cursor_cli",
        "claude-4.6-sonnet-medium",
    ),
    "grok-build-grok-4.5-relay": ("grok_build", "grok-4.5"),
}
EXPECTED_OPTIONS = {
    "codex-gpt-5.5-relay": {
        "relay_base_url": "https://ai.ailink1.com/v1",
    },
    "cursor-claude-4.6-sonnet-medium": {
        "endpoint": "https://api2.cursor.sh",
    },
    "grok-build-grok-4.5-relay": {
        "relay_base_url": "https://ai.ailink1.com/v1",
        "relay_context_window": 500000,
    },
}


def checked_manifest() -> AgentConfigurationManifest:
    return load_agent_configuration_manifest(PROJECT_ROOT)


def refresh_runtime_bindings(data: dict) -> dict:
    configurations = {
        configuration["config_id"]: AgentConfigurationIdentity.model_validate(
            configuration
        )
        for configuration in data["configurations"]
    }
    for runtime in data.get("runtime_identities", []):
        configuration = configurations.get(runtime["agent_config_id"])
        if configuration is not None:
            runtime["agent_config_sha256"] = compute_agent_configuration_sha256(
                configuration
            )
            runtime["toolchain"] = configuration.toolchain.value
    return data


def test_checked_agent_manifest_validates_and_matches_expected_truth():
    manifest = checked_manifest()
    expected = build_agent_configuration_manifest(PROJECT_ROOT)
    assert manifest.schema_version == 2
    assert verify_agent_configuration_manifest(manifest, PROJECT_ROOT) == manifest
    assert manifest == expected
    assert len(manifest.configurations) == 3
    assert tuple(configuration.config_id for configuration in manifest.configurations) == EXPECTED_CONFIG_IDS


def test_checked_agent_manifest_exact_configuration_semantics():
    manifest = checked_manifest()
    for configuration in manifest.configurations:
        expected_toolchain, expected_model = EXPECTED_TOOLCHAINS_MODELS[
            configuration.config_id
        ]
        assert configuration.toolchain.value == expected_toolchain
        assert configuration.requested_model == expected_model
        assert configuration.agent_timeout_seconds == 600
        assert configuration.execution_policy_sha256 == POLICY_SHA256
        options = {
            option.name: option.value for option in configuration.toolchain_options
        }
        assert options == EXPECTED_OPTIONS[configuration.config_id]
    assert manifest.policy_sha256 == POLICY_SHA256
    assert all(
        configuration.toolchain is not AgentToolchain.CLAUDE_CODE
        for configuration in manifest.configurations
    )


def test_agent_manifest_excludes_credentials_from_configuration_options():
    manifest = checked_manifest()
    forbidden_fragments = (
        "api_key", "token", "secret", "credential", "password", "auth",
        "executable", "path", "home", "telemetry",
    )
    assert "claude_code" not in {
        configuration.toolchain.value for configuration in manifest.configurations
    }
    for configuration in manifest.configurations:
        for option in configuration.toolchain_options:
            normalized = option.name.replace("-", "_").replace(".", "_")
            assert not any(fragment in normalized for fragment in forbidden_fragments)


def test_agent_manifest_runtime_provenance_binds_each_selected_config():
    manifest = checked_manifest()
    runtime_by_id = {
        runtime.agent_config_id: runtime for runtime in manifest.runtime_identities
    }
    assert tuple(runtime_by_id) == EXPECTED_CONFIG_IDS
    assert {
        config_id: runtime.cli_version
        for config_id, runtime in runtime_by_id.items()
    } == {
        "codex-gpt-5.5-relay": "codex-cli 0.153.4",
        "cursor-claude-4.6-sonnet-medium": "2026.09.18-9a7762b",
        "grok-build-grok-4.5-relay": "grok 1.0.34 (3736acbc8658)",
    }
    config_by_id = {
        configuration.config_id: configuration
        for configuration in manifest.configurations
    }
    for config_id, runtime in runtime_by_id.items():
        configuration = config_by_id[config_id]
        assert runtime.agent_config_sha256 == compute_agent_configuration_sha256(
            configuration
        )
        assert runtime.toolchain == configuration.toolchain


def test_agent_manifest_rejects_invalid_runtime_provenance():
    data = checked_manifest().model_dump(mode="json")
    missing = json.loads(json.dumps(data))
    missing["runtime_identities"] = missing["runtime_identities"][:2]
    duplicate = json.loads(json.dumps(data))
    duplicate["runtime_identities"][1] = duplicate["runtime_identities"][0]
    unknown = json.loads(json.dumps(data))
    unknown["runtime_identities"][0]["agent_config_id"] = "unknown-config"
    sha_mismatch = json.loads(json.dumps(data))
    sha_mismatch["runtime_identities"][0]["agent_config_sha256"] = "b" * 64
    toolchain_mismatch = json.loads(json.dumps(data))
    toolchain_mismatch["runtime_identities"][0]["toolchain"] = "cursor_cli"
    for mutated in (missing, duplicate, unknown, sha_mismatch, toolchain_mismatch):
        with pytest.raises(ValidationError):
            AgentConfigurationManifest.model_validate(mutated)


def test_agent_manifest_freezes_claude_exclusion_cursor_fallback():
    manifest = checked_manifest()
    assert len(manifest.fallback_provenance) == 1
    fallback = manifest.fallback_provenance[0]
    assert fallback.originally_intended_toolchain is AgentToolchain.CLAUDE_CODE
    assert fallback.intended_model == "claude-sonnet-4-6"
    assert fallback.status == "runtime_inadmissible_on_this_host"
    assert fallback.reason == "upstream_environment_sandbox_incompatibility"
    assert fallback.selected_replacement_config_id == "cursor-claude-4.6-sonnet-medium"
    assert fallback.replacement_mechanism == "preregistered_fallback"


def test_agent_manifest_rejects_invalid_fallback_target():
    data = checked_manifest().model_dump(mode="json")
    data["fallback_provenance"][0]["selected_replacement_config_id"] = "missing"
    with pytest.raises(ValidationError):
        AgentConfigurationManifest.model_validate(data)


def test_agent_manifest_freezes_cursor_limitation_and_claim_boundaries():
    manifest = checked_manifest()
    assert len(manifest.runtime_limitations) == 1
    limitation = manifest.runtime_limitations[0]
    assert limitation.config_id == "cursor-claude-4.6-sonnet-medium"
    assert (
        "could not be individually observed through the CLI's structured runtime audit stream"
        in limitation.limitation
    )
    assert limitation.websearch_runtime_denial_individually_observed is False
    assert limitation.task_runtime_denial_individually_observed is False
    assert "WebSearch runtime denial individually observed = PASS" not in json.dumps(
        manifest.model_dump(mode="json")
    )
    boundaries = {
        boundary.config_id: boundary
        for boundary in manifest.provider_claim_boundaries
    }
    assert set(boundaries) == set(EXPECTED_CONFIG_IDS)
    assert boundaries["codex-gpt-5.5-relay"].provider_facing_route == "Ailink relay"
    assert boundaries["grok-build-grok-4.5-relay"].provider_facing_route == "Ailink relay"
    assert (
        boundaries["cursor-claude-4.6-sonnet-medium"].provider_facing_route
        == "https://api2.cursor.sh"
    )
    assert all(
        boundary.physical_upstream_independently_verified is False
        and boundary.physical_upstream_equivalence_claimed is False
        for boundary in boundaries.values()
    )


def test_agent_manifest_rejects_overclaimed_cursor_or_upstream_boundaries():
    limitation = checked_manifest().model_dump(mode="json")
    limitation["runtime_limitations"][0][
        "websearch_runtime_denial_individually_observed"
    ] = True
    upstream = checked_manifest().model_dump(mode="json")
    upstream["provider_claim_boundaries"][0][
        "physical_upstream_independently_verified"
    ] = True
    equivalence = checked_manifest().model_dump(mode="json")
    equivalence["provider_claim_boundaries"][1][
        "physical_upstream_equivalence_claimed"
    ] = True
    for mutated in (limitation, upstream, equivalence):
        with pytest.raises(ValidationError):
            AgentConfigurationManifest.model_validate(mutated)


def test_agent_manifest_deterministic_hash_and_bytes():
    manifest = checked_manifest()
    expected = build_agent_configuration_manifest(PROJECT_ROOT)
    raw = MANIFEST_PATH.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw == deterministic_manifest_json(expected).encode("utf-8")
    assert json.loads(raw) == manifest.model_dump(mode="json")
    assert compute_agent_configuration_manifest_sha256(manifest) == AGENT_MANIFEST_SHA256


def test_agent_manifest_hash_changes_for_required_semantic_changes():
    baseline = checked_manifest()
    baseline_hash = compute_agent_configuration_manifest_sha256(baseline)
    data = baseline.model_dump(mode="json")

    mutations = []
    model_change = json.loads(json.dumps(data))
    model_change["configurations"][0]["requested_model"] = "gpt-5.5-other"
    mutations.append(refresh_runtime_bindings(model_change))

    timeout_change = json.loads(json.dumps(data))
    timeout_change["configurations"][1]["agent_timeout_seconds"] = 601
    mutations.append(refresh_runtime_bindings(timeout_change))

    endpoint_change = json.loads(json.dumps(data))
    endpoint_change["configurations"][1]["toolchain_options"][0]["value"] = "https://example.com"
    mutations.append(refresh_runtime_bindings(endpoint_change))

    relay_change = json.loads(json.dumps(data))
    relay_change["configurations"][0]["toolchain_options"][0]["value"] = "https://example.com/v1"
    mutations.append(refresh_runtime_bindings(relay_change))

    context_change = json.loads(json.dumps(data))
    context_change["configurations"][2]["toolchain_options"][1]["value"] = 500001
    mutations.append(refresh_runtime_bindings(context_change))

    policy_change = json.loads(json.dumps(data))
    policy_change["policy_sha256"] = "b" * 64
    for configuration in policy_change["configurations"]:
        configuration["execution_policy_sha256"] = "b" * 64
    mutations.append(refresh_runtime_bindings(policy_change))

    set_change = json.loads(json.dumps(data))
    set_change["configurations"] = set_change["configurations"][:2]
    set_change["runtime_identities"] = set_change["runtime_identities"][:2]
    set_change["provider_claim_boundaries"] = set_change["provider_claim_boundaries"][:2]
    mutations.append(set_change)

    runtime_change = json.loads(json.dumps(data))
    runtime_change["runtime_identities"][0]["cli_version"] = "codex-cli 0.153.5"
    mutations.append(runtime_change)

    fallback_change = json.loads(json.dumps(data))
    fallback_change["fallback_provenance"][0]["intended_model"] = "other-model"
    mutations.append(fallback_change)

    limitation_change = json.loads(json.dumps(data))
    limitation_change["runtime_limitations"][0]["limitation"] += " Additional boundary."
    mutations.append(limitation_change)

    boundary_change = json.loads(json.dumps(data))
    boundary_change["provider_claim_boundaries"][0]["provider_facing_route"] = "Other route"
    mutations.append(boundary_change)

    assert all(
        compute_agent_configuration_manifest_sha256(
            AgentConfigurationManifest.model_validate(mutated)
        ) != baseline_hash
        for mutated in mutations
    )


def test_agent_manifest_script_check_succeeds():
    result = subprocess.run(
        [sys.executable, "scripts/v13_agent_manifest.py", "--check"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "agent_manifest_sha256="
        f"{AGENT_MANIFEST_SHA256}"
    )


def test_agent_manifest_check_rejects_semantic_or_byte_drift(tmp_path):
    copied = tmp_path / "repo"
    copied.mkdir()
    (copied / "tasks/reliability").mkdir(parents=True)
    (copied / "scripts").mkdir()
    (copied / "tasks/reliability/v1.3-agent-policy.json").write_bytes(
        (PROJECT_ROOT / "tasks/reliability/v1.3-agent-policy.json").read_bytes()
    )
    manifest_path = copied / AGENT_MANIFEST_PATH
    manifest_path.write_bytes(MANIFEST_PATH.read_bytes())
    semantic = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic["configurations"][0]["requested_model"] = "changed"
    manifest_path.write_text(json.dumps(semantic, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(Exception):
        verify_agent_configuration_manifest(
            AgentConfigurationManifest.model_validate(semantic),
            copied,
        )

    manifest = build_agent_configuration_manifest(copied)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AgentManifestIntegrityError, match="byte serialization"):
        verify_agent_configuration_manifest(manifest, copied)


def test_existing_policy_and_candidate_semantic_hashes_unchanged():
    policy = build_agent_configuration_manifest(PROJECT_ROOT)
    assert policy.policy_sha256 == POLICY_SHA256
    checked_policy = json.loads(
        (PROJECT_ROOT / "tasks/reliability/v1.3-agent-policy.json").read_text(
            encoding="utf-8"
        )
    )
    from patchbench.domain import AgentExecutionPolicy

    assert compute_agent_execution_policy_sha256(
        AgentExecutionPolicy.model_validate(checked_policy)
    ) == POLICY_SHA256
    candidate = load_candidate_manifest(PROJECT_ROOT)
    canonical = json.dumps(
        candidate.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == CANDIDATE_SHA256
