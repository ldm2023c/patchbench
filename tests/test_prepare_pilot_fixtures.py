"""Pilot solvability checks; reference repairs never enter agent workspaces."""
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import sys

import pytest

from patchbench.config.task_loader import load_task
from patchbench.repository.git_repository import GitRepositoryManager
from scripts.prepare_pilot_fixtures import (
    PILOTS, PILOT_ROOT, PROJECT_ROOT, FixturePreparationError, git, prepare_fixture,
)


def task_for(name):
    return load_task(PROJECT_ROOT / "tasks" / "pilot" / name / "task.yaml")


def reference_repair(name, workspace):
    """A small witness of solvability, applied only to a disposable worktree."""
    if name == "config_precedence":
        path = workspace / "deployconf" / "cli.py"
        text = path.read_text()
        for field in ("endpoint", "retries", "label"):
            text = text.replace(f'default=DEFAULTS["{field}"]', 'default=None')
        path.write_text(text)
        path = workspace / "deployconf" / "config.py"
        path.write_text(path.read_text().replace('if environment.get(variable):',
                                                'if variable in environment:')
                        .replace('if value:', 'if value is not None:'))
    else:
        path = workspace / "bookmarks" / "codec.py"
        text = path.read_text().replace(
            'fields = [unescape(field) for field in line.split("|")]',
            '''raw_fields = []
    start = 0
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\\\":
            escaped = True
        elif char == "|":
            raw_fields.append(line[start:index])
            start = index + 1
    raw_fields.append(line[start:])
    fields = [unescape(field) for field in raw_fields]''')
        text = text.replace('fields[2] or None if len(fields) == 3 else None',
                            'fields[2] if len(fields) == 3 else None')
        path.write_text(text)


def evaluate(task, workspace):
    # Execute the exact TaskSpec argv; expose this test interpreter as `python`.
    environment = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    return subprocess.run(shlex.split(task.evaluation.command), cwd=workspace,
                          env=environment, capture_output=True, text=True,
                          timeout=task.evaluation.timeout_seconds)


@pytest.mark.parametrize("name", PILOTS)
def test_deterministic_preparation_and_solvability(tmp_path, name):
    task = task_for(name)
    source = PILOT_ROOT / name
    first = tmp_path / "first"
    second = tmp_path / "second"
    for destination in (first, second, first):
        assert prepare_fixture(source, destination, task.repository.base_commit) == task.repository.base_commit
    assert Path(task.repository.path) == PILOT_ROOT / ".prepared" / name
    repository = task.repository.model_copy(update={"path": str(first)})
    manager = GitRepositoryManager(tmp_path / "workspaces")
    with manager.workspace(repository, "validation") as workspace:
        baseline = evaluate(task, workspace.path)
        assert baseline.returncode == 1
        assert f"Ran {16 if name == 'config_precedence' else 14} tests" in baseline.stderr
        assert "FAILED" in baseline.stderr
        expected_failure = ("test_file_used_when_cli_omitted" if name == "config_precedence"
                            else "test_delimiter_in_title")
        assert re.search(rf"^{expected_failure} \([^\n]+\) \.\.\. (FAIL|ERROR)$",
                         baseline.stderr, re.MULTILINE), baseline.stderr
        assert git(workspace.path, "status", "--porcelain") == ""
        reference_repair(name, workspace.path)
        repaired = evaluate(task, workspace.path)
        assert repaired.returncode == 0, repaired.stderr
        assert f"Ran {16 if name == 'config_precedence' else 14} tests" in repaired.stderr
        assert "OK" in repaired.stderr
        changed = git(workspace.path, "diff", "--name-only").splitlines()
        assert changed and all(not p.startswith("test") for p in changed)
    assert list((tmp_path / "workspaces").iterdir()) == []
    assert git(first, "status", "--porcelain") == ""
    assert git(first, "rev-parse", "HEAD") == task.repository.base_commit
    assert git(first, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize("name", PILOTS)
def test_refuses_dirty_or_wrong_head(tmp_path, name):
    source = PILOT_ROOT / name
    destination = tmp_path / "runtime"
    commit = task_for(name).repository.base_commit
    prepare_fixture(source, destination, commit)
    with pytest.raises(FixturePreparationError, match="HEAD mismatch"):
        prepare_fixture(source, destination, "0" * 40)
    assert git(destination, "rev-parse", "HEAD") == commit
    (destination / "README.md").write_text("owner edits\n")
    with pytest.raises(FixturePreparationError, match="not clean"):
        prepare_fixture(source, destination, commit)
    assert (destination / "README.md").read_text() == "owner edits\n"


def test_refuses_unprepared_existing_directory(tmp_path):
    with pytest.raises(FixturePreparationError, match="Not a prepared fixture"):
        prepare_fixture(PILOT_ROOT / PILOTS[0], tmp_path, "unused")


@pytest.mark.parametrize("name", PILOTS)
def test_refuses_template_drift_without_overwriting_runtime(tmp_path, name):
    source = tmp_path / "template"
    shutil.copytree(PILOT_ROOT / name, source, ignore=shutil.ignore_patterns("__pycache__"))
    destination = tmp_path / "runtime"
    commit = task_for(name).repository.base_commit
    prepare_fixture(source, destination, commit)
    (source / "README.md").write_text("changed template\n")
    with pytest.raises(FixturePreparationError, match="template differs"):
        prepare_fixture(source, destination, commit)
    assert git(destination, "status", "--porcelain") == ""
    assert git(destination, "rev-parse", "HEAD") == commit


@pytest.mark.parametrize("name", PILOTS)
def test_preparation_ignores_inherited_git_overrides(tmp_path, monkeypatch, name):
    # A separate real repository/index must remain byte-for-byte untouched.
    source = PILOT_ROOT / name
    commit = task_for(name).repository.base_commit
    decoy = tmp_path / "decoy"
    prepare_fixture(source, decoy, commit)
    index_before = (decoy / ".git" / "index").read_bytes()
    config = tmp_path / "host.gitconfig"
    config.write_text("[i18n]\n    commitEncoding = ISO-8859-1\n")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "i18n.commitEncoding")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "ISO-8859-1")
    destination = tmp_path / "runtime"
    assert prepare_fixture(source, destination, commit) == commit
    assert prepare_fixture(source, destination, commit) == commit
    assert (decoy / ".git" / "index").read_bytes() == index_before
    assert git(decoy, "rev-parse", "HEAD") == commit
    assert git(destination, "rev-parse", "--show-toplevel") == str(destination)
