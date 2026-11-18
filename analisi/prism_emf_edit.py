"""Edit verified XY geometry inside a legacy drawing without redrawing its artwork."""

from base64 import b64encode
from math import sqrt
from struct import pack_into, unpack_from

import numpy as np
import pandas as pd

from .prism_binary import _DATASET
from .prism_binary_editable import _axis_config, _id_array, _one, _preview, _subgroups
from .prism_binary_graphs import validate_binary_graph


CURVE = "emf-xy-curve"
POINTS = "emf-xy-errors"
_XY = ["X", "Y"]
_ERRORS = ["Upper error", "Lower error"]
_MAX_POINTS = 256
_MAX_CURVES = 16
_POINT_OVERLAYS = (0x8, 0xA, 0xE)


def _require(condition, message="The XY data do not match a supported saved drawing."):
    if not condition:
        raise ValueError(message)


def _geometry(graph):
    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    left, top, right, bottom = unpack_from("<4h", chart)
    axes = _axis_config(graph)
    _require([right - left, bottom - top] == [axis["length"] for axis in axes])
    return {
        "chart": [left, top, right, bottom],
        "axes": [{key: axis[key] for key in ("bounds", "unit", "scale")} for axis in axes],
    }


def _project(values, style):
    result = np.array(values, dtype=float, copy=True)
    _require(result.ndim == 2 and result.shape[1] == 2 and np.isfinite(result).all(),
             "Enter finite X and Y values for every point.")
    chart = np.asarray(style["chart"], dtype=float)
    _require(chart.shape == (4,) and np.isfinite(chart).all() and np.abs(chart).max() <= 32767)
    _require(chart[0] < chart[2] and chart[1] < chart[3] and len(style["axes"]) == 2)
    for index, (axis, origin, direction, length) in enumerate(zip(
            style["axes"], chart[[0, 3]], (1, -1), chart[2:] - chart[:2], strict=True)):
        low, high = axis["bounds"]
        unit = axis["unit"]
        _require(np.isfinite([low, high, unit]).all() and low < high and unit > 0
                 and np.isclose((high - low) / unit, length, rtol=1e-5))
        column = result[:, index]
        if axis["scale"] == "log":
            _require((column > 0).all(), "Logarithmic coordinates must be positive.")
            np.log10(column, out=column)
        else:
            _require(axis["scale"] == "linear")
        tolerance = unit * 1e-7
        _require(((column >= low - tolerance) & (column <= high + tolerance)).all(),
                 "Coordinates and error endpoints must stay inside the saved axes.")
        column[:] = origin + direction * (column - low) / unit
    return result


def _drawing_series(graph, family, allowed_flags):
    order = _id_array(_one(graph, 0x15))
    links = _one(graph, 0x16)
    _require(len(order) == len(set(order)) and len(links) == 2 + 12 * len(order)
             and unpack_from("<H", links)[0] == len(order))
    scenes = list(_subgroups(graph, 0x8018))
    _require(len(scenes) == 1 and len(scenes[0][0]) == 12)
    series = {}
    for header, records in _subgroups(scenes[0][1], 0x8020):
        _require(len(header) == 30)
        if unpack_from("<H", header)[0] != 9:
            continue
        attributes = _one(records, 0x8028)
        _require(len(attributes) == 144)
        key, kind, uid, visible = unpack_from("<4H", attributes)
        drawing_flags, = unpack_from("<H", attributes, 58)
        _require(key not in series and kind == family and visible == 1
                 and drawing_flags in allowed_flags)
        caches = [payload for tag, path, payload in records if tag == 0x29 and path == (40,)]
        _require(len(caches) == 1 and 12 <= len(caches[0]) <= 4 + 32 * _MAX_POINTS)
        count, = unpack_from("<I", caches[0])
        _require(len(caches[0]) == 4 + 4 * count)
        series[key] = uid, np.frombuffer(caches[0][4:], dtype="<i4"), attributes
    _require(set(series) == set(order))
    ordered = [series[key] for key in order]
    _require(sorted(uid for uid, _, _ in ordered) ==
             sorted(unpack_from("<i", links, 2 + 12 * i)[0] for i in range(len(order))))
    return ordered


def _series(graph, family, flags, *, overlay_flags=()):
    return [(uid, cache) for uid, cache, attributes in _drawing_series(graph, family, (flags, *overlay_flags))
            if unpack_from("<H", attributes, 58)[0] == flags]


