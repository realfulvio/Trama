"""Encoding, palette, symbol mapping and presentation state for native Bubble plots.

Keeps raw worksheet column data separate from mutable presentation overrides so interactive previews,
Undo steps, palette/limit/midpoint changes and symbol-map edits update artists and result tables
without re-running project statistics.
"""
from copy import deepcopy
from math import isfinite, sqrt
import re

from matplotlib import colormaps
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Colormap, Normalize, TwoSlopeNorm, is_color_like, to_hex
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, HPacker, TextArea
import numpy as np
import pandas as pd

from .category_graphs import COLORS
from .graph_legend import typed_group_token
from .i18n import tr
from .point_style import attach_points


ATTR = "_tramastat_bubble"
BUBBLE = "Bubble plot"
SHEET = "Bubble values"

MAX_AREA = "Maximum area (pt²)"
FIXED_AREA = "Fixed area (pt²)"
SIZE_MODE = "Size mode"
SIZE_LEGEND = "Show size legend"

FILL_MODE = "Fill color"
FIXED_COLOR = "Point color"
CATEGORY_COLORS = "Category colors"
COLOR_COLUMN = "Color"
PALETTE = "Palette"
REVERSE_PALETTE = "Reverse palette"
COLOR_LIMITS = "Color limits"
COLOR_MIN = "Color minimum"
COLOR_MID = "Diverging midpoint"
COLOR_MAX = "Color maximum"
MISSING_COLOR = "Missing color"
COLOR_LEGEND = "Show color scale"
COLOR_TITLE = "Color scale title"

SHAPE_MODE = "Shape mode"
FIXED_SHAPE = "Symbol shape"
SHAPE_COLUMN = "Shape"
SHAPE_MAP = "Symbol map"
MISSING_SHAPE = "Missing shape"
SHAPE_LEGEND = "Show shape legend"
SHOW_LABELS = "Show labels"

SIZE_BY_COLUMN, SIZE_FIXED = SIZE_MODES = ("From column", "Fixed area")
FILL_BY_CATEGORY, FILL_FIXED, FILL_CONTINUOUS = FILL_MODES = ("By category", "Fixed color", "Continuous scale")
LIMITS_AUTO, LIMITS_MANUAL = LIMITS_MODES = ("Automatic", "Manual")
SHAPE_FIXED, SHAPE_BY_CATEGORY = SHAPE_MODES = ("Fixed shape", "By category")

DEFAULT_AREA = 400.0
DEFAULT_FIXED_AREA = 120.0
AREA_LIMIT = 10_000.0
MAX_LABELS = 60
NEUTRAL = "No group"
NEUTRAL_COLOR = "#7d8894"
DEFAULT_FIXED_COLOR = COLORS[0]
DEFAULT_MISSING_COLOR = "#9aa4b2"
ALPHA = 0.62

# Sequential and diverging scales tuned for clarity on white figure backgrounds.
BUBBLE_PALETTES = {
    "Viridis": "viridis",
    "Cividis": "cividis",
    "Blues": "Blues",
    "Magma": "magma",
    "Greys": "Greys",
    "Blue–red": "RdBu_r",
    "Cool–warm": "coolwarm",
    "Purple–green": "PRGn",
}
DIVERGING_PALETTES = frozenset({"Blue–red", "Cool–warm", "Purple–green"})

# 12 strongly distinguishable primary shapes, plus 2 stroke fallback markers.
PRIMARY_SHAPES = ("o", "s", "^", "D", "v", "p", "*", "P", "X", "h", "<", ">")
FALLBACK_SHAPES = ("x", "+")
SHAPE_CHOICES = (*PRIMARY_SHAPES, *FALLBACK_SHAPES)
UNFILLED_MARKERS = frozenset({"x", "+"})
DEFAULT_FIXED_SHAPE = "o"
DEFAULT_MISSING_SHAPE = "x"
MAX_CATEGORIES = 500
MAX_LABELS_LEN = 160
MAX_COLOR_TEXT = 40

ROOT_KEYS = (
    "size_mode", "maximum_area", "fixed_area", "show_size_legend",
    "fill_mode", "fixed_color", "category_colors", "palette", "reverse",
    "limits_mode", "color_min", "color_mid", "color_max", "missing_color",
    "show_color_legend", "color_title",
    "shape_mode", "fixed_shape", "shape_map", "missing_shape", "show_shape_legend",
    "show_labels",
)

STYLE_TO_FIELD = {
    "size_mode": SIZE_MODE,
    "maximum_area": MAX_AREA,
    "fixed_area": FIXED_AREA,
    "show_size_legend": SIZE_LEGEND,
    "fill_mode": FILL_MODE,
    "fixed_color": FIXED_COLOR,
    "category_colors": CATEGORY_COLORS,
    "palette": PALETTE,
    "reverse": REVERSE_PALETTE,
    "limits_mode": COLOR_LIMITS,
    "color_min": COLOR_MIN,
    "color_mid": COLOR_MID,
    "color_max": COLOR_MAX,
    "missing_color": MISSING_COLOR,
    "show_color_legend": COLOR_LEGEND,
    "color_title": COLOR_TITLE,
    "shape_mode": SHAPE_MODE,
    "fixed_shape": FIXED_SHAPE,
    "shape_map": SHAPE_MAP,
    "missing_shape": MISSING_SHAPE,
    "show_shape_legend": SHAPE_LEGEND,
    "show_labels": SHOW_LABELS,
}

FIELD_TO_STYLE = {field: key for key, field in STYLE_TO_FIELD.items()}


