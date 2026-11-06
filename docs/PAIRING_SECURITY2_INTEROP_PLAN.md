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

## Shared lab key-possession protocol (2026-11-04)

A new *experimental* firmware-only encrypted endpoint
`POST /omote-ha-proof` verifies a P-256 ECDSA signature for a candidate
Home Assistant key, bound to the current Espressif Security2 session ID
and a fresh 32-byte client nonce. The exact versioned wire contract is
`tests/fixtures/sec2_lab_ha_proof_contract.json`, pinned to the
firmware-owned source in HACS CI.

**This is neither trusted pairing nor a HACS runtime connection:** the
manual reference Python client creates an ephemeral test key. Firmware
does not save it or grant privileges; HACS dev20 does not call the lab
endpoint. The original port-80 configuration interface stays read-only
and fully usable. No HACS pairing UI or firmware write route is enabled.

Before HACS can use this candidate proof, implement the missing
counterpart: a durable hardware-bound device public-key identity with
device key-possession proof, protected private key storage, pinned
device fingerprint verification in HACS, durable HA identity key storage,
replay-safe transcript confirmation, and a one-shot physical touchscreen
approval bound to **both** keys and the actual Security2 session.
Old credentials must not be silently inherited by a reinstalled HA.

## Device software identity lab milestone (2026-11-05)

Firmware now has an **opt-in-only** third encrypted LAB endpoint,
`omote-device-proof`, with a locally provisioned P-256 software key.
The device signs a fresh client challenge over
`OMOTE-SEC2-LAB-DEVICE-PROOF-V1 || current Security2 session ID ||
challenge || device public key` and returns its SEC1 public key and
DER signature inside AES-GCM. A manual Python tester verifies it and
displays a SHA-256 public-key fingerprint. The exact versioned contract
is pinned in HACS `tests/fixtures/sec2_lab_device_identity_contract.json`
and cross-checked with firmware in CI.

**Not production device identity:** The key is stored in ordinary NVS
under `omsec2id/labkey`, which is not guaranteed encrypted or
hardware-protected on this board configuration. Copying the flash
may copy the private key. HACS must not pin it as trusted production
device identity, and it does not connect to `omote-device-proof`.
No eFuse provisioning, paired HA identity, approval action,
authorization, or deployment has been implemented.

The previously user-verified hardware Security2 SRP6a/AES-GCM and
candidate HA P-256 proof both passed. The *new* software device identity
path is code-level only until the lab build and hardware
challenge/signature test pass. Firmware feature branch is isolated and
the normal Waveshare/HACS behavior is unaffected.

The next security architecture task is establishing how to protect the
production private key on the ESP32-S3 without accidentally burning
eFuses or erasing the user's only working remote. That must be designed
and reviewed before production HA identity pinning or trusted pairing.

## Same-session dual-key laboratory review (2026-11-05)

The user has hardware-verified the SRP6a/AES-GCM lab client, candidate HA
P-256 proof, software-backed device P-256 proof, and the local no-wait
quota rearm. These facts establish **lab interoperability, not pairing**.

Firmware now has a LAB-only volatile mutual-proof policy. After the
candidate HA key signature and device software-key signature are
separately verified **in the same encrypted Security2 session**,
firmware records their exact public-key SHA-256 fingerprints in RAM,
rejecting mixed session IDs, duplicate proofs and expired evidence.
The Waveshare can present the full candidate HA fingerprint across
four rows and offer `Review OK` or `Reject` for 60 seconds. The
matching manual Python client prints the **ephemeral public** HA
fingerprint for an operator to compare. Private keys and the six-digit
PIN remain undisclosed.

This is a visual, volatile **lab acknowledgement only**. The reference
Python client may finish and close its socket before the touchscreen
review; it is therefore *not* live authenticated enrollment. No peer
credential is persisted, neither NVS nor HA is authorized, no deployment
or OTA capability is enabled. The firmware contract
`sec2_lab_mutual_review_contract.json` is pinned by HACS under
`tests/fixtures/` and CI checks they match. HACS still does not open
port 18082 or offer a Pair button.

