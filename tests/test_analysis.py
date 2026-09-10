"""Artifact-only fixtures and public API tests for read-only analysis."""

import json
from pathlib import Path
import subprocess

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.application.analysis import AnalysisError, analyze_experiment
from patchbench.domain import (
    EvaluationResult, ExperimentConfiguration, ExperimentRecord,
    RunProvenance, RunStatus, aggregate_runs, render_evaluation_log,
    summarize_evaluation_log, summarize_patch,
)
from patchbench.storage import ArtifactStoreError, FilesystemArtifactStore
from tests.test_replay import FIX_PATCH, make_run


def write_experiment(root, outcomes=(True, False, True, False), *, historical=False,
                     provenance=True, unknown=False):
    store = FilesystemArtifactStore(root)
    runs = []
    for i, passed in enumerate(outcomes):
        run = make_run(root, run_id=("z-run", "a-run", "m-run", "b-run")[i], evaluation_passed=passed)
        run.duration_seconds = float(i + 1)
        run.agent.name = "fake"
        run.agent.status = AgentRunStatus.COMMAND_FAILED if i == 0 else AgentRunStatus.COMPLETED
        run.agent.exit_code = 7 if i == 0 else 0
        patch = FIX_PATCH if passed else ""
        output = "custom evaluator" if unknown else (
            "Ran 1 test in 0.010s\n\nOK" if passed else
            "FAIL: test_add (tests.Calculator)\n\nRan 1 test in 0.010s\n\nFAILED (failures=1)")
        test_log = render_evaluation_log(EvaluationResult(
            exit_code=0 if passed else 1, passed=passed, duration_seconds=0.01,
            stdout="", stderr=output), "python -m unittest")
        if provenance:
            run.provenance = RunProvenance(
                base_commit_used="a" * 40, task_fingerprint_sha256="b" * 64,
                evaluation_command="python -m unittest", evaluation_timeout_seconds=30,
                evaluation_backend="host")
        if not historical:
            run.patch_summary = summarize_patch(patch)
            run.evaluation_evidence = summarize_evaluation_log(test_log)
        run.artifacts.directory.mkdir(parents=True)
        raw = run.model_dump(mode="json")
        if historical:
            raw.pop("patch_summary")
            raw.pop("evaluation_evidence")
            if not provenance:
                raw.pop("provenance")
        run.artifacts.metadata.write_text(json.dumps(raw))
        run.artifacts.patch.write_text(patch)
        run.artifacts.test_log.write_text(test_log)
        runs.append(run)
    experiment = ExperimentRecord(
        experiment_id="experiment-1", task_id=runs[0].task_id,
        requested_runs=len(runs), run_ids=[r.run_id for r in runs],
        configuration=ExperimentConfiguration(agent_name="fake", evaluation_backend="host"),
        aggregate=aggregate_runs(runs), duration_seconds=10,
    )
    store.save_experiment(experiment)
    return store, experiment


def mutate(path, edit):
    raw = json.loads(path.read_text())
    edit(raw)
    path.write_text(json.dumps(raw))


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


