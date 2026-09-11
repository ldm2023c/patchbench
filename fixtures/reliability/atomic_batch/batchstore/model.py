"""Validated requests and immutable committed outcomes."""
from dataclasses import dataclass
from collections.abc import Mapping

from .errors import ValidationError


def target(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("target must be a nonblank string")
    return value


def integer(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("value must be an integer")
    return value


@dataclass(frozen=True)
class Operation:
    kind: str
    key: str
    value: int | None = None

    def __post_init__(self):
        target(self.key)
        if self.kind not in ("set", "increment", "delete"):
            raise ValidationError("unknown operation")
        if self.kind == "delete":
            if self.value is not None:
                raise ValidationError("delete has no value")
        else:
            integer(self.value)
            if self.kind == "set" and self.value < 0:
                raise ValidationError("balance cannot be negative")


def operations(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValidationError("operations must be a nonempty list or tuple")
    result = []
    for value in values:
        if isinstance(value, Operation):
            result.append(value)
        elif isinstance(value, Mapping):
            if set(value) - {"kind", "key", "value"} or not {"kind", "key"} <= set(value):
                raise ValidationError("invalid operation fields")
            result.append(Operation(**value))
        else:
            raise ValidationError("invalid operation")
    return tuple(result)


@dataclass(frozen=True)
class Event:
    kind: str
    key: str
    before: int | None
    after: int | None


@dataclass(frozen=True)
class BatchResult:
    events: tuple[Event, ...]
