"""Presentation overrides for native hierarchical clustering figures.

The module is importable without Tk. It never refits a tree, never rebuilds the
canvas and never changes branch coordinates, matrix values or result tables.
A partial override inherits the appearance captured by the renderer, not the
previous draft. ``{}`` restores that captured appearance.
"""

from copy import deepcopy
from functools import partial
import math

import numpy as np
from matplotlib import colormaps
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.colors import Colormap, to_hex, to_rgba
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.ticker import AutoLocator, FixedFormatter, MultipleLocator
from matplotlib.transforms import Bbox


class _ExactReverse(Colormap):
    """Reverse a colormap by lookup, not by resampling its table.

    ``Colormap.reversed()`` rebuilds the lookup table, so ``plasma_r(0.25)`` is
    not exactly ``plasma(0.75)``. Sampling ``1 - x`` keeps that identity.
    """

    def __init__(self, name):
        self._base = colormaps[name]
        super().__init__(f"{name}_r", self._base.N)

    def __call__(self, X, alpha=None, bytes=False):
        values = np.array(X, copy=True, dtype=float)
        return self._base(1.0 - values, alpha=alpha, bytes=bytes)


ATTR = "_tramastat_hierarchical"
CMAPS = ("viridis", "plasma", "magma", "cividis", "coolwarm", "RdBu_r")
LINE_STYLES = ("solid", "dashed", "dotted", "dashdot")
COLOR_MODES = ("analysis", "single", "cluster")
ORIENTATIONS = ("vertical", "horizontal")
ASPECTS = ("auto", "equal")
TREE_KEYS = ("row", "column")
ROOT_KEYS = ("row", "column", "heatmap", "layout")
TREE_FIELDS = ("visible", "color_mode", "color", "mixed_color", "palette", "width", "line_style", "alpha",
               "labels", "distance")
LABEL_FIELDS = ("visible", "rotation", "size", "color", "first", "interval")
DISTANCE_FIELDS = ("visible", "minimum", "maximum", "step", "reversed")
MAX_DISTANCE_TICKS = 200
HEAT_FIELDS = ("cmap", "reverse", "minimum", "maximum", "colorbar", "title", "orientation", "cell_aspect")
LAYOUT_FIELDS = ("row_tree_ratio", "column_tree_ratio")
# Collapsed colorbar column. The axis stays in the figure; it just stops taking space.
_COLLAPSED = 0.02


