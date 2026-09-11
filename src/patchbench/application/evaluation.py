"""Shared Run/Replay evaluation with an optional disposable frozen-test view."""

import json
from pathlib import Path
import shutil
import stat
from uuid import uuid4

from patchbench.domain.models import EvaluationConfig, EvaluationResult, RepositoryConfig
from patchbench.evaluators import frozen_runner
from patchbench.evaluators.command import CommandEvaluator, EvaluationError
from patchbench.evaluators.sandbox import SandboxCommandEvaluator
from patchbench.repository.git_repository import GitRepositoryManager, GitWorkspace
from patchbench.sandbox.base import Sandbox, sandbox_scope


def _evaluate(path: Path, configuration: EvaluationConfig, sandbox: Sandbox | None) -> EvaluationResult:
    if sandbox is None:
        return CommandEvaluator().evaluate(path, configuration)
    with sandbox_scope(sandbox, workspace=path) as handle:
        return SandboxCommandEvaluator(sandbox).evaluate(handle, configuration)


def _remove_entry(path: Path) -> None:
    """Remove one root-level evaluation entry without following its symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def evaluate_patch(
    manager: GitRepositoryManager,
    workspace: GitWorkspace,
    configuration: EvaluationConfig,
    patch: str,
    *,
    sandbox: Sandbox | None = None,
) -> EvaluationResult:
    """Evaluate legacy workspace or reconstruct the full patch with frozen tests."""
    frozen = configuration.frozen_unittest
    if frozen is None:
        return _evaluate(workspace.path, configuration, sandbox)

    repository = RepositoryConfig(
        type="local", path=str(workspace.source_repository), base_commit=workspace.base_commit,
    )
    with manager.workspace(repository, f"evaluation-{uuid4().hex}") as official:
        try:
            retained = {}
            for name in frozen.test_files:
                path = official.path / name
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise EvaluationError(f"Frozen test is not a regular base file: {name}")
                retained[name] = path.read_bytes()
            manager.apply_patch(official, patch)
            for name, contents in retained.items():
                path = official.path / name
                _remove_entry(path)
                path.write_bytes(contents)
            control = official.path / ".patchbench-eval"
            _remove_entry(control)
            control.mkdir()
            runner_path = Path(frozen_runner.__file__)
            (control / "runner.py").write_bytes(runner_path.read_bytes())
            (control / "tests.json").write_text(json.dumps(frozen.test_files), encoding="utf-8")
        except OSError as error:
            raise EvaluationError(f"Unable to prepare frozen evaluation: {error}") from error
        return _evaluate(official.path, configuration, sandbox)
