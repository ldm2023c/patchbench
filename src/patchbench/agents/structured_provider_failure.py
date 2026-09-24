"""Narrow structured provider-failure evidence shared by adapters and audits."""

import json
import re
from typing import Literal


CodexRateLimitEventType = Literal["error", "turn.failed"]

_HTTP_429_PATTERN = re.compile(r"(?<!\d)429(?!\d)")
_TOO_MANY_REQUESTS_PATTERN = re.compile(
    r"\btoo\s+many\s+requests\b", re.IGNORECASE
)


def codex_structured_http_429_event_types(
    stdout: str,
) -> tuple[CodexRateLimitEventType, ...]:
    """Return recognized event types proving a Codex HTTP 429 failure."""

    seen: set[CodexRateLimitEventType] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        message: object = None
        if event_type == "error":
            message = event.get("message")
        elif event_type == "turn.failed":
            error = event.get("error")
            if isinstance(error, dict):
                message = error.get("message")
        else:
            continue

        if (
            isinstance(message, str)
            and _HTTP_429_PATTERN.search(message)
            and _TOO_MANY_REQUESTS_PATTERN.search(message)
        ):
            seen.add(event_type)
    return tuple(item for item in ("error", "turn.failed") if item in seen)


def has_codex_structured_http_429(stdout: str) -> bool:
    """Return whether recognized Codex JSONL proves an HTTP 429 failure."""

    return bool(codex_structured_http_429_event_types(stdout))
