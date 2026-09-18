"""Persist a current profile."""
import json
from pathlib import Path

from .model import Profile


def save(root, profile):
    if not isinstance(profile, Profile):
        raise TypeError("profile must be Profile")
    root = Path(root)
    record = {"version": 1, "id": profile.profile_id,
              "name": profile.display_name, "tags": list(profile.tags)}
    (root / "profile.json").write_text(json.dumps(record), encoding="utf-8")
