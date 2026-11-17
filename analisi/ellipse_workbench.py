"""Confidence overlay settings, validation and scatter artists."""

import numpy as np
import pandas as pd
from matplotlib import rcParams
from matplotlib.colors import to_rgba
from matplotlib.patches import Polygon
from scipy.spatial import ConvexHull, QhullError

from . import stats as engine
from .presentation import LINE_STYLES, MARKERS


MATCH_POINTS = "Match point groups"
ALL_POINTS = "All XY data"
SEPARATE_GROUP = "Separate categorical variable"
MEAN_REGION = "Confidence region of mean"
DATA_ELLIPSE = "Data ellipse"
HULL = "Convex hull"
NONE, SINGLE_COLOR, BY_GROUP = "None", "Single color", "By group"
LINE_PATTERNS = {name.capitalize(): style for name, style in LINE_STYLES.items() if name != "none"}
CENTER_MARKERS = {name: marker for name, marker in MARKERS.items() if name != "No symbol"}
DEFAULT_COLOR = "#1f77b4"

ELLIPSE_OPTIONS = {
    "Ellipse": (NONE, MEAN_REGION, DATA_ELLIPSE, HULL),
    "Ellipse grouping": (MATCH_POINTS, ALL_POINTS, SEPARATE_GROUP),
    "Ellipse group": "Optional",
    "Level (%)": 95.0,
    "Center marker": (NONE, *CENTER_MARKERS),
    "Center size": 6.0,
    "Fill": (NONE, SINGLE_COLOR, BY_GROUP),
    "Fill color": "Text",
    "Fill opacity (%)": 20.0,
    "Border": (BY_GROUP, SINGLE_COLOR, NONE),
    "Border color": "Text",
    "Border opacity (%)": 100.0,
    "Border width": 1.5,
    "Border style": tuple(LINE_PATTERNS),
}
ELLIPSE_TABS = {
    "Ellipse": ("Ellipse", "Ellipse grouping", "Ellipse group", "Level (%)", "Center marker", "Center size"),
    "Fill and border": ("Fill", "Fill color", "Fill opacity (%)", "Border", "Border color",
                        "Border opacity (%)", "Border width", "Border style"),
}


def ellipse_visibility(options):
    """Return availability of dependent dialog fields for the current choices."""
    overlay = options.get("Ellipse", NONE)
    enabled = overlay != NONE
    grouping = options.get("Ellipse grouping", MATCH_POINTS)
    fill = options.get("Fill", NONE)
    border = options.get("Border", BY_GROUP)
    center = options.get("Center marker", NONE)
    return {
        "Ellipse grouping": enabled,
        "Ellipse group": enabled and grouping == SEPARATE_GROUP,
        "Level (%)": overlay in (MEAN_REGION, DATA_ELLIPSE),
        "Center marker": enabled,
        "Center size": enabled and center != NONE,
        "Fill": enabled,
        "Fill color": enabled and fill == SINGLE_COLOR,
        "Fill opacity (%)": enabled and fill != NONE,
        "Border": enabled,
        "Border color": enabled and border == SINGLE_COLOR,
        "Border opacity (%)": enabled and border != NONE,
        "Border width": enabled and border != NONE,
        "Border style": enabled and border != NONE,
    }


