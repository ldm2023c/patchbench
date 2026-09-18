"""Reliability preparation and visible buggy-base checks; no reference repairs."""
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from patchbench.config.task_loader import load_task
from patchbench.repository.git_repository import GitRepositoryManager
from scripts.prepare_reliability_fixtures import (
    CANDIDATES, FIXTURE_ROOT, PROJECT_ROOT, FixturePreparationError,
    git, prepare_fixture, template_files,
)


def task_for(name):
    return load_task(PROJECT_ROOT / "tasks" / "reliability" / name / "task.yaml")


@pytest.mark.parametrize("name", CANDIDATES)
def test_preparation_and_behavioral_baseline(tmp_path, name):
    task = task_for(name)
    assert task.id == name
    assert Path(task.repository.path) == FIXTURE_ROOT / ".prepared" / name
    assert re.fullmatch(r"[0-9a-f]{40}", task.repository.base_commit)
    assert task.evaluation.command == "python -I -S -B .patchbench-eval/runner.py"
    assert task.evaluation.frozen_unittest.version == 1
    assert task.evaluation.frozen_unittest.test_files == [{
        "streaming_events": "test_eventstream.py", "request_signing": "test_websign.py",
        "atomic_batch": "test_batchstore.py", "cache_revalidation": "test_cacheclient.py",
        "env_config": "test_envcfg.py", "byte_ranges": "test_byterange.py",
        "config_resolution": "test_serviceconf.py", "message_codec": "test_msgcodec.py",
    }[name]]
    assert task.evaluation.timeout_seconds == 120
    with TemporaryDirectory(dir=tmp_path) as temporary:
        base = Path(temporary)
        first, second = base / "first", base / "second"
        for destination in (first, second, first):
            assert prepare_fixture(FIXTURE_ROOT / name, destination, task.repository.base_commit) == task.repository.base_commit
        expected = {p.relative_to(FIXTURE_ROOT / name).as_posix() for p in template_files(FIXTURE_ROOT / name)}
        assert set(git(first, "ls-files").splitlines()) == expected
        assert all((first / p).read_bytes() == (FIXTURE_ROOT / name / p).read_bytes() for p in expected)
        assert all(line.startswith("100644 ") for line in git(first, "ls-files", "--stage").splitlines())
        assert git(first, "status", "--porcelain") == ""
        repository = task.repository.model_copy(update={"path": str(first)})
        manager = GitRepositoryManager(base / "workspaces")
        with manager.workspace(repository, "baseline") as workspace:
            result = subprocess.run(shlex.split("python -B -m unittest -v"), cwd=workspace.path,
                                    env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]},
                                    capture_output=True, text=True, timeout=task.evaluation.timeout_seconds)
            assert result.returncode == 1, result.stderr
            failures = {
                "streaming_events": ["test_split_json_record", "test_split_utf8", "test_unicode_byte_limit"],
                "request_signing": ["test_duplicate_query_values", "test_literal_plus", "test_header_ows_collapsed"],
                "atomic_batch": ["test_mid_batch_store_rollback", "test_mid_batch_journal_rollback",
                                 "test_changed_payload_conflict", "test_failed_key_corrected_retry"],
                "cache_revalidation": ["test_304_preserves_validator", "test_replacement_validator",
                                       "test_failed_refresh_does_not_change_entry", "test_expired_error_propagates"],
                "env_config": ["test_present_empty_debug_rejected", "test_present_empty_label",
                               "test_unknown_boolean_rejected", "test_mode_case_is_exact"],
                "byte_ranges": ["test_suffix_short", "test_clips_explicit_end",
                                "test_open_ended_past_end_is_unsatisfiable",
                                "test_large_arbitrary_integer_is_unsatisfiable"],
                "config_resolution": ["test_override_false_wins", "test_override_zero_wins",
                                      "test_override_empty_label_wins",
                                      "test_bad_shadowed_field_is_still_rejected"],
                "message_codec": ["test_canonical_zero_priority_vector", "test_canonical_unicode_bytes",
                                  "test_v1_type_maps_to_kind_and_default_priority", "test_future_version_rejected"],
            }[name]
            for case in failures:
                assert re.search(rf"^{case} \([^\n]+\) \.\.\. (FAIL|ERROR)$", result.stderr, re.MULTILINE), result.stderr
            if name == "env_config":
                for key in ("APP_DEBUG", "APP_WORKERS", "APP_MODE", "APP_LABEL"):
                    for value in (False, 0, None):
                        assert f"(name='{key}', value={value!r}) ... FAIL" in result.stderr
            legacy = {"streaming_events": "test_simple_ascii", "request_signing": "test_simple_legacy_request",
                      "atomic_batch": "test_single_commit", "cache_revalidation": "test_fresh_hit",
                      "env_config": "test_missing_defaults", "byte_ranges": "test_first_byte",
                      "config_resolution": "test_defaults", "message_codec": "test_canonical_ascii_vector"}[name]
            assert re.search(rf"^{legacy} \([^\n]+\) \.\.\. ok$", result.stderr, re.MULTILINE)
            assert "ImportError" not in result.stderr and "ModuleNotFoundError" not in result.stderr
            assert len(re.findall(r" \.\.\. ok$", result.stderr, re.MULTILINE)) >= 10
            assert git(workspace.path, "status", "--porcelain") == ""
        assert list((base / "workspaces").iterdir()) == []
        assert git(first, "worktree", "list", "--porcelain").count("worktree ") == 1
        assert git(first, "status", "--porcelain") == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", CANDIDATES)
