import pytest

from patchbench.domain.models import RepositoryConfig
from patchbench.repository.git_repository import GitRepositoryManager, GitWorkspace
from tests.helpers import create_fixture_repository, git


def test_workspace_starts_clean_at_configured_base_commit(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    (source / "calculator.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a * b\n", encoding="utf-8"
    )
    git(source, "add", "calculator.py")
    git(
        source,
        "-c",
        "user.name=PatchBench Test",
        "-c",
        "user.email=test@patchbench.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "later source change",
    )
    source_head = git(source, "rev-parse", "HEAD")
    workspace_root = tmp_path / "workspaces"
    manager = GitRepositoryManager(workspace_root)
    configuration = RepositoryConfig(
        type="local", path=str(source), base_commit=base_commit
    )

    with manager.workspace(configuration, "run-001") as workspace:
        assert git(workspace.path, "rev-parse", "HEAD") == base_commit
        assert git(workspace.path, "status", "--porcelain") == ""
        assert "return a - b" in (workspace.path / "calculator.py").read_text()

    assert not (workspace_root / "run-001").exists()
    assert git(source, "rev-parse", "HEAD") == source_head
    assert "return a * b" in (source / "calculator.py").read_text()


def test_workspace_is_cleaned_when_run_step_raises(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    workspace_root = tmp_path / "workspaces"
    manager = GitRepositoryManager(workspace_root)
    configuration = RepositoryConfig(
        type="local", path=str(source), base_commit=base_commit
    )

    with pytest.raises(RuntimeError, match="simulated execution failure"):
        with manager.workspace(configuration, "failed-run"):
            raise RuntimeError("simulated execution failure")

    assert not (workspace_root / "failed-run").exists()
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_capture_diff_includes_modifications_deletions_and_new_files(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    configuration = RepositoryConfig(
        type="local", path=str(source), base_commit=base_commit
    )

    with manager.workspace(configuration, "patch-run") as workspace:
        calculator = workspace.path / "calculator.py"
        calculator.write_text(
            calculator.read_text().replace("return a - b", "return a + b")
        )
        (workspace.path / "test_calculator.py").unlink()
        (workspace.path / "agent_note.txt").write_text("created by agent\n")

        patch = manager.capture_diff(workspace)

    assert "diff --git a/calculator.py b/calculator.py" in patch
    assert "deleted file mode" in patch
    assert "diff --git a/agent_note.txt b/agent_note.txt" in patch
    assert "new file mode 100644" in patch
    assert "+created by agent" in patch


def test_apply_patch_reproduces_captured_changes_without_staging(tmp_path) -> None:
    source, base_commit = create_fixture_repository(tmp_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    configuration = RepositoryConfig(
        type="local", path=str(source), base_commit=base_commit
    )

    with manager.workspace(configuration, "capture") as workspace:
        target = workspace.path / "calculator.py"
        target.write_text(
            target.read_text().replace("return a - b", "return a + b"),
            encoding="utf-8",
        )
        binary_contents = b"\x00\x01historical-binary\xff"
        (workspace.path / "evidence.bin").write_bytes(binary_contents)
        patch = manager.capture_diff(workspace)

    with manager.workspace(configuration, "replay") as workspace:
        manager.apply_patch(workspace, patch)

        assert "return a + b" in (workspace.path / "calculator.py").read_text()
        assert (workspace.path / "evidence.bin").read_bytes() == binary_contents
        assert git(workspace.path, "diff", "--cached") == ""
        assert "calculator.py" in git(workspace.path, "status", "--porcelain")


def test_apply_patch_skips_git_for_empty_patch(tmp_path, monkeypatch) -> None:
    manager = GitRepositoryManager(tmp_path / "workspaces")
    workspace = GitWorkspace(tmp_path / "workspace", tmp_path / "source", "abc")
    monkeypatch.setattr(
        manager,
        "_git",
        lambda *args, **kwargs: pytest.fail("git apply must not run"),
    )

    manager.apply_patch(workspace, " \n\t")
