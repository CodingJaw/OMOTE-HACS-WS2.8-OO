"""Fail-closed loader for the isolated, bundled Espressif Security2 v5.4.2.

The bundled client retains Espressif's SRP6a/AES-GCM implementation, and
generated protocomm protobufs load from a private descriptor pool.
No external IDF_PATH, sys.path changes, runtime downloads or package
installation is attempted. This module never opens a network connection.
"""
from __future__ import annotations

import inspect
from importlib import metadata


class LabPrerequisiteError(RuntimeError):
    """Short diagnostic code; never include host secrets or raw import errors."""


def _supported_dependencies() -> bool:
    """Baseline matches Home Assistant Core 2024.9.1's installed libraries."""
    try:
        cryptography = metadata.version("cryptography").split(".")
        protobuf = metadata.version("protobuf").split(".")
        return (
            42 <= int(cryptography[0]) <= 45
            and int(protobuf[0]) == 4
            and int(protobuf[1]) >= 25
        )
    except (metadata.PackageNotFoundError, ValueError, IndexError):
        return False


def load_official_security2():
    """Return bundled unmodified-algorithm Espressif Security2 class.

    Only used by explicitly enabled LAB WebSocket after administrator
    authorization. An incompatible HA Python environment fails closed.
    """
    if not _supported_dependencies():
        raise LabPrerequisiteError("incompatible_crypto_or_protobuf_version")
    try:
        from .sec2_vendor.security2 import Security2
        params = inspect.signature(Security2).parameters
        if not {"sec_patch_ver", "username", "password", "verbose"}.issubset(params):
            raise LabPrerequisiteError("unsupported_bundled_security2_version")
        return Security2
    except LabPrerequisiteError:
        raise
    except Exception:
        raise LabPrerequisiteError("bundled_security2_import_failed") from None
