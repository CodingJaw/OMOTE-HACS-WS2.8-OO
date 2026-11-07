"""Offline tests for Apache-2.0 bundled Espressif Security2 v5.4.2.

No IDF_PATH, installation of source checkouts, network access,
Home Assistant startup, firmware writes, or PIN attempt are required.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
NAME = "omote_bundled_sec2_test"
pkg = types.ModuleType(NAME)
pkg.__path__ = [str(ROOT)]
sys.modules[NAME] = pkg
spec = importlib.util.spec_from_file_location(
    NAME + ".sec2_lab_espidf", ROOT / "sec2_lab_espidf.py"
)
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)


class BundledSecurity2Tests(unittest.TestCase):
    def test_upstream_license_and_no_espidf_checkout_needed(self):
        vendor = ROOT / "sec2_vendor"
        self.assertTrue((vendor / "LICENSE").is_file())
        self.assertIn("Apache License", (vendor / "LICENSE").read_text())
        self.assertIn("ESP-IDF v5.4.2", (vendor / "NOTICE.md").read_text())
        src = (ROOT / "sec2_lab_espidf.py").read_text()
        self.assertNotIn("IDF_PATH", src)
        self.assertNotIn("sys.path.insert", src)
        self.assertNotIn("pip install", src)
        self.assertNotIn("security0", src)

    def test_loader_rejects_incompatible_protobuf_and_crypto_versions(self):
        with patch.object(loader.metadata, "version") as version:
            version.side_effect = lambda name: {
                "cryptography": "43.0.0", "protobuf": "3.20.3",
            }[name]
            with self.assertRaises(loader.LabPrerequisiteError) as failed:
                loader.load_official_security2()
            self.assertEqual(str(failed.exception),
                             "incompatible_crypto_or_protobuf_version")
            version.side_effect = lambda name: {
                "cryptography": "43.0.0", "protobuf": "4.25.4",
            }[name]
            self.assertTrue(loader._supported_dependencies())

    def test_bundled_security2_load_and_protobuf_session_frame(self):
        from google.protobuf.descriptor_pool import Default
        start = list(sys.path)
        with patch.dict(os.environ, {"IDF_PATH": "/does/not/exist"}):
            Security2 = loader.load_official_security2()
        self.assertEqual(sys.path, start)
        sec = Security2(
            sec_patch_ver=1, username="omote-ha",
            password="123456", verbose=False
        )
        frame = sec.security_session(None)
        self.assertIsInstance(frame, str)
        self.assertLess(len(frame), 4096)
        from omote_bundled_sec2_test.sec2_vendor import proto
        self.assertIs(proto.session_pb2.DESCRIPTOR.pool, proto.pool.POOL)
        packet = proto.session_pb2.SessionData()
        packet.ParseFromString(frame.encode("latin-1"))
        self.assertEqual(packet.sec_ver, proto.session_pb2.SecScheme2)
        self.assertEqual(packet.sec2.msg, proto.sec2_pb2.S2Session_Command0)
        self.assertEqual(packet.sec2.sc0.client_username, b"omote-ha")
        self.assertGreater(len(packet.sec2.sc0.client_pubkey), 128)
        # Generic protobuf names must not become globally registered.
        self.assertIsNot(proto.pool.POOL, Default())

    def test_no_runtime_module_namespace_hijack(self):
        from omote_bundled_sec2_test.sec2_vendor.security2 import Security2
        self.assertTrue(callable(Security2))
        source = (ROOT / "sec2_vendor/security2.py").read_text()
        self.assertIn("from . import proto", source)
        self.assertIn("from .convenience import", source)
        self.assertNotIn("\nimport proto\n", source)


if __name__ == "__main__":
    unittest.main()
