"""Cached representation storage and freshness policy."""
from .clock import ticks
from .model import Entry


class Cache:
    def __init__(self, fresh_ttl=10, stale_if_error_ttl=20):
        self.fresh_ttl = ticks(fresh_ttl)
        self.stale_if_error_ttl = ticks(stale_if_error_ttl)
        self._entries = {}

    def lookup(self, key):
        return self._entries.get(key)

    def state(self, entry, now):
        age = now - entry.fetched_at
        if age < self.fresh_ttl:
            return "fresh"
        if age <= self.fresh_ttl + self.stale_if_error_ttl:
            return "stale"
        return "expired"

    def replace(self, key, response, now):
        previous = self.lookup(key)
        validator = previous.validator if previous is not None else response.validator
        entry = Entry(response.body, validator, now)
        self._entries[key] = entry
        return entry

    def refresh(self, key, now):
        entry = self._entries[key]
        refreshed = Entry(entry.body, None, now)
        self._entries[key] = refreshed
        return refreshed
