"""Bind sparse point graphs from ZIP projects to the original XY worksheet."""

from math import ceil, floor, isfinite
from struct import Struct, error as StructError, unpack_from

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from .prism_binary import _records
from .prism_binary_editable import _axis_config, _id_array, _one, _require, _subgroups
from .prism_import import _identifier, _json_object
from .reporting import Result


ZIP_SPARSE_XY = "Prism ZIP XY data"
_MAX_GRAPH_BYTES = 2 * 1024 * 1024
_MAX_POINTS = 50_000
_MAX_TICKS = 200
_LINKS = Struct("<3i")
_TEXT_PROPERTY = Struct("<HI")
_MARKERS = {1: "s", 3: "v", 5: "o"}


def _graph_records(data, fen_id):
    identifiers, records = [], []
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8012:
            _require(len(payload) == 2)
            identifiers.append(unpack_from("<H", payload)[0])
        elif parents[:2] == (1, 18):
            records.append((tag, parents[2:], payload))
    _require(identifiers == [fen_id])
    return records


def _linear_axes(records):
    axes = _axis_config(records)
    scales = {unpack_from("<H", header)[0]: header for header, _ in _subgroups(records, 0x8025)}
    headers = [payload for tag, nest, payload in records if tag == 0x17 and not nest]
    for axis, header in zip(axes, headers[:2], strict=True):
        _require(axis["scale"] == "linear" and not axis["custom_ticks"])
        uid, = unpack_from("<H", header, 54)
        step, origin = unpack_from("<2d", scales[uid], 54)
        low, high = axis["bounds"]
        _require(isfinite(step) and step > 0 and isfinite(origin))
        first, last = (low - origin) / step, (high - origin) / step
        _require(isfinite(first) and isfinite(last) and 0 <= last - first <= _MAX_TICKS)
        yield {"bounds": [low, high],
               "ticks": [origin + i * step for i in range(ceil(first - 1e-10), floor(last + 1e-10) + 1)]}


def _plain_zip_text(detail):
    header = _one(detail, 0x902B)
    _require(len(header) == 18)
    text, = [bytes(p) for tag, path, p in detail if tag == 0x102C and path == (0x102B,)]
    style, = [p for tag, path, p in detail if tag == 0x102D and path == (0x102B,)]
    runs, count, start = unpack_from("<HHI", style)
    _require(runs == 1 and start == 0 and len(style) == 8 + count * _TEXT_PROPERTY.size)
    properties = dict(_TEXT_PROPERTY.iter_unpack(style[8:]))
    _require(properties.get(10) == 65001 and 1 <= properties.get(1, 0) <= 48)
    label = text.decode("utf-8")
    _require(len(label) <= 240 and all(char.isprintable() for char in label))
    rgba = properties.get(8, 0xFF000000).to_bytes(4, "little")
    _require(rgba[3] == 255)
    return unpack_from("<H", header)[0], label, properties[1], "#" + rgba[:3].hex()


def _saved_captions(records, objects):
    try:
        chart = _one(records, 0x13)
        _require(len(chart) == 48)
        x, y = _axis_config(records)
        ids = (unpack_from("<H", chart, 32)[0], x["title"], y["title"])
        _require(len(set(ids)) == 3)
        names = dict(zip(ids, ("title", "xlabel", "ylabel"), strict=True))
        captions = {}
        for header, details in objects:
            if unpack_from("<H", header)[0] != 2:
                continue
            text_header = _one(details, 0x902B)
            _require(len(text_header) == 18)
            name = names.get(unpack_from("<H", text_header)[0])
            if name is not None:
                _require(name not in captions)
                hidden = bool(unpack_from("<H", header, 28)[0] & 0x200)
                captions[name] = "" if hidden else _plain_zip_text(details)[1]
        return captions
    except (KeyError, ValueError, StructError):
        return {}


def _hidden_legend_keys(objects):
    entries = {}
    for header, details in objects:
        if unpack_from("<H", header)[0] != 14:
            continue
        try:
            description, marker = _one(details, 0x9D), _one(details, 0x209D)
            _require(len(description) in (56, 504) and len(marker) == 12)
            key, = unpack_from("<I", description, 8)
            kind, _, linked_key = unpack_from("<IfI", marker)
            _require(kind == 2 and linked_key == key and key not in entries)
            entries[key] = bool(unpack_from("<H", header, 28)[0] & 0x200)
        except (ValueError, StructError):
            return set()
    return {key for key, hidden in entries.items() if hidden}


def _series(records, columns):
    order = _id_array(_one(records, 0x15))
    links = _one(records, 0x16)
    _require(len(links) == 2 + len(order) * _LINKS.size and unpack_from("<H", links)[0] == len(order))
    linked = set()
    for dataset, first, second in _LINKS.iter_unpack(links[2:]):
        _require(dataset in columns and dataset not in linked and first == second == -1)
        linked.add(dataset)
    _require(linked == columns.keys())

    scene, = list(_subgroups(records, 0x8018))
    objects = list(_subgroups(scene[1], 0x8020))
    _require(all(len(header) == 30 for header, _ in objects))
    hidden = _hidden_legend_keys(objects)
    styles, seen = {}, set()
    for header, details in objects:
        if unpack_from("<H", header)[0] != 9:
            continue
        style = _one(details, 0x8028)
        _require(len(style) == 144)
        key, family, dataset, visible, _, error, draw, _bars = unpack_from("<8H", style)
        _require(key not in styles and (family, visible, error, draw) == (0, 1, 0, 0)
                 and dataset in linked and dataset not in seen and style[71] == 0)
        seen.add(dataset)
        item = {"column": columns[dataset], "color": "#" + bytes(style[68:71]).hex()}
        marker, size = unpack_from("<2H", style, 60)
        if marker in _MARKERS and 1 <= size <= 30:
            item.update(marker=_MARKERS[marker], marker_size=size)
        if key in hidden:
            item["legend"] = False
        styles[key] = item
    _require(len(order) == len(styles) and set(order) == styles.keys() and seen == linked)
    return [styles[key] for key in order], _saved_captions(records, objects)


