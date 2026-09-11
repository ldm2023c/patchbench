"""Public errors for the event-log import boundary."""


class EventStreamError(ValueError):
    def __init__(self, record_number, reason):
        self.record_number = record_number
        super().__init__(f"record {record_number}: {reason}")


class RecordTooLarge(EventStreamError):
    """A physical record exceeds the configured raw-byte budget."""


class ClosedStreamError(EventStreamError):
    """An operation was attempted after stream finalization."""
