"""Graph formatting and multi-panel layout composition."""
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from math import ceil, floor, isfinite
import re
from sys import float_info

import numpy as np
from matplotlib import cbook, rcParams
from matplotlib.collections import PathCollection
from matplotlib.collections import Collection
from matplotlib.colors import is_color_like, to_rgba, to_rgba_array
from matplotlib.container import BarContainer, ErrorbarContainer
from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.markers import MarkerStyle
from matplotlib.mathtext import MathTextParser
from matplotlib.ticker import (AutoMinorLocator, FixedFormatter, FuncFormatter, Locator,
                               MaxNLocator, NullLocator, StrMethodFormatter)
from matplotlib.transforms import IdentityTransform

from .probability_scale import PROBABILITY_SCALES
from .qq_panels import (PANEL_KEY, POINTS_ATTR, POINTS_KEY, REFERENCE_ATTR, REFERENCE_KEY,
                        normalize_panel_styles, panel_axes)
from .graph_annotations import ANNOTATIONS, draw_annotations, validate_annotations
from .graph_shapes import SHAPES, draw_shapes, validate_shapes
from .layout_geometry import (AUTO_PAPER, LABEL_PAD, LABEL_SIZE, PAPER_SIZES, PT, WHITE, layout_frame, page_ink,
                              page_size, panel_boxes)


@dataclass
class Layout:
    name: str
    columns: int
    panels: list[tuple[str, int]]
    paper: str = AUTO_PAPER
    background: str = WHITE

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 160:
            raise ValueError("Enter a layout name of up to 160 characters.")
        if type(self.columns) is not int or not 1 <= self.columns <= 4 or not 1 <= len(self.panels) <= 12:
            raise ValueError("A layout needs 1 to 12 panels in 1 to 4 columns.")
        if any(not isinstance(title, str) or type(index) is not int or index < 0
               for title, index in self.panels):
            raise ValueError("Invalid layout panel reference.")
        if not isinstance(self.paper, str) or self.paper not in PAPER_SIZES:
            raise ValueError("Choose a layout paper size.")
        if not isinstance(self.background, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background):
            raise ValueError("Use a six-digit hex colour for the layout background.")


SCALES = ("linear", "log", *PROBABILITY_SCALES)
LEGEND_LOCATIONS = ("hidden", "best", "upper right", "upper left", "lower left",
                    "lower right", "center left", "center right", "lower center", "upper center")
FONT_FAMILIES = ("sans-serif", "serif", "monospace")
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-.", "none": "None"}
MARKERS = {"Circle": "o", "Square": "s", "Diamond": "D", "Triangle up": "^", "Triangle down": "v",
           "Plus": "+", "Cross": "x", "Star": "*", "No symbol": "none"}
FONT_SIZES = ("title_size", "label_size", "tick_size", "legend_size")
LINE_FIELDS = {"color", "line_style", "width", "marker", "marker_size", "marker_color", "label"}
SERIES_FIELDS = {
    "line": LINE_FIELDS,
    "errorbar": LINE_FIELDS,
    "scatter": {"color", "marker", "marker_size", "label"},
    "bar": {"color", "label"},
    # Native XY series keep draw style and side on the recipe; the style dict formats line and symbol.
    "xy": LINE_FIELDS,
}
SERIES_KEY = re.compile(r"(line|errorbar|scatter|bar|xy):[1-9][0-9]*:.*", re.DOTALL)
# Box and violin groups are keyed by their source identity, not by their position in the plot.
GROUP_FIELDS = {"color", "visible"}
GROUP_KEY = re.compile(r"(box|violin|pair|trajectory|trajectory-mean):.+", re.DOTALL)
MAX_GROUP_STYLES = 512
MAX_MAJOR_TICKS = 200
MAX_MINOR_TICKS = 800
MATH_TEXT = MathTextParser("path")


def _record(value, keys, message):
    if not isinstance(value, dict) or value.keys() - keys:
        raise ValueError(message)
    return value


def _number(value):
    if type(value) not in (int, float):
        return False
    # Reject integers too large to represent as a Matplotlib coordinate.
    return abs(value) <= float_info.max and isfinite(value)


def _text(value):
    return isinstance(value, str) and len(value) <= 160


def _check_math_text(value):
    if cbook.is_math_text(value):
        try:
            MATH_TEXT.parse(value)
        except ValueError as error:
            raise ValueError(f"Invalid math notation in graph label {value!r}.") from error


def _color(value):
    return isinstance(value, str) and len(value) <= 40 and is_color_like(value)


def _tick_domain(limits, step, start, subdivisions):
    low, high = sorted(limits)
    first, last = (low - start) / step, (high - start) / step
    return (isfinite(first) and isfinite(last) and abs(first) < 1e14 and abs(last) < 1e14
            and last - first <= min(MAX_MAJOR_TICKS - 1, MAX_MINOR_TICKS / max(1, subdivisions)))


