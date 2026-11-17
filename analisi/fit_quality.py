"""Exact runs test and replicate lack of fit for an existing nonlinear fit.

Both diagnostics read residuals that were already computed. They do not refit,
reorder the source rows, or change the weighting. The runs p is the exact lower
tail given the observed sign counts. The lack-of-fit F is the usual linear-model
reference; for a genuinely nonlinear mean it is only a diagnostic.
"""
import math
from fractions import Fraction

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError

RUNS = "Runs test"
REPLICATES = "Replicate lack of fit"
RESIDUAL_VIEW = "Residuals versus X"
OPTIONS = {RUNS: False, REPLICATES: False, RESIDUAL_VIEW: False}
_UNWEIGHTED = "Unweighted"
_RUN_LIMIT = 2000
_TAIL = "Exact lower tail"

_RUN_ROWS = ("Status", "Reason", "N", "Positive", "Negative", "Zero", "Observed runs",
             "Expected runs", "p", "Tail", "Zero tolerance")
_LOF_ROWS = ("Status", "Reason", "N", "Unique X", "Free parameters", "Residual SS", "Pure error SS",
             "Lack of fit SS", "df pure error", "df lack of fit", "MS pure error", "MS lack of fit",
             "F", "p", "Note")
_LOF_NOTE = ("The F reference is exact for a regular linear model with independent normal "
             "homoscedastic errors. For a nonlinear mean it is an approximate diagnostic. "
             "A p value that is not small does not show that the curve is correct.")


def _say(key, english):
    from .i18n import tr
    translated = tr(key)
    return english if translated == key else translated


def check_options(options):
    """Reject weighted runs or replicate tests before any fit. Residual view stays allowed."""
    weighting = options.get("Weighting", _UNWEIGHTED)
    if weighting in (None, "", _UNWEIGHTED):
        return
    message = _say("analysis.fit.error.unweighted",
                   "This diagnostic requires unweighted fitting.")
    if options.get(RUNS):
        raise FieldError(RUNS, message)
    if options.get(REPLICATES):
        raise FieldError(REPLICATES, message)


def _unavailable(rows, reason, **known):
    values = {name: None for name in rows}
    values.update(Status="Not available", Reason=reason, Tail=_TAIL if "Tail" in rows else None)
    values.update(known)
    if "Note" in rows and not values.get("Note"):
        values["Note"] = _say("analysis.fit.lof.note", _LOF_NOTE)
    return {name: values[name] for name in rows}


def _available(rows, reason, **known):
    values = {name: None for name in rows}
    values.update(Status="Available", Reason=reason, Tail=_TAIL if "Tail" in rows else None)
    values.update(known)
    if "Note" in rows and not values.get("Note"):
        values["Note"] = _say("analysis.fit.lof.note", _LOF_NOTE)
    return {name: values[name] for name in rows}


def _zero_tolerance(observed, predicted):
    if len(observed) == 0:
        return 0.0
    scale = max(float(np.max(np.abs(observed))), float(np.max(np.abs(predicted))))
    if not np.isfinite(scale):
        return None
    return float(64 * np.finfo(float).eps * scale)


def _comb(n, k):
    if k < 0 or n < 0 or k > n:
        return 0
    return math.comb(n, k)


def _lower_tail(positive, negative, runs):
    """P(R <= runs) for the exact two-sign runs distribution."""
    total = _comb(positive + negative, positive)
    if total <= 0:
        return None
    count = 0
    for observed in range(2, runs + 1):
        j = observed // 2
        if observed % 2 == 0:
            count += 2 * _comb(positive - 1, j - 1) * _comb(negative - 1, j - 1)
        else:
            count += (_comb(positive - 1, j) * _comb(negative - 1, j - 1)
                      + _comb(positive - 1, j - 1) * _comb(negative - 1, j))
    return float(Fraction(count, total))


