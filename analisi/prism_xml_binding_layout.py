"""Link the two plots of a legacy binding page to their original worksheets."""

from struct import Struct, error as StructError, unpack, unpack_from
from uuid import uuid4

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
import numpy as np
from pandas.api.types import is_numeric_dtype

from .curve_models import MODELS
from .prism_binary import _DATASET
from .prism_binary_editable import _axis_config, _id_array, _one, _project_records, _require, _subgroups
from .prism_binary_graphs import _read_title
from .prism_binary_layouts import read_binary_layouts
from .prism_layout_edit import PRISM_PANEL_DATA
from .prism_restore import PRISM_GRAPH_LINK, PRISM_NOTES, PRISM_TITLE, SAVED_BINARY_LAYOUT, SAVED_XY
from .prism_xml_binding import SCATCHARD, scatchard
from .prism_zip_layout import ZIP_LAYOUT, _linked_objects, _page_size, _positioned_records
from .prism_zip_xy import _linear_axes, _saved_plot_box
from .reporting import Result
from .stats import nonlinear
from .xy_series import _numbers


XML_BINDING_XY = "Prism XML binding graph"
_BINDING = "One-site specific binding"
_LINK = Struct("<3i")
_MARKERS = {1: "s", 5: "o"}


def _dataset_fields(tables):
    fields = {}
    for owner, records in tables.items():
        if records is None:
            continue
        for tag, _, payload in records:
            if tag == 0x800F:
                uid, _, _, analysis, sheet, storage, _, nature, role, form, repeats, x, _, _, _ = _DATASET.unpack(payload)
                _require(sheet == owner and uid not in fields)
                fields[uid] = (analysis, owner, storage, nature, role, form, repeats, x)
    return fields


def _worksheet_chart(records, encoding, fields, sources, recipes):
    links = _one(records, 0x16)
    _require(len(links) == 2 + 2 * _LINK.size and unpack_from("<H", links)[0] == 2)
    sheets = _id_array(_one(records, 0x14))
    inputs, derived = {}, {}
    for uid, first, second in _LINK.iter_unpack(links[2:]):
        analysis, sheet, storage, nature, role, form, repeats, x = fields[uid]
        x_field = fields[x]
        _require(repeats == 1 and sheet in sheets and x_field[:3] == (analysis, sheet, storage)
                 and x_field[4] == 4 and x_field[6] == 1 and form == 10 and nature == 1)
        if analysis == -1 and (storage, role, first, second) == (101, 8, -1, -1):
            inputs[uid] = (sheet, sources[sheet])
        elif (storage, first, second) == (102, 2, 2) and analysis in recipes:
            origin, method, options = recipes[analysis]
            _require(role == (8 if method == SCATCHARD else 40))
            derived[uid] = origin, method, options
    (observed_id, (observed_sheet, (frame, x, groups))), = inputs.items()
    (calculated_id, (origin, method, options)), = derived.items()
    _require(len(sheets) == len(set(sheets)) == 2 and len(groups) == len(groups[0][1]) == 1)
    y, = groups[0][1]
    _require(is_numeric_dtype(frame[x]) and is_numeric_dtype(frame[y]))
    is_ratio = method == SCATCHARD
    _require((observed_sheet != origin if is_ratio else observed_sheet == origin)
             and (not is_ratio or len(frame) == 2))
    style = _chart_style(records, encoding, observed_id, calculated_id)
    style.update({"x": x, "y": y, "kind": "ratio" if is_ratio else "binding"})
    if not is_ratio:
        _require(options.get("Model") == _BINDING)
    return observed_sheet, origin, frame, style


def _caption(details, encoding, flags):
    header = _one(details, 0x802B)
    _require(len(header) == 18)
    identity, = unpack_from("<H", header)
    text, = [bytes(part) for tag, path, part in details if tag == 0x2C and path == (43,)]
    caption = text.decode(encoding).replace("\r\n", "\n").replace("\r", "\n").strip()
    _require(len(caption) <= 240 and all(char.isprintable() or char == "\n" for char in caption))
    return identity, "" if flags & 0x200 else caption


def _chart_style(records, encoding, observed, calculated):
    chart = _one(records, 0x13)
    _require(len(chart) == 48)
    x_axis, y_axis = _axis_config(records)
    names = (unpack_from("<H", chart, 32)[0], x_axis["title"], y_axis["title"])
    _require(len(set(names)) == len(names))
    (scene_header, scene), = _subgroups(records, 0x8018)
    _require(len(scene_header) == 12)
    objects = list(_subgroups(scene, 0x8020))
    order = _id_array(_one(records, 0x15))
    series, labels = {}, {}
    for header, details in objects:
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 2:
            try:
                identity, caption = _caption(details, encoding, unpack_from("<H", header, 28)[0])
            except (ValueError, StructError):
                continue
            _require(identity not in labels)
            labels[identity] = caption
        elif kind == 9:
            drawing = _one(details, 0x8028)
            _require(len(drawing) == 144)
            key, family, uid, visible, _, bars, draw, _ = unpack_from("<8H", drawing)
            marker, size = unpack_from("<2H", drawing, 60)
            _require(key not in series and uid in (observed, calculated)
                     and (family, visible, bars) == (0, 1, 0) and draw in (0, 2)
                     and drawing[71] == drawing[87] == 0)
            item = {"point": "#" + bytes(drawing[68:71]).hex(), "line": "#" + bytes(drawing[84:87]).hex()}
            if marker in _MARKERS and 1 <= size <= 30:
                item.update(marker=_MARKERS[marker], size=size)
            series[key] = uid, item
    _require(len(order) == 2 and set(order) == series.keys()
             and {uid for uid, _ in series.values()} == {observed, calculated})
    styles = dict(series.values())
    captions = {key: labels[uid] for key, uid in zip(("title", "xlabel", "ylabel"), names, strict=True)
                if uid in labels}
    style = {"axes": list(_linear_axes(records)), "captions": captions,
             "observed": styles[observed], "calculated": styles[calculated]}
    plot = _saved_plot_box(records, objects)
    if plot is not None:
        style["plot"] = plot
    return style


