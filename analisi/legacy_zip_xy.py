"""Bind point graphs from ZIP projects to the original XY worksheet."""

from math import ceil, floor, isfinite
from struct import Struct, error as StructError, unpack_from

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
from scipy.special import stdtrit

from .legacy_binary import _records
from .legacy_binary_editable import _axis_config, _id_array, _one, _require, _subgroups
from .legacy_import import _identifier, _json_object
from .reporting import Result


ZIP_SPARSE_XY = "Legacy ZIP XY data"
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


def _axis_scale_headers(records):
    scales = {unpack_from("<H", header)[0]: header for header, _ in _subgroups(records, 0x8025)}
    headers = [payload for tag, nest, payload in records if tag == 0x17 and not nest]
    for header in headers[:2]:
        uid, = unpack_from("<H", header, 54)
        yield scales[uid]


def _axis_spacing(records):
    return (unpack_from("<2d", header, 54) for header in _axis_scale_headers(records))


def _linear_axes(records):
    axes = _axis_config(records)
    for axis, (step, origin) in zip(axes, _axis_spacing(records), strict=True):
        _require(axis["scale"] == "linear" and not axis["custom_ticks"])
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


def _saved_captions(records, objects, *, axis_titles=None):
    try:
        chart = _one(records, 0x13)
        _require(len(chart) == 48)
        if axis_titles is None:
            x, y = _axis_config(records)
            axis_titles = x["title"], y["title"]
        ids = (unpack_from("<H", chart, 32)[0], *axis_titles)
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


def saved_graph_axes(archive, graph_uid, fen_id, *, viewport_only=False):
    """Translate the saved viewport and detect labels for log10 concentrations."""
    from .presentation import validated_style

    try:
        member = archive.getinfo(f"graphs/{graph_uid}/data.bin")
        _require(0 < member.file_size <= _MAX_GRAPH_BYTES)
        records = _graph_records(archive.read(member), fen_id)
        style = {"axis": {}}
        concentration_ticks = None
        axes = _axis_config(records, viewport_only=viewport_only)
        for dim, axis, header in zip("xy", axes, _axis_scale_headers(records), strict=True):
            step, origin = unpack_from("<2d", header, 54)
            low, high = axis["bounds"]
            scale = axis["scale"]
            style[dim + "scale"] = scale
            if scale == "log":
                low, high = 10. ** low, 10. ** high
            limits = {"min": low, "max": high}
            if scale == "linear" and not axis["custom_ticks"]:
                limits.update(step=step, start=origin)
                divisions, = unpack_from("<H", header, 52)
                if (dim == "x" and viewport_only and len(header) == 134
                        and unpack_from("<4H", header, 78) == (2, 2, 0, 2) and divisions in (0, 9)
                        and step == 1 and origin.is_integer() and -300 <= low < high <= 300
                        and (high - low) * 9 <= _MAX_TICKS - 1):
                    concentration_ticks = divisions == 9
            style["axis"][dim] = limits
        scene, = _subgroups(records, 0x8018)
        objects = list(_subgroups(scene[1], 0x8020))
        if viewport_only:
            visible = {unpack_from("<H", _one(body, 0x2A))[0] for header, body in objects
                       if unpack_from("<H", header)[0] == 8 and not unpack_from("<H", header, 28)[0] & 0x800}
            identifiers = [unpack_from("<H", item, 54)[0] for tag, parent, item in records
                           if tag == 0x17 and not parent]
            _require(visible == set(identifiers[:2]))
        captions = _saved_captions(records, objects, axis_titles=tuple(axis["title"] for axis in axes))
        style.update({key: value for key, value in captions.items() if len(value) <= 160})
        return validated_style(style), concentration_ticks
    except (KeyError, ValueError, StructError, OverflowError):
        return None


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


def _saved_plot_box(records, objects):
    try:
        chart = _one(records, 0x13)
        left, top, right, bottom = unpack_from("<4h", chart)
        _require(len(chart) == 48 and right > left and bottom > top)
        _require(sum(unpack_from("<H", header)[0] == 10 for header, _ in objects) == 1)
        bounds = []
        for header, _ in objects:
            if unpack_from("<H", header, 28)[0] & 0x200:
                continue
            x0, y0, x1, y1 = unpack_from("<4h", header, 2)
            if x0 < x1 and y0 < y1:
                bounds.append((x0, y0, x1, y1))
        # Positioned panels confirm the padded dimensions independently.
        # Use this geometry only when the saved panel size matches it.
        plot_left = min(box[0] for box in bounds) - 24
        plot_top = min(box[1] for box in bounds) - 24
        plot_right = max(box[2] for box in bounds) + 24
        plot_bottom = max(box[3] for box in bounds) + 24
        _require(plot_left <= left < right <= plot_right and plot_top <= top < bottom <= plot_bottom)
        width, height = plot_right - plot_left, plot_bottom - plot_top
        axes_box = [(left - plot_left) / width, (plot_bottom - bottom) / height,
                    (right - left) / width, (bottom - top) / height]
        return {"size": [width, height], "axes_box": axes_box}
    except (ValueError, StructError):
        return None


