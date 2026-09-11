"""Ordered committed-event journal."""
from .errors import ValidationError
from .model import Event


class Journal:
    def __init__(self):
        self._entries = []

    def snapshot(self):
        return tuple(self._entries)

    def append_batch(self, events):
        if not isinstance(events, (list, tuple)):
            raise ValidationError("events must be a list or tuple")
        for event in events:
            if not isinstance(event, Event):
                raise ValidationError("invalid journal event")
            self._entries.append(event)
