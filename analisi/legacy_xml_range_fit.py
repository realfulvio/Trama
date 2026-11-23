"""Recover a verified legacy log-Y transform and its bounded straight-line fit."""
from collections import Counter
from hashlib import sha256
import json
from math import isfinite
from struct import Struct, error as StructError, unpack, unpack_from
from sys import float_info

from pandas.api.types import is_numeric_dtype

from . import regression_range as rr
from .legacy_binary import _DATASET
from .graph_annotations import ANNOTATIONS, validate_annotation
from .presentation import validated_style
from .legacy_binary_editable import (_axis_config, _id_array, _one, _require, _series_columns, _subgroups,
                                    _text_object)
from .legacy_binary_results import _title
from .legacy_restore import LEGACY_NOTES, LEGACY_TITLE, _append_linked_recipe
from .legacy_xml_fit_axes import fit_result_sheets
from .select_transform import CALCULATED, SELECT_TRANSFORM
from .xy_series import XY_METHOD

_LOG_Y_PROFILE = "d0250f4c9e851ef9e392ef5503f0bb9c037ee7e8e444a81fef234c301d3b73c2"
_FIT_PROFILE = "08d4c3231721f472516cb3ed49c065574ebb37cfb5cd7bc5e88448cba3424a98"
_FIT_HEADERS = (
    "d08c9536a81512bd6dba99527ebed05352ecc7fc2047f778d0b03e737d31975a",
    "64ee30d02330037eaad58328acb90bda22b9f953a943f228560e52992c1e75d8",
)
_CONSTRAINTS = {
    0xC4: "e02d212ac7025fc2cfd09d772a44140e50cb40858803eb21e7579b4496742300",
    0xC9: "6e5c4056a66e8215d08096d586b149230c80055549f2e42940192d0d35131aaa",
}


def _heading(records, expected):
    summary = _one(records, 0xA)
    _require(len(summary) == 300 and bytes(summary[24:]).partition(b"\0")[0] == expected)


def _transformed_response(records, sheet, producer):
    link = _one(records, 0xD)
    _require(len(link) == 24)
    slot, response, repeats = unpack_from("<3I", link)
    _require(slot == 0 and repeats == 1)
    fields = [_DATASET.unpack(payload) for tag, _, payload in records if tag == 0x800F]
    matches = [item for item in fields if item[0] == response]
    _require(len(matches) == 1)
    _, _, _, analysis, owner, storage, _, kind, role, form, repeat, x_uid, _, _, _ = matches[0]
    _require((analysis, owner, storage, kind, role, form, repeat) == (producer, sheet, 102, 1, 8, 10, 1))
    _require(sum(item[0] == x_uid and item[3:6] == (producer, sheet, 102)
                 and item[7:11] == (1, 4, 10, 1) for item in fields) == 1)
    return response


def _fit_options(kind, records, response):
    _require(kind[:2] == (0, 5) and kind[3:] == (1, 255, 1, 65535, 0))
    _heading(records, b"Straight lineLeast squares fit")
    _require(fit_result_sheets(records) is not None)
    _require(unpack("<H3i", _one(records, 0x3D)) == (1, response, response, response))
    block = bytes(_one(records, 0x46))
    # Ignore the curve count and drawing bounds, observed X summary, and fit limits.
    # Everything else must match the verified least-squares configuration.
    _require(len(block) == 1352 and sha256(block[:1100] + block[1124:1132] + block[1164:1196]
                                          + block[1212:]).hexdigest() == _FIT_PROFILE)
    count, curve_min, curve_max = unpack_from("<3d", block, 1100)
    minimum, maximum = unpack_from("<2d", block, 1196)
    _require(all(isfinite(value) and abs(value) < float_info.max for value in
                 (minimum, maximum, curve_min, curve_max)))
    _require(isfinite(count) and count.is_integer() and 2 <= count <= rr.MAX_POINTS)
    config, = _subgroups(records, 0x8047)
    _require(unpack("<4i4B6i", config[0]) == (1, 0, 2, 0, 43, 22, 0, 10, 1, response, 1, response, -1, -1))
    models = list(_subgroups(config[1], 0x8048))
    _require(tuple(sha256(header).hexdigest() for header, _ in models) == _FIT_HEADERS)
    for _, model in models:
        _require(b"".join(bytes(_one(model, 0x49)).rstrip(b"\0").split()) == b"Y=YIntercept+Slope*X")
        _require(all(sha256(_one(model, tag)).hexdigest() == digest for tag, digest in _CONSTRAINTS.items()))
    return rr.ranges({rr.FIT_MIN: minimum, rr.FIT_MAX: maximum,
                      rr.CURVE_MIN: curve_min, rr.CURVE_MAX: curve_max, rr.CURVE_POINTS: int(count)})


