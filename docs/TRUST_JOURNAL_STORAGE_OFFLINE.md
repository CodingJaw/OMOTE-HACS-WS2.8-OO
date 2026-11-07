# OMOTE diagnostic trust journal storage — offline prototype (2026-11-07)

**Not production pairing, identity enrollment, or secure credentials.**

The user verified 11/11 public trust-journal contract and simulator tests.
This iteration adds conservative *storage prototypes* and targeted
fault-injection tests. The existing physical Security2 encrypted laboratory
listener, Home Assistant candidate key, UI, configuration, and production
deployment restrictions are not changed.

## Home Assistant: disconnected atomic public snapshot

`custom_components/omote_manager/trust_journal_file_draft.py` contains
`OfflineJournalFile`, which is not imported by the live integration.
It writes **only public diagnostic metadata**, in a caller-supplied temporary
directory, with these steps:

1. Re-read the existing snapshot; fail closed if malformed or corrupted.
2. Validate the exact public record and a bounded set of used transaction IDs.
3. Reject local epoch rollback, dropped replay tombstones and illegal
   phase reversal for a recorded transaction.
4. Canonically serialize, append a SHA-256 corruption checksum and bound
   file size to 8 KiB.
5. Create a mode-0600 temporary file *in the same directory*, write, fsync,
   `os.replace` and fsync the parent directory.
6. On restart, re-validate everything. Never silently reset corrupt data.

These steps model local atomic replacement and best-effort crash durability
on a normal filesystem. They do **not** provide a tamper-proof MAC,
anti-rollback across restored backups, atomic synchronization with the
device, or a production key store. A process/OS crash after rename but
before directory fsync still requires explicit recovery assessment. No
code copies data to HA `.storage` or registers services.

## Firmware: unlinked two-slot NVS journal core

`Platformio/tools/config-v2-tests/trust_journal_slots_draft.hpp` is a
C++17 standalone state machine driven by a mockable `Backend`:

- Two independent slots (future NVS blobs) use sequence numbers and CRC32
  to detect **accidental** corruption, not malicious modification.
- A save must follow a successful read; corrupt/ambiguous snapshots refuse
  further writes instead of falling back to a possibly stale older slot.
- Slot writes are read back and compared. Bad, truncated or failed writes
  do not set any trust bit.
- Reuse of a transaction ID in the same epoch, invalid phase regressions,
  stale generations and incorrect device/public-key fingerprints are
  rejected where the offline model can validate them.
- `trusted()`, `deployment_enabled()` and
  `production_reconnect_enabled()` always return false.

`trust_journal_espidf_nvs_adapter_draft.hpp` documents how `nvs_get_blob`,
`nvs_set_blob` and `nvs_commit` **could** back those two slots. This
adapter is **not included from runtime firmware**, is not compiled by the
ordinary Waveshare image, and is not instantiated. It does not open or
format a namespace or change eFuses. Never bind the adapter until partition
selection, flash/NVS security, power-loss behavior and recovery have been
reviewed and tested physically.

A CRC32 is not a signature or a protection against flash editing. Neither
NVS double-slot storage nor Home Assistant's SHA-256 checksum protects
against replay of an older *entire storage image*. Real anti-rollback needs
additional authenticated or hardware-rooted mechanisms.

## New isolated tests

From the firmware repository on `feature/config-v2-transactional`:

```bash
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_trust_journal_slots_host.py' -v
```

This compiles and executes `trust_journal_slots_host_test.cpp` with C++17
(`g++` or `clang++`). If no compiler is available, the compilation test
is **SKIPPED**, not a pass. It uses a fake NVS backend; it does not access USB.

From the HACS repository on `main`:

```bash
python -m unittest discover -s tests -p 'test_trust_journal_file_draft.py' -v
```

The tests create temporary files, inject truncation and modified checksums,
exercise recovery/rollback rules, and check that no private keys or runtime
registration are involved. They do **not** modify HA's actual `.storage`
or candidate identities.

**Acceptance remains open until those tests pass.** Afterwards we still
need a review of the full storage API, concurrency and backup restore policy,
hardware-backed identity choices, actual NVS partition implementation,
reboot/power-cut testing and two-party cryptographic receipt verification.

**Permanent pairing, firmware writes, OTA, trusted reconnect and all
eFuse changes remain disabled.**