def _check_axis_options(options, scale):
    _record(options, {"min", "max", "step", "start", "minor", "decimals"}, "Invalid axis options.")
    if any(not _number(value) for value in options.values()):
        raise ValueError("Enter finite numbers for axis options.")
    if ("min" in options) != ("max" in options):
        raise ValueError("Enter both axis limits, or leave both blank for an automatic range.")
    limits = (options["min"], options["max"]) if "min" in options else None
    if limits and (limits[0] >= limits[1] or not _number(limits[1] - limits[0])):
        raise ValueError("The axis minimum must be smaller than the maximum and the span must be finite.")
    if limits and scale == "linear" and Locator().nonsingular(*limits) != limits:
        raise ValueError("These axis limits are too close together to render.")
    if "minor" in options and (type(options["minor"]) is not int or options["minor"] not in (0, *range(2, 11))):
        raise ValueError("Use 0 to hide minor ticks, or enter 2 to 10 divisions per major interval.")
    if "decimals" in options and (type(options["decimals"]) is not int or not 0 <= options["decimals"] <= 10):
        raise ValueError("Enter 0 to 10 decimal places.")
    if "start" in options and "step" not in options:
        raise ValueError("Enter a major interval to choose its starting value.")
    if "step" in options:
        if options["step"] <= 0:
            raise ValueError("The major interval must be positive.")
        if limits and not _tick_domain(limits, options["step"], options.get("start", 0), options.get("minor", 0)):
            raise ValueError("The major interval places too many ticks or is too small at this range.")
    if scale in PROBABILITY_SCALES:
        divisor = PROBABILITY_SCALES[scale]
        if limits and not 0 < limits[0] < limits[1] < divisor:
            raise ValueError(f"Probability limits must be strictly between 0 and {divisor:g}.")
        if set(options) - {"min", "max"}:
            raise ValueError("Probability axes use fixed tick positions and labels.")
    if scale == "log":
        if limits and limits[0] <= 0:
            raise ValueError("Logarithmic axis limits must be strictly positive.")
        if "step" in options or options.get("minor", 0):
            raise ValueError("Logarithmic axes use logarithmic tick spacing.")


def _check_series(key, options):
    match = SERIES_KEY.fullmatch(key) if isinstance(key, str) and len(key) <= 1024 else None
    if match is None:
        raise ValueError("Invalid graph series reference.")
    kind = match[1]
    _record(options, SERIES_FIELDS[kind], "This setting is not available for the selected series.")
    for name, value in options.items():
        if name in {"color", "marker_color"} and not _color(value):
            raise ValueError("Enter a valid color, for example #2866ae.")
        if name in {"width", "marker_size"} and (not _number(value) or not 0.1 <= value <= 72):
            raise ValueError("Enter line widths and symbol sizes between 0.1 and 72 points.")
        if name == "line_style" and value not in tuple(LINE_STYLES):
            raise ValueError("Choose a valid line style.")
        if name == "marker" and (value not in tuple(MARKERS.values()) or (kind == "scatter" and value == "none")):
            raise ValueError("Choose a valid symbol.")
        if name == "label" and (not _text(value) or value.startswith("_")):
            raise ValueError("Enter a series legend label of up to 160 characters that does not start with an underscore.")


def _check_groups(groups):
    if not isinstance(groups, dict) or len(groups) > MAX_GROUP_STYLES:
        raise ValueError(f"Format up to {MAX_GROUP_STYLES} box or violin groups.")
    for key, options in groups.items():
        if not isinstance(key, str) or len(key) > 1024 or GROUP_KEY.fullmatch(key) is None:
            raise ValueError("Invalid graph group reference.")
        _record(options, GROUP_FIELDS, "This setting is not available for box and violin groups.")
        if "color" in options and not _color(options["color"]):
            raise ValueError("Enter a valid color, for example #2866ae.")
        if "visible" in options and type(options["visible"]) is not bool:
            raise ValueError("Invalid group visibility.")


def validated_style(style):
    _record(style, {"title", "xlabel", "ylabel", "xscale", "yscale", "grid", "grid_minor",
                    "accent", "axis", "frame", "font_family", *FONT_SIZES, "legend", "series",
                    "groups", "reference_lines", ANNOTATIONS, SHAPES, PANEL_KEY}, "Invalid graph style.")
    for key in ("title", "xlabel", "ylabel"):
        if key in style and not _text(style[key]):
            raise ValueError("Graph labels are limited to 160 characters.")
    if any(style.get(key, "linear") not in SCALES for key in ("xscale", "yscale")):
        raise ValueError("Choose a supported axis scale.")
    for key in ("grid", "grid_minor"):
        if key in style and type(style[key]) is not bool:
            raise ValueError("Invalid grid setting.")
    if "accent" in style:
        # Legacy styles accepted any Matplotlib color, including RGB arrays.
        try:
            valid_accent = is_color_like(style["accent"])
        except (TypeError, ValueError, OverflowError):
            valid_accent = False
        if not valid_accent:
            raise ValueError("Enter a valid color, for example #2866ae.")
    if style.get("frame", "open") not in ("open", "box"):
        raise ValueError("Invalid graph frame.")
    if style.get("font_family", FONT_FAMILIES[0]) not in FONT_FAMILIES:
        raise ValueError("Choose a valid font family.")
    for key in FONT_SIZES:
        if key in style and (not _number(style[key]) or not 4 <= style[key] <= 72):
            raise ValueError("Enter font sizes between 4 and 72 points.")
    if "legend" in style and style["legend"] not in LEGEND_LOCATIONS:
        raise ValueError("Choose a valid legend position.")
    axes = _record(style.get("axis", {}), {"x", "y"}, "Invalid graph axis.")
    for dimension, options in axes.items():
        _check_axis_options(options, style.get(dimension + "scale"))
    series = style.get("series", {})
    if not isinstance(series, dict) or len(series) > 256:
        raise ValueError("Format up to 256 individual series.")
    for key, options in series.items():
        _check_series(key, options)
    _check_groups(style.get("groups", {}))
    validate_annotations(style.get(ANNOTATIONS, []))
    validate_shapes(style.get(SHAPES, []))
    if PANEL_KEY in style:
        normalize_panel_styles(style[PANEL_KEY])
    refs = style.get("reference_lines", [])
    if not isinstance(refs, list) or len(refs) > 12:
        raise ValueError("Add up to 12 reference lines per graph.")
    for ref in refs:
        _record(ref, {"axis", "value", "label"}, "Invalid reference line.")
        label = ref.get("label", "")
        if (ref.get("axis") not in ("x", "y") or not _number(ref.get("value"))
                or not _text(label) or len(label.splitlines()) > 1):
            raise ValueError("Each reference needs an axis, a finite value and an optional label up to 160 characters.")
    return style


