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
    parse_jsonc,
    validate_bundle,
)

from .review_model import make_review

from .editor_model import (
    scene_detail,
    edit_scene,
    edit_page_title,
    edit_widget,
    edit_widget_layout,
    edit_button_map,
    draft_diff,
    revert_draft_file,
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
        "reviewed": {},
    }


def _reviewed_summary(record: dict, draft: dict | None) -> dict:
    """Return metadata only; detect stored snapshot damage without leaking JSON."""
    summary = {
        "saved_at": str(record.get("saved_at", ""))[:64] if isinstance(record, dict) else "",
        "sha256": "",
        "file_count": 0,
        "review_status": "unavailable",
        "integrity": "damaged",
        "matches_current_draft": False,
    }
    try:
        files = record["files"]
        check_bundle_limits(files)
        if "Scenes.json" not in files or file_digest(files) != record["sha256"]:
            raise WorkspaceError("Reviewed snapshot integrity check failed")
        if any(issue["level"] == "error" for issue in validate_bundle(files)):
            raise WorkspaceError("Reviewed snapshot validation failed")
        if record.get("review_status") not in ("remote-checked", "offline-unverified"):
            raise WorkspaceError("Reviewed snapshot verification state is invalid")
    except (KeyError, TypeError, ValueError, AttributeError, WorkspaceError):
        return summary
    summary.update({
        "sha256": record["sha256"],
        "file_count": len(files),
        "review_status": record["review_status"],
        "integrity": "verified",
        "matches_current_draft": bool(
            draft and file_digest(draft["files"]) == record["sha256"]
        ),
    })
    return summary


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
            # Schema v1 predates separately retained reviewed snapshots.
            self._state.setdefault("reviewed", {})

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
            "reviewed": {
                entry_id: _reviewed_summary(record, state["drafts"].get(entry_id))
                for entry_id, record in state.get("reviewed", {}).items()
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
        # Do not replace a valid existing draft with corrupt or partial reads.
        # Syntax acceptance, including comments, matches the live OMOTE parser.
        for path, raw in files.items():
            try:
                parsed = parse_jsonc(raw)
            except WorkspaceError as exc:
                raise WorkspaceError(f"Invalid imported file {path}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise WorkspaceError(f"Invalid top-level JSON object in {path}")
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

    def scene_editor(self, entry_id: str, scene_path: str) -> dict[str, Any]:
        """Return live parsed information from the local draft only."""
        draft = self._state["drafts"].get(entry_id)
        if draft is None:
            raise WorkspaceError("Import a remote before editing its scenes")
        return scene_detail(draft["files"], scene_path)

    async def async_edit_scene(
        self, revision: int, entry_id: str, path: str,
        name: str, screen_name: str, bind_key: str, press_type: str,
    ) -> None:
        """Update scene index and scene file within one HA storage revision."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = edit_scene(
                draft["files"], path, name=name, screen_name=screen_name,
                bind_key=bind_key, press_type=press_type,
            )
        await self._mutate(revision, operation)

    async def async_edit_page_title(
        self, revision: int, entry_id: str, scene_path: str, page_index: int,
        name: str, short_name: str,
    ) -> None:
        """Edit scene-local page title, not shared page definition."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = edit_page_title(
                draft["files"], scene_path, page_index,
                name=name, short_name=short_name,
            )
        await self._mutate(revision, operation)

    async def async_edit_widget(
        self, revision: int, entry_id: str, scene_path: str, page_index: int,
        widget_index: int, field: str, value: str, command_index: int = 0,
    ) -> None:
        """Change a documented widget caption or existing command mapping."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = edit_widget(
                draft["files"], scene_path, page_index, widget_index,
                field=field, value=value, command_index=command_index,
            )
        await self._mutate(revision, operation)

    async def async_edit_widget_layout(
        self, revision: int, entry_id: str, scene_path: str, page_index: int,
        widget_index: int, settings: dict[str, Any],
    ) -> None:
        """Edit widget placement within one private HA draft revision."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = edit_widget_layout(
                draft["files"], scene_path, page_index, widget_index, settings
            )
        await self._mutate(revision, operation)

    async def async_edit_button_map(
        self, revision: int, entry_id: str, scene_path: str, page_index: int,
        key: str, event: str, command: str,
    ) -> None:
        """Change a documented physical key event mapping in an HA-only draft."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = edit_button_map(
                draft["files"], scene_path, page_index, key=key,
                event=event, command=command,
            )
        await self._mutate(revision, operation)

    def review_snapshot(self, entry_id: str) -> tuple[dict[str, Any], dict[str, str]]:
        """Build read-only plan and capture source files needed for drift check.

        Only changed draft paths that existed at import need their source
        content checked. No configuration bytes are returned over WebSocket.
        """
        draft = self._state["drafts"].get(entry_id)
        if draft is None:
            raise WorkspaceError("Import a remote before reviewing a deployment")
        report = make_review(draft["files"], draft["base_files"])
        report["revision"] = self._state["revision"]
        originals = {
            item["path"]: draft["base_files"][item["path"]]
            for item in report["changed_files"]
            if item["before_sha256"] is not None
        }
        return report, originals

    def release_snapshot(
        self, entry_id: str
    ) -> tuple[dict[str, Any], dict[str, str], dict[str, str], dict[str, str]]:
        """Capture one immutable view of proposed, baseline and review revision.

        This copies state before any awaits in the HTTP drift verification.
        Changed-path originals are included separately for efficient API reads.
        """
        state = self._read()
        draft = state["drafts"].get(entry_id)
        if draft is None:
            raise WorkspaceError("Import this remote before downloading a release kit")
        proposed = draft["files"]
        baseline = draft["base_files"]
        report = make_review(proposed, baseline)
        report["revision"] = state["revision"]
        originals = {
            item["path"]: baseline[item["path"]]
            for item in report["changed_files"]
            if item["before_sha256"] is not None
        }
        return report, proposed, baseline, originals

    async def async_save_reviewed(
        self, expected_revision: int, entry_id: str,
        expected_sha256: str, *, live_checked: bool,
    ) -> dict[str, Any]:
        """Pin one explicitly reviewed HA-only configuration per remote.

        This operation never calls the device. Previous imported backups live
        in the independent backup history store and remain untouched.
        """
        if type(live_checked) is not bool:
            raise WorkspaceError("Invalid live verification selection")

        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Import a remote before saving a reviewed copy")
            files = draft["files"]
            check_bundle_limits(files)
            digest = file_digest(files)
            if digest != expected_sha256:
                raise WorkspaceError("Draft changed since review; rerun preflight")
            report = make_review(files, draft["base_files"])
            if report["errors"]:
                raise WorkspaceError("Fix validation errors before retaining a review")
            if not report["changed_count"]:
                raise WorkspaceError("No reviewed changes to retain")
            reviewed = state.setdefault("reviewed", {})
            if entry_id not in reviewed and len(reviewed) >= MAX_DRAFTS:
                raise WorkspaceError("Too many reviewed remote configurations")
            reviewed[entry_id] = {
                "saved_at": _now(),
                "sha256": digest,
                "baseline_sha256": report["baseline_sha256"],
                "review_status": (
                    "remote-checked" if live_checked else "offline-unverified"
                ),
                "files": dict(files),
            }
        await self._mutate(expected_revision, operation)
        return self.summary()["reviewed"][entry_id]

    def reviewed_snapshot(self, entry_id: str) -> dict[str, str]:
        """Return a validated copy for a future authenticated resend flow."""
        record = self._state.get("reviewed", {}).get(entry_id)
        if record is None:
            raise WorkspaceError("No reviewed configuration saved for this remote")
        meta = _reviewed_summary(record, None)
        if meta["integrity"] != "verified":
            raise WorkspaceError("Reviewed configuration is damaged")
        return deepcopy(record["files"])

    def diff(self, entry_id: str, path: str | None = None) -> dict[str, Any]:
        """Inspect local draft changes without exposing other configuration."""
        draft = self._state["drafts"].get(entry_id)
        if draft is None:
            raise WorkspaceError("Import a remote before comparing files")
        return draft_diff(draft["files"], draft["base_files"], path=path)

    async def async_revert_file(
        self, revision: int, entry_id: str, path: str,
    ) -> None:
        """Restore one draft file to its imported original; never touch firmware."""
        def operation(state):
            draft = state["drafts"].get(entry_id)
            if draft is None:
                raise WorkspaceError("Missing local draft")
            draft["files"] = revert_draft_file(
                draft["files"], draft["base_files"], path
            )
        await self._mutate(revision, operation)
