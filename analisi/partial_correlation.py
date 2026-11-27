"""Partial correlation of numeric variables given one or more covariates.

Pearson correlates residuals from an ordinary fit on the covariates, with an intercept.
Spearman ranks every selected column on the rows that enter the fit, then uses the same
residuals. One decomposition of the covariate design serves every variable. The correlation
matrix is never inverted.
"""
from itertools import combinations
from math import sqrt

from matplotlib.figure import Figure
from matplotlib import colormaps
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .point_style import attach_points, positions_of
from .processing import _column
from .reporting import Result, _plot, _report
from .worksheet_row_identity import ROW_SPANS


METHOD = "Partial correlation"
VARIABLES = "Variables"
COVARIATES = "Covariates"
CORRELATION = "Method"
HOLM = "Holm adjustment"
SCATTER = "Residual scatter"
METHODS = ("Pearson", "Spearman")
MIN_VARIABLES, MAX_VARIABLES = 2, 12
MIN_COVARIATES, MAX_COVARIATES = 1, 8
OPTIONS = {CORRELATION: METHODS, HOLM: False, SCATTER: False}
CANCELLED = "The partial correlation was cancelled."

PAIRS = "Pairs"
COEFFICIENTS = "Coefficients"
SAMPLE = "Sample"

_ERRORS = {
    "variables": f"Choose {MIN_VARIABLES} to {MAX_VARIABLES} distinct variables.",
    "covariates": f"Choose {MIN_COVARIATES} to {MAX_COVARIATES} distinct covariates.",
    "overlap": "{name} cannot be both a variable and a covariate.",
    "missing": "Choose a column for {field}.",
    "numeric": 'Column "{name}" is not numeric.',
    "flag": "Choose yes or no for {field}.",
    "method": "Choose Pearson or Spearman.",
    "constant": "Covariate {name} is constant on the rows used by this correlation.",
    "redundant": "Covariate {name} repeats {other}.",
    "rank": "The covariates do not have full rank on the rows used by this correlation.",
    "rows": "N − k − 2 must be positive. This selection leaves {n} complete rows and {k} covariates.",
    "scatter": "The residual scatter needs exactly two variables.",
}
_ZERO = "The residual variance of {names} is zero, so this pair is not estimable."
_FISHER_N = "The Fisher interval needs N − k − 3 to be positive."
_PERFECT = "The absolute correlation is 1, so the Fisher interval is not estimable."
_EXACT = 1.0 - 1e-12


class PartialCorrelationCancelled(Exception):
    """The worker asked the partial-correlation fit to stop."""


def check_options(frame, options):
    """Recipe checks that do not fit the model. The fit stays on the worker."""
    variables = _names(options, VARIABLES, MIN_VARIABLES, MAX_VARIABLES, _ERRORS["variables"])
    covariates = _names(options, COVARIATES, MIN_COVARIATES, MAX_COVARIATES, _ERRORS["covariates"])
    shared = [name for name in covariates if name in set(variables)]
    if shared:
        raise FieldError(COVARIATES, _ERRORS["overlap"].format(name=shared[0]))
    method = options.get(CORRELATION, METHODS[0])
    if method not in METHODS:
        raise FieldError(CORRELATION, _ERRORS["method"])
    for field in (HOLM, SCATTER):
        if not isinstance(options.get(field, False), bool):
            raise FieldError(field, _ERRORS["flag"].format(field=field))
    if options.get(SCATTER, False) and len(variables) != 2:
        raise FieldError(SCATTER, _ERRORS["scatter"])
    for name in variables:
        _numeric(frame, name, VARIABLES)
    for name in covariates:
        _numeric(frame, name, COVARIATES)
    return variables, covariates, method


