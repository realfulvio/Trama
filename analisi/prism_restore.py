"""Restore verified native recipes and materialize saved Prism views."""
import csv
from math import remainder
import re
from uuid import uuid4

import numpy as np
import pandas as pd

from .analysis_chain import ResultSource
from .data import EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_EMF, EDITABLE_PRISM_STACKS, EDITABLE_PRISM_XY, MAX_CELLS
from .extract_rearrange import EXTRACT_REARRANGE, EXTRACT_TABLE
from .hierarchical_workbench import HIERARCHY_GRAPH, TREE_AXIS
from .kmeans_archive import ARCHIVE as KMEANS_ARCHIVE
from .kmeans_options import GAP_PLOT, SELECTION, SILHOUETTE_PLOT, WSS_PLOT
from .kmeans_reports import ASSIGNMENTS_TABLE, METRIC, MODEL_GRAPH, assignment_column
from .pca_graphs import COLOR_GROUPS, SAVED_DIRECTIONS
from .pca_overlays import KIND as PCA_OVERLAY, SAVED_APPEARANCE as PCA_OVERLAY_APPEARANCE
from .prism_import import _identifier, _json_object, _store_table, _zip_table
from .prism_fit_graph import FIT_GRAPH, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC, fit_graph_spec, saved_samples
from .prism_pca_view import saved_component_directions, saved_score_overlay
from .prism_recipes import restore_recipe
from .prism_mv_scatter import APPEARANCE, CLUSTERED_SCATTER, saved_scatter
from .survival_plot import CI_BARS, SURVIVAL_GRAPH, SURVIVAL_SERIES, SURVIVAL_SUMMARY, UNCERTAINTY

SAVED_XY = "Imported Prism XY graph"
SAVED_BINARY_GRAPH = "Imported Prism original graph"
SAVED_BINARY_LAYOUT = "Imported Prism layout"
SAVED_EDITABLE_GRAPH = "Imported Prism editable graph"
SAVED_BINARY_RESULT = "Imported Prism saved results"
BINARY_GRAPH_COLLECTION = "Prism graph collection"
BINARY_LAYOUT_COLLECTION = "Prism layout collection"
PRISM_GRAPH_LINK = "Prism original graph link"
PRISM_GRAPH_STYLE = "Prism original graph style"
PRISM_LAYOUT_PANELS = "Prism layout panels"
MAX_LAYOUT_PANEL_DATA = 2 * 1024 * 1024
PRISM_PREVIEW = "Prism graph preview"
PRISM_RESULT_SHEET = "Prism result sheet"
PRISM_TITLE = "Prism sheet title"
PRISM_NOTES = "Prism import notes"


def panel_source_style(method, options):
    """Identify a saved graph that can be recalculated from live worksheet data."""
    if method == SAVED_XY:
        from .prism_xml_binding_layout import XML_BINDING_XY
        from .prism_zip_xy import ZIP_SPARSE_XY

        style = options.get(XML_BINDING_XY, options.get(ZIP_SPARSE_XY))
    elif method == SAVED_EDITABLE_GRAPH:
        style = options.get(PRISM_GRAPH_STYLE)
    else:
        return None
    return style if isinstance(style, dict) else None


def resolve_layout_panel_graphs(run, runs, tables):
    from .prism_layout_edit import PRISM_PANEL_DATA
    from .prism_xml_binding_layout import XML_BINDING_XY
    from .prism_zip_layout import ZIP_LAYOUT

    links = run.options.get(PRISM_PANEL_DATA)
    companion = run.method == SAVED_XY and XML_BINDING_XY in run.options
    if (run.method != SAVED_BINARY_LAYOUT and not companion) or not isinstance(links, dict):
        return {}
    expected = SAVED_XY if companion or ZIP_LAYOUT in run.options else SAVED_EDITABLE_GRAPH
    graphs = {}
    for item in runs:
        link = item.options.get(PRISM_GRAPH_LINK)
        if (item.method == expected and item.title in tables and isinstance(link, str)
                and panel_source_style(item.method, item.options) is not None):
            graphs[link] = None if link in graphs else item
    return {panel: graphs[link]
            for panel, link in links.items() if isinstance(link, str) and graphs.get(link) is not None}


def _list(value):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("Unsupported Prism sheet list.")
    return value


def _opaque_color(value):
    return value[:7].lower() if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}[fF]{2}", value) else None


def _cluster_color_order(groups, count, observations):
    """Translate archived group indices to native first-observation order."""
    if (type(count) is not int or not 1 <= count <= 24 or not 2 <= observations <= 3000
            or not isinstance(groups, list) or len(groups) != count):
        return None
    encountered, first = set(), []
    for group in groups:
        points = group.get("points") if isinstance(group, dict) else None
        if not isinstance(points, list) or not 1 <= len(points) <= observations:
            return None
        members = set()
        for point in points:
            index = point.get("idx") if isinstance(point, dict) else None
            if type(index) is not int or not 0 <= index < observations or index in members or index in encountered:
                return None
            members.add(index)
        encountered.update(members)
        first.append(min(members))
    if len(encountered) != observations:
        return None
    return sorted(range(count), key=first.__getitem__)


def _dendrogram_presentation(component, orientation, *, side=None, order=None):
    """Translate saved branch colors and strokes and the matching linear distance axis."""
    style = {}
    visible = component.get("isVisible")
    if type(visible) is bool:
        style["visible"] = visible
    color_map = component.get("colormap") or {}
    color = _opaque_color(color_map.get("color"))
    if color_map.get("@class") == "SingleColormap" and color:
        style.update(color_mode="single", color=color)
    if (order and component.get("clustersLink") == f"/{side}s/clusters"
            and color_map.get("@class") == "CategoricalColormap" and color_map.get("colorArrayType") == "dataLines"
            and color_map.get("colorsTransparencyPercent") == 0):
        colors = color_map.get("colors")
        if isinstance(colors, dict) and set(colors) == {str(index) for index in order}:
            palette = [_opaque_color(colors[str(index)]) for index in order]
            mixed = _opaque_color(color_map.get("outlierColor"))
            if all(palette) and mixed:
                style.update(color_mode="cluster", palette=palette, mixed_color=mixed)
    stroke = component.get("linesStrokeSettings") or {}
    width = stroke.get("strokeThickness")
    if type(width) in {int, float} and 0 < width <= 12:
        style["width"] = float(width)
    if stroke.get("strokeStyle") in ("solid", "dashed", "dotted", "dashdot"):
        style["line_style"] = stroke["strokeStyle"]
    axis = component.get("axis") or {}
    segments = axis.get("segments")
    if axis.get("orientation") != orientation or not isinstance(segments, list) or len(segments) != 1:
        return style
    segment, = segments
    if segment.get("@class") != "LinearAxisSegment":
        return style
    low, high, step = (segment.get(key) for key in ("lowerLimit", "upperLimit", "interval"))
    if type(low) in {int, float} and type(high) in {int, float} and 0 <= low < high < float("inf"):
        distance = {"minimum": float(low), "maximum": float(high)}
        title = axis.get("title")
        if isinstance(title, dict) and title.get("isVisible") is False:
            distance["title_visible"] = False
        labels = segment.get("labelsSettings")
        if (segment.get("ticksVisibility") == "all" and isinstance(labels, dict)
                and labels.get("isVisible") is True):
            distance["visible"] = True
        if type(step) in {int, float} and 0 < step < float("inf") and segment.get("startTicksValue") == low:
            from .hierarchical_style import MAX_DISTANCE_TICKS

            # The native locator is anchored at zero, so retain matching tick grids.
            if (high - low) / step < MAX_DISTANCE_TICKS and abs(remainder(low, step)) <= step * 1e-10:
                distance["step"] = float(step)
        if type(segment.get("isReversed")) is bool:
            distance["reversed"] = segment["isReversed"]
        style["distance"] = distance
    return style


