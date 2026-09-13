"""Deterministic compilation tests using disposable source and Run artifacts."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import os

import pytest
import yaml

from patchbench.application.diagnosis_evidence import (
    DiagnosisCompilationError, DiagnosisCompilationReason,
    _canonical_json, _collect_snapshot, _policy_identity, _snapshot_hash,
    _verify_inputs, _reconstruct,
    compile_diagnosis_evidence,
)
from patchbench.domain import (DiagnosisSourcePolicy, RunProvenance, EvaluationResult,
    compute_task_fingerprint, render_evaluation_log, summarize_patch, summarize_evaluation_log)
from patchbench.domain.models import FROZEN_UNITTEST_COMMAND
from patchbench.config.task_loader import load_task
from patchbench.repository.git_repository import GitRepositoryManager
from patchbench.storage.filesystem import FilesystemArtifactStore
from tests.helpers import git
from tests.test_replay import make_run


def write_files(root, files):
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)


def test_snapshot_complete_exact_sorted_and_explicit_exclusions(tmp_path):
    files = {"src/b.py": b"\xef\xbb\xbf b \r\n", "src/a.py": b"a\n", "empty.py": b"",
             "vendor/x": b"vendor", "generated/x": b"generated", "node_modules/x": b"node",
             ".venv/x": b"venv", "build/x": b"build", "dist/x": b"dist", "results/x": b"result",
             "docs/x": b"excluded", "test_frozen.py": b"frozen", "tests/helper.py": b"included",
             "src/__pycache__/x": b"\x00", ".git/config": b"git", ".patchbench-eval/runner.py": b"runner",
             ".pytest_cache/x": b"cache", ".mypy_cache/x": b"cache", ".ruff_cache/x": b"cache"}
    write_files(tmp_path, files)
    policy = DiagnosisSourcePolicy(production_roots=["."], excluded_paths=["docs"])
    actual, present = _collect_snapshot(tmp_path, policy, ["test_frozen.py"])
    expected = {name: contents for name, contents in files.items()
                if name not in {"docs/x", "test_frozen.py", "src/__pycache__/x", ".git/config",
                                ".patchbench-eval/runner.py", ".pytest_cache/x", ".mypy_cache/x", ".ruff_cache/x"}}
    assert actual == expected
    assert list(actual) == sorted(actual)
    assert present == {"."}


def test_snapshot_and_policy_hashes_are_order_independent(tmp_path):
    files = {"b.py": b"b", "a.py": b"a"}
    one, two = tmp_path / "one", tmp_path / "two"
    write_files(one, files)
    write_files(two, dict(reversed(list(files.items()))))
    policies = [DiagnosisSourcePolicy(production_roots=roots, excluded_paths=exclusions)
                for roots, exclusions in [(["a.py", "b.py"], ["x", "y"]), (["b.py", "a.py"], ["y", "x"])]]
    first, _ = _collect_snapshot(one, policies[0], [])
    second, _ = _collect_snapshot(two, policies[1], [])
    assert first == second
    assert _snapshot_hash(first) == _snapshot_hash(second)
    assert _policy_identity(policies[0]) == _policy_identity(policies[1])
    assert _snapshot_hash({"a": b"same"}) != _snapshot_hash({"b": b"same"})
    assert _snapshot_hash(files, order=["a.py", "b.py"]) != _snapshot_hash(files, order=["b.py", "a.py"])
    expected = b'{"files":[],"snapshot_version":1}'
    assert _snapshot_hash({}) == hashlib.sha256(expected).hexdigest()
    assert _canonical_json({"b": "雪", "a": 1}) == '{"a":1,"b":"雪"}'.encode()


@pytest.mark.parametrize("contents", [b"\xff", b"\x00binary"])
def test_included_binary_rejected_not_silently_skipped(tmp_path, contents):
    write_files(tmp_path, {"src/blob": contents})
    with pytest.raises(DiagnosisCompilationError) as caught:
        _collect_snapshot(tmp_path, DiagnosisSourcePolicy(production_roots=["src"]), [])
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_SOURCE


@pytest.mark.parametrize("declared", ["link", "link/file.py", "."])
def test_snapshot_never_follows_symlink(tmp_path, declared):
    external = tmp_path / "external"
    write_files(external, {"file.py": b"secret"})
    root = tmp_path / "source"
    root.mkdir()
    (root / "link").symlink_to(external, target_is_directory=True)
    with pytest.raises(DiagnosisCompilationError) as caught:
        _collect_snapshot(root, DiagnosisSourcePolicy(production_roots=[declared]), [])
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_SOURCE
    snapshot, _ = _collect_snapshot(root, DiagnosisSourcePolicy(production_roots=["."], excluded_paths=["link"]), [])
    assert snapshot == {}


@pytest.fixture
def historical(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-01-01T00:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00+00:00")

    def create(*, files=None, edit=None, roots=None, excluded=None, frozen=True):
        root = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        root.mkdir()
        source = root / "repo"
        frozen_bytes = b"import unittest\n# trusted frozen test\n"
        write_files(source, files if files is not None else {"src/a.py": b"a = 1\n", "src/b.py": b"b = 2\n"})
        write_files(source, {"test_frozen.py": frozen_bytes})
        git(source, "init", "-q")
        git(source, "config", "user.name", "Test")
        git(source, "config", "user.email", "test@example.invalid")
        git(source, "config", "core.autocrlf", "false")
        git(source, "add", "-A")
        git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "base")
        commit = git(source, "rev-parse", "HEAD")
        task_path = root / "task.yaml"
        evaluation = dict(command=FROZEN_UNITTEST_COMMAND if frozen else "python -m unittest", timeout_seconds=120)
        if frozen:
            evaluation["frozen_unittest"] = dict(version=1, test_files=["test_frozen.py"])
        task_path.write_text(yaml.safe_dump(dict(schema_version=1, id="task",
            repository=dict(type="local", path="repo", base_commit=commit), task=dict(prompt="Fix the task."),
            evaluation=evaluation)), encoding="utf-8")
        task = load_task(task_path)
        manager = GitRepositoryManager(root / "workspaces")
        with manager.workspace(task.repository, "historical") as workspace:
            if edit:
                edit(workspace.path)
            patch = manager.capture_diff(workspace)
        record = make_run(root / "results", run_id="subject", task_id="task", evaluation_passed=False)
        record.provenance = RunProvenance(base_commit_used=commit,
            task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used=commit),
            evaluation_command=evaluation["command"], evaluation_timeout_seconds=120, evaluation_backend="host")
        log = render_evaluation_log(EvaluationResult(exit_code=1, passed=False, duration_seconds=1,
            stdout="", stderr="FAIL: test_contract (tests.Contract)\n\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"), evaluation["command"])
        record.patch_summary = summarize_patch(patch)
        record.evaluation_evidence = summarize_evaluation_log(log)
        record.artifacts.directory.mkdir(parents=True)
        record.artifacts.metadata.write_text(record.model_dump_json())
        record.artifacts.patch.write_bytes(patch.encode())
        record.artifacts.test_log.write_bytes(log.encode())
        record.artifacts.agent_log.write_text("The bug is definitely in b.py")
        return dict(task_path=task_path, run_id="subject", benchmark_definition_sha256="b" * 64,
            expected_task_contract_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
            source_policy=DiagnosisSourcePolicy(production_roots=roots or ["src"], excluded_paths=excluded or []),
            max_bundle_json_bytes=1_000_000, artifact_store=FilesystemArtifactStore(root / "results"),
            repository_manager=manager)
    return create


def verified(case):
    return _verify_inputs(case["task_path"], case["run_id"], case["expected_task_contract_sha256"], case["artifact_store"])


def reconstruct(case):
    return _reconstruct(verified(case), case["source_policy"], case["repository_manager"])


def test_reconstruction_uses_historical_base_and_keeps_untouched_source(historical):
    def edit(path):
        write_files(path, {"src/a.py": b"a = 3\n", "test_frozen.py": b"# Agent weakened tests\n"})
    case = historical(edit=edit, roots=["."])
    source = case["task_path"].parent / "repo"
    write_files(source, {"src/b.py": b"future HEAD\n"})
    git(source, "add", "-A")
    git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "later")
    before = git(source, "rev-parse", "HEAD")
    base, candidate, frozen = reconstruct(case)
    assert base == {"src/a.py": b"a = 1\n", "src/b.py": b"b = 2\n"}
    assert candidate == {"src/a.py": b"a = 3\n", "src/b.py": b"b = 2\n"}
    assert frozen == {"test_frozen.py": b"import unittest\n# trusted frozen test\n"}
    assert "Agent weakened" in verified(case).patch
    assert git(source, "rev-parse", "HEAD") == before
    assert not list(case["repository_manager"].workspace_root.iterdir())


@pytest.mark.parametrize("action", ["add", "delete", "rename", "empty_patch"])
def test_reconstruction_added_deleted_empty_snapshots(historical, action):
    def edit(path):
        if action == "add":
            write_files(path, {"new.py": b""})
        elif action == "delete":
            (path / "old.py").unlink()
        elif action == "rename":
            (path / "old.py").rename(path / "new.py")
    roots = ["new.py"] if action == "add" else ["old.py"] if action == "delete" else ["."]
    case = historical(files={"old.py": b"old\n"}, edit=edit, roots=roots)
    base, candidate, _ = reconstruct(case)
    if action == "add":
        assert base == {} and candidate == {"new.py": b""}
    elif action == "delete":
        assert base == {"old.py": b"old\n"} and candidate == {}
    elif action == "rename":
        assert base == {"old.py": b"old\n"} and candidate == {"new.py": b"old\n"}
    else:
        assert verified(case).patch == ""
        assert base == candidate


def test_missing_root_in_both_states_fails_and_cleans(historical):
    case = historical(roots=["missing"])
    with pytest.raises(DiagnosisCompilationError) as caught:
        reconstruct(case)
    assert caught.value.reason is DiagnosisCompilationReason.SOURCE_UNAVAILABLE
    assert not list(case["repository_manager"].workspace_root.iterdir())


@pytest.mark.parametrize("filename", ["patch.diff", "test.log"])
def test_raw_artifact_tampering_fails_before_reconstruction(historical, filename):
    case = historical()
    path = case["artifact_store"].results_root / "subject" / filename
    path.write_text("tampered")
    with pytest.raises(DiagnosisCompilationError) as caught:
        verified(case)
    assert caught.value.reason is DiagnosisCompilationReason.RUN_EVIDENCE_MISMATCH


def mutate_run(case, mutate):
    path = case["artifact_store"].results_root / "subject/metadata.json"
    data = json.loads(path.read_bytes())
    mutate(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("change,reason", [
    (lambda r: r.update(provenance=None), "missing_run_evidence"),
    (lambda r: r.update(patch_summary=None, evaluation_evidence=None), "missing_run_evidence"),
    (lambda r: r["agent"].update(status="command_failed"), "not_semantic_run"),
    (lambda r: r["agent"].update(status="timed_out"), "not_semantic_run"),
    (lambda r: r["provenance"].update(task_fingerprint_sha256="c" * 64), "run_provenance_mismatch"),
    (lambda r: r["provenance"].update(base_commit_used="HEAD"), "run_provenance_mismatch"),
    (lambda r: r["provenance"].update(evaluation_command="other"), "run_provenance_mismatch"),
    (lambda r: r["provenance"].update(evaluation_timeout_seconds=9), "run_provenance_mismatch"),
])
def test_required_run_evidence_and_semantics(historical, change, reason):
    case = historical()
    mutate_run(case, change)
    with pytest.raises(DiagnosisCompilationError) as caught:
        verified(case)
    assert caught.value.reason.value == reason


def test_raw_task_hash_and_unsupported_evaluator(historical):
    case = historical()
    case["expected_task_contract_sha256"] = "c" * 64
    with pytest.raises(DiagnosisCompilationError) as caught:
        verified(case)
    assert caught.value.reason is DiagnosisCompilationReason.TASK_CONTRACT_MISMATCH
    case = historical(frozen=False)
    with pytest.raises(DiagnosisCompilationError) as caught:
        verified(case)
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_EVALUATOR


def test_exact_patch_reconstruction_required(historical, monkeypatch):
    case = historical(edit=lambda root: write_files(root, {"src/a.py": b"modified\n"}))
    manager = case["repository_manager"]
    original = manager.capture_diff
    monkeypatch.setattr(manager, "capture_diff", lambda workspace: original(workspace) + "\n")
    with pytest.raises(DiagnosisCompilationError) as caught:
        reconstruct(case)
    assert caught.value.reason is DiagnosisCompilationReason.PATCH_RECONSTRUCTION_FAILED
    assert not list(manager.workspace_root.iterdir())


def source_items(bundle):
    return {(item.source_state.value, item.path): item for item in bundle.evidence_items
            if item.kind.value == "production_source"}


def snapshot_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_full_bundle_complete_deterministic_and_read_only(historical, monkeypatch):
    case = historical(edit=lambda root: write_files(root, {"src/a.py": b"a = 3\n"}))
    results = case["artifact_store"].results_root
    before = snapshot_tree(results)
    original_read = Path.read_bytes
    def guard(path):
        if path.name in {"agent.log", "agent.stderr.log"}:
            pytest.fail("Compiler must not read Agent self-report")
        return original_read(path)
    monkeypatch.setattr(Path, "read_bytes", guard)
    first = compile_diagnosis_evidence(**case)
    second = compile_diagnosis_evidence(**case)
    assert first == second
    assert first.bundle_id == second.bundle_id
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.provenance == second.provenance
    assert [item.evidence_id for item in first.evidence_items] == [f"E{i:03d}" for i in range(1, len(first.evidence_items) + 1)]
    sources = source_items(first)
    assert set(sources) == {("base", "src/a.py"), ("base", "src/b.py"),
                            ("candidate", "src/a.py"), ("candidate", "src/b.py")}
    assert sources["candidate", "src/b.py"].content == "b = 2\n"
    assert sources["base", "src/a.py"].owner.value == "benchmark"
    assert sources["candidate", "src/a.py"].owner.value == "subject"
    for item in first.evidence_items:
        assert item.artifact_sha256 == hashlib.sha256(item.content.encode()).hexdigest()
    encoded = _canonical_json(first.model_dump(mode="json"))
    assert b"The bug is definitely in b.py" not in encoded
    # Host-path restrictions apply outside exact raw evidence content.
    structured = first.model_dump(mode="json")
    for item in structured["evidence_items"]:
        item.pop("content")
    structured_bytes = _canonical_json(structured)
    assert str(case["task_path"].parent).encode() not in structured_bytes
    assert b"diagnosis-" not in structured_bytes
    assert first.mode.value == "blind" and first.peer_run_id is None and first.provenance.peer is None
    assert {item.kind.value for item in first.evidence_items} == {"task_contract", "production_source",
        "frozen_test", "canonical_patch", "evaluation_output"}
    # Independently spell canonical serialization for the externally visible hash.
    material = first.model_dump(mode="json")
    material.pop("bundle_sha256")
    assert first.bundle_sha256 == hashlib.sha256(json.dumps(material, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    monkeypatch.setattr(Path, "read_bytes", original_read)
    assert snapshot_tree(results) == before
    assert not list(case["repository_manager"].workspace_root.iterdir())


def test_raw_absolute_paths_preserved_without_host_specific_structured_paths(historical):
    raw = b'LOCATION = "/home/example/project/file.py"\nSCRATCH = "/tmp/run-123/file.py"\n'
    case = historical(files={"src/a.py": raw})
    first = compile_diagnosis_evidence(**case)
    second = compile_diagnosis_evidence(**case)
    assert first == second
    assert first.bundle_id == second.bundle_id
    assert first.bundle_sha256 == second.bundle_sha256
    for state in ("base", "candidate"):
        item = source_items(first)[state, "src/a.py"]
        assert item.content.encode("utf-8") == raw
        assert '"/home/example/project/file.py"' in item.content
        assert '"/tmp/run-123/file.py"' in item.content

    # Inspect all generated structure, including policy, identity and provenance,
    # without treating opaque raw evidence as compiler-generated metadata.
    structured = first.model_dump(mode="json")
    for item in structured["evidence_items"]:
        item.pop("content")
        path = item["path"]
        if path is not None:
            assert not PurePosixPath(path).is_absolute()
            assert ".." not in PurePosixPath(path).parts
            assert "\\" not in path
            assert PurePosixPath(path).as_posix() == path
    structured_bytes = _canonical_json(structured)
    for host_path in (case["task_path"].parent,
                      case["task_path"].parent / "repo",
                      case["repository_manager"].workspace_root):
        assert str(host_path).encode("utf-8") not in structured_bytes
    assert b"diagnosis-" not in structured_bytes
    assert b"/home/" not in structured_bytes
    assert b"/tmp/" not in structured_bytes


def test_bundle_frozen_tests_are_base_truth_and_never_production(historical):
    case = historical(roots=["."], edit=lambda root: write_files(root, {"test_frozen.py": b"# weakened\n"}))
    bundle = compile_diagnosis_evidence(**case)
    frozen = next(item for item in bundle.evidence_items if item.kind.value == "frozen_test")
    patch = next(item for item in bundle.evidence_items if item.kind.value == "canonical_patch")
    assert frozen.content == "import unittest\n# trusted frozen test\n"
    assert frozen.owner.value == "benchmark" and frozen.source_state.value == "frozen"
    assert "# weakened" in patch.content
    assert not any(path == "test_frozen.py" for _, path in source_items(bundle))


def test_bundle_empty_patch_and_source_are_exact_zero_line_items(historical):
    case = historical(files={"src/empty.py": b""})
    bundle = compile_diagnosis_evidence(**case)
    for item in bundle.evidence_items:
        if item.kind.value in {"canonical_patch", "production_source"}:
            assert item.content == ""
            assert item.start_line is item.end_line is None
            assert item.artifact_sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("action", ["add", "delete", "rename"])
def test_bundle_added_deleted_and_renamed_paths(historical, action):
    def edit(root):
        if action == "delete":
            (root / "src/a.py").unlink()
        elif action == "rename":
            (root / "src/a.py").rename(root / "src/new.py")
        else:
            write_files(root, {"src/new.py": b"new\n"})
    case = historical(edit=edit)
    paths = source_items(compile_diagnosis_evidence(**case))
    assert ("base", "src/a.py") in paths
    assert (("candidate", "src/a.py") in paths) == (action == "add")
    assert (("candidate", "src/new.py") in paths) == (action != "delete")
    assert ("base", "src/new.py") not in paths


def test_bundle_size_gate_uses_final_compact_utf8_bytes_without_fallback(historical):
    case = historical(files={"src/a.py": "雪\n".encode(), "src/untouched.py": b"x" * 3000})
    bundle = compile_diagnosis_evidence(**case)
    size = len(_canonical_json(bundle.model_dump(mode="json")))
    assert compile_diagnosis_evidence(**(case | {"max_bundle_json_bytes": size})) == bundle
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**(case | {"max_bundle_json_bytes": size - 1}))
    assert caught.value.reason is DiagnosisCompilationReason.BUNDLE_TOO_LARGE
    assert not list(case["repository_manager"].workspace_root.iterdir())


def test_creation_order_and_host_location_do_not_change_bundle(historical):
    files = {"src/b.py": b"b\n", "src/a.py": b"a\n"}
    first = historical(files=files)
    second = historical(files=dict(reversed(list(files.items()))))
    assert first["expected_task_contract_sha256"] == second["expected_task_contract_sha256"]
    assert compile_diagnosis_evidence(**first) == compile_diagnosis_evidence(**second)


def test_current_head_and_task_mutable_ref_are_not_historical_truth(historical):
    case = historical()
    # The supplied raw contract can contain a mutable ref; its externally pinned
    # bytes must still match, while resolved Run provenance owns historical base.
    path = case["task_path"]
    raw = yaml.safe_load(path.read_text())
    raw["repository"]["base_commit"] = "HEAD"
    path.write_text(yaml.safe_dump(raw))
    case["expected_task_contract_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = path.parent / "repo"
    write_files(source, {"src/b.py": b"later HEAD\n"})
    git(source, "add", "-A")
    git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "later")
    bundle = compile_diagnosis_evidence(**case)
    assert source_items(bundle)["candidate", "src/b.py"].content == "b = 2\n"
    assert bundle.base_commit != git(source, "rev-parse", "HEAD")


@pytest.mark.parametrize("state", ["base", "candidate"])
@pytest.mark.parametrize("kind", ["binary", "symlink"])
def test_compiler_rejects_included_unsupported_source_and_cleans(historical, state, kind):
    def introduce(root):
        path = root / "src/unsupported"
        if kind == "symlink":
            path.symlink_to("a.py")
        else:
            path.write_bytes(b"\x00binary")
    if state == "candidate":
        case = historical(edit=introduce)
    else:
        case = historical(files={"src/a.py": b"a\n", "src/unsupported": b"\x00binary"})
        if kind == "symlink":
            # Supply a snapshot fixture with a symlink at the committed base.
            source = case["task_path"].parent / "repo"
            (source / "src/unsupported").unlink()
            introduce(source)
            git(source, "add", "-A")
            git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "symlink base")
            commit = git(source, "rev-parse", "HEAD")
            task = load_task(case["task_path"])
            mutate_run(case, lambda r: r["provenance"].update(base_commit_used=commit,
                task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used=commit)))
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_SOURCE
    assert not list(case["repository_manager"].workspace_root.iterdir())


def test_compiler_policy_exclusions_and_exact_source_bytes(historical):
    contents = b"\xef\xbb\xbf  value = 1\r\n\r\n"
    case = historical(files={"src/a.py": contents, "src/vendor/blob": b"\xff",
        "src/__pycache__/noise": b"\x00", "src/generated/data": b"keep"}, excluded=["src/vendor"])
    bundle = compile_diagnosis_evidence(**case)
    paths = source_items(bundle)
    assert set(paths) == {(state, path) for state in ("base", "candidate")
                         for path in ("src/a.py", "src/generated/data")}
    assert paths["candidate", "src/a.py"].content.encode() == contents
    assert paths["candidate", "src/a.py"].end_line == 2


@pytest.mark.parametrize("field,value", [("id", "other-task"), ("task", {"prompt": "Different contract"})])
def test_raw_contract_pinning_does_not_replace_semantic_identity(historical, field, value):
    case = historical()
    path = case["task_path"]
    data = yaml.safe_load(path.read_text())
    data[field] = value
    path.write_text(yaml.safe_dump(data))
    case["expected_task_contract_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.RUN_PROVENANCE_MISMATCH


def test_official_pass_rejected_before_source_reconstruction(historical, monkeypatch):
    case = historical()
    def passing(record):
        record.update(status="passed", evaluation_passed=True)
        record["evaluation_evidence"].update(passed=True, exit_code=0)
    mutate_run(case, passing)
    monkeypatch.setattr(case["repository_manager"], "workspace", lambda *a: pytest.fail("Must not reconstruct PASS"))
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.NOT_SEMANTIC_RUN


def test_explicitly_excluded_root_exists_but_contributes_no_source(historical):
    case = historical(excluded=["src"])
    bundle = compile_diagnosis_evidence(**case)
    assert source_items(bundle) == {}
    assert bundle.provenance.subject.base_source_snapshot_sha256 == _snapshot_hash({})
    assert bundle.provenance.subject.candidate_source_snapshot_sha256 == _snapshot_hash({})


def test_included_special_file_is_rejected_without_reading(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(DiagnosisCompilationError) as caught:
        _collect_snapshot(tmp_path, DiagnosisSourcePolicy(production_roots=["."]), [])
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_SOURCE


def test_patch_apply_error_is_typed_and_worktree_is_cleaned(historical, monkeypatch):
    from patchbench.repository.git_repository import RepositoryError
    case = historical()
    def fail(*args):
        raise RepositoryError("cannot apply patch")
    monkeypatch.setattr(case["repository_manager"], "apply_patch", fail)
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.PATCH_RECONSTRUCTION_FAILED
    assert not list(case["repository_manager"].workspace_root.iterdir())


def test_frozen_snapshot_hash_preserves_declared_order(historical):
    case = historical(files={"src/a.py": b"a\n", "test_z.py": b"# z\n", "test_a.py": b"# a\n"})
    path = case["task_path"]
    for order in (["test_z.py", "test_a.py"], ["test_a.py", "test_z.py"]):
        raw = yaml.safe_load(path.read_text())
        raw["evaluation"]["frozen_unittest"]["test_files"] = order
        path.write_text(yaml.safe_dump(raw))
        case["expected_task_contract_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        task = load_task(path)
        mutate_run(case, lambda r: r["provenance"].update(task_fingerprint_sha256=
            compute_task_fingerprint(task, base_commit_used=r["provenance"]["base_commit_used"])))
        bundle = compile_diagnosis_evidence(**case)
        expected = {"snapshot_version": 1, "files": [{"path": name,
            "sha256": hashlib.sha256((path.parent / "repo" / name).read_bytes()).hexdigest(),
            "byte_length": len((path.parent / "repo" / name).read_bytes())} for name in order]}
        assert bundle.provenance.subject.frozen_tests_snapshot_sha256 == hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_missing_historical_commit_is_typed(historical):
    case = historical()
    task = load_task(case["task_path"])
    mutate_run(case, lambda r: r["provenance"].update(base_commit_used="0" * 40,
        task_fingerprint_sha256=compute_task_fingerprint(task, base_commit_used="0" * 40)))
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.SOURCE_UNAVAILABLE
    assert not list(case["repository_manager"].workspace_root.iterdir())


def test_source_locator_is_never_silently_trimmed(historical):
    case = historical(files={"src/a.py ": b"text\n"})
    with pytest.raises(DiagnosisCompilationError) as caught:
        compile_diagnosis_evidence(**case)
    assert caught.value.reason is DiagnosisCompilationReason.UNSUPPORTED_SOURCE