@dataclass
class GraphSeries:
    key: str
    name: str
    kind: str
    artist: object

    @property
    def fields(self):
        if self.kind == "errorbar" and self.artist.lines[0] is None:
            return {"color", "label"}
        if self.kind == "scatter" and str(self.artist.get_gid() or "").startswith("bubble:"):
            # Bubble areas encode the Size column, so a uniform symbol size is not offered.
            return SERIES_FIELDS["scatter"] - {"marker_size"}
        return SERIES_FIELDS[self.kind]


def active_series_fields(axes, series, draw_style=None):
    """Return the series fields active for the current draw structure of ``series``."""
    if series is None:
        return set()
    if series.kind != "xy":
        return set(series.fields)
    if draw_style is not None:
        has_line = draw_style in {"Line", "Line and points"}
        has_marker = draw_style in {"Points", "Line and points"}
    else:
        defaults = getattr(axes, "_tramastat_defaults", None) if axes is not None else None
        if defaults and series.key in defaults.get("series", {}):
            _, original = defaults["series"][series.key]
            linestyle, marker = original[1], original[3]
        else:
            linestyle, marker = series.artist.get_linestyle(), series.artist.get_marker()
        has_line = linestyle not in ("None", "none", None, "")
        has_marker = marker not in ("None", "none", None, "")
    active = {"color", "label"}
    if has_line:
        active |= {"line_style", "width"}
    if has_marker:
        active |= {"marker", "marker_size", "marker_color"}
    return active


def _xy_lines(axes):
    """Native XY artists on every axes, in recipe order when the plot recorded it."""
    figure = getattr(axes, "figure", None)
    found = []
    if figure is not None:
        for other in figure.axes:
            found.extend(artist for artist in other.lines if str(artist.get_gid() or "").startswith("xy:1:"))
    order = getattr(axes, "_tramastat_xy_order", None)
    if order:
        by_gid = {artist.get_gid(): artist for artist in found}
        found = [by_gid[gid] for gid in order if gid in by_gid]
    return found


def _series(axes):
    xy_lines = _xy_lines(axes)
    xy_ids = {id(artist) for artist in xy_lines}
    errorbars = [artist for artist in axes.containers if isinstance(artist, ErrorbarContainer)]
    error_lines = {line for center, caps, _ in (artist.lines for artist in errorbars)
                   for line in (center, *caps) if line is not None}
    artists = [("line", artist) for artist in axes.lines
               if id(artist) not in xy_ids and not str(artist.get_gid() or "").startswith("tramastat-shape-")]
    artists.extend(("errorbar", artist) for artist in errorbars)
    artists.extend(("scatter", artist) for artist in axes.collections if isinstance(artist, PathCollection))
    artists.extend(("bar", artist) for artist in axes.containers if isinstance(artist, BarContainer) and artist.patches)
    counts = {}
    for kind, artist in artists:
        label = artist.get_label() or ""
        if label.startswith("_"):
            label = ""
        identity = kind, label
        number = counts[identity] = counts.get(identity, 0) + 1
        if kind == "line" and artist in error_lines:
            # Count the former entries so other unlabeled line keys stay stable.
            continue
        caption = "Error bars" if kind == "errorbar" else kind.capitalize()
        name = f"{caption} · {label} ({number})" if label else f"{caption} {number}"
        key = f"{kind}:{number}:{label}"
        if len(key) <= 1024:
            yield GraphSeries(key, name, kind, artist)
    for artist in xy_lines:
        column = str(artist.get_gid())[len("xy:1:"):]
        key = artist.get_gid()
        if isinstance(key, str) and len(key) <= 1024:
            yield GraphSeries(key, column, "xy", artist)


@dataclass
class GraphGroup:
    """One box or violin: every artist drawn for a group, with the role that decides how it is colored."""
    key: str
    name: str
    kind: str
    x: float
    artists: list


def register_groups(axes, groups):
    axes._tramastat_groups = list(groups)


def _artist_state(artist):
    if isinstance(artist, Line2D):
        state = {"color": artist.get_color(), "markerfacecolor": artist.get_markerfacecolor(),
                 "markeredgecolor": artist.get_markeredgecolor()}
    elif isinstance(artist, Collection):
        state = {"facecolor": artist.get_facecolor().copy(), "edgecolor": artist.get_edgecolor().copy()}
    elif isinstance(artist, Patch):
        state = {"facecolor": artist.get_facecolor(), "edgecolor": artist.get_edgecolor()}
    else:
        state = {}
    return state, artist.get_visible()


def _group_defaults(group):
    return [_artist_state(artist) for artist, _ in group.artists]


def _paint(artist, role, state, color):
    if role == "fill":
        # The translucent fill keeps its own alpha; the outline takes the full color.
        alpha = to_rgba_array(state["facecolor"])[0][3]
        artist.set(facecolor=to_rgba(color, alpha), edgecolor=color)
    elif role == "marker":
        artist.set(color=color, markeredgecolor=color)
    elif role == "point":
        artist.set_facecolor(color)
    elif role == "mean":
        artist.set_edgecolor(color)
    elif isinstance(artist, Line2D) and artist.get_marker() not in (None, "None", "", "none"):
        artist.set(color=color, markerfacecolor=color, markeredgecolor=color)
    else:
        artist.set_color(color)