def _categorical_axis_labels(axis, orientation):
    if not isinstance(axis, dict) or axis.get("orientation") != orientation:
        return {}
    segments = axis.get("segments_ext")
    if not isinstance(segments, list) or len(segments) != 1:
        return {}
    segment = segments[0]
    if not isinstance(segment, dict) or segment.get("@class") != "CategoricalAxisSegment":
        return {}
    settings = segment.get("labelsSettings")
    if not isinstance(settings, dict) or segment.get("labelsFormat") != "values":
        return {}
    labels = {}
    visible = settings.get("isVisible")
    if type(visible) is bool:
        labels["visible"] = visible
    angle = settings.get("rotationAngle", 0)
    if type(angle) in (int, float) and -90 <= angle <= 90:
        labels["rotation"] = angle
    color = _opaque_color(settings.get("textColor"))
    if color:
        labels["color"] = color
    font = settings.get("font")
    if isinstance(font, dict):
        size = font.get("size")
        if type(size) in (int, float) and 4 <= size <= 40:
            labels["size"] = size
        family = font.get("family")
        if isinstance(family, str) and 0 < len(family.strip()) <= 160 and family.isprintable():
            labels["family"] = family.strip()
        if font.get("weight", "normal") in ("normal", "bold"):
            labels["bold"] = font.get("weight") == "bold"
    first = segment.get("startLevelIndex")
    if type(first) is int and 0 <= first < 100000:
        labels["first"] = first + 1
    fixed = segment.get("levelsIntervalFixed")
    interval = segment.get("levelsInterval")
    if fixed is False:
        labels["interval"] = 0
    elif fixed is True and type(interval) is int and 1 <= interval <= 100000:
        labels["interval"] = interval
    return labels


_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _archived_legend_title(title):
    text = title.get("text")
    if not isinstance(text, dict):
        return None
    phrase = text.get("string")
    if not isinstance(phrase, str) or len(phrase) > 160 or not phrase.isprintable():
        return None
    characters = list(phrase)
    formatting = text.get("formatting")
    if isinstance(formatting, list):
        for span in formatting[:160]:
            if not isinstance(span, dict) or not isinstance(span.get("attributes"), dict):
                continue
            index = span.get("range")
            if (span["attributes"].get("baseline") == "subscript" and isinstance(index, str)
                    and re.fullmatch(r"[0-9]{1,3}", index) and int(index) < len(characters)):
                position = int(index)
                characters[position] = characters[position].translate(_SUBSCRIPT_DIGITS)
    return "".join(characters)


def _standalone_cluster_legend(graph, tree, style, order):
    uid, legends = tree.get("uid"), graph.get("legends")
    if (tree.get("isColorLegendEnabled") is not True or "palette" not in style or not order
            or not isinstance(uid, str) or not uid or not isinstance(legends, list) or len(legends) > 256):
        return {}
    matching = [item for item in legends if isinstance(item, dict)
                and item.get("@class") == "CategoricalSymbolsLegend" and item.get("colorSettings") == [uid]
                and item.get("isEnabled") is not False]
    if len(matching) != 1:
        return {}
    legend, = matching
    children = legend.get("children")
    if not isinstance(children, list) or len(children) != len(order):
        return {}
    index_by_color = {color: index + 1 for index, color in enumerate(style["palette"])}
    entries, seen = [], set()
    for item in children:
        if not isinstance(item, dict) or item.get("@class") != "SymbolLegend":
            return {}
        group = index_by_color.get(_opaque_color(item.get("symbolFillColor")))
        title = item.get("title")
        label = _archived_legend_title(title) if isinstance(title, dict) else None
        if group is None or group in seen or label is None or title.get("isVisible") is False:
            return {}
        seen.add(group)
        entries.append({"group": group, "label": label})
    title = legend.get("title")
    caption = _archived_legend_title(title) if isinstance(title, dict) and title.get("isVisible") is not False else ""
    return {"legend_visible": True, "legend_title": caption or "", "legend_entries": entries}


def _heatmap_colorbar(graph, heatmap):
    uid = heatmap.get("uid")
    legends = graph.get("legends")
    if not isinstance(uid, str) or not uid or not isinstance(legends, list) or len(legends) > 256:
        return {}
    matching = [item for item in legends if isinstance(item, dict)
                and item.get("@class") == "GradientColorLegend" and item.get("colorSettings") == [uid]]
    if len(matching) != 1:
        return {}
    legend, = matching
    result = {}
    orientation = legend.get("orientation")
    if orientation in ("horizontal", "vertical"):
        result["orientation"] = orientation
    reversed_scale = legend.get("isReversedDirection")
    if type(reversed_scale) is bool:
        result["scale_reverse"] = reversed_scale
    title = legend.get("title")
    if isinstance(title, dict):
        plain = _archived_legend_title(title)
        if plain is not None:
            result["title"] = plain
        if title.get("isVisible") is False:
            result["title_position"] = "hidden"
        elif title.get("isVisible") is True and title.get("dockPosition") == "above":
            result["title_position"] = "above"
    labels = legend.get("labelsSettings")
    if isinstance(labels, dict):
        visible = labels.get("isVisible")
        if type(visible) is bool:
            result["scale_labels"] = visible
        color = _opaque_color(labels.get("textColor"))
        if color:
            result["scale_color"] = color
        font = labels.get("font")
        if isinstance(font, dict):
            size, family = font.get("size"), font.get("family")
            if type(size) in (int, float) and 4 <= size <= 40:
                result["scale_size"] = size
            if isinstance(family, str) and 0 < len(family.strip()) <= 160 and family.isprintable():
                result["scale_font"] = family.strip()
    return result