def analyse(frame, options, cancel=None):
    variables, covariates, method = check_options(frame, options)
    if _stopped(cancel):
        raise PartialCorrelationCancelled(CANCELLED)
    values = np.column_stack([_numeric(frame, name, VARIABLES).to_numpy(float) for name in variables]
                             + [_numeric(frame, name, COVARIATES).to_numpy(float) for name in covariates])
    excluded_rows = _excluded_rows(frame, [*variables, *covariates])
    finite = np.isfinite(values).all(axis=1)
    used = [index for index in range(len(frame)) if index not in excluded_rows and finite[index]]
    excluded_count = sum(1 for index in range(len(frame)) if index in excluded_rows)
    incomplete_count = len(frame) - excluded_count - len(used)
    matrix = values[used]
    if method == "Spearman" and len(used):
        matrix = stats.rankdata(matrix, axis=0, method="average")
    k = len(covariates)
    n = len(used)
    if _stopped(cancel):
        raise PartialCorrelationCancelled(CANCELLED)
    _independent(matrix, covariates)
    df = n - k - 2
    if df <= 0:
        raise FieldError(COVARIATES, _ERRORS["rows"].format(n=n, k=k))
    design = np.column_stack([np.ones(n), matrix[:, len(variables):]])
    q, factor = np.linalg.qr(design, mode="reduced")
    diagonal = np.abs(np.diag(factor))
    tolerance = 1e-8 * (float(diagonal.max()) if diagonal.size else 1.0)
    if int(np.sum(diagonal > tolerance)) < design.shape[1]:
        raise FieldError(COVARIATES, _ERRORS["rank"])
    residuals = []
    dead = []
    for index, name in enumerate(variables):
        if _stopped(cancel):
            raise PartialCorrelationCancelled(CANCELLED)
        column = matrix[:, index]
        residual = column - q @ (q.T @ column)
        scale = float(np.std(column, ddof=1))
        spread = float(np.sqrt(np.dot(residual, residual) / max(n - 1, 1)))
        residuals.append(residual)
        if spread <= 1e-8 * max(scale, 1.0):
            dead.append(name)
    dead_names = set(dead)
    coefficients = np.full((len(variables), len(variables)), np.nan)
    for index, name in enumerate(variables):
        if name not in dead_names:
            coefficients[index, index] = 1.0
    records = []
    probabilities = []
    for left, right in combinations(range(len(variables)), 2):
        pair = [variables[left], variables[right]]
        involved = [name for name in pair if name in dead_names]
        if involved:
            coefficient = probability = low = high = np.nan
            note = _ZERO.format(names=" and ".join(involved))
        else:
            coefficient = _correlate(residuals[left], residuals[right])
            if abs(coefficient) >= _EXACT:
                coefficient = float(np.copysign(1.0, coefficient))
                probability = 0.0
                low = high = np.nan
                note = "" if method == "Spearman" else _PERFECT
            else:
                t = coefficient * sqrt(df / (1.0 - coefficient * coefficient))
                probability = float(2.0 * stats.t.sf(abs(t), df))
                low, high, note = _interval(coefficient, n, k, method)
        probabilities.append(probability)
        records.append({"Variable 1": pair[0], "Variable 2": pair[1], "Method": method, "N": n,
                        "Covariates": ", ".join(covariates), "r": coefficient, "df": df, "p": probability,
                        "CI low": low, "CI high": high, "Note": note})
    if options.get(HOLM, False):
        for record, adjusted in zip(records, _holm(probabilities), strict=True):
            record["Holm p"] = adjusted
    pairs = pd.DataFrame(records)
    if options.get(HOLM, False):
        pairs = pairs[["Variable 1", "Variable 2", "Method", "N", "Covariates", "r", "df", "p",
                       "CI low", "CI high", "Holm p", "Note"]]
    for row, (left, right) in enumerate(combinations(range(len(variables)), 2)):
        coefficients[left, right] = coefficients[right, left] = pairs["r"].iloc[row]
    tables = {
        COEFFICIENTS: pd.DataFrame(coefficients, index=list(variables), columns=list(variables)),
        PAIRS: pairs,
        SAMPLE: _report(_sample(method, n, k, excluded_count, incomplete_count, covariates, dead)),
    }
    figure = _figure(frame, variables, coefficients, residuals, used, options.get(SCATTER, False), method)
    return Result(tables, figure)


def _names(options, field, low, high, message):
    names = options.get(field, ())
    if (not isinstance(names, (list, tuple)) or not low <= len(names) <= high
            or any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names)):
        raise FieldError(field, message)
    return list(names)


def _numeric(frame, name, field):
    if name not in frame.columns:
        raise FieldError(field, _ERRORS["missing"].format(field=field))
    try:
        return _column(frame, name, field)
    except FieldError:
        raise FieldError(field, _ERRORS["numeric"].format(name=name)) from None


def _excluded_rows(frame, names):
    selected = set(names)
    return {int(row) for row, column in frame.attrs.get("excluded_cells") or () if column in selected}


def _independent(matrix, covariates):
    if not len(matrix):
        return
    controls = matrix[:, -len(covariates):]
    for index, name in enumerate(covariates):
        column = controls[:, index]
        if float(np.ptp(column)) == 0.0:
            raise FieldError(COVARIATES, _ERRORS["constant"].format(name=name))
        for earlier in range(index):
            if np.array_equal(column, controls[:, earlier]):
                raise FieldError(COVARIATES, _ERRORS["redundant"].format(name=name, other=covariates[earlier]))


