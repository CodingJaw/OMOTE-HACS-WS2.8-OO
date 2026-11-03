# OMOTE HACS — active-main development and preserved releases

**Confirmed operator workflow (2026-11-03): HACS installs and updates the integration from `main`; do not rely on installing feature branches.** Therefore `main` is the **active development and HACS distribution branch**, not a frozen stable release.

## Branch roles

| Branch | Purpose | Policy |
| --- | --- | --- |
| `main` | **Active HACS development, installation and update source** | Commit tested integration updates here; each update is visible to HACS |
| `stable/verified-dev17-before-v2` | Exact known-good `dev17` snapshot, `13a94cf0bd7f2e03cfca3210fd10435bd101578e` | Preserve unchanged |
| `verified-dev17` | Additional known-good `dev17` snapshot, same commit | Preserve unchanged |
| `working` | Older `dev14` fallback, `3f801ad96371d4a277430aaaac99791233e18050` | Preserve unchanged |
| `develop` | Historical older branch | Not the HACS install source |
| `feature/*` | Optional staging for risky or concurrent work | Consolidate accepted, passing code into `main`; do not require HACS to install from it |

The firmware project has its own separate rules. Continue experimental firmware
work on `CodingJaw/OMOTE-Firmware-WS2.8-OO:feature/config-v2-transactional`.
Do **not** change firmware `waveshare28v2-port` or enable deployment.

## Update process for HACS

1. Start from the latest `main`. When making a risky change, preserve the
   current good commit in a new named `stable/*` branch **before updating main**.
2. Develop and land HACS changes in `main`. Feature branches may be used
   temporarily for safety or concurrency, but are **not** the installation path.
3. Every update must pass Python, JavaScript, JSON and cross-repository API
   contract checks; preserve HA Core 2024.9.1/HACS 2.0.5 compatibility.
4. Increment the integration manifest version and the frontend module/cache
   version together, to make HACS update detection and browser cache
   invalidation reliable. Version changes must satisfy
   `tests/test_frontend_assets.py`.
5. HACS users update/reinstall from the normal **main/default branch** source.
   After update, validate config flow, panel, import, backups and reconnect on
   the actual Home Assistant installation. A CI pass does **not** prove HA
   acceptance.
6. If the latest main build fails installation, preserve forensic details,
   restore the last-good snapshot to `main` under the operator's direction,
   and issue an updated manifest version. Do not delete the stable snapshots.
7. Keep firmware configuration mutations and pairing **OFF** until secure
   transactions, touchscreen approvals, independent recovery and physical
   Waveshare tests have been proven; HACS main code must remain safe for
   read-only installation in the meantime.

## Branch protection

This workflow intentionally permits reviewed development on `main`; do not
configure GitHub rules that prevent all main-branch development. If rulesets
are desired, require passing checks before merges and prohibit force-pushes
and deletion on `main` and saved `stable/*` branches. The connected
GitHub integration cannot configure or verify rulesets (HTTP 403); this
document is **process guidance**, not a claim of technical protection.