def _heatmap_presentation(graph, heatmap, color_orders, axes):
    section = {}
    for component in _list(graph.get("components", [])):
        side = component.get("levelsSourceType")
        if (side not in ("rows", "columns") or component.get("@class") != "DendrogramGraphComponent"
                or component.get("branchesLink") != f"/{side}/dendrogram"):
            continue
        key = side[:-1]
        if key not in axes or key in section:
            raise ValueError("Unexpected saved dendrogram component.")
        section[key] = _dendrogram_presentation(component, "horizontal" if side == "rows" else "vertical",
                                                side=key, order=color_orders.get(key))
    for key, name, orientation in (("column", "axisX", "horizontal"), ("row", "axisY", "vertical")):
        labels = _categorical_axis_labels(graph.get(name), orientation)
        if labels:
            section.setdefault(key, {})["labels"] = labels
    settings = _heatmap_colorbar(graph, heatmap)
    colormap = heatmap.get("colormap") or {}
    if (colormap.get("@class") == "GradientColormap" and colormap.get("colorScheme") == "Viridis"
            and colormap.get("colorsTransparencyPercent") == 0):
        settings["cmap"] = "viridis"
    if type(heatmap.get("isColorLegendEnabled")) is bool:
        settings["colorbar"] = heatmap["isColorLegendEnabled"]
    if settings:
        section["heatmap"] = settings
    return section


def _hierarchy_views(archive, names, analysis, axes, color_orders):
    """Recognize only views with matching analysis, graph, source sheet and tree identities."""
    from .hierarchical_style import validate_hierarchical_style

    found = {}
    try:
        references = _list(analysis.get("graphs", []))
    except ValueError:
        return found
    for reference in references:
        try:
            settings = reference["settings"]
            uid = _identifier(settings["uid"])
            data_sheet = _identifier(settings["graph"]["dataSheet"])
            path = f"graphs/{uid}/sheet.json"
            if path not in names:
                continue
            sheet = _json_object(archive, path)
            graph = sheet["graph"]
            if sheet.get("uid") != uid or graph.get("dataSheet") != data_sheet:
                continue
            title = sheet.get("title")
            ext = graph.get("gdoSettingsExt", {})
            heatmap = ext.get("heatmap", {})
            tree = ext.get("dendrogram", {})
            options = {"Graph output": "Heat map"}
            if heatmap.get("@class") == "HeatmapFigure::Settings":
                section = _heatmap_presentation(graph, heatmap, color_orders, axes)
            elif tree.get("@class") == "DendrogramFigure::Settings":
                axis = {"/rows/dendrogram": "row", "/columns/dendrogram": "column"}.get(tree.get("branchesLink"))
                if axis not in axes or graph.get("components"):
                    continue
                # The distance axis has the saved branch heights. The orthogonal
                # axis indexes leaves. Infer orientation only from the verified range.
                orientations = [direction for key, direction in (("axisX", "horizontal"), ("axisY", "vertical"))
                                if "distance" in _dendrogram_presentation(
                                    {**tree, "axis": graph.get(key)}, direction)]
                if len(orientations) > 1:
                    continue
                orientation = orientations[0] if orientations else "vertical"
                horizontal = orientation == "horizontal"
                distance_key, leaf_key = ("axisX", "axisY") if horizontal else ("axisY", "axisX")
                tree_style = _dendrogram_presentation({**tree, "axis": graph.get(distance_key)}, orientation,
                                                      side=axis, order=color_orders.get(axis))
                labels = _categorical_axis_labels(graph.get(leaf_key), "vertical" if horizontal else "horizontal")
                if labels:
                    tree_style["labels"] = labels
                tree_style.update(_standalone_cluster_legend(graph, tree, tree_style, color_orders.get(axis)))
                section = {axis: tree_style}
                options = {"Graph output": "Dendrogram", TREE_AXIS: axis.capitalize() + "s",
                           "Dendrogram orientation": orientation.capitalize()}
            else:
                continue
            style = {"hierarchical": validate_hierarchical_style(section)} if section else {}
            found[uid] = title if isinstance(title, str) and title else None, options, style
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            continue
    return found


def _restore_hierarchy_views(archive, names, sheet, results, producer, slot, options, restyled):
    direction = options["Direction"]
    axes = ("row", "column") if direction == "Rows and columns" else (direction.lower()[:-1],)
    content = results.get("content") if isinstance(results, dict) else None
    color_orders = {}
    if (isinstance(content, dict) and not producer.attrs.get("excluded")
            and not producer[options["Variables"]].isna().any(axis=None)):
        for side, field, size in (("row", "Clusters", len(producer)),
                                  ("column", "Column clusters", len(options["Variables"]))):
            view = content.get(f"{side}s")
            if side in axes and options.get(f"{side.capitalize()} cut") == "Count" and isinstance(view, dict):
                color_orders[side] = _cluster_color_order(view.get("clusters"), options[field], size)
    views = _hierarchy_views(archive, names, sheet, axes, color_orders)
    primary = [uid for uid, (_, view, _) in views.items() if uid not in restyled
               and view["Graph output"] == options["Graph output"]
               and (options["Graph output"] != "Dendrogram" or view.get(TREE_AXIS) == direction)]
    styles = producer.attrs.setdefault("prism_graph_styles", {}) if views else {}
    if len(primary) == 1:
        uid = primary[0]
        _, view, style = views.pop(uid)
        if "Dendrogram orientation" in view:
            options["Dendrogram orientation"] = view["Dendrogram orientation"]
        if style:
            styles[slot] = style
        options[PRISM_NOTES] = ("Recalculates the supported hierarchy and restores selected saved graph settings. "
                                "Other settings use Trama formatting.")
        restyled.add(uid)
    table = "Merges" if len(axes) == 1 else "Row Merges"
    for uid, (title, view, style) in views.items():
        if uid in restyled:
            continue
        child = len(producer.attrs["prism_recipes"])
        view[PRISM_TITLE] = (title or view["Graph output"])[:160]
        view[PRISM_NOTES] = ("Recalculates this view from the linked native hierarchy. "
                             "Selected saved graph settings are restored.")
        if _append_linked_recipe(producer, slot, table, HIERARCHY_GRAPH, view):
            if style:
                styles[child] = style
            restyled.add(uid)


def _saved_xy(graph, owners, remaining_cells):
    datasets = graph.get("inputDataSets")
    if not isinstance(datasets, list) or not datasets or len(datasets) > 100 or len(set(datasets)) != len(datasets):
        return None
    parts, labels, rows = [], set(), 0
    has_replicates = False
    for i, uid in enumerate(datasets):
        matches = owners.get(uid, ())
        if len(matches) != 1:
            return None
        frame, geometry = matches[0]
        mapping = frame.attrs["prism_columns"]
        xcols = mapping.get(frame.attrs["prism_x"], [])
        columns = mapping[uid]
        if len(xcols) != 1 or not columns:
            return None
        mode = frame.attrs["prism_y_format"]
        errors = []
        if mode in {"y_plus_minus", "y_high_low"}:
            errors = columns[1:3]
        elif mode in {"y_sd", "y_sd_n", "y_se", "y_se_n"}:
            errors = columns[1:2] * 2
        has_replicates |= mode == "y_replicates"
        if mode != "y_replicates":
            columns = columns[:1]
        x = frame[xcols[0]]
        if not pd.api.types.is_numeric_dtype(x):
            return None
        name = re.sub(r" \[(?:\d+|Mean|Center)\]$", "", columns[0])
        for column in columns:
            if not pd.api.types.is_numeric_dtype(frame[column]):
                return None
        xs = np.repeat(x.to_numpy(dtype=float, na_value=np.nan), len(columns))
        ys = frame[columns].to_numpy(dtype=float, na_value=np.nan).ravel()
        keep = np.isfinite(xs) & np.isfinite(ys)
        if not keep.any():
            return None
        rows += int(keep.sum())
        if rows * 7 > remaining_cells:
            return None
        part = pd.DataFrame({"X": xs[keep], "Y": ys[keep], "Series": name,
                             "Dataset": i + 1, "Geometry": geometry})
        if len(errors) == 2:
            plus, minus = (pd.to_numeric(frame[key], errors="coerce").to_numpy(dtype=float, na_value=np.nan)[keep]
                           for key in errors)
            if mode == "y_high_low":
                plus, minus = plus - ys[keep], ys[keep] - minus
            part["Y plus"], part["Y minus"] = plus, minus
        parts.append(part)
        labels.add(xcols[0])
    points = pd.concat(parts, ignore_index=True)
    points.attrs["table_format"] = "Prism graph snapshot"
    note = ("Saved Prism XY coordinates. Replicates are shown individually with Trama formatting."
            if has_replicates else "Saved Prism XY coordinates. The plot uses Trama formatting.")
    points.attrs["prism_recipes"] = [(SAVED_XY, {
        PRISM_TITLE: graph["title"], "X label": next(iter(labels)) if len(labels) == 1 else "X",
        PRISM_NOTES: note,
    })]
    return points


