"""Build and verify the PatchBench V1.3 Agent configuration manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patchbench.domain import (
    AgentConfigurationIdentity,
    AgentConfigurationManifest,
    AgentConfigurationOption,
    AgentExecutionPolicy,
    AgentFallbackProvenance,
    AgentProviderClaimBoundary,
    AgentRuntimeIdentity,
    AgentToolchain,
    CursorRuntimeLimitation,
    compute_agent_configuration_manifest_sha256,
    compute_agent_configuration_sha256,
    compute_agent_execution_policy_sha256,
)


POLICY_PATH = Path("tasks/reliability/v1.3-agent-policy.json")
AGENT_MANIFEST_PATH = Path("tasks/reliability/v1.3-agent-configurations.json")
ACCEPTED_POLICY_SHA256 = "c17f5e7ff825e8fbc455c3a649b1288083aea4580bcdccd1c78c8a707c50eb00"
AGENT_TIMEOUT_SECONDS = 600
CURSOR_LIMITATION = (
    "Cursor CLI production preToolUse enforcement was runtime-validated through "
    "the Shell credential-scrub branch; WebSearch and Task denial branches were "
    "statically validated against the same active hook and Cursor's documented "
    "hook semantics, but could not be individually observed through the CLI's "
    "structured runtime audit stream."
)


class AgentManifestIntegrityError(RuntimeError):
    """Checked-in Agent configuration manifest does not match M8 truth."""


def _load_model(path: Path, model_type, category: str):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise AgentManifestIntegrityError(
            f"Unable to load {category} '{path}': {error}"
        ) from error


def load_policy(project_root: Path = PROJECT_ROOT) -> AgentExecutionPolicy:
    """Load the checked-in execution policy and require its accepted identity."""
    policy = _load_model(
        project_root / POLICY_PATH, AgentExecutionPolicy, "Agent execution policy"
    )
    actual = compute_agent_execution_policy_sha256(policy)
    if actual != ACCEPTED_POLICY_SHA256:
        raise AgentManifestIntegrityError(
            f"Policy SHA mismatch: expected {ACCEPTED_POLICY_SHA256}, found {actual}"
        )
    return policy


def build_agent_configuration_manifest(
    project_root: Path = PROJECT_ROOT,
) -> AgentConfigurationManifest:
    """Return the preregistered three-Agent semantic configuration manifest."""
    policy = load_policy(project_root)
    policy_sha256 = compute_agent_execution_policy_sha256(policy)
    codex = AgentConfigurationIdentity(
        schema_version=1,
        config_id="codex-gpt-5.5-relay",
        toolchain=AgentToolchain.CODEX,
        requested_model="gpt-5.5",
        agent_timeout_seconds=AGENT_TIMEOUT_SECONDS,
        execution_policy_sha256=policy_sha256,
        toolchain_options=(
            AgentConfigurationOption(
                name="relay_base_url",
                value="https://ai.ailink1.com/v1",
            ),
        ),
    )
    cursor = AgentConfigurationIdentity(
        schema_version=1,
        config_id="cursor-claude-4.6-sonnet-medium",
        toolchain=AgentToolchain.CURSOR_CLI,
        requested_model="claude-4.6-sonnet-medium",
        agent_timeout_seconds=AGENT_TIMEOUT_SECONDS,
        execution_policy_sha256=policy_sha256,
        toolchain_options=(
            AgentConfigurationOption(
                name="endpoint",
                value="https://api2.cursor.sh",
            ),
        ),
    )
    grok = AgentConfigurationIdentity(
        schema_version=1,
        config_id="grok-build-grok-4.5-relay",
        toolchain=AgentToolchain.GROK_BUILD,
        requested_model="grok-4.5",
        agent_timeout_seconds=AGENT_TIMEOUT_SECONDS,
        execution_policy_sha256=policy_sha256,
        toolchain_options=(
            AgentConfigurationOption(
                name="relay_base_url",
                value="https://ai.ailink1.com/v1",
            ),
            AgentConfigurationOption(
                name="relay_context_window",
                value=500000,
            ),
        ),
    )
    return AgentConfigurationManifest(
        schema_version=2,
        policy_sha256=policy_sha256,
        configurations=(codex, cursor, grok),
        runtime_identities=(
            AgentRuntimeIdentity(
                schema_version=1,
                agent_config_id=codex.config_id,
                agent_config_sha256=compute_agent_configuration_sha256(codex),
                toolchain=codex.toolchain,
                cli_version="codex-cli 0.153.4",
            ),
            AgentRuntimeIdentity(
                schema_version=1,
                agent_config_id=cursor.config_id,
                agent_config_sha256=compute_agent_configuration_sha256(cursor),
                toolchain=cursor.toolchain,
                cli_version="2026.09.18-9a7762b",
            ),
            AgentRuntimeIdentity(
                schema_version=1,
                agent_config_id=grok.config_id,
                agent_config_sha256=compute_agent_configuration_sha256(grok),
                toolchain=grok.toolchain,
                cli_version="grok 1.0.34 (3736acbc8658)",
            ),
        ),
        fallback_provenance=(
            AgentFallbackProvenance(
                originally_intended_toolchain=AgentToolchain.CLAUDE_CODE,
                intended_model="claude-sonnet-4-6",
                status="runtime_inadmissible_on_this_host",
                reason="upstream_environment_sandbox_incompatibility",
                selected_replacement_config_id=cursor.config_id,
                replacement_mechanism="preregistered_fallback",
            ),
        ),
        runtime_limitations=(
            CursorRuntimeLimitation(
                config_id=cursor.config_id,
                limitation=CURSOR_LIMITATION,
                websearch_runtime_denial_individually_observed=False,
                task_runtime_denial_individually_observed=False,
            ),
        ),
        provider_claim_boundaries=(
            AgentProviderClaimBoundary(
                config_id=codex.config_id,
                provider_facing_route="Ailink relay",
                physical_upstream_independently_verified=False,
                physical_upstream_equivalence_claimed=False,
            ),
            AgentProviderClaimBoundary(
                config_id=cursor.config_id,
                provider_facing_route="https://api2.cursor.sh",
                physical_upstream_independently_verified=False,
                physical_upstream_equivalence_claimed=False,
            ),
            AgentProviderClaimBoundary(
                config_id=grok.config_id,
                provider_facing_route="Ailink relay",
                physical_upstream_independently_verified=False,
                physical_upstream_equivalence_claimed=False,
            ),
        ),
    )


def load_agent_configuration_manifest(
    project_root: Path = PROJECT_ROOT,
) -> AgentConfigurationManifest:
    """Load and validate the checked-in Agent configuration manifest."""
    return _load_model(
        project_root / AGENT_MANIFEST_PATH,
        AgentConfigurationManifest,
        "Agent configuration manifest",
    )


def _first_mismatch(
    checked: AgentConfigurationManifest,
    expected: AgentConfigurationManifest,
) -> str:
    if checked.schema_version != expected.schema_version:
        return "schema version mismatch"
    if checked.policy_sha256 != expected.policy_sha256:
        return "policy SHA mismatch"
    checked_ids = tuple(configuration.config_id for configuration in checked.configurations)
    expected_ids = tuple(configuration.config_id for configuration in expected.configurations)
    if checked_ids != expected_ids:
        return "configuration set/order mismatch"
    for actual, wanted in zip(checked.configurations, expected.configurations, strict=True):
        if actual != wanted:
            return f"configuration '{actual.config_id}' semantic mismatch"
    return "Agent configuration manifest mismatch"


def verify_agent_configuration_manifest(
    manifest: AgentConfigurationManifest,
    project_root: Path = PROJECT_ROOT,
) -> AgentConfigurationManifest:
    """Fail closed unless the checked manifest matches deterministic M8 truth."""
    expected = build_agent_configuration_manifest(project_root)
    if manifest != expected:
        raise AgentManifestIntegrityError(_first_mismatch(manifest, expected))
    path = project_root / AGENT_MANIFEST_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AgentManifestIntegrityError(
            f"Unable to read checked Agent manifest bytes: {error}"
        ) from error
    if raw != deterministic_manifest_json(expected):
        raise AgentManifestIntegrityError("Agent manifest JSON byte serialization mismatch")
    return manifest


def deterministic_manifest_json(manifest: AgentConfigurationManifest) -> str:
    """Return deterministic pretty JSON with exactly one trailing newline."""
    return json.dumps(
        manifest.model_dump(mode="json"), indent=2, ensure_ascii=False
    ) + "\n"


def write_agent_configuration_manifest(
    manifest: AgentConfigurationManifest,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Write the reviewable checked-in manifest only when explicitly requested."""
    (project_root / AGENT_MANIFEST_PATH).write_text(
        deterministic_manifest_json(manifest), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify checked manifest")
    mode.add_argument("--write", action="store_true", help="rewrite checked manifest")
    arguments = parser.parse_args()
    try:
        if arguments.write:
            manifest = build_agent_configuration_manifest()
            write_agent_configuration_manifest(manifest)
        else:
            manifest = load_agent_configuration_manifest()
            verify_agent_configuration_manifest(manifest)
    except AgentManifestIntegrityError as error:
        raise SystemExit(f"Agent manifest integrity failure: {error}") from error
    print(
        "agent_manifest_sha256="
        f"{compute_agent_configuration_manifest_sha256(manifest)}"
    )


if __name__ == "__main__":
    main()
