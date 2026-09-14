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
    compute_subject_evidence_sha256, score_diagnosis_route,
    score_semantic_diagnosis,
)
from patchbench.application.diagnosis_metrics import (
    DiagnosisMetricsError, DiagnosisMetricsReason, aggregate_route_scores,
    aggregate_semantic_scores, compare_blind_contrastive,
)

__all__ = ["ReplayError", "ReplayExecution", "replay_run", "run_task",
           "DiagnosisExecution", "DiagnosisExecutionError", "DiagnosisExecutionReason", "execute_blind_diagnosis",
           "execute_contrastive_diagnosis", "ContrastivePeerSelection", "DiagnosisPeerError", "DiagnosisPeerReason",
           "select_contrastive_peer", "ContrastiveCompilationError", "ContrastiveCompilationReason",
           "compile_contrastive_diagnosis_evidence", "DiagnosisValidationError",
           "DiagnosisValidationReason", "compute_subject_evidence_sha256",
           "score_diagnosis_route", "score_semantic_diagnosis",
           "DiagnosisMetricsError", "DiagnosisMetricsReason",
           "aggregate_route_scores", "aggregate_semantic_scores",
           "compare_blind_contrastive"]