@pytest.mark.parametrize("outcomes", [(True, True), (False, False), (False, True, True, False)])
def test_outcomes_order_pair_counts_and_read_only(tmp_path, outcomes, monkeypatch):
    store, experiment = write_experiment(tmp_path / "results", outcomes)
    before = snapshot(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("Analyze must not execute subprocesses or write files")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    result = analyze_experiment(experiment.experiment_id, artifact_store=store)
    assert result == analyze_experiment(experiment.experiment_id, artifact_store=store)
    assert [r.run_id for r in result.runs] == experiment.run_ids
    assert result.aggregate == experiment.aggregate
    assert result.exact_patch_variant_count == len(set(outcomes))
    assert result.failure_category_counts == {
        "agent_command_failed": 1, "agent_timed_out": 0,
        "no_patch": outcomes.count(False), "test_failed": outcomes.count(False),
    }
    assert result.provenance.base_commit_used == "a" * 40
    if len(set(outcomes)) == 2:
        assert result.example_pair.pass_run_id == experiment.run_ids[outcomes.index(True)]
        assert result.example_pair.fail_run_id == experiment.run_ids[outcomes.index(False)]
    else:
        assert result.example_pair is None
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("provenance", [False, True])
def test_historical_summaries_reconstructed_without_migration(tmp_path, provenance):
    store, experiment = write_experiment(tmp_path, historical=True, provenance=provenance)
    before = snapshot(tmp_path)
    result = analyze_experiment(experiment.experiment_id, artifact_store=store)
    assert (result.provenance is not None) == provenance
    assert result.runs[0].patch == summarize_patch(FIX_PATCH)
    assert result.runs[0].evaluation.framework == "unittest"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mutation,message", [
    (lambda r: r.update(task_id="other"), "task_id"),
    (lambda r: r["agent"].update(name="codex"), "agent name"),
    (lambda r: r["agent"].update(requested_model="other"), "requested model"),
    (lambda r: r["agent"].update(timeout_seconds=99), "agent timeout"),
    (lambda r: r["provenance"].update(evaluation_backend="docker"), "evaluation backend"),
    (lambda r: r.update(provenance=None), "provenance"),
    (lambda r: r["provenance"].update(base_commit_used="different"), "provenance"),
    (lambda r: r["provenance"].update(task_fingerprint_sha256="c" * 64), "provenance"),
    (lambda r: r["provenance"].update(evaluation_command="other"), "provenance"),
    (lambda r: r["provenance"].update(evaluation_timeout_seconds=99), "provenance"),
    (lambda r: r.update(status="failed"), "status"),
    (lambda r: r["patch_summary"].update(patch_sha256="c" * 64), "patch summary"),
    (lambda r: r["patch_summary"]["files"][0].update(diff_sha256="c" * 64), "patch summary"),
    (lambda r: r["evaluation_evidence"].update(tests_run=99), "evaluation evidence"),
    (lambda r: r["evaluation_evidence"].update(output_tail=["tampered"]), "evaluation evidence"),
])
def test_inconsistent_metadata_rejected(tmp_path, mutation, message):
    store, experiment = write_experiment(tmp_path)
    mutate(tmp_path / experiment.run_ids[0] / "metadata.json", mutation)
    with pytest.raises(AnalysisError, match=message):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


@pytest.mark.parametrize("filename,replacement", [
    ("patch.diff", FIX_PATCH.replace("a + b", "b + a")),
    ("test.log", "Command: python -m unittest\nExit code: 0\nDuration seconds: 0.010000\n\nSTDOUT:\n\nSTDERR:\nchanged"),
    ("patch.diff", "invalid patch"), ("test.log", "invalid log"),
])
def test_raw_tampering_rejected(tmp_path, filename, replacement):
    store, experiment = write_experiment(tmp_path)
    (tmp_path / experiment.run_ids[0] / filename).write_text(replacement)
    with pytest.raises(AnalysisError):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


def test_historical_log_outcome_mismatch_rejected(tmp_path):
    store, experiment = write_experiment(tmp_path, historical=True)
    path = tmp_path / experiment.run_ids[0] / "test.log"
    path.write_text(path.read_text().replace("Exit code: 0", "Exit code: 1"))
    with pytest.raises(AnalysisError, match="evaluation outcome"):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


def test_aggregate_mismatch_rejected(tmp_path):
    store, experiment = write_experiment(tmp_path)
    mutate(tmp_path / "experiments" / experiment.experiment_id / "metadata.json",
           lambda r: r["aggregate"].update(evaluation_pass_rate=0.123))
    with pytest.raises(AnalysisError, match="aggregate"):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


