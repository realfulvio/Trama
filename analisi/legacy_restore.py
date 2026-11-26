"""Restore verified native recipes and materialize saved project views."""
import csv
from math import remainder
import re
from uuid import uuid4

import numpy as np
import pandas as pd

from .plot_function import OBSERVATION_COLUMNS, PLOT_FUNCTION
from .analysis_chain import ResultSource
from . import anova_comparison_plot, anova_diagnostics, anova_grouped_plot, regression_range
from .category_graphs import COLUMN_GRAPH, GEOMETRIC_CENTER, GROUPED_GRAPH, MAX_CATEGORIES, MAX_PLOT_CELLS, MAX_POINTS, POINTS
from .data import EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_EMF, EDITABLE_LEGACY_STACKS, EDITABLE_LEGACY_XY, MAX_CELLS
from .extract_rearrange import EXTRACT_REARRANGE, EXTRACT_TABLE, OUTPUT
from .hierarchical_workbench import HIERARCHY_GRAPH, TREE_AXIS
from .kmeans_archive import ARCHIVE as KMEANS_ARCHIVE
from .kmeans_options import GAP_PLOT, SELECTION, SILHOUETTE_PLOT, WSS_PLOT
from .kmeans_reports import ASSIGNMENTS_TABLE, METRIC, MODEL_GRAPH, assignment_column
from .paired_graphs import shows_paired_estimation
from .pca_graphs import COLOR_GROUPS, SAVED_DIRECTIONS, SAVED_VIEWPORT
from .pca_overlays import KIND as PCA_OVERLAY, SAVED_APPEARANCE as PCA_OVERLAY_APPEARANCE
from .pca_parallel_archive import ARCHIVE as PCA_PARALLEL_ARCHIVE
from .legacy_import import _identifier, _json_object, _store_table, _zip_table
from .legacy_fit_graph import FIT_GRAPH, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC, FIT_GRAPH_TICKS, fit_graph_spec, saved_samples
from .nonlinear_calibration import PADE_DRAWING
from .stats import STARTING_COEFFICIENTS_BY_SERIES
from .legacy_pca_view import saved_component_directions, saved_parallel_reference, saved_score_overlay
from .legacy_recipes import restore_log_dose_fit, restore_recipe, saved_anova_diagnostics, saved_anova_primary_factor
from .legacy_mv_scatter import APPEARANCE, CLUSTERED_SCATTER, saved_scatter
from .replicate_fit import MERGE_REPLICATES
from .survival_plot import CI_BARS, SURVIVAL_GRAPH, SURVIVAL_SERIES, SURVIVAL_SUMMARY, UNCERTAINTY

SAVED_XY = "Imported XY graph"
SAVED_AXES = "Imported empty axes"
SAVED_BINARY_GRAPH = "Imported archived graph"
SAVED_BINARY_LAYOUT = "Imported archived layout"
SAVED_EDITABLE_GRAPH = "Imported editable graph"
SAVED_BINARY_RESULT = "Imported saved results"
BINARY_GRAPH_COLLECTION = "Imported graph collection"
BINARY_LAYOUT_COLLECTION = "Imported layout collection"
LEGACY_GRAPH_LINK = "Legacy original graph link"
LEGACY_GRAPH_STYLE = "Legacy original graph style"
LEGACY_LAYOUT_PANELS = "Legacy layout panels"
LEGACY_LAYOUT_GRID = "Legacy layout grid"
MAX_LAYOUT_PANEL_DATA = 2 * 1024 * 1024
LEGACY_PREVIEW = "Legacy graph preview"
LEGACY_RESULT_SHEET = "Legacy result sheet"
LEGACY_TITLE = "Legacy sheet title"
LEGACY_NOTES = "Legacy import notes"


def initial_sheet_reference(initial_sheet, runs, run_view):
    """Resolve the imported table and recipe slot to the desktop navigator reference."""
    if not initial_sheet:
        return None
    kind, key = initial_sheet[0]
    if kind != "run":
        return kind, key
    for index, run in enumerate(runs):
        if (run.title, run.slot) == key:
            return run_view(run.method), index
    return None


def linked_curve_view(run):
    return bool(run.options.get(LEGACY_GRAPH_LINK)) and (
        run.method == PLOT_FUNCTION or (run.method == SAVED_XY and run.options.get(FIT_GRAPH) is True)
        or (run.method == "Interpolate a standard curve" and PADE_DRAWING in run.options)
        or (run.method == "Global nonlinear regression" and FIT_GRAPH_SPEC in run.options)
        or (run.method == "Nonlinear regression" and STARTING_COEFFICIENTS_BY_SERIES in run.options
            and FIT_GRAPH_SPEC in run.options))


def paired_graph_index(run, runs):
    """Find the unique counterpart of an imported graph by its saved identity."""
    link = run.options.get(LEGACY_GRAPH_LINK)
    if not isinstance(link, str) or not link:
        return None
    matches = []
    for index, other in enumerate(runs):
        if other.options.get(LEGACY_GRAPH_LINK) != link:
            continue
        if run.method == SAVED_BINARY_GRAPH:
            if (other.method == SAVED_EDITABLE_GRAPH or linked_curve_view(other)
                    or (other.method == SAVED_XY and SAVED_AXES in other.options)):
                matches.append(index)
        elif other.method == SAVED_BINARY_GRAPH:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def panel_source_style(method, options):
    """Identify a saved graph that can be recalculated from live worksheet data."""
    if method == SAVED_XY:
        from .legacy_xml_binding_layout import XML_BINDING_XY
        from .legacy_zip_xy import ZIP_SPARSE_XY

        style = options.get(XML_BINDING_XY, options.get(ZIP_SPARSE_XY))
    elif method == SAVED_EDITABLE_GRAPH:
        style = options.get(LEGACY_GRAPH_STYLE)
    else:
        return None
    return style if isinstance(style, dict) else None


