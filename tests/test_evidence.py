import hashlib
import json
import sys

import pytest
from pydantic import ValidationError

from patchbench.agents.fake import FakeAgent
from patchbench.application.local_run import run_task
from patchbench.application.experiment import run_experiment
from patchbench.application.replay import replay_run
from patchbench.domain import (
    EvidenceParsingError, EvaluationEvidence, EvaluationResult,
    ExperimentConfiguration, PatchFileSummary, PatchSummary, RunRecord,
    render_evaluation_log, summarize_evaluation_log, summarize_patch,
)
from patchbench.repository import GitRepositoryManager
from patchbench.storage import FilesystemArtifactStore
from tests.helpers import create_fixture_repository, git, write_run_task
from tests.test_local_run import RecordingSandbox
from tests.test_replay import FIX_PATCH, make_run, make_task


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def modified(path="app.py", replacement="new"):
    return (f"diff --git a/{path} b/{path}\nindex 123..456 100644\n"
            f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+{replacement}\n")


def test_empty_patch():
    assert summarize_patch("").model_dump() == dict(
        patch_sha256=sha(""), patch_bytes=0, changed_file_count=0,
        text_added_lines=0, text_deleted_lines=0, files=[])


def test_exact_patch_and_file_identities_preserve_pass_variation():
    production = modified("app.py", "新")
    test_a, test_b = modified("tests/test_app.py", "assert first"), modified("tests/test_app.py", "assert second")
    first, second = summarize_patch(production + test_a), summarize_patch(production + test_b)
    assert first == summarize_patch(production + test_a)
    assert first.patch_sha256 == sha(production + test_a)
    assert first.patch_bytes == len((production + test_a).encode("utf-8"))
    assert first.changed_file_count == 2
    assert (first.text_added_lines, first.text_deleted_lines) == (2, 2)
    assert first.files[0].diff_sha256 == second.files[0].diff_sha256 == sha(production)
    assert first.files[1].diff_sha256 == sha(test_a)
    assert first.files[1].diff_sha256 != second.files[1].diff_sha256
    assert first.patch_sha256 != second.patch_sha256
    assert summarize_patch(production.replace("@@ -1 +1 @@", "@@ -9 +9 @@")).patch_sha256 != sha(production)
    assert summarize_patch(production.rstrip("\n")).patch_sha256 != sha(production)


@pytest.mark.parametrize("path,role", [
    ("README.md", "non_test"), ("config.yaml", "non_test"), ("latest/a.py", "non_test"),
    ("tests/helper.txt", "test"), ("test_app.py", "test"), ("app_test.py", "test"),
    ("tests/__pycache__/test_app.pyc", "generated"), ("test_app.pyc", "generated"),
    ("app.pyo", "generated"), ("__pycache__/data", "generated"),
])
def test_path_roles(path, role):
    assert summarize_patch(modified(path)).files[0].role == role


@pytest.mark.parametrize("kind,patch,path,counts", [
    ("added", "diff --git a/new.py b/new.py\nnew file mode 100644\nindex 000..123\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x\n", "new.py", (1, 0)),
    ("deleted", "diff --git a/old.py b/old.py\ndeleted file mode 100644\nindex 123..000\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n", "old.py", (0, 1)),
    ("renamed", "diff --git a/old name b/new name\nsimilarity index 100%\nrename from old name\nrename to new name\n", "new name", (0, 0)),
    ("copied", "diff --git a/old.py b/new.py\nsimilarity index 100%\ncopy from old.py\ncopy to new.py\n", "new.py", (0, 0)),
    ("modified", "diff --git a/app.py b/app.py\nold mode 100644\nnew mode 100755\n", "app.py", (0, 0)),
    ("added", "diff --git a/empty b/empty\nnew file mode 100644\nindex 0000000..e69de29\n", "empty", (0, 0)),
])
def test_change_types(kind, patch, path, counts):
    file = summarize_patch(patch).files[0]
    assert (file.change_type, file.path, file.binary) == (kind, path, False)
    assert (file.added_lines, file.deleted_lines) == counts
    assert file.diff_sha256 == sha(patch)


def test_hunk_counts_include_header_like_content_not_headers_or_markers():
    patch = ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
             "@@ -1,2 +1,2 @@\n context\n--- removed text\n+++ added text\n"
             "\\ No newline at end of file\n@@ -7 +7 @@\n-old\n"
             "\\ No newline at end of file\n+new\n\\ No newline at end of file\n")
    result = summarize_patch(patch)
    assert (result.text_added_lines, result.text_deleted_lines) == (2, 2)


