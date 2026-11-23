"""Restore worksheet-linked horizontal point graphs from ZIP projects."""

from math import isfinite
from struct import Struct, error as StructError, unpack_from

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

from .legacy_binary_editable import _axis_config, _id_array, _one, _require, _subgroups
from .legacy_import import _identifier, _json_object
from .legacy_zip_xy import (_axis_spacing, _graph_records, _linear_axes, _plain_zip_text, _saved_captions,
                           _MAX_GRAPH_BYTES, _MAX_POINTS, _MAX_TICKS)
from .reporting import Result


ZIP_COLUMN = "Legacy ZIP aligned column"
_POINT_SIZE = 249
_COLUMN_LINK = Struct("<3i")


def _point_colors(records, key, dataset, rows, *, painted=4, empty_default=False):
    points = _one(records, 0xAE)
    index, count, stride = unpack_from("<3I", points)
    _require(index == key and stride == _POINT_SIZE and count == rows + 1
             and len(points) == 12 + count * stride)
    colors, seen = [], set()
    for start in range(12, len(points) - stride, stride):
        point = points[start:start + stride]
        owner, row, replicate = unpack_from("<3I", point, 4)
        _require(owner == dataset and row < rows and row not in seen and replicate == 0xFFFFFFFF)
        _require(point[0] in (0, painted))
        seen.add(row)
        if point[0] == painted:
            rgba = bytes(point[165:169])
            _require(rgba[3] == 255)
            colors.append([row, "#" + rgba[:3].hex()])
    default = points[-stride:]
    owner, row, replicate = unpack_from("<3I", default, 4)
    _require(default[0] == 0 and owner == dataset
             and ((row, replicate) == (0, 0) or empty_default and row == replicate == 0xFFFFFFFF))
    return colors


def _column_style(records, column, dataset, rows):
    key, = _id_array(_one(records, 0x15))
    _require(bytes(_one(records, 0x16)) == Struct("<H3i").pack(1, dataset, -2, -2))
    axes = list(_linear_axes(records))
    x_config, y_config = _axis_config(records)
    chart = _one(records, 0x13)
    _require(len(chart) == 48)
    left, top, right, bottom = unpack_from("<4h", chart)
    _require(right - left == x_config["length"] and bottom - top == y_config["length"])
    title_id, = unpack_from("<H", chart, 32)
    x_uid, y_uid = [unpack_from("<H", p, 54)[0] for tag, path, p in records if tag == 0x17 and not path][:2]
    scales = {unpack_from("<H", h)[0]: (h, children) for h, children in _subgroups(records, 0x8025)}
    scale, _ = scales[x_uid]
    _require(len(scale) == 134)
    suffix = bytes(scale[102:118]).split(b"\0", 1)[0].decode("utf-8")
    _require(all(char.isprintable() for char in suffix))
    position, length, owner, slot = Struct("<3Hi").unpack(_one(scales[y_uid][1], 0x27))
    _require(owner == dataset and slot == -2 and length == y_config["length"] and 0 < position < length)

    (_, scene), = list(_subgroups(records, 0x8018))
    styles, labels, annotations, hidden_axes = [], {}, [], {}
    chart_labels = {title_id, x_config["title"], y_config["title"]}
    chart_labels.update(unpack_from("<H", p, 48)[0] for tag, path, p in records if tag == 0x17 and not path)
    for header, detail in _subgroups(scene, 0x8020):
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        flags, = unpack_from("<H", header, 28)
        if kind == 9:
            styles.append(_one(detail, 0x8028))
        elif kind == 8:
            axis, = Struct("<H").unpack(_one(detail, 0x2A))
            _require(axis not in hidden_axes)
            hidden_axes[axis] = bool(flags & 0x800)
        elif kind == 2 and not flags & 0x200:
            identity, text, size, color = _plain_zip_text(detail)
            _require(identity not in labels)
            labels[identity] = text
            if identity not in chart_labels:
                x0, y0, x1, y1 = unpack_from("<4h", header, 18)
                x, y = ((x0 + x1) / 2 - left) / (right - left), (bottom - (y0 + y1) / 2) / (bottom - top)
                _require(-1 <= x <= 2 and -1 <= y <= 2)
                annotations.append([text, x, y, size, color])
    style, = styles
    _require(len(style) == 144 and hidden_axes.get(x_uid) is False and hidden_axes.get(y_uid) is True)
    _require(unpack_from("<8H", style) == (key, 1, dataset, 1, 0, 1, 0, 2))
    flags, symbol, size = unpack_from("<3H", style, 58)
    _require(flags == 0xC008 and symbol == 3 and 1 <= size <= 30 and style[71] == 0)
    return {"column": column, "axes": axes, "alignment": position / length, "suffix": suffix,
            "aspect": (bottom - top) / (right - left),
            "size": size, "color": "#" + bytes(style[68:71]).hex(),
            "point_colors": _point_colors(records, key, dataset, rows),
            "title": labels.get(title_id, ""), "xlabel": labels.get(x_config["title"], ""),
            "annotations": annotations}