def attach_binding_layout(data, sources, binding):
    """Attach only a complete two-graph page with verified analysis and worksheet links."""
    recipes = {uid: (sheet, method, options) for uid, sheet, _, method, options in binding}
    if {method for _, method, _ in recipes.values()} != {"Nonlinear regression", SCATCHARD}:
        return
    try:
        layouts, skipped = read_binary_layouts(data)
        layout, = layouts
        _require(not skipped and layout["placements_complete"] and len(layout["placements"]) == 2)
        indexed, encoding, graphs, tables = _project_records(data, range(65536))
        fields = _dataset_fields(tables)
        references = [panel["graph_id"] for panel in layout["placements"]]
        _require(len(set(references)) == 2 and set(references).issubset(indexed))
        charts = {key: _worksheet_chart(graphs[key], encoding, fields, sources, recipes) for key in references}
        (fit_key,), (ratio_key,) = ([key for key in charts if charts[key][3]["kind"] == kind]
                                  for kind in ("binding", "ratio"))
        fit_sheet, _, fit_frame, fit_style = charts[fit_key]
        _, ratio_origin, ratio_frame, ratio_style = charts[ratio_key]
        _require(ratio_origin == fit_sheet and ratio_frame is not fit_frame)
        records, units = _positioned_records(data, layout["id"])
        page = _one(records, 0xA)
        _require(len(page) == 300)
        rendered = {key: (_read_title(_one(graphs[key], 9), encoding)[:160], charts[key][3]) for key in charts}
        panels, connectors, references = _linked_objects(records, rendered)
        for number, key in enumerate(references):
            if key == ratio_key:
                panels[number]["binding_panel"] = str(references.index(fit_key) + 1)
        geometry = {"paper": [value / 100 for value in unpack_from("<2i", page)], "units_per_inch": units,
                    "panels": panels, "connectors": connectors}
        _page_size(geometry)
        _require(len(fit_frame.attrs["prism_recipes"]) < 255
                 and len(ratio_frame.attrs.get("prism_recipes", ())) < 256)
    except (IndexError, KeyError, TypeError, ValueError, OverflowError, StructError):
        return

    instance = uuid4().hex
    links = {key: f"{instance}:{key}" for key in charts}
    for key, (name, style) in rendered.items():
        options = {PRISM_TITLE: name, PRISM_GRAPH_LINK: links[key], XML_BINDING_XY: style}
        if key == ratio_key:
            options[PRISM_PANEL_DATA] = {"binding": links[fit_key]}
        charts[key][2].attrs.setdefault("prism_recipes", []).append((SAVED_XY, options))
    fit_frame.attrs["prism_recipes"].append((SAVED_BINARY_LAYOUT, {
        PRISM_TITLE: layout["title"][:160],
        PRISM_NOTES: "Linked observations, fitted curve and independently editable intercept line.",
        ZIP_LAYOUT: geometry,
        PRISM_PANEL_DATA: {str(number): links[key] for number, key in enumerate(references, 1)},
    }))


def render_binding_graph(frame, style, title, *, binding=None, axes=None):
    if axes is None:
        figure = Figure(figsize=(8., 5.5), layout="constrained")
        axes = figure.add_subplot()
    else:
        figure = axes.figure
    observed = style["observed"]
    calculated = style["calculated"]
    x, y = style["x"], style["y"]
    if style["kind"] == "binding":
        fit, = nonlinear(frame, x, y, _BINDING).values()
        draw_x, draw_y = fit.data[x], fit.data[y]
        grid = np.linspace(*style["axes"][0]["bounds"], 256)
        line_x = grid[grid >= 0.]
        line_y = MODELS[_BINDING].equation(line_x, *fit.parameters["Estimate"])
        dot, stroke = observed, calculated
    elif style["kind"] == "ratio":
        if binding is None or binding[1].get("kind") != "binding":
            raise ValueError("The binding observations worksheet is missing.")
        source, source_style = binding
        points = scatchard(source, {"X": source_style["x"], "Y": source_style["y"]}).tables["Scatchard"]
        draw_x, draw_y = points["Bound"], points["Bound / free"]
        line_x, line_y = _numbers(frame, x), _numbers(frame, y)
        dot, stroke = calculated, observed
    else:
        raise ValueError("Invalid binding chart.")
    _require(all(is_color_like(color) for color in (dot["point"], stroke["line"])))
    axes.plot(draw_x, draw_y, linestyle="none", color=dot["point"], marker=dot.get("marker", "o"),
              markersize=dot.get("size", 4))
    axes.plot(line_x, line_y, color=stroke["line"], linewidth=1)
    captions = style["captions"]
    axes.set(title=captions.get("title", title), xlabel=captions.get("xlabel", x), ylabel=captions.get("ylabel", y))
    for dimension, dimension_style in zip(("x", "y"), style["axes"], strict=True):
        getattr(axes, f"set_{dimension}ticks")(dimension_style["ticks"])
        getattr(axes, f"set_{dimension}lim")(dimension_style["bounds"])
    axes.spines[["right", "top"]].set_visible(False)
    for text in (axes.title, axes.xaxis.label, axes.yaxis.label):
        text.set_parse_math(False)
    return Result({}, figure)
