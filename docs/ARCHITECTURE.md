# Architecture and firmware compatibility

**Phase 1 (this branch):** HACS-installable integration with manual endpoint setup, status polling, configuration inventory, read-only API transport, and an admin-only sidebar panel using Home Assistant 2024.9.1's `panel_custom` API. The panel uses admin-authenticated Home Assistant WebSocket commands to preview eligible JSON files and initiate private configuration backups; firmware writes remain disabled.

Compatibility baseline: Home Assistant Core 2024.9.1, Frontend 20240906.0, HACS integration 2.0.5 / frontend 20250128065759.

Source firmware: CodingJaw/OMOTE-Firmware-WS2.8-OO, branch waveshare28v2-port.

## Confirmed existing endpoints

- GET /api/status (api: omote-config-v1)
- GET /api/fs/tree (JSON config inventory)
- GET /api/fs/stat?path=...
- GET /api/fs/read/raw?path=... (stream file)
- GET /api/fs/read/chunk?path=... (chunked read for large files)
- GET /api/fs/read?path=... (legacy JSON wrapper)
- POST or PUT /api/fs/write?path=... (direct overwrite)
- POST /api/fs/delete?path=...
- GET /api/device/settings
- POST /api/device/settings
- GET /api/device/settings/schema
- GET/POST /api/device/sync-mode
- POST /api/device/reboot
- POST /api/ir/learn/start and /stop; GET /poll

The firmware's fs/write handler opens with std::ios::trunc. It does not validate or atomically activate a complete configuration. The server currently uses permissive CORS and does not authenticate configuration calls. Accordingly, **the initial integration makes no writes**.

## Supported configuration representations