def saved_sparse_xy(archive, graph, graph_uid, owners, sources):
    """Return a source and recipe for verified single-value sparse XY graphs."""
    try:
        return _saved_sparse_xy(archive, graph, graph_uid, owners, sources)
    except (KeyError, TypeError, ValueError, OverflowError, StructError):
        return None


def _saved_sparse_xy(archive, graph, graph_uid, owners, sources):
    ids = graph.get("inputDataSets")
    _require(graph.get("uid") == graph_uid and isinstance(ids, list) and 1 <= len(ids) <= 100)
    ids = [_identifier(uid) for uid in ids]
    matches = [owners.get(uid, ()) for uid in ids]
    _require(len(set(ids)) == len(ids) and all(len(group) == 1 for group in matches))
    frame = matches[0][0][0]
    _require(all(group[0][0] is frame for group in matches) and frame.attrs["prism_y_format"] == "y_single"
             and 0 < len(frame) * len(ids) <= _MAX_POINTS)
    source, = [uid for uid, data in sources.items() if data is frame]
    sheet = _json_object(archive, f"data/sheets/{source}/sheet.json")
    _require(sheet.get("uid") == source and type(sheet.get("fenID")) is int)
    mapping = frame.attrs["prism_columns"]
    x, = mapping[frame.attrs["prism_x"]]
    _require(pd.api.types.is_numeric_dtype(frame[x]))
    columns = {}
    for uid in ids:
        name, = mapping[uid]
        _require(pd.api.types.is_numeric_dtype(frame[name]) or not frame[name].notna().any())
        identity = _json_object(archive, f"data/sets/{uid}.json")
        dataset = identity["fenID"]
        _require(type(dataset) is int and dataset not in columns)
        columns[dataset] = name
    _require(any(not frame[name].notna().any() for name in columns.values())
             and any(frame[name].notna().any() for name in columns.values()))

    member = archive.getinfo(f"graphs/{graph_uid}/data.bin")
    _require(0 < member.file_size <= _MAX_GRAPH_BYTES and type(graph.get("fenID")) is int)
    records = _graph_records(archive.read(member), graph["fenID"])
    _require(_id_array(_one(records, 0x14)) == [sheet["fenID"]])
    series, captions = _series(records, columns)
    return frame, {"x": x, "series": series, "axes": list(_linear_axes(records)), "captions": captions}


def render_sparse_xy(frame, style, title, *, axes=None):
    try:
        return _render_sparse_xy(frame, style, title, axes)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid source columns or settings for the saved XY graph.") from error


def _render_sparse_xy(frame, style, title, axes):
    series, scales = style["series"], style["axes"]
    _require(isinstance(series, list) and 1 <= len(series) <= 100 and len(scales) == 2
             and len(series) * len(frame) <= _MAX_POINTS)
    if axes is None:
        figure = Figure(figsize=(7, 4), layout="constrained")
        axes = figure.add_subplot()
    else:
        figure = axes.get_figure(root=True)
    captions = style.get("captions", {})
    axes.set_title(captions.get("title", title), parse_math=False)
    axes.set_xlabel(captions.get("xlabel", style["x"]), parse_math=False)
    axes.set_ylabel(captions.get("ylabel", ""), parse_math=False)
    axes.spines[["right", "top"]].set_visible(False)
    for scale, ticks, limits in zip(scales, (axes.set_xticks, axes.set_yticks),
                                    (axes.set_xlim, axes.set_ylim), strict=True):
        low, high = scale["bounds"]
        values = scale["ticks"]
        _require(isfinite(low) and isfinite(high) and low < high and len(values) <= _MAX_TICKS + 1
                 and all(isfinite(value) for value in values))
        ticks(values)
        limits(low, high)
    x = pd.to_numeric(frame[style["x"]], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    portions = []
    for number, item in enumerate(series, 1):
        column, color = item["column"], item["color"]
        _require(isinstance(column, str) and is_color_like(color))
        y = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        valid = np.isfinite(x) & np.isfinite(y)
        if not valid.any():
            continue
        shown_x, shown_y = x[valid], y[valid]
        label = column if item.get("legend", True) else "_nolegend_"
        axes.plot(shown_x, shown_y, color=color, marker=item.get("marker", "o"),
                  markersize=item.get("marker_size"), linestyle="none", label=label)
        portions.append(pd.DataFrame({"X": shown_x, "Y": shown_y, "Series": column,
                                      "Dataset": number, "Geometry": "points"}))
    if not portions:
        raise ValueError("The saved graph has no complete XY points.")
    if len(portions) <= 15 and axes.get_legend_handles_labels()[0]:
        for label in axes.legend().get_texts():
            label.set_parse_math(False)
    return Result({"Saved XY coordinates": pd.concat(portions, ignore_index=True)}, figure)
