"""Policy for configuration JSON files exposed by the initial manager.

The first phase intentionally omits device settings and credential files from
both backups and the sidebar file viewer.
"""
from __future__ import annotations

from .const import SAFE_PREFIXES, SAFE_ROOT_FILES, SENSITIVE_FILES

_SECRET_NAMES = frozenset(name.casefold() for name in SENSITIVE_FILES)


def is_exportable_json(path: str) -> bool:
    """Allow only known, non-sensitive OMOTE user-configuration paths."""
    if not isinstance(path, str):
        return False
    if (
        not path.endswith(".json")
        or path.startswith("/")
        or ".." in path
        or "\\" in path
        or path.rsplit("/", 1)[-1].casefold() in _SECRET_NAMES
    ):
        return False
    return path in SAFE_ROOT_FILES or path.startswith(SAFE_PREFIXES)
