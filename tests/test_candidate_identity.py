"""Offline real P-256 persistence, corruption and non-authorizing boundary.

No Home Assistant runtime, actual Waveshare or pairing attempts are needed.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
pkg = types.ModuleType("omote_candidate_tests")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(
    pkg.__name__ + ".candidate_identity", ROOT / "candidate_identity.py"
)
identity = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = identity
spec.loader.exec_module(identity)


class FakeHAStore:
    """JSON serialization round trip models HA .storage, not an encrypted vault."""
    def __init__(self, raw=None, fail_save=False):
        self.raw = deepcopy(raw)
        self.saves = 0
        self.fail_save = fail_save

    async def async_load(self):
        return deepcopy(self.raw)

    async def async_save(self, state):
        if self.fail_save:
            raise OSError("backend unavailable")
        self.raw = json.loads(json.dumps(state))
        self.saves += 1


class CandidateIdentityTests(unittest.TestCase):
    ENTRY = "ea01c36f98c7404c993bbd8d86d0dd1c"

    def _store(self, backing=None):
        target = backing or FakeHAStore()
        store = identity.CandidateIdentityStore(target)
        asyncio.run(store.async_load())
        return store, target

    def test_no_secret_created_on_start_and_idempotent_admin_preparation(self):
        store, backing = self._store()
        self.assertEqual(backing.saves, 0)
        self.assertFalse(store.status(self.ENTRY)["prepared"])
        self.assertEqual(store.status(self.ENTRY)["fingerprint"], "")
        first = asyncio.run(store.async_prepare(self.ENTRY))
        second = asyncio.run(store.async_prepare(self.ENTRY))
        self.assertTrue(first["prepared"])
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(backing.saves, 1)
        self.assertEqual(len(first["fingerprint"]), 64)
        self.assertFalse(first["trusted"])
        self.assertFalse(first["pairing_enabled"])
        self.assertFalse(first["deployment_enabled"])
        self.assertFalse(first["nvs_or_device_updated"])
        for value in (first, second, store.status(self.ENTRY)):
            serialized = json.dumps(value)
            self.assertNotIn("private", serialized)
            self.assertNotIn("signature", serialized)
            self.assertNotIn("nonce", serialized)
            self.assertNotIn("access_token", serialized)
        # This local test store *does* contain an unencrypted DER private key,
        # which is why these credentials may not be treated as hardware-secure.
        self.assertIn("private_der_b64", str(backing.raw))

    def test_restarts_keep_same_per_remote_public_fingerprint(self):
        store, backing = self._store()
        a = asyncio.run(store.async_prepare(self.ENTRY))
        rebooted, _ = self._store(backing)
        self.assertEqual(rebooted.status(self.ENTRY)["fingerprint"], a["fingerprint"])
        self.assertFalse(asyncio.run(rebooted.async_prepare(self.ENTRY))["created"])
        self.assertEqual(backing.saves, 1)
        other_id = "b" * 32
        b = asyncio.run(rebooted.async_prepare(other_id))
        self.assertNotEqual(a["fingerprint"], b["fingerprint"])
        self.assertTrue(b["prepared"])
        self.assertEqual(store.status(self.ENTRY)["fingerprint"], a["fingerprint"])

    def test_actual_lab_wire_proof_uses_saved_private_key_and_fresh_nonce(self):
        store, backing = self._store()
        fingerprint = asyncio.run(store.async_prepare(self.ENTRY))["fingerprint"]
        proof = store.make_lab_ha_proof(self.ENTRY, 123456)
        self.assertEqual(proof[0], 1)
        self.assertEqual(proof[1], 4)
        self.assertEqual(len(proof[1:66]), 65)
        self.assertEqual(len(proof[66:98]), 32)
        self.assertEqual(int.from_bytes(proof[98:100], "big"), len(proof) - 100)
        self.assertEqual(sha256(proof[1:66]).hexdigest(), fingerprint)
        pubkey = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), proof[1:66],
        )
        signed = (
            b"OMOTE-SEC2-LAB-HA-PROOF-V1"
            + (123456).to_bytes(4, "big") + proof[1:98]
        )
        pubkey.verify(proof[100:], signed, ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):
            pubkey.verify(
                proof[100:], signed.replace(
                    (123456).to_bytes(4, "big"), (123457).to_bytes(4, "big"),
                ), ec.ECDSA(hashes.SHA256()),
            )
        proof2 = store.make_lab_ha_proof(self.ENTRY, 123456)
        self.assertEqual(proof[1:66], proof2[1:66])
        self.assertNotEqual(proof[66:98], proof2[66:98])
        rebooted, _ = self._store(backing)
        proof3 = rebooted.make_lab_ha_proof(self.ENTRY, 123457)
        self.assertEqual(proof[1:66], proof3[1:66])
        self.assertNotEqual(proof[66:98], proof3[66:98])

    def test_corrupt_missing_or_modified_key_fails_closed_no_rotation(self):
        store, backing = self._store()
        asyncio.run(store.async_prepare(self.ENTRY))
        original = deepcopy(backing.raw)
        for tamper in ("fingerprint", "private_der_b64", "format"):
            broken = deepcopy(original)
            data = broken["identities"][self.ENTRY]
            if tamper == "fingerprint":
                data[tamper] = "0" * 64
            elif tamper == "private_der_b64":
                data[tamper] = "x" * 200
            else:
                data[tamper] = "unknown"
            saved = FakeHAStore(broken)
            failed, _ = self._store(saved)
            with self.subTest(tamper=tamper):
                with self.assertRaises(identity.CandidateIdentityError):
                    failed.status(self.ENTRY)
                with self.assertRaises(identity.CandidateIdentityError):
                    asyncio.run(failed.async_prepare(self.ENTRY))
                self.assertEqual(saved.saves, 0)
        self.assertEqual(original, backing.raw)

    def test_save_failure_does_not_publish_or_return_identity(self):
        backing = FakeHAStore(fail_save=True)
        store, _ = self._store(backing)
        with self.assertRaises(identity.CandidateIdentityError):
            asyncio.run(store.async_prepare(self.ENTRY))
        self.assertFalse(store.status(self.ENTRY)["prepared"])
        self.assertEqual(backing.saves, 0)

    def test_invalid_input_cannot_create_storage(self):
        store, backing = self._store()
        for entry in ("", "a/b", "../bad", "x" * 129, None):
            with self.subTest(entry=entry):
                with self.assertRaises(identity.CandidateIdentityError):
                    asyncio.run(store.async_prepare(entry))
        for session in (-1, 0x100000000, True, "11", None):
            with self.subTest(session=session), self.assertRaises(
                identity.CandidateIdentityError
            ):
                store.make_lab_ha_proof(self.ENTRY, session)
        self.assertEqual(backing.saves, 0)

    def test_concurrent_prepare_cannot_rotate_or_double_write(self):
        store, backing = self._store()

        async def prepare_twice():
            return await asyncio.gather(
                store.async_prepare(self.ENTRY),
                store.async_prepare(self.ENTRY),
            )

        a, b = asyncio.run(prepare_twice())
        self.assertEqual({a["created"], b["created"]}, {True, False})
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertEqual(backing.saves, 1)

    def test_websocket_never_exposes_private_key_or_firmware_calls(self):
        ws = (ROOT / "candidate_identity_ws.py").read_text()
        panel = (ROOT / "panel.py").read_text()
        api = (ROOT / "api.py").read_text()
        self.assertIn("connection.user.is_admin", ws)
        self.assertIn("omote_manager/pairing/candidate/status", ws)
        self.assertIn("omote_manager/pairing/candidate/prepare", ws)
        self.assertNotIn("make_lab_ha_proof(", ws)
        for forbidden in (
            "private_der_b64", "async_get_clientsession", "._session.post(",
            "._session.put(", "18082", "omote-device-proof",
            "replaceAfterAuthenticatedPhysicalApproval",
        ):
            self.assertNotIn(forbidden, ws)
        self.assertNotIn("omote_manager/pairing/candidate/prepare", api)
        self.assertIn("register_candidate_identity_websockets(hass)", panel)


if __name__ == "__main__":
    unittest.main()
