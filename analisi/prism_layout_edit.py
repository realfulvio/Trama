"""Edit verified panel destinations in the preserved EMF+ page."""
from base64 import b64encode
from collections import Counter, defaultdict
from math import isfinite
import os
from pathlib import Path
from struct import pack_into, unpack_from
from tempfile import NamedTemporaryFile

from .prism_binary_graphs import validate_binary_graph
from .prism_emf_edit import CURVE, POINTS, _emf_records, edit_emf_preview


PRISM_EDITABLE_PANELS = "Prism editable layout panels"
PRISM_PANEL_EDITS = "Prism layout panel edits"
PRISM_PANEL_DATA = "Prism layout panel data"


def _rect(bounds):
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) is not int or not -32768 <= v <= 32767 for v in bounds)):
        raise ValueError("Enter whole-number coordinates for the panel.")
    left, top, right, bottom = bounds
    if not 0 < right - left <= 32767 or not 0 < bottom - top <= 32767:
        raise ValueError("Enter a positive panel width and height within the layout.")
    return tuple(bounds)


def _destinations(raw):
    for kind, length, offset in _emf_records(raw):
        if kind != 70 or raw[offset + 12:offset + 16] != b"EMF+":
            continue
        cursor = offset + 16
        while cursor < offset + length:
            command, _, size, _ = unpack_from("<HHII", raw, cursor)
            if command == 0x401A:
                left, top, width, height = unpack_from("<4h", raw, cursor + 36)
                yield (left, top, left + width, top + height), (command, cursor + 36)
            elif command == 0x401B:
                x0, y0, x1, y1, x2, y2 = points = unpack_from("<6f", raw, cursor + 40)
                if all(isfinite(v) and abs(v - round(v)) < .01 for v in points):
                    left, top, right, upper, lower, bottom = map(round, (x0, y0, x1, y1, x2, y2))
                    if left == lower and top == upper:
                        yield (left, top, right, bottom), (command, cursor + 40)
            cursor += size


def _unique_destinations(raw):
    found = defaultdict(list)
    for bounds, binding in _destinations(raw):
        found[bounds].append(binding)
    return {bounds: matches[0] for bounds, matches in found.items() if len(matches) == 1}


def editable_panels(preview, placements, graph_titles, *, placements_complete=False):
    if not preview or preview.get("format") != "emf" or not 1 <= len(placements) <= 24:
        return []
    raw = validate_binary_graph(preview, layout=True)
    destinations = _unique_destinations(raw)
    counts = Counter(tuple(item["bounds"]) for item in placements)
    panels = []
    for index, item in enumerate(placements, 1):
        uid = item["graph_id"]
        bounds = tuple(item["bounds"])
        if uid is not None and counts[bounds] == 1 and bounds in destinations:
            panels.append({"id": str(index), "graph_id": uid, "title": graph_titles.get(uid, f"Panel {index}"),
                           "bounds": item["bounds"]})
    if panels or not placements_complete:
        return panels

    # The drawing can contain reflowed positions. A complete set of unique graph placeholders
    # and draws lets the user move the saved artwork even when source graph identities are unknown.
    if (len(destinations) != len(placements) or len(counts) != len(placements)
            or any(item["graph_id"] is None for item in placements)):
        return []
    try:
        for bounds in destinations:
            _rect(list(bounds))
    except ValueError:
        return []
    return [{"id": str(index), "graph_id": None, "title": f"Saved artwork {index}", "bounds": list(bounds)}
            for index, bounds in enumerate(destinations, 1)]


def _image_slots(raw, destinations):
    """Bind each image instance to its draw, including reused object IDs."""
    images, draws, counts = {}, {}, Counter()
    for kind, length, offset in _emf_records(raw):
        if kind != 70 or raw[offset + 12:offset + 16] != b"EMF+":
            continue
        cursor = offset + 16
        while cursor < offset + length:
            command, flags, size, _ = unpack_from("<HHII", raw, cursor)
            uid = flags & 255
            if command == 0x4008:
                images.pop(uid, None)
                if flags >> 8 == 5:
                    images[uid] = (cursor + 28, cursor + size)
            elif command in (0x401A, 0x401B):
                span = images[uid]
                counts[span] += 1
                draws[cursor + (36 if command == 0x401A else 40)] = span
            cursor += size
    return {bounds: draws[offset] for bounds, (_, offset) in destinations.items() if counts[draws[offset]] == 1}


