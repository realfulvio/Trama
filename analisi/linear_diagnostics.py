"""Residual diagnostics and pointwise bands for simple linear regression.

The intercept, slope and fixed 95% slope interval come from ``analisi.stats.linear``.
Mean and prediction bands use a two-sided t critical value on n − 2 degrees of
freedom. They are pointwise, not simultaneous.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError
from .reporting import Result, _plot, _report
from .stats import complete, linear
from . import linear_estimates, regression_range

RESIDUAL_DIAGNOSTICS = "Residual diagnostics"
BAND = "Band"
BAND_NONE = "None"
BAND_MEAN = "Confidence (mean)"
BAND_PREDICTION = "Prediction (new observation)"
BANDS = (BAND_NONE, BAND_MEAN, BAND_PREDICTION)
LEVEL = "Confidence level (%)"
GRAPH = "Graph"
GRAPH_FIT = "Fit"
GRAPH_RESIDUALS = "Residuals vs fitted"
GRAPHS = (GRAPH_FIT, GRAPH_RESIDUALS)
LINEAR_OPTIONS = {
    RESIDUAL_DIAGNOSTICS: False,
    BAND: BANDS,
    LEVEL: 95.0,
    GRAPH: GRAPHS,
    **linear_estimates.OPTIONS,
    regression_range.SHOW_OUTSIDE: False,
}

RESIDUALS_SHEET = "Residuals"
MEAN_BAND_SHEET = "Pointwise confidence band"
PREDICTION_BAND_SHEET = "Pointwise prediction band"
NOTE_KEY = "Diagnostics note"
# 1 − h at or below this is treated as a perfect leverage point.
_LEVERAGE_TOLERANCE = 1e-12
_LINE_COLOR = "#bc4040"


@dataclass(frozen=True)
class _Fit:
    summary: dict
    index: pd.Index
    x: np.ndarray
    y: np.ndarray
    fitted: np.ndarray
    residual: np.ndarray
    leverage: np.ndarray
    s2: float
    mean_x: float
    sxx: float

    @property
    def n(self):
        return len(self.x)

    @property
    def df(self):
        return self.n - 2


def linear_confidence_level(options):
    """Return a band level strictly inside (0, 100), or raise FieldError."""
    raw = options.get(LEVEL, 95.0)
    try:
        level = float(raw)
    except (TypeError, ValueError, OverflowError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    return level


def _selection(options):
    band = options.get(BAND, BAND_NONE) or BAND_NONE
    graph = options.get(GRAPH, GRAPH_FIT) or GRAPH_FIT
    if band not in BANDS:
        raise ValueError("Choose a linear regression band.")
    if graph not in GRAPHS:
        raise ValueError("Choose a linear regression graph.")
    diagnostics = bool(options.get(RESIDUAL_DIAGNOSTICS, False))
    # Reject a bad level before fitting or drawing.
    level = linear_confidence_level(options) if band != BAND_NONE or linear_estimates.requested(options) else None
    linear_estimates.check_options(options)
    return band, graph, diagnostics, level


def _fit(frame, x_name, y_name):
    summary = linear(frame, x_name, y_name)
    data = complete(frame, [x_name, y_name])
    x = data[x_name].to_numpy(dtype=float)
    y = data[y_name].to_numpy(dtype=float)
    # Center before Sxx. Σx² − n·mean² cancels when X sits far from zero.
    mean_x = float(np.mean(x))
    center = x - mean_x
    sxx = float(np.dot(center, center))
    slope = float(summary["Slope"])
    # Same OLS line as intercept + slope·x, evaluated without a large offset.
    fitted = float(np.mean(y)) + slope * center
    residual = y - fitted
    sse = float(np.dot(residual, residual))
    s2 = 0.0 if sse <= 0 else sse / (len(x) - 2)
    leverage = 1.0 / len(x) + center * center / sxx
    return _Fit(summary, data.index, x, y, fitted, residual, leverage, s2, mean_x, sxx)


def _undefined(leverage, s2):
    """Studentized residual and Cook's distance need s > 0 and h < 1."""
    if not np.isfinite(s2) or s2 <= 0:
        return np.ones(len(leverage), dtype=bool)
    return (1.0 - leverage) <= _LEVERAGE_TOLERANCE


def residual_table(fit):
    undefined = _undefined(fit.leverage, fit.s2)
    student = np.full(fit.n, np.nan)
    cook = np.full(fit.n, np.nan)
    defined = ~undefined
    if defined.any():
        scale = np.sqrt(fit.s2)
        gap = 1.0 - fit.leverage[defined]
        student[defined] = fit.residual[defined] / (scale * np.sqrt(gap))
        cook[defined] = fit.residual[defined]**2 * fit.leverage[defined] / (2.0 * fit.s2 * gap**2)
    return pd.DataFrame({
        "Source row": fit.index.to_numpy(),
        "X": fit.x,
        "Y": fit.y,
        "Fitted Y": fit.fitted,
        "Residual": fit.residual,
        "Leverage": fit.leverage,
        "Internally studentized residual": student,
        "Cook's distance": cook,
    })


