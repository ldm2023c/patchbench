import io
import unittest

from eventstream import (ClosedStreamError, EventStreamDecoder, EventStreamError,
                         RecordTooLarge, read_events, read_file)


class EventStreamTests(unittest.TestCase):
    def test_simple_ascii(self):
        self.assertEqual(read_events([b'{"n":1}\n']), [{"n": 1}])

    def test_multiple_records(self):
        self.assertEqual(read_events([b'{}\n{"n":2}\n']), [{}, {"n": 2}])

    def test_empty_stream(self):
        self.assertEqual(read_events([]), [])

    def test_empty_chunks(self):
        self.assertEqual(read_events([b"", b'{}\n', b""]), [{}])

    def test_keepalives(self):
        self.assertEqual(read_events([b'\n\n{}\n\n']), [{}])

    def test_complete_crlf(self):
        self.assertEqual(read_events([b'{}\r\n\r\n{"a":1}\r\n']), [{}, {"a": 1}])

    def test_unicode_complete(self):
        self.assertEqual(read_events(['{"s":"雪"}\n'.encode()]), [{"s": "雪"}])

    def test_json_surrounding_whitespace(self):
        self.assertEqual(read_events([b' \t{} \t\n']), [{}])

    def test_split_json_record(self):
        decoder = EventStreamDecoder()
        self.assertEqual(decoder.feed(b'{"n":'), [])
        self.assertEqual(decoder.feed(b'1}\n'), [{"n": 1}])
        self.assertEqual(decoder.finish(), [])

    def test_every_byte_boundary(self):
        data = '{"s":"雪"}\r\n\n{"n":2}\n'.encode()
        for index in range(len(data) + 1):
            self.assertEqual(read_events([data[:index], data[index:]]), [{"s": "雪"}, {"n": 2}])

    def test_split_utf8(self):
        self.assertEqual(read_events([b'{"s":"\xe9', b'\x9b', b'\xaa"}\n']), [{"s": "雪"}])

    def test_split_crlf_pending(self):
        decoder = EventStreamDecoder(max_record_bytes=2)
        self.assertEqual(decoder.feed(b'{}\r'), [])
        self.assertEqual(decoder.feed(b'\n'), [{}])
        self.assertEqual(decoder.finish(), [])

    def test_finish_processes_unterminated(self):
        decoder = EventStreamDecoder()
        self.assertEqual(decoder.feed(b'{}'), [])
        self.assertEqual(decoder.finish(), [{}])

    def test_malformed_json_domain_error(self):
        with self.assertRaises(EventStreamError) as caught:
            read_events([b'nope\n'])
        self.assertEqual(caught.exception.record_number, 1)

    def test_non_object_json(self):
        for value in (b'[]\n', b'null\n', b'1\n', b'"text"\n'):
            with self.subTest(value=value), self.assertRaises(EventStreamError):
                read_events([value])

    def test_invalid_utf8_domain_error(self):
        with self.assertRaises(EventStreamError) as caught:
            read_events([b'\xff\n'])
        self.assertEqual(caught.exception.record_number, 1)

    def test_physical_record_numbers(self):
        with self.assertRaises(EventStreamError) as caught:
            read_events([b'\n{}\nbad\n'])
        self.assertEqual(caught.exception.record_number, 3)
        self.assertIn("record 3:", str(caught.exception))

    def test_invalid_utf8_after_keepalive(self):
        with self.assertRaises(EventStreamError) as caught:
            read_events([b'\n{}\n\xff\n'])
        self.assertEqual(caught.exception.record_number, 3)

    def test_whitespace_only_is_not_keepalive(self):
        with self.assertRaises(EventStreamError):
            read_events([b' \t\n'])

    def test_exact_byte_limit(self):
        self.assertEqual(read_events([b'{}\n'], max_record_bytes=2), [{}])

    def test_ascii_over_limit(self):
        with self.assertRaises(RecordTooLarge):
            read_events([b'{"x":1}\n'], max_record_bytes=6)

    def test_unicode_byte_limit(self):
        data = '{"s":"雪"}\n'.encode()
        with self.assertRaises(RecordTooLarge):
            read_events([data], max_record_bytes=len(data) - 2)

    def test_unfinished_record_size_enforced(self):
        with self.assertRaises(RecordTooLarge):
            EventStreamDecoder(max_record_bytes=8).feed(b' ' * 9)

    def test_pending_cr_becomes_content(self):
        decoder = EventStreamDecoder(max_record_bytes=2)
        self.assertEqual(decoder.feed(b'{}\r'), [])
        with self.assertRaises(RecordTooLarge):
            decoder.finish()

    def test_bare_cr_is_not_a_delimiter(self):
        with self.assertRaises(EventStreamError):
            read_events([b'{}\r{}\n'])

    def test_closed_stream(self):
        decoder = EventStreamDecoder()
        decoder.finish()
        with self.assertRaises(ClosedStreamError):
            decoder.feed(b"")
        with self.assertRaises(ClosedStreamError):
            decoder.finish()

    def test_invalid_configuration_and_chunk_type(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                EventStreamDecoder(limit)
        with self.assertRaises(TypeError):
            EventStreamDecoder().feed("{}\n")

    def test_reader_one_chunk(self):
        self.assertEqual(read_file(io.BytesIO(b'{}\n')), [{}])

    def test_reader_chunk_size_independence(self):
        data = '{"s":"雪"}\r\n{"n":2}'.encode()
        for size in (1, 2, 5, 11, 4096):
            self.assertEqual(read_file(io.BytesIO(data), chunk_size=size), [{"s": "雪"}, {"n": 2}])

    def test_reader_invalid_chunk_size(self):
        with self.assertRaises(ValueError):
            read_file(io.BytesIO(), chunk_size=0)

    def test_finish_error_still_closes(self):
        decoder = EventStreamDecoder()
        self.assertEqual(decoder.feed(b'{"x":'), [])
        with self.assertRaises(EventStreamError):
            decoder.finish()
        with self.assertRaises(ClosedStreamError):
            decoder.feed(b"")

    def test_pending_cr_followed_by_content_exceeds_limit(self):
        decoder = EventStreamDecoder(max_record_bytes=2)
        self.assertEqual(decoder.feed(b'{}\r'), [])
        with self.assertRaises(RecordTooLarge):
            decoder.feed(b' ')

    def test_unicode_line_separator_is_string_content(self):
        self.assertEqual(read_events(['{"s":"a\u2028b"}\n'.encode()]), [{"s": "a\u2028b"}])
