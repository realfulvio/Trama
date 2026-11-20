"""Recover confidence overlays on a saved PCA scores graph."""

from collections import Counter
import re

from . import ellipse_workbench as ellipses, pca_overlays
from .graph_legend import typed_group_token
from .pca_graphs import COLOR_GROUPS, HORIZONTAL, VERTICAL
from .prism_import import _identifier, _json_object


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
    column, = scores.attrs["prism_columns"][uid]
    match = re.fullmatch(r"PC([1-9][0-9]*)", column)
    number = int(match[1]) if match else 0
    if not 1 <= number <= component_count:
        raise ValueError("Expected a saved principal component.")
    return number


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
        score_group, = scores.attrs["prism_columns"][variable]
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
    return uid, restored
