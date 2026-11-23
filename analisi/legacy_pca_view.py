"""Recover parallel references, component directions and overlays from saved PCA results."""

from collections import Counter
import re

import numpy as np

from . import ellipse_workbench as ellipses, pca_overlays, pca_parallel_archive, pca_retention
from .graph_legend import typed_group_token
from .pca_graphs import COLOR_GROUPS, HORIZONTAL, SAVED_VIEWPORT, VERTICAL
from .legacy_import import _identifier, _json_object
from .legacy_mv_scatter import fixed_axis_record


_COLOR = re.compile(r"#[0-9a-fA-F]{8}")


def _palette(graph, overlay, labels):
    """Identify the contour legend by its paired fill and border colors."""
    fill = overlay["isFillEnabled"]
    border_counts = Counter(color.lower() for color in overlay["borderColormap"]["colors"].values())
    fill_counts = Counter(color.lower() for color in overlay["colormap"]["colors"].values()) if fill else None
    result = []
    for legend in graph.get("legends", []):
        if legend.get("@class") != "CategoricalSymbolsLegend":
            continue
        styles, faces, edges = {}, [], []
        for entry in legend["children"]:
            label = entry["title"]["text"]["string"]
            edge, face = entry.get("symbolBorderColor", ""), entry.get("symbolFillColor", "")
            if label not in labels or label in styles or not _COLOR.fullmatch(edge):
                break
            edge = edge.lower()
            edges.append(edge)
            style = {"Border color": edge[:7], "Border opacity (%)": int(edge[7:], 16) * 100 / 255}
            if fill:
                if not _COLOR.fullmatch(face):
                    break
                face = face.lower()
                faces.append(face)
                style.update({"Fill color": face[:7], "Fill opacity (%)": int(face[7:], 16) * 100 / 255})
            styles[label] = style
        else:
            if (styles.keys() == labels and Counter(edges) == border_counts
                    and (not fill or Counter(faces) == fill_counts)):
                result.append(styles)
    return result[0] if len(result) == 1 else {}


def _point_colors(graph, labels):
    symbols = graph["gdoSettings"]["symbols"]
    colors = Counter(color.lower() for color in symbols["colormap"]["colors"].values())
    candidates = []
    for legend in graph.get("legends", []):
        if legend.get("@class") != "CategoricalSymbolsLegend":
            continue
        entries = legend["children"]
        if len(entries) != len(labels):
            continue
        mapping = {entry["title"]["text"]["string"]: entry["symbolFillColor"].lower() for entry in entries}
        if (mapping.keys() == labels and all(_COLOR.fullmatch(value) for value in mapping.values())
                and Counter(mapping.values()) == colors):
            candidates.append(mapping)
    return candidates[0] if len(candidates) == 1 else {}


def _component(scores, selector, component_count):
    if not isinstance(selector, list):
        raise ValueError("Expected a saved principal component.")
    uid, = selector
    column, = scores.attrs["legacy_columns"][uid]
    match = re.fullmatch(r"PC([1-9][0-9]*)", column)
    number = int(match[1]) if match else 0
    if not 1 <= number <= component_count:
        raise ValueError("Expected a saved principal component.")
    return number


def saved_component_directions(archive, analysis, view_sources, variables):
    """Read finite loadings owned by this analysis, with the original variable labels."""
    try:
        record, = [item for item in analysis["resultSheets"] if item.get("title") == "Loadings"]
        owner = _identifier(analysis["uid"])
        view = _json_object(archive, f"analyses/{owner}/result_sheets/{_identifier(record['uid'])}.json")
        if view.get("name") != "Loadings" or view.get("isInternal"):
            return {}
        table = view_sources[view["dataSheet"]]
        if (list(table.columns[:1]) != ["Var"] or not table["Var"].is_unique
                or set(table["Var"]) != set(variables)):
            return {}
        table = table.set_index("Var").loc[variables]
        components = list(table)
        if not components or components != [f"PC{index}" for index in range(1, len(components) + 1)]:
            return {}
        if len(components) > len(variables):
            return {}
        loadings = table.to_numpy(dtype=float)
        if not np.isfinite(loadings).all() or (np.abs(loadings) > 1.000001).any():
            return {}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return {}
    return {name: dict(zip(variables, loadings[:, index].tolist(), strict=True))
            for index, name in enumerate(components)}


