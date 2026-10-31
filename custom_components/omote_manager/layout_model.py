"""Safe, firmware-native widget layout controls for OMOTE's Waveshare port.

JsonPage.cpp applies percentage-based SizeXY, PosX/PosY and HeightPct to most
widgets; Title/Label use HeightPct/AlignTo, and Image uses PosX/PosY, AlignTo
and a separate SizeXYinPixels (not edited here).

The module never accesses a device or mutates the original imported document.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .workspace_model import WorkspaceError

FULL_LAYOUT = frozenset({
    "Button", "ColorButtons", "NumberPad",
    "HaToggle", "HaLabel", "HaSwitch", "HaSlider",
    "HaMomentary", "HaClimate",
})
TEXT_LAYOUT = frozenset({"Title", "Label"})
IMAGE_LAYOUT = frozenset({"Image"})
SUPPORTED_LAYOUT = FULL_LAYOUT | TEXT_LAYOUT | IMAGE_LAYOUT


def _percentage(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > 100:
        raise WorkspaceError(f"{field} must be an integer from {minimum} to 100")
    return value


def _optional_percentage(value: Any, field: str, *, minimum: int = 1) -> int | None:
    if value is None:
        return None
    return _percentage(value, field, minimum=minimum)


def layout_description(widget: dict) -> dict[str, Any]:
    """Describe existing firmware layout keys without rewriting JSON."""
    kind = widget.get("Type", "")
    size = widget.get("SizeXY")
    valid_size = (
        isinstance(size, list) and len(size) == 2
        and all(type(v) is int and 0 <= v <= 100 for v in size)
    )
    width = size[0] if valid_size and size[0] else None
    height = size[1] if valid_size and size[1] else widget.get("HeightPct")
    if type(height) is not int or height <= 0:
        height = None

    absolute = "PosX" in widget or "PosY" in widget
    aligned = "AlignTo" in widget
    return {
        "supported": kind in SUPPORTED_LAYOUT,
        "can_position": kind in (FULL_LAYOUT | IMAGE_LAYOUT),
        "can_size_pct": kind in FULL_LAYOUT,
        "can_height_pct": kind in (FULL_LAYOUT | TEXT_LAYOUT),
        "image_size_px": widget.get("SizeXYinPixels") if kind == "Image" else None,
        "mode": "absolute" if absolute else ("align" if aligned else "flow"),
        "align_to": widget.get("AlignTo", 0),
        "x_pct": widget.get("PosX", 0),
        "y_pct": widget.get("PosY", 0),
        "width_pct": width if kind in FULL_LAYOUT else None,
        "height_pct": height if kind in (FULL_LAYOUT | TEXT_LAYOUT) else None,
        "height_note": "minimum 10% at runtime" if kind in FULL_LAYOUT else "",
    }


def update_widget_layout(
    widget: dict, settings: dict[str, Any], widget_index: int
) -> dict:
    """Apply only supported OMOTE layout fields to a copy of a widget.

    'flow' removes explicit layout properties. 'align' anchors to top or an
    earlier widget. 'absolute' writes PosX/PosY percentages and removes AlignTo.
    The UI uses the configured percentages to approximate a visual layout.
    """
    if not isinstance(widget, dict):
        raise WorkspaceError("Widget must be an object")
    kind = widget.get("Type")
    if kind not in SUPPORTED_LAYOUT:
        raise WorkspaceError(f"Layout editing is not supported for {kind!r}")

    mode = settings.get("mode")
    if mode not in ("flow", "align", "absolute"):
        raise WorkspaceError("Layout mode must be flow, align or absolute")
    if mode == "absolute" and kind in TEXT_LAYOUT:
        raise WorkspaceError("Title/Label widgets do not support PosX/PosY")
    align_to = settings.get("align_to", 0)
    if type(align_to) is not int or not (0 <= align_to <= widget_index):
        raise WorkspaceError("AlignTo must point to top (0) or an earlier widget")
    x_pct = _percentage(settings.get("x_pct", 0), "PosX")
    y_pct = _percentage(settings.get("y_pct", 0), "PosY")

    if kind in IMAGE_LAYOUT:
        if settings.get("width_pct") is not None or settings.get("height_pct") is not None:
            raise WorkspaceError("Image uses pixel dimensions, not SizeXY percentages")
    elif kind in TEXT_LAYOUT:
        if settings.get("width_pct") is not None:
            raise WorkspaceError("Title/Label do not support SizeXY percentage width")
        _optional_percentage(settings.get("height_pct"), "HeightPct", minimum=1)
    else:
        _optional_percentage(settings.get("width_pct"), "Width", minimum=1)
        # Firmware clamps positive heights below 10% to 10%.
        _optional_percentage(settings.get("height_pct"), "Height", minimum=1)

    changed = deepcopy(widget)
    for key in ("AlignTo", "PosX", "PosY"):
        changed.pop(key, None)
    if mode == "align":
        changed["AlignTo"] = align_to
    elif mode == "absolute":
        changed["PosX"] = x_pct
        changed["PosY"] = y_pct

    if kind in FULL_LAYOUT:
        changed.pop("HeightPct", None)
        changed.pop("SizeXY", None)
        width = settings.get("width_pct")
        height = settings.get("height_pct")
        if width is not None:
            # JsonPage::applyWidgetLayout calls SetSize(lv_pct(x),lv_pct(y)).
            # A zero second value instructs it to set width only.
            changed["SizeXY"] = [width, height or 0]
        elif height is not None:
            changed["HeightPct"] = height
    elif kind in TEXT_LAYOUT:
        changed.pop("HeightPct", None)
        height = settings.get("height_pct")
        if height is not None:
            changed["HeightPct"] = height

    return changed
