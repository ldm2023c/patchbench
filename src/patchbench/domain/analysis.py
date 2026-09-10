"""Read-only Experiment analysis results composed from verified evidence."""

from pydantic import Field

from patchbench.agents.base import AgentRunStatus
from patchbench.domain.comparison import PassFailComparison
from patchbench.domain.failure import FailureCategory
from patchbench.domain.models import (
    DomainModel, NonEmptyString, PatchSummary, EvaluationEvidence,
    ExperimentConfiguration, ExperimentAggregate, RunProvenance,
)


class RunEvidence(DomainModel):
    run_id: NonEmptyString
    evaluation_passed: bool
    agent_status: AgentRunStatus
    duration_seconds: float = Field(ge=0)
    failure_categories: list[FailureCategory]
    patch: PatchSummary
    evaluation: EvaluationEvidence


class ExperimentAnalysis(DomainModel):
    experiment_id: NonEmptyString
    task_id: NonEmptyString
    configuration: ExperimentConfiguration
    aggregate: ExperimentAggregate
    provenance: RunProvenance | None
    exact_patch_variant_count: int = Field(ge=1)
    failure_category_counts: dict[str, int]
    runs: list[RunEvidence] = Field(min_length=1)
    example_pair: PassFailComparison | None
