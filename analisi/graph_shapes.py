"""Native vector shapes (lines, rectangles, ellipses) stored with a graph's presentation."""
from math import isfinite
from sys import float_info
import uuid
import warnings

from matplotlib.colors import is_color_like, to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, FancyArrowPatch, Rectangle

from .probability_scale import PROBABILITY_SCALES

SHAPES = "shapes"
KINDS = ("line", "rectangle", "ellipse")
UNITS = ("axes", "data")
LINE_STYLES = ("solid", "dashed", "dotted", "dash-dot")
LAYERS = ("below", "above")
MAX_SHAPES = 100
SHAPE_KEYS = {"id", "kind", "units", "points", "stroke", "width", "line_style", "fill", "alpha", "layer"}
ARROW_KEYS = {"arrow_heads", "arrow_style", "arrow_size"}
OPTIONAL_KEYS = ARROW_KEYS | {"hatch", "hatch_color"}
ARROW_HEADS = ("none", "start", "end", "both")
ARROW_STYLES = ("open", "filled", "cap")
ARROW_SIZE = 10.0
HATCHES = ("none", "diagonal", "cross", "dots")
_HATCHES = {"none": None, "diagonal": "/", "cross": "xx", "dots": ".."}
_ARROWS = {
    "open": {"start": "<-", "end": "->", "both": "<->"},
    "filled": {"start": "<|-", "end": "-|>", "both": "<|-|>"},
    "cap": {"start": "]-,widthA=0.5,lengthA=0", "end": "-[,widthB=0.5,lengthB=0",
            "both": "|-|,widthA=0.5,widthB=0.5"},
}

_MPL_LINESTYLES = {
    "solid": "-",
    "dashed": "--",
    "dotted": ":",
    "dash-dot": "-.",
}


def _number(value):
    return type(value) in (int, float) and abs(value) <= float_info.max and isfinite(value)


def _valid_color(value):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped or len(stripped) > 40 or len(value) > 40 or stripped.lower() == "none":
        return False
    if not is_color_like(value):
        return False
    try:
        to_rgba(value)
    except (TypeError, ValueError):
        return False
    return True


def _canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value


def validate_shape(record):
    """Validate one shape record and return an independent canonical copy."""
    if (not isinstance(record, dict) or not SHAPE_KEYS.issubset(record)
            or record.keys() - SHAPE_KEYS - OPTIONAL_KEYS):
        raise ValueError("Invalid graph shape record.")
    shape_id = record["id"]
    if not _canonical_uuid(shape_id):
        raise ValueError("Each graph shape requires a canonical lowercase UUID.")
    kind = record["kind"]
    if kind not in KINDS:
        raise ValueError("Choose line, rectangle, or ellipse for the shape kind.")
    units = record["units"]
    if units not in UNITS:
        raise ValueError("Choose axes or data coordinates for the shape.")
    points = record["points"]
    if (not isinstance(points, (list, tuple)) or len(points) != 2
            or any(not isinstance(pt, (list, tuple)) or len(pt) != 2 or not all(map(_number, pt)) for pt in points)):
        raise ValueError("Enter two pairs of finite X and Y coordinates.")
    x1, y1 = points[0][0], points[0][1]
    x2, y2 = points[1][0], points[1][1]
    if units == "axes" and not all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
        raise ValueError("Plot fractions must be between 0 and 1.")
    if kind == "line":
        if x1 == x2 and y1 == y2:
            raise ValueError("A line shape must have two distinct endpoints.")
        canonical_points = [[x1, y1], [x2, y2]]
    else:
        if x1 == x2 or y1 == y2:
            raise ValueError("A rectangle or ellipse must have positive width and height.")
        canonical_points = [[min(x1, x2), min(y1, y2)], [max(x1, x2), max(y1, y2)]]
    stroke = record["stroke"]
    if not _valid_color(stroke):
        raise ValueError("Enter a valid stroke color.")
    width = record["width"]
    if not _number(width) or not 0.1 <= width <= 12:
        raise ValueError("Enter a stroke width between 0.1 and 12 points.")
    line_style = record["line_style"]
    if line_style not in LINE_STYLES:
        raise ValueError("Choose solid, dashed, dotted, or dash-dot for the shape line style.")
    fill = record["fill"]
    if kind == "line":
        if fill is not None:
            raise ValueError("Line shapes do not support a fill color.")
    elif fill is not None and not _valid_color(fill):
        raise ValueError("Enter a valid fill color or leave fill empty.")
    alpha = record["alpha"]
    if not _number(alpha) or not 0 <= alpha <= 1:
        raise ValueError("Enter an opacity between 0 and 1.")
    layer = record["layer"]
    if layer not in LAYERS:
        raise ValueError("Choose below or above for the shape layer.")
    if kind == "line":
        if {"hatch", "hatch_color"}.intersection(record):
            raise ValueError("Fill patterns require a rectangle or ellipse.")
        if record.get("arrow_heads", "none") not in ARROW_HEADS:
            raise ValueError("Choose none, start, end, or both for the arrowheads.")
        if record.get("arrow_style", "open") not in ARROW_STYLES:
            raise ValueError("Choose open, filled or cap for the arrowhead style.")
        size = record.get("arrow_size", ARROW_SIZE)
        if not _number(size) or not 3 <= size <= 40:
            raise ValueError("Enter an arrowhead size between 3 and 40 points.")
    else:
        if ARROW_KEYS.intersection(record):
            raise ValueError("Arrowhead settings require a line shape.")
        if record.get("hatch", "none") not in HATCHES:
            raise ValueError("Choose none, diagonal, cross, or dots for the fill pattern.")
        if "hatch_color" in record and not _valid_color(record["hatch_color"]):
            raise ValueError("Enter a valid pattern color.")
    canonical = {
        "id": shape_id,
        "kind": kind,
        "units": units,
        "points": canonical_points,
        "stroke": stroke,
        "width": width,
        "line_style": line_style,
        "fill": fill,
        "alpha": alpha,
        "layer": layer,
    }
    # Preserve the exact legacy dictionary: optional defaults are never inserted on load.
    canonical.update({key: record[key] for key in sorted(OPTIONAL_KEYS) if key in record})
    return canonical