def resolve_layout_panel_graphs(run, runs, tables):
    from .legacy_layout_edit import LEGACY_PANEL_DATA
    from .legacy_xml_binding_layout import XML_BINDING_XY
    from .legacy_zip_layout import ZIP_LAYOUT

    links = run.options.get(LEGACY_PANEL_DATA)
    companion = run.method == SAVED_XY and XML_BINDING_XY in run.options
    if (run.method != SAVED_BINARY_LAYOUT and not companion) or not isinstance(links, dict):
        return {}
    expected = SAVED_XY if companion or ZIP_LAYOUT in run.options else SAVED_EDITABLE_GRAPH
    graphs = {}
    for item in runs:
        link = item.options.get(LEGACY_GRAPH_LINK)
        if (item.method == expected and item.title in tables and isinstance(link, str)
                and panel_source_style(item.method, item.options) is not None):
            graphs[link] = None if link in graphs else item
    return {panel: graphs[link]
            for panel, link in links.items() if isinstance(link, str) and graphs.get(link) is not None}


def linked_panel_readers(title, runs, tables):
    """Runs owned by a different table which read this worksheet through panel links."""
    from .legacy_layout_edit import LEGACY_PANEL_DATA

    return [run for run in runs if run.title != title and LEGACY_PANEL_DATA in run.options
            and any(graph.title == title for graph in resolve_layout_panel_graphs(run, runs, tables).values())]


def layout_panel_sources(run, graphs):
    """List the worksheet behind each editable panel and any linked companion data."""
    from .legacy_layout_edit import LEGACY_EDITABLE_PANELS, LEGACY_PANEL_DATA
    from .legacy_zip_layout import ZIP_LAYOUT

    layout = run.options.get(ZIP_LAYOUT)
    positioned = layout.get("panels") if isinstance(layout, dict) else None
    if isinstance(positioned, list) and run.result is not None:
        choices = []
        linked = LEGACY_PANEL_DATA in run.options
        for number, panel in enumerate(positioned, 1):
            if not isinstance(panel, dict) or not isinstance(caption := panel.get("title"), str):
                continue
            graph = graphs.get(str(number))
            if graph is not None or not linked:
                choices.append((f"{number} · {caption}", graph.title if graph is not None else run.title))
            binding = panel.get("binding_panel")
            companion = graphs.get(binding) if isinstance(binding, str) else None
            if companion is not None and (graph is None or companion.title != graph.title):
                choices.append((f"{number} · {companion.title}", companion.title))
        return choices

    panels = run.options.get(LEGACY_EDITABLE_PANELS)
    if not isinstance(panels, list):
        panels = []
    captions = {panel["id"]: panel.get("title") for panel in panels
                if isinstance(panel, dict) and isinstance(panel.get("id"), str)}
    return [(f"{panel} · {captions.get(panel) or graph.name}", graph.title) for panel, graph in graphs.items()]


def _list(value):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("Unsupported legacy sheet list.")
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
    styles = producer.attrs.setdefault("legacy_graph_styles", {}) if views else {}
    if len(primary) == 1:
        uid = primary[0]
        _, view, style = views.pop(uid)
        if "Dendrogram orientation" in view:
            options["Dendrogram orientation"] = view["Dendrogram orientation"]
        if style:
            styles[slot] = style
        options[LEGACY_NOTES] = ("Recalculates the supported hierarchy and restores selected saved graph settings. "
                                "Other settings use Trama formatting.")
        restyled.add(uid)
    table = "Merges" if len(axes) == 1 else "Row Merges"
    for uid, (title, view, style) in views.items():
        if uid in restyled:
            continue
        child = len(producer.attrs["legacy_recipes"])
        view[LEGACY_TITLE] = (title or view["Graph output"])[:160]
        view[LEGACY_NOTES] = ("Recalculates this view from the linked native hierarchy. "
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
        mapping = frame.attrs["legacy_columns"]
        xcols = mapping.get(frame.attrs["legacy_x"], [])
        columns = mapping[uid]
        if len(xcols) != 1 or not columns:
            return None
        mode = frame.attrs["legacy_y_format"]
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
    points.attrs["table_format"] = "Imported graph snapshot"
    note = ("Saved XY coordinates. Replicates are shown individually with Trama formatting."
            if has_replicates else "Saved XY coordinates. The plot uses Trama formatting.")
    points.attrs["legacy_recipes"] = [(SAVED_XY, {
        LEGACY_TITLE: graph["title"], "X label": next(iter(labels)) if len(labels) == 1 else "X",
        LEGACY_NOTES: note,
    })]
    return points


def _clustered_columns(producer, slot, cached):
    """Match the saved assignment columns to the requested native models."""
    recipes = producer.attrs["legacy_recipes"]
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
               LEGACY_NOTES: ("Uses the live K-means assignments as input. Trama recalculates standardized PCA "
                             "and the saved color grouping."
                             + _pca_parallel_note(options)
                             + _pca_overlay_note(options))}
    if SAVED_DIRECTIONS in options:
        options[SAVED_DIRECTIONS] = {name: {mapping[column]: value for column, value in reference.items()}
                                     for name, reference in options[SAVED_DIRECTIONS].items()}
    if PCA_OVERLAY_APPEARANCE in options:
        options[PCA_OVERLAY_APPEARANCE] = {**options[PCA_OVERLAY_APPEARANCE], "column": mapping[color]}
    return _append_linked_recipe(producer, slot, ASSIGNMENTS_TABLE, method, options)


def _link_clustered_scatter(producer, slot, cached, columns, style, title):
    x, y, category = columns
    fitted = producer.attrs["legacy_recipes"][slot][1].get(KMEANS_ARCHIVE)
    if fitted is None or x not in producer or y not in producer or category in producer:
        return False
    mapping = _clustered_columns(producer, slot, cached)
    if mapping is None:
        return False
    position = cached.columns.get_loc(category) - len(producer.columns)
    groups = fitted["models"][position]["groups"]
    pairs = pd.DataFrame({"id": groups, "label": cached[category].astype(str)}).drop_duplicates()
    count = producer.attrs["legacy_recipes"][slot][1]["Minimum k"] + position
    if len(pairs) != count or len(set(pairs["label"])) != count or set(pairs["label"]) != style["palette"].keys():
        return False
    labels = pairs.sort_values("id")["label"].tolist()
    return _append_linked_recipe(producer, slot, ASSIGNMENTS_TABLE, SAVED_XY, {
        LEGACY_TITLE: title[:160], APPEARANCE: style,
        CLUSTERED_SCATTER: {"x": x, "y": y, "group": mapping[category], "labels": labels},
    })


