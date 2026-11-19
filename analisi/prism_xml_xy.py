"""Restore replica-based XY error bars from the graph block of a legacy XML project."""

from base64 import b64decode
from math import ceil, floor, isfinite
from struct import Struct, error as StructError, unpack_from
from zlib import decompressobj, error as ZlibError

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from .data import MAX_ENTRY
from .prism_binary import _DATASET
from .prism_binary_editable import (_axis_config, _id_array, _one, _project_records, _require, _subgroups,
                                    _text_object)
from .prism_binary_graphs import _read_title
from .prism_restore import PRISM_TITLE, SAVED_XY
from .prism_xml_binding import restored_binding_recipes
from .prism_xml_binding_layout import attach_binding_layout
from .reporting import Result

XML_ERROR_BARS = "Prism XML XY errors"
_TEMPLATE_TYPE = "{urn:schemas-microsoft-com:datatypes}dt"
_MARKERS = {1: "s", 5: "o"}
_LINKS = Struct("<3i")
_POINT_STRIDE = 249
_MAX_GRAPH_POINTS = 50_000
_MAX_TICKS = 200


def attach_xml_error_graphs(root, namespace, sources):
    """Attach native recipes to their source tables. Bad artwork does not stop data import."""
    templates = root.findall(namespace + "Template")
    if not sources or len(templates) != 1:
        return
    template = templates[0]
    if len(template) or template.get(_TEMPLATE_TYPE) != "bin.base64":
        return
    try:
        compressed = b64decode("".join((template.text or "").split()), validate=True)
        decoder = decompressobj()
        data = decoder.decompress(compressed, MAX_ENTRY + 1)
        if len(data) > MAX_ENTRY or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            return
        index, encoding, graphs, tables = _project_records(data, sources)
    except (ValueError, ZlibError, StructError):
        return

    try:
        binding = list(restored_binding_recipes(data, sources))
    except (ValueError, StructError):
        binding = []
    for _, _, frame, method, options in binding:
        recipes = frame.attrs.setdefault("prism_recipes", [])
        if len(recipes) < 256:
            recipes.append((method, options))
    attach_binding_layout(data, sources, binding)

    for uid in index:
        graph = graphs.get(uid)
        if not graph or any(tag in {0x5E, 0xF00} and not path for tag, path, _ in graph):
            continue
        try:
            table, = _id_array(_one(graph, 0x14))
            frame, x, groups = sources[table]
            columns = _replicate_columns(tables[table], table, groups)
            style = _graph_style(graph, encoding, table, columns, len(frame))
            view_name = _read_title(_one(graph, 9), encoding)
            # Empty tables remain editable even when they cannot produce a graph yet.
            options = {PRISM_TITLE: view_name[:160], "X": x, XML_ERROR_BARS: style}
        except (IndexError, KeyError, TypeError, ValueError, StructError):
            continue
        frame.attrs.setdefault("prism_recipes", []).append((SAVED_XY, options))


def _replicate_columns(records, table, groups):
    fields = {}
    links = {}
    for tag, _, data in records:
        if tag == 0x0D:
            # The template reserves one ID field per replica in each link.
            _require(len(data) >= 24)
            index, uid, repeat = unpack_from("<3I", data)
            _require(index not in links and index < len(groups))
            label, columns = groups[index]
            _require(len(data) == 24 + 8 * repeat and 2 <= repeat == len(columns))
            links[index] = uid, label, columns
        elif tag == 0x800F:
            uid, _, _, analysis, owner, storage, _, kind, role, form, repeat, linked_x, _, _, _ = _DATASET.unpack(data)
            _require(uid not in fields and (analysis, owner, storage, kind) == (-1, table, 101, 1))
            fields[uid] = (role, form, repeat, linked_x)
    _require(len(links) == len(groups))
    xs = [uid for uid, values in fields.items() if values[:3] == (4, 10, 1)]
    _require(len(xs) == 1 and len(fields) == 1 + len(links))
    x, = xs
    result = {}
    for uid, label, columns in links.values():
        _require(uid not in result and fields[uid] == (8, 61, len(columns), x))
        result[uid] = label, columns
    return result


