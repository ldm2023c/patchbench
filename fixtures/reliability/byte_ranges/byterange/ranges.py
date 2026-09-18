"""Resolve byte-range headers for a known blob size."""

from dataclasses import dataclass


class RangeSyntaxError(ValueError):
    pass


class UnsatisfiableRange(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedRange:
    start: int
    end: int


def resolve_ranges(header: str, resource_size: int) -> tuple[ResolvedRange, ...]:
    if type(resource_size) is not int or resource_size < 0:
        raise ValueError("resource_size must be a nonnegative integer")
    if not isinstance(header, str) or not header.startswith("bytes="):
        raise RangeSyntaxError("expected bytes unit")

    resolved = []
    for member in header[6:].split(","):
        try:
            first_text, last_text = member.split("-")
            first = int(first_text or "0")
            last = int(last_text or str(resource_size - 1))
        except ValueError as error:
            raise RangeSyntaxError("invalid range member") from error
        if first > last:
            raise RangeSyntaxError("reversed range")
        if first >= resource_size:
            raise UnsatisfiableRange("range starts beyond resource")
        resolved.append(ResolvedRange(first, last))
    return tuple(resolved)
