# OMOTE HACS — operational branch and release policy

**User-confirmed rule (2026-11-03): HACS currently installs and works only from `main`.**
A passing CI build on a feature branch is **not** evidence that Home Assistant
can install, load or use that branch. Never ask the operator to switch HACS
directly to an untested feature branch as a substitute for acceptance testing.

## Preserved refs (verified via GitHub compare on 2026-11-03)

| Ref | Role | Baseline | May experimental work modify it? |
| --- | --- | --- | --- |
| `main` | Only currently confirmed HACS installation/update source | `13a94cf0bd7f2e03cfca3210fd10435bd101578e` (`dev17`) | **No** |
| `verified-dev17` | Immutable known-good release reference | Same exact commit as `main` on 2026-11-03 | **No** |
| `working` | Older `dev14` fallback | Separate older snapshot; seven commits behind `main` | **No** |
| `develop` | Historical development reference | Not an HA acceptance target | Avoid without explicit request |
| `feature/usb-recovery-assets-phase` | Current HACS asset/security experimental work | Based on `main`, ahead; not installed in production | **Yes** |
| Other `feature/*` | Earlier or alternative drafts | May overlap; review before combining | Only by explicit scope |

The matching OMOTE firmware development branch is
`CodingJaw/OMOTE-Firmware-WS2.8-OO:feature/config-v2-transactional`.
The stable, previously working firmware branch `waveshare28v2-port` must not
be changed by these experiments.

## Operational rules

1. **Never push, force-push, rebase, merge into, delete, or reset** HACS
   `main`, `working`, or `verified-dev17` as part of experimental work.
   Never change the connected production HACS installation without the
   operator's explicit approval and a known restore path.
2. Use an existing appropriately named HACS `feature/*` branch (or a new
   feature branch based on `main`) for proposed changes. Keep changes
   reviewable and run HA 2024.9.1-compatible unit/contract/JS/JSON tests.
3. Preserve the server-side deployment **kill switch OFF** and leave v1
   writes, unauthenticated pairing, direct file mutation, and firmware
   transactions unreachable until verified secure firmware support, independent
   recovery and actual Waveshare testing pass.
4. A proposed release must include: exact Git commit, tested HA Core/HACS
   versions, CI links, a diff against `verified-dev17`, firmware API and
   migration compatibility review, and explicit rollback instructions.
5. User acceptance testing of the updated **actual main-branch HACS install**
   is necessary to call the update supported. To avoid risking the only
   working installation, first test in a **separate HA test instance**, where
   the candidate code can be installed independently. Do not merge or switch
   production `main` just to find out whether it loads.
6. When the candidate passes all gates, ask the operator for specific
   authorization **before** promotion to `main`. First preserve a fresh
   immutable candidate/release ref and the current `main` SHA. Merge only
   the approved release commit(s), never merge competing draft PRs blindly.
7. After promotion, verify installation from `main`, config flow, sidebar,
   remote discovery, read-only import, backup/review workflows, reconnect,
   and recovery-safe behavior in the target Home Assistant version. If any
   step fails, restore the earlier release from an immutable ref under
   operator direction; do not silently deploy a different branch.

## Branch protection limitation

This document is process policy, **not technical GitHub branch protection**.
The connected GitHub integration currently receives HTTP 403 for reading
`main` branch protection and cannot configure or verify rulesets.

For an enforceable release gate, a repository administrator should configure
GitHub Settings → Rules → Rulesets (or Branch protection) for `main`:
require a pull request and passing HACS validation checks; restrict direct
pushes/force pushes/deletion, require deliberate reviewer approval, and
restrict bypass permissions as appropriate. Also protect the saved
`working` and `verified-dev17` refs from deletion or rewriting.

No GitHub protection change is claimed until confirmed in repository settings.
