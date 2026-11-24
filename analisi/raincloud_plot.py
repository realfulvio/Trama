"""Raincloud plot: half-violin density, compact box summary, and deterministic rain points."""
from dataclasses import dataclass, field
from hashlib import blake2b

from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from . import distribution_graphs as base
from .category_graphs import COLORS, MAX_POINTS
from .category_order import ranks
from .data import decimal_comma
from .graph_legend import MAX_LEGEND_KEY_LENGTH, typed_group_token
from .presentation import GraphGroup, register_groups
from .processing import FieldError
from .reporting import Result, _plot, _report


METHOD = "Raincloud plot"
RESPONSE = "Response"
GROUP = "Group"
ORIENTATION = "Orientation"
SHOW_DENSITY = "Show density"
SHOW_BOX = "Show box"
SHOW_POINTS = "Show points"
BANDWIDTH_MULTIPLIER = "Bandwidth multiplier"

VERTICAL, HORIZONTAL = ORIENTATIONS = ("Vertical", "Horizontal")
OPTIONS = {
    RESPONSE: None,
    GROUP: "Optional",
    ORIENTATION: ORIENTATIONS,
    SHOW_DENSITY: True,
    SHOW_BOX: True,
    SHOW_POINTS: True,
    BANDWIDTH_MULTIPLIER: 1.0,
}

SUMMARY_SHEET = "Raincloud summary"
DENSITY_SHEET = "Raincloud density"
SETTINGS_SHEET = "Settings"
SUMMARY_COLUMNS = [
    "Group", "N", "Minimum", "Q1", "Median", "Q3", "Maximum", "Whisker low", "Whisker high",
]
DENSITY_COLUMNS = ["Group", "Value", "Density"]
ERROR_PREFIX = "raincloud.error."

# Non-overlapping lane geometry around category center pos:
#   rain points in [pos - 0.39, pos - 0.09], compact box in [pos - 0.04, pos + 0.04],
#   half-violin cloud in [pos + 0.05, pos + 0.41].
CLOUD_OFFSET = 0.05
CLOUD_WIDTH = 0.36
BOX_WIDTH = 0.08
RAIN_CENTER_OFFSET = -0.24
RAIN_HALF_SPAN = 0.15
MAX_TIE_SPREAD = 32
_AXIS_KEYS = (
    "xlabel", "ylabel", "xscale", "yscale", "x_axis", "y_axis",
    "reference_lines", "axis_guides", "axis_bands", "axis_breaks", "linked_axes",
)


@dataclass
class _RaincloudGroup:
    value: object
    label: str
    token: str
    values: np.ndarray
    rows: np.ndarray
    color: str
    pos: float
    stats: dict | None = None
    note: str = ""
    artists: list = field(default_factory=list)


def visibility(show_density):
    """Fields that apply to the chosen raincloud visibility toggles."""
    return {BANDWIDTH_MULTIPLIER: bool(show_density)}


def style_after_parameter_change(style, old_options, new_options):
    """Preserve group styles across edits; drop axis-bound overrides when orientation swaps axes."""
    if not style:
        return style
    kept = dict(style)
    if (old_options or {}).get(ORIENTATION, VERTICAL) != (new_options or {}).get(ORIENTATION, VERTICAL):
        for key in _AXIS_KEYS:
            kept.pop(key, None)
    return kept


def _err(code, **params):
    """Encode an engine FieldError with the method error prefix for EN/IT translation."""
    # Store canonical English in the message while keeping code lookup clean in raincloud_plot_catalog.
    from .raincloud_plot_catalog import MESSAGES

    template = MESSAGES[ERROR_PREFIX + code][0]
    text = template.format(**params) if params else template
    return text


def _parse_response(series):
    """Convert response column to float64; blanks, bools, text, and non-finite numbers become NaN."""
    n = len(series)
    if n == 0:
        return np.empty(0, dtype=np.float64)
    if pd.api.types.is_bool_dtype(series):
        return np.full(n, np.nan, dtype=np.float64)
    if pd.api.types.is_numeric_dtype(series):
        arr = series.to_numpy(dtype=np.float64, na_value=np.nan)
        return np.where(np.isfinite(arr), arr, np.nan)
    raw = series.to_numpy(dtype=object)
    parsed = np.empty(n, dtype=object)
    for index, val in enumerate(raw):
        if val is None or isinstance(val, (bool, np.bool_, complex, np.complexfloating)):
            parsed[index] = np.nan
        elif isinstance(val, str):
            stripped = val.strip()
            parsed[index] = np.nan if not stripped else decimal_comma(stripped)
        else:
            parsed[index] = val
    arr = pd.to_numeric(pd.Series(parsed), errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
    return np.where(np.isfinite(arr), arr, np.nan)


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, _err("flag", field=name))
    return bool(value)


