"""Public resource-client errors."""
class CacheError(Exception):
    pass


class ValidationError(CacheError):
    pass


class BackendUnavailable(CacheError):
    pass


class ProtocolError(CacheError):
    pass