def saved_aligned_column(archive, graph, uid, sources):
    """Bind the supported single-series horizontal point graph to its data sheet."""
    try:
        ids = graph.get("inputDataSets")
        _require(graph.get("uid") == uid and isinstance(ids, list) and len(ids) == 1)
        dataset_uid = _identifier(ids[0])
        (sheet_uid, frame), = [(name, frame) for name, frame in sources.items()
                               if frame.attrs["table_format"] == "column" and dataset_uid in frame.attrs["legacy_y"]]
        _require(frame.attrs["legacy_y_format"] == "y_single" and 0 < len(frame) <= _MAX_POINTS)
        column, = frame.attrs["legacy_columns"][dataset_uid]
        _require(pd.api.types.is_numeric_dtype(frame[column]))
        sheet = _json_object(archive, f"data/sheets/{sheet_uid}/sheet.json")
        dataset = _json_object(archive, f"data/sets/{dataset_uid}.json")["fenID"]
        _require(sheet.get("uid") == sheet_uid and type(sheet.get("fenID")) is int
                 and type(dataset) is int and type(graph.get("fenID")) is int)
        member = archive.getinfo(f"graphs/{uid}/data.bin")
        _require(0 < member.file_size <= _MAX_GRAPH_BYTES)
        records = _graph_records(archive.read(member), graph["fenID"])
        _require(_id_array(_one(records, 0x14)) == [sheet["fenID"]])
        return frame, _column_style(records, column, dataset, len(frame))
    except (KeyError, TypeError, ValueError, StructError, OverflowError):
        return None


def _geometric_style(records, datasets):
    """Recognize the column scatter profile with a geometric mean and its 95% CI."""
    keys = _id_array(_one(records, 0x15))
    links = _one(records, 0x16)
    _require(len(keys) == len(datasets) == len(set(keys)) and len(links) == 2 + len(keys) * _COLUMN_LINK.size
             and unpack_from("<H", links)[0] == len(keys))
    for (dataset, axis, replicate), expected in zip(_COLUMN_LINK.iter_unpack(links[2:]), datasets, strict=True):
        _require(dataset == expected and axis in (-2, -1) and replicate == -2)

    scene, = _subgroups(records, 0x8018)
    objects = list(_subgroups(scene[1], 0x8020))
    series, visible_axes = {}, set()
    for header, body in objects:
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        _require(kind in (2, 8, 9, 10, 14))
        if kind == 8 and not unpack_from("<H", header, 28)[0] & 0x800:
            visible_axes.add(Struct("<H").unpack(_one(body, 0x2A))[0])
        elif kind == 9:
            style = _one(body, 0x8028)
            key, family, dataset, enabled, center, mode, interval, sides = unpack_from("<8H", style)
            _require(len(style) == 144 and key not in series
                     and (family, enabled, center, mode, interval, sides) == (1, 1, 2, 1, 3, 2)
                     and unpack_from("<H", style, 58)[0] == 12)
            extended, = [payload for tag, parent, payload in body if tag == 0x9C and parent == (40,)]
            _require(len(extended) == 317 and unpack_from("<2I", extended) == (26, key)
                     and unpack_from("<3I", extended, 293) == (3, 3, 0x2FFFF)
                     and unpack_from("<I", extended, 313)[0] == dataset)
            series[key] = dataset
    _require(set(series) == set(keys) and [series[key] for key in keys] == datasets)

    x, y, _ = [payload for tag, parent, payload in records if tag == 0x17 and not parent]
    _require(len(x) == len(y) == 60 and unpack_from("<2d", x, 16) == (1., float(len(datasets))))
    x_id, y_id = [unpack_from("<H", axis, 54)[0] for axis in (x, y)]
    _require(visible_axes == {x_id, y_id})
    low, high = unpack_from("<2d", y, 16)
    length, _, kind, title = unpack_from("<4H", y, 42)
    left, top, right, bottom = unpack_from("<4h", _one(records, 0x13))
    _require(right - left == unpack_from("<H", x, 42)[0] and bottom - top == length
             and kind in (0, 1) and isfinite(low) and isfinite(high) and low < high)
    scale, = [header for header, _ in _subgroups(records, 0x8025) if unpack_from("<H", header)[0] == y_id]
    _require(unpack_from("<2d", scale, 2) == (low, high) and unpack_from("<H", scale, 28)[0] == kind)
    _, (step, origin) = _axis_spacing(records)
    limits = {"min": low, "max": high}
    if kind:
        _require(-300 <= low < high <= 300 and step == 1.)
        limits = {"min": 10. ** low, "max": 10. ** high}
    else:
        _require(isfinite(step) and step > 0 and isfinite(origin) and (high - low) / step <= _MAX_TICKS)
        limits.update(step=step, start=origin)
    axis_titles = unpack_from("<H", x, 48)[0], title
    captions = _saved_captions(records, objects, axis_titles=axis_titles)
    return {"yscale": "log" if kind else "linear", "axis": {"y": limits},
            **{key: value for key, value in captions.items() if len(value) <= 160}}


