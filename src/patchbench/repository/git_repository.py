"""Isolated Git workspaces for local PatchBench Runs."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from patchbench.domain.models import RepositoryConfig


class RepositoryError(RuntimeError):
    """Raised when a source repository or Run workspace is invalid."""


@dataclass(frozen=True)
class GitWorkspace:
    """An isolated worktree checked out at a resolved base commit."""

    path: Path
    source_repository: Path
    base_commit: str


class GitRepositoryManager:
    """Create and clean isolated worktrees without modifying their source."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    @contextmanager
    def workspace(
        self, repository: RepositoryConfig, run_id: str
    ) -> Iterator[GitWorkspace]:
        """Yield a clean detached worktree and always remove it afterward."""

        source = Path(repository.path).expanduser().resolve()
        base_commit = self._verify_source(source, repository.base_commit)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace_path = self.workspace_root / run_id

        if workspace_path.exists():
            raise RepositoryError(f"Run workspace already exists: {workspace_path}")

        self._git(
            source,
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(workspace_path),
            base_commit,
        )

        try:
            actual_commit = self._git(workspace_path, "rev-parse", "HEAD").stdout.strip()
            if actual_commit != base_commit:
                raise RepositoryError(
                    f"Workspace HEAD {actual_commit} does not match base commit {base_commit}"
                )

            if self._git(workspace_path, "status", "--porcelain").stdout:
                raise RepositoryError(f"Run workspace is not clean: {workspace_path}")

            yield GitWorkspace(workspace_path, source, base_commit)
        finally:
            self._remove_workspace(source, workspace_path)

    def capture_diff(self, workspace: GitWorkspace) -> str:
        """Return a binary-capable Git diff containing every workspace change."""

        self._git(workspace.path, "add", "-A")
        return self._git(
            workspace.path,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "HEAD",
        ).stdout

    def _verify_source(self, source: Path, configured_commit: str) -> str:
        if not source.is_dir():
            raise RepositoryError(f"Local repository does not exist: {source}")

        top_level = Path(
            self._git(source, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        if top_level != source:
            raise RepositoryError(
                f"Configured repository path is not a Git repository root: {source}"
            )

        return self._git(
            source, "rev-parse", "--verify", f"{configured_commit}^{{commit}}"
        ).stdout.strip()

    def _remove_workspace(self, source: Path, workspace_path: Path) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "worktree",
                "remove",
                "--force",
                str(workspace_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        subprocess.run(
            ["git", "-C", str(source), "worktree", "prune"],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(repository), *arguments],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            raise RepositoryError(
                f"Git command failed for '{repository}': {detail.strip()}"
            ) from error
