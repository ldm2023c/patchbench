from pathlib import Path
import shutil

import pytest

from patchbench.config.task_loader import load_task
from scripts.prepare_example_fixture import (
    FixturePreparationError,
    PROJECT_ROOT,
    TASK_PATH,
    prepare_fixture,
)
from tests.helpers import create_fixture_repository, git


def copy_fixture_files(destination: Path) -> None:
    destination.mkdir()
    source = PROJECT_ROOT / "fixtures" / "example_repo"
    shutil.copy2(source / "calculator.py", destination / "calculator.py")
    shutil.copy2(source / "test_calculator.py", destination / "test_calculator.py")


def test_prepare_fixture_creates_expected_commit_and_is_idempotent(tmp_path) -> None:
    fixture = tmp_path / "example_repo"
    copy_fixture_files(fixture)
    expected_commit = load_task(TASK_PATH).repository.base_commit

    assert prepare_fixture(fixture, expected_commit) == expected_commit
    assert prepare_fixture(fixture, expected_commit) == expected_commit


def test_prepare_fixture_rejects_wrong_clean_head_without_overwriting(tmp_path) -> None:
    fixture, original_head = create_fixture_repository(tmp_path)
    expected_commit = load_task(TASK_PATH).repository.base_commit

    with pytest.raises(FixturePreparationError, match="Fixture HEAD mismatch") as error:
        prepare_fixture(fixture, expected_commit)

    assert "Existing Git metadata was left unchanged" in str(error.value)
    assert git(fixture, "rev-parse", "HEAD") == original_head
    assert git(fixture, "status", "--porcelain") == ""
