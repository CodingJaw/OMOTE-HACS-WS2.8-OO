# OMOTE Manager — Home Assistant integration

A HACS custom integration for [OMOTE object-oriented firmware](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO), including the Waveshare ESP32-S3 Touch LCD 2.8 V2 port.

**Development build 0.1.0-dev2 — read-only; no firmware writes.**

**2024.9.1 setup fix:** The config-flow form now uses serializable built-in field types and validates hostnames after submission. Tests exercise the HA 2024.9.1 form serializer.

## Compatibility baseline

- Home Assistant Core **2024.9.1**
- Home Assistant Frontend **20240906.0**
- HACS Integration **2.0.5**
- HACS Frontend **20250128065759**
- OMOTE API **omote-config-v1**, on TCP 80 by default

These are targets; live installation against the specified versions remains to be tested.

## Installation (development branch)

1. In HACS, add this repository as a **custom repository** of type **Integration**.
2. Select the **develop** branch/version if your HACS UI offers it. This is not a published stable release.
3. Install OMOTE Manager and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → OMOTE Manager**.
5. Enter the Waveshare OMOTE IP or hostname, and API port (80).

Your device must be reachable from Home Assistant's network and must report `"api": "omote-config-v1"` from `/api/status`. Multiple remotes are supported as separate configuration entries.

### Entities

- Online (connectivity)
- Configuration files (count)
- Configuration API (version)

### Actions (Developer Tools → Actions/Services)

- `omote_manager.refresh`: refresh status and file inventory by integration entry ID.
- `omote_manager.backup_configuration`: save a snapshot of eligible configuration JSON files to Home Assistant's private `.storage/omote_manager.backups_<entry_id>` store. Retains up to three snapshots; excludes credentials and `DeviceSettings.json`. Each file limited to 64 KiB; snapshot limited to 512 KiB. **This is not a complete firmware backup.**

The integration can read the live device settings and schema through its API client, but a settings editor is not part of this first development build.

## Security

The current firmware's configuration HTTP interface uses **unauthenticated HTTP** and permissive CORS. Do not expose it to the Internet or untrusted LAN clients. This integration deliberately exposes **no write, delete, or reboot actions** while the firmware lacks authenticated, transactional deployment.

## Planned milestones

1. Read-only monitoring and backups (this development build).
2. Shared profiles, named locations, command editing and draft validation.
3. Firmware-authenticated, atomic stage/commit/rollback; only then enable explicit deploy.
4. Graphical remote layout editor and optional OTA support.

See [architecture and requested firmware extensions](docs/ARCHITECTURE.md).

## Project repositories

- HACS development: [CodingJaw/OMOTE-HACS-WS2.8-OO](https://github.com/CodingJaw/OMOTE-HACS-WS2.8-OO)
- Firmware (unchanged): [CodingJaw/OMOTE-Firmware-WS2.8-OO](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO)
