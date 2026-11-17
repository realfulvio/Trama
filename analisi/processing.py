"""Scientific worksheet data-processing analyses.

Transform concentrations (X), Remove baseline and column math, Prune rows and
Fraction of total. Every function receives the table with excluded cells
already masked and returns new frames. The source frame is never modified, so
an error leaves the caller's data exactly as it was.

Implementation conventions are documented next to their code and covered
by tests/test_processing.py.
"""
from decimal import Decimal, InvalidOperation
from math import ceil, floor
import re

import numpy as np
import pandas as pd
from scipy import stats

from .data import MAX_CELLS, MAX_COLUMNS, decimal_comma
from .field_error import FieldError
from .reporting import Result, _report
from .stats import linear

MULTIPLE, OPTIONAL, OPTIONAL_MULTIPLE, TEXT = "Multiple", "Optional", "Multiple (optional)", "Text"

UNIT_CHANGES = ("No change", "Multiply by", "Divide by")
LOGARITHMS = ("None", "Log10", "Natural log")
BASELINES = ("Baseline column, same row", "Alternate columns: A, C, E… are baselines",
             "Alternate columns: B, D, F… are baselines", "Mean of first K rows", "Mean of last K rows",
             "Linear fit of baseline column vs X")
OPERATIONS = ("Difference: Y − baseline", "Ratio: Y / baseline", "Sum: Y + baseline", "Product: Y × baseline",
              "Fractional difference: (Y − baseline) / baseline",
              "Percent difference: 100 × (Y − baseline) / baseline")
PRUNE_MODES = ("Keep rows within an X range", "Average every K rows (sorted by X)")
COMBINED_TOTALS = "All three (one table)"
DENOMINATORS = ("Column total", "Row total", "Grand total", "All three (separate tables)", COMBINED_TOTALS)
WILSON_BROWN = "Wilson–Brown (modified Wilson)"
INTERVALS = ("None", "Clopper–Pearson (exact)", "Wilson (no continuity correction)", WILSON_BROWN)

METHODS = {
    "Transform concentrations (X)": {
        "X": None, "Replace zero X": False, "Zero replacement (original units)": 1e-11,
        "Change units": UNIT_CHANGES, "Unit factor": 1.0, "Logarithm": LOGARITHMS,
    },
    "Remove baseline and column math": {
        "Data columns": MULTIPLE, "Baseline column": OPTIONAL, "Baseline subcolumns": OPTIONAL_MULTIPLE,
        "X": OPTIONAL, "Row titles": OPTIONAL,
        "Replicate handling": ("Independent columns", "Each replicate vs baseline mean", "Mean vs baseline mean",
                               "Matched subcolumns"),
        "Baseline": BASELINES, "Rows for baseline (K)": 1, "Drop baseline rows": False, "Operation": OPERATIONS,
    },
    "Prune rows": {
        "X": None, "Method": PRUNE_MODES, "X minimum (blank = no limit)": TEXT,
        "X maximum (blank = no limit)": TEXT, "Rows per group (K)": 2,
        "Average only rows above an X threshold": False, "X threshold": TEXT,
    },
    "Fraction of total": {
        "Variables": MULTIPLE, "Row titles": OPTIONAL, "Divide by": DENOMINATORS,
        "Show as": ("Fractions", "Percentages"), "Confidence interval": INTERVALS, "Confidence level (%)": 95.0,
    },
}

# Subcolumns created by replicate and summary-data tables, e.g. "Control [2]".
SUBCOLUMN = re.compile(r".+ \[(?:[1-9]\d*|Mean|SD|SEM|N|Center|Plus|Minus|Lower|Upper|CV%?|Value|Error)\]"
                       r"(?: \(\d+\))?")