def _clustered_columns(producer, slot, cached):
    """Match the saved assignment columns to the requested native models."""
    recipes = producer.attrs["prism_recipes"]
    if len(recipes) >= 256 or not cached.iloc[:, :len(producer.columns)].equals(producer):
        return None
    saved_options = recipes[slot][1]
    columns = cached.columns[len(producer.columns):]
    counts = range(saved_options["Minimum k"], saved_options["Maximum k"] + 1)
    if list(columns) != [f"{count} clusters" for count in counts]:
        return None
    mapping = {name: name for name in producer}
    for count, name in zip(counts, columns, strict=True):
        values = cached[name].dropna()
        labels = set(values.unique())
        numbers = set(range(1, count + 1))
        if labels != numbers and labels != {f"Cluster {label}" for label in numbers}:
            return None
        mapping[name] = assignment_column(producer, count)
    return mapping


def _link_clustered_pca(producer, slot, cached, method, options):
    mapping = _clustered_columns(producer, slot, cached)
    if mapping is None:
        return False
    color = options[COLOR_GROUPS]
    options = {**options, "Variables": [mapping[name] for name in options["Variables"]],
               COLOR_GROUPS: mapping[color] if color is not None else None,
               PRISM_NOTES: ("Uses the live K-means assignments as input. Trama recalculates standardized PCA "
                             "and the saved color grouping with its own samples from the saved seed."
                             + _pca_overlay_note(options))}
    if SAVED_DIRECTIONS in options:
        options[SAVED_DIRECTIONS] = {name: {mapping[column]: value for column, value in reference.items()}
                                     for name, reference in options[SAVED_DIRECTIONS].items()}
    if PCA_OVERLAY_APPEARANCE in options:
        options[PCA_OVERLAY_APPEARANCE] = {**options[PCA_OVERLAY_APPEARANCE], "column": mapping[color]}
    return _append_linked_recipe(producer, slot, ASSIGNMENTS_TABLE, method, options)


def _link_clustered_scatter(producer, slot, cached, columns, style, title):
    x, y, category = columns
    fitted = producer.attrs["prism_recipes"][slot][1].get(KMEANS_ARCHIVE)
    if fitted is None or x not in producer or y not in producer or category in producer:
        return False
    mapping = _clustered_columns(producer, slot, cached)
    if mapping is None:
        return False
    position = cached.columns.get_loc(category) - len(producer.columns)
    groups = fitted["models"][position]["groups"]
    pairs = pd.DataFrame({"id": groups, "label": cached[category].astype(str)}).drop_duplicates()
    count = producer.attrs["prism_recipes"][slot][1]["Minimum k"] + position
    if len(pairs) != count or len(set(pairs["label"])) != count or set(pairs["label"]) != style["palette"].keys():
        return False
    labels = pairs.sort_values("id")["label"].tolist()
    return _append_linked_recipe(producer, slot, ASSIGNMENTS_TABLE, SAVED_XY, {
        PRISM_TITLE: title[:160], APPEARANCE: style,
        CLUSTERED_SCATTER: {"x": x, "y": y, "group": mapping[category], "labels": labels},
    })


def _link_hierarchy_scatter(graph, saved, cached, columns, style, title):
    (producer, slot), axis, groups, graph_id = saved
    if graph.get("fenID") != graph_id or type(graph.get("fenID")) is not int:
        return False
    x, y, category = columns
    options = producer.attrs["prism_recipes"][slot][1]
    variables = options["Variables"]
    if producer.attrs.get("excluded") or producer[variables].isna().any(axis=None):
        return False
    order = _cluster_color_order(groups, options.get("Clusters" if axis == "Row" else "Column clusters"), len(cached))
    if order is None or list(cached.columns[-1:]) != [category]:
        return False
    labels = [f"Cluster {i + 1}" for i in order]
    archived = cached[category].to_numpy(dtype=str)
    if set(labels) != style["palette"].keys() or any(
            archived[point["idx"]] != f"Cluster {i + 1}" for i, group in enumerate(groups) for point in group["points"]):
        return False
    if axis == "Row":
        if x not in variables or y not in variables or not cached.iloc[:, :-1].equals(producer):
            return False
    else:
        names = options.get("Observation labels")
        if not isinstance(names, str) or names not in producer or len(cached.columns) != len(producer) + 2:
            return False
        features = producer[names].astype(str).tolist()
        if (features != cached.columns[1:-1].tolist() or len(set(features)) != len(features)
                or x not in features or y not in features or cached.iloc[:, 0].tolist() != variables
                or not np.array_equal(cached.iloc[:, 1:-1].to_numpy(dtype=float), producer[variables].to_numpy(dtype=float).T)):
            return False
    table = axis + " Assignments" if options["Direction"] == "Rows and columns" else "Assignments"
    return _append_linked_recipe(producer, slot, table, SAVED_XY, {
        PRISM_TITLE: title[:160], APPEARANCE: style,
        CLUSTERED_SCATTER: {"x": x, "y": y, "labels": labels, "hierarchy": True},
    })


def _pca_overlay_note(options):
    return (" Restores the saved level and grouping as a data ellipse."
            if PCA_OVERLAY in options else "")


def _append_linked_recipe(producer, slot, table, method, options):
    recipes = producer.attrs["prism_recipes"]
    if len(recipes) >= 256:
        return False
    ids = producer.attrs.setdefault("prism_analysis_ids", {})
    parent = ids.setdefault(slot, str(uuid4()))
    consumer = len(recipes)
    ids[consumer] = str(uuid4())
    producer.attrs.setdefault("prism_analysis_sources", {})[consumer] = ResultSource(parent, table)
    recipes.append((method, options))
    return True


