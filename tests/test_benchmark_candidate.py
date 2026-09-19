"""Repository-state integrity checks for the V1.3 candidate benchmark."""

import hashlib
import json
from pathlib import Path

import pytest

from patchbench.config.task_loader import load_task
from patchbench.domain import (
    BenchmarkCandidateManifest,
    compute_benchmark_candidate_sha256,
    compute_benchmark_design_sha256,
    compute_task_fingerprint,
)
from scripts.prepare_reliability_fixtures import CANDIDATES
from scripts.v13_candidate_manifest import (
    ACCEPTED_DESIGN_SHA256,
    BenchmarkCandidateIntegrityError,
    build_candidate_manifest,
    load_candidate_manifest,
    load_design,
    verify_candidate_manifest,
    write_candidate_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CANDIDATE_SHA256 = "a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043"
EXPECTED_ORDER = (
    "env_config", "request_signing", "byte_ranges", "config_resolution",
    "message_codec", "schema_upgrade", "resource_lifecycle", "streaming_events",
    "atomic_batch", "format_fallback", "atomic_writer", "cache_revalidation",
)


@pytest.fixture(scope="module")
def checked_candidate():
    return load_candidate_manifest(PROJECT_ROOT)


@pytest.fixture(scope="module")
def rebuilt_candidate(tmp_path_factory):
    return build_candidate_manifest(
        PROJECT_ROOT, temporary_root=tmp_path_factory.mktemp("candidate-build")
    )


def candidate_with(candidate, mutate):
    data = candidate.model_dump(mode="json")
    mutate(data)
    return BenchmarkCandidateManifest.model_validate(data)


def test_checked_candidate_links_exact_design_and_order(checked_candidate):
    design = load_design(PROJECT_ROOT)
    task_ids = tuple(task.task_id for task in checked_candidate.tasks)
    assert checked_candidate.schema_version == 1
    assert checked_candidate.suite_id == design.suite_id == "patchbench-v1.3"
    assert compute_benchmark_design_sha256(design) == ACCEPTED_DESIGN_SHA256
    assert checked_candidate.design_sha256 == ACCEPTED_DESIGN_SHA256
    assert task_ids == tuple(task.task_id for task in design.tasks) == EXPECTED_ORDER
    assert len(task_ids) == 12
    assert len(set(task_ids)) == len(task_ids)
    assert set(task_ids) == set(CANDIDATES)


def test_checked_candidate_task_contract_identities(checked_candidate):
    paths = []
    for candidate_task in checked_candidate.tasks:
        task_id = candidate_task.task_id
        expected_path = f"tasks/reliability/{task_id}/task.yaml"
        assert candidate_task.task_spec_path == expected_path
        paths.append(expected_path)
        spec_path = PROJECT_ROOT / expected_path
        task = load_task(spec_path)
        assert task.id == task_id
        assert candidate_task.task_spec_sha256 == hashlib.sha256(
            spec_path.read_bytes()
        ).hexdigest()
        assert candidate_task.resolved_base_commit == task.repository.base_commit
        assert candidate_task.task_fingerprint_sha256 == compute_task_fingerprint(
            task, base_commit_used=candidate_task.resolved_base_commit
        )
        frozen = task.evaluation.frozen_unittest
        assert frozen is not None and frozen.version == 1
        assert tuple(item.path for item in candidate_task.official_evaluator_files) == tuple(
            frozen.test_files
        )
        assert len(candidate_task.official_evaluator_files) == 1
        official = candidate_task.official_evaluator_files[0]
        fixture_file = PROJECT_ROOT / "fixtures/reliability" / task_id / official.path
        assert official.sha256 == hashlib.sha256(fixture_file.read_bytes()).hexdigest()
    assert len(paths) == len(set(paths))


def test_independent_builds_ignore_temporary_machine_paths(tmp_path, checked_candidate):
    first = build_candidate_manifest(PROJECT_ROOT, temporary_root=tmp_path / "one")
    second = build_candidate_manifest(PROJECT_ROOT, temporary_root=tmp_path / "elsewhere")
    assert first == second == checked_candidate
    assert compute_benchmark_candidate_sha256(first) == compute_benchmark_candidate_sha256(second)


def test_checked_candidate_sha_is_anchored(checked_candidate, rebuilt_candidate):
    assert rebuilt_candidate == checked_candidate
    assert compute_benchmark_candidate_sha256(checked_candidate) == EXPECTED_CANDIDATE_SHA256


def test_deterministic_serialization_round_trip(tmp_path, checked_candidate):
    root = tmp_path / "copy"
    (root / "tasks/reliability").mkdir(parents=True)
    write_candidate_manifest(checked_candidate, root)
    raw = (root / "tasks/reliability/v1.3-candidate.json").read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert BenchmarkCandidateManifest.model_validate(json.loads(raw)) == checked_candidate


@pytest.mark.parametrize(
    "label,mutate",
    [
        ("design SHA", lambda data: data.update(design_sha256="0" * 64)),
        ("TaskSpec file SHA", lambda data: data["tasks"][0].update(task_spec_sha256="0" * 64)),
        ("semantic task fingerprint", lambda data: data["tasks"][0].update(task_fingerprint_sha256="0" * 64)),
        ("resolved base commit", lambda data: data["tasks"][0].update(resolved_base_commit="0" * 40)),
        ("official evaluator file identity", lambda data: data["tasks"][0]["official_evaluator_files"][0].update(sha256="0" * 64)),
        ("candidate task set/order", lambda data: data["tasks"].reverse()),
        ("candidate task set/order", lambda data: data["tasks"].pop()),
    ],
)
def test_verifier_rejects_representative_candidate_drift(
    tmp_path, checked_candidate, label, mutate
):
    stale = candidate_with(checked_candidate, mutate)
    with pytest.raises(BenchmarkCandidateIntegrityError, match=label):
        verify_candidate_manifest(stale, PROJECT_ROOT, temporary_root=tmp_path)


def test_loader_fails_closed_for_missing_and_malformed_candidate(tmp_path):
    with pytest.raises(BenchmarkCandidateIntegrityError, match="candidate manifest"):
        load_candidate_manifest(tmp_path)
    path = tmp_path / "tasks/reliability/v1.3-candidate.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(BenchmarkCandidateIntegrityError, match="candidate manifest"):
        load_candidate_manifest(tmp_path)


def test_leakage_audit_rejects_reserved_answer_path(monkeypatch, tmp_path):
    from scripts import v13_candidate_manifest as builder

    original = builder.git

    def injected_git(repository, *arguments):
        value = original(repository, *arguments)
        if arguments == ("ls-files",):
            return value + "\nsolutions/reference_patch.py"
        return value

    monkeypatch.setattr(builder, "git", injected_git)
    with pytest.raises(BenchmarkCandidateIntegrityError, match="reserved artifact path"):
        build_candidate_manifest(PROJECT_ROOT, temporary_root=tmp_path)
