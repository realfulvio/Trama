"""Reproducible table transformations and multiple testing."""
import re

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .stats import complete, t_test


def _numeric_columns(frame, columns):
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("Select distinct numeric columns.")
    result = {}
    for name in columns:
        values = complete(frame, [name])[name]
        result[name] = values.reindex(frame.index)
    return pd.DataFrame(result)


def normalize(frame, columns, mode):
    data = _numeric_columns(frame, columns)
    if mode == "Percent of range":
        reference = data.min()
        scale = data.max() - reference
        multiplier = 100
    elif mode == "Z score":
        reference = data.mean()
        scale = data.std(ddof=1)
        multiplier = 1
    elif mode in {"Percent of first value", "Subtract first value"}:
        if (data.notna().sum() == 0).any():
            raise ValueError("The selected columns need at least one observation each.")
        reference = pd.Series({name: data[name].dropna().iloc[0] for name in columns})
        if mode == "Subtract first value":
            return data - reference
        return _divide(data, reference) * 100
    else:
        raise ValueError("Select a normalization method.")
    return _divide(data - reference, scale) * multiplier


def _divide(frame, divisor):
    if (divisor == 0).any() or not np.isfinite(divisor).all():
        raise ValueError("Normalization requires a finite, nonzero denominator in each column.")
    return frame / divisor


def transform(frame, columns, operation):
    data = _numeric_columns(frame, columns)
    domain = {"Log10": (data > 0) | data.isna(), "Natural log": (data > 0) | data.isna(),
              "Square root": (data >= 0) | data.isna(), "Reciprocal": (data != 0) | data.isna()}
    if operation in domain and not domain[operation].all().all():
        raise ValueError("The selected data contain values outside the transform domain.")
    functions = {"Log10": np.log10, "Natural log": np.log, "Square root": np.sqrt,
                 "Reciprocal": np.reciprocal, "Absolute value": np.abs, "Square": np.square}
    if operation not in functions:
        raise ValueError("Select a transformation.")
    result = functions[operation](data)
    if np.isinf(result.to_numpy()).any():
        raise ValueError("A transformed value exceeds the numeric range.")
    return result


def row_statistics(frame, columns):
    data = _numeric_columns(frame, columns)
    return pd.DataFrame({"N": data.count(axis=1), "Sum": data.sum(axis=1, min_count=1),
                         "Mean": data.mean(axis=1), "Median": data.median(axis=1),
                         "SD": data.std(axis=1), "SEM": data.sem(axis=1),
                         "Min": data.min(axis=1), "Max": data.max(axis=1)})


def reshape_replicates(frame, columns, row_label=None):
    if not columns or row_label in columns or len(columns) != len(set(columns)):
        raise ValueError("Select distinct replicate columns and a separate row label.")
    data = _numeric_columns(frame, columns)
    label = row_label or "Row"
    if label in {"Series", "Replicate", "Value"}:
        label = f"{label} (row)"
    labels = frame[row_label].to_numpy() if row_label else np.arange(1, len(frame) + 1)
    blocks, seen = [], set()
    for name in columns:
        match = re.fullmatch(r"(.*) \[([1-9]\d*)\]", name)
        series, replicate = (match[1], int(match[2])) if match else (name, 1)
        if (series, replicate) in seen:
            raise ValueError("Multiple columns map to the same series and replicate.")
        seen.add((series, replicate))
        blocks.append(pd.DataFrame({label: labels, "Series": series, "Replicate": replicate,
                                    "Value": data[name].to_numpy()}))
    return pd.concat(blocks, ignore_index=True)


def adjust_p(frame, column, method):
    p = _numeric_columns(frame, [column])[column]
    observed = p.dropna()
    if observed.empty or not observed.between(0, 1).all():
        raise ValueError("Enter at least one p value, with values in [0, 1].")
    adjusted = pd.Series(np.nan, index=p.index)
    adjusted.loc[observed.index] = multipletests(observed, method=method)[1]
    return pd.DataFrame({"p": p, "Adjusted p": adjusted})


def multiple_tests(frame, variables, group, mode, correction, subject=None):
    rows = []
    for name in variables:
        fit = t_test(frame, name, group, mode, subject=subject)
        rows.append({"Variable": name, "Difference": fit["Difference"], "t": fit["t"],
                     "df": fit["df"], "p": fit["p"]})
    table = pd.DataFrame(rows).set_index("Variable")
    table["Adjusted p"] = adjust_p(table, "p", correction)["Adjusted p"]
    return table


def grubbs(frame, column, alpha=.05):
    values = complete(frame, [column])[column]
    n = len(values)
    if n < 3 or not 0 < alpha < 1 or values.std() <= 0:
        raise ValueError("Grubbs' test requires 3 or more varying values and alpha in (0, 1).")
    scores = abs(values - values.mean()) / values.std(ddof=1)
    index = scores.idxmax()
    extreme = scores.loc[index]
    t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
    critical = ((n - 1) / np.sqrt(n)) * t / np.sqrt(n - 2 + t*t)
    return {"N": n, "Candidate row": str(index), "Candidate value": values.loc[index],
            "G": extreme, "Critical G": critical, "Alpha": alpha, "Flagged": bool(extreme > critical)}
