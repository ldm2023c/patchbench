"""Immutable backend outcomes and cached representations."""
from dataclasses import dataclass

from .errors import ValidationError


def resource_key(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("resource key must be a nonblank string")
    return value


@dataclass(frozen=True)
class Value:
    body: bytes
    validator: str | None = None

    def __post_init__(self):
        if not isinstance(self.body, bytes):
            raise ValidationError("body must be bytes")
        if self.validator is not None and (not isinstance(self.validator, str) or not self.validator):
            raise ValidationError("validator must be a nonempty string or None")


@dataclass(frozen=True)
class NotModified:
    pass


@dataclass(frozen=True)
class Entry:
    body: bytes
    validator: str | None
    fetched_at: int
