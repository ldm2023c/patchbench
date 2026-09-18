import unittest

from envcfg import ConfigError, RuntimeConfig, load_env


class EnvironmentConfigTests(unittest.TestCase):
    def test_missing_defaults(self):
        self.assertEqual(load_env({}), RuntimeConfig(False, 4, "development", None))

    def test_basic_values(self):
        self.assertEqual(load_env({"APP_DEBUG": "true", "APP_WORKERS": "8",
            "APP_MODE": "production", "APP_LABEL": "api"}),
            RuntimeConfig(True, 8, "production", "api"))

    def test_false_spelling(self):
        self.assertFalse(load_env({"APP_DEBUG": "false"}).debug)

    def test_one_spelling(self):
        self.assertTrue(load_env({"APP_DEBUG": "1"}).debug)

    def test_case_insensitive_yes(self):
        self.assertTrue(load_env({"APP_DEBUG": "YeS"}).debug)

    def test_zero_spelling(self):
        self.assertFalse(load_env({"APP_DEBUG": "0"}).debug)

    def test_no_spelling(self):
        self.assertFalse(load_env({"APP_DEBUG": "NO"}).debug)

    def test_workers_lower_bound(self):
        self.assertEqual(load_env({"APP_WORKERS": "0"}).workers, 0)

    def test_workers_upper_bound(self):
        self.assertEqual(load_env({"APP_WORKERS": "64"}).workers, 64)

    def test_workers_leading_zeroes(self):
        self.assertEqual(load_env({"APP_WORKERS": "004"}).workers, 4)

    def test_test_mode(self):
        self.assertEqual(load_env({"APP_MODE": "test"}).mode, "test")

    def test_unrelated_variables_ignored(self):
        self.assertEqual(load_env({"PATH": "/bin", "APP_OTHER": "bad"}), load_env({}))

    def test_label_whitespace_preserved(self):
        self.assertEqual(load_env({"APP_LABEL": " a b "}).label, " a b ")

    def test_present_empty_label(self):
        self.assertEqual(load_env({"APP_LABEL": ""}).label, "")

    def test_present_empty_debug_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_DEBUG"):
            load_env({"APP_DEBUG": ""})

    def test_unknown_boolean_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_DEBUG"):
            load_env({"APP_DEBUG": "enabled"})

    def test_boolean_whitespace_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_DEBUG"):
            load_env({"APP_DEBUG": " true"})

    def test_empty_workers_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_WORKERS"):
            load_env({"APP_WORKERS": ""})

    def test_workers_out_of_range_rejected(self):
        for text in ("65", "999", "-1"):
            with self.subTest(text=text), self.assertRaisesRegex(ConfigError, "APP_WORKERS"):
                load_env({"APP_WORKERS": text})

    def test_workers_noncanonical_rejected(self):
        for text in ("+2", " 2", "2 ", "²", "٢"):
            with self.subTest(text=text), self.assertRaisesRegex(ConfigError, "APP_WORKERS"):
                load_env({"APP_WORKERS": text})

    def test_empty_mode_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_MODE"):
            load_env({"APP_MODE": ""})

    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(ConfigError, "APP_MODE"):
            load_env({"APP_MODE": "staging"})

    def test_mode_case_is_exact(self):
        with self.assertRaisesRegex(ConfigError, "APP_MODE"):
            load_env({"APP_MODE": "Production"})

    def test_owned_value_must_be_text(self):
        for name in ("APP_DEBUG", "APP_WORKERS", "APP_MODE", "APP_LABEL"):
            with self.subTest(name=name), self.assertRaisesRegex(ConfigError, name):
                load_env({name: 7})


if __name__ == "__main__":
    unittest.main()
