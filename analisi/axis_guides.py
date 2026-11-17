"""Custom axis ticks, reference grid lines, and shaded axis bands."""
from copy import deepcopy
from math import isfinite, ulp
from numbers import Real
from sys import float_info
import uuid

import matplotlib as mpl
from matplotlib import rcParams
from matplotlib.colors import is_color_like, to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FixedFormatter, Formatter, FuncFormatter, Locator

from .probability_scale import PROBABILITY_SCALES

AXIS_GUIDES = "axis_guides"
AXIS_BANDS = "axis_bands"

GUIDE_AXES = ("x", "y")
GUIDE_STYLES = ("-", "--", ":", "-.")
GUIDE_SIDES = ("primary", "opposite")
BAND_HATCHES = ("", "/", "\\", "|", "-", "+", "x", ".", "o")

MAX_GUIDES_PER_AXIS = 30
MAX_GUIDES_TOTAL = 60
MAX_BANDS = 12
MAX_LABEL_LENGTH = 160

DEFAULT_GUIDE_COLOR = "#657486"
DEFAULT_GUIDE_WIDTH = 1.0
DEFAULT_GUIDE_STYLE = "--"
DEFAULT_GUIDE_FONT_SIZE = 9.0
DEFAULT_GUIDE_SIDE = "primary"
DEFAULT_BAND_ALPHA = 0.15

_GUIDE_BASE_KEYS = {"id", "axis", "value", "tick", "line", "label", "color", "width", "style", "visible"}
_GUIDE_OPTIONAL_KEYS = {"label_color", "font_size", "side"}
_GUIDE_ALL_KEYS = _GUIDE_BASE_KEYS | _GUIDE_OPTIONAL_KEYS
_BAND_KEYS = {"id", "axis", "lower", "upper", "color", "alpha", "hatch", "visible"}
_LINE_BREAK_CHARS = frozenset("\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")

GUIDE_GID_PREFIX = "trama-axis-guide:"
BAND_GID_PREFIX = "trama-axis-band:"


def _is_number(value):
    if type(value) not in (int, float):
        return False
    return isfinite(value) and abs(value) <= float_info.max


def _is_canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value


