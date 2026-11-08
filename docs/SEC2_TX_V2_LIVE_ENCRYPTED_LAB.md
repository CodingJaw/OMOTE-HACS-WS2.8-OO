# HACS Security2 v2 transaction live LAB compatibility — development only

Updated: 2026-11-08. HACS development branch: `main`.
This change adds tests and a pinned protocol fixture only.
**No HACS production enrollment, HA service, automatic connection,
credential write, configuration deployment or OTA endpoint is enabled.**

## Verified prior baseline

The user reported that all previous offline v2 mutual transaction proof
tests passed in both repositories (8 firmware tests, 8 HACS tests and
3 HACS v2 proof-to-receipt binding tests). The Waveshare also passed
the hardware fixed-receipt mbedTLS signature diagnostic. The actual Waveshare later passed live Security2 SRP6a/AES-GCM and
both bound P-256 signature checks, including transcript comparison, on
2026-11-08. That verifies live cryptography, not physical Review OK.

## New firmware-only opt-in experimental exchange

The firmware feature branch has a new *separate* build target
`waveshare28v2_omote_sec2_tx_v2_lab`, extending the existing
touchscreen-started encrypted `sec2_lab` but guarded with the new
`OMOTE_CONFIG_V2_SEC2_TX_V2_LAB` flag.

Within the already authenticated Security2 session on port 18082:
- `omote-tx2-open` receives a fresh HA ephemeral P-256 public key and
  32-byte challenge, and returns a device-generated transaction ID,
  device challenge, lab epoch, device public key and actual session cookie.
- `omote-tx2-commit` receives a full transaction-context HA signature,
  verifies it against the same callback session, then returns an
  existing lab software device-key signature and transcript digest.
- The *manual firmware Python client* verifies both signatures and
  independently checks transcript digest before printing `NOT PAIRED`.
  It does not use the HA's persistently prepared candidate key.
- The pending transaction is volatile and expires after 30 seconds.
  The existing lab PIN, persistent Security2 attempt count and physical
  Start lab action remain in effect.

See the firmware-owned source contract, copied exactly into
`tests/fixtures/sec2_tx_v2_live_lab_wire_contract.json`. The HACS
validation workflow pins this fixture to a firmware commit. The HACS
offline signed context v2 verifier remains
`custom_components/omote_manager/sec2_mutual_transaction_proof_v2_draft.py`
and is NOT registered as a network handler.

## HACS test

From the **HACS repository root**:

```bash
git pull --ff-only origin main
python -m unittest discover -s tests \
  -p 'test_sec2_tx_v2_live_lab_wire_contract.py' -v
```

Expected: 3 tests. New tests have not yet been run by the user.
No firmware flashing is involved in this HACS test.

The separate firmware build and manual live client are documented in
`docs/SEC2_TX_V2_LIVE_ENCRYPTED_LAB.md` in the firmware repository.
Do not flash until the build and static guards pass.

## Read-only local touchscreen review LAB addendum — unverified

The firmware feature branch now has a third **encrypted, read-only** endpoint,
`omote-tx2-review`, bound to the same authenticated Security2 session and
verified mutual v2 transcript digest as the preceding OPEN/COMMIT. It reports
only `pending` or physically `reviewed`. It cannot remotely trigger Review OK,
pair the device or change persistent trust. Failure, rejection and expiry
do not produce a reviewed status.

The firmware-owned addendum
`Platformio/tools/config-v2-tests/sec2_tx_v2_local_review_lab_wire_contract.json`
is mirrored in HACS at
`tests/fixtures/sec2_tx_v2_local_review_lab_wire_contract.json`.
A pinned comparison runs in HACS CI; HACS does not register or call this
LAB endpoint. The firmware's standalone Python CLI supports an explicit
`--tx-v2-await-touch` flag to test the local-touch outcome.

Run this offline HACS test from the repository root:

```bash
python3 -m unittest discover -s tests \
  -p 'test_sec2_tx_v2_local_review_lab_wire_contract.py' -v
```

This is development code and **has not yet been accepted on hardware**.
The next test must show an actual physical Review OK on the Waveshare and
a corresponding successful status read by the same encrypted lab client.
It must never be mistaken for an HA admin approval or production enrollment.

## Still blocking production

A live signed proof is still NOT pairing. Device key protection,
persistent HA identity, HA-admin + physical touchscreen approval of the
same transaction, fresh enrollment receipts, rollback-safe durable trust
writes, revocation/recovery and authenticated reconnect must be designed
and verified separately. No eFuse or flash encryption configuration
is changed by this feature.