def _linked_plot_source(graph, uid, views, owners):
    selected = graph.get("inputDataSets")
    graph_id = graph.get("fenID")
    if (graph.get("uid") != uid or type(graph_id) is not int or not isinstance(selected, list)
            or len(selected) != 1 or not isinstance(selected[0], str)):
        return None
    dataset, = selected
    matches = views.get((dataset, graph_id), ())
    if len(matches) != 1 or len(owners.get(dataset, ())) != 1:
        return None
    (producer, slot, frame, plot), = matches
    if owners[dataset][0][0] is not frame:
        return None
    return producer, slot, plot


def _link_hierarchy_elbow(graph, uid, title, elbow_views, owners):
    source = _linked_plot_source(graph, uid, elbow_views, owners)
    if source is None:
        return False
    producer, slot, axis = source
    options = producer.attrs["prism_recipes"][slot][1]
    dual = options["Direction"] == "Rows and columns"
    if not dual and options["Graph output"] == "Elbow plot":
        return True
    return _append_linked_recipe(producer, slot, "Row Merges" if dual else "Merges", HIERARCHY_GRAPH, {
        "Graph output": "Elbow plot", TREE_AXIS: axis, PRISM_TITLE: title[:160],
        PRISM_NOTES: "Recalculates the elbow plot from the linked native hierarchy.",
    })


_KMEANS_PLOT_VIEWS = {
    "Elbow plot": (WSS_PLOT, "WSS", "y_single", ["WCSS"]),
    "Silhouette plot": (SILHOUETTE_PLOT, "Silhouette", "y_single", ["Silhouette score"]),
    "Gap plot": (GAP_PLOT, "Gap", "y_sd", ["Gap statistics [Mean]", "Gap statistics [SD]"]),
}


def _register_kmeans_plot(views, producer, options, name, frame, view):
    graph_id = view.get("graphId")
    if name not in _KMEANS_PLOT_VIEWS or type(graph_id) is not int:
        return
    flag, metric, mode, y_columns = _KMEANS_PLOT_VIEWS[name]
    x = frame.attrs["prism_x"]
    datasets = frame.attrs["prism_y"]
    columns = frame.attrs["prism_columns"]
    if (options.get(flag) is True and x and len(datasets) == 1
            and frame.attrs["prism_y_format"] == mode and columns[x] == ["Number of clusters"]
            and columns[datasets[0]] == y_columns):
        views.setdefault((datasets[0], graph_id), []).append((*producer, frame, metric))


def _link_kmeans_plot(graph, uid, title, views, owners):
    source = _linked_plot_source(graph, uid, views, owners)
    if source is None:
        return False
    producer, slot, metric = source
    return _append_linked_recipe(producer, slot, "Selection", MODEL_GRAPH, {
        METRIC: metric, PRISM_TITLE: title[:160],
    })


def _register_analysis_view(views, producer, name, frame, view, samples=None):
    graph_id = view.get("graphId")
    modes = {"Curve": ("y_single",), "XY data": ("y_single", "y_replicates"),
             "Survival proportions": ("y_single", "y_plus_minus")}.get(name, ())
    if (type(graph_id) is not int or not frame.attrs["prism_x"]
            or frame.attrs["prism_y_format"] not in modes):
        return
    for dataset in frame.attrs["prism_y"]:
        views.setdefault((dataset, graph_id), []).append((*producer, frame, name, samples))


def _matching_graph_members(graph, uid, views, owners):
    graph_id = graph.get("fenID")
    selected = graph.get("inputDataSets")
    if graph.get("uid") != uid or type(graph_id) is not int or not isinstance(selected, list) or not selected:
        return None
    members = []
    for dataset in selected:
        matches = views.get((dataset, graph_id), ())
        if len(matches) != 1 or len(owners.get(dataset, ())) != 1:
            return None
        member, = matches
        if owners[dataset][0][0] is not member[2]:
            return None
        members.append(member)
    source, slot, _, _, samples = members[0]
    if any(producer is not source or other != slot for producer, other, *_ in members):
        return None
    parts = {name: frame for _, _, frame, name, _ in members}
    datasets = [dataset for frame in parts.values() for dataset in frame.attrs["prism_y"]]
    if set(datasets) != set(selected) or len(datasets) != len(members):
        return None
    return source, slot, parts, samples


def _link_fit_plot(graph, uid, title, views, owners, points):
    match = _matching_graph_members(graph, uid, views, owners)
    if match is None:
        return False
    source, slot, parts, samples = match
    if set(parts) != {"Curve", "XY data"}:
        return False
    options = source.attrs["prism_recipes"][slot][1]
    spec = fit_graph_spec(source, options, points, samples)
    if spec is None:
        return False
    if not _append_linked_recipe(source, slot, FIT_GRAPH_POINTS, SAVED_XY, {
        PRISM_TITLE: title[:160], FIT_GRAPH: True, "X label": spec["x"], "Y label": spec["y"],
    }):
        return False
    options[FIT_GRAPH_SPEC] = spec
    return True


def _link_survival_plot(graph, uid, title, views, owners):
    match = _matching_graph_members(graph, uid, views, owners)
    if match is None:
        return False
    source, slot, parts, _ = match
    if set(parts) != {"Survival proportions"}:
        return False
    table = parts["Survival proportions"]
    options = source.attrs["prism_recipes"][slot][1]
    columns = table.attrs["prism_columns"]
    order = [columns[dataset][0] for dataset in graph["inputDataSets"]]
    if table.attrs["prism_y_format"] == "y_plus_minus":
        if options.get(UNCERTAINTY) != CI_BARS:
            return False
        order = [label.removesuffix(" [Center]") for label in order]
    if columns[table.attrs["prism_x"]] != [options["Time"]] or len(set(order)) != len(order):
        return False
    if not _append_linked_recipe(source, slot, SURVIVAL_SUMMARY, SAVED_XY, {
        PRISM_TITLE: title[:160], SURVIVAL_GRAPH: True, SURVIVAL_SERIES: order,
    }):
        return False
    options[SURVIVAL_GRAPH] = True
    return True


def _link_grouped_anova(sheet, parameters, label, grouped_views, view_sources):
    recipe = restore_recipe(sheet, parameters, view_sources)
    if recipe is None:
        return False
    source, method, options = recipe
    if source not in grouped_views:
        return False
    cached = view_sources[source]
    ids = cached.attrs["prism_y"]
    selected = _list(sheet.get("inputDataSets", []))
    if [item.get("uid") for item in selected if isinstance(item, dict)] != ids or len(selected) != len(ids):
        return False
    mapped = [name for uid in ids for name in cached.attrs["prism_columns"][uid]]
    if len(mapped) != len(cached.columns) - 1 or mapped != list(cached.columns[1:]):
        return False
    producer, slot = grouped_views[source]
    return _append_linked_recipe(producer, slot, EXTRACT_TABLE, method, {
        **options, PRISM_TITLE: label[:160],
        PRISM_NOTES: "Recalculates the ordinary two-factor ANOVA from the linked rearranged worksheet.",
    })


