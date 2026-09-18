import unittest

from byterange import RangeSyntaxError, ResolvedRange, UnsatisfiableRange, resolve_ranges


class ByteRangeTests(unittest.TestCase):
    def test_first_byte(self):
        self.assertEqual(resolve_ranges("bytes=0-0", 10), (ResolvedRange(0, 0),))

    def test_full_explicit_range(self):
        self.assertEqual(resolve_ranges("bytes=0-9", 10), (ResolvedRange(0, 9),))

    def test_middle_explicit_range(self):
        self.assertEqual(resolve_ranges("bytes=3-6", 10), (ResolvedRange(3, 6),))

    def test_last_byte(self):
        self.assertEqual(resolve_ranges("bytes=9-9", 10), (ResolvedRange(9, 9),))

    def test_open_ended_middle(self):
        self.assertEqual(resolve_ranges("bytes=2-", 10), (ResolvedRange(2, 9),))

    def test_open_ended_zero(self):
        self.assertEqual(resolve_ranges("bytes=0-", 10), (ResolvedRange(0, 9),))

    def test_suffix_short(self):
        self.assertEqual(resolve_ranges("bytes=-3", 10), (ResolvedRange(7, 9),))

    def test_suffix_equal_size(self):
        self.assertEqual(resolve_ranges("bytes=-10", 10), (ResolvedRange(0, 9),))

    def test_suffix_larger_than_size(self):
        self.assertEqual(resolve_ranges("bytes=-30", 10), (ResolvedRange(0, 9),))

    def test_clips_explicit_end(self):
        self.assertEqual(resolve_ranges("bytes=8-99", 10), (ResolvedRange(8, 9),))

    def test_clips_huge_end(self):
        self.assertEqual(resolve_ranges("bytes=1-999999999999999999999999", 4),
                         (ResolvedRange(1, 3),))

    def test_preserves_order_overlap_and_duplicates(self):
        self.assertEqual(resolve_ranges("bytes=7-9,0-2,7-9,2-4", 10),
            (ResolvedRange(7, 9), ResolvedRange(0, 2), ResolvedRange(7, 9), ResolvedRange(2, 4)))

    def test_mixed_member_forms(self):
        self.assertEqual(resolve_ranges("bytes=-2,3-,0-0", 10),
            (ResolvedRange(8, 9), ResolvedRange(3, 9), ResolvedRange(0, 0)))

    def test_leading_zeroes(self):
        self.assertEqual(resolve_ranges("bytes=003-004", 10), (ResolvedRange(3, 4),))

    def test_large_arbitrary_integer_is_unsatisfiable(self):
        with self.assertRaises(UnsatisfiableRange):
            resolve_ranges("bytes=999999999999999999999999-", 10)

    def test_open_ended_past_end_is_unsatisfiable(self):
        with self.assertRaises(UnsatisfiableRange):
            resolve_ranges("bytes=10-", 10)

    def test_explicit_start_past_end_is_unsatisfiable(self):
        with self.assertRaises(UnsatisfiableRange):
            resolve_ranges("bytes=10-99", 10)

    def test_zero_size_valid_forms_unsatisfiable(self):
        for header in ("bytes=0-0", "bytes=0-", "bytes=-1"):
            with self.subTest(header=header), self.assertRaises(UnsatisfiableRange):
                resolve_ranges(header, 0)

    def test_any_unsatisfiable_member_rejects_whole_call(self):
        with self.assertRaises(UnsatisfiableRange):
            resolve_ranges("bytes=0-1,10-20", 10)

    def test_malformed_member_precedes_unsatisfiable(self):
        with self.assertRaises(RangeSyntaxError):
            resolve_ranges("bytes=10-20,bad", 10)

    def test_reversed_explicit_is_syntax_error(self):
        with self.assertRaises(RangeSyntaxError):
            resolve_ranges("bytes=8-2", 10)

    def test_zero_suffix_is_syntax_error(self):
        with self.assertRaises(RangeSyntaxError):
            resolve_ranges("bytes=-0", 10)

    def test_wrong_unit_and_missing_equals(self):
        for header in ("items=0-1", "bytes0-1", "Bytes=0-1"):
            with self.subTest(header=header), self.assertRaises(RangeSyntaxError):
                resolve_ranges(header, 10)

    def test_empty_member(self):
        for header in ("bytes=", "bytes=0-1,", "bytes=,0-1", "bytes=0-1,,2-3"):
            with self.subTest(header=header), self.assertRaises(RangeSyntaxError):
                resolve_ranges(header, 10)

    def test_extra_hyphens_and_signed_decimal(self):
        for header in ("bytes=1-2-3", "bytes=--2", "bytes=+1-2", "bytes=1--2"):
            with self.subTest(header=header), self.assertRaises(RangeSyntaxError):
                resolve_ranges(header, 10)

    def test_non_ascii_and_non_decimal(self):
        for header in ("bytes=١-٢", "bytes=²-3", "bytes=0x1-2", "bytes=1.0-2"):
            with self.subTest(header=header), self.assertRaises(RangeSyntaxError):
                resolve_ranges(header, 10)

    def test_whitespace_disallowed_everywhere(self):
        for header in (" bytes=0-1", "bytes=0-1 ", "bytes=0 -1", "bytes=0-1, 2-3"):
            with self.subTest(header=header), self.assertRaises(RangeSyntaxError):
                resolve_ranges(header, 10)

    def test_invalid_resource_size(self):
        for size in (-1, True, 2.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                resolve_ranges("bytes=0-0", size)

    def test_header_must_be_text(self):
        with self.assertRaises(RangeSyntaxError):
            resolve_ranges(b"bytes=0-0", 10)


if __name__ == "__main__":
    unittest.main()
