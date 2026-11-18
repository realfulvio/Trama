"""Cox regression with the exact conditional treatment of tied event times.

At every event time ``t`` let ``D`` be the ``d`` rows that fail and ``R`` the rows with ``T >= t``, censored rows at
``t`` included. The discrete conditional partial likelihood is::

    sum(eta_D) - log( sum_{S in R, |S| = d} exp(sum(eta_S)) )

with ``eta = X b`` and no intercept. The denominator is the elementary symmetric polynomial ``e_d`` of the weights
``exp(eta_i)`` over ``R``. A time with ``d = 1`` coincides with Breslow and Efron and a time with ``d = |R|``
contributes exactly zero, so it is skipped.

Nothing here enumerates subsets. Rows are added to a state one at a time in order of decreasing time. The risk sets
are nested, so after the last row of a time the state is the risk set of that time. For each size ``r = 1 … d_max``
the state keeps ``log e_r`` together with the mean and the covariance of ``sum(x_S)`` when ``S`` is drawn with
probability proportional to ``exp(sum(eta_S))`` among the subsets of size ``r``. Adding a row is a mixture of the
subsets that leave it out and those that take it (``S_r' = S_r + w S_{r-1}``), which keeps every quantity a convex
combination or a logarithm sum, whatever the range of the weights. The score of a time is the observed
``sum(x_D)`` minus that mean and its information is that covariance, so the Hessian is the information matrix.

The predictors are centred and scaled for the iteration (a translation changes every term of a time by the same
amount and cancels; a scale is a reparametrization) and the coefficients, standard errors and intervals are
returned on the original scale. Newton's method with step halving starts from zero and gives at most 100
iterations. The information must have full rank at every point, the fit must reach a finite maximum with a small
score, and the cancellation event is polled between rows and between iterations.

Launch limits, checked before the state is allocated and never replaced by another estimator: 2 000 complete rows,
8 design columns after coding and a work budget ``sum(|R| d (p + 1)^2)`` of 5 000 000 units over the times with
``1 <= d < |R|``. One evaluation costs at most ``rows × d_max × (p + 1)^2`` units because of the nested state.

Predicted survival, residual sheets, diagnostics and graphs belong to Breslow and Efron and are refused on the
control that asks for them.
"""
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from . import models
from .cox_outputs import AUTOMATIC, DIAGNOSTICS, GRAPH, PREDICT, SCHOENFELD, code_statuses
from .i18n import translate_message, ui
from .monte_carlo import MonteCarloCancelled
from .processing import FieldError
from .reporting import Result
from .stats import complete

METHOD = "Cox regression"
TIES = "Ties"
EXACT = "Exact (conditional)"
PREDICTORS = "Predictors"
MAX_ROWS, MAX_COLUMNS, MAX_UNITS, MAX_ITERATIONS = 2000, 8, 5_000_000, 100
ERROR_PREFIX = "cox.exact.error."
# Outputs built on the Breslow baseline hazard, in the order they are refused.
UNSUPPORTED = (PREDICT, DIAGNOSTICS, SCHOENFELD)
CHECK_EVERY = 64  # rows between two looks at the cancellation event
DECREMENT_TOLERANCE = 1e-10  # Newton decrement, in the scaled coordinates, below which one last step is taken
FINAL_TOLERANCE = 1e-8  # the score after that step, measured the same way
RANK_TOLERANCE = 1e-10  # smallest eigenvalue of the information relative to the largest
VANISHING_INFORMATION = 1e-8  # smallest eigenvalue relative to the largest one at the start (monotone likelihood)
COEFFICIENT_LIMIT = 20.0  # |coefficient| of a standardized predictor beyond which the likelihood has no maximum
STEP_HALVINGS = 30


class CoxExactCancelled(MonteCarloCancelled):
    """The fit was cancelled before a result was published."""


def is_exact(options):
    return isinstance(options, dict) and options.get(TIES) == EXACT


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CoxExactCancelled("The exact Cox fit was cancelled.")


def _caption(value):
    shown = ui(value)
    if shown == value:  # a lower-cased caption such as "event value"
        shown = ui(value[:1].upper() + value[1:]).lower()
    return shown