def restore_sheets(archive, names, sheets, sources, tables, cells):
    """Add non-executable snapshots and supported native analysis recipes."""
    from .prism_layout_edit import PRISM_PANEL_DATA
    from .prism_zip_column import ZIP_COLUMN, saved_aligned_column
    from .prism_zip_layout import ZIP_LAYOUT, saved_positioned_layout
    from .prism_zip_xy import ZIP_SPARSE_XY, saved_sparse_xy

    warnings = []
    restyled = set()
    owners = {}
    view_sources = dict(sources)
    deferred_pca = []
    clustered_views = {}
    deferred_anova = []
    grouped_views = {}
    elbow_views = {}
    hierarchy_scatters = {}
    kmeans_views = {}
    fit_views = {}
    survival_views = {}
    linked_xy = {}
    for source in sources.values():
        if source.attrs["prism_x"]:
            for uid in source.attrs["prism_y"]:
                owners.setdefault(uid, []).append((source, "points"))

    def add(name, frame):
        nonlocal cells
        if len(tables) >= 256 or cells + frame.size > MAX_CELLS:
            return False
        cells += frame.size
        _store_table(tables, name, frame)
        return True

    for entry in _list(sheets.get("analyses", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            path = f"analyses/{uid}/"
            sheet = _json_object(archive, path + "sheet.json")
            label = sheet.get("title") or uid
            if not isinstance(label, str):
                raise ValueError("Invalid analysis title.")
            params_path, results_path = path + "parameters.json", path + "results.json"
            params = _json_object(archive, params_path) if params_path in names else {}
            results = _json_object(archive, results_path) if results_path in names else None
            is_pca = sheet.get("analysisClass") == "PCA"
            is_grouped_anova = sheet.get("analysisClass") == "TWO_WAY_ANOVA"
            recipe = None if is_pca or is_grouped_anova else restore_recipe(sheet, params, sources, results)
            producer = None
            fit_samples = None
            if recipe:
                source, method, options = recipe
                restored = sources[source].attrs.setdefault("prism_recipes", [])
                if len(restored) < 256:
                    slot = len(restored)
                    options = {**options, PRISM_TITLE: label[:160]}
                    restored.append((method, options))
                    if method == "Hierarchical clustering":
                        _restore_hierarchy_views(archive, names, sheet, results, sources[source], slot, options, restyled)
                        producer = sources[source], slot
                    if method in {SELECTION, EXTRACT_REARRANGE}:
                        producer = sources[source], len(restored) - 1
                    if method == "Kaplan–Meier survival" and len(options["Event columns"]) == 1:
                        producer = sources[source], slot
                    if (method == "Nonlinear regression" and len(options["Y columns"]) == 1
                            and len(options["Grouping variables"]) <= 1):
                        fit_samples = saved_samples(params)
                        if fit_samples is not None:
                            producer = sources[source], slot
            elif is_pca:
                deferred_pca.append((sheet, params, label))
            elif is_grouped_anova:
                deferred_anova.append((sheet, params, label))
            else:
                warnings.append(f"Recalculation unavailable for {label}.")
            for record in _list(sheet.get("resultSheets", [])):
                if not isinstance(record, dict):
                    continue
                saved = restore_view(archive, names, path, record, label, sheet, add, owners, view_sources,
                                     MAX_CELLS - cells)
                if producer is not None and saved is not None:
                    view_uid, name, frame, view = saved
                    if view_sources[view_uid] is frame:
                        if method == SELECTION:
                            if name == "Clustered data":
                                clustered_views[view_uid] = producer
                            else:
                                _register_kmeans_plot(kmeans_views, producer, options, name, frame, view)
                        if fit_samples is not None:
                            _register_analysis_view(fit_views, producer, name, frame, view, fit_samples)
                        if method == "Kaplan–Meier survival":
                            _register_analysis_view(survival_views, producer, name, frame, view)
                        if (method == EXTRACT_REARRANGE and name == "Results"
                                and frame.attrs.get("prism_snapshot_source_format") == "grouped"):
                            grouped_views[view_uid] = producer
                        if method == "Hierarchical clustering" and isinstance(results, dict):
                            axis = {"Clustered data (rows)": "Row", "Clustered data (columns)": "Column"}.get(name)
                            graph_id = view.get("graphId")
                            if (axis is not None and type(graph_id) is int and options.get(f"{axis} cut") == "Count"
                                    and options["Direction"] in {f"{axis}s", "Rows and columns"}):
                                content = results.get("content")
                                result_axis = content.get(axis.lower() + "s") if isinstance(content, dict) else None
                                if isinstance(result_axis, dict):
                                    hierarchy_scatters[view_uid] = (producer, axis, result_axis.get("clusters"), graph_id)
                        if method == "Hierarchical clustering" and options.get("Elbow data"):
                            axis = {"Elbow plot (rows)": "Rows", "Elbow plot (columns)": "Columns"}.get(name)
                            datasets = frame.attrs["prism_y"]
                            graph_id = view.get("graphId")
                            if (axis is not None and options["Direction"] in {axis, "Rows and columns"}
                                    and frame.attrs["prism_x"] and len(datasets) == 1 and type(graph_id) is int):
                                elbow_views.setdefault((datasets[0], graph_id), []).append((*producer, frame, axis))
        except (KeyError, TypeError, ValueError, csv.Error):
            warnings.append(f"Some saved analysis content could not be read for {label}.")
    # The saved input may be a multivariable table emitted by a later analysis in the document.
    for sheet, params, label in deferred_pca:
        recipe = restore_recipe(sheet, params, view_sources)
        if recipe is None:
            warnings.append(f"Recalculation unavailable for {label}.")
            continue
        source, method, options = recipe
        options = {**options, PRISM_TITLE: label[:160]}
        directions = saved_component_directions(archive, sheet, view_sources, options["Variables"])
        if directions:
            options[SAVED_DIRECTIONS] = directions
        overlay = saved_score_overlay(archive, sheet, view_sources[source], view_sources, options)
        if overlay:
            options.update(overlay[1])
            options[PRISM_NOTES] += _pca_overlay_note(options)
        if source in clustered_views and _link_clustered_pca(
                *clustered_views[source], view_sources[source], method, options):
            if overlay:
                restyled.add(overlay[0])
            continue
        restored = view_sources[source].attrs.setdefault("prism_recipes", [])
        if len(restored) < 256:
            restored.append((method, options))
            if overlay:
                restyled.add(overlay[0])
    for sheet, params, label in deferred_anova:
        try:
            if _link_grouped_anova(sheet, params, label, grouped_views, view_sources):
                continue
        except (KeyError, TypeError, ValueError):
            pass
        warnings.append(f"Recalculation unavailable for {label}.")
    for entry in _list(sheets.get("graphs", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            if uid in restyled:
                continue
            graph = _json_object(archive, f"graphs/{uid}/sheet.json")
            label = graph.get("title") or uid
            if not isinstance(label, str):
                raise ValueError("Invalid graph title.")
            if _link_hierarchy_elbow(graph, uid, label, elbow_views, owners):
                continue
            if _link_kmeans_plot(graph, uid, label, kmeans_views, owners):
                continue
            points = _saved_xy({**graph, "title": label[:160]}, owners, MAX_CELLS - cells)
            if points is not None and _link_fit_plot(graph, uid, label, fit_views, owners, points):
                continue
            if points is not None and _link_survival_plot(graph, uid, label, survival_views, owners):
                continue
            if points is None and graph.get("uid") == uid:
                linked = saved_sparse_xy(archive, graph, uid, owners, sources)
                if linked is not None:
                    source, style = linked
                    recipes = source.attrs.setdefault("prism_recipes", [])
                    if len(recipes) < 256:
                        options = {
                            PRISM_TITLE: label[:160], ZIP_SPARSE_XY: style,
                            PRISM_NOTES: "Linked XY data, saved axis limits and series colors. "
                                         "Trama uses native point markers and graph formatting.",
                        }
                        recipes.append((SAVED_XY, options))
                        linked_xy[uid] = (source, graph["fenID"], options)
                        continue
                column = saved_aligned_column(archive, graph, uid, sources)
                if column is not None:
                    source, style = column
                    recipes = source.attrs.setdefault("prism_recipes", [])
                    if len(recipes) < 256:
                        recipes.append((SAVED_XY, {
                            PRISM_TITLE: label[:160], ZIP_COLUMN: style,
                            PRISM_NOTES: "Linked column data with saved axis settings and point colors.",
                        }))
                        continue
                scatter = saved_scatter(graph, view_sources, MAX_CELLS - cells)
                if scatter is not None:
                    points, style, columns = scatter
                    source = graph["graph"]["dataSheet"]
                    if source in clustered_views and _link_clustered_scatter(
                            *clustered_views[source], view_sources[source], columns, style, label):
                        continue
                    if source in hierarchy_scatters and _link_hierarchy_scatter(
                            graph, hierarchy_scatters[source], view_sources[source], columns, style, label):
                        continue
                    points.attrs["table_format"] = "Prism graph snapshot"
                    points.attrs["prism_recipes"] = [(SAVED_XY, {
                        PRISM_TITLE: label[:160], APPEARANCE: style,
                        PRISM_NOTES: "Editable saved scatter coordinates, category colors and axis limits. "
                                     "Trama draws the rest of the graph with native formatting.",
                    })]
            if points is None or not add(f"Prism graph · {label}", points):
                warnings.append(f"Graph unavailable for {label}.")
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Graph unavailable for {label}.")
    for entry in _list(sheets.get("layouts", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            sheet = _json_object(archive, f"layouts/{uid}/sheet.json")
            label = str(sheet.get("title") or uid)[:160]
            linked = saved_positioned_layout(archive, uid, sheet, linked_xy)
            if linked is not None:
                source, layout, panel_recipes = linked
                recipes = source.attrs["prism_recipes"]
                if len(recipes) < 256:
                    options = {
                        PRISM_TITLE: label, ZIP_LAYOUT: layout,
                        PRISM_NOTES: "Linked data and saved page positions. "
                                     "Trama draws the panels and connector lines with native formatting.",
                    }
                    if panel_recipes:
                        options[PRISM_PANEL_DATA] = {
                            str(number): recipe.setdefault(PRISM_GRAPH_LINK, uuid4().hex)
                            for number, recipe in enumerate(panel_recipes, 1)
                        }
                    recipes.append((SAVED_BINARY_LAYOUT, options))
                    continue
        except (KeyError, TypeError, ValueError):
            pass
        warnings.append(f"Layout unavailable for {label}.")
    if warnings:
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            "Prism import · " + " ".join(warnings[:4]) +
            (f" ({len(warnings) - 4} more notices.)" if len(warnings) > 4 else ""))


def restore_binary_views(data, sources, tables, cells, fonts, document_title):
    from .prism_binary_editable import read_editable_graphs
    from .prism_binary_graphs import read_binary_graphs
    from .prism_binary_layouts import read_binary_layouts
    from .prism_binary_results import restore_binary_results
    from .prism_emf_edit import CURVE, LIMIT_SOURCE, POINTS
    from .prism_layout_edit import PRISM_EDITABLE_PANELS
    from .prism_pdf_stacks import STACK_KIND

    source_names = set(tables)
    cells = restore_binary_results(data, sources, tables, cells, fonts)
    for title, frame in tables.items():
        if title not in source_names:
            saved = frame.attrs["prism_binary_result"]
            sheet = saved["sheet_title"].partition(":")[2].strip() or "Saved results"
            frame.attrs["prism_recipes"] = [(SAVED_BINARY_RESULT, {
                PRISM_TITLE: title.removeprefix("Prism result · ")[:240],
                PRISM_NOTES: "Original saved Prism result. Use Result as Data to make an editable copy.",
                PRISM_RESULT_SHEET: sheet,
                "Prism result provenance": saved,
            })]
    try:
        graphs, unavailable = read_binary_graphs(data)
    except ValueError as error:
        graphs, unavailable = [], [str(error)]
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        import_id = uuid4().hex
        graph_links = {graph["id"]: f'{import_id}:{graph["id"]}' for graph in graphs}
        views = [(SAVED_BINARY_GRAPH, {
            PRISM_TITLE: graph["title"],
            PRISM_NOTES: ("Original graph drawing saved by Prism. Export as "
                          f'{graph["preview"]["format"].upper()} to preserve the vector image.'),
            PRISM_PREVIEW: graph["preview"],
            PRISM_GRAPH_LINK: graph_links[graph["id"]],
        }) for graph in graphs]
        _store_collection(tables, document_title, "graphs", BINARY_GRAPH_COLLECTION, views)
        cells += 1
    elif graphs:
        graphs = []
        unavailable += ["The project has reached its table or cell limit."]
    if tables and unavailable:
        count = len(unavailable)
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            f"Unavailable Prism graph previews ({count}) · " + ", ".join(unavailable[:4]))
    cells, layouts = _restore_binary_layouts(data, document_title, graphs, tables, cells, read_binary_layouts)
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        result_frames = {frame.attrs["prism_binary_result"]["sheet_id"]: frame for frame in tables.values()
                         if "prism_binary_result" in frame.attrs}
        try:
            cached_curves = {panel["graph_id"] for _, options in layouts
                             for panel in options.get(PRISM_EDITABLE_PANELS, ())}
            editable = read_editable_graphs(data, sources, result_frames, MAX_CELLS - cells,
                                            cached_curves=cached_curves)
        except ValueError:
            editable = {}
        linked = {}
        for graph in graphs:
            uid = graph["id"]
            if uid not in editable:
                continue
            frame, style = editable[uid]
            kind = style.get("kind")
            binding = style.get(LIMIT_SOURCE)
            if binding is None and (len(tables) >= 256 or cells + frame.size > MAX_CELLS):
                continue
            if kind == STACK_KIND:
                if graph["preview"]["format"] != "pdf":
                    continue
                table_format = EDITABLE_PRISM_STACKS
                notes = ("Edit the percentages in the graph data sheet. The editable view retains the saved drawing. "
                         "The original view provides the original vector PDF.")
            elif kind == "columns":
                table_format = EDITABLE_PRISM_COLUMNS
                notes = "Edit means and displayed errors in the graph data sheet. Saved formatting and annotations are retained."
            elif kind in (CURVE, POINTS):
                if graph["preview"]["format"] != "emf":
                    continue
                table_format = EDITABLE_PRISM_EMF
                notes = ("Edit coordinates and displayed endpoints in the original worksheet." if binding is not None else
                         "Edit coordinates and any displayed error distances in the graph data sheet.")
                notes += " The editable view retains the saved drawing. The original graph remains available."
                if style.get("fixed_overlays"):
                    notes += " The overlaid observations retain their saved positions."
                if style.get("cached_curve"):
                    notes += " The starting coordinates are approximate values recovered from the saved curve."
                if style.get("fixed_band"):
                    notes += " The original shaded band retains its saved values."
            else:
                table_format = EDITABLE_PRISM_XY
                notes = "Editable XY graph with recovered Prism formatting. Original drawing remains available."
            if binding is not None:
                frame = sources[binding["sheet"]]
            else:
                frame.attrs["table_format"] = table_format
            frame.attrs.setdefault("prism_recipes", []).append((SAVED_EDITABLE_GRAPH, {
                PRISM_TITLE: graph["title"] + " · Editable",
                PRISM_NOTES: notes,
                PRISM_GRAPH_STYLE: style,
                PRISM_GRAPH_LINK: graph_links[uid],
                **({PRISM_PREVIEW: graph["preview"]} if table_format != EDITABLE_PRISM_XY else {}),
            }))
            if binding is None:
                _store_table(tables, f'Prism graph data · {graph["title"]}', frame)
                cells += frame.size
            if table_format in (EDITABLE_PRISM_COLUMNS, EDITABLE_PRISM_EMF):
                linked[uid] = (frame, style)
        _link_layout_panel_data(layouts, graph_links, linked)


def _store_collection(tables, title, label, table_format, views):
    carrier = pd.DataFrame({"Prism project": [title]})
    carrier.attrs.update(table_format=table_format, prism_recipes=views)
    _store_table(tables, f"Prism {label} · {title}", carrier)


def _restore_binary_layouts(data, title, graphs, tables, cells, reader):
    from .prism_layout_edit import PRISM_EDITABLE_PANELS, editable_panels

    try:
        layouts, unavailable = reader(data)
    except ValueError as error:
        layouts, unavailable = [], [str(error)]
    graph_previews = {graph["id"]: graph["preview"] for graph in graphs}
    graph_titles = {graph["id"]: graph["title"] for graph in graphs}
    views, panel_bytes = [], 0
    for layout in layouts:
        options = {PRISM_TITLE: layout["title"]}
        if layout.get("preview"):
            options[PRISM_PREVIEW] = layout["preview"]
            options[PRISM_NOTES] = "Original page saved by Prism. Export as EMF to retain the vector drawing."
            panels = editable_panels(layout["preview"], layout["placements"], graph_titles,
                                     placements_complete=layout["placements_complete"])
            if panels:
                options[PRISM_EDITABLE_PANELS] = panels
        elif layout.get("placements_complete") and 1 <= len(layout.get("placements", ())) <= 24:
            panels = []
            for placement in layout["placements"]:
                graph_id = placement["graph_id"]
                if graph_id is not None and graph_id not in graph_previews:
                    break
                panels.append({"bounds": placement["bounds"], "preview": graph_previews.get(graph_id)})
            if len(panels) != len(layout["placements"]) or not any(panel["preview"] for panel in panels):
                unavailable.append(layout["title"])
                continue
            size = sum(len(panel["preview"]["data"]) for panel in panels if panel["preview"])
            if panel_bytes + size > MAX_LAYOUT_PANEL_DATA:
                unavailable.append(layout["title"])
                continue
            panel_bytes += size
            options[PRISM_LAYOUT_PANELS] = panels
            options[PRISM_NOTES] = "Page reconstructed from the original graph positions and saved drawings."
        else:
            unavailable.append(layout["title"])
            continue
        views.append((SAVED_BINARY_LAYOUT, options))
    if views and len(tables) < 256 and cells < MAX_CELLS:
        _store_collection(tables, title, "layouts", BINARY_LAYOUT_COLLECTION, views)
        cells += 1
    elif views:
        unavailable.append("The project has reached its table or cell limit.")
        views = []
    if tables and unavailable:
        titles = list(dict.fromkeys(unavailable))
        next(iter(tables.values())).attrs.setdefault("import_warnings", []).append(
            f"Unavailable Prism layouts ({len(titles)}) · " + ", ".join(titles[:4]))
    return cells, views


def _link_layout_panel_data(layouts, graph_links, linked):
    from .prism_layout_edit import (PRISM_EDITABLE_PANELS, PRISM_PANEL_DATA, edit_panel_artwork,
                                    layout_panel_artwork)

    for _, options in layouts:
        panels = options.get(PRISM_EDITABLE_PANELS)
        if not panels or not any(panel["graph_id"] in linked for panel in panels):
            continue
        artwork = layout_panel_artwork(options[PRISM_PREVIEW], panels)
        links = {}
        for panel in panels:
            panel_id, uid = panel["id"], panel["graph_id"]
            if panel_id not in artwork or uid not in linked:
                continue
            frame, style = linked[uid]
            try:
                edit_panel_artwork(frame, style, artwork[panel_id])
            except ValueError:
                continue
            links[panel_id] = graph_links[uid]
        if links:
            options[PRISM_PANEL_DATA] = links


def restore_view(archive, names, path, record, analysis_title, analysis, add, owners, view_sources, remaining_cells):
    view_id = _identifier(record.get("uid"))
    view_path = f"{path}result_sheets/{view_id}.json"
    if view_path not in names:
        return
    view = _json_object(archive, view_path)
    if view.get("isInternal") or not view.get("dataSheet"):
        return
    uid = _identifier(view["dataSheet"])
    sheet = _json_object(archive, f"data/sheets/{uid}/sheet.json")
    frame = _zip_table(archive, names, sheet["table"], remaining_cells, result=True)
    if frame is None or frame.empty:
        return
    name = view.get("name") or record.get("title") or view_id
    if not view.get("isVisible") and not frame.attrs["prism_x"]:
        return
    source_format = frame.attrs.get("table_format")
    if source_format in {"multivariable", "grouped"}:
        frame.attrs["prism_snapshot_source_format"] = source_format
    frame.attrs["table_format"] = "Prism result snapshot"
    if not add(f"Prism result · {analysis_title} · {name}", frame):
        return
    view_sources.setdefault(uid, frame)
    if frame.attrs["prism_x"]:
        geometry = "line" if name == "Curve" else "points"
        if analysis.get("analysisClass") == "SURVIVAL" and name == "Survival proportions":
            geometry = "step"
        for dataset in frame.attrs["prism_y"]:
            owners.setdefault(dataset, []).append((frame, geometry))
    return uid, name, frame, view
