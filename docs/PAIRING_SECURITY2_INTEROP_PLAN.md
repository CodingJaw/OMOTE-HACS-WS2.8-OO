# OMOTE HACS secure pairing — Python interoperability plan

Status (2026-11-06): **production pairing not implemented**. HACS dev22 has read-only pairing status, firmware-owned Security2 lab protocol contracts, and a persistent administrator-prepared P-256 *candidate* HA identity. The isolated Waveshare laboratory image has demonstrated SRP6a/AES-GCM and two P-256 possession proofs on hardware, but HACS itself does **not** establish Security2 sessions or enroll trust. Firmware deployment and OTA remain disabled. This document is a compatibility checklist, not authorization to expose remote write routes.

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

## Next step after HA candidate-key restart acceptance (2026-11-06)

The user verified on Home Assistant that the dev22 per-remote candidate
public-key SHA-256 fingerprint **survives restarts** and a second
`Prepare HA key locally` action returns the **same** fingerprint
without rotating the key. That accepts the local HA persistence gate.
The candidate is still **NOT PAIRED**.

The firmware-owned `sec2_lab_ha_proof_contract.json` now has an
additional HACS CI interoperability test,
`tests/test_candidate_lab_interop.py`. It checks a *persisted* candidate
HA key across simulated restarts against the exact firmware-specified
wire frame: version 1; 65-byte SEC1 P-256 public key; 32-byte nonce;
big-endian DER signature length; and ECDSA-SHA256 over the domain,
Security2 session ID, key and nonce. It rejects session substitution,
nonce tampering and wrong signed domain. A clean HA installation has no
automatically inherited key or trust. This test is completely OFFLINE,
does not export private material, and does not open port 18082.

### Transport packaging acceptance before enabling any live HACS pairing

The firmware test harness deliberately uses Espressif's reference
`tools/esp_prov/security/security2.py` and
`Transport_HTTP` from an explicit `IDF_PATH` checkout. Home
Assistant normally does **not** include that full source tree,
its generated protobuf modules or its transport dependencies.

Do **not** import the development-machine's ESP-IDF paths at HA runtime,
accept arbitrary imported Python packages, shell out to the reference CLI,
vendor an unreviewed SRP implementation or ask the browser to handle
HA private keys. First isolate a reviewed, version-pinned, testable
protocol client compatible with HA Core 2024.9.1, with no access to
production firmware configuration writes.

Required runtime gates:

1. Explicit administrator-initiated, per-remote LAB action only, with
   the freshly displayed six-digit PIN entered securely and never logged;
   no scheduled, boot-triggered or discovery-initiated PAKE attempts.
2. A strict 120-second local listener timeout, bounded payloads, no
   redirects, no unexpected IP/port destinations, and the existing
   five Security2-frame/physical-window quotas honored.
3. Use the **already persisted** HA private key only inside the server;
   derive a new client nonce each session, verify both the device
   possession signature and its 64-hex public-key fingerprint, and
   bind the candidate HA proof to the exact same encrypted session.
4. The Waveshare must show the **same HA candidate fingerprint**
   as HACS. Its physical **Review OK** is still a LAB-only acknowledgement
   until a protected device key, a live session-held approval, and
   durable two-way trust replacement are reviewed and implemented.
5. Negative tests (wrong PIN, substituted endpoint, rogue device key,
   replay, expired session, reboot, abort, double request), duplicate
   concurrent attempts, and **no** secret in logs/HTTP/WebSocket replies.
6. Production API status and HACS deployment/OTA gates must remain
   disabled regardless of laboratory success.

PIN-free reconnect requires a **separate** mutually authenticated
cryptographic transport for subsequent sessions. A persisted P-256
public key and an ECDSA signature by themselves do not establish
an encrypted channel or a reusable authorization token.

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


## 2026-11-06 — isolated persistent-candidate Security2 laboratory adapter

HACS `main` now includes `custom_components/omote_manager/sec2_lab_session.py`
and `tests/test_sec2_lab_session.py`. This adapter is **not imported or
registered in Home Assistant's runtime startup or WebSocket handlers**.
It is opt-in test infrastructure, not a supported Pair action.

When called explicitly by future tightly scoped *server-side* laboratory
tooling, it requires affirmative `ack_lab_only`, a literal IPv4 host,
a six-digit locally displayed PIN, a previously prepared HA candidate
identity, and caller-injected **official ESP-IDF** Security2 and HTTP
transport factories. It then checks the lab version, performs bounded
Security2 negotiation, validates an encrypted fixed probe, sends the
existing persistent HA candidate's per-session P-256 signature frame,
and verifies an encrypted per-session challenge signature by the
device's **unprotected experimental NVS software key**.

The device public-key fingerprint is returned only as an **untrusted
laboratory observation**. Nothing pins it, persists peer trust, or
authorizes pairing, credential changes, deployment, OTA or recovery
writes. Errors expose a stage name rather than PIN, ciphertext,
session cookie or raw device output. Responses are bounded to 4096
characters, per-exchange deadlines are 8 seconds, and a single overall
attempt is limited to 40 seconds. There is **no automatic retry**;
the firmware's persistent Security2 attempt budget remains applicable.

