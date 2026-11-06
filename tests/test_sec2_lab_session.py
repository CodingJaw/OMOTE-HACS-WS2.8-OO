"""Offline negative tests for the unregistered Security2 laboratory adapter.

No network access, PIN logging, trust enrollment or firmware writes.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import types
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BASE = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
pkg = types.ModuleType("sec2_adapter_tests")
pkg.__path__ = [str(BASE)]
sys.modules[pkg.__name__] = pkg
for module_name in ("candidate_identity", "sec2_lab_session"):
    spec = importlib.util.spec_from_file_location(
        pkg.__name__ + "." + module_name, BASE / (module_name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
lab = sys.modules[pkg.__name__ + ".sec2_lab_session"]


class FakeIdentity:
    fingerprint = "a" * 64
    def status(self, entry_id):
        if entry_id != "remote-1":
            raise ValueError("unknown remote")
        return {"prepared": True, "trusted": False, "fingerprint": self.fingerprint}

    def make_lab_ha_proof(self, entry_id, session_id):
        assert entry_id == "remote-1" and session_id == 17
        public = b"\x04" + b"\x00" * 64
        self.fingerprint = sha256(public).hexdigest()
        return b"\x01" + public + b"\x02" * 32 + b"\x00\x08" + b"x" * 8


class LabAdapterTests(unittest.TestCase):
    def test_cookie_strict(self):
        self.assertEqual(lab._session_id("session=17"), 17)
        for cookie in ("", "session=-1", "session=01", "session=4294967296",
                       "session=17; token=abc", "Session=17", "session=17\n"):
            with self.subTest(cookie=repr(cookie)), self.assertRaises(ValueError):
                lab._session_id(cookie)

    def test_device_proof_authentic_and_replay_rejected(self):
        private = ec.generate_private_key(ec.SECP256R1())
        public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        challenge = b"\x01" + b"\x4d" * 32
        sid = 17
        signed = lab._DEVICE_DOMAIN + sid.to_bytes(4, "big") + challenge[1:] + public
        signature = private.sign(signed, ec.ECDSA(hashes.SHA256()))
        frame = b"\x01" + public + len(signature).to_bytes(2, "big") + signature
        self.assertEqual(lab._device_proof(sid, challenge, frame), sha256(public).hexdigest())
        for altered_sid, altered_challenge, altered_frame in (
            (18, challenge, frame),
            (sid, b"\x01" + b"\x22" * 32, frame),
            (sid, challenge, frame + b"\x00"),
            (sid, challenge, frame[:-1] + bytes([frame[-1] ^ 1])),
        ):
            with self.assertRaises((ValueError, Exception)):
                lab._device_proof(altered_sid, altered_challenge, altered_frame)

    def test_rejects_without_explicit_consent_and_before_network(self):
        requests = []
        def forbidden_factory(address):
            requests.append(address)
            raise AssertionError("Never connect")
        for kwargs in (
            {"ack_lab_only": False, "host": "127.0.0.1", "pin": "123456"},
            {"ack_lab_only": True, "host": "example.com", "pin": "123456"},
            {"ack_lab_only": True, "host": "127.0.0.1", "pin": "bad"},
        ):
            with self.assertRaises(lab.LabSessionError):
                asyncio.run(lab.run_lab_session(
                    entry_id="remote-1", identities=FakeIdentity(),
                    security_factory=forbidden_factory,
                    transport_factory=forbidden_factory, **kwargs
                ))
        self.assertEqual(requests, [])

    def test_no_ha_runtime_registration_or_secret_return(self):
        source = (BASE / "sec2_lab_session.py").read_text()
        init = (BASE / "__init__.py").read_text()
        ws = (BASE / "candidate_identity_ws.py").read_text()
        self.assertNotIn("sec2_lab_session", init + ws)
        self.assertNotIn("@websocket_api", source)
        self.assertNotIn("async_register", source)
        self.assertNotIn("POST /api/config", source)
        self.assertNotIn("deployment_enabled\": True", source)
        self.assertNotIn("ota_enabled\": True", source)


if __name__ == "__main__":
    unittest.main()