def _link_hierarchy_scatter(graph, saved, cached, columns, style, title):
    (producer, slot), axis, groups, graph_id = saved
    if graph.get("fenID") != graph_id or type(graph.get("fenID")) is not int:
        return False
    x, y, category = columns
    options = producer.attrs["legacy_recipes"][slot][1]
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
        LEGACY_TITLE: title[:160], APPEARANCE: style,
        CLUSTERED_SCATTER: {"x": x, "y": y, "labels": labels, "hierarchy": True},
    })


def _pca_parallel_note(options):
    if PCA_PARALLEL_ARCHIVE in options:
        return (" The saved parallel reference is reused for matching data and settings. "
                "Other inputs use samples generated from the saved seed.")
    return " Trama generates its own parallel samples from the saved seed."


def _pca_overlay_note(options):
    note = " Restores the saved level and grouping as a data ellipse." if PCA_OVERLAY in options else ""
    if SAVED_VIEWPORT in options:
        note += " The saved score axes and zero lines apply when the original components are selected."
    return note


def _append_linked_recipe(producer, slot, table, method, options):
    recipes = producer.attrs["legacy_recipes"]
    if len(recipes) >= 256:
        return False
    ids = producer.attrs.setdefault("legacy_analysis_ids", {})
    parent = ids.setdefault(slot, str(uuid4()))
    consumer = len(recipes)
    ids[consumer] = str(uuid4())
    producer.attrs.setdefault("legacy_analysis_sources", {})[consumer] = ResultSource(parent, table)
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
    options = producer.attrs["legacy_recipes"][slot][1]
    dual = options["Direction"] == "Rows and columns"
    if not dual and options["Graph output"] == "Elbow plot":
        return True
    return _append_linked_recipe(producer, slot, "Row Merges" if dual else "Merges", HIERARCHY_GRAPH, {
        "Graph output": "Elbow plot", TREE_AXIS: axis, LEGACY_TITLE: title[:160],
        LEGACY_NOTES: "Recalculates the elbow plot from the linked native hierarchy.",
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
    x = frame.attrs["legacy_x"]
    datasets = frame.attrs["legacy_y"]
    columns = frame.attrs["legacy_columns"]
    if (options.get(flag) is True and x and len(datasets) == 1
            and frame.attrs["legacy_y_format"] == mode and columns[x] == ["Number of clusters"]
            and columns[datasets[0]] == y_columns):
        views.setdefault((datasets[0], graph_id), []).append((*producer, frame, metric))


def _link_kmeans_plot(graph, uid, title, views, owners):
    source = _linked_plot_source(graph, uid, views, owners)
    if source is None:
        return False
    producer, slot, metric = source
    return _append_linked_recipe(producer, slot, "Selection", MODEL_GRAPH, {
        METRIC: metric, LEGACY_TITLE: title[:160],
    })


def _register_analysis_view(views, producer, name, frame, view, samples=None):
    graph_id = view.get("graphId")
    modes = {"Curve": ("y_single",), "XY data": ("y_single", "y_replicates"),
             "Survival proportions": ("y_single", "y_plus_minus")}.get(name, ())
    if (type(graph_id) is not int or not frame.attrs["legacy_x"]
            or frame.attrs["legacy_y_format"] not in modes):
        return
    for dataset in frame.attrs["legacy_y"]:
        views.setdefault((dataset, graph_id), []).append((*producer, frame, name, samples))


def _saved_analysis_graph_table(archive, path, record, name):
    try:
        view_id = _identifier(record["uid"])
        view = _json_object(archive, f"{path}result_sheets/{view_id}.json")
        if view.get("name") != name or type(view.get("graphId")) is not int:
            return None
        sheet = _identifier(view["dataSheet"])
        return view["graphId"], _json_object(archive, f"data/sheets/{sheet}/sheet.json")["table"]
    except (KeyError, TypeError, ValueError):
        return None


def _paired_estimation_members(archive, path, record):
    """Resolve the exact saved graph belonging to the restored paired estimate."""
    data = _saved_analysis_graph_table(archive, path, record, "Estimation Plot")
    if data is None:
        return None
    graph_id, table = data
    try:
        if not isinstance(table, dict) or table.get("format") != "column" or table.get("dataFormat") != "y_single":
            return None
        first, second, difference = (_identifier(dataset) for dataset in table["dataSets"])
        if len({first, second, difference}) == 3:
            return graph_id, (first, second, difference)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _anova_interval_members(archive, path, record):
    data = _saved_analysis_graph_table(archive, path, record, "Mul. comp. CI plot")
    if data is None:
        return None
    graph_id, table = data
    if not isinstance(table, dict) or table.get("dataFormat") != "y_high_low":
        return None
    datasets = table.get("dataSets")
    if isinstance(datasets, list) and len(datasets) == 1:
        try:
            return graph_id, (_identifier(datasets[0]),)
        except ValueError:
            pass
    return None


def _saved_grouped_members(archive, path, record, name):
    data = _saved_analysis_graph_table(archive, path, record, name)
    if data is None:
        return None
    graph_id, table = data
    if not isinstance(table, dict) or table.get("format") != "grouped" or table.get("dataFormat") != "y_replicates":
        return None
    datasets = table.get("dataSets")
    if not isinstance(datasets, list) or not 2 <= len(datasets) <= 128:
        return None
    try:
        members = tuple(_identifier(dataset) for dataset in datasets)
    except ValueError:
        return None
    return (graph_id, members) if len(set(members)) == len(members) else None


def _link_extracted_grouped_plot(producer, slot, frame, members, label):
    groups = [frame.attrs["legacy_columns"].get(uid, []) for uid in members]
    columns = [name for group in groups for name in group]
    if (frame.attrs["legacy_y"] != list(members) or not all(groups) or columns != list(frame.columns[1:])
            or len(frame) > MAX_CATEGORIES or len(frame) * len(groups) > MAX_PLOT_CELLS
            or len(frame) * len(columns) > MAX_POINTS):
        return False
    return _append_linked_recipe(producer, slot, EXTRACT_TABLE, GROUPED_GRAPH, {
        "Variables": columns, "Row titles": "Row title", "Graph style": POINTS,
        LEGACY_TITLE: label[:160], LEGACY_NOTES: "Linked raw observations drawn with native grouped graph formatting.",
    })


def _saved_anova_interval_requested(method, options, parameters):
    if method != "Multifactor ANOVA" or not options.get("Cell comparison factors"):
        return False
    try:
        return parameters["content"]["postTests"]["pairwiseTests"]["graph"]["confidenceIntervals"] is True
    except (KeyError, TypeError):
        return False


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
    datasets = [dataset for frame in parts.values() for dataset in frame.attrs["legacy_y"]]
    if set(datasets) != set(selected) or len(datasets) != len(members):
        return None
    return source, slot, parts, samples


def _link_fit_plot(archive, graph, uid, title, views, owners, points):
    from .legacy_zip_xy import saved_graph_axes

    match = _matching_graph_members(graph, uid, views, owners)
    if match is None:
        return False
    source, slot, parts, samples = match
    if set(parts) != {"Curve", "XY data"}:
        return False
    options = source.attrs["legacy_recipes"][slot][1]
    design = parts["XY data"] if options.get(MERGE_REPLICATES) is True else source
    try:
        found = fit_graph_spec(design, options, points, samples)
    except (KeyError, TypeError, ValueError):
        found = None
    if found is None:
        return False
    spec, show_outside = found
    saved = saved_graph_axes(archive, uid, graph["fenID"], viewport_only=spec.get("clip to series") is True)
    style, concentration_ticks = (None, None) if saved is None else saved
    chart = {LEGACY_TITLE: title[:160], FIT_GRAPH: True, "X label": options["X"], "Y label": spec["y"]}
    if concentration_ticks is not None:
        chart[FIT_GRAPH_TICKS] = concentration_ticks
    child = len(source.attrs["legacy_recipes"])
    if not _append_linked_recipe(source, slot, FIT_GRAPH_POINTS, SAVED_XY, chart):
        return False
    options[FIT_GRAPH_SPEC] = spec
    if show_outside:
        options[regression_range.SHOW_OUTSIDE] = True
    if style is not None:
        source.attrs.setdefault("legacy_graph_styles", {})[child] = style
    return True


def _link_survival_plot(archive, graph, uid, title, views, owners):
    from .legacy_zip_xy import saved_graph_axes

    match = _matching_graph_members(graph, uid, views, owners)
    if match is None:
        return False
    source, slot, parts, _ = match
    if set(parts) != {"Survival proportions"}:
        return False
    table = parts["Survival proportions"]
    options = source.attrs["legacy_recipes"][slot][1]
    columns = table.attrs["legacy_columns"]
    order = [columns[dataset][0] for dataset in graph["inputDataSets"]]
    if table.attrs["legacy_y_format"] == "y_plus_minus":
        if options.get(UNCERTAINTY) != CI_BARS:
            return False
        order = [label.removesuffix(" [Center]") for label in order]
    if columns[table.attrs["legacy_x"]] != [options["Time"]] or len(set(order)) != len(order):
        return False
    child = len(source.attrs["legacy_recipes"])
    if not _append_linked_recipe(source, slot, SURVIVAL_SUMMARY, SAVED_XY, {
        LEGACY_TITLE: title[:160], SURVIVAL_GRAPH: True, SURVIVAL_SERIES: order,
    }):
        return False
    options[SURVIVAL_GRAPH] = True
    saved = saved_graph_axes(archive, uid, graph["fenID"])
    if saved is not None:
        appearance, _ = saved
        if appearance["xscale"] == "linear":
            style = {"axis": {"x": appearance["axis"]["x"]}}
            for name in ("title", "xlabel"):
                if name in appearance:
                    style[name] = appearance[name]
            source.attrs.setdefault("legacy_graph_styles", {})[child] = style
    return True


def _link_grouped_anova(sheet, parameters, label, grouped_views, view_sources):
    recipe = restore_recipe(sheet, parameters, view_sources)
    if recipe is None:
        return False
    source, method, options = recipe
    if source not in grouped_views:
        return False
    cached = view_sources[source]
    ids = cached.attrs["legacy_y"]
    selected = _list(sheet.get("inputDataSets", []))
    if [item.get("uid") for item in selected if isinstance(item, dict)] != ids or len(selected) != len(ids):
        return False
    mapped = [name for uid in ids for name in cached.attrs["legacy_columns"][uid]]
    if len(mapped) != len(cached.columns) - 1 or mapped != list(cached.columns[1:]):
        return False
    producer, slot = grouped_views[source]
    return _append_linked_recipe(producer, slot, EXTRACT_TABLE, method, {
        **options, LEGACY_TITLE: label[:160],
        LEGACY_NOTES: "Recalculates the ordinary two-factor ANOVA from the linked rearranged worksheet.",
    })


def _link_transformed_fit(sheet, params, label, transforms, curves, fit_views):
    from .processing import transform_concentrations

    input_sheet, = sheet["inputSheets"]
    parent, slot, saved, transform_view = transforms[input_sheet["uid"]]
    options = restore_log_dose_fit(sheet, params, saved)
    if options is None:
        return False
    names = [options["X"], *options["Y columns"]]
    transform = parent.attrs["legacy_recipes"][slot][1]
    data = transform_concentrations(parent, transform).tables["Transformed data"]
    if not np.array_equal(data[names].to_numpy(dtype=float, na_value=np.nan),
                          saved[names].to_numpy(dtype=float, na_value=np.nan), equal_nan=True):
        return False
    fit_slot = len(parent.attrs["legacy_recipes"])
    if not _append_linked_recipe(parent, slot, "Transformed data", "Nonlinear regression",
                                 {**options, LEGACY_TITLE: label[:160]}):
        return False
    samples = saved_samples(params)
    if samples is not None and len(curves) == 1:
        curve, view = curves[0]
        producer = parent, fit_slot
        _register_analysis_view(fit_views, producer, "XY data", saved, transform_view, samples)
        _register_analysis_view(fit_views, producer, "Curve", curve,
                                {**view, "graphId": transform_view.get("graphId")}, samples)
    return True


def restore_sheets(archive, names, sheets, sources, tables, cells, *, focused=None):
    """Add non-executable snapshots and supported native analysis recipes."""
    from .legacy_layout_edit import LEGACY_PANEL_DATA
    from .legacy_zip_column import ZIP_COLUMN, saved_aligned_column, saved_geometric_column
    from .legacy_zip_grouped import saved_grouped_bars
    from .legacy_zip_layout import ZIP_LAYOUT, saved_positioned_layout
    from .legacy_zip_xy import ZIP_SPARSE_XY, saved_zip_xy

    warnings = []
    restyled = set()
    owners = {}
    view_sources = dict(sources)
    deferred_pca = []
    clustered_views = {}
    deferred_anova = []
    deferred_fits = []
    transformed_views = {}
    grouped_views = {}
    extracted_grouped_plots = {}
    elbow_views = {}
    hierarchy_scatters = {}
    kmeans_views = {}
    fit_views = {}
    paired_estimation_views = set()
    comparison_views = {}
    anova_grouped_views = {}
    survival_views = {}
    linked_xy = {}
    initial_run = None
    for source in sources.values():
        if source.attrs["legacy_x"]:
            for uid in source.attrs["legacy_y"]:
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
            chained_fit = recipe is None and sheet.get("analysisClass") == "NONLINEAR_REGRESSION"
            curve_views = []
            producer = None
            fit_samples = None
            paired_estimation = False
            comparison_producer = None
            grouped_primary = None
            if recipe:
                source, method, options = recipe
                restored = sources[source].attrs.setdefault("legacy_recipes", [])
                if len(restored) < 256:
                    slot = len(restored)
                    options = {**options, LEGACY_TITLE: label[:160]}
                    restored.append((method, options))
                    if method == "Multifactor ANOVA":
                        _, diagnostic_graphs = saved_anova_diagnostics(params["content"])
                        for graph in diagnostic_graphs:
                            _append_linked_recipe(sources[source], slot, anova_diagnostics.SHEET,
                                                  anova_diagnostics.METHOD, {
                                                      LEGACY_TITLE: f"{graph} · {label[:120]}",
                                                      anova_diagnostics.GRAPH: graph,
                                                  })
                    paired_estimation = shows_paired_estimation(method, options)
                    if _saved_anova_interval_requested(method, options, params):
                        comparison_producer = sources[source], slot
                    grouped_primary = saved_anova_primary_factor(sources[source], method, params, options)
                    if method == "Hierarchical clustering":
                        _restore_hierarchy_views(archive, names, sheet, results, sources[source], slot, options, restyled)
                        producer = sources[source], slot
                    if method in {SELECTION, EXTRACT_REARRANGE}:
                        producer = sources[source], len(restored) - 1
                    if method == "Transform concentrations (X)":
                        producer = sources[source], slot
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
            elif chained_fit:
                deferred_fits.append((sheet, params, label, curve_views))
            else:
                warnings.append(f"Recalculation unavailable for {label}.")
            for record in _list(sheet.get("resultSheets", [])):
                if not isinstance(record, dict):
                    continue
                if paired_estimation and (key := _paired_estimation_members(archive, path, record)) is not None:
                    paired_estimation_views.add(key)
                if comparison_producer is not None and (key := _anova_interval_members(archive, path, record)) is not None:
                    comparison_views.setdefault(key, []).append(comparison_producer)
                if grouped_primary and (key := _saved_grouped_members(archive, path, record, "Grouped")) is not None:
                    anova_grouped_views.setdefault(key, []).append((sources[source], slot, options, grouped_primary))
                saved = restore_view(archive, names, path, record, label, sheet, add, owners, view_sources,
                                     MAX_CELLS - cells)
                if chained_fit and saved is not None and saved[1] == "Curve":
                    curve_views.append(saved[2:])
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
                        if method == "Transform concentrations (X)" and name == "Transformed data":
                            transformed_views[view_uid] = (*producer, frame, view)
                        if method == "Kaplan–Meier survival":
                            _register_analysis_view(survival_views, producer, name, frame, view)
                        if (method == EXTRACT_REARRANGE and options[OUTPUT] == "Grouped" and name == "Results"
                                and frame.attrs.get("legacy_snapshot_source_format") == "grouped"):
                            grouped_views[view_uid] = producer
                            key = _saved_grouped_members(archive, path, record, "Results")
                            if key is not None:
                                extracted_grouped_plots.setdefault(key, []).append((*producer, frame))
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
                            datasets = frame.attrs["legacy_y"]
                            graph_id = view.get("graphId")
                            if (axis is not None and options["Direction"] in {axis, "Rows and columns"}
                                    and frame.attrs["legacy_x"] and len(datasets) == 1 and type(graph_id) is int):
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
        options = {**options, LEGACY_TITLE: label[:160]}
        directions = saved_component_directions(archive, sheet, view_sources, options["Variables"])
        if directions:
            options[SAVED_DIRECTIONS] = directions
        parallel = saved_parallel_reference(archive, sheet, view_sources[source], view_sources, options)
        if parallel is not None:
            options[PCA_PARALLEL_ARCHIVE] = parallel
            options[LEGACY_NOTES] = ("Recalculates standardized PCA and the saved color grouping."
                                    + _pca_parallel_note(options))
        overlay = saved_score_overlay(archive, sheet, view_sources[source], view_sources, options)
        if overlay:
            options.update(overlay[1])
            options[LEGACY_NOTES] += _pca_overlay_note(options)
        if source in clustered_views and _link_clustered_pca(
                *clustered_views[source], view_sources[source], method, options):
            if overlay:
                restyled.add(overlay[0])
            continue
        restored = view_sources[source].attrs.setdefault("legacy_recipes", [])
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
    for sheet, params, label, curves in deferred_fits:
        try:
            if _link_transformed_fit(sheet, params, label, transformed_views, curves, fit_views):
                continue
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
        warnings.append(f"Recalculation unavailable for {label}.")
    for entry in _list(sheets.get("graphs", [])):
        label = str(entry)
        prior = None
        try:
            uid = _identifier(entry)
            if uid in restyled:
                continue
            graph = _json_object(archive, f"graphs/{uid}/sheet.json")
            label = graph.get("title") or uid
            if not isinstance(label, str):
                raise ValueError("Invalid graph title.")
            if focused == ("graph", uid) and graph.get("uid") == uid:
                prior = {name: len(frame.attrs.get("legacy_recipes", ())) for name, frame in tables.items()}
            if (paired_estimation_views and graph.get("uid") == uid and type(graph.get("fenID")) is int
                    and (graph["fenID"], tuple(graph.get("inputDataSets", ()))) in paired_estimation_views):
                continue
            datasets = graph.get("inputDataSets")
            if ((comparison_views or anova_grouped_views or extracted_grouped_plots) and graph.get("uid") == uid
                    and type(graph.get("fenID")) is int and isinstance(datasets, list)
                    and all(isinstance(dataset, str) for dataset in datasets)):
                key = graph["fenID"], tuple(datasets)
                matches = comparison_views.get(key, ())
                if len(matches) == 1 and _append_linked_recipe(
                        *matches[0], anova_comparison_plot.SOURCE_TABLE, anova_comparison_plot.METHOD,
                        {LEGACY_TITLE: label[:160]}):
                    continue
                matches = anova_grouped_views.get(key, ())
                if len(matches) == 1:
                    parent, slot, options, primary = matches[0]
                    chart = {LEGACY_TITLE: label[:160], anova_grouped_plot.RESPONSE_LABEL: options["Response"]}
                    if _append_linked_recipe(parent, slot, anova_grouped_plot.TABLE, anova_grouped_plot.METHOD, chart):
                        options[anova_grouped_plot.PRIMARY] = primary
                        continue
                matches = extracted_grouped_plots.get(key, ())
                if len(matches) == 1 and _link_extracted_grouped_plot(*matches[0], key[1], label):
                    continue
            if _link_hierarchy_elbow(graph, uid, label, elbow_views, owners):
                continue
            if _link_kmeans_plot(graph, uid, label, kmeans_views, owners):
                continue
            points = _saved_xy({**graph, "title": label[:160]}, owners, MAX_CELLS - cells)
            if points is not None and _link_fit_plot(archive, graph, uid, label, fit_views, owners, points):
                continue
            if points is not None and _link_survival_plot(archive, graph, uid, label, survival_views, owners):
                continue
            if graph.get("uid") == uid:
                linked = saved_zip_xy(archive, graph, uid, owners, sources, replicates=points is not None)
                if linked is not None:
                    source, style = linked
                    recipes = source.attrs.setdefault("legacy_recipes", [])
                    if len(recipes) < 256:
                        if style.get("sample_sd") is True:
                            note = "Linked XY row means with sample SD on both sides and saved axis limits."
                        elif points is not None:
                            note = ("Linked XY replicates with saved axis limits. The observations are shown "
                                    "individually because the saved error summary is unavailable.")
                        else:
                            note = ("Linked XY data, saved axis limits and series colors. "
                                    "Trama uses native point markers and graph formatting.")
                        options = {
                            LEGACY_TITLE: label[:160], ZIP_SPARSE_XY: style,
                            LEGACY_NOTES: note,
                        }
                        recipes.append((SAVED_XY, options))
                        if points is None:
                            linked_xy[uid] = (source, graph["fenID"], options)
                        continue
            if points is None and graph.get("uid") == uid:
                column = saved_aligned_column(archive, graph, uid, sources)
                if column is not None:
                    source, style = column
                    recipes = source.attrs.setdefault("legacy_recipes", [])
                    if len(recipes) < 256:
                        recipes.append((SAVED_XY, {
                            LEGACY_TITLE: label[:160], ZIP_COLUMN: style,
                            LEGACY_NOTES: "Linked column data with saved axis settings and point colors.",
                        }))
                        continue
                geometric = saved_geometric_column(archive, graph, uid, sources)
                if geometric is not None:
                    source, columns, style = geometric
                    recipes = source.attrs.setdefault("legacy_recipes", [])
                    if len(recipes) < 256:
                        source.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
                        recipes.append((COLUMN_GRAPH, {
                            "Variables": columns, "Graph style": POINTS, "Center": GEOMETRIC_CENTER,
                            "Interval": "Confidence interval", "Confidence level (%)": 95.,
                            LEGACY_TITLE: label[:160],
                        }))
                        continue
                grouped = saved_grouped_bars(archive, graph, uid, sources)
                if grouped is not None:
                    source, options, style = grouped
                    recipes = source.attrs.setdefault("legacy_recipes", [])
                    if len(recipes) < 256:
                        source.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
                        recipes.append((GROUPED_GRAPH, {**options, LEGACY_TITLE: label[:160]}))
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
                    points.attrs["table_format"] = "Imported graph snapshot"
                    points.attrs["legacy_recipes"] = [(SAVED_XY, {
                        LEGACY_TITLE: label[:160], APPEARANCE: style,
                        LEGACY_NOTES: "Editable saved scatter coordinates, category colors and axis limits. "
                                     "Trama draws the rest of the graph with native formatting.",
                    })]
            if points is None or not add(f"Imported graph · {label}", points):
                warnings.append(f"Graph unavailable for {label}.")
        except (KeyError, TypeError, ValueError):
            prior = None
            warnings.append(f"Graph unavailable for {label}.")
        finally:
            if prior is not None:
                # Each recovered graph adds one recipe, either to a live sheet or to a new snapshot.
                added = [(name, index) for name, frame in tables.items()
                         for index in range(prior.get(name, 0), len(frame.attrs.get("legacy_recipes", ())))]
                if len(added) == 1:
                    initial_run = added[0]
    for entry in _list(sheets.get("layouts", [])):
        label = str(entry)
        try:
            uid = _identifier(entry)
            sheet = _json_object(archive, f"layouts/{uid}/sheet.json")
            label = str(sheet.get("title") or uid)[:160]
            linked = saved_positioned_layout(archive, uid, sheet, linked_xy)
            if linked is not None:
                source, layout, panel_recipes = linked
                recipes = source.attrs["legacy_recipes"]
                if len(recipes) < 256:
                    options = {
                        LEGACY_TITLE: label, ZIP_LAYOUT: layout,
                        LEGACY_NOTES: "Linked data and saved page positions. "
                                     "Trama draws the panels and connector lines with native formatting.",
                    }
                    if panel_recipes:
                        options[LEGACY_PANEL_DATA] = {
                            str(number): recipe.setdefault(LEGACY_GRAPH_LINK, uuid4().hex)
                            for number, recipe in enumerate(panel_recipes, 1)
                        }
                    recipes.append((SAVED_BINARY_LAYOUT, options))
                    if focused == ("layout", uid):
                        title = next(name for name, frame in tables.items() if frame is source)
                        initial_run = title, len(recipes) - 1
                    continue
        except (KeyError, TypeError, ValueError):
            pass
        warnings.append(f"Layout unavailable for {label}.")
    if warnings:
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            "Project import · " + " ".join(warnings[:4]) +
            (f" ({len(warnings) - 4} more notices.)" if len(warnings) > 4 else ""))
    return initial_run


def restore_binary_views(data, sources, tables, cells, fonts, document_title):
    from .legacy_binary_dose import restore_dose_graphs, restore_pade_graphs
    from .legacy_binary_editable import read_editable_graphs
    from .legacy_binary_global import restore_global_graphs
    from .legacy_binary_graphs import read_binary_graphs
    from .legacy_binary_layouts import read_binary_layouts
    from .legacy_binary_range import BINARY_XY_RANGE
    from .legacy_binary_results import report_saved_result_warnings, restore_binary_results
    from .legacy_binary_simulation import read_simulation_graphs
    from .legacy_emf_edit import CURVE, LIMIT_SOURCE, POINTS
    from .legacy_layout_edit import LEGACY_EDITABLE_PANELS
    from .legacy_pdf_stacks import STACK_KIND

    source_names = set(tables)
    dose_curves, classic_curves, calibration_curves, global_curves = {}, {}, {}, {}
    pade_curves = {}
    unavailable_results = set()
    cells = restore_binary_results(
        data, sources, tables, cells, fonts, dose_curves=dose_curves, classic_curves=classic_curves,
        calibration_curves=calibration_curves, global_curves=global_curves,
        pade_curves=pade_curves, pending_analyses=unavailable_results)
    for title, frame in tables.items():
        if title not in source_names:
            saved = frame.attrs["legacy_binary_result"]
            sheet = saved["sheet_title"].partition(":")[2].strip() or "Saved results"
            frame.attrs["legacy_recipes"] = [(SAVED_BINARY_RESULT, {
                LEGACY_TITLE: title.removeprefix("Imported result · ")[:240],
                LEGACY_NOTES: "Saved result from the source project. Use Result as Data to make an editable copy.",
                LEGACY_RESULT_SHEET: sheet,
                "Legacy result provenance": saved,
            })]
    try:
        records, unavailable = read_binary_graphs(data, include_without_preview=True)
    except ValueError as error:
        records, unavailable = [], [str(error)]
    graphs = [graph for graph in records if "preview" in graph]
    without_preview = {graph["id"]: graph["title"] for graph in records if "preview" not in graph}
    import_id = uuid4().hex
    graph_links = {graph["id"]: f'{import_id}:{graph["id"]}' for graph in records}
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        views = [(SAVED_BINARY_GRAPH, {
            LEGACY_TITLE: graph["title"],
            LEGACY_NOTES: ("Original drawing from the source project. Export as "
                          f'{graph["preview"]["format"].upper()} to preserve the vector image.'),
            LEGACY_PREVIEW: graph["preview"],
            LEGACY_GRAPH_LINK: graph_links[graph["id"]],
        }) for graph in graphs]
        graph_carrier = _store_collection(tables, document_title, "graphs", BINARY_GRAPH_COLLECTION, views)
        cells += 1
    elif graphs:
        graphs = []
        unavailable += ["The project has reached its table or cell limit."]
    cells, layouts = _restore_binary_layouts(data, document_title, graphs, graph_links,
                                             tables, cells, read_binary_layouts)
    restored_graphs = set()
    if graphs or without_preview:
        result_frames = {frame.attrs["legacy_binary_result"]["sheet_id"]: frame for frame in tables.values()
                         if "legacy_binary_result" in frame.attrs}
        if classic_curves:
            restored_graphs = restore_dose_graphs(data, graphs, graph_links, {}, result_frames,
                                                 classic_curves=classic_curves)
        if calibration_curves:
            restored_graphs.update(restore_dose_graphs(
                data, [graph for graph in graphs if graph["id"] not in restored_graphs], graph_links,
                calibration_curves, result_frames, verify_series=True))
        restored_global, recovered = restore_global_graphs(data, graphs, graph_links, global_curves, result_frames,
                                                           sources)
        restored_graphs.update(restored_global)
        unavailable_results.difference_update(recovered)
        restored_pade, recovered = restore_pade_graphs(data, graphs, graph_links, pade_curves, result_frames, sources)
        restored_graphs.update(restored_pade)
        unavailable_results.difference_update(recovered)
        titles = {graph["id"]: graph["title"] for graph in graphs if graph["id"] not in restored_graphs}
        titles.update(without_preview)
        for uid, analysis, frame, options, style in read_simulation_graphs(
                data, result_frames, titles, MAX_CELLS - cells, observations=sources):
            observed = OBSERVATION_COLUMNS in options
            if not observed:
                if len(tables) >= 256:
                    continue
                frame.attrs["table_format"] = "xy"
                _store_table(tables, f"Imported graph data · {titles[uid]}", frame)
                cells += frame.size
            recipes = frame.attrs.setdefault("legacy_recipes", [])
            frame.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = style
            note = ("Edit the original observations or equation parameters to redraw the graph." if observed
                    else "Edit the equation parameters or the saved X values to redraw the curve.")
            if uid in without_preview:
                note = "Reconstructed from the saved data and plot settings. " + note
                del without_preview[uid]
            recipes.append((PLOT_FUNCTION, {
                **options, LEGACY_TITLE: titles[uid][:150] + " · Linked", LEGACY_GRAPH_LINK: graph_links[uid],
                LEGACY_NOTES: note,
            }))
            restored_graphs.add(uid)
            unavailable_results.discard(analysis)
    unavailable.extend(without_preview.values())
    if tables and unavailable:
        count = len(unavailable)
        first = next(iter(tables.values()))
        first.attrs.setdefault("import_warnings", []).append(
            f"Unavailable imported graph previews ({count}) · " + ", ".join(unavailable[:4]))
    report_saved_result_warnings(tables, unavailable_results)
    if graphs and len(tables) < 256 and cells < MAX_CELLS:
        try:
            cached_curves = {panel["graph_id"] for _, options in layouts
                             for panel in options.get(LEGACY_EDITABLE_PANELS, ())}
            editable = read_editable_graphs(data, sources, result_frames, MAX_CELLS - cells,
                                            cached_curves=cached_curves, skip=restored_graphs)
        except ValueError:
            editable = {}
        linked = {}
        for graph in graphs:
            uid = graph["id"]
            if uid not in editable:
                continue
            frame, style = editable[uid]
            kind = style.get("kind")
            if kind == "empty_axes":
                recipes = graph_carrier.attrs["legacy_recipes"]
                if len(recipes) < 256:
                    appearance = {key: value for key, value in style.items() if key != "kind"}
                    graph_carrier.attrs.setdefault("legacy_graph_styles", {})[len(recipes)] = appearance
                    recipes.append((SAVED_XY, {
                        LEGACY_TITLE: graph["title"][:150] + " · Editable",
                        LEGACY_NOTES: "This saved graph contains only axes. Use Format Graph to edit them.",
                        LEGACY_GRAPH_LINK: graph_links[uid], SAVED_AXES: appearance,
                    }))
                    restored_graphs.add(uid)
                continue
            binding = style.get(LIMIT_SOURCE)
            shaded_range = style.pop(BINARY_XY_RANGE, None)
            if binding is None and (len(tables) >= 256 or cells + frame.size > MAX_CELLS):
                continue
            if kind == STACK_KIND:
                if graph["preview"]["format"] != "pdf":
                    continue
                table_format = EDITABLE_LEGACY_STACKS
                notes = ("Edit the percentages in the graph data sheet. The editable view retains the saved drawing. "
                         "The original view provides the original vector PDF.")
            elif kind == "columns":
                table_format = EDITABLE_LEGACY_COLUMNS
                notes = "Edit means and displayed errors in the graph data sheet. Saved formatting and annotations are retained."
            elif kind in (CURVE, POINTS):
                if graph["preview"]["format"] != "emf":
                    continue
                table_format = EDITABLE_LEGACY_EMF
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
                table_format = EDITABLE_LEGACY_XY
                notes = "Editable XY graph with recovered formatting. Original drawing remains available."
                if kind == "residual_points":
                    notes = "Edit the coordinates from the saved residual table. The original drawing remains available."
            if binding is not None:
                frame = sources[binding["sheet"]]
            else:
                frame.attrs["table_format"] = table_format
            frame.attrs.setdefault("legacy_recipes", []).append((SAVED_EDITABLE_GRAPH, {
                LEGACY_TITLE: graph["title"] + " · Editable",
                LEGACY_NOTES: notes,
                LEGACY_GRAPH_STYLE: style,
                LEGACY_GRAPH_LINK: graph_links[uid],
                **({LEGACY_PREVIEW: graph["preview"]} if table_format != EDITABLE_LEGACY_XY else {}),
            }))
            restored_graphs.add(uid)
            if shaded_range is not None:
                frame.attrs["legacy_recipes"].append((SAVED_XY, {
                    LEGACY_TITLE: graph["title"] + " · Linked range",
                    BINARY_XY_RANGE: shaded_range,
                }))
            if binding is None:
                _store_table(tables, f'Imported graph data · {graph["title"]}', frame)
                cells += frame.size
            if table_format in (EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_EMF):
                linked[uid] = (frame, style)
        _link_layout_panel_data(layouts, graph_links, linked)
    if graphs and dose_curves:
        restore_dose_graphs(data, [graph for graph in graphs if graph["id"] not in restored_graphs],
                            graph_links, dose_curves, result_frames)


def _store_collection(tables, title, label, table_format, views):
    carrier = pd.DataFrame({"Imported project": [title]})
    carrier.attrs.update(table_format=table_format, legacy_recipes=views)
    _store_table(tables, f"Imported {label} · {title}", carrier)
    return carrier


def _restore_binary_layouts(data, title, graphs, graph_links, tables, cells, reader):
    from .legacy_binary_layouts import grid_panel_order
    from .legacy_layout_edit import LEGACY_EDITABLE_PANELS, editable_panels

    try:
        layouts, unavailable = reader(data)
    except ValueError as error:
        layouts, unavailable = [], [str(error)]
    graph_previews = {graph["id"]: graph["preview"] for graph in graphs}
    graph_titles = {graph["id"]: graph["title"] for graph in graphs}
    views, panel_bytes = [], 0
    for layout in layouts:
        options = {LEGACY_TITLE: layout["title"]}
        if layout.get("preview"):
            options[LEGACY_PREVIEW] = layout["preview"]
            options[LEGACY_NOTES] = "Original page from the source project. Export as EMF to retain the vector drawing."
            panels = editable_panels(layout["preview"], layout["placements"], graph_titles,
                                     placements_complete=layout["placements_complete"])
            if panels:
                options[LEGACY_EDITABLE_PANELS] = panels
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
            options[LEGACY_LAYOUT_PANELS] = panels
            options[LEGACY_NOTES] = "Page reconstructed from the original graph positions and saved drawings."
        else:
            unavailable.append(layout["title"])
            continue
        if layout["placements_complete"] and (grid := grid_panel_order(layout["placements"])):
            columns, panels = grid
            if all(uid in graph_links for uid in panels):
                options[LEGACY_LAYOUT_GRID] = {"columns": columns, "links": [graph_links[uid] for uid in panels]}
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
            f"Unavailable imported layouts ({len(titles)}) · " + ", ".join(titles[:4]))
    return cells, views


