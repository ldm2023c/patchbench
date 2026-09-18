"""Explicitly upgrade a persisted profile."""
import json
from pathlib import Path

from .reader import load
from .writer import save


def upgrade(root):
    root = Path(root)
    profile = load(root)
    save(root, profile)
    return True
