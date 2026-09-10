"""PatchBench domain models."""

from patchbench.domain.aggregation import (
    ExperimentAggregationError,
    aggregate_runs,
)
from patchbench.domain.comparison import (
    PassFailComparison,
    PassFailComparisonError,
    compare_pass_fail_runs,
)
from patchbench.domain.failure import (
    FailureAnalysis,
    FailureCategory,
    classify_run_failure,
)
from patchbench.domain.models import (
    AgentExecutionMetadata,
    ArtifactPaths,
    EvaluationCaseEvidence,
    EvaluationEvidence,
    PatchFileSummary,
    PatchSummary,
    EvaluationConfig,
    EvaluationResult,
    ExperimentAggregate,
    ExperimentConfiguration,
    ExperimentRecord,
    ReplayRecord,
    RepositoryConfig,
    RunProvenance,
    RunRecord,
    Sha256Hex,
    RunStatus,
    TaskMetadata,
    TaskPromptConfig,
    TaskSpec,
)

from patchbench.domain.provenance import compute_task_fingerprint

from patchbench.domain.evidence_errors import EvidenceParsingError
from patchbench.domain.patch_evidence import summarize_patch
from patchbench.domain.evaluation_evidence import render_evaluation_log, summarize_evaluation_log

from patchbench.domain.analysis import ExperimentAnalysis, RunEvidence

__all__ = [
    "ExperimentAnalysis",
    "RunEvidence",
    "EvidenceParsingError",
    "EvaluationCaseEvidence",
    "EvaluationEvidence",
    "PatchFileSummary",
    "PatchSummary",
    "summarize_patch",
    "render_evaluation_log",
    "summarize_evaluation_log",
    "AgentExecutionMetadata",
    "ArtifactPaths",
    "EvaluationConfig",
    "EvaluationResult",
    "ExperimentAggregate",
    "ExperimentAggregationError",
    "ExperimentConfiguration",
    "ExperimentRecord",
    "FailureAnalysis",
    "FailureCategory",
    "PassFailComparison",
    "PassFailComparisonError",
    "RepositoryConfig",
    "ReplayRecord",
    "RunProvenance",
    "RunRecord",
    "Sha256Hex",
    "RunStatus",
    "TaskMetadata",
    "TaskPromptConfig",
    "TaskSpec",
    "compute_task_fingerprint",
    "aggregate_runs",
    "classify_run_failure",
    "compare_pass_fail_runs",
]
