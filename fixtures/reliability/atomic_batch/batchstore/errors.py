"""Errors exposed by the batch service."""
class BatchError(Exception):
    pass


class ValidationError(BatchError):
    pass


class PreconditionError(BatchError):
    pass


class IdempotencyConflict(BatchError):
    pass
