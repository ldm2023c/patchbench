"""Tool-less Diagnosis inference providers; separate from coding Agents."""

from patchbench.providers.base import (
    DiagnosisProvider, DiagnosisProviderRequest, DiagnosisProviderResponse,
    DiagnosisProviderError, DiagnosisProviderSetupError, DiagnosisProviderRequestError,
    DiagnosisProviderRefusalError, DiagnosisProviderIncompleteError,
)

__all__ = ["DiagnosisProvider", "DiagnosisProviderRequest", "DiagnosisProviderResponse",
           "DiagnosisProviderError", "DiagnosisProviderSetupError", "DiagnosisProviderRequestError",
           "DiagnosisProviderRefusalError", "DiagnosisProviderIncompleteError"]
