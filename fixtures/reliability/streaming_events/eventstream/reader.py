"""Convenience adapters; framing belongs exclusively to EventStreamDecoder."""
from .decoder import EventStreamDecoder


def read_events(chunks, *, max_record_bytes=65536):
    decoder = EventStreamDecoder(max_record_bytes=max_record_bytes)
    events = []
    for chunk in chunks:
        events.extend(decoder.feed(chunk))
    events.extend(decoder.finish())
    return events


def read_file(stream, *, chunk_size=4096, max_record_bytes=65536):
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    return read_events(iter(lambda: stream.read(chunk_size), b""),
                       max_record_bytes=max_record_bytes)
