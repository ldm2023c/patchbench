"""Coding-agent implementations."""

from patchbench.agents.base import (
    Agent,
    AgentInfrastructureError,
    AgentProviderTransportError,
    AgentRunRequest,
    AgentRunResult,
    AgentRunStatus,
    AgentSetupError,
)
from patchbench.agents.codex import CodexAdapter
from patchbench.agents.claude_code import ClaudeCodeAdapter
from patchbench.agents.cursor_cli import CursorCliAdapter
from patchbench.agents.fake import FakeAgent, FakeAgentError
from patchbench.agents.grok_build import GrokBuildAdapter

__all__ = [
    "Agent",
    "AgentInfrastructureError",
    "AgentProviderTransportError",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRunStatus",
    "AgentSetupError",
    "CodexAdapter",
    "ClaudeCodeAdapter",
    "CursorCliAdapter",
    "GrokBuildAdapter",
    "FakeAgent",
    "FakeAgentError",
]