@pytest.mark.parametrize("path", ["space name.py", "a b/more space.py"])
def test_unquoted_spaces(path):
    assert summarize_patch(modified(path)).files[0].path == path


def test_quoted_git_paths():
    quoted = r'"a/\346\226\260\tname.py" "b/\346\226\260\tname.py"'
    patch = ('diff --git ' + quoted + '\nold mode 100644\nnew mode 100755\n')
    assert summarize_patch(patch).files[0].path == "新\tname.py"


@pytest.mark.parametrize("patch", [
    "garbage", " \n", "diff --git a/app.py b/app.py\n",
    modified().replace("@@ -1 +1 @@", "@@ -2,3 +2,3 @@"),
    modified().replace("+++ b/app.py", "+++ b/wrong.py"),
    modified() + "unexpected trailing content\n",
    "diff --git a/a b/b\nrename from a\n",
    "diff --git a/a b/a\nGIT binary patch\n",
    "diff --git a/a b/a\nunknown metadata\n",
])
def test_malformed_patch_refused(patch):
    with pytest.raises(EvidenceParsingError):
        summarize_patch(patch)


def test_binary_notice():
    patch = "diff --git a/data.bin b/data.bin\nindex 123..456 100644\nBinary files a/data.bin and b/data.bin differ\n"
    file = summarize_patch(patch).files[0]
    assert file.binary and file.added_lines is None and file.deleted_lines is None
    assert file.diff_sha256 == sha(patch)


def test_real_git_patch_binary_quoted_paths_and_empty_files(tmp_path):
    source, commit = create_fixture_repository(tmp_path)
    manager = GitRepositoryManager(tmp_path / "workspaces")
    task = make_task(source, commit)
    with manager.workspace(task.repository, "capture") as workspace:
        (workspace.path / "space name.txt").write_text("new\n")
        (workspace.path / "新\tname.py").write_text("unicode\n")
        (workspace.path / "empty").touch()
        (workspace.path / "blob.bin").write_bytes(bytes(range(256)))
        patch = manager.capture_diff(workspace)
    summary = summarize_patch(patch)
    assert summary.patch_sha256 == sha(patch)
    files = {file.path: file for file in summary.files}
    assert set(files) == {"space name.txt", "新\tname.py", "empty", "blob.bin"}
    assert all(file.change_type == "added" for file in files.values())
    assert files["blob.bin"].binary
    assert files["blob.bin"].added_lines is None
    assert summary.text_added_lines == 2


def log(output="", *, exit_code=0, stream="stderr", command="python -m unittest"):
    return render_evaluation_log(EvaluationResult(
        exit_code=exit_code, passed=exit_code == 0, duration_seconds=1.23456789,
        stdout=output if stream == "stdout" else "",
        stderr=output if stream == "stderr" else ""), command)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("verdict", ["OK", "OK (skipped=1)", "OK (expected failures=1)"])
def test_successful_unittest(stream, verdict):
    text = log(f"test_a ... ok\n\nRan 2 tests in 0.010s\n\n{verdict}\n", stream=stream)
    evidence = summarize_evaluation_log(text)
    assert (evidence.framework, evidence.tests_run, evidence.failure_count, evidence.error_count) == ("unittest", 2, 0, 0)
    assert evidence.failing_cases == [] and evidence.passed
    assert evidence.duration_seconds == 1.234568
    assert evidence.test_log_sha256 == sha(text)


@pytest.mark.parametrize("counts,expected", [("failures=2", (2, 0)), ("errors=1", (0, 1)), ("failures=2, errors=1", (2, 1))])
def test_failed_unittest_counts_and_case_order(counts, expected):
    text = log(f"FAIL: case A (tests.A)\ntraceback\nERROR: case B (tests.B)\n"
               f"\nRan 3 tests in 0.010s\n\nFAILED ({counts})", exit_code=1)
    evidence = summarize_evaluation_log(text)
    assert evidence.framework == "unittest"
    assert evidence.tests_run == 3
    assert (evidence.failure_count, evidence.error_count) == expected
    assert [(c.name, c.outcome) for c in evidence.failing_cases] == [("case A (tests.A)", "fail"), ("case B (tests.B)", "error")]
    assert not evidence.passed


