# HACS single-active integration plan (feature branch)

**Design authority:** [Firmware single-active design](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO/blob/feature/config-v2-transactional/docs/CONFIG_V2_SINGLE_ACTIVE_DESIGN.md),
[HACS issue #2](https://github.com/CodingJaw/OMOTE-HACS-WS2.8-OO/issues/2).
All older A/B, previous-generation, /rollback and automatic rollback work is
cancelled. The known-good firmware and HACS main branch are unchanged.

## Already possible with no firmware writes

1. Import and edit safe OMOTE JSON into an isolated HA draft.
2. Validate scene/page/command references, supported widget types, duplicate
   scene names/paths and syntax; warn that image binaries are not in the
   HA JSON subset.
3. Run a point-in-time live drift review and explicitly retain a locally
   validated JSON snapshot **independently** of the editable draft.
4. Maintain the existing separate three-backup history and restore either
   a retained review or a backup to the HA draft only, with overwrite
   confirmation, optimistic revision checks and integrity validation.
5. Export a no-deploy single-active archive with `proposed/`, `baseline/`,
   review metadata and, for truly JSON-only configs, a firmware-canonical
   manifest preview with per-file byte lengths and SHA-256.
6. Inspect read-only firmware capabilities, LittleFS capacity, active revision,
   legacy/active/recovery mode and recovery reason; older v1 devices work.

## Strictly blocked until the firmware contract is finalized

- Encrypted device-bound one-time-code pairing, pinned peer identity and
  revocation in HA protected storage.
- Authenticated begin/chunk/validate/commit/abort/status operations with
  device-generated IDs, drift/current revision preconditions, idempotent
  retries and firm size/space quotas.
- HA administrator confirmation AND a fresh target physical touchscreen
  confirmation for each and every deployment, including a recovery resend.
- A complete image/asset reader and binary digests; portable settings
  deliberately exclude private DeviceSettings/HaSettings, credentials, and
  Wi-Fi NVS/pairing secrets.
- Independent firmware recovery screen and persistent network reconnection
  verified on actual Waveshare hardware. A network outage itself does not
  trigger recovery or automatic resend.
- Real power-interruption, flash restore and invalid configuration testing.
  The firmware must never overwrite root files incrementally during an upload.

## Release gate

The server-side deploy permission remains hard-disabled. No mDNS TXT field,
capability flag, preview build label or merely valid ZIP can enable it. The
upcoming HACS UI should offer manual recovery review only after a secure
firmware contract, physical acceptance tests and explicit release approval.

## Shared-page edit safety

`editor_model.scene_detail` now returns `shared_with_scenes` per page:
a bounded, path/name-only list of other scenes that reuse that page JSON.
Scene tab labels remain scene-local. Profile Studio displays a warning
and requires confirmation before changing widget text, command mappings,
physical button assignments, or visual widget positions on a shared page.
These are local HA draft edits only; no physical remote commands are sent.
