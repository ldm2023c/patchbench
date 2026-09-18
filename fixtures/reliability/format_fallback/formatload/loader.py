"""Load a preferred JSON format with an older line-oriented fallback."""
from dataclasses import dataclass
import json


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    mode: str
    retries: int


def _settings(fields):
    if not isinstance(fields, dict) or set(fields) != {"mode", "retries"}:
        raise FormatError("expected mode and retries")
    mode, retries = fields["mode"], fields["retries"]
    if not isinstance(mode, str) or not mode or type(retries) is not int or not 0 <= retries <= 5:
        raise FormatError("invalid settings")
    return Settings(mode, retries)


def _current(text):
    try:
        return _settings(json.loads(text))
    except (ValueError, TypeError) as error:
        raise FormatError("invalid current format") from error


def _legacy(text):
    fields = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.count("=") != 1:
            raise FormatError("invalid legacy line")
        key, value = (part.strip() for part in line.split("=", 1))
        if key in fields:
            raise FormatError("duplicate legacy field")
        fields[key] = value
    try:
        fields["retries"] = int(fields["retries"])
    except (KeyError, ValueError) as error:
        raise FormatError("invalid legacy retries") from error
    return _settings(fields)


def load(source):
    try:
        return _current(source.read_current())
    except (OSError, ValueError):
        return _legacy(source.read_legacy())