@pytest.mark.parametrize("output", ["2 passed in 0.01s", "OK", "Ran 1 test in 0.1s", "Ran 1 test in 0.1s\n\nFAILED (mystery=1)", "Ran 1 test in 0.1s\n\nOK\nRan 2 tests in 0.1s\n\nOK"])
def test_unknown_framework_not_inferred_from_command(output):
    evidence = summarize_evaluation_log(log(output))
    assert evidence.framework == "unknown"
    assert (evidence.tests_run, evidence.failure_count, evidence.error_count) == (None, None, None)
    assert evidence.failing_cases == []


def test_wrapper_renderer_exact_format_and_tail():
    text = log("hello", command="run")
    assert text == "Command: run\nExit code: 0\nDuration seconds: 1.234568\n\nSTDOUT:\n\nSTDERR:\nhello"
    text = log("\n".join(f"  line {i}" if i % 2 else "" for i in range(100)))
    evidence = summarize_evaluation_log(text)
    assert evidence.output_tail == [f"  line {i}" for i in range(61, 100, 2)]
    assert evidence.test_log_sha256 == sha(text)


@pytest.mark.parametrize("text", ["", "random", log().replace("Exit code: 0", "Exit code: bad"), log().replace("1.234568", "-1.234568"), log().replace("STDOUT:", "OUTPUT:"), log("\nSTDERR:\nambiguous")])
def test_malformed_wrapper_refused(text):
    with pytest.raises(EvidenceParsingError):
        summarize_evaluation_log(text)


def test_model_invariants():
    file = summarize_patch(modified()).files[0].model_dump()
    for change in ({"binary": True}, {"added_lines": None}, {"deleted_lines": -1}):
        with pytest.raises(ValidationError):
            PatchFileSummary(**(file | change))
    summary = summarize_patch(modified()).model_dump()
    for change in ({"changed_file_count": 2}, {"text_added_lines": 9}, {"text_deleted_lines": 9}):
        with pytest.raises(ValidationError):
            PatchSummary(**(summary | change))
    evidence = summarize_evaluation_log(log()).model_dump()
    for change in ({"tests_run": 1}, {"passed": False}, {"output_tail": ["x"] * 21}, {"output_tail": [""]}, {"framework": "unittest"}):
        with pytest.raises(ValidationError):
            EvaluationEvidence(**(evidence | change))


