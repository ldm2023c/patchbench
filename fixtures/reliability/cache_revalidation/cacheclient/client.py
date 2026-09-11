"""Resource lookup, conditional refresh and backend fallback."""
from .cache import Cache
from .errors import BackendUnavailable, ProtocolError
from .model import NotModified, Value, resource_key


class Client:
    def __init__(self, backend, clock, cache=None):
        self.backend = backend
        self.clock = clock
        self.cache = cache if cache is not None else Cache()

    def get(self, key):
        resource_key(key)
        now = self.clock()
        entry = self.cache.lookup(key)
        if entry is not None and self.cache.state(entry, now) == "fresh":
            return entry.body
        validator = entry.validator if entry is not None else None
        if entry is not None:
            self.cache.refresh(key, now)
        try:
            response = self.backend.fetch(key, if_none_match=validator)
        except BackendUnavailable:
            if entry is not None:
                return entry.body
            raise
        if isinstance(response, NotModified):
            if entry is None or validator is None:
                raise ProtocolError("not-modified requires a cached validator")
            return self.cache.refresh(key, self.clock()).body
        if isinstance(response, Value):
            return self.cache.replace(key, response, self.clock()).body
        raise ProtocolError("unexpected backend response")
