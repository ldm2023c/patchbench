import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from profilestore import Profile, SchemaError, load, save, upgrade


class SchemaUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = Profile("u1", "Ada", ("admin", "ops"))

    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")

    def v1(self, tags=None):
        self.write("profile.json", {"version": 1, "id": "u1", "name": "Ada",
                                    "tags": ["admin", "ops"] if tags is None else tags})

    def v2(self, tags=None):
        self.write("profile.json", {"version": 2, "id": "u1", "display_name": "Ada"})
        self.write("tags.json", {"profile_id": "u1", "tags": ["admin", "ops"] if tags is None else tags})

    def read_json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def assert_save_rejects_without_mutation(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with self.assertRaises(SchemaError):
            save(self.root, self.profile)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.root.iterdir()}, before
        )

    def test_model_normalizes_list_tags(self):
        self.assertEqual(Profile("u1", "Ada", ["x"]).tags, ("x",))

    def test_model_rejects_empty_id(self):
        with self.assertRaises(SchemaError):
            Profile("", "Ada", ())

    def test_model_rejects_empty_name(self):
        with self.assertRaises(SchemaError):
            Profile("u1", "", ())

    def test_model_rejects_invalid_tag(self):
        with self.assertRaises(SchemaError):
            Profile("u1", "Ada", [""])

    def test_simple_v2_read(self):
        self.v2()
        self.assertEqual(load(self.root), self.profile)

    def test_v2_empty_tags(self):
        self.v2([])
        self.assertEqual(load(self.root).tags, ())

    def test_v2_read_preserves_bytes(self):
        self.v2()
        before = [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")]
        load(self.root)
        self.assertEqual(before, [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")])

    def test_v2_missing_companion_rejected(self):
        self.v2()
        (self.root / "tags.json").unlink()
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_v2_mismatched_companion_rejected(self):
        self.v2()
        self.write("tags.json", {"profile_id": "other", "tags": []})
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_missing_primary_rejected(self):
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_malformed_primary_rejected(self):
        (self.root / "profile.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_malformed_companion_rejected(self):
        self.v2()
        (self.root / "tags.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_save_rejects_non_profile(self):
        with self.assertRaises(TypeError):
            save(self.root, object())

    def test_v1_backward_read_preserves_tags(self):
        self.v1()
        self.assertEqual(load(self.root), self.profile)

    def test_v1_read_does_not_migrate(self):
        self.v1()
        before = (self.root / "profile.json").read_bytes()
        load(self.root)
        self.assertEqual((self.root / "profile.json").read_bytes(), before)
        self.assertFalse((self.root / "tags.json").exists())

    def test_save_new_emits_v2(self):
        save(self.root, self.profile)
        self.assertEqual(self.read_json("profile.json"), {"version": 2, "id": "u1", "display_name": "Ada"})
        self.assertEqual(self.read_json("tags.json"), {"profile_id": "u1", "tags": ["admin", "ops"]})

    def test_save_over_v1_emits_v2(self):
        self.v1([])
        save(self.root, self.profile)
        self.assertEqual(load(self.root), self.profile)
        self.assertEqual(self.read_json("profile.json")["version"], 2)

    def test_save_over_v2_updates_both_files(self):
        self.v2([])
        save(self.root, self.profile)
        self.assertEqual(load(self.root), self.profile)

    def test_migrate_v1_preserves_data(self):
        self.v1()
        self.assertTrue(upgrade(self.root))
        self.assertEqual(load(self.root), self.profile)
        self.assertEqual(self.read_json("profile.json")["version"], 2)

    def test_migrate_v1_empty_tags(self):
        self.v1([])
        self.assertTrue(upgrade(self.root))
        self.assertEqual(load(self.root).tags, ())

    def test_migrate_v2_noop_bytes(self):
        self.v2()
        before = [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")]
        self.assertFalse(upgrade(self.root))
        self.assertEqual(before, [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")])

    def test_second_migration_noop(self):
        self.v1()
        self.assertTrue(upgrade(self.root))
        before = [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")]
        self.assertFalse(upgrade(self.root))
        self.assertEqual(before, [(self.root / name).read_bytes() for name in ("profile.json", "tags.json")])

    def test_future_version_read_rejected(self):
        self.v2()
        self.write("profile.json", {"version": 3, "id": "u1", "display_name": "Ada"})
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_future_version_upgrade_rejected_unchanged(self):
        self.v2()
        self.write("profile.json", {"version": 3, "id": "u1", "display_name": "Ada"})
        before = (self.root / "profile.json").read_bytes()
        with self.assertRaises(SchemaError):
            upgrade(self.root)
        self.assertEqual((self.root / "profile.json").read_bytes(), before)

    def test_future_version_save_rejected_unchanged(self):
        self.v2()
        self.write("profile.json", {"version": 3, "id": "u1", "display_name": "Ada"})
        before = (self.root / "profile.json").read_bytes()
        with self.assertRaises(SchemaError):
            save(self.root, self.profile)
        self.assertEqual((self.root / "profile.json").read_bytes(), before)

    def test_v1_mixed_companion_rejected(self):
        self.v1()
        self.write("tags.json", {"profile_id": "u1", "tags": []})
        with self.assertRaises(SchemaError):
            load(self.root)

    def test_mixed_migration_does_not_overwrite(self):
        self.v1()
        self.write("tags.json", {"profile_id": "u1", "tags": []})
        before = (self.root / "tags.json").read_bytes()
        with self.assertRaises(SchemaError):
            upgrade(self.root)
        self.assertEqual((self.root / "tags.json").read_bytes(), before)

    def test_invalid_existing_save_rejected(self):
        (self.root / "profile.json").write_text("{bad", encoding="utf-8")
        with self.assertRaises(SchemaError):
            save(self.root, self.profile)

    def test_save_rejects_v1_companion_conflict_unchanged(self):
        self.v1()
        self.write("tags.json", {"profile_id": "u1", "tags": ["other"]})
        self.assert_save_rejects_without_mutation()

    def test_save_rejects_v2_missing_companion_unchanged(self):
        self.v2()
        (self.root / "tags.json").unlink()
        self.assert_save_rejects_without_mutation()

    def test_save_rejects_v2_mismatched_companion_unchanged(self):
        self.v2()
        self.write("tags.json", {"profile_id": "other", "tags": ["other"]})
        self.assert_save_rejects_without_mutation()

    def test_save_rejects_v2_malformed_companion_unchanged(self):
        self.v2()
        (self.root / "tags.json").write_text("{bad", encoding="utf-8")
        self.assert_save_rejects_without_mutation()

    def test_save_rejects_orphan_companion_unchanged(self):
        self.write("tags.json", {"profile_id": "u1", "tags": ["orphan"]})
        self.assert_save_rejects_without_mutation()


if __name__ == "__main__":
    unittest.main()
