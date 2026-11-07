# Security2 verified-proof transcript v1 — offline canonical binding

Status: **DRAFT / OFFLINE ONLY / NEVER TRUST** (2026-11-07).
Firmware development branch: `feature/config-v2-transactional`.
HACS development branch: `main`. This HACS document mirrors the firmware-owned specification; no live HA enrollment is added.

## Previously verified physical milestone

The user reported PASS of the Waveshare ESP32-S3 serial LAB verifying the
existing **fixed** signed enrollment receipt vectors through ESP-IDF mbedTLS,
including modified-phase and wrong-session rejection. This did not establish
a live Security2 session digest. This new milestone remains separately
**unverified against a real session**.

## Wire format

The firmware-owned contract is:
`Platformio/tools/config-v2-tests/sec2_verified_proofs_transcript_contract_v1.json`.
The HACS repository mirrors the contract and signed public test vector.
All integers are network-order; hex input is lowercase. The digest is SHA-256
of these exact raw bytes:

```text
ASCII("OMOTE-SEC2-VERIFIED-PROOFS-V1" + LF)
u8 1
u32_be Security2 session cookie (nonzero)
u32_be identity epoch (nonzero)
16 bytes random transaction ID
u8 device-ID length (8–32)
device-ID bytes
65 bytes verified HA SEC1 uncompressed P-256 public key
65 bytes verified device SEC1 uncompressed P-256 public key
32 bytes HA proof nonce
32 bytes device proof challenge
u8 HA DER signature length (8–80)
HA signed DER P-256/SHA-256 proof
u8 device DER signature length (8–80)
device signed DER P-256/SHA-256 proof
```

Before producing a digest the offline helper verifies **both** signatures
over the existing LAB proof messages:

```text
HA proof:
ASCII("OMOTE-SEC2-LAB-HA-PROOF-V1") ||
u32_be(session_cookie) || ha_public_sec1_65 || ha_nonce_32

Device proof:
ASCII("OMOTE-SEC2-LAB-DEVICE-PROOF-V1") ||
u32_be(session_cookie) || device_challenge_32 || device_public_sec1_65
```

The helper yields a digest, two computed public-key fingerprints, and
canonical payload bytes, **never** a pairing grant. The public fixture
contains valid ephemeral P-256 signatures, but no private keys and no
production device or HA identity.

## Security boundary: what is still missing

These proofs are cryptographically valid for the supplied cookie, but a
standalone serializer **cannot know whether the cookie originated from the
current locally authenticated Security2 channel**. The current code
cannot enforce same-live-session, freshness or transport authentication.
Also, the existing proof signatures do not independently sign tx_id,
device_id or epoch; although these fields change the transcript hash,
an attacker able to substitute these unsourced fields could make a
different hash. Production wiring must bind these fields to explicit,
fresh, mutually authenticated transaction state BEFORE receipts are
signed. Never accept a digest or claim of verified session directly from
an unauthenticated HTTP request.

Next work before runtime trust:
1. Capture proof inputs from **both sides' actual authenticated session
   state**, including their independently observed session IDs.
2. Bind a fresh tx_id/device/epoch into proof messages or equivalent
   mutually signed transaction challenge; do not assume hashing binds
   unsignaled client metadata.
3. Independently derive digest on firmware and HACS; reject mismatch
   before any signed receipt can become eligible.
4. Require verified HA-admin authorization and physical touchscreen
   confirmation bound to the same transaction and identity fingerprints.
5. Establish hardware key protection/recovery and crash-safe durable
   two-party journal before permitting persistent pairing.

**No API endpoint, HA service, NVS trust write, flash encryption,
OTA, deployment or eFuse operation is enabled by this draft.**

## Tests

Firmware host, with Python `cryptography`, C++17 and `libssl-dev`:

```bash
python3 -m unittest discover \
  -s Platformio/tools/config-v2-tests \
  -p 'test_sec2_verified_proofs_transcript.py' -v
python3 -m unittest discover \
  -s Platformio/tools/config-v2-tests \
  -p 'test_sec2_verified_proofs_crosslang.py' -v
```

HACS:

```bash
python -m unittest discover -s tests \
  -p 'test_sec2_verified_proofs_transcript.py' -v
```

The HACS offline proof-to-receipt integration test also signs
new ephemeral proof messages in memory, derives the transcript hash,
signs an enrollment receipt with that hash, and confirms that a
different transaction hash is rejected. The test NEVER sets
`paired=true` or grants deployments:

```bash
python -m unittest discover -s tests \
  -p 'test_sec2_transcript_receipt_binding.py' -v
```

Firmware CI runs Python and independent OpenSSL C++ proofs and expects the
same canonical 402-byte synthetic test vector. HACS CI pins the exact
firmware contract, vector and draft helper. Passing these tests only
establishes offline proof/byte interoperability, not Security2
authenticated live-session binding.
