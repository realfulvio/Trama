"""Restore XY graphs and analyses from the template of a legacy XML project."""

from base64 import b64decode
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from math import ceil, floor, isfinite
from struct import Struct, error as StructError, unpack, unpack_from
from zlib import decompressobj, error as ZlibError

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from .data import MAX_ENTRY
from .legacy_binary import _DATASET
from .legacy_binary_editable import (_axis_config, _id_array, _one, _project_records, _require, _subgroups,
                                    _text_object)
from .legacy_binary_graphs import _read_title
from .legacy_binary_results import _title
from .legacy_restore import LEGACY_NOTES, LEGACY_TITLE, SAVED_XY, _append_linked_recipe
from .legacy_xml_binding import indexed_analyses, restored_binding_recipes
from .legacy_xml_binding_layout import attach_binding_layout
from .legacy_xml_fit_axes import fit_result_sheets, fit_viewport, indexed_fit_views
from .legacy_xml_fit_band import attach_fit_interval_bands
from .legacy_xml_range_fit import attach_bounded_line
from .reference_normalization import EACH, KEEP, MAXIMUM, METHOD, MINIMUM, NORMALIZED, PERCENTAGES, RAW
from .repeated_input import SAVED_REPLICATE_DISPLAY, _series_name
from .reporting import Result
from .worksheet_series import series_columns

XML_ERROR_BARS = "Legacy XML XY errors"
_TEMPLATE_TYPE = "{urn:schemas-microsoft-com:datatypes}dt"
_MARKERS = {1: "s", 5: "o"}
_LINKS = Struct("<3i")
_POINT_STRIDE = 249
_MAX_GRAPH_POINTS = 50_000
_MAX_TICKS = 200
# The observed profile uses the minimum and maximum row means separately for each series.
_REPLICATE_NORMALIZE_PROFILE = "ba9596bc8702eee7a46c1bb40bef4a00eb77b5f1bf5f92791f61ced5a4744c1b"
_NORMALIZED_FIT_PROFILE = "74166d76a178569bd1e3545fab4dbdc1fef47be6d6d98e9f90e97d7d62005ffc"
_NORMALIZED_FIT_OPTIONS = (1, 0, 2, 1, 34, 16, 0, 9, 1, 8, 4, 7, -1, -1)
_NORMALIZED_FIT_HEADERS = (
    "8d12f7b9ec3bd215b857af858468a61622d3b37a8baa41daf8a18b3517806388",
    "d1a4ab967545b84d9e1926517d5d091dc93aa667cd16c22ac298ef881fc86402",
)
_NORMALIZED_CONSTRAINTS = {
    0xC4: "2998012907ffc53c7f28e83d28a05e1ddd9781639ee18b45bf4f34f66a8dd1fd",
    0xC9: "8ffeda13d6d229318db0347ac069827af256069db8fa29eaa68d07bfa131a4d0",
}
_DOSE_EQUATION = b"Y=Bottom+(Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))"
_DOSE_MODEL = "Normalized stimulation (variable slope, log10 X)"


def template_data(root, namespace):
    """Decode the one bounded binary Template element without executing its content."""
    templates = root.findall(namespace + "Template")
    if len(templates) != 1:
        return None
    template = templates[0]
    if len(template) or template.get(_TEMPLATE_TYPE) != "bin.base64":
        return None
    try:
        compressed = b64decode("".join((template.text or "").split()), validate=True)
        decoder = decompressobj()
        data = decoder.decompress(compressed, MAX_ENTRY + 1)
    except (ValueError, ZlibError):
        return None
    if len(data) <= MAX_ENTRY and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail:
        return data
    return None


def attach_xml_error_graphs(root, namespace, sources):
    """Attach native recipes to their source tables. Bad artwork does not stop data import."""
    data = template_data(root, namespace)
    if data is None:
        return
    try:
        originals, analyses = indexed_analyses(data)
    except (ValueError, StructError):
        originals, analyses = set(), []
    outputs = {uid: _single_result_sheet(contents) for uid, _, _, contents in analyses}
    table_ids = set(sources) | {uid for uid in outputs.values() if uid is not None}
    fit_sheets = {uid: sheets for uid, _, kind, contents in analyses
                  if kind[:2] == (0, 5) and (sheets := fit_result_sheets(contents)) is not None}
    curve_sheets = {uid: curve for uid, (_, curve) in fit_sheets.items()}
    table_ids.update(sheet for pair in fit_sheets.values() for sheet in pair)
    try:
        index, encoding, graphs, tables = _project_records(data, table_ids)
    except (ValueError, StructError):
        return

    source_analyses = [item for item in analyses if item[1] in originals and item[1] in sources]
    binding = list(restored_binding_recipes(source_analyses, sources))
    for _, _, frame, method, options in binding:
        recipes = frame.attrs.setdefault("legacy_recipes", [])
        if len(recipes) < 256:
            recipes.append((method, options))
    attach_binding_layout(data, sources, binding)
    fit_views = indexed_fit_views(graphs)
    _restore_xy_transforms(sources, source_analyses, analyses, originals, outputs, tables,
                           curve_sheets, fit_views, encoding)
    attach_bounded_line(analyses, sources, originals, outputs, tables, graphs, fit_views, encoding)
    attach_fit_interval_bands(sources, source_analyses, fit_sheets, tables, fit_views, encoding)

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
            options = {LEGACY_TITLE: view_name[:160], "X": x, XML_ERROR_BARS: style}
        except (IndexError, KeyError, TypeError, ValueError, StructError):
            continue
        frame.attrs.setdefault("legacy_recipes", []).append((SAVED_XY, options))


