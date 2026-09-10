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

__all__ = [
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
