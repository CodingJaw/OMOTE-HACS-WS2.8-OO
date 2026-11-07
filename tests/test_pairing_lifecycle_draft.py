"""Offline-only matching pairing lifecycle contract and hard gates.

No Home Assistant runtime, device, trusted peer, or firmware write occurs.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/omote_manager/pairing_lifecycle_draft.py"
CONTRACT = ROOT / "tests/fixtures/pairing_lifecycle_contract_v1.json"
NAME = "omote_pairing_draft_tests"
spec = importlib.util.spec_from_file_location(NAME, SOURCE)
policy = importlib.util.module_from_spec(spec)
sys.modules[NAME] = policy
spec.loader.exec_module(policy)
FPR_HA = "a" * 64
FPR_DEVICE = "b" * 64


class PairingLifecycleTests(unittest.TestCase):
    def test_firmware_owned_contract_is_identical_when_provided(self):
        reference = os.environ.get("OMOTE_FIRMWARE_PAIRING_LIFECYCLE")
        if reference:
            self.assertEqual(json.loads(CONTRACT.read_text()),
                             json.loads(Path(reference).read_text()))
        contract = json.loads(CONTRACT.read_text())
        self.assertEqual(contract["states"], [item.value for item in policy.State])
        self.assertTrue(contract["authorization"]["laboratory_only"])
        production = {
            name: enabled for name, enabled in contract["authorization"].items()
            if name != "laboratory_only"
        }
        self.assertTrue(production)
        self.assertFalse(any(production.values()))
        self.assertTrue(contract["rules"]["require_device_identity_hardware_protection_before_trust"])

    def test_real_lab_review_does_not_grant_trust(self):
        s = policy.DraftPairing().apply("open_window", now=100, session_id=17)
        s = s.apply("verify_both", now=101, session_id=17,
                    ha_fingerprint=FPR_HA,
                    device_fingerprint=FPR_DEVICE,
                    evidence_verified=True)
        s = s.apply("present_review", now=102)
        s = s.apply("approve", now=103, admin_approved=True, touch_approved=True)
        self.assertEqual(s.state, policy.State.REVIEW_APPROVED)
        self.assertFalse(s.public_status()["paired"])
        self.assertFalse(s.public_status()["deployment_enabled"])
        with self.assertRaises(policy.PairingPolicyError):
            s.apply("commit_trust", now=104)
        with self.assertRaises(policy.PairingPolicyError):
            s.apply("reconnect", now=104)

    def test_reject_timeout_and_replay(self):
        started = policy.DraftPairing().apply("open_window", now=100, session_id=22)
        with self.assertRaises(policy.PairingPolicyError):
            started.apply("verify_both", now=220, ha_fingerprint=FPR_HA,
                          device_fingerprint=FPR_DEVICE, evidence_verified=True)
        with self.assertRaises(policy.PairingPolicyError):
            started.apply("present_review", now=101)
        proved = started.apply("verify_both", now=110, evidence_verified=True,
                               ha_fingerprint=FPR_HA, device_fingerprint=FPR_DEVICE)
        reviewing = proved.apply("present_review", now=111)
        with self.assertRaises(policy.PairingPolicyError):
            reviewing.apply("approve", now=171,
                            admin_approved=True, touch_approved=True)
        rejected = reviewing.apply("reject", now=112)
        self.assertEqual(rejected.state, policy.State.UNPAIRED)
        with self.assertRaises(policy.PairingPolicyError):
            rejected.apply("open_window", now=113, session_id=22)

    def test_two_party_approval_required(self):
        s = policy.DraftPairing().apply("open_window", now=1, session_id=3)
        s = s.apply("verify_both", now=2, evidence_verified=True,
                    ha_fingerprint=FPR_HA, device_fingerprint=FPR_DEVICE)
        s = s.apply("present_review", now=3)
        for admin, touch in ((False, True), (True, False), (False, False)):
            with self.subTest(admin=admin, touch=touch), self.assertRaises(
                policy.PairingPolicyError
            ):
                s.apply("approve", now=4, admin_approved=admin, touch_approved=touch)

    def test_reboot_drops_transient_review_and_never_trusts(self):
        s = policy.DraftPairing().apply("open_window", now=1, session_id=4)
        s = s.apply("verify_both", now=2, evidence_verified=True,
                    ha_fingerprint=FPR_HA, device_fingerprint=FPR_DEVICE)
        s = s.apply("present_review", now=3)
        s = s.apply("approve", now=4, admin_approved=True, touch_approved=True)
        after = s.apply("reboot", now=5)
        self.assertEqual(after.state, policy.State.UNPAIRED)
        self.assertFalse(after.public_status()["paired"])
        with self.assertRaises(policy.PairingPolicyError):
            after.apply("open_window", now=6, session_id=4)

    def test_bad_fingerprints_session_or_clock_fail_closed(self):
        first = policy.DraftPairing().apply("open_window", now=1, session_id=5)
        for fingerprint in ("A" * 64, "a" * 63, "xyz", None):
            with self.assertRaises(policy.PairingPolicyError):
                first.apply("verify_both", now=2, evidence_verified=True,
                            ha_fingerprint=fingerprint, device_fingerprint=FPR_DEVICE)
        with self.assertRaises(policy.PairingPolicyError):
            first.apply("verify_both", now=2, session_id=6,
                        evidence_verified=True, ha_fingerprint=FPR_HA,
                        device_fingerprint=FPR_DEVICE)
        with self.assertRaises(policy.PairingPolicyError):
            first.apply("verify_both", now=0, evidence_verified=True,
                        ha_fingerprint=FPR_HA, device_fingerprint=FPR_DEVICE)

    def test_no_runtime_registration_or_key_write(self):
        source = SOURCE.read_text()
        self.assertNotIn("@websocket_api", source)
        self.assertNotIn("async_register", source)
        self.assertNotIn("private_der_b64", source)
        self.assertNotIn(".async_save(", source)
        self.assertNotIn(".post(", source)
        self.assertNotIn(".put(", source)
        self.assertIn('if event in ("commit_trust", "reconnect"):', source)


if __name__ == "__main__":
    unittest.main()
