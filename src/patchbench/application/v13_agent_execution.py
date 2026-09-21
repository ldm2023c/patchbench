"""Frozen PatchBench V1.3 Agent resolution and experiment execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from patchbench.agents import Agent, CodexAdapter, CursorCliAdapter, GrokBuildAdapter
from patchbench.application.experiment import run_experiment
from patchbench.domain import (
    AgentConfigurationIdentity,
    AgentConfigurationManifest,
    AgentConfigurationOption,
    AgentIdentityBinding,
    AgentRuntimeIdentity,
    AgentToolchain,
    ExperimentConfiguration,
    ExperimentRecord,
    compute_agent_configuration_manifest_sha256,
    compute_agent_configuration_sha256,
)
from patchbench.sandbox.base import Sandbox


ACCEPTED_M8_AGENT_MANIFEST_SHA256 = (
    "6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965"
)
V13_AGENT_MANIFEST_PATH = Path("tasks/reliability/v1.3-agent-configurations.json")


class FrozenAgentResolutionError(ValueError):
    """Raised when a frozen V1.3 Agent configuration cannot be resolved."""


@dataclass(frozen=True)
class FrozenAgentExecutionPlan:
    """Resolved execution facts for one frozen V1.3 Agent configuration."""

    configuration: AgentConfigurationIdentity
    runtime_identity: AgentRuntimeIdentity
    identity_binding: AgentIdentityBinding
    experiment_configuration: ExperimentConfiguration
    agent_factory: Callable[[], Agent]


def load_v13_agent_manifest(
    project_root: Path | None = None,
) -> AgentConfigurationManifest:
    """Load the checked-in frozen V1.3 Agent manifest."""

    root = Path.cwd() if project_root is None else Path(project_root)
    path = root / V13_AGENT_MANIFEST_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentConfigurationManifest.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise FrozenAgentResolutionError(
            f"Unable to load frozen V1.3 Agent manifest '{path}': {error}"
        ) from error


def resolve_v13_agent_config(
    config_id: str,
    *,
    evaluation_backend: Literal["host", "docker"],
    project_root: Path | None = None,
) -> FrozenAgentExecutionPlan:
    """Resolve one accepted frozen V1.3 Agent configuration by config ID."""

    manifest = load_v13_agent_manifest(project_root)
    manifest_sha256 = compute_agent_configuration_manifest_sha256(manifest)
    if manifest_sha256 != ACCEPTED_M8_AGENT_MANIFEST_SHA256:
        raise FrozenAgentResolutionError(
            "Frozen V1.3 Agent manifest semantic SHA mismatch: expected "
            f"{ACCEPTED_M8_AGENT_MANIFEST_SHA256}, found {manifest_sha256}"
        )
    return _derive_v13_agent_execution_plan(
        manifest,
        config_id=config_id,
        evaluation_backend=evaluation_backend,
        manifest_sha256=manifest_sha256,
    )


def run_v13_agent_experiment(
    task_path: str | Path,
    *,
    config_id: str,
    requested_runs: int,
    evaluation_backend: Literal["host", "docker"],
    project_root: Path | None = None,
    workspace_root: Path | None = None,
    results_root: Path | None = None,
    sandbox: Sandbox | None = None,
) -> ExperimentRecord:
    """Run an Experiment through the accepted frozen V1.3 Agent path."""

    plan = resolve_v13_agent_config(
        config_id,
        evaluation_backend=evaluation_backend,
        project_root=project_root,
    )
    return run_experiment(
        task_path,
        requested_runs=requested_runs,
        configuration=plan.experiment_configuration,
        agent_factory=plan.agent_factory,
        workspace_root=workspace_root,
        results_root=results_root,
        sandbox=sandbox,
    )


def _derive_v13_agent_execution_plan(
    manifest: AgentConfigurationManifest,
    *,
    config_id: str,
    evaluation_backend: Literal["host", "docker"],
    manifest_sha256: str,
) -> FrozenAgentExecutionPlan:
    if evaluation_backend not in {"host", "docker"}:
        raise FrozenAgentResolutionError("evaluation_backend must be 'host' or 'docker'")

    configuration = _select_configuration(manifest, config_id)
    runtime_identity = _select_runtime_identity(manifest, configuration)
    if runtime_identity.toolchain != configuration.toolchain:
        raise FrozenAgentResolutionError("runtime identity toolchain mismatch")
    agent_factory = _agent_factory(configuration, runtime_identity)
    config_sha256 = compute_agent_configuration_sha256(configuration)
    if runtime_identity.agent_config_sha256 != config_sha256:
        raise FrozenAgentResolutionError("runtime identity configuration SHA mismatch")

    identity_binding = AgentIdentityBinding(
        manifest_sha256=manifest_sha256,
        config_id=configuration.config_id,
        config_sha256=config_sha256,
    )
    experiment_configuration = ExperimentConfiguration(
        agent_name=configuration.toolchain.value,
        requested_model=configuration.requested_model,
        agent_timeout_seconds=configuration.agent_timeout_seconds,
        evaluation_backend=evaluation_backend,
        identity_binding=identity_binding,
    )
    return FrozenAgentExecutionPlan(
        configuration=configuration,
        runtime_identity=runtime_identity,
        identity_binding=identity_binding,
        experiment_configuration=experiment_configuration,
        agent_factory=agent_factory,
    )


def _select_configuration(
    manifest: AgentConfigurationManifest,
    config_id: str,
) -> AgentConfigurationIdentity:
    for configuration in manifest.configurations:
        if configuration.config_id == config_id:
            return configuration
    raise FrozenAgentResolutionError(f"Unknown frozen V1.3 Agent config ID: {config_id}")


def _select_runtime_identity(
    manifest: AgentConfigurationManifest,
    configuration: AgentConfigurationIdentity,
) -> AgentRuntimeIdentity:
    matches = tuple(
        runtime for runtime in manifest.runtime_identities
        if runtime.agent_config_id == configuration.config_id
    )
    if len(matches) != 1:
        raise FrozenAgentResolutionError(
            "Frozen V1.3 Agent manifest must contain exactly one runtime identity "
            f"for {configuration.config_id}"
        )
    return matches[0]


def _options_by_name(
    configuration: AgentConfigurationIdentity,
    expected_names: set[str],
) -> dict[str, str | int | bool]:
    options = {option.name: option.value for option in configuration.toolchain_options}
    actual_names = set(options)
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names
    if missing:
        raise FrozenAgentResolutionError(
            f"Frozen config {configuration.config_id} is missing required option(s): "
            + ", ".join(sorted(missing))
        )
    if unexpected:
        raise FrozenAgentResolutionError(
            f"Frozen config {configuration.config_id} has unexpected option(s): "
            + ", ".join(sorted(unexpected))
        )
    return options


def _string_option(
    options: dict[str, str | int | bool], name: str) -> str:
    value = options[name]
    if not isinstance(value, str):
        raise FrozenAgentResolutionError(f"Frozen option {name} must be a string")
    return value


def _positive_int_option(options: dict[str, str | int | bool], name: str) -> int:
    value = options[name]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FrozenAgentResolutionError(
            f"Frozen option {name} must be a positive integer"
        )
    return value


def _agent_factory(
    configuration: AgentConfigurationIdentity,
    runtime_identity: AgentRuntimeIdentity,
) -> Callable[[], Agent]:
    if configuration.toolchain is AgentToolchain.CODEX:
        options = _options_by_name(configuration, {"relay_base_url"})
        relay_base_url = _string_option(options, "relay_base_url")

        def make_codex() -> Agent:
            return CodexAdapter(
                model=configuration.requested_model,
                relay_base_url=relay_base_url,
                expected_cli_version=runtime_identity.cli_version,
            )

        return make_codex

    if configuration.toolchain is AgentToolchain.CURSOR_CLI:
        options = _options_by_name(configuration, {"endpoint"})
        endpoint = _string_option(options, "endpoint")

        def make_cursor() -> Agent:
            return CursorCliAdapter(
                model=configuration.requested_model,
                endpoint=endpoint,
                expected_cli_version=runtime_identity.cli_version,
            )

        return make_cursor

    if configuration.toolchain is AgentToolchain.GROK_BUILD:
        options = _options_by_name(
            configuration, {"relay_base_url", "relay_context_window"}
        )
        relay_base_url = _string_option(options, "relay_base_url")
        relay_context_window = _positive_int_option(options, "relay_context_window")

        def make_grok() -> Agent:
            return GrokBuildAdapter(
                model=configuration.requested_model,
                relay_base_url=relay_base_url,
                relay_context_window=relay_context_window,
                expected_cli_version=runtime_identity.cli_version,
            )

        return make_grok

    raise FrozenAgentResolutionError(
        f"Unsupported frozen V1.3 Agent toolchain: {configuration.toolchain.value}"
    )