def _single_result_sheet(contents):
    try:
        count, output, *unused = unpack("<11i", _one(contents, 0x3C))
    except (ValueError, StructError):
        return None
    if count == 10 and 0 <= output <= 65535 and set(unused) == {-1}:
        return output
    return None


def _restore_xy_transforms(sources, source_analyses, analyses, originals, outputs, tables, curve_sheets, views, encoding):
    writers = Counter(outputs.values())
    original_sheets = originals | sources.keys()
    log_results = {}
    for uid, sheet, kind, contents in source_analyses:
        frame, x, groups = sources[sheet]
        output = outputs[uid]
        try:
            options = _xml_log_transform(sheet, kind, contents, tables.get(sheet), frame, x, groups, output)
        except (ValueError, StructError, KeyError, TypeError):
            continue
        if options is not None:
            recipes = frame.attrs.setdefault("legacy_recipes", [])
            if len(recipes) < 256:
                if output not in original_sheets and writers[output] == 1:
                    log_results[output] = uid, len(recipes), frame, x, groups
                recipes.append(("Transform concentrations (X)", options))

    normalized_results = {}
    for uid, sheet, kind, contents in analyses:
        if sheet not in log_results or kind[:2] != (4, 255):
            continue
        producer, slot, frame, x, groups = log_results[sheet]
        output = outputs[uid]
        if output is None or output == sheet or output in original_sheets or writers[output] != 1:
            continue
        try:
            source_columns = _replicate_columns(tables[sheet], sheet, groups, analysis=producer)
            output_columns = _replicate_columns(tables[output], output, groups, analysis=uid)
            options = _xml_replicate_normalization(uid, kind, contents, frame, x, groups, source_columns)
        except (ValueError, StructError, KeyError, TypeError):
            continue
        normalized_slot = len(frame.attrs["legacy_recipes"])
        if _append_linked_recipe(frame, slot, "Transformed data", METHOD, options):
            normalized_results[output] = normalized_slot, frame, x, output_columns

    for uid, sheet, kind, contents in analyses:
        if sheet not in normalized_results or kind[:2] != (0, 5):
            continue
        slot, frame, x, columns = normalized_results[sheet]
        if len(frame.attrs["legacy_recipes"]) > 254:
            continue
        try:
            options = _xml_normalized_fit(uid, kind, contents, x, columns)
        except (ValueError, StructError, TypeError):
            continue
        title = options[LEGACY_TITLE]
        method = "Global nonlinear regression"
        first_slot = len(frame.attrs["legacy_recipes"])
        _append_linked_recipe(frame, slot, NORMALIZED, method, {
            **options, LEGACY_TITLE: title + " · Separate fits",
        })
        _append_linked_recipe(frame, slot, NORMALIZED, method, {
            **options, LEGACY_TITLE: title + " · Shared Log EC50", "Shared parameters": ["Log EC50"],
            "Compare with independent fits": True,
        })
        curve = curve_sheets.get(uid)
        viewport = fit_viewport(views.get((sheet, curve)), tables.get(curve), uid, curve, columns, encoding)
        if viewport is not None:
            axes_style, display = viewport
            styles = frame.attrs.setdefault("legacy_graph_styles", {})
            for fit_slot in (first_slot, first_slot + 1):
                styles[fit_slot] = deepcopy(axes_style)
                if display:
                    frame.attrs["legacy_recipes"][fit_slot][1][SAVED_REPLICATE_DISPLAY] = deepcopy(display)


