"""Offline file durability tests. Uses only TemporaryDirectory, never HA storage."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
PACKAGE = "omote_file_journal_offline_test"
module = types.ModuleType(PACKAGE)
module.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = module

def load_module(name):
    spec = importlib.util.spec_from_file_location(
        PACKAGE + "." + name, ROOT / (name + ".py"))
    target = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = target
    spec.loader.exec_module(target)
    return target

model = load_module("trust_journal_draft")
storage = load_module("trust_journal_file_draft")

def record(epoch=1, phase="prepared", txid="1" * 32):
    return {
        "format": "omote-trust-journal-v1-draft",
        "tx_id": txid, "device_id": "a" * 16,
        "ha_key_sha256": "b" * 64,
        "device_key_sha256": "c" * 64,
        "device_key_protection": "software_lab_untrusted",
        "phase": phase, "epoch": epoch,
    }

def state(epoch=1, phase="prepared", txid="1" * 32, history=None):
    return model.Journal(record=record(epoch, phase, txid),
        used_txids=frozenset(history if history is not None else [txid]),
        max_epoch=epoch)

class OfflineFileJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trust-snapshot.json"
        self.store = storage.OfflineJournalFile(self.path)

    def test_atomic_save_load_and_permissions(self):
        self.assertIsNone(self.store.load().record)
        self.store.save(state())
        self.assertEqual(self.store.load().record, record())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(self.store.load().public_status()["paired"])
        self.assertFalse(self.store.load().public_status()["deployment_enabled"])
        envelope = json.loads(self.path.read_text())
        self.assertEqual(set(envelope), {"snapshot", "sha256"})
        self.assertNotIn("private_key", self.path.read_text())

    def test_ordered_update_preserves_replay_tombstones(self):
        self.store.save(state())
        self.store.save(state(phase="commit_intent"))
        self.store.save(state(phase="peer_confirmed"))
        self.store.save(state(phase="aborted"))
        self.store.save(state(2, "prepared", "2"*32, history={"1"*32, "2"*32}))
        recovered = self.store.load()
        self.assertEqual(recovered.max_epoch, 2)
        self.assertEqual(recovered.used_txids, frozenset({"1"*32, "2"*32}))
        self.assertFalse(recovered.public_status()["paired"])

    def test_corrupted_or_truncated_snapshot_not_silently_reset(self):
        self.store.save(state())
        self.path.write_bytes(b'{"snapshot":')
        with self.assertRaises(model.TrustJournalError):
            self.store.load()
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state(2, txid="2"*32, history={"1"*32, "2"*32}))
        self.assertEqual(self.path.read_bytes(), b'{"snapshot":')

    def test_modified_snapshot_with_stale_checksum_is_rejected(self):
        self.store.save(state())
        content = json.loads(self.path.read_text())
        content["snapshot"]["record"]["phase"] = "peer_confirmed"
        self.path.write_text(json.dumps(content))
        with self.assertRaises(model.TrustJournalError):
            self.store.load()

    def test_epoch_and_phase_rollback_rejected(self):
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state(1, "commit_intent"))
        self.store.save(state(1, "prepared"))
        self.store.save(state(1, "commit_intent"))
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state(1, "prepared"))
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state(0, "prepared"))
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state(2, "prepared", "2"*32))
        with self.assertRaises(model.TrustJournalError):
            self.store.save(model.Journal(
                record=record(1, "commit_intent"),
                max_epoch=1, used_txids=frozenset()))

    def test_symlink_and_excessive_snapshot_rejected(self):
        actual = Path(self.temp.name) / "actual.json"
        actual.write_text("not a journal")
        self.path.symlink_to(actual)
        with self.assertRaises(model.TrustJournalError):
            self.store.load()
        with self.assertRaises(model.TrustJournalError):
            self.store.save(state())
        self.path.unlink()
        self.path.write_bytes(b"x" * (storage.MAX_BYTES + 1))
        with self.assertRaises(model.TrustJournalError):
            self.store.load()

    def test_no_ha_runtime_registration_or_key_storage(self):
        source = (ROOT / "trust_journal_file_draft.py").read_text()
        for forbidden in ("@websocket_api", "async_register", "Store(", ".async_save(",
                          "private_der_b64", "nvs_set_blob", "esp_efuse"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