def _column(frame, name, field, *, preserve_integers=False):
    if not name or name not in frame:
        raise FieldError(field, f"Choose a column for {field}.")
    raw = frame[name]
    numbers = pd.to_numeric(raw, errors="coerce", dtype_backend="numpy_nullable")
    if np.iscomplexobj(np.asarray(numbers)):
        raise FieldError(field, f'Column "{name}" contains complex data.')
    values = numbers.to_numpy(dtype=float, na_value=np.nan)
    if (raw.notna().to_numpy() & ~np.isfinite(values)).any():
        raise FieldError(field, f'Column "{name}" contains text or infinite values.')
    if pd.api.types.is_integer_dtype(numbers):
        if preserve_integers:
            return numbers
        _check_integer_precision(numbers, values, field)
    elif not pd.api.types.is_float_dtype(raw):
        # Mixed decimal and integer strings may already have been coerced to a float column.
        large = np.abs(values) >= 2**53
        for original, value in zip(raw.iloc[large], values[large], strict=True):
            if not isinstance(original, (str, int, np.integer, Decimal)):
                continue
            number = Decimal(str(original))
            if number == number.to_integral_value() and number != int(value):
                raise FieldError(field, f'Column "{name}" contains integers outside the supported precision.')
    return pd.Series(values, index=frame.index, name=name)


def _check_integer_precision(series, values, field):
    large = np.abs(values) >= 2**53
    if any(int(original) != int(value) for original, value in zip(series.iloc[large], values[large], strict=True)):
        raise FieldError(field, f'Column "{series.name}" contains integers outside the supported precision.')


def _number(value, field):
    try:
        number = float(decimal_comma(value) if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, f"{field} must be a number.") from None
    if not np.isfinite(number):
        raise FieldError(field, f"{field} must be finite.")
    return number


def _positive(value, field, detail=""):
    number = _number(value, field)
    if number <= 0:
        raise FieldError(field, f"{field} must be greater than zero.{detail}")
    return number


def _x_limit(value, field, xs):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not pd.api.types.is_integer_dtype(xs):
        return _number(value, field)
    try:
        number = Decimal(decimal_comma(str(value)))
    except InvalidOperation:
        raise FieldError(field, f"{field} must be a number.") from None
    if not number.is_finite():
        raise FieldError(field, f"{field} must be finite.")
    return number


def _within_x_limit(xs, limit, *, minimum):
    if pd.api.types.is_integer_dtype(xs):
        limits = np.iinfo(getattr(xs.dtype, "numpy_dtype", xs.dtype))
        if limit < limits.min:
            return xs.notna() if minimum else pd.Series(False, index=xs.index)
        if limit > limits.max:
            return pd.Series(False, index=xs.index) if minimum else xs.notna()
        limit = ceil(limit) if minimum else floor(limit)
    return xs >= limit if minimum else xs <= limit


def _reported_x_limit(limit):
    if limit is None:
        return "none"
    if isinstance(limit, Decimal):
        number = float(limit)
        return number if Decimal(str(number)) == limit else str(limit)
    return limit


def _whole(value, field, minimum, maximum=None):
    if isinstance(value, bool):
        raise FieldError(field, f"{field} must be a whole number.")
    number = _number(value, field)
    if not number.is_integer():
        raise FieldError(field, f"{field} must be a whole number.")
    number = int(number)
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise FieldError(field, f"{field} must be {limit}.")
    return number


def _distinct(frame, roles):
    """roles maps field → column name (or None). Columns may fill one role each."""
    seen = {}
    for field, name in roles.items():
        if not name:
            continue
        if name not in frame:
            raise FieldError(field, f'Column "{name}" is not in the table.')
        if name in seen:
            raise FieldError(field, f'"{name}" is already used as {seen[name]}.')
        seen[name] = field


def _finite(values, field, action, *, present=None):
    data = (values.to_numpy(dtype=float, na_value=np.nan) if isinstance(values, (pd.DataFrame, pd.Series))
            else np.asarray(values, dtype=float))
    invalid = np.isinf(data) if present is None else np.asarray(present) & ~np.isfinite(data)
    if invalid.any():
        raise FieldError(field, f"{action} makes a value exceed the numeric range.")


# Transform concentrations (X) ------------------------------------------------


