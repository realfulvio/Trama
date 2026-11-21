"""Scaled Schoenfeld residuals and Cox–Snell diagnostics for the Cox regression dialog.

Both outputs are built on the one fit of ``cox_outputs.fit_cox``: the scaled residuals use its covariance matrix,
the Cox–Snell residuals use the Breslow baseline that Trama draws for every ties method. They are graphical
checks. Nothing here tests the proportional hazards assumption or reads the graph for the analyst.

The functions take the fit and the arrays computed by ``cox_outputs`` as arguments, so this module does not import
it. A value that cannot be calculated raises a ``FieldError`` that names the control to correct, and no result is
returned: a missing value is never replaced by zero.
"""
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from .processing import FieldError
from .reporting import _plot

SCALED, COX_SNELL = "Scaled Schoenfeld residuals", "Cox-Snell diagnostics"
X_AXIS = "Schoenfeld x axis"
EVENT_TIME, SOURCE_ROW = "Event time", "Source row"
X_AXES = (EVENT_TIME, SOURCE_ROW)
SCALED_GRAPH, SNELL_GRAPH = "Scaled Schoenfeld", "Cox-Snell plot"
SCALED_SHEET, SNELL_SHEET, SNELL_HAZARD_SHEET = (
    "Scaled Schoenfeld residuals", "Cox-Snell residuals", "Cox-Snell cumulative hazard")
SNELL_COLUMN = "Cox-Snell residual"
HAZARD_COLUMNS = ("Residual", "At risk", "Events", "Censored", "Cumulative hazard")
GUIDE_COLOR = "#7f8c99"

# English texts of the errors raised here. i18n registers the Italian version under "cox.error.<key>".
MESSAGES = {
    "scaled_covariance": "The covariance matrix of the coefficients is not finite or has a non-positive variance, "
                         "so the scaled Schoenfeld residuals cannot be calculated. Check the predictors for "
                         "collinearity, complete separation or extreme scales.",
    "scaled_values": "The scaled Schoenfeld residuals are not finite for these data. Center or rescale the "
                     "continuous predictors.",
    "scaled_shape": "The Schoenfeld residuals do not match the coefficient covariance of the fit.",
    "snell_values": "A Cox–Snell residual is not finite, or is too small to be represented, for these data. "
                    "Center or rescale the continuous predictors.",
    "x_axis": "Choose Event time or Source row for the Schoenfeld x axis.",
}


def x_axis(options):
    """The horizontal axis of the scaled Schoenfeld graph: the event time unless the recipe says otherwise."""
    choice = options.get(X_AXIS) or EVENT_TIME
    if choice not in X_AXES:
        raise FieldError(X_AXIS, MESSAGES["x_axis"])
    return choice


def scaled_schoenfeld(fit, raw):
    """m · (rᵢᵀ V) for every event row, with rᵢ the raw residual of ``cox_outputs.schoenfeld``.

    m is the number of events of the fit and V is the covariance of the coefficients that the single fit
    returned (naive, from the information of the chosen ties method). The residuals stay centered on zero:
    β is not added. Rows, order, Source row and Time are those of the raw sheet.
    """
    names = list(fit.design.columns)
    covariance = None if fit.cov is None else np.asarray(fit.cov, dtype=float)
    if (covariance is None or covariance.shape != (len(names), len(names)) or not np.isfinite(covariance).all()
            or not (np.diag(covariance) > 0).all()):
        raise FieldError(SCALED, MESSAGES["scaled_covariance"])
    residuals = raw[names].to_numpy(dtype=float)
    events = int(np.count_nonzero(fit.event))
    if residuals.shape != (events, len(names)) or not np.isfinite(residuals).all():
        raise FieldError(SCALED, MESSAGES["scaled_shape"])
    with np.errstate(all="ignore"):
        scaled = events * (residuals @ covariance)
    if scaled.shape != residuals.shape or not np.isfinite(scaled).all():
        raise FieldError(SCALED, MESSAGES["scaled_values"])
    sheet = raw[["Source row", "Time"]].copy()
    for position, name in enumerate(names):
        sheet[name] = scaled[:, position]
    return sheet


