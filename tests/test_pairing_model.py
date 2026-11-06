"""Fail-closed Security2 preview wire contract from the firmware repository."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "custom_components/omote_manager"
FIXTURE = json.loads((ROOT / "tests/fixtures/pairing_v1_preview_contract.json").read_text())

PKG = "omote_pairing_model_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(MODULES)]
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".pairing_model", MODULES / "pairing_model.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


class PairingModelTests(unittest.TestCase):
    def test_firmware_owned_contract_is_identical(self):
        path = os.environ.get("OMOTE_FIRMWARE_PAIRING_CONTRACT")
        if path:
            self.assertEqual(FIXTURE, json.loads(Path(path).read_text()))

    def test_legacy_firmware_is_unsupported_not_unauthorized(self):
        result = model.summarize_pairing_status(None)
        self.assertFalse(result["available"])
        self.assertFalse(result["encrypted_session_ready"])
        self.assertFalse(result["pairing_enabled"])
        self.assertFalse(result["deployment_enabled"])

    def test_feature_firmware_status_is_informative_but_not_trusted(self):
        result = model.summarize_pairing_status(FIXTURE["response"])
        self.assertTrue(result["available"])
        self.assertIn("srp6a", result["scheme"])
        self.assertFalse(result["device_identity_verified"])
        self.assertFalse(result["encrypted_session_ready"])
        self.assertFalse(result["pairing_enabled"])
        self.assertFalse(result["deployment_enabled"])

    def test_disabled_production_pairing_is_distinct_from_optional_lab(self):
        result = model.summarize_pairing_status(FIXTURE["response"])
        self.assertIn("PRODUCTION pairing only", result["explanation"])
        self.assertIn("port 18082", result["explanation"])
        self.assertIn("not monitored by this status API", result["explanation"])
        self.assertFalse(result["encrypted_session_ready"])
        self.assertFalse(result["device_identity_verified"])
        self.assertFalse(result["pairing_enabled"])
        self.assertFalse(result["deployment_enabled"])

    def test_frontend_does_not_claim_lab_session_is_inactive(self):
        frontend = (MODULES / "frontend/omote-panel.js").read_text()
        self.assertIn("Production encrypted session: NOT AVAILABLE", frontend)
        self.assertNotIn("Encrypted session: NOT ACTIVE", frontend)
        self.assertIn("Pairing: DISABLED", frontend)
        self.assertIn("Deployment: DISABLED", frontend)

    def test_fake_pairing_security_advertisements_cannot_enable_pairing(self):
        original = FIXTURE["response"]
        for altered in (
            {"state": "paired"},
            {"pairing_window_open": True},
            {"paired": True},
            {"session_ready": True},
            {"device_identity_available": True},
            {"deployment_enabled": True},
            {"transport": "httpd"},
            {"transport_port": 81},
            {"security_scheme": "security0"},
            {"touch_approval_required": False},
            {"unknown": "field"},
            {"transport_port": False}, # bool is not an int
            {"paired": 0}, # int is not a bool
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(model.PairingStatusError):
                    model.summarize_pairing_status({**original, **altered})

    def test_no_crypto_or_peer_trust_is_claimed_by_preview(self):
        source = (MODULES / "pairing_model.py").read_text()
        ws = (MODULES / "panel.py").read_text()
        self.assertIn('"pairing_enabled": False', source)
        self.assertIn('"device_identity_verified": False', source)
        self.assertIn('info["pairing_enabled"] = False', ws)
        self.assertIn('info["deployment_enabled"] = False', ws)
        self.assertNotIn("._session.post(", source + ws)
        self.assertNotIn("._session.put(", source + ws)


if __name__ == "__main__":
    unittest.main()
