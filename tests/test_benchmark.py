"""V1.3 M1 operator-side benchmark design and candidate identity contracts."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.domain import (
    BenchmarkCapability, BenchmarkCandidateManifest, BenchmarkDesignManifest,
    BenchmarkTaskProfile, DesignedDifficulty, TaskMetadata, TaskSpec,
    compute_benchmark_candidate_sha256, compute_benchmark_design_sha256,
)


DESIGN_PATH = Path(__file__).resolve().parents[1] / "tasks/reliability/v1.3-design.json"
SHA_A = "a" * 64
SHA_B = "b" * 64
LOCKED_MATRIX = {
    "env_config": ("local_boundary", "easy"),
    "request_signing": ("local_boundary", "medium"),
    "byte_ranges": ("local_boundary", "hard"),
    "config_resolution": ("cross_file", "easy"),
    "message_codec": ("cross_file", "medium"),
    "schema_upgrade": ("cross_file", "hard"),
    "resource_lifecycle": ("state_consistency", "easy"),
    "streaming_events": ("state_consistency", "medium"),
    "atomic_batch": ("state_consistency", "hard"),
    "format_fallback": ("regression_robustness", "easy"),
    "atomic_writer": ("regression_robustness", "medium"),
    "cache_revalidation": ("regression_robustness", "hard"),
}
# Anchored against a separate canonical JSON calculation of the validated artifact.
EXPECTED_DESIGN_SHA256 = "dc48fdac627abe9fcd95303d3042b5f0c822abbb0bb53a4dfba17dcc2f99f931"


def design_data() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def profile_data(**overrides) -> dict:
    return {
        "task_id": "sample_task",
        "primary_capability": "local_boundary",
        "designed_difficulty": "easy",
        "rationale": "A local parsing boundary with one repair locus.",
    } | overrides


def candidate_data() -> dict:
    return {
        "schema_version": 1,
        "suite_id": "patchbench-v1.3",
        "design_sha256": SHA_A,
        "tasks": [{
            "task_id": "sample_task",
            "task_spec_path": "tasks/reliability/sample_task/task.yaml",
            "task_spec_sha256": SHA_A,
            "task_fingerprint_sha256": SHA_B,
            "resolved_base_commit": "c" * 40,
            "official_evaluator_files": [
                {"path": "tests/test_sample.py", "sha256": SHA_A},
                {"path": "runner.py", "sha256": SHA_B},
            ],
        }],
    }


def candidate_hash(data: dict) -> str:
    return compute_benchmark_candidate_sha256(BenchmarkCandidateManifest.model_validate(data))


def test_taxonomy_has_exact_values_and_rejects_unknown():
    assert {item.value for item in BenchmarkCapability} == {
        "local_boundary", "cross_file", "state_consistency", "regression_robustness",
    }
    assert {item.value for item in DesignedDifficulty} == {"easy", "medium", "hard"}
    for capability in BenchmarkCapability:
        assert BenchmarkTaskProfile.model_validate(profile_data(
            primary_capability=capability.value)).primary_capability == capability
    for difficulty in DesignedDifficulty:
        assert BenchmarkTaskProfile.model_validate(profile_data(
            designed_difficulty=difficulty.value)).designed_difficulty == difficulty
    for overrides in ({"primary_capability": "unknown"}, {"designed_difficulty": "unknown"}):
        with pytest.raises(ValidationError):
            BenchmarkTaskProfile.model_validate(profile_data(**overrides))


def test_profile_optional_secondary_and_frozen_metadata():
    profile = BenchmarkTaskProfile.model_validate(profile_data())
    assert profile.secondary_capability is None
    assert BenchmarkTaskProfile.model_validate(profile_data(
        secondary_capability="cross_file")).secondary_capability is BenchmarkCapability.CROSS_FILE
    with pytest.raises(ValidationError):
        profile.task_id = "other"


@pytest.mark.parametrize("overrides", [
    {"secondary_capability": "local_boundary"},
    {"secondary_capability": "unknown"},
    {"task_id": ""},
    {"task_id": " sample_task"},
    {"rationale": ""},
    {"rationale": "  "},
    {"rationale": " padded "},
    {"extra": "no"},
])
def test_profile_rejects_invalid_values(overrides):
    with pytest.raises(ValidationError):
        BenchmarkTaskProfile.model_validate(profile_data(**overrides))


def test_checked_in_design_is_exact_locked_matrix():
    design = BenchmarkDesignManifest.model_validate(design_data())
    assert design.schema_version == 1
    assert design.suite_id == "patchbench-v1.3"
    assert design.difficulty_rubric_version == "structural-v1"
    assert [item.capability.value for item in design.capability_definitions] == [
        capability.value for capability in BenchmarkCapability]
    assert [item.dimension.value for item in design.structural_difficulty_dimensions] == [
        "symptom_root_cause_distance", "coordinated_edit_breadth",
        "temporal_state_interaction", "interacting_contract_edge_case_count",
        "regression_repository_navigation_pressure",
    ]
    assert [item.definition for item in design.structural_difficulty_dimensions] == [
        "Symptom → root-cause distance.", "Coordinated edit breadth.",
        "Temporal/state interaction.", "Interacting contract / edge-case count.",
        "Regression / repository-navigation pressure.",
    ]
    assert [item.difficulty.value for item in design.difficulty_definitions] == [
        difficulty.value for difficulty in DesignedDifficulty]
    assert all(item.definition for item in (*design.capability_definitions,
        *design.structural_difficulty_dimensions, *design.difficulty_definitions))
    assert len(design.tasks) == 12
    assert {task.task_id: (task.primary_capability.value, task.designed_difficulty.value)
            for task in design.tasks} == LOCKED_MATRIX
    assert all(task.secondary_capability is None and task.rationale for task in design.tasks)
    assert Counter(task.primary_capability for task in design.tasks) == {
        capability: 3 for capability in BenchmarkCapability
    }
    assert Counter(task.designed_difficulty for task in design.tasks) == {
        difficulty: 4 for difficulty in DesignedDifficulty
    }
    assert Counter((task.primary_capability, task.designed_difficulty)
                   for task in design.tasks) == {
        (capability, difficulty): 1
        for capability in BenchmarkCapability for difficulty in DesignedDifficulty
    }


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(schema_version=2),
    lambda d: d.update(suite_id=" patchbench-v1.3"),
    lambda d: d.update(difficulty_rubric_version=""),
    lambda d: d.update(tasks=[]),
    lambda d: d.update(extra="no"),
    lambda d: d["tasks"].append(d["tasks"][0]),
    lambda d: d["capability_definitions"].pop(),
    lambda d: d["capability_definitions"].append(d["capability_definitions"][0]),
    lambda d: d["structural_difficulty_dimensions"].pop(),
    lambda d: d["difficulty_definitions"].pop(),
    lambda d: d["capability_definitions"][0].update(capability="unknown"),
    lambda d: d["difficulty_definitions"][0].update(definition="  "),
    lambda d: d["structural_difficulty_dimensions"][0].update(extra="no"),
])
def test_design_rejects_malformed_manifest(mutation):
    data = design_data()
    mutation(data)
    with pytest.raises(ValidationError):
        BenchmarkDesignManifest.model_validate(data)


def test_design_hash_is_anchored_and_sensitive_to_complete_semantics():
    data = design_data()
    design = BenchmarkDesignManifest.model_validate(data)
    expected = EXPECTED_DESIGN_SHA256
    assert compute_benchmark_design_sha256(design) == expected
    assert compute_benchmark_design_sha256(BenchmarkDesignManifest.model_validate(data)) == expected
    assert len(expected) == 64 and expected == expected.lower()
    for change in ("capability", "difficulty", "rationale", "identity", "order"):
        modified = design_data()
        if change == "capability":
            modified["tasks"][0]["primary_capability"] = "cross_file"
        elif change == "difficulty":
            modified["tasks"][0]["designed_difficulty"] = "hard"
        elif change == "rationale":
            modified["tasks"][0]["rationale"] += " More context."
        elif change == "identity":
            modified["tasks"][0]["task_id"] = "different_task"
        else:
            modified["tasks"][0], modified["tasks"][1] = modified["tasks"][1], modified["tasks"][0]
        assert compute_benchmark_design_sha256(
            BenchmarkDesignManifest.model_validate(modified)) != expected


@pytest.mark.parametrize("field,index", [
    ("capability_definitions", 0),
    ("structural_difficulty_dimensions", 2),
    ("difficulty_definitions", 0),
    ("difficulty_definitions", 1),
    ("difficulty_definitions", 2),
])
def test_methodology_definition_changes_design_identity(field, index):
    modified = design_data()
    modified[field][index]["definition"] += " Revised."
    assert compute_benchmark_design_sha256(
        BenchmarkDesignManifest.model_validate(modified)) != EXPECTED_DESIGN_SHA256


def test_canonical_hash_uses_compact_sorted_utf8_json():
    data = design_data()
    data["suite_id"] = "bench"
    data["tasks"] = [profile_data(rationale="A café boundary.")]
    design = BenchmarkDesignManifest.model_validate(data)
    expected = hashlib.sha256(json.dumps(design.model_dump(mode="json"),
        ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    assert compute_benchmark_design_sha256(design) == expected


@pytest.mark.parametrize("field", ["task_spec_sha256", "task_fingerprint_sha256"])
def test_candidate_rejects_malformed_sha(field):
    data = candidate_data()
    data["tasks"][0][field] = "A" * 64
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)


def test_candidate_rejects_bad_design_and_evaluator_sha():
    data = candidate_data()
    data["design_sha256"] = "x" * 64
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)
    data = candidate_data()
    data["tasks"][0]["official_evaluator_files"][0]["sha256"] = "short"
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a\\b",
                                   "a//b", "a/./b", " path", "path ", "a:b"])
def test_candidate_rejects_noncanonical_paths(path):
    data = candidate_data()
    data["tasks"][0]["task_spec_path"] = path
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)
    data = candidate_data()
    data["tasks"][0]["official_evaluator_files"][0]["path"] = path
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)


def test_candidate_rejects_duplicate_ids_paths_and_missing_evaluator():
    data = candidate_data()
    data["tasks"].append(data["tasks"][0].copy())
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)
    data["tasks"][1]["task_id"] = "other_task"
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)
    data = candidate_data()
    data["tasks"][0]["official_evaluator_files"].append(
        data["tasks"][0]["official_evaluator_files"][0].copy())
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)
    data = candidate_data()
    data["tasks"][0]["official_evaluator_files"] = []
    with pytest.raises(ValidationError):
        BenchmarkCandidateManifest.model_validate(data)


def test_candidate_hash_binds_design_task_base_and_evaluator():
    original = candidate_data()
    baseline = candidate_hash(original)
    assert candidate_hash(candidate_data()) == baseline
    for location, field, value in [
        ("manifest", "design_sha256", SHA_B),
        ("task", "task_id", "other_task"),
        ("task", "task_spec_path", "tasks/other.yaml"),
        ("task", "task_spec_sha256", SHA_B),
        ("task", "task_fingerprint_sha256", SHA_A),
        ("task", "resolved_base_commit", "d" * 40),
        ("evaluator", "path", "tests/other.py"),
        ("evaluator", "sha256", SHA_B),
    ]:
        modified = candidate_data()
        target = modified if location == "manifest" else modified["tasks"][0]
        if location == "evaluator":
            target = target["official_evaluator_files"][0]
        target[field] = value
        assert candidate_hash(modified) != baseline, (location, field)


def test_benchmark_metadata_stays_outside_agent_task_contract():
    assert set(TaskMetadata.model_fields) == {"language"}
    assert "primary_capability" not in TaskSpec.model_fields
    assert "designed_difficulty" not in TaskSpec.model_fields
    assert "rationale" not in TaskSpec.model_fields
