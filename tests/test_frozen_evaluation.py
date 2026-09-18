"""Frozen evaluation integrity with disposable repositories and editing stubs."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from patchbench.agents.base import AgentRunResult, AgentRunStatus
from patchbench.application import evaluation as evaluation_module
from patchbench.application.evaluation import evaluate_patch
from patchbench.application.experiment import run_experiment
from patchbench.application.local_run import run_task
from patchbench.application.replay import replay_run
from patchbench.config.task_loader import load_task
from patchbench.domain.models import ExperimentConfiguration, FROZEN_UNITTEST_COMMAND
from patchbench.domain.evaluation_evidence import summarize_evaluation_log
from patchbench.evaluators.command import EvaluationError
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.storage.filesystem import FilesystemArtifactStore
from tests.helpers import create_fixture_repository, git, write_run_task


FROZEN_TEST = '''import unittest
from calculator import add

class Arithmetic(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
'''
WEAK_TEST = '''import unittest
class Weakened(unittest.TestCase):
    def test_ignored(self):
        pass
'''


def make_frozen_task(tmp_path, test_source=FROZEN_TEST):
    source, _ = create_fixture_repository(tmp_path)
    (source / "test_calculator.py").write_text(test_source)
    git(source, "add", "test_calculator.py")
    git(source, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "unittest contract")
    commit = git(source, "rev-parse", "HEAD")
    task_path = write_run_task(tmp_path, source, commit, command=FROZEN_UNITTEST_COMMAND)
    raw = yaml.safe_load(task_path.read_text())
    raw["evaluation"]["frozen_unittest"] = {"version": 1, "test_files": ["test_calculator.py"]}
    task_path.write_text(yaml.safe_dump(raw))
    return source, commit, task_path


class EditingAgent:
    def __init__(self, edit):
        self.edit = edit
        self.workspace = None

    def run(self, request):
        self.workspace = request.workspace
        self.edit(request.workspace)
        return AgentRunResult(status=AgentRunStatus.COMPLETED, exit_code=0,
                              stdout="edited", stderr="", duration_seconds=0)


def repair(workspace):
    path = workspace / "calculator.py"
    path.write_text(path.read_text().replace("return a - b", "return a + b"))


def assert_clean(source, commit, root):
    assert list(root.iterdir()) == []
    assert git(source, "status", "--porcelain") == ""
    assert git(source, "rev-parse", "HEAD") == commit
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.fixture(autouse=True)
def python_path(monkeypatch):
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])


@pytest.mark.parametrize("edit_kind", ["weaken", "delete", "skip", "directory", "reserved", "reserved_file"])
def test_visible_test_edits_cannot_weaken_official_result(tmp_path, edit_kind):
    source, commit, task_path = make_frozen_task(tmp_path)
    def edit(workspace):
        test = workspace / "test_calculator.py"
        if edit_kind == "delete":
            test.unlink()
        elif edit_kind == "directory":
            test.unlink()
            test.mkdir()
            (test / "child.py").write_text("raise SystemExit(0)")
        elif edit_kind.startswith("reserved"):
            reserved = workspace / ".patchbench-eval"
            if edit_kind == "reserved_file":
                reserved.write_text("Agent file")
            else:
                reserved.mkdir()
                (reserved / "runner.py").write_text("raise SystemExit(0)")
        else:
            test.write_text(WEAK_TEST if edit_kind == "weaken" else
                            WEAK_TEST.replace("class Weakened", '@unittest.skip("skip")\nclass Weakened'))
    record = run_task(task_path, agent=EditingAgent(edit), agent_name="stub",
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert not record.evaluation_passed
    assert record.evaluation_evidence.tests_run == 1
    assert record.evaluation_evidence.failure_count == 1
    patch = record.artifacts.patch.read_text()
    assert (".patchbench-eval" if edit_kind.startswith("reserved") else "test_calculator.py") in patch
    assert "Frozen unittest suite contains zero" not in record.artifacts.test_log.read_text()
    if edit_kind == "delete":
        assert "deleted file mode" in patch
    assert_clean(source, commit, tmp_path / "workspaces")


def test_repair_and_test_edits_preserve_canonical_evidence_and_replay(tmp_path):
    source, commit, task_path = make_frozen_task(tmp_path)
    def edit(workspace):
        repair(workspace)
        (workspace / "test_calculator.py").write_text(WEAK_TEST)
        (workspace / "test_added.py").write_text('raise RuntimeError("not an official test")')
        (workspace / "unittest.py").write_text('raise RuntimeError("shadow unittest")')
        (workspace / "sitecustomize.py").write_text('raise RuntimeError("shadow site")')
    record = run_task(task_path, agent=EditingAgent(edit), agent_name="stub",
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert record.evaluation_passed
    assert record.evaluation_evidence.tests_run == 1
    log = record.artifacts.test_log.read_text()
    assert "test_add" in log and "test_ignored" not in log
    assert record.provenance.evaluation_command == FROZEN_UNITTEST_COMMAND
    assert record.evaluation_evidence == summarize_evaluation_log(log)
    assert record.evaluation_evidence.test_log_sha256 == hashlib.sha256(log.encode()).hexdigest()
    patch = record.artifacts.patch.read_text()
    assert "test_added.py" in patch and "class Weakened" in patch and "return a + b" in patch
    assert ".patchbench-eval" not in patch
    assert record.patch_summary.patch_sha256 == hashlib.sha256(patch.encode()).hexdigest()
    for historical in (record, record.model_copy(update={"provenance": None})):
        replay = replay_run(load_task(task_path), historical, patch,
                            workspace_root=tmp_path / "workspaces")
        assert replay.record.replay_evaluation_passed
        assert "test_add" in replay.evaluation_result.stderr
        assert "test_ignored" not in replay.evaluation_result.stderr
    assert_clean(source, commit, tmp_path / "workspaces")


@pytest.mark.parametrize("path_name", ["test_calculator.py", ".patchbench-eval"])
def test_symlink_restoration_does_not_touch_external_target(tmp_path, path_name):
    source, commit, task_path = make_frozen_task(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_text("keep")
    def edit(workspace):
        path = workspace / path_name
        if path.exists():
            path.unlink()
        try:
            path.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported")
    record = run_task(task_path, agent=EditingAgent(edit), agent_name="stub",
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert not record.evaluation_passed
    assert "120000" in record.artifacts.patch.read_text()
    assert list(external.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"
    assert_clean(source, commit, tmp_path / "workspaces")


def test_zero_frozen_tests_cannot_pass(tmp_path):
    source, commit, task_path = make_frozen_task(tmp_path, "# No tests\n")
    record = run_task(task_path, agent=EditingAgent(lambda _: None), agent_name="stub",
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert not record.evaluation_passed
    assert "zero tests" in record.artifacts.test_log.read_text()
    assert record.evaluation_evidence.framework == "unknown"
    assert_clean(source, commit, tmp_path / "workspaces")


@pytest.mark.parametrize("base_kind", ["missing", "directory", "symlink"])
def test_invalid_frozen_base_is_infrastructure_error_and_cleans(tmp_path, base_kind):
    source, commit, task_path = make_frozen_task(tmp_path)
    path = source / "test_calculator.py"
    path.unlink()
    if base_kind == "directory":
        path.mkdir()
        (path / "child").write_text("data")
    elif base_kind == "symlink":
        try:
            path.symlink_to("calculator.py")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unsupported")
    git(source, "add", "-A")
    git(source, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "invalid frozen base")
    commit = git(source, "rev-parse", "HEAD")
    raw = yaml.safe_load(task_path.read_text())
    raw["repository"]["base_commit"] = commit
    task_path.write_text(yaml.safe_dump(raw))
    with pytest.raises(EvaluationError):
        run_task(task_path, agent=EditingAgent(lambda _: None), agent_name="stub",
                 workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert not (tmp_path / "results").exists()
    assert_clean(source, commit, tmp_path / "workspaces")


def test_evaluation_copy_never_changes_agent_workspace_and_cleans_on_error(tmp_path, monkeypatch):
    source, commit, task_path = make_frozen_task(tmp_path)
    task = load_task(task_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    with manager.workspace(task.repository, "agent") as workspace:
        (workspace.path / "test_calculator.py").write_text(WEAK_TEST)
        patch = manager.capture_diff(workspace)
        def check_and_fail(self, path, config):
            assert path != workspace.path
            assert (path / "test_calculator.py").read_text() == FROZEN_TEST
            assert (path / ".patchbench-eval/runner.py").is_file()
            assert (workspace.path / "test_calculator.py").read_text() == WEAK_TEST
            assert not (workspace.path / ".patchbench-eval").exists()
            raise EvaluationError("simulated evaluator exception")
        monkeypatch.setattr(evaluation_module.CommandEvaluator, "evaluate", check_and_fail)
        with pytest.raises(EvaluationError, match="simulated"):
            evaluate_patch(manager, workspace, task.evaluation, patch)
        assert list((tmp_path / "workspaces").iterdir()) == [workspace.path]
        assert manager.capture_diff(workspace) == patch
    assert_clean(source, commit, tmp_path / "workspaces")


def test_experiment_inherits_frozen_verdict(tmp_path):
    source, commit, task_path = make_frozen_task(tmp_path)
    experiment = run_experiment(task_path, requested_runs=2,
        configuration=ExperimentConfiguration(agent_name="stub", evaluation_backend="host"),
        agent_factory=lambda: EditingAgent(lambda w: (w / "test_calculator.py").write_text(WEAK_TEST)),
        workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert experiment.aggregate.evaluation_fail_count == 2
    store = FilesystemArtifactStore(tmp_path / "results")
    assert all(store.load_run_record(run_id).evaluation_evidence.tests_run == 1 for run_id in experiment.run_ids)
    assert_clean(source, commit, tmp_path / "workspaces")


@pytest.mark.docker
@pytest.mark.parametrize("fixed", [False, True])
def test_frozen_host_docker_parity(tmp_path, fixed):
    if os.environ.get("PATCHBENCH_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set PATCHBENCH_RUN_DOCKER_TESTS=1 to run Docker tests")
    from patchbench.sandbox.docker import DockerSandbox
    source, commit, task_path = make_frozen_task(tmp_path)
    def edit(workspace):
        if fixed:
            repair(workspace)
        (workspace / "test_calculator.py").write_text(WEAK_TEST)
        (workspace / "test_extra.py").write_text('raise RuntimeError("must not discover")')
        control = workspace / ".patchbench-eval"
        control.mkdir()
        (control / "runner.py").write_text("raise SystemExit(0)")
    records = [run_task(task_path, agent=EditingAgent(edit), agent_name="stub",
                       workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results",
                       sandbox=sandbox) for sandbox in (None, DockerSandbox())]
    assert all(record.evaluation_passed == fixed for record in records)
    assert all(record.evaluation_evidence.tests_run == 1 for record in records)
    assert records[0].artifacts.patch.read_bytes() == records[1].artifacts.patch.read_bytes()
    assert_clean(source, commit, tmp_path / "workspaces")


def test_preparation_patch_error_cleans_second_worktree(tmp_path):
    from patchbench.repository.git_repository import RepositoryError
    source, commit, task_path = make_frozen_task(tmp_path)
    task = load_task(task_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    with manager.workspace(task.repository, "agent") as workspace:
        with pytest.raises(RepositoryError):
            evaluate_patch(manager, workspace, task.evaluation, "not a patch")
        assert list((tmp_path / "workspaces").iterdir()) == [workspace.path]
        assert not (workspace.path / ".patchbench-eval").exists()
    assert_clean(source, commit, tmp_path / "workspaces")


def test_python_environment_does_not_replace_runner_imports(tmp_path, monkeypatch):
    source, commit, task_path = make_frozen_task(tmp_path)
    injected = tmp_path / "injected"
    injected.mkdir()
    (injected / "unittest.py").write_text('raise RuntimeError("PYTHONPATH injection")')
    (injected / "sitecustomize.py").write_text('raise RuntimeError("site injection")')
    monkeypatch.setenv("PYTHONPATH", str(injected))
    record = run_task(task_path, agent=EditingAgent(repair), agent_name="stub",
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    assert record.evaluation_passed
    assert record.evaluation_evidence.tests_run == 1
    assert_clean(source, commit, tmp_path / "workspaces")


@pytest.mark.parametrize("name,tests,failures,errors", [
    ("streaming_events", 33, 8, 6), ("request_signing", 35, 17, 0),
    ("atomic_batch", 36, 10, 0), ("cache_revalidation", 39, 19, 1),
    ("env_config", 25, 27, 0), ("byte_ranges", 29, 12, 4),
    ("config_resolution", 22, 13, 0), ("message_codec", 24, 6, 4),
])
def test_reliability_official_frozen_baselines(tmp_path, name, tests, failures, errors):
    from scripts.prepare_reliability_fixtures import FIXTURE_ROOT, PROJECT_ROOT, prepare_fixture
    from patchbench.domain.evaluation_evidence import render_evaluation_log
    task = load_task(PROJECT_ROOT / "tasks/reliability" / name / "task.yaml")
    source = tmp_path / "source"
    prepare_fixture(FIXTURE_ROOT / name, source, task.repository.base_commit)
    repository = task.repository.model_copy(update={"path": str(source)})
    manager = GitRepositoryManager(tmp_path / "workspaces")
    with manager.workspace(repository, "baseline") as workspace:
        result = evaluate_patch(manager, workspace, task.evaluation, "")
    evidence = summarize_evaluation_log(render_evaluation_log(result, task.evaluation.command))
    assert not result.passed
    assert (evidence.tests_run, evidence.failure_count, evidence.error_count) == (tests, failures, errors)
    assert_clean(source, task.repository.base_commit, tmp_path / "workspaces")