def validate_shapes(records):
    """Validate a list of shape records (up to 100) and return a deep canonical copy."""
    if not isinstance(records, list):
        raise ValueError("Invalid graph shapes.")
    if len(records) > MAX_SHAPES:
        raise ValueError(f"Add up to {MAX_SHAPES} shapes per graph.")
    canonical = []
    seen_ids = set()
    for record in records:
        item = validate_shape(record)
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate shape ID {item['id']}.")
        seen_ids.add(item["id"])
        canonical.append(item)
    return canonical


def on_axis_domain(axes, record):
    """Return whether ``record`` is inside the valid numeric domain of ``axes``."""
    if record["units"] == "axes":
        return True
    points = record["points"]
    for index, scale in enumerate((axes.get_xscale(), axes.get_yscale())):
        coordinates = [point[index] for point in points]
        if scale == "log" and any(value <= 0 for value in coordinates):
            return False
        if scale in PROBABILITY_SCALES and any(not 0 < value < PROBABILITY_SCALES[scale] for value in coordinates):
            return False
    return True


def draw_shapes(axes, records):
    """Draw validated ``records`` on ``axes`` without altering data limits or autoscale."""
    saved_datalim = axes.dataLim.frozen()
    saved_ignore = axes.ignore_existing_data_limits
    saved_xlim = axes.get_xlim()
    saved_ylim = axes.get_ylim()
    saved_autox = axes.get_autoscalex_on()
    saved_autoy = axes.get_autoscaley_on()
    artists = []
    try:
        for index, record in enumerate(records):
            if not on_axis_domain(axes, record):
                warnings.warn(
                    f"Skipping out-of-domain graph shape {record['id']} on non-linear axis.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            transform = axes.transAxes if record["units"] == "axes" else axes.transData
            zorder = (1.0 if record["layer"] == "below" else 5.0) + index / 1000.0
            gid = f"tramastat-shape-{record['id']}"
            linestyle = _MPL_LINESTYLES[record["line_style"]]
            (x1, y1), (x2, y2) = record["points"]
            heads = record.get("arrow_heads", "none")
            if record["kind"] == "line" and heads != "none":
                head_style = record.get("arrow_style", "open")
                artist = FancyArrowPatch(
                    (x1, y1), (x2, y2), transform=transform,
                    arrowstyle=_ARROWS[head_style][heads],
                    mutation_scale=record.get("arrow_size", ARROW_SIZE),
                    shrinkA=0, shrinkB=0, edgecolor=record["stroke"],
                    facecolor=record["stroke"] if head_style == "filled" else "none",
                    linewidth=record["width"], linestyle=linestyle, alpha=record["alpha"],
                    zorder=zorder, gid=gid, clip_on=True, label="_nolegend_",
                )
                axes.add_patch(artist)
            elif record["kind"] == "line":
                artist = Line2D(
                    [x1, x2],
                    [y1, y2],
                    transform=transform,
                    color=record["stroke"],
                    linewidth=record["width"],
                    linestyle=linestyle,
                    alpha=record["alpha"],
                    zorder=zorder,
                    gid=gid,
                    clip_on=True,
                    label="_nolegend_",
                )
                axes.add_line(artist)
            elif record["kind"] == "rectangle":
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                facecolor = "none" if record["fill"] is None else record["fill"]
                artist = Rectangle(
                    (xmin, ymin),
                    xmax - xmin,
                    ymax - ymin,
                    transform=transform,
                    edgecolor=record["stroke"],
                    facecolor=facecolor,
                    fill=record["fill"] is not None,
                    hatch=_HATCHES[record.get("hatch", "none")],
                    linewidth=record["width"],
                    linestyle=linestyle,
                    alpha=record["alpha"],
                    zorder=zorder,
                    gid=gid,
                    clip_on=True,
                    label="_nolegend_",
                )
                axes.add_patch(artist)
            else:
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                facecolor = "none" if record["fill"] is None else record["fill"]
                artist = Ellipse(
                    ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0),
                    xmax - xmin,
                    ymax - ymin,
                    transform=transform,
                    edgecolor=record["stroke"],
                    facecolor=facecolor,
                    fill=record["fill"] is not None,
                    hatch=_HATCHES[record.get("hatch", "none")],
                    linewidth=record["width"],
                    linestyle=linestyle,
                    alpha=record["alpha"],
                    zorder=zorder,
                    gid=gid,
                    clip_on=True,
                    label="_nolegend_",
                )
                axes.add_patch(artist)
            if "hatch_color" in record:
                artist.set_hatchcolor(record["hatch_color"])
            artist.set_clip_path(axes.patch)
            artists.append(artist)
    finally:
        axes.dataLim.set(saved_datalim)
        axes.ignore_existing_data_limits = saved_ignore
        axes.set_xlim(saved_xlim, auto=saved_autox)
        axes.set_ylim(saved_ylim, auto=saved_autoy)
    return artists


def skipped_shapes(axes, records):
    """IDs of validated ``records`` that ``draw_shapes`` skips on ``axes`` because they are outside its domain."""
    return [record["id"] for record in records if not on_axis_domain(axes, record)]
