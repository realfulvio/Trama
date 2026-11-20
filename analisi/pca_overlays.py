"""Adapt the confidence overlay renderer to plotted PCA observation coordinates."""

import math

import numpy as np
import pandas as pd
from matplotlib.colors import is_color_like

from . import ellipse_workbench as ellipses
from .graph_legend import typed_group_token
from .processing import FieldError


KIND, GROUPING, LEVEL = "PCA overlay", "PCA overlay grouping", "PCA overlay level (%)"
SAVED_APPEARANCE = "PCA saved overlay appearance"
POOLED, BY_POINTS = "All plotted points", "By point group"
SHEET = "Confidence overlays"
OPTIONS = {KIND: ellipses.ELLIPSE_OPTIONS["Ellipse"], GROUPING: (POOLED, BY_POINTS), LEVEL: 95.0}
TABS = {"PCA overlays": tuple(OPTIONS)}
LABEL_KEYS = {
    "PCA overlays": "pca.overlays.tab",
    KIND: "pca.overlays.kind",
    GROUPING: "pca.overlays.grouping",
    LEVEL: "pca.overlays.level",
}
CHOICE_KEYS = {
    ellipses.NONE: "pca.overlays.none",
    ellipses.MEAN_REGION: "pca.overlays.mean",
    ellipses.DATA_ELLIPSE: "pca.overlays.data",
    ellipses.HULL: "pca.overlays.hull",
    POOLED: "pca.overlays.all",
    BY_POINTS: "pca.overlays.by_points",
}


def active_fields(point_view, kind):
    return {KIND: point_view, GROUPING: point_view and kind != ellipses.NONE,
            LEVEL: point_view and kind in (ellipses.MEAN_REGION, ellipses.DATA_ELLIPSE)}


def saved_point_colors(options, group_column):
    appearance = options.get(SAVED_APPEARANCE)
    if isinstance(appearance, dict) and appearance.get("column") == group_column:
        markers = appearance.get("markers")
        if isinstance(markers, dict) and len(markers) <= 40:
            return {label: color for label, color in markers.items()
                    if isinstance(color, str) and is_color_like(color)}
    return {}


def configuration(options, point_view, group_column):
    kind = options.get(KIND, ellipses.NONE)
    if not point_view or kind == ellipses.NONE:
        return None
    if kind not in OPTIONS[KIND]:
        raise FieldError(KIND, "Choose a PCA overlay.")
    grouping = options.get(GROUPING, POOLED)
    if grouping not in OPTIONS[GROUPING] or grouping == BY_POINTS and not group_column:
        raise FieldError(GROUPING, "Choose a color grouping column or use all plotted points.")
    settings = {"Ellipse": kind, "Fill": ellipses.BY_GROUP, "Fill opacity (%)": 15.0,
                "X": "X", "Y": "Y", "Group": "Group" if grouping == BY_POINTS else None}
    if kind != ellipses.HULL:
        raw = options.get(LEVEL, OPTIONS[LEVEL])
        try:
            level = float(raw)
        except (TypeError, ValueError, OverflowError):
            level = math.nan
        if isinstance(raw, (bool, np.bool_)) or not 0 < level < 100:
            raise FieldError(LEVEL, "The PCA overlay level must be strictly between 0 and 100.")
        settings["Level (%)"] = level
    appearance = options.get(SAVED_APPEARANCE)
    if (kind == ellipses.MEAN_REGION and grouping == BY_POINTS and isinstance(appearance, dict)
            and appearance.get("column") == group_column and type(appearance.get("fill")) is bool):
        try:
            styles = ellipses.normalize_ellipse_group_styles({"Group": appearance.get("styles", {})})
        except FieldError:
            pass  # Stale appearance data must not prevent recalculating the analysis.
        else:
            settings[SAVED_APPEARANCE] = styles.get("Group", {})
            if not appearance["fill"]:
                settings["Fill"] = ellipses.NONE
    return settings


def draw(axes, coordinates, point_groups, settings):
    frame = pd.DataFrame(coordinates, columns=["X", "Y"])
    colors, captions = {}, {}
    if settings["Group"]:
        keys = np.empty(len(frame), dtype=object)
        saved = settings.get(SAVED_APPEARANCE, {})
        overrides = {}
        for key, caption, rows, color in point_groups:
            keys[rows] = key
            colors[key] = color
            captions[key] = caption
            identity = key.removeprefix("group:")
            if identity in saved:
                overrides[typed_group_token(key)] = saved[identity]
        frame["Group"] = keys
        if overrides:
            settings = {**settings, ellipses.GROUP_STYLES: {"Group": overrides}}
    elif len(point_groups) == 1:
        colors["All"] = point_groups[0][-1]
    rows = ellipses.draw_confidence_overlays(axes, frame, settings, colors, allow_unavailable=True)
    if captions:
        rows["Group"] = rows["Group"].map(captions)
    return rows
