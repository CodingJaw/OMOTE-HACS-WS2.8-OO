# OMOTE HACS secure pairing — Python interoperability plan

Status (2026-11-04): **pairing not implemented**. HACS dev20 now has a read-only pairing-status inspector and strict protocol contract; it still cannot open a pairing window or create an encrypted session.
There is no secure remote pairing, device identity proof, firmware upload
or config deployment. This document is a compatibility checklist, not an
instruction to expose HTTP write routes.

## Supported target

- HA Core 2024.9.1 and HACS 2.0.5 remain the compatibility baseline.
- Only an explicitly locally opened Waveshare pairing window can accept
  new HA trust. The remote shows the six-digit ephemeral PIN.
- Candidate: Espressif `protocomm_security2`, SRP6a and AES-GCM, over
  Wi-Fi HTTPD (not BLE). Do not use security0 or silently downgrade.
- Evaluate the ESP-IDF release-matched Python
  `tools/esp_prov/security/security2.py` reference implementation, including
  pinned versions of its SRP6a, protobuf and cryptography dependencies.
  Do not execute the CLI, leak the PIN to logs, or install unrestricted
  runtime dependencies in Home Assistant.
- SRP6a alone authenticates knowledge of the PIN. It does NOT prove a
  long-lived device/HA key pair. After the PAKE, require a separate
  authenticated HA public-key possession proof, device identity pinning,
  session binding and the remote's physical peer-fingerprint approval.
- Persist device credentials only in private per-device HA storage, with
  revocation and re-pairing on HA reinstall, and never inside portable
  JSON/image profiles.
- Pairing does NOT authorize deployment. Every future deployment requires
  a fresh HA admin action and a fresh target touchscreen approval of the
  exact transaction and manifest digests.

## Verified design/progress and next boundary

- A read-only preview is now defined by the firmware-owned
  `Platformio/tools/config-v2-tests/pairing_v1_preview_contract.json`.
  HACS pins the fixture in CI and validates `GET /api/config/v2/pairing/status`
  with 4 KiB limit, redirect rejection, legacy 404 fallback and strict
  fail-closed typed fields. An untrusted device's preview is **not identity
  proof**. The HACS Overview button only reports unsupported/disabled.
- On the isolated Waveshare firmware feature branch,
  `config_v2_sec2_srp_material.*` actually invokes
  `esp_srp_gen_salt_verifier` with a fresh local six-digit code and
  zeroizes/free its owned salt/verifier. It does not start HTTPD, authorize
  pairing, or expose a PIN.
- **Next:** implement a bounded Security2 HTTPD transport isolated from the
  read-only Arduino WebServer; prove the official ESP-IDF `security2.py`
  client interoperates with an actual locally opened firmware pairing window.
  The encrypted channel must then carry a device-identity key possession
  proof and a separately verified HA peer public key challenge bound to
  that exact PAKE session before any trust is persisted.
- Run negative and power-cycle tests: wrong PIN, unsolicited discovery,
  spoofed identity, replay, aborted sessions, simultaneous sessions, five
  failures across reset, expired PIN, touchscreen reject, HA reinstallation.
  HACS private-key generation and storage must be designed before enabling
  any UI that accepts a real PIN.
- **Do not mark user acceptance** until real board testing. Existing v1
  config import, read-only diagnostics and local backup workflows remain
  separate. Remote-to-remote trust (other ESP routers) is a later extension
  after the HA-to-Waveshare transport is proven.

## Required independent tests before an enabled pairing screen

1. Python version/dependency compatibility with HA 2024.9.1.
2. Official Python client vs actual firmware Security2 handshake (success,
   wrong PIN, expired PIN, cancellation, reconnect, replay and concurrent
   attempts). A mock handshake is not enough.
3. Device-generated salt/verifier for the locally displayed, ephemeral PIN;
   no plaintext credential on the network or in diagnostic output.
4. Device and HA public-key ownership proof, fingerprint mismatch rejection,
   key rotation and HA reinstall preservation of user configuration.
5. Persistent five-attempt lockout across reset and independent touchscreen
   confirmation. No transport may directly invoke `VerifiedPeer`.
6. Bounded transport limits, CPU/heap measurements, per-session nonce safety,
   power interruption, and USB recovery on the Waveshare 2.8 V2.
7. Run the same negative fixtures in both repositories; fail closed if either
   implementation differs. Deployment kill switch stays OFF.

Espressif reference: https://github.com/espressif/esp-idf/tree/release/v5.3/tools/esp_prov
Security advisory: https://github.com/espressif/esp-idf/security/advisories/GHSA-9r76-858f-v6jh
Related firmware contract: `docs/CONFIG_V2_SECURITY2_INTEROP_GATE.md` on
`feature/config-v2-transactional`.