def _multiplier(options):
    value = options.get(BANDWIDTH_MULTIPLIER, 1.0)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            value = float(decimal_comma(stripped))
        except ValueError:
            raise FieldError(BANDWIDTH_MULTIPLIER, _err("bandwidth_number")) from None
    elif isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(BANDWIDTH_MULTIPLIER, _err("bandwidth_number"))
    else:
        value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise FieldError(BANDWIDTH_MULTIPLIER, _err("bandwidth_positive"))
    return value


def _is_present_group(series):
    """Mask of non-missing group entries (NaN, None, and empty strings are missing)."""
    arr = series.to_numpy(dtype=object)
    notna = pd.notna(series).to_numpy(dtype=bool)
    mask = notna.copy()
    for index in np.flatnonzero(notna):
        val = arr[index]
        if isinstance(val, str) and val == "":
            mask[index] = False
    return mask


def check_options(frame, options):
    """Validate raincloud options against ``frame`` and return normalized parameters."""
    if not frame.columns.is_unique:
        raise FieldError(RESPONSE, _err("unique_columns"))
    response = options.get(RESPONSE)
    if not isinstance(response, str) or not response or response not in frame:
        raise FieldError(RESPONSE, _err("choose_response"))
    group = options.get(GROUP) or None
    if group is not None and (not isinstance(group, str) or group not in frame):
        raise FieldError(GROUP, _err("choose_group"))
    if group == response:
        raise FieldError(GROUP, _err("distinct_group"))
    orientation = options.get(ORIENTATION, VERTICAL)
    if orientation not in ORIENTATIONS:
        raise FieldError(ORIENTATION, _err("orientation"))
    show_density = _flag(options, SHOW_DENSITY, True)
    show_box = _flag(options, SHOW_BOX, True)
    show_points = _flag(options, SHOW_POINTS, True)
    if not (show_density or show_box or show_points):
        raise FieldError(SHOW_DENSITY, _err("components"))
    multiplier = _multiplier(options) if show_density else 1.0
    return {
        "response": response,
        "group": group,
        "orientation": orientation,
        "show_density": show_density,
        "show_box": show_box,
        "show_points": show_points,
        "multiplier": multiplier,
    }


def _build_groups(frame, params):
    """Filter usable rows, order groups (worksheet order or first occurrence), and check budgets."""
    response = params["response"]
    group_col = params["group"]
    numbers = _parse_response(frame[response])
    finite = np.isfinite(numbers)
    total_rows = len(frame)

    if group_col is None:
        valid_rows = np.flatnonzero(finite)
        if not len(valid_rows):
            raise FieldError(RESPONSE, _err("no_data"))
        discarded_response = int(total_rows - len(valid_rows))
        discarded_group = 0
        raw_groups = [("All", "All", "all", numbers[valid_rows], valid_rows + 1)]
    else:
        present_group = _is_present_group(frame[group_col])
        valid_mask = finite & present_group
        valid_rows = np.flatnonzero(valid_mask)
        if not len(valid_rows):
            raise FieldError(RESPONSE, _err("no_data"))
        discarded_group = int((~present_group).sum())
        discarded_response = int((present_group & ~finite).sum())

        col_values = frame[group_col].to_numpy(dtype=object)[valid_rows]
        buckets = {}
        ordered_tokens = []
        for idx, val in enumerate(col_values):
            token = typed_group_token(val)
            if token not in buckets:
                buckets[token] = (val, [])
                ordered_tokens.append(token)
            buckets[token][1].append(idx)

        priority = ranks(frame, group_col)
        if priority:
            ordered_tokens = sorted(ordered_tokens, key=lambda tok: priority.get(tok, len(priority)))

        raw_groups = []
        for token in ordered_tokens:
            val, local_indices = buckets[token]
            idx_arr = np.asarray(local_indices, dtype=np.intp)
            row_nums = valid_rows[idx_arr] + 1
            raw_groups.append((val, str(val), token, numbers[valid_rows[idx_arr]], row_nums))

    if len(raw_groups) > base.MAX_GROUPS:
        raise FieldError(GROUP, _err("too_many_groups", limit=base.MAX_GROUPS))

    total_used = sum(len(vals) for _, _, _, vals, _ in raw_groups)
    if params["show_density"] and total_used * base.GRID_POINTS > base.MAX_KDE_EVALUATIONS:
        raise FieldError(BANDWIDTH_MULTIPLIER, _err("kde_budget"))
    if total_used > MAX_POINTS:
        raise FieldError(RESPONSE, _err("too_many_points", limit=MAX_POINTS))

    groups = [
        _RaincloudGroup(
            value=val,
            label=label,
            token=token,
            values=vals,
            rows=row_nums,
            color=COLORS[index % len(COLORS)],
            pos=float(index + 1),
        )
        for index, (val, label, token, vals, row_nums) in enumerate(raw_groups)
    ]
    for grp in groups:
        try:
            grp.stats = base._statistics(_StatsProxy(grp.values), base.TUKEY)
        except FieldError as error:
            raise FieldError(RESPONSE, _err("numeric_range")) from error
    return groups, total_used, total_rows - total_used, discarded_response, discarded_group


