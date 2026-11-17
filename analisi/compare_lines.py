"""Compare two or more straight lines fitted by ordinary least squares.

Three nested models describe the same observations:

* full: an intercept and a slope for each group (2g parameters);
* parallel: an intercept for each group and one shared slope (g + 1);
* identical: one intercept and one slope for every group (2).

Slopes are compared first, full against parallel. Elevations are compared only
when that first p value is at least Alpha, parallel against identical, with the
parallel model's mean square error as the denominator. Both tests use the extra
sum-of-squares F ratio ``((SSE_r − SSE_f)/(df_r − df_f)) / (SSE_f/df_f)`` with
g − 1 numerator degrees of freedom and the upper F tail.

X is centered on the mean of every complete observation before fitting, and the
models are solved by orthogonal least squares (no normal equations). Reported
intercepts are moved back to the X scale that was entered.

Input is a long table (X, Y and Group columns) or a wide XY worksheet with one
shared X column and several Y columns. On a wide sheet each finite Y cell is an
observation of its series, repeated X values included; replicate subcolumns
recognized by the worksheet roles form one series and are never averaged first.
Missing and excluded cells are simply left out.
"""
from math import isfinite

import numpy as np
import pandas as pd
from scipy import stats

from .category_graphs import COLORS
from .processing import FieldError, _column
from .reporting import Result, _plot, _report
from .worksheet_series import series_columns, series_labels

COMPARE_LINES = "Compare regression lines"
LONG, WIDE = INPUTS = ("Long table", "Wide XY")
INDIVIDUAL, COMPARISON = MODEL_VIEWS = ("Individual lines", "Model chosen by the comparison")
MODEL_VIEW = "Model view"
OPTIONS = {"Input": INPUTS, "X": None, "Y": None, "Group": None, "Y columns": "Multiple",
           "Alpha": 0.05, MODEL_VIEW: MODEL_VIEWS}
LINES_SHEET = "Regression lines"
COMPARISON_SHEET = "Line comparison"
SUMMARY_SHEET = "Summary"
SLOPES, ELEVATIONS = "Slopes", "Elevations"
TESTED, NOT_TESTED = "Tested", "Not tested"
MAX_GROUPS = 24
MIN_ROWS = 3
GID = "lines:"
# Residual sums of squares at or below this fraction of the total sum of squares are treated as zero.
_EXACT = 1e-12
# A reduced model may beat the full one only by rounding; anything larger is a numerical failure.
_ROUNDING = 1e-9


def visibility(input_mode):
    """Fields that apply to the chosen input layout."""
    wide = input_mode == WIDE
    return {"Y": not wide, "Group": not wide, "Y columns": wide}


def _alpha(options):
    value = options.get("Alpha", .05)
    if isinstance(value, str):
        try:
            value = float(value.replace(",", ".").strip())
        except ValueError:
            value = np.nan
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        value = np.nan
    value = float(value)
    if not isfinite(value) or not 0 < value < 1:
        raise FieldError("Alpha", "Alpha must be a number strictly between 0 and 1.")
    return value


def _role(frame, options, name):
    value = options.get(name) or None
    if value is None:
        raise FieldError(name, f"Choose a column for {name}.")
    if not isinstance(value, str) or value not in frame:
        raise FieldError(name, f"Choose an existing column for {name}.")
    return value


def _text(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = value if isinstance(value, str) else str(value.item() if isinstance(value, np.generic) else value)
    return text if text.strip() else None


def _long(frame, options):
    x_name, y_name, group_name = (_role(frame, options, name) for name in ("X", "Y", "Group"))
    if len({x_name, y_name, group_name}) < 3:
        field = "Y" if y_name == x_name else "Group"
        raise FieldError(field, "Choose three different columns for X, Y and Group.")
    x = _column(frame, x_name, "X").to_numpy(dtype=float)
    y = _column(frame, y_name, "Y").to_numpy(dtype=float)
    labels = [_text(value) for value in frame[group_name].to_numpy(dtype=object)]
    keep = np.isfinite(x) & np.isfinite(y) & np.array([label is not None for label in labels], dtype=bool)
    rows = np.flatnonzero(keep)
    order = list(dict.fromkeys(labels[i] for i in rows))
    series = [(name, rows[[labels[i] == name for i in rows]]) for name in order]
    data = [(name, x[member], y[member], member + 1) for name, member in series]
    return data, x_name, y_name, "Group"


def _wide(frame, options):
    x_name = _role(frame, options, "X")
    names = options.get("Y columns") or []
    if isinstance(names, str) or not all(isinstance(name, str) for name in names):
        raise FieldError("Y columns", "Choose the Y columns.")
    if not names:
        raise FieldError("Y columns", "Select at least two Y columns.")
    missing = [name for name in names if name not in frame]
    if missing:
        raise FieldError("Y columns", f'Column "{missing[0]}" is not in the worksheet.')
    if x_name in names:
        raise FieldError("Y columns", "X cannot also be a Y column.")
    x = _column(frame, x_name, "X").to_numpy(dtype=float)
    groups = series_columns(frame, list(dict.fromkeys(names)), recognize_replicates=False)
    data = []
    for label, members in zip(series_labels(groups), groups, strict=True):
        xs, ys, rows = [], [], []
        values = {name: _column(frame, name, "Y columns").to_numpy(dtype=float) for name in members}
        # Row order first, then subcolumn order, so source rows stay sorted.
        for i in range(len(frame)):
            if not np.isfinite(x[i]):
                continue
            for name in members:
                if np.isfinite(values[name][i]):
                    xs.append(x[i])
                    ys.append(values[name][i])
                    rows.append(i + 1)
        data.append((label, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), np.asarray(rows)))
    return data, x_name, ", ".join(names) if len(names) <= 3 else "Y", "Y columns"