def stable_expected_events(fit):
    """H₀(tᵢ) exp(ηᵢ) for every row, formed on the log scale and never through H₀ itself.

    The Breslow increments are log d_j − log Σ_{T_k ≥ t_j} exp(η_k), accumulated with ``logaddexp``. A baseline
    that underflows and a hazard ratio that overflows, as with predictors far from zero, meet in one exponent, so
    the product stays representable whenever its value is. This is what ``cox_outputs.expected_events`` computes,
    reached by a path that does not need the baseline sheet to be representable.
    """
    eta, time, event = fit.eta, fit.time, fit.event
    times, deaths = np.unique(time[event], return_counts=True)
    order = np.argsort(-time, kind="stable")
    log_risk = np.logaddexp.accumulate(eta[order])[np.searchsorted(-time[order], -times, side="right") - 1]
    log_hazard = np.logaddexp.accumulate(np.log(deaths) - log_risk)
    jumps = np.searchsorted(times, time, side="right")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        return np.exp(np.r_[-np.inf, log_hazard][jumps] + eta)


def cox_snell_residuals(fit, expected):
    """One row per observation used in the fit: rᵢ = H₀(tᵢ) exp(xᵢ β), the expected events of the residual sheet.

    A time before the first event has a real zero. Anything not finite, or a row at or after the first event whose
    product underflows to zero, is an error: the table never carries a silent zero.
    """
    residual = np.asarray(expected, dtype=float)
    if (residual.shape != fit.time.shape or not np.isfinite(residual).all() or (residual < 0).any()
            or ((residual == 0) & (fit.time >= fit.time[fit.event].min())).any()):
        raise FieldError(COX_SNELL, MESSAGES["snell_values"])
    return pd.DataFrame({"Source row": fit.data.index.to_numpy() + 1, "Time": fit.time,
                         "Event": fit.event.astype(int), SNELL_COLUMN: residual})


def cox_snell_hazard(residuals):
    """Nelson–Aalen estimate of the cumulative hazard of the Cox–Snell residuals, one row per distinct residual.

    At risk counts the residuals ≥ u, Events and Censored split the subjects whose residual equals u, and the
    jump Events / At risk is added to the previous total. Censoring-only values appear with no jump. A sorted
    scan with counts per distinct value: no comparison against every row for every u.
    """
    residual = residuals[SNELL_COLUMN].to_numpy(dtype=float)
    event = residuals["Event"].to_numpy(dtype=float)
    values, inverse, counts = np.unique(residual, return_inverse=True, return_counts=True)
    events = np.rint(np.bincount(inverse, weights=event, minlength=len(values))).astype(int)
    at_risk = len(residual) - np.cumsum(counts) + counts
    hazard = np.cumsum(events / at_risk)
    if not np.isfinite(hazard).all():
        raise FieldError(COX_SNELL, MESSAGES["snell_values"])
    return pd.DataFrame({"Residual": values, "At risk": at_risk.astype(int), "Events": events,
                         "Censored": (counts - events).astype(int), "Cumulative hazard": hazard},
                        columns=list(HAZARD_COLUMNS))


def scaled_figure(sheet, term, axis, time_name):
    """Points only: the scaled residuals of one term against the event time or the source row, with y = 0 marked."""
    by_row = axis == SOURCE_ROW
    figure, axes = _plot(f"Scaled Schoenfeld residuals: {term}", SOURCE_ROW if by_row else time_name,
                         f"Scaled Schoenfeld residual ({term})")
    axes.axhline(0, color=GUIDE_COLOR, linewidth=1, zorder=1)
    axes.scatter(sheet[SOURCE_ROW if by_row else "Time"], sheet[term], zorder=2)
    if by_row:
        axes.xaxis.set_major_locator(MaxNLocator(integer=True))
    return figure


def cox_snell_figure(hazard):
    """Estimated cumulative hazard of the residuals on a linear scale, as a post step curve from (0, 0), with y = x."""
    figure, axes = _plot("Cox–Snell residuals", "Cox–Snell residual", "Estimated cumulative hazard of the residuals")
    values, cumulative = hazard["Residual"].to_numpy(), hazard["Cumulative hazard"].to_numpy()
    start = not (values[0] == 0 and cumulative[0] == 0)
    axes.step(np.r_[[0.] * start, values], np.r_[[0.] * start, cumulative], where="post",
              label="Cumulative hazard of the residuals")
    last = float(values[-1])
    axes.plot([0., last], [0., last], linestyle="--", color=GUIDE_COLOR, label="y = x")
    axes.set_xlim(left=0)
    axes.set_ylim(bottom=0)
    axes.legend(frameon=False)
    return figure
