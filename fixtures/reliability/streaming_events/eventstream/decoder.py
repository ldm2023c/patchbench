"""Incremental interface for importing JSON object records."""
import json

from .errors import ClosedStreamError, EventStreamError, RecordTooLarge


class EventStreamDecoder:
    def __init__(self, max_record_bytes=65536):
        if isinstance(max_record_bytes, bool) or not isinstance(max_record_bytes, int) or max_record_bytes <= 0:
            raise ValueError("max_record_bytes must be a positive integer")
        self.max_record_bytes = max_record_bytes
        self.record_number = 1
        self.closed = False

    def _check_open(self):
        if self.closed:
            raise ClosedStreamError(self.record_number, "stream is closed")

    def _record(self, text):
        number = self.record_number
        self.record_number += 1
        if len(text) > self.max_record_bytes:
            raise RecordTooLarge(number, "record exceeds byte limit")
        text = text.strip()
        if not text:
            return None
        try:
            event = json.loads(text)
        except ValueError as error:
            raise EventStreamError(number, "invalid JSON") from error
        if not isinstance(event, dict):
            raise EventStreamError(number, "expected JSON object")
        return event

    def feed(self, chunk):
        self._check_open()
        if not isinstance(chunk, bytes):
            raise TypeError("chunk must be bytes")
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EventStreamError(self.record_number, "invalid UTF-8") from error
        events = []
        for line in text.splitlines():
            event = self._record(line)
            if event is not None:
                events.append(event)
        return events

    def finish(self):
        self._check_open()
        self.closed = True
        return []