class HierarchicalStyleError(ValueError):
    """A style value the renderer will not apply. ``field`` is a canonical path."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def _fail(field, message):
    raise HierarchicalStyleError(field, message)


def _path(prefix, key):
    return f"{prefix}.{key}" if prefix else key


def _mapping(value, field):
    if not isinstance(value, dict):
        _fail(field or "hierarchical", "Expected an object of presentation settings.")
    return value


def _unknown(value, allowed, prefix):
    for key in value:
        if key not in allowed:
            _fail(_path(prefix, key), f"Unknown setting {_path(prefix, key)}.")


def _number(value, field):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        _fail(field, "Enter a finite number.")
    return value


def _bool(value, field):
    if type(value) is not bool:
        _fail(field, "Choose yes or no.")
    return value


def _choice(value, allowed, field):
    if value not in allowed:
        _fail(field, "Choose one of the listed values.")
    return value


def _color(value, field):
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() == "none":
        _fail(field, "Enter an opaque color such as #2866ae.")
    try:
        red, green, blue, alpha = to_rgba(value)
    except (TypeError, ValueError):
        _fail(field, "Enter an opaque color such as #2866ae.")
    if alpha < 1 - 1e-9:
        _fail(field, "Colors are opaque. Use the opacity setting for transparency.")
    return to_hex((red, green, blue), keep_alpha=False)


def _text(value, field):
    if not isinstance(value, str) or len(value) > 160 or any(ch == "\n" or ch == "\r" or ord(ch) < 32
                                                             or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        _fail(field, "Enter one line of up to 160 characters.")
    return value


def _palette(value, field):
    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        _fail(field, "Enter between 1 and 24 opaque colors.")
    return [_color(item, field) for item in value]


def _optional_limit(value, field, *, low=None):
    if value is None:
        return None
    number = _number(value, field)
    if low is not None and number < low:
        _fail(field, "Enter a finite limit inside the allowed range.")
    return number


def _labels(value, prefix):
    _mapping(value, prefix)
    _unknown(value, LABEL_FIELDS, prefix)
    out = {}
    if "visible" in value:
        out["visible"] = _bool(value["visible"], _path(prefix, "visible"))
    if "rotation" in value:
        rotation = _number(value["rotation"], _path(prefix, "rotation"))
        if not -90 <= rotation <= 90:
            _fail(_path(prefix, "rotation"), "Enter a label angle from −90 to 90 degrees.")
        out["rotation"] = rotation
    if "size" in value:
        size = _number(value["size"], _path(prefix, "size"))
        if not 4 <= size <= 40:
            _fail(_path(prefix, "size"), "Enter a label size from 4 to 40 points.")
        out["size"] = size
    if "color" in value:
        out["color"] = _color(value["color"], _path(prefix, "color"))
    if "first" in value:
        first = value["first"]
        if type(first) is not int or first < 1:
            _fail(_path(prefix, "first"), "Enter a whole first label of 1 or more.")
        out["first"] = first
    if "interval" in value:
        interval = value["interval"]
        if type(interval) is not int or not 0 <= interval <= 100000:
            _fail(_path(prefix, "interval"), "Enter a whole label interval from 0 to 100000.")
        out["interval"] = interval
    return out


def _distance(value, prefix):
    _mapping(value, prefix)
    _unknown(value, DISTANCE_FIELDS, prefix)
    out = {}
    if "visible" in value:
        out["visible"] = _bool(value["visible"], _path(prefix, "visible"))
    minimum = value["minimum"] if "minimum" in value else None
    maximum = value["maximum"] if "maximum" in value else None
    if "minimum" in value:
        out["minimum"] = _optional_limit(minimum, _path(prefix, "minimum"), low=0)
    if "maximum" in value:
        out["maximum"] = _optional_limit(maximum, _path(prefix, "maximum"), low=0)
    if out.get("minimum") is not None and out.get("maximum") is not None and not out["minimum"] < out["maximum"]:
        _fail(_path(prefix, "maximum"), "The distance maximum must be greater than the minimum.")
    if "step" in value:
        step = value["step"]
        if step is not None:
            step = _number(step, _path(prefix, "step"))
            if step <= 0:
                _fail(_path(prefix, "step"), "The distance step must be greater than zero.")
        out["step"] = step
    if "reversed" in value:
        out["reversed"] = _bool(value["reversed"], _path(prefix, "reversed"))
    return out


def _tree(value, prefix):
    _mapping(value, prefix)
    _unknown(value, TREE_FIELDS, prefix)
    out = {}
    if "visible" in value:
        out["visible"] = _bool(value["visible"], _path(prefix, "visible"))
    if "color_mode" in value:
        out["color_mode"] = _choice(value["color_mode"], COLOR_MODES, _path(prefix, "color_mode"))
    if "color" in value:
        out["color"] = _color(value["color"], _path(prefix, "color"))
    if "mixed_color" in value:
        out["mixed_color"] = _color(value["mixed_color"], _path(prefix, "mixed_color"))
    if "palette" in value:
        out["palette"] = _palette(value["palette"], _path(prefix, "palette"))
    if "width" in value:
        width = _number(value["width"], _path(prefix, "width"))
        if not 0 < width <= 12:
            _fail(_path(prefix, "width"), "Enter a branch width greater than 0 and up to 12 points.")
        out["width"] = width
    if "line_style" in value:
        out["line_style"] = _choice(value["line_style"], LINE_STYLES, _path(prefix, "line_style"))
    if "alpha" in value:
        alpha = _number(value["alpha"], _path(prefix, "alpha"))
        if not 0 <= alpha <= 1:
            _fail(_path(prefix, "alpha"), "Enter an opacity from 0 to 1.")
        out["alpha"] = alpha
    if "labels" in value:
        out["labels"] = _labels(value["labels"], _path(prefix, "labels"))
    if "distance" in value:
        out["distance"] = _distance(value["distance"], _path(prefix, "distance"))
    return out


def _heatmap(value):
    prefix = "heatmap"
    _mapping(value, prefix)
    _unknown(value, HEAT_FIELDS, prefix)
    out = {}
    if "cmap" in value:
        out["cmap"] = _choice(value["cmap"], CMAPS, "heatmap.cmap")
    if "reverse" in value:
        out["reverse"] = _bool(value["reverse"], "heatmap.reverse")
    has_min, has_max = "minimum" in value, "maximum" in value
    if has_min != has_max:
        _fail("heatmap.maximum" if has_min else "heatmap.minimum",
              "Enter both color limits, or leave both automatic.")
    if has_min:
        minimum = _optional_limit(value["minimum"], "heatmap.minimum")
        maximum = _optional_limit(value["maximum"], "heatmap.maximum")
        if (minimum is None) != (maximum is None):
            _fail("heatmap.maximum" if minimum is not None else "heatmap.minimum",
                  "Enter both color limits, or leave both automatic.")
        if minimum is not None and not minimum < maximum:
            _fail("heatmap.maximum", "The color maximum must be greater than the minimum.")
        out["minimum"] = minimum
        out["maximum"] = maximum
    if "colorbar" in value:
        out["colorbar"] = _bool(value["colorbar"], "heatmap.colorbar")
    if "title" in value:
        out["title"] = _text(value["title"], "heatmap.title")
    if "orientation" in value:
        out["orientation"] = _choice(value["orientation"], ORIENTATIONS, "heatmap.orientation")
    if "cell_aspect" in value:
        out["cell_aspect"] = _choice(value["cell_aspect"], ASPECTS, "heatmap.cell_aspect")
    return out


def _layout(value):
    _mapping(value, "layout")
    _unknown(value, LAYOUT_FIELDS, "layout")
    out = {}
    for key in LAYOUT_FIELDS:
        if key not in value:
            continue
        number = _number(value[key], f"layout.{key}")
        if not 0.05 <= number <= 1:
            _fail(f"layout.{key}", "Enter a ratio from 0.05 to 1.")
        out[key] = number
    return out


def validate_hierarchical_style(options, *, figure=None):
    """Return a canonical copy and check distance settings against the current tree, if present."""
    if not isinstance(options, dict):
        _fail("hierarchical", "Expected an object of presentation settings.")
    _unknown(options, ROOT_KEYS, "")
    canonical = {}
    if "row" in options:
        canonical["row"] = _tree(options["row"], "row")
    if "column" in options:
        canonical["column"] = _tree(options["column"], "column")
    if "heatmap" in options:
        canonical["heatmap"] = _heatmap(options["heatmap"])
    if "layout" in options:
        canonical["layout"] = _layout(options["layout"])
    if figure is not None:
        components = _require(figure)["components"]
        for name in TREE_KEYS:
            comp = components.get(name)
            distance = canonical.get(name, {}).get("distance")
            if comp is not None and distance:
                merged = _merge(comp["baseline"]["distance"], distance)
                low, high = _distance_limits(comp, merged)
                field = f"{name}.distance"
                if low >= high:
                    endpoint = "minimum" if "minimum" in distance and "maximum" not in distance else "maximum"
                    _fail(f"{field}.{endpoint}", "The distance maximum must be greater than the minimum.")
                if merged["step"] is not None and (high - low) / merged["step"] >= MAX_DISTANCE_TICKS:
                    _fail(f"{field}.step", "The distance step would draw more than 200 ticks.")
    return canonical


def _meta(figure):
    meta = getattr(figure, ATTR, None)
    if not isinstance(meta, dict) or not meta.get("components"):
        return None
    for comp in meta["components"].values():
        axes = comp.get("axes")
        if axes is None or axes.figure is not figure:
            return None
    return meta


def _require(figure):
    meta = _meta(figure)
    if meta is None:
        _fail("figure", "This figure is not a native hierarchical clustering graph.")
    return meta


def describe_hierarchical_artists(figure):
    """Live artists of a native hierarchical figure. Empty for any other figure."""
    meta = _meta(figure)
    if meta is None:
        return {}
    described = {}
    for key in TREE_KEYS:
        comp = meta["components"].get(key)
        if comp is None:
            continue
        described[key] = {
            "axes": comp["axes"],
            "branches": comp["branches"],
            "distance_dimension": comp["distance_dimension"],
            "leaf_order": comp["leaf_order"],
            "cluster_ids": comp["cluster_ids"],
        }
    heat = meta["components"].get("heatmap")
    if heat is not None:
        described["heatmap"] = {"axes": heat["axes"], "image": heat["image"], "colorbar": heat.get("colorbar")}
    return described


def snapshot_hierarchical_style(figure):
    """Independent copy of the applied override. ``{}`` before the first override."""
    meta = _meta(figure)
    applied = None if meta is None else meta.get("applied")
    if not applied:
        return {}
    return deepcopy(applied)


def baseline_hierarchical_style(figure):
    """Renderer defaults as a full canonical section. Used by the editor, not saved on its own."""
    meta = _require(figure)
    section = {}
    for key in TREE_KEYS:
        comp = meta["components"].get(key)
        if comp is not None:
            section[key] = deepcopy(comp["baseline"])
    heat = meta["components"].get("heatmap")
    if heat is not None:
        section["heatmap"] = deepcopy(heat["baseline"])
    layout = meta.get("layout_baseline") or {}
    if layout:
        section["layout"] = deepcopy(layout)
    return section


def _ensure(figure):
    meta = getattr(figure, ATTR, None)
    if not isinstance(meta, dict):
        meta = {"components": {}, "applied": None}
        setattr(figure, ATTR, meta)
    meta.setdefault("components", {})
    return meta


def _hexes(colors):
    array = np.atleast_2d(np.asarray(colors, dtype=float))
    return [to_hex(row, keep_alpha=False) for row in array]


def _float_pair(view):
    first, second = float(view[0]), float(view[1])
    low, high = (first, second) if first <= second else (second, first)
    return low, high, first > second


def _label_sample(axes, dimension):
    labels = axes.get_xticklabels() if dimension == "x" else axes.get_yticklabels()
    labels = [text for text in labels if text.get_text()]
    if not labels:
        return 0.0, 10.0, "#000000"
    color = labels[0].get_color()
    try:
        canonical = _color(color if isinstance(color, str) else to_hex(color, keep_alpha=False), "labels.color")
    except HierarchicalStyleError:
        canonical = "#000000"
    return float(labels[0].get_rotation()), float(labels[0].get_fontsize()), canonical


def _line_style(options):
    style = str(options.get("Branch style", "Solid")).lower().replace("-", "")
    return style if style in LINE_STYLES else "solid"


def register_tree(figure, key, axes, branches, *, horizontal, margin, order, cluster_ids, children,
                  leaf_labels, label_colors, options, palette, mixed_color):
    """Remember one dendrogram. Reading the artists does not change the figure."""
    if key not in TREE_KEYS:
        return
    low, high, reversed_view = _float_pair(axes.get_xlim() if horizontal else axes.get_ylim())
    dimension = "y" if horizontal else "x"
    rotation, size, sample = _label_sample(axes, dimension) if not margin else (0.0, 10.0, "#000000")
    colors = _hexes(branches.get_colors())
    alpha = branches.get_alpha()
    linewidths = branches.get_linewidths()
    width = float(linewidths[0] if len(linewidths) else 1.4)
    leaf_colors = tuple(label_colors) if label_colors is not None else tuple([sample] * len(leaf_labels))
    distance_label = axes.get_xlabel() if horizontal else axes.get_ylabel()
    comp = {
        "axes": axes,
        "branches": branches,
        "distance_dimension": "x" if horizontal else "y",
        "leaf_order": tuple(int(index) for index in order),
        "cluster_ids": None if cluster_ids is None else tuple(int(index) for index in cluster_ids),
        "children": tuple((int(left), int(right)) for left, right in np.asarray(children)[:, :2]),
        "leaf_labels": tuple(str(text) for text in leaf_labels),
        "label_colors": leaf_colors,
        "label_host": None if margin else axes,
        "label_dimension": dimension,
        "margin": bool(margin),
        "decorations": list(axes.lines),
        "decoration_visible": [bool(line.get_visible()) for line in axes.lines],
        "captured": {
            "colors": colors,
            "distance_min": low,
            "distance_max": high,
            "distance_label": distance_label,
            "axis_on": bool(axes.axison),
        },
        "baseline": {
            "visible": True,
            "color_mode": "analysis",
            "color": colors[0] if colors else _color(mixed_color, "color"),
            "mixed_color": _color(mixed_color, "mixed_color"),
            "palette": [_color(item, "palette") for item in palette],
            "width": width,
            "line_style": _line_style(options),
            "alpha": 1.0 if alpha is None else float(alpha),
            "labels": {
                "visible": True,
                "rotation": rotation,
                "size": size,
                "color": sample,
                "first": int(options.get("First label", 1)),
                "interval": int(options.get("Label interval (0 = automatic)", 0)),
            },
            "distance": {
                "visible": bool(axes.axison),
                "minimum": None,
                "maximum": None,
                "step": None,
                "reversed": reversed_view,
            },
        },
    }
    _ensure(figure)["components"][key] = comp


def bind_matrix_labels(figure, matrix):
    """Point heatmap trees at the matrix tick labels. The matrix owns those texts."""
    meta = _ensure(figure)
    for key, dimension in (("row", "y"), ("column", "x")):
        comp = meta["components"].get(key)
        if comp is None or not comp["margin"]:
            continue
        rotation, size, sample = _label_sample(matrix, dimension)
        comp["label_host"] = matrix
        comp["label_dimension"] = dimension
        comp["label_colors"] = tuple([sample] * len(comp["leaf_labels"]))
        labels = comp["baseline"]["labels"]
        labels["rotation"] = rotation
        labels["size"] = size
        labels["color"] = sample
        labels["visible"] = True


def register_heatmap(figure, axes, image, colorbar):
    """Remember the matrix and its existing colorbar axis."""
    spec = axes.get_subplotspec()
    gridspec = spec.get_gridspec()
    color_spec = colorbar.ax.get_subplotspec()
    widths = tuple(float(value) for value in gridspec.get_width_ratios())
    heights = tuple(float(value) for value in gridspec.get_height_ratios())
    title = colorbar.ax.get_ylabel() or "Value"
    meta = _ensure(figure)
    meta["components"]["heatmap"] = {
        "axes": axes,
        "image": image,
        "colorbar": colorbar,
        "captured": {
            "clim": (float(image.get_clim()[0]), float(image.get_clim()[1])),
            "title": title,
        },
        "baseline": {
            "cmap": "viridis",
            "reverse": False,
            "minimum": None,
            "maximum": None,
            "colorbar": True,
            "title": title,
            "orientation": "vertical",
            "cell_aspect": "equal" if axes.get_aspect() == "equal" else "auto",
        },
    }
    meta["layout_captured"] = {
        "gridspec": gridspec,
        "width_ratios": widths,
        "height_ratios": heights,
        "heatmap_slot": (spec.rowspan.start, spec.colspan.start),
        "colorbar_slot": (color_spec.rowspan.start, color_spec.colspan.start),
        "tree_slots": {key: (component["axes"].get_subplotspec().rowspan.start,
                             component["axes"].get_subplotspec().colspan.start)
                       for key, component in meta["components"].items() if key in TREE_KEYS},
    }
    layout = {}
    if "row" in meta["components"] and len(widths) >= 2 and widths[1]:
        layout["row_tree_ratio"] = widths[0] / widths[1]
    if "column" in meta["components"] and len(heights) >= 2 and heights[1]:
        layout["column_tree_ratio"] = heights[0] / heights[1]
    meta["layout_baseline"] = layout


def _merge(base, override):
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _branch_groups(children, cluster_ids):
    count = len(cluster_ids)
    groups = [0] * (2 * count - 1)
    for index, cluster_id in enumerate(cluster_ids):
        groups[index] = int(cluster_id)
    assigned = []
    for index, (left, right) in enumerate(children):
        node = count + index
        groups[node] = groups[left] if groups[left] == groups[right] else 0
        assigned.append(groups[node])
    return assigned


def _branch_colors(comp, merged, override):
    mode = merged.get("color_mode", "analysis")
    if mode == "single":
        return [merged["color"]] * len(comp["branches"].get_segments())
    if mode == "cluster":
        cluster_ids = comp["cluster_ids"]
        segments = len(comp["branches"].get_segments())
        if not cluster_ids:
            return [merged["mixed_color"]] * segments
        palette = merged["palette"]
        mixed = merged["mixed_color"]
        return [palette[(group - 1) % len(palette)] if group else mixed
                for group in _branch_groups(comp["children"], cluster_ids)]
    return list(comp["captured"]["colors"])


class _FittingLeafLabels(FixedFormatter):
    """Thin the text at draw time while preserving tick positions and per-leaf style."""

    def __init__(self, texts):
        super().__init__(texts)
        self._font = None
        self._extent = 0.
        self._anchor = 0
        self._stride = 1

    def _label_extent(self):
        label = self.axis.get_major_ticks(1)[0].label1
        font = label.get_fontproperties().copy(), label.get_rotation()
        if font != self._font:
            # Measure literal text in points so the result is reusable across DPI and export backends.
            renderer = RendererAgg(1, 1, 72)
            probe = Text(fontproperties=font[0], rotation=font[1], parse_math=False,
                         usetex=False, figure=Figure(dpi=72))
            size = "width" if self.axis.axis_name == "x" else "height"
            self._extent = 0.
            for value in self.seq:
                probe.set_text(value)
                self._extent = max(self._extent, getattr(probe.get_window_extent(renderer), size))
            self._font = font
        return self._extent

    def set_locs(self, locs):
        super().set_locs(locs)
        self._anchor, self._stride = 0, 1
        if len(locs) < 2:
            return
        axes = self.axis.axes
        lower, upper = sorted(self.axis.get_view_interval())
        pixels = axes.bbox.width if self.axis.axis_name == "x" else axes.bbox.height
        if pixels <= 0 or lower == upper:
            return
        spacing = (locs[1] - locs[0]) * pixels / (upper - lower) * 72 / axes.figure.dpi
        if spacing > 0:
            self._anchor = int(np.searchsorted(locs, lower))
            self._stride = max(1, math.ceil((self._label_extent() + 4) / spacing))

    def __call__(self, x, pos=None):
        if pos is None or (pos - self._anchor) % self._stride:
            return ""
        return super().__call__(x, pos)


def set_leaf_ticks(axes, dimension, positions, texts, *, automatic=False, rotation=0.):
    axis = axes.xaxis if dimension == "x" else axes.yaxis
    axis.set_ticks(positions, texts, parse_math=False, rotation=rotation)
    if automatic and len(texts) > 1:
        axis.set_major_formatter(_FittingLeafLabels(texts))
    return axis.get_ticklabels()


def _apply_labels(comp, merged, override):
    host = comp.get("label_host")
    if host is None:
        return
    labels = merged["labels"]
    dimension = comp["label_dimension"]
    if not labels["visible"]:
        set_leaf_ticks(host, dimension, [], [])
        return
    texts = comp["leaf_labels"]
    count = len(texts)
    interval = int(labels["interval"]) or max(1, (count + 54) // 55)
    chosen = list(range(int(labels["first"]) - 1, count, interval))
    positions = [index + 0.5 for index in chosen]
    shown = [texts[index] for index in chosen]
    artists = set_leaf_ticks(host, dimension, positions, shown,
                            automatic=labels["interval"] == 0, rotation=labels["rotation"])
    if "color" in (override.get("labels") or {}):
        colors = [labels["color"]] * len(shown)
    else:
        colors = [comp["label_colors"][index] for index in chosen]
    for artist, color in zip(artists, colors, strict=True):
        artist.set_fontsize(labels["size"])
        artist.set_color(color)
        artist.set_parse_math(False)


def _show_distance_only(axes, dimension):
    axes.set_axis_on()
    leaf = "y" if dimension == "x" else "x"
    axes.tick_params(axis=leaf, which="both", bottom=False, top=False, left=False, right=False,
                     labelbottom=False, labeltop=False, labelleft=False, labelright=False)
    for name in ("left", "right", "top", "bottom"):
        axes.spines[name].set_visible(False)
    if dimension == "x":
        axes.tick_params(axis="x", which="major", bottom=True, labelbottom=True)
        axes.spines["bottom"].set_visible(True)
        axes.yaxis.label.set_visible(False)
    else:
        axes.tick_params(axis="y", which="major", left=True, labelleft=True)
        axes.spines["left"].set_visible(True)
        axes.xaxis.label.set_visible(False)


def _distance_limits(comp, distance):
    captured = comp["captured"]
    low = captured["distance_min"] if distance["minimum"] is None else distance["minimum"]
    high = captured["distance_max"] if distance["maximum"] is None else distance["maximum"]
    return low, high


def _apply_distance(comp, merged):
    axes = comp["axes"]
    dimension = comp["distance_dimension"]
    captured = comp["captured"]
    distance = merged["distance"]
    low, high = _distance_limits(comp, distance)
    limits = (high, low) if distance["reversed"] else (low, high)
    if dimension == "x":
        axes.set_xlim(*limits)
        axis = axes.xaxis
    else:
        axes.set_ylim(*limits)
        axis = axes.yaxis
    axis.set_major_locator(AutoLocator() if distance["step"] is None else MultipleLocator(distance["step"]))
    if comp["margin"]:
        if distance["visible"]:
            _show_distance_only(axes, dimension)
            axis.label.set_text(captured["distance_label"])
            axis.label.set_parse_math(False)
        else:
            axes.set_axis_off()
        return
    axis.label.set_text(captured["distance_label"] if distance["visible"] else "")
    axis.label.set_visible(bool(distance["visible"]))
    axis.label.set_parse_math(False)
    if dimension == "x":
        axes.tick_params(axis="x", which="major", bottom=bool(distance["visible"]),
                         labelbottom=bool(distance["visible"]))
    else:
        axes.tick_params(axis="y", which="major", left=bool(distance["visible"]),
                         labelleft=bool(distance["visible"]))


def _apply_tree(comp, merged, override):
    branches = comp["branches"]
    branches.set_colors(_branch_colors(comp, merged, override))
    branches.set_linewidth(float(merged["width"]))
    branches.set_linestyle(merged["line_style"])
    branches.set_alpha(float(merged["alpha"]))
    branches.set_visible(bool(merged["visible"]))
    visible = bool(merged["visible"])
    for line, was_visible in zip(comp["decorations"], comp["decoration_visible"], strict=True):
        line.set_visible(visible and was_visible)
    _apply_labels(comp, merged, override)
    _apply_distance(comp, merged)


def _retarget_child_removes(axes):
    """Bind child removal to this axes after a figure deepcopy.

    The copy owns the artists, but each ``_remove_method`` can still point at
    the source figure's child list. Colorbar updates remove those artists.
    """
    children = axes._children
    for artist in list(children):
        artist._remove_method = children.remove


def _detach_colorbar(colorbar):
    """Drop callbacks and clear the axis without removing it from the figure."""
    if colorbar is None:
        return None
    _retarget_child_removes(colorbar.ax)
    mappable = colorbar.mappable
    cid = getattr(mappable, "colorbar_cid", None)
    if cid is not None:
        mappable.callbacks.disconnect(cid)
    mappable.colorbar = None
    mappable.colorbar_cid = None
    axes = colorbar.ax
    for name in ("_extend_cid1", "_extend_cid2"):
        callback = getattr(colorbar, name, None)
        if callback is not None:
            axes.callbacks.disconnect(callback)
    original = getattr(colorbar, "_ax_remove", None)
    if original is not None:
        axes._remove_method = original
    axes.cla = type(axes).cla.__get__(axes, type(axes))
    for name in getattr(colorbar, "_interactive_funcs", ()):
        original_method = getattr(type(axes), name, None)
        if original_method is not None:
            setattr(axes, name, original_method.__get__(axes, type(axes)))
    axes.cla()
    return axes


def _label_colorbar(colorbar, title, orientation):
    colorbar.set_label(title)
    if orientation == "horizontal":
        colorbar.ax.set_ylabel("")
        colorbar.ax.xaxis.label.set_parse_math(False)
    else:
        colorbar.ax.set_xlabel("")
        colorbar.ax.yaxis.label.set_parse_math(False)


def _apply_heatmap(figure, meta, merged):
    heat = meta["components"]["heatmap"]
    image = heat["image"]
    image.set_cmap(_ExactReverse(merged["cmap"]) if merged["reverse"] else colormaps[merged["cmap"]])
    if merged["minimum"] is None:
        image.set_clim(*heat["captured"]["clim"])
    else:
        image.set_clim(merged["minimum"], merged["maximum"])
    heat["axes"].set_aspect("equal" if merged["cell_aspect"] == "equal" else "auto")
    colorbar = heat.get("colorbar")
    orientation = merged["orientation"]
    if colorbar is not None:
        _retarget_child_removes(colorbar.ax)
    if colorbar is None or colorbar.orientation != orientation:
        slot = _detach_colorbar(colorbar)
        if slot is None:
            return
        colorbar = figure.colorbar(image, cax=slot, orientation=orientation)
        heat["colorbar"] = colorbar
    else:
        colorbar.update_normal(image)
    _label_colorbar(colorbar, merged["title"], orientation)
    colorbar.ax.set_visible(bool(merged["colorbar"]))


def _align_tree(matrix, dimension, tree, _renderer):
    """Match the matrix's actual outline when its aspect ratio shrinks its grid cell."""
    slot = matrix.get_position(original=True)
    view = matrix.get_position()
    tree_slot = tree.get_position(original=True)
    if dimension == "row":
        x = tree_slot.x0 + view.x0 - slot.x0
        return Bbox.from_bounds(x, view.y0, tree_slot.width, view.height)
    y = tree_slot.y0 + view.y1 - slot.y1
    return Bbox.from_bounds(view.x0, y, view.width, tree_slot.height)


