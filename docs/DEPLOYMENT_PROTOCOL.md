# Historical OMOTE A/B deployment proposal — SUPERSEDED

**This document is historical and is NOT the current implementation contract.**
On November 1, 2026 the user cancelled managed A/B generations,
previous-revision rollback and automatic rollback. The authoritative design is
[firmware CONFIG_V2_SINGLE_ACTIVE_DESIGN.md](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO/blob/feature/config-v2-transactional/docs/CONFIG_V2_SINGLE_ACTIVE_DESIGN.md);
see also [this HACS branch's current integration plan](SINGLE_ACTIVE_HACS.md).
Never implement any A/B or /rollback endpoint based on the text below.
All network firmware writes remain disabled until the authenticated
single-active transaction contract is frozen and tested.

## Archived proposal (superseded)

**Firmware tracking issue:** [CodingJaw/OMOTE-Firmware-WS2.8-OO #1](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO/issues/1).

**Status:** Design proposal only; implementation requires firmware approval and
hardware testing. Nothing in this document authorizes writes to running devices.

## Current firmware limitations

The Waveshare port at
\`Platformio/lib/esp32HalImpl/wifiHandler/config_http.cpp\` currently exposes:

- \`POST /api/fs/write?path=...\` and \`PUT /api/fs/write?path=...\`, which
  truncate and write the active LittleFS path directly;
- \`POST /api/fs/delete?path=...\`, which removes the active path directly;
- \`GET /api/fs/tree\`, \`/api/fs/stat\`, \`/api/fs/read/raw\` and
  \`/api/fs/read/chunk\` for read-only inspection;
- \`POST /api/device/reboot\` and \`/api/device/sync-mode\` for reboot and
  editor synchronization.

There is currently no authentication on the write endpoints, no multi-file
transaction, no active/previous generation, no atomic commit marker, no
rollback endpoint and no confirmed post-reboot health acknowledgment. The
current API has permissive cross-origin response headers. Do not expose
port 80 to the Internet or untrusted networks. HACS must not invoke any
configuration-writing endpoint until a secure implementation is approved.

## Proposed API version

Keep \`omote-config-v1\` read-only support in HACS. Add a capability-negotiated
\`omote-config-v2\` transaction interface without changing v1 file-read behavior.
A v2 version string alone must not enable deployment; all required capabilities
must be positively verified.

\`GET /api/config/v2/capabilities\` (auth requirement depends on privacy policy):
\`device_id\`, \`firmware_build\`, \`api_version\`, \`auth_mode\`, \`max_file_bytes\`,
\`max_transaction_bytes\`, \`available_staging_bytes\`,
\`active_revision_sha256\`, \`previous_revision_sha256\`,
\`transaction_support\`, \`rollback_support\`,
\`write_protection_enabled\`.

All state mutations require authenticated requests bound to the particular
device and to a server-generated unpredictable nonce. A local pairing flow
with physical confirmation on the device is preferred. Authentication must
protect against replay and credential theft; do not place bearer tokens or
pairing secrets in URLs or send sensitive tokens unprotected over plaintext
HTTP. Require an authenticated transport (e.g. TLS with certificate pinning or
an equivalently reviewed secure channel). CORS must not grant anonymous
cross-origin configuration writes. Rate-limit authentication failures.

## Transaction lifecycle

1. **Preflight** (read-only): Home Assistant computes SHA-256 over the exact
   bytes of its saved baseline and proposed files, validates JSON-with-comments
   and cross-file references, queries the current active firmware revision and
   confirms that the remote still matches the imported baseline. Reject stale
   revisions, missing capacity, unknown file paths and unsupported firmware.
2. **Begin**:
   \`POST /api/config/v2/transactions\` with unique request ID, target
   manifest digest and \`if_active_revision_sha256\`. The device refuses if a
   transaction is active, the baseline differs or space is insufficient.
   Return a short-lived transaction identifier and staging limits.
3. **Stage**:
   \`PUT /api/config/v2/transactions/{id}/files/{safe_path}\` with verified
   content-range/offset and per-file SHA-256, streaming in small chunks.
   Staging must never truncate an active file. No traversal, credential or
   unrecognized file path is allowed. Retries must be idempotent and detect
   changed bytes at an offset.
4. **Validate**:
   \`POST /api/config/v2/transactions/{id}/validate\`. Check every staged
   length and digest, parse all JSON, resolve scene/page/command references,
   confirm storage quotas and calculate the staged generation digest.
5. **Commit**:
   \`POST /api/config/v2/transactions/{id}/commit\` with precondition hashes
   and an explicit confirmation token. The firmware activates the entire
   validated generation as one recoverable operation, not a sequence of
   direct writes. Prefer A/B generation storage plus a crash-safe active
   manifest/pointer, or a carefully reviewed journaled alternative.
6. **Verify health**:
   A reboot/reload must report the activated digest, successful scene loading
   and a stable API response. The prior generation remains available. If
   a boot fails, CRC/hash mismatches, filesystem corruption or a watchdog
   reset occurs, automatically recover the known-good generation.
7. **Acknowledge**:
   Home Assistant confirms the new digest, marks the previous revision as
   rollback-ready and saves the deployment result. If the status is unknown,
   report uncertainty rather than automatically retrying a commit.
8. **Rollback**:
   \`POST /api/config/v2/rollback\` with required authentication, expected
   current digest and explicit user confirmation. Restore the prior coherent
   generation and verify its new active digest.
9. **Abort**:
   \`DELETE /api/config/v2/transactions/{id}\` cleans temporary data without
   altering active JSON. Expired transactions must be garbage-collected.

A single-file rename is not an atomic multi-file transaction. If the current
firmware loads JSON from fixed root paths, the implementation must either
adopt an A/B-aware path resolver for all JSON load sites or provide a
crash-recoverable journal that prevents readers from seeing a partially
updated scene/page/command graph. Account for existing LittleFS root layout
and non-JSON assets before changing load paths.

## Required safety properties

- The device remains usable without Home Assistant, cloud access or Wi-Fi.
- The default system must reject unauthenticated writes. Legacy \`/api/fs/write\`
  and \`/api/fs/delete\` should be disabled or explicitly protected in normal
  operation; preserve a documented physically authorized recovery path.
- No automatic deployments. The HA user must choose the target remote, inspect
  a colored diff and backup, pass validation/drift checks and confirm deploy.
- A transaction is bound to one device ID, firmware build and base revision.
  Concurrent HACS users must not silently overwrite each other.
- Account for flash endurance, maximum JSON size, free space, PSRAM/heap limits,
  power loss during staging/commit/rollback and interrupted Wi-Fi.
- Never stage, display or log \`HaSettings.json\`, MQTT credentials, or other
  sensitive files through the initial HACS deployment surface.
- Keep a known-good fallback and explicit recovery instructions for corrupted
  LittleFS, repeated watchdog resets or failed firmware updates.
- Avoid logging secrets, raw authentication headers or complete JSON payloads.
- Firmware may reject configurations unsupported by its build even when HA
  structural validation succeeded. Do not equate static validation with
  hardware correctness.

## Integration gating

HACS release v0.1.0-dev10 creates a **download-only** ZIP containing
\`proposed/\`, \`rollback/\` and \`MANIFEST.json\`. The ZIP is not uploaded.
Future enabling criteria:

- A v2 firmware implementation and tests exist on a separate approved
  firmware branch, with demonstrated interrupted-write and rollback recovery.
- HACS integration tests cover auth denial, precondition conflicts, crash
  recovery, staging cancellation, verification timeouts and rollback.
- A distinct opt-in UI path requires administrator approval per deployment.
- A hard kill-switch leaves direct deployment off for unsupported devices.
- Firmware modifications must not be merged into the working Waveshare
  branch until tested and explicitly approved by the user.

## Hardware acceptance checklist

Test on a Waveshare ESP32-S3-Touch-LCD-2.8 V2 with current working firmware:

- A/B storage fits in the configured flash partition under realistic file size.
- Kill power during each staging, validation, commit and rollback phase:
  active scenes are intact or restored automatically.
- Simulate Wi-Fi dropout, duplicate requests, hostile paths, bogus auth and
  wrong hashes; confirm no active file is partially changed.
- Verify scene switch, LVGL touchscreen, physical keys and key wake behavior
  after reload and rollback.
- Verify that a new remote can be added later and inherits the intended
  reusable scene profiles only with explicit assignment.
