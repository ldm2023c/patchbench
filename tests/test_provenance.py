import hashlib
import json
import re
import sys

import pytest
from pydantic import TypeAdapter, ValidationError
import yaml

from patchbench.agents.fake import FakeAgent
from patchbench.application.local_run import run_task
from patchbench.application.experiment import run_experiment
from patchbench.application.replay import replay_run
from patchbench.config.task_loader import load_task
from patchbench.domain import (
    ExperimentConfiguration, RunProvenance, Sha256Hex, TaskSpec,
    compute_task_fingerprint,
)
from patchbench.storage import FilesystemArtifactStore
from tests.helpers import create_fixture_repository, write_run_task
from tests.test_local_run import RecordingSandbox
from tests.test_replay import FIX_PATCH, make_run, make_task


def semantic_task():
    return TaskSpec.model_validate({
        "schema_version": 1, "id": "task",
        "repository": {"type": "local", "path": "../repo", "base_commit": "main"},
        "task": {"prompt": "修复 café\nKeep behavior."},
        "evaluation": {"command": "python -B -m unittest -v", "timeout_seconds": 120},
        "metadata": {"language": "python"},
    })


def test_fingerprint_locked_unicode_serialization():
    task = semantic_task()
    # Independent literal canonical JSON anchors key order, UTF-8, and payload.
    canonical = ('{"evaluation":{"command":"python -B -m unittest -v","timeout_seconds":120},'
                 '"id":"task","metadata":{"language":"python"},'
                 '"repository":{"base_commit":"' + 'a' * 40 + '","type":"local"},'
                 '"schema_version":1,"task":{"prompt":"修复 café\\nKeep behavior."}}')
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    for _ in range(2):
        actual = compute_task_fingerprint(task, base_commit_used="a" * 40)
        assert actual == expected
        assert re.fullmatch(r"[0-9a-f]{64}", actual)


@pytest.mark.parametrize("path", ["../repo", "/home/alice/repo", "/Users/bob/repo"])
def test_fingerprint_excludes_repository_path_and_unresolved_ref(path):
    task = semantic_task()
    changed = task.model_dump()
    changed["repository"].update(path=path, base_commit="abcdef0")
    assert compute_task_fingerprint(TaskSpec.model_validate(changed), base_commit_used="a" * 40) == compute_task_fingerprint(task, base_commit_used="a" * 40)


@pytest.mark.parametrize("section,key,value", [
    ("task", "prompt", "Different prompt"),
    ("evaluation", "command", "python -m unittest -q"),
    ("evaluation", "timeout_seconds", 121),
    ("metadata", "language", "rust"),
])
def test_semantic_changes_change_fingerprint(section, key, value):
    task = semantic_task()
    changed = task.model_dump()
    changed[section][key] = value
    assert compute_task_fingerprint(TaskSpec.model_validate(changed), base_commit_used="a" * 40) != compute_task_fingerprint(task, base_commit_used="a" * 40)


def test_resolved_commit_changes_fingerprint():
    task = semantic_task()
    assert compute_task_fingerprint(task, base_commit_used="a" * 40) != compute_task_fingerprint(task, base_commit_used="b" * 40)


def test_yaml_format_and_key_order_do_not_affect_fingerprint(tmp_path):
    payload = semantic_task().model_dump()
    paths = [tmp_path / "first.yaml", tmp_path / "second.yaml"]
    paths[0].write_text(yaml.safe_dump(payload, sort_keys=True))
    paths[1].write_text("# formatting only\n" + yaml.safe_dump(payload, sort_keys=False, default_flow_style=True))
    assert compute_task_fingerprint(load_task(paths[0]), base_commit_used="a" * 40) == compute_task_fingerprint(load_task(paths[1]), base_commit_used="a" * 40)


@pytest.mark.parametrize("invalid", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + "a" * 64, "a" * 64 + "\n", b"a" * 64, 123])
def test_sha256_rejects_noncanonical_values(invalid):
    with pytest.raises(ValidationError):
        RunProvenance(base_commit_used="abc", task_fingerprint_sha256=invalid,
                      evaluation_command="test", evaluation_timeout_seconds=1,
                      evaluation_backend="host")


def test_sha256_accepts_lowercase_and_provenance_forbids_extra_fields():
    assert TypeAdapter(Sha256Hex).validate_python("0123456789abcdef" * 4) == "0123456789abcdef" * 4
    data = dict(base_commit_used="abc", task_fingerprint_sha256="a" * 64,
                evaluation_command="test", evaluation_timeout_seconds=1,
                evaluation_backend="host")
    for change in ({"evaluation_backend": "other"}, {"evaluation_timeout_seconds": 0}, {"extra": True}):
        with pytest.raises(ValidationError):
            RunProvenance(**(data | change))


@pytest.mark.parametrize("backend", ["host", "docker"])
def test_new_runs_persist_resolved_provenance(tmp_path, backend):
    source, commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, commit[:8], command=f'{sys.executable} -c "pass"')
    task = load_task(task_path)
    record = run_task(task_path, agent=FakeAgent(), agent_name="fake",
                      sandbox=RecordingSandbox() if backend == "docker" else None,
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    expected = RunProvenance(
        base_commit_used=commit,
        task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used=commit),
        evaluation_command=task.evaluation.command,
        evaluation_timeout_seconds=task.evaluation.timeout_seconds,
        evaluation_backend=backend,
    )
    assert record.provenance == expected
    assert record.agent.backend == "host"
    assert json.loads(record.artifacts.metadata.read_text())["provenance"] == expected.model_dump()
    assert FilesystemArtifactStore(tmp_path / "results").load_run_record(record.run_id).provenance == expected


@pytest.mark.parametrize("backend", ["host", "docker"])
def test_experiment_children_have_consistent_provenance(tmp_path, backend):
    source, commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, "HEAD", command=f'{sys.executable} -c "pass"')
    task = load_task(task_path)
    record = run_experiment(task_path, requested_runs=2,
                            configuration=ExperimentConfiguration(agent_name="fake", evaluation_backend=backend),
                            agent_factory=FakeAgent,
                            sandbox=RecordingSandbox() if backend == "docker" else None,
                            workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    store = FilesystemArtifactStore(tmp_path / "results")
    expected = RunProvenance(base_commit_used=commit,
                             task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used=commit),
                             evaluation_command=task.evaluation.command,
                             evaluation_timeout_seconds=task.evaluation.timeout_seconds,
                             evaluation_backend=record.configuration.evaluation_backend)
    for run_id in record.run_ids:
        child = store.load_run_record(run_id)
        assert child.provenance == expected
        assert child.agent.backend == "host"


@pytest.mark.parametrize("omit", [True, False])
def test_historical_metadata_without_provenance_loads_and_replays(tmp_path, omit):
    source, commit = create_fixture_repository(tmp_path)
    record = make_run(tmp_path / "results")
    raw = record.model_dump(mode="json")
    if omit:
        raw.pop("provenance")
    record.artifacts.directory.mkdir(parents=True)
    original = json.dumps(raw)
    record.artifacts.metadata.write_text(original)
    record.artifacts.patch.write_text(FIX_PATCH)
    store = FilesystemArtifactStore(tmp_path / "results")
    loaded = store.load_run_record(record.run_id)
    assert loaded.provenance is None
    replay = replay_run(make_task(source, commit), loaded, store.load_run_patch(record.run_id),
                        workspace_root=tmp_path / "workspaces")
    assert replay.record.replay_evaluation_passed
    assert record.artifacts.metadata.read_text() == original
