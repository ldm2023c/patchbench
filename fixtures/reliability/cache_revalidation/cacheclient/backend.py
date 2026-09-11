"""Deterministic backend double with per-key scripted outcomes."""
from collections import deque

from .errors import BackendUnavailable


class ScriptedBackend:
    def __init__(self):
        self._outcomes = {}
        self.calls = []

    def enqueue(self, key, *outcomes):
        self._outcomes.setdefault(key, deque()).extend(outcomes)

    def fetch(self, key, *, if_none_match=None):
        self.calls.append((key, if_none_match))
        queue = self._outcomes.get(key)
        if not queue:
            raise BackendUnavailable("no scripted response")
        outcome = queue.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
