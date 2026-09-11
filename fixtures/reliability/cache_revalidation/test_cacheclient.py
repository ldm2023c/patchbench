import unittest

from cacheclient import (BackendUnavailable, Cache, Client, Entry, ManualClock,
                         NotModified, ProtocolError, ScriptedBackend, ValidationError, Value)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.backend = ScriptedBackend()
        self.cache = Cache(fresh_ttl=10, stale_if_error_ttl=20)
        self.client = Client(self.backend, self.clock, self.cache)

    def seed(self, validator="v1"):
        self.backend.enqueue("a", Value(b"old", validator))
        self.assertEqual(self.client.get("a"), b"old")

    def test_miss_success(self):
        self.seed()
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 0))
        self.assertEqual(self.backend.calls, [("a", None)])

    def test_miss_error(self):
        with self.assertRaises(BackendUnavailable):
            self.client.get("a")
        self.assertIsNone(self.cache.lookup("a"))

    def test_fresh_hit(self):
        self.seed()
        self.clock.advance(9)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls, [("a", None)])

    def test_fresh_boundary_equality(self):
        self.seed()
        self.clock.advance(10)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls, [("a", None)])
        self.assertEqual(self.cache.lookup("a").fetched_at, 0)

    def test_stale_conditional_request(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", NotModified())
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls[-1], ("a", "v1"))

    def test_304_preserves_validator(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", NotModified())
        self.client.get("a")
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 11))

    def test_304_makes_entry_fresh(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", NotModified())
        self.client.get("a")
        self.clock.advance(9)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(len(self.backend.calls), 2)

    def test_304_next_revalidation_uses_same_validator(self):
        self.seed()
        self.backend.enqueue("a", NotModified(), NotModified())
        self.clock.advance(11)
        self.client.get("a")
        self.clock.advance(11)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls, [("a", None), ("a", "v1"), ("a", "v1")])

    def test_replacement_body(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", Value(b"new", "v2"))
        self.assertEqual(self.client.get("a"), b"new")
        self.assertEqual(self.cache.lookup("a").fetched_at, 11)

    def test_replacement_validator(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", Value(b"new", "v2"))
        self.client.get("a")
        self.assertEqual(self.cache.lookup("a"), Entry(b"new", "v2", 11))

    def test_replacement_next_conditional(self):
        self.seed()
        self.backend.enqueue("a", Value(b"new", "v2"), Value(b"latest", "v3"))
        self.clock.advance(11)
        self.client.get("a")
        self.clock.advance(11)
        self.client.get("a")
        self.assertEqual(self.backend.calls[-1], ("a", "v2"))

    def test_no_validator_unconditional(self):
        self.seed(None)
        self.clock.advance(11)
        self.backend.enqueue("a", Value(b"new"))
        self.assertEqual(self.client.get("a"), b"new")
        self.assertEqual(self.backend.calls[-1], ("a", None))

    def test_replacement_removes_validator(self):
        self.cache.replace("a", Value(b"old", "v1"), 0)
        self.cache.replace("a", Value(b"new"), 1)
        self.assertEqual(self.cache.lookup("a"), Entry(b"new", None, 1))

    def test_stale_error_fallback(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", BackendUnavailable("offline"))
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls[-1], ("a", "v1"))

    def test_failed_refresh_does_not_change_entry(self):
        self.seed()
        before = self.cache.lookup("a")
        self.clock.advance(11)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.cache.lookup("a"), before)

    def test_repeated_stale_failure_retries(self):
        self.seed()
        self.clock.advance(11)
        self.client.get("a")
        self.client.get("a")
        self.assertEqual(self.backend.calls, [("a", None), ("a", "v1"), ("a", "v1")])

    def test_expired_error_propagates(self):
        self.seed()
        self.clock.advance(31)
        with self.assertRaises(BackendUnavailable):
            self.client.get("a")

    def test_expired_failure_retains_entry(self):
        self.seed()
        before = self.cache.lookup("a")
        self.clock.advance(31)
        try:
            self.client.get("a")
        except BackendUnavailable:
            pass
        self.assertEqual(self.cache.lookup("a"), before)

    def test_expired_success(self):
        self.seed()
        self.clock.advance(31)
        self.backend.enqueue("a", Value(b"new"))
        self.assertEqual(self.client.get("a"), b"new")
        self.assertEqual(self.cache.lookup("a").fetched_at, 31)
        self.assertEqual(self.backend.calls[-1], ("a", "v1"))

    def test_expired_conditional_success(self):
        self.seed()
        self.clock.advance(31)
        self.backend.enqueue("a", NotModified())
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 31))

    def test_stale_boundary_equality(self):
        self.seed()
        self.clock.advance(30)
        self.assertEqual(self.client.get("a"), b"old")
        self.assertEqual(self.backend.calls[-1], ("a", "v1"))

    def test_fallback_does_not_extend_window(self):
        self.seed()
        self.clock.advance(30)
        self.client.get("a")
        self.clock.advance(1)
        with self.assertRaises(BackendUnavailable):
            self.client.get("a")

    def test_different_keys_isolated(self):
        self.seed()
        self.backend.enqueue("b", Value(b"bee", "vb"))
        self.client.get("b")
        self.clock.advance(11)
        self.backend.enqueue("a", Value(b"new"))
        self.client.get("a")
        self.assertEqual(self.cache.lookup("b"), Entry(b"bee", "vb", 0))
        self.assertEqual(self.backend.calls, [("a", None), ("b", None), ("a", "v1")])

    def test_miss_304_protocol_error(self):
        self.backend.enqueue("a", NotModified())
        with self.assertRaises(ProtocolError):
            self.client.get("a")
        self.assertIsNone(self.cache.lookup("a"))

    def test_validatorless_304_preserves_entry(self):
        self.seed(None)
        self.clock.advance(11)
        self.backend.enqueue("a", NotModified())
        with self.assertRaises(ProtocolError):
            self.client.get("a")
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", None, 0))

    def test_unexpected_response_preserves_entry(self):
        self.seed()
        self.clock.advance(11)
        self.backend.enqueue("a", "invalid")
        with self.assertRaises(ProtocolError):
            self.client.get("a")
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 0))

    def test_other_exception_propagates_without_mutation(self):
        self.seed()
        self.clock.advance(11)
        error = RuntimeError("backend defect")
        self.backend.enqueue("a", error)
        with self.assertRaises(RuntimeError) as caught:
            self.client.get("a")
        self.assertIs(caught.exception, error)
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 0))

    def test_invalid_key(self):
        for key in ("", " ", None, 3):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.client.get(key)
        self.assertEqual(self.backend.calls, [])

    def test_invalid_configuration(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Cache(fresh_ttl=value)

    def test_zero_ttls(self):
        cache = Cache(0, 0)
        self.assertEqual(cache.state(Entry(b"x", None, 0), 0), "fresh")
        self.assertEqual(cache.state(Entry(b"x", None, 0), 1), "expired")

    def test_standalone_policy_boundaries(self):
        entry = Entry(b"x", None, 0)
        self.assertEqual([self.cache.state(entry, age) for age in (9, 10, 11, 30, 31)],
                         ["fresh", "fresh", "stale", "stale", "expired"])

    def test_standalone_refresh_preserves_representation(self):
        self.cache.replace("a", Value(b"x", "vx"), 0)
        self.assertEqual(self.cache.refresh("a", 5), Entry(b"x", "vx", 5))

    def test_standalone_replace_updates_validator(self):
        self.cache.replace("a", Value(b"x", "v1"), 0)
        self.assertEqual(self.cache.replace("a", Value(b"y", "v2"), 5), Entry(b"y", "v2", 5))

    def test_clock_advance(self):
        clock = ManualClock(100)
        clock.advance(3)
        self.assertEqual(clock(), 103)
        with self.assertRaises(ValidationError):
            clock.advance(-1)
        self.assertEqual(clock(), 103)

    def test_exact_body_bytes(self):
        self.backend.enqueue("a", Value(b"\x00\xff"))
        self.assertEqual(self.client.get("a"), b"\x00\xff")

    def test_miss_retry_after_error(self):
        with self.assertRaises(BackendUnavailable):
            self.client.get("a")
        self.backend.enqueue("a", Value(b"ok"))
        self.assertEqual(self.client.get("a"), b"ok")

    def test_completion_time_on_success(self):
        clock = self.clock
        class AdvancingBackend:
            def fetch(self, key, *, if_none_match=None):
                clock.advance(4)
                return Value(b"done", "v")
        client = Client(AdvancingBackend(), clock, self.cache)
        self.assertEqual(client.get("a"), b"done")
        self.assertEqual(self.cache.lookup("a").fetched_at, 4)

    def test_error_completion_crosses_stale_boundary(self):
        self.seed()
        self.clock.advance(30)
        clock = self.clock
        class AdvancingBackend:
            def fetch(self, key, *, if_none_match=None):
                clock.advance(1)
                raise BackendUnavailable("offline")
        client = Client(AdvancingBackend(), clock, self.cache)
        with self.assertRaises(BackendUnavailable):
            client.get("a")
        self.assertEqual(self.cache.lookup("a"), Entry(b"old", "v1", 0))

    def test_cache_instances_are_isolated(self):
        self.seed()
        self.assertIsNone(Cache().lookup("a"))
