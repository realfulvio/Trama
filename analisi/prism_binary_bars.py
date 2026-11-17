"""Edit column geometry in a validated Prism drawing, retaining its original typography and artwork."""

from base64 import b64encode
from collections import Counter
from math import isclose, isfinite, isnan, sqrt
from struct import Struct, pack_into, unpack_from

import numpy as np
import pandas as pd
from scipy.special import stdtrit

from .prism_binary import _DATASET
from .prism_binary_editable import _id_array, _one, _preview, _subgroups
from .prism_binary_graphs import _emf_dimensions, validate_binary_graph


MAX_BARS = 256
BAR_VALUES = ["Mean", "Upper error", "Lower error"]


def _require(condition):
    if not condition:
        raise ValueError("Unsupported editable Prism column graph.")


def _drawing_objects(emf):
    """Index only the coordinate-bearing commands that can represent bars."""
    rectangles, outlines, whiskers = {}, {}, {}
    pos = 108
    while pos < len(emf):
        tag, size = unpack_from("<II", emf, pos)
        if tag == 70:
            cursor = pos + 16
            while cursor < pos + size:
                kind, _, length, _ = unpack_from("<HHII", emf, cursor)
                if kind == 0x400A:
                    for offset in range(cursor + 20, cursor + length, 8):
                        rectangles[offset] = unpack_from("<4h", emf, offset)
                elif kind == 0x400D and length == 40:
                    points = unpack_from("<12h", emf, cursor + 16)
                    left, base, _, top, _, _, right = points[:7]
                    expected = (left, base, left, top, left, top, right, top, right, top, right, base)
                    if left < right and base > top and points == expected:
                        outlines[cursor + 16] = (left, right, base, top)
                elif kind == 0x400D and length == 32:
                    left, end, right, cap_y, center, stem_y, stem_x, top = unpack_from("<8h", emf, cursor + 16)
                    if left < center < right and center == stem_x and end == cap_y == stem_y and end != top:
                        whiskers[cursor + 16] = (center, top, end)
                cursor += length
        pos += size
    return rectangles, outlines, whiskers


def _bar_object(drawing, bottom, center, width, height):
    rectangles, outlines, whiskers = drawing
    top = bottom - height
    matches = [(offset, left, right, y) for offset, (left, right, base, y) in outlines.items()
               if base == bottom and abs(y - top) <= 1 and abs((left + right) / 2 - center) <= 1
               and abs(right - left - width) <= 1]
    _require(len(matches) == 1)
    offset, left, right, top = matches[0]
    fills = [(start, box) for start, box in rectangles.items()
             if box[:2] == (left, top) and abs(box[2] - right + left) <= 1
             and abs(box[3] - bottom + top) <= 1]
    errors = [[], []]
    for start, (x, stem, end) in whiskers.items():
        if abs(x - center) <= 1 and stem == top:
            errors[int(end > top)].append((start, end))
    _require(len(fills) <= 1 and any(errors) and all(len(side) <= 1 for side in errors))
    del outlines[offset]
    for side in errors:
        if side:
            del whiskers[side[0][0]]
    if fills:
        del rectangles[fills[0][0]]
    return offset, top, fills[0] if fills else None, tuple(side[0] if side else None for side in errors)


def _check_caps(caps, levels, bottom):
    for cap, level in zip(caps, levels, strict=True):
        _require((cap is None and level is None)
                 or (cap is not None and level is not None and abs(cap[1] - (bottom - level)) <= 1))


def _scale(graph, chart):
    axes = [p for tag, parents, p in graph if tag == 0x17 and not parents]
    _require(len(axes) == 3 and all(len(p) == 60 for p in axes))
    low, high = unpack_from("<2d", axes[1], 16)
    length, _, scale = unpack_from("<3H", axes[1], 42)
    index, = unpack_from("<H", axes[1], 54)
    ticks = [p for tag, parents, p in graph if tag == 0x8025 and not parents
             and len(p) in (122, 134) and unpack_from("<H", p)[0] == index]
    _require(len(ticks) == 1 and scale == 0 and 100 <= length <= 20_000 and low == 0.0
             and isfinite(high) and 0 < high < 1e100)
    tick_low, tick_high, unit = unpack_from("<3d", ticks[0], 2)
    left, top, right, bottom = unpack_from("<4h", chart)
    _require(right > left and bottom - top == length and tick_low == low
             and isclose(tick_high, high, rel_tol=1e-6)
             and isclose(unit, high / length, rel_tol=1e-6))
    return left, right, bottom, high, unit


