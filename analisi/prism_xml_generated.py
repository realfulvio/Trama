"""Restore source-free XY curves from their analysis-owned saved values."""

from math import ceil, floor, isfinite
from struct import Struct, error as StructError, unpack_from

from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter
import numpy as np
import pandas as pd

from .custom_equations import compile_equation
from .data import MAX_CELLS
from .prism_binary import _DATASET, _record_once, _records
from .prism_binary_editable import _axis_config, _id_array, _one, _project_records, _require, _subgroups
from .prism_binary_graphs import _read_title
from .prism_binary_results import _column_ids, _read_groups, _sequence_snapshot
from .prism_restore import PRISM_NOTES, PRISM_TITLE, SAVED_XY
from .prism_xml_binding_layout import _annotation, _caption
from .reporting import Result

XML_GENERATED_XY = "Prism XML generated XY graph"
_MAX_SERIES = 24
_MAX_TICKS = 200
_LINK = Struct("<3i")
_DOUBLE = Struct("<d")


def _generator_records(data):
    records = [(tag, path[1:], payload) for tag, path, payload in _records(data)
               if path == (1,) or path[:2] == (1, 57)]
    groups = {}
    for header, contents in _subgroups(records, 0x8039):
        if len(header) == 2:
            uid, = unpack_from("<H", header)
            groups[uid] = None if uid in groups else contents
    return groups


def _equations(records, count):
    curves = {}
    for header, function in _subgroups(records, 0x8047):
        _require(len(header) == 44)
        kind, position, repetitions = unpack_from("<3I", header)
        _require(kind == repetitions == 1 and position not in curves and position < count)
        (_, expression), = _subgroups(function, 0x8048)
        text = bytes(_one(expression, 0x49)).rstrip(b"\r\n\0").decode("ascii")
        values = _one(expression, 0x54)
        names = bytes(_one(expression, 0x53))
        _require(len(values) % _DOUBLE.size == 0 and len(values) <= 8 * _DOUBLE.size)
        values = [value for value, in _DOUBLE.iter_unpack(values)]
        fields = names.split(b"\0", len(values))
        _require(len(fields) == len(values) + 1 and all(isfinite(value) for value in values))
        parameters = dict(zip((name.decode("ascii") for name in fields[:-1]), values, strict=True))
        _require(len(parameters) == len(values) and text.startswith("Y="))
        compiled = compile_equation(text[2:], parameters)
        curves[position] = (compiled, {"equation": text, "parameters": parameters})
    _require(set(curves) == set(range(count)))
    return [curves[position] for position in range(count)]


def _ticks(bounds, step, origin):
    low, high = ((value - origin) / step for value in bounds)
    _require(isfinite(low) and isfinite(high) and 0 <= high - low <= _MAX_TICKS)
    # Original bounds and tick parameters may have differing stored precision.
    return [origin + index * step for index in range(ceil(low - 1e-6), floor(high + 1e-6) + 1)]


def _axis_settings(graph, labels):
    headers = {unpack_from("<H", header)[0]: header for header, _ in _subgroups(graph, 0x8025)}
    axes = [payload for tag, path, payload in graph if tag == 0x17 and not path]
    entries = []
    for axis, record in zip(_axis_config(graph), axes[:2], strict=True):
        _require(axis["scale"] == "linear" and not axis["custom_ticks"])
        settings = headers[unpack_from("<H", record, 54)[0]]
        step, origin = unpack_from("<2d", settings, 54)
        minor_count, = unpack_from("<H", settings, 52)
        _require(isfinite(step) and step > 0 and isfinite(origin) and minor_count <= 10)
        ticks = _ticks(axis["bounds"], step, origin)
        minor = _ticks(axis["bounds"], step / minor_count, origin) if minor_count > 1 else []
        config = {"bounds": axis["bounds"], "label": labels.get(axis["title"], ""),
                  "ticks": ticks, "minor": minor, "grid": bool(settings[42])}
        # The extended scale record stores the literal percent suffix at this position.
        if len(settings) == 134 and settings[102:112] == b"%" + bytes(9):
            config["percent"] = True
        entries.append(config)
    return entries


