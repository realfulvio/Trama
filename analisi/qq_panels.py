"""Canonical Q–Q panel identity and independent per-panel style normalization."""
from math import isfinite
import re
from sys import float_info

from matplotlib.ticker import Locator

PANEL_KEY = "qq_panels"
PANEL_ATTR = "_trama_qq_panel"
POINTS_ATTR = "_trama_qq_points"
REFERENCE_ATTR = "_trama_qq_reference"
NORMAL_PANEL = "normal"
LOGNORMAL_PANEL = "lognormal"
PANEL_IDS = (NORMAL_PANEL, LOGNORMAL_PANEL)

POINTS_KEY = "points"
REFERENCE_KEY = "reference_line"
TEXT_KEYS = ("title", "xlabel", "ylabel")
RECORD_KEYS = (*TEXT_KEYS, "axis", "legend_visible", POINTS_KEY, REFERENCE_KEY)
POINT_KEYS = ("visible", "marker", "size", "color", "alpha")
REFERENCE_KEYS = ("visible", "color", "width", "style", "alpha")
POINT_MARKERS = ("o", "s", "D", "^", "v", "+", "x")
LINE_STYLES = ("-", "--", "-.", ":")
MIN_POINT_SIZE, MAX_POINT_SIZE = 0.5, 36.0
MIN_LINE_WIDTH, MAX_LINE_WIDTH = 0.1, 10.0
HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
AXIS_DIMENSIONS = ("x", "y")
LIMIT_KEYS = ("min", "max")
MAX_LABEL_LENGTH = 160


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        numeric = float(value)
    except OverflowError:
        return False
    return isfinite(numeric) and abs(numeric) <= float_info.max


def _bounded_number(value, low, high, message):
    if not _finite_number(value):
        raise ValueError(message)
    numeric = float(value)
    if not (low <= numeric <= high):
        raise ValueError(message)
    return numeric


def _hex_color(value):
    if not isinstance(value, str) or not HEX_COLOR_RE.fullmatch(value):
        raise ValueError("Enter a valid color, for example #127A78.")
    return value


def panel_axes(figure):
    """Return {canonical_panel_id: Axes} using explicit renderer metadata on each axes."""
    if figure is None:
        return {}
    mapping = {}
    for axis in getattr(figure, "axes", ()):
        panel_id = getattr(axis, PANEL_ATTR, None)
        if panel_id in PANEL_IDS and panel_id not in mapping:
            mapping[panel_id] = axis
    return mapping


def _normalize_axis_bounds(bounds):
    if not isinstance(bounds, dict) or bounds.keys() - set(LIMIT_KEYS):
        raise ValueError("Invalid Q–Q panel axis limits.")
    if not bounds:
        return {}
    if ("min" in bounds) != ("max" in bounds):
        raise ValueError("Enter both axis limits, or leave both blank for an automatic range.")
    low_raw, high_raw = bounds["min"], bounds["max"]
    if not _finite_number(low_raw) or not _finite_number(high_raw):
        raise ValueError("Enter finite numbers for axis options.")
    low, high = float(low_raw), float(high_raw)
    if low >= high or not _finite_number(high - low):
        raise ValueError("The axis minimum must be smaller than the maximum and the span must be finite.")
    if Locator().nonsingular(low, high) != (low, high):
        raise ValueError("These axis limits are too close together to render.")
    return {"min": low, "max": high}


def _normalize_record(record):
    if not isinstance(record, dict) or record.keys() - set(RECORD_KEYS):
        raise ValueError("Invalid Q–Q panel style record.")
    cleaned = {}
    for key in TEXT_KEYS:
        if key in record:
            value = record[key]
            if not isinstance(value, str) or len(value) > MAX_LABEL_LENGTH:
                raise ValueError("Graph labels are limited to 160 characters.")
            cleaned[key] = value
    if "axis" in record:
        raw_axis = record["axis"]
        if not isinstance(raw_axis, dict) or raw_axis.keys() - set(AXIS_DIMENSIONS):
            raise ValueError("Invalid Q–Q panel axis settings.")
        cleaned_axis = {}
        for dim in AXIS_DIMENSIONS:
            if dim in raw_axis:
                bounds = _normalize_axis_bounds(raw_axis[dim])
                if bounds:
                    cleaned_axis[dim] = bounds
        if cleaned_axis:
            cleaned["axis"] = cleaned_axis
    if "legend_visible" in record:
        visible = record["legend_visible"]
        if type(visible) is not bool:
            raise ValueError("Invalid Q–Q panel legend visibility.")
        cleaned["legend_visible"] = visible
    if POINTS_KEY in record:
        cleaned[POINTS_KEY] = _normalize_points(record[POINTS_KEY])
    if REFERENCE_KEY in record:
        cleaned[REFERENCE_KEY] = _normalize_reference_line(record[REFERENCE_KEY])
    return cleaned


def _normalize_points(raw):
    if not isinstance(raw, dict) or raw.keys() - set(POINT_KEYS):
        raise ValueError("Invalid Q–Q panel point settings.")
    cleaned = {}
    if "visible" in raw:
        if type(raw["visible"]) is not bool:
            raise ValueError("Invalid Q–Q panel point visibility.")
        cleaned["visible"] = raw["visible"]
    if "marker" in raw:
        marker = raw["marker"]
        if not isinstance(marker, str) or marker not in POINT_MARKERS:
            raise ValueError("Choose a supported Q–Q point symbol.")
        cleaned["marker"] = marker
    if "size" in raw:
        cleaned["size"] = _bounded_number(raw["size"], MIN_POINT_SIZE, MAX_POINT_SIZE,
                                          "Enter a point size between 0.5 and 36 points.")
    if "color" in raw:
        cleaned["color"] = _hex_color(raw["color"])
    if "alpha" in raw:
        cleaned["alpha"] = _bounded_number(raw["alpha"], 0.0, 1.0, "Enter an opacity between 0 and 1.")
    return cleaned


def _normalize_reference_line(raw):
    if not isinstance(raw, dict) or raw.keys() - set(REFERENCE_KEYS):
        raise ValueError("Invalid Q–Q panel reference line settings.")
    cleaned = {}
    if "visible" in raw:
        if type(raw["visible"]) is not bool:
            raise ValueError("Invalid Q–Q panel reference line visibility.")
        cleaned["visible"] = raw["visible"]
    if "color" in raw:
        cleaned["color"] = _hex_color(raw["color"])
    if "width" in raw:
        cleaned["width"] = _bounded_number(raw["width"], MIN_LINE_WIDTH, MAX_LINE_WIDTH,
                                           "Enter a line width between 0.1 and 10 points.")
    if "style" in raw:
        line_style = raw["style"]
        if not isinstance(line_style, str) or line_style not in LINE_STYLES:
            raise ValueError("Choose a supported reference line style.")
        cleaned["style"] = line_style
    if "alpha" in raw:
        cleaned["alpha"] = _bounded_number(raw["alpha"], 0.0, 1.0, "Enter an opacity between 0 and 1.")
    return cleaned


def normalize_panel_styles(value):
    """Validate a ``qq_panels`` mapping and return an independent deep copy."""
    if not isinstance(value, dict) or value.keys() - set(PANEL_IDS):
        raise ValueError("Invalid Q–Q panel style mapping.")
    return {panel_id: _normalize_record(value[panel_id]) for panel_id in PANEL_IDS if panel_id in value}
