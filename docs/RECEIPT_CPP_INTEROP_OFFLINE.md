# OMOTE Security2 receipt interoperability — offline milestone

**Scope:** firmware-side P-256 receipt verification and byte-for-byte
cross-language test vectors. This is **not production pairing**.

## Delivered

- Firmware-owned `enrollment_receipt_vectors_v1.json`: two fixed public
  signed test cases (HA prepare; device commit intent). No test private
  keys are checked in.
- HACS exact mirror at `tests/fixtures/enrollment_receipt_vectors_v1.json`.
- Firmware standalone C++17 `enrollment_receipt_verify_draft.hpp`:
  canonical versioned ASCII JSON encoding, field allowlisting, expected
  tx/device ID/epoch/public fingerprints/session transcript checks, public
  P-256 SEC1 key SHA-256 comparison, DER ECDSA/SHA-256 verification.
- Host harness `enrollment_receipt_verify_host.cpp` uses OpenSSL only
  under `OMOTE_RECEIPT_HOST_OPENSSL`. Firmware-side dormant header
  contains a separate ESP-IDF mbedTLS code path.
- `test_enrollment_receipt_crosslang.py` builds the C++ host harness
  and verifies both signatures, canonical byte equivalence and rejection
  of modified fields, session contexts and peer fingerprints.
- HACS `test_enrollment_receipt_vectors.py` verifies the SAME fixed
  signatures using `cryptography` and requires canonical byte equality.
- HACS CI compares the exact firmware fixture from a pinned GitHub
  commit; firmware has an isolated C++ host CI workflow.

## Safety boundaries

This code sits in `Platformio/tools/config-v2-tests/`. The verifier
is **not** included by the ordinary Waveshare runtime or used as a
Security2 endpoint, and HACS has no production enrollment command.
The verification function is a diagnostic boolean, never an access token.
No firmware NVS journal adapter is linked, no HA .storage trust is
created, and the existing working encrypted LAB remains separate.
There is no pairing permission, authenticated reconnect, OTA, deployment
or eFuse modification.

The fixed `session_transcript_sha256` is synthetic test data. The
production transcript definition must include the authenticated
Security2 channel/session identifier, device identity and roles,
enrollment transaction, both public identities, nonces, and fresh
physical/admin approvals. That transcript must be independently
derived and verified on BOTH peers — never accepted as a client-supplied
string. Likewise, the mbedTLS path still needs a real ESP-IDF build
and hardware acceptance; compiling the OpenSSL host path does not
prove firmware mbedTLS API and memory compatibility.

Even when every signed offline receipt verifies, no trust should be
promoted without a hardware-reviewed private-key strategy and
power-failure-safe two-party enrollment and reconciliation.

## Host tests

Firmware `feature/config-v2-transactional`:
```sh
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_enrollment_receipt_crosslang.py' -v
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_enrollment_receipt_contract.py' -v
```
The C++ test requires g++, OpenSSL headers/library (`libssl-dev` on
Debian) and must report **3 tests OK with no skips** to claim compiler
interoperability.

HACS `main`:
```sh
python -m unittest discover -s tests -p 'test_enrollment_receipt_vectors.py' -v
python -m unittest discover -s tests -p 'test_enrollment_receipt_draft.py' -v
```
Requires cryptography in the test environment; no live HA server call.

**Acceptance:** the previous 12/12 tests passed on the user's systems.
These new fixed-vector and C++ tests must run and pass separately
before calling offline firmware cryptography interoperability verified.
Production pairing remains a distinct, uncompleted milestone.