def translate_error(error):
    """An engine message in the active language; anything unknown is returned unchanged."""
    return translate_message(str(error), ERROR_PREFIX, convert={"field": _caption})


def check_outputs(options):
    """Refuse, on the control that asked for it, any output that Exact does not build. Profiles are only kept."""
    for field in UNSUPPORTED:
        if options.get(field):
            raise FieldError(field, f"Exact (conditional) ties give the coefficient and model sheets only. "
                                    f"Turn off {field} or choose Efron or Breslow.")
    if (options.get(GRAPH) or AUTOMATIC) != AUTOMATIC:
        raise FieldError(GRAPH, f"Exact (conditional) ties draw no graph. Set {GRAPH} to Automatic or choose Efron "
                                "or Breslow.")


# ----- layout and likelihood -------------------------------------------------------------------------------------

@dataclass
class Layout:
    """Rows in decreasing time order and, for each time that adds a term, its events and risk-set size."""
    x: np.ndarray
    reads: dict  # risk-set size |R| -> (positions of the events in x, number of events d)
    last: int  # rows needed: the risk set of the earliest informative time
    depth: int  # largest d among the informative times
    events: int
    tied_times: int


def schedule(time, event):
    """Row order and the informative times (1 <= d < |R|) of rows sorted by decreasing time."""
    time, event = np.asarray(time, dtype=float), np.asarray(event, dtype=bool)
    order = np.argsort(-time, kind="stable")
    time, event = time[order], event[order]
    starts = np.flatnonzero(np.r_[True, time[1:] != time[:-1]])
    stops = np.r_[starts[1:], len(time)]
    reads, tied = {}, 0
    for start, stop in zip(starts, stops, strict=True):
        positions = start + np.flatnonzero(event[start:stop])
        tied += len(positions) >= 2
        if 1 <= len(positions) < stop:
            reads[int(stop)] = (positions, len(positions))
    return order, reads, int(tied)


def work_units(reads, columns):
    """The launch budget sum(|R| d (p + 1)^2) over the informative times."""
    return sum(stop * d for stop, (_, d) in reads.items()) * (columns + 1) ** 2


def layout(x, time, event):
    order, reads, tied = schedule(time, event)
    return Layout(np.asarray(x, dtype=float)[order], reads, max(reads, default=0),
                  max((d for _, d in reads.values()), default=0), int(np.asarray(event, dtype=bool).sum()), tied)


def evaluate(shape, beta, cancel=None):
    """Log likelihood, score and information (minus the Hessian) of the exact conditional likelihood at ``beta``."""
    x, depth = shape.x, shape.depth
    columns = x.shape[1]
    eta = x @ beta
    log_sum = np.full(depth + 1, -np.inf)
    log_sum[0] = 0.0
    mean = np.zeros((depth + 1, columns))
    cov = np.zeros((depth + 1, columns, columns))
    value, score, information = 0.0, np.zeros(columns), np.zeros((columns, columns))
    for row in range(shape.last):
        if row % CHECK_EVERY == 0:
            check_cancel(cancel)
        top = min(depth, row + 1)
        grown, below = slice(1, top + 1), slice(0, top)
        take = eta[row] + log_sum[below]
        updated = np.logaddexp(log_sum[grown], take)
        share = np.exp(take - updated)
        shift = mean[below] + x[row] - mean[grown]
        cov[grown] = ((1 - share)[:, None, None] * cov[grown] + share[:, None, None] * cov[below]
                      + (share * (1 - share))[:, None, None] * shift[:, :, None] * shift[:, None, :])
        mean[grown] += share[:, None] * shift
        log_sum[grown] = updated
        found = shape.reads.get(row + 1)
        if found is not None:
            positions, d = found
            value += eta[positions].sum() - log_sum[d]
            score += x[positions].sum(axis=0) - mean[d]
            information += cov[d]
    return value, score, information


def log_likelihood(x, time, event, beta):
    """The exact conditional log likelihood, score and information for a design and a coefficient vector."""
    return evaluate(layout(x, time, event), np.asarray(beta, dtype=float))


