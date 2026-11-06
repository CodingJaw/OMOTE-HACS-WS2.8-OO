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


class WorkingCandidate:
    def __init__(self):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.public = self.private.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        self.fingerprint = sha256(self.public).hexdigest()

    def status(self, entry_id):
        if entry_id != "remote-1":
            raise ValueError("Unexpected remote")
        return {"prepared": True, "trusted": False, "fingerprint": self.fingerprint}

    def make_lab_ha_proof(self, entry_id, session_id):
        if entry_id != "remote-1" or session_id != 17:
            raise ValueError("Wrong session")
        nonce = b"\x33" * 32
        message = b"OMOTE-SEC2-LAB-HA-PROOF-V1" + session_id.to_bytes(4, "big") + self.public + nonce
        signature = self.private.sign(message, ec.ECDSA(hashes.SHA256()))
        return b"\x01" + self.public + nonce + len(signature).to_bytes(2, "big") + signature


class MockSecurity2:
    def __init__(self, *, sec_patch_ver, username, password, verbose):
        assert sec_patch_ver == 1 and username == "omote-ha"
        assert password == "123456" and verbose is False
        self.iteration = 0

    def security_session(self, response):
        self.iteration += 1
        if self.iteration == 1:
            assert response is None
            return "SRP-FIRST"
        if self.iteration == 2:
            assert response == "SRP-RESPONSE"
            return None
        raise AssertionError("Unexpected SRP step")

    def encrypt_data(self, data):
        return data

    def decrypt_data(self, data):
        return data


class MockConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class MockLabTransport:
    def __init__(self, address, *, wrong_device_signature=False, bad_reply=False,
                 oversize=False):
        assert address == "127.0.0.1:18082"
        self.headers = {"Cookie": "session=17"}
        self.conn = MockConnection()
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.calls = []
        self.wrong_device_signature = wrong_device_signature
        self.bad_reply = bad_reply
        self.oversize = oversize

    async def send_data(self, endpoint, payload):
        self.calls.append(endpoint)
        if endpoint == "proto-ver":
            return '{"prov":{"ver":"omote-sec2-lab-v1","sec_patch_ver":1}}'
        if endpoint == "prov-session":
            return "SRP-RESPONSE"
        if endpoint == "omote-probe":
            assert payload == "OMOTE-SEC2-PROBE-V1"
            return "OMOTE-SEC2-OK-V1"
        if endpoint == "omote-ha-proof":
            if self.oversize:
                return "A" * 4097
            assert payload.encode("latin-1")[0] == 1
            return "INVALID" if self.bad_reply else "OMOTE-LAB-HA-PROOF-OK-V1"
        if endpoint == "omote-device-proof":
            challenge = payload.encode("latin-1")
            assert len(challenge) == 33 and challenge[0] == 1
            public = self.private.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
            signed = lab._DEVICE_DOMAIN + (17).to_bytes(4, "big") + challenge[1:] + public
            signature = self.private.sign(signed, ec.ECDSA(hashes.SHA256()))
            if self.wrong_device_signature:
                signature = signature[:-1] + bytes([signature[-1] ^ 1])
            response = b"\x01" + public + len(signature).to_bytes(2, "big") + signature
            return response.decode("latin-1")
        raise AssertionError("Unexpected endpoint")


class LabExchangeTests(unittest.TestCase):
    def run_session(self, **settings):
        transports = []
        def make_transport(address):
            t = MockLabTransport(address, **settings)
            transports.append(t)
            return t
        result = asyncio.run(lab.run_lab_session(
            host="127.0.0.1", pin="123456", entry_id="remote-1",
            identities=WorkingCandidate(),
            security_factory=MockSecurity2,
            transport_factory=make_transport,
            ack_lab_only=True,
        ))
        return result, transports[0]

    def test_completed_encrypted_lab_proofs_never_grant_trust(self):
        result, transport = self.run_session()
        self.assertTrue(result["encrypted_probes_passed"])
        self.assertTrue(result["lab_only"])
        self.assertRegex(result["candidate_ha_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["untrusted_device_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertFalse(result["trusted"])
        self.assertFalse(result["paired"])
        self.assertFalse(result["deployment_enabled"])
        self.assertFalse(result["ota_enabled"])
        self.assertTrue(transport.conn.closed)
        self.assertEqual(
            transport.calls,
            ["proto-ver", "prov-session", "omote-probe",
             "omote-ha-proof", "omote-device-proof"]
        )

    def test_rejects_corrupt_device_proof(self):
        with self.assertRaises(lab.LabSessionError) as ctx:
            self.run_session(wrong_device_signature=True)
        self.assertEqual(ctx.exception.stage, "device-proof")

    def test_rejects_bad_ha_receipt(self):
        with self.assertRaises(lab.LabSessionError) as ctx:
            self.run_session(bad_reply=True)
        self.assertEqual(ctx.exception.stage, "candidate-proof")

    def test_rejects_oversized_reply(self):
        with self.assertRaises(lab.LabSessionError) as ctx:
            self.run_session(oversize=True)
        self.assertEqual(ctx.exception.stage, "candidate-proof")


if __name__ == "__main__":
    unittest.main()
