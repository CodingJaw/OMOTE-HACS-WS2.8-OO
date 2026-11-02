"""Pure, firmware-compatible configuration model for OMOTE draft editing.

This file has no Home Assistant dependencies so it can be exercised against the
actual firmware JSON fixtures. It does not read or write firmware storage.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .safe_files import is_exportable_json

MAX_FILES = 256
MAX_TOTAL_BYTES = 512 * 1024
MAX_FILE_BYTES = 64 * 1024


class WorkspaceError(ValueError):
    """Invalid draft operation or configuration."""


def parse_jsonc(text: str) -> Any:
    """Parse JSON with // and /* */ comments as accepted by OMOTE's parser.

    Comments inside quoted strings are preserved. An unclosed block comment
    raises an error rather than silently discarding data.
    """
    result: list[str] = []
    index = 0
    quote = False
    escape = False
    length = len(text)
    while index < length:
        ch = text[index]
        if quote:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                quote = False
            index += 1
            continue
        if ch == '"':
            quote = True
            result.append(ch)
            index += 1
            continue
        if ch == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] not in "\r\n":
                index += 1
            result.append(" ")
            continue
        if ch == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            block_closed = False
            while index + 1 < length:
                if text[index:index + 2] == "*/":
                    index += 2
                    block_closed = True
                    break
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            if not block_closed:
                raise WorkspaceError("Unterminated block comment")
            result.append(" ")
            continue
        result.append(ch)
        index += 1
    try:
        return json.loads("".join(result))
    except json.JSONDecodeError as exc:
        raise WorkspaceError(
            f"Invalid OMOTE JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def dump_json(document: Any) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def file_digest(files: dict[str, str]) -> str:
    """Deterministic digest independent of dictionary insertion order."""
    digest = hashlib.sha256()
    for path, body in sorted(files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(body.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def check_bundle_limits(files: dict[str, str]) -> None:
    if len(files) > MAX_FILES:
        raise WorkspaceError("Too many configuration files")
    size = 0
    for path, raw in files.items():
        if not is_exportable_json(path):
            raise WorkspaceError(f"File is not an allowed configuration path: {path}")
        if not isinstance(raw, str):
            raise WorkspaceError(f"Configuration content is not text: {path}")
        this_size = len(raw.encode("utf-8"))
        if this_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"File exceeds 64 KiB: {path}")
        size += this_size
        if size > MAX_TOTAL_BYTES:
            raise WorkspaceError("Configuration snapshot exceeds 512 KiB")


def editable_commands(files: dict[str, str], path: str) -> list[dict[str, Any]]:
    """Read command definitions without modifying the original JSON text."""
    if not path.startswith("Commands/") or not is_exportable_json(path):
        raise WorkspaceError("Select a Commands/*.json file")
    if path not in files:
        raise WorkspaceError("Command file is missing from the draft")
    doc = parse_jsonc(files[path])
    if not isinstance(doc, dict) or not isinstance(doc.get("Commands"), list):
        raise WorkspaceError("Command file must contain a Commands array")
    return deepcopy(doc["Commands"])


def edit_command(
    files: dict[str, str],
    path: str,
    name: str,
    mode: str,
    protocol: str,
    data: list[str],
) -> dict[str, str]:
    """Edit only Mode/Protocol/Data on a named command in a draft.

    Any unknown fields are retained; comments in this ONE edited file are
    normalized away when serialized, while untouched files remain byte-exact.
    """
    if not isinstance(name, str) or not name:
        raise WorkspaceError("Select a command")
    if not isinstance(protocol, str) or not (0 < len(protocol) <= 80):
        raise WorkspaceError("Protocol must be 1–80 characters")
    if not isinstance(data, list) or len(data) > 16 or not all(
        isinstance(part, str) and len(part) <= 8192 for part in data
    ):
        raise WorkspaceError("Data must contain no more than 16 strings")
    if mode not in ("IR", "MQTT"):
        raise WorkspaceError("Only firmware-supported IR and MQTT modes are editable")
    if mode == "IR" and not data:
        raise WorkspaceError("IR commands require at least one data value")
    if mode == "MQTT" and protocol == "PUB" and len(data) != 2:
        raise WorkspaceError("MQTT PUB requires topic and payload")
    if mode == "MQTT" and protocol == "SUB" and len(data) != 4:
        raise WorkspaceError("MQTT SUB requires four values")
    if mode == "MQTT" and protocol not in ("PUB", "SUB"):
        raise WorkspaceError("MQTT protocol must be PUB or SUB")

    commands = editable_commands(files, path)
    hits = [command for command in commands
            if isinstance(command, dict) and command.get("Command") == name]
    if len(hits) != 1:
        raise WorkspaceError("Command missing or ambiguous (duplicate name)")
    hits[0].update({"Mode": mode, "Protocol": protocol, "Data": data})
    doc = parse_jsonc(files[path])
    doc["Commands"] = commands
    changed = dict(files)
    changed[path] = dump_json(doc)
    check_bundle_limits(changed)
    return changed


def _issue(level: str, path: str, message: str) -> dict[str, str]:
    return {"level": level, "path": path, "message": message}


def validate_bundle(files: dict[str, str]) -> list[dict[str, str]]:
    """Check structure and cross-file references using real OMOTE JSON shapes.

    Does not pretend to validate all firmware-specific widget/IR semantics.
    Unknown widget keys remain supported.
    """
    issues: list[dict[str, str]] = []
    try:
        check_bundle_limits(files)
    except WorkspaceError as exc:
        return [_issue("error", "", str(exc))]
    parsed: dict[str, dict] = {}
    for path, text in sorted(files.items()):
        try:
            doc = parse_jsonc(text)
            if not isinstance(doc, dict):
                raise WorkspaceError("Top-level JSON must be an object")
            parsed[path] = doc
        except WorkspaceError as exc:
            issues.append(_issue("error", path, str(exc)))

    def reference(path: str, ref: Any, expected_prefix: str) -> str | None:
        if not isinstance(ref, str) or not ref.startswith(expected_prefix):
            issues.append(_issue("error", path, f"Invalid reference: {ref!r}"))
            return None
        if ref not in files:
            issues.append(_issue("error", path, f"Referenced file not found: {ref}"))
            return None
        if ref not in parsed:
            issues.append(_issue("error", path, f"Referenced file could not be parsed: {ref}"))
            return None
        return ref

    command_names: dict[str, set[str]] = {}
    for path, doc in parsed.items():
        if not path.startswith("Commands/"):
            continue
        commands = doc.get("Commands")
        if not isinstance(commands, list):
            issues.append(_issue("error", path, "Expected Commands array"))
            continue
        seen: set[str] = set()
        for ix, command in enumerate(commands):
            label = f"Commands[{ix}]"
            if not isinstance(command, dict):
                issues.append(_issue("error", path, f"{label} is not an object"))
                continue
            name = command.get("Command")
            mode = command.get("Mode")
            protocol = command.get("Protocol")
            data = command.get("Data")
            if not isinstance(name, str) or not name:
                issues.append(_issue("error", path, f"{label}: missing Command name"))
            elif name in seen:
                issues.append(_issue("error", path, f"Duplicate command: {name}"))
            else:
                seen.add(name)
            if mode not in ("IR", "MQTT"):
                issues.append(_issue("error", path, f"{label}: unsupported Mode {mode!r}"))
            if not isinstance(protocol, str) or not protocol:
                issues.append(_issue("error", path, f"{label}: Protocol must be a string"))
            if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
                issues.append(_issue("error", path, f"{label}: Data must be an array of strings"))
            elif mode == "MQTT" and protocol in ("PUB", "SUB"):
                expected = 2 if protocol == "PUB" else 4
                if len(data) != expected:
                    issues.append(_issue("error", path, f"{label}: MQTT {protocol} requires {expected} values"))
            elif mode == "IR" and not data:
                issues.append(_issue("error", path, f"{label}: IR data cannot be empty"))
        command_names[path] = seen

    scenes_index = parsed.get("Scenes.json")
    if scenes_index is None:
        issues.append(_issue("error", "Scenes.json", "Scenes.json is required"))
    elif not isinstance(scenes_index.get("Scenes"), list):
        issues.append(_issue("error", "Scenes.json", "Expected Scenes array"))
    else:
        indexed_paths: set[str] = set()
        for item in scenes_index["Scenes"]:
            if not isinstance(item, dict):
                issues.append(_issue("error", "Scenes.json", "Scene entry must be an object"))
                continue
            scene_file = item.get("FileName")
            if isinstance(scene_file, str):
                if scene_file in indexed_paths:
                    issues.append(_issue(
                        "error", "Scenes.json",
                        f"Duplicate scene file in index: {scene_file}"
                    ))
                indexed_paths.add(scene_file)
            reference("Scenes.json", scene_file, "Scenes/")

    def ensure_command(path: str, filename: str, name: Any) -> None:
        if not isinstance(name, str) or not name:
            issues.append(_issue("error", path, "Invalid command reference"))
        elif filename in command_names and name not in command_names[filename]:
            issues.append(_issue("error", path, f"Command {name!r} not found in {filename}"))

    for path, doc in parsed.items():
        if not path.startswith("Scenes/"):
            continue
        pages = doc.get("Pages", [])
        if not isinstance(pages, list):
            issues.append(_issue("error", path, "Pages must be an array"))
            continue
        for item in pages:
            if not isinstance(item, dict):
                issues.append(_issue("error", path, "Page item must be an object"))
                continue
            page_path = reference(path, item.get("FileName"), "Pages/")
            if page_path is None:
                continue
            page = parsed[page_path]
            commandfile = page.get("CommandFile")
            if commandfile is not None:
                checked = reference(page_path, commandfile, "Commands/")
                if checked is not None:
                    prefix = item.get("CommandPrefix", "")
                    if not isinstance(prefix, str):
                        issues.append(_issue("error", path, "CommandPrefix must be text"))
                        prefix = ""
                    widgets = page.get("Widgets", [])
                    if not isinstance(widgets, list):
                        issues.append(_issue("error", page_path, "Widgets must be an array"))
                        widgets = []
                    for widget in widgets:
                        if not isinstance(widget, dict) or "Command" not in widget:
                            continue
                        cmds = widget["Command"]
                        for cmd in (cmds if isinstance(cmds, list) else [cmds]):
                            ensure_command(page_path, checked, prefix + str(cmd))
                    button_maps = page.get("ButtonMaps", {})
                    if not isinstance(button_maps, dict):
                        issues.append(_issue("error", page_path, "ButtonMaps must be an object"))
                        button_maps = {}
                    for event_map in button_maps.values():
                        if isinstance(event_map, dict):
                            for cmd in event_map.values():
                                if isinstance(cmd, str):
                                    ensure_command(page_path, checked, prefix + cmd)
        for sequence in ("StartCommandSequence", "ExitCommandSequence"):
            actions = doc.get(sequence, [])
            if not isinstance(actions, list):
                issues.append(_issue("error", path, f"{sequence} must be an array"))
                continue
            for command in actions:
                if not isinstance(command, dict):
                    issues.append(_issue("error", path, f"{sequence} entry must be an object"))
                    continue
                filename = reference(path, command.get("CommandFile"), "Commands/")
                if filename:
                    ensure_command(path, filename, command.get("Command"))

    # Directly included pages not necessarily referenced by an indexed scene.
    for path, doc in parsed.items():
        if not path.startswith("Pages/"):
            continue
        if "CommandFile" in doc:
            reference(path, doc["CommandFile"], "Commands/")
        widgets = doc.get("Widgets", [])
        if isinstance(widgets, list) and any(
            isinstance(widget, dict)
            and (
                str(widget.get("Type", "")).casefold() == "image"
                or "ImagePath" in widget
                or "ImageFile" in widget
            )
            for widget in widgets
        ):
            issues.append(_issue(
                "warning", path,
                "Image widget assets are not included in JSON-only HA snapshots; "
                "the future secure deployment must verify their binary dependencies"
            ))
    return issues


def available_scenes(files: dict[str, str]) -> list[dict[str, str]]:
    """Return selectable scene entries (without exposing arbitrary JSON blobs)."""
    raw = files.get("Scenes.json")
    if not raw:
        return []
    try:
        index = parse_jsonc(raw)
    except WorkspaceError:
        return []
    if not isinstance(index, dict) or not isinstance(index.get("Scenes"), list):
        return []
    return [
        {"name": obj.get("SceneName", obj["FileName"]), "path": obj["FileName"]}
        for obj in index["Scenes"]
        if isinstance(obj, dict)
        and isinstance(obj.get("FileName"), str)
        and obj["FileName"].startswith("Scenes/")
        and obj["FileName"] in files
    ]


def extract_scene_template(files: dict[str, str], scene_path: str) -> tuple[dict, dict[str, str]]:
    """Extract a scene and transitively referenced page/command files.

    Scenes.json itself is not included: the entry is carried separately so
    template application can append it without replacing the target index.
    """
    index = parse_jsonc(files.get("Scenes.json", ""))
    if not isinstance(index, dict) or not isinstance(index.get("Scenes"), list):
        raise WorkspaceError("Scenes.json must have a Scenes array")
    matches = [item for item in index["Scenes"] if isinstance(item, dict)
               and item.get("FileName") == scene_path]
    if len(matches) != 1:
        raise WorkspaceError("Scene must have exactly one index entry")
    if scene_path not in files or not scene_path.startswith("Scenes/"):
        raise WorkspaceError("Selected scene file is missing")
    scene = parse_jsonc(files[scene_path])
    if not isinstance(scene, dict):
        raise WorkspaceError("Scene must be an object")
    paths = {scene_path}
    pages = scene.get("Pages", [])
    if not isinstance(pages, list):
        raise WorkspaceError("Scene Pages must be an array")
    for item in pages:
        if not isinstance(item, dict) or not isinstance(item.get("FileName"), str):
            raise WorkspaceError("Invalid scene page")
        page_path = item["FileName"]
        if not page_path.startswith("Pages/") or page_path not in files:
            raise WorkspaceError(f"Missing page: {page_path}")
        paths.add(page_path)
        page = parse_jsonc(files[page_path])
        if isinstance(page, dict) and "CommandFile" in page:
            commandfile = page["CommandFile"]
            if not isinstance(commandfile, str):
                raise WorkspaceError(f"Invalid command file in {page_path}")
            paths.add(commandfile)
    for key in ("StartCommandSequence", "ExitCommandSequence"):
        actions = scene.get(key, [])
        if not isinstance(actions, list):
            raise WorkspaceError(f"{key} must be an array")
        for command in actions:
            if isinstance(command, dict) and "CommandFile" in command:
                if not isinstance(command["CommandFile"], str):
                    raise WorkspaceError(f"Invalid command file in {key}")
                paths.add(command["CommandFile"])
    for path in paths:
        if path not in files or not is_exportable_json(path):
            raise WorkspaceError(f"Invalid scene dependency: {path}")
    bundle = {path: files[path] for path in sorted(paths)}
    check_bundle_limits(bundle)
    return deepcopy(matches[0]), bundle


def apply_scene_template(files: dict[str, str], scene_entry: dict,
                         template_files: dict[str, str]) -> dict[str, str]:
    """Copy a reusable scene into a local draft; never overwrite conflicts."""
    if "Scenes.json" not in files:
        raise WorkspaceError("Destination draft requires Scenes.json")
    if not isinstance(scene_entry, dict) or not isinstance(scene_entry.get("FileName"), str):
        raise WorkspaceError("Invalid template scene entry")
    if scene_entry["FileName"] not in template_files:
        raise WorkspaceError("Template does not contain its scene file")
    for path, raw in template_files.items():
        if path in files and files[path] != raw:
            raise WorkspaceError(
                f"Conflicting file {path}; existing draft was not changed"
            )
    index = parse_jsonc(files["Scenes.json"])
    if not isinstance(index, dict) or not isinstance(index.get("Scenes"), list):
        raise WorkspaceError("Destination Scenes.json is invalid")
    entry_path = scene_entry["FileName"]
    index_changed = True
    for other in index["Scenes"]:
        if not isinstance(other, dict):
            raise WorkspaceError("Invalid destination scene index")
        if (other.get("FileName") == entry_path or
                other.get("SceneName") == scene_entry.get("SceneName")):
            if other != scene_entry:
                raise WorkspaceError("Scene index already uses this name or file")
            index_changed = False
            break
    if index_changed:
        index["Scenes"].append(deepcopy(scene_entry))
    updated = dict(files)
    updated.update(template_files)
    if index_changed:
        # Only reserialize the index when adding a new scene.
        updated["Scenes.json"] = dump_json(index)
    check_bundle_limits(updated)
    return updated
