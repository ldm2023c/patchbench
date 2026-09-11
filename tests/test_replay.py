import inspect
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.application import replay as replay_module
from patchbench.application import evaluation as evaluation_module
from patchbench.application.replay import ReplayError, replay_run
from patchbench.domain import (
    AgentExecutionMetadata,
    ArtifactPaths,
    EvaluationResult,
    ReplayRecord,
    RunRecord,
    RunStatus,
    TaskSpec,
)
from patchbench.repository import GitRepositoryManager, RepositoryError
from patchbench.sandbox.base import (
    SandboxExecResult,
    SandboxHandle,
    SandboxResourceLimits,
)
from patchbench.storage import ArtifactStoreError, FilesystemArtifactStore
from tests.helpers import create_fixture_repository, git


FIX_PATCH = """\
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a: int, b: int) -> int:
-    return a - b
+    return a + b
"""


def make_task(repository: Path, base_commit: str) -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "schema_version": 1,
            "id": "calculator_bug",
            "repository": {
                "type": "local",
                "path": str(repository),
                "base_commit": base_commit,
            },
            "task": {"prompt": "Fix the calculator bug."},
            "evaluation": {
                "command": f"{sys.executable} -m pytest -q",
                "timeout_seconds": 30,
            },
        }
    )


def make_run(
    results_root: Path,
    run_id: str = "source-run",
    *,
    evaluation_passed: bool = True,
    task_id: str = "calculator_bug",
) -> RunRecord:
    directory = results_root / run_id
    return RunRecord(
        run_id=run_id,
        task_id=task_id,
        status=RunStatus.PASSED if evaluation_passed else RunStatus.FAILED,
        evaluation_passed=evaluation_passed,
        duration_seconds=1.0,
        agent=AgentExecutionMetadata(
            name="historical-agent",
            backend="host",
            status=AgentRunStatus.COMPLETED,
            exit_code=0,
            duration_seconds=0.5,
        ),
        artifacts=ArtifactPaths(
            directory=directory,
            metadata=directory / "metadata.json",
            prompt=directory / "prompt.txt",
            agent_log=directory / "agent.log",
            agent_stderr_log=directory / "agent.stderr.log",
            test_log=directory / "test.log",
            patch=directory / "patch.diff",
        ),
    )


def persist_source(record: RunRecord, patch_text: str) -> None:
    record.artifacts.directory.mkdir(parents=True)
    record.artifacts.metadata.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    record.artifacts.patch.write_text(patch_text, encoding="utf-8")