def _choice(options, name):
    choices = ELLIPSE_OPTIONS[name]
    value = options.get(name, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Select a valid option for {name}.")
    return value


def _number(options, name):
    raw = options.get(name, ELLIPSE_OPTIONS[name])
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite number.") from None
    if not np.isfinite(value) or isinstance(raw, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite number.")
    return value


def _opacity(options, name):
    value = _number(options, name)
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100.")
    return value / 100


def _points(options, name):
    value = _number(options, name)
    if not 0.1 <= value <= 72:
        raise ValueError(f"{name} must be between 0.1 and 72 points.")
    return value


def _single_color(options, name):
    value = options.get(name, "")
    try:
        color = to_rgba(value.strip() or DEFAULT_COLOR) if isinstance(value, str) else None
    except ValueError:
        color = None
    if color is None or not color[3]:
        raise ValueError(f"{name} must be a visible color such as {DEFAULT_COLOR}.")
    return color[:3]


def _contour(points, overlay, level):
    if overlay == HULL:
        try:
            boundary = ConvexHull(points).vertices
        except QhullError:
            raise ValueError("A convex hull needs at least three non-collinear XY pairs.") from None
        return points[np.r_[boundary, boundary[0]]]
    with np.errstate(over="ignore", invalid="ignore"):
        contour = engine.ellipse(points, level / 100, "mean" if overlay == MEAN_REGION else "data")
    if not np.isfinite(contour).all():
        raise ValueError("The selected XY data exceed the numeric range for an ellipse.")
    return contour


def draw_confidence_overlays(axes, frame, options, point_colors):
    """Draw contours from source XY data and summarize each observed contour group.

    Point colors are keyed by the original grouping value, or "All" when
    points are ungrouped. Pass the source frame before any point-group filtering.
    """
    overlay = _choice(options, "Ellipse")
    if overlay == NONE:
        return pd.DataFrame()

    grouping = _choice(options, "Ellipse grouping")
    point_group = options.get("Group") or None
    group = point_group if grouping == MATCH_POINTS else None
    if grouping == SEPARATE_GROUP:
        group = options.get("Ellipse group")
        if not isinstance(group, str) or not group or group not in frame:
            raise ValueError("Choose an existing categorical column for the ellipse group.")
    if group is not None and (not isinstance(group, str) or group not in frame):
        raise ValueError("Choose an existing point group column.")
    x, y = options.get("X"), options.get("Y")
    if not all(isinstance(column, str) and column in frame for column in (x, y)):
        raise ValueError("Choose existing X and Y columns for the ellipse.")
    data = engine.complete(frame, [x, y], [group] if group else ())
    if data.empty:
        raise ValueError("No complete XY pairs with an ellipse group." if group else "No complete XY pairs.")

    level = _number(options, "Level (%)") if overlay != HULL else None
    if level is not None and not 0 < level < 100:
        raise ValueError("Level (%) must be strictly between 0 and 100.")
    fill, border = (_choice(options, key) for key in ("Fill", "Border"))
    fill_alpha = _opacity(options, "Fill opacity (%)") if fill != NONE else 0
    border_alpha = _opacity(options, "Border opacity (%)") if border != NONE else 0
    if not (fill_alpha or border_alpha):
        raise ValueError("Select a visible fill or border for the confidence overlay.")
    fill_color = _single_color(options, "Fill color") if fill == SINGLE_COLOR and fill_alpha else None
    border_color = _single_color(options, "Border color") if border == SINGLE_COLOR and border_alpha else None
    width = _points(options, "Border width") if border_alpha else None
    pattern = LINE_PATTERNS[_choice(options, "Border style")] if border_alpha else None
    marker = CENTER_MARKERS.get(_choice(options, "Center marker"))
    size = _points(options, "Center size") if marker else None

    groups = [("All", data)]
    if group:
        complete_groups = dict(iter(data.groupby(group, sort=False, observed=True)))
        empty = data.iloc[:0]
        groups = [(label, complete_groups.get(label, empty)) for label in frame[group].dropna().unique()]
    palette = rcParams["axes.prop_cycle"].by_key().get("color") or [DEFAULT_COLOR]
    separate_legend = grouping == SEPARATE_GROUP and group != point_group
    palette_offset = len(point_colors) if separate_legend else 0
    rows, centers, drawn = [], [], 0
    for index, (label, part) in enumerate(groups):
        points = part[[x, y]].to_numpy()
        with np.errstate(over="ignore", invalid="ignore"):
            center_x, center_y = points.mean(axis=0) if len(points) else (np.nan, np.nan)
        row = {"Group": str(label), "N": len(points), "Center X": center_x, "Center Y": center_y,
               "Overlay": overlay, "Level (%)": level, "Status": "Drawn"}
        rows.append(row)
        try:
            xy = _contour(points, overlay, level)
            if marker and not np.isfinite([center_x, center_y]).all():
                raise ValueError("The selected XY data exceed the numeric range for a center marker.")
        except np.linalg.LinAlgError:
            row["Status"] = "Unavailable: the XY covariance could not be calculated."
            continue
        except ValueError as error:
            row["Status"] = f"Unavailable: {error}"
            continue

        fallback = palette[(index + palette_offset) % len(palette)]
        group_color = point_colors.get(label, fallback) if group == point_group else fallback
        legend_label = f"{group} · {label}" if separate_legend else None
        if fill_alpha:
            axes.add_patch(Polygon(xy, closed=True, facecolor=fill_color or group_color,
                                   edgecolor="none", alpha=fill_alpha, zorder=.9,
                                   label=legend_label if not border_alpha else None))
        if border_alpha:
            axes.plot(*xy.T, color=border_color or group_color, linewidth=width, linestyle=pattern,
                      alpha=None if border_alpha == 1 else border_alpha, label=legend_label)
        if marker:
            centers.append((center_x, center_y, border_color or fill_color or group_color))
        drawn += 1
    if not drawn:
        raise ValueError(f"No confidence overlay could be drawn. {rows[0]['Status']}")
    for center_x, center_y, color in centers:
        axes.plot([center_x], [center_y], marker=marker, markersize=size, linestyle="none", color=color, zorder=3)
    if fill_alpha:
        axes.autoscale_view()
    return pd.DataFrame(rows)
