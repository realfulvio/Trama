"""Pareto plot: descending frequency/weight bars with cumulative percentage curve on a 0–100% axis."""
from dataclasses import dataclass
from decimal import Decimal
from math import fsum, isfinite

from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import StrMethodFormatter
import numpy as np
import pandas as pd

from .data import decimal_comma
from .graph_legend import MAX_LEGEND_KEY_LENGTH, typed_group_token
from .presentation import GraphGroup, register_groups
from .processing import FieldError
from .reporting import Result, _plot, _report


METHOD = "Pareto plot"
CATEGORY = "Category"
WEIGHT = "Weight"
THRESHOLD = "Threshold"
DEFAULT_THRESHOLD = 80.0

OPTIONS = {
    CATEGORY: None,
    WEIGHT: "Optional",
    THRESHOLD: "Text",
}

CATEGORIES_SHEET = "Pareto categories"
SETTINGS_SHEET = "Settings"
CATEGORIES_COLUMNS = ["Category", "Amount", "Percent", "Cumulative percent"]
ERROR_PREFIX = "pareto.error."

MAX_CATEGORIES = 256

BAR_COLOR = "#216a94"
BAR_EDGE = "#184f6e"
HIGHLIGHT_COLOR = "#ca6239"
HIGHLIGHT_EDGE = "#963f1e"
LINE_COLOR = "#1d3348"
THRESHOLD_COLOR = "#b84a24"


@dataclass(frozen=True)
class _ParetoCategory:
    value: object
    label: str
    token: str
    amount: float | int
    percent: float
    cumulative_percent: float


def _err(code, **params):
    """Return canonical English error text for ``code`` (translated in UI via pareto_plot_catalog)."""
    from .pareto_plot_catalog import MESSAGES

    template = MESSAGES[ERROR_PREFIX + code][0]
    return template.format(**params) if params else template


def parse_threshold(raw):
    """Validate optional Threshold (%): blank/None disables it; otherwise strictly 0 < value < 100."""
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            value = float(decimal_comma(stripped))
        except ValueError:
            raise FieldError(THRESHOLD, _err("threshold_number")) from None
    elif isinstance(raw, (bool, np.bool_)) or not isinstance(raw, (int, float, np.integer, np.floating)):
        raise FieldError(THRESHOLD, _err("threshold_number"))
    else:
        try:
            value = float(raw)
        except OverflowError:
            raise FieldError(THRESHOLD, _err("threshold_number")) from None
    if not isfinite(value):
        raise FieldError(THRESHOLD, _err("threshold_number"))
    if not (0.0 < value < 100.0):
        raise FieldError(THRESHOLD, _err("threshold_range"))
    return value


def normalize_options(options):
    """Return canonical EN recipe dict (empty string when threshold is disabled, float when enabled)."""
    cleaned = dict(options or {})
    weight = cleaned.get(WEIGHT)
    if weight in ("", None):
        cleaned[WEIGHT] = None
    if THRESHOLD in cleaned:
        parsed = parse_threshold(cleaned[THRESHOLD])
        cleaned[THRESHOLD] = "" if parsed is None else parsed
    return cleaned


def _present_category_mask(series):
    """Boolean mask of rows with a present, non-empty category value."""
    notna = pd.notna(series).to_numpy(dtype=bool)
    if not notna.any():
        return notna
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        arr = series.to_numpy(dtype=object)
        mask = notna.copy()
        for idx in np.flatnonzero(notna):
            val = arr[idx]
            if isinstance(val, str) and not val.strip():
                mask[idx] = False
        return mask
    return notna


