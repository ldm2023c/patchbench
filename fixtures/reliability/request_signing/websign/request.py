"""Lossless request inputs for signing middleware."""
from collections.abc import Mapping
from dataclasses import dataclass
import re

from .errors import CanonicalizationError

TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    raw_query: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""

    def __post_init__(self):
        if not isinstance(self.method, str) or not TOKEN.fullmatch(self.method):
            raise CanonicalizationError("invalid method")
        if not isinstance(self.path, str) or not self.path.startswith("/") or any(c in self.path for c in "\r\n"):
            raise CanonicalizationError("path must start with / and contain no line breaks")
        if not isinstance(self.raw_query, str):
            raise CanonicalizationError("raw query must be text")
        if not isinstance(self.body, bytes):
            raise CanonicalizationError("body must be bytes")
        pairs = self.headers.items() if isinstance(self.headers, Mapping) else self.headers
        try:
            pairs = tuple((name, value) for name, value in pairs)
        except (TypeError, ValueError) as error:
            raise CanonicalizationError("headers must be name/value pairs") from error
        for name, value in pairs:
            if not isinstance(name, str) or not TOKEN.fullmatch(name):
                raise CanonicalizationError("invalid header name")
            if not isinstance(value, str) or any(c in value for c in "\r\n"):
                raise CanonicalizationError("invalid header value")
        object.__setattr__(self, "headers", pairs)
