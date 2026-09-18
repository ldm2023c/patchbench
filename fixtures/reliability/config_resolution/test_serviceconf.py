import unittest

from serviceconf import ConfigError, EffectiveConfig, load_mapping, resolve_config


def resolve(overrides=None, environment=None, file=None):
    return resolve_config(load_mapping(overrides or {}), load_mapping(environment or {}),
                          load_mapping(file or {}))


class ServiceConfigTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(resolve(), EffectiveConfig(True, 3, "service"))

    def test_file_layer(self):
        self.assertEqual(resolve(file={"enabled": False, "retries": 4, "label": "file"}),
                         EffectiveConfig(False, 4, "file"))

    def test_environment_over_file(self):
        self.assertEqual(resolve(environment={"enabled": True, "retries": 5, "label": "env"},
                                 file={"enabled": False, "retries": 4, "label": "file"}),
                         EffectiveConfig(True, 5, "env"))

    def test_override_over_environment(self):
        self.assertEqual(resolve(overrides={"enabled": True, "retries": 7, "label": "override"},
                                 environment={"enabled": False, "retries": 5, "label": "env"}),
                         EffectiveConfig(True, 7, "override"))

    def test_positive_override_without_lower_layers(self):
        self.assertEqual(resolve(overrides={"retries": 6}), EffectiveConfig(True, 6, "service"))

    def test_loaded_nonempty_layer_values(self):
        layer = load_mapping({"enabled": True, "retries": 2, "label": "worker"})
        self.assertEqual(layer.present, {"enabled", "retries", "label"})
        self.assertEqual(dict(layer.values), {"enabled": True, "retries": 2, "label": "worker"})

    def test_independent_field_resolution(self):
        self.assertEqual(resolve(overrides={"label": "top"}, environment={"retries": 2},
                                 file={"enabled": False}), EffectiveConfig(False, 2, "top"))

    def test_layer_records_presence_separately(self):
        layer = load_mapping({"enabled": False, "retries": 0, "label": ""})
        self.assertEqual(layer.present, {"enabled", "retries", "label"})
        self.assertEqual(dict(layer.values), {"enabled": False, "retries": 0, "label": ""})

    def test_override_false_wins(self):
        self.assertFalse(resolve(overrides={"enabled": False}, environment={"enabled": True}).enabled)

    def test_override_zero_wins(self):
        self.assertEqual(resolve(overrides={"retries": 0}, environment={"retries": 5}).retries, 0)

    def test_override_empty_label_wins(self):
        self.assertEqual(resolve(overrides={"label": ""}, environment={"label": "env"}).label, "")

    def test_environment_false_wins(self):
        self.assertFalse(resolve(environment={"enabled": False}).enabled)

    def test_environment_zero_wins(self):
        self.assertEqual(resolve(environment={"retries": 0}, file={"retries": 6}).retries, 0)

    def test_file_empty_label_wins(self):
        self.assertEqual(resolve(file={"label": ""}).label, "")

    def test_field_presence_is_independent(self):
        self.assertEqual(resolve(overrides={"enabled": False}, environment={"label": "env"},
                                 file={"retries": 8}), EffectiveConfig(False, 8, "env"))

    def test_whitespace_label_is_value(self):
        self.assertEqual(resolve(overrides={"label": "  "}).label, "  ")

    def test_loader_rejects_unknown_key(self):
        with self.assertRaisesRegex(ConfigError, "mystery"):
            load_mapping({"mystery": 1})

    def test_loader_rejects_none_for_each_field(self):
        for key in ("enabled", "retries", "label"):
            with self.subTest(key=key), self.assertRaisesRegex(ConfigError, key):
                load_mapping({key: None})

    def test_loader_rejects_bad_types(self):
        for key, value in (("enabled", 1), ("enabled", "false"), ("retries", True),
                           ("retries", "2"), ("label", 5)):
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ConfigError, key):
                load_mapping({key: value})

    def test_loader_rejects_negative_retries(self):
        with self.assertRaisesRegex(ConfigError, "retries"):
            load_mapping({"retries": -1})

    def test_bad_shadowed_field_is_still_rejected(self):
        with self.assertRaisesRegex(ConfigError, "retries"):
            resolve_config(load_mapping({"retries": 1}), load_mapping({"retries": 2}),
                           load_mapping({"retries": None}))

    def test_loading_copies_caller_mapping(self):
        raw = {"label": "first"}
        layer = load_mapping(raw)
        raw["label"] = "later"
        self.assertEqual(dict(layer.values), {"label": "first"})


if __name__ == "__main__":
    unittest.main()