def _point_directions(payload, dataset, rows):
    _, count, stride = unpack_from("<3I", payload)
    _require(stride == _POINT_STRIDE and count == rows and len(payload) == 12 + count * stride)
    seen, changes = set(), []
    for offset in range(12, len(payload), stride):
        uid, row = unpack_from("<2I", payload, offset + 4)
        flag = payload[offset]
        _require(uid == dataset and row < count and row not in seen and flag in (0, 0x41))
        seen.add(row)
        if flag == 0x41:
            direction = payload[offset + 77]
            _require(direction in (0, 1))
            changes.append([row, direction])
    return changes


def _graph_style(graph, encoding, table, columns, rows):
    charts = list(_subgroups(graph, 0x8018))
    _require(len(charts) == 1 and len(charts[0][0]) == 12)
    order = _id_array(_one(graph, 0x15))
    _require(len(order) * rows <= _MAX_GRAPH_POINTS and len(set(order)) == len(order))

    links = _one(graph, 0x16)
    _require(len(links) == 2 + len(order) * _LINKS.size and unpack_from("<H", links)[0] == len(order))
    linked = set()
    for uid, sheet, _ in _LINKS.iter_unpack(links[2:]):
        _require(uid in columns and uid not in linked and sheet == table)
        linked.add(uid)

    points = {}
    for kind, path, payload in graph:
        if kind == 0xAE and not path:
            key, = unpack_from("<I", payload)
            _require(key not in points)
            points[key] = payload
    _require(points.keys() == set(order))

    series, labels = {}, {}
    for header, records in _subgroups(charts[0][1], 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        _require(kind in (2, 8, 9, 10))
        if kind == 2:
            flags, = unpack_from("<H", header, 28)
            text_id, text = _text_object(records, encoding, flags)
            _require(text_id not in labels)
            labels[text_id] = text
        if kind != 9:
            continue
        style = _one(records, 0x8028)
        _require(len(style) == 144)
        key, family, dataset, visible, direction, error, draw, bars = unpack_from("<8H", style)
        symbol, marker, size, stroke = unpack_from("<4H", style, 58)
        _require(key in points and key not in series and dataset in linked and
                 (family, visible, error, draw, bars, symbol, stroke) == (0, 1, 2, 1, 2, 8, 1)
                 and direction in (0, 1) and marker in _MARKERS and 1 <= size <= 30)
        label, names = columns[dataset]
        changes = _point_directions(points[key], dataset, rows)
        # Three little-endian COLORREF fields describe the symbol, line and whisker.
        colors = [bytes(style[offset:offset + 4]) for offset in (68, 84, 88)]
        _require(all(not color[3] for color in colors))
        series[key] = {"label": label, "columns": names, "dataset": dataset,
                       "marker": _MARKERS[marker], "size": size, "colors": ["#" + c[:3].hex() for c in colors],
                       "default": direction, "changes": changes}
    _require(series.keys() == set(order) and {item["dataset"] for item in series.values()} == linked)

    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    chart_title, = unpack_from("<H", chart, 32)
    axes = _axis_config(graph)
    records = [payload for tag, path, payload in graph if tag == 0x17 and not path]
    scales = {unpack_from("<H", header)[0]: header for header, _ in _subgroups(graph, 0x8025)}
    settings = []
    for axis, record in zip(axes, records[:2], strict=True):
        scale_id, = unpack_from("<H", record, 54)
        _require(axis["scale"] == "linear" and not axis["custom_ticks"])
        step, origin = unpack_from("<2d", scales[scale_id], 54)
        start, stop = axis["bounds"]
        _require(isfinite(step) and step > 0 and isfinite(origin))
        low, high = (start - origin) / step, (stop - origin) / step
        _require(isfinite(low) and isfinite(high) and 0 <= high - low <= _MAX_TICKS)
        ticks = [origin + i * step for i in range(ceil(low - 1e-10), floor(high + 1e-10) + 1)]
        settings.append({"bounds": axis["bounds"], "ticks": ticks, "label": labels.get(axis["title"], "")})
    return {"series": [series[key] for key in order], "axes": settings, "title": labels.get(chart_title, ""),
            "aspect": axes[1]["length"] / axes[0]["length"]}


def render_xml_error_graph(frame, options):
    try:
        return _render(frame, options)
    except (IndexError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid source columns or settings for the saved XY graph.") from error


def _render(frame, options):
    style = options[XML_ERROR_BARS]
    series, scales = style["series"], style["axes"]
    _require(isinstance(series, list) and 0 < len(series) <= 128 and len(scales) == 2)
    _require(len(series) * len(frame) <= _MAX_GRAPH_POINTS)
    aspect = float(style["aspect"])
    _require(isfinite(aspect) and 0.005 <= aspect <= 200)
    width = float(np.clip(5 / aspect, 4, 12))
    figure = Figure(figsize=(width, 5), layout="constrained")
    axes = figure.add_subplot()
    axes.set_box_aspect(aspect)
    axes.spines[["right", "top"]].set_visible(False)
    axes.set_title(style["title"], parse_math=False)
    for axis, scale, limits, ticks in zip((axes.xaxis, axes.yaxis), scales, (axes.set_xlim, axes.set_ylim),
                                         (axes.set_xticks, axes.set_yticks), strict=True):
        low, high = scale["bounds"]
        values = scale["ticks"]
        _require(isfinite(low) and isfinite(high) and low < high and len(values) <= _MAX_TICKS + 1
                 and all(isfinite(value) for value in values))
        ticks(values)
        limits(low, high)
        axis.set_label_text(scale["label"], parse_math=False)

    x = pd.to_numeric(frame[options["X"]], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    tables = []
    for item in series:
        columns, changes = item["columns"], item["changes"]
        _require(isinstance(columns, list) and len(columns) >= 2 and len(columns) == len(set(columns))
                 and isinstance(changes, list) and len(changes) <= _MAX_GRAPH_POINTS and item["default"] in (0, 1))
        raw = frame[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        raw = np.where(np.isfinite(raw), raw, np.nan)
        counts = np.isfinite(raw).sum(axis=1)
        shown = np.isfinite(x) & (counts > 0)
        if not shown.any():
            continue
        center = np.full(len(frame), np.nan)
        deviation = np.full(len(frame), np.nan)
        with np.errstate(over="ignore", invalid="ignore"):
            center[shown] = np.nanmean(raw[shown], axis=1)
            complete = shown & (counts > 1)
            deviation[complete] = np.nanstd(raw[complete], axis=1, ddof=1)
        if not np.isfinite(center[shown]).all() or not np.isfinite(deviation[complete]).all():
            raise ValueError("The saved XY graph has values outside the supported numerical range.")

        direction = np.full(len(frame), item["default"], dtype=np.int8)
        for row, side in changes:
            _require(type(row) is int and 0 <= row < _MAX_GRAPH_POINTS and side in (0, 1))
            if row < len(frame):
                direction[row] = side
        below = np.where(direction == 1, deviation, 0)
        above = np.where(direction == 0, deviation, 0)
        marker_color, line_color, whisker_color = item["colors"]
        _require(item["marker"] in _MARKERS.values() and 1 <= item["size"] <= 30
                 and all(is_color_like(color) for color in item["colors"]))
        axes.errorbar(x, center, yerr=np.array([below, above]), color=line_color, ecolor=whisker_color,
                      marker=item["marker"], markersize=item["size"], markerfacecolor=marker_color,
                      markeredgecolor=marker_color, capsize=0, label=str(item["label"]))
        tables.append(pd.DataFrame({"X": x[shown], "Y": center[shown], "Dataset": item["dataset"],
                                    "Series": item["label"], "Geometry": "line", "Y minus": below[shown],
                                    "Y plus": above[shown]}))
    if not tables:
        raise ValueError("The saved graph has no complete XY points.")
    return Result({"Saved XY coordinates": pd.concat(tables, ignore_index=True)}, figure)
