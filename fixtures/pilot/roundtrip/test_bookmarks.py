import unittest

from bookmarks.codec import decode, encode
from bookmarks.document import dumps, loads
from bookmarks.model import Bookmark


class BookmarkTests(unittest.TestCase):
    def check_roundtrip(self, record):
        self.assertEqual(decode(encode(record)), record)

    def test_simple_legacy_record(self):
        self.assertEqual(decode("Guide|https://example.org"),
                         Bookmark("Guide", "https://example.org"))

    def test_absent_note(self):
        self.check_roundtrip(Bookmark("Guide", "https://example.org"))

    def test_empty_note_stays_present(self):
        self.check_roundtrip(Bookmark("Guide", "https://example.org", ""))

    def test_delimiter_in_title(self):
        self.check_roundtrip(Bookmark("Tools | Guides", "https://example.org", "read"))

    def test_delimiter_in_url(self):
        self.check_roundtrip(Bookmark("Search", "https://example.org/?q=a|b"))

    def test_backslash_before_delimiter(self):
        self.check_roundtrip(Bookmark("Path", "https://example.org", "folder\\|next"))

    def test_literal_backslash_n(self):
        self.check_roundtrip(Bookmark("Path", "https://example.org", r"folder\new"))

    def test_newline_and_carriage_return(self):
        self.check_roundtrip(Bookmark("Notes", "https://example.org", "one\ntwo\rthree"))

    def test_whitespace_and_unicode_preserved(self):
        record = Bookmark(" 旅行 ", "https://example.org", "  later\u2028today  ")
        self.check_roundtrip(record)
        self.assertEqual(loads(dumps([record])), [record])

    def test_multiple_records_document(self):
        records = [Bookmark("A|B", "https://a.org", ""), Bookmark("C", "https://c.org")]
        self.assertEqual(loads(dumps(records)), records)

    def test_empty_document_and_blank_lines(self):
        self.assertEqual(dumps([]), "")
        self.assertEqual(loads("\n\n"), [])

    def test_invalid_escape_reports_line_number(self):
        with self.assertRaisesRegex(ValueError, "line 2: invalid escape"):
            loads("Good|https://a.org\nBad|https://b.org|oops\\q\n")

    def test_malformed_records_rejected(self):
        for line in ["only-title", "A|https://a.org|note|extra",
                     "A|https://a.org|trailing\\", "|https://a.org", "A|ftp://a.org"]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                decode(line)

    def test_canonical_wire_records(self):
        cases = [
            (r"Tools\|Guides|https://example.org", Bookmark("Tools|Guides", "https://example.org")),
            (r"Path|https://example.org|folder\\next", Bookmark("Path", "https://example.org", "folder\\next")),
            (r"Notes|https://example.org|one\ntwo\rthree", Bookmark("Notes", "https://example.org", "one\ntwo\rthree")),
            ("Guide|https://example.org|", Bookmark("Guide", "https://example.org", "")),
            ("Guide|https://example.org", Bookmark("Guide", "https://example.org")),
        ]
        for encoded, record in cases:
            with self.subTest(encoded=encoded, direction="decode"):
                self.assertEqual(decode(encoded), record)
            with self.subTest(encoded=encoded, direction="encode"):
                self.assertEqual(encode(record), encoded)