def _apply_group(group, defaults, options):
    shown = options.get("visible", True)
    for (artist, role), (state, visible) in zip(group.artists, defaults, strict=True):
        artist.set(**state)
        if "color" in options:
            _paint(artist, role, state, options["color"])
        artist.set_visible(visible and shown)


def graph_groups(axes):
    """Return the box and violin groups in plot order, or an empty list for other graphs."""
    defaults = getattr(axes, "_tramastat_defaults", None)
    if defaults:
        return [group for group, _ in defaults["groups"].values()]
    return list(getattr(axes, "_tramastat_groups", ()))


def _line_defaults(artist):
    return (artist.get_color(), artist.get_linestyle(), artist.get_linewidth(), artist.get_marker(),
            artist.get_markersize(), artist.get_markerfacecolor(), artist.get_markeredgecolor(), artist.get_label())


def _series_defaults(series):
    artist = series.artist
    if series.kind in {"line", "xy"}:
        return _line_defaults(artist)
    if series.kind == "errorbar":
        center, caps, whiskers = artist.lines
        return (_line_defaults(center) if center is not None else None,
                [(cap.get_color(), cap.get_markeredgecolor()) for cap in caps],
                [whisker.get_colors().copy() for whisker in whiskers], artist.get_label())
    if series.kind == "scatter":
        return (artist.get_facecolors().copy(), artist.get_edgecolors().copy(), artist.get_paths(),
                artist.get_sizes().copy(), artist.get_label())
    return ([patch.get_facecolor() for patch in artist.patches], artist.get_label())


def graph_series(axes):
    """Return styleable artists using their original identities."""
    defaults = getattr(axes, "_tramastat_defaults", None)
    return [series for series, _ in defaults["series"].values()] if defaults else list(_series(axes))


def _axis_defaults(axes, dimension):
    axis = getattr(axes, dimension + "axis")
    return {
        "limits": getattr(axes, f"get_{dimension}lim")(),
        "auto": getattr(axes, f"get_autoscale{dimension}_on")(),
        "scale": axis.get_scale(),
        "major_locator": axis.get_major_locator(), "minor_locator": axis.get_minor_locator(),
        "major_formatter": axis.get_major_formatter(), "minor_formatter": axis.get_minor_formatter(),
        "major_params": axis.get_tick_params("major"), "minor_params": axis.get_tick_params("minor"),
    }


def _capture_defaults(axes):
    legend = axes.get_legend()
    return {
        "axes": {dimension: _axis_defaults(axes, dimension) for dimension in ("x", "y")},
        "texts": [(artist, artist.get_text(), artist.get_fontproperties().copy())
                  for artist in (axes.title, axes.xaxis.label, axes.yaxis.label)],
        "axisbelow": axes.get_axisbelow(),
        "spines": {name: spine.get_visible() for name, spine in axes.spines.items()},
        "series": {series.key: (series, _series_defaults(series)) for series in _series(axes)},
        "groups": {group.key: (group, _group_defaults(group)) for group in getattr(axes, "_tramastat_groups", ())},
        "legend": legend,
        "legend_fonts": [(artist, artist.get_fontproperties().copy())
                         for artist in [legend.get_title(), *legend.get_texts()]] if legend else [],
    }


def axis_has_numeric_ticks(axes, dimension):
    if (dimension in getattr(axes, "_tramastat_numeric_axes", ())
            or getattr(axes, dimension + "axis").get_scale() in PROBABILITY_SCALES):
        return True
    defaults = getattr(axes, "_tramastat_defaults", None)
    axis = getattr(axes, dimension + "axis")
    formatter = defaults["axes"][dimension]["major_formatter"] if defaults else axis.get_major_formatter()
    # The workbench uses fixed ticks with text labels on categorical axes.
    return not isinstance(formatter, (FixedFormatter, FuncFormatter)) and axis.get_units() is None


def zero_baseline_axes(axes):
    """Value axes whose bars are stacked from zero and cannot be logarithmic."""
    return getattr(axes, "_tramastat_zero_baseline", ())


def validate_graph_style(axes, style):
    validated_style(style)
    for key in ("title", "xlabel", "ylabel"):
        if key in style:
            _check_math_text(style[key])
    series_options = style.get("series", {})
    for options in series_options.values():
        _check_math_text(options.get("label", ""))
    if series_options:
        for series in graph_series(axes):
            if series_options.get(series.key, {}).keys() - series.fields:
                raise ValueError(f"This setting is not available for {series.name}.")
    for ref in style.get("reference_lines", []):
        _check_math_text(ref.get("label", ""))
    defaults = getattr(axes, "_tramastat_defaults", None)
    for dimension in ("x", "y"):
        axis = getattr(axes, dimension + "axis")
        baseline = defaults["axes"][dimension] if defaults else _axis_defaults(axes, dimension)
        scale = style.get(dimension + "scale", baseline["scale"])
        options = style.get("axis", {}).get(dimension, {})
        refs = [ref for ref in style.get("reference_lines", []) if ref["axis"] == dimension]
        _check_axis_options(options, scale)
        if (options or refs or scale != baseline["scale"]) and not axis_has_numeric_ticks(axes, dimension):
            raise ValueError(f"The {dimension.upper()} axis needs numeric ticks for these settings.")
        if scale != "linear" and dimension in zero_baseline_axes(axes):
            name = "logarithmic" if scale == "log" else "probability"
            raise ValueError(f"Stacked bars start at zero, so the {dimension.upper()} axis cannot use a {name} "
                             "scale. Choose linear, or change Placement of groups in Graph settings.")
        if scale == "log" and dimension + "scale" in style and (axis.get_data_interval() <= 0).any():
            raise ValueError("A logarithmic axis requires strictly positive data.")
        if scale == "log" and any(ref["value"] <= 0 for ref in refs):
            raise ValueError("A reference on a logarithmic axis must be strictly positive.")
        if scale in PROBABILITY_SCALES:
            divisor = PROBABILITY_SCALES[scale]
            low, high = axis.get_data_interval()
            if dimension + "scale" in style and np.isfinite([low, high]).all() and (low < 0 or high > divisor):
                raise ValueError(f"A probability axis accepts data from 0 to {divisor:g}.")
            if any(not 0 < ref["value"] < divisor for ref in refs):
                raise ValueError("A probability reference must be inside the probability range.")
        if "step" in options:
            limits = (options["min"], options["max"]) if "min" in options else baseline["limits"]
            if not _tick_domain(limits, options["step"], options.get("start", 0), options.get("minor", 0)):
                raise ValueError("The major interval places too many ticks or is too small at this range.")
    return style


