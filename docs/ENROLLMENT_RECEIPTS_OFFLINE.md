# Signed enrollment receipts — isolated Security2 continuation (2026-11-07)

**Offline cryptographic protocol design and tests only. This is NOT pairing.**

The physical Waveshare laboratory already completed a genuine Home Assistant
Security2 SRP6a/AES-GCM encrypted exchange, P-256 candidate identity proof,
device software-key proof and touchscreen Review OK. The device correctly
reports **No verified peer. Pairing unavailable** afterward.

The next dependency is a verifiable **enrollment receipt**, not an enrollment
button. Both parties must agree on exactly which identities, transaction,
device, epoch and session they are acknowledging.

## Firmware-owned protocol contract

`Platformio/tools/config-v2-tests/enrollment_receipt_contract_v1.json`
defines the receipt wire format and restrictions. HACS mirrors it at
`tests/fixtures/enrollment_receipt_contract_v1.json`; the HACS CI workflow
compares the exact pinned firmware fixture.

Each signed **body** has:
- `version`: exact string `omote-enrollment-receipt-v1-draft`
- `tx_id`: 128-bit random lowercase-hex enrollment transaction ID
- `device_id`: physical device identifier, not hostname or IP
- `epoch`: positive identity generation number
- `ha_key_sha256`, `device_key_sha256`: canonical SEC1 uncompressed
  P-256 public-key SHA-256 fingerprints
- `session_transcript_sha256`: hash of a future *authenticated*, canonical
  Security2 enrollment transcript (NOT derived from a public HTTP status)
- `nonce`: independently generated 128-bit per-receipt value
- `signer`: `ha` or `device`
- `phase`: `prepare`, `commit_intent` or `peer_confirmed`

The signature is ECDSA P-256/SHA-256 in DER encoding, over exactly:

```text
UTF8("OMOTE-ENROLLMENT-RECEIPT-V1" + LF) ||
ASCII_JSON(body, sort_keys=True, no_spaces, escaped_ascii=True)
```

`signature_der_hex` accompanies the body. This signature proves possession
relative to a public key supplied **independently from the verified encrypted
channel**, not a key embedded in an untrusted receipt. Signature checks alone
DO NOT prove the key is hardware-protected or permanently trusted.

## Reconciliation is explicitly NON-AUTHORIZING

`custom_components/omote_manager/enrollment_receipt_draft.py` is an
offline HACS model. It checks ECDSA signatures, canonical fields and
fingerprints, transcript hash, txid, device ID and epoch. Duplicate signer /
phase and signer / nonce receipts are rejected. If six distinct valid receipts
cover all three phases on both sides, it reports **diagnostic** complete;
otherwise it requests authenticated reconciliation.

**Even with six valid receipts, it always returns `paired=false`,
`trusted=false`, `deployment_enabled=false`, and `ota_enabled=false`.**

It does not open a listener, register HA services, touch firmware, write NVS
or touch eFuses. It does not integrate with the existing LAB screen.
The private signing keys used by the tests are generated in memory.

## Important unsolved production questions

- Define and verify the **canonical Security2 transcript** to be hashed.
  The current offline tests *supply* the expected transcript digest; they
  do not independently derive it from a live session.
- Bind the individual receipt to fresh administrator approval and physical
  touchscreen approval. An authenticated signature without these approvals
  must never authorize enrollment.
- Implement the Waveshare's exact canonical serializer and ECDSA
  verification with independently verified keys and strict request limits.
  The firmware change here is a **contract + test**, not a crypto endpoint.
- Audit crash/reboot and revocation behavior, stale-image replay, durable
  transaction ordering and reconciliation before any production storage
  writes or trust promotion.
- Investigate hardware-protected device identity separately. The current
  `software_lab_untrusted` key is not a production hardware trust root.
  **No eFuse programming is included or authorized.**

## Offline tests

Firmware (`feature/config-v2-transactional`):

```bash
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_enrollment_receipt_contract.py' -v
```

HACS (`main`, isolated Python venv with `cryptography` installed):

```bash
python -m unittest discover -s tests -p 'test_enrollment_receipt_draft.py' -v
```

The tests validate signatures and negative cases without touching the real
Home Assistant `.storage` or Waveshare. The existence of these tests does
not establish that the actual device firmware implements the new receipts.

**All production pairing, HA credential and device trust writes, OTA,
configuration deployment, authenticated reconnect and eFuse operations
remain disabled.**
