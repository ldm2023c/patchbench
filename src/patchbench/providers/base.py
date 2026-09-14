"""Text/schema-only diagnosis inference boundary, independent of coding Agents."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import ConfigDict, StringConstraints
from typing import Annotated

from patchbench.domain.models import DomainModel, NonEmptyString
from patchbench.domain.diagnosis_execution import DiagnosisProviderSettings, DiagnosisProviderUsage, Duration


@dataclass(frozen=True)
class DiagnosisProviderRequest:
    instructions: str
    input_text: str
    # Canonical JSON text keeps the entire request immutable and externally sendable.
    output_schema_json: str


class DiagnosisProviderResponse(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    response_id: NonEmptyString
    returned_model: NonEmptyString
    output_text: Annotated[str, StringConstraints(strict=True, strip_whitespace=False)]
    usage: DiagnosisProviderUsage
    duration_seconds: Duration
    client_name: NonEmptyString
    client_version: NonEmptyString


class DiagnosisProvider(Protocol):
    @property
    def settings(self) -> DiagnosisProviderSettings: ...

    def infer(self, request: DiagnosisProviderRequest) -> DiagnosisProviderResponse: ...


class DiagnosisProviderError(RuntimeError):
    """Provider boundary failure; never a semantic abstention."""


class DiagnosisProviderSetupError(DiagnosisProviderError):
    pass


class DiagnosisProviderRequestError(DiagnosisProviderError):
    pass


class DiagnosisProviderRefusalError(DiagnosisProviderError):
    pass


class DiagnosisProviderIncompleteError(DiagnosisProviderError):
    pass
