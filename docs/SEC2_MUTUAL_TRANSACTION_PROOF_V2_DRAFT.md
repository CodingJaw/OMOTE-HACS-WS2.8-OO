# OMOTE Security2 v2 mutual transaction proof — OFFLINE DRAFT

Date: 2026-11-07. **Never used by the live pairing or deployment paths.**

## Verified prerequisites

The user reported 6/6 HACS v1 transcript tests, 3/3 HACS proof-to-receipt
tests, 6/6 firmware Python tests and 4/4 independent OpenSSL C++ tests,
plus 9/9 USB capture tests and an actual ESP32-S3 serial log reporting
fixed public receipt vector checks PASS.

The earlier `omote-sec2-verified-proofs-transcript-v1-draft` validated
signatures on the Security2 cookie and each proof challenge. However,
the two original proof signatures did NOT cover the enrollment tx_id,
device_id or identity epoch. Those fields were merely mixed into the
transcript hash after the signatures. This is insufficient to authorize
a particular transaction.

## v2 mutual signing design

See `sec2_mutual_transaction_proof_v2_contract.json` (firmware-owned)
and the offline-only Python helper. The P-256 signing keys here are
ephemeral, software test keys; none are committed.

Before either peer signs, both peers must agree on the exact context:

```text
u8  version = 2
u32 Security2 session cookie (big-endian, nonzero)
u32 identity epoch (big-endian, nonzero)
16-byte fresh enrollment transaction ID
u8 device ID length (8..32) + device ID bytes
65-byte HA SEC1 uncompressed P-256 public key
65-byte device SEC1 uncompressed P-256 public key
32-byte fresh HA nonce
32-byte fresh device challenge
```

Then each peer signs **those exact same context bytes** under
a different domain:

```text
HA    ECDSA_P256_SHA256_DER("OMOTE-SEC2-TX-PROOF-HA-V2\\n" || context)
Device ECDSA_P256_SHA256_DER("OMOTE-SEC2-TX-PROOF-DEVICE-V2\\n" || context)
```

The offline validator requires BOTH signatures and an independent
`observed` context. Every field must match the authenticated
peer/session's observed state before a digest is derived:

```text
SHA256("OMOTE-SEC2-TX-TRANSCRIPT-V2\\n" ||
       context || u8_ha_signature_length || ha_signature_DER ||
       u8_device_signature_length || device_signature_DER)
```

Any modification to the cookie, transaction ID, device ID, epoch,
public keys or either challenge invalidates the signatures or the
independent context match. A receipt containing the old digest is
rejected when checked against the new transaction's expected digest.

## Unimplemented security gates

- No runtime Security2 handler calls the helper. A Python `observed`
  dictionary is NOT by itself proof of genuine session authentication.
  Both peers must collect the expected context from their respective
  locally authenticated encrypted session and enforce replay protection.
- This scheme requires a **new multi-step, same-session exchange**
  where both challenges, keys, device ID, tx_id and epoch are agreed
  BEFORE either participant signs. It is NOT wire compatible with the
  existing one-way lab proof endpoints without that exchange.
- HA administrator authorization and physical touchscreen consent
  must independently bind the same context, or a signed proof cannot
  authorize enrollment.
- Persistent replay protection, durable two-phase trust journal,
  recovery/revocation, hardware identity protection and power-failure
  testing are still required before persistent pairing.
- The v2 helper and tests do NOT grant pairing, authenticated reconnect,
  config write, deployment, OTA, secure boot or eFuse programming.

## Tests (not yet user-verified)

Firmware, from `OMOTE-Firmware-WS2.8-OO/Platformio`:

```bash
python3 -m unittest discover -s tools/config-v2-tests \\
  -p 'test_sec2_mutual_transaction_proof_v2.py' -v
```

HACS, from `OMOTE-HACS-WS2.8-OO` root:

```bash
python -m unittest discover -s tests \\
  -p 'test_sec2_mutual_transaction_proof_v2.py' -v
python -m unittest discover -s tests \\
  -p 'test_sec2_mutual_transaction_receipt_v2.py' -v
```

The 8 firmware tests and 8+3 HACS tests cover valid mutual signatures,
complete-context alterations, independent-session mismatch, DER
tampering, unauthorized permissions and offline signed receipt binding.
No physical upload is needed. These tests do not establish live
Security2 channel binding.
