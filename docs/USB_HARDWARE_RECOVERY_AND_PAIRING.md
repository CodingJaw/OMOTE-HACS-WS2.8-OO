# Waveshare 2.8 V2 — controlled USB testing and recovery gate

**Scope:** Waveshare ESP32-S3-Touch-LCD-2.8 V2, OMOTE firmware
\`feature/config-v2-transactional\`. This is a *procedure to prepare*, not
a claim that a firmware backup or recovery has been performed.

## Non-negotiable preflight

1. Record the known-good firmware commit, environment, partition table, flash
   size, flash mode, PSRAM settings, serial port and device MAC. Confirm the
   display (ST7789), CST3530 touch, and physical UI still work.
2. Save an offline copy of the known-good source and its built firmware,
   bootloader and partition table. Export OMOTE JSON and **all image files**.
   Home Assistant's current JSON snapshots do not include binary images.
3. Before changing any flash partitions or attempting a test upload, preserve
   a **full 16 MiB flash image** if the board is verified to have 16 MiB flash.
   Use an installed \`esptool\` compatible with the board. Example only, to run
   **after verifying** the port and flash size:
   \`esptool.py --chip esp32s3 --port /dev/ttyACM0 read_flash 0x0 0x1000000 waveshare-before-test-16m.bin\`.
   Keep this image private: it can include Wi-Fi, HA tokens and pairing data.
4. Verify the resulting image is exactly 16,777,216 bytes, store its SHA-256
   offline and retain a working USB bootloader recovery path. Do **not**
   publish the image to GitHub or attach it to issues.
5. Run firmware host safety tests and the target PlatformIO build. Do not
   use \`uploadfs\`, \`erase_flash\`, \`write_flash\` or a partition-changing
   update before the backup is verified.
6. Confirm a known-good USB restore procedure and power supply are available
   before any experimental flash. A full flash restore can overwrite Wi-Fi,
   NVS and credentials; confirm those consequences first.

## Hardware acceptance (future, not yet passed)

- Confirm offline touchscreen and IR control with no Wi-Fi or HA.
- Confirm independent recovery UI if scene JSON is invalid.
- Confirm persistent recovery Wi-Fi/reprovisioning and reconnect.
- Verify one-time pairing code plus a **separate touchscreen confirmation**;
  code expiry, replay rejection, device identity pinning and revocation.
- Require a fresh HA administrator approval and fresh physical confirmation
  for **every** commit and recovery resend.
- Test interrupted staging, power loss, stale manifest, missing image,
  mismatched SHA, malformed PNG/JPEG and a full flash storage condition.
- Confirm the previous working configuration is not partially overwritten
  during upload, and recovery is possible without HA/Wi-Fi when needed.

**Deployment is disabled** until all applicable acceptance checks are
demonstrated on the actual board and recorded in the firmware issue.

## User decisions

- USB tests may use the current Waveshare, but only after backup/recovery
  preflight.
- Pairing must use both a one-time code and physical touchscreen confirmation.
- Complete configurations include referenced PNG/JPEG binaries and exact
  per-file hashes, not only JSON.
- In recovery, HA may *suggest* the last reviewed configuration but may
  not transfer it without fresh user and device approval.
- No A/B generations, no automatic rollback, no automatic resend.