Scenes.json references Scenes/*.json. Scene files reference Pages/*.json and Commands/*.json; pages reference command files. Commands include Mode IR and MQTT and may include comments. Home Assistant should preserve original JSON file semantics, not convert them to a new runtime format. Shared templates / rooms are **manager-side concepts**, not extra firmware objects.

## Recommended firmware additions (NOT implemented)

1. Pairing/authenticated configuration endpoints; do not expose the existing write API on untrusted networks.
2. Device ID, firmware capabilities and persistent configuration revision/hash.
3. Transactional multi-file validation, stage, commit, and rollback with verification.
4. Notification of changed configuration revision.

Firmware code must not be changed without separate approval. The HACS integration remains independent of network IR router and USB HID firmware.

## HA-only Profile Studio (0.1.0-dev4)

The `WorkspaceStore` maintains named hierarchical locations, reusable scene templates and per-remote draft file snapshots in Home Assistant private storage, using monotonically increasing revisions for optimistic concurrency. Imports and templates exclude device settings, HA credentials and secret files. A shared template is a byte-exact source scene plus recursively referenced pages and command files; its Scene index entry is stored separately to avoid overwriting a destination's entire Scenes.json file. Templates copy only into a second remote's HA draft and reject conflicting file paths. Command editing updates the original OMOTE Mode / Protocol / Data fields while retaining unknown keys. OMOTE JSON with line/block comments is supported for reading and validation; editing one command file normalizes its comments. Validation checks parse errors, Scenes.json references, scene page references, page command file references and command field semantics, but cannot certify actual IR/HA hardware operation. Firmware deployment remains entirely disabled.

The HA WebSocket workspace endpoints require HA administrator authorization and are not exposed directly to the LAN. No changes to the firmware repository are required for this milestone.

## Complete-read transport and atomic draft import (v0.1.0-dev6)

Prior versions used a single `aiohttp.StreamReader.read(65537)`, which can return a partial TCP response before EOF. This caused truncated valid firmware JSON files to appear as syntax errors. Files now use `/api/fs/stat` to verify the expected byte count, consume raw responses to EOF via `iter_chunked`, and use `/api/fs/read/chunk` with explicit byte offsets and header validation as a fallback. JSON syntax and object type are checked before replacing a Home Assistant draft. All file transfers are bounded to 64 KiB per file and 512 KiB total. A firmware-provided content hash or atomic read snapshot is still desirable for detecting same-size in-place changes. The code does not write to the device.

## Scene/page/widget/key editor (v0.1.0-dev7)

Firmware key names and event types were verified against `Platformio/lib/HAL/Hardware/KeyPressAbstract.hpp` in the Waveshare source. Scene index `SceneName`, `BindToKey`, and `PressType` are edited in Scenes.json; `ScreenName` and scene-local `PageName`/`ShortName` are edited in Scenes/scene files. Touchscreen Button/Label captions and existing Button/ColorButtons/NumberPad command entries, along with physical key `ButtonMaps`, are edited in Pages/page files (which can be shared by scenes). Only firmware-supported keys/events and commands that exist in the referenced command file after applying scene CommandPrefix are permitted; the validator must still be run to detect cross-scene effects.

Each mutation is one revision-checked HA Store write. Changed files are exposed as bounded unified diffs against their original imported text, with per-file revert; new template-added files can be removed from the HA draft. No HTTP writes or device firmware operations occur.

## Visual page layout (v0.1.0-dev8)

The Waveshare board driver defines a 240×320 portrait ST7789 display. The editor reports existing page widget placement fields from the firmware JSON and provides an approximate interactive browser preview. The firmware's `JsonPage::applyWidgetLayout` uses percentage-based `SizeXY` and `PosX`/`PosY`, optional `HeightPct`, and alignment to earlier widgets. Importantly, Image widgets use `SizeXYinPixels`, whereas Label/Title widgets do not support free XY placement. The model enforces these distinctions and validates 0–100 percentage ranges and backward-only alignment. The preview uses simplified flow and size estimates; actual LVGL layout is not simulated. Dragging updates inspector inputs without persisting changes until the explicit Save button invokes an administrator-only websocket command, which changes a revision-checked HA draft and never accesses device-write endpoints.

## Color-coded comparison and read-only deployment preflight (v0.1.0-dev9)

The unified diff viewer classifies lines as added, removed, unchanged context, file headers or hunk markers and applies theme-aware CSS colors. It uses `textContent` and DOM nodes rather than `innerHTML` for untrusted file text. Unchanged context can be hidden without re-fetching the diff.

`review_model.make_review` builds a bounded, content-free change manifest containing raw-byte SHA-256 hashes and size deltas. The administrator-only `omote_manager/editor/preflight` WebSocket command can optionally read the latest remote API inventory and files corresponding to changed draft paths, verifying those files still match their imported baseline. Added paths already existing remotely and same-length but content-different changes are detected; edits made while the check runs mark the review stale. Only changed paths are compared, and the read-only check cannot prevent races after completion. No firmware HTTP write methods are introduced; deployment remains explicitly blocked pending authenticated transactions and rollback support.

## Download-only deployment/recovery kit (v0.1.0-dev10)

`release_model.build_deployment_kit` uses a revision/hash-bound immutable workspace snapshot to build a bounded ZIP archive containing the complete whitelisted OMOTE JSON proposal and its original imported baseline in separate folders. The archived `MANIFEST.json` contains byte-level SHA-256 hashes, changed paths, file counts and an explicit "not deployable by current integration" indicator. Sensitive settings and non-JSON files remain excluded. The archive is returned only through an administrator-only Home Assistant WebSocket command; the browser creates the local ZIP download from base64 without introducing a public HTTP endpoint. The firmware is never modified.

With live verification selected, the integration rechecks the remote API, inventory and affected file contents before export and refuses known drift/conflicts. It rejects changes to the workspace revision or draft hash while packaging. If the user chooses offline review, the archive is prominently marked `offline_unverified`. The current API does not furnish an atomic remote snapshot or transaction, so even live verification cannot prevent subsequent changes.

The future protocol proposal, including device pairing/authentication, multi-file transactional commit, power-failure recovery and rollback, is documented in `docs/DEPLOYMENT_PROTOCOL.md`. No firmware updates are part of v0.1.0-dev10.

## Verified backup history and local-draft recovery (v0.1.0-dev11)

The original `backup_configuration` Home Assistant service now delegates to `OmoteBackupHistory.capture`, preserving the existing storage key and SHA-256 format and retaining the most recent three snapshots. Each remote file is read completely through `OmoteApi.read_file(...verify_json=True)`, all paths are allowlisted, and each snapshot is validated and hashed before replacing history. Corrupt previous snapshots are marked as damaged instead of being exposed as arbitrary JSON content through the sidebar.

The administrator-only `omote_manager/backups/list` WebSocket command exposes metadata only. `omote_manager/backups/load-to-draft` requires the exact snapshot index, SHA-256, workspace revision and explicit `replace` flag; it verifies both integrity and the registered remote entry before calling `WorkspaceStore.async_import`. This permits recovery of an earlier HA draft while the device is offline but does not issue any firmware write, reboot or restore API request. The UI confirms that restoring a draft discards unsent local edits and that the device remains unchanged.

## Optional v2 read-only capability probe (v0.1.0-dev12)

`OmoteApi.capabilities` makes only a bounded, non-redirecting GET request to `/api/config/v2/capabilities`. HTTP 404 is treated as legacy-v1; malformed or oversized responses fail closed. The independent `capability_model` validates exact boolean types and bounded string/limit/hash fields and strips device identity and active revision identifiers from the public sidebar summary. Its `deployment_enabled` flag is hardcoded false regardless of what a device advertises. This prevents insecure or preview builds from enabling deployment based on a version string or self-reported flags.

The administrator-only `omote_manager/capabilities` websocket endpoint uses an already-configured remote's API object and returns normalized metadata without any secret fields. Its UI is advisory, not an authentication or transaction mechanism. Compatible with legacy v1 firmware and the `omote-config-v2-preview` branch without requiring firmware changes.

## Explicitly confirmed zeroconf discovery (v0.1.0-dev13)

Manifest `zeroconf: ["_omote._tcp.local."]` with `zeroconf` dependency delegates mDNS watching to Home Assistant's built-in discovery service. Config flow requires a stable lowercase efuse MAC TXT hint, the expected protocol/model marker and a private IPv4 address, verifies `/api/status`, then presents `zeroconf_confirm` without creating an entry automatically. Manual host/port setup is retained and duplicate hosts or `hostname.local` entries abort. Known discovery IDs do not trigger unauthenticated silent IP changes. Discovery identifiers are explicitly untrusted and do not authorize pairing, transactions or firmware writes.

The firmware service is announced only in the isolated config-v2 feature branch. A separate host-testable firmware state machine models the per-deployment physical touchscreen approval gate, but it is not connected to network commits. The final authenticated protocol and Waveshare hardware power-loss tests remain blockers for enabling deployment. Existing Home Assistant Core 2024.9.1 setup and storage formats are unchanged.