def _replicate_summary(values):
    values = np.where(np.isfinite(values), values, np.nan)
    count = np.isfinite(values).sum(axis=1)
    mean = np.full(len(values), np.nan)
    deviation = np.full(len(values), np.nan)
    present, complete = count > 0, count > 1
    with np.errstate(over="ignore", invalid="ignore"):
        mean[present] = np.nanmean(values[present], axis=1)
        deviation[complete] = np.nanstd(values[complete], axis=1, ddof=1)
    return mean, deviation, count


def _confirmed_sample_sd(frame, x, columns, drawing):
    """Verify the statistic against the cached source and error extents."""
    valid_x = np.isfinite(x)
    x = x[valid_x]
    values = frame[columns].to_numpy(dtype=float, na_value=np.nan)[valid_x]
    means, deviations, counts = _replicate_summary(values)
    present = counts > 0
    if not present.any() or not (np.isfinite(means[present]).all()
                                 and np.isfinite(deviations[counts > 1]).all()):
        return False
    x, means, deviations, counts, values = (part[present] for part in (x, means, deviations, counts, values))
    cached = unpack_from("<4d", drawing, 26)
    if not np.allclose((x.min(), x.max()), cached[:2], rtol=2e-12, atol=0):
        return False
    deviation = np.nan_to_num(deviations, nan=0.0)
    sem = deviation / np.sqrt(counts)
    confidence = sem * stdtrit(np.maximum(counts - 1, 1), 0.975)
    values = np.where(np.isfinite(values), values, np.nan)

    def matches(low, high):
        return np.allclose(cached[2:], (low, high), rtol=2e-12, atol=0)

    return (matches((means - deviation).min(), (means + deviation).max())
            and not any(matches((means - error).min(), (means + error).max())
                        for error in (np.zeros(len(means)), sem, confidence))
            and not matches(np.nanmin(values), np.nanmax(values)))


def _series(records, datasets, *, replica_data):
    replicates = replica_data is not None
    if replicates:
        _require(not any(tag == 0xAE and not path for tag, path, _ in records))
    order = _id_array(_one(records, 0x15))
    links = _one(records, 0x16)
    _require(len(links) == 2 + len(order) * _LINKS.size and unpack_from("<H", links)[0] == len(order))
    linked = set()
    selector = -2 if replicates else -1
    for dataset, first, second in _LINKS.iter_unpack(links[2:]):
        _require(dataset in datasets and dataset not in linked and first == second == selector)
        linked.add(dataset)
    _require(linked == datasets.keys())

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
        key, family, dataset, visible, side, error, draw, bars = unpack_from("<8H", style)
        _require(key not in styles and (family, visible) == (0, 1) and dataset in linked
                 and dataset not in seen and style[71] == 0)
        if replicates:
            _require((side, error, draw, bars) == (2, 1, 1, 2)
                     and unpack_from("<H", style, 58)[0] == 14)
        else:
            _require((error, draw) == (0, 0))
        seen.add(dataset)
        item = {**datasets[dataset], "color": "#" + bytes(style[68:71]).hex()}
        marker, size = unpack_from("<2H", style, 60)
        if marker in _MARKERS and 1 <= size <= 30:
            item.update(marker=_MARKERS[marker], marker_size=size)
        if key in hidden:
            item["legend"] = False
        if (replicates and unpack_from("<H", style, 64)[0] == 0 and not (style[87] or style[91])
                and _confirmed_sample_sd(*replica_data, item["columns"], style)):
            item.update(line_color="#" + bytes(style[84:87]).hex(),
                        whisker_color="#" + bytes(style[88:91]).hex())
        styles[key] = item
    _require(len(order) == len(styles) and set(order) == styles.keys() and seen == linked)
    return [styles[key] for key in order], _saved_captions(records, objects), _saved_plot_box(records, objects)


def saved_zip_xy(archive, graph, graph_uid, owners, sources, *, replicates=False):
    """Return the original worksheet and the settings for a linked point graph."""
    try:
        return _saved_zip_xy(archive, graph, graph_uid, owners, sources, replicates=replicates)
    except (KeyError, TypeError, ValueError, OverflowError, StructError):
        return None


