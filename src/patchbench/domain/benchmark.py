"""Operator-side benchmark design and future candidate identity contracts."""

import hashlib
import json
from enum import Enum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from patchbench.domain.models import DomainModel, Sha256Hex


TaskId = Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                         pattern=r"^[a-z][a-z0-9_]*$")]
CanonicalName = Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                                pattern=r"^[a-z][a-z0-9.-]*$")]
RelativePath = Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                               min_length=1)]
GitCommitHex = Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                               pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Rationale = Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                            min_length=1, max_length=500)]


class BenchmarkCapability(str, Enum):
    LOCAL_BOUNDARY = "local_boundary"
    CROSS_FILE = "cross_file"
    STATE_CONSISTENCY = "state_consistency"
    REGRESSION_ROBUSTNESS = "regression_robustness"


class DesignedDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class _StructuralDimension(str, Enum):
    SYMPTOM_ROOT_CAUSE_DISTANCE = "symptom_root_cause_distance"
    COORDINATED_EDIT_BREADTH = "coordinated_edit_breadth"
    TEMPORAL_STATE_INTERACTION = "temporal_state_interaction"
    INTERACTING_CONTRACT_EDGE_CASE_COUNT = "interacting_contract_edge_case_count"
    REGRESSION_REPOSITORY_NAVIGATION_PRESSURE = "regression_repository_navigation_pressure"


class _MethodologyDefinition(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    definition: Annotated[str, StringConstraints(strict=True, strip_whitespace=False,
                                                 min_length=1, max_length=1000)]

    @field_validator("definition")
    @classmethod
    def validate_definition(cls, value: str) -> str:
        if value != value.strip() or not value.strip() or any(
                ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("methodology definition must be nonblank canonical text")
        return value


class _CapabilityDefinition(_MethodologyDefinition):
    capability: BenchmarkCapability


class _DifficultyDimension(_MethodologyDefinition):
    dimension: _StructuralDimension


class _DifficultyDefinition(_MethodologyDefinition):
    difficulty: DesignedDifficulty


class BenchmarkTaskProfile(DomainModel):
    """Design-time classification, never part of an Agent-visible TaskSpec."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    task_id: TaskId
    primary_capability: BenchmarkCapability
    secondary_capability: BenchmarkCapability | None = None
    designed_difficulty: DesignedDifficulty
    rationale: Rationale

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        if value != value.strip() or not value.strip() or any(
                ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("rationale must be nonblank canonical text")
        return value

    @model_validator(mode="after")
    def validate_secondary_capability(self) -> Self:
        if self.secondary_capability == self.primary_capability:
            raise ValueError("secondary capability must differ from primary capability")
        return self


class BenchmarkDesignManifest(DomainModel):
    """Ordered design metadata; its hash is not a concrete benchmark freeze."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    suite_id: CanonicalName
    difficulty_rubric_version: CanonicalName
    capability_definitions: tuple[_CapabilityDefinition, ...]
    structural_difficulty_dimensions: tuple[_DifficultyDimension, ...]
    difficulty_definitions: tuple[_DifficultyDefinition, ...]
    tasks: tuple[BenchmarkTaskProfile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_tasks(self) -> Self:
        if tuple(item.capability for item in self.capability_definitions) != tuple(BenchmarkCapability):
            raise ValueError("capability definitions must cover all capabilities in canonical order")
        if tuple(item.dimension for item in self.structural_difficulty_dimensions) != tuple(_StructuralDimension):
            raise ValueError("structural dimensions must cover all five dimensions in canonical order")
        if tuple(item.difficulty for item in self.difficulty_definitions) != tuple(DesignedDifficulty):
            raise ValueError("difficulty definitions must cover all difficulties in canonical order")
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark design task IDs must be unique")
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_benchmark_design_sha256(design: BenchmarkDesignManifest) -> str:
    """Hash all validated design semantics, including task order and rationales."""
    return hashlib.sha256(_canonical_json_bytes(design.model_dump(mode="json"))).hexdigest()


def _validate_relative_path(path: str) -> str:
    if (path != path.strip() or path.startswith("/") or "\\" in path or ":" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("path must be canonical repository-relative POSIX text")
    return path


class BenchmarkCandidateFile(DomainModel):
    """Exact bytes of one official evaluator or test file."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    path: RelativePath
    sha256: Sha256Hex

    _path = field_validator("path")(_validate_relative_path)


class BenchmarkCandidateTask(DomainModel):
    """Concrete task contract and official evaluation identities for future M3."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    task_id: TaskId
    task_spec_path: RelativePath
    task_spec_sha256: Sha256Hex
    task_fingerprint_sha256: Sha256Hex
    resolved_base_commit: GitCommitHex
    official_evaluator_files: tuple[BenchmarkCandidateFile, ...] = Field(min_length=1)

    _task_spec_path = field_validator("task_spec_path")(_validate_relative_path)

    @model_validator(mode="after")
    def validate_evaluator_files(self) -> Self:
        paths = [item.path for item in self.official_evaluator_files]
        if len(paths) != len(set(paths)):
            raise ValueError("official evaluator file paths must be unique per task")
        return self


class BenchmarkCandidateManifest(DomainModel):
    """A future concrete candidate; no M1 candidate is instantiated or frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    suite_id: CanonicalName
    design_sha256: Sha256Hex
    tasks: tuple[BenchmarkCandidateTask, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_tasks(self) -> Self:
        ids = [task.task_id for task in self.tasks]
        paths = [task.task_spec_path for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate task IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("candidate TaskSpec paths must be unique")
        return self


def compute_benchmark_candidate_sha256(candidate: BenchmarkCandidateManifest) -> str:
    """Hash the design link and every concrete task/evaluator identity."""
    return hashlib.sha256(_canonical_json_bytes(candidate.model_dump(mode="json"))).hexdigest()
