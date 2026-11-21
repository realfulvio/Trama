"""Editable column plots with a band linked to a saved descriptive result."""
from hashlib import sha256
from math import ceil, floor, isclose, isfinite
from struct import Struct, error as StructError, unpack, unpack_from

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
from scipy.stats import t

from .axis_guides import DEFAULT_BAND_ALPHA
from .prism_binary import _DATASET
from .prism_binary_editable import _id_array, _one, _project_records, _require, _subgroups, _text_object
from .prism_binary_graphs import _read_title
from .prism_restore import PRISM_NOTES, PRISM_TITLE, SAVED_XY, _append_linked_recipe
from .prism_xml_binding import indexed_analyses
from .prism_zip_column import _point_colors
from .reporting import Result
from .xy_series import _numbers

QC_REFERENCE = "Imported descriptive band reference"
XML_QC = "Prism XML linked descriptive graph"
QC_POINTS = "Linked column plot data"
_MAX_POINTS = 50_000
_MAX_TICKS = 200
_SUMMARY_KIND = (65498, 255, 1, 1, 251, 0, 65535, 65535)
_SUMMARY_SETTINGS = "56bebcd536601c208b452ce9aca0d5266e1251bd554f428618cd28cf2d40e13f"
_LINK = Struct("<3i")


def _column_ids(records, owner, producer, names):
    headers = [_DATASET.unpack(raw) for tag, path, raw in records if tag == 0x800F and not path]
    fields = {row[0]: row for row in headers}
    _require(headers and len(fields) == len(headers))
    storage = 101 if producer == -1 else 102
    _require(all(row[3:6] == (producer, owner, storage) for row in headers))
    links = sorted(unpack_from("<3I", raw) for tag, path, raw in records if tag == 0x0D and not path)
    _require([slot for slot, _, _ in links] == list(range(len(names))) and len({row[1] for row in links}) == len(links))
    role = (1, 8, 10, 1) if producer == -1 else (2, 8, 12, 1)
    _require(all(repeat == 1 and fields[uid][7:11] == role for _, uid, repeat in links))
    return {uid: names[slot] for slot, uid, _ in links}


def _saved_band(records, producer, names, frame):
    selected = [ref for tag, path, raw in records if tag == 0xA9 and not path
                and (ref := unpack("<11I", raw))[1] != 0xFFFFFFFF]
    lower, upper = selected
    column = lower[3]
    _require(1 <= column <= len(names)
             and lower == (4, 25, producer, column, 0, 0, 0, 0, 0, 4, 0x07020000)
             and upper == (4, 26, producer, column, 0, 0, 0, 0, 0, 4, 0x07030000))
    reference = names[column - 1]
    data = _numbers(frame, reference)
    mask = np.isfinite(data)
    for row, slot in frame.attrs.get("excluded", ()):
        if slot == column - 1 and 0 <= row < len(data):
            mask[row] = False
    values = data[mask]
    _require(len(values) >= 2)
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    guides = [raw for tag, path, raw in records if tag == 0x26 and not path]
    _require(len(guides) == 3 and all(len(raw) == 34 for raw in guides)
             and [unpack_from("<H", raw, 8)[0] for raw in guides] == [0, 5, 0])
    start, zero, stop = (raw for tag, path, raw in records if tag == 0xA2 and not path)
    _require(all(len(raw) == 110 and unpack_from("<H", raw)[0] == 7 for raw in (start, zero, stop)))
    lo, center, hi = [unpack_from("<d", raw, 2)[0] for raw in (start, zero, stop)]
    _require(center == unpack_from("<d", guides[1])[0] and isfinite(center)
             and isclose(lo, mean - sd, rel_tol=5e-8, abs_tol=1e-12)
             and isclose(hi, mean + sd, rel_tol=5e-8, abs_tol=1e-12)
             and unpack_from("<I", start, 36)[0] == 2 and unpack_from("<I", stop, 36)[0] == 0
             and start[40:43].tobytes() == stop[40:43].tobytes()
             and start[43] == stop[43] == 0)
    return reference, {"color": "#" + bytes(start[40:43]).hex(), "alpha": DEFAULT_BAND_ALPHA, "center": center}