def _columns(sheet, records, frame):
    fields, links = {}, {}
    for tag, _, payload in records:
        if tag == 0x0D:
            _require(len(payload) >= 24)
            index, dataset, repeat = unpack_from("<3I", payload)
            _require(index not in links and len(payload) == 12 + 12 * repeat)
            links[index] = dataset, repeat
        elif tag == 0x800F:
            _require(len(payload) == _DATASET.size)
            uid, _, _, analysis, owner, storage, _, kind, role, form, repeat, _, _, rows, cells = (
                _DATASET.unpack(payload)
            )
            _require(uid not in fields and owner == sheet and analysis == -1 and storage == 101
                     and 1 <= repeat <= 512 and 0 <= rows <= len(frame) and rows * repeat == cells)
            fields[uid] = kind, role, form, repeat, rows
    _require(sorted(links) == list(range(len(links))))
    non_y = [entry for entry in fields.values() if entry[:2] != (1, 8)]
    _require(len(non_y) <= 2 and all(entry[:4] in ((1, 4, 10, 1), (2, 256, 12, 1)) for entry in non_y))
    pos, columns = len(non_y), {}
    for uid, repeat in (links[key] for key in sorted(links)):
        if uid == 0xFFFFFFFF:
            continue
        kind, role, form, width, rows = fields[uid]
        _require(uid not in columns and (kind, role) == (1, 8) and repeat == width
                 and ((form == 10 and width == 1) or (form == 21 and width == 2) or form == 61))
        columns[uid] = form, frame.iloc[:rows, pos:pos + width]
        pos += width
    _require(pos == len(frame.columns) and len(fields) == len(columns) + len(non_y))
    return columns


def _summaries(table, form, grouped):
    if grouped:
        _require(form in (21, 61))
        for values in table.to_numpy(dtype=float, na_value=np.nan):
            if form == 21:
                mean, error = values
                yield mean, [(error, error)]
            else:
                yield _mean_errors(values)
    else:
        _require(form == 10)
        yield _mean_errors(table.iloc[:, 0].to_numpy(dtype=float, na_value=np.nan))


def _mean_errors(values):
    values = values[~np.isnan(values)]
    _require(len(values) > 1 and np.isfinite(values).all())
    sd = float(values.std(ddof=1))
    sem = sd / sqrt(len(values))
    mean = float(values.mean())
    ci = float(stdtrit(len(values) - 1, 0.975)) * sem
    errors = [(error, error) for error in (sem, sd, ci)]
    errors.append((float(values.max()) - mean, mean - float(values.min())))
    return mean, errors


def _series(graph):
    scenes = list(_subgroups(graph, 0x8018))
    _require(len(scenes) == 1 and len(scenes[0][0]) == 12)
    result = {}
    for obj, records in _subgroups(scenes[0][1], 0x8020):
        _require(len(obj) == 30)
        if unpack_from("<H", obj)[0] != 9:
            continue
        head = _one(records, 0x8028)
        _require(len(head) == 144)
        key, family, uid, active = unpack_from("<4H", head)
        flags, = unpack_from("<H", head, 58)
        width, = unpack_from("<H", head, 98)
        stride, _, rows, _, count = unpack_from("<5H", head, 110)
        _require(key not in result and family == active == 1 and flags in (4, 8, 12)
                 and stride == 5 and 1 <= rows <= MAX_BARS and 1 <= width <= 2000)
        caches = [p for tag, parents, p in records if tag == 0x29 and parents == (40,)]
        _require(len(caches) == 1 and len(caches[0]) == 4 + 4 * count
                 and unpack_from("<I", caches[0])[0] == count and count >= rows * 5)
        points = list(Struct("<5i").iter_unpack(caches[0][4:4 + 20 * rows]))
        result[key] = uid, width, points
    return result


def _saved_errors(mean, candidates, levels, unit):
    def match(pair):
        return all(level is None or (isfinite(error) and error > 0
                   and abs((mean + direction * error) / unit - level) <= 1)
                   for level, direction, error in zip(levels, (1, -1), pair, strict=True))

    matched = [pair for pair in candidates if pair[0] == pair[1] and match(pair)]
    if not matched:
        matched = [pair for pair in candidates if match(pair)]
    visible = {tuple(error if level is not None else None
                     for level, error in zip(levels, pair, strict=True))
               for pair in matched}
    _require(len(visible) == 1)
    return visible.pop()


