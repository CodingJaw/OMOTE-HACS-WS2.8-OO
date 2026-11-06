"""Opt-in Espressif Security2 Python reference-client loader.

No package installation or network access takes place here. The HACS
integration MUST NOT auto-download or dynamically install cryptography code.
The operator must explicitly provide a compatible installed ESP-IDF checkout
through IDF_PATH on the Home Assistant host, and enable LAB mode separately.

WARNING: Espressif's Python provisioning reference uses unqualified module
names "proto", "utils" and "security", so refuse collisions rather than
replace Home Assistant's already loaded unrelated modules.
"""
from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path
import sys


class LabPrerequisiteError(RuntimeError):
    """Error code only. Never expose underlying filesystem or import details."""


_REQUIRED = (
    "tools/esp_prov/security/security2.py",
    "tools/esp_prov/security/srp6a.py",
    "tools/esp_prov/utils/__init__.py",
    "tools/esp_prov/proto/__init__.py",
    "components/protocomm/python/session_pb2.py",
    "components/protocomm/python/sec2_pb2.py",
    "components/protocomm/python/constants_pb2.py",
)


def _inside(path: str, root: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(root)
    except (ValueError, TypeError, OSError):
        return False


def load_official_security2():
    """Load the official matching ESP-IDF Python Security2 class, fail closed.

    This routine is called ONLY after explicit LAB enablement and cannot
    start any remote connection, prepare keys or grant pairing authority.
    """
    configured = os.environ.get("IDF_PATH")
    if not configured or len(configured) > 1024:
        raise LabPrerequisiteError("idf_path_not_configured")
    try:
        root = Path(configured).expanduser().resolve(strict=True)
        if (not root.is_dir()
                or not all((root / p).is_file() for p in _REQUIRED)):
            raise LabPrerequisiteError("espidf_source_not_found")
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, LabPrerequisiteError):
            raise
        raise LabPrerequisiteError("espidf_source_not_found") from None

    tool_path = (root / "tools/esp_prov").resolve()
    # ESP-IDF uses these globally importable packages. Never clobber a
    # third-party package already imported by Home Assistant.
    for name in ("proto", "utils", "security"):
        module = sys.modules.get(name)
        if module is not None and not _inside(
            getattr(module, "__file__", None), tool_path
        ):
            raise LabPrerequisiteError("espidf_module_namespace_conflict")

    inserted = str(tool_path) not in sys.path
    try:
        if inserted:
            sys.path.insert(0, str(tool_path))
        package = importlib.import_module("security.security2")
        target = getattr(package, "Security2")
        signature = inspect.signature(target)
        needed = {"sec_patch_ver", "username", "password", "verbose"}
        if not needed.issubset(signature.parameters):
            raise LabPrerequisiteError("unsupported_espidf_security2_version")
        if not _inside(getattr(package, "__file__", None), tool_path):
            raise LabPrerequisiteError("espidf_module_namespace_conflict")
        return target
    except LabPrerequisiteError:
        raise
    except Exception:
        raise LabPrerequisiteError("espidf_import_or_dependency_failure") from None
    finally:
        if inserted:
            # Keep Home Assistant's import search path unchanged. The loaded
            # namespaced Espressif modules remain cached for the LAB run.
            sys.path.remove(str(tool_path))
