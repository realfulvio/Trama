"""Restore the legacy Prism XY line objects that agree with their saved drawing."""

from collections import Counter, defaultdict
from math import isclose, isfinite
from struct import Struct, error as StructError, unpack_from

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import NullLocator

from .prism_binary import _DATASET, _records
from .prism_binary_graphs import _emf_dimensions, _graph_index, _read_title


def _require(condition):
    if not condition:
        raise ValueError("Unsupported editable Prism graph.")


def _one(records, tag):
    found = [payload for kind, parents, payload in records if kind == tag and not parents]
    _require(len(found) == 1)
    return found[0]


def _id_array(payload):
    _require(8 <= len(payload) <= 516 and len(payload) % 4 == 0)
    count, *ids = [value for value, in Struct("<i").iter_unpack(payload)]
    _require(0 < count <= 128 and count == len(ids) and all(uid >= 0 for uid in ids))
    return ids


def _project_records(data, table_ids):
    graphs, tables = {}, {}
    indexed = current = None
    encoding = "ascii"
    for tag, parents, payload in _records(data):
        if parents == (1,):
            if tag == 0x8002:
                _require(indexed is None)
                indexed, encoding = _graph_index(payload)
            elif tag in (0x8012, 0x8008):
                current = None
                if len(payload) != 2:
                    continue
                uid, = unpack_from("<H", payload)
                groups = graphs if tag == 0x8012 else tables
                wanted = indexed if tag == 0x8012 else table_ids
                if wanted is not None and uid in wanted:
                    current = []
                    groups[uid] = None if uid in groups else current
        elif parents[:2] == (1, 18) and current is not None:
            current.append((tag, parents[2:], payload))
        elif parents == (1, 8) and current is not None and tag in (0x0D, 0x800F):
            current.append((tag, (), payload))
    return indexed or {}, encoding, graphs, tables


def _series_columns(uid, records, frame, analysis):
    fields, links = {}, {}
    for tag, _, payload in records:
        if tag == 0x0D:
            _require(len(payload) == 24 and unpack_from("<I", payload, 8)[0] == 1)
            index, data_uid = unpack_from("<II", payload)
            _require(index not in links)
            links[index] = data_uid
        elif tag == 0x800F:
            _require(len(payload) == _DATASET.size)
            data_uid, _, _, result, owner, storage, _, kind, role, form, repeat, linked_x, _, rows, cells = (
                _DATASET.unpack(payload)
            )
            _require(data_uid not in fields and owner == uid and result == analysis
                     and storage == (101 if analysis == -1 else 102)
                     and repeat == 1 and rows == cells)
            fields[data_uid] = (kind, role, form), linked_x
    _require(sorted(links) == list(range(len(links))))
    y = [data_uid for _, data_uid in sorted(links.items()) if data_uid != 0xFFFFFFFF]
    x = [data_uid for data_uid, (kind, _) in fields.items() if kind in ((1, 4, 10), (4, 4, 11))]
    titles = [data_uid for data_uid, (kind, _) in fields.items() if kind == (2, 256, 12)]
    _require(len(x) == 1 and len(titles) <= 1 and len(set(y)) == len(y)
             and set(x + y + titles) == fields.keys() and frame.shape[1] == 1 + len(y) + len(titles))
    offset = len(titles)
    return {
        data_uid: (uid, frame, offset, column)
        for column, data_uid in enumerate(y, offset + 1)
        if fields[data_uid][0] == (1, 8, 10)
        or fields[data_uid] == ((1, 40, 10), x[0])
    }


def _subgroups(records, tag):
    """Collect subgroups from one already validated TLV parent."""
    depth = tag & 0x3FFF
    group = None
    for kind, parents, payload in records:
        if not parents:
            if group is not None:
                yield group
            group = (payload, []) if kind == tag else None
        elif group is not None and parents[0] == depth:
            group[1].append((kind, parents[1:], payload))
    if group is not None:
        yield group