def _apply_layout(meta, canonical, heat_merged):
    captured = meta.get("layout_captured")
    if not captured:
        return
    gridspec = captured["gridspec"]
    widths = list(captured["width_ratios"])
    heights = list(captured["height_ratios"])
    layout = canonical.get("layout", {})
    if "row" in meta["components"] and "row_tree_ratio" in layout and len(widths) >= 2:
        widths[0] = float(layout["row_tree_ratio"]) * captured["width_ratios"][1]
    if "column" in meta["components"] and "column_tree_ratio" in layout and len(heights) >= 2:
        heights[0] = float(layout["column_tree_ratio"]) * captured["height_ratios"][1]
    heat = meta["components"].get("heatmap")
    horizontal = bool(heat_merged and heat_merged["orientation"] == "horizontal" and heat_merged["colorbar"])
    shown = bool(heat_merged and heat_merged["colorbar"] and heat_merged["orientation"] == "vertical")
    if heat is not None and len(widths) >= 3 and not shown:
        widths[2] = _COLLAPSED
    if heat is None:
        return
    heat_row, heat_col = captured["heatmap_slot"]
    bar_slot = captured["colorbar_slot"]
    colorbar = heat.get("colorbar")
    if colorbar is None:
        return
    if horizontal:
        # One shared grid keeps both tree axes aligned with the matrix when the bar moves below it.
        bar_slot = (len(heights), heat_col)
        heights.append(heights[heat_row] * .055)
        if "horizontal_grid" not in captured:
            captured["horizontal_grid"] = heat["axes"].figure.add_gridspec(len(heights), len(widths), hspace=.08)
        gridspec = captured["horizontal_grid"]
    gridspec.set_width_ratios(widths)
    gridspec.set_height_ratios(heights)
    square_cells = heat_merged["cell_aspect"] == "equal"
    for key, slot in captured["tree_slots"].items():
        tree = meta["components"][key]["axes"]
        tree.set_subplotspec(gridspec[slot])
        tree.set_axes_locator(partial(_align_tree, heat["axes"], key) if square_cells else None)
    heat["axes"].set_subplotspec(gridspec[heat_row, heat_col])
    colorbar.ax.set_subplotspec(gridspec[bar_slot])


def apply_hierarchical_style(figure, options):
    """Apply a validated override. Invalid input raises before any artist changes."""
    canonical = validate_hierarchical_style(options, figure=figure)
    meta = _require(figure)
    if not canonical and not meta.get("applied"):
        return
    for key in TREE_KEYS:
        comp = meta["components"].get(key)
        if comp is None:
            continue
        override = canonical.get(key, {})
        _apply_tree(comp, _merge(comp["baseline"], override), override)
    heat = meta["components"].get("heatmap")
    heat_merged = None
    if heat is not None:
        heat_merged = _merge(heat["baseline"], canonical.get("heatmap", {}))
        _apply_heatmap(figure, meta, heat_merged)
    if heat is not None or meta.get("layout_captured"):
        _apply_layout(meta, canonical, heat_merged)
    meta["applied"] = deepcopy(canonical)