@dataclass
class _StatsProxy:
    values: np.ndarray
    note: str = ""


def _rain_offsets(values, identity):
    """Deterministic bounded offsets in [-RAIN_HALF_SPAN, +RAIN_HALF_SPAN] for rain points."""
    n = len(values)
    if n <= 1:
        return np.zeros(n, dtype=np.float64)
    digest = blake2b(identity.encode("utf-8"), digest_size=8).digest()
    seed = int.from_bytes(digest, "little")
    rng = np.random.default_rng(seed)
    offsets = rng.uniform(-RAIN_HALF_SPAN, RAIN_HALF_SPAN, n)
    order = np.argsort(values, kind="stable")
    sorted_vals = values[order]
    cuts = np.r_[0, np.flatnonzero(sorted_vals[1:] != sorted_vals[:-1]) + 1, n]
    for start, stop in zip(cuts[:-1], cuts[1:], strict=True):
        count = stop - start
        if 1 < count <= MAX_TIE_SPREAD:
            offsets[order[start:stop]] = np.linspace(-RAIN_HALF_SPAN, RAIN_HALF_SPAN, count)
    return offsets


def _draw_half_violin(axes, grp, multiplier, horizontal, density_rows, bandwidths):
    """Draw half-violin strictly on the + side of ``grp.pos``; skip singleton/constant groups."""
    try:
        fit = base._density(grp.values, multiplier)
    except FieldError as error:
        raise FieldError(BANDWIDTH_MULTIPLIER, _err("bandwidth_range")) from error
    if fit is None:
        if grp.stats["n"] == 1:
            grp.note = "N = 1: one observation, no density."
        else:
            grp.note = f"N = {grp.stats['n']}: constant values, no density."
        return None
    grid, density, bandwidth = fit
    scaled = CLOUD_WIDTH * density / density.max()
    base_coord = np.full_like(grid, grp.pos + CLOUD_OFFSET)
    edge_coord = grp.pos + CLOUD_OFFSET + scaled
    if horizontal:
        poly = axes.fill_between(
            grid, base_coord, edge_coord,
            facecolor=to_rgba(grp.color, 0.30), edgecolor=grp.color, linewidth=1.3, zorder=2.2,
        )
    else:
        poly = axes.fill_betweenx(
            grid, base_coord, edge_coord,
            facecolor=to_rgba(grp.color, 0.30), edgecolor=grp.color, linewidth=1.3, zorder=2.2,
        )
    grp.artists.append((poly, "fill"))
    density_rows.append(pd.DataFrame({
        "Group": pd.Series([grp.value] * len(grid), dtype=object),
        "Value": grid,
        "Density": density,
    }))
    bandwidths[grp.pos] = bandwidth
    return bandwidth


