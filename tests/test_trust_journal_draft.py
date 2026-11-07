"""Offline-only trust-journal schema and two-party interruption tests."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/omote_manager/trust_journal_draft.py"
CONTRACT = ROOT / "tests/fixtures/trust_journal_contract_v1.json"
spec = importlib.util.spec_from_file_location("omote_trust_journal_test", SOURCE)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def sample(**kw):
    value = {"format": "omote-trust-journal-v1-draft",
             "tx_id": "1" * 32, "device_id": "a" * 16,
             "ha_key_sha256": "b" * 64, "device_key_sha256": "c" * 64,
             "device_key_protection": "software_lab_untrusted",
             "phase": "prepared", "epoch": 1}
    return dict(value, **kw)


class TrustJournalTests(unittest.TestCase):
    def test_shared_contract_and_explicit_disabled_authorizations(self):
        data = json.loads(CONTRACT.read_text())
        path = os.environ.get("OMOTE_FIRMWARE_TRUST_JOURNAL_CONTRACT")
        if path:
            self.assertEqual(data, json.loads(Path(path).read_text()))
        self.assertEqual(data["contract"], "omote-trust-journal-v1-draft")
        self.assertEqual(set(data["public_record"]["exact_keys"]), model.FIELDS)
        self.assertTrue(data["authorization"]["laboratory_only"])
        self.assertTrue(all(value is False for key, value in data["authorization"].items()
                            if key != "laboratory_only"))
        self.assertFalse(data["protocol"]["network_endpoint_enabled"])
        self.assertFalse(data["protocol"]["credentials_or_trust_writes_enabled"])

    def test_strict_public_record_without_secrets(self):
        self.assertEqual(model.validate_public_record(sample()), sample())
        for field, invalid in (("tx_id", "z"*32),
                               ("ha_key_sha256", "B"*64),
                               ("device_key_sha256", "0"*63),
                               ("device_id", "abcd"),
                               ("epoch", True),
                               ("phase", "paired"),
                               ("device_key_protection", "hardware_protected")):
            with self.subTest(field=field), self.assertRaises(model.TrustJournalError):
                model.validate_public_record(sample(**{field: invalid}))
        with self.assertRaises(model.TrustJournalError):
            model.validate_public_record(dict(sample(), secret_private_key="private"))
        with self.assertRaises(model.TrustJournalError):
            model.validate_public_record({k: v for k, v in sample().items() if k != "tx_id"})

    def test_two_party_journal_never_grants_trust_even_after_receipts(self):
        left = model.Journal().transition("prepare", data=sample(),
                       approved_on_both_devices=True, same_transcript=True)
        right = model.Journal().transition("prepare", data=sample(),
                       approved_on_both_devices=True, same_transcript=True)
        left = left.transition("commit_intent", same_transcript=True)
        right = right.transition("commit_intent", same_transcript=True)
        left = left.transition("peer_receipt", authenticated_receipt=True,
                               same_transcript=True)
        right = right.transition("peer_receipt", authenticated_receipt=True,
                                 same_transcript=True)
        self.assertEqual(left.record["phase"], "peer_confirmed")
        self.assertEqual(right.record["phase"], "peer_confirmed")
        self.assertFalse(left.public_status()["paired"])
        self.assertFalse(right.public_status()["paired"])
        for forbidden in ("grant_trust", "authenticated_reconnect", "deploy",
                          "revoke_production", "efuse"):
            with self.subTest(event=forbidden), self.assertRaises(model.TrustJournalError):
                left.transition(forbidden)

    def test_missing_approval_wrong_transcript_or_fake_receipt(self):
        start = model.Journal()
        with self.assertRaises(model.TrustJournalError):
            start.transition("prepare", data=sample(), same_transcript=True)
        prepared = start.transition("prepare", data=sample(),
                  approved_on_both_devices=True, same_transcript=True)
        with self.assertRaises(model.TrustJournalError):
            prepared.transition("commit_intent", same_transcript=False)
        intent = prepared.transition("commit_intent", same_transcript=True)
        for auth, transcript in ((False, True), (True, False)):
            with self.subTest(auth=auth), self.assertRaises(model.TrustJournalError):
                intent.transition("peer_receipt", authenticated_receipt=auth,
                                  same_transcript=transcript)

    def test_interrupted_asymmetric_commit_remains_untrusted(self):
        left = model.Journal().transition("prepare", data=sample(),
                   approved_on_both_devices=True, same_transcript=True)
        right = model.Journal().transition("prepare", data=sample(),
                    approved_on_both_devices=True, same_transcript=True)
        left = left.transition("commit_intent", same_transcript=True)
        # Lost link or reboot before the other device moves to commit intent.
        self.assertEqual(left.transition("reboot").record["phase"], "commit_intent")
        self.assertEqual(right.transition("reboot").record["phase"], "prepared")
        for peer in (left, right):
            self.assertFalse(peer.public_status()["paired"])
            self.assertFalse(peer.public_status()["deployment_enabled"])
        with self.assertRaises(model.TrustJournalError):
            right.transition("peer_receipt", authenticated_receipt=True,
                             same_transcript=True)

    def test_txid_replay_epoch_rollback_and_tombstone(self):
        start = model.Journal().transition("prepare", data=sample(),
                    approved_on_both_devices=True, same_transcript=True)
        aborted = start.transition("abort")
        with self.assertRaises(model.TrustJournalError):
            aborted.transition("prepare", data=sample(),
                               approved_on_both_devices=True, same_transcript=True)
        with self.assertRaises(model.TrustJournalError):
            aborted.transition("prepare", data=sample(tx_id="2"*32, epoch=1),
                               approved_on_both_devices=True, same_transcript=True)
        with self.assertRaises(model.TrustJournalError):
            start.transition("revoke_tombstone", authenticated_receipt=False,
                             same_transcript=True)
        tombstone = start.transition("revoke_tombstone",
                          authenticated_receipt=True, same_transcript=True)
        self.assertEqual(tombstone.record["phase"], "revoked")
        self.assertFalse(tombstone.public_status()["paired"])

    def test_no_runtime_registration_or_storage(self):
        src = SOURCE.read_text()
        for forbidden in ("@websocket_api", "async_register", ".async_save(",
                          "open(", "requests.", "aiohttp.", "esp_efuse", "NVS"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
