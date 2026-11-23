"""Confidence overlay settings, validation and scatter artists."""

import numpy as np
import pandas as pd
from matplotlib import rcParams
from matplotlib.colors import to_hex, to_rgba
from matplotlib.patches import Polygon
from scipy.spatial import ConvexHull, QhullError

from . import stats as engine
from .category_order import preferred_levels, ranks
from .graph_legend import typed_group_token
from .presentation import LINE_STYLES, MARKERS
from .processing import FieldError


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
GROUP_STYLES = "Ellipse group styles"
GROUP_FILL_FIELDS = ("Fill color", "Fill opacity (%)")
GROUP_BORDER_FIELDS = ("Border color", "Border opacity (%)", "Border width", "Border style")

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


def _opacity_percent(options, name):
    value = _number(options, name)
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100.")
    return value


def _opacity(options, name):
    return _opacity_percent(options, name) / 100


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


def ellipse_grouping_column(options):
    grouping = options.get("Ellipse grouping", MATCH_POINTS)
    if grouping == MATCH_POINTS:
        return options.get("Group") or None
    if grouping == SEPARATE_GROUP:
        return options.get("Ellipse group") or None
    return None


def normalize_ellipse_group_styles(styles):
    """Validate sparse overrides keyed by grouping column and typed value."""
    if styles is None:
        return {}
    if not isinstance(styles, dict) or len(styles) > 512:
        raise FieldError(GROUP_STYLES, "Expected an object with up to 512 ellipse group styles.")
    cleaned = {}
    count = 0
    for column, groups in styles.items():
        if not isinstance(column, str) or not column or not isinstance(groups, dict):
            raise FieldError(GROUP_STYLES, "Invalid ellipse group style column.")
        count += len(groups)
        if count > 512:
            raise FieldError(GROUP_STYLES, "Expected an object with up to 512 ellipse group styles.")
        records = {}
        for identity, settings in groups.items():
            if not isinstance(identity, str) or not identity or not isinstance(settings, dict):
                raise FieldError(GROUP_STYLES, "Invalid ellipse group style entry.")
            record = {}
            for field in settings:
                try:
                    if field in ("Fill color", "Border color"):
                        record[field] = to_hex(_single_color(settings, field))
                    elif field in ("Fill opacity (%)", "Border opacity (%)"):
                        record[field] = _opacity_percent(settings, field)
                    elif field == "Border width":
                        record[field] = _points(settings, field)
                    elif field == "Border style":
                        record[field] = _choice(settings, field)
                    else:
                        raise ValueError("Unknown ellipse group style field.")
                except ValueError as error:
                    raise FieldError(field, str(error)) from error
            if record:
                records[identity] = record
        if records:
            cleaned[column] = records
    return cleaned


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


def draw_confidence_overlays(axes, frame, options, point_colors, *, allow_unavailable=False):
    """Draw contours from source XY data and summarize each observed contour group.

    Point colors are keyed by the original grouping value, or "All" when
    points are ungrouped. Pass the source frame before any point-group filtering.
    PCA can keep the report when every group has insufficient geometry.
    """
    overlay = _choice(options, "Ellipse")
    if overlay == NONE:
        return pd.DataFrame()

    grouping = _choice(options, "Ellipse grouping")
    point_group = options.get("Group") or None
    group = ellipse_grouping_column(options)
    if grouping == SEPARATE_GROUP and (not isinstance(group, str) or group not in frame):
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
    styles = normalize_ellipse_group_styles(options.get(GROUP_STYLES)).get(group, {}) if group else {}
    fill_alpha = _opacity(options, "Fill opacity (%)") if fill != NONE else 0
    border_alpha = _opacity(options, "Border opacity (%)") if border != NONE else 0
    group_fill = fill == BY_GROUP and any(record.get("Fill opacity (%)", 0) for record in styles.values())
    group_border = border == BY_GROUP and any(record.get("Border opacity (%)", 0) for record in styles.values())
    if not (fill_alpha or border_alpha or group_fill or group_border):
        raise ValueError("Select a visible fill or border for the confidence overlay.")
    fill_color = _single_color(options, "Fill color") if fill == SINGLE_COLOR and fill_alpha else None
    border_color = _single_color(options, "Border color") if border == SINGLE_COLOR and border_alpha else None
    width = _points(options, "Border width") if border_alpha or group_border else None
    pattern = LINE_PATTERNS[_choice(options, "Border style")] if border_alpha or group_border else None
    marker = CENTER_MARKERS.get(_choice(options, "Center marker"))
    size = _points(options, "Center size") if marker else None

    groups = [("All", data)]
    if group:
        complete_groups = dict(iter(data.groupby(group, sort=False, observed=True)))
        empty = data.iloc[:0]
        levels = preferred_levels(frame[group].dropna().unique(), ranks(frame, group))
        groups = [(label, complete_groups.get(label, empty)) for label in levels]
    palette = rcParams["axes.prop_cycle"].by_key().get("color") or [DEFAULT_COLOR]
    separate_legend = grouping == SEPARATE_GROUP and group != point_group
    palette_offset = len(point_colors) if separate_legend else 0
    rows, centers, calculated = [], [], 0
    has_fill = False
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
        override = styles.get(typed_group_token(label), {}) if styles else {}
        face, edge = fill_color or group_color, border_color or group_color
        face_alpha, edge_alpha = fill_alpha, border_alpha
        edge_width, edge_pattern = width, pattern
        if fill == BY_GROUP:
            face = override.get("Fill color", face)
            if "Fill opacity (%)" in override:
                face_alpha = override["Fill opacity (%)"] / 100
        if border == BY_GROUP:
            edge = override.get("Border color", edge)
            if "Border opacity (%)" in override:
                edge_alpha = override["Border opacity (%)"] / 100
            edge_width = override.get("Border width", width)
            if "Border style" in override:
                edge_pattern = LINE_PATTERNS[override["Border style"]]
        if face_alpha:
            axes.add_patch(Polygon(xy, closed=True, facecolor=face,
                                   edgecolor="none", alpha=face_alpha, zorder=.9,
                                   label=legend_label if not edge_alpha else None))
            has_fill = True
        if edge_alpha:
            axes.plot(*xy.T, color=edge, linewidth=edge_width, linestyle=edge_pattern,
                      alpha=None if edge_alpha == 1 else edge_alpha, label=legend_label)
        if marker:
            custom_border = override.get("Border color") if border == BY_GROUP and edge_alpha else None
            custom_fill = override.get("Fill color") if fill == BY_GROUP and face_alpha else None
            centers.append((center_x, center_y, custom_border or custom_fill or border_color or fill_color or group_color))
        if not (face_alpha or edge_alpha or marker):
            row["Status"] = "Hidden by style"
        calculated += 1
    if not calculated and not allow_unavailable:
        raise ValueError(f"No confidence overlay could be drawn. {rows[0]['Status']}")
    for center_x, center_y, color in centers:
        axes.plot([center_x], [center_y], marker=marker, markersize=size, linestyle="none", color=color, zorder=3)
    if has_fill:
        axes.autoscale_view()
    return pd.DataFrame(rows)
