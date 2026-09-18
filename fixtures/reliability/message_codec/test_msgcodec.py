import unittest

from msgcodec import Message, MessageError, decode, encode


class MessageCodecTests(unittest.TestCase):
    def test_canonical_ascii_vector(self):
        message = Message("m1", "event", 3, {"ok": True, "count": 2})
        self.assertEqual(encode(message),
            b'{"id":"m1","kind":"event","payload":{"count":2,"ok":true},"priority":3,"version":2}')

    def test_decode_current_vector(self):
        wire = b'{"version":2,"payload":{"ok":true},"priority":4,"kind":"command","id":"m2"}'
        self.assertEqual(decode(wire), Message("m2", "command", 4, {"ok": True}))

    def test_roundtrip_nonzero_priority(self):
        message = Message("job", "command", 7, {"count": 5, "ready": False})
        self.assertEqual(decode(encode(message)), message)

    def test_roundtrip_zero_priority(self):
        message = Message("job", "event", 0, {})
        self.assertEqual(decode(encode(message)), message)

    def test_trace_id_roundtrip(self):
        message = Message("m", "event", 2, {"x": None}, "trace-7")
        self.assertEqual(decode(encode(message)), message)

    def test_none_trace_omitted(self):
        self.assertNotIn(b"trace_id", encode(Message("m", "event", 2, {})))

    def test_canonical_unicode_bytes(self):
        self.assertEqual(encode(Message("caf\u00e9", "event", 1, {"city": "\u6771\u4eac"})),
            '{"id":"café","kind":"event","payload":{"city":"東京"},"priority":1,"version":2}'.encode("utf-8"))

    def test_canonical_zero_priority_vector(self):
        self.assertEqual(encode(Message("m", "event", 0, {})),
            b'{"id":"m","kind":"event","payload":{},"priority":0,"version":2}')

    def test_v1_type_maps_to_kind_and_default_priority(self):
        self.assertEqual(decode(b'{"version":1,"id":"old","type":"event","payload":{"n":1}}'),
                         Message("old", "event", 0, {"n": 1}))

    def test_v1_reencodes_as_v2(self):
        old = b'{"version":1,"id":"old","type":"command","payload":{}}'
        self.assertEqual(encode(decode(old)),
            b'{"id":"old","kind":"command","payload":{},"priority":0,"version":2}')

    def test_future_version_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":3,"id":"x","kind":"event","priority":1,"payload":{}}')

    def test_unknown_v2_field_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","kind":"event","priority":1,"payload":{},"extra":1}')

    def test_unknown_v1_field_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":1,"id":"x","type":"event","payload":{},"priority":1}')

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","id":"y","kind":"event","priority":1,"payload":{}}')

    def test_present_null_trace_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","kind":"event","priority":1,"payload":{},"trace_id":null}')

    def test_missing_required_priority_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","kind":"event","payload":{}}')

    def test_bool_priority_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","kind":"event","priority":true,"payload":{}}')

    def test_unknown_kind_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'{"version":2,"id":"x","kind":"other","priority":1,"payload":{}}')

    def test_bad_payload_values_rejected(self):
        for fragment in (b'[]', b'{"n":1.5}', b'{"n":[1]}', b'{"n":{}}'):
            with self.subTest(fragment=fragment), self.assertRaises(MessageError):
                decode(b'{"version":2,"id":"x","kind":"event","priority":1,"payload":' + fragment + b'}')

    def test_invalid_utf8_is_message_error(self):
        with self.assertRaises(MessageError):
            decode(b'\xff')

    def test_invalid_json_is_message_error(self):
        with self.assertRaises(MessageError):
            decode(b'{broken')

    def test_model_rejects_bad_types(self):
        for args in (("", "event", 0, {}), ("m", "other", 0, {}),
                     ("m", "event", True, {}), ("m", "event", 10, {}),
                     ("m", "event", 0, {"n": 1.5}), ("m", "event", 0, {}, "")):
            with self.subTest(args=args), self.assertRaises(MessageError):
                Message(*args)

    def test_model_copies_payload(self):
        source = {"n": 1}
        message = Message("m", "event", 1, source)
        source["n"] = 2
        self.assertEqual(message.payload, {"n": 1})

    def test_model_rejects_unpaired_surrogate(self):
        for args in (("\ud800", "event", 1, {}), ("m", "event", 1, {"x": "\ud800"})):
            with self.subTest(args=args), self.assertRaises(MessageError):
                Message(*args)

    def test_payload_integer_bounds(self):
        message = Message("m", "event", 1, {"low": -(2 ** 63), "high": 2 ** 63 - 1})
        self.assertEqual(decode(encode(message)), message)

    def test_payload_integer_overflow_rejected(self):
        for value in (-(2 ** 63) - 1, 2 ** 63):
            with self.subTest(value=value), self.assertRaises(MessageError):
                Message("m", "event", 1, {"count": value})

    def test_wrong_top_level_rejected(self):
        with self.assertRaises(MessageError):
            decode(b'[]')

    def test_nonbytes_wire_rejected(self):
        with self.assertRaises(MessageError):
            decode('{"version":2}')


if __name__ == "__main__":
    unittest.main()
