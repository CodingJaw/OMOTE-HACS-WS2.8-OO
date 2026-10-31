# Architecture and firmware compatibility

**Phase 1 (this branch):** HACS-installable Home Assistant integration with manual endpoint setup, status polling, configuration inventory and read-only API transport.

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