@pytest.mark.parametrize("unsafe", ["../x", "a/b", "/absolute", "", ".", "a/../b"])
def test_storage_rejects_unsafe_ids(tmp_path, unsafe):
    store = FilesystemArtifactStore(tmp_path)
    with pytest.raises(ArtifactStoreError, match="Unsafe"):
        store.load_experiment_record(unsafe)
    with pytest.raises(ArtifactStoreError, match="Unsafe"):
        store.load_run_test_log(unsafe)


def test_loaders_use_canonical_namespace_not_metadata_paths(tmp_path):
    store, experiment = write_experiment(tmp_path)
    assert store.load_experiment_record(experiment.experiment_id) == experiment
    directory = tmp_path / experiment.run_ids[0]
    mutate(directory / "metadata.json", lambda r: r["artifacts"].update(test_log="/untrusted/path", patch="/untrusted/patch"))
    assert store.load_run_test_log(experiment.run_ids[0]) == (directory / "test.log").read_text()
    assert analyze_experiment(experiment.experiment_id, artifact_store=store).runs


@pytest.mark.parametrize("content", ["{", "{}", '{"experiment_id":"different"}'])
def test_malformed_experiment_metadata(tmp_path, content):
    store, experiment = write_experiment(tmp_path)
    (tmp_path / "experiments" / experiment.experiment_id / "metadata.json").write_text(content)
    with pytest.raises(ArtifactStoreError, match="Invalid"):
        store.load_experiment_record(experiment.experiment_id)


def test_experiment_id_mismatch(tmp_path):
    store, experiment = write_experiment(tmp_path)
    mutate(tmp_path / "experiments" / experiment.experiment_id / "metadata.json",
           lambda r: r.update(experiment_id="other"))
    with pytest.raises(ArtifactStoreError, match="ID"):
        store.load_experiment_record(experiment.experiment_id)


@pytest.mark.parametrize("filename", ["metadata.json", "patch.diff", "test.log"])
def test_missing_run_artifacts(tmp_path, filename):
    store, experiment = write_experiment(tmp_path)
    (tmp_path / experiment.run_ids[0] / filename).unlink()
    with pytest.raises(ArtifactStoreError, match="Unable"):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


def test_missing_experiment_does_not_create_results(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(ArtifactStoreError, match="Unable"):
        analyze_experiment("missing", artifact_store=FilesystemArtifactStore(root))
    assert not root.exists()


def test_raw_line_endings_are_not_normalized(tmp_path):
    store, experiment = write_experiment(tmp_path)
    for filename, loader in (("patch.diff", store.load_run_patch), ("test.log", store.load_run_test_log)):
        path = tmp_path / experiment.run_ids[0] / filename
        raw = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(raw)
        assert loader(experiment.run_ids[0]).encode("utf-8") == raw
    with pytest.raises(AnalysisError):
        analyze_experiment(experiment.experiment_id, artifact_store=store)


def test_symlink_directory_escape_rejected(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "experiments").symlink_to(outside, target_is_directory=True)
    (root / "escaped").symlink_to(outside, target_is_directory=True)
    store = FilesystemArtifactStore(root)
    with pytest.raises(ArtifactStoreError, match="Unsafe"):
        store.load_experiment_record("example")
    with pytest.raises(ArtifactStoreError, match="Unsafe"):
        store.load_run_test_log("escaped")


def test_exact_variants_recomputed_for_historical_all_pass(tmp_path):
    store, experiment = write_experiment(tmp_path, (True, True, True), historical=True)
    (tmp_path / experiment.run_ids[1] / "patch.diff").write_text(FIX_PATCH.replace("a + b", "b + a"))
    result = analyze_experiment(experiment.experiment_id, artifact_store=store)
    assert result.exact_patch_variant_count == 2
    assert result.example_pair is None


def test_invalid_utf8_log_is_store_error(tmp_path):
    store, experiment = write_experiment(tmp_path)
    (tmp_path / experiment.run_ids[0] / "test.log").write_bytes(b"\xff")
    with pytest.raises(ArtifactStoreError):
        analyze_experiment(experiment.experiment_id, artifact_store=store)
