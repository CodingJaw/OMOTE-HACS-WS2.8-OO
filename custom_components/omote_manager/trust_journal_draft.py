"""Offline-only trust journal validator and interrupted-enrollment simulator.

Never import into pairing WebSocket handlers, endpoints or firmware writers.
This simulator deliberately NEVER authorizes a real peer or device command.
The 'peer_confirmed' phase denotes an authenticated receipt observed in an
offline model, not distributed atomic commit or a production trust grant.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

FORMAT = "omote-trust-journal-v1-draft"
PHASES = frozenset({"prepared", "commit_intent", "peer_confirmed",
                    "aborted", "revoked"})
FIELDS = frozenset({"format", "tx_id", "device_id", "ha_key_sha256",
                    "device_key_sha256", "device_key_protection",
                    "phase", "epoch"})


class TrustJournalError(ValueError):
    """Rejected malformed or unauthenticated offline draft transition."""


def _hex(value: object, length: int) -> bool:
    return type(value) is str and bool(re.fullmatch(
        rf"[0-9a-f]{{{length}}}", value
    ))


def validate_public_record(data: object) -> dict:
    """Strictly parse public metadata only; never parse secret/key material."""
    if type(data) is not dict or data.keys() != FIELDS:
        raise TrustJournalError("record-fields")
    if data["format"] != FORMAT:
        raise TrustJournalError("record-version")
    if not _hex(data["tx_id"], 32):
        raise TrustJournalError("transaction-id")
    if not (type(data["device_id"]) is str
            and re.fullmatch(r"[0-9a-f]{16,64}", data["device_id"])
            and len(data["device_id"]) % 2 == 0):
        raise TrustJournalError("device-id")
    for key in ("ha_key_sha256", "device_key_sha256"):
        if not _hex(data[key], 64):
            raise TrustJournalError("fingerprint")
    if data["device_key_protection"] != "software_lab_untrusted":
        # No unproven claim of hardware protection is accepted by this model.
        raise TrustJournalError("unverified-key-protection")
    if data["phase"] not in PHASES or type(data["phase"]) is not str:
        raise TrustJournalError("phase")
    if type(data["epoch"]) is not int or data["epoch"] <= 0:
        raise TrustJournalError("epoch")
    return dict(data)


@dataclass(frozen=True)
class Journal:
    """No persistence; represents one peer's local public metadata snapshot."""
    record: dict | None = None
    used_txids: frozenset[str] = frozenset()
    max_epoch: int = 0
    trust_enabled: bool = False
    writes_enabled: bool = False

    def transition(self, event: str, *, data: dict | None = None,
                   authenticated_receipt: bool = False,
                   approved_on_both_devices: bool = False,
                   same_transcript: bool = False) -> "Journal":
        if event in ("grant_trust", "authenticated_reconnect", "deploy",
                     "revoke_production", "efuse"):
            raise TrustJournalError("production-operation-disabled")
        if event == "prepare":
            d = validate_public_record(data)
            if self.record is not None and self.record["phase"] not in (
                    "aborted", "revoked"):
                raise TrustJournalError("outstanding-transaction")
            if d["phase"] != "prepared" or d["tx_id"] in self.used_txids:
                raise TrustJournalError("transaction-replay")
            if d["epoch"] != self.max_epoch + 1:
                raise TrustJournalError("epoch-rollback")
            if not (approved_on_both_devices and same_transcript):
                raise TrustJournalError("missing-approvals-or-transcript")
            return replace(self, record=d, used_txids=self.used_txids
                           | {d["tx_id"]}, max_epoch=d["epoch"])
        if self.record is None:
            raise TrustJournalError("no-prepared-transaction")
        phase = self.record["phase"]
        if event == "commit_intent":
            if phase != "prepared":
                raise TrustJournalError("out-of-order-commit")
            if not same_transcript:
                raise TrustJournalError("transcript-mismatch")
            return replace(self, record={**self.record, "phase": "commit_intent"})
        if event == "peer_receipt":
            if phase != "commit_intent" or not (authenticated_receipt and same_transcript):
                raise TrustJournalError("unverified-peer-receipt")
            return replace(self, record={**self.record, "phase": "peer_confirmed"})
        if event == "abort":
            if phase == "revoked":
                raise TrustJournalError("already-revoked")
            return replace(self, record={**self.record, "phase": "aborted"})
        if event == "revoke_tombstone":
            # This is a test-only tombstone. Production revocation still blocked.
            if not (authenticated_receipt and same_transcript):
                raise TrustJournalError("unauthorized-tombstone")
            return replace(self, record={**self.record, "phase": "revoked"})
        if event == "reboot":
            # No information in this process-only model is durable. The caller
            # must explicitly reconstruct it from validated storage in future.
            return self
        raise TrustJournalError("unknown-event")

    def public_status(self) -> dict:
        return {
            "journal_phase": self.record["phase"] if self.record else "empty",
            "production_pairing_enabled": False,
            "paired": False,
            "authenticated_reconnect_enabled": False,
            "deployment_enabled": False,
            "ota_enabled": False,
        }
