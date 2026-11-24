"""Two-factor interaction plot: observed cell means, error bars, and categorical X axis."""
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np
import pandas as pd
from scipy.stats import t

from .category_graphs import COLORS
from .category_order import ranks
from .data import decimal_comma
from .field_error import FieldError
from .graph_legend import LEGEND_OPTIONS_KEY, apply_legend_options, typed_group_token
from .reporting import Result, _plot, _report


METHOD = "Interaction plot"
RESPONSE = "Response"
X_FACTOR = "X factor"
SERIES_FACTOR = "Series factor"
ERROR_BARS = "Error bars"
CONFIDENCE_LEVEL = "Confidence level"

NONE = "None"
SD = "SD"
SEM = "SEM"
CI = "Confidence interval"
ERROR_BAR_CHOICES = (NONE, SD, SEM, CI)
DEFAULT_ERROR_BARS = CI
DEFAULT_CONFIDENCE_LEVEL = 95.0

OPTIONS = {
    RESPONSE: None,
    X_FACTOR: None,
    SERIES_FACTOR: None,
    ERROR_BARS: ERROR_BAR_CHOICES,
    CONFIDENCE_LEVEL: DEFAULT_CONFIDENCE_LEVEL,
}

CELLS_SHEET = "Interaction cells"
SETTINGS_SHEET = "Settings"
COLUMNS = ["X level", "Series", "N", "Mean", "SD", "SEM", "Lower", "Upper"]
ERROR_PREFIX = "interaction.error."
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")


def visibility(error_bars):
    """Fields that apply to the chosen error-bar mode."""
    return {CONFIDENCE_LEVEL: error_bars == CI}


@dataclass(frozen=True)
class _Level:
    token: str
    value: object
    label: str


@dataclass(frozen=True)
class _Prepared:
    response: str
    x_factor: str
    series_factor: str
    error_bars: str
    confidence_level: float
    x_levels: list
    series_levels: list
    valid_x_codes: np.ndarray
    valid_series_codes: np.ndarray
    valid_values: np.ndarray
    used_rows: int
    discarded_rows: int


def _text(value):
    if isinstance(value, np.generic):
        value = value.item()
    return str(value)


def _token_kind(token):
    prefix, _, _ = token.partition(":")
    return prefix


def _present_mask(series):
    """Return a boolean mask where non-missing factor values exist (blank/whitespace strings count as missing)."""
    not_na = ~series.isna().to_numpy(dtype=bool)
    if pd.api.types.is_string_dtype(series.dtype):
        stripped = series.fillna("").astype(str).str.strip().to_numpy()
        return not_na & (stripped != "")
    if series.dtype == object:
        arr = series.to_numpy(dtype=object)
        out = not_na.copy()
        for idx in np.flatnonzero(not_na):
            val = arr[idx]
            if isinstance(val, str) and not val.strip():
                out[idx] = False
        return out
    return not_na


