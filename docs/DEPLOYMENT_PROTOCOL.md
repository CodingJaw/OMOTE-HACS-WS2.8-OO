# OMOTE Config v2 — HACS single-active handoff (draft)

**Status: NOT IMPLEMENTED OR DEPLOYABLE.** This document describes the
integration contract to finalize with the firmware team. It is not a working
network API. No Home Assistant command currently sends firmware writes.

**Authoritative firmware design:**
[CONFIG_V2_SINGLE_ACTIVE_DESIGN.md](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO/blob/feature/config-v2-transactional/docs/CONFIG_V2_SINGLE_ACTIVE_DESIGN.md)

**Tracking:** [HACS issue #2](https://github.com/CodingJaw/OMOTE-HACS-WS2.8-OO/issues/2),
[firmware issue #1](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO/issues/1).

## Current user-approved decisions

- Exactly **one active configuration** on the Waveshare. No A/B
  generations, automatic rollback, previous/pending generation, trial boot
  or remote rollback endpoint.
- Home Assistant retains the **latest explicitly reviewed JSON draft**
  separately from a bounded history of **three imported backups**.
- Recovery is **manual only**: alert the HA administrator and let them
  select a saved reviewed copy, but never automatically upload or resend.
- Every deployment and recovery resend requires an authenticated HA
  administrator **and a new physical touchscreen approval on the target**.
- Keep Profile Studio's review, approval and eventual deployment controls
  together. Discovery uses mDNS with manual IP/hostname fallback.
- HACS deploy remains server-side disabled until the encrypted firmware
  protocol, atomic single-pointer activation and physical recovery testing
  pass. No changes to `waveshare28v2-port`.

## Implemented now (feature branch, read-only)

1. Legacy v1 and v2-preview capability negotiation. Retired A/B fields are
   accepted when present but never required or shown as functional rollback.
2. Read-only LittleFS status normalizes `storage_model=single-active`,
   `config_mode=legacy|active|recovery`, `recovery_required`,
   `recovery_reason`, `active_revision_sha256`, and capacity counters.
   Malformed or inconsistent states fail closed. Firmware flags never enable
   remote mutations.
3. The Overview panel displays the active mode and recovery warning.
   Profile Studio offers an explicit read-only recovery check. No automatic
   background action or network write occurs.
4. Profile Studio can retain one reviewed, validated JSON snapshot per remote
   in HA private storage; backup history remains independent. The reviewed
   snapshot is SHA-256 checked when read, and metadata (not content) is
   returned over the standard workspace WebSocket.
5. The offline ZIP contains `proposed/`, `imported-baseline/`,
   `MANIFEST.json`, and `PORTABLE_INDEX.json`. It is a **JSON-only**
   reference, not a firmware-ready image, not a complete device backup and
   not a deployable firmware manifest. Binary image assets and private
   settings are excluded.

## Draft firmware API contract — NOT OPERATIONAL

All mutation endpoints below require a device-bound encrypted authenticated
session and replay-resistant request identifiers. No secrets in URL query
strings, discovery TXT or unauthenticated status responses.

| Method | Path | Intended behavior |
|---|---|---|
| GET | `/api/config/v2/capabilities` | Public nonsecret version, limits and write-disabled status |
| GET | `/api/config/v2/storage/status` | Read-only storage model, recovery mode, active SHA-256 |
| POST | `/api/config/v2/pair/*` | Physical one-time-code device pairing; contract pending |
| POST | `/api/config/v2/transactions` | Begin device-bound staged transaction against expected active SHA |
| PUT | `/api/config/v2/transactions/{id}/files/{path}` | Bounded, idempotent, checksum-verified chunks |
| POST | `/api/config/v2/transactions/{id}/validate` | Verify complete manifest, all hashes, graph and assets |
| POST | `/api/config/v2/transactions/{id}/commit` | Require new local touchscreen approval and atomically select one manifest |
| GET | `/api/config/v2/transactions/{id}` | Status and safe recovery from uncertain response |
| DELETE | `/api/config/v2/transactions/{id}` | Abort inactive staging |

**No rollback endpoint.** A corrupted active configuration must start a
firmware-owned local recovery UI and retain independent Wi-Fi/provisioning
capability. Only after authenticated reconnection may an administrator
explicitly resend a reviewed configuration through the same staged,
touchscreen-approved transaction flow.

## Security and compatibility requirements

- mDNS MAC/TXT and an IP address are untrusted hints, never pairing identities.
- HACS must pin a verified device identity and reject device swaps, replay,
  stale active SHA, concurrent edits, unapproved touchscreen sessions and
  truncated/oversized payloads.
- DeviceSettings.json, HaSettings.json, NVS Wi-Fi credentials, MQTT/FTP/NTP
  secrets and pairing keys must not enter portable shared profiles. A separate
  opt-in encrypted per-device settings flow is future work.
- JSON-only review packages must never claim complete image dependency
  coverage. Real secure deployment requires exact referenced image assets
  and cross-file validation from firmware.
- HA Core 2024.9.1 compatibility must be preserved. Old preview responses
  with false/empty A/B placeholder fields remain readable, but never
  activate rollback UI.
- Keep admin-only WebSocket authorization, bounded responses and strict
  optimistic workspace revision checks.

## Hardware acceptance gate (before enabling writes)

- Verify full 16 MiB flash backup integrity and safe recovery/restore.
- Confirm runtime loads only the selected immutable snapshot; malformed
  graphs enter independent recovery instead of crashing the UI.
- Verify real PNG/JPEG/image decoding from content-addressed objects.
- Test USB power cuts during staging and active-pointer commit.
- Test HA disconnect/reconnect and manual secure resend from recovery.
- Verify standalone touchscreen/UI responsiveness and no silent writes.
- Complete pairing, replay and touchscreen approval adversarial tests.

**Deployment kill switch remains OFF until every gate is demonstrated.**