def _preview(raw):
    return {"format": "emf", "data": b64encode(raw).decode("ascii")}


def layout_panel_artwork(preview, panels):
    """Return artwork for panels with an exclusive, verified image destination."""
    raw = validate_binary_graph(preview, layout=True)
    slots = _image_slots(raw, _unique_destinations(raw))
    return {panel["id"]: _preview(raw[start:stop])
            for panel in panels if (span := slots.get(tuple(panel["bounds"]))) is not None
            for start, stop in (span,)}


def edit_panel_artwork(frame, style, artwork):
    if style.get("kind") in (CURVE, POINTS):
        return edit_emf_preview(frame, style, artwork)
    if style.get("kind") == "columns":
        from .prism_binary_bars import edit_bar_preview

        return edit_bar_preview(frame, style, artwork)
    raise ValueError("This panel does not have a supported data drawing.")


def edited_layout_preview(preview, panels, edits, panel_data=None):
    if not edits and not panel_data:
        return preview
    edits = {} if edits is None else edits
    panel_data = {} if panel_data is None else panel_data
    if (not isinstance(edits, dict) or not isinstance(panels, list) or not 1 <= len(panels) <= 24
            or any(not isinstance(panel, dict) or not isinstance(panel.get("id"), str) for panel in panels)):
        raise ValueError("Invalid Prism layout edits.")
    original = {panel["id"]: _rect(panel.get("bounds")) for panel in panels}
    if (len(original) != len(panels) or len(set(original.values())) != len(original)
            or (edits.keys() | panel_data.keys()) - original.keys()):
        raise ValueError("Invalid Prism layout panel selection.")
    envelope = (min(b[0] for b in original.values()), min(b[1] for b in original.values()),
                max(b[2] for b in original.values()), max(b[3] for b in original.values()))
    raw = validate_binary_graph(preview, layout=True)
    destinations = _unique_destinations(raw)
    patched = bytearray(raw)
    if panel_data:
        slots = _image_slots(raw, destinations)
        for panel, (frame, style) in panel_data.items():
            if original[panel] not in slots:
                raise ValueError("The panel image cannot be edited independently.")
            start, stop = slots[original[panel]]
            updated = validate_binary_graph(edit_panel_artwork(frame, style, _preview(raw[start:stop])))
            if len(updated) != stop - start:
                raise ValueError("The edited panel changed the layout drawing structure.")
            patched[start:stop] = updated
    for panel, requested in edits.items():
        left, top, right, bottom = _rect(requested)
        if not (envelope[0] <= left < right <= envelope[2] and envelope[1] <= top < bottom <= envelope[3]):
            raise ValueError("Keep the panel within the original layout’s panel area.")
        if original[panel] not in destinations:
            raise ValueError("The panel could not be matched to the original Prism drawing.")
        if tuple(requested) == original[panel]:
            continue
        command, offset = destinations[original[panel]]
        if command == 0x401A:
            pack_into("<4h", patched, offset, left, top, right - left, bottom - top)
        else:
            pack_into("<6f", patched, offset, left, top, right, top, left, bottom)
    return preview if patched == raw else _preview(patched)


def export_edited_layout(path, preview, panels, edits, panel_data=None):
    """Save the current drawing as EMF, leaving the archived preview in the project intact."""
    path = Path(path)
    if path.suffix.lower() != ".emf":
        raise ValueError("Use an .emf file name for the layout drawing.")
    current = edited_layout_preview(preview, panels, edits, panel_data)
    data = validate_binary_graph(current, layout=True)
    temp = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(data)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