def _lstsq(design, y):
    """Least-squares coefficients, rank and residual sum of squares (orthogonal solver)."""
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coefficients
    return coefficients, int(rank), float(residual @ residual)


def _extra_ss(reduced, full, reduced_df, full_df, mse_df, mse_sse):
    """Extra sum-of-squares F test; only rounding below zero is corrected."""
    gain = reduced - full
    if gain < 0:
        if -gain > _ROUNDING * max(reduced, full, 1e-300):
            raise ValueError("The nested models could not be fitted reliably. Check the X and Y values.")
        gain = 0.
    df1 = reduced_df - full_df
    f = (gain / df1) / (mse_sse / mse_df)
    return f, df1, mse_df, float(stats.f.sf(f, df1, mse_df))


def compare_lines(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("X", "Worksheet column names must be unique.")
    mode = options.get("Input", LONG) or LONG
    if mode not in INPUTS:
        raise FieldError("Input", "Choose Long table or Wide XY.")
    alpha = _alpha(options)
    view = options.get(MODEL_VIEW, INDIVIDUAL) or INDIVIDUAL
    if view not in MODEL_VIEWS:
        raise FieldError(MODEL_VIEW, "Choose which lines the graph shows.")
    data, x_name, y_name, field = (_wide if mode == WIDE else _long)(frame, options)
    if len(data) < 2:
        raise FieldError(field, "Compare at least two groups: the selected data contain "
                                f"{len(data)} group{'s' if len(data) != 1 else ''} with complete X and Y values.")
    if len(data) > MAX_GROUPS:
        raise FieldError(field, f"Compare at most {MAX_GROUPS} groups at a time.")
    for name, x, _, _ in data:
        if len(x) < MIN_ROWS:
            raise FieldError(field, f'Group "{name}" has {len(x)} complete X/Y pair{"s" if len(x) != 1 else ""}. '
                                    f"Each line needs at least {MIN_ROWS}.")
        if np.unique(x).size < 2:
            raise FieldError("X", f'Group "{name}" has a single X value, so its slope is undefined. '
                                  "Each line needs at least two distinct X values.")

    g = len(data)
    x_all = np.concatenate([x for _, x, _, _ in data])
    y_all = np.concatenate([y for _, _, y, _ in data])
    member = np.concatenate([np.full(len(x), k) for k, (_, x, _, _) in enumerate(data)])
    n = len(x_all)
    reference = float(np.mean(x_all))
    centered = x_all - reference
    total = float(((y_all - y_all.mean()) ** 2).sum())

    # Full model, one fit per group: the design is block diagonal, so the separate fits are the full fit.
    lines, sse_full = [], 0.
    for k, (name, x, y, rows) in enumerate(data):
        design = np.column_stack([np.ones(len(x)), x - reference])
        (b0, b1), rank, sse = _lstsq(design, y)
        if rank < 2:
            raise FieldError("X", f'Group "{name}": the X values are too close together to estimate a slope.')
        sse_full += sse
        intercept = b0 - b1 * reference
        count = len(x)
        mean_x = float(np.mean(x))
        sxx = float(((x - mean_x) ** 2).sum())
        s2 = sse / (count - 2)
        lines.append({"Group": name, "N": count, "Intercept": intercept, "Slope": b1,
                      "Intercept SE": float(np.sqrt(s2 * (1 / count + mean_x ** 2 / sxx))),
                      "Slope SE": float(np.sqrt(s2 / sxx)), "SSE": sse, "Residual df": count - 2,
                      "X min": float(x.min()), "X max": float(x.max())})
    df_full = n - 2 * g
    if not total > 0 or sse_full <= _EXACT * total:
        raise FieldError(field, "Every line passes exactly through its points, so the residual variance is zero "
                                "and the F tests are undefined.")

    dummies = (member[:, None] == np.arange(g)[None, :]).astype(float)
    parallel_coef, parallel_rank, sse_parallel = _lstsq(np.column_stack([dummies, centered]), y_all)
    identical_coef, identical_rank, sse_identical = _lstsq(np.column_stack([np.ones(n), centered]), y_all)
    if parallel_rank < g + 1 or identical_rank < 2:
        raise FieldError("X", "The X values do not vary enough to compare the lines.")
    df_parallel, df_identical = n - g - 1, n - 2

    f_slopes = _extra_ss(sse_parallel, sse_full, df_parallel, df_full, df_full, sse_full)
    comparisons = [{"Comparison": SLOPES, "F": f_slopes[0], "df1": f_slopes[1], "df2": f_slopes[2],
                    "p": f_slopes[3], "Status": TESTED}]
    slopes_differ = f_slopes[3] < alpha
    if slopes_differ:
        comparisons.append({"Comparison": ELEVATIONS, "F": np.nan, "df1": np.nan, "df2": np.nan, "p": np.nan,
                            "Status": NOT_TESTED})
        elevations_differ = None
    else:
        if not sse_parallel > _EXACT * total:
            raise FieldError(field, "The parallel lines fit the data exactly, so the elevation test is undefined.")
        f_heights = _extra_ss(sse_identical, sse_parallel, df_identical, df_parallel, df_parallel, sse_parallel)
        comparisons.append({"Comparison": ELEVATIONS, "F": f_heights[0], "df1": f_heights[1], "df2": f_heights[2],
                            "p": f_heights[3], "Status": TESTED})
        elevations_differ = f_heights[3] < alpha

    common_slope = float(parallel_coef[g])
    parallel_intercepts = [float(parallel_coef[k] - common_slope * reference) for k in range(g)]
    pooled_slope = float(identical_coef[1])
    pooled_intercept = float(identical_coef[0] - pooled_slope * reference)

    summary = {"Alpha": alpha, "Groups": g, "N": n, "Residual df (separate lines)": df_full}
    if slopes_differ:
        summary["Conclusion"] = (f"The slopes differ (P = {f_slopes[3]:.4g} < {alpha:g}). "
                                 "Elevations were not compared.")
    elif elevations_differ:
        summary["Conclusion"] = (f"The slopes do not differ (P = {f_slopes[3]:.4g}); the lines are parallel with "
                                 f"different elevations (P = {comparisons[1]['p']:.4g} < {alpha:g}).")
    else:
        summary["Conclusion"] = (f"No evidence that the lines differ (slopes P = {f_slopes[3]:.4g}, elevations "
                                 f"P = {comparisons[1]['p']:.4g}). One line fits every group.")
    if not slopes_differ:
        summary["Common slope"] = common_slope
        for k, (name, *_rest) in enumerate(data):
            summary[f"Parallel intercept · {name}"] = parallel_intercepts[k]
    if elevations_differ is False:
        summary["Pooled intercept"] = pooled_intercept
        summary["Pooled slope"] = pooled_slope
    if slopes_differ and g == 2:
        first, second = lines
        difference = first["Slope"] - second["Slope"]
        crossing = (second["Intercept"] - first["Intercept"]) / difference if difference else np.nan
        if np.isfinite(crossing):
            summary["Intersection X"] = float(crossing)
            summary["Intersection Y"] = float(first["Intercept"] + first["Slope"] * crossing)
            low = max(first["X min"], second["X min"])
            high = min(first["X max"], second["X max"])
            summary["Intersection note"] = ("Within the X range observed in both groups." if low <= crossing <= high
                                            else "Outside the X range observed in both groups (extrapolated).")
        else:
            summary["Intersection note"] = "The lines do not cross at a finite X."

    sheet = pd.DataFrame(lines, columns=["Group", "N", "Intercept", "Slope", "Intercept SE", "Slope SE", "SSE",
                                         "Residual df", "X min", "X max"])
    report = pd.DataFrame(comparisons, columns=["Comparison", "F", "df1", "df2", "p", "Status"])

    figure, axes = _plot(COMPARE_LINES, x_name, y_name)
    palette = COLORS * (g // len(COLORS) + 1)
    if view == COMPARISON and not slopes_differ:
        drawn = ([(pooled_intercept, pooled_slope)] * g if elevations_differ is False
                 else [(a, common_slope) for a in parallel_intercepts])
    else:
        drawn = [(line["Intercept"], line["Slope"]) for line in lines]
    pooled = view == COMPARISON and elevations_differ is False
    for k, ((name, x, y, _), (a, b)) in enumerate(zip(data, drawn, strict=True)):
        color = palette[k]
        points = axes.scatter(x, y, color=color, s=28, zorder=2.5, label=name)
        points.set_gid(f"{GID}points:{name}")
        if pooled:
            continue
        ends = np.array([x.min(), x.max()])
        (line,) = axes.plot(ends, a + b * ends, color=color, linewidth=1.8, label="_nolegend_")
        line.set_gid(f"{GID}line:{name}")
    if pooled:
        ends = np.array([x_all.min(), x_all.max()])
        (line,) = axes.plot(ends, pooled_intercept + pooled_slope * ends, color="#333333", linewidth=1.8,
                            label="Pooled line")
        line.set_gid(f"{GID}line:pooled")
    axes.legend(frameon=False, loc="best")
    return Result({LINES_SHEET: sheet, COMPARISON_SHEET: report, SUMMARY_SHEET: _report(summary)}, figure)
