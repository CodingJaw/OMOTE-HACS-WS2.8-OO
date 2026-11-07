# Bundled Espressif Security2 reference client

Upstream: Espressif Systems, **ESP-IDF v5.4.2**
https://github.com/espressif/esp-idf/tree/v5.4.2

Original files copied with upstream Apache-2.0 copyright notices:
- `tools/esp_prov/security/security2.py` → `security2.py`
- `tools/esp_prov/security/security.py` → `security.py`
- `tools/esp_prov/security/srp6a.py` → `srp6a.py`
- `tools/esp_prov/utils/convenience.py` → `convenience.py`
- `components/protocomm/python/{constants,sec0,sec1,sec2,session}_pb2.py` → `proto/*_pb2.py`

Changes made for Home Assistant compatibility: replace non-qualified imports
(`proto`, `utils`, and generated `*_pb2`) with relative imports, use a
private protobuf `DescriptorPool` instead of the process-wide default,
and assign namespaced generated module names when building descriptors.
No SRP6a parameter, cryptographic primitive, nonce/counter algorithm or
wire protocol has been deliberately altered. This does not authorize pairing.

`LICENSE` contains the upstream Apache License 2.0 text. Third-party
Python packages `cryptography` and `protobuf` remain Home Assistant's
installed dependencies and are not copied into this integration.

Acceptance baseline: HA 2024.9.1, Python 3.12.5, cryptography 43.0.0,
protobuf 4.25.4; actual Waveshare Security2 session compatibility requires
its own hardware test. No full ESP-IDF source checkout or `IDF_PATH` is
needed for the bundled LAB client.