The offline tests cover exact cookie parsing, actual P-256 device
signatures and session/nonce replay rejection, explicit-consent and
preflight rejection without a network connection, successful
mocked end-to-end exchange, invalid HA receipts, corrupted device
signatures, oversized replies, and an explicit check that no runtime
HACS WebSocket registration was added.

**Hardware acceptance is still pending.** The official Espressif Python
client modules are **not packaged as HACS runtime dependencies**;
there is deliberately no production or UI execution path. Before
registering a deliberately initiated admin-only lab operation, review
exact HA 2024.9.1 Python dependencies, HTTP transport cancellation,
redirect behavior, concurrent attempts and a short-lived PIN handling
boundary. The standalone ephemeral-key Python lab client and the
normal HACS read-only integration are unchanged.

The firmware `feature/config-v2-transactional` branch and all eFuses
remain unchanged. Protected device identity, live session-held
fingerprint approval, durable trust, re-pairing and PIN-free reconnect
are not yet implemented.


## 2026-11-06 — HACS dev23: explicitly enabled HA-originated LAB exchange

New **experimental** HACS `main` server-side code uses the original
persistent per-entry candidate HA P-256 key to contact the same isolated
Waveshare laboratory port-18082 protocol that the standalone
`sec2_lab_client.py` exercised. This is *not production pairing*.

### Security architecture

- `sec2_lab_http.py` implements an original aiohttp asynchronous transport
  for only five fixed LAB endpoints. Unlike Espressif's Python
  `Transport_HTTP` based on synchronous `HTTPConnection`, this does not
  block HA's event loop and enforces an eight-second request deadline.
  No redirects, proxy environment, generic URLs, other ports, unrelated
  firmware APIs, or persistent cookies are permitted. Binary frame bytes
  preserve the reference client's Latin-1 encoding and the exact verified
  `session=<uint32>` cookie; responses and requests are limited to 4 KiB.
- `sec2_lab_espidf.py` loads the **official** Security2 SRP6a/AES-GCM
  implementation from a local compatible ESP-IDF checkout, only after
  explicit opt-in. No cryptography code is silently downloaded,
  installed, or substituted with Security0/Security1. An absent or
  incomplete checkout and global Python module conflicts fail closed.
  It requires an ESP-IDF version of the client accepting
  `sec_patch_ver`, as used by the already-tested standalone client.
  A compatible ESP-IDF source and its protobuf/cryptography dependencies
  must exist in the Home Assistant Python environment for a real test.
- `sec2_lab_ws.py` registers admin-only LAB readiness and execute
  WebSockets. Actual execution is **disabled by default** unless
  `OMOTE_SEC2_LAB_ENABLE=1` is set in the HA process environment.
  `IDF_PATH` must point to the ESP-IDF source root *as mounted on that
  same HA host/container*, not just a checkout on a separate desktop.
  The requested target must be the registered remote's private LAN
  IPv4 address. There is no user-supplied host or port and only one
  in-flight attempt is accepted per remote.
- The dev23 Overview section shows LAB readiness and a one-shot
  experimental action. It requires a separate explicit browser
  confirmation and the current physically displayed six-digit PIN.
  Enter the PIN only over a trusted HTTPS HA session if possible.
  The PIN is transient and never intentionally logged or returned;
  the firmware's persistent attempt counters still apply. Never retry
  automatically after an SRP failure or expiry.
- The existing `sec2_lab_session.py` still performs the saved HA
  signature frame and verifies the encrypted device software-key
  challenge. It returns only the two public fingerprints and explicit
  `paired=false`, `trusted=false`, `deployment_enabled=false`,
  `ota_enabled=false`. Neither the browser nor a successful lab run
  can save trust, send a configuration transaction, trigger recovery
  or OTA, or change eFuses. The firmware code and stable branches
  have not been modified.

### First installation and acceptance procedure

1. Run the Python offline suites: `test_sec2_lab_session.py`,
   `test_sec2_lab_http.py`, `test_sec2_lab_espidf.py` and
   `test_sec2_lab_ws.py`. Confirm complete CI and read-only
   Profile Studio regression before laboratory activation.
2. Install HACS dev23 from `main`; restart HA. With the feature gate
   unset, LAB readiness must explicitly say **disabled** and the test
   action must remain disabled. Existing dev22 candidate identity
   fingerprint must be unchanged.
3. In an isolated development HA installation or deliberately
   maintained host, install/provide an already-audited matching official
   ESP-IDF source checkout plus its Python provisioning prerequisites.
   Set `IDF_PATH` and `OMOTE_SEC2_LAB_ENABLE=1` in the **HA process**
   environment, then restart HA. Do not set these in a desktop shell
   and assume they automatically reach an HA container.
