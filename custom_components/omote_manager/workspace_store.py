"""Persistent, optimistic-concurrency workspace for OMOTE configuration drafts.

Manager-side metadata does not change the on-device OMOTE JSON format. All
mutations are protected by an asyncio lock and persisted before publication.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .safe_files import is_exportable_json
from .workspace_model import (
    WorkspaceError,
    apply_scene_template,
    available_scenes,
    check_bundle_limits,
    edit_command,
    editable_commands,
    extract_scene_template,
    file_digest,
    validate_bundle,
)

MAX_LOCATIONS = 100
MAX_TEMPLATES = 64
MAX_DRAFTS = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _initial() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": 0,
        "locations": [],
        "templates": [],
        "drafts": {},
    }


def _draft_summary(entry_id: str, draft: dict) -> dict:
    files = draft["files"]
    originals = draft["base_files"]
    return {
        "entry_id": entry_id,
        "imported_at": draft["imported_at"],
        "file_count": len(files),
        "modified_count": sum(
            1 for p, content in files.items() if originals.get(p) != content
        ),
        "original_sha256": draft["original_sha256"],
        "current_sha256": file_digest(files),
        "scenes": available_scenes(files),
        "command_files": sorted(
            p for p in files if p.startswith("Commands/") and is_exportable_json(p)
        ),
    }


class WorkspaceStore:
    """Manager-side saved drafts, shared scene templates and locations."""

    def __init__(self, hass):
        self._store = Store(hass, 1, f"{DOMAIN}.workspace")
        self._state = _initial()
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        state = await self._store.async_load()
        if state is not None:
            if not isinstance(state, dict) or state.get("schema_version") != 1:
                raise WorkspaceError("Unsupported OMOTE workspace storage version")
            self._state = state

    def _read(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def summary(self) -> dict[str, Any]:
        state = self._read()
        return {
            "revision": state["revision"],
            "locations": state["locations"],
            "templates": [
                {
                    "id": template["id"],
                    "name": template["name"],
                    "location_id": template["location_id"],
                    "scene_path": template["scene_entry"]["FileName"],
                    "source_entry_id": template["source_entry_id"],
                    "file_count": len(template["files"]),
                }
                for template in state["templates"]
            ],
            "drafts": {
                entry_id: _draft_summary(entry_id, draft)
                for entry_id, draft in state["drafts"].items()
            },
            "deployment_enabled": False,
        }

    async def _mutate(self, expected_revision: int, operation):
        async with self._lock:
            if expected_revision != self._state["revision"]:
                raise WorkspaceError(
                    "Workspace changed in another session; refresh before saving"
                )
            next_state = self._read()
            result = operation(next_state)
            next_state["revision"] += 1
            await self._store.async_save(next_state)
            self._state = next_state
            return result

    async def async_import(
        self,
        expected_revision: int,
        entry_id: str,
        files: dict[str, str],
        replace: bool = False,
    ) -> None:
        """Import live firmware JSON into a safe, independent local draft."""
        check_bundle_limits(files)
        if "Scenes.json" not in files:
            raise WorkspaceError("OMOTE is missing Scenes.json")
        copied = dict(files)

        def operation(state):
            drafts = state["drafts"]
            if entry_id in drafts and not replace:
                raise WorkspaceError(
                    "A draft already exists; explicitly confirm replacement to reimport"
                )
            if entry_id not in drafts and len(drafts) >= MAX_DRAFTS:
                raise WorkspaceError("Too many remote drafts")
            drafts[entry_id] = {
                "imported_at": _now(),
                "base_files": dict(copied),
                "files": dict(copied),
                "original_sha256": file_digest(copied),
            }
        await self._mutate(expected_revision, operation)

    async def async_create_location(
        self, expected_revision: int, name: str, parent_id: str | None = None
    ) -> str:
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 64):
            raise WorkspaceError("Location name must contain 1–64 characters")
        name = name.strip()
        new_id = _new_id("loc")

        def operation(state):
            locations = state["locations"]
            if len(locations) >= MAX_LOCATIONS:
                raise WorkspaceError("Too many locations")
            if parent_id and not any(item["id"] == parent_id for item in locations):
                raise WorkspaceError("Parent location does not exist")
            if any(
                item["name"].casefold() == name.casefold()
                and item["parent_id"] == parent_id
                for item in locations
            ):
                raise WorkspaceError("A sibling location already has this name")
            locations.append({
                "id": new_id, "name": name, "parent_id": parent_id
            })
        await self._mutate(expected_revision, operation)
        return new_id

    async def async_create_template(
        self,
        expected_revision: int,
        entry_id: str,
        scene_path: str,
        name: str,
        location_id: str | None,
    ) -> str:
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
            raise WorkspaceError("Template name must contain 1–80 characters")
        name = name.strip()
        new_id = _new_id("tpl")

        def operation(state):
            if len(state["templates"]) >= MAX_TEMPLATES:
                raise WorkspaceError("Too many shared templates")
            if location_id and not any(
                item["id"] == location_id for item in state["locations"]
            ):
                raise WorkspaceError("Location does not exist")
            draft = state["drafts"].get(entry_id)
            if not draft:
                raise WorkspaceError("Import a remote before creating a template")
            scene_entry, included_files = extract_scene_template(
                draft["files"], scene_path
            )
            state["templates"].append({
                "id": new_id,
                "name": name,
                "location_id": location_id,
                "source_entry_id": entry_id,
                "scene_entry": scene_entry,
                "files": included_files,
                "created_at": _now(),
            })
        await self._mutate(expected_revision, operation)
        return new_id

    async def async_apply_template(
        self, expected_revision: int, entry_id: str, template_id: str
    ) -> None:
        """Apply to an HA draft only, never a firmware endpoint."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if not draft:
                raise WorkspaceError("Import a destination remote first")
            template = next(
                (t for t in state["templates"] if t["id"] == template_id),
                None
            )
            if template is None:
                raise WorkspaceError("Unknown template")
            updated = apply_scene_template(
                draft["files"], template["scene_entry"], template["files"]
            )
            draft["files"] = updated
        await self._mutate(expected_revision, operation)

    def commands(self, entry_id: str, path: str) -> list[dict]:
        draft = self._state["drafts"].get(entry_id)
        if not draft:
            raise WorkspaceError("Import a remote to edit its commands")
        return editable_commands(draft["files"], path)

    async def async_edit_command(
        self,
        expected_revision: int,
        entry_id: str,
        path: str,
        name: str,
        mode: str,
        protocol: str,
        data: list[str],
    ) -> None:
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if not draft:
                raise WorkspaceError("Import a remote before editing")
            draft["files"] = edit_command(
                draft["files"], path, name, mode, protocol, data
            )
        await self._mutate(expected_revision, operation)

    def validation(self, entry_id: str) -> dict[str, Any]:
        draft = self._state["drafts"].get(entry_id)
        if draft is None:
            raise WorkspaceError("Import a remote before validating")
        issues = validate_bundle(draft["files"])
        return {
            "issues": issues,
            "errors": sum(issue["level"] == "error" for issue in issues),
            "warnings": sum(issue["level"] == "warning" for issue in issues),
            "revision": self._state["revision"],
            "sha256": file_digest(draft["files"]),
            "deployment_enabled": False,
        }
