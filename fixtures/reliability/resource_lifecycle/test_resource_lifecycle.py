import unittest

from reslife import Lease, LifecycleError, open_lease


class FakeResource:
    def __init__(self, events, failure=None):
        self.events = events
        self.failure = failure

    def use(self, value):
        self.events.append(f"use:{value}")
        if self.failure:
            raise self.failure
        return ("result", value)

    def release(self):
        self.events.append("release")


class Provider:
    def __init__(self, events, failure=None, acquire_failure=None):
        self.events = events
        self.failure = failure
        self.acquire_failure = acquire_failure

    def acquire(self):
        self.events.append("acquire")
        if self.acquire_failure:
            raise self.acquire_failure
        return FakeResource(self.events, self.failure)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.provider = Provider(self.events)

    def test_simple_use(self):
        lease = open_lease(self.provider)
        self.assertEqual(lease.use("a"), ("result", "a"))

    def test_acquire_once(self):
        lease = open_lease(self.provider)
        lease.use("a")
        lease.use("b")
        self.assertEqual(self.events.count("acquire"), 1)

    def test_result_unchanged(self):
        self.assertEqual(open_lease(self.provider).use(0), ("result", 0))

    def test_close_releases(self):
        lease = open_lease(self.provider)
        lease.close()
        self.assertEqual(self.events, ["acquire", "release"])

    def test_context_normal_exit(self):
        with open_lease(self.provider) as lease:
            self.assertEqual(lease.use("x"), ("result", "x"))
        self.assertEqual(self.events, ["acquire", "use:x", "release"])

    def test_context_body_exception(self):
        error = LookupError("body")
        with self.assertRaises(LookupError) as caught:
            with open_lease(self.provider):
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ["acquire", "release"])

    def test_acquire_failure_propagates(self):
        error = LookupError("acquire")
        with self.assertRaises(LookupError) as caught:
            open_lease(Provider(self.events, acquire_failure=error))
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ["acquire"])

    def test_independent_leases(self):
        a = open_lease(self.provider)
        b = open_lease(self.provider)
        a.close()
        b.close()
        self.assertEqual(self.events.count("release"), 2)

    def test_use_multiple_values(self):
        lease = open_lease(self.provider)
        self.assertEqual([lease.use(x) for x in (1, 2, 3)], [("result", x) for x in (1, 2, 3)])

    def test_direct_lease(self):
        lease = Lease(FakeResource(self.events))
        self.assertEqual(lease.use("direct"), ("result", "direct"))

    def test_close_twice_releases_once(self):
        lease = open_lease(self.provider)
        lease.close()
        lease.close()
        self.assertEqual(self.events, ["acquire", "release"])

    def test_use_after_close_rejected(self):
        lease = open_lease(self.provider)
        lease.close()
        with self.assertRaises(LifecycleError):
            lease.use("late")
        self.assertEqual(self.events, ["acquire", "release"])

    def test_operation_failure_cleans_up(self):
        error = ValueError("use")
        lease = open_lease(Provider(self.events, failure=error))
        with self.assertRaises(ValueError) as caught:
            lease.use("x")
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ["acquire", "use:x", "release"])

    def test_operation_failure_then_close_no_double_release(self):
        lease = open_lease(Provider(self.events, failure=ValueError("use")))
        with self.assertRaises(ValueError):
            lease.use("x")
        lease.close()
        self.assertEqual(self.events.count("release"), 1)

    def test_operation_failure_closes_lease(self):
        lease = open_lease(Provider(self.events, failure=ValueError("use")))
        with self.assertRaises(ValueError):
            lease.use("x")
        with self.assertRaises(LifecycleError):
            lease.use("again")


if __name__ == "__main__":
    unittest.main()
