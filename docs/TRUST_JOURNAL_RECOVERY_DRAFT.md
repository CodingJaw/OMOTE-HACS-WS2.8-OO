# OMOTE public trust journal and interruption recovery — draft

**Design and test only (2026-11-07).** The live Security2 LAB
interoperability and touchscreen Review OK have passed on the Waveshare,
but its software key remains **untrusted**, and no verified production
peer exists. This document does **not** change that result.

## Shared immutable public record

The firmware is the source of truth for
`Platformio/tools/config-v2-tests/trust_journal_contract_v1.json`;
HACS stores an exact contract fixture in `tests/fixtures/` for CI.

A proposed public journal entry holds only:

| Field | Meaning |
|---|---|
| `format` | Exact version tag `omote-trust-journal-v1-draft` |
| `tx_id` | Fresh, unpredictable 128-bit transaction identifier (hex) |
| `device_id` | Stable physical device identifier (not an IP address) |
| `ha_key_sha256` | SHA-256 of reviewed canonical HA P-256 public key |
| `device_key_sha256` | SHA-256 of reviewed device P-256 public key |
| `device_key_protection` | `software_lab_untrusted` in this draft ONLY |
| `phase` | `prepared`, `commit_intent`, `peer_confirmed`, `aborted`, `revoked` |
| `epoch` | Positive strictly increasing generation counter |

Private keys, PINs, session secrets and tokens are forbidden in this
public record. The validation code refuses unexpected fields, forged
hardware-protection claims, invalid fingerprints and stale epochs.
`device_key_protection=software_lab_untrusted` is a deliberately
non-authorizing marker, **not an acceptable production key policy**.

## Two-party protocol design

1. Start a fresh Security2 enrollment window with a new six-digit code.
2. Prove both keys in a fresh encrypted session and bind the canonical
   transaction to the keys, device ID, endpoint, protocol version and
   ephemeral channel transcript.
3. Confirm the same fingerprints and transaction on HA as administrator
   and on the physical Waveshare. A mere HACS UI click is insufficient.
4. Validate a candidate *prepared* journal record on both sides.
5. Before any peer is considered enrolled, durably save and verify both
   parties' *commit intent*, exchange signed and channel-bound receipts,
   and reconcile any disagreement. Device and HA storage are not atomic
   together; no simple two-phase exchange eliminates every crash window.
6. On loss of power or a lost receipt, show `pending/reconcile`, not
   `paired`. Resume only after fresh cryptographic identity proofs
   and a versioned reconciliation exchange.
7. Authentication and authorization are distinct: even a verified
   production identity would not enable firmware writes. Every deployment
   still needs a fresh HA-admin approval and touchscreen confirmation.
8. Replacement HA installations require a new deliberate pairing and
   must preserve existing configuration. Revocation is a monotonic
   tombstone, not just erasing an entry, to reject stale backup replay.

**Important limits:** The current `trust_journal_draft.py` is an
in-memory pure test model, **not durable storage**. A simulated
`peer_confirmed` phase is diagnostic only and always reports
`paired=false`. Persistence needs a separately designed and tested
NVS journal on the device and protected .storage format on HA, with
verified crash behavior and rollback resistance. Restarting the model
does not establish flash durability. An authenticated receipt must
eventually be verified cryptographically, not accepted as a caller-set
boolean as in the inert tests.

## Decisions to resolve before real enrollment

- Whether production device private keys remain exportable in software
  (laboratory-only security) or must use flash encryption, secure boot,
  secure-element hardware or ESP32 hardware-backed key facilities.
  Analyze this specific Waveshare board and ESP32-S3 revision before
  selecting an irreversible eFuse plan; **NO eFuse changes now**.
- Which power-loss-resistant NVS journal commit mechanism and anti-rollback
  guarantees are feasible on the board. Do not claim monotonicity from
  an ordinary editable NVS integer alone.
- How to recover when HA and device journals disagree, or one peer is
  restored from backup; no unverified automatic trust resurrection.
- How physical approval is bound to a specific `tx_id` and display
  fingerprint, including timeout, deduplication and persistence behavior.
- How revocation and key replacement work while the device is offline.

## Test commands (no hardware change)

Firmware on `feature/config-v2-transactional`:

```sh
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_trust_journal_contract.py' -v
```

HACS on `main`:

```sh
python -m unittest discover -s tests -p 'test_trust_journal_draft.py' -v
```

To compare the exact contract from the two local worktrees, set
`OMOTE_FIRMWARE_TRUST_JOURNAL_CONTRACT` to the full path of the firmware
JSON fixture when running the HACS tests. HACS CI also fetches the
version-pinned firmware fixture and compares it exactly.

**Production enrollment, remote configuration writing, deployment,
OTA, trusted reconnection and eFuse writes remain disabled.**
