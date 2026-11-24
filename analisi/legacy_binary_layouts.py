"""Recover the saved layouts in legacy PCFFGRA4 projects."""

from struct import Struct, unpack_from

from .legacy_binary import _records
from .legacy_binary_graphs import MAX_BINARY_GRAPH_TOTAL, _graph_index, _read_title, _stored_emf_preview


_MAX_LAYOUTS = 256
_MAX_OBJECTS = 256
_REFERENCE = Struct("<IH6s")


def _layout_index(payload):
    if len(payload) not in (10064, 10068):
        raise ValueError("Unsupported legacy binary layout index.")
    count, = unpack_from("<I", payload, 52)
    if count > _MAX_LAYOUTS:
        raise ValueError("Legacy binary layout count exceeds the limit.")
    ids = unpack_from(f"<{count}i", payload, 6060)
    if len(set(ids)) != count or any(not 0 <= uid <= 65535 for uid in ids):
        raise ValueError("Invalid legacy binary layout identifiers.")
    return dict.fromkeys(ids)


def _placement_references(payload):
    if not payload or len(payload) < 2:
        return None
    count, = unpack_from("<H", payload)
    if count > _MAX_OBJECTS or len(payload) != 2 + count * _REFERENCE.size:
        return None
    graph_ids = set()
    for uid, secondary, reserved in _REFERENCE.iter_unpack(payload[2:]):
        if uid > 65535 or secondary != 65535 or any(reserved):
            return None
        if uid != 65535:
            graph_ids.add(uid)
    return graph_ids


def _placements(group, indexed_graphs):
    header = group.get(0x8018)
    references = _placement_references(group.get(0x37))
    if not header or len(header) != 12 or references is None:
        return [], False
    count, group_count = unpack_from("<II", header, 4)
    objects = group["objects"]
    if not len(objects) <= count <= _MAX_OBJECTS:
        return [], False
    positions, seen = [], set()
    for payload, link in objects:
        if len(payload) != 30 or not link or len(link) != 2:
            continue
        kind, = unpack_from("<H", payload)
        if kind != 11:
            continue
        uid, = unpack_from("<H", link)
        # The innermost rectangle matches the original preview's DrawImagePoints.
        left, top, right, bottom = unpack_from("<4h", payload, 18)
        if left >= right or top >= bottom:
            continue
        if uid != 65535:
            if uid not in references or uid not in indexed_graphs:
                continue
            seen.add(uid)
        positions.append({"graph_id": None if uid == 65535 else uid,
                          "bounds": [left, top, right, bottom]})
    return positions, not group_count and len(positions) == count and seen == references


def grid_panel_order(placements):
    """Recognize pages that the native layout editor can represent as a row-major grid."""
    if not 1 <= len(placements) <= 12 or any(panel["graph_id"] is None for panel in placements):
        return None
    cells = {(top, left): (panel["graph_id"], right, bottom)
             for panel in placements for left, top, right, bottom in (panel["bounds"],)}
    rows = sorted({top for top, _ in cells})
    columns = sorted({left for _, left in cells})
    if len(cells) != len(placements) or len(columns) > 4 or len(rows) * len(columns) != len(cells):
        return None
    next_column = dict(zip(columns, columns[1:]))
    next_row = dict(zip(rows, rows[1:]))
    if any(right > next_column.get(left, right) or bottom > next_row.get(top, bottom)
           for (top, left), (_, right, bottom) in cells.items()):
        return None
    return len(columns), [cells[top, left][0] for top in rows for left in columns]


def read_binary_layouts(data):
    """Return indexed layouts and the titles of missing or unreadable sheets."""
    indexed, group, objects = None, None, None
    graph_ids, encoding = {}, "ascii"
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8002:
            if indexed is not None:
                raise ValueError("Duplicate legacy binary layout index.")
            indexed = _layout_index(payload)
            try:
                graph_ids, encoding = _graph_index(payload)
            except ValueError:
                # A broken graph index affects graph links only.
                codepage = unpack_from("<I", payload, 10064)[0] if len(payload) == 10068 else 1252
                encoding = f"cp{codepage}" if codepage in (1251, 1252) else "ascii"
        elif parents == (1,) and tag == 0x8035:
            group, objects = None, None
            if indexed is None or len(payload) != 2:
                continue
            uid, = unpack_from("<H", payload)
            if uid in indexed:
                group = {"objects": []} if indexed[uid] is None else None
                indexed[uid] = group if group is not None else False
        elif parents == (1,) and tag == 0x4035:
            group, objects = None, None
        elif group is None:
            continue
        elif parents == (1, 53) and tag in (9, 0x37, 0x61, 0x8018):
            group[tag] = False if tag in group else payload
        elif parents == (1, 53, 24) and tag == 0x8020:
            objects = group["objects"]
            if len(objects) <= _MAX_OBJECTS:
                objects.append([payload, None])
            else:
                objects = None
        elif parents == (1, 53, 24, 32) and tag == 0x2F and objects is not None:
            objects[-1][1] = False if objects[-1][1] is not None else payload

    if indexed is None:
        raise ValueError("Missing legacy binary layout index.")
    layouts, skipped, remaining = [], [], MAX_BINARY_GRAPH_TOTAL
    for uid, group in indexed.items():
        title = f"Layout {uid}"
        try:
            if not group or not group.get(9):
                raise ValueError("Missing legacy layout title.")
            title = _read_title(group[9], encoding) or title
        except ValueError:
            skipped.append(title)
            continue

        positions, complete = _placements(group, graph_ids)
        layout = {"id": uid, "title": title, "placements": positions, "placements_complete": complete}
        try:
            preview = _stored_emf_preview(group.get(0x61), remaining, layout=True)
        except ValueError:
            pass
        else:
            layout["preview"] = preview
            remaining -= len(preview["data"])
        layouts.append(layout)
    return layouts, skipped
