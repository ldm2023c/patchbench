"""Application-layer Run, Replay, and Diagnosis orchestration."""

from patchbench.application.local_run import run_task
from patchbench.application.replay import ReplayError, ReplayExecution, replay_run
from patchbench.application.diagnosis_execution import (
    DiagnosisExecution, DiagnosisExecutionError, DiagnosisExecutionReason, execute_blind_diagnosis,
    execute_contrastive_diagnosis,
)
from patchbench.application.diagnosis_peer import (
    ContrastivePeerSelection, DiagnosisPeerError, DiagnosisPeerReason, select_contrastive_peer,
)
from patchbench.application.diagnosis_contrastive import (
    ContrastiveCompilationError, ContrastiveCompilationReason, compile_contrastive_diagnosis_evidence,
)
from patchbench.application.diagnosis_validation import (
    DiagnosisValidationError, DiagnosisValidationReason,
    compute_diagnosis_gold_sha256, compute_subject_evidence_sha256, score_diagnosis_route,
    score_semantic_diagnosis, validate_semantic_gold_evidence,
)
from patchbench.application.diagnosis_suite import (
    DiagnosisSuiteError, DiagnosisSuiteReason, compute_run_record_sha256,
    finalize_diagnosis_validation_freeze, prepare_contrastive_fairness_review,
    verify_contrastive_fairness_review,
    verify_diagnosis_validation_freeze,
    verify_diagnosis_validation_suite, verify_diagnosis_validation_v1_composition,
    verify_semantic_validation_case,
)
from patchbench.application.diagnosis_metrics import (
    DiagnosisMetricsError, DiagnosisMetricsReason, aggregate_route_scores,
    aggregate_semantic_scores, compare_blind_contrastive,
)
from patchbench.application.diagnosis_gold_lock import (
    DiagnosisGoldLockError, DiagnosisGoldLockReason,
    build_diagnosis_gold_lock, verify_diagnosis_gold_lock,
)
from patchbench.application.diagnosis_validation_run import (
    DiagnosisValidationRunError, DiagnosisValidationRunReason,
    build_diagnosis_validation_run_plan, run_frozen_diagnosis_validation,
)
from patchbench.application.diagnosis_validation_collection import (
    DiagnosisValidationCollectionError, DiagnosisValidationCollectionReason,
    collect_diagnosis_validation_shards, parse_case_selection,
)

__all__ = ["ReplayError", "ReplayExecution", "replay_run", "run_task",
           "DiagnosisValidationRunError", "DiagnosisValidationRunReason",
           "build_diagnosis_validation_run_plan", "run_frozen_diagnosis_validation",
           "DiagnosisGoldLockError", "DiagnosisGoldLockReason",
           "build_diagnosis_gold_lock", "verify_diagnosis_gold_lock",
           "DiagnosisExecution", "DiagnosisExecutionError", "DiagnosisExecutionReason", "execute_blind_diagnosis",
           "execute_contrastive_diagnosis", "ContrastivePeerSelection", "DiagnosisPeerError", "DiagnosisPeerReason",
           "select_contrastive_peer", "ContrastiveCompilationError", "ContrastiveCompilationReason",
           "compile_contrastive_diagnosis_evidence", "DiagnosisValidationError",
           "DiagnosisValidationReason", "compute_subject_evidence_sha256",
           "compute_diagnosis_gold_sha256",
           "score_diagnosis_route", "score_semantic_diagnosis",
           "validate_semantic_gold_evidence", "DiagnosisSuiteError",
           "DiagnosisSuiteReason", "compute_run_record_sha256",
           "prepare_contrastive_fairness_review",
           "verify_contrastive_fairness_review",
           "finalize_diagnosis_validation_freeze",
           "verify_diagnosis_validation_freeze",
           "verify_diagnosis_validation_suite",
           "verify_diagnosis_validation_v1_composition",
           "verify_semantic_validation_case",
           "DiagnosisMetricsError", "DiagnosisMetricsReason",
           "aggregate_route_scores", "aggregate_semantic_scores",
           "compare_blind_contrastive",
           "DiagnosisValidationCollectionError",
           "DiagnosisValidationCollectionReason",
           "collect_diagnosis_validation_shards",
           "parse_case_selection"]