def _double_arrow(records, chart):
    # Both anchors of this dashed arrow are literal graph positions.
    payload = _one(records, 0x23)
    if len(payload) != 26 or unpack_from("<4H", payload) != (10, 1, 0, 0):
        return None
    segments = [part for tag, path, part in records if tag == 0xD9 and path == (216,)]
    if len(segments) != 2 or any(len(part) != 20 for part in segments):
        return None
    left, top, right, bottom = unpack_from("<4h", chart)
    if left >= right or top >= bottom:
        return None
    points = []
    for segment in segments:
        space, x, y = unpack_from("<3i", segment)
        x, y = (x - left) / (right - left), (bottom - y) / (bottom - top)
        if space != 2 or not (-1 <= x <= 2 and -1 <= y <= 2):
            return None
        points.append([x, y])
    return points


def _appearance(graph, encoding, columns):
    chart = _one(graph, 0x13)
    _require(len(chart) == 48)
    heading, = unpack_from("<H", chart, 32)
    axis_titles = {unpack_from("<H", record, 48)[0] for tag, path, record in graph if tag == 0x17 and not path}
    (scene_header, scene), = _subgroups(graph, 0x8018)
    _require(len(scene_header) == 12)
    labels, notes, arrows, series = {}, [], [], {}
    background = None
    for header, records in _subgroups(scene, 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 2:
            flags, = unpack_from("<H", header, 28)
            uid, caption = _caption(records, encoding, flags)
            _require(uid not in labels)
            labels[uid] = caption
            if caption and not flags and uid != heading and uid not in axis_titles:
                note = _annotation(header, chart, caption)
                if note is not None:
                    notes.append(note)
        elif kind == 3:
            arrow = _double_arrow(records, chart)
            if arrow is not None:
                arrows.append(arrow)
        elif kind == 10:
            # A solid fill on the saved plot rectangle, distinct from the page background.
            fill = _one(records, 0x21)
            bounds = unpack_from("<4h", header, 18)
            plot = unpack_from("<4h", chart)
            if bounds[:3] == plot[:3] and 0 <= bounds[3] - plot[3] <= 6:
                if len(fill) == 16 and fill[2:6] == fill[6:10] and not fill[5]:
                    background = "#" + fill[2:5].hex()
        elif kind == 9:
            drawing = _one(records, 0x8028)
            _require(len(drawing) == 144)
            key, family, uid, visible, _, errors, draw, _ = unpack_from("<8H", drawing)
            _require(key not in series and uid in columns and family == errors == 0 and visible == 1
                     and draw in (0, 2) and not drawing[87])
            series[key] = {"column": columns[uid], "color": "#" + drawing[84:87].hex()}
    order = _id_array(_one(graph, 0x15))
    _require(len(order) == len(set(order)) == len(columns) and set(order) == series.keys()
             and {entry["column"] for entry in series.values()} == set(columns.values()))
    axes = _axis_settings(graph, labels)
    left, top, right, bottom = unpack_from("<4h", chart)
    _require(left < right and top < bottom)
    return {"title": labels.get(heading, ""), "axes": axes, "series": [series[key] for key in order],
            "notes": notes, "arrows": arrows, "background": background,
            "aspect": (bottom - top) / (right - left)}


def _saved_curve(graph, encoding, sheets, generators, available, remaining):
    sheet, = _id_array(_one(graph, 0x14))
    metadata, datasets = sheets[sheet]
    layout = _record_once(metadata, 0x8E)
    _require(len(layout) >= 36 and unpack_from("<i", layout, 16)[0] == 10)
    columns = _column_ids(metadata, _MAX_SERIES)
    _require(0 < len(columns) <= _MAX_SERIES)
    links = _one(graph, 0x16)
    _require(len(links) == 2 + _LINK.size * len(columns) and unpack_from("<H", links)[0] == len(columns)
             and sorted(uid for uid, _, _ in _LINK.iter_unpack(links[2:])) == sorted(columns))
    owners = {_DATASET.unpack(header)[3] for header, _ in datasets}
    owner, = owners
    _require(owner in available)
    records = generators[owner]
    _require(records is not None)
    descriptor = _one(records, 0x3A)
    _require(len(descriptor) == 16 and unpack_from("<H", descriptor)[0] == 15
             and _one(records, 0x3B) == bytes(4))
    outputs = _one(records, 0x3C)
    _require(len(outputs) == 44 and unpack_from("<i", outputs)[0] == 10)
    result_sheet, = unpack_from("<i", outputs, 4)
    # Some older templates point to the graph's own single-precision snapshot
    # instead of the current analysis result. Both still carry this analysis ID.
    _require(result_sheet in sheets and sheets[result_sheet] is not None)
    frame = _sequence_snapshot(sheet, owner, metadata, datasets, layout, remaining, {}, source_free=True)
    _require(frame is not None)
    equations = _equations(records, len(columns))
    x, *y = frame.columns
    for column, (compiled, mapping) in zip(y, equations, strict=True):
        expected = compiled.evaluate(frame[x], mapping["parameters"])
        saved = frame[column].to_numpy(dtype=float)
        _require(np.isfinite(saved).all() and np.allclose(saved, expected, rtol=8e-6, atol=1e-9))
    style = _appearance(graph, encoding, dict(zip(columns, y, strict=True)))
    style["x"] = x
    style["equations"] = [{"column": column, **data} for column, (_, data) in zip(y, equations, strict=True)]
    title = _read_title(_one(graph, 9), encoding)
    _require(bool(title))
    frame.attrs["table_format"] = "xy"
    frame.attrs["prism_recipes"] = [(SAVED_XY, {
        PRISM_TITLE: title[:160],
        PRISM_NOTES: "Recovered theoretical graph. The worksheet contains the original generated values.",
        XML_GENERATED_XY: style,
    })]
    return title, frame


def recover_generated_graphs(data):
    """Yield verified saved samples, without inventing a source table."""
    try:
        index, encoding, graphs, _ = _project_records(data, set())
        _, sheets, original, listed, _ = _read_groups(data)
        if original or not listed:
            return
        generators = _generator_records(data)
    except (ValueError, StructError):
        return
    remaining = MAX_CELLS
    for uid in tuple(index)[:256]:
        if not graphs.get(uid):
            continue
        try:
            title, frame = _saved_curve(graphs[uid], encoding, sheets, generators, listed, remaining)
        except (KeyError, TypeError, ValueError, StructError):
            continue
        remaining -= frame.size
        yield title, frame


def render_generated_graph(frame, style):
    """Build a native chart for editable copies of the generated values."""
    try:
        return _render(frame, style)
    except (KeyError, IndexError, TypeError, OverflowError) as error:
        raise ValueError("Invalid columns or settings for the saved theoretical graph.") from error


def _render(frame, style):
    aspect = float(style["aspect"])
    _require(isfinite(aspect) and .005 <= aspect <= 200 and 0 < len(style["series"]) <= _MAX_SERIES)
    figure = Figure(figsize=(8, 5), layout="constrained")
    axes = figure.add_subplot()
    axes.set_box_aspect(aspect)
    if style.get("background"):
        axes.set_facecolor(style["background"])
    axes.set_title(style["title"], parse_math=False)
    for axis, config in zip((axes.xaxis, axes.yaxis), style["axes"], strict=True):
        _require(len(config["ticks"]) <= _MAX_TICKS + 1 and len(config["minor"]) <= _MAX_TICKS + 1)
        axis.set_major_locator(FixedLocator(config["ticks"]))
        axis.set_minor_locator(FixedLocator(config["minor"]))
        axis.set_label_text(config["label"], parse_math=False)
        if config.get("percent") is True:
            axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}%"))
        if config["grid"]:
            axis.grid(True, which="major", color="#a0a0a4", linewidth=.65)
            axis.grid(True, which="minor", color="#a0a0a4", linewidth=.35, linestyle=":")
    axes.set_xlim(*style["axes"][0]["bounds"])
    axes.set_ylim(*style["axes"][1]["bounds"])
    x = pd.to_numeric(frame[style["x"]], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    views = []
    for item in style["series"]:
        column = item["column"]
        y = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        y = np.where(np.isfinite(x) & np.isfinite(y), y, np.nan)
        axes.plot(x, y, color=item["color"], linewidth=1.7, label=column)
        views.append(pd.DataFrame({"X": x, "Y": y, "Series": column}))
    if not any(view["Y"].notna().any() for view in views):
        raise ValueError("The saved graph has no complete XY points.")
    for left, top, value in style["notes"]:
        axes.text(left, top, value, transform=axes.transAxes, ha="left", va="top", parse_math=False)
    for start, end in style["arrows"]:
        axes.annotate("", xy=end, xytext=start, xycoords="axes fraction", textcoords="axes fraction",
                      arrowprops={"arrowstyle": "<|-|>", "linestyle": "--", "color": "#1b1b1b", "linewidth": 1.15})
    equations = [
        {"Series": entry["column"], "Equation": entry["equation"],
         "Parameters": ", ".join(f"{name}={value:.10g}" for name, value in entry["parameters"].items())}
        for entry in style["equations"]
    ]
    return Result({"Saved XY coordinates": pd.concat(views, ignore_index=True),
                   "Saved equations": pd.DataFrame(equations)}, figure)
