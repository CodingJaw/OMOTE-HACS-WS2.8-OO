# OMOTE HACS secure pairing — Python interoperability plan

Status: **not implemented**. The current HACS client remains read-only.
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
