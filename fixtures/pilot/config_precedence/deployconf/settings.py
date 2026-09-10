"""Validated deployment settings shared by the CLI and embedded callers."""
from dataclasses import dataclass

DEFAULTS = {"endpoint": "https://localhost", "retries": 3, "label": "default"}


@dataclass(frozen=True)
class Settings:
    endpoint: str
    retries: int
    label: str

    @classmethod
    def from_mapping(cls, values):
        endpoint = values["endpoint"]
        if not isinstance(endpoint, str) or not endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        retries = int(values["retries"])
        if retries < 0:
            raise ValueError("retries must be nonnegative")
        label = values["label"]
        if not isinstance(label, str):
            raise ValueError("label must be text")
        return cls(endpoint, retries, label)

    def as_dict(self):
        return {"endpoint": self.endpoint, "retries": self.retries, "label": self.label}
