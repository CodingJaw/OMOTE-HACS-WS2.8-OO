# OMOTE Manager — Home Assistant integration

A HACS custom integration for [OMOTE object-oriented firmware](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO), including the Waveshare ESP32-S3 Touch LCD 2.8 V2 port.

**Development build 0.1.0-dev6 — Home Assistant draft editing; no firmware writes.**

**2024.9.1 setup fix:** The config-flow form now uses serializable built-in field types and validates hostnames after submission. Tests exercise the HA 2024.9.1 form serializer.

## Compatibility baseline

- Home Assistant Core **2024.9.1**
- Home Assistant Frontend **20240906.0**
- HACS Integration **2.0.5**
- HACS Frontend **20250128065759**
- OMOTE API **omote-config-v1**, on TCP 80 by default

These are targets; live installation against the specified versions remains to be tested.

## Installation (available on default branch)

1. In HACS, add this repository as a **custom repository** of type **Integration**.
2. Download OMOTE Manager from the default `main` branch (development build; not a stable release).
3. Install OMOTE Manager and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → OMOTE Manager**.
5. Enter the Waveshare OMOTE IP or hostname, and API port (80).

Your device must be reachable from Home Assistant's network and must report `"api": "omote-config-v1"` from `/api/status`. Multiple remotes are supported as separate configuration entries.

### Sidebar management panel

After restarting Home Assistant, the **OMOTE Manager** sidebar entry opens an admin-only management panel. Use the **Profile Studio** navigation button near the top of the panel to jump to its configuration workspace; the panel displays an explicit loading or error message if the editor cannot initialize. It displays each registered remote's connectivity, API version, and the inventory of OMOTE configuration JSON files grouped under Scenes, Pages, Commands, Devices, and Actions. Click a file for a read-only preview. The Backup JSON button saves a credential-excluding snapshot in Home Assistant storage; Refresh queries the remote again.

The panel is implemented using the `panel_custom` and WebSocket APIs available in Home Assistant 2024.9.1. Static resources are served by the integration; no external scripts or cloud services are used.

### Profile Studio (local drafts)

The sidebar now contains **Profile Studio**, an authenticated, admin-only workspace:

1. Select an OMOTE remote and click **Import remote JSON**. It reads only approved scene, page, command, device, and action files, excluding known settings and credentials.
2. Create named **locations** (Home, Living Room, Bedroom) and child locations.
3. Save a **shared scene template**, including referenced pages and commands, into HA's private storage; copy it into another remote's **local draft**. Existing files with different contents are never overwritten.
4. Choose a `Commands/*.json` file, select an IR or MQTT command, edit its protocol and data fields, then **Save command in draft**.
5. Click **Validate draft** to check JSON syntax, OMOTE scene/page/command references and command fields.

Edits remain in `.storage/omote_manager.workspace` on the Home Assistant host across restarts. Original files are retained alongside the draft to detect local modifications. The editor normalizes the modified command file's formatting and drops comments *in that edited file only*; all other imported JSON text is preserved.

**Firmware deployment is intentionally disabled.** Current OMOTE configuration writes are unauthenticated and non-transactional. The integration does not overwrite live files, reboot the device, or expose OTA updates. Template application affects only HA drafts. Profiles are extracted from existing OMOTE Scene objects; we do not invent incompatible firmware object formats.

The original live file browser remains read-only. Future milestones will add safe deployment and the touchscreen page layout editor.

### Entities

- Online (connectivity)
- Configuration files (count)
- Configuration API (version)

### Actions (Developer Tools → Actions/Services)

- `omote_manager.refresh`: refresh status and file inventory by integration entry ID.
- `omote_manager.backup_configuration`: save a snapshot of eligible configuration JSON files to Home Assistant's private `.storage/omote_manager.backups_<entry_id>` store. Retains up to three snapshots; excludes credentials and `DeviceSettings.json`. Each file limited to 64 KiB; snapshot limited to 512 KiB. **This is not a complete firmware backup.**

The integration can read the live device settings and schema through its API client; editing settings and commands is planned for a future build.

## Security

The current firmware's configuration HTTP interface uses **unauthenticated HTTP** and permissive CORS. Do not expose it to the Internet or untrusted LAN clients. This integration deliberately exposes **no write, delete, or reboot actions** while the firmware lacks authenticated, transactional deployment.

### Important: complete-file import fix (v0.1.0-dev6)

Earlier versions accidentally treated one `aiohttp` stream read as a complete response. On ESP32 this could import partial JSON and produce many false syntax errors. This release drains the entire response, compares the number of bytes with `/api/fs/stat`, and falls back to verified offset-based chunked reads if needed. Before replacing an existing draft, every imported file is syntactically validated (including OMOTE's JSON comments). A failed import keeps the previous draft unchanged.

If you previously imported a corrupt draft, select the remote and click **Import remote JSON** again, accepting the local-draft replacement prompt. This replaces the HOME ASSISTANT draft only. Then run **Validate draft**. If it still reports errors, check the newly reported details; they may be genuine missing command references or files that differ from the firmware repository.

### If the editor is missing after updating

Home Assistant's browser can retain a previously registered JavaScript custom element even after the server is upgraded. This release uses a new versioned element tag to avoid stale constructors. After installing v0.1.0-dev6, restart Home Assistant and perform a **hard browser reload** (Ctrl+Shift+R). If Profile Studio does not appear, use the top **Profile Studio** button; its loading/error state should be visible, and the browser console will identify JavaScript failures.

## Planned milestones

1. Read-only monitoring and backups (this development build).
2. Shared profiles, named locations, command editing and draft validation.
3. Firmware-authenticated, atomic stage/commit/rollback; only then enable explicit deploy.
4. Graphical remote layout editor and optional OTA support.

See [architecture and requested firmware extensions](docs/ARCHITECTURE.md).

## Project repositories

- HACS development: [CodingJaw/OMOTE-HACS-WS2.8-OO](https://github.com/CodingJaw/OMOTE-HACS-WS2.8-OO)
- Firmware (unchanged): [CodingJaw/OMOTE-Firmware-WS2.8-OO](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO)