def _parse_weights(series, present_cat):
    """Validate and extract numeric weights on ``present_cat`` rows.

    Missing/blank weights on present-category rows are discarded and counted.
    Present booleans, non-numeric text, complex values, non-finite numbers, and negative numbers
    raise ``FieldError(WEIGHT, ...)``.
    """
    n = len(series)
    weights = np.full(n, np.nan, dtype=np.float64)
    cat_indices = np.flatnonzero(present_cat)
    if not len(cat_indices):
        return weights, np.zeros(n, dtype=bool), 0

    if pd.api.types.is_bool_dtype(series):
        raw_notna = pd.notna(series).to_numpy(dtype=bool)
        if raw_notna[cat_indices].any():
            raise FieldError(WEIGHT, _err("weight_boolean"))
        return weights, np.zeros(n, dtype=bool), int(len(cat_indices))

    if pd.api.types.is_complex_dtype(series):
        raw_notna = pd.notna(series).to_numpy(dtype=bool)
        if raw_notna[cat_indices].any():
            raise FieldError(WEIGHT, _err("weight_non_numeric"))
        return weights, np.zeros(n, dtype=bool), int(len(cat_indices))

    if pd.api.types.is_numeric_dtype(series):
        raw_notna = pd.notna(series).to_numpy(dtype=bool)
        arr = series.to_numpy(dtype=np.float64, na_value=np.nan)
        present_w = present_cat & raw_notna
        discarded_w = int((present_cat & ~raw_notna).sum())
        if present_w.any():
            vals = arr[present_w]
            if not np.isfinite(vals).all():
                raise FieldError(WEIGHT, _err("weight_non_finite"))
            if (vals < 0).any():
                raise FieldError(WEIGHT, _err("weight_negative"))
        weights[present_w] = arr[present_w]
        return weights, present_w, discarded_w

    # Mixed / object / string column: validate every present entry strictly.
    raw = series.to_numpy(dtype=object)
    raw_notna = pd.notna(series).to_numpy(dtype=bool)
    valid_w = np.zeros(n, dtype=bool)
    discarded_w = 0
    for idx in cat_indices:
        if not raw_notna[idx]:
            discarded_w += 1
            continue
        val = raw[idx]
        if isinstance(val, (bool, np.bool_)):
            raise FieldError(WEIGHT, _err("weight_boolean"))
        if isinstance(val, (complex, np.complexfloating)):
            raise FieldError(WEIGHT, _err("weight_non_numeric"))
        if isinstance(val, str):
            stripped = val.strip()
            if not stripped:
                discarded_w += 1
                continue
            try:
                num = float(decimal_comma(stripped))
            except ValueError:
                raise FieldError(WEIGHT, _err("weight_non_numeric")) from None
        elif isinstance(val, (int, float, np.integer, np.floating)):
            try:
                num = float(val)
            except OverflowError:
                raise FieldError(WEIGHT, _err("weight_non_finite")) from None
        else:
            raise FieldError(WEIGHT, _err("weight_non_numeric"))
        if not isfinite(num):
            raise FieldError(WEIGHT, _err("weight_non_finite"))
        if num < 0:
            raise FieldError(WEIGHT, _err("weight_negative"))
        weights[idx] = 0.0 if num == 0.0 else num
        valid_w[idx] = True
    return weights, valid_w, discarded_w


def check_options(frame, options):
    """Validate Pareto plot options against ``frame`` and return normalized parameters."""
    if not frame.columns.is_unique:
        raise FieldError(CATEGORY, _err("unique_columns"))
    category = options.get(CATEGORY)
    if not isinstance(category, str) or not category or category not in frame:
        raise FieldError(CATEGORY, _err("choose_category"))
    weight = options.get(WEIGHT)
    if weight in ("", None):
        weight = None
    elif not isinstance(weight, str) or weight not in frame:
        raise FieldError(WEIGHT, _err("choose_weight"))
    if weight is not None and weight == category:
        raise FieldError(WEIGHT, _err("distinct_weight"))
    if THRESHOLD in options:
        threshold = parse_threshold(options[THRESHOLD])
    else:
        threshold = DEFAULT_THRESHOLD
    return {
        "category": category,
        "weight": weight,
        "threshold": threshold,
    }