class _SpacedLocator(Locator):
    def __init__(self, step, start, subdivisions):
        self.step = step
        self.start = start
        self.subdivisions = subdivisions
        self.fallback = MaxNLocator(nbins=8)

    def __call__(self):
        return self.tick_values(*self.axis.get_view_interval())

    def tick_values(self, vmin, vmax):
        # Navigation can zoom out far beyond the range validated by the dialog.
        if not _tick_domain((vmin, vmax), self.step, self.start, self.subdivisions):
            return self.fallback.tick_values(vmin, vmax)
        low, high = sorted((vmin, vmax))
        first, last = (low - self.start) / self.step, (high - self.start) / self.step
        epsilon = max(1e-10, abs(first) * 3e-16, abs(last) * 3e-16)
        ticks = self.start + np.arange(ceil(first - epsilon), floor(last + epsilon) + 1) * self.step
        # A narrow zoom between ticks should retain a useful axis.
        return ticks if len(ticks) else self.fallback.tick_values(vmin, vmax)


def _apply_axis(axes, dimension, style, previous, defaults):
    axis = getattr(axes, dimension + "axis")
    scale_key = dimension + "scale"
    scale = style.get(scale_key, defaults["scale"])
    options = style.get("axis", {}).get(dimension, {})
    prior_options = previous.get("axis", {}).get(dimension, {})
    if options != prior_options or scale != previous.get(scale_key, defaults["scale"]):
        getattr(axes, f"set_{dimension}scale")(scale)
        if scale == defaults["scale"]:
            for which in ("major", "minor"):
                getattr(axis, f"set_{which}_locator")(defaults[f"{which}_locator"])
                getattr(axis, f"set_{which}_formatter")(defaults[f"{which}_formatter"])
        set_limits = getattr(axes, f"set_{dimension}lim")
        if "min" in options:
            set_limits(options["min"], options["max"])
        elif scale == defaults["scale"]:
            set_limits(defaults["limits"], auto=defaults["auto"])
        else:
            getattr(axes, f"set_autoscale{dimension}_on")(True)
            axes.autoscale_view(scalex=dimension == "x", scaley=dimension == "y")
        if "step" in options:
            axis.set_major_locator(_SpacedLocator(options["step"], options.get("start", 0), options.get("minor", 0)))
        if "minor" in options:
            axis.set_minor_locator(AutoMinorLocator(options["minor"]) if options["minor"] else NullLocator())
        if "decimals" in options:
            axis.set_major_formatter(StrMethodFormatter("{x:." + str(options["decimals"]) + "f}"))
    for which in ("major", "minor"):
        original = defaults[f"{which}_params"]
        if any(key in style or key in previous for key in ("tick_size", "font_family")):
            labelsize = original.get("labelsize", rcParams[f"{dimension}tick.labelsize"])
            axis.set_tick_params(
                which=which, labelsize=style.get("tick_size", labelsize),
                labelfontfamily=style.get("font_family", original.get("labelfontfamily")),
            )
        grid_key = "grid" if which == "major" else "grid_minor"
        if grid_key in style:
            enabled = style[grid_key]
            axis.grid(enabled, which=which, **({"alpha": .25 if which == "major" else .13} if enabled else {}))
        elif grid_key in previous:
            axis.set_tick_params(which=which, gridOn=original.get("gridOn", False),
                                 grid_alpha=original.get("grid_alpha", rcParams["grid.alpha"]))


def _apply_line(artist, defaults, options):
    color, linestyle, width, marker, size, face, edge, label = defaults
    marker_face = options.get("color", color) if np.array_equal(face, color) else face
    marker_edge = options.get("color", color) if np.array_equal(edge, color) else edge
    artist.set(
        color=options.get("color", color), linestyle=LINE_STYLES.get(options.get("line_style"), linestyle),
        linewidth=options.get("width", width), marker=options.get("marker", marker),
        markersize=options.get("marker_size", size), markerfacecolor=options.get("marker_color", marker_face),
        markeredgecolor=options.get("marker_color", marker_edge), label=options.get("label", label),
    )


