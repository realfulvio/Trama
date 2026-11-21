"""Recover the viewport shared by the model comparisons on a linked XML XY graph."""
from math import isclose, isfinite
from struct import Struct, error as StructError, unpack, unpack_from

from .axis_breaks import normalise_axis_breaks
from .prism_binary import _DATASET
from .prism_binary_editable import _id_array, _one, _require, _subgroups, _text_object


def fit_curve_sheet(contents):
    try:
        count, unused, summary, curve, *rest = unpack("<10i", _one(contents, 0x3C))
    except (ValueError, StructError):
        return None
    if (count == 9 and unused == -1 and set(rest) == {-1} and 0 <= summary <= 65535
            and 0 <= curve <= 65535 and summary != curve):
        return curve
    return None


def indexed_fit_views(graphs):
    views = {}
    for graph in graphs.values():
        if not graph:
            continue
        try:
            observed, curves = _id_array(_one(graph, 0x14))
        except (ValueError, StructError):
            continue
        key = observed, curves
        views[key] = graph if key not in views else None
    return views


def _interval(axis, key, scales, encoding):
    header, records = scales[key]
    low, high, unit = unpack_from("<3d", header, 2)
    scale, extent, gap = unpack_from("<3H", header, 28)
    step, start = unpack_from("<2d", header, 54)
    span = extent - gap
    _require(scale == 0 and span > 0 and all(isfinite(x) for x in (low, high, unit, step, start))
             and low < high and unit > 0 and step > 0 and isclose((high - low) / unit, span, abs_tol=1))
    labels = []
    for tag, path, raw in records:
        if tag == 0x26 and not path:
            _require(axis == "x" and len(raw) == 34)
            value, = unpack_from("<d", raw)
            text, end, _ = bytes(raw[10:22]).partition(b"\0")
            _require(end and text and low <= value <= high)
            labels.append([value, text.decode(encoding)])
    segment = {"low": low, "high": high, "major_step": step, "major_origin": start}
    # The saved dose-response profile displays exponents as concentrations. The
    # subdivision code alone also occurs on axes labelled in raw log units.
    subdivisions, = unpack_from("<H", header, 52)
    if (axis == "x" and unpack_from("<4H", header, 78) == (2, 2, 0, 2)
            and subdivisions in (0, 9) and step == 1 and start.is_integer()
            and (high - low) * 9 <= 199):
        segment["tick_format"] = "power10"
        segment["minor_ticks"] = 8 if subdivisions == 9 else 0
    if labels:
        segment["tick_labels"] = labels
    return segment, span, gap


def _replicate_display(graph, drawings, observed_columns, curve_records):
    # This drawing family has row means, SD caps on one side and separate fitted lines.
    # A different drawing profile can still contribute a valid saved viewport.
    if any(tag == 0xAE and not path for tag, path, _ in graph):
        return {}
    curve_ids = {}
    for tag, _, raw in curve_records:
        if tag == 0x0D:
            if len(raw) != 24:
                return {}
            slot, dataset, repeat = unpack_from("<3I", raw)
            if slot >= len(observed_columns) or slot in curve_ids or repeat != 1:
                return {}
            curve_ids[slot] = dataset
    if len(curve_ids) != len(observed_columns) or len(set(curve_ids.values())) != len(curve_ids):
        return {}
    settings, curves = {}, {}
    for dataset, raw in drawings.items():
        family, = unpack_from("<H", raw, 2)
        side, error, draw, bars = unpack_from("<4H", raw, 8)
        symbol, marker, _, stroke = unpack_from("<4H", raw, 58)
        if dataset in observed_columns:
            if (family, error, draw, bars, symbol, stroke) != (0, 1, 1, 2, 12, 0):
                return {}
            if side not in (0, 1) or marker not in (1, 2) or raw[84:88] != raw[88:92] or raw[87]:
                return {}
            label, _ = observed_columns[dataset]
            settings[label] = {"marker": {1: "s", 2: "^"}[marker], "side": ("upper", "lower")[side],
                               "color": "#" + bytes(raw[84:87]).hex()}
        else:
            if (family, side, error, draw, bars, symbol, marker, stroke) != (0, 2, 0, 2, 2, 138, 0, 1) or raw[71]:
                return {}
            curves[dataset] = "#" + bytes(raw[68:71]).hex()
    if set(curves) != set(curve_ids.values()):
        return {}
    for slot, (label, _) in enumerate(observed_columns.values()):
        settings[label]["line_color"] = curves[curve_ids[slot]]
    return settings


