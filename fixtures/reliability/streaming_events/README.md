# Eventstream importer

A small event-log import library for byte-stream transports. Python 3.12,
standard library only; no network transport is needed to exercise this package.

```python
from eventstream import EventStreamDecoder
stream = EventStreamDecoder(max_record_bytes=65536)
events = stream.feed(b'{"event":"created"}\n')
events += stream.finish()
```

`feed(bytes)` accepts arbitrary byte boundaries, including inside JSON records,
UTF-8 code points, and CRLF. It returns completed events in order. Empty chunks
are harmless. A partial physical record stays pending until LF or `finish()`;
chunk boundaries never delimit records. Equivalent byte streams must produce
identical events under any chunking. Non-bytes input raises TypeError.

Records are UTF-8 JSON objects delimited by LF or CRLF. Only the single CR
immediately preceding LF belongs to the delimiter. An ordinary CR is record
content. Empty physical records are keepalives, returning no event, but still
advance the physical record number. Do not strip other whitespace: JSON may
accept surrounding whitespace, but a whitespace-only non-empty record is invalid.
A final non-empty record without LF is parsed by `finish()`; a trailing LF does
not invent another record. Raw Unicode line separators inside JSON strings are
content, not transport delimiters.

Errors are EventStreamError instances with a 1-based `record_number` and message
`record N: ...`. Invalid UTF-8, malformed JSON and non-object JSON must be wrapped
in this domain error. No unwrapped UnicodeDecodeError or JSONDecodeError escapes.
After a record error the caller should discard the decoder; recovery is not part
of this API. No guarantee is made about returning earlier events from the same
feed call if a later record in that call fails.

`max_record_bytes` is a positive integer (not bool). It limits raw record bytes,
excluding LF or CRLF, and is enforced even before an unfinished oversized record
can grow indefinitely. A pending final CR may be held provisionally beyond the
limit by one byte while waiting to see whether LF follows. If another byte
follows, or EOF occurs, that CR is content and counts toward the limit.
Oversize input raises RecordTooLarge, a subclass of EventStreamError.

`finish()` closes the stream exactly once, including when final parsing fails.
Further feed/finish calls raise ClosedStreamError, also an EventStreamError.
`read_events(iterable_of_bytes)` and `read_file(binary_stream, chunk_size=...)`
share decoder semantics. Reader framing must not be duplicated. Positive integer
chunk sizes and the same byte-size limits apply.

Run all visible tests: `python -B -m unittest -v`.
