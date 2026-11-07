# Secure pairing lifecycle — draft contract (non-authorizing)

**Status:** host-only protocol design and negative tests; **NO production pairing**.

The hardware-confirmed encrypted LAB session successfully verified both
P-256 possession proofs, and the user physically tapped **Review OK**.
The Waveshare subsequently reported **No verified peer. Pairing unavailable**.
That is expected because the LAB device key is stored in software-accessible
NVS and the LAB path has no durable mutual trust or reconnect protocol.

## Proposed transitions (not enabled in firmware)

```text
unpaired -> window_open -> proofs_verified -> review_pending
                                              | reject / expiry
                                              v
                                            unpaired
                                              ^
                                              |
review_pending -> review_approved -> [LOCKED: protected keys,
                                     HA-admin & touchscreen confirmation,
                                     two-party durable commit]
                                     -> paired -> revoked
```

This is **a draft design**, not a declaration that these states can occur
on the actual remote. The firmware's pairing capability advertisement
remains disabled and all Config v1/v2 remote mutations stay disabled.
The HACS offline model explicitly throws on `commit_trust`,
`reconnect`, and `revoke` instead of granting access.

### Production implementation prerequisites

1. Select and review device identity protection, including secure boot,
   physical key-extraction threat model, and a recoverable plan for lost
   HA, damaged flash, and hardware replacement. **No eFuse writes yet.**
2. Use the existing SRP6a/AES-GCM + fresh touchscreen six-digit enrollment
   method, then prove BOTH persistent public keys in the same session.
3. Ensure a separate fresh HA admin authorization and matching local
   touchscreen fingerprint approval. Refuse missing or stale confirmations.
4. Implement a fail-closed, power-cut-safe *two-party* enrollment: neither
   side may claim `paired` merely because its own local record was written.
   A crashed or interrupted enrollment must be recoverable without
   automatically trusting the peer.
5. Define what reconnect proof binds (device ID, HA key, fresh nonces,
   session IDs, protocol version, expected fingerprint, timeouts); refuse
   old proof replay and mismatched public identities.
6. Require explicit touchscreen-assisted revocation/replacement. Retain
   the existing user configuration while requiring a fresh pairing.
7. Keep deployment permissions a **separate** authorization layer requiring
   new admin and touchscreen approval for each single-active transaction;
   enrollment alone never enables writes.

### Safety / implementation boundaries

- LAB listener: independent opt-in port 18082, 120s local window;
  SHA-256 fingerprint review timeout 60s.
- Current software LAB device key is **not** a production hardware identity.
- No new HTTP/WebSocket endpoint, persistent pairing record, NVS schema,
  key writes, eFuse setting, recovery method, config deployment or OTA is
  introduced by the shared contract or policy tests.
- Firmware source of truth:
  `Platformio/tools/config-v2-tests/pairing_lifecycle_contract_v1.json`.
  HACS mirrors the file in `tests/fixtures/` and can compare exact JSON
  by setting `OMOTE_FIRMWARE_PAIRING_LIFECYCLE` for its tests.

### Offline tests

```sh
# From firmware repo root on the isolated feature branch:
python3 -m unittest discover -s Platformio/tools/config-v2-tests -p 'test_pairing_lifecycle_contract.py' -v

# From HACS repo root:
OMOTE_FIRMWARE_PAIRING_LIFECYCLE=/path/to/firmware/Platformio/tools/config-v2-tests/pairing_lifecycle_contract_v1.json \
  python -m unittest discover -s tests -p 'test_pairing_lifecycle_draft.py' -v
```

No device flash or Home Assistant update is needed for these tests.