def _emf_records(raw):
    offset = 108
    while offset < len(raw):
        kind, size = unpack_from("<II", raw, offset)
        yield kind, size, offset
        offset += size


def _curve_records(raw):
    for kind, size, offset in _emf_records(raw):
        if kind != 70:
            continue
        cursor = offset + 16
        while cursor < offset + size:
            command, flags, length, _ = unpack_from("<HHII", raw, cursor)
            if command == 0x400D and flags & 0xFF00 == 0x4000:
                count, = unpack_from("<I", raw, cursor + 12)
                if 4 <= count <= 2 * _MAX_POINTS and count % 2 == 0:
                    yield cursor + 16, np.frombuffer(raw, "<i2", count=2 * count, offset=cursor + 16).reshape(-1, 2)
            cursor += length


def _expanded(points):
    # A saved stroke duplicates the start and each internal vertex.
    return np.concatenate((points[:1], np.repeat(points, 2, axis=0)[:-1]))


def _edit_curve(raw, values, style, cached=None):
    saved = _project(style["source"], style)
    new = _project(values, style)
    lengths = style.get("series_lengths", [len(saved)])
    _require(new.shape == saved.shape and isinstance(lengths, list) and 1 <= len(lengths) <= _MAX_CURVES
             and all(type(length) is int and 2 <= length <= _MAX_POINTS for length in lengths)
             and sum(lengths) == len(saved))
    strokes = [(offset, coords) for offset, coords in _curve_records(raw)
               if np.array_equal(coords, _expanded(coords[1::2]))]
    result = bytearray(raw)
    used = set()
    start = 0
    for index, length in enumerate(lengths):
        stop = start + length
        expected = saved[start:stop]
        matches = [(offset, coords) for offset, coords in strokes
                   if len(coords) == 2 * length and np.all(np.abs(coords[1::2] - expected) <= 2)]
        _require(len(matches) == 1, "The saved curve cannot be matched to a unique drawing stroke.")
        offset, coords = matches[0]
        _require(offset not in used, "Multiple saved series refer to the same drawing stroke.")
        if cached is not None:
            _require(np.all(np.abs(coords[1::2] - cached[index]) <= 2))
        used.add(offset)
        shifted = coords + _expanded(np.rint(new[start:stop] - expected))
        _require(np.abs(shifted).max() <= 32767)
        result[offset:offset + coords.nbytes] = shifted.astype("<i2").tobytes()
        start = stop
    return result


def read_emf_curve(graph, owners, remaining_cells, multiple=False):
    """Bind saved XY curves to the numeric tables, caches and original strokes."""
    style = {"kind": CURVE, **_geometry(graph)}
    sheets = set(_id_array(_one(graph, 0x14)))
    series = _series(graph, 0, 0x88, overlay_flags=_POINT_OVERLAYS if multiple else ())
    _require(2 <= len(series) <= _MAX_CURVES if multiple else len(series) == 1)
    _require(len({uid for uid, _ in series}) == len(series))
    origin = np.array(style["chart"])[[0, 3]]
    cached, frames = [], []
    for uid, cache in series:
        matches = [entry for entry in owners[uid] if entry[0] in sheets]
        _require(len(matches) == 1 and cache.size % 2 == 0)
        _, source, x, y = matches[0]
        values = source.iloc[:, [x, y]].to_numpy(dtype=float, na_value=np.nan)
        _require(2 <= len(values) <= _MAX_POINTS and len(values) * 3 <= remaining_cells)
        pixels = _project(values, style)
        expected = cache.reshape(-1, 2) * [1, -1] + origin
        _require(expected.shape == pixels.shape and np.all(np.abs(expected - pixels) <= 2))
        cached.append(expected)
        frame = pd.DataFrame(values, columns=_XY)
        frame["Series"] = str(source.columns[y])
        frames.append(frame)
        remaining_cells -= frame.size
    if multiple:
        labels = [frame["Series"].iat[0] for frame in frames]
        if len(set(labels)) < len(labels):
            for (uid, _), frame, label in zip(series, frames, labels, strict=True):
                frame["Series"] = f"{label} · {uid}"
        style["series_lengths"] = [len(frame) for frame in frames]
        style["fixed_overlays"] = len(_id_array(_one(graph, 0x15))) - len(series)
    frame = pd.concat(frames, ignore_index=True)
    values = frame[_XY].to_numpy(dtype=float)
    style["source"] = values.tolist()
    _edit_curve(_preview(graph), values, style, cached)
    return frame, style


