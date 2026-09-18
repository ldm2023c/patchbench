"""Read a persisted profile directory."""
import json
from pathlib import Path

from .model import Profile, SchemaError


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise SchemaError(f"invalid or missing {path.name}") from error


def load(root):
    root = Path(root)
    primary = _json(root / "profile.json")
    if not isinstance(primary, dict):
        raise SchemaError("invalid primary record")
    if primary.get("version") == 1:
        if set(primary) != {"version", "id", "name", "tags"}:
            raise SchemaError("invalid v1 primary")
        return Profile(primary["id"], primary["name"], ())
    if set(primary) != {"version", "id", "display_name"}:
        raise SchemaError("invalid v2 primary")
    companion = _json(root / "tags.json")
    if not isinstance(companion, dict) or set(companion) != {"profile_id", "tags"}:
        raise SchemaError("invalid companion")
    if companion["profile_id"] != primary["id"]:
        raise SchemaError("mismatched companion")
    return Profile(primary["id"], primary["display_name"], companion["tags"])