def _chart(graph, encoding, datasets):
    """Read the chart and its verified set of visible, unweighted XY series."""
    links = _one(graph, 0x16)
    _require(len(links) == 2 + 12 * len(datasets) and unpack_from("<H", links)[0] == len(datasets))
    _require({dataset for dataset, _, _ in Struct("<3i").iter_unpack(links[2:])} == datasets)
    (scene, contents), = _subgroups(graph, 0x8018)
    _require(len(scene) == 12)
    text, drawings = {}, {}
    for header, records in _subgroups(contents, 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 2:
            flags, = unpack_from("<H", header, 28)
            text_id, title = _text_object(records, encoding, flags, multiline=True)
            _require(text_id not in text)
            text[text_id] = title, header, records
        elif kind == 9:
            raw = _one(records, 0x8028)
            _require(len(raw) == 144)
            identity, family, dataset, visible, side, error, _, bars = unpack_from("<8H", raw)
            _require(dataset not in drawings and (family, visible, side, error, bars) == (0, 1, 2, 0, 2))
            drawings[dataset] = identity, raw
    order = _id_array(_one(graph, 0x15))
    _require(set(drawings) == datasets
             and len(order) == len(datasets) and set(order) == {identity for identity, _ in drawings.values()})
    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    return chart, text, {dataset: raw for dataset, (_, raw) in drawings.items()}


def _viewport(graph, chart, text):
    title_id, = unpack_from("<H", chart, 32)
    style = {"title": text[title_id][0], "axis": {}}
    handles = {unpack_from("<H", raw)[0]: raw for raw, _ in _subgroups(graph, 0x8025)}
    axes = [raw for tag, path, raw in graph if tag == 0x17 and not path]
    for name, axis, raw in zip(("x", "y"), _axis_config(graph, viewport_only=True), axes[:2], strict=True):
        _require(axis["scale"] == "linear" and not axis["custom_ticks"] and unpack_from("<H", raw, 50)[0] == 1)
        handle, = unpack_from("<H", raw, 54)
        step, start = unpack_from("<2d", handles[handle], 54)
        low, high = axis["bounds"]
        style[name + "label"] = text[axis["title"]][0]
        style["axis"][name] = {"min": low, "max": high, "step": step, "start": start}
    return style


def _text_notes(graph, chart, text):
    left, top, right, bottom = unpack_from("<4h", chart)
    if left >= right or top >= bottom:
        return []
    axis_labels = {unpack_from("<H", raw, 48)[0] for tag, path, raw in graph if tag == 0x17 and not path}
    axis_labels.add(unpack_from("<H", chart, 32)[0])
    notes = []
    for identity, (caption, header, records) in text.items():
        if not caption or identity in axis_labels or unpack_from("<H", header, 28)[0]:
            continue
        x0, y0, x1, y1 = unpack_from("<4h", header, 18)
        if not (left <= x0 < right and top <= y0 < y1 <= bottom and x0 < x1):
            continue
        font = [raw for tag, path, raw in records if tag == 0x2D and path == (43,)]
        if len(font) != 1 or len(font[0]) != 26:
            continue
        size, = unpack_from("<H", font[0], 10)
        alignment = "right" if x1 > right else "left"
        x = .98 if alignment == "right" else (x0 - left) / (right - left)
        y = (bottom - (y0 + y1) / 2) / (bottom - top)
        try:
            notes.append(validate_annotation({"text": caption, "position": [x, y], "units": "axes",
                                              "align": alignment, "size": size, "color": "#000000"}))
        except ValueError:
            continue
    return notes


def _fit_graph_style(graph, encoding, observation, fitted):
    """Recover the viewport and two artists when both series belong to this recipe."""
    chart, text, drawings = _chart(graph, encoding, {observation, fitted})
    points, line = drawings[observation], drawings[fitted]
    _require(all(unpack_from("<H", raw, 12)[0] == 2 for raw in (points, line)))
    symbol, marker, size, stroke = unpack_from("<4H", points, 58)
    _require((symbol, marker, stroke) == (8, 5, 0) and 1 <= size <= 30 and points[87] == 0)
    _require(unpack_from("<4H", line, 58) == (136, 0, 4, 1) and line[71] == 0)
    style = _viewport(graph, chart, text)
    style["series"] = {"scatter:1:": {"color": "#" + bytes(points[84:87]).hex(), "marker": "o",
                                       "marker_size": size},
                       "line:1:": {"color": "#" + bytes(line[68:71]).hex()}}
    notes = _text_notes(graph, chart, text)
    if notes:
        style[ANNOTATIONS] = notes
    return validated_style(style)


def _raw_graph(graphs, encoding, source, dataset, x, y):
    matches = []
    for graph in graphs.values():
        if not graph:
            continue
        try:
            _require(_id_array(_one(graph, 0x14)) == [source])
            chart, text, drawings = _chart(graph, encoding, {dataset})
            points = drawings[dataset]
            symbol, marker, size, stroke = unpack_from("<4H", points, 58)
            _require(unpack_from("<H", points, 12)[0] == 0 and (symbol, marker, stroke) == (8, 10, 1)
                     and 1 <= size <= 30 and points[71] == points[87] == 0)
            style = _viewport(graph, chart, text)
            style.update(legend="hidden", series={f"xy:1:{y}": {
                "color": "#" + bytes(points[68:71]).hex(),
                "marker_color": "#" + bytes(points[84:87]).hex(), "marker_size": size,
            }})
            title = _title(_one(graph, 9))[:160]
            _require(bool(title))
            options = {LEGACY_TITLE: title, "X": x, "Y columns": [y], "Series style": {y: "Line and points"}}
            matches.append((options, validated_style(style)))
        except (KeyError, TypeError, ValueError, StructError, OverflowError):
            continue
    return matches[0] if len(matches) == 1 else None


def _fit_graph(tables, views, encoding, source, producer, fit, observation):
    try:
        _, curve = fit_result_sheets(fit)
        graph = views[source, curve]
        records = tables[curve]
        columns = [_DATASET.unpack(raw) for tag, _, raw in records if tag == 0x800F]
        known, = (row[0] for row in columns if row[3:6] == (producer, curve, 102) and row[7:11] == (1, 40, 10, 1))
        _require(known != observation and graph is not None)
        return _fit_graph_style(graph, encoding, observation, known)
    except (KeyError, TypeError, ValueError, StructError, OverflowError):
        return None


def attach_bounded_line(analyses, sources, originals, outputs, tables, graphs, views, encoding):
    writers = Counter(outputs.values())
    for uid, parent, kind, records in analyses:
        if parent not in originals or parent not in sources or kind[:2] != (3, 255):
            continue
        emitted = outputs[uid]
        if emitted is None or emitted in originals or writers[emitted] != 1:
            continue
        dependents = [(key, fit_kind, fit) for key, source, fit_kind, fit in analyses if source == emitted]
        if len(dependents) != 1:
            continue
        frame, x, groups = sources[parent]
        try:
            _require(kind[3:] == (1, 191, 0, 3, 0) and len(groups) == 1 and len(groups[0][1]) == 1)
            _heading(records, b"Transform: Y=Log(Y)")
            _require(sha256(_one(records, 0x46)).hexdigest() == _LOG_Y_PROFILE)
            selected, = _series_columns(parent, tables[parent], frame, -1)
            _require(unpack("<H3i", _one(records, 0x3D)) == (1, selected, -1, -1))
            y, = groups[0][1]
            _require(all(is_numeric_dtype(frame[name]) for name in (x, y)))
            response = _transformed_response(tables[emitted], emitted, uid)
            (fit_uid, fit_kind, fit), = dependents
            fit_options = _fit_options(fit_kind, fit, response)
            log_y = f"log10({y})"
            _require(len(log_y) <= 160 and log_y not in frame and "\n" not in log_y and "\r" not in log_y)
            parent_title = _title(_one(records, 9))[:160]
            fit_title = _title(_one(fit, 9))[:160]
        except (KeyError, TypeError, ValueError, StructError):
            continue
        recipes = frame.attrs.setdefault("legacy_recipes", [])
        if len(recipes) > 254:
            continue
        slot = len(recipes)
        recipes.append((SELECT_TRANSFORM, {
            LEGACY_TITLE: parent_title, "Variables": [x],
            CALCULATED: [{"name": log_y, "expression": f"=LOG10(COL({json.dumps(y, ensure_ascii=False)}))"}],
        }))
        style = _fit_graph(tables, views, encoding, emitted, fit_uid, fit, response)
        if style is not None:
            frame.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
            fit_options[rr.SHOW_OUTSIDE] = True
        _append_linked_recipe(frame, slot, "Selected data", "Linear regression", {
            LEGACY_TITLE: fit_title, LEGACY_NOTES: "Fits a straight line to the log10 responses within the saved X range.",
            "X": x, "Y": log_y, **fit_options,
        })
        raw = _raw_graph(graphs, encoding, parent, selected, x, y)
        if raw is not None and len(recipes) < 256:
            options, style = raw
            frame.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
            recipes.append((XY_METHOD, options))
