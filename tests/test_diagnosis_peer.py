"""Persisted Experiment order defines one same-cell comparison peer."""

import json

import pytest

from patchbench.agents.base import AgentRunStatus
from patchbench.application.diagnosis_peer import select_contrastive_peer, DiagnosisPeerError
from patchbench.domain import ExperimentRecord, ExperimentConfiguration, aggregate_runs
from patchbench.domain.models import EvaluationResult, RunStatus
from patchbench.domain.evaluation_evidence import render_evaluation_log, summarize_evaluation_log
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.config.task_loader import load_task
from tests.test_diagnosis_evidence import historical, write_files


def write_record(store, record):
    (store.results_root / record.run_id / "metadata.json").write_text(record.model_dump_json())


def change_record(store, run_id, section, field, value):
    path = store.results_root / run_id / "metadata.json"
    data = json.loads(path.read_bytes())
    (data if section is None else data[section])[field] = value
    path.write_text(json.dumps(data))


def save_experiment(store, ids):
    runs = [store.load_run_record(run_id) for run_id in ids]
    sample = runs[0]
    record = ExperimentRecord(experiment_id="peers", task_id=sample.task_id, requested_runs=len(ids), run_ids=ids,
        configuration=ExperimentConfiguration(agent_name=sample.agent.name, requested_model=sample.agent.requested_model,
            agent_timeout_seconds=sample.agent.timeout_seconds, evaluation_backend=sample.provenance.evaluation_backend),
        aggregate=aggregate_runs(runs), duration_seconds=1)
    directory = store.results_root / "experiments" / "peers"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(record.model_dump_json())


@pytest.fixture
def peer_world(historical):
    case = historical()
    store = case["artifact_store"]
    subject = store.load_run_record("subject")
    task = load_task(case["task_path"])
    with case["repository_manager"].workspace(task.repository, "peer-fixture") as workspace:
        write_files(workspace.path, {"src/a.py": b"a = 3\n"})
        peer_patch = case["repository_manager"].capture_diff(workspace)
    for run_id, passed in [("fail1", False), ("z-passA", True), ("a-passB", True)]:
        run = subject.model_copy(deep=True)
        run.run_id = run_id
        run.artifacts = store.create_paths(run_id)
        run.evaluation_passed = passed
        run.status = RunStatus.PASSED if passed else RunStatus.FAILED
        log = render_evaluation_log(EvaluationResult(exit_code=0 if passed else 1, passed=passed, duration_seconds=1,
            stdout="", stderr="Ran 1 test in 0.001s\n\nOK\n" if passed else "FAIL\n"), task.evaluation.command)
        run.patch_summary = summarize_patch(peer_patch)
        run.evaluation_evidence = summarize_evaluation_log(log)
        run.artifacts.patch.write_bytes(peer_patch.encode())
        run.artifacts.test_log.write_bytes(log.encode())
        run.artifacts.agent_log.write_text("Agent narrative must not be read")
        write_record(store, run)
    save_experiment(store, ["fail1", "z-passA", "a-passB"])
    return case


def select(case):
    return select_contrastive_peer("subject", "peers", artifact_store=case["artifact_store"])


def test_experiment_order_and_subject_outside_experiment(peer_world):
    store = peer_world["artifact_store"]
    assert "subject" not in store.load_experiment_record("peers").run_ids
    first = select(peer_world)
    assert first == select(peer_world)
    assert (first.peer_run_id, first.peer_run_index) == ("z-passA", 1)
    save_experiment(store, ["a-passB", "z-passA", "fail1"])
    assert select(peer_world).peer_run_id == "a-passB"


def test_subject_excluded_and_no_pass(peer_world):
    store = peer_world["artifact_store"]
    save_experiment(store, ["subject", "z-passA"])
    assert select(peer_world).peer_run_index == 1
    save_experiment(store, ["subject", "fail1"])
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "no_same_cell_pass"


@pytest.mark.parametrize("status", ["command_failed", "timed_out", "pass"])
def test_ineligible_subject_rejected_before_experiment_read(peer_world, monkeypatch, status):
    store = peer_world["artifact_store"]
    if status == "pass":
        record = store.load_run_record("z-passA")
        record.run_id = "subject"
        write_record(store, record)
    else:
        change_record(store, "subject", "agent", "status", status)
    monkeypatch.setattr(store, "load_experiment_record", lambda *args: pytest.fail("Must reject subject first"))
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "subject_not_semantic"


@pytest.mark.parametrize("section,field,value", [(None, "task_id", "other"),
    ("agent", "name", "other"), ("agent", "requested_model", "other"), ("agent", "timeout_seconds", 999),
    ("provenance", "evaluation_backend", "docker"), ("provenance", "base_commit_used", "a" * 40),
    ("provenance", "task_fingerprint_sha256", "a" * 64), ("provenance", "evaluation_command", "other"),
    ("provenance", "evaluation_timeout_seconds", 999)])
def test_peer_exact_cell_mismatch_fails_closed(peer_world, section, field, value):
    change_record(peer_world["artifact_store"], "z-passA", section, field, value)
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "peer_experiment_mismatch"


def test_inconsistent_internal_fail_run_not_silently_skipped(peer_world):
    change_record(peer_world["artifact_store"], "fail1", "agent", "name", "other")
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "peer_experiment_mismatch"


def test_subject_experiment_config_mismatch(peer_world):
    change_record(peer_world["artifact_store"], "subject", "agent", "requested_model", "other")
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "subject_cell_mismatch"


@pytest.mark.parametrize("run_id", ["subject", "z-passA"])
def test_missing_provenance_fails_closed(peer_world, run_id):
    change_record(peer_world["artifact_store"], run_id, None, "provenance", None)
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == ("subject_evidence_missing" if run_id == "subject" else "peer_run_evidence_missing")


def test_operational_pass_not_eligible(peer_world):
    change_record(peer_world["artifact_store"], "z-passA", "agent", "status", "command_failed")
    assert select(peer_world).peer_run_id == "a-passB"


@pytest.mark.parametrize("run_id", ["subject", "z-passA"])
def test_missing_both_summaries_rejected(peer_world, run_id):
    store = peer_world["artifact_store"]
    change_record(store, run_id, None, "patch_summary", None)
    change_record(store, run_id, None, "evaluation_evidence", None)
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == ("subject_evidence_missing" if run_id == "subject" else "peer_run_evidence_missing")


def test_unrepresentable_agent_backend_fails_typed(peer_world):
    # Current D1 allows only host coding agents; invalid backend metadata must not be skipped.
    change_record(peer_world["artifact_store"], "z-passA", "agent", "backend", "docker")
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "peer_run_evidence_missing"


def test_experiment_config_independently_checked(peer_world):
    path = peer_world["artifact_store"].results_root / "experiments" / "peers" / "metadata.json"
    data = json.loads(path.read_bytes())
    data["configuration"]["agent_name"] = "different-agent"
    path.write_text(json.dumps(data))
    with pytest.raises(DiagnosisPeerError) as caught:
        select(peer_world)
    assert caught.value.reason.value == "subject_cell_mismatch"