def saved_geometric_column(archive, graph, uid, sources):
    """Bind a verified scatter to the same live column data as the saved graph."""
    from .category_graphs import MAX_CATEGORIES, MAX_POINTS
    from .presentation import validated_style

    try:
        selected = graph.get("inputDataSets")
        _require(graph.get("uid") == uid and isinstance(selected, list) and 1 <= len(selected) <= MAX_CATEGORIES)
        ids = [_identifier(value) for value in selected]
        _require(len(set(ids)) == len(ids))
        (sheet_uid, frame), = [(name, frame) for name, frame in sources.items()
                               if frame.attrs.get("table_format") == "column"
                               and set(ids).issubset(frame.attrs["legacy_y"])]
        _require(frame.attrs["legacy_y_format"] == "y_single" and frame.attrs["legacy_x"] is None
                 and 0 < len(frame) * len(ids) <= MAX_POINTS)
        columns, datasets = [], []
        for dataset_uid in ids:
            column, = frame.attrs["legacy_columns"][dataset_uid]
            _require(pd.api.types.is_numeric_dtype(frame[column]))
            columns.append(column)
            data = _json_object(archive, f"data/sets/{dataset_uid}.json")
            _require(type(data["fenID"]) is int and data["fenID"] >= 0)
            datasets.append(data["fenID"])
        _require(len(set(columns)) == len(set(datasets)) == len(ids))
        sheet = _json_object(archive, f"data/sheets/{sheet_uid}/sheet.json")
        _require(sheet.get("uid") == sheet_uid and type(sheet.get("fenID")) is int and type(graph.get("fenID")) is int)
        member = archive.getinfo(f"graphs/{uid}/data.bin")
        _require(0 < member.file_size <= _MAX_GRAPH_BYTES)
        records = _graph_records(archive.read(member), graph["fenID"])
        _require(_id_array(_one(records, 0x14)) == [sheet["fenID"]])
        return frame, columns, validated_style(_geometric_style(records, datasets))
    except (KeyError, TypeError, ValueError, StructError, OverflowError):
        return None


def render_aligned_column(frame, style):
    try:
        column, color, size = style["column"], style["color"], style["size"]
        suffix, alignment, aspect = style["suffix"], style["alignment"], style["aspect"]
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        active = np.flatnonzero(np.isfinite(values))
        _require(0 < len(active) <= len(frame) <= _MAX_POINTS and 0 < alignment < 1
                 and isfinite(aspect) and aspect > 0 and is_color_like(color) and 1 <= size <= 30
                 and isinstance(suffix, str) and len(suffix) <= 16)
        overrides = dict(style["point_colors"])
        _require(len(overrides) <= _MAX_POINTS and all(type(row) is int and 0 <= row < _MAX_POINTS
                 and is_color_like(color) for row, color in overrides.items()))
        horizontal, vertical = style["axes"]
        x_low, x_high = horizontal["bounds"]
        y_low, y_high = vertical["bounds"]
        ticks = horizontal["ticks"]
        _require(all(isfinite(number) for number in (x_low, x_high, y_low, y_high))
                 and x_low < x_high and y_low < y_high and len(ticks) <= _MAX_TICKS + 1
                 and all(isfinite(tick) for tick in ticks))
        figure = Figure(figsize=(7, 3), layout="constrained")
        axes = figure.add_subplot()
        axes.set_box_aspect(aspect)
        y = np.full(len(active), y_low + alignment * (y_high - y_low))
        axes.scatter(values[active], y, c=[overrides.get(row, color) for row in active], marker="v", s=size ** 2)
        axes.set_xticks(ticks)
        axes.set_xlim(x_low, x_high)
        axes.set_ylim(y_low, y_high)
        axes.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}{suffix}"))
        axes.yaxis.set_visible(False)
        axes.spines[["left", "right", "top"]].set_visible(False)
        axes.set_xlabel(style["xlabel"], parse_math=False)
        axes.set_title(style["title"], parse_math=False)
        annotations = style["annotations"]
        _require(len(annotations) <= 128)
        for text, x, fraction, font_size, text_color in annotations:
            _require(isinstance(text, str) and len(text) <= 240 and -1 <= x <= 2 and -1 <= fraction <= 2
                     and 1 <= font_size <= 48 and is_color_like(text_color))
            axes.text(x, fraction, text, transform=axes.transAxes, ha="center", va="center",
                      fontsize=font_size, color=text_color, parse_math=False)
        return Result({"Saved XY coordinates": pd.DataFrame({"X": values[active], "Y": y,
                       "Source row": active + 1, "Series": column, "Geometry": "points"})}, figure)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid source columns or settings for the saved column graph.") from error