def transform_concentrations(frame, o):
    """Replace zero X, change units, then take the logarithm, in that order.

    Trama choice: in log mode, X values that are zero (without replacement)
    or negative become blank cells. The Notes sheet reports how many, so no
    value disappears silently and no -inf/inf or NumPy warning is produced.
    """
    x = o.get("X")
    _distinct(frame, {"X": x})
    values = _column(frame, x, "X")
    replace = bool(o.get("Replace zero X", False))
    units = o.get("Change units", "No change")
    logarithm = o.get("Logarithm", "None")
    if units not in UNIT_CHANGES:
        raise FieldError("Change units", "Choose how to change units.")
    if logarithm not in LOGARITHMS:
        raise FieldError("Logarithm", "Choose a logarithm.")
    notes = {"X column": x}
    if replace:
        field = "Zero replacement (original units)"
        substitute = _positive(o.get(field), field)
        replaced = int((values == 0).sum())
        values = values.mask(values == 0, substitute)
        notes.update({"Zero replacement": f"{substitute:g}", "Zero X replaced": replaced})
    else:
        notes["Zero replacement"] = "Off"
    if units != "No change":
        factor = _positive(o.get("Unit factor"), "Unit factor",
                           " Division by zero is undefined." if units == "Divide by" else "")
        with np.errstate(over="ignore", under="ignore"):
            values = values * factor if units == "Multiply by" else values / factor
        _finite(values, "Unit factor", "Changing units")
        notes["Unit change"] = f"{units.lower()} {factor:g}"
    else:
        notes["Unit change"] = "Off"
    notes["Logarithm"] = logarithm
    if logarithm != "None":
        notes["Zero X left blank"] = int((values == 0).sum())
        notes["Negative X left blank"] = int((values < 0).sum())
        positive = values.where(values > 0)
        values = np.log10(positive) if logarithm == "Log10" else np.log(positive)
    result = frame.copy()
    result[x] = values
    return Result({"Transformed data": result, "Notes": _report(notes)})


# Remove baseline and column math ----------------------------------------------


def _apply(operation, y, baseline):
    """Return the result and the number of computed cells with a zero denominator."""
    divides = operation.startswith(("Ratio", "Fractional", "Percent"))
    zero = int(((baseline == 0) & y.notna()).sum()) if divides else 0
    denominator = baseline.where(baseline != 0) if divides else baseline
    with np.errstate(all="ignore"):
        if operation.startswith("Difference"):
            result = y - baseline
        elif operation.startswith("Ratio"):
            result = y / denominator
        elif operation.startswith("Sum"):
            result = y + baseline
        elif operation.startswith("Product"):
            result = y * baseline
        elif operation.startswith("Fractional"):
            result = (y - baseline) / denominator
        elif operation.startswith("Percent"):
            result = ((y - baseline) / denominator) * 100
        else:
            raise FieldError("Operation", "Choose an operation.")
    _finite(result, "Operation", operation.partition(":")[0])
    return result, zero