def runs_test(residuals):
    """Lower-tail runs test on raw residuals, in the fit's row order."""
    observed = residuals["Observed"].to_numpy(dtype=float)
    predicted = residuals["Predicted"].to_numpy(dtype=float)
    residual = residuals["Residual"].to_numpy(dtype=float) if "Residual" in residuals else observed - predicted
    x = residuals["X"].to_numpy(dtype=float)
    count = int(len(x))
    tolerance = _zero_tolerance(observed, predicted)
    base = {"N": count, "Zero tolerance": tolerance, "Tail": _TAIL}
    if count == 0 or not np.isfinite(x).all() or tolerance is None or not np.isfinite(residual).all():
        return _unavailable(_RUN_ROWS, _say(
            "analysis.fit.runs.nonfinite",
            "Runs test needs finite X values and finite residuals."), **base)
    if len(np.unique(x)) != count:
        return _unavailable(_RUN_ROWS, _say(
            "analysis.fit.runs.duplicate",
            "X values are repeated. Use the replicate lack-of-fit test instead of the runs test."), **base)
    if count > 1 and not np.all(np.diff(x) > 0):
        return _unavailable(_RUN_ROWS, _say(
            "analysis.fit.runs.order",
            "X values are not strictly increasing. Reorder the source rows and calculate again."), **base)
    if count > _RUN_LIMIT:
        return _unavailable(_RUN_ROWS, _say(
            "analysis.fit.runs.budget",
            "Runs test uses an exact distribution and is available for up to 2000 fitted rows."), **base)
    zeros = np.abs(residual) <= tolerance
    signs = residual[~zeros]
    positive = int(np.sum(signs > 0))
    negative = int(np.sum(signs < 0))
    zero = int(np.sum(zeros))
    changes = int(np.sum(signs[1:] * signs[:-1] < 0)) if len(signs) else 0
    observed_runs = (1 + changes) if len(signs) else None
    used = positive + negative
    expected = (1 + 2 * positive * negative / used) if used else None
    known = {**base, "Positive": positive, "Negative": negative, "Zero": zero,
             "Observed runs": observed_runs, "Expected runs": expected}
    if not (positive > 1 and negative > 1 and used > 5):
        return _unavailable(_RUN_ROWS, _say(
            "analysis.fit.runs.domain",
            "Runs test needs more than five non-zero residuals and at least two of each sign."), **known)
    probability = _lower_tail(positive, negative, observed_runs)
    return _available(_RUN_ROWS, _say(
        "analysis.fit.runs.available",
        "Exact lower tail conditional on the sign counts. This does not prove that the errors are independent."),
        **known, p=probability)


def _ss_tolerance(*terms):
    scale = max((abs(float(term)) for term in terms), default=0.0)
    return float(128 * np.finfo(float).eps * scale)