@pytest.mark.parametrize(
    (
        "source_passed",
        "patch_text",
        "replay_passed",
        "outcome_matches",
    ),
    [
        (True, FIX_PATCH, True, True),
        (False, "", False, True),
        (True, "", False, False),
        (False, FIX_PATCH, True, False),
    ],
)
def test_replay_observes_all_source_and_replay_outcome_combinations(
    tmp_path: Path,
    source_passed: bool,
    patch_text: str,
    replay_passed: bool,
    outcome_matches: bool,
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    workspace_root = tmp_path / "workspaces"

    execution = replay_run(
        make_task(source_repository, base_commit),
        make_run(tmp_path / "results", evaluation_passed=source_passed),
        patch_text,
        workspace_root=workspace_root,
    )

    record = execution.record
    assert record.source_evaluation_passed is source_passed
    assert record.replay_evaluation_passed is replay_passed
    assert record.outcome_matches is outcome_matches
    assert record.base_commit_used == base_commit
    assert record.evaluation_backend == "host"
    assert record.duration_seconds >= execution.evaluation_result.duration_seconds
    assert not (workspace_root / record.replay_id).exists()
    assert git(source_repository, "worktree", "list", "--porcelain").count(
        "worktree "
    ) == 1


def test_patch_apply_failure_skips_evaluation_and_cleans_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    workspace_root = tmp_path / "workspaces"
    monkeypatch.setattr(
        evaluation_module.CommandEvaluator,
        "evaluate",
        lambda *args, **kwargs: pytest.fail("evaluator must not run"),
    )

    with pytest.raises(RepositoryError, match="Git command failed"):
        replay_run(
            make_task(source_repository, base_commit),
            make_run(tmp_path / "results"),
            "not a Git patch",
            workspace_root=workspace_root,
        )

    assert not any(workspace_root.iterdir())
    assert git(source_repository, "worktree", "list", "--porcelain").count(
        "worktree "
    ) == 1


def test_task_mismatch_is_rejected_before_worktree_creation(
    tmp_path: Path, monkeypatch
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    source_run = make_run(tmp_path / "results", task_id="another-task")
    monkeypatch.setattr(
        replay_module.GitRepositoryManager,
        "workspace",
        lambda *args, **kwargs: pytest.fail("worktree must not be created"),
    )

    with pytest.raises(ReplayError, match="does not match"):
        replay_run(make_task(source_repository, base_commit), source_run, FIX_PATCH)


class RecordingSandbox:
    def __init__(self, *, exit_code: int, error: Exception | None = None) -> None:
        self.exit_code = exit_code
        self.error = error
        self.events: list[str] = []
        self.workspace: Path | None = None

    def create(
        self,
        workspace: Path | None = None,
        resource_limits: SandboxResourceLimits | None = None,
    ) -> SandboxHandle:
        self.events.append("create")
        self.workspace = workspace
        return SandboxHandle(identifier="replay-sandbox")

    def exec(
        self,
        handle: SandboxHandle,
        command,
        *,
        timeout_seconds: float | None = None,
    ) -> SandboxExecResult:
        self.events.append("exec")
        if self.error is not None:
            raise self.error
        return SandboxExecResult(
            exit_code=self.exit_code,
            stdout="sandbox output",
            stderr="",
        )

    def destroy(self, handle: SandboxHandle) -> None:
        self.events.append("destroy")


def test_replay_uses_supplied_sandbox_and_treats_fail_as_completed(
    tmp_path: Path,
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    sandbox = RecordingSandbox(exit_code=7)

    execution = replay_run(
        make_task(source_repository, base_commit),
        make_run(tmp_path / "results", evaluation_passed=True),
        FIX_PATCH,
        workspace_root=tmp_path / "workspaces",
        sandbox=sandbox,
    )

    assert sandbox.events == ["create", "exec", "destroy"]
    assert sandbox.workspace is not None and not sandbox.workspace.exists()
    assert execution.record.evaluation_backend == "docker"
    assert execution.record.replay_evaluation_passed is False
    assert execution.record.outcome_matches is False


def test_replay_cleans_sandbox_and_worktree_on_sandbox_failure(
    tmp_path: Path,
) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    workspace_root = tmp_path / "workspaces"
    error = RuntimeError("sandbox infrastructure failed")
    sandbox = RecordingSandbox(exit_code=0, error=error)

    with pytest.raises(RuntimeError, match="sandbox infrastructure failed"):
        replay_run(
            make_task(source_repository, base_commit),
            make_run(tmp_path / "results"),
            FIX_PATCH,
            workspace_root=workspace_root,
            sandbox=sandbox,
        )

    assert sandbox.events == ["create", "exec", "destroy"]
    assert sandbox.workspace is not None and not sandbox.workspace.exists()
    assert not any(workspace_root.iterdir())


@pytest.mark.parametrize(
    ("source_passed", "replay_passed", "outcome_matches"),
    [
        (True, True, False),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ],
)
def test_replay_record_rejects_contradictory_outcome_match(
    source_passed: bool,
    replay_passed: bool,
    outcome_matches: bool,
) -> None:
    with pytest.raises(ValidationError, match="outcome_matches"):
        ReplayRecord(
            replay_id="replay-1",
            source_run_id="source-1",
            task_id="calculator_bug",
            base_commit_used="abc123",
            evaluation_backend="host",
            source_evaluation_passed=source_passed,
            replay_evaluation_passed=replay_passed,
            outcome_matches=outcome_matches,
            duration_seconds=1.0,
        )


def test_replay_application_api_has_no_agent_dependency() -> None:
    parameters = inspect.signature(replay_run).parameters

    assert "agent" not in parameters
    assert "agent_factory" not in parameters
    assert "from patchbench.agents" not in inspect.getsource(replay_module)


def test_load_source_run_and_patch_without_mutation(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    source = make_run(results_root)
    persist_source(source, FIX_PATCH)
    metadata_before = source.artifacts.metadata.read_bytes()
    patch_before = source.artifacts.patch.read_bytes()
    store = FilesystemArtifactStore(results_root)

    loaded = store.load_run_record(source.run_id)
    loaded_patch = store.load_run_patch(source.run_id)

    assert loaded == source
    assert loaded_patch == FIX_PATCH
    assert source.artifacts.metadata.read_bytes() == metadata_before
    assert source.artifacts.patch.read_bytes() == patch_before


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        ("metadata", "Unable to load Run metadata"),
        ("patch", "Unable to load Run patch"),
    ],
)
def test_missing_source_artifact_is_explicit(
    tmp_path: Path, artifact: str, message: str
) -> None:
    results_root = tmp_path / "results"
    source = make_run(results_root)
    persist_source(source, FIX_PATCH)
    getattr(source.artifacts, artifact).unlink()
    store = FilesystemArtifactStore(results_root)

    with pytest.raises(ArtifactStoreError, match=message):
        if artifact == "metadata":
            store.load_run_record(source.run_id)
        else:
            store.load_run_patch(source.run_id)


@pytest.mark.parametrize("contents", ["{not json", "{}"])
def test_malformed_source_metadata_is_explicit(
    tmp_path: Path, contents: str
) -> None:
    results_root = tmp_path / "results"
    source = make_run(results_root)
    persist_source(source, FIX_PATCH)
    source.artifacts.metadata.write_text(contents, encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="Invalid Run metadata"):
        FilesystemArtifactStore(results_root).load_run_record(source.run_id)


def test_source_metadata_run_id_must_match_requested_directory(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    source = make_run(results_root, run_id="requested-run")
    mismatched = source.model_copy(update={"run_id": "metadata-run"})
    persist_source(mismatched, FIX_PATCH)
    requested_directory = results_root / "requested-run"
    (requested_directory / "metadata.json").write_text(
        json.dumps(mismatched.model_dump(mode="json")), encoding="utf-8"
    )

    with pytest.raises(ArtifactStoreError, match="does not match requested"):
        FilesystemArtifactStore(results_root).load_run_record("requested-run")


@pytest.mark.parametrize("run_id", ["../../outside", "/absolute", "foo/bar"])
def test_run_lookup_rejects_paths_outside_direct_child(
    tmp_path: Path, run_id: str
) -> None:
    store = FilesystemArtifactStore(tmp_path / "results")

    with pytest.raises(ArtifactStoreError, match="Unsafe Run ID"):
        store.load_run_record(run_id)


def test_replay_persistence_writes_only_metadata_and_test_log(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "results")
    record = ReplayRecord(
        replay_id="replay-1",
        source_run_id="source-1",
        task_id="calculator_bug",
        base_commit_used="abc123",
        evaluation_backend="host",
        source_evaluation_passed=True,
        replay_evaluation_passed=True,
        outcome_matches=True,
        duration_seconds=1.5,
    )
    evaluation = EvaluationResult(
        exit_code=0,
        passed=True,
        duration_seconds=1.0,
        stdout="1 passed",
        stderr="",
    )

    metadata = store.save_replay(record, evaluation, "pytest -q")

    assert metadata == tmp_path / "results/replays/replay-1/metadata.json"
    assert {path.name for path in metadata.parent.iterdir()} == {
        "metadata.json",
        "test.log",
    }
    assert json.loads(metadata.read_text(encoding="utf-8")) == record.model_dump(
        mode="json"
    )
    assert "Command: pytest -q" in (metadata.parent / "test.log").read_text()
    assert not (metadata.parent / "patch.diff").exists()

    original = metadata.read_bytes()
    with pytest.raises(ArtifactStoreError, match="Unable to persist Replay"):
        store.save_replay(record, evaluation, "pytest -q")
    assert metadata.read_bytes() == original


def test_full_replay_flow_preserves_source_artifacts(tmp_path: Path) -> None:
    source_repository, base_commit = create_fixture_repository(tmp_path)
    task = make_task(source_repository, base_commit)
    results_root = tmp_path / "results"
    source = make_run(results_root)
    persist_source(source, FIX_PATCH)
    metadata_before = source.artifacts.metadata.read_bytes()
    patch_before = source.artifacts.patch.read_bytes()
    store = FilesystemArtifactStore(results_root)

    execution = replay_run(
        task,
        store.load_run_record(source.run_id),
        store.load_run_patch(source.run_id),
        workspace_root=tmp_path / "workspaces",
    )
    store.save_replay(
        execution.record,
        execution.evaluation_result,
        task.evaluation.command,
    )

    assert source.artifacts.metadata.read_bytes() == metadata_before
    assert source.artifacts.patch.read_bytes() == patch_before
    assert execution.record.replay_evaluation_passed is True
