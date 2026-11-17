"""Edit verified legacy Grouped stacks inside their saved one-page drawing."""

from collections import defaultdict
from ctypes import byref, c_float, c_int
from math import isfinite
from struct import Struct, unpack_from

import numpy as np
from PIL import Image, ImageChops, ImageOps
from pypdfium2 import PdfMatrix, raw

from .prism_binary_editable import _id_array, _one, _require, _subgroups
from .prism_binary_graphs import _MAX_PREVIEW_BYTES, _decode_preview
from .prism_pdf_preview import _page, _render_page


STACK_KIND = "pdf stacks"
_MAX_STACKS = 12
_MAX_SEGMENTS = 12


def _validate_percentages(values):
    if (not np.isfinite(values).all() or (values < 1e-6).any() or (values > 100).any()
            or (values.sum(axis=1) > 100 + 1e-10).any()):
        raise ValueError("Enter percentages of at least 0.000001, with a total of at most 100 per stack.")


def _values(frame):
    if not (1 <= len(frame) <= _MAX_STACKS and 2 <= frame.shape[1] - 1 <= _MAX_SEGMENTS):
        raise ValueError("The recovered graph requires its original stacks and series.")
    values = frame.iloc[:, 1:].to_numpy(dtype=float, na_value=np.nan)
    _validate_percentages(values)
    return values


def validate_stack_values(frame, style):
    values = _values(frame)
    labels = frame.iloc[:, 0].tolist()
    _require(isinstance(style, dict) and style.get("kind") == STACK_KIND
             and frame.columns.tolist() == style.get("columns")
             and all(isinstance(label, str) and label for label in labels)
             and labels == style.get("labels")
             and values.shape == np.shape(style.get("values")))
    return values


def _path_points(obj, count):
    matrix = obj.get_matrix()
    points = []
    for index in range(count):
        segment = raw.FPDFPath_GetPathSegment(obj, index)
        if not segment or raw.FPDFPathSegment_GetType(segment) != (
                raw.FPDF_SEGMENT_MOVETO if index == 0 else raw.FPDF_SEGMENT_LINETO):
            return None
        x, y = c_float(), c_float()
        if not raw.FPDFPathSegment_GetPoint(segment, byref(x), byref(y)):
            return None
        point = matrix.on_point(x.value, y.value)
        if not all(isfinite(value) for value in point):
            return None
        points.append(point)
    return points


def _paths(page):
    rectangles, horizontals = defaultdict(list), []
    _require(page.get_rotation() == 0 and 1 <= raw.FPDFPage_CountObjects(page) <= 400)
    for obj in page.get_objects(max_depth=1):
        _require(obj.type in (raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_TEXT))
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        fill, stroke = c_int(), c_int()
        _require(raw.FPDFPath_GetDrawMode(obj, byref(fill), byref(stroke)))
        count = raw.FPDFPath_CountSegments(obj)
        if count == 2 and not fill.value and stroke.value:
            points = _path_points(obj, 2)
            if points and abs(points[0][1] - points[1][1]) < 0.001:
                (x1, y), (x2, _) = points
                horizontals.append((min(x1, x2), max(x1, x2), y))
        elif count == 5 and fill.value and not stroke.value:
            points = _path_points(obj, 5)
            if not points:
                continue
            left, bottom, right, top = obj.get_bounds()
            corners = {(left, bottom), (left, top), (right, top), (right, bottom)}
            if (right > left and top > bottom and set(points[:4]) == corners
                    and points[4] == points[0]
                    and all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:]))):
                rectangles[left, right].append((bottom, top, obj))
    return rectangles, horizontals


def _stack_geometry(page, original):
    rectangles, horizontals = _paths(page)
    # The axis uses three short ticks at 0, 50 and 100 with one longer baseline
    # extending right. Confirm the labels before interpreting positions as percentages.
    tick_groups = defaultdict(list)
    for left, right, y in horizontals:
        if 2 <= right - left <= 9:
            tick_groups[left, right].append(y)
    candidates = []
    page_left, _, _, _ = page.get_bbox()
    text = page.get_textpage()
    try:
        for (label_right, axis_left), ticks in tick_groups.items():
            if len(ticks) != 3:
                continue
            low, mid, high = sorted(ticks)
            if high - low < 25 or abs(2 * mid - low - high) > 0.01:
                continue
            labels = [text.get_text_bounded(left=page_left, right=label_right + 1,
                                            bottom=y - 6, top=y + 6).strip() for y in (low, mid, high)]
            if labels != ["0%", "50%", "100%"]:
                continue
            baseline = [right for left, right, y in horizontals
                        if abs(left - axis_left) < 0.001 and abs(y - low) < 0.001 and right - left > 15]
            if len(baseline) != 1:
                continue
            groups = [sorted(segments, key=lambda segment: segment[0])
                      for (left, right), segments in sorted(rectangles.items())
                      if axis_left < left < right < baseline[0]
                      and any(bottom >= low - 0.15 and top <= high + 0.15 for bottom, top, _ in segments)]
            if len(groups) != len(original) or any(len(group) != original.shape[1] for group in groups):
                continue
            if any(abs(a[1] - b[0]) > 0.001 for group in groups for a, b in zip(group, group[1:])):
                continue
            if any(raw.FPDFClipPath_CountPaths(raw.FPDFPageObj_GetClipPath(obj)) > 0
                   for group in groups for _, _, obj in group):
                continue
            scale = (high - low) / 100
            if all(abs(edge - (low + scale * expected)) <= 0.15
                   for group, row in zip(groups, original, strict=True)
                   for segment, pair in zip(group, zip(np.r_[0, row.cumsum()[:-1]], row.cumsum()), strict=True)
                   for edge, expected in zip(segment[:2], pair, strict=True)):
                candidates.append((scale, groups))
    finally:
        text.close()
    _require(len(candidates) == 1)
    return candidates[0]


