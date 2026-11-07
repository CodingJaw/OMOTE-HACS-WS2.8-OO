"""Offline-only atomic file snapshot for PUBLIC trust-journal diagnostics.

No runtime service imports this module. This is not a secure key store, a
rollback-proof record, or a production trust database. It is deliberately
inert: even a valid peer_confirmed snapshot never grants pairing rights.

Each save atomically replaces one file with os.replace, fsyncs the file and
parent directory, and verifies its SHA-256 corruption checksum on recovery.
SHA-256 without a secret authenticating key does NOT prevent deliberate edits.
Corrupt or unexpected existing data fails closed instead of silently clearing
the state or selecting an older journal entry.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .trust_journal_draft import Journal, TrustJournalError, validate_public_record

FORMAT = "omote-trust-file-snapshot-v1-draft"
MAX_BYTES = 8192
MAX_TXIDS = 64


def _encode(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def _hex(value: object, n: int) -> bool:
    return type(value) is str and bool(re.fullmatch(rf"[0-9a-f]{{{n}}}", value))


def _snapshot(journal: Journal) -> dict:
    if type(journal) is not Journal or journal.trust_enabled or journal.writes_enabled:
        raise TrustJournalError("privileged-journal-forbidden")
    if (type(journal.max_epoch) is not int or journal.max_epoch < 0
            or type(journal.used_txids) is not frozenset
            or len(journal.used_txids) > MAX_TXIDS
            or not all(_hex(v, 32) for v in journal.used_txids)):
        raise TrustJournalError("invalid-journal-metadata")
    record = None if journal.record is None else validate_public_record(journal.record)
    if record is not None and (record["tx_id"] not in journal.used_txids
                               or record["epoch"] > journal.max_epoch):
        raise TrustJournalError("journal-inconsistent")
    return {"version": FORMAT, "record": record, "used_txids": sorted(journal.used_txids),
            "max_epoch": journal.max_epoch}


def _decode(data: bytes) -> Journal:
    if len(data) > MAX_BYTES:
        raise TrustJournalError("snapshot-too-large")
    try:
        obj = json.loads(data.decode("ascii"))
        if type(obj) is not dict or set(obj) != {"snapshot", "sha256"}:
            raise TrustJournalError("snapshot-envelope")
        raw = _encode(obj["snapshot"])
        if not _hex(obj["sha256"], 64) or sha256(raw).hexdigest() != obj["sha256"]:
            raise TrustJournalError("snapshot-checksum")
        doc = obj["snapshot"]
        if type(doc) is not dict or set(doc) != {"version", "record", "used_txids", "max_epoch"}:
            raise TrustJournalError("snapshot-fields")
        if doc["version"] != FORMAT:
            raise TrustJournalError("snapshot-version")
        txids = doc["used_txids"]
        if (type(txids) is not list or len(txids) > MAX_TXIDS
                or txids != sorted(set(txids)) or not all(_hex(v, 32) for v in txids)):
            raise TrustJournalError("snapshot-txids")
        epoch = doc["max_epoch"]
        if type(epoch) is not int or epoch < 0:
            raise TrustJournalError("snapshot-epoch")
        record = (None if doc["record"] is None
                  else validate_public_record(doc["record"]))
        if record is not None and (record["tx_id"] not in txids
                                   or record["epoch"] > epoch):
            raise TrustJournalError("snapshot-consistency")
        return Journal(record=record, used_txids=frozenset(txids), max_epoch=epoch)
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
        if isinstance(exc, TrustJournalError):
            raise
        raise TrustJournalError("invalid-snapshot") from None


class OfflineJournalFile:
    """Path must be a private, existing test directory; never HA .storage."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _check_target(self) -> None:
        parent = self.path.parent
        if (not parent.is_dir() or parent.is_symlink()
                or not stat.S_ISDIR(os.lstat(parent).st_mode)
                or not self.path.name or self.path.name in (".", "..")):
            raise TrustJournalError("unsafe-journal-directory")
        if self.path.is_symlink():
            raise TrustJournalError("symlink-journal-rejected")
        if self.path.exists() and not stat.S_ISREG(os.lstat(self.path).st_mode):
            raise TrustJournalError("nonregular-journal-rejected")

    def load(self) -> Journal:
        self._check_target()
        if not self.path.exists():
            return Journal()
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_BYTES + 1)
        except OSError:
            raise TrustJournalError("snapshot-read-failed") from None
        return _decode(data)

    def save(self, journal: Journal) -> None:
        self._check_target()
        # Fail closed: refuse to overwrite damaged state even with a good snapshot.
        previous = self.load()
        current = _snapshot(journal)
        if previous.record is None and journal.record is not None:
            if journal.record["phase"] != "prepared":
                raise TrustJournalError("snapshot-must-begin-prepared")
        if journal.max_epoch < previous.max_epoch or not previous.used_txids.issubset(journal.used_txids):
            raise TrustJournalError("snapshot-rollback")
        if previous.record is not None and journal.record is None:
            raise TrustJournalError("snapshot-record-removal")
        if previous.record is not None and journal.record is not None:
            if journal.max_epoch == previous.max_epoch:
                allowed = {"prepared": {"prepared", "commit_intent", "aborted", "revoked"},
                           "commit_intent": {"commit_intent", "peer_confirmed", "aborted", "revoked"},
                           "peer_confirmed": {"peer_confirmed", "aborted", "revoked"},
                           "aborted": {"aborted"}, "revoked": {"revoked"}}
                if (journal.record["tx_id"] != previous.record["tx_id"]
                        or journal.record["phase"] not in allowed[previous.record["phase"]]):
                    raise TrustJournalError("snapshot-phase-rollback")
        payload = _encode(current)
        wire = _encode({"snapshot": current, "sha256": sha256(payload).hexdigest()})
        if len(wire) > MAX_BYTES:
            raise TrustJournalError("snapshot-too-large")
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix=".omote-journal-", dir=self.path.parent)
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(wire)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            tmp = None
            parent_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except OSError:
            raise TrustJournalError("snapshot-save-failed") from None
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