def diagnostics_note(table):
    columns = ["Internally studentized residual", "Cook's distance"]
    if table[columns].isna().to_numpy().any():
        return ("Internally studentized residuals and Cook's distance are blank where the "
                "residual standard deviation is zero or leverage is one.")
    return None


def _critical(level, df):
    critical = float(stats.t.isf((100 - level) / 200, df))
    if not np.isfinite(critical):
        raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    return critical


def band_table(fit, level, band, grid=None):
    """Pointwise limits at the sorted unique observed X values."""
    xs = np.unique(fit.x) if grid is None else grid
    center = xs - fit.mean_x
    extra = 0.0 if band == BAND_MEAN else 1.0
    spread = extra + 1.0 / fit.n + center * center / fit.sxx
    se = np.sqrt(fit.s2) * np.sqrt(spread)
    half = _critical(level, fit.df) * se
    # Intercept + slope·x, evaluated on centered X so a location shift stays harmless.
    fitted = float(np.mean(fit.y)) + float(fit.summary["Slope"]) * center
    sampling = "observed X" if grid is None else "the curve coordinates"
    if band == BAND_MEAN:
        name = MEAN_BAND_SHEET
        wording = (f"Pointwise {level:g}% confidence band for the mean at {sampling} "
                   "(not simultaneous)")
    else:
        name = PREDICTION_BAND_SHEET
        wording = (f"Pointwise {level:g}% prediction band for a new observation at {sampling} "
                   "(not simultaneous)")
    return name, pd.DataFrame({
        "X": xs,
        "Fitted Y": fitted,
        "Lower": fitted - half,
        "Upper": fitted + half,
        "Band": wording,
    })


def _figure(fit, graph, x_name, y_name, limits, curve=None, observations=None):
    if graph == GRAPH_RESIDUALS:
        figure, axes = _plot("Residuals vs fitted", "Fitted Y", "Residual")
        axes.scatter(fit.fitted, fit.residual)
        axes.axhline(0, color="#667085", linewidth=1)
        return figure
    figure, axes = _plot("Linear regression", x_name, y_name)
    x, y = (fit.x, fit.y) if observations is None else observations.T
    axes.scatter(x, y)
    if curve is None:
        domain = np.array([fit.x.min(), fit.x.max()])
        axes.plot(domain, fit.summary["Intercept"] + fit.summary["Slope"] * domain, color=_LINE_COLOR)
    else:
        axes.plot(curve["X"], curve["Predicted"], color=_LINE_COLOR)
    if limits is not None:
        axes.fill_between(limits["X"], limits["Lower"], limits["Upper"],
                          color=_LINE_COLOR, alpha=0.15, linewidth=0, zorder=0)
    return figure


def linear_result(frame, options):
    """Sheets and one figure for Linear regression. The caller's frame is not modified."""
    x_name, y_name = options["X"], options["Y"]
    band, graph, diagnostics, level = _selection(options)
    ranges = regression_range.ranges(options)
    fit = _fit(regression_range.fitting_rows(frame, x_name, ranges), x_name, y_name)
    summary = dict(fit.summary)
    summary.update({field: ranges[field] for field in regression_range.FIT_FIELDS if field in ranges})
    tables = {}
    if diagnostics:
        residuals = residual_table(fit)
        note = diagnostics_note(residuals)
        if note:
            summary[NOTE_KEY] = note
        tables[RESIDUALS_SHEET] = residuals
    limits = None
    grid = regression_range.drawing_grid(fit.x, ranges)
    curve = None
    if grid is not None:
        with np.errstate(over="ignore", invalid="ignore"):
            predicted = fit.y.mean() + fit.summary["Slope"] * (grid - fit.mean_x)
        curve = tables[regression_range.CURVE_SHEET] = regression_range.coordinate_table(grid, predicted, fit.x)
    if band != BAND_NONE:
        sheet, limits = band_table(fit, level, band, grid)
        tables[sheet] = limits
    if linear_estimates.requested(options):
        tables[linear_estimates.SHEET] = linear_estimates.estimate_table(fit, options, level)
    observations = None
    if graph == GRAPH_FIT and options.get(regression_range.SHOW_OUTSIDE) is True and any(
            key in ranges for key in regression_range.FIT_FIELDS):
        # A nonnumeric response outside the fit cannot contribute a plotted point.
        xy = frame[[x_name, y_name]].apply(pd.to_numeric, errors="coerce")
        values = xy.to_numpy(dtype=complex if np.iscomplexobj(xy.to_numpy()) else float, na_value=np.nan)
        valid = np.isfinite(values).all(axis=1) & np.isreal(values).all(axis=1)
        observations = values[valid].real
    figure = _figure(fit, graph, x_name, y_name, limits, curve, observations)
    return Result({"Regression": _report(summary), **tables}, figure)
