"""Bookmark records used by the import/export boundary."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Bookmark:
    title: str
    url: str
    note: str | None = None

    def __post_init__(self):
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("title must be nonempty text")
        if not isinstance(self.url, str) or not self.url.startswith(("https://", "http://")):
            raise ValueError("url must be an HTTP(S) URL")
        if self.note is not None and not isinstance(self.note, str):
            raise ValueError("note must be text or absent")
