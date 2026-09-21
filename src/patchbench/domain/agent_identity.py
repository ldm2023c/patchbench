"""Operator-side Coding Agent execution policy and identity contracts."""

import hashlib
import json
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from patchbench.domain.models import DomainModel, Sha256Hex


CanonicalId = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=False, pattern=r"^[a-z][a-z0-9_.-]*$"
    ),
]
ExactText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=1, max_length=500),
]
OptionValue = StrictStr | StrictInt | StrictBool


class AgentToolchain(str, Enum):
    """Coding Agent toolchains recognized by the V1.3 identity schema."""

    CODEX = "codex"
    CLAUDE_CODE = "claude_code"
    GROK_BUILD = "grok_build"
    CURSOR_CLI = "cursor_cli"


class IsolationRequirement(str, Enum):
    """A control required whenever the selected toolchain exposes it."""

    REQUIRED_WHERE_SUPPORTED = "required_where_supported"


class AgentExtensionIsolationPolicy(DomainModel):
    """Optional external-context surfaces that must be neutralized when controllable."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    mcp: IsolationRequirement
    plugins: IsolationRequirement
    skills: IsolationRequirement
    subagents: IsolationRequirement
    web_search: IsolationRequirement
    other_external_context: IsolationRequirement


class AgentExecutionPolicy(DomainModel):
    """High-level fairness requirements shared by intended Agent configurations."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    policy_id: CanonicalId
    headless_execution: StrictBool
    single_supplied_prompt: StrictBool
    process_exits_after_run: StrictBool
    explicit_patchbench_workspace: StrictBool
    explicit_model: StrictBool
    silent_model_fallback_forbidden: StrictBool
    fresh_session: StrictBool
    ambient_configuration_isolation: IsolationRequirement
    personal_instructions_excluded: StrictBool
    cross_session_memory_isolation: IsolationRequirement
    extensions: AgentExtensionIsolationPolicy
    repository_instruction_neutrality: StrictBool
    authentication_preflight: StrictBool
    credentials_excluded_from_identity: StrictBool
    cli_version_runtime_provenance: StrictBool
    full_invocation_timeout: StrictBool
    process_tree_cleanup: StrictBool
    auto_update_isolation: IsolationRequirement
    patchbench_owns_worktree: StrictBool
    agent_git_lifecycle_forbidden: StrictBool
    git_diff_canonical_patch_truth: StrictBool
    natural_toolchain_differences_allowed: StrictBool


class AgentConfigurationOption(DomainModel):
    """One bounded semantic option interpreted explicitly by a future adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    name: CanonicalId
    value: OptionValue

    @field_validator("name")
    @classmethod
    def reject_credential_option_names(cls, value: str) -> str:
        normalized = value.replace("-", "_").replace(".", "_")
        credential_terms = {
            "api_key", "api_token", "access_token", "auth_token", "bearer_token",
            "client_secret", "private_key", "password", "credential", "credentials",
            "secret",
        }
        if any(
            normalized == term or normalized.endswith(f"_{term}")
            for term in credential_terms
        ):
            raise ValueError("credentials and secrets are not Agent identity options")
        return value

    @field_validator("value")
    @classmethod
    def validate_scalar_value(cls, value: OptionValue) -> OptionValue:
        if isinstance(value, str):
            if value != value.strip() or not value or any(
                ord(character) < 32 or ord(character) == 127 for character in value
            ):
                raise ValueError("string option values must be nonblank canonical text")
        return value


class AgentConfigurationIdentity(DomainModel):
    """Semantic identity of one intended Coding Agent configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    config_id: CanonicalId
    toolchain: AgentToolchain
    requested_model: ExactText
    agent_timeout_seconds: Annotated[int, Field(strict=True, gt=0)]
    execution_policy_sha256: Sha256Hex
    toolchain_options: tuple[AgentConfigurationOption, ...] = ()

    @field_validator("requested_model")
    @classmethod
    def validate_requested_model(cls, value: str) -> str:
        if value != value.strip() or not value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("requested model must be nonblank canonical text")
        return value

    @model_validator(mode="after")
    def validate_options(self) -> Self:
        names = tuple(option.name for option in self.toolchain_options)
        if len(names) != len(set(names)):
            raise ValueError("Agent configuration option names must be unique")
        if names != tuple(sorted(names)):
            raise ValueError("Agent configuration options must use canonical name order")
        return self


class AgentRuntimeIdentity(DomainModel):
    """Observed toolchain version tied to one semantic Agent configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    agent_config_id: CanonicalId
    agent_config_sha256: Sha256Hex
    toolchain: AgentToolchain
    cli_version: ExactText

    @field_validator("cli_version")
    @classmethod
    def validate_cli_version(cls, value: str) -> str:
        if value != value.strip() or not value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("CLI version must be nonblank exact observed text")
        return value


class AgentFallbackProvenance(DomainModel):
    """Preregistered fallback from an inadmissible intended toolchain."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    originally_intended_toolchain: AgentToolchain
    intended_model: ExactText
    status: Literal["runtime_inadmissible_on_this_host"]
    reason: Literal["upstream_environment_sandbox_incompatibility"]
    selected_replacement_config_id: CanonicalId
    replacement_mechanism: Literal["preregistered_fallback"]


