"""Firmware-native scene, page and physical-button editor for HA-only drafts.

OMOTE configuration is a graph:
    Scenes.json -> Scenes/*.json -> Pages/*.json -> Commands/*.json
The editor changes only existing documented fields and preserves other keys.
No firmware transport, Home Assistant imports or network access occurs here.
"""
from __future__ import annotations

import difflib
from typing import Any

from .safe_files import is_exportable_json
from .layout_model import layout_description, update_widget_layout
from .workspace_model import WorkspaceError, check_bundle_limits, dump_json, parse_jsonc

# Exact KeyPressAbstract::KeyId names in waveshare28v2-port.
KEY_IDS = (
    "Power", "Stop", "Rewind", "Play", "FastForward", "Menu", "Info",
    "Back", "Source", "Up", "Down", "Left", "Right", "Center",
    "VolUp", "VolDown", "Mute", "Record", "ChannelUp", "ChannelDown",
    "Aux1", "Aux2", "Aux3", "Aux4", "Guide", "Home", "Cycle", "Exit",
    "Pause", "TV", "Stream", "STB", "Audio", "BluRay", "DVD",
)
PRESS_TYPES = ("Press", "Release", "Repeat", "Short", "Long")
# Only use scene-binding event types actually implemented by the firmware.
SCENE_EVENTS = PRESS_TYPES
EDITABLE_WIDGET_TYPES = ("Button", "ColorButtons", "NumberPad", "Label")
MAX_DIFF_CHARS = 30_000


def _document(files: dict[str, str], path: str) -> dict:
    """Load a safe firmware JSON object and reject missing files."""
    if path not in files or not is_exportable_json(path):
        raise WorkspaceError(f"Configuration file is missing: {path}")
    doc = parse_jsonc(files[path])
    if not isinstance(doc, dict):
        raise WorkspaceError(f"Expected JSON object: {path}")
    return doc