# ----- the fit ---------------------------------------------------------------------------------------------------

@dataclass
class ExactFit:
    beta: np.ndarray
    se: np.ndarray
    log_likelihood: float
    iterations: int
    events: int
    tied_times: int


def _no_maximum():
    return FieldError(PREDICTORS, "The exact conditional likelihood has no finite maximum for these data: a "
                                  "predictor separates the events from the rest of their risk sets. Remove or "
                                  "recode a predictor.")


def _singular():
    return FieldError(PREDICTORS, "The model cannot be estimated: the information matrix is singular. A predictor "
                                  "may be constant within the risk sets of the tied events, or predictors may be "
                                  "collinear. Remove or recode a predictor.")


def _checked(information, start):
    """The information when it has full rank and has not vanished since the start of the iteration.

    ``start`` is the largest eigenvalue at zero coefficients. A likelihood that keeps growing as a coefficient
    runs away (separation) has an information that decays towards zero long before the score does.
    """
    if not np.isfinite(information).all():
        raise _no_maximum()
    values = np.linalg.eigvalsh((information + information.T) / 2)
    if values[-1] <= 0 or values[0] <= RANK_TOLERANCE * values[-1]:
        raise _singular()
    if values[0] <= VANISHING_INFORMATION * start:
        raise _no_maximum()
    return information


def fit_scaled(shape, cancel=None):
    """Newton's method with step halving on the scaled design; returns the coefficients and the final terms."""
    beta = np.zeros(shape.x.shape[1])
    value, score, information = evaluate(shape, beta, cancel)
    start = float(np.linalg.eigvalsh((information + information.T) / 2)[-1]) if np.isfinite(information).all() else 0.0
    for iteration in range(1, MAX_ITERATIONS + 1):
        check_cancel(cancel)
        information = _checked(information, start)
        step = np.linalg.solve(information, score)
        decrement = float(score @ step)
        if not (np.isfinite(step).all() and np.isfinite(value)):
            raise _no_maximum()
        if decrement < DECREMENT_TOLERANCE:
            # One last full step makes the error quadratic in the decrement; keep it if the terms stay finite.
            final = beta + step
            with np.errstate(all="ignore"):
                terms = evaluate(shape, final, cancel)
            if np.isfinite(terms[0]) and np.isfinite(terms[1]).all() and np.isfinite(terms[2]).all():
                beta, (value, score, information) = final, terms
            information = _checked(information, start)
            if float(score @ np.linalg.solve(information, score)) > FINAL_TOLERANCE:
                raise FieldError(PREDICTORS, "The exact fit did not reach a small score. Check for extreme or "
                                             "nearly collinear predictors.")
            return beta, value, information, iteration
        scale = 1.0
        for _ in range(STEP_HALVINGS):
            trial = beta + scale * step
            with np.errstate(all="ignore"):
                terms = evaluate(shape, trial, cancel)
            if (np.isfinite(terms[0]) and np.isfinite(terms[1]).all() and np.isfinite(terms[2]).all()
                    and terms[0] >= value - 1e-12 * (1 + abs(value))):
                break
            scale /= 2
        else:
            raise FieldError(PREDICTORS, "The exact fit did not converge: the likelihood cannot be improved. "
                                         "Check for extreme or nearly collinear predictors.")
        beta, (value, score, information) = trial, terms
        if np.abs(beta).max() > COEFFICIENT_LIMIT:
            raise _no_maximum()
    raise FieldError(PREDICTORS, f"The exact fit did not converge in {MAX_ITERATIONS} iterations. Check for extreme "
                                 "or nearly collinear predictors.")


def fit_exact(design, time, event, cancel=None):
    """Coefficients, standard errors and log likelihood on the original scale of the predictors."""
    design = np.asarray(design, dtype=float)
    centre = design.mean(axis=0)
    scale = design.std(axis=0)
    scale[scale == 0] = 1.0
    shape = layout((design - centre) / scale, time, event)
    if not shape.reads:
        raise _singular()
    beta, value, information, iterations = fit_scaled(shape, cancel)
    covariance = np.linalg.inv(information)
    se = np.sqrt(np.diag(covariance)) / scale
    if not (np.isfinite(se).all() and (se > 0).all()):
        raise _no_maximum()
    return ExactFit(beta / scale, se, float(value), iterations, shape.events, shape.tied_times)