def remove_baseline(frame, o):
    """Combine each data column with a baseline from the same row or the same column.

    Trama choices: a cell whose denominator is zero becomes blank and is
    counted in the Notes sheet; a baseline with no values at all is an error.
    With Independent columns (the default, and the only path of recipes saved
    before 0.49) replicate subcolumns ("Name [1]") are treated as independent
    columns; the other Replicate handling modes live in replicate_baseline.
    """
    from .replicate_baseline import INDEPENDENT, replicate_baseline, replicate_handling

    if replicate_handling(o) != INDEPENDENT:
        return replicate_baseline(frame, o)
    columns = list(o.get("Data columns") or [])
    if not columns or len(set(columns)) != len(columns):
        raise FieldError("Data columns", "Select one or more distinct data columns.")
    mode, operation = o.get("Baseline"), o.get("Operation")
    if mode not in BASELINES:
        raise FieldError("Baseline", "Choose a baseline.")
    if operation not in OPERATIONS:
        raise FieldError("Operation", "Choose an operation.")
    x, titles, base_name = o.get("X"), o.get("Row titles"), o.get("Baseline column")
    uses_column = mode in (BASELINES[0], BASELINES[5])
    roles = {"X": x, "Row titles": titles, "Baseline column": base_name if uses_column else None}
    _distinct(frame, roles)
    for name in columns:
        if name not in frame:
            raise FieldError("Data columns", f'Column "{name}" is not in the table.')
        for field, role in roles.items():
            if role == name:
                raise FieldError("Data columns", f'"{name}" is already used as {field}.')
    data = {name: _column(frame, name, "Data columns") for name in columns}
    rows = len(frame)
    summary = {"Baseline": mode, "Operation": operation}
    keep = np.ones(rows, dtype=bool)
    extra = {}
    if uses_column:
        if not base_name:
            raise FieldError("Baseline column", "Choose the baseline column.")
        baseline = _column(frame, base_name, "Baseline column")
        if baseline.isna().all():
            raise FieldError("Baseline column", f'The baseline column "{base_name}" has no values.')
        summary["Baseline column"] = base_name
        if mode == BASELINES[5]:
            if not x:
                raise FieldError("X", "Choose an X column for the linear baseline.")
            xs = _column(frame, x, "X")
            pairs = pd.DataFrame({"x": xs, "baseline": baseline}).dropna()
            if len(pairs) < 3 or pairs["x"].nunique() < 2:
                raise FieldError("Baseline column", "A linear baseline needs at least three complete X/baseline "
                                 "pairs with two or more distinct X values.")
            with np.errstate(all="ignore"):
                fit = linear(pairs, "x", "baseline")
                baseline = fit["Intercept"] + fit["Slope"] * xs
            _finite((fit["Intercept"], fit["Slope"]), "Baseline column", "Fitting the baseline", present=True)
            _finite(baseline, "Baseline column", "Predicting the baseline", present=xs.notna())
            summary.update({"Pairs used": fit["N"], "Intercept": fit["Intercept"], "Slope": fit["Slope"]})
            x_label = f"{x} (X)" if x in {"Observed baseline", "Predicted baseline"} else x
            extra["Linear baseline"] = pd.DataFrame({x_label: frame[x], "Observed baseline": frame[base_name],
                                                     "Predicted baseline": baseline})
        targets = [(name, baseline) for name in columns]
    elif mode in BASELINES[1:3]:
        if len(columns) < 2 or len(columns) % 2:
            raise FieldError("Data columns", "Alternate pairing needs an even number of selected columns. "
                                             "Pairs follow the table order.")
        position = list(frame.columns).index
        ordered = sorted(columns, key=position)
        odd, even = ordered[0::2], ordered[1::2]
        baselines, measured = (odd, even) if mode == BASELINES[1] else (even, odd)
        for name in baselines:
            if data[name].isna().all():
                raise FieldError("Data columns", f'The baseline column "{name}" has no values.')
        targets = [(name, data[base]) for name, base in zip(measured, baselines, strict=True)]
        summary.update({f"Baseline for {name}": base for name, base in zip(measured, baselines, strict=True)})
    else:
        k = _whole(o.get("Rows for baseline (K)"), "Rows for baseline (K)", 1, rows)
        first = mode == BASELINES[3]
        window = slice(0, k) if first else slice(rows - k, rows)
        targets = []
        for name in columns:
            reference = data[name].iloc[window]
            if reference.isna().all():
                where = "first" if first else "last"
                raise FieldError("Rows for baseline (K)",
                                 f'Column "{name}" has no values in the {where} {k} row(s).')
            with np.errstate(all="ignore"):
                value = reference.mean()
                if not np.isfinite(value):
                    scale = reference.abs().max()
                    value = (reference / scale).mean() * scale
            _finite(value, "Rows for baseline (K)", "Averaging the baseline", present=True)
            targets.append((name, pd.Series(value, index=frame.index)))
            summary[f"Baseline of {name}"] = value
        if o.get("Drop baseline rows", False):
            keep[window] = False
            summary["Rows removed"] = k
    output = {}
    if titles:
        output[titles] = frame[titles]
    if x:
        output[x] = frame[x]
    zero = 0
    for name, baseline in targets:
        output[name], count = _apply(operation, data[name], baseline)
        zero += count
    if zero:
        summary["Zero denominators left blank"] = zero
    result = pd.DataFrame(output, index=frame.index).iloc[keep].reset_index(drop=True)
    return Result({"Processed data": result, **extra, "Notes": _report(summary)})


# Prune rows -----------------------------------------------------------------