def _parse_response(series):
    """Convert response column to float64; non-numeric or non-finite values become NaN (never raises)."""
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_complex_dtype(dtype):
        return np.full(len(series), np.nan, dtype=np.float64)
    if pd.api.types.is_string_dtype(dtype):
        cleaned = series.fillna("").map(decimal_comma)
        return pd.to_numeric(cleaned, errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
    if pd.api.types.is_numeric_dtype(dtype):
        return series.to_numpy(dtype=np.float64, na_value=np.nan)
    arr = series.to_numpy(dtype=object)
    parsed = np.empty(len(arr), dtype=object)
    for idx, val in enumerate(arr):
        if val is None or isinstance(val, (bool, np.bool_, complex, np.complexfloating)):
            parsed[idx] = np.nan
        elif isinstance(val, str):
            parsed[idx] = decimal_comma(val)
        else:
            parsed[idx] = val
    return pd.to_numeric(pd.Series(parsed), errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)


def _disambiguate_labels(raw_levels):
    """Disambiguate only colliding display labels, keeping unique labels literal and disambiguation stable."""
    bases = [_text(val) for _, val in raw_levels]
    counts = {}
    for base in bases:
        counts[base] = counts.get(base, 0) + 1
    if all(count == 1 for count in counts.values()):
        return [_Level(token, val, base) for (token, val), base in zip(raw_levels, bases, strict=True)]

    non_str_counts = {}
    for (token, _), base in zip(raw_levels, bases, strict=True):
        if counts[base] > 1 and not token.startswith("str:"):
            non_str_counts[base] = non_str_counts.get(base, 0) + 1

    taken = {base for base, count in counts.items() if count == 1}
    resolved = []
    for (token, val), base in zip(raw_levels, bases, strict=True):
        if counts[base] == 1:
            resolved.append(_Level(token, val, base))
            continue
        if token.startswith("str:"):
            candidate = repr(base)
            label = candidate if candidate not in taken else f"{base} (str)"
        elif non_str_counts.get(base, 0) == 1 and base not in taken:
            label = base
        else:
            candidate = f"{base} ({_token_kind(token)})"
            label = candidate if candidate not in taken else f"{base} ({token})"
        while label in taken:
            label = f"{label} [{token}]"
        taken.add(label)
        resolved.append(_Level(token, val, label))
    return resolved


def _extract_levels(column, present_rows, priority):
    """Extract typed levels in first-occurrence order (or worksheet priority order) from ``present_rows``."""
    arr = column.to_numpy(dtype=object)[present_rows]
    index = {}
    raw_levels = []
    codes = np.empty(len(present_rows), dtype=np.intp)
    for pos, value in enumerate(arr):
        token = typed_group_token(value)
        code = index.get(token)
        if code is None:
            code = index[token] = len(raw_levels)
            raw_levels.append((token, value.item() if isinstance(value, np.generic) else value))
        codes[pos] = code
    if priority:
        order = sorted(range(len(raw_levels)), key=lambda i: priority.get(raw_levels[i][0], len(priority)))
        raw_levels = [raw_levels[i] for i in order]
        inverse = np.empty(len(order), dtype=np.intp)
        for new_idx, old_idx in enumerate(order):
            inverse[old_idx] = new_idx
        codes = inverse[codes]
    levels = _disambiguate_labels(raw_levels)
    return levels, codes


def _validate_roles(frame, options):
    if not frame.columns.is_unique:
        raise FieldError(RESPONSE, "Worksheet column names must be unique.")
    names = {}
    for field in (RESPONSE, X_FACTOR, SERIES_FACTOR):
        name = options.get(field)
        if name is None or name == "":
            raise FieldError(field, f"Choose a column for {field}.")
        if not isinstance(name, str) or name not in frame:
            raise FieldError(field, f"Choose an existing column for {field}.")
        names[field] = name
    if names[X_FACTOR] == names[RESPONSE]:
        raise FieldError(X_FACTOR, "Choose an X factor column different from Response.")
    if names[SERIES_FACTOR] in (names[RESPONSE], names[X_FACTOR]):
        raise FieldError(SERIES_FACTOR, "Choose a Series factor column different from Response and X factor.")
    return names[RESPONSE], names[X_FACTOR], names[SERIES_FACTOR]


def _validate_error_options(options):
    raw_mode = options.get(ERROR_BARS)
    error_bars = DEFAULT_ERROR_BARS if raw_mode is None or raw_mode == "" else raw_mode
    if error_bars not in ERROR_BAR_CHOICES:
        raise FieldError(ERROR_BARS, "Choose a valid Error bars mode.")
    level = DEFAULT_CONFIDENCE_LEVEL
    if error_bars == CI:
        raw_level = options.get(CONFIDENCE_LEVEL, DEFAULT_CONFIDENCE_LEVEL)
        if isinstance(raw_level, (bool, np.bool_)):
            raise FieldError(CONFIDENCE_LEVEL, "Confidence level must be greater than 0 and less than 100.")
        try:
            text_val = decimal_comma(raw_level) if isinstance(raw_level, str) else raw_level
            level = float(text_val)
        except (TypeError, ValueError, OverflowError):
            raise FieldError(CONFIDENCE_LEVEL, "Confidence level must be greater than 0 and less than 100.") from None
        if not math.isfinite(level) or not (0.0 < level < 100.0):
            raise FieldError(CONFIDENCE_LEVEL, "Confidence level must be greater than 0 and less than 100.")
    return error_bars, level


def check_options(frame, options):
    """Validate recipe options and worksheet structure without drawing a figure."""
    response, x_factor, series_factor = _validate_roles(frame, options)
    error_bars, level = _validate_error_options(options)
    both_present = _present_mask(frame[x_factor]) & _present_mask(frame[series_factor])
    present_rows = np.flatnonzero(both_present)
    if not len(present_rows):
        raise FieldError(RESPONSE, "No row has a finite numeric Response with both factors present.")
    x_levels, x_codes = _extract_levels(frame[x_factor], present_rows, ranks(frame, x_factor))
    if len(x_levels) < 2:
        raise FieldError(X_FACTOR, "X factor requires at least two levels.")
    series_levels, series_codes = _extract_levels(frame[series_factor], present_rows, ranks(frame, series_factor))
    if len(series_levels) < 2:
        raise FieldError(SERIES_FACTOR, "Series factor requires at least two levels.")
    y_values = _parse_response(frame[response])[present_rows]
    valid_mask = np.isfinite(y_values)
    used_rows = int(valid_mask.sum())
    if used_rows == 0:
        raise FieldError(RESPONSE, "No row has a finite numeric Response with both factors present.")
    discarded_rows = int(len(frame) - used_rows)
    return _Prepared(
        response=response,
        x_factor=x_factor,
        series_factor=series_factor,
        error_bars=error_bars,
        confidence_level=level,
        x_levels=x_levels,
        series_levels=series_levels,
        valid_x_codes=x_codes[valid_mask],
        valid_series_codes=series_codes[valid_mask],
        valid_values=y_values[valid_mask],
        used_rows=used_rows,
        discarded_rows=discarded_rows,
    )


@lru_cache(maxsize=512)
def _t_critical(df, confidence_level):
    return float(t.ppf(0.5 + (confidence_level / 100.0) / 2.0, df=df))


def _cell_stats(vals, error_bars, confidence_level):
    n = int(len(vals))
    if n == 0:
        return 0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan
    if n == 1:
        mean = float(vals[0])
        if not math.isfinite(mean):
            raise FieldError(RESPONSE, "Response values exceed the supported numeric range.")
        return 1, mean, np.nan, np.nan, np.nan, np.nan, np.nan

    anchor = float(vals[0])
    with np.errstate(over="ignore", invalid="ignore"):
        shifted = vals - anchor
    if np.all(np.isfinite(shifted)):
        mean = anchor + float(np.mean(shifted))
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            mean = float(np.mean(vals))
    if not math.isfinite(mean):
        raise FieldError(RESPONSE, "Response values exceed the supported numeric range.")

    if np.all(vals == vals[0]):
        sd = 0.0
        sem = 0.0
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            diff = vals - mean
        if np.all(np.isfinite(diff)):
            max_abs = float(np.max(np.abs(diff)))
            if max_abs == 0.0:
                sd = 0.0
            else:
                scaled = diff / max_abs
                sd = max_abs * math.sqrt(float(np.sum(scaled * scaled)) / (n - 1))
        else:
            sd = float(np.std(vals, ddof=1))
        if not math.isfinite(sd):
            raise FieldError(RESPONSE, "Response values exceed the supported numeric range.")
        sem = sd / math.sqrt(n)
        if not math.isfinite(sem):
            raise FieldError(RESPONSE, "Response values exceed the supported numeric range.")

    if error_bars == NONE:
        return n, mean, sd, sem, np.nan, np.nan, np.nan
    if error_bars == SD:
        half = sd
    elif error_bars == SEM:
        half = sem
    else:
        half = _t_critical(n - 1, confidence_level) * sem
    lower = mean - half
    upper = mean + half
    if not (math.isfinite(half) and math.isfinite(lower) and math.isfinite(upper)):
        raise FieldError(RESPONSE, "Response values exceed the supported numeric range.")
    return n, mean, sd, sem, lower, upper, half


def compute_interaction_cells(prepared):
    """Compute the ``Interaction cells`` table and matrix arrays for plotting."""
    n_x = len(prepared.x_levels)
    n_s = len(prepared.series_levels)
    n_cells = n_x * n_s

    cell_ids = prepared.valid_x_codes * n_s + prepared.valid_series_codes
    order = np.argsort(cell_ids, kind="mergesort")
    sorted_ids = cell_ids[order]
    sorted_vals = prepared.valid_values[order]
    starts = np.searchsorted(sorted_ids, np.arange(n_cells), side="left")
    ends = np.searchsorted(sorted_ids, np.arange(n_cells), side="right")

    x_col = []
    s_col = []
    n_col = []
    mean_col = []
    sd_col = []
    sem_col = []
    lower_col = []
    upper_col = []

    means_grid = np.full((n_s, n_x), np.nan, dtype=np.float64)
    half_grid = np.full((n_s, n_x), np.nan, dtype=np.float64)

    for xi, x_lvl in enumerate(prepared.x_levels):
        for si, s_lvl in enumerate(prepared.series_levels):
            cid = xi * n_s + si
            vals = sorted_vals[starts[cid]:ends[cid]]
            n, mean, sd, sem, lower, upper, half = _cell_stats(
                vals, prepared.error_bars, prepared.confidence_level
            )
            x_col.append(x_lvl.label)
            s_col.append(s_lvl.label)
            n_col.append(n)
            mean_col.append(mean)
            sd_col.append(sd)
            sem_col.append(sem)
            lower_col.append(lower)
            upper_col.append(upper)
            means_grid[si, xi] = mean
            half_grid[si, xi] = half

    table = pd.DataFrame({
        "X level": pd.Series(x_col, dtype=object),
        "Series": pd.Series(s_col, dtype=object),
        "N": pd.Series(n_col, dtype=int),
        "Mean": pd.Series(mean_col, dtype=np.float64),
        "SD": pd.Series(sd_col, dtype=np.float64),
        "SEM": pd.Series(sem_col, dtype=np.float64),
        "Lower": pd.Series(lower_col, dtype=np.float64),
        "Upper": pd.Series(upper_col, dtype=np.float64),
    })
    return table, means_grid, half_grid


def _legend_title(series_factor, error_bars, confidence_level):
    if error_bars == SD:
        return f"{series_factor}\n(Mean ± SD)"
    if error_bars == SEM:
        return f"{series_factor}\n(Mean ± SEM)"
    if error_bars == CI:
        return f"{series_factor}\n(Mean ± {confidence_level:g}% CI)"
    return series_factor


def _keep_literal_text(axes):
    """Ensure ticks, legend entries, and default axis/title strings stay literal (never parsed as mathtext)."""
    for tick in axes.get_xticklabels():
        tick.set_parse_math(False)
    style = getattr(axes, "_tramastat_style", {})
    if "title" not in style:
        axes.title.set_parse_math(False)
    if "xlabel" not in style:
        axes.xaxis.label.set_parse_math(False)
    if "ylabel" not in style:
        axes.yaxis.label.set_parse_math(False)
    legend = axes.get_legend()
    if legend is not None:
        legend_opts = style.get(LEGEND_OPTIONS_KEY, {})
        if "title" not in legend_opts:
            legend.get_title().set_parse_math(False)
        custom_labels = legend_opts.get("labels", {})
        entry_keys = getattr(legend, "_tramastat_legend_keys", ())
        for idx, text in enumerate(legend.get_texts()):
            key = entry_keys[idx] if idx < len(entry_keys) else None
            if key not in custom_labels:
                text.set_parse_math(False)
        if style.get(LEGEND_OPTIONS_KEY):
            apply_legend_options(axes.figure, style[LEGEND_OPTIONS_KEY])


def draw_interaction_plot(prepared, means_grid, half_grid):
    """Build the Matplotlib Figure for the interaction plot."""
    figure, axes = _plot(METHOD, prepared.x_factor, prepared.response)
    axes.title.set_parse_math(False)
    axes.xaxis.label.set_parse_math(False)
    axes.yaxis.label.set_parse_math(False)

    n_x = len(prepared.x_levels)
    x_pos = np.arange(n_x, dtype=float)
    use_bars = prepared.error_bars != NONE

    for si, s_lvl in enumerate(prepared.series_levels):
        color = COLORS[si % len(COLORS)]
        marker = MARKERS[si % len(MARKERS)]
        means = means_grid[si]
        if not use_bars:
            axes.plot(
                x_pos, means, color=color, marker=marker, linestyle="-",
                linewidth=1.8, markersize=6.5, label=s_lvl.label, zorder=3,
            )
        else:
            yerr = half_grid[si]
            axes.errorbar(
                x_pos, means, yerr=yerr, fmt=f"-{marker}",
                color=color, ecolor=color, linewidth=1.8, markersize=6.5,
                elinewidth=1.3, capsize=4, label=s_lvl.label, zorder=3,
            )

    x_labels = [lvl.label for lvl in prepared.x_levels]
    long_labels = any(len(lbl) > 12 for lbl in x_labels)
    axes.set_xticks(x_pos, x_labels, rotation=20 if n_x > 5 or long_labels else 0)
    for tick in axes.get_xticklabels():
        tick.set_parse_math(False)
    axes.set_xlim(-0.5, n_x - 0.5)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)

    legend_title = _legend_title(prepared.series_factor, prepared.error_bars, prepared.confidence_level)
    legend = axes.legend(
        title=legend_title, loc="upper left", bbox_to_anchor=(1.02, 1),
        borderaxespad=0, frameon=False,
    )
    legend.get_title().set_parse_math(False)
    for text in legend.get_texts():
        text.set_parse_math(False)
    axes._tramastat_after_style = _keep_literal_text
    return figure


