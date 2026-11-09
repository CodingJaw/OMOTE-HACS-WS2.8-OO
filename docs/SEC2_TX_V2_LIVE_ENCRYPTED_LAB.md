# HACS Security2 v2 transaction live LAB compatibility — development only

## Latest Waveshare acceptance, and production nonce blocker (2026-11-08)

The user's Waveshare hardware verified the full live Security2 laboratory
transaction and **device-signed physical Review OK**. The last signed touch
receipt PASS reported transcript
`07bae75c41e01f7a7dd8ef4ec82cc7a6d12453c7df410c9a61a83392344bb6af`.
This is evidence of a functioning **laboratory** workflow, NOT persistent
HA/device trust, deployment access, or an authenticated production pairing.

Espressif ESP-IDF 5.3.2's Security2 Python and firmware code reuse the
same AES-GCM nonce for repeated session messages; ESP-IDF 5.4.2 has
a counter-based nonce patch (patch 1). Future production pairing MUST reject
patch 0, require a nonce-safe implementation on both ends, use
cryptographically bound negotiation and verify nonce uniqueness across
both traffic directions, including reconnection and counter overflow.

The firmware now has an offline source auditor
`Platformio/tools/config-v2-tests/sec2_nonce_policy.py` and an optional
strict `--require-sec2-patch1` client check (both are diagnostics,
not production pairing). The firmware-owned contract
`sec2_transport_nonce_requirements_v1.json` is mirrored as
`tests/fixtures/sec2_transport_nonce_requirements_v1.json`, and HACS
CI compares it to a pinned firmware commit. It does NOT register an
enrollment endpoint or switch on remote writes. To test its constraints:

```bash
cd ~/Documents/026code/OMOTE-HACS-WS2.8-OO
python3 -m unittest discover -s tests \
  -p 'test_sec2_transport_nonce_requirements.py' -v
```

No HACS restart, remote connection, PIN, NVS erase, or flashing is needed.
The nonsecret legacy laboratory test can still run; production pairing,
trust, authenticated reconnect, configuration deployment and OTA remain
disabled until the secure-transport issue and other acceptance gates pass.



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

## Optional signed touchscreen receipt — offline HACS compatibility only

After real Waveshare hardware confirmed the physical Review OK status over
Security2, firmware work added a separate one-time LAB-only signed receipt
endpoint `omote-tx2-touch-receipt`. This is device-key proof of that
specific review state, session ID, verified v2 transcript SHA-256, and
a fresh HA client challenge. The hardware signature has NOT yet been
tested. The test key remains ordinary software-backed NVS identity.

The firmware-owned wire contract is mirrored byte-for-byte as
`tests/fixtures/sec2_tx_v2_signed_touch_receipt_lab_contract.json`.
HACS CI compares it to a pinned firmware commit. No Home Assistant
integration component registers, calls or accepts this endpoint as
production enrollment, and no credentials or persistent trust are written.

From the HACS repository root:

```bash
python3 -m unittest discover -s tests \
  -p 'test_sec2_tx_v2_signed_touch_receipt_lab_contract.py' -v
```

The firmware's independent manual client supports
`--tx-v2-lab --tx-v2-await-touch --tx-v2-attest-touch --ack-lab-only`,
which verifies the physical acknowledgment's P-256 signature. This
remains a deliberately non-authorizing lab exercise. Persistent HA admin
approval, production-protected device identity, anti-replay trust journal,
secure reconnect, revocation and deployments are separate follow-up tasks.

**Security warning:** ESP-IDF 5.3.2's existing Python Security2
implementation reuses an AES-GCM nonce across messages. Any production
enrollment design must replace/upgrade this with a verified unique
nonce or monotonic counter on both peers before secrets/trust are enabled.

## Isolated newer-toolchain patch-1 build candidate (NOT YET BUILT)

Firmware feature branch now includes a separate
`waveshare28v2_omote_sec2_tx_v2_nonce1_lab` target which pins the
**matched** Tasmota 2026.10.50 platform, Arduino v3.3.12-1 and ESP-IDF
5.5.5. The existing working Security2 v2 lab retains its older framework
and code. The new target refuses to start its listener if the linked
Security2 implementation does not advertise counter-nonce patch 1.

This is explicitly **compile-first and not yet tested on a Waveshare**.
The future protocol still needs authenticated downgrade resistance,
nonce/replay/overflow handling and durable device identity approval.
HACS receives only a read-only fixture contract, not a pairing service.

The firmware-owned contract `sec2_nonce1_toolchain_candidate_contract.json`
is mirrored in `tests/fixtures/sec2_nonce1_toolchain_candidate_contract.json`
and pinned in CI. Offline HACS compatibility test:

```bash
python3 -m unittest discover -s tests \
  -p 'test_sec2_nonce1_toolchain_candidate_contract.py' -v
```

The firmware repository's
`docs/SEC2_NONCE1_IDF55_EXPERIMENTAL_MIGRATION.md` contains the
compile-only target instructions, a **shallow sparse non-recursive**
ESP-IDF Python checkout under `~/Documents/026code/esp-idf-nonce1`,
and subsequent conditional hardware test. Do not flash the unverified
toolchain or replace the working `esp-idf` checkout automatically.

## Still blocking production

A live signed proof is still NOT pairing. Device key protection,
persistent HA identity, HA-admin + physical touchscreen approval of the
same transaction, fresh enrollment receipts, rollback-safe durable trust
writes, revocation/recovery and authenticated reconnect must be designed
and verified separately. No eFuse or flash encryption configuration
is changed by this feature.