def _draw_compact_box(axes, grp, horizontal, show_points):
    """Draw compact box summary centered at ``grp.pos`` without obscuring the rain cloud."""
    stats = grp.stats
    color = grp.color
    pos = grp.pos
    half = BOX_WIDTH / 2.0

    if stats["reduced"]:
        if horizontal:
            segments = [
                [(stats["min"], pos), (stats["max"], pos)],
                [(stats["min"], pos - half * 0.4), (stats["min"], pos + half * 0.4)],
                [(stats["max"], pos - half * 0.4), (stats["max"], pos + half * 0.4)],
            ]
            med_line = Line2D([stats["median"], stats["median"]], [pos - half, pos + half],
                              color=color, linewidth=2.2, zorder=4.2)
        else:
            segments = [
                [(pos, stats["min"]), (pos, stats["max"])],
                [(pos - half * 0.4, stats["min"]), (pos + half * 0.4, stats["min"])],
                [(pos - half * 0.4, stats["max"]), (pos + half * 0.4, stats["max"])],
            ]
            med_line = Line2D([pos - half, pos + half], [stats["median"], stats["median"]],
                              color=color, linewidth=2.2, zorder=4.2)
        lc = LineCollection(segments, colors=color, linewidths=1.2, zorder=3.8)
        axes.add_collection(lc)
        axes.add_line(med_line)
        grp.artists.extend([(lc, "line"), (med_line, "line")])
        return

    q1, q3 = stats["q1"], stats["q3"]
    low, high = stats["low"], stats["high"]
    cap_half = half * 0.55

    if horizontal:
        rect = Rectangle((q1, pos - half), max(q3 - q1, 0.0), BOX_WIDTH,
                         facecolor=to_rgba(color, 0.24), edgecolor=color, linewidth=1.2, zorder=3.5)
        segments = [
            [(low, pos), (q1, pos)],
            [(q3, pos), (high, pos)],
            [(low, pos - cap_half), (low, pos + cap_half)],
            [(high, pos - cap_half), (high, pos + cap_half)],
        ]
        med_line = Line2D([stats["median"], stats["median"]], [pos - half, pos + half],
                          color=color, linewidth=2.2, zorder=4.2)
    else:
        rect = Rectangle((pos - half, q1), BOX_WIDTH, max(q3 - q1, 0.0),
                         facecolor=to_rgba(color, 0.24), edgecolor=color, linewidth=1.2, zorder=3.5)
        segments = [
            [(pos, low), (pos, q1)],
            [(pos, q3), (pos, high)],
            [(pos - cap_half, low), (pos + cap_half, low)],
            [(pos - cap_half, high), (pos + cap_half, high)],
        ]
        med_line = Line2D([pos - half, pos + half], [stats["median"], stats["median"]],
                          color=color, linewidth=2.2, zorder=4.2)

    axes.add_patch(rect)
    lc = LineCollection(segments, colors=color, linewidths=1.2, zorder=3.8)
    axes.add_collection(lc)
    axes.add_line(med_line)
    grp.artists.extend([(rect, "fill"), (lc, "line"), (med_line, "line")])

    if not show_points and stats["outside"].any():
        outliers = grp.values[stats["outside"]]
        pos_arr = np.full(len(outliers), pos)
        xs, ys = (outliers, pos_arr) if horizontal else (pos_arr, outliers)
        flier_line = Line2D(xs, ys, linestyle="none", marker="o", markersize=4,
                            markerfacecolor="white", markeredgecolor=color, color=color, zorder=4.0)
        axes.add_line(flier_line)
        grp.artists.append((flier_line, "marker"))


def _draw_rain_points(axes, grp, horizontal, total_used):
    """Draw all observations for ``grp`` in one PathCollection on the - side of ``grp.pos``."""
    offsets = _rain_offsets(grp.values, f"raincloud:{grp.token}")
    cat_coords = grp.pos + RAIN_CENTER_OFFSET + offsets
    xs, ys = (grp.values, cat_coords) if horizontal else (cat_coords, grp.values)
    dense = total_used > 2000
    scatter = axes.scatter(
        xs, ys,
        s=8 if dense else 20,
        color=grp.color,
        edgecolors="none" if dense else "white",
        linewidths=0.0 if dense else 0.5,
        alpha=0.72,
        zorder=3.0,
    )
    grp.artists.append((scatter, "point"))


def _draw_degenerate_anchor(axes, grp, horizontal):
    """Draw a minimal marker when only density is enabled on a singleton/constant group."""
    pos = grp.pos
    val = grp.stats["median"]
    if horizontal:
        artist = Line2D([val], [pos], marker="o", markersize=5, color=grp.color,
                        linestyle="none", zorder=3.5)
    else:
        artist = Line2D([pos], [val], marker="o", markersize=5, color=grp.color,
                        linestyle="none", zorder=3.5)
    axes.add_line(artist)
    grp.artists.append((artist, "line"))


