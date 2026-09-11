import unittest

from batchstore import (BatchService, Event, IdempotencyConflict, Journal,
                        Operation, PreconditionError, Store, ValidationError)


def op(kind, key="a", value=None):
    return Operation(kind, key, value)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.store = Store({"a": 10, "b": 3})
        self.journal = Journal()
        self.service = BatchService(self.store, self.journal)

    def apply(self, operations, key="request"):
        return self.service.apply_batch(key, operations)

    def failing_batch(self):
        return [op("increment", value=2), op("increment", "missing", 1)]

    def test_single_commit(self):
        result = self.apply([op("increment", value=2)])
        self.assertEqual(self.store.snapshot(), {"a": 12, "b": 3})
        self.assertEqual(result.events, (Event("increment", "a", 10, 12),))
        self.assertEqual(self.journal.snapshot(), result.events)

    def test_create_balance(self):
        self.apply([op("set", "c", 8)])
        self.assertEqual(self.store.snapshot()["c"], 8)

    def test_replace_balance(self):
        self.apply([op("set", value=4)])
        self.assertEqual(self.store.snapshot()["a"], 4)

    def test_delete_balance(self):
        result = self.apply([op("delete")])
        self.assertNotIn("a", self.store.snapshot())
        self.assertEqual(result.events, (Event("delete", "a", 10, None),))

    def test_multi_operation_order(self):
        result = self.apply([op("set", "c", 5), op("increment", "c", -2), op("delete", "c")])
        self.assertEqual(result.events, (Event("set", "c", None, 5),
                         Event("increment", "c", 5, 3), Event("delete", "c", 3, None)))
        self.assertEqual(self.journal.snapshot(), result.events)
        self.assertNotIn("c", self.store.snapshot())

    def test_zero_increment_emits_event(self):
        self.assertEqual(self.apply([op("increment", value=0)]).events, (Event("increment", "a", 10, 10),))

    def test_set_same_value_emits_event(self):
        self.assertEqual(len(self.apply([op("set", value=10)]).events), 1)

    def test_missing_target(self):
        with self.assertRaises(PreconditionError):
            self.apply([op("delete", "missing")])
        self.assertEqual(self.store.snapshot(), {"a": 10, "b": 3})

    def test_negative_result(self):
        with self.assertRaises(PreconditionError):
            self.apply([op("increment", value=-11)])
        self.assertEqual(self.store.snapshot()["a"], 10)

    def test_invalid_idempotency_key(self):
        for key in ("", " ", None, 2):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.apply([op("set", value=1)], key)
        self.assertEqual(self.journal.snapshot(), ())

    def test_invalid_collections(self):
        for operations in ([], (), None, "set", {"kind": "set"}):
            with self.subTest(operations=operations), self.assertRaises(ValidationError):
                self.apply(operations)

    def test_invalid_operation_shape(self):
        for value in ({"kind": "set"}, {"kind": "set", "key": "a", "value": 1, "extra": 2}, 5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.apply([value])

    def test_invalid_operation_fields(self):
        for kind, key, value in (("unknown", "a", 1), ("set", "", 1), ("set", "a", True),
                                 ("set", "a", -1), ("increment", "a", 1.5), ("delete", "a", 3)):
            with self.subTest(kind=kind, key=key, value=value), self.assertRaises(ValidationError):
                self.apply([{"kind": kind, "key": key, "value": value}])

    def test_complete_validation_before_effects(self):
        with self.assertRaises(ValidationError):
            self.apply([op("set", value=1), {"kind": "increment", "key": "a", "value": "2"}])
        self.assertEqual(self.store.snapshot(), {"a": 10, "b": 3})
        self.assertEqual(self.journal.snapshot(), ())

    def test_mid_batch_store_rollback(self):
        with self.assertRaises(PreconditionError):
            self.apply(self.failing_batch())
        self.assertEqual(self.store.snapshot(), {"a": 10, "b": 3})

    def test_mid_batch_journal_rollback(self):
        prior = self.apply([op("set", "c", 1)], "prior")
        with self.assertRaises(PreconditionError):
            self.apply(self.failing_batch())
        self.assertEqual(self.journal.snapshot(), prior.events)

    def test_delete_is_rolled_back(self):
        with self.assertRaises(PreconditionError):
            self.apply([op("delete"), op("increment", value=1)])
        self.assertEqual(self.store.snapshot(), {"a": 10, "b": 3})

    def test_new_target_is_rolled_back(self):
        with self.assertRaises(PreconditionError):
            self.apply([op("set", "c", 4), op("increment", "b", -4)])
        self.assertNotIn("c", self.store.snapshot())

    def test_idempotent_replay(self):
        operations = [op("increment", value=2)]
        first = self.apply(operations)
        self.assertEqual(self.apply(operations), first)
        self.assertEqual(self.store.snapshot()["a"], 12)
        self.assertEqual(self.journal.snapshot(), first.events)

    def test_equivalent_representation_replay(self):
        first = self.apply([op("delete")])
        self.assertEqual(self.apply(({"key": "a", "kind": "delete"},)), first)
        self.assertEqual(self.apply([{"key": "a", "kind": "delete", "value": None}]), first)

    def test_changed_payload_conflict(self):
        first = self.apply([op("set", value=1)])
        with self.assertRaises(IdempotencyConflict):
            self.apply([op("set", value=2)])
        self.assertEqual(self.store.snapshot()["a"], 1)
        self.assertEqual(self.journal.snapshot(), first.events)

    def test_changed_order_conflict(self):
        operations = [op("set", value=1), op("set", "b", 2)]
        self.apply(operations)
        with self.assertRaises(IdempotencyConflict):
            self.apply(list(reversed(operations)))

    def test_failed_key_corrected_retry(self):
        with self.assertRaises(PreconditionError):
            self.apply([op("increment", "missing", 1)])
        result = self.apply([op("set", "missing", 3)])
        self.assertEqual(result.events, (Event("set", "missing", None, 3),))
        self.assertEqual(self.store.snapshot()["missing"], 3)

    def test_same_request_retry_after_precondition_fixed(self):
        operations = [op("increment", "missing", 1)]
        with self.assertRaises(PreconditionError):
            self.apply(operations)
        self.apply([op("set", "missing", 5)], "setup")
        result = self.apply(operations)
        self.assertEqual(result.events, (Event("increment", "missing", 5, 6),))

    def test_invalid_request_does_not_consume_key(self):
        with self.assertRaises(ValidationError):
            self.apply([])
        self.assertEqual(len(self.apply([op("set", value=1)]).events), 1)

    def test_replay_result_after_unrelated_commit(self):
        operations = [op("increment", value=1)]
        first = self.apply(operations)
        self.apply([op("set", value=100)], "other")
        self.assertEqual(self.apply(operations), first)
        self.assertEqual(self.store.snapshot()["a"], 100)

    def test_unrelated_keys_execute_independently(self):
        self.apply([op("increment", value=1)], "one")
        self.apply([op("increment", value=1)], "two")
        self.assertEqual(self.store.snapshot()["a"], 12)
        self.assertEqual(len(self.journal.snapshot()), 2)

    def test_invalid_payload_on_replay(self):
        self.apply([op("set", value=1)])
        with self.assertRaises(ValidationError):
            self.apply([None])

    def test_request_input_is_not_retained(self):
        request = [{"kind": "set", "key": "a", "value": 1}]
        first = self.apply(request)
        request[0]["value"] = 99
        self.assertEqual(self.apply([op("set", value=1)]), first)

    def test_snapshot_is_detached(self):
        snapshot = self.store.snapshot()
        snapshot["a"] = 0
        self.assertEqual(self.store.snapshot()["a"], 10)

    def test_standalone_store_commit(self):
        events = self.store.apply_batch([op("increment", value=1), op("increment", value=2)])
        self.assertEqual(self.store.snapshot()["a"], 13)
        self.assertEqual(events[-1], Event("increment", "a", 11, 13))
        self.assertEqual(self.journal.snapshot(), ())

    def test_standalone_store_atomicity(self):
        with self.assertRaises(PreconditionError):
            self.store.apply_batch(self.failing_batch())
        self.assertEqual(self.store.snapshot(), {"a": 10, "b": 3})

    def test_journal_append_order(self):
        events = (Event("set", "x", None, 1), Event("delete", "x", 1, None))
        self.journal.append_batch(events)
        self.assertEqual(self.journal.snapshot(), events)

    def test_journal_validates_whole_batch(self):
        existing = Event("set", "a", None, 1)
        self.journal.append_batch([existing])
        with self.assertRaises(ValidationError):
            self.journal.append_batch([Event("set", "b", None, 2), "invalid"])
        self.assertEqual(self.journal.snapshot(), (existing,))

    def test_journal_empty_append(self):
        self.journal.append_batch([])
        self.assertEqual(self.journal.snapshot(), ())

    def test_instances_are_isolated(self):
        self.apply([op("set", value=1)])
        other = BatchService()
        result = other.apply_batch("request", [op("set", "a", 7)])
        self.assertEqual(result.events, (Event("set", "a", None, 7),))