def _is_valid_color(value):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped or len(value) > 40 or stripped.lower() == "none":
        return False
    if not is_color_like(value):
        return False
    try:
        to_rgba(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_single_line_label(value):
    if not isinstance(value, str) or len(value) > MAX_LABEL_LENGTH:
        return False
    return not any(ch in _LINE_BREAK_CHARS for ch in value)


def ulp_close(first, second):
    """Return True if two finite floats match within 8 ULPs."""
    if first == second:
        return True
    return abs(first - second) <= 8 * max(ulp(first), ulp(second))


def new_guide_id():
    return str(uuid.uuid4())


def _normalise_guide(record):
    if not isinstance(record, dict) or record.keys() - _GUIDE_ALL_KEYS:
        raise ValueError("Invalid axis guide record.")
    for required in ("id", "axis", "value"):
        if required not in record:
            raise ValueError("Each axis guide requires an ID, axis, and value.")
    guide_id = record["id"]
    if not _is_canonical_uuid(guide_id):
        raise ValueError("Each axis guide requires a canonical lowercase UUID.")
    axis = record["axis"]
    if axis not in GUIDE_AXES:
        raise ValueError("Axis guide axis must be X or Y.")
    raw_value = record["value"]
    if not _is_number(raw_value):
        raise ValueError("Axis guide coordinate must be a finite number.")
    value = float(raw_value)

    tick = record.get("tick", False)
    if type(tick) is not bool:
        raise ValueError("Axis guide tick setting must be true or false.")
    line = record.get("line", True)
    if type(line) is not bool:
        raise ValueError("Axis guide line setting must be true or false.")
    visible = record.get("visible", True)
    if type(visible) is not bool:
        raise ValueError("Axis guide visibility must be true or false.")
    if visible and not tick and not line:
        raise ValueError("A visible axis guide must show a tick, a line, or both.")

    label = record.get("label", "")
    if not _is_single_line_label(label):
        raise ValueError("Axis guide label must be a single line of up to 160 characters.")
    color = record.get("color", DEFAULT_GUIDE_COLOR)
    if not _is_valid_color(color):
        raise ValueError("Enter a valid axis guide color, for example #657486.")
    raw_width = record.get("width", DEFAULT_GUIDE_WIDTH)
    if not _is_number(raw_width) or not 0.2 <= float(raw_width) <= 8.0:
        raise ValueError("Axis guide width must be between 0.2 and 8 points.")
    width = float(raw_width)
    line_style = record.get("style", DEFAULT_GUIDE_STYLE)
    if not isinstance(line_style, str) or line_style not in GUIDE_STYLES:
        raise ValueError("Choose -, --, :, or -. for the axis guide line style.")

    normalised = {
        "id": guide_id,
        "axis": axis,
        "value": value,
        "tick": tick,
        "line": line,
        "label": label,
        "color": color,
        "width": width,
        "style": line_style,
        "visible": visible,
    }
    if "label_color" in record:
        label_color = record["label_color"]
        if not _is_valid_color(label_color):
            raise ValueError("Enter a valid axis guide label color.")
        normalised["label_color"] = label_color
    if "font_size" in record:
        raw_size = record["font_size"]
        if not _is_number(raw_size) or not 4.0 <= float(raw_size) <= 72.0:
            raise ValueError("Axis guide font size must be between 4 and 72 points.")
        normalised["font_size"] = float(raw_size)
    if "side" in record:
        side = record["side"]
        if not isinstance(side, str) or side not in GUIDE_SIDES:
            raise ValueError("Axis guide side must be primary or opposite.")
        normalised["side"] = side
    return normalised


def normalise_guides(records):
    """Validate and return an independent normalised copy of axis guide records."""
    if not isinstance(records, list):
        raise ValueError("Invalid axis guides.")
    if len(records) > MAX_GUIDES_TOTAL:
        raise ValueError(f"Add up to {MAX_GUIDES_TOTAL} axis guides per graph.")
    normalised = []
    seen_ids = set()
    axis_counts = {"x": 0, "y": 0}
    tick_values = {"x": [], "y": []}
    for record in records:
        item = _normalise_guide(record)
        guide_id = item["id"]
        if guide_id in seen_ids:
            raise ValueError(f"Duplicate axis guide ID {guide_id}.")
        seen_ids.add(guide_id)
        axis = item["axis"]
        axis_counts[axis] += 1
        if axis_counts[axis] > MAX_GUIDES_PER_AXIS:
            raise ValueError(f"Add up to {MAX_GUIDES_PER_AXIS} axis guides on the {axis.upper()} axis.")
        if item["visible"] and item["tick"]:
            value = item["value"]
            if any(ulp_close(existing, value) for existing in tick_values[axis]):
                raise ValueError("Two visible custom ticks cannot share the same coordinate on an axis.")
            tick_values[axis].append(value)
        normalised.append(item)
    return normalised


def _normalise_band(record):
    if not isinstance(record, dict) or record.keys() - _BAND_KEYS:
        raise ValueError("Invalid axis band record.")
    for required in ("id", "axis", "lower", "upper", "color"):
        if required not in record:
            raise ValueError("Each axis band requires an ID, axis, lower and upper bounds, and a color.")
    band_id = record["id"]
    if not _is_canonical_uuid(band_id):
        raise ValueError("Each axis band requires a canonical lowercase UUID.")
    axis = record["axis"]
    if axis not in GUIDE_AXES:
        raise ValueError("Axis band axis must be X or Y.")
    raw_lower, raw_upper = record["lower"], record["upper"]
    if not _is_number(raw_lower) or not _is_number(raw_upper):
        raise ValueError("Axis band limits must be finite numbers.")
    lower, upper = float(raw_lower), float(raw_upper)
    if lower >= upper or not _is_number(upper - lower):
        raise ValueError("Axis band lower limit must be smaller than the upper limit with a finite span.")
    color = record["color"]
    if not _is_valid_color(color):
        raise ValueError("Enter a valid axis band color.")
    raw_alpha = record.get("alpha", DEFAULT_BAND_ALPHA)
    if not _is_number(raw_alpha) or not 0.0 <= float(raw_alpha) <= 1.0:
        raise ValueError("Axis band opacity must be between 0 and 1.")
    alpha = float(raw_alpha)
    hatch = record.get("hatch", "")
    if not isinstance(hatch, str) or hatch not in BAND_HATCHES:
        raise ValueError("Choose a valid axis band hatch pattern.")
    visible = record.get("visible", True)
    if type(visible) is not bool:
        raise ValueError("Axis band visibility must be true or false.")
    return {
        "id": band_id,
        "axis": axis,
        "lower": lower,
        "upper": upper,
        "color": color,
        "alpha": alpha,
        "hatch": hatch,
        "visible": visible,
    }


def normalise_bands(records):
    """Validate and return an independent normalised copy of axis band records."""
    if not isinstance(records, list):
        raise ValueError("Invalid axis bands.")
    if len(records) > MAX_BANDS:
        raise ValueError(f"Add up to {MAX_BANDS} axis bands per graph.")
    normalised = []
    seen_ids = set()
    for record in records:
        item = _normalise_band(record)
        band_id = item["id"]
        if band_id in seen_ids:
            raise ValueError(f"Duplicate axis band ID {band_id}.")
        seen_ids.add(band_id)
        normalised.append(item)
    return normalised


def _is_real_number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    numeric = float(value)
    return isfinite(numeric) and abs(numeric) <= float_info.max


def merge_ticks(regular, labels, guides, lower, upper, scale):
    """Merge regular axis ticks with prevalidated custom tick guides for one axis."""
    if not _is_real_number(lower) or not _is_real_number(upper):
        raise ValueError("Axis view bounds must be finite numbers.")
    lower_val, upper_val = float(lower), float(upper)
    if lower_val >= upper_val or not _is_real_number(upper_val - lower_val):
        raise ValueError("Axis view lower bound must be smaller than the upper bound.")
    if scale not in ("linear", "log") or (scale == "log" and lower_val <= 0):
        raise ValueError("Tick merging supports linear axes and strictly positive logarithmic axes.")

    reg_list = list(regular)
    lbl_list = list(labels)
    if len(reg_list) != len(lbl_list):
        raise ValueError("Regular tick locations and labels must have the same length.")

    items = []
    for raw_loc, lbl in zip(reg_list, lbl_list):
        if not _is_real_number(raw_loc):
            raise ValueError("Regular tick locations must be finite numbers.")
        loc = float(raw_loc)
        if lower_val <= loc <= upper_val:
            items.append((loc, str(lbl)))

    seen_custom_ticks = []
    for guide in guides:
        raw_val = guide.get("value")
        if not _is_number(raw_val):
            raise ValueError("Axis guide coordinate must be a finite number.")
        val = float(raw_val)
        if not guide.get("visible", True) or not guide.get("tick", False):
            continue
        if scale == "log" and val <= 0:
            raise ValueError("Visible ticks on a logarithmic axis must be strictly positive.")
        if any(ulp_close(existing, val) for existing in seen_custom_ticks):
            raise ValueError("Two visible custom ticks cannot share the same coordinate on an axis.")
        seen_custom_ticks.append(val)
        if not lower_val <= val <= upper_val:
            continue
        prior = next((index for index, (existing, _) in enumerate(items) if ulp_close(existing, val)), None)
        custom_label = guide.get("label", "")
        if prior is None:
            items.append((val, custom_label if custom_label else format(val, ".12g")))
        elif custom_label:
            items[prior] = (items[prior][0], custom_label)

    items.sort(key=lambda item: item[0])
    return [loc for loc, _ in items], [lbl for _, lbl in items]


def is_native_plot_axes(axes):
    """Return True if ``axes`` belongs to a native plot rather than an imported preview image."""
    if axes is None:
        return False
    if getattr(axes, "_tramastat_non_native", False):
        return False
    if not getattr(axes, "axison", True):
        return False
    return True


def axis_supports_guides(axes, dimension, scale=None):
    """Return True if ``dimension`` ('x' or 'y') on ``axes`` supports axis guides and bands."""
    if not is_native_plot_axes(axes):
        return False
    if dimension in getattr(axes, "_tramastat_categorical_axes", ()):
        return False
    axis = getattr(axes, dimension + "axis")
    effective_scale = scale or axis.get_scale()
    if effective_scale in PROBABILITY_SCALES or effective_scale not in ("linear", "log"):
        return False
    if dimension in getattr(axes, "_tramastat_numeric_axes", ()):
        return True
    defaults = getattr(axes, "_tramastat_defaults", None)
    formatter = defaults["axes"][dimension]["major_formatter"] if defaults else axis.get_major_formatter()
    return not isinstance(formatter, (FixedFormatter, FuncFormatter)) and axis.get_units() is None


def validate_axis_guides_domain(axes, guides, bands, *, xscale=None, yscale=None):
    """Validate that normalised ``guides`` and ``bands`` are valid on ``axes`` before any mutation."""
    if not guides and not bands:
        return
    if not is_native_plot_axes(axes):
        raise ValueError("Axis guides and bands are only supported on native numeric plots.")
    defaults = getattr(axes, "_tramastat_defaults", None)
    scales = {
        "x": xscale or (defaults["axes"]["x"]["scale"] if defaults else axes.xaxis.get_scale()),
        "y": yscale or (defaults["axes"]["y"]["scale"] if defaults else axes.yaxis.get_scale()),
    }
    for dim in GUIDE_AXES:
        dim_guides = [g for g in guides if g["axis"] == dim]
        dim_bands = [b for b in bands if b["axis"] == dim]
        if not dim_guides and not dim_bands:
            continue
        scale = scales[dim]
        if scale in PROBABILITY_SCALES or scale not in ("linear", "log"):
            raise ValueError(f"The {dim.upper()} axis scale does not support axis guides or bands.")
        if not axis_supports_guides(axes, dim, scale):
            raise ValueError(f"The {dim.upper()} axis is categorical and does not support numeric guides or bands.")
        if scale == "log":
            if any(g.get("visible", True) and g["value"] <= 0 for g in dim_guides):
                raise ValueError("Visible guides on a logarithmic axis must be strictly positive.")
            if any(b.get("visible", True) and b["lower"] <= 0 for b in dim_bands):
                raise ValueError("Visible bands on a logarithmic axis must have strictly positive bounds.")


# ----- Matplotlib rendering & dynamic locator/formatter wrappers -----------------------------------------


class _GuideLocator(Locator):
    """Dynamic locator wrapper that merges base ticks with visible primary custom tick guides."""

    def __init__(self, base_locator, guides):
        super().__init__()
        self.base_locator = base_locator
        self.guides = tuple(deepcopy(guides))

    def set_axis(self, axis):
        super().set_axis(axis)
        self.base_locator.set_axis(axis)

    def set_params(self, **kwargs):
        self.base_locator.set_params(**kwargs)

    def __call__(self):
        if self.axis is None:
            return []
        return self.tick_values(*self.axis.get_view_interval())

    def tick_values(self, vmin, vmax):
        base_locs = self.base_locator.tick_values(vmin, vmax)
        low_f, high_f = float(vmin), float(vmax)
        lower, upper = (low_f, high_f) if low_f <= high_f else (high_f, low_f)
        scale = self.axis.get_scale() if self.axis is not None else "linear"
        if scale not in ("linear", "log") or (scale == "log" and lower <= 0):
            return base_locs
        merged_locs, _ = merge_ticks(base_locs, [""] * len(base_locs), self.guides, lower, upper, scale)
        return merged_locs

    def regular_values(self, vmin, vmax):
        return self.base_locator.tick_values(vmin, vmax)

    def __getattr__(self, name):
        return getattr(self.base_locator, name)


class _GuideFormatter(Formatter):
    """Dynamic formatter wrapper that keeps base formatting for regular ticks and literal text for custom ticks."""

    def __init__(self, base_formatter, guide_locator, guides):
        super().__init__()
        self.base_formatter = base_formatter
        self.guide_locator = guide_locator
        self.guides = tuple(deepcopy(guides))

    def set_axis(self, axis):
        super().set_axis(axis)
        self.base_formatter.set_axis(axis)

    def set_locs(self, locs):
        if self.axis is not None:
            vmin, vmax = self.axis.get_view_interval()
            reg_locs = self.guide_locator.regular_values(vmin, vmax)
        else:
            reg_locs = locs
        super().set_locs(reg_locs)
        self.base_formatter.set_locs(reg_locs)

    def __call__(self, x, pos=None):
        for guide in self.guides:
            if ulp_close(float(x), guide["value"]):
                if guide["label"]:
                    return guide["label"]
                break
        return self.base_formatter(x, pos)

    def format_ticks(self, values):
        if self.axis is None:
            return [self(v, i) for i, v in enumerate(values)]
        vmin, vmax = self.axis.get_view_interval()
        low_f, high_f = float(vmin), float(vmax)
        lower, upper = (low_f, high_f) if low_f <= high_f else (high_f, low_f)
        scale = self.axis.get_scale()
        if scale not in ("linear", "log") or (scale == "log" and lower <= 0):
            return self.base_formatter.format_ticks(values)
        reg_locs = [float(loc) for loc in self.guide_locator.regular_values(vmin, vmax)
                    if lower <= float(loc) <= upper]
        reg_labels = self.base_formatter.format_ticks(reg_locs)
        merged_locs, merged_labels = merge_ticks(reg_locs, reg_labels, self.guides, lower, upper, scale)
        values_list = [float(v) for v in values]
        if len(values_list) == len(merged_locs) and all(ulp_close(a, b) for a, b in zip(values_list, merged_locs)):
            return merged_labels
        formatted = []
        for val in values_list:
            matched_reg = next((lbl for rloc, lbl in zip(reg_locs, reg_labels) if ulp_close(rloc, val)), None)
            matched_guide = next((g for g in self.guides if ulp_close(g["value"], val)), None)
            if matched_guide is not None:
                if matched_guide["label"]:
                    formatted.append(matched_guide["label"])
                elif matched_reg is not None:
                    formatted.append(matched_reg)
                else:
                    formatted.append(format(val, ".12g"))
            elif matched_reg is not None:
                formatted.append(matched_reg)
            else:
                formatted.append(self.base_formatter.format_ticks([val])[0])
        return formatted

    def get_offset(self):
        return self.base_formatter.get_offset()

    def __getattr__(self, name):
        return getattr(self.base_formatter, name)


class _OppositeTickLine(Line2D):
    """A single opposite-side tick mark that automatically hides outside the current axis view."""

    def __init__(self, axis_obj, value, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guide_axis = axis_obj
        self._guide_value = float(value)

    def draw(self, renderer):
        low, high = sorted(self._guide_axis.get_view_interval())
        if not (low <= self._guide_value <= high):
            return
        super().draw(renderer)


def _capture_tick_defaults(axis, dimension):
    kw = getattr(axis, "_major_tick_kw", {})
    tick_color = kw.get("color", rcParams[f"{dimension}tick.color"])
    label_color = kw.get("labelcolor", rcParams[f"{dimension}tick.labelcolor"])
    if label_color == "inherit":
        label_color = tick_color
    labelsize = kw.get("labelsize", rcParams[f"{dimension}tick.labelsize"])
    tick_width = kw.get("width", rcParams[f"{dimension}tick.major.width"])
    parse_math = rcParams["text.parse_math"]
    if axis.majorTicks:
        sample = axis.majorTicks[0]
        parse_math = sample.label1.get_parse_math()
    return {
        "tick_color": tick_color,
        "label_color": label_color,
        "labelsize": labelsize,
        "tick_width": tick_width,
        "parse_math": parse_math,
    }


def _restore_tick_style(tick, tick_defaults):
    tick.tick1line.set_color(tick_defaults["tick_color"])
    tick.tick1line.set_markeredgecolor(tick_defaults["tick_color"])
    tick.tick1line.set_markeredgewidth(tick_defaults["tick_width"])
    tick.tick1line.set_gid(None)
    tick.label1.set_color(tick_defaults["label_color"])
    tick.label1.set_fontsize(tick_defaults["labelsize"])
    tick.label1.set_parse_math(tick_defaults["parse_math"])
    tick.label1.set_gid(None)


def _style_primary_guide_ticks(axis, ticks, guides, tick_defaults):
    for tick in getattr(axis, "majorTicks", ()):
        _restore_tick_style(tick, tick_defaults)
    for tick in ticks:
        loc = float(tick.get_loc())
        matched = next((g for g in guides if ulp_close(loc, g["value"])), None)
        if matched is None:
            continue
        gid_base = f"{GUIDE_GID_PREFIX}{matched['id']}"
        tick.tick1line.set_color(matched["color"])
        tick.tick1line.set_markeredgecolor(matched["color"])
        tick.tick1line.set_gid(f"{gid_base}:tick")
        tick.label1.set_parse_math(False)
        tick.label1.set_color(matched.get("label_color", matched["color"]))
        tick.label1.set_fontsize(matched.get("font_size", DEFAULT_GUIDE_FONT_SIZE))
        tick.label1.set_gid(f"{gid_base}:label")


def clear_axis_guides_and_bands(axes):
    """Remove all axis guide/band artists and restore original locators, formatters, and tick properties."""
    for artist in (*getattr(axes, "_tramastat_axis_guides", ()), *getattr(axes, "_tramastat_axis_bands", ())):
        try:
            artist.remove()
        except ValueError:
            pass
    axes._tramastat_axis_guides = []
    axes._tramastat_axis_bands = []

    wrappers = getattr(axes, "_tramastat_axis_guide_wrappers", None)
    if wrappers:
        for dim, info in wrappers.items():
            axis = getattr(axes, dim + "axis")
            axis.__dict__.pop("_update_ticks", None)
            axis.set_major_locator(info["locator"])
            axis.set_major_formatter(info["formatter"])
            tick_defaults = info["tick_defaults"]
            for tick in getattr(axis, "majorTicks", ()):
                _restore_tick_style(tick, tick_defaults)
            axis.reset_ticks()
        axes._tramastat_axis_guide_wrappers = {}


def _band_artists(axes, bands):
    artists = []
    for band in bands:
        if not band.get("visible", True):
            continue
        vertical = band["axis"] == "x"
        transform = axes.get_xaxis_transform() if vertical else axes.get_yaxis_transform()
        lower, upper = band["lower"], band["upper"]
        span = upper - lower
        xy = (lower, 0.0) if vertical else (0.0, lower)
        width, height = (span, 1.0) if vertical else (1.0, span)
        hatch = band["hatch"] or None
        rect = Rectangle(
            xy,
            width,
            height,
            transform=transform,
            facecolor=band["color"],
            edgecolor=band["color"] if hatch else "none",
            linewidth=0.0,
            alpha=band["alpha"],
            hatch=hatch,
            zorder=0.5,
            clip_on=True,
            label="_nolegend_",
        )
        rect.set_clip_path(axes.patch)
        rect.set_gid(f"{BAND_GID_PREFIX}{band['id']}")
        axes.add_artist(rect)
        artists.append(rect)
    return artists


def _guide_artists(axes, guides):
    artists = []
    for guide in guides:
        if not guide.get("visible", True):
            continue
        vertical = guide["axis"] == "x"
        value = guide["value"]
        transform = axes.get_xaxis_transform() if vertical else axes.get_yaxis_transform()
        gid_base = f"{GUIDE_GID_PREFIX}{guide['id']}"
        color = guide["color"]
        label_color = guide.get("label_color", color)
        font_size = guide.get("font_size", DEFAULT_GUIDE_FONT_SIZE)
        side = guide.get("side", DEFAULT_GUIDE_SIDE)
        label_text = guide.get("label", "")

        if guide["line"]:
            xs, ys = ([value, value], [0.0, 1.0]) if vertical else ([0.0, 1.0], [value, value])
            line = Line2D(
                xs,
                ys,
                transform=transform,
                color=color,
                linestyle=guide["style"],
                linewidth=guide["width"],
                zorder=1.8,
                clip_on=True,
                label="_nolegend_",
            )
            line.set_clip_path(axes.patch)
            line.set_gid(f"{gid_base}:line")
            axes.add_artist(line)
            artists.append(line)

        if guide["tick"] and side == "opposite":
            axis_obj = axes.xaxis if vertical else axes.yaxis
            marker = mpl.markers.TICKUP if vertical else mpl.markers.TICKRIGHT
            tx, ty = ([value], [1.0]) if vertical else ([1.0], [value])
            tick_mark = _OppositeTickLine(
                axis_obj,
                value,
                tx,
                ty,
                transform=transform,
                marker=marker,
                markersize=4.0,
                markeredgewidth=max(0.8, min(2.0, guide["width"])),
                color=color,
                linestyle="None",
                clip_on=False,
                zorder=3.0,
                label="_nolegend_",
            )
            tick_mark.set_gid(f"{gid_base}:tick")
            axes.add_artist(tick_mark)
            artists.append(tick_mark)

            tick_text = label_text if label_text else format(value, ".12g")
            pos = (value, 1.0) if vertical else (1.0, value)
            offset = (0, 6) if vertical else (6, 0)
            ha = "center" if vertical else "left"
            va = "bottom" if vertical else "center"
            ann = axes.annotate(
                tick_text,
                pos,
                xycoords=transform,
                xytext=offset,
                textcoords="offset points",
                annotation_clip=True,
                ha=ha,
                va=va,
                color=label_color,
                fontsize=font_size,
                parse_math=False,
                clip_on=False,
                zorder=3.5,
            )
            ann.set_gid(f"{gid_base}:label")
            artists.append(ann)
        elif not guide["tick"] and guide["line"] and label_text:
            if vertical:
                pos = (value, 0.0 if side == "primary" else 1.0)
                offset = (4, 4) if side == "primary" else (4, -4)
                ha, va = "left", ("bottom" if side == "primary" else "top")
            else:
                pos = (0.0 if side == "primary" else 1.0, value)
                offset = (4, 4) if side == "primary" else (-4, 4)
                ha, va = ("left" if side == "primary" else "right"), "bottom"
            ann = axes.annotate(
                label_text,
                pos,
                xycoords=transform,
                xytext=offset,
                textcoords="offset points",
                annotation_clip=True,
                ha=ha,
                va=va,
                color=label_color,
                fontsize=font_size,
                parse_math=False,
                clip_on=True,
                zorder=2.0,
            )
            ann.set_clip_path(axes.patch)
            ann.set_gid(f"{gid_base}:label")
            artists.append(ann)
    return artists


def apply_axis_guides_and_bands(axes, guides, bands):
    """Apply validated ``guides`` and ``bands`` to ``axes`` without modifying dataLim or limits."""
    clear_axis_guides_and_bands(axes)
    if not guides and not bands:
        return
    saved_datalim = axes.dataLim.frozen()
    saved_ignore = axes.ignore_existing_data_limits
    saved_xlim = axes.get_xlim()
    saved_ylim = axes.get_ylim()
    saved_autox = axes.get_autoscalex_on()
    saved_autoy = axes.get_autoscaley_on()
    try:
        axes._tramastat_axis_bands = _band_artists(axes, bands)
        axes._tramastat_axis_guides = _guide_artists(axes, guides)
        wrappers = {}
        for dim in GUIDE_AXES:
            primary_ticks = [
                g for g in guides
                if g["axis"] == dim and g.get("visible", True) and g.get("tick", False)
                and g.get("side", DEFAULT_GUIDE_SIDE) == "primary"
            ]
            if not primary_ticks:
                continue
            axis = getattr(axes, dim + "axis")
            base_locator = axis.get_major_locator()
            base_formatter = axis.get_major_formatter()
            tick_defaults = _capture_tick_defaults(axis, dim)
            wrappers[dim] = {
                "locator": base_locator,
                "formatter": base_formatter,
                "tick_defaults": tick_defaults,
            }
            guide_locator = _GuideLocator(base_locator, primary_ticks)
            guide_formatter = _GuideFormatter(base_formatter, guide_locator, primary_ticks)
            axis.set_major_locator(guide_locator)
            axis.set_major_formatter(guide_formatter)
            orig_update_ticks = type(axis)._update_ticks

            def _wrapped_update_ticks(ax_obj=axis, orig=orig_update_ticks, tg=primary_ticks, td=tick_defaults):
                ticks = orig(ax_obj)
                _style_primary_guide_ticks(ax_obj, ticks, tg, td)
                return ticks

            axis._update_ticks = _wrapped_update_ticks
            axis.reset_ticks()
        axes._tramastat_axis_guide_wrappers = wrappers
    finally:
        axes.dataLim.set_points(saved_datalim.get_points())
        axes.ignore_existing_data_limits = saved_ignore
        axes.set_xlim(saved_xlim)
        axes.set_ylim(saved_ylim)
        axes.set_autoscalex_on(saved_autox)
        axes.set_autoscaley_on(saved_autoy)
