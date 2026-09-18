import unittest

from formatload import FormatError, Settings, load


class Source:
    def __init__(self, current='{"mode":"safe","retries":2}', legacy='mode=old\nretries=1', current_error=None, legacy_error=None):
        self.current, self.legacy = current, legacy
        self.current_error, self.legacy_error = current_error, legacy_error
        self.calls = []

    def read_current(self):
        self.calls.append("current")
        if self.current_error:
            raise self.current_error
        return self.current

    def read_legacy(self):
        self.calls.append("legacy")
        if self.legacy_error:
            raise self.legacy_error
        return self.legacy


class FallbackTests(unittest.TestCase):
    def test_current_wins(self):
        source = Source()
        self.assertEqual(load(source), Settings("safe", 2))
        self.assertEqual(source.calls, ["current"])

    def test_current_zero_retries(self):
        self.assertEqual(load(Source(current='{"mode":"fast","retries":0}')), Settings("fast", 0))

    def test_current_max_retries(self):
        self.assertEqual(load(Source(current='{"mode":"fast","retries":5}')), Settings("fast", 5))

    def test_legacy_on_missing_current(self):
        source = Source(current_error=FileNotFoundError("current"))
        self.assertEqual(load(source), Settings("old", 1))
        self.assertEqual(source.calls, ["current", "legacy"])

    def test_legacy_blank_lines(self):
        source = Source(current_error=FileNotFoundError(), legacy='\nmode=old\n\nretries=1\n')
        self.assertEqual(load(source), Settings("old", 1))

    def test_legacy_whitespace(self):
        source = Source(current_error=FileNotFoundError(), legacy='mode = old\n retries = 1')
        self.assertEqual(load(source), Settings("old", 1))

    def test_both_absent(self):
        source = Source(current_error=FileNotFoundError(), legacy_error=FileNotFoundError("legacy"))
        with self.assertRaises(FileNotFoundError):
            load(source)
        self.assertEqual(source.calls, ["current", "legacy"])

    def test_malformed_legacy(self):
        source = Source(current_error=FileNotFoundError(), legacy='mode=old\nretries=no')
        with self.assertRaises(FormatError):
            load(source)

    def test_legacy_duplicate(self):
        source = Source(current_error=FileNotFoundError(), legacy='mode=old\nmode=new\nretries=1')
        with self.assertRaises(FormatError):
            load(source)

    def test_current_mode_preserved(self):
        self.assertEqual(load(Source(current='{"mode":"custom","retries":3}')).mode, "custom")

    def test_missing_current_field_rejected_without_fallback(self):
        source = Source(current='{"mode":"safe"}')
        with self.assertRaises(FormatError):
            load(source)
        self.assertEqual(source.calls, ["current"])

    def test_malformed_current_json_no_fallback(self):
        source = Source(current='{bad')
        with self.assertRaises(FormatError):
            load(source)
        self.assertEqual(source.calls, ["current"])

    def test_invalid_current_value_no_fallback(self):
        source = Source(current='{"mode":"safe","retries":true}')
        with self.assertRaises(FormatError):
            load(source)
        self.assertEqual(source.calls, ["current"])

    def test_permission_error_no_fallback(self):
        error = PermissionError("denied")
        source = Source(current_error=error)
        with self.assertRaises(PermissionError) as caught:
            load(source)
        self.assertIs(caught.exception, error)
        self.assertEqual(source.calls, ["current"])

    def test_unrelated_io_error_no_fallback(self):
        error = OSError("device failure")
        source = Source(current_error=error)
        with self.assertRaises(OSError) as caught:
            load(source)
        self.assertIs(caught.exception, error)
        self.assertEqual(source.calls, ["current"])


if __name__ == "__main__":
    unittest.main()