class BubbleStyleError(ValueError):
    """Validation failure tied to a canonical presentation field."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


class _ExactReverse(Colormap):
    """Reverse a colormap via ``1 - u`` rather than lookup-table resampling."""

    def __init__(self, base):
        self._base = base
        super().__init__(f"{base.name}_exact_r", base.N)

    def __call__(self, X, alpha=None, bytes=False):
        values = np.array(X, copy=True, dtype=float)
        return self._base(1.0 - values, alpha=alpha, bytes=bytes)


def shape_label(marker):
    return tr(f"bubble.shape.{marker}")


def _fail(field, message):
    raise BubbleStyleError(field, message)


def _finite_number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        return False
    return isfinite(float(value))


def valid_color(value):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_COLOR_TEXT:
        return False
    try:
        return bool(is_color_like(value.strip()))
    except (TypeError, ValueError, OverflowError):
        return False


def _clean_color(value, field):
    if not valid_color(value):
        _fail(field, "Enter a valid color, for example #216a94.")
    return to_hex(value.strip(), keep_alpha=False)


def _optional_number(value, field):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped.replace(",", ".") if re.fullmatch(r"[+-]?\d*,\d+(?:[eE][+-]?\d+)?", stripped) else stripped)
        except ValueError:
            _fail(field, f"{field} must be a finite number.")
        if not isfinite(parsed):
            _fail(field, f"{field} must be a finite number.")
        return parsed
    if not _finite_number(value):
        _fail(field, f"{field} must be a finite number.")
    return float(value)


def category_entry(raw):
    """Extract ``(token, display_label, type_key, shape_key, sort_key)`` preserving mixed int/str types."""
    if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
        return None
    if isinstance(raw, np.generic):
        raw = raw.item()
    if isinstance(raw, str):
        if not raw.strip():
            return None
        return (typed_group_token(raw), raw, "bubble.style.type.text", raw, (1, raw.casefold(), raw))
    if isinstance(raw, bool):
        label = str(raw)
        return (typed_group_token(raw), label, "bubble.style.type.bool", raw, (2, int(raw), label))
    if isinstance(raw, int):
        label = str(raw)
        return (typed_group_token(raw), label, "bubble.style.type.number", raw, (0, float(raw), label))
    if isinstance(raw, float):
        if not isfinite(raw):
            return None
        if raw.is_integer() and abs(raw) <= 2**53:
            as_int = int(raw)
            label = str(as_int)
            return (typed_group_token(as_int), label, "bubble.style.type.number", as_int, (0, raw, label))
        label = f"{raw:g}"
        return (typed_group_token(raw), label, "bubble.style.type.number", raw, (0, raw, label))
    text = str(raw)
    return (typed_group_token(raw), text, "bubble.style.type.other", text, (3, text.casefold(), text))


def resolve_category_levels(raw_values, *, column_order=None, preserve_first_seen=False):
    """Collect unique category entries cleanly with homonym disambiguation (``1`` vs ``'1'``)."""
    by_token = {}
    entries_per_row = []
    for raw in raw_values:
        item = category_entry(raw)
        entries_per_row.append(item)
        if item is not None and item[0] not in by_token:
            by_token[item[0]] = item
    levels = list(by_token.values())
    if column_order:
        order_index = {}
        for pos, name in enumerate(column_order):
            order_index[str(name)] = pos
            order_index[typed_group_token(name)] = pos
        levels.sort(key=lambda item: (order_index.get(item[0], order_index.get(item[1], len(order_index))), item[4]))
    elif not preserve_first_seen:
        levels.sort(key=lambda item: item[4])
    label_counts = {}
    for _, label, *_ in levels:
        label_counts[label] = label_counts.get(label, 0) + 1
    disambiguated = {}
    for token, label, type_key, *_ in levels:
        if label_counts[label] > 1:
            disambiguated[token] = f"{label} ({tr(type_key)})"
        else:
            disambiguated[token] = label
    return levels, disambiguated, entries_per_row


def _validate_mapping(value, field, validator):
    if not isinstance(value, dict):
        _fail(field, f"{field} must be an object mapping levels to values.")
    if len(value) > MAX_CATEGORIES:
        _fail(field, f"{field} supports at most {MAX_CATEGORIES} levels.")
    out = {}
    for key, item in value.items():
        token = str(key) if isinstance(key, str) else typed_group_token(key)
        if not token or len(token) > 1000:
            _fail(field, f"Invalid level key in {field}.")
        out[token] = validator(item, field)
    return out


def validate_bubble_style(options, *, figure=None):
    """Validate and canonicalize ``style['bubble']`` overrides."""
    if options is None:
        return {}
    if not isinstance(options, dict):
        _fail("bubble", "Bubble style must be an object of presentation settings.")
    unknown = set(options) - set(ROOT_KEYS)
    if unknown:
        _fail(next(iter(sorted(unknown))), "Unsupported bubble presentation option.")

    state = getattr(figure, ATTR, None) if figure is not None else None
    if figure is not None and state is None:
        _fail("figure", "This figure is not a native Bubble plot.")

    out = {}
    if "size_mode" in options:
        if options["size_mode"] not in SIZE_MODES:
            _fail("size_mode", "Choose a valid size mode.")
        if state is not None and options["size_mode"] == SIZE_BY_COLUMN and not state["has_size"]:
            _fail("size_mode", "From column sizing requires a Size column.")
        out["size_mode"] = options["size_mode"]

    if "maximum_area" in options:
        val = _optional_number(options["maximum_area"], "maximum_area")
        if val is None or not 0 < val <= AREA_LIMIT:
            _fail("maximum_area", f"Maximum area must be greater than 0 and at most {AREA_LIMIT:,.0f} pt².")
        out["maximum_area"] = float(val)

    if "fixed_area" in options:
        val = _optional_number(options["fixed_area"], "fixed_area")
        if val is None or not 0 < val <= AREA_LIMIT:
            _fail("fixed_area", f"Fixed area must be greater than 0 and at most {AREA_LIMIT:,.0f} pt².")
        out["fixed_area"] = float(val)

    for bkey in ("show_size_legend", "reverse", "show_color_legend", "show_shape_legend", "show_labels"):
        if bkey in options:
            if not isinstance(options[bkey], (bool, np.bool_)):
                _fail(bkey, f"{bkey}: choose on or off.")
            out[bkey] = bool(options[bkey])

    if "fill_mode" in options:
        if options["fill_mode"] not in FILL_MODES:
            _fail("fill_mode", "Choose a valid fill color mode.")
        if state is not None and options["fill_mode"] == FILL_CONTINUOUS and not state["has_color"]:
            _fail("fill_mode", "Continuous scale requires a Color column.")
        out["fill_mode"] = options["fill_mode"]

    if "fixed_color" in options:
        out["fixed_color"] = _clean_color(options["fixed_color"], "fixed_color")

    if "category_colors" in options:
        out["category_colors"] = _validate_mapping(options["category_colors"], "category_colors", _clean_color)

    if "palette" in options:
        if options["palette"] not in BUBBLE_PALETTES:
            _fail("palette", "Choose a supported palette.")
        out["palette"] = options["palette"]

    if "limits_mode" in options:
        if options["limits_mode"] not in LIMITS_MODES:
            _fail("limits_mode", "Choose Automatic or Manual color limits.")
        out["limits_mode"] = options["limits_mode"]

    for nkey in ("color_min", "color_mid", "color_max"):
        if nkey in options:
            out[nkey] = _optional_number(options[nkey], nkey)

    if "missing_color" in options:
        out["missing_color"] = _clean_color(options["missing_color"], "missing_color")

    if "color_title" in options:
        title = options["color_title"]
        if title is None:
            out["color_title"] = ""
        elif not isinstance(title, str) or len(title) > MAX_LABELS_LEN:
            _fail("color_title", "Color scale title must be up to 160 characters.")
        else:
            out["color_title"] = title.strip()

    if "shape_mode" in options:
        if options["shape_mode"] not in SHAPE_MODES:
            _fail("shape_mode", "Choose a valid shape mode.")
        if state is not None and options["shape_mode"] == SHAPE_BY_CATEGORY and not state["has_shape"]:
            _fail("shape_mode", "By category shape requires a Shape column.")
        out["shape_mode"] = options["shape_mode"]

    def _check_shape(val, fld):
        if val not in SHAPE_CHOICES:
            _fail(fld, "Choose a valid symbol shape.")
        return val

    if "fixed_shape" in options:
        out["fixed_shape"] = _check_shape(options["fixed_shape"], "fixed_shape")

    if "missing_shape" in options:
        out["missing_shape"] = _check_shape(options["missing_shape"], "missing_shape")

    if "shape_map" in options:
        out["shape_map"] = _validate_mapping(options["shape_map"], "shape_map", _check_shape)

    effective_mode = out.get("limits_mode", state["default_encoding"]["limits_mode"] if state else LIMITS_AUTO)
    cmin = out.get("color_min", state["default_encoding"]["color_min"] if state else None)
    cmax = out.get("color_max", state["default_encoding"]["color_max"] if state else None)
    cmid = out.get("color_mid", state["default_encoding"]["color_mid"] if state else None)
    # Note: manual limits checked carefully on merged state below in apply_bubble_style too.
    if effective_mode == LIMITS_MANUAL:
        if cmin is None or cmax is None:
            _fail("color_min" if cmin is None else "color_max",
                  "Enter finite Color minimum and Color maximum when limits are Manual.")
        if cmin >= cmax:
            _fail("color_min", "Color minimum must be strictly less than Color maximum.")
        if cmid is not None and not (cmin < cmid < cmax):
            _fail("color_mid", "Diverging midpoint must lie strictly between Color minimum and Color maximum.")
    return out


def describe_bubble_artists(figure):
    """Return bubble presentation metadata if ``figure`` is a native Bubble plot, else empty dict."""
    state = getattr(figure, ATTR, None)
    return dict(state) if isinstance(state, dict) else {}


def baseline_bubble_style(figure):
    """Canonical recipe baseline settings for dialogs and Inspector."""
    state = getattr(figure, ATTR, None)
    if not isinstance(state, dict):
        return {}
    return deepcopy(state["default_encoding"])


def snapshot_bubble_style(figure):
    """Current effective bubble presentation settings."""
    state = getattr(figure, ATTR, None)
    if not isinstance(state, dict):
        return {}
    return deepcopy(state["effective_encoding"])


def _lookup_level(mapping, token, label):
    if not mapping:
        return None
    if token in mapping:
        return mapping[token]
    if label in mapping:
        return mapping[label]
    if token.startswith("float:"):
        try:
            fval = float(token[6:])
            if fval.is_integer():
                alt = f"int:{int(fval)}"
                if alt in mapping:
                    return mapping[alt]
        except ValueError:
            pass
    elif token.startswith("int:"):
        alt = f"float:{float(int(token[4:]))!r}"
        if alt in mapping:
            return mapping[alt]
    return None


def resolve_shape_assignment(state, merged):
    """Compute per-point marker array, level summary entries and repetition warnings."""
    n = len(state["source_rows"])
    shape_mode = merged["shape_mode"]
    fixed_shape = merged["fixed_shape"]
    if shape_mode == SHAPE_FIXED or not state["has_shape"]:
        return {
            "mode": SHAPE_FIXED,
            "markers": np.full(n, fixed_shape, dtype=object),
            "shape_keys": [None] * n,
            "levels": [],
            "has_missing": False,
            "warning": None,
        }

    levels = state["shape_levels"]
    disambiguated = state["shape_display_map"]
    row_entries = state["shape_rows"]
    shape_map = merged["shape_map"]
    missing_shape = merged["missing_shape"]

    assigned = {}
    used_auto = set()
    # First reserve explicit manual overrides so automatic levels pick unused primary markers cleanly.
    for item in levels:
        token, label = item[0], item[1]
        picked = _lookup_level(shape_map, token, label)
        if picked is not None:
            assigned[token] = picked
            used_auto.add(picked)

    unused = [m for m in PRIMARY_SHAPES if m not in used_auto]
    cycle_pos = 0
    for item in levels:
        token = item[0]
        if token in assigned:
            continue
        if unused:
            assigned[token] = unused.pop(0)
        else:
            assigned[token] = PRIMARY_SHAPES[cycle_pos % len(PRIMARY_SHAPES)]
            cycle_pos += 1

    markers = np.empty(n, dtype=object)
    shape_keys = []
    has_missing = False
    for idx, entry in enumerate(row_entries):
        if entry is None:
            markers[idx] = missing_shape
            shape_keys.append(None)
            has_missing = True
        else:
            markers[idx] = assigned[entry[0]]
            shape_keys.append(entry[3])

    used_symbols = list(assigned.values())
    duplicate_symbols = len(set(used_symbols)) < len(used_symbols)
    missing_collision = has_missing and missing_shape in used_symbols
    warning = None
    if len(levels) > len(PRIMARY_SHAPES) or duplicate_symbols or missing_collision:
        warning = tr("bubble.style.warning.shape_repeat", limit=len(PRIMARY_SHAPES))

    level_rows = [
        {
            "token": item[0],
            "raw_label": item[1],
            "display": disambiguated[item[0]],
            "type_key": item[2],
            "marker": assigned[item[0]],
            "shape_key": item[3],
        }
        for item in levels
    ]
    return {
        "mode": SHAPE_BY_CATEGORY,
        "markers": markers,
        "shape_keys": shape_keys,
        "levels": level_rows,
        "has_missing": has_missing,
        "missing_shape": missing_shape,
        "warning": warning,
    }


def normalize_continuous_signal(values, *, reverse, limits_mode, color_min, color_mid, color_max):
    """Map numeric signal vector (for drawn points only) onto clamped ``u in [0, 1]`` and MPL Norm."""
    finite = np.isfinite(values)
    valid = values[finite]
    if valid.size == 0:
        return {
            "all_missing": True,
            "any_missing": True,
            "constant": False,
            "limits": None,
            "midpoint": None,
            "norm": None,
            "u": np.full(len(values), np.nan, dtype=float),
        }

    any_missing = bool((~finite).any())
    if limits_mode == LIMITS_MANUAL:
        low, high = float(color_min), float(color_max)
    else:
        low, high = float(valid.min()), float(valid.max())

    if low == high:
        u = np.full(len(values), np.nan, dtype=float)
        u[finite] = 0.5
        return {
            "all_missing": False,
            "any_missing": any_missing,
            "constant": True,
            "constant_value": low,
            "limits": (low, high),
            "midpoint": None,
            "norm": Normalize(vmin=low - 0.5, vmax=high + 0.5, clip=True),
            "u": u,
        }

    if color_mid is not None:
        mid = float(color_mid)
        if limits_mode == LIMITS_AUTO and not (low < mid < high):
            span = max(abs(high - mid), abs(low - mid), 1.0)
            low = min(low, mid - span)
            high = max(high, mid + span)
        norm = TwoSlopeNorm(vcenter=mid, vmin=low, vmax=high)
        clipped = np.clip(valid, low, high)
        raw_u = np.clip(np.asarray(norm(clipped), dtype=float), 0.0, 1.0)
    else:
        mid = None
        norm = Normalize(vmin=low, vmax=high, clip=True)
        clipped = np.clip(valid, low, high)
        raw_u = np.clip(np.asarray(norm(clipped), dtype=float), 0.0, 1.0)

    u_eff = (1.0 - raw_u) if reverse else raw_u
    u = np.full(len(values), np.nan, dtype=float)
    u[finite] = u_eff
    return {
        "all_missing": False,
        "any_missing": any_missing,
        "constant": False,
        "limits": (low, high),
        "midpoint": mid,
        "norm": norm,
        "u": u,
    }


def resolve_colors(state, merged):
    """Compute per-point RGBA array and legend/colorbar metadata."""
    n = len(state["source_rows"])
    fill_mode = merged["fill_mode"]
    if fill_mode == FILL_CONTINUOUS and state["has_color"]:
        scale = normalize_continuous_signal(
            state["color_values"],
            reverse=merged["reverse"],
            limits_mode=merged["limits_mode"],
            color_min=merged["color_min"],
            color_mid=merged["color_mid"],
            color_max=merged["color_max"],
        )
        palette_name = merged["palette"]
        base_cmap = colormaps[BUBBLE_PALETTES[palette_name]]
        display_cmap = _ExactReverse(base_cmap) if merged["reverse"] else base_cmap
        missing_hex = merged["missing_color"]
        missing_rgba = np.array(colormaps["viridis"](0.0)[:4], dtype=float)
        from matplotlib.colors import to_rgba
        missing_rgba = np.array(to_rgba(missing_hex, ALPHA), dtype=float)

        rgba = np.tile(missing_rgba, (n, 1))
        finite = np.isfinite(scale["u"])
        if finite.any():
            # Apply u directly to base_cmap: u already incorporates reversal (1 - u_raw) cleanly.
            mapped = np.asarray(base_cmap(scale["u"][finite], alpha=ALPHA), dtype=float)
            if mapped.ndim == 1:
                mapped = mapped[None, :]
            rgba[finite] = mapped
        hex_colors = [to_hex(row[:3], keep_alpha=False) for row in rgba]
        return {
            "mode": FILL_CONTINUOUS,
            "rgba": rgba,
            "hex": hex_colors,
            "u": scale["u"],
            "limits": scale["limits"],
            "midpoint": scale["midpoint"],
            "norm": scale["norm"],
            "cmap": display_cmap,
            "all_missing": scale["all_missing"],
            "any_missing": scale["any_missing"],
            "constant": scale["constant"],
            "constant_value": scale.get("constant_value"),
            "missing_hex": missing_hex,
            "group_entries": [],
        }

    from matplotlib.colors import to_rgba
    if fill_mode == FILL_FIXED or not state["has_group"]:
        color_hex = merged["fixed_color"] if fill_mode == FILL_FIXED else (
            merged["category_colors"].get("__single__") or merged["fixed_color"]
        )
        rgba_one = np.array(to_rgba(color_hex, ALPHA), dtype=float)
        return {
            "mode": fill_mode,
            "rgba": np.tile(rgba_one, (n, 1)),
            "hex": [color_hex] * n,
            "u": None,
            "limits": None,
            "midpoint": None,
            "norm": None,
            "cmap": None,
            "all_missing": False,
            "any_missing": False,
            "constant": False,
            "missing_hex": merged["missing_color"],
            "group_entries": [],
        }

    # FILL_BY_CATEGORY with Group column
    levels = state["group_levels"]
    disambiguated = state["group_display_map"]
    row_entries = state["group_rows"]
    custom = merged["category_colors"]
    rgba = np.empty((n, 4), dtype=float)
    hex_colors = [None] * n
    level_color = {}
    palette_iter = iter(COLORS * (len(levels) // len(COLORS) + 1))
    group_entries = []
    for item in levels:
        token, label = item[0], item[1]
        picked = _lookup_level(custom, token, label) or next(palette_iter)
        level_color[token] = picked
        group_entries.append((token, disambiguated[token], picked))

    has_blank = False
    blank_hex = _lookup_level(custom, "__neutral__", NEUTRAL) or NEUTRAL_COLOR
    for idx, entry in enumerate(row_entries):
        if entry is None:
            has_blank = True
            col = blank_hex
        else:
            col = level_color[entry[0]]
        hex_colors[idx] = col
        rgba[idx] = to_rgba(col, ALPHA)
    if has_blank:
        group_entries.append(("__neutral__", NEUTRAL, blank_hex))
    return {
        "mode": FILL_BY_CATEGORY,
        "rgba": rgba,
        "hex": hex_colors,
        "u": None,
        "limits": None,
        "midpoint": None,
        "norm": None,
        "cmap": None,
        "all_missing": False,
        "any_missing": False,
        "constant": False,
        "missing_hex": merged["missing_color"],
        "group_entries": group_entries,
    }


def resolve_sizes(state, merged):
    n = len(state["source_rows"])
    if merged["size_mode"] == SIZE_FIXED or not state["has_size"]:
        area = float(merged["fixed_area"])
        return {
            "mode": SIZE_FIXED,
            "areas": np.full(n, area, dtype=float),
            "largest": None,
            "maximum_area": float(merged["maximum_area"]),
            "fixed_area": area,
            "references": [],
        }
    sizes = state["size_values"]
    largest = float(sizes.max())
    max_area = float(merged["maximum_area"])
    areas = max_area * (sizes / largest)
    picked = []
    for val in (largest, float(np.median(sizes)), float(sizes.min())):
        lbl = f"{val:.4g}"
        if all(lbl != ex for _, ex in picked):
            picked.append((val, lbl))
    return {
        "mode": SIZE_BY_COLUMN,
        "areas": areas,
        "largest": largest,
        "maximum_area": max_area,
        "fixed_area": float(merged["fixed_area"]),
        "references": picked,
    }


def _detach_previous(figure, axes):
    old_cbar = getattr(axes, "_tramastat_bubble_colorbar", None)
    if old_cbar is not None:
        try:
            old_cbar.remove()
        except Exception:
            if old_cbar.ax in figure.axes:
                figure.delaxes(old_cbar.ax)
        axes._tramastat_bubble_colorbar = None

    for coll in list(axes.collections):
        gid = str(coll.get_gid() or "")
        if gid.startswith("bubble:") or gid == "bubble-batch":
            coll.remove()

    for txt in list(axes.texts):
        if getattr(txt, "_tramastat_bubble_label", False):
            txt.remove()

    leg = axes.get_legend()
    if leg is not None and getattr(leg, "_tramastat_bubble_owned", False):
        leg.remove()

    for art in list(axes.artists):
        if getattr(art, "_tramastat_bubble_owned", False) or str(art.get_gid() or "").startswith("bubble-"):
            art.remove()
    axes._tramastat_size_legend = None

    for fig_leg in list(figure.legends):
        if getattr(fig_leg, "_tramastat_bubble_owned", False) or str(fig_leg.get_gid() or "").startswith("bubble-"):
            fig_leg.remove()


def _attach_unit_footer(legend, text, figure):
    if not text:
        return
    ta = TextArea(text, textprops={"fontsize": 8, "color": "#4f5b66"})
    ta.set_figure(figure)
    ta.set_gid("bubble-size-unit")
    box = HPacker(children=[ta], pad=0, sep=0)
    box.set_figure(figure)
    legend._legend_box.get_children().append(box)


def _is_pure_legacy_render(state, merged):
    return (
        merged["size_mode"] == SIZE_BY_COLUMN
        and merged["fill_mode"] == FILL_BY_CATEGORY
        and merged["shape_mode"] == SHAPE_FIXED
        and merged["fixed_shape"] == "o"
        and not merged["category_colors"]
        and state["has_size"]
    )


def render_bubble_plot(figure, state, merged, *, preserve_legacy_series=False, style=None):
    """Render or update all bubble collections, colorbar, legends and labels in place."""
    if not figure.axes:
        return
    axes = figure.axes[0]
    axes._tramastat_bubble_x = axes._tramastat_bubble_x if hasattr(axes, "_tramastat_bubble_x") else None

    if preserve_legacy_series and _is_pure_legacy_render(state, merged):
        # Preserve edited scatter series from older saved styles unless bubble overrides changed.
        size_res = resolve_sizes(state, merged)
        color_res = resolve_colors(state, merged)
        shape_res = resolve_shape_assignment(state, merged)
        _store_rendered(state, merged, size_res, color_res, shape_res)
        return

    _detach_previous(figure, axes)

    x = state["x"]
    y = state["y"]
    n = len(x)
    size_res = resolve_sizes(state, merged)
    color_res = resolve_colors(state, merged)
    shape_res = resolve_shape_assignment(state, merged)
    areas = size_res["areas"]
    rgba = color_res["rgba"]
    markers = shape_res["markers"]
    legacy_mode = _is_pure_legacy_render(state, merged)

    recipe_keys = state.get("recipe_names", ("Bubble plot",))
    rows = state["source_rows"]
    sheet_rows = state.get("sheet_rows", len(rows))

    if legacy_mode:
        # Preserve exact v0.116.0 per-group collections and gid naming (`bubble:<group>`).
        if not state["has_group"]:
            col = axes.scatter(
                x, y, s=areas, marker="o", color=COLORS[0], alpha=ALPHA,
                edgecolors="white", linewidths=0.7, label="_nolegend_", zorder=2.5,
            )
            col.set_gid("bubble:")
            attach_points(col, rows, x, y, recipe_keys, sheet_rows, data=state.get("row_spans_data"))
        else:
            row_entries = state["group_rows"]
            disamb = state["group_display_map"]
            for token, disp_name, color_hex in color_res["group_entries"]:
                if token == "__neutral__":
                    mask = np.array([e is None for e in row_entries], dtype=bool)
                else:
                    mask = np.array([e is not None and e[0] == token for e in row_entries], dtype=bool)
                col = axes.scatter(
                    x[mask], y[mask], s=areas[mask], marker="o", color=color_hex, alpha=ALPHA,
                    edgecolors="white", linewidths=0.7, label=disp_name, zorder=2.5,
                )
                col.set_gid(f"bubble:{disp_name}")
                attach_points(col, rows[mask], x[mask], y[mask], recipe_keys, sheet_rows, data=state.get("row_spans_data"))
    else:
        # Vectorized batch per unique shape marker: 50k points fit into 1-14 collections (~20-50 ms).
        unique_markers = list(dict.fromkeys(markers.tolist()))
        for marker in unique_markers:
            mask = markers == marker
            filled = marker not in UNFILLED_MARKERS
            if filled:
                col = axes.scatter(
                    x[mask], y[mask], s=areas[mask], marker=marker,
                    facecolors=rgba[mask], edgecolors="white", linewidths=0.7,
                    label="_nolegend_", zorder=2.5,
                )
            else:
                col = axes.scatter(
                    x[mask], y[mask], s=areas[mask], marker=marker,
                    c=rgba[mask], linewidths=1.5,
                    label="_nolegend_", zorder=2.5,
                )
            col.set_gid(f"bubble:shape:{marker}")
            attach_points(col, rows[mask], x[mask], y[mask], recipe_keys, sheet_rows, data=state.get("row_spans_data"))

    axes.margins(0.08)

    # Point annotations (capped at MAX_LABELS)
    labels = state.get("labels")
    if labels is not None and merged["show_labels"]:
        labeled = [(idx, txt) for idx, txt in enumerate(labels) if txt is not None]
        if len(labeled) <= MAX_LABELS:
            x_min = float(x.min()) if len(x) else 0.0
            x_max = float(x.max()) if len(x) else 1.0
            x_span = x_max - x_min
            flip_threshold = x_min + 0.72 * x_span if (not legacy_mode and x_span > 0) else float("inf")
            for idx, txt in labeled:
                offset = sqrt(areas[idx]) / 2.0 + 2.0
                flip_left = x[idx] > flip_threshold
                note = axes.annotate(
                    txt,
                    (x[idx], y[idx]),
                    xytext=(-offset if flip_left else offset, 0),
                    textcoords="offset points",
                    va="center",
                    ha="right" if flip_left else "left",
                    fontsize=8,
                    color="#34414f",
                    zorder=3,
                )
                note.set_parse_math(False)
                note._tramastat_bubble_label = True

    # Legends & Colorbar placement
    has_colorbar = (
        color_res["mode"] == FILL_CONTINUOUS
        and merged["show_color_legend"]
        and not color_res["all_missing"]
    )
    has_shape_leg = shape_res["mode"] == SHAPE_BY_CATEGORY and merged["show_shape_legend"]
    has_group_leg = color_res["mode"] == FILL_BY_CATEGORY and state["has_group"] and len(color_res["group_entries"]) > 0
    has_missing_leg = (
        color_res["mode"] == FILL_CONTINUOUS
        and merged["show_color_legend"]
        and (color_res["all_missing"] or color_res["any_missing"])
    )
    use_figure_gutters = not legacy_mode and (has_colorbar or has_shape_leg or has_missing_leg)

    if has_colorbar:
        sm = ScalarMappable(norm=color_res["norm"], cmap=color_res["cmap"])
        sm.set_array([])
        title = merged["color_title"] or state["color_column"]
        cb = figure.colorbar(sm, ax=axes, label=title, pad=0.025, fraction=0.042)
        cb.ax.yaxis.label.set_parse_math(False)
        if color_res["constant"]:
            val = color_res["constant_value"]
            cb.set_ticks([val])
            cb.set_ticklabels([f"{val:g}"])
        axes._tramastat_bubble_colorbar = cb

    if legacy_mode:
        if has_group_leg:
            leg_group = axes.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0,
                                    title=state["group_column"])
            leg_group._tramastat_bubble_owned = True
            leg_group.set_in_layout(True)
            for handle in leg_group.legend_handles:
                handle.set_sizes([64.0])
            for t in [leg_group.get_title(), *leg_group.get_texts()]:
                t.set_parse_math(False)
        if merged["show_size_legend"]:
            handles = [
                Line2D([], [], marker="o", linestyle="none",
                       markersize=sqrt(size_res["maximum_area"] * v / size_res["largest"]),
                       markerfacecolor=(0.55, 0.6, 0.65, ALPHA), markeredgecolor="white")
                for v, _ in size_res["references"]
            ]
            leg_size = Legend(
                axes, handles, [lbl for _, lbl in size_res["references"]],
                title=state["size_column"], loc="lower left", bbox_to_anchor=(1.02, 0),
                borderaxespad=0, labelspacing=1.4, borderpad=0.9, frameon=False,
            )
            leg_size.get_title().set_parse_math(False)
            leg_size.set_gid("bubble-size-legend")
            leg_size._tramastat_bubble_owned = True
            leg_size.set_in_layout(True)
            unit = tr("bubble.legend.unit_max", name=state["size_column"], area=f"{size_res['maximum_area']:g}")
            _attach_unit_footer(leg_size, unit, figure)
            axes.add_artist(leg_size)
            axes._tramastat_size_legend = leg_size
    else:
        # Independent, non-overlapping right-gutter guides managed by constrained_layout.
        def _make_fig_legend(handles, labels, title, loc, gid, *, ncol=1, labelspacing=0.6):
            leg = figure.legend(
                handles, labels, title=title, loc=loc, frameon=False,
                ncol=ncol, fontsize=8.5, title_fontsize=9.5, labelspacing=labelspacing,
            )
            leg.set_gid(gid)
            leg._tramastat_bubble_owned = True
            leg.get_title().set_parse_math(False)
            for t in leg.get_texts():
                t.set_parse_math(False)
            return leg

        if has_group_leg:
            g_handles = [
                Line2D([], [], marker="o", linestyle="none", markersize=7.5,
                       markerfacecolor=(col), markeredgecolor="white", alpha=ALPHA)
                for _, _, col in color_res["group_entries"]
            ]
            g_labels = [lbl for _, lbl, _ in color_res["group_entries"]]
            _make_fig_legend(g_handles, g_labels, state["group_column"],
                             "outside right upper", "bubble-group-legend",
                             ncol=(2 if len(g_labels) > 6 else 1))

        if has_shape_leg:
            s_handles = [
                Line2D([], [], marker=row["marker"], linestyle="none", markersize=7.5,
                       markerfacecolor="#4d5a68", markeredgecolor="#4d5a68", color="#4d5a68")
                for row in shape_res["levels"]
            ]
            s_labels = [row["display"] for row in shape_res["levels"]]
            if shape_res["has_missing"]:
                m_shape = shape_res["missing_shape"]
                s_handles.append(Line2D([], [], marker=m_shape, linestyle="none", markersize=7.5,
                                        markerfacecolor="#7d8894", markeredgecolor="#7d8894", color="#7d8894"))
                s_labels.append(tr("bubble.legend.missing"))
            shape_loc = "outside right center" if has_group_leg else "outside right upper"
            _make_fig_legend(s_handles, s_labels, state["shape_column"], shape_loc,
                             "bubble-shape-legend", ncol=(2 if len(s_labels) > 6 else 1))

        if has_missing_leg:
            m_label = tr("bubble.legend.all_missing") if color_res["all_missing"] else tr("bubble.legend.missing")
            m_handle = Line2D([], [], marker="o", linestyle="none", markersize=7.5,
                              markerfacecolor=color_res["missing_hex"], markeredgecolor="white", alpha=ALPHA)
            m_loc = "outside right center" if (has_shape_leg or not color_res["all_missing"]) else "outside right upper"
            m_title = (merged["color_title"] or state["color_column"]) if color_res["all_missing"] else ""
            _make_fig_legend([m_handle], [m_label], m_title, m_loc, "bubble-missing-legend")

        if merged["show_size_legend"]:
            if size_res["mode"] == SIZE_BY_COLUMN:
                sz_handles = [
                    Line2D([], [], marker="o", linestyle="none",
                           markersize=sqrt(size_res["maximum_area"] * v / size_res["largest"]),
                           markerfacecolor=(0.55, 0.6, 0.65, ALPHA), markeredgecolor="white")
                    for v, _ in size_res["references"]
                ]
                sz_labels = [lbl for _, lbl in size_res["references"]]
                sz_title = state["size_column"]
                unit = tr("bubble.legend.unit_max", name=state["size_column"], area=f"{size_res['maximum_area']:g}")
            else:
                sz_handles = [
                    Line2D([], [], marker="o", linestyle="none",
                           markersize=sqrt(size_res["fixed_area"]),
                           markerfacecolor=(0.55, 0.6, 0.65, ALPHA), markeredgecolor="white")
                ]
                sz_labels = [f"{size_res['fixed_area']:g} pt²"]
                sz_title = tr("bubble.style.group.size")
                unit = tr("bubble.legend.unit_fixed", area=f"{size_res['fixed_area']:g}")
            if use_figure_gutters:
                leg_size = _make_fig_legend(sz_handles, sz_labels, sz_title, "outside right lower",
                                            "bubble-size-legend", labelspacing=1.2)
            else:
                leg_size = Legend(
                    axes, sz_handles, sz_labels, title=sz_title, loc="lower left",
                    bbox_to_anchor=(1.02, 0), borderaxespad=0, labelspacing=1.2, borderpad=0.9, frameon=False,
                )
                leg_size.get_title().set_parse_math(False)
                leg_size.set_gid("bubble-size-legend")
                leg_size._tramastat_bubble_owned = True
                leg_size.set_in_layout(True)
                axes.add_artist(leg_size)
            _attach_unit_footer(leg_size, unit, figure)
            axes._tramastat_size_legend = leg_size

    _store_rendered(state, merged, size_res, color_res, shape_res)


def _store_rendered(state, merged, size_res, color_res, shape_res):
    state["effective_encoding"] = deepcopy(merged)
    state["shape_warning"] = shape_res.get("warning")
    state["color_summary"] = {
        "limits": color_res["limits"],
        "midpoint": color_res["midpoint"],
        "all_missing": color_res["all_missing"],
        "any_missing": color_res["any_missing"],
        "constant": color_res["constant"],
        "constant_value": color_res.get("constant_value"),
    }
    state["size_summary"] = {
        "mode": size_res["mode"],
        "largest": size_res["largest"],
        "references": size_res["references"],
        "maximum_area": size_res["maximum_area"],
        "fixed_area": size_res["fixed_area"],
    }
    state["shape_summary"] = {
        "mode": shape_res["mode"],
        "levels": shape_res["levels"],
        "has_missing": shape_res["has_missing"],
        "warning": shape_res["warning"],
    }
    state["rendered_points"] = {
        "source_rows": state["source_rows"],
        "x": state["x"],
        "y": state["y"],
        "area_pt2": size_res["areas"],
        "color_u": color_res["u"],
        "color_hex": color_res["hex"],
        "markers": shape_res["markers"],
        "shape_keys": shape_res["shape_keys"],
    }


def apply_bubble_style(figure, options, *, style=None):
    """Apply canonical ``style['bubble']`` overrides to a live Bubble plot figure."""
    state = getattr(figure, ATTR, None)
    if not isinstance(state, dict):
        return
    canonical = validate_bubble_style(options or {}, figure=figure)
    baseline = state["default_encoding"]
    merged = {**baseline, **canonical}
    if merged["limits_mode"] == LIMITS_MANUAL:
        cmin, cmax, cmid = merged["color_min"], merged["color_max"], merged["color_mid"]
        if cmin is None or cmax is None:
            _fail("color_min" if cmin is None else "color_max",
                  "Enter finite Color minimum and Color maximum when limits are Manual.")
        if cmin >= cmax:
            _fail("color_min", "Color minimum must be strictly less than Color maximum.")
        if cmid is not None and not (cmin < cmid < cmax):
            _fail("color_mid", "Diverging midpoint must lie strictly between Color minimum and Color maximum.")
    already_pure_legacy = (
        not canonical
        and state["effective_encoding"] == baseline
        and _is_pure_legacy_render(state, baseline)
        and any(str(c.get_gid() or "").startswith("bubble:") for c in figure.axes[0].collections)
    )
    render_bubble_plot(
        figure, state, merged,
        preserve_legacy_series=already_pure_legacy,
        style=style,
    )


def build_bubble_tables(state):
    """Build synchronized ``Bubble values`` and ``Settings`` DataFrames from rendered state."""
    from .reporting import _report

    merged = state["effective_encoding"]
    pts = state["rendered_points"]
    n = len(state["source_rows"])
    columns = {
        "Source row": pts["source_rows"],
        "X": pts["x"],
        "Y": pts["y"],
    }
    if state["has_size"]:
        columns["Size"] = state["size_values"]
    columns["Marker area (pt²)"] = pts["area_pt2"]

    is_legacy = (
        merged["size_mode"] == SIZE_BY_COLUMN
        and merged["fill_mode"] == FILL_BY_CATEGORY
        and merged["shape_mode"] == SHAPE_FIXED
        and merged["fixed_shape"] == "o"
        and not merged["category_colors"]
        and merged == state["default_encoding"]
    )
    if state["has_group"] and (merged["fill_mode"] == FILL_BY_CATEGORY or is_legacy):
        columns["Group"] = state["group_raw"]
    if not is_legacy:
        if state["has_color"] and merged["fill_mode"] == FILL_CONTINUOUS:
            columns["Color"] = state["color_values"]
            columns["Color position (u)"] = pts["color_u"]
        columns["Fill color"] = pts["color_hex"]
        if state["has_shape"] and merged["shape_mode"] == SHAPE_BY_CATEGORY:
            columns["Shape"] = state["shape_raw"]
        columns["Symbol"] = list(pts["markers"])
    if state["has_label"]:
        columns["Label"] = state["label_raw"]

    sheet = pd.DataFrame(columns)

    sz = state["size_summary"]
    cs = state["color_summary"]
    ss = state["shape_summary"]
    omitted_label = (
        "Rows omitted (missing or excluded X, Y or Size)"
        if merged["size_mode"] == SIZE_BY_COLUMN
        else "Rows omitted (missing or excluded X or Y)"
    )
    settings = {
        "X": state["x_column"],
        "Y": state["y_column"],
        "Size mode": merged["size_mode"],
        "Size": state["size_column"] or "None",
        "Fill color": merged["fill_mode"],
        "Group": state["group_column"] or "None",
        "Color": state["color_column"] or "None",
        "Shape mode": merged["shape_mode"],
        "Shape": state["shape_column"] or "None",
        "Label": state["label_column"] or "None",
        "Rows drawn": n,
        omitted_label: state["omitted_missing"],
        "Rows omitted (size zero)": state["omitted_zero"],
    }
    if merged["size_mode"] == SIZE_BY_COLUMN:
        settings["Area rule"] = "area = Maximum area × Size / largest drawn Size (shared by every group)"
        settings["Largest drawn size"] = sz["largest"]
        settings[MAX_AREA] = sz["maximum_area"]
        settings["Area units"] = "pt²"
        refs = ", ".join(lbl for _, lbl in sz["references"])
        settings["Size legend"] = refs if merged["show_size_legend"] else "Hidden"
        settings["Zero sizes"] = state["zero_policy"]
    else:
        settings["Area rule"] = f"area = Fixed area ({sz['fixed_area']:g} pt²)"
        settings[FIXED_AREA] = sz["fixed_area"]
        settings["Area units"] = "pt²"

    if merged["fill_mode"] == FILL_CONTINUOUS and state["has_color"]:
        settings[PALETTE] = merged["palette"]
        settings[REVERSE_PALETTE] = merged["reverse"]
        settings[COLOR_LIMITS] = merged["limits_mode"]
        if cs["all_missing"]:
            settings["Color range"] = f"All drawn values missing ({state['color_column']}); drawn in {merged['missing_color']}"
        elif cs["constant"]:
            settings["Color range"] = f"Constant value {cs['constant_value']:g} (center color)"
        else:
            lo, hi = cs["limits"]
            settings["Color range"] = f"{lo:g} to {hi:g}"
            if cs["midpoint"] is not None:
                settings[COLOR_MID] = cs["midpoint"]
            if cs["any_missing"]:
                settings[MISSING_COLOR] = merged["missing_color"]
    elif merged["fill_mode"] == FILL_FIXED:
        settings[FIXED_COLOR] = merged["fixed_color"]

    if merged["shape_mode"] == SHAPE_BY_CATEGORY and state["has_shape"]:
        settings["Shape mapping"] = ", ".join(f"{row['display']} -> {row['marker']}" for row in ss["levels"])
        settings[MISSING_SHAPE] = merged["missing_shape"]
        if ss["warning"]:
            settings["Shape repetition"] = ss["warning"]
    else:
        settings[FIXED_SHAPE] = merged["fixed_shape"]

    settings["Labels"] = state["label_note"]
    if state.get("has_blank_group"):
        settings["Blank groups"] = f'Drawn in gray as "{NEUTRAL}".'
    return sheet, _report(settings)


def sync_bubble_tables(result):
    """Refresh ``Bubble values`` and ``Settings`` on a Result directly from its figure state."""
    if result is None or result.figure is None:
        return
    state = getattr(result.figure, ATTR, None)
    if not isinstance(state, dict):
        return
    sheet, settings = build_bubble_tables(state)
    result.tables[SHEET] = sheet
    result.tables["Settings"] = settings