def saved_parallel_reference(archive, analysis, frame, view_sources, options):
    """Read the symmetric percentile levels as asymmetric distances from the saved mean."""
    percentile = float(options[pca_retention.PERCENTILE])
    if percentile != 95:
        return None
    try:
        record, = [item for item in analysis["resultSheets"] if item.get("title") == "Eigenvalues"]
        owner = _identifier(analysis["uid"])
        view = _json_object(archive, f"analyses/{owner}/result_sheets/{_identifier(record['uid'])}.json")
        if view.get("name") != "Eigenvalues" or view.get("isInternal"):
            return None
        table = view_sources[view["dataSheet"]]
        variables = options["Variables"]
        if not 1 <= len(table) <= len(variables) or list(table["Row title"]) != [
                f"PC{number}" for number in range(1, len(table) + 1)]:
            return None
        observed = table["Eigenvalue (from data) [Center]"].to_numpy(dtype=float)
        prefix = "Eigenvalue (from Parallel Analysis)"
        mean, low, high = (table[f"{prefix} [{part}]"].to_numpy(dtype=float)
                           for part in ("Center", "Lower", "Upper"))
        if (low < 0).any() or (high < 0).any():
            return None
        return pca_parallel_archive.capture(
            frame, variables, options[pca_retention.SIMULATIONS], options[pca_retention.SEED],
            percentile, observed, mean, mean - low, mean + high)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _score_viewport(graph, x, y):
    """Import the fixed linear viewport and dotted zero references on a score plot."""
    try:
        title = graph["title"]["text"]["string"]
        if graph["title"]["isVisible"] is not True or not isinstance(title, str) or not 1 <= len(title) <= 240:
            return None
        viewport = {"title": title, "components": [x, y]}
        for key, name, orientation in (("x", "axisX", "horizontal"), ("y", "axisY", "vertical")):
            axis = graph[name]
            segment, = axis["segments"]
            if (axis["orientation"] != orientation or axis["title"]["isVisible"] is not True
                    or segment["@class"] != "LinearAxisSegment" or segment.get("minorTicksCount", 0) != 0
                    or not all(segment.get(field) is True for field in
                               ("isLowerLimitFixed", "isUpperLimitFixed", "isIntervalFixed"))):
                return None
            result = fixed_axis_record({
                "title": axis["title"]["text"]["string"], "low": segment["lowerLimit"], "high": segment["upperLimit"],
                "start": segment["startTicksValue"], "step": segment["interval"],
                "reversed": segment.get("isReversed", False),
            })
            ticks = segment.get("customTicks", [])
            if not isinstance(ticks, list) or len(ticks) > 1:
                return None
            if ticks:
                tick, = ticks
                line = tick["gridLine"]
                width, color = line["strokeThickness"], line["strokeColor"]
                if (tick["@class"] != "CustomAxisTick" or type(tick["value"]) not in (int, float)
                        or tick["value"] != 0 or tick["tickType"] != "none" or tick["labelText"] != ""
                        or line["isVisible"] is not True or line["orderOfDrawing"] != "under"
                        or line["strokeStyle"] != "dot" or not _COLOR.fullmatch(color)
                        or type(width) not in (int, float) or not .2 <= width <= 8):
                    return None
                result["zero"] = {"color": color.lower(), "width": float(width)}
            viewport[key] = result
        return viewport
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def saved_score_overlay(archive, analysis, input_frame, view_sources, options):
    """Restore the unambiguous graph settings, keeping PCA on its original input."""
    group = options[COLOR_GROUPS]
    if not group:
        return None
    try:
        owner = _identifier(analysis["uid"])
        reference, = analysis["graphs"]
        model = reference["settings"]
        uid = _identifier(model["uid"])
        sheet = _json_object(archive, f"graphs/{uid}/sheet.json")
        graph = sheet["graph"]
        if (sheet.get("uid") != uid or sheet.get("settingsSource") != owner
                or sheet.get("analysisSettingsID") != reference["id"]
                or model["graph"]["dataSheet"] != graph["dataSheet"]
                or graph.get("@class") != "MVGraph"
                or graph.get("gdoTypesExt") != {"defaults": ["symbols", "confidence ellipses"]}):
            return None
        score_view, = [record for record in analysis["resultSheets"] if record.get("title") == "PC scores"]
        view = _json_object(archive, f"analyses/{owner}/result_sheets/{_identifier(score_view['uid'])}.json")
        if view.get("name") != "PC scores" or view.get("dataSheet") != graph["dataSheet"]:
            return None
        scores = view_sources[graph["dataSheet"]]
        x, y = (_component(scores, graph[f"{axis}Variables"], len(options["Variables"])) for axis in ("x", "y"))
        overlay = graph["gdoSettingsExt"]["confidence ellipses"]
        variable = overlay["groupingVariable"]
        score_group, = scores.attrs["legacy_columns"][variable]
        level = overlay["confidenceLevel"]
        fill = overlay["isFillEnabled"]
        if (x == y or overlay.get("@class") != "ConfidenceEllipsesFigure::Settings"
                or variable != graph["gdoSettings"]["symbols"]["colorVariable"]
                or score_group != group or type(level) not in (int, float) or not 0 < level < 100
                or type(fill) is not bool or not scores[score_group].reset_index(drop=True).equals(
                    input_frame[group].reset_index(drop=True))):
            return None
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None
    restored = {HORIZONTAL: x, VERTICAL: y, pca_overlays.KIND: ellipses.DATA_ELLIPSE,
                pca_overlays.GROUPING: pca_overlays.BY_POINTS, pca_overlays.LEVEL: float(level)}
    labels = scores[score_group].dropna().unique()
    tokens = {str(label): typed_group_token(label) for label in labels}
    styles, markers = {}, {}
    if 1 <= len(tokens) == len(labels) <= 40:
        try:
            styles = {tokens[label]: style for label, style in _palette(graph, overlay, tokens.keys()).items()}
            markers = {tokens[label]: color for label, color in _point_colors(graph, tokens.keys()).items()}
        except (KeyError, TypeError, ValueError, AttributeError):
            pass  # Geometry and confidence level remain usable if the palette is incomplete.
    restored[pca_overlays.SAVED_APPEARANCE] = {"column": group, "fill": fill, "styles": styles, "markers": markers}
    if viewport := _score_viewport(graph, x, y):
        restored[SAVED_VIEWPORT] = viewport
    return uid, restored
