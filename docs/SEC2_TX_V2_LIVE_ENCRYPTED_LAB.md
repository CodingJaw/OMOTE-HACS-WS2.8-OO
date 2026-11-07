# HACS Security2 v2 transaction live LAB compatibility — development only

Date: 2026-11-07. HACS development branch: `main`.
This change adds tests and a pinned protocol fixture only.
**No HACS production enrollment, HA service, automatic connection,
credential write, configuration deployment or OTA endpoint is enabled.**

## Verified prior baseline

The user reported that all previous offline v2 mutual transaction proof
tests passed in both repositories (8 firmware tests, 8 HACS tests and
3 HACS v2 proof-to-receipt binding tests). The Waveshare also passed
the hardware fixed-receipt mbedTLS signature diagnostic. Neither result
proves the newly added live Security2 exchange has run.

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

## Still blocking production

A live signed proof is still NOT pairing. Device key protection,
persistent HA identity, HA-admin + physical touchscreen approval of the
same transaction, fresh enrollment receipts, rollback-safe durable trust
writes, revocation/recovery and authenticated reconnect must be designed
and verified separately. No eFuse or flash encryption configuration
is changed by this feature.