@pytest.mark.parametrize("docker", [False, True])
def test_new_run_persists_exact_artifact_hashes(tmp_path, docker):
    source, commit = create_fixture_repository(tmp_path)
    task_path = write_run_task(tmp_path, source, commit, command=f'{sys.executable} -c "pass"')
    record = run_task(task_path, agent=FakeAgent(), agent_name="fake",
                      sandbox=RecordingSandbox() if docker else None,
                      workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    loaded = FilesystemArtifactStore(tmp_path / "results").load_run_record(record.run_id)
    assert loaded == record
    assert record.patch_summary.patch_sha256 == hashlib.sha256(record.artifacts.patch.read_bytes()).hexdigest()
    assert record.evaluation_evidence.test_log_sha256 == hashlib.sha256(record.artifacts.test_log.read_bytes()).hexdigest()
    assert record.evaluation_evidence.passed == record.evaluation_passed
    assert record.agent.backend == "host"
    assert record.provenance.base_commit_used == commit
    assert record.provenance.evaluation_backend == ("docker" if docker else "host")
    assert {p.name for p in record.artifacts.directory.iterdir()} == {"metadata.json", "prompt.txt", "agent.log", "agent.stderr.log", "patch.diff", "test.log"}
    raw = record.model_dump()
    raw["evaluation_passed"] = not record.evaluation_passed
    with pytest.raises(ValidationError):
        RunRecord.model_validate(raw)


def test_experiment_children_receive_evidence(tmp_path):
    source, commit = create_fixture_repository(tmp_path)
    task = write_run_task(tmp_path, source, commit, command=f'{sys.executable} -c "pass"')
    experiment = run_experiment(task, requested_runs=2, agent_factory=FakeAgent,
                                configuration=ExperimentConfiguration(agent_name="fake", evaluation_backend="host"),
                                workspace_root=tmp_path / "workspaces", results_root=tmp_path / "results")
    store = FilesystemArtifactStore(tmp_path / "results")
    for run_id in experiment.run_ids:
        run = store.load_run_record(run_id)
        assert run.patch_summary is not None and run.evaluation_evidence is not None
    assert "patch_summary" not in experiment.model_dump()


@pytest.mark.parametrize("omit", [False, True])
def test_historical_evidence_absent_loads_and_replays_without_rewrite(tmp_path, omit):
    source, commit = create_fixture_repository(tmp_path)
    record = make_run(tmp_path / "results")
    raw = record.model_dump(mode="json")
    if omit:
        raw.pop("patch_summary")
        raw.pop("evaluation_evidence")
    record.artifacts.directory.mkdir(parents=True)
    original = json.dumps(raw)
    record.artifacts.metadata.write_text(original)
    record.artifacts.patch.write_text(FIX_PATCH)
    store = FilesystemArtifactStore(tmp_path / "results")
    loaded = store.load_run_record(record.run_id)
    assert loaded.patch_summary is None and loaded.evaluation_evidence is None
    replay = replay_run(make_task(source, commit), loaded, store.load_run_patch(record.run_id), workspace_root=tmp_path / "workspaces")
    assert replay.record.replay_evaluation_passed
    assert record.artifacts.metadata.read_text() == original


def test_unittest_cases_can_be_in_other_stream_than_summary():
    result = EvaluationResult(exit_code=1, passed=False, duration_seconds=0,
                              stdout="FAIL: in_stdout (tests.A)",
                              stderr="ERROR: in_stderr (tests.B)\n\nRan 2 tests in 0.010s\n\nFAILED (failures=1, errors=1)")
    evidence = summarize_evaluation_log(render_evaluation_log(result, "run"))
    assert [case.name for case in evidence.failing_cases] == ["in_stdout (tests.A)", "in_stderr (tests.B)"]


def test_zero_tests_and_unexpected_success_are_not_reinterpreted():
    zero = summarize_evaluation_log(log("Ran 0 tests in 0.000s\n\nOK"))
    assert zero.tests_run == 0
    unusual = summarize_evaluation_log(log("Ran 1 test in 0.001s\n\nFAILED (unexpected successes=1)", exit_code=1))
    assert unusual.framework == "unittest" and unusual.failure_count == unusual.error_count == 0
    assert not unusual.passed


def test_unbounded_duration_refused_with_narrow_error():
    with pytest.raises(EvidenceParsingError):
        summarize_evaluation_log(log().replace("1.234568", "9" * 400 + ".000000"))


def test_run_evidence_must_be_paired(tmp_path):
    raw = make_run(tmp_path).model_dump()
    raw["patch_summary"] = summarize_patch("").model_dump()
    with pytest.raises(ValidationError):
        RunRecord.model_validate(raw)


def test_real_git_binary_modification_and_deletion(tmp_path):
    source, commit = create_fixture_repository(tmp_path)
    # Prepare binary content using ordinary fixture-test Git conventions.
    (source / "data.bin").write_bytes(bytes(range(256)) * 20)
    git(source, "add", "data.bin")
    git(source, "-c", "user.name=Test", "-c", "user.email=test@invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "binary base")
    task = make_task(source, git(source, "rev-parse", "HEAD"))
    manager = GitRepositoryManager(tmp_path / "workspaces")
    for delete in (False, True):
        with manager.workspace(task.repository, "binary") as workspace:
            if delete:
                (workspace.path / "data.bin").unlink()
            else:
                (workspace.path / "data.bin").write_bytes(bytes(range(255, -1, -1)) * 20)
            patch = manager.capture_diff(workspace)
        file = summarize_patch(patch).files[0]
        assert file.binary and file.added_lines is None and file.deleted_lines is None
        assert file.change_type == ("deleted" if delete else "modified")
        assert file.diff_sha256 == sha(patch)


@pytest.mark.parametrize("body", ["Binary files a/wrong and b/a differ\n", "GIT binary patch\nliteral 1\nbad\n"])
def test_malformed_binary_sections_refused(body):
    with pytest.raises(EvidenceParsingError):
        summarize_patch("diff --git a/a b/a\n" + body)


def test_no_newline_marker_cannot_precede_hunk_content():
    with pytest.raises(EvidenceParsingError):
        summarize_patch(modified().replace("-old", "\\ No newline at end of file\n-old"))