def prune_rows(frame, o):
    """Keep an inclusive X range or average consecutive groups of rows after sorting by X.

    Trama choices for cases the guides do not settle:
    - Rows with a blank X are dropped in both modes and counted in the Notes.
    - Averaging sorts by X with a stable sort, so tied X keep their source order
      and a tie can fall on both sides of a group boundary.
    - Every numeric column is averaged over its present values; a group with no
      value in a column stays blank in that column.
    - A text column keeps its value when it is the same in the whole group and
      is blank otherwise.
    - An incomplete last group is kept as the mean of its rows.
    """
    x = o.get("X")
    _distinct(frame, {"X": x})
    xs = _column(frame, x, "X", preserve_integers=True)
    mode = o.get("Method")
    missing = int(xs.isna().sum())
    notes = {"Method": mode, "Rows in": len(frame), "Rows with blank X dropped": missing}
    if mode == PRUNE_MODES[0]:
        low_field, high_field = "X minimum (blank = no limit)", "X maximum (blank = no limit)"
        low = _x_limit(o.get(low_field), low_field, xs)
        high = _x_limit(o.get(high_field), high_field, xs)
        if low is None and high is None:
            raise FieldError(low_field, "Enter an X minimum, an X maximum or both.")
        if low is not None and high is not None and low > high:
            raise FieldError(high_field, "X maximum must not be smaller than X minimum.")
        keep = xs.notna()
        if low is not None:
            keep &= _within_x_limit(xs, low, minimum=True)
        if high is not None:
            keep &= _within_x_limit(xs, high, minimum=False)
        result = frame.loc[keep.to_numpy()].reset_index(drop=True)
        notes.update({"X minimum": _reported_x_limit(low), "X maximum": _reported_x_limit(high)})
    elif mode == PRUNE_MODES[1]:
        field = "Rows per group (K)"
        k = _whole(o.get(field), field, 2, MAX_CELLS)
        present = xs.notna().to_numpy()
        present_x = xs.iloc[present]
        order = np.argsort(present_x.to_numpy(), kind="stable")
        rows = frame.loc[present].iloc[order].reset_index(drop=True)
        rows[x] = present_x.iloc[order].reset_index(drop=True)
        count = len(rows)
        whole = 0
        if o.get("Average only rows above an X threshold", False):
            threshold = _x_limit(o.get("X threshold"), "X threshold", xs)
            if threshold is None:
                raise FieldError("X threshold", "Enter an X threshold.")
            whole = int(_within_x_limit(rows[x], threshold, minimum=False).sum())
            notes["Rows kept whole (X ≤ threshold)"] = whole
        groups = np.r_[np.arange(whole), whole + np.arange(count - whole) // k]
        numeric = [name for name in rows.columns if pd.api.types.is_numeric_dtype(rows[name])
                   and not pd.api.types.is_bool_dtype(rows[name])]
        text = [name for name in rows.columns if name not in numeric]
        parts = []
        exact_x = (pd.api.types.is_integer_dtype(rows[x]) and
                   ((rows[x] > 2**53) | (rows[x] < -(2**53))).any())
        if exact_x:
            # Sum Python integers before division so only the final mean is rounded.
            grouped_x = rows[x].astype(object).groupby(groups, sort=False)
            parts.append((grouped_x.sum() / grouped_x.size()).astype(float))
            numeric.remove(x)
        if numeric:
            means = rows[numeric].astype("Float64")
            for name in numeric:
                if pd.api.types.is_integer_dtype(rows[name]):
                    _check_integer_precision(rows[name], means[name].to_numpy(dtype=float, na_value=np.nan), field)
            grouped = means.groupby(groups, sort=False)
            with np.errstate(all="ignore"):
                averaged = grouped.mean()
            _finite(averaged, field, "Averaging the rows")
            if averaged.isna().any().any():
                _finite(averaged, field, "Averaging the rows", present=grouped.count() > 0)
            parts.append(averaged)
        if text:
            grouped = rows[text].groupby(groups, sort=False)
            parts.append(grouped.first().where(grouped.nunique() <= 1))
        result = pd.concat(parts, axis=1)[list(rows.columns)].reset_index(drop=True)
        result[x] = result[x].astype(float)
        tail = (count - whole) % k
        notes.update({"Rows per group": k, "Incomplete last group (rows)": tail})
    else:
        raise FieldError("Method", "Choose a pruning method.")
    notes["Rows out"] = len(result)
    return Result({"Pruned data": result, "Notes": _report(notes)})


# Fraction of total ----------------------------------------------------------


def _intervals(kind, counts, totals, level):
    if kind == WILSON_BROWN and not 50 <= level < 100:
        raise FieldError("Confidence level (%)", "Wilson–Brown requires a confidence level from 50% to below 100%.")
    tail = (100 - level) / 200
    k, n = np.asarray(counts, dtype=float), np.asarray(totals, dtype=float)
    valid = np.isfinite(k) & np.isfinite(n) & (n > 0)
    k, n = np.where(valid, k, 0.), np.where(valid, n, 1.)
    with np.errstate(all="ignore"):
        if kind == INTERVALS[1]:
            lower = np.where(k == 0, 0., stats.beta.ppf(tail, k, n - k + 1))
            upper = np.where(k == n, 1., stats.beta.isf(tail, k + 1, n - k))
        else:
            z = stats.norm.isf(tail)
            p = k / n
            weight = z * z / n
            scale = 1 + weight
            centre = (p + weight / 2) / scale
            half = z * np.sqrt(p * (1 - p) + weight / 4) / np.sqrt(n) / scale
            lower, upper = np.clip(centre - half, 0, 1), np.clip(centre + half, 0, 1)
            if kind == WILSON_BROWN:
                # Brown, Cai and DasGupta (2001), §4.1.1, use the full
                # alpha in the Poisson substitution for a single bound.
                cutoff = np.where(n > 50, 3, 2)
                low_tail = (k >= 1) & (k <= cutoff) & (k < n)
                remaining = n - k
                high_tail = (remaining >= 1) & (remaining <= cutoff) & (k > 0)
                low_poisson = stats.chi2.ppf(2 * tail, 2 * np.where(low_tail, k, 1)) / (2 * n)
                high_poisson = stats.chi2.ppf(2 * tail, 2 * np.where(high_tail, remaining, 1)) / (2 * n)
                lower = np.where(k == 0, 0., np.where(low_tail, low_poisson, lower))
                upper = np.where(k == n, 1., np.where(high_tail, 1 - high_poisson, upper))
    return np.where(valid, lower, np.nan), np.where(valid, upper, np.nan)


def fraction_of_total(frame, o):
    """Divide each value by its column, row or grand total.

    Blank cells stay blank and do not count in any total. A total that is zero
    or has no observations gives blank results. Confidence intervals treat each
    cell as k successes out of n = its total and need whole, nonnegative counts.
    """
    columns = list(o.get("Variables") or [])
    if not columns or len(set(columns)) != len(columns):
        raise FieldError("Variables", "Select one or more distinct numeric columns.")
    titles = o.get("Row titles")
    _distinct(frame, {"Row titles": titles})
    for name in columns:
        if name not in frame:
            raise FieldError("Variables", f'Column "{name}" is not in the table.')
        if name == titles:
            raise FieldError("Variables", f'"{name}" is already used as Row titles.')
        if SUBCOLUMN.fullmatch(str(name)):
            raise FieldError("Variables", f'"{name}" is a subcolumn. Fraction of total works on tables without '
                                          "replicate or summary subcolumns. Choose plain columns.")
    data = pd.DataFrame({name: _column(frame, name, "Variables") for name in columns}, index=frame.index)
    mode, interval = o.get("Divide by"), o.get("Confidence interval", "None")
    if mode not in DENOMINATORS:
        raise FieldError("Divide by", "Choose which total to divide by.")
    width = 3 * len(columns) + int(bool(titles))
    if mode == COMBINED_TOTALS and (width > MAX_COLUMNS or width * len(data) > MAX_CELLS):
        raise FieldError("Divide by", "The combined table is too wide or large. Choose separate tables.")
    if interval not in INTERVALS:
        raise FieldError("Confidence interval", "Choose a confidence interval.")
    percent = o.get("Show as") == "Percentages"
    scale = 100 if percent else 1
    noun = "Percent" if percent else "Fraction"
    level = None
    if interval != "None":
        if mode in DENOMINATORS[3:]:
            raise FieldError("Confidence interval", "Confidence intervals are not available with all three totals. "
                                                    "Choose one total, or set Confidence interval to None.")
        level = _number(o.get("Confidence level (%)"), "Confidence level (%)")
        if not 0 < level < 100:
            raise FieldError("Confidence level (%)", "Confidence level (%) must be between 0 and 100.")
        invalid = data.notna() & ((data < 0) | (data % 1 != 0))
        if invalid.to_numpy().any():
            raise FieldError("Confidence interval", "Confidence intervals need counts: whole numbers that are zero "
                                                    "or positive. Set Confidence interval to None for other data.")
    with np.errstate(all="ignore"):
        column_total = data.sum(min_count=1)
        row_total = data.sum(axis=1, min_count=1)
        grand_total = np.nansum(data.to_numpy()) if data.notna().any().any() else np.nan
    _finite(column_total, "Divide by", "Summing the columns", present=data.notna().any())
    _finite(grand_total, "Divide by", "Summing the table", present=data.notna().any().any())
    if mode == DENOMINATORS[1] or mode in DENOMINATORS[3:]:
        _finite(row_total, "Divide by", "Summing the rows", present=data.notna().any(axis=1))
    denominators = {
        "column": pd.DataFrame(np.broadcast_to(column_total.to_numpy(), data.shape), index=data.index,
                               columns=columns),
        "row": pd.DataFrame(np.broadcast_to(row_total.to_numpy()[:, None], data.shape), index=data.index,
                            columns=columns),
        "grand": pd.DataFrame(grand_total, index=data.index, columns=columns, dtype=float),
    }
    wanted = {"Column total": ["column"], "Row total": ["row"], "Grand total": ["grand"],
              **dict.fromkeys(DENOMINATORS[3:], ["column", "row", "grand"])}[mode]

    def labelled(values):
        table = pd.DataFrame(values, index=data.index, columns=columns)
        if titles:
            table.insert(0, titles, frame[titles])
        return table

    tables = {}
    for key in wanted:
        total = denominators[key]
        with np.errstate(all="ignore"):
            fraction = data / total.where(total != 0)
            values = fraction * scale
        _finite(values, "Divide by", "Dividing by the total")
        tables[f"{noun} of {key} total"] = labelled(values)
        if level is not None:
            lower, upper = _intervals(interval, data, total, level)
            tables[f"Lower {level:g}% limit"] = labelled(lower * scale)
            tables[f"Upper {level:g}% limit"] = labelled(upper * scale)
    if mode == COMBINED_TOTALS:
        combined = {}
        for column in columns:
            for key in wanted:
                name = f"{column} · {key} total"
                while name in combined or name == titles:
                    name += " (ratio)"
                combined[name] = tables[f"{noun} of {key} total"][column]
        table = pd.DataFrame(combined, index=data.index)
        if titles:
            table.insert(0, titles, frame[titles])
        tables = {f"{noun} of all totals": table}
    totals = {f"Column total: {name}": value for name, value in column_total.items()}
    totals["Grand total"] = grand_total
    notes = {"Divide by": mode, "Show as": "Percentages" if percent else "Fractions",
             "Confidence interval": interval if level is None else f"{interval}, {level:g}%"}
    if mode == DENOMINATORS[3]:
        notes["Presentation"] = ("Trama returns one table per "
                                 "total with the same values.")
    if "row" in wanted:
        names = frame[titles].astype("string").fillna("").tolist() if titles else [""] * len(frame)
        totals.update({f"Row total: row {row}" + (f" ({name})" if name else ""): value
                       for row, (name, value) in enumerate(zip(names, row_total, strict=True), 1)})
    tables["Totals"] = _report(totals)
    tables["Notes"] = _report(notes)
    return Result(tables)


ANALYSES = {
    "Transform concentrations (X)": transform_concentrations,
    "Remove baseline and column math": remove_baseline,
    "Prune rows": prune_rows,
    "Fraction of total": fraction_of_total,
}


def processing_analysis(method, frame, options):
    return ANALYSES[method](frame, options)