def _stack_series(graph, rows):
    scenes = list(_subgroups(graph, 0x8018))
    _require(len(scenes) == 1)
    series = {}
    for header, records in _subgroups(scenes[0][1], 0x8020):
        _require(len(header) == 30)
        if unpack_from("<H", header)[0] != 9:
            continue
        payload = _one(records, 0x8028)
        _require(len(payload) == 144)
        key, family, uid, active = unpack_from("<4H", payload)
        flags, = unpack_from("<H", payload, 58)
        stride, _, points = unpack_from("<3H", payload, 110)
        _require(key not in series and family == active == 1 and flags == 10 and stride == 3 and points == rows)
        series[key] = uid
    return series


def read_pdf_stack(graph, sources, tables, remaining_cells):
    payload = _one(graph, 0xF00)
    _require(0 < len(payload) <= _MAX_PREVIEW_BYTES)
    count, uid = Struct("<II").unpack(_one(graph, 0x14))
    _require(count == 1 and Struct("<III").unpack(_one(graph, 0x8018)) == (uid, 15, 0))
    source = sources[uid]
    _require(source.attrs.get("table_format") == "grouped")
    groups = source.attrs.get("worksheet_roles", {}).get("y", [])
    _require(2 <= len(groups) <= _MAX_SEGMENTS and all(len(group) == 1 for group in groups))
    names = [group[0] for group in groups]
    links = sorted(unpack_from("<III", record) for tag, _, record in tables[uid] if tag == 0x0D)
    _require(len(links) == len(names)
             and all(index == expected and repeats == 1 for expected, (index, _, repeats) in enumerate(links)))
    datasets = _one(graph, 0x16)
    order = _id_array(_one(graph, 0x15))
    _require(len(datasets) == 2 + len(names) * 12 and unpack_from("<H", datasets)[0] == len(names)
             and len(set(order)) == len(order) == len(names)
             and list(Struct("<III").iter_unpack(datasets[2:])) == [(data_uid, 1, 1) for _, data_uid, _ in links])
    _require(1 <= len(source) <= _MAX_STACKS and len(source) * (len(names) + 1) <= remaining_cells)
    series = _stack_series(graph, len(source))
    _require(set(series) == set(order) and [series[key] for key in order] == [link[1] for link in links])
    labels = source.columns.difference(names)
    _require(len(labels) <= 1)
    frame = source[names].copy()
    group_name = "Stack"
    while group_name in names:
        group_name += " label"
    row_labels = source[labels[0]].astype("string").fillna("") if len(labels) else [""] * len(frame)
    frame.insert(0, group_name, [label if label.strip() else f"Stack {index}"
                                 for index, label in enumerate(row_labels, 1)])
    values = _values(frame)
    with _page(bytes(payload)) as (page, _):
        _stack_geometry(page, values)
    return frame, {"kind": STACK_KIND, "columns": frame.columns.tolist(),
                   "labels": frame.iloc[:, 0].tolist(), "values": values.tolist()}


def render_pdf_stack(frame, style, preview, max_side=1600, *, crop=True):
    values = validate_stack_values(frame, style)
    original = np.asarray(style["values"], dtype=float)
    _validate_percentages(original)
    _require(isinstance(preview, dict) and preview.get("format") == "pdf")
    data, _ = _decode_preview(preview)
    with _page(data) as (page, dimensions):
        scale, groups = _stack_geometry(page, original)
        for group, old_row, new_row in zip(groups, original, values, strict=True):
            if np.array_equal(old_row, new_row):
                continue
            old_percent = [0, *old_row.cumsum()]
            old_edges = [group[0][0], *(top for _, top, _ in group)]
            # Calibrate against the actual PDF boundaries so rounding cannot
            # reverse the direction of a small edit.
            if old_percent[-1] < 100:
                old_edges.append(old_edges[-1] + (100 - old_percent[-1]) * scale)
                old_percent.append(100)
            edges = np.interp([0, *new_row.cumsum()], old_percent, old_edges)
            for (bottom, top, obj), start, end in zip(group, edges[:-1], edges[1:], strict=True):
                if abs(bottom - start) > 0.001 or abs(top - end) > 0.001:
                    factor = (end - start) / (top - bottom)
                    obj.transform(PdfMatrix(1, 0, 0, factor, 0, start - factor * bottom))
        image = _render_page(page, dimensions, max_side)
    if not crop:
        return image
    bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    _require(bounds is not None)
    return ImageOps.expand(image.crop(bounds), border=12, fill="white")