def _aggregate(frame, params):
    """Aggregate categories, validate totals, and sort descending with stable first-occurrence ties."""
    category_col = params["category"]
    weight_col = params["weight"]
    total_rows = len(frame)

    cat_series = frame[category_col]
    present_cat = _present_category_mask(cat_series)
    discarded_category = int(total_rows - present_cat.sum())

    if weight_col is None:
        valid_rows = np.flatnonzero(present_cat)
        discarded_weight = 0
        if not len(valid_rows):
            raise FieldError(CATEGORY, _err("no_categories"))
        col_values = cat_series.to_numpy(dtype=object)[valid_rows]
        buckets = {}
        for val in col_values:
            token = f"str:{val}" if type(val) is str else typed_group_token(val)
            entry = buckets.get(token)
            if entry is None:
                if len(buckets) >= MAX_CATEGORIES:
                    raise FieldError(CATEGORY, _err("too_many_categories", limit=MAX_CATEGORIES))
                buckets[token] = [val, 1]
            else:
                entry[1] += 1
        raw_items = [(val, str(val), token, count) for token, (val, count) in buckets.items()]
        total = int(len(valid_rows))
        used_rows = total
    else:
        if not present_cat.any():
            raise FieldError(CATEGORY, _err("no_categories"))
        weights, valid_w, discarded_weight = _parse_weights(frame[weight_col], present_cat)
        valid_rows = np.flatnonzero(valid_w)
        if not len(valid_rows):
            raise FieldError(WEIGHT, _err("no_usable_weights"))
        col_values = cat_series.to_numpy(dtype=object)[valid_rows]
        row_weights = weights[valid_rows]
        buckets = {}
        for val, w in zip(col_values, row_weights, strict=True):
            token = f"str:{val}" if type(val) is str else typed_group_token(val)
            entry = buckets.get(token)
            if entry is None:
                if len(buckets) >= MAX_CATEGORIES:
                    raise FieldError(CATEGORY, _err("too_many_categories", limit=MAX_CATEGORIES))
                buckets[token] = (val, [float(w)])
            else:
                entry[1].append(float(w))
        raw_items = []
        for token, (val, w_list) in buckets.items():
            try:
                cat_sum = fsum(w_list)
            except OverflowError:
                raise FieldError(WEIGHT, _err("total_positive")) from None
            if not isfinite(cat_sum):
                raise FieldError(WEIGHT, _err("total_positive"))
            raw_items.append((val, str(val), token, cat_sum))
        try:
            total = fsum(item[3] for item in raw_items)
        except OverflowError:
            raise FieldError(WEIGHT, _err("total_positive")) from None
        if not isfinite(total) or total <= 0.0:
            raise FieldError(WEIGHT, _err("total_positive"))
        used_rows = int(len(valid_rows))

    # Stable descending sort: ties preserve first-occurrence insertion order.
    ordered = sorted(raw_items, key=lambda item: -item[3])

    amounts = [item[3] for item in ordered]
    n = len(ordered)
    last_positive = max(i for i, a in enumerate(amounts) if a > 0)
    categories = []
    running_terms = []
    for idx, (val, label, token, amount) in enumerate(ordered):
        running_terms.append(float(amount))
        pct = (float(amount) / float(total)) * 100.0
        if idx >= last_positive:
            cum_pct = 100.0
        else:
            cum_val = (fsum(running_terms) / float(total)) * 100.0
            cum_pct = min(100.0, max(0.0, cum_val))
        categories.append(_ParetoCategory(val, label, token, amount, pct, cum_pct))

    return categories, total, used_rows, discarded_category, discarded_weight


def _threshold_index(categories, threshold):
    """Index of the first category reaching or exceeding ``threshold`` %, or None when disabled."""
    if threshold is None:
        return None
    for idx, cat in enumerate(categories):
        if cat.cumulative_percent >= threshold:
            return idx
    return len(categories) - 1


def _sync_secondary_style(axes):
    """Keep the right 0–100% axis typography, spine, limits, and combined legend aligned after apply_style."""
    right = getattr(axes, "_tramastat_pareto_right", None)
    if right is None:
        return
    style = getattr(axes, "_tramastat_style", {}) or {}
    right.set_ylim(0.0, 100.0)
    right.spines["right"].set_visible(True)
    for name in ("left", "top", "bottom"):
        right.spines[name].set_visible(False)

    # Mirror primary Y label/tick typography onto the secondary Y axis.
    parent_label = axes.yaxis.label
    right_label = right.yaxis.label
    right_label.set_fontproperties(parent_label.get_fontproperties().copy())
    right_label.set_parse_math(False)
    if "font_family" in style:
        right_label.set_fontfamily(style["font_family"])
    if "label_size" in style:
        right_label.set_fontsize(style["label_size"])

    params = axes.yaxis.get_tick_params(which="major")
    tick_opts = {k: params[k] for k in ("labelsize", "labelfontfamily") if k in params}
    if "tick_size" in style:
        tick_opts["labelsize"] = style["tick_size"]
    if "font_family" in style:
        tick_opts["labelfontfamily"] = style["font_family"]
    if tick_opts:
        right.tick_params(axis="y", which="both", **tick_opts)

    # Rebuild combined legend when legend position/font changed so right-axis entries stay included.
    entries = getattr(axes, "_tramastat_pareto_legend_entries", None)
    if not entries:
        return
    location = style.get("legend")
    if location == "hidden":
        axes.legend_ = None
        return
    existing = axes.get_legend()
    if location or existing is None:
        loc = location or "center right"
        legend = axes.legend(
            [handle for handle, _ in entries],
            [text for _, text in entries],
            loc=loc,
            frameon=True,
            framealpha=0.88,
        )
        for artist in [legend.get_title(), *legend.get_texts()]:
            artist.set_parse_math(False)
            if "font_family" in style:
                artist.set_fontfamily(style["font_family"])
            if "legend_size" in style:
                artist.set_fontsize(style["legend_size"])
        if style.get("legend_options"):
            from .graph_legend import apply_legend_options

            apply_legend_options(axes.figure, style["legend_options"])
    elif "font_family" in style or "legend_size" in style:
        for artist in [existing.get_title(), *existing.get_texts()]:
            artist.set_parse_math(False)
            if "font_family" in style:
                artist.set_fontfamily(style["font_family"])
            if "legend_size" in style:
                artist.set_fontsize(style["legend_size"])


