"""Offline-only draft OMOTE pairing lifecycle model.

This models review ordering, expiry and replay rejection, NOT production
identity validation or credential persistence. Cryptographic evidence is a
trusted test input here: this module must NEVER be registered as a Home
Assistant WebSocket, service, pairing or deployment authorization endpoint.

The final trust commit is intentionally IMPOSSIBLE pending protected device
keys, durable two-party transaction and physical power-loss tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    UNPAIRED = "unpaired"
    WINDOW_OPEN = "window_open"
    PROOFS_VERIFIED = "proofs_verified"
    REVIEW_PENDING = "review_pending"
    REVIEW_APPROVED = "review_approved"
    PAIRED = "paired"
    REVOKED = "revoked"


class PairingPolicyError(ValueError):
    """An unapproved, expired or replayed offline transition was rejected."""


@dataclass(frozen=True)
class DraftPairing:
    state: State = State.UNPAIRED
    started_at: int | None = None
    reviewed_at: int | None = None
    session_id: int | None = None
    ha_fingerprint: str | None = None
    device_fingerprint: str | None = None
    used_sessions: frozenset[int] = frozenset()
    # No field here is credential storage or an authorization grant.
    production_trust: bool = False
    deployment_enabled: bool = False

    def apply(self, event: str, *, now: int,
              session_id: int | None = None,
              ha_fingerprint: str | None = None,
              device_fingerprint: str | None = None,
              evidence_verified: bool = False,
              admin_approved: bool = False,
              touch_approved: bool = False) -> "DraftPairing":
        """Advance an inert test model only; never write keys or call firmware."""
        if type(now) is not int or now < 0:
            raise PairingPolicyError("invalid-clock")
        if event in ("expire", "reboot"):
            # Transient reviews always vanish; retain replay tombstones.
            return DraftPairing(used_sessions=self.used_sessions)
        if event in ("commit_trust", "reconnect"):
            raise PairingPolicyError("production-enrollment-disabled")
        if event == "revoke":
            # Real revocation needs authenticated peer and local touch; since
            # those are not implemented, even this model cannot grant it.
            raise PairingPolicyError("production-revocation-disabled")
        if event == "open_window":
            if self.state not in (State.UNPAIRED, State.REVOKED):
                raise PairingPolicyError("pairing-window-already-open")
            if type(session_id) is not int or not 1 <= session_id <= 0xFFFFFFFF:
                raise PairingPolicyError("invalid-session")
            if session_id in self.used_sessions:
                raise PairingPolicyError("replayed-session")
            return DraftPairing(
                state=State.WINDOW_OPEN, started_at=now, session_id=session_id,
                used_sessions=self.used_sessions | {session_id}
            )
        if self.started_at is None or now < self.started_at or now - self.started_at >= 120:
            raise PairingPolicyError("pairing-window-expired")
        if session_id is not None and session_id != self.session_id:
            raise PairingPolicyError("session-mismatch")
        if event == "verify_both":
            if self.state != State.WINDOW_OPEN:
                raise PairingPolicyError("out-of-order-proofs")
            import re
            if (not evidence_verified
                    or not all(type(x) is str and re.fullmatch(r"[0-9a-f]{64}", x)
                               for x in (ha_fingerprint, device_fingerprint))):
                raise PairingPolicyError("proofs-not-authenticated")
            from dataclasses import replace
            return replace(self, state=State.PROOFS_VERIFIED,
                           ha_fingerprint=ha_fingerprint,
                           device_fingerprint=device_fingerprint)
        if event == "present_review":
            if self.state != State.PROOFS_VERIFIED:
                raise PairingPolicyError("review-before-proofs")
            from dataclasses import replace
            return replace(self, state=State.REVIEW_PENDING, reviewed_at=now)
        if event in ("approve", "reject"):
            if self.state != State.REVIEW_PENDING or self.reviewed_at is None:
                raise PairingPolicyError("review-not-pending")
            if now < self.reviewed_at or now - self.reviewed_at >= 60:
                raise PairingPolicyError("review-expired")
            if event == "reject":
                return DraftPairing(used_sessions=self.used_sessions)
            if not (admin_approved and touch_approved):
                raise PairingPolicyError("two-party-approval-required")
            from dataclasses import replace
            return replace(self, state=State.REVIEW_APPROVED)
        raise PairingPolicyError("event-not-allowed")

    def public_status(self) -> dict:
        """A diagnostic projection, not a credential or authorization token."""
        return {
            "state": self.state.value,
            "paired": False,
            "trusted": False,
            "production_pairing_enabled": False,
            "authenticated_reconnect_enabled": False,
            "deployment_enabled": False,
            "ota_enabled": False,
            "efuse_changed": False,
        }