def _xml_log_transform(sheet, kind, contents, records, frame, x, groups, output):
    if kind[:2] != (3, 255) or kind[3:] != (1, 191, 0, len(groups), 0):
        return None
    summary = _one(contents, 0xA)
    # The saved standard transform identifies its X operation twice, in the header and the result summary.
    _require(len(summary) == 300 and bytes(summary[24:]).partition(b"\0")[0] == b"Transform: X=Log(X)")
    _require(output is not None and output != sheet)
    columns = _replicate_columns(records, sheet, groups)
    selection = _one(contents, 0x3D)
    _require(len(selection) == 2 + len(columns) * _LINKS.size and unpack_from("<H", selection)[0] == len(columns))
    _require(list(_LINKS.iter_unpack(selection[2:])) == [(uid, -1, -1) for uid in columns])
    _require(is_numeric_dtype(frame[x]))
    return {LEGACY_TITLE: _title(_one(contents, 9))[:160], "X": x, "Logarithm": "Log10"}


def _xml_replicate_normalization(uid, kind, contents, frame, x, groups, source_columns):
    _require(kind == (4, 255, uid, 1, 251, 0, 10, 65535))
    settings = _one(contents, 0x46)
    _require(len(settings) == 1352 and sha256(settings).hexdigest() == _REPLICATE_NORMALIZE_PROFILE)
    _require(len(groups) == 2 and all(len(columns) == 3 for _, columns in groups))
    _verify_pair_selection(contents, source_columns)
    columns = [list(names) for _, names in groups]
    variables = [name for names in columns for name in names]
    _require(series_columns(frame, variables, recognize_replicates=True) == columns)
    return {
        LEGACY_TITLE: _title(_one(contents, 9))[:160], "Input": RAW, "X": x, "Variables": variables,
        "Replicates": EACH, "Zero reference": MINIMUM, "One reference": MAXIMUM,
        "Units": PERCENTAGES, "Reference values in output": KEEP, "Graph results": False,
    }


def _verify_pair_selection(contents, columns):
    first, second = columns
    _require(unpack("<H6i", _one(contents, 0x3D)) == (2, first, 4, 4, second, 4, -1))


def _xml_normalized_fit(uid, kind, contents, x, columns):
    _require(kind == (0, 5, uid, 1, 255, 1, 65535, 0))
    settings = _one(contents, 0x46)
    _require(len(settings) == 1352 and sha256(settings).hexdigest() == _NORMALIZED_FIT_PROFILE)
    _verify_pair_selection(contents, columns)
    model_settings, = _subgroups(contents, 0x8047)
    _require(unpack("<4i4B6i", model_settings[0]) == _NORMALIZED_FIT_OPTIONS)
    fits = list(_subgroups(model_settings[1], 0x8048))
    _require(tuple(sha256(header).hexdigest() for header, _ in fits) == _NORMALIZED_FIT_HEADERS)
    for _, records in fits:
        equation = b"".join(bytes(_one(records, 0x49)).rstrip(b"\0").split())
        _require(equation == _DOSE_EQUATION)
        _require(all(sha256(_one(records, tag)).hexdigest() == digest
                     for tag, digest in _NORMALIZED_CONSTRAINTS.items()))
    series = list(columns.values())
    _require(len({label for label, _ in series}) == 2)
    _require(all(_series_name(name, True) == label for label, names in series for name in names))
    return {
        LEGACY_TITLE: _title(_one(contents, 9))[:140], "Input format": "Wide XY",
        LEGACY_NOTES: "Refits the two series from the normalized replicates. Confidence intervals and curves "
                     "are calculated by Trama.",
        "X": x, "Y columns": [name for _, names in series for name in names], "X values": "As entered",
        "Model": _DOSE_MODEL, "Replicates": "Individual observations", "Merge numbered replicates": True,
        "Weighting": "Unweighted",
    }


def _replicate_columns(records, table, groups, *, analysis=-1):
    fields = {}
    links = {}
    empty_titles = set()
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
            uid, _, _, result, owner, storage, _, kind, role, form, repeat, linked_x, _, rows, cells = (
                _DATASET.unpack(data)
            )
            _require(uid not in fields and uid not in empty_titles and (result, owner, storage) ==
                     (analysis, table, 101 if analysis == -1 else 102))
            if analysis != -1 and (kind, role, form, repeat, rows, cells) == (2, 256, 12, 1, 0, 0):
                _require(not empty_titles)
                empty_titles.add(uid)
                continue
            _require(kind == 1)
            fields[uid] = (role, form, repeat, linked_x)
    _require(len(links) == len(groups))
    xs = [uid for uid, values in fields.items() if values[:3] == (4, 10, 1)]
    _require(len(xs) == 1 and len(fields) == 1 + len(links))
    x, = xs
    result = {}
    for _, (uid, label, columns) in sorted(links.items()):
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