def pareto_plot(frame, options):
    """Compute Pareto table, settings report, and native dual-axis Matplotlib figure."""
    params = check_options(frame, options)
    categories, total, used_rows, discarded_cat, discarded_w = _aggregate(frame, params)

    category_col = params["category"]
    weight_col = params["weight"]
    threshold = params["threshold"]
    highlight_idx = _threshold_index(categories, threshold)
    highlight_cat = categories[highlight_idx] if highlight_idx is not None else None

    y_label = weight_col if weight_col is not None else "Count"
    heights = [category.amount for category in categories]
    maximum = max(heights)
    axis_label = y_label
    if maximum < 1e-12 or maximum > 1e150:
        # Keep the renderer away from its singular limits and from intermediate overflow.
        # Decimal scaling keeps even subnormal weights usable without constructing 10**exponent as a float.
        exponent = Decimal.from_float(float(maximum)).adjusted()
        heights = [float(Decimal.from_float(float(value)).scaleb(-exponent)) for value in heights]
        axis_label = f"{y_label} (×10^{exponent})"
    figure, axes = _plot(METHOD, category_col, axis_label)
    axes.title.set_parse_math(False)
    axes.xaxis.label.set_parse_math(False)
    axes.yaxis.label.set_parse_math(False)
    axes.grid(axis="y", alpha=0.25)
    axes.set_axisbelow(True)

    xs = np.arange(len(categories), dtype=float)
    cum_pcts = [cat.cumulative_percent for cat in categories]

    face_colors = [
        to_rgba(HIGHLIGHT_COLOR, 0.85) if idx == highlight_idx else to_rgba(BAR_COLOR, 0.78)
        for idx in range(len(categories))
    ]
    edge_colors = [
        HIGHLIGHT_EDGE if idx == highlight_idx else BAR_EDGE
        for idx in range(len(categories))
    ]
    line_widths = [
        1.6 if idx == highlight_idx else 1.1
        for idx in range(len(categories))
    ]

    bar_container = axes.bar(
        xs,
        heights,
        width=0.68,
        color=face_colors,
        edgecolor=edge_colors,
        linewidth=line_widths,
        zorder=2.2,
    )

    axes.set_ylim(0.0, max(heights) * 1.12)
    axes.set_xlim(-0.6, len(categories) - 0.4)

    labels = [cat.label for cat in categories]
    rotate = len(categories) > 6 or any(len(lbl) > 10 for lbl in labels)
    axes.set_xticks(xs, labels, rotation=28 if rotate else 0, ha="right" if rotate else "center")
    for tick in axes.get_xticklabels():
        tick.set_parse_math(False)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)

    # Secondary 0–100% Y axis for cumulative percentage (independent of linear linked_axes).
    right = axes.twinx()
    right.set_ylim(0.0, 100.0)
    right.set_yticks([0, 20, 40, 60, 80, 100])
    right.yaxis.set_major_formatter(StrMethodFormatter("{x:g}%"))
    right.set_ylabel("Cumulative percent (%)", parse_math=False)
    right.grid(False)
    right.spines[["left", "top", "bottom"]].set_visible(False)
    right.spines["right"].set_visible(True)
    right.set_zorder(axes.get_zorder() + 1)
    right.patch.set_visible(False)

    cum_line, = right.plot(
        xs,
        cum_pcts,
        color=LINE_COLOR,
        linewidth=2.0,
        marker="o",
        markersize=5.0,
        markerfacecolor=LINE_COLOR,
        markeredgecolor="white",
        markeredgewidth=0.8,
        clip_on=False,
        zorder=4.0,
        gid="pareto-cumulative",
        label="Cumulative percent",
    )

    groups = []
    for idx, (cat, patch) in enumerate(zip(categories, bar_container.patches, strict=True)):
        key = f"pareto:cat:{cat.token}"
        if len(key) <= MAX_LEGEND_KEY_LENGTH:
            groups.append(GraphGroup(key, cat.label, "pareto", float(idx), [(patch, "fill")]))
    groups.append(GraphGroup("pareto:line:cumulative", "Cumulative percent", "pareto-line", 0.0, [(cum_line, "line")]))

    bars_proxy = Patch(facecolor=to_rgba(BAR_COLOR, 0.78), edgecolor=BAR_EDGE, linewidth=1.1, label=y_label)
    bars_proxy.set_gid("pareto-bars")
    legend_entries = [(bars_proxy, y_label), (cum_line, "Cumulative percent")]

    if highlight_idx is not None:
        thresh_label = f"Threshold ({threshold:g}%)"
        hline = right.axhline(
            threshold,
            color=THRESHOLD_COLOR,
            linestyle="--",
            linewidth=1.35,
            zorder=3.2,
            gid="pareto-threshold-line",
            label=thresh_label,
        )
        vline = right.plot(
            [float(highlight_idx), float(highlight_idx)],
            [0.0, highlight_cat.cumulative_percent],
            color=THRESHOLD_COLOR,
            linestyle=":",
            linewidth=1.15,
            alpha=0.75,
            zorder=3.1,
        )[0]
        hmarker = right.plot(
            [float(highlight_idx)],
            [highlight_cat.cumulative_percent],
            linestyle="none",
            marker="o",
            markersize=7.5,
            color=HIGHLIGHT_COLOR,
            markerfacecolor=HIGHLIGHT_COLOR,
            markeredgecolor="white",
            markeredgewidth=1.2,
            clip_on=False,
            zorder=4.6,
        )[0]
        groups.append(
            GraphGroup(
                "pareto:line:threshold",
                thresh_label,
                "pareto-threshold",
                float(highlight_idx),
                [(hline, "line"), (vline, "line"), (hmarker, "line")],
            )
        )
        hi_label = f"Reaches {threshold:g}%"
        hi_proxy = Patch(facecolor=to_rgba(HIGHLIGHT_COLOR, 0.85), edgecolor=HIGHLIGHT_EDGE, linewidth=1.6, label=hi_label)
        hi_proxy.set_gid("pareto-threshold-bar")
        legend_entries.insert(1, (hi_proxy, hi_label))
        legend_entries.append((hline, thresh_label))

    register_groups(axes, groups)
    axes._tramastat_pareto_right = right
    axes._tramastat_pareto_legend_entries = legend_entries
    axes._tramastat_after_style = _sync_secondary_style

    legend = axes.legend(
        [handle for handle, _ in legend_entries],
        [text for _, text in legend_entries],
        loc="center right",
        frameon=True,
        framealpha=0.88,
    )
    for text_artist in [legend.get_title(), *legend.get_texts()]:
        text_artist.set_parse_math(False)

    amount_series = (
        pd.Series([int(cat.amount) for cat in categories], dtype="int64")
        if weight_col is None
        else pd.Series([float(cat.amount) for cat in categories], dtype="float64")
    )
    categories_df = pd.DataFrame({
        "Category": pd.Series([cat.value for cat in categories], dtype=object),
        "Amount": amount_series,
        "Percent": [cat.percent for cat in categories],
        "Cumulative percent": [cat.cumulative_percent for cat in categories],
    }, columns=CATEGORIES_COLUMNS)

    settings = {
        "Mode": "Weighted sum" if weight_col is not None else "Counts",
        "Category column": category_col,
        "Weight column": weight_col if weight_col is not None else "None (counts)",
        "Categories": len(categories),
        "Total": total,
        "Threshold (%)": threshold if threshold is not None else "Disabled",
        "Threshold category": highlight_cat.value if highlight_cat is not None else "None",
        "Threshold cumulative percent (%)": (
            highlight_cat.cumulative_percent if highlight_cat is not None else "None"
        ),
        "Observations used": used_rows,
        "Rows discarded": discarded_cat + discarded_w,
        "Discarded (missing category)": discarded_cat,
        "Discarded (missing weight)": discarded_w,
    }
    tables = {
        CATEGORIES_SHEET: categories_df,
        SETTINGS_SHEET: _report(settings),
    }
    return Result(tables, figure)
