# OMOTE Manager — Home Assistant integration

A HACS custom integration for [OMOTE object-oriented firmware](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO), including the Waveshare ESP32-S3 Touch LCD 2.8 V2 port.

**Development build 0.1.0-dev10 — Home Assistant draft editing; no firmware writes.**

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

The original live file browser remains read-only. Safe firmware deployment is a future milestone.

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

### Scene / page / button editor and draft comparison (v0.1.0-dev7)

Within **Profile Studio**, scroll past the Command Editor to **Scenes, pages & button assignments**:

- Choose a scene from the imported firmware's Scenes.json and edit the scene menu name, screen title and optional physical launch key/press type.
- Choose a tab/page and edit its scene-local page name and short tab label.
- Select an existing touchscreen Button, Label, ColorButtons or NumberPad widget. Edit its existing text (if supported) or its command binding, including an individual command-array position.
- Choose an OMOTE physical key and event (Press, Release, Repeat, Short, Long); map it to an existing command in the page command file or clear the event.
- Use **Compare original and draft** to view exact changed JSON lines, then optionally revert just that local draft file.

All changes use the unmodified OMOTE firmware JSON structures and are saved only to Home Assistant's private workspace store. Unknown JSON fields are retained. Editing an existing file normalizes that file's formatting/comments. **Page definition files may be shared by multiple scenes**: changes to their widgets or physical ButtonMaps are visible in every scene referencing the page. Page title/short tab label edits only touch the selected scene entry.

For safety, the editor restricts command bindings to names already present in the corresponding command file, taking each scene's CommandPrefix into account. To select another command, first add it to the corresponding firmware-format command file in a future milestone. After editing, select **Validate draft** to inspect cross-file references. The diff viewer is local only and is not a deploy/restore interface.

### Visual touchscreen page layout (v0.1.0-dev8)

The **Visual page layout** section within **Profile Studio → Scenes, pages & button assignments** displays a schematic portrait **240 × 320 px** Waveshare screen and the selected page's widgets. It reads current `HeightPct`, `AlignTo`, `PosX`, `PosY` and `SizeXY` fields from the imported JSON.

Select a widget in the dropdown or click its preview box. The inspector can place a widget in automatic flow, align it to an earlier widget, or assign explicit `PosX` and `PosY` values (0–100%); widgets that support `SizeXY` can also have percentage width/height. Movable preview widgets may be dragged to propose a new position. **Dragging is not an automatic save**: select **Save layout to draft** to commit the change to HA storage, then **Validate draft** and inspect the original-vs-draft diff.

**Firmware interpretation matters:** `SizeXY` and `PosX`/`PosY` are percentages despite their names. Image widgets use a separate `SizeXYinPixels` field which is not edited in this milestone. Original `Label`/`Title` widgets support height and alignment but not explicit absolute positions. Actual LVGL sizes, fonts, tabs, widget-specific rendering and status-bar height are not reproduced exactly: the preview is a **schematic**, not a device emulator. Changes to a page file affect every scene referring to that shared page.

Deployment remains disabled. No image assets are uploaded, no device commands are sent, and no firmware files are modified.

### Color-coded JSON comparison and deployment-readiness review (v0.1.0-dev9)

In **Profile Studio → Compare original and draft**, updated unified diffs use **green for added lines**, **red for removed lines** and **blue for change-section headers**. A legend explains the colors, a summary counts added/removed lines, and **Hide unchanged lines** removes the unmodified context from view. Files are rendered using browser text nodes, not HTML, so JSON content cannot inject markup into the panel.

A new **Deployment readiness review** underneath the comparison lists changed paths, per-file raw-byte SHA-256 hashes and sizes, structural validation counts and any blockers. With **Read changed files from Waveshare** enabled, the Home Assistant backend verifies the firmware API, reads only the draft's changed original files, and compares them to the imported baseline; a new draft file already present on the remote is reported as a conflict. If the device is offline, deselect the live check for a local-only review. This check is point-in-time and does not guarantee the files remain unchanged afterward.

**Deployment remains disabled.** The firmware API does not yet provide authenticated transaction staging, commit verification and reliable rollback. The review never writes configuration files, does not change the device, and does not overwrite drafts. Draft edits invalidate an earlier review.

### Downloadable deployment and recovery kit (v0.1.0-dev10)

**This is an offline file export, not automatic firmware deployment.** The current Waveshare configuration API still has unsafe direct file-write endpoints. No data is uploaded to the remote by this release.

After editing a draft in **Profile Studio → Compare original and draft**:

1. Click **Run review** to validate the files and (optionally) compare changed originals to the live Waveshare.
2. If the draft has changes, zero validation errors, and no live conflicts, the **Download reviewed ZIP** button becomes available.
3. Click to download `omote-deployment-review-kit.zip`. With a live review, the integration repeats the remote baseline check immediately before creating the archive. If the remote is offline, uncheck **Read changed files from Waveshare**, run an offline review, and confirm the warning before exporting. Offline exports are **UNVERIFIED**.
4. Inspect the archive: `proposed/` is the full editable OMOTE JSON subset in the Home Assistant draft; `rollback/` is the original JSON subset imported from the remote; `MANIFEST.json` provides changed file paths, sizes and SHA-256 hashes; `READ_ME_FIRST.txt` contains recovery warnings.

The ZIP **does not include** `HaSettings.json`, `DeviceSettings.json`, other known credential files, images, the complete LittleFS filesystem, or a flashable firmware image. Custom JSON values may contain personal or sensitive command data. Protect the downloaded ZIP accordingly. Restoring this limited baseline cannot substitute for a complete device/firmware backup.

A checked or exported archive does not enable wireless deployment. Newer firmware will need an authenticated, versioned, crash-safe transaction protocol and device-side rollback. See [Deployment protocol proposal](docs/DEPLOYMENT_PROTOCOL.md). The user must explicitly approve any firmware modifications.

### If the editor is missing after updating

Home Assistant's browser can retain a previously registered JavaScript custom element even after the server is upgraded. This release uses a new versioned element tag to avoid stale constructors. After installing v0.1.0-dev9, restart Home Assistant and perform a **hard browser reload** (Ctrl+Shift+R). If Profile Studio does not appear, use the top **Profile Studio** button; its loading/error state should be visible, and the browser console will identify JavaScript failures.

## Planned milestones

1. Read-only monitoring and backups (this development build).
2. Shared profiles, named locations, command editing and draft validation.
3. Firmware-authenticated, atomic stage/commit/rollback; only then enable explicit deploy.
4. Graphical remote layout editor and optional OTA support.

See [architecture and requested firmware extensions](docs/ARCHITECTURE.md).

## Project repositories

- HACS development: [CodingJaw/OMOTE-HACS-WS2.8-OO](https://github.com/CodingJaw/OMOTE-HACS-WS2.8-OO)
- Firmware (unchanged): [CodingJaw/OMOTE-Firmware-WS2.8-OO](https://github.com/CodingJaw/OMOTE-Firmware-WS2.8-OO)
