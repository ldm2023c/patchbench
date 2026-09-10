import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployconf.cli import main, plan


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "deployment.toml"
        self.path.write_text('[deploy]\nendpoint="https://file.example"\nretries=7\nlabel="file"\n')

    def configured(self, *args, env=None):
        return plan(["--config", str(self.path), *args], env or {})

    def test_defaults(self):
        self.assertEqual(plan([], {}).as_dict(),
                         dict(endpoint="https://localhost", retries=3, label="default"))

    def test_file_used_when_cli_omitted(self):
        self.assertEqual(self.configured().as_dict(),
                         dict(endpoint="https://file.example", retries=7, label="file"))

    def test_environment_over_file(self):
        value = self.configured(env={"DEPLOY_ENDPOINT": "https://env.example"})
        self.assertEqual(value.endpoint, "https://env.example")

    def test_cli_over_all_sources(self):
        value = self.configured("--endpoint", "https://cli.example",
                                env={"DEPLOY_ENDPOINT": "https://env.example"})
        self.assertEqual(value.endpoint, "https://cli.example")

    def test_zero_cli_retries_is_explicit(self):
        self.assertEqual(self.configured("--retries", "0").retries, 0)

    def test_empty_cli_label_is_explicit(self):
        self.assertEqual(self.configured("--label", "").label, "")

    def test_empty_environment_label_is_explicit(self):
        self.assertEqual(self.configured(env={"DEPLOY_LABEL": ""}).label, "")

    def test_each_field_resolves_independently(self):
        value = self.configured("--label", "cli", env={"DEPLOY_RETRIES": "0"})
        self.assertEqual(value.as_dict(),
                         dict(endpoint="https://file.example", retries=0, label="cli"))

    def test_unknown_file_key_rejected(self):
        self.path.write_text('[deploy]\nretry=9\n')
        with self.assertRaisesRegex(ValueError, "unknown deployment settings"):
            self.configured()

    def test_invalid_winning_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            plan(["--endpoint", "ftp://invalid"], {})

    def test_negative_retries_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            plan(["--retries", "-1"], {})

    def test_main_outputs_json(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--label", "release"]), 0)
        self.assertEqual(json.loads(output.getvalue())["label"], "release")

    def test_missing_file_reports_error(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["--config", str(self.path) + ".missing"]), 2)
        self.assertIn("configuration error", error.getvalue())

    def test_explicit_builtin_defaults_override_file(self):
        self.assertEqual(self.configured("--endpoint", "https://localhost",
                                         "--retries", "3", "--label", "default").as_dict(),
                         dict(endpoint="https://localhost", retries=3, label="default"))
        self.assertEqual(self.configured().as_dict(),
                         dict(endpoint="https://file.example", retries=7, label="file"))

    def test_explicit_empty_cli_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            self.configured("--endpoint", "")

    def test_explicit_empty_environment_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            self.configured(env={"DEPLOY_ENDPOINT": ""})
