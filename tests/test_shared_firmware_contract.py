"""Contract parity against the firmware-owned, pinned preview fixture."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "tests/fixtures/config_v2_preview_contract.json").read_text())
PKG = "omote_contract_test"
MODULE_ROOT = ROOT / "custom_components/omote_manager"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(MODULE_ROOT)]
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".capability_model", MODULE_ROOT / "capability_model.py")
cap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cap
spec.loader.exec_module(cap)


class TestSharedContract(unittest.TestCase):
    def test_local_fixture_matches_firmware_when_supplied(self):
        path = os.environ.get("OMOTE_FIRMWARE_CONTRACT")
        if path:
            self.assertEqual(CONTRACT, json.loads(Path(path).read_text()))

    def test_preview_capabilities_are_fail_closed(self):
        self.assertFalse(CONTRACT["deployment_authorized"])
        info = cap.summarize_capabilities(CONTRACT["preview_capabilities"])
        self.assertEqual(info["generation"], "preview")
        self.assertFalse(info["deployment_enabled"])
        self.assertFalse(info["transaction_support"])
        self.assertFalse(info["rollback_support"])
        self.assertTrue(info["write_protection_enabled"])

    def test_single_active_states_are_read_only(self):
        for sample in CONTRACT["storage_samples"]:
            with self.subTest(mode=sample["config_mode"]):
                normalized = cap.summarize_storage_status(sample)
                self.assertEqual(normalized["config_mode"], sample["config_mode"])
                self.assertEqual(normalized["storage_model"], "single-active")
                self.assertFalse(normalized["deployment_enabled"])

    def test_dangerous_storage_metadata_is_rejected(self):
        sample = CONTRACT["storage_samples"][0]
        for patch in ({"config_mode": "active"},
                      {"recovery_required": True},
                      {"estimated_free_bytes": 7000000},
                      {"active_revision_sha256": "invalid"}):
            with self.subTest(patch=patch), self.assertRaises(cap.CapabilitiesError):
                cap.summarize_storage_status(dict(sample, **patch))

    def test_no_transaction_transport_before_security_approval(self):
        source = (MODULE_ROOT / "api.py").read_text()
        self.assertNotIn("/api/config/v2/transactions", source)
        self.assertNotIn("._session.post(", source)
        self.assertNotIn("._session.put(", source)
        self.assertNotIn("._session.delete(", source)


if __name__ == "__main__":
    unittest.main()