def _bindings(order, series, columns, left, right, bottom, high, unit, drawing):
    rows, result = [], []
    for key in order:
        dataset, width, points = series[key]
        form, table = columns[dataset]
        grouped = form != 10
        if not grouped:
            _require(len(points) == 2)
            leading, plotted = points
            x, _, height, upper, lower = plotted
            if leading != (x, height, 0, 0, 0):
                # The leading summary can retain both ends even when the
                # drawing cache stores only the upper whisker.
                summary_lower = leading[4]
                _require(leading[:4] == (x, height, height, upper) and lower == height
                         and 0 <= summary_lower < height < upper
                         and abs((height - summary_lower) - (upper - height)) <= 1)
            points = points[1:]
        for index, (point, summary) in enumerate(zip(points, _summaries(table, form, grouped), strict=True)):
            x, baseline, height, upper, lower = point
            mean, possible_errors = summary
            _require(baseline == 0 and 0 < height <= high / unit + 1
                     and left <= left + x - width / 2 < left + x + width / 2 <= right + 1
                     and isfinite(mean) and abs(mean / unit - height) <= 1)
            _, _, _, caps = _bar_object(drawing, bottom, left + x, width, height)
            upper = upper if caps[0] else None
            lower = lower if caps[1] else None
            _require((upper is None or height < upper <= high / unit + 1)
                     and (lower is None or 0 <= lower < height))
            _check_caps(caps, (upper, lower), bottom)
            # The cache may include a computed half that the graph does not
            # draw. Validate the magnitudes of the visible halves only.
            up_error, down_error = _saved_errors(mean, possible_errors, (upper, lower), unit)
            label = str(table.columns[0])
            if form == 21:
                label = label.removesuffix(" [Mean]")
            if grouped:
                label += f" · {index + 1}"
            rows.append((mean, up_error, down_error, label))
            result.append([left + x, width, height, upper, mean, up_error, lower, down_error])
            _require(len(result) <= MAX_BARS)
    _require(len({bar[0] for bar in result}) == len(result))
    frame = pd.DataFrame(rows, columns=[*BAR_VALUES, "Group"])
    if frame["Lower error"].isna().all():
        frame = frame.drop(columns="Lower error")
    return frame, result


def read_bar_graph(graph, sources, tables, remaining_cells):
    """Restore a single-source column graph only after checking data, cache and drawing."""
    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    left, right, bottom, high, unit = _scale(graph, chart)
    sheet_ids = _id_array(_one(graph, 0x14))
    _require(len(sheet_ids) == 1)
    sheet = sheet_ids[0]
    order = _id_array(_one(graph, 0x15))
    links = _one(graph, 0x16)
    _require(len(links) == 2 + 12 * len(order) and unpack_from("<H", links)[0] == len(order))
    series = _series(graph)
    _require(len(series) == len(order) == len(set(order)) and set(series) == set(order)
             and Counter(value[0] for value in series.values())
             == Counter(uid for uid, _, _ in Struct("<3i").iter_unpack(links[2:])))
    columns = _columns(sheet, tables[sheet], sources[sheet])
    drawing = _drawing_objects(_preview(graph))
    points, bindings = _bindings(order, series, columns, left, right, bottom, high, unit, drawing)
    _require(points.size <= remaining_cells)
    return points, {"kind": "columns", "bottom": bottom, "bounds": [0.0, high], "unit": unit, "bars": bindings}


def _saved_half(mean, height, level, distance, direction, unit, maximum):
    if level is None:
        _require(distance is None)
        return
    _require(type(level) is int and 0 <= level <= maximum + 1 and (level - height) * direction > 0
             and isfinite(distance) and distance > 0 and abs((mean + direction * distance) / unit - level) <= 1)


def _edited_half(mean, distance, old_mean, old_distance, level, direction, unit, high):
    if level is None:
        if not isnan(distance):
            raise ValueError("This error bar side is absent in the original graph.")
        return None
    if (mean, distance) == (old_mean, old_distance):
        return 0
    end = mean + direction * distance
    if not (isfinite(distance) and distance >= 0 and 0 <= end <= high):
        raise ValueError(f"Enter a nonnegative error within the saved Y range (0 to {high:g}).")
    if end == old_mean + direction * old_distance:
        return 0
    return level - round(end / unit)


