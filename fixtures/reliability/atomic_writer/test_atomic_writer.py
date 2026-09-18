import unittest

from atomicfile import write_atomic


class MemoryFS:
    def __init__(self, target=b"old"):
        self.files = {"record": target} if target is not None else {}
        self.events = []
        self.write_error = None
        self.replace_error = None

    def write_temp(self, target, data):
        name = target + ".tmp"
        self.events.append("write")
        if name in self.files:
            raise RuntimeError("stale temp")
        self.files[name] = data[: max(1, len(data) // 2)] if self.write_error else data
        if self.write_error:
            raise self.write_error
        return name

    def replace(self, temp, target):
        self.events.append("replace")
        if self.replace_error:
            raise self.replace_error
        self.files[target] = self.files.pop(temp)

    def remove(self, temp):
        self.events.append("remove")
        self.files.pop(temp, None)


class AtomicWriterTests(unittest.TestCase):
    def test_simple_replace(self):
        fs = MemoryFS()
        write_atomic(fs, "record", b"new")
        self.assertEqual(fs.files, {"record": b"new"})

    def test_new_target(self):
        fs = MemoryFS(None)
        write_atomic(fs, "record", b"new")
        self.assertEqual(fs.files, {"record": b"new"})

    def test_empty_bytes(self):
        fs = MemoryFS()
        write_atomic(fs, "record", b"")
        self.assertEqual(fs.files, {"record": b""})

    def test_binary_bytes(self):
        fs = MemoryFS()
        write_atomic(fs, "record", bytes(range(16)))
        self.assertEqual(fs.files["record"], bytes(range(16)))

    def test_success_order(self):
        fs = MemoryFS()
        write_atomic(fs, "record", b"new")
        self.assertEqual(fs.events, ["write", "replace"])

    def test_two_successful_writes(self):
        fs = MemoryFS()
        write_atomic(fs, "record", b"first")
        write_atomic(fs, "record", b"second")
        self.assertEqual(fs.files, {"record": b"second"})

    def test_invalid_target_empty(self):
        fs = MemoryFS()
        with self.assertRaises(ValueError):
            write_atomic(fs, "", b"new")
        self.assertEqual(fs.events, [])

    def test_invalid_target_type(self):
        fs = MemoryFS()
        with self.assertRaises(ValueError):
            write_atomic(fs, None, b"new")
        self.assertEqual(fs.events, [])

    def test_invalid_data(self):
        fs = MemoryFS()
        with self.assertRaises(TypeError):
            write_atomic(fs, "record", "new")
        self.assertEqual(fs.events, [])

    def test_write_failure_preserves_target(self):
        fs = MemoryFS()
        error = OSError("write")
        fs.write_error = error
        with self.assertRaises(OSError) as caught:
            write_atomic(fs, "record", b"replacement")
        self.assertIs(caught.exception, error)
        self.assertEqual(fs.files["record"], b"old")

    def test_write_failure_removes_partial_temp(self):
        fs = MemoryFS()
        fs.write_error = OSError("write")
        with self.assertRaises(OSError):
            write_atomic(fs, "record", b"replacement")
        self.assertNotIn("record.tmp", fs.files)

    def test_replace_failure_preserves_target(self):
        fs = MemoryFS()
        error = OSError("replace")
        fs.replace_error = error
        with self.assertRaises(OSError) as caught:
            write_atomic(fs, "record", b"replacement")
        self.assertIs(caught.exception, error)
        self.assertEqual(fs.files["record"], b"old")

    def test_replace_failure_removes_temp(self):
        fs = MemoryFS()
        fs.replace_error = OSError("replace")
        with self.assertRaises(OSError):
            write_atomic(fs, "record", b"replacement")
        self.assertNotIn("record.tmp", fs.files)

    def test_retry_after_write_failure(self):
        fs = MemoryFS()
        fs.write_error = OSError("write")
        with self.assertRaises(OSError):
            write_atomic(fs, "record", b"replacement")
        fs.write_error = None
        write_atomic(fs, "record", b"replacement")
        self.assertEqual(fs.files, {"record": b"replacement"})

    def test_retry_after_replace_failure(self):
        fs = MemoryFS()
        fs.replace_error = OSError("replace")
        with self.assertRaises(OSError):
            write_atomic(fs, "record", b"replacement")
        fs.replace_error = None
        write_atomic(fs, "record", b"replacement")
        self.assertEqual(fs.files, {"record": b"replacement"})

    def test_target_not_removed_before_replace(self):
        fs = MemoryFS()
        fs.replace_error = OSError("replace")
        with self.assertRaises(OSError):
            write_atomic(fs, "record", b"new")
        self.assertEqual(fs.files["record"], b"old")


if __name__ == "__main__":
    unittest.main()
