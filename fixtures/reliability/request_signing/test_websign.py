import hashlib
import hmac
import unittest
from unittest.mock import patch

from websign import (CanonicalizationError, Request, canonical_headers,
                     canonical_query, canonical_request, sign, verify)


class WebsignTests(unittest.TestCase):
    def request(self, query="", headers=None, body=b"", method="POST", path="/hook"):
        return Request(method, path, query, [("Host", "example.org")] if headers is None else headers, body)

    def test_simple_legacy_request(self):
        request = Request("POST", "/hook", "a=1", {"Host": "example.org"}, b"hi")
        self.assertTrue(verify(request, b"key", sign(request, b"key")))

    def test_empty_query(self):
        self.assertEqual(canonical_query(""), "")

    def test_query_sorting(self):
        self.assertEqual(canonical_query("z=9&a=1"), "a=1&z=9")

    def test_duplicate_query_values(self):
        self.assertEqual(canonical_query("a=2&a=1&a=1"), "a=1&a=1&a=2")

    def test_empty_names_values_and_bare_keys(self):
        self.assertEqual(canonical_query("=v&flag&x="), "=v&flag=&x=")

    def test_empty_components(self):
        self.assertEqual(canonical_query("&"), "=&=")

    def test_literal_plus(self):
        self.assertEqual(canonical_query("x=a+b"), "x=a%2Bb")

    def test_percent_space_uses_rfc3986(self):
        self.assertEqual(canonical_query("x=a%20b"), "x=a%20b")

    def test_percent_decode_once(self):
        self.assertEqual(canonical_query("x=%252F"), "x=%252F")

    def test_hex_case_and_encoded_delimiters(self):
        self.assertEqual(canonical_query("x=%2f%26%3d"), "x=%2F%26%3D")

    def test_split_only_first_equals(self):
        self.assertEqual(canonical_query("x=a=b"), "x=a%3Db")

    def test_unreserved_characters(self):
        self.assertEqual(canonical_query("x=AZaz09-._~"), "x=AZaz09-._~")

    def test_unicode_query(self):
        self.assertEqual(canonical_query("x=雪"), "x=%E9%9B%AA")

    def test_malformed_percent_escape(self):
        for query in ("x=%", "x=%2", "x=%GG"):
            with self.subTest(query=query), self.assertRaises(CanonicalizationError):
                canonical_query(query)

    def test_invalid_utf8(self):
        with self.assertRaises(CanonicalizationError):
            canonical_query("x=%FF")

    def test_sort_encoded_names_not_decoded(self):
        self.assertEqual(canonical_query("z=1&é=2"), "%C3%A9=2&z=1")

    def test_header_case_and_selection(self):
        self.assertEqual(canonical_headers([("HOST", "example.org"), ("X-Noise", "ignored")], ["Host"]),
                         ("host:example.org", "host"))

    def test_repeated_headers_preserve_arrival_order(self):
        self.assertEqual(canonical_headers([("X-Tag", "one"), ("x-tag", "two")], ["x-tag"]),
                         ("x-tag:one,two", "x-tag"))

    def test_header_ows_collapsed(self):
        self.assertEqual(canonical_headers([("X-Tag", " \tone\t  two \t")], ["x-tag"]),
                         ("x-tag:one two", "x-tag"))

    def test_empty_repeated_header_values(self):
        self.assertEqual(canonical_headers([("X", ""), ("x", " v ")], ["x"]), ("x:,v", "x"))

    def test_only_sp_htab_are_trimmed(self):
        self.assertEqual(canonical_headers([("X", "\u00a0value\u00a0")], ["x"]), ("x:\u00a0value\u00a0", "x"))

    def test_signed_names_sorted_and_deduplicated(self):
        self.assertEqual(canonical_headers([("Z", "2"), ("A", "1")], ["z", "A", "a"]),
                         ("a:1\nz:2", "a;z"))

    def test_required_header_missing(self):
        with self.assertRaises(CanonicalizationError):
            canonical_headers([], ["host"])

    def test_empty_header_selection(self):
        self.assertEqual(canonical_headers([], []), ("", ""))

    def test_invalid_request_inputs(self):
        for kwargs in ({"method": "bad method"}, {"path": "relative"}, {"body": "text"},
                       {"headers": [("Host", "a\nb")]}, {"headers": [("bad name", "x")]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CanonicalizationError):
                self.request(**kwargs)
        with self.assertRaises(CanonicalizationError):
            canonical_headers([], "host")

    def test_canonical_request_exact_vector(self):
        expected = b"POST\n/hook\na=1\nhost:example.org\nhost\n" + hashlib.sha256(b"hi").hexdigest().encode()
        self.assertEqual(canonical_request(self.request("a=1", body=b"hi", method="post"), ["host"]), expected)

    def test_hmac_matches_independent_fixed_vector(self):
        message = b"POST\n/hook\na=1\nhost:example.org\nhost\n" + hashlib.sha256(b"hi").hexdigest().encode()
        self.assertEqual(sign(self.request("a=1", body=b"hi"), b"key"), hmac.new(b"key", message, hashlib.sha256).hexdigest())

    def test_body_bytes_and_path_preserved(self):
        original = self.request(body=b"\x00\xff", path="/a%2Fb")
        signature = sign(original, b"key")
        self.assertFalse(verify(self.request(body=b"\x00\xfe", path="/a%2Fb"), b"key", signature))
        self.assertFalse(verify(self.request(body=b"\x00\xff", path="/a/b"), b"key", signature))

    def test_wrong_key_signature_and_method(self):
        request = self.request()
        signature = sign(request, b"key")
        self.assertFalse(verify(request, b"other", signature))
        self.assertFalse(verify(request, b"key", "not-hex"))
        self.assertFalse(verify(self.request(method="GET"), b"key", signature))

    def test_equivalent_duplicate_query_requests_verify(self):
        signature = sign(self.request("a=1&a=2"), b"key")
        self.assertTrue(verify(self.request("a=2&a=1"), b"key", signature))

    def test_equivalent_header_ows_requests_verify(self):
        signature = sign(self.request(headers=[("Host", " a  b ")]), b"key")
        self.assertTrue(verify(self.request(headers=[("HOST", "a\tb")]), b"key", signature))

    def test_unsigned_headers_do_not_change_signature(self):
        self.assertEqual(sign(self.request(), b"key"), sign(self.request(headers=[("Host", "example.org"), ("Extra", "value")]), b"key"))

    def test_malformed_input_propagates_through_sign_and_verify(self):
        for name, operation in (("sign", lambda r: sign(r, b"key")), ("verify", lambda r: verify(r, b"key", "bad"))):
            with self.subTest(operation=name), self.assertRaises(CanonicalizationError):
                operation(self.request("x=%GG"))

    def test_verification_uses_constant_time_comparison(self):
        request = self.request()
        signature = sign(request, b"key")
        original = hmac.compare_digest
        with patch("hmac.compare_digest", wraps=original) as compare:
            self.assertTrue(verify(request, b"key", signature))
        compare.assert_called_once_with(signature, signature)

    def test_request_preserves_repeated_headers_and_body(self):
        headers = [("X", "a"), ("x", "b")]
        request = self.request(headers=headers, body=b"\x00\xff")
        headers.append(("x", "later"))
        self.assertEqual(request.headers, (("X", "a"), ("x", "b")))
        self.assertEqual(request.body, b"\x00\xff")