def _link_layout_panel_data(layouts, graph_links, linked):
    from .legacy_layout_edit import (LEGACY_EDITABLE_PANELS, LEGACY_PANEL_DATA, edit_panel_artwork,
                                    layout_panel_artwork)

    for _, options in layouts:
        panels = options.get(LEGACY_EDITABLE_PANELS)
        if not panels or not any(panel["graph_id"] in linked for panel in panels):
            continue
        artwork = layout_panel_artwork(options[LEGACY_PREVIEW], panels)
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
            options[LEGACY_PANEL_DATA] = links


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
    if not view.get("isVisible") and not frame.attrs["legacy_x"]:
        return
    source_format = frame.attrs.get("table_format")
    if source_format in {"multivariable", "grouped"}:
        frame.attrs["legacy_snapshot_source_format"] = source_format
    frame.attrs["table_format"] = "Imported result snapshot"
    if not add(f"Imported result · {analysis_title} · {name}", frame):
        return
    view_sources.setdefault(uid, frame)
    if frame.attrs["legacy_x"]:
        geometry = "line" if name == "Curve" else "points"
        if analysis.get("analysisClass") == "SURVIVAL" and name == "Survival proportions":
            geometry = "step"
        for dataset in frame.attrs["legacy_y"]:
            owners.setdefault(dataset, []).append((frame, geometry))
    return uid, name, frame, view
