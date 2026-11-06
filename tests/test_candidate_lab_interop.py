"""Firmware-owned LAB HA-proof frame interoperability using a saved HA candidate key.

Unlike the earlier disposable CLI identity, this exercise signs twice
using a *persisted* HA candidate key, reloads the store, and independently
checks the exact firmware request framing and ECDSA cryptography.  It is
an OFFLINE protocol test: never contacts the Waveshare, exposes private
material, enables pairing, or allows remote writes.
"""
from __future__ import annotations

import asyncio
import copy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
CONTRACT_PATH = Path(__file__).with_name("fixtures") / "sec2_lab_ha_proof_contract.json"

package = types.ModuleType("candidate_lab_interop_tests")
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(
    package.__name__ + ".candidate_identity", COMPONENT / "candidate_identity.py"
)
identity = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = identity
spec.loader.exec_module(identity)


class SerializedLocalStore:
    def __init__(self, initial=None):
        self.saved = copy.deepcopy(initial)

    async def async_load(self):
        return copy.deepcopy(self.saved)

    async def async_save(self, value):
        # Simulate Home Assistant Store's serialized restart boundary.
        self.saved = json.loads(json.dumps(value))


class CandidateLabInteropTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT_PATH.read_text())
        self.record_store = SerializedLocalStore()
        self.identity = identity.CandidateIdentityStore(self.record_store)
        asyncio.run(self.identity.async_load())
        self.remote_entry_id = "c" * 32

    def test_firmware_contract_is_pinned_and_frame_format_matches(self):
        reference = os.environ.get("OMOTE_FIRMWARE_LAB_PROOF_CONTRACT")
        if reference:
            self.assertEqual(self.contract, json.loads(Path(reference).read_text()))
        request = self.contract["request"]
        self.assertEqual(request["version"], 1)
        self.assertEqual(request["header_bytes"], 100)
        self.assertEqual(request["signature_min_bytes"], 8)
        self.assertEqual(request["signature_max_bytes"], 80)
        self.assertEqual(self.contract["transport"]["endpoint"], "omote-ha-proof")
        self.assertTrue(
            self.contract["transport"]["must_be_inside_completed_encrypted_security2_session"]
        )
        self.assertEqual(request["domain"].encode("ascii"), identity._DOMAIN)
        self.assertTrue(all(x is False for x in self.contract["authorization"].values()))

        status = asyncio.run(self.identity.async_prepare(self.remote_entry_id))
        session_id = 0x98765432
        proof = self.identity.make_lab_ha_proof(self.remote_entry_id, session_id)

        self.assertEqual(proof[0], 1)
        self.assertEqual(proof[1], 4)
        self.assertEqual(len(proof[1:66]), 65)
        self.assertEqual(len(proof[66:98]), 32)
        sig_len = int.from_bytes(proof[98:100], "big")
        self.assertGreaterEqual(sig_len, request["signature_min_bytes"])
        self.assertLessEqual(sig_len, request["signature_max_bytes"])
        self.assertEqual(len(proof), request["header_bytes"] + sig_len)

        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), proof[1:66]
        )
        message = request["domain"].encode() + session_id.to_bytes(4, "big") + proof[1:98]
        public_key.verify(proof[100:], message, ec.ECDSA(hashes.SHA256()))
        self.assertEqual(sha256(proof[1:66]).hexdigest(), status["fingerprint"])
        self.assertFalse(status["trusted"])
        self.assertFalse(status["pairing_enabled"])
        self.assertFalse(status["deployment_enabled"])

        # A captured request is invalid if the live Security2 session is not
        # identical.  The nonce is also signed, so it cannot be replaced.
        tamper = [
            request["domain"].encode() + (session_id + 1).to_bytes(4, "big") + proof[1:98],
            message[:-1] + bytes([message[-1] ^ 1]),
            b"NOT-OMOTE" + message[len(request["domain"]):],
        ]
        for modified in tamper:
            with self.subTest(kind=modified[:10]), self.assertRaises(InvalidSignature):
                public_key.verify(proof[100:], modified, ec.ECDSA(hashes.SHA256()))

    def test_reboot_reuses_same_key_but_never_reuses_nonce_or_signature(self):
        first = asyncio.run(self.identity.async_prepare(self.remote_entry_id))
        p1 = self.identity.make_lab_ha_proof(self.remote_entry_id, 54321)
        reloaded = identity.CandidateIdentityStore(self.record_store)
        asyncio.run(reloaded.async_load())
        p2 = reloaded.make_lab_ha_proof(self.remote_entry_id, 54321)
        self.assertEqual(p1[1:66], p2[1:66])
        self.assertNotEqual(p1[66:98], p2[66:98])
        self.assertNotEqual(p1[100:], p2[100:])
        self.assertEqual(first["fingerprint"], reloaded.status(self.remote_entry_id)["fingerprint"])
        self.assertFalse(reloaded.status(self.remote_entry_id)["trusted"])

    def test_clean_ha_install_requires_new_candidate_key_and_not_automatic_trust(self):
        old = asyncio.run(self.identity.async_prepare(self.remote_entry_id))
        new_store = identity.CandidateIdentityStore(SerializedLocalStore())
        asyncio.run(new_store.async_load())
        self.assertFalse(new_store.status(self.remote_entry_id)["prepared"])
        with self.assertRaises(identity.CandidateIdentityError):
            new_store.make_lab_ha_proof(self.remote_entry_id, 0)
        fresh = asyncio.run(new_store.async_prepare(self.remote_entry_id))
        self.assertNotEqual(fresh["fingerprint"], old["fingerprint"])
        self.assertFalse(fresh["trusted"])
        self.assertFalse(fresh["pairing_enabled"])

    def test_no_firmware_or_browser_signing_endpoint(self):
        ws_source = (COMPONENT / "candidate_identity_ws.py").read_text()
        api_source = (COMPONENT / "api.py").read_text()
        self.assertNotIn("make_lab_ha_proof(", ws_source)
        self.assertNotIn("private_der_b64", ws_source)
        self.assertNotIn("omote-ha-proof", api_source)
        self.assertNotIn("18082", api_source)
        self.assertNotIn("candidate/rotate", ws_source)
        self.assertNotIn("candidate/delete", ws_source)


if __name__ == "__main__":
    unittest.main()