def _saved_zip_xy(archive, graph, graph_uid, owners, sources, *, replicates):
    ids = graph.get("inputDataSets")
    _require(graph.get("uid") == graph_uid and isinstance(ids, list) and 1 <= len(ids) <= 100)
    ids = [_identifier(uid) for uid in ids]
    matches = [owners.get(uid, ()) for uid in ids]
    _require(len(set(ids)) == len(ids) and all(len(group) == 1 for group in matches))
    frame = matches[0][0][0]
    mode = "y_replicates" if replicates else "y_single"
    _require(all(group[0][0] is frame for group in matches) and frame.attrs["legacy_y_format"] == mode)
    if replicates:
        _require(frame.attrs["table_format"] == "xy")
    source, = [uid for uid, data in sources.items() if data is frame]
    sheet = _json_object(archive, f"data/sheets/{source}/sheet.json")
    _require(sheet.get("uid") == source and type(sheet.get("fenID")) is int)
    mapping = frame.attrs["legacy_columns"]
    x, = mapping[frame.attrs["legacy_x"]]
    _require(pd.api.types.is_numeric_dtype(frame[x]))
    datasets, repeats = {}, 0
    for uid in ids:
        columns = mapping[uid]
        repeats += len(columns)
        identity = _json_object(archive, f"data/sets/{uid}.json")
        dataset = identity["fenID"]
        _require(type(dataset) is int and dataset not in datasets and 1 <= len(columns) <= 512)
        if replicates:
            label = identity.get("title")
            _require(len(columns) >= 2 and isinstance(label, str) and 0 < len(label) <= 160)
            datasets[dataset] = {"columns": columns, "label": label}
        else:
            name, = columns
            _require(pd.api.types.is_numeric_dtype(frame[name]) or not frame[name].notna().any())
            datasets[dataset] = {"column": name}
    _require(0 < len(frame) * repeats <= _MAX_POINTS)
    if not replicates:
        present = [frame[item["column"]].notna().any() for item in datasets.values()]
        _require(any(present) and not all(present))

    member = archive.getinfo(f"graphs/{graph_uid}/data.bin")
    _require(0 < member.file_size <= _MAX_GRAPH_BYTES and type(graph.get("fenID")) is int)
    records = _graph_records(archive.read(member), graph["fenID"])
    _require(_id_array(_one(records, 0x14)) == [sheet["fenID"]])
    replica_data = (frame, frame[x].to_numpy(dtype=float, na_value=np.nan)) if replicates else None
    series, captions, plot = _series(records, datasets, replica_data=replica_data)
    style = {"x": x, "series": series, "axes": list(_linear_axes(records)), "captions": captions}
    if replicates and all("whisker_color" in item for item in series):
        style["sample_sd"] = True
    if plot is not None:
        style["plot"] = plot
    return frame, style


def render_sparse_xy(frame, style, title, *, axes=None):
    try:
        return _render_sparse_xy(frame, style, title, axes)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid source columns or settings for the saved XY graph.") from error


def _render_sparse_xy(frame, style, title, axes):
    series, scales = style["series"], style["axes"]
    _require(isinstance(series, list) and 1 <= len(series) <= 100 and len(scales) == 2)
    points = 0
    fields = []
    for item in series:
        columns = item.get("columns", [item.get("column")])
        label = item.get("label", item.get("column"))
        _require(isinstance(columns, list) and 1 <= len(columns) <= 512
                 and all(isinstance(name, str) for name in columns)
                 and len(set(columns)) == len(columns) and isinstance(label, str)
                 and is_color_like(item["color"]))
        points += len(columns) * len(frame)
        fields.append((columns, label))
    _require(points <= _MAX_POINTS)
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
    sample_sd = style.get("sample_sd") is True
    portions = []
    for number, (item, (columns, name)) in enumerate(zip(series, fields, strict=True), 1):
        values = frame[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        if sample_sd:
            mean, error, count = _replicate_summary(values)
            valid = np.isfinite(x) & (count > 0)
            _require(np.isfinite(mean[valid]).all() and np.isfinite(error[valid & (count > 1)]).all())
            xs, y = x, mean
        else:
            xs, y = np.repeat(x, len(columns)), values.ravel()
            valid = np.isfinite(xs) & np.isfinite(y)
        if not valid.any():
            continue
        shown_x, shown_y = xs[valid], y[valid]
        label = name if item.get("legend", True) else "_nolegend_"
        markers = {"marker": item.get("marker", "o"), "markersize": item.get("marker_size"), "label": label}
        data = {"X": shown_x, "Y": shown_y, "Series": name, "Dataset": number, "Geometry": "points"}
        if sample_sd:
            _require(is_color_like(item["line_color"]) and is_color_like(item["whisker_color"]))
            error = error[valid]
            axes.errorbar(shown_x, shown_y, yerr=error, color=item["line_color"], ecolor=item["whisker_color"],
                          markerfacecolor=item["color"], markeredgecolor=item["color"], capsize=3, **markers)
            data.update({"Y minus": error, "Y plus": error})
        else:
            axes.plot(shown_x, shown_y, color=item["color"], linestyle="none", **markers)
        portions.append(pd.DataFrame(data))
    if not portions:
        raise ValueError("The saved graph has no complete XY points.")
    if len(portions) <= 15 and axes.get_legend_handles_labels()[0]:
        for label in axes.legend().get_texts():
            label.set_parse_math(False)
    return Result({"Saved XY coordinates": pd.concat(portions, ignore_index=True)}, figure)