def _edited_heights(frame, style):
    try:
        bottom, (low, high), unit, bars = (style[key] for key in ("bottom", "bounds", "unit", "bars"))
        _require(type(bottom) is int and -32768 <= bottom <= 32767
                 and low == 0 and isfinite(high) and isfinite(unit) and 0 < unit <= high
                 and 100 <= high / unit <= 20_000 and isinstance(bars, list) and 0 < len(bars) <= MAX_BARS
                 and len(frame) == len(bars) and set(BAR_VALUES[:2]) <= set(frame.columns))
        data = frame.reindex(columns=BAR_VALUES).to_numpy(dtype=float, na_value=np.nan)
        saved = []
        updates = []
        for (mean, up_error, down_error), entry in zip(data, bars, strict=True):
            _require(isinstance(entry, (list, tuple)) and len(entry) in (6, 8))
            # 0.10 stored just the upper half in the project.
            x, width, height, upper, old_mean, old_up, lower, old_down = (*entry, None, None)[:8]
            _require(all(type(value) is int for value in (x, width, height))
                     and -32768 <= x <= 32767 and 0 < width <= 2000
                     and 0 < height <= high / unit + 1 and (upper is not None or lower is not None)
                     and isfinite(old_mean) and abs(old_mean / unit - height) <= 1)
            _saved_half(old_mean, height, upper, old_up, 1, unit, high / unit)
            _saved_half(old_mean, height, lower, old_down, -1, unit, high / unit)
            if not isfinite(mean) or (mean != old_mean and not low <= mean <= high):
                raise ValueError(f"Enter a finite mean within the saved Y range ({low:g} to {high:g}).")
            up_shift = _edited_half(mean, up_error, old_mean, old_up, upper, 1, unit, high)
            down_shift = _edited_half(mean, down_error, old_mean, old_down, lower, -1, unit, high)
            new_height = height if mean == old_mean else round(mean / unit)
            saved.append((x, width, height, (upper, lower)))
            updates.append((height - new_height, up_shift, down_shift))
        return bottom, saved, updates
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid saved Prism column graph settings.") from error


def validate_bar_values(frame, style):
    _edited_heights(frame, style)


def edit_bar_preview(frame, style, preview):
    """Produce a preview with only the matched EMF+ data primitives changed."""
    if not isinstance(preview, dict) or preview.get("format") != "emf":
        raise ValueError("Editable Prism column graphs require an EMF preview.")
    emf = validate_binary_graph(preview)
    bottom, bars, updates = _edited_heights(frame, style)
    drawing = _drawing_objects(emf)
    objects = []
    for x, width, height, levels in bars:
        bar = _bar_object(drawing, bottom, x, width, height)
        _check_caps(bar[3], levels, bottom)
        objects.append(bar)
    if not any(any(update) for update in updates):
        return preview

    updated = bytearray(emf)
    for (outline, top, fill, caps), (dy, up_shift, down_shift) in zip(objects, updates, strict=True):
        if not any((dy, up_shift, down_shift)):
            continue
        new_top = min(bottom, max(-32768, top + dy))
        if dy:
            for index in (3, 5, 7, 9):
                pack_into("<h", updated, outline + 2 * index, new_top)
            if fill:
                offset, (_, y, _, height) = fill
                pack_into("<h", updated, offset + 2, new_top)
                pack_into("<h", updated, offset + 6, min(32767, max(0, y + height - new_top)))
        for direction, cap, shift in zip((1, -1), caps, (up_shift, down_shift), strict=True):
            if cap is None or not (dy or shift):
                continue
            whisker, end = cap
            new_end = min(new_top, max(-32768, end + shift)) if direction == 1 else max(new_top, min(bottom, end + shift))
            for index in (1, 3, 5):
                pack_into("<h", updated, whisker + 2 * index, new_end)
            if new_end == new_top:
                center, = unpack_from("<h", updated, whisker + 8)
                pack_into("<h", updated, whisker, center)
                pack_into("<h", updated, whisker + 4, center)
            pack_into("<h", updated, whisker + 14, new_top)
    _emf_dimensions(updated)
    return {"format": "emf", "data": b64encode(updated).decode("ascii")}