def _correlate(left, right):
    left = left - left.mean()
    right = right - right.mean()
    scale = sqrt(float(np.dot(left, left) * np.dot(right, right)))
    return float(np.dot(left, right) / scale)


def _interval(coefficient, n, k, method):
    if method == "Spearman" or n - k - 3 <= 0:
        return np.nan, np.nan, "" if method == "Spearman" else _FISHER_N
    delta = float(stats.norm.ppf(0.975) / sqrt(n - k - 3))
    centre = float(np.arctanh(coefficient))
    low, high = np.tanh(centre + np.array([-delta, delta]))
    return float(low), float(high), ""


def _holm(probabilities):
    usable = [(index, float(p)) for index, p in enumerate(probabilities) if np.isfinite(p)]
    order = sorted(usable, key=lambda item: (item[1], item[0]))
    adjusted = [np.nan] * len(probabilities)
    previous = 0.0
    count = len(order)
    for step, (index, probability) in enumerate(order):
        previous = min(1.0, max(previous, probability * (count - step)))
        adjusted[index] = previous
    return adjusted


def _sample(method, n, k, excluded, incomplete, covariates, dead):
    fisher_df = n - k - 3
    if method == "Spearman":
        interval = "Not estimated"
        probability = "Two-sided t on N − k − 2 degrees of freedom; approximate"
    elif fisher_df <= 0:
        interval = "Not estimable"
        probability = "Two-sided t on N − k − 2 degrees of freedom"
    else:
        interval = "Fisher z, standard error 1/√(N − k − 3)"
        probability = "Two-sided t on N − k − 2 degrees of freedom"
    report = {"Method": method, "N": n, "Excluded rows": excluded, "Incomplete rows": incomplete,
              "df": n - k - 2, "Covariates": ", ".join(covariates), "p values": probability,
              "Confidence interval": interval}
    if dead:
        report["Not estimable"] = ", ".join(dead)
    return report


def _figure(frame, variables, coefficients, residuals, used, scatter, method):
    title = "Partial correlation"
    if scatter and len(variables) == 2:
        figure = Figure(figsize=(10, 5), dpi=100, layout="constrained")
        heat = figure.add_subplot(1, 2, 1)
        drawn = figure.add_subplot(1, 2, 2)
        _heat(heat, figure, coefficients, variables)
        _scatter(drawn, frame, variables, residuals, used, method)
        heat.set_title(title)
        return figure
    figure, heat = _plot(title)
    _heat(heat, figure, coefficients, variables)
    return figure


def _heat(axes, figure, coefficients, names):
    image = axes.imshow(coefficients, cmap=colormaps["RdBu_r"].with_extremes(bad="#e2e8ef"), vmin=-1.0, vmax=1.0)
    axes.set_xticks(range(len(names)), names, rotation=40, ha="right")
    axes.set_yticks(range(len(names)), names)
    axes._tramastat_categorical_axes = ("x", "y")
    axes.tick_params(length=0)
    colorbar = make_axes_locatable(axes).append_axes("right", size="4%", pad=0.24)
    figure.colorbar(image, cax=colorbar, label="r")
    if len(names) <= 10:
        for (row, column), value in np.ndenumerate(coefficients):
            label = f"{value:.2f}" if np.isfinite(value) else "—"
            axes.text(column, row, label, va="center", ha="center",
                      color="white" if np.isfinite(value) and abs(value) >= 0.55 else "#1c3345")


def _scatter(axes, frame, variables, residuals, used, method):
    axes.set_title("Residual scatter")
    axes.set_xlabel(f"Residual of {variables[0]}")
    axes.set_ylabel(f"Residual of {variables[1]}")
    axes.spines[["right", "top"]].set_visible(False)
    artist = axes.scatter(residuals[0], residuals[1])
    positions = positions_of(frame, frame.index[used])
    if positions is not None:
        attach_points(artist, positions, residuals[0], residuals[1], tuple(variables), len(frame),
                      row_spans=frame.attrs.get(ROW_SPANS), data=frame)
    if method == "Spearman":
        axes.set_xlabel(f"Rank residual of {variables[0]}")
        axes.set_ylabel(f"Rank residual of {variables[1]}")


def _stopped(cancel):
    if cancel is None:
        return False
    is_set = getattr(cancel, "is_set", None)
    return bool(is_set() if is_set is not None else cancel())
