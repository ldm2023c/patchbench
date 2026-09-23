"""M12 calibration evidence freeze tests with synthetic runtime evidence."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchbench.agents.base import AgentRunStatus
from patchbench.application.v13_agent_execution import resolve_v13_agent_config
from patchbench.application.v13_calibration import verify_v13_calibration_protocol
from patchbench.domain import (
    AgentExecutionMetadata, CalibrationBatchStatus, CalibrationSlotStatus,
    EvaluationResult, ExperimentAggregate, ExperimentRecord, RunProvenance,
    RunRecord, RunStatus, V13CalibrationBatch, V13CalibrationEvidenceFreeze,
    V13CalibrationSlot, render_evaluation_log, summarize_evaluation_log,
    summarize_patch,
)
from patchbench.storage.filesystem import FilesystemArtifactStore
from scripts import v13_calibration_evidence as evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_IDS = (
    "codex-gpt-5.5-relay", "cursor-claude-4.6-sonnet-medium",
    "grok-build-grok-4.5-relay",
)
RUN_IDS = ("synthetic-run-01", "synthetic-run-02", "synthetic-run-03")
EXPERIMENT_IDS = (
    "synthetic-experiment-01", "synthetic-experiment-02",
    "synthetic-experiment-03",
)


def _synthetic_source(
    tmp_path: Path,
    *,
    evaluation_passed: tuple[bool, bool, bool] = (True, True, True),
) -> Path:
    """Create a deterministic accepted source tree without provider execution."""
    source = tmp_path / "calibration" / "calibration-001"
    artifacts_root = source / "artifacts"
    artifacts_root.mkdir(parents=True)
    store = FilesystemArtifactStore(artifacts_root)
    protocol = verify_v13_calibration_protocol(PROJECT_ROOT).protocol
    slots = []
    for index, (config_id, run_id, experiment_id, passed) in enumerate(zip(
        CONFIG_IDS, RUN_IDS, EXPERIMENT_IDS, evaluation_passed, strict=True
    )):
        plan = resolve_v13_agent_config(
            config_id, evaluation_backend="docker", project_root=PROJECT_ROOT
        )
        result = EvaluationResult(
            exit_code=0 if passed else 1, passed=passed,
            duration_seconds=0.25 + index,
            stdout=f"synthetic evaluation stdout {index}\n",
            stderr="" if passed else f"synthetic evaluation failure {index}\n",
        )
        test_log = render_evaluation_log(result, "python -m unittest -q")
        paths = store.create_paths(run_id)
        record = RunRecord(
            run_id=run_id, task_id="example_bug",
            status=RunStatus.PASSED if passed else RunStatus.FAILED,
            evaluation_passed=passed, duration_seconds=2.0 + index,
            agent=AgentExecutionMetadata(
                name=plan.experiment_configuration.agent_name, backend="host",
                status=AgentRunStatus.COMPLETED, exit_code=0,
                duration_seconds=1.0 + index,
                timeout_seconds=plan.experiment_configuration.agent_timeout_seconds,
                requested_model=plan.experiment_configuration.requested_model,
                identity_binding=plan.identity_binding,
            ),
            artifacts=paths,
            provenance=RunProvenance(
                base_commit_used=protocol.calibration_base_commit,
                task_fingerprint_sha256="0" * 64,
                evaluation_command="python -m unittest -q",
                evaluation_timeout_seconds=120, evaluation_backend="docker",
            ),
            patch_summary=summarize_patch(""),
            evaluation_evidence=summarize_evaluation_log(test_log),
        )
        paths.metadata.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        paths.prompt.write_text(f"synthetic prompt {index}\n", encoding="utf-8")
        paths.agent_log.write_text(
            f"synthetic agent stdout {index}\n", encoding="utf-8"
        )
        paths.agent_stderr_log.write_text(
            f"synthetic agent stderr {index}\n", encoding="utf-8"
        )
        paths.test_log.write_text(test_log, encoding="utf-8")
        paths.patch.write_text("", encoding="utf-8")
        experiment = ExperimentRecord(
            experiment_id=experiment_id, task_id="example_bug", requested_runs=1,
            run_ids=[run_id], configuration=plan.experiment_configuration,
            aggregate=ExperimentAggregate(
                run_count=1, evaluation_pass_count=int(passed),
                evaluation_fail_count=int(not passed),
                evaluation_pass_rate=float(passed), agent_command_failure_count=0,
                agent_timeout_count=0, total_duration_seconds=2.0 + index,
                mean_duration_seconds=2.0 + index,
                min_duration_seconds=2.0 + index,
                max_duration_seconds=2.0 + index,
            ),
            duration_seconds=2.0 + index,
        )
        store.save_experiment(experiment)
        slots.append(V13CalibrationSlot(
            config_id=config_id, status=CalibrationSlotStatus.RUNTIME_ADMITTED,
            experiment_id=experiment_id, run_id=run_id,
            agent_status=AgentRunStatus.COMPLETED, evaluation_passed=passed,
            identity_binding=plan.identity_binding,
        ))
    batch = V13CalibrationBatch(
        batch_id="calibration-001",
        protocol_sha256=evidence.ACCEPTED_PROTOCOL_SHA256,
        calibration_task_id="example_bug",
        calibration_task_spec_sha256=protocol.calibration_task_spec_sha256,
        m3_candidate_sha256=evidence.ACCEPTED_M3_CANDIDATE_SHA256,
        m8_agent_manifest_sha256=evidence.ACCEPTED_M8_AGENT_MANIFEST_SHA256,
        ordered_agent_config_ids=CONFIG_IDS, status=CalibrationBatchStatus.ACCEPTED,
        slots=tuple(slots),
    )
    (source / "batch.json").write_text(
        json.dumps(batch.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return source


def _mutate_batch(source: Path, update) -> None:
    path = source / "batch.json"
    data = json.loads(path.read_text())
    update(data)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_checked_freeze_hashes_are_source_independent():
    checked = evidence.verify_checked_freeze()
    assert evidence.compute_v13_calibration_evidence_freeze_sha256(checked) == evidence.ACCEPTED_FREEZE_SHA256
    assert evidence._sha256_bytes((PROJECT_ROOT / evidence.FREEZE_PATH).read_bytes()) == evidence.ACCEPTED_FREEZE_BYTE_SHA256


def test_checked_freeze_verifies_in_minimal_tree_without_results(tmp_path):
    path = tmp_path / evidence.FREEZE_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes((PROJECT_ROOT / evidence.FREEZE_PATH).read_bytes())
    assert evidence.verify_checked_freeze(tmp_path).source_batch_id == "calibration-001"
    assert not (tmp_path / "results").exists()


def test_freeze_is_strict_immutable_and_contains_no_local_paths_or_raw_logs():
    freeze = evidence.load_checked_freeze()
    with pytest.raises(ValidationError):
        V13CalibrationEvidenceFreeze.model_validate(
            freeze.model_dump(mode="json") | {"extra": True}
        )
    with pytest.raises(ValidationError):
        freeze.source_batch_id = "changed"
    raw = (PROJECT_ROOT / evidence.FREEZE_PATH).read_text()
    assert "/home/" not in raw and "agent.log" not in raw
    assert "API_KEY" not in raw and "AUTH_TOKEN" not in raw


def test_synthetic_source_satisfies_production_builder(tmp_path):
    freeze = evidence.build_calibration_evidence_freeze(_synthetic_source(tmp_path))
    assert tuple(slot.config_id for slot in freeze.slots) == CONFIG_IDS
    assert tuple(slot.run_id for slot in freeze.slots) == RUN_IDS
    assert tuple(slot.experiment_id for slot in freeze.slots) == EXPERIMENT_IDS


@pytest.mark.parametrize("update", [
    lambda d: d.update(batch_id="other"),
    lambda d: d.update(status="completed_not_admitted"),
    lambda d: d.update(previous_batch_id="earlier", environment_remediation="x"),
    lambda d: d.update(protocol_sha256="0" * 64),
    lambda d: d.update(m3_candidate_sha256="0" * 64),
    lambda d: d.update(m8_agent_manifest_sha256="0" * 64),
    lambda d: d.update(ordered_agent_config_ids=d["ordered_agent_config_ids"][:2]),
    lambda d: d.update(ordered_agent_config_ids=d["ordered_agent_config_ids"] + ["extra-config"]),
    lambda d: d["slots"].__setitem__(0, d["slots"][0] | {
        "status": "runtime_not_admitted", "failure_reason": "agent_setup_failed",
        "experiment_id": None, "run_id": None, "agent_status": None,
        "evaluation_passed": None, "identity_binding": None,
    }),
    lambda d: d["slots"][0]["identity_binding"].update(config_sha256="0" * 64),
    lambda d: d["slots"][0].update(agent_status="timed_out"),
])
def test_source_batch_contract_drift_rejects(tmp_path, update):
    source = _synthetic_source(tmp_path)
    _mutate_batch(source, update)
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError):
        evidence.build_calibration_evidence_freeze(source)


def test_source_builder_allows_completed_evaluator_fail(tmp_path):
    source = _synthetic_source(tmp_path, evaluation_passed=(False, True, True))
    rebuilt = evidence.build_calibration_evidence_freeze(source)
    assert rebuilt.slots[0].agent_status is AgentRunStatus.COMPLETED
    assert rebuilt.slots[0].evaluation_passed is False


@pytest.mark.parametrize(("relative", "message"), [
    (f"artifacts/{RUN_IDS[0]}/metadata.json", "Run/Experiment"),
    (f"artifacts/experiments/{EXPERIMENT_IDS[0]}/metadata.json", "Run/Experiment"),
])
def test_missing_run_or_experiment_rejects(tmp_path, relative, message):
    source = _synthetic_source(tmp_path)
    (source / relative).unlink()
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match=message):
        evidence.build_calibration_evidence_freeze(source)


def test_experiment_run_linkage_mismatch_rejects(tmp_path):
    source = _synthetic_source(tmp_path)
    path = source / "artifacts/experiments" / EXPERIMENT_IDS[0] / "metadata.json"
    data = json.loads(path.read_text())
    data["run_ids"] = [RUN_IDS[1]]
    path.write_text(json.dumps(data))
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="linkage"):
        evidence.build_calibration_evidence_freeze(source)


@pytest.mark.parametrize("field", ["task_id", "backend", "base_commit"])
def test_task_backend_or_base_commit_mismatch_rejects(tmp_path, field):
    source = _synthetic_source(tmp_path)
    path = source / "artifacts" / RUN_IDS[0] / "metadata.json"
    data = json.loads(path.read_text())
    if field == "task_id":
        data[field] = "other"
    elif field == "backend":
        data["provenance"]["evaluation_backend"] = "host"
    else:
        data["provenance"]["base_commit_used"] = "0" * 40
    path.write_text(json.dumps(data))
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="linkage"):
        evidence.build_calibration_evidence_freeze(source)


@pytest.mark.parametrize(("filename", "message"), [
    ("patch.diff", "patch hash"), ("test.log", "test-log hash"),
])
def test_raw_evidence_hash_mismatch_rejects(tmp_path, filename, message):
    source = _synthetic_source(tmp_path)
    path = source / "artifacts" / RUN_IDS[0] / filename
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match=message):
        evidence.build_calibration_evidence_freeze(source)


def test_source_batch_byte_mutation_changes_freeze_and_source_comparison(tmp_path):
    source = _synthetic_source(tmp_path)
    original = evidence.build_calibration_evidence_freeze(source)
    (source / "batch.json").write_bytes((source / "batch.json").read_bytes() + b"\n")
    rebuilt = evidence.build_calibration_evidence_freeze(source)
    assert rebuilt.source_batch_json_sha256 != original.source_batch_json_sha256
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="differs"):
        evidence.verify_source_against_checked_freeze(source)


def test_extra_later_batch_rejects(tmp_path):
    source = _synthetic_source(tmp_path)
    (source.parent / "calibration-002").mkdir()
    with pytest.raises(evidence.CalibrationEvidenceIntegrityError, match="extra"):
        evidence.build_calibration_evidence_freeze(source)