**Not yet hardware-tested:** the new combined fingerprint presentation
and touchscreen Review OK/Reject path. This must pass firmware CI and
real Waveshare touch testing before being accepted as laboratory UI
interoperability. Real protected device identity, persistent HA key,
live session-held pairing approval, replay-resistant cross-identity
transcript and revocation are distinct later milestones.

## HA dev22 — persistent local candidate identity per remote (2026-11-05)

The HACS development integration now implements a local-only,
administrator-prepared P-256 *candidate* identity per registered OMOTE
entry. It is **NOT paired or trusted** and remains disconnected from
firmware Security2 until the protected-key/live-session pairing gate
has been reviewed.

Implementation:
- `candidate_identity.py` stores one canonical PKCS#8 DER private key
  (base64-encoded) and its SHA-256 fingerprint of the 65-byte P-256
  SEC1 public key in HA's separate `.storage/omote_manager.candidate_identities`
  via the Home Assistant `Store` API.
- **Important:** HA `.storage` is **not guaranteed encrypted at rest**.
  A full HA backup (or disk access) may copy this candidate private
  key. This is a development candidate, not a hardware-protected
  credential. Protect HA backup archives and the operating-system
  filesystem; no private key appears in portable OMOTE JSON profile
  backups, browser replies or logs. A new installation without a
  restored key generates a new candidate; restoring the HA backup
  can restore the old key.
- Keys are created only by the explicit, admin-only OMOTE Manager
  **Prepare HA key locally** button and confirmation. A read-only
  **status** displays the public fingerprint. There is NO automatic
  key creation at HA startup, no implicit key rotation, no browser
  access to private DER, and no signing API exposed to WebSocket.
- The local identity source can produce an offline, domain-bound
  P-256 ECDSA proof in the preexisting encrypted LAB candidate-HA
  frame format, including a fresh random nonce and the exact
  Security2 session identifier. This method is NOT connected to
  an actual network transport. Tests verify real ECDSA signatures,
  fingerprint stability across HA restart, distinct per-remote
  identities, and fail-closed corrupted/wrong-version/failed-save
  behavior.
- HACS main bumped to **0.1.0-dev22** for a new sidebar element
  and cache-busting frontend assets.

The local WebSockets `omote_manager/pairing/candidate/status` and
`.../prepare` check administrator privileges and registered remote
entry IDs; they return **only non-secret fingerprint/status fields**
and never contact the remote or authorize configuration writes.

The separate six-digit lab Python command still generates a NEW
ephemeral key on each invocation and still requires the on-screen
code. Preparing a persistent candidate key in HACS does **not**
turn that CLI into permanent pairing.

### Remaining blockers for real PIN-free reconnection

1. Establish **protected** Waveshare device private-key storage,
   flash/NVS threat model, recovery/rotation procedure and verified
   physical provisioning, without unauthorized eFuse changes.
2. Implement a HACS-originated Security2 session bound to the
   saved per-remote HA candidate P-256 key **and** a pinned,
   cryptographically verified protected device identity, including
   server-authenticated anti-MITM and replay-safe transcript binding.
3. Hold a live authenticated connection while the actual
   touchscreen compares the verified HA fingerprint, then store
   the approved HA public identity durably with readback and
   rollback/error handling. A stale or closed lab socket can never
   approve persistent trust.
4. Prove an authenticated, PIN-less reconnection after HA/Waveshare
   restart and a fresh-pairing requirement following explicit
   removal or clean HA reinstall. A full HA backup restore needs
   explicit identity/ownership handling.
5. Keep **all configuration deployment and OTA disabled** until
   separately authenticated admin action, fresh device touch
   approval of the exact proposed transaction and hardware rollback.

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
