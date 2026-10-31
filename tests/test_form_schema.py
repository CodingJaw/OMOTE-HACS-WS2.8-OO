"""Regression tests for Home Assistant Core 2024.9.1 config-flow schema.

Can run without importing the Home Assistant runtime. CI installs the same
voluptuous and voluptuous_serialize versions that ship with HA 2024.9.1.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import voluptuous as vol
import voluptuous_serialize

FORM_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "omote_manager" / "form.py"
)
spec = importlib.util.spec_from_file_location("omote_manager_form", FORM_PATH)
assert spec and spec.loader
form = importlib.util.module_from_spec(spec)
spec.loader.exec_module(form)


class TestUserForm(unittest.TestCase):
    def test_ha_2024_9_schema_serialization(self):
        # This operation raised TypeError in the user's setup form.
        converted = voluptuous_serialize.convert(form.user_form_schema())
        self.assertIsInstance(converted, list)
        self.assertTrue(any(field.get("name") == "host" for field in converted))
        self.assertTrue(any(field.get("name") == "port" for field in converted))

    def test_normalize_hostname_and_ip(self):
        self.assertEqual(form.normalize_host(" OMOTE.local "), "omote.local")
        self.assertEqual(form.normalize_host("192.168.1.20"), "192.168.1.20")

    def test_reject_url(self):
        for candidate in (
            "http://omote.local", "omote.local:80", "a/b", "", "bad host",
        ):
            with self.subTest(host=candidate), self.assertRaises(vol.Invalid):
                form.normalize_host(candidate)

    def test_field_validation(self):
        schema = form.user_form_schema()
        self.assertEqual(schema({"host": "omote.local"})["port"], 80)
        self.assertEqual(
            schema({"host": "omote.local", "port": "8080"})["port"], 8080
        )
        with self.assertRaises(vol.Invalid):
            schema({"host": "omote.local", "port": 65536})


if __name__ == "__main__":
    unittest.main()
