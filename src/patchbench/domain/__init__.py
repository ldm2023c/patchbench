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
    RepositoryConfig,
    RunRecord,
    RunStatus,
    TaskMetadata,
    TaskPromptConfig,
    TaskSpec,
)

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
    "RunRecord",
    "RunStatus",
    "TaskMetadata",
    "TaskPromptConfig",
    "TaskSpec",
    "aggregate_runs",
    "classify_run_failure",
    "compare_pass_fail_runs",
]