def _preview(graph):
    payload = _one(graph, 0x5E)
    _require(len(payload) >= 136 and unpack_from("<II", payload) == (len(payload) - 136, 1))
    emf = payload[136:]
    _emf_dimensions(emf)
    return emf


def _drawing(emf):
    """Read strokes and strings from the validated EMF+ drawing, with no playback."""
    objects = {}
    paths, lines = [], []
    strings, legacy_strings = {}, set()
    pos = 108
    while pos < len(emf):
        kind, size = unpack_from("<II", emf, pos)
        record = emf[pos:pos + size]
        pos += size
        if kind == 84:
            count, offset = unpack_from("<II", record, 44)
            if count and offset:
                legacy_strings.add(bytes(record[offset:offset + 2 * count]).decode("utf-16le"))
        if kind != 70:
            continue
        cursor = 16
        while cursor < size:
            kind_plus, flags, size_plus, _ = unpack_from("<HHII", record, cursor)
            part = record[cursor:cursor + size_plus]
            cursor += size_plus
            key = flags & 255
            if kind_plus == 0x4008:
                objects[key] = flags >> 8, part
            elif kind_plus == 0x4015:
                pen_key, = unpack_from("<I", part, 12)
                path_type, path = objects[key]
                pen_type, pen = objects[pen_key]
                _require(path_type == 3 and pen_type == 2)
                count, encoding = unpack_from("<II", path, 16)
                _require(encoding == 0x4000 and 2 <= count <= 256 and count % 2 == 0)
                point_end = 24 + 4 * count
                _require(bytes(path[point_end:point_end + count]) == b"\x00\x01" * (count // 2))
                coords = list(Struct("<hh").iter_unpack(path[24:point_end]))
                paths.append((coords, _stroke(pen)))
            elif kind_plus == 0x400D:
                pen_type, pen = objects[key]
                _require(pen_type == 2)
                coords = np.frombuffer(part[16:], dtype="<i2").reshape(-1, 2)
                lines.append((coords, _stroke(pen)))
            elif kind_plus in (0x401C, 0x4036):
                count_offset, start = (20, 40) if kind_plus == 0x401C else (24, 28)
                count, = unpack_from("<I", part, count_offset)
                if count:
                    title = bytes(part[start:start + 2 * count]).decode("utf-16le").strip()
                    if title:
                        strings[title] = _text_font(objects.get(key))
            elif kind_plus in (0x400A, 0x4014):
                # The simple line profile has no filled shapes apart from the
                # white graph background. Filled paths may be data or annotations.
                _require(kind_plus == 0x400A and unpack_from("<I", part, 12)[0] == 0xFFFFFFFF)
    _require(len(paths) == 2 and len(lines) <= 256)
    return paths, lines, strings or {value.strip(): {} for value in legacy_strings if value.strip()}


def _text_font(font_object):
    if font_object is None or font_object[0] != 6:
        return {}
    font = font_object[1]
    size, unit, style, _, count = unpack_from("<f4I", font, 16)
    if unit not in (2, 3) or not 24 <= size <= 240 or style > 3 or not 0 < count <= 32:
        return {}
    family = bytes(font[36:36 + 2 * count]).decode("utf-16le")
    if not family.isprintable():
        return {}
    return {"fontsize": size / 6, "fontweight": "bold" if style & 1 else "normal",
            "fontstyle": "italic" if style & 2 else "normal"}


def _stroke(pen):
    flags, unit, width = unpack_from("<IIf", pen, 20)
    b, g, r, a = pen[-4:]
    _require(flags in (80, 208, 464) and unit == 0 and a == 255 and isfinite(width) and 0 < width <= 36)
    if flags == 464:
        # The saved dotted reference uses a round dash cap and a one-to-two dash pattern.
        _require(unpack_from("<Iff", pen, 44) == (2, 1.0, 2.0))
    return {"color": f"#{r:02x}{g:02x}{b:02x}", "width": width / 6,
            "dotted": flags == 464}


def _axis_coordinates(paths, configs):
    result = []
    # Axes are saved as a long segment followed by shorter perpendicular tick
    # segments. The endpoint overhang is one half of the pen width.
    for axis in range(2):
        other = 1 - axis
        matches = [(coords, stroke) for coords, stroke in paths if coords[0][other] == coords[1][other]]
        _require(len(matches) == 1)
        coords, stroke = matches[0]
        _require(not stroke["dotted"])
        lo, hi = sorted((coords[0][axis], coords[1][axis]))
        expected_span = configs[axis]["length"]
        _require(abs(hi - lo - stroke["width"] * 6 - expected_span) <= 2)
        base = coords[0][other]
        ticks = {}
        for start, end in zip(coords[2::2], coords[3::2], strict=True):
            _require(start[other] == base and start[axis] == end[axis] and lo <= start[axis] <= hi)
            length = abs(end[other] - base)
            _require(0 < length <= 100)
            ticks[start[axis]] = length
        low = (lo + hi - expected_span) / 2
        result.append((low, low + expected_span, base, ticks, stroke))
    return result


def _axis_config(graph):
    axes = [p for tag, path, p in graph if tag == 0x17 and not path]
    _require(len(axes) == 3 and all(len(p) == 60 for p in axes))
    scales = {}
    for header, records in _subgroups(graph, 0x8025):
        _require(len(header) in (122, 134))
        uid, = unpack_from("<H", header)
        _require(uid not in scales)
        scales[uid] = header, records
    configs = []
    for p in axes[:2]:
        low, high = unpack_from("<2d", p, 16)
        length, _, kind, title = unpack_from("<4H", p, 42)
        tick_id, = unpack_from("<H", p, 54)
        header, records = scales[tick_id]
        tick_low, tick_high, unit = unpack_from("<3d", header, 2)
        _require(kind in (0, 1) and unpack_from("<H", header, 28)[0] == kind
                 and 100 <= length <= 20000 and all(isfinite(value) for value in (low, high, unit))
                 and -1e100 < low < high < 1e100 and unit > 0
                 and (kind == 0 or -300 <= low < high <= 300)
                 and isclose(low, tick_low, abs_tol=unit) and isclose(high, tick_high, abs_tol=unit)
                 and isclose((high - low) / length, unit, rel_tol=1e-5))
        configs.append({"bounds": [low, high], "title": title, "length": length, "unit": unit,
                        "scale": "log" if kind else "linear",
                        "custom_ticks": [p for tag, path, p in records if tag == 0x26 and not path]})
    return configs


def _scene(graph, encoding):
    scenes = list(_subgroups(graph, 0x8018))
    _require(len(scenes) == 1)
    header, scene = scenes[0]
    chart = _one(graph, 0x13)
    _require(len(header) == 12 and len(chart) == 48)
    chart_title, = unpack_from("<H", chart, 32)
    texts, series = {}, {}
    custom = []
    for object_header, records in _subgroups(scene, 0x8020):
        _require(len(object_header) == 30)
        kind, = unpack_from("<H", object_header)
        flags, = unpack_from("<H", object_header, 28)
        _require(kind in (2, 8, 9, 10, 15))
        if kind in (2, 15):
            text_header = _one(records, 0x802B)
            _require(len(text_header) == 18)
            text_id, = unpack_from("<H", text_header)
            parts = [bytes(p) for tag, path, p in records if tag == 0x2C and path == (43,)]
            _require(len(parts) <= 1 and text_id not in texts)
            text = (parts[0] if parts else b"").decode(encoding).strip()
            _require(len(text) <= 240 and all(char.isprintable() for char in text))
            texts[text_id] = "" if flags & 0x200 else text
            if kind == 15 and texts[text_id]:
                custom.append(text)
        elif kind == 9:
            series_header = _one(records, 0x8028)
            _require(len(series_header) == 144)
            key, family, dataset, visible = unpack_from("<4H", series_header)
            _require(key not in series and family == 0 and visible == 1 and dataset < 0x8000
                     and unpack_from("<H", series_header, 58)[0] == 0x88)
            caches = [p for tag, path, p in records if tag == 0x29 and path == (40,)]
            _require(len(caches) == 1 and len(caches[0]) >= 12)
            cache = caches[0]
            count, = unpack_from("<I", cache)
            _require(count >= 4 and count % 2 == 0 and len(cache) == 4 + 4 * count)
            series[key] = dataset, np.frombuffer(cache[4:], dtype="<i4").reshape(-1, 2)
    return texts, custom, texts.get(chart_title, ""), series


def _value(pixel, start, config):
    raw = config["bounds"][0] + (pixel - start) * config["unit"]
    # The picture coordinates are integers. The saved scale gives the original
    # rounding precision of each projected position.
    result = float(f"{raw:.10g}")
    return 0.0 if abs(result) < config["unit"] else result



def _data_value(value, config):
    return 10.0 ** value if config["scale"] == "log" else value

def _graph_axes(paths, lines, configs, texts, custom, title, drawn_text, encoding):
    positions = _axis_coordinates(paths, configs)
    x_left, x_right = positions[0][:2]
    y_top, y_bottom = positions[1][:2]
    ticks = [dict(axis[3]) for axis in positions]
    references = []
    curves = []
    for coords, stroke in lines:
        if len(coords) != 2:
            _require(not stroke["dotted"])
            curves.append((coords, stroke))
            continue
        (x, y), (xx, yy) = coords.tolist()
        x_cross, y_cross = positions[1][2], positions[0][2]
        if x == xx and y == y_cross and 0 < abs(yy - y) <= 100 and not stroke["dotted"]:
            ticks[0][x] = abs(yy - y)
        elif y == yy and x == x_cross and 0 < abs(xx - x) <= 100 and not stroke["dotted"]:
            ticks[1][y] = abs(xx - x)
        elif y == yy and abs(x - x_left) <= 2 and abs(xx - x_right) <= 2 and stroke["dotted"]:
            references.append({**stroke, "y": _data_value(_value(y_bottom - y, 0, configs[1]), configs[1])})
        else:
            raise ValueError("Unsupported Prism drawing annotation.")

    visible_labels = {title} if title else set()
    styles = []
    for axis, (config, tick_pixels) in enumerate(zip(configs, ticks, strict=True)):
        axis_label = texts.get(config["title"], "")
        if axis_label:
            visible_labels.add(axis_label)
        labels = []
        for raw in config["custom_ticks"]:
            _require(len(raw) in (26, 34))
            value, = unpack_from("<d", raw)
            prefix = bytes(raw[10:22]).split(b"\0", 1)[0]
            # The short tick field may be truncated. Its visible string is also
            # saved as a text object. Require a unique prefix corroboration.
            matching = [text for text in custom if text.encode(encoding) == prefix]
            if not matching:
                matching = [text for text in custom if text.encode(encoding).startswith(prefix)]
            _require(isfinite(value) and prefix and len(matching) == 1)
            labels.append((value, matching[0]))
        rendered_ticks = []
        for pixel, length in tick_pixels.items():
            distance = pixel - x_left if axis == 0 else y_bottom - pixel
            _require(-2 <= distance <= config["length"] + 2)
            distance = min(max(distance, 0), config["length"])
            value = _value(distance, 0, config)
            matches = [(target, label) for target, label in labels if abs(target - value) <= 2 * config["unit"]]
            _require(len(matches) <= 1)
            if matches:
                value, label = matches[0]
                visible_labels.add(label)
            else:
                # An ordinary saved tick can be visible without a numeric label.
                label = ""
            rendered_ticks.append([_data_value(value, config), label, length / 6])
        cross_pixel = positions[axis][2]
        other = configs[1 - axis]
        cross = _value(y_bottom - cross_pixel if axis == 0 else cross_pixel - x_left, 0, other)
        _require(other["bounds"][0] - other["unit"] <= cross <= other["bounds"][1] + other["unit"])
        cross = min(max(cross, other["bounds"][0]), other["bounds"][1])
        styles.append({**positions[axis][4], "bounds": [_data_value(v, config) for v in config["bounds"]],
                       "label": axis_label, "scale": config["scale"],
                       "cross": _data_value(cross, other), "ticks": sorted(rendered_ticks)})
    _require(visible_labels == drawn_text.keys())
    return styles, references, curves, (x_left, y_bottom)


def _editable(graph, encoding, owners, remaining_cells):
    _read_title(_one(graph, 9), encoding)
    sheets = set(_id_array(_one(graph, 0x14)))
    order = _id_array(_one(graph, 0x15))
    _require(len(set(order)) == len(order))
    links = _one(graph, 0x16)
    _require(len(links) == 2 + 12 * len(order) and unpack_from("<H", links)[0] == len(order))
    # The old link array may include incomplete or disabled series. This
    # profile requires an explicit active object for every saved link.
    linked = [uid for uid, _, _ in Struct("<3i").iter_unpack(links[2:])]
    texts, custom, title, series = _scene(graph, encoding)
    _require(set(order) == series.keys() and Counter(linked) == Counter(uid for uid, _ in series.values()))
    configs = _axis_config(graph)
    paths, lines, drawn_text = _drawing(_preview(graph))
    axes, references, curves, (left, bottom) = _graph_axes(paths, lines, configs, texts, custom, title, drawn_text, encoding)
    _require(len(curves) == len(series))
    point_frames, styles = [], []
    for key in order:
        uid, cached = series[key]
        matches = [owner for owner in owners[uid] if owner[0] in sheets]
        _require(len(matches) == 1)
        _, frame, x_col, y_col = matches[0]
        xy = frame.iloc[:, [x_col, y_col]].to_numpy(dtype=float, na_value=np.nan)
        _require(len(xy) == len(cached) and np.isfinite(xy).all() and len(xy) * 4 <= remaining_cells)
        units = np.array([config["unit"] for config in configs])
        origin = np.array([config["bounds"][0] for config in configs])
        coords = xy.copy()
        for axis, config in enumerate(configs):
            if config["scale"] == "log":
                _require(np.all(coords[:, axis] > 0))
                coords[:, axis] = np.log10(coords[:, axis])
        projected = (coords - origin) / units
        _require(np.all(np.abs(projected - cached) <= 2))
        # Prism's DrawLines duplicates adjacent endpoints. The graph object
        # cache has each point once. Match the full sequence before accepting
        # the preview pen as this dataset's pen.
        picture = cached * [1, -1] + [left, bottom]
        matches = [
            i for i, (points, _) in enumerate(curves)
            if len(points) == 2 * len(cached) and np.all(np.abs(points[1::2] - picture) <= 2)
            and np.all(np.abs(points[2::2] - picture[:-1]) <= 2)
            and np.all(np.abs(points[0] - picture[0]) <= 2)
        ]
        _require(len(matches) == 1)
        _, stroke = curves.pop(matches[0])
        styles.append({"id": key, **stroke})
        point_frames.append(pd.DataFrame({
            "X": xy[:, 0], "Y": xy[:, 1], "Series": str(frame.columns[y_col]), "Dataset": key,
        }))
        remaining_cells -= len(xy) * 4
    return pd.concat(point_frames, ignore_index=True), {
        "title": title, "axes": axes, "series": styles, "references": references,
        "aspect": configs[1]["length"] / configs[0]["length"], "fonts": drawn_text,
    }


def read_editable_graphs(data, sources, result_frames, remaining_cells, *, cached_curves=()):
    """Return editable data and drawing metadata for verified graphs."""
    from .prism_binary_bars import read_bar_graph
    from .prism_emf_edit import read_cached_emf_curve, read_emf_curve, read_emf_error_points
    from .prism_pdf_stacks import read_pdf_stack

    frames = {**result_frames, **sources}
    indexed, encoding, graphs, tables = _project_records(data, frames)
    owners = defaultdict(list)
    for uid, frame in frames.items():
        if records := tables.get(uid):
            analysis = frame.attrs.get("prism_binary_result", {}).get("analysis_id", -1)
            try:
                columns = _series_columns(uid, records, frame, analysis)
            except ValueError:
                continue
            for data_uid, owner in columns.items():
                owners[data_uid].append(owner)
    restored = {}
    for uid in indexed:
        if graph := graphs.get(uid):
            readers = (
                (read_emf_curve, (graph, owners, remaining_cells, True)),
                (_editable, (graph, encoding, owners, remaining_cells)),
                (read_bar_graph, (graph, sources, tables, remaining_cells)),
                (read_emf_curve, (graph, owners, remaining_cells)),
                (read_emf_error_points, (graph, sources, tables, remaining_cells)),
                (read_pdf_stack, (graph, sources, tables, remaining_cells)),
            )
            if uid in cached_curves:
                readers += ((read_cached_emf_curve, (graph, remaining_cells)),)
            for read, args in readers:
                try:
                    points, style = read(*args)
                except (KeyError, StructError, ValueError):
                    continue
                restored[uid] = points, style
                remaining_cells -= points.size
                break
    return restored


def render_editable_graph(frame, style):
    """Render the saved line styles against the current editable coordinates."""
    _require(isinstance(style, dict) and {"X", "Y", "Dataset", "Series"} <= set(frame.columns))
    figure = Figure(figsize=(7.2, 4.8), layout="constrained")
    axes = figure.add_subplot()
    fonts = style.get("fonts", {})
    axes.set_title(style["title"], parse_math=False, **fonts.get(style["title"], {}))
    axes.set_box_aspect(style.get("aspect"))
    axes.spines[["top", "right"]].set_visible(False)
    axes.set_xscale(style["axes"][0].get("scale", "linear"))
    axes.set_yscale(style["axes"][1].get("scale", "linear"))
    for axis, spine, config in zip((axes.xaxis, axes.yaxis), ("bottom", "left"), style["axes"], strict=True):
        axis.set_label_text(config["label"], parse_math=False, **fonts.get(config["label"], {}))
        axes.spines[spine].set_position(("data", config["cross"]))
        axes.spines[spine].set_color(config["color"])
        axes.spines[spine].set_linewidth(config["width"])
        ticks = axis.set_ticks([tick[0] for tick in config["ticks"]],
                               [tick[1] for tick in config["ticks"]], parse_math=False)
        axis.set_minor_locator(NullLocator())
        axis.set_tick_params(color=config["color"], width=config["width"])
        for artist, tick in zip(axis.get_major_ticks(len(ticks)), config["ticks"], strict=True):
            artist.label1.update(fonts.get(tick[1], {}))
            if len(tick) == 3:
                artist.tick1line.set_markersize(tick[2])
                artist.tick2line.set_markersize(tick[2])
    for reference in style["references"]:
        axes.axhline(reference["y"], color=reference["color"], lw=reference["width"], ls=(0, (1, 2)))
    for series in style["series"]:
        part = frame.loc[frame["Dataset"].eq(series["id"])]
        labels = part["Series"].dropna().astype(str).unique()
        if part.empty or len(labels) != 1:
            raise ValueError("Each editable Prism dataset needs one series label.")
        axes.plot(part["X"], part["Y"], label=labels[0], color=series["color"], lw=series["width"])
    axes.set_xlim(style["axes"][0]["bounds"])
    axes.set_ylim(style["axes"][1]["bounds"])
    return figure