def _apply_series(series, defaults, options):
    artist = series.artist
    if series.kind == "xy":
        has_line = defaults[1] not in ("None", "none", None, "")
        has_marker = defaults[3] not in ("None", "none", None, "")
        xy_options = {
            key: value for key, value in options.items()
            if (has_line or key not in {"line_style", "width"})
            and (has_marker or key not in {"marker", "marker_size", "marker_color"})
        }
        _apply_line(artist, defaults, xy_options)
        return
    if series.kind == "line":
        _apply_line(artist, defaults, options)
    elif series.kind == "errorbar":
        center, caps, whiskers = artist.lines
        center_defaults, cap_colors, whisker_colors, label = defaults
        if center is not None:
            _apply_line(center, center_defaults, {key: value for key, value in options.items() if key != "label"})
        for cap, (color, edge) in zip(caps, cap_colors, strict=True):
            cap.set(color=options.get("color", color), markeredgecolor=options.get("color", edge))
        for whisker, colors in zip(whiskers, whisker_colors, strict=True):
            whisker.set_color(options.get("color", colors))
        artist.set_label(options.get("label", label))
    elif series.kind == "scatter":
        face, edge, paths, sizes, label = defaults
        if "marker" in options:
            marker = MarkerStyle(options["marker"])
            paths = [marker.get_path().transformed(marker.get_transform())]
        artist.set_paths(paths)
        artist.set_sizes([options["marker_size"] ** 2] if "marker_size" in options else sizes)
        artist.set(facecolor=options.get("color", face), edgecolor=options.get("color", edge),
                   label=options.get("label", label))
    else:
        colors, label = defaults
        for patch, color in zip(artist.patches, colors, strict=True):
            patch.set_facecolor(options.get("color", color))
        artist.set_label(options.get("label", label))


def _reference_artists(axes, references):
    artists = []
    for ref in references:
        value = ref["value"]
        vertical = ref["axis"] == "x"
        transform = axes.get_xaxis_transform() if vertical else axes.get_yaxis_transform()
        x, y = ([value, value], [0, 1]) if vertical else ([0, 1], [value, value])
        line = Line2D(x, y, transform=transform, color="#657486", linestyle="--", linewidth=1, zorder=1.8)
        # add_artist keeps reference lines out of the analysis data range.
        axes.add_artist(line)
        artists.append(line)
        if ref.get("label"):
            position = (value, 1) if vertical else (1, value)
            offset = (4, -4) if vertical else (-4, 4)
            artists.append(axes.annotate(ref["label"], position, xycoords=transform, xytext=offset,
                                         textcoords="offset points", annotation_clip=True,
                                         va="top" if vertical else "bottom",
                                         ha="left" if vertical else "right", color="#46576b", fontsize=9))
    return artists


def _apply_legend(axes, style, defaults, series_changed):
    original = defaults["legend"]
    location = style.get("legend")
    for artist, font in defaults["legend_fonts"]:
        artist.set_fontproperties(font)
    axes.legend_ = original
    if location == "hidden":
        axes.legend_ = None
        return
    if location or (series_changed and original):
        handles, labels = axes.get_legend_handles_labels()
        if handles:
            # A legend placed outside the axes keeps its anchor when only the series change.
            anchor = {}
            if not location and original and original._bbox_to_anchor is not None:
                anchor = {"bbox_to_anchor": original.get_bbox_to_anchor(), "bbox_transform": IdentityTransform()}
            axes.legend(handles, labels, loc=location or original._loc,
                        title=original.get_title().get_text() if original else None, **anchor)
    legend = axes.get_legend()
    if legend:
        for artist in [legend.get_title(), *legend.get_texts()]:
            if "font_family" in style:
                artist.set_fontfamily(style["font_family"])
            if "legend_size" in style:
                artist.set_fontsize(style["legend_size"])


def _apply_xy_legend(axes, style):
    """One legend, in Y-column order, including series that live on the twin axes.

    ``_apply_legend`` only sees artists on the primary axes. Rebuilding here
    keeps a color change from dropping the right-axis entries or the twin.
    """
    order = getattr(axes, "_tramastat_xy_order", None)
    if not order:
        return
    by_gid = {}
    for other in axes.figure.axes:
        for artist in other.lines:
            gid = artist.get_gid()
            if gid:
                by_gid[gid] = artist
    handles = []
    for gid in order:
        artist = by_gid.get(gid)
        if artist is None:
            continue
        y_values = np.asarray(artist.get_ydata(), dtype=float)
        label = artist.get_label() or ""
        if not np.isfinite(y_values).any() or not label or label.startswith("_"):
            continue
        handles.append(artist)
    if style.get("legend") == "hidden" or not handles:
        axes.legend_ = None
        return
    existing = axes.get_legend()
    location = style.get("legend") or (existing._loc if existing is not None else "best")
    axes.legend(handles, [artist.get_label() for artist in handles], loc=location)
    legend = axes.get_legend()
    if legend is None:
        return
    for artist in [legend.get_title(), *legend.get_texts()]:
        if "font_family" in style:
            artist.set_fontfamily(style["font_family"])
        if "legend_size" in style:
            artist.set_fontsize(style["legend_size"])


def _capture_qq_panel_defaults(axes):
    legend = axes.get_legend()
    points = getattr(axes, POINTS_ATTR, None)
    reference = getattr(axes, REFERENCE_ATTR, None)
    legend_font = legend.get_texts()[0].get_fontproperties().copy() if (legend is not None and legend.get_texts()) else None
    legend_title = legend.get_title().get_text() if legend is not None else ""
    return {
        "texts": [(artist, artist.get_text(), artist.get_fontproperties().copy(), artist.get_parse_math())
                  for artist in (axes.title, axes.xaxis.label, axes.yaxis.label)],
        "xlim": axes.get_xlim(),
        "ylim": axes.get_ylim(),
        "autox": axes.get_autoscalex_on(),
        "autoy": axes.get_autoscaley_on(),
        "legend": legend,
        "legend_visible": legend.get_visible() if legend is not None else False,
        "legend_loc": getattr(legend, "_loc", "upper left") if legend is not None else "upper left",
        "legend_frameon": legend.get_frame_on() if legend is not None else False,
        "legend_title": legend_title or None,
        "legend_font": legend_font,
        "points": None if points is None else {
            "visible": bool(points.get_visible()),
            "paths": [path.copy() for path in points.get_paths()],
            "sizes": np.array(points.get_sizes(), copy=True),
            "facecolors": np.array(points.get_facecolors(), copy=True),
            "edgecolors": np.array(points.get_edgecolors(), copy=True),
            "linewidths": np.array(points.get_linewidths(), copy=True),
            "alpha": points.get_alpha(),
        },
        "reference_line": None if reference is None else {
            "visible": bool(reference.get_visible()),
            "color": reference.get_color(),
            "linewidth": float(reference.get_linewidth()),
            "linestyle": reference.get_linestyle(),
            "alpha": reference.get_alpha(),
        },
    }