def _label(value: Any, name: str, max_length: int = 80, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > max_length or (
        not empty and not value.strip()
    ):
        raise WorkspaceError(f"{name} must be 1–{max_length} characters")
    return value.strip()


def _scene(files: dict[str, str], scene_path: str) -> tuple[dict, dict, dict]:
    if not isinstance(scene_path, str) or not scene_path.startswith("Scenes/"):
        raise WorkspaceError("Select a scene from Scenes.json")
    index = _document(files, "Scenes.json")
    entries = index.get("Scenes")
    if not isinstance(entries, list):
        raise WorkspaceError("Scenes.json is missing its Scenes array")
    found = [item for item in entries
             if isinstance(item, dict) and item.get("FileName") == scene_path]
    if len(found) != 1:
        raise WorkspaceError("Scene reference missing or duplicated")
    return index, found[0], _document(files, scene_path)


def _page(
    files: dict[str, str], scene_path: str, page_index: int
) -> tuple[dict, dict, str, dict]:
    _, _, scene = _scene(files, scene_path)
    pages = scene.get("Pages")
    if not isinstance(pages, list) or type(page_index) is not int or not (
        0 <= page_index < len(pages)
    ):
        raise WorkspaceError("Invalid scene page index")
    item = pages[page_index]
    if not isinstance(item, dict):
        raise WorkspaceError("Invalid scene page entry")
    path = item.get("FileName")
    if not isinstance(path, str) or not path.startswith("Pages/"):
        raise WorkspaceError("Invalid page file reference")
    return scene, item, path, _document(files, path)


def _command_names(files: dict[str, str], page: dict, prefix: str) -> list[str]:
    path = page.get("CommandFile")
    if not isinstance(path, str) or not path.startswith("Commands/"):
        return []
    command_file = _document(files, path)
    commands = command_file.get("Commands", [])
    if not isinstance(commands, list):
        return []
    names = []
    for cmd in commands:
        name = cmd.get("Command") if isinstance(cmd, dict) else None
        if isinstance(name, str) and name.startswith(prefix):
            names.append(name[len(prefix):])
    return sorted(set(names))


def scene_detail(files: dict[str, str], scene_path: str) -> dict[str, Any]:
    """Return a bounded editor view with page/widget/key assignments."""
    _, entry, scene = _scene(files, scene_path)
    pages = scene.get("Pages", [])
    if not isinstance(pages, list):
        raise WorkspaceError("Invalid scene Pages array")
    result = []
    for ix, item in enumerate(pages):
        if not isinstance(item, dict):
            raise WorkspaceError(f"Invalid page at index {ix}")
        _, _, path, page = _page(files, scene_path, ix)
        prefix = item.get("CommandPrefix", "")
        if not isinstance(prefix, str):
            raise WorkspaceError("CommandPrefix is not text")
        widgets = page.get("Widgets", [])
        if not isinstance(widgets, list):
            raise WorkspaceError("Invalid Widgets array")
        maps = page.get("ButtonMaps", {})
        if not isinstance(maps, dict):
            raise WorkspaceError("Invalid ButtonMaps object")
        widget_rows = []
        for widget_ix, widget in enumerate(widgets):
            if not isinstance(widget, dict):
                continue
            widget_rows.append({
                "index": widget_ix,
                "type": widget.get("Type", ""),
                "text": widget.get("Text", ""),
                "command": widget.get("Command"),
                "editable_text": widget.get("Type") in ("Button", "Label")
                                 and isinstance(widget.get("Text"), str),
                "editable_command": widget.get("Type") in EDITABLE_WIDGET_TYPES
                                    and isinstance(widget.get("Command"), (str, list)),
                "layout": layout_description(widget),
            })
        result.append({
            "index": ix,
            "name": item.get("PageName", path),
            "short_name": item.get("ShortName", ""),
            "path": path,
            "command_prefix": prefix,
            "command_file": page.get("CommandFile", ""),
            "command_options": _command_names(files, page, prefix),
            "override_keys": item.get("OverrideKeys", []),
            "widgets": widget_rows,
            "button_maps": {
                key: events for key, events in maps.items()
                if key in KEY_IDS and isinstance(events, dict)
            },
        })
    return {
        "scene_path": scene_path,
        "scene_name": entry.get("SceneName", ""),
        "screen_name": scene.get("ScreenName", ""),
        "bind_to_key": entry.get("BindToKey", ""),
        "press_type": entry.get("PressType", "Press"),
        "keys": list(KEY_IDS),
        "event_types": list(PRESS_TYPES),
        "pages": result,
    }


def _write(files: dict[str, str], docs: dict[str, dict]) -> dict[str, str]:
    """Return a complete, capacity-checked new draft without mutating files."""
    result = dict(files)
    for path, doc in docs.items():
        result[path] = dump_json(doc)
    check_bundle_limits(result)
    return result


def edit_scene(
    files: dict[str, str],
    scene_path: str,
    *,
    name: str,
    screen_name: str,
    bind_key: str,
    press_type: str,
) -> dict[str, str]:
    """Edit scene title and optional physical launch shortcut."""
    index, entry, scene = _scene(files, scene_path)
    name = _label(name, "Scene name")
    screen_name = _label(screen_name, "Screen title")
    if bind_key and bind_key not in KEY_IDS:
        raise WorkspaceError("Unknown physical button")
    if bind_key and press_type not in SCENE_EVENTS:
        raise WorkspaceError("Unsupported scene key event")
    for other in index["Scenes"]:
        if other is not entry and isinstance(other, dict):
            if other.get("SceneName") == name:
                raise WorkspaceError("Another scene already has that name")
            if bind_key and other.get("BindToKey") == bind_key and other.get("PressType", "Press") == press_type:
                raise WorkspaceError("Another scene already uses that key and event")
    entry["SceneName"] = name
    if bind_key:
        entry["BindToKey"] = bind_key
        entry["PressType"] = press_type
    else:
        entry.pop("BindToKey", None)
        entry.pop("PressType", None)
    scene["ScreenName"] = screen_name
    return _write(files, {"Scenes.json": index, scene_path: scene})


def edit_page_title(
    files: dict[str, str],
    scene_path: str,
    page_index: int,
    *,
    name: str,
    short_name: str,
) -> dict[str, str]:
    """Edit the scene's page/tab labels, leaving shared page definitions alone."""
    scene, entry, _, _ = _page(files, scene_path, page_index)
    entry["PageName"] = _label(name, "Page name")
    entry["ShortName"] = _label(short_name, "Tab label", 32, empty=True)
    return _write(files, {scene_path: scene})


def _check_command(value: str, names: list[str]) -> str:
    value = _label(value, "Command", 128)
    if value not in names:
        raise WorkspaceError(
            f"Command {value!r} does not exist in this page's command file "
            "(after its scene prefix)"
        )
    return value


def edit_widget(
    files: dict[str, str],
    scene_path: str,
    page_index: int,
    widget_index: int,
    *,
    field: str,
    value: str,
    command_index: int = 0,
) -> dict[str, str]:
    """Change a Button/Label caption or one existing widget command slot."""
    _, entry, path, page = _page(files, scene_path, page_index)
    widgets = page.get("Widgets")
    if not isinstance(widgets, list) or type(widget_index) is not int or not (
        0 <= widget_index < len(widgets)
    ):
        raise WorkspaceError("Invalid widget index")
    widget = widgets[widget_index]
    if not isinstance(widget, dict):
        raise WorkspaceError("Invalid widget")
    kind = widget.get("Type")
    if field == "text":
        if kind not in ("Button", "Label") or not isinstance(widget.get("Text"), str):
            raise WorkspaceError("This widget has no editable text caption")
        widget["Text"] = _label(value, "Widget text", 100, empty=True)
    elif field == "command":
        if kind not in EDITABLE_WIDGET_TYPES or "Command" not in widget:
            raise WorkspaceError("This widget has no editable command")
        prefix = entry.get("CommandPrefix", "")
        names = _command_names(files, page, prefix)
        command = _check_command(value, names)
        current = widget["Command"]
        if isinstance(current, str):
            if command_index != 0:
                raise WorkspaceError("Single-command widget index must be zero")
            widget["Command"] = command
        elif isinstance(current, list):
            if (type(command_index) is not int or command_index < 0
                    or command_index >= len(current)):
                raise WorkspaceError("Invalid command array position")
            current[command_index] = command
        else:
            raise WorkspaceError("Unsupported widget command shape")
    else:
        raise WorkspaceError("Widget field must be text or command")
    return _write(files, {path: page})


def edit_widget_layout(
    files: dict[str, str],
    scene_path: str,
    page_index: int,
    widget_index: int,
    settings: dict[str, Any],
) -> dict[str, str]:
    """Change existing widget coordinates/sizing in one HA-only draft file.

    The same page can be referenced by multiple scenes; edit is deliberately
    made against the referenced page JSON rather than against a scene copy.
    """
    _, _, path, page = _page(files, scene_path, page_index)
    widgets = page.get("Widgets")
    if not isinstance(widgets, list) or type(widget_index) is not int or not (
        0 <= widget_index < len(widgets)
    ):
        raise WorkspaceError("Invalid widget index")
    widgets[widget_index] = update_widget_layout(
        widgets[widget_index], settings, widget_index
    )
    return _write(files, {path: page})


def edit_button_map(
    files: dict[str, str],
    scene_path: str,
    page_index: int,
    *,
    key: str,
    event: str,
    command: str,
) -> dict[str, str]:
    """Create/update/clear one physical key + press-event command mapping."""
    _, entry, path, page = _page(files, scene_path, page_index)
    if key not in KEY_IDS:
        raise WorkspaceError("Invalid physical key name")
    if event not in PRESS_TYPES:
        raise WorkspaceError("Unsupported key event")
    if not isinstance(command, str):
        raise WorkspaceError("Command must be text")
    button_maps = page.setdefault("ButtonMaps", {})
    if not isinstance(button_maps, dict):
        raise WorkspaceError("Page ButtonMaps must be an object")
    if command:
        names = _command_names(files, page, entry.get("CommandPrefix", ""))
        value = _check_command(command, names)
        existing = button_maps.setdefault(key, {})
        if not isinstance(existing, dict):
            raise WorkspaceError("Existing key mapping is invalid")
        existing[event] = value
    elif key in button_maps:
        events = button_maps[key]
        if not isinstance(events, dict):
            raise WorkspaceError("Existing key mapping is invalid")
        events.pop(event, None)
        if not events:
            button_maps.pop(key)
    return _write(files, {path: page})


def draft_diff(
    files: dict[str, str], original_files: dict[str, str],
    path: str | None = None,
) -> dict[str, Any]:
    """Return only the differences between imported and edited HA draft files.

    A paginated/size-bounded unified diff is for review only, not deployment.
    """
    check_bundle_limits(files)
    changed = sorted(p for p in files.keys() | original_files.keys()
                     if files.get(p) != original_files.get(p))
    if path is None:
        return {
            "changed_files": changed,
            "count": len(changed),
            "total_files": len(files),
        }
    if not is_exportable_json(path) or path not in changed:
        raise WorkspaceError("Select a modified configuration file")
    before = original_files.get(path, "")
    after = files.get(path, "")
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"imported/{path}",
        tofile=f"draft/{path}",
        n=3,
    )
    chunks = []
    size = 0
    truncated = False
    for line in lines:
        if size + len(line) > MAX_DIFF_CHARS:
            truncated = True
            break
        chunks.append(line)
        size += len(line)
    return {
        "path": path,
        "diff": "".join(chunks),
        "truncated": truncated,
        "count": len(changed),
        "changed_files": changed,
    }


def revert_draft_file(
    files: dict[str, str], original_files: dict[str, str], path: str
) -> dict[str, str]:
    """Revert one local file; template-added files are removed from the draft.

    No firmware file is ever touched.
    """
    if path not in files or not is_exportable_json(path):
        raise WorkspaceError("Unknown or unsafe draft file")
    updated = dict(files)
    if path in original_files:
        updated[path] = original_files[path]
    else:
        del updated[path]
    check_bundle_limits(updated)
    return updated