def replicate_test(residuals, *, p_free):
    """Lack of fit against pure error at exactly equal X values."""
    try:
        free = int(p_free)
    except (TypeError, ValueError):
        free = None
    if isinstance(p_free, bool) or free is None or free < 0 or int(p_free) != p_free:
        return _unavailable(_LOF_ROWS, _say(
            "analysis.fit.lof.parameters",
            "Replicate lack of fit needs a nonnegative whole number of free parameters."))
    observed = residuals["Observed"].to_numpy(dtype=float)
    predicted = residuals["Predicted"].to_numpy(dtype=float)
    residual = residuals["Residual"].to_numpy(dtype=float) if "Residual" in residuals else observed - predicted
    x = residuals["X"].to_numpy(dtype=float)
    count = int(len(x))
    if count == 0 or not np.isfinite(np.concatenate([x, observed, predicted, residual])).all():
        return _unavailable(_LOF_ROWS, _say(
            "analysis.fit.lof.nonfinite",
            "Replicate lack of fit needs finite X values, observations and predictions."),
            N=count, **{"Free parameters": free})
    order = np.argsort(x, kind="mergesort")
    grouped_x = x[order]
    grouped_y = observed[order]
    grouped_fit = predicted[order]
    splits = np.flatnonzero(np.diff(grouped_x)) + 1
    blocks = np.split(np.arange(count), splits)
    pure = 0.0
    distinct = len(blocks)
    for block in blocks:
        if np.ptp(grouped_fit[block]) > _ss_tolerance(np.max(np.abs(grouped_fit[block]))):
            return _unavailable(_LOF_ROWS, _say(
                "analysis.fit.lof.inconsistent",
                "Predictions at the same X do not agree, so lack of fit was not calculated."),
                N=count, **{"Unique X": distinct, "Free parameters": free})
        centered = grouped_y[block] - grouped_y[block].mean()
        pure += float(centered @ centered)
    sse = float(residual @ residual)
    lack = sse - pure
    tau = _ss_tolerance(sse, pure)
    clamped = False
    if -tau <= lack < 0:
        lack = 0.0
        clamped = True
    df_pure = count - distinct
    df_lack = distinct - free
    known = {"N": count, "Unique X": distinct, "Free parameters": free, "Residual SS": sse,
             "Pure error SS": pure, "Lack of fit SS": None if lack < -tau else lack,
             "df pure error": df_pure, "df lack of fit": df_lack}
    if lack < -tau:
        return _unavailable(_LOF_ROWS, _say(
            "analysis.fit.lof.negative",
            "The lack-of-fit sum of squares is negative beyond the numeric tolerance."), **known)
    if not (count > distinct > free):
        if df_pure <= 0:
            reason = _say("analysis.fit.lof.no_replicates",
                          "Replicate lack of fit needs repeated X values.")
        else:
            reason = _say("analysis.fit.lof.no_degrees",
                          "Replicate lack of fit needs more distinct X values than free parameters.")
        return _unavailable(_LOF_ROWS, reason, **known)
    if pure <= 0:
        if lack <= 0:
            reason = _say("analysis.fit.lof.zero_both",
                          "Pure error is zero and lack of fit is zero, so F and p are not available.")
        else:
            reason = _say("analysis.fit.lof.zero_pure",
                          "Pure error is zero while lack of fit is positive, so F and p are not available.")
        return _unavailable(_LOF_ROWS, reason, **known,
                            **{"MS pure error": None, "MS lack of fit": None})
    ms_pure = pure / df_pure
    ms_lack = lack / df_lack
    ratio = ms_lack / ms_pure
    probability = float(stats.f.sf(ratio, df_lack, df_pure))
    reason = _say("analysis.fit.lof.available",
                  "Comparison of lack of fit with the variation among replicates.")
    if clamped:
        reason = _say("analysis.fit.lof.clamped",
                      "A tiny negative lack-of-fit sum of squares was set to zero.") + " " + reason
    return _available(_LOF_ROWS, reason, **known, **{
        "MS pure error": ms_pure, "MS lack of fit": ms_lack, "F": ratio, "p": probability})


def _close(left, right):
    return abs(left - right) <= _ss_tolerance(left, right)


def fit_quality(fit, *, runs, replicates):
    """Adapt one finished Fit. Both flags false returns nothing and does not read the optimizer."""
    if not runs and not replicates:
        return {}
    residuals = fit.residuals
    diagnostics = fit.diagnostics
    count = int(diagnostics["N"])
    free = count - int(diagnostics["df"])
    result = {}
    if runs:
        result[RUNS] = runs_test(residuals)
    if replicates:
        sse = float(np.square(residuals["Residual"].to_numpy(dtype=float)).sum())
        if count != len(residuals) or free < 0 or not _close(sse, float(fit.residual_ss)):
            result[REPLICATES] = _unavailable(_LOF_ROWS, _say(
                "analysis.fit.lof.residuals",
                "The stored residuals do not agree with the fit, so lack of fit was not calculated."),
                N=count, **{"Free parameters": free if free >= 0 else None})
        else:
            result[REPLICATES] = replicate_test(residuals, p_free=free)
    return result