def _apply_qq_points(points, orig, options):
    if points is None or orig is None:
        return
    points.set_visible(options.get("visible", orig["visible"]))
    marker = options.get("marker")
    if marker is not None:
        ms = MarkerStyle(marker)
        points.set_paths([ms.get_path().transformed(ms.get_transform())])
    else:
        points.set_paths([path.copy() for path in orig["paths"]])
    size = options.get("size")
    points.set_sizes([float(size) ** 2] if size is not None else orig["sizes"].copy())
    if "color" in options or "alpha" in options:
        base_rgb = options.get("color", tuple(orig["facecolors"][0][:3]))
        base_alpha = options.get("alpha", float(orig["facecolors"][0][3]))
        face_rgba = to_rgba(base_rgb, base_alpha)
        points.set_facecolor(face_rgba)
        if marker in ("+", "x"):
            points.set_edgecolor(face_rgba)
            base_lw = float(orig["linewidths"][0]) if len(orig["linewidths"]) else 0.6
            points.set_linewidths([max(1.2, base_lw)])
        else:
            orig_edge = orig["edgecolors"][0][:3] if len(orig["edgecolors"]) else (1.0, 1.0, 1.0)
            points.set_edgecolor((*orig_edge, base_alpha))
            points.set_linewidths(orig["linewidths"].copy())
        points.set_alpha(None)
    else:
        points.set_alpha(orig["alpha"])
        points.set_facecolor(orig["facecolors"].copy())
        if marker in ("+", "x"):
            points.set_edgecolor(orig["facecolors"].copy())
            base_lw = float(orig["linewidths"][0]) if len(orig["linewidths"]) else 0.6
            points.set_linewidths([max(1.2, base_lw)])
        else:
            points.set_edgecolor(orig["edgecolors"].copy())
            points.set_linewidths(orig["linewidths"].copy())


def _apply_qq_reference(reference, orig, options):
    if reference is None or orig is None:
        return
    reference.set_visible(options.get("visible", orig["visible"]))
    reference.set_color(options.get("color", orig["color"]))
    reference.set_linewidth(options.get("width", orig["linewidth"]))
    reference.set_linestyle(options.get("style", orig["linestyle"]))
    reference.set_alpha(options.get("alpha", orig["alpha"]))


def _apply_qq_panels(figure, style, primary_axes):
    panels = panel_axes(figure)
    if not panels:
        return
    # Empty axis records mean automatic limits. Use the same normalized form
    # accepted by validation before looking up min/max on saved recipes.
    panel_styles = normalize_panel_styles(style.get(PANEL_KEY, {}))
    for panel_id, ax in panels.items():
        defaults = getattr(ax, "_tramastat_qq_defaults", None)
        if defaults is None:
            continue
        pstyle = panel_styles.get(panel_id, {})
        is_primary = ax is primary_axes
        for (artist, orig_text, orig_font, orig_parse_math), key in zip(
            defaults["texts"], ("title", "xlabel", "ylabel"), strict=True
        ):
            if key in pstyle:
                artist.set_text(pstyle[key])
                artist.set_parse_math(False)
            elif not is_primary:
                artist.set(text=orig_text, fontproperties=orig_font)
                artist.set_parse_math(orig_parse_math)
            elif key not in style:
                artist.set_parse_math(orig_parse_math)
        p_axis = pstyle.get("axis", {})
        for dim in ("x", "y"):
            if dim in p_axis:
                bounds = p_axis[dim]
                getattr(ax, f"set_{dim}lim")(bounds["min"], bounds["max"])
            elif not is_primary:
                getattr(ax, f"set_{dim}lim")(defaults[f"{dim}lim"], auto=defaults[f"auto{dim}"])
        _apply_qq_points(getattr(ax, POINTS_ATTR, None), defaults["points"], pstyle.get(POINTS_KEY, {}))
        _apply_qq_reference(getattr(ax, REFERENCE_ATTR, None), defaults["reference_line"], pstyle.get(REFERENCE_KEY, {}))
        if "legend_visible" in pstyle:
            want_legend = pstyle["legend_visible"]
        elif is_primary and "legend" in style:
            want_legend = style["legend"] != "hidden"
        else:
            want_legend = defaults["legend_visible"]
        handles, labels = ax.get_legend_handles_labels()
        visible_pairs = [(handle, text) for handle, text in zip(handles, labels) if handle.get_visible()]
        if not visible_pairs:
            current = ax.get_legend()
            if current is not None:
                current.set_visible(False)
            continue
        if defaults["legend"] is None and not want_legend:
            ax.legend_ = None
            continue
        loc = (
            style["legend"]
            if (is_primary and "legend" in style and style["legend"] != "hidden")
            else defaults["legend_loc"]
        )
        created = ax.legend(
            [handle for handle, _ in visible_pairs],
            [text for _, text in visible_pairs],
            loc=loc,
            frameon=defaults["legend_frameon"],
            title=defaults["legend_title"],
        )
        for text_artist in [created.get_title(), *created.get_texts()]:
            if defaults["legend_font"] is not None:
                text_artist.set_fontproperties(defaults["legend_font"])
            if "font_family" in style:
                text_artist.set_fontfamily(style["font_family"])
            if "legend_size" in style:
                text_artist.set_fontsize(style["legend_size"])
            text_artist.set_parse_math(False)
        created.set_visible(bool(want_legend))