def _viewport(graph, plotted, observed_columns, curve_records, encoding):
    from .presentation import validated_style

    axes = [raw for tag, path, raw in graph if tag == 0x17 and not path]
    _require(len(axes) == 3 and all(len(raw) == 60 for raw in axes))
    scales = {}
    for header, records in _subgroups(graph, 0x8025):
        _require(len(header) == 134)
        key, = unpack_from("<H", header)
        _require(key not in scales)
        scales[key] = header, records

    (scene_header, objects), = _subgroups(graph, 0x8018)
    _require(len(scene_header) == 12)
    titles, series, drawings = {}, {}, {}
    for header, records in _subgroups(objects, 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 2:
            key, text = _text_object(records, encoding, unpack_from("<H", header, 28)[0])
            _require(key not in titles and len(text) <= 160)
            titles[key] = text
        elif kind == 9:
            saved = _one(records, 0x8028)
            series_id, _, dataset, visible = unpack_from("<4H", saved)
            _require(len(saved) == 144 and series_id not in series and visible == 1)
            series[series_id] = dataset
            drawings[dataset] = saved
    order = _id_array(_one(graph, 0x15))
    _require(len(order) == len(series) == len(plotted) and set(order) == series.keys()
             and set(series.values()) == plotted)
    style = {}
    charts = [raw for tag, path, raw in graph if tag == 0x13 and not path]
    if len(charts) == 1 and len(charts[0]) == 48:
        title_id, = unpack_from("<H", charts[0], 32)
        if title_id in titles:
            style["title"] = titles[title_id].replace("$", r"\$")
    for axis, raw in zip(("x", "y"), axes[:2], strict=True):
        length, _, scale, title, count, _, first, second, _ = unpack_from("<9H", raw, 42)
        _require(scale == 0 and count == (2 if axis == "x" else 1) and 100 <= length <= 20000)
        segment, span, gap = _interval(axis, first, scales, encoding)
        _require(gap == 0)
        low, high = unpack_from("<2d", raw, 16)
        _require(low == segment["low"])
        style[axis + "label"] = titles[title].replace("$", r"\$")
        if axis == "y":
            _require(high == segment["high"] and span == length and (high - low) / segment["major_step"] <= 199)
            style["axis"] = {"y": {"min": low, "max": high, "step": segment["major_step"],
                                   "start": segment["major_origin"]}}
        else:
            other, other_span, gap = _interval(axis, second, scales, encoding)
            _require(high == other["high"] and span + gap + other_span == length)
            segment["share"] = 100 * span / (length - gap)
            other["share"] = 100 - segment["share"]
            style["axis_breaks"] = normalise_axis_breaks({
                "axis": "x", "gap": gap / length, "segments": [segment, other]})
    return validated_style(style), _replicate_display(graph, drawings, observed_columns, curve_records)


def fit_viewport(graph, curve_records, producer, curve_sheet, observed_columns, encoding):
    """Only use a view whose four plotted datasets belong to the two known producer tables."""
    if not graph or not curve_records:
        return None
    try:
        columns = set()
        for tag, _, raw in curve_records:
            if tag == 0x800F:
                field, _, _, source, sheet, storage, _, kind, role, form, repeat, *_ = _DATASET.unpack(raw)
                _require((source, sheet, storage) == (producer, curve_sheet, 102))
                if (kind, role, form, repeat) == (1, 40, 10, 1):
                    _require(field not in columns)
                    columns.add(field)
        _require(len(columns) == len(observed_columns) == 2 and columns.isdisjoint(observed_columns))
        links = _one(graph, 0x16)
        _require(len(links) == 50 and unpack_from("<H", links)[0] == 4)
        plotted = [field for field, _, _ in Struct("<3i").iter_unpack(links[2:])]
        _require(set(plotted) == columns.union(observed_columns))
        return _viewport(graph, set(plotted), observed_columns, curve_records, encoding)
    except (KeyError, TypeError, ValueError, StructError, OverflowError):
        return None