class CursorRuntimeLimitation(DomainModel):
    """Frozen limitation for Cursor CLI runtime admission evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    config_id: CanonicalId
    limitation: ExactText
    websearch_runtime_denial_individually_observed: StrictBool
    task_runtime_denial_individually_observed: StrictBool

    @model_validator(mode="after")
    def reject_overclaimed_denial_observation(self) -> Self:
        if (
            self.websearch_runtime_denial_individually_observed
            or self.task_runtime_denial_individually_observed
        ):
            raise ValueError("Cursor WebSearch/Task runtime denial was not observed")
        return self


class AgentProviderClaimBoundary(DomainModel):
    """Frozen provider-facing route and upstream verification boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    config_id: CanonicalId
    provider_facing_route: ExactText
    physical_upstream_independently_verified: StrictBool
    physical_upstream_equivalence_claimed: StrictBool

    @model_validator(mode="after")
    def reject_unverified_upstream_claims(self) -> Self:
        if self.physical_upstream_independently_verified:
            raise ValueError("physical upstream was not independently verified")
        if self.physical_upstream_equivalence_claimed:
            raise ValueError("physical upstream equivalence must not be claimed")
        return self


class AgentConfigurationManifest(DomainModel):
    """Ordered intended configurations sharing one execution policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=2)]
    policy_sha256: Sha256Hex
    configurations: tuple[AgentConfigurationIdentity, ...] = Field(min_length=1)
    runtime_identities: tuple[AgentRuntimeIdentity, ...] = ()
    fallback_provenance: tuple[AgentFallbackProvenance, ...] = ()
    runtime_limitations: tuple[CursorRuntimeLimitation, ...] = ()
    provider_claim_boundaries: tuple[AgentProviderClaimBoundary, ...] = ()

    @model_validator(mode="after")
    def validate_configurations(self) -> Self:
        ids = tuple(configuration.config_id for configuration in self.configurations)
        if len(ids) != len(set(ids)):
            raise ValueError("Agent configuration IDs must be unique")
        if ids != tuple(sorted(ids)):
            raise ValueError("Agent configurations must use canonical config ID order")
        pairs = tuple(
            (configuration.toolchain, configuration.config_id)
            for configuration in self.configurations
        )
        if len(pairs) != len(set(pairs)):
            raise ValueError("toolchain/config ID pairs must be unique")
        if any(
            configuration.execution_policy_sha256 != self.policy_sha256
            for configuration in self.configurations
        ):
            raise ValueError("all Agent configurations must bind the manifest policy")

        configuration_by_id = {
            configuration.config_id: configuration
            for configuration in self.configurations
        }
        runtime_ids = tuple(runtime.agent_config_id for runtime in self.runtime_identities)
        if len(runtime_ids) != len(set(runtime_ids)):
            raise ValueError("runtime identities must be unique per configuration")
        if runtime_ids != tuple(sorted(runtime_ids)):
            raise ValueError("runtime identities must use canonical config ID order")
        for runtime in self.runtime_identities:
            configuration = configuration_by_id.get(runtime.agent_config_id)
            if configuration is None:
                raise ValueError("runtime identity references unknown configuration")
            if runtime.agent_config_sha256 != compute_agent_configuration_sha256(configuration):
                raise ValueError("runtime identity configuration SHA mismatch")
            if runtime.toolchain != configuration.toolchain:
                raise ValueError("runtime identity toolchain mismatch")

        fallback_targets = tuple(
            fallback.selected_replacement_config_id
            for fallback in self.fallback_provenance
        )
        if fallback_targets != tuple(sorted(fallback_targets)):
            raise ValueError("fallback provenance must use canonical target order")
        if any(target not in configuration_by_id for target in fallback_targets):
            raise ValueError("fallback provenance references unknown configuration")

        limitation_ids = tuple(limitation.config_id for limitation in self.runtime_limitations)
        if len(limitation_ids) != len(set(limitation_ids)):
            raise ValueError("runtime limitations must be unique per configuration")
        if limitation_ids != tuple(sorted(limitation_ids)):
            raise ValueError("runtime limitations must use canonical config ID order")
        if any(config_id not in configuration_by_id for config_id in limitation_ids):
            raise ValueError("runtime limitation references unknown configuration")

        boundary_ids = tuple(boundary.config_id for boundary in self.provider_claim_boundaries)
        if len(boundary_ids) != len(set(boundary_ids)):
            raise ValueError("provider claim boundaries must be unique per configuration")
        if boundary_ids != tuple(sorted(boundary_ids)):
            raise ValueError("provider claim boundaries must use canonical config ID order")
        if any(config_id not in configuration_by_id for config_id in boundary_ids):
            raise ValueError("provider claim boundary references unknown configuration")

        if self.schema_version == 1:
            return self
        sorted_ids = tuple(sorted(ids))
        if runtime_ids != sorted_ids:
            raise ValueError("schema v2 requires one runtime identity per configuration")
        if len(self.fallback_provenance) != 1:
            raise ValueError("schema v2 requires one fallback provenance record")
        if len(self.runtime_limitations) != 1:
            raise ValueError("schema v2 requires one Cursor runtime limitation")
        if boundary_ids != sorted_ids:
            raise ValueError("schema v2 requires one provider claim boundary per configuration")
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def compute_agent_execution_policy_sha256(policy: AgentExecutionPolicy) -> str:
    """Hash every validated semantic execution-policy field."""
    return hashlib.sha256(_canonical_json_bytes(policy.model_dump(mode="json"))).hexdigest()


def compute_agent_configuration_sha256(
    configuration: AgentConfigurationIdentity,
) -> str:
    """Hash every validated semantic Agent configuration field."""
    return hashlib.sha256(
        _canonical_json_bytes(configuration.model_dump(mode="json"))
    ).hexdigest()


def compute_agent_configuration_manifest_sha256(
    manifest: AgentConfigurationManifest,
) -> str:
    """Hash every validated semantic Agent configuration manifest field."""
    return hashlib.sha256(
        _canonical_json_bytes(manifest.model_dump(mode="json"))
    ).hexdigest()