def capture_defaults(figure):
    """Remember the analysis defaults of a graph before any preview changes it."""
    if figure.axes and not hasattr(figure.axes[0], "_tramastat_defaults"):
        figure.axes[0]._tramastat_defaults = _capture_defaults(figure.axes[0])
    for ax in panel_axes(figure).values():
        if not hasattr(ax, "_tramastat_qq_defaults"):
            ax._tramastat_qq_defaults = _capture_qq_panel_defaults(ax)


def apply_style(figure, style):
    if not style and (not figure.axes or not hasattr(figure.axes[0], "_tramastat_defaults")):
        return
    if not figure.axes:
        raise ValueError("This graph has no axes to format.")
    axes = figure.axes[0]
    validate_graph_style(axes, style)
    capture_defaults(figure)
    defaults = axes._tramastat_defaults
    previous = getattr(axes, "_tramastat_style", {})
    for artist in (*getattr(axes, "_tramastat_references", ()), *getattr(axes, "_tramastat_annotations", ()),
                   *getattr(axes, "_tramastat_shapes", ())):
        artist.remove()
    for dimension in ("x", "y"):
        _apply_axis(axes, dimension, style, previous, defaults["axes"][dimension])
    axes.set_axisbelow(True if style.get("grid") or style.get("grid_minor") else defaults["axisbelow"])
    for (artist, label, font), key, size in zip(defaults["texts"], ("title", "xlabel", "ylabel"),
                                                ("title_size", "label_size", "label_size"), strict=True):
        artist.set(text=style.get(key, label), fontproperties=font)
        if "font_family" in style:
            artist.set_fontfamily(style["font_family"])
        if size in style:
            artist.set_fontsize(style[size])
    for name, visible in defaults["spines"].items():
        if "frame" in style and name in {"left", "right", "bottom", "top"}:
            visible = style["frame"] == "box" or name in {"left", "bottom"}
        axes.spines[name].set_visible(visible)

    legacy = defaults.get("legacy_accent")
    if legacy is None and "accent" in style:
        artist = next(iter(axes.lines or axes.collections), None)
        if artist is not None:
            getter = artist.get_color if isinstance(artist, Line2D) else artist.get_facecolor
            setter = artist.set_color if isinstance(artist, Line2D) else artist.set_facecolor
            legacy = defaults["legacy_accent"] = (getter(), setter)
    if legacy is not None and "accent" in previous:
        color, setter = legacy
        setter(color)

    series_options = style.get("series", {})
    for key, (series, original) in defaults["series"].items():
        if key in series_options or key in previous.get("series", {}):
            _apply_series(series, original, series_options.get(key, {}))
    group_options = style.get("groups", {})
    for key, (group, original) in defaults["groups"].items():
        if key in group_options or key in previous.get("groups", {}):
            _apply_group(group, original, group_options.get(key, {}))
    if legacy is not None and "accent" in style:
        _, setter = legacy
        artist = setter.__self__
        has_color = False
        for key, options in series_options.items():
            if "color" not in options or key not in defaults["series"]:
                continue
            target = defaults["series"][key][0].artist
            if isinstance(target, ErrorbarContainer):
                center, caps, whiskers = target.lines
                has_color = artist in (center, *caps, *whiskers)
            else:
                has_color = target is artist
            if has_color:
                break
        if not has_color:
            setter(style["accent"])
    _apply_legend(axes, style, defaults, bool(series_options or "accent" in style))
    _apply_xy_legend(axes, style)
    axes._tramastat_references = _reference_artists(axes, style.get("reference_lines", []))
    axes._tramastat_shapes = draw_shapes(axes, style.get(SHAPES, []))
    axes._tramastat_annotations = draw_annotations(axes, style.get(ANNOTATIONS, []))
    _apply_qq_panels(figure, style, axes)
    axes._tramastat_style = deepcopy(style)
    # Annotations that depend on the formatted axis (pairwise brackets) are removed and drawn again.
    after = getattr(axes, "_tramastat_after_style", None)
    if after is not None:
        after(axes)


def compose_layout(title, columns, figures, *, paper=AUTO_PAPER, background=WHITE):
    Layout(title, columns, [("panel", i) for i in range(len(figures))], paper, background)
    page_width, page_height = size = page_size(columns, len(figures), paper)
    sizes = [graph.get_size_inches() for graph in figures]
    boxes = panel_boxes(columns, sizes, paper)
    figure = layout_frame(title, size, boxes, background=background, panel_letters=False)
    ink = page_ink(background)
    for i, (graph, (w, h), (x, y, scale)) in enumerate(zip(figures, sizes, boxes, strict=True)):
        # Render each original axis with its own ticks, legend and plot type.
        with BytesIO() as buffer:
            graph.savefig(buffer, format="png", dpi=150)
            buffer.seek(0)
            pixels = imread(buffer)
        panel = figure.add_axes((x / page_width, 1 - (y + h * scale) / page_height,
                                 w * scale / page_width, h * scale / page_height))
        panel.imshow(pixels)
        panel.set_axis_off()
        panel.set_title(chr(ord("A") + i), loc="left", y=1, pad=LABEL_PAD * PT,
                        fontsize=LABEL_SIZE, fontweight="bold", color=ink)
    return figure