def style_after_parameter_change(style, before, after):
    """Preserve per-series style and legend labels when toggling Error bars between None and bar modes."""
    if not style:
        return style
    before_bars = (before.get(ERROR_BARS) or DEFAULT_ERROR_BARS) != NONE
    after_bars = (after.get(ERROR_BARS) or DEFAULT_ERROR_BARS) != NONE
    if before_bars == after_bars:
        return style
    old_prefix = "errorbar:" if before_bars else "line:"
    new_prefix = "errorbar:" if after_bars else "line:"

    def _remap(key):
        return new_prefix + key[len(old_prefix):] if isinstance(key, str) and key.startswith(old_prefix) else key

    updated = dict(style)
    if isinstance(style.get("series"), dict):
        updated["series"] = {_remap(k): v for k, v in style["series"].items()}
    legend_opts = style.get(LEGEND_OPTIONS_KEY)
    if isinstance(legend_opts, dict) and isinstance(legend_opts.get("labels"), dict):
        updated_legend = dict(legend_opts)
        updated_legend["labels"] = {_remap(k): v for k, v in legend_opts["labels"].items()}
        updated[LEGEND_OPTIONS_KEY] = updated_legend
    return updated


def interaction_plot(frame, options):
    """Compute cell summaries and draw the two-factor interaction plot."""
    prepared = check_options(frame, options)
    cells_table, means_grid, half_grid = compute_interaction_cells(prepared)
    figure = draw_interaction_plot(prepared, means_grid, half_grid)

    empty_cells = int((cells_table["N"] == 0).sum())
    settings = {
        "Response": prepared.response,
        "X factor": prepared.x_factor,
        "Series factor": prepared.series_factor,
        "Error bars": prepared.error_bars,
    }
    if prepared.error_bars == CI:
        settings["Confidence level (%)"] = prepared.confidence_level
    settings.update({
        "Rows used": prepared.used_rows,
        "Rows discarded": prepared.discarded_rows,
        "X levels": len(prepared.x_levels),
        "Series": len(prepared.series_levels),
        "Empty cells": f"{empty_cells} (cells with N = 0 leave empty statistics and break connecting lines)",
        "Note": (
            "Descriptive plot of observed cell means. Error bars belong to each individual cell "
            "(assuming independent observations within the cell, without multiplicity correction) "
            "and do not compute p-values, fitted marginal means, or paired-measure adjustments."
        ),
    })
    return Result({CELLS_SHEET: cells_table, SETTINGS_SHEET: _report(settings)}, figure)
