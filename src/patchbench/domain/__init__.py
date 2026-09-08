"""PatchBench domain models."""

from patchbench.domain.aggregation import (
    ExperimentAggregationError,
    aggregate_runs,
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
    "RepositoryConfig",
    "RunRecord",
    "RunStatus",
    "TaskMetadata",
    "TaskPromptConfig",
    "TaskSpec",
    "aggregate_runs",
]
