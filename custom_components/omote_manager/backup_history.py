"""Credential-excluding per-device backup history and local-draft recovery.

Compatible with existing v0.1.0-dev1..dev10 Home Assistant Store records.
Every operation is read-only toward firmware, except *reading* JSON to create
a new Home Assistant backup. Restoring changes only the HA workspace draft.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .safe_files import is_exportable_json
from .workspace_model import (
    MAX_FILES, WorkspaceError, check_bundle_limits, file_digest, parse_jsonc,
)

BACKUP_HISTORY_LIMIT = 3


class OmoteBackupHistory:
    """Persist and verify at most three snapshots for one integration entry."""

    def __init__(self, hass, entry_id: str) -> None:
        if not isinstance(entry_id, str) or not entry_id:
            raise WorkspaceError("Invalid OMOTE backup entry")
        self._store = Store(hass, 1, f"{DOMAIN}.backups_{entry_id}")

    async def _history(self) -> list[dict[str, Any]]:
        record = await self._store.async_load()
        if record is None:
            return []
        if not isinstance(record, dict) or not isinstance(record.get("snapshots"), list):
            raise WorkspaceError("OMOTE backup history is damaged")
        history = record["snapshots"]
        if len(history) > 100:
            raise WorkspaceError("Backup history exceeds safe record count")
        return history

    @staticmethod
    def _verify(snapshot: Any) -> dict[str, str]:
        if not isinstance(snapshot, dict):
            raise WorkspaceError("Backup snapshot metadata is invalid")
        files = snapshot.get("files")
        if not isinstance(files, dict) or "Scenes.json" not in files:
            raise WorkspaceError("Backup is missing required OMOTE files")
        check_bundle_limits(files)
        for path, raw in files.items():
            try:
                value = parse_jsonc(raw)
            except WorkspaceError as exc:
                raise WorkspaceError(f"Corrupt backup file {path}: {exc}") from exc
            if not isinstance(value, dict):
                raise WorkspaceError(f"Backup file {path} must be a JSON object")
        digest = snapshot.get("sha256")
        if not isinstance(digest, str) or digest != file_digest(files):
            raise WorkspaceError("Backup integrity check failed (SHA-256 mismatch)")
        return files

    async def list_metadata(self) -> list[dict[str, Any]]:
        """Expose only metadata; never return JSON contents to sidebar."""
        history = await self._history()
        items = []
        for index, snapshot in enumerate(history):
            item = {
                "index": index,
                "created_at": "",
                "file_count": 0,
                "sha256": "",
                "bytes": 0,
                "integrity": "damaged",
            }
            if isinstance(snapshot, dict):
                stamp = snapshot.get("created_at")
                if isinstance(stamp, str):
                    item["created_at"] = stamp[:64]
                try:
                    files = self._verify(snapshot)
                except WorkspaceError:
                    pass
                else:
                    item.update({
                        "file_count": len(files),
                        "sha256": snapshot["sha256"],
                        "bytes": sum(len(raw.encode("utf-8")) for raw in files.values()),
                        "integrity": "verified",
                    })
            items.append(item)
        return list(reversed(items))

    async def load_snapshot(
        self, index: int, sha256: str
    ) -> dict[str, str]:
        """Load one exact, integrity-checked snapshot for HA draft restoration."""
        history = await self._history()
        if type(index) is not int or not 0 <= index < len(history):
            raise WorkspaceError("Backup snapshot not found")
        snapshot = history[index]
        files = self._verify(snapshot)
        if sha256 != snapshot["sha256"]:
            raise WorkspaceError("Selected backup changed; refresh backup history")
        return deepcopy(files)

    async def capture(self, api) -> dict[str, Any]:
        """Capture a complete safe JSON subset or leave history unchanged."""
        await api.status()
        all_paths = await api.files()
        paths = sorted(path for path in set(all_paths) if is_exportable_json(path))
        if not paths or len(paths) > MAX_FILES or "Scenes.json" not in paths:
            raise WorkspaceError("No complete safe OMOTE configuration inventory")
        files: dict[str, str] = {}
        for path in paths:
            files[path] = await api.read_file(path, verify_json=True)
            check_bundle_limits(files)
        self._verify({
            "files": files,
            "sha256": file_digest(files),
        })
        snapshot = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "sha256": file_digest(files),
        }
        history = await self._history()
        # Persist only after all reads, size caps and JSON checks succeed.
        await self._store.async_save({
            "snapshots": (history + [snapshot])[-BACKUP_HISTORY_LIMIT:]
        })
        return {
            "created_at": snapshot["created_at"],
            "file_count": len(files),
            "bytes": sum(len(content.encode("utf-8")) for content in files.values()),
            "sha256": snapshot["sha256"],
            "integrity": "verified",
        }