# ----- the analysis ----------------------------------------------------------------------------------------------

def _check_rows(rows):
    if rows > MAX_ROWS:
        raise FieldError(TIES, f"Exact (conditional) ties accept up to {MAX_ROWS} complete rows; this analysis has "
                               f"{rows}. Choose Efron or Breslow, or reduce the data.")


def _check_size(columns, units):
    if columns > MAX_COLUMNS:
        raise FieldError(TIES, f"Exact (conditional) ties accept up to {MAX_COLUMNS} design columns after coding; "
                               f"this model has {columns}. Choose Efron or Breslow, or remove predictors.")
    if units > MAX_UNITS:
        raise FieldError(TIES, f"Exact (conditional) ties accept a work budget of {MAX_UNITS} units per evaluation; "
                               f"this analysis needs {units}. Choose Efron or Breslow, or reduce the data.")


def _inputs(frame, options):
    time, event = options["Time"], options["Event"]
    predictors = list(options["Predictors"])
    categories = list(options.get("Categorical predictors") or [])
    if time == event:
        raise FieldError("Event", "Choose different columns for Time and Event.")
    if event in predictors:
        raise FieldError(PREDICTORS, "The Event column cannot also be a predictor.")
    # Positional rows: Source row is the 1-based position in the worksheet, before missing cells are masked.
    source = frame.reset_index(drop=True)
    source = source.assign(**{event: code_statuses(source, event, options)})
    try:
        if predictors and set(categories).issubset(predictors):
            # The same complete cases as the fit below; the row limit is known before the design is built.
            _check_rows(len(complete(source, [time, event, *[c for c in predictors if c not in categories]],
                                     categories)))
        data, design, references = models._inputs(source, [time, event], predictors, categories, intercept=False)
    except FieldError:
        raise
    except ValueError as error:
        raise FieldError(PREDICTORS, str(error)) from error
    return data, design, references, time, event


def cox_exact_result(frame, options, cancel=None):
    """Coefficient and model sheets of the exact conditional fit, or a FieldError on the control to correct."""
    check_outputs(options)
    data, design, references, time, event = _inputs(frame, options)
    negative = np.flatnonzero((data[time] < 0).to_numpy())
    if len(negative):
        row = int(data.index[negative[0]]) + 1
        raise FieldError("Time", f'Cox regression needs nonnegative times; row {row} of "{time}" is '
                                 f"{data[time].iloc[negative[0]]:g}.")
    events = int(data[event].sum())
    if events < 2:
        raise FieldError("Event", f"The exact fit needs at least two events among the complete rows; "
                                  f"{events} found. Check the event and censor values.")
    times, status = data[time].to_numpy(dtype=float), data[event].to_numpy(dtype=float) == 1
    # Validation precedes every allocation of the engine.
    _check_rows(len(data))
    _check_size(design.shape[1], work_units(schedule(times, status)[1], design.shape[1]))
    check_cancel(cancel)
    result = fit_exact(design.to_numpy(dtype=float), times, status, cancel)
    z = scipy_stats.norm.isf(0.025)
    estimate = result.beta
    ci = np.column_stack([estimate - z * result.se, estimate + z * result.se])
    model = SimpleNamespace(params=estimate, bse=result.se, conf_int=lambda: ci,
                            pvalues=2 * scipy_stats.norm.sf(np.abs(estimate / result.se)),
                            llf=result.log_likelihood, aic=-2 * result.log_likelihood + 2 * len(estimate))
    try:
        with np.errstate(over="ignore"):
            tables = models._report(model, design, references, len(frame), True)
    except ValueError as error:
        raise FieldError(PREDICTORS, str(error)) from error
    extra = pd.DataFrame.from_dict({TIES: EXACT, "Events": result.events, "Tied event times": result.tied_times},
                                   orient="index", columns=["Value"]).astype(object)
    tables["Model"] = pd.concat([tables["Model"].astype(object), extra])
    return Result(tables)
