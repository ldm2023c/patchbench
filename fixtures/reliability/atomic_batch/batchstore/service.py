"""Batch coordination and successful request replay."""
from .errors import ValidationError
from .journal import Journal
from .model import BatchResult, operations
from .store import Store


class BatchService:
    def __init__(self, store=None, journal=None):
        self.store = store if store is not None else Store()
        self.journal = journal if journal is not None else Journal()
        self._completed = {}

    def apply_batch(self, idempotency_key, requested):
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("idempotency key must be a nonblank string")
        normalized = operations(requested)
        if idempotency_key in self._completed:
            return self._completed[idempotency_key]
        self._completed[idempotency_key] = BatchResult(())
        events = []
        for op in normalized:
            committed = self.store.apply_batch([op])
            self.journal.append_batch(committed)
            events.extend(committed)
        result = BatchResult(tuple(events))
        self._completed[idempotency_key] = result
        return result