def read_cached_emf_curve(graph, remaining_cells):
    """Recover the coordinates of one cached curve in the original axis units."""
    style = {"kind": CURVE, **_geometry(graph), "cached_curve": True}
    series = _series(graph, 0, 0x88)
    _require(len(series) == 1)
    _, cache = series[0]
    _require(cache.size % 2 == 0 and 4 <= cache.size <= 2 * _MAX_POINTS
             and cache.size // 2 * 3 <= remaining_cells)
    offsets = cache.reshape(-1, 2)
    values = np.empty_like(offsets, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        for index, axis in enumerate(style["axes"]):
            values[:, index] = axis["bounds"][0] + offsets[:, index] * axis["unit"]
            if axis["scale"] == "log":
                values[:, index] = np.power(10., values[:, index])
    style["source"] = values.tolist()
    pixels = offsets * [1, -1] + np.asarray(style["chart"])[[0, 3]]
    _edit_curve(_preview(graph), values, style, [pixels])
    frame = pd.DataFrame(values, columns=_XY)
    frame["Series"] = "Saved curve"
    return frame, style


def _point_pixels(values, style):
    values = np.asarray(values, dtype=float)
    _require(values.ndim == 2 and values.shape[1] == 4 and (values[:, 2:] >= 0).all(),
             "Enter finite, nonnegative error distances.")
    center = _project(values[:, :2], style)
    upper = _project(np.column_stack((values[:, 0], values[:, 1] + values[:, 2])), style)[:, 1]
    lower = _project(np.column_stack((values[:, 0], values[:, 1] - values[:, 3])), style)[:, 1]
    return np.column_stack((center, upper, lower))


def _classic_commands(raw, *, vertical_only=False):
    markers, segments = {}, {}
    previous_move = None
    for kind, _, offset in _emf_records(raw):
        _require(kind not in (36, 70))  # This profile uses untransformed classic EMF.
        if kind in (42, 43):
            box = np.array(unpack_from("<4i", raw, offset + 8))
            if ((box[2:] - box[:2] > 0) & (box[2:] - box[:2] <= 100)).all():
                markers[offset + 8] = box
        if kind == 54 and previous_move is not None:
            start = unpack_from("<2i", raw, previous_move)
            end = unpack_from("<2i", raw, offset + 8)
            if not vertical_only or start[0] == end[0]:
                segments[(previous_move, offset + 8)] = (start, end)
        _require(len(markers) <= 1024 and len(segments) <= 4096)
        previous_move = offset + 8 if kind == 27 else None
    return markers, segments


def _point_bindings(markers, segments, point):
    x, y, hi, lo = point
    marker = [offset for offset, box in markers.items() if np.all(np.abs((box[:2] + box[2:]) / 2 - (x, y)) <= 2)]
    stems = [(key, a, b) for key, (a, b) in segments.items()
             if a[0] == b[0] and abs(a[0] - x) <= 2 and abs(min(a[1], b[1]) - hi) <= 2
             and abs(max(a[1], b[1]) - lo) <= 2 and a[1] != b[1]]
    _require(len(marker) == len(stems) == 1)
    stem, start, end = stems[0]
    if start[1] > end[1]:
        stem = stem[::-1]
        start, end = end, start
    cap_groups = []
    for stem_end in (start, end):
        px, py = stem_end
        caps = [key for key, (a, b) in segments.items()
                if a[1] == b[1] == py and min(a[0], b[0]) < px < max(a[0], b[0])
                and abs((a[0] + b[0]) / 2 - px) <= 2 and abs(a[0] - b[0]) <= 100]
        _require(1 <= len(caps) <= 2)
        cap_groups.append(caps)
    return marker[0], stem, cap_groups


def _edit_points(raw, values, style):
    if "limit_nudges" in style:
        from .prism_emf_limits import edit_limit_points

        return edit_limit_points(raw, values, style)
    saved = _point_pixels(style["source"], style)
    new = _point_pixels(values, style)
    _require(new.shape == saved.shape and 1 <= len(saved) <= _MAX_POINTS)
    markers, segments = _classic_commands(raw)
    result = bytearray(raw)
    used = set()

    def move(offset, dx, dy):
        _require(offset not in used)
        used.add(offset)
        x, y = unpack_from("<2i", raw, offset)
        pack_into("<2i", result, offset, x + dx, y + dy)

    for point, shift in zip(saved, np.rint(new - saved).astype(int), strict=True):
        marker, stem, caps = _point_bindings(markers, segments, point)
        dx, dy, high_shift, low_shift = map(int, shift)
        move(marker, dx, dy)
        move(marker + 8, dx, dy)
        for endpoint, cap_group, delta in zip(stem, caps, (high_shift, low_shift), strict=True):
            move(endpoint, dx, delta)
            for cap in cap_group:
                for offset in cap:
                    move(offset, dx, delta)
    return result


def _xy_group_links(source, records):
    roles = source.attrs["worksheet_roles"]
    _require(len(roles["x"]) == 1)
    links = [unpack_from("<3I", payload) for tag, _, payload in records if tag == 0x0D and len(payload) == 40]
    _require(len(links) == len(roles["y"]) and sorted(index for index, _, _ in links) == list(range(len(links))))
    return roles["x"][0], {uid: (repeat, roles["y"][index]) for index, uid, repeat in links}


def read_emf_error_points(graph, sources, tables, remaining_cells):
    """Restore classic XY markers and two-ended SEM whiskers on replicate tables."""
    style = {"kind": POINTS, **_geometry(graph)}
    _require(all(axis["scale"] == "linear" for axis in style["axes"]))
    sheet, = _id_array(_one(graph, 0x14))
    source = sources[sheet]
    x, groups = _xy_group_links(source, tables[sheet])
    attributes = [_DATASET.unpack(payload) for tag, _, payload in tables[sheet] if tag == 0x800F]
    rows = []
    origin = np.array(style["chart"])[[0, 3, 3, 3]]
    for uid, cache in _series(graph, 0, 0x8):
        repeat, columns = groups[uid]
        _require(len(columns) == repeat == 3)
        match = [entry for entry in attributes if entry[0] == uid]
        _require(len(match) == 1 and match[0][3:6] == (-1, sheet, 101)
                 and match[0][7:11] == (1, 8, 61, repeat))
        values = source[[x, *columns]].to_numpy(dtype=float, na_value=np.nan)
        plotted = values[~np.isnan(values[:, 1:]).all(axis=1)]
        _require(0 < len(plotted) <= _MAX_POINTS - len(rows) and np.isfinite(plotted).all())
        means = plotted[:, 1:].mean(axis=1)
        sem = plotted[:, 1:].std(axis=1, ddof=1) / sqrt(repeat)
        summary = np.column_stack((plotted[:, 0], means, sem, sem))
        expected = (_point_pixels(summary, style) - origin) * [1, -1, -1, -1]
        chunks = np.lib.stride_tricks.sliding_window_view(cache, 4)
        for point in expected:
            _require(np.count_nonzero(np.all(np.abs(chunks - point) <= 2, axis=1)) == 1)
        rows.extend([*point, str(columns[0]).removesuffix(" [1]")] for point in summary)
    frame = pd.DataFrame(rows, columns=[*_XY, *_ERRORS, "Series"])
    _require(1 <= len(frame) <= _MAX_POINTS and frame.size <= remaining_cells)
    values = frame.iloc[:, :-1].to_numpy(dtype=float)
    style["source"] = values.tolist()
    _edit_points(_preview(graph), values, style)
    return frame, style


def edit_emf_preview(frame, style, preview):
    """Return the saved EMF with edits confined to independently matched geometry."""
    _require(isinstance(preview, dict) and preview.get("format") == "emf")
    raw = validate_binary_graph(preview)
    try:
        kind = style["kind"]
        _require(kind in (CURVE, POINTS))
        fields = _XY if kind == CURVE else [*_XY, *_ERRORS]
        _require(list(frame.columns) == [*fields, "Series"])
        values = frame[fields].to_numpy(dtype=float, na_value=np.nan)
        result = (_edit_curve if kind == CURVE else _edit_points)(raw, values, style)
    except (IndexError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid saved XY drawing or worksheet values.") from error
    if result == raw:
        return preview
    edited = {"format": "emf", "data": b64encode(result).decode("ascii")}
    validate_binary_graph(edited)
    return edited