def test_refuses_dirty_or_wrong_head_without_overwriting(tmp_path, name):
    destination = tmp_path / "runtime"
    expected = task_for(name).repository.base_commit
    prepare_fixture(FIXTURE_ROOT / name, destination, expected)
    with pytest.raises(FixturePreparationError, match="HEAD mismatch"):
        prepare_fixture(FIXTURE_ROOT / name, destination, "0" * 40)
    assert git(destination, "rev-parse", "HEAD") == expected
    (destination / "README.md").write_text("owner edits\n")
    with pytest.raises(FixturePreparationError, match="not clean"):
        prepare_fixture(FIXTURE_ROOT / name, destination, expected)
    assert (destination / "README.md").read_text() == "owner edits\n"


@pytest.mark.parametrize("name", CANDIDATES)
def test_refuses_template_drift(tmp_path, name):
    source = tmp_path / "template"
    shutil.copytree(FIXTURE_ROOT / name, source, ignore=shutil.ignore_patterns("__pycache__"))
    destination = tmp_path / "runtime"
    expected = task_for(name).repository.base_commit
    prepare_fixture(source, destination, expected)
    (source / "README.md").write_text("changed template\n")
    with pytest.raises(FixturePreparationError, match="template differs"):
        prepare_fixture(source, destination, expected)
    assert git(destination, "rev-parse", "HEAD") == expected
    assert git(destination, "status", "--porcelain") == ""


@pytest.mark.parametrize("name", CANDIDATES)
def test_inherited_git_overrides_do_not_affect_preparation(tmp_path, monkeypatch, name):
    expected = task_for(name).repository.base_commit
    decoy = tmp_path / "decoy"
    prepare_fixture(FIXTURE_ROOT / name, decoy, expected)
    before = (decoy / ".git" / "index").read_bytes()
    config = tmp_path / "gitconfig"
    config.write_text("[i18n]\ncommitEncoding = ISO-8859-1\n")
    for key, value in {"GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy),
                       "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
                       "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": str(config),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "i18n.commitEncoding",
                       "GIT_CONFIG_VALUE_0": "ISO-8859-1"}.items():
        monkeypatch.setenv(key, value)
    assert prepare_fixture(FIXTURE_ROOT / name, tmp_path / "runtime", expected) == expected
    assert (decoy / ".git" / "index").read_bytes() == before


def test_parent_repository_hygiene():
    for name in CANDIDATES:
        assert not (FIXTURE_ROOT / name / ".git").exists()
        ignored = subprocess.run(["git", "check-ignore", f"fixtures/reliability/.prepared/{name}/.git/config"],
                                 cwd=PROJECT_ROOT, capture_output=True, text=True)
        assert ignored.returncode == 0
    entries = git(PROJECT_ROOT, "ls-files", "--stage", "fixtures/reliability")
    assert not any(line.startswith("160000 ") or "/.prepared/" in line or "/.git/" in line for line in entries.splitlines())
