"""Bind visible XY limits to matching strokes in classic saved EMF drawings."""

from struct import pack_into, unpack_from

import numpy as np
import pandas as pd

from .prism_binary import _DATASET, _XY_LIMITS
from .prism_binary_editable import _id_array, _one, _preview
from .prism_emf_edit import (
    POINTS, _ERRORS, _MAX_POINTS, _XY, _classic_commands, _drawing_series,
    _geometry, _point_pixels, _project, _require, _xy_group_links,
)


def _limit_pixels(values, style):
    points = np.array(values, dtype=float, copy=True)
    nudge = np.asarray(style["limit_nudges"], dtype=float)
    _require(points.ndim == 2 and points.shape[1] == 4 and 1 <= len(points) <= _MAX_POINTS
             and nudge.shape == (len(points),) and np.isfinite(nudge).all()
             and style["axes"][0]["scale"] == "linear")
    points[:, 0] += nudge
    errors = points[:, 2:]
    errors[np.isnan(errors)] = 0.
    return _point_pixels(points, style)


def _stroke_endpoints(segments, x, first, second):
    """Return matches with the payload offsets in the requested Y order."""
    matches = []
    for offsets, (start, stop) in segments.items():
        if abs(start[0] - x) > 2 or start[1] == stop[1]:
            continue
        if abs(start[1] - first) <= 2 and abs(stop[1] - second) <= 2:
            matches.append(offsets)
        elif abs(stop[1] - first) <= 2 and abs(start[1] - second) <= 2:
            matches.append(offsets[::-1])
    return matches


def _bindings(markers, segments, point):
    x, center, top, bottom = point
    matches = [(offset, box) for offset, box in markers.items()
               if abs((box[0] + box[2]) / 2 - x) <= 2 and abs((box[1] + box[3]) / 2 - center) <= 2]
    _require(len(matches) == 1)
    (marker, box), = matches
    whole = _stroke_endpoints(segments, x, top, bottom)
    if whole:
        _require(len(whole) == 1)
        upper, lower = whole[0]
        return ((marker, 1), (marker + 8, 1), (upper, 2), (lower, 3))

    # In the outlined marker profile, the two strokes overlap behind
    # the marker and terminate at opposite sides of its box.
    _require(top < center < bottom)
    above = _stroke_endpoints(segments, x, top, box[3])
    below = _stroke_endpoints(segments, x, bottom, box[1])
    _require(len(above) == len(below) == 1)
    (upper, inner_above), = above
    (lower, inner_below), = below
    return ((marker, 1), (marker + 8, 1), (upper, 2), (inner_above, 1), (lower, 3), (inner_below, 1))


def edit_limit_points(raw, values, style):
    original = np.asarray(style["source"], dtype=float)
    _require(original.shape == values.shape)
    _require(np.array_equal(np.isnan(original[:, 2:]), np.isnan(values[:, 2:])),
             "Keep the displayed error sides present and the absent error sides blank.")
    saved = _limit_pixels(original, style)
    current = _limit_pixels(values, style)
    markers, segments = _classic_commands(raw, vertical_only=True)
    result = bytearray(raw)
    used = set()
    for point, shift in zip(saved, np.rint(current - saved).astype(int), strict=True):
        for offset, index in _bindings(markers, segments, point):
            _require(offset not in used)
            used.add(offset)
            x, y = unpack_from("<2i", raw, offset)
            pack_into("<2i", result, offset, x + int(shift[0]), y + int(shift[index]))
    return result


def _visible_errors(values, cache, nudge, style):
    n = len(values)
    _require(0 < n <= _MAX_POINTS and 4 * n <= cache.size and not cache[4 * n:].any())
    projected_x = values[:, 0] + nudge
    center = _project(np.column_stack((projected_x, values[:, 1])), style)
    ends = [_project(np.column_stack((projected_x, values[:, i])), style)[:, 1] for i in (2, 3)]
    left, _, _, bottom = style["chart"]
    pixels = cache[:4 * n].reshape(n, 4) * [1, -1, -1, -1] + [left, bottom, bottom, bottom]
    _require(np.all(np.abs(center - pixels[:, :2]) <= 2))
    errors = np.full((n, 2), np.nan)
    for i, point in enumerate(pixels):
        for index, displayed in enumerate(point[2:]):
            if displayed == point[1]:
                continue
            _require(abs(displayed - ends[index][i]) <= 2)
            distance = values[i, index + 2] - values[i, 1]
            side = int(displayed > point[1])
            _require(distance != 0 and (distance < 0) == bool(side) and np.isnan(errors[i, side]))
            errors[i, side] = abs(distance)
        _require(not np.isnan(errors[i]).all())
    return errors


def read_emf_limit_points(graph, sources, tables, remaining_cells):
    """Recover independently matched point series and retain any shaded band."""
    style = {"kind": POINTS, **_geometry(graph)}
    sheet, = _id_array(_one(graph, 0x14))
    source = sources[sheet]
    records = tables[sheet]
    x, groups = _xy_group_links(source, records)
    fields = {entry[0]: entry for tag, _, payload in records if tag == 0x800F
              for entry in [_DATASET.unpack(payload)]}
    series = _drawing_series(graph, 0, (0xA,))
    _require(len({uid for uid, _, _ in series}) == len(series))
    rows, nudges = [], []
    bands = 0
    for uid, cache, attributes in series:
        repeats, columns = groups[uid]
        entry = fields[uid]
        _require(len(columns) == repeats == 3 and entry[3:6] == (-1, sheet, 101)
                 and entry[7:11] == (1, 8, _XY_LIMITS, repeats))
        mode = unpack_from("<2H", attributes, 60)
        if mode == (0, 4) and unpack_from("<H", attributes, 10)[0] == 4:
            bands += 1
            continue
        _require(mode in ((5, 7), (10, 7)))
        nudge, = unpack_from("<d", attributes, 128)
        values = source[[x, *columns]].to_numpy(dtype=float, na_value=np.nan)
        values = values[~np.isnan(values[:, 1:]).all(axis=1)]
        _require(0 < len(values) <= _MAX_POINTS - len(rows) and np.isfinite(values).all()
                 and np.isfinite(nudge) and (len(rows) + len(values)) * 5 <= remaining_cells)
        errors = _visible_errors(values, cache, nudge, style)
        label = str(columns[0]).removesuffix(" [Center]")
        rows.extend([*point[:2], *error, label] for point, error in zip(values, errors, strict=True))
        nudges.extend([nudge] * len(values))
    _require(bool(rows) and bands <= 1)
    frame = pd.DataFrame(rows, columns=[*_XY, *_ERRORS, "Series"])
    points = frame.iloc[:, :4].to_numpy(dtype=float)
    style["source"] = [[None if np.isnan(value) else value for value in row] for row in points.tolist()]
    style["limit_nudges"] = nudges
    if bands:
        style["fixed_band"] = True
    edit_limit_points(_preview(graph), points, style)
    return frame, style