4. In OMOTE Manager, select the registered Waveshare, click
   **Check LAB prerequisites**, and confirm the explicit LAB action
   becomes available. This checks the host opt-in and source-path
   configuration, *not* full dependency compatibility; a missing or
   mismatched Espressif client must still fail before opening the
   remote Security2 session.
5. Only after the firmware lab image and a verified USB backup,
   physically navigate on Waveshare to Settings > SEC2 encrypted LAB
   test > Start lab. The firmware opens port 18082 briefly and shows
   a fresh local six-digit code. In HACS click **Run encrypted LAB test**
   once, accept the laboratory warning and enter that code. Compare
   the exact candidate HA SHA-256 public fingerprint shown by HACS
   with the four rows on the remote. Try Review OK / Reject in
   deliberately separate windows if needed, respecting the NVS
   message budget and physical rearm policy.
6. Regardless of success, verify HACS reports **NOT PAIRED**,
   normal read-only firmware capability status remains unchanged,
   and no config/deployment/OTA permission appears. Stop on a
   mismatch or failed stage; do not blindly retry or erase NVS.
   This is still *volatile lab evidence*, not a live trusted enrollment.

**Acceptance remains pending:** The new HACS-originated live session,
correct Home Assistant 2024.9.1 dependency isolation, touchscreen
fingerprint review, and device test are not yet hardware-confirmed.
The existing user-confirmed 8/8 offline adapter tests predate dev23;
new suites require their own test execution. No eFuse or firmware
update is needed simply to install this HACS work. Permanent trust,
protected device private key, PIN-free reconnect and deployment are
still blocked by firmware issue #1 / HACS issue #6.


## 2026-11-06 — dev23 bundled Security2 (supersedes earlier IDF_PATH guidance)

The laboratory client is now packaged directly with the HACS integration.
The earlier dev23 instructions requiring a full ESP-IDF source checkout,
`IDF_PATH` on Home Assistant, or an IDF installation in the
`/srv/homeassistant125` virtual environment are **obsolete**.

The integration vendors only Espressif's Apache-2.0 Python Security2
SRP6a/AES-GCM and compact protocomm protobuf modules from **ESP-IDF
v5.4.2** in `custom_components/omote_manager/sec2_vendor/`.
`LICENSE` and `NOTICE.md` preserve license terms, exact upstream
file provenance, and a list of adapted imports. The provisioning
transport is not vendored: HACS uses its existing bounded async
`sec2_lab_http.py` on port 18082 instead.

All vendored modules use private relative imports. The generated
protobuf modules use a private DescriptorPool rather than injecting
generic `session.proto` etc. into Home Assistant's process-global
protobuf pool. They reuse the installed `cryptography` and
`protobuf` packages. The loader refuses incompatible versions or
missing dependencies, with no Security0/1 downgrade, no runtime
downloads and no `sys.path` changes. The HA 2024.9.1 reported
environment (Python 3.12.5, cryptography 43.0.0, protobuf 4.25.4)
matches the intended laboratory dependency range; actual runtime
imports and hardware interoperability still require testing.

### Opt-in for the user's supervisord-managed HA Core

The user's Core 2024.9.1 process runs from
`/srv/homeassistant125/bin/hass` via
`/etc/supervisor/conf.d/hass.conf`, as user `homeassistant`.
**Do not use shell syntax** for Supervisor's `environment` option.
Only AFTER offline tests, HACS restart/regression checks and an
explicit decision to perform one physical lab attempt, add this
single setting **inside the existing [program:hass] section**:

```ini
environment=OMOTE_SEC2_LAB_ENABLE="1"
```

No `IDF_PATH` variable and no ESP-IDF installation is required.
Apply Supervisor configuration changes using its managed controls
during a planned HA restart, then confirm the HACS Overview LAB
readiness reports the bundled Security2 client available. The
read-only HACS functionality stays accessible even when LAB is OFF.

The laboratory run still needs an intentionally flashed experimental
Waveshare lab image, a locally tapped Start lab, a fresh on-screen
six-digit PIN, and knowledge of the persistent NVS attempt quota.
After testing, remove the environment setting and restart HA to
disable the experimental test. Do not migrate this capability into
production pairing or deployment without separate protocol/key
protection and hardware approval.

### Required offline tests

The existing 8/8 dev22 adapter suite was physically user-executed on
the developer's Python 3.12 venv. The new bundled-source and
Home-Assistant-integrated path have **not yet passed user or CI
acceptance**. Run:

```bash
python -m pip install cryptography==43.0.1 aiohttp==3.10.5 protobuf==4.25.4 voluptuous==0.15.2
python -m unittest discover -s tests -p 'test_sec2_lab*.py' -v
```

Tests cover the newly vendored protobuf wire structures, SRP command
generation, descriptor isolation, dependency-fail-closed behavior,
async transport strictness and WebSocket admin/default-off gates. Do
not open the Waveshare's lab window until these tests pass and a
matching lab firmware/USB restore checkpoint is confirmed.