def _appearance(graph, encoding, names, producer, frame, columns):
    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    left, top, right, bottom = unpack_from("<4h", chart)
    width, height = right - left, bottom - top
    _require(100 <= width <= 20_000 and 100 <= height <= 20_000)
    axes = [raw for tag, path, raw in graph if tag == 0x17 and not path]
    _require(len(axes) == 3 and all(len(raw) == 60 for raw in axes))
    xaxis, yaxis = axes[:2]
    _require(unpack_from("<3H", xaxis, 42) == (width, 0, 0)
             and unpack_from("<3H", yaxis, 42) == (height, 0, 0))
    scales = {}
    for raw, children in _subgroups(graph, 0x8025):
        scale_id, = unpack_from("<H", raw)
        _require(scale_id not in scales)
        scales[scale_id] = raw, children
    _, xrecords = scales[unpack_from("<H", xaxis, 54)[0]]
    yscale, yrecords = scales[unpack_from("<H", yaxis, 54)[0]]
    positions = {}
    for tag, path, raw in xrecords:
        if tag == 0x27 and not path:
            start, span, dataset, slot = unpack("<3Hi", raw)
            _require(dataset in columns and dataset not in positions and slot == -2 and 0 <= start < start + span <= width)
            positions[dataset] = start + span / 2
    _require(positions.keys() == columns.keys() and len(set(positions.values())) == len(positions))

    start, stop = unpack_from("<2d", yaxis, 16)
    tick_low, tick_high, unit = unpack_from("<3d", yscale, 2)
    step, origin = unpack_from("<2d", yscale, 54)
    _require(-1e100 < start < stop < 1e100 and step > 0 and all(isfinite(x) for x in (origin, step, unit))
             and (tick_low, tick_high) == (start, stop) and isclose(unit * height, stop - start))
    minimum, maximum = (start - origin) / step, (stop - origin) / step
    _require(isfinite(minimum) and isfinite(maximum) and 0 < maximum - minimum <= _MAX_TICKS)
    ticks = [origin + index * step for index in range(ceil(minimum - 1e-10), floor(maximum + 1e-10) + 1)]
    reference, band = _saved_band(yrecords, producer, names, frame)

    order = _id_array(_one(graph, 0x15))
    links = _one(graph, 0x16)
    _require(len(links) == 2 + len(order) * _LINK.size and unpack_from("<H", links)[0] == len(order))
    _require(set(_LINK.iter_unpack(links[2:])) == {(uid, -1, -2) for uid in columns})
    points = {}
    for tag, path, raw in graph:
        if tag == 0xAE and not path:
            key, = unpack_from("<I", raw)
            _require(key not in points)
            points[key] = [(tag, path, raw)]
    _require(set(order) == points.keys() and len(order) == len(columns)
             and len(frame) * len(columns) <= _MAX_POINTS)
    (scene_header, scene), = _subgroups(graph, 0x8018)
    _require(len(scene_header) == 12)
    series, texts = {}, {}
    for header, records in _subgroups(scene, 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 2:
            key, title = _text_object(records, encoding, unpack_from("<H", header, 28)[0])
            _require(key not in texts)
            texts[key] = title
        elif kind == 9:
            style = _one(records, 0x8028)
            _require(len(style) == 144)
            key, family, dataset, visible, direction, error, draw, bars = unpack_from("<8H", style)
            symbol, marker, size, stroke = unpack_from("<4H", style, 58)
            _require(key in points and key not in series and dataset in columns
                     and (family, visible, direction, error, draw, bars) == (1, 1, 2, 1, 0, 2)
                     and (symbol, marker, stroke) == (0x4008, 10, 0) and 1 <= size <= 30 and style[71] == 0)
            x0, _, x1, _ = unpack_from("<4h", header, 18)
            _require(isclose((x0 + x1) / 2 - left, positions[dataset], abs_tol=1))
            colors = _point_colors(points[key], key, dataset, len(frame), painted=6, empty_default=True)
            series[key] = {"column": columns[dataset], "x": positions[dataset] / width, "size": size,
                           "color": "#" + bytes(style[68:71]).hex(), "points": colors}
        else:
            _require(kind in (8, 10))
    _require(series.keys() == set(order) and {item["column"] for item in series.values()} == set(names))
    return reference, {"series": [series[key] for key in order], "limits": [start, stop], "ticks": ticks,
                       "title": texts.get(unpack_from("<H", chart, 32)[0], ""),
                       "ylabel": texts.get(unpack_from("<H", yaxis, 48)[0], ""),
                       "aspect": height / width, "band": band}


def attach_qc_graphs(data, sources):
    try:
        originals, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        return
    candidates = []
    for producer, source, kind, contents in analyses:
        if kind != _SUMMARY_KIND or source not in sources or source not in originals:
            continue
        try:
            _require(sha256(_one(contents, 0x46)).hexdigest() == _SUMMARY_SETTINGS and bytes(_one(contents, 0x3D)) == b"\0\0")
            count, output, *unused = unpack("<11i", _one(contents, 0x3C))
            _require(count == 10 and 0 <= output <= 65535 and output not in originals and set(unused) == {-1})
        except (ValueError, StructError):
            continue
        candidates.append((producer, source, output, contents))
    if not candidates:
        return
    table_ids = {sheet for _, source, output, _ in candidates for sheet in (source, output)}
    try:
        _, encoding, graphs, tables = _project_records(data, table_ids)
    except (ValueError, StructError):
        return
    for producer, source, output, contents in candidates:
        frame = sources[source]
        names = frame.columns.tolist()
        if not 1 <= len(names) <= 128 or not all(pd.api.types.is_numeric_dtype(frame[name]) for name in names):
            continue
        try:
            columns = _column_ids(tables[source], source, -1, names)
            _column_ids(tables[output], output, producer, names)
            graph, = (value for value in graphs.values() if value is not None and _id_array(_one(value, 0x14)) == [source])
            reference, appearance = _appearance(graph, encoding, names, producer, frame, columns)
            summary_name = _read_title(_one(contents, 9), encoding)[:160]
            graph_name = _read_title(_one(graph, 9), encoding)[:160]
        except (ValueError, IndexError, KeyError, TypeError, StructError):
            continue
        recipes = frame.attrs.setdefault("prism_recipes", [])
        if len(recipes) < 255:
            recipes.append(("Descriptive statistics", {"Variables": names, QC_REFERENCE: reference, PRISM_TITLE: summary_name}))
            _append_linked_recipe(frame, len(recipes) - 1, QC_POINTS, SAVED_XY,
                                  {XML_QC: appearance, PRISM_TITLE: graph_name,
                                   PRISM_NOTES: f"The shaded band follows the mean ± SD of {reference}."})


def qc_summary(frame, summary, reference):
    """Keep the saved percentile convention and supply points to the linked graph."""
    if len(frame) * len(summary) > _MAX_POINTS:
        raise ValueError("The linked column plot contains too many points.")
    parts = []
    summary = summary.copy()
    for name in summary.index:
        data = _numbers(frame, name)
        rows = np.flatnonzero(np.isfinite(data))
        values = data[rows]
        summary.loc[name, ["Q1", "Q3"]] = np.quantile(values, [.25, .75], method="weibull")
        summary.loc[name, "Sum"] = values.sum()
        parts.append(pd.DataFrame({"Series": name, "Source row": rows + 1, "Y": values}))
    summary["Range"] = summary["Max"] - summary["Min"]
    margin = t.ppf(.975, summary["N"].to_numpy(dtype=float) - 1) * summary["SEM"]
    summary["CI 95% low"] = summary["Mean"] - margin
    summary["CI 95% high"] = summary["Mean"] + margin
    points = pd.concat(parts, ignore_index=True)
    mean, sd = summary.loc[reference, ["Mean", "SD"]] if reference in summary.index else (np.nan, np.nan)
    points["Band lower"], points["Band upper"] = mean - sd, mean + sd
    return {"Summary": summary, QC_POINTS: points}


def render_qc_graph(frame, style):
    series, band = style["series"], style["band"]
    low, high = style["limits"]
    aspect = style["aspect"]
    ticks, center = style["ticks"], band["center"]
    _require(isinstance(series, list) and 1 <= len(series) <= 128
             and -1e100 < low < high < 1e100 and 0 < aspect <= 200 and isfinite(center)
             and isinstance(ticks, list) and len(ticks) <= _MAX_TICKS + 1 and all(isfinite(tick) for tick in ticks)
             and is_color_like(band["color"]) and 0 < band["alpha"] <= 1 and len(frame) <= _MAX_POINTS)
    positions = [item["x"] for item in series]
    labels = [item["column"] for item in series]
    _require(len(set(positions)) == len(series) and len(set(labels)) == len(series)
             and all(0 < x < 1 for x in positions))
    figure = Figure(figsize=(7, 4.8), layout="constrained")
    axes = figure.add_subplot()
    axes._tramastat_numeric_axes = ("y",)
    axes.set_box_aspect(aspect)
    axes.set_xticks(positions, labels)
    for label in axes.get_xticklabels():
        label.set_parse_math(False)
    axes.set_yticks(ticks)
    axes.set(xlim=(0, 1), ylim=(low, high))
    axes.set_ylabel(style["ylabel"], parse_math=False)
    axes.set_title(style["title"], parse_math=False)
    axes.spines[["right", "top"]].set_visible(False)
    axes.axhline(center, color="#64748b", linewidth=1)
    if len(frame):
        bounds = frame[["Band lower", "Band upper"]].drop_duplicates()
        _require(len(bounds) == 1)
        low_band, high_band = bounds.iloc[0]
        if pd.notna(low_band) and pd.notna(high_band) and isfinite(low_band) and isfinite(high_band) and low_band < high_band:
            axes.axhspan(low_band, high_band, facecolor=band["color"], alpha=band["alpha"],
                        edgecolor="none", zorder=0, gid="linked-control-band")
    tables = []
    for index, item in enumerate(series, 1):
        group = frame.loc[frame["Series"] == item["column"], ["Source row", "Y"]].copy()
        colors = dict(item["points"])
        _require(1 <= item["size"] <= 30 and is_color_like(item["color"]) and len(colors) <= _MAX_POINTS
                 and all(type(row) is int and 0 <= row < _MAX_POINTS and is_color_like(color)
                         for row, color in colors.items()))
        if group.empty:
            continue
        group["Symbol color"] = [colors.get(row - 1, item["color"]) for row in group["Source row"]]
        group["X"], group["Dataset"], group["Series"], group["Geometry"] = item["x"], index, item["column"], "points"
        axes.scatter(group["X"], group["Y"], c=group["Symbol color"], s=item["size"] ** 2)
        tables.append(group)
    if not tables:
        raise ValueError("The saved column graph has no points.")
    return Result({"Saved XY coordinates": pd.concat(tables, ignore_index=True)}, figure)