def raincloud_plot(frame, options):
    """Compute raincloud statistics, optional KDE density, and native Matplotlib figure."""
    params = check_options(frame, options)
    groups, total_used, discarded, discarded_resp, discarded_grp = _build_groups(frame, params)

    horizontal = params["orientation"] == HORIZONTAL
    show_density = params["show_density"]
    show_box = params["show_box"]
    show_points = params["show_points"]
    multiplier = params["multiplier"]

    group_title = params["group"] or ""
    response = params["response"]
    x_label = response if horizontal else group_title
    y_label = group_title if horizontal else response
    figure, axes = _plot("Raincloud plot", x_label, y_label)
    axes.title.set_parse_math(False)
    axes.xaxis.label.set_parse_math(False)
    axes.yaxis.label.set_parse_math(False)

    density_rows = []
    bandwidths = {}
    for grp in groups:
        bw = None
        if show_density:
            bw = _draw_half_violin(axes, grp, multiplier, horizontal, density_rows, bandwidths)
        if show_box:
            _draw_compact_box(axes, grp, horizontal, show_points)
        if show_points:
            _draw_rain_points(axes, grp, horizontal, total_used)
        if show_density and bw is None and not show_box and not show_points:
            _draw_degenerate_anchor(axes, grp, horizontal)

    positions = [grp.pos for grp in groups]
    labels = [grp.label for grp in groups]
    long_labels = any(len(lbl) > 10 for lbl in labels)
    if horizontal:
        axes.set_yticks(positions, labels)
        for tick in axes.get_yticklabels():
            tick.set_parse_math(False)
        axes.set_ylim(0.4, len(groups) + 0.6)
        axes._tramastat_numeric_axes = ("x",)
        axes._tramastat_categorical_axes = ("y",)
    else:
        axes.set_xticks(positions, labels, rotation=20 if len(groups) > 5 or long_labels else 0)
        for tick in axes.get_xticklabels():
            tick.set_parse_math(False)
        axes.set_xlim(0.4, len(groups) + 0.6)
        axes._tramastat_numeric_axes = ("y",)
        axes._tramastat_categorical_axes = ("x",)

    # Keep numeric axis bounds crisp even if no artists (e.g., density-only on singletons).
    axes.autoscale_view()

    register_groups(
        axes,
        [
            GraphGroup(f"raincloud:{grp.token}", grp.label, "raincloud", grp.pos, grp.artists)
            for grp in groups
            if len(f"raincloud:{grp.token}") <= MAX_LEGEND_KEY_LENGTH
        ],
    )

    summary_df = pd.DataFrame({
        "Group": pd.Series([grp.value for grp in groups], dtype=object),
        "N": [grp.stats["n"] for grp in groups],
        "Minimum": [grp.stats["min"] for grp in groups],
        "Q1": [grp.stats["q1"] if not grp.stats["reduced"] else np.nan for grp in groups],
        "Median": [grp.stats["median"] for grp in groups],
        "Q3": [grp.stats["q3"] if not grp.stats["reduced"] else np.nan for grp in groups],
        "Maximum": [grp.stats["max"] for grp in groups],
        "Whisker low": [grp.stats["low"] for grp in groups],
        "Whisker high": [grp.stats["high"] for grp in groups],
    }, columns=SUMMARY_COLUMNS)

    settings = {
        "Response": response,
        "Group": params["group"] or "None (single distribution)",
        "Orientation": params["orientation"],
        "Show density": show_density,
        "Show box": show_box,
        "Show points": show_points,
        "Observations used": total_used,
        "Rows discarded": discarded,
        "Discarded (missing or non-finite response)": discarded_resp,
        "Discarded (missing group)": discarded_grp,
        "Percentiles": base.QUARTILE_NOTE,
        "Whiskers": "Tukey (1.5 × IQR, inclusive fences; median and range when N < 4).",
    }
    if show_density:
        settings.update(base.rule_settings(base.VIOLIN, base.TUKEY, multiplier))

    tables = {SUMMARY_SHEET: summary_df}
    if show_density:
        tables[DENSITY_SHEET] = (
            pd.concat(density_rows, ignore_index=True)
            if density_rows
            else pd.DataFrame(columns=DENSITY_COLUMNS)
        )
    tables[SETTINGS_SHEET] = _report(settings)
    return Result(tables, figure)
