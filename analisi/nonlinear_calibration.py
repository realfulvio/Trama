"""Calibration for one-phase and four- or five-parameter logistic standard curves.

A nonlinear result is a point estimate inside the observed standard range.
Out-of-range and non-identifiable responses are reported without an imputed
concentration. This is not a prediction interval for a new measurement.

Four-parameter models are the catalog stimulation and inhibition equations.
Concentration X uses Bottom + (Top − Bottom) / (1 + (Mid / x)^Hill), with the
catalog function's own limit at x = 0. log10 X is already logarithmic: the
interpolated value stays in that entered unit and is not exponentiated.

Direction "Y from X" predicts responses at unknown X for Linear, One-phase
decay and the 4PL and 5PL curves, with an optional pointwise band
for the mean response or for the mean of k new observations. Queries outside the
closed X range of the standards are reported as Outside calibration without a
value.

Direction "X from Y" can report inverse intervals for the Linear curve,
One-phase decay and the 4PL and 5PL models. One-phase association stays a
point estimate. A nonlinear interval is the closed set of X in the
observed range whose pointwise asymptotic band contains the query response.
The same fit supplies the curve, the covariance and the residual variance.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd
from scipy import special, stats
from scipy.optimize import brentq

from .curve_models import MODELS
from .data import decimal_comma
from .exploration import interpolate_linear
from . import nonlinear_inverse
from . import pade_calibration as pade
from .nonlinear_inverse import InverseBudgetError
from .processing import FieldError
from .reporting import _report
from .stats import complete, linear, nonlinear


CURVES = ("Linear", "Nonlinear")
ONE_PHASE_MODELS = ("One-phase decay", "One-phase association")
CONCENTRATION_4PL = ("Stimulation (variable slope)", "Inhibition (variable slope)")
LOG10_4PL = ("Stimulation (variable slope, log10 X)", "Inhibition (variable slope, log10 X)")
CONCENTRATION_5PL = nonlinear_inverse.CONCENTRATION_5PL
LOG10_5PL = nonlinear_inverse.LOG10_5PL
CONCENTRATION_MODELS = (*CONCENTRATION_4PL, CONCENTRATION_5PL)
_FOUR_PL_MODELS = (*CONCENTRATION_4PL, *LOG10_4PL)
_FIVE_PL_MODELS = nonlinear_inverse.FIVE_PL
_SIGMOID_MODELS = (*_FOUR_PL_MODELS, *_FIVE_PL_MODELS)
PADE_MODEL = pade.MODEL
INVERSE_MODELS = (*ONE_PHASE_MODELS, *_SIGMOID_MODELS, PADE_MODEL)
INVERSE_INTERVAL_MODELS = nonlinear_inverse.MODELS
MAX_INVERSE_QUERIES = 256
INTERVAL_NOTE = ("Pointwise asymptotic approximation from the fitted curve and its covariance. "
                 "Not a likelihood profile, a simultaneous band or a bootstrap, and not an extrapolation.")
OUTSIDE_REASON = "The response is outside the range of the fitted curve."
IDENTIFIABLE_REASON = "The response does not identify one concentration on this curve."
EXACT_REASON = "The fit is exact, so an interval is not defined."
BOUND_REASON = "A parameter is on a bound, so the covariance is not a local approximation."
COVARIANCE_REASON = "The parameter covariance cannot support an interval."
DF_REASON = "Residual degrees of freedom are not positive."
EMPTY_REASON = "The response is inside the curve's range but outside every pointwise interval."
IN_RANGE = "In range"
OUT_OF_RANGE = "Out of range"
NOT_IDENTIFIABLE = "Not identifiable"
POWER_COLUMN = "10^X"
# Catalog ids look like "Inhibition (variable slope, log10 X)", with the unit inside the parentheses.
_LOG10_MARK = ", log10 X)"


# Y from X. A recipe without Direction keeps the 0.52.0 inverse calibration.
DIRECTION = "Direction"
DIRECTIONS = ("X from Y", "Y from X")
UNKNOWN_X = "Unknown X"
UNKNOWN_RESPONSES = "Unknown responses"
MISSING_X_ONLY = "Only rows without X"
PADE_DRAWING = "Imported Padé drawing range"
MAX_PADE_DRAWING_POINTS = 2000
FORWARD_INTERVAL_MODELS = ("One-phase decay", *_SIGMOID_MODELS)
FORWARD_MODELS = (*FORWARD_INTERVAL_MODELS, PADE_MODEL)
_FORWARD_MODEL_ERROR = "Y from X supports the Linear curve, One-phase decay, 4PL, 5PL and Padé (1,1)."
UNCERTAINTY = "Uncertainty"
UNCERTAINTIES = ("None", "Mean response", "Prediction")
LEVEL = "Confidence level (%)"
DEFAULT_LEVEL = 95.0
OUTSIDE_CALIBRATION = "Outside calibration"
UNCERTAINTY_UNAVAILABLE = "Uncertainty unavailable"
PREDICTIONS = "Calibrated predictions"
BANDS = "Calibration bands"
BAND_POINTS = 200
# A One-phase decay Rate within this fraction of one decay over the X range sits on its lower bound (0).
RATE_BOUND = 1e-8
# A 4PL parameter this close to a finite catalog bound, relative to the larger of the two, sits on it.
PARAMETER_BOUND = 1e-8
# Optional column of replicate counts k for Prediction: the band is for the mean of k new observations.
COUNT = "Replicate count column"
REPLICATES = "Replicate count"
# Counts are exact integers in a float64 column.
MAX_COUNT = 2**53
# X from Y on the Linear curve. Interval columns follow the 0.53.0 columns of Interpolated values.
INTERPOLATED = "Interpolated values"
COMPONENTS = "Inverse interval components"
INTERVAL_STATUS = "Interval status"
COMPLETE = "Complete"
CLIPPED = {(True, False): "Clipped low", (False, True): "Clipped high", (True, True): "Clipped both",
           (False, False): COMPLETE}
DISCONNECTED = "Disconnected"


@dataclass(frozen=True)
class StandardCurve:
    tables: dict[str, pd.DataFrame]
    curve: np.ndarray | None = None
    linear: dict | None = None
    model: str | None = None
    forward: bool = False
    uncertainty: str = "None"
    level: float | None = None
    # True when a replicate count column set k per query. The drawn band stays at k = 1.
    replicates: bool = False


def interpolate_standard_curve(frame, x, y, query, curve="Linear", model=None, uncertainty="None", level=None,
                               count=None, *, missing_x_only=False, saved_drawing=None):
    """Interpolate unknown responses, or keep the existing linear calibration.

    Mean response or Prediction adds inverse intervals for the Linear curve and for One-phase decay
    and the 4PL and 5PL models. One-phase association provides point estimates.
    """
    if curve not in CURVES:
        raise ValueError("Select a linear or nonlinear standard curve.")
    uncertainty = uncertainty or UNCERTAINTIES[0]
    if uncertainty not in UNCERTAINTIES:
        raise FieldError(UNCERTAINTY, "Select None, Mean response or Prediction.")
    _check_inverse_uncertainty(curve, model, uncertainty)
    if curve == "Linear":
        fit, estimates = interpolate_linear(frame, x, y, query)
        tables = {INTERPOLATED: estimates, "Linear calibration": _report(fit)}
        if uncertainty == UNCERTAINTIES[0]:
            return StandardCurve(tables, linear=fit)
        level = _checked_level(level)
        counts = None
        if uncertainty == UNCERTAINTIES[2] and count:
            counts = replicate_counts(frame, count, query, (x, y))
        intervals, components = _inverse_linear(frame, x, y, fit, estimates, uncertainty, level, counts)
        tables[INTERPOLATED] = intervals
        if components is not None:
            tables = {INTERPOLATED: intervals, COMPONENTS: components, "Linear calibration": tables["Linear calibration"]}
        return StandardCurve(tables, linear=fit, uncertainty=uncertainty, level=level, replicates=counts is not None)
    if model is None:
        model = INVERSE_MODELS[0]
    if model not in INVERSE_MODELS:
        raise ValueError("Select a supported calibration model.")
    if model == PADE_MODEL:
        return _pade_inverse_curve(frame, x, y, query, missing_x_only=missing_x_only, saved_drawing=saved_drawing)
    checked = None
    counts = None
    if uncertainty != UNCERTAINTIES[0]:
        checked = _checked_level(level)
        if count:
            counts = replicate_counts(frame, count, query, (x, y))
        _check_inverse_queries(frame, query)
    return _nonlinear_curve(frame, x, y, query, model, uncertainty, checked, counts)


def calibration_choice_error(frame, x, y, curve, model):
    """Point the dialog at the choice that blocks a nonlinear fit, when one is known."""
    if curve != "Nonlinear":
        return
    if model == PADE_MODEL:
        pade.validate_standards(frame, x, y)
        return
    if model not in MODELS:
        return
    spec = MODELS[model]
    try:
        standards = complete(frame, [x, y])
    except ValueError as error:
        raise FieldError("X", str(error)) from error
    if standards.empty:
        raise FieldError("X", "The calibration standards do not define an X interval.")
    xx = standards[x].to_numpy(dtype=float)
    yy = standards[y].to_numpy(dtype=float)
    if spec.domain == "nonnegative" and np.any(xx < 0):
        raise FieldError("Model", f"{model} requires nonnegative X. A log10 X model accepts negative log concentrations.")
    if spec.domain == "positive" and np.any(xx <= 0):
        raise FieldError("Model", f"{model} requires positive X values.")
    if len(xx) <= len(spec.parameters) or len(np.unique(xx)) < len(spec.parameters):
        raise FieldError("X", f"Not enough distinct X values for {model}.")
    if np.ptp(yy) <= 0:
        raise FieldError("Y", "Response values have zero variation.")
    if model in _SIGMOID_MODELS:
        low, high = float(yy.min()), float(yy.max())
        tolerance = _tolerance(max(abs(low), abs(high)))
        # Standards at only the two plateaus leave the transition unconstrained,
        # even when the optimizer returns finite parameters and covariance.
        if not ((yy - low > tolerance) & (high - yy > tolerance)).any():
            family = "5PL" if model in _FIVE_PL_MODELS else "4PL"
            raise FieldError("Y", f"The {family} model could not estimate the regression reliably. "
                                  "Include standards with responses between the two plateaus.")


def _log10_model(model):
    return model == LOG10_5PL or isinstance(model, str) and model.endswith(_LOG10_MARK)


def model_field_key(model):
    if _log10_model(model):
        return "calib.inverse_nonlinear.field.model_log10"
    if model in CONCENTRATION_MODELS:
        return "calib.inverse_nonlinear.field.model_concentration"
    return "calib.inverse_nonlinear.field.model"


def _row_title_column(frame, x, y):
    blocked = {x, y}
    for name in frame.columns:
        if name in blocked:
            continue
        if str(name).casefold() in {"row title", "row titles"}:
            return name
    return None


def _predict(model, theta, x_values):
    predicted = MODELS[model].equation(np.asarray(x_values, dtype=float), *theta)
    values = np.asarray(predicted, dtype=float).reshape(-1)
    if values.shape != (np.size(x_values),) or not np.isfinite(values).all():
        raise ValueError("Could not evaluate the calibration curve.")
    return values


def _tolerance(scale):
    return max(1e-8 * float(scale), 1e-12)


def _identifiable(model, theta, xmin, xmax, f_min, f_max, observed):
    """Accept a fit only when the curve has one direction on the observed domain.

    The direction is the change from f(xmin) to f(xmax). A flat curve, or a grid
    that turns against that change, has no unique concentration. This does not
    assume a Rate parameter and does not add bounds to the one-phase recipes.
    """
    scale = max([abs(float(value)) for value in (*np.asarray(observed, dtype=float), f_min, f_max)])
    tolerance = _tolerance(scale)
    if abs(f_max - f_min) <= tolerance:
        return False
    direction = 1.0 if f_max > f_min else -1.0
    # Confirm the catalog equation does not turn around. This grid is not inverted.
    change = np.diff(_predict(model, theta, np.linspace(xmin, xmax, 64)))
    wrong = change < -tolerance if direction > 0 else change > tolerance
    return not bool(np.any(wrong))


def _power_of_ten(solved):
    """Finite positive 10^X. Underflow and overflow stay missing rather than 0."""
    solved = np.asarray(solved, dtype=float)
    power = np.full(solved.shape, np.nan)
    finite = np.isfinite(solved)
    if not finite.any():
        return power
    with np.errstate(over="ignore", under="ignore"):
        converted = np.power(10.0, solved[finite])
    converted[~np.isfinite(converted) | (converted <= 0)] = np.nan
    power[finite] = converted
    return power


def _solve(model, theta, xmin, xmax, f_min, f_max, response):
    """Solve f(x) - response = 0 on the closed observed X interval."""
    tolerance = _tolerance(max(abs(f_min), abs(f_max), abs(response)))
    if abs(response - f_min) <= tolerance:
        return float(xmin), IN_RANGE
    if abs(response - f_max) <= tolerance:
        return float(xmax), IN_RANGE
    low, high = (f_min, f_max) if f_min <= f_max else (f_max, f_min)
    if response < low - tolerance or response > high + tolerance:
        return np.nan, OUT_OF_RANGE
    if model in _FIVE_PL_MODELS:
        solved = nonlinear_inverse.five_pl_point_estimate(model, theta, response)
        if solved is not None and xmin <= solved <= xmax:
            return solved, IN_RANGE
        return np.nan, NOT_IDENTIFIABLE

    def residual(value):
        return _predict(model, theta, [value])[0] - response

    try:
        root = brentq(residual, xmin, xmax, xtol=1e-12, rtol=1e-12)
    except ValueError:
        return np.nan, NOT_IDENTIFIABLE
    if not np.isfinite(root) or root < xmin or root > xmax:
        return np.nan, NOT_IDENTIFIABLE
    return float(root), IN_RANGE


def _check_inverse_queries(frame, query):
    if len(complete(frame, [query])) > MAX_INVERSE_QUERIES:
        raise FieldError(UNKNOWN_RESPONSES, "Inverse intervals accept at most 256 unknown responses.")


def check_nonlinear_inverse(frame, options):
    """Validate a nonlinear X-from-Y interval without fitting or searching.

    Level, model, replicate counts and the query budget name their fields here, so the dialog can
    reject them before the worker starts the root search.
    """
    curve, model, uncertainty, _level, count = inverse_options(options)
    if curve != "Nonlinear" or uncertainty == UNCERTAINTIES[0]:
        return
    query = options.get(UNKNOWN_RESPONSES)
    if not query:
        raise FieldError(UNKNOWN_RESPONSES, "Choose a column of unknown response values.")
    _check_inverse_queries(frame, query)
    if count:
        replicate_counts(frame, count, query, (options.get("X"), options.get("Y")))


def check_calibration_options(frame, options):
    """Validate visible choices before either desktop schedules the fit."""
    if calibration_direction(options) == DIRECTIONS[1]:
        forward_options(options)
    else:
        check_nonlinear_inverse(frame, options)
        if not options.get(UNKNOWN_RESPONSES):
            raise FieldError(UNKNOWN_RESPONSES, "Choose a column of unknown response values.")
    x, y = options.get("X"), options.get("Y")
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    calibration_choice_error(frame, x, y, options.get("Curve"), options.get("Model"))


def _pade_drawing(fitted, saved, x, y):
    """Keep archived plot sampling separate from the interpolation domain."""
    if not isinstance(saved, dict) or (saved.get("x"), saved.get("y")) != (x, y):
        return fitted.curve.copy()
    low, high, count = (saved.get(key) for key in ("min", "max", "points"))
    if (type(count) is not int or not 2 <= count <= MAX_PADE_DRAWING_POINTS
            or any(type(value) not in (int, float) or not -1e100 < value < 1e100 for value in (low, high))
            or not low < high or low >= fitted.x_max or high <= fitted.x_min):
        return fitted.curve.copy()
    grid = np.linspace(low, high, count)
    with np.errstate(over="ignore", invalid="ignore"):
        try:
            response = pade.evaluate_z(fitted.coefficients, (grid - fitted.x_min) / fitted.x_scale)
        except ValueError:
            # A change in the standards can put a pole inside the saved display range.
            return fitted.curve.copy()
    return np.column_stack((grid, response))


def _pade_inverse_curve(frame, x, y, query, *, missing_x_only=False, saved_drawing=None):
    fitted = pade.fit_pade(frame, x, y)
    query_data = frame.reset_index(drop=True)
    if missing_x_only is True:
        query_data = query_data.loc[query_data[x].isna()]
    samples = complete(query_data, [query])[query]
    if samples.empty:
        raise FieldError(UNKNOWN_RESPONSES, "Enter one or more unknown response values.")
    title_column = _row_title_column(frame, x, y)
    columns = ["Source row", "Response", "Interpolated X", "Status", "Domain low", "Domain high"]
    if title_column is not None:
        columns.insert(1, "Row title")
    responses = samples.to_numpy(dtype=float)
    solved, statuses = pade.invert_pade(fitted, responses)
    rows = []
    for offset, position in enumerate(samples.index):
        record = {"Source row": frame.index[position], "Response": float(responses[offset]),
                  "Interpolated X": float(solved[offset]),
                  "Status": statuses[offset], "Domain low": fitted.x_min, "Domain high": fitted.x_max}
        if title_column is not None:
            record["Row title"] = frame[title_column].iloc[position]
        rows.append(record)
    estimates = pd.DataFrame(rows, columns=columns)
    tables = {"Interpolated values": estimates, "Calibration parameters": fitted.parameters.copy(),
              "Fit diagnostics": _report(dict(fitted.diagnostics))}
    return StandardCurve(tables, curve=_pade_drawing(fitted, saved_drawing, x, y), model=PADE_MODEL)


def _nonlinear_curve(frame, x, y, query, model, uncertainty="None", level=None, counts=None):
    # Unknown responses stay out of the fit.
    if model in _SIGMOID_MODELS:
        calibration_choice_error(frame, x, y, "Nonlinear", model)
    fit = nonlinear(frame, x, y, model)["All"]
    samples = complete(frame, [query])[query]
    if samples.empty:
        raise ValueError("Enter one or more unknown response values.")
    names = MODELS[model].parameters
    named = {name: float(fit.parameters.at[name, "Estimate"]) for name in names}
    theta = tuple(named[name] for name in names)
    xmin, xmax = float(fit.data[x].min()), float(fit.data[x].max())
    if not np.isfinite([xmin, xmax]).all() or xmin >= xmax:
        raise ValueError("The calibration standards do not define an X interval.")
    f_min, f_max = _predict(model, theta, [xmin, xmax])
    identifiable = _identifiable(model, theta, xmin, xmax, f_min, f_max, fit.data[y].to_numpy())
    title_column = _row_title_column(frame, x, y)
    positions = frame.index.get_indexer(samples.index) if title_column is not None else None
    if positions is not None and (positions < 0).any():
        raise ValueError("Could not align unknown responses with the worksheet rows.")
    columns = ["Source row", "Response", "Interpolated X", "Status", "Domain low", "Domain high"]
    if title_column is not None:
        columns.insert(1, "Row title")
    rows = []
    for offset, (index, response) in enumerate(samples.items()):
        response = float(response)
        if identifiable:
            solved, status = _solve(model, theta, xmin, xmax, f_min, f_max, response)
        else:
            solved, status = np.nan, NOT_IDENTIFIABLE
        record = {"Source row": index, "Response": response, "Interpolated X": solved, "Status": status,
                  "Domain low": xmin, "Domain high": xmax}
        if title_column is not None:
            record["Row title"] = frame[title_column].iloc[int(positions[offset])]
        rows.append(record)
    estimates = pd.DataFrame(rows, columns=columns)
    if _log10_model(model):
        # Optional. Interpolated X itself stays in the log10 unit that was entered.
        position = list(estimates.columns).index("Interpolated X") + 1
        estimates.insert(position, POWER_COLUMN, _power_of_ten(estimates["Interpolated X"].to_numpy(dtype=float)))
    tables = {"Interpolated values": estimates, "Calibration parameters": fit.parameters.copy(),
              "Fit diagnostics": _report(dict(fit.diagnostics))}
    if uncertainty == UNCERTAINTIES[0]:
        return StandardCurve(tables, curve=np.array(fit.curve, copy=True), model=model)
    estimates, components = _nonlinear_intervals(fit, x, y, model, theta, estimates, uncertainty, level, counts)
    tables = {INTERPOLATED: estimates}
    if components is not None:
        tables[COMPONENTS] = components
    tables["Calibration parameters"] = fit.parameters.copy()
    diagnostics = dict(fit.diagnostics)
    diagnostics["Interval note"] = INTERVAL_NOTE
    tables["Fit diagnostics"] = _report(diagnostics)
    return StandardCurve(tables, curve=np.array(fit.curve, copy=True), model=model, uncertainty=uncertainty,
                         level=level, replicates=counts is not None)


def _checked_level(level):
    try:
        level = float(DEFAULT_LEVEL if level is None else level)
    except (TypeError, ValueError, OverflowError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    return level


def _replicate_count(value, column, row):
    """One k. Text follows the worksheet decimal comma; booleans, fractions and missing values are refused."""
    message = f'Column "{column}" needs a whole number of replicates between 1 and {MAX_COUNT} on row {row}.'
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(COUNT, message)
    try:
        number = Decimal(decimal_comma(str(value).strip()))
    except InvalidOperation:
        raise FieldError(COUNT, message) from None
    if not number.is_finite() or not 1 <= number <= MAX_COUNT or number != number.to_integral_value():
        raise FieldError(COUNT, message)
    return int(number)


def replicate_counts(frame, column, query, used=()):
    """k for every finite query that the calculation uses, in worksheet order.

    Rows without a query, or with an excluded query, need no k. An excluded count on a used query is missing.
    Positions, not labels, so duplicate index labels stay aligned with the query rows.
    """
    if not column or column not in frame:
        raise FieldError(COUNT, "Choose a column of replicate counts, or leave the field empty for k = 1.")
    if column == query or column in used:
        raise FieldError(COUNT, "Choose a replicate count column distinct from X, Y and the unknown values.")
    positions = _query_positions(frame, query)
    raw = frame[column]
    return np.array([_replicate_count(raw.iloc[position], column, position + 1) for position in positions],
                    dtype=np.int64)


def _query_positions(frame, query):
    """Worksheet positions of the finite queries, in the order of complete(frame, [query])."""
    return complete(frame.reset_index(drop=True), [query]).index.to_numpy(dtype=np.int64)


def _inverse_components(a, b, c, low, high):
    """Closed pieces of {t in [low, high] : a t² + b t + c <= 0}.

    The coefficients are normalized by the largest one, so the tolerances below are relative.
    A convex tangent contributes its single zero, and a concave tangent accepts the whole range. The pair of
    roots uses q = -(b + sign(b)·sqrt(disc))/2, roots q/a and c/q, so neither root loses digits to
    cancellation. Each piece carries whether its ends are the observed bounds. A root exactly on a
    bound belongs to the set, so an isolated bound with p = 0 is a piece of its own.
    Returns None when the coefficients cannot be represented.
    """
    coefficients = np.array([a, b, c], dtype=float)
    if not np.isfinite(coefficients).all():
        return None
    scale = float(np.max(np.abs(coefficients)))
    if scale == 0:
        return [(low, high, True, True)]
    a, b, c = coefficients / scale
    eps = 64 * np.finfo(float).eps
    roots = []
    if a == 0:
        if abs(b) > eps * abs(c):
            roots = [-c / b]
    else:
        disc = b * b - 4 * a * c
        tolerance = eps * (b * b + 4 * abs(a * c))
        if disc < -tolerance:
            return [(low, high, True, True)] if a < 0 else []
        if disc <= tolerance:
            if a < 0:
                return [(low, high, True, True)]
            tangent = -0.5 * b / a
            return [(tangent, tangent, tangent == low, tangent == high)] if low <= tangent <= high else []
        pair = -0.5 * (b + np.copysign(np.sqrt(disc), b))
        roots = [pair / a, c / pair]
    roots = sorted(root for root in roots if np.isfinite(root) and low < root < high)

    def value(t):
        return (a * t + b) * t + c

    stops = [low, *roots, high]
    pieces = []
    for start, stop in zip(stops, stops[1:]):
        if value(0.5 * (start + stop)) <= 0:
            if pieces and pieces[-1][1] == start:
                pieces[-1] = (pieces[-1][0], stop)
            else:
                pieces.append((start, stop))
    if (not pieces or pieces[0][0] != low) and value(low) <= 0:
        pieces.insert(0, (low, low))
    if (not pieces or pieces[-1][1] != high) and value(high) <= 0:
        pieces.append((high, high))
    return [(start, stop, start == low, stop == high) for start, stop in pieces]


def _inverse_linear(frame, x, y, fit, estimates, uncertainty, level, counts):
    """Inverse intervals for the line, with the 0.53.0 point estimates.

    With u = x − mean(x), z = Y − f(mean(x)) and slope b, X is in the set when
    (b² − q²s²/Sxx)u² − 2zb·u + z² − q²s²(1/n + r) <= 0, r = 0 for the mean response and
    1/k for the mean of k new observations. u is scaled by the larger distance from the
    mean to an observed bound, so the solved variable lies in [−1, 1].
    """
    standards = complete(frame, [x, y])
    xx = standards[x].to_numpy(dtype=float)
    yy = standards[y].to_numpy(dtype=float)
    n = len(xx)
    center = float(xx.mean())
    xmin, xmax = float(xx.min()), float(xx.max())
    # The one regression of this run is ``fit`` (centered by linregress). The least-squares line passes
    # through (mean x, mean y), so a0 = f(mean x) = mean(y) without the cancellation of intercept + slope·mean(x).
    # The 0.53.0 point estimates in ``estimates`` are kept as they are.
    centered = xx - center
    sxx = float(centered @ centered)
    a0 = float(yy.mean())
    slope = float(fit["Slope"])
    residual = yy - a0 - slope * centered
    ss = float(residual @ residual)
    df = n - 2
    s2 = ss / df if df > 0 else np.nan
    quantile = float(stats.t.isf((100 - level) / 200, df)) if df > 0 else np.nan
    width = max(center - xmin, xmax - center)
    available = (df > 0 and np.isfinite(s2) and sxx > 0 and width > 0 and np.isfinite(quantile)
                 and np.isfinite(slope) and slope != 0 and not _zero_residual(ss, n, yy))
    responses = estimates["Response"].to_numpy(dtype=float)
    outside = estimates["Outside calibration"].to_numpy(dtype=bool)
    lower = np.full(len(responses), np.nan)
    upper = np.full(len(responses), np.nan)
    status = np.empty(len(responses), dtype=object)
    labels = list(estimates.index)
    components = []
    tmin, tmax = ((xmin - center) / width, (xmax - center) / width) if width > 0 else (0.0, 0.0)
    for row, response in enumerate(responses):
        if outside[row]:
            status[row] = OUTSIDE_CALIBRATION
            continue
        if not available:
            status[row] = UNCERTAINTY_UNAVAILABLE
            continue
        r = 0.0 if uncertainty == UNCERTAINTIES[1] else 1.0 / (counts[row] if counts is not None else 1)
        z = response - a0
        with np.errstate(over="ignore", invalid="ignore"):
            spread = quantile * quantile * s2
            pieces = _inverse_components((slope * slope - spread / sxx) * width * width, -2 * z * slope * width,
                                         z * z - spread * (1 / n + r), tmin, tmax)
        estimate = z / slope / width
        if not pieces or not any(start <= estimate <= stop for start, stop, _, _ in pieces):
            # The point estimate always satisfies the inequality. Missing it means rounding took over.
            status[row] = UNCERTAINTY_UNAVAILABLE
            continue

        # Observed bounds are reported exactly, not through center + width·t.
        ends = [(xmin if at_low else center + width * start, xmax if at_high else center + width * stop)
                for start, stop, at_low, at_high in pieces]
        if len(pieces) > 1:
            status[row] = DISCONNECTED
            for number, (start, stop) in enumerate(ends, 1):
                components.append({"Source row": labels[row], "Component": number, "X lower": start, "X upper": stop})
            continue
        lower[row], upper[row] = ends[0]
        status[row] = CLIPPED[pieces[0][2:]]
    table = estimates.copy()
    table["X lower"] = lower
    table["X upper"] = upper
    table[INTERVAL_STATUS] = status
    if counts is not None:
        table[REPLICATES] = counts
    found = None
    if components:
        found = pd.DataFrame(components, columns=["Source row", "Component", "X lower", "X upper"])
    return table, found


def _interval_block(model, fit, x, y, theta):
    """Why this fit cannot carry an interval, or None when the forward-band rules accept it."""
    xx = fit.data[x].to_numpy(dtype=float)
    yy = fit.data[y].to_numpy(dtype=float)
    df = int(fit.diagnostics["df"])
    ss = float(fit.residual_ss)
    if not df > 0:
        return DF_REASON
    s2 = ss / df
    if not np.isfinite(s2):
        return DF_REASON
    if _zero_residual(ss, len(xx), yy):
        return EXACT_REASON
    covariance = None if fit.covariance is None else np.asarray(fit.covariance, dtype=float)
    if not _usable_covariance(covariance, len(theta)):
        return COVARIANCE_REASON
    if model in _SIGMOID_MODELS:
        if _at_bound(model, theta):
            return BOUND_REASON
    elif not (np.allclose(covariance, covariance.T, rtol=1e-8, atol=0) and theta[2] * float(np.ptp(xx)) > RATE_BOUND):
        return BOUND_REASON if not theta[2] * float(np.ptp(xx)) > RATE_BOUND else COVARIANCE_REASON
    return None


def _bound_flags(left, right, xmin, xmax):
    width = xmax - xmin
    if not width > 0:
        return left == xmin, right == xmax
    tolerance = 128 * np.finfo(float).eps
    return abs((left - xmin) / width) <= tolerance, abs((right - xmax) / width) <= tolerance


def _report_piece(left, right, xmin, xmax):
    at_low, at_high = _bound_flags(left, right, xmin, xmax)
    return (xmin if at_low else left, xmax if at_high else right, at_low, at_high)


def _nonlinear_intervals(fit, x, y, model, theta, estimates, uncertainty, level, counts):
    """Add interval columns from the fit already used for the point estimates."""
    block = _interval_block(model, fit, x, y, theta)
    xmin, xmax = float(estimates["Domain low"].iloc[0]), float(estimates["Domain high"].iloc[0])
    variance = None
    degrees = None
    covariance = None
    if block is None:
        degrees = int(fit.diagnostics["df"])
        variance = float(fit.residual_ss) / degrees
        covariance = np.asarray(fit.covariance, dtype=float)
    account = nonlinear_inverse.SearchAccount()
    lower = np.full(len(estimates), np.nan)
    upper = np.full(len(estimates), np.nan)
    status = np.empty(len(estimates), dtype=object)
    reason = np.empty(len(estimates), dtype=object)
    components = []
    sources = estimates["Source row"].tolist()
    point_status = estimates["Status"].tolist()
    responses = estimates["Response"].to_numpy(dtype=float)
    solved = estimates["Interpolated X"].to_numpy(dtype=float)
    for row, response in enumerate(responses):
        if point_status[row] == OUT_OF_RANGE:
            status[row], reason[row] = "", OUTSIDE_REASON
            continue
        if point_status[row] != IN_RANGE:
            status[row], reason[row] = "", IDENTIFIABLE_REASON
            continue
        if block is not None:
            status[row], reason[row] = UNCERTAINTY_UNAVAILABLE, block
            continue
        try:
            pieces = nonlinear_inverse.inverse_band_components(
                model, theta, covariance, variance, degrees, float(response), xmin, xmax,
                uncertainty=uncertainty, level=level, replicates=int(counts[row]) if counts is not None else 1,
                account=account)
        except InverseBudgetError as error:
            status[row], reason[row] = UNCERTAINTY_UNAVAILABLE, str(error)
            continue
        contained = any(left <= solved[row] <= right for left, right in pieces)
        if not pieces or not contained:
            status[row], reason[row] = UNCERTAINTY_UNAVAILABLE, EMPTY_REASON if not pieces else (
                "The interval search did not contain the point estimate.")
            continue
        if len(pieces) == 1:
            start, stop, at_low, at_high = _report_piece(*pieces[0], xmin, xmax)
            lower[row], upper[row] = start, stop
            status[row], reason[row] = CLIPPED[(at_low, at_high)], ""
            continue
        status[row], reason[row] = DISCONNECTED, ""
        for number, piece in enumerate(pieces, 1):
            start, stop, _at_low, _at_high = _report_piece(*piece, xmin, xmax)
            components.append({"Source row": sources[row], "Component": number, "X lower": start, "X upper": stop})
    table = estimates.copy()
    table["X lower"] = lower
    table["X upper"] = upper
    table[INTERVAL_STATUS] = status
    table["Reason"] = reason
    if counts is not None:
        table[REPLICATES] = counts
    found = None
    if components:
        found = pd.DataFrame(components, columns=["Source row", "Component", "X lower", "X upper"])
    return table, found


def calibration_visibility(direction, curve, uncertainty, model=None, *, pade_rows=False):
    """Fields that matter for the current choices. Hidden values never reach the calculation.

    Intervals exist for Linear and supported nonlinear models in Y from X, for the inverse Linear
    curve, and for an inverse nonlinear model in ``INVERSE_INTERVAL_MODELS``. A call without
    ``model`` keeps the historical visibility, so older callers do not change.
    """
    forward = direction == DIRECTIONS[1]
    forward_intervals = forward and (curve == "Linear" or model is None or model in FORWARD_INTERVAL_MODELS)
    inverse_nonlinear = not forward and curve == "Nonlinear" and model in INVERSE_INTERVAL_MODELS
    intervals = forward_intervals or (not forward and curve == "Linear") or inverse_nonlinear
    fields = {UNKNOWN_RESPONSES: not forward, UNKNOWN_X: forward, "Model": curve == "Nonlinear",
              UNCERTAINTY: intervals, LEVEL: intervals and uncertainty in UNCERTAINTIES[1:],
              COUNT: intervals and uncertainty == UNCERTAINTIES[2]}
    if pade_rows:
        fields[MISSING_X_ONLY] = not forward and curve == "Nonlinear" and model == PADE_MODEL
    return fields


def inverse_options(options):
    """Validate an X from Y recipe. Returns (curve, model, uncertainty, level, count).

    A recipe without Uncertainty, or with None, keeps the 0.53.0 path. Level and count are read only
    when the uncertainty uses them, so stale values from another choice never reach the calculation.
    """
    curve = options.get("Curve") or "Linear"
    if curve not in CURVES:
        raise FieldError("Curve", "Select a linear or nonlinear standard curve.")
    uncertainty = options.get(UNCERTAINTY) or UNCERTAINTIES[0]
    if uncertainty not in UNCERTAINTIES:
        raise FieldError(UNCERTAINTY, "Select None, Mean response or Prediction.")
    _check_inverse_uncertainty(curve, options.get("Model"), uncertainty)
    level = _checked_level(options.get(LEVEL)) if uncertainty != UNCERTAINTIES[0] else None
    return curve, options.get("Model"), uncertainty, level, replicate_option(options, uncertainty)


def _check_inverse_uncertainty(curve, model, uncertainty):
    if curve == "Linear" or uncertainty == UNCERTAINTIES[0] or not model or model in INVERSE_INTERVAL_MODELS:
        return
    if model == PADE_MODEL:
        raise FieldError(UNCERTAINTY, f"Intervals are not available for {PADE_MODEL}. Choose None.")
    raise FieldError(UNCERTAINTY, "Inverse intervals are not available for One-phase association. Choose None.")


def replicate_option(options, uncertainty):
    """The replicate count column, read only for Prediction."""
    return (options.get(COUNT) or None) if uncertainty == UNCERTAINTIES[2] else None


def calibration_direction(options):
    direction = options.get(DIRECTION) or DIRECTIONS[0]
    if direction not in DIRECTIONS:
        raise FieldError(DIRECTION, "Select X from Y or Y from X.")
    return direction


def forward_options(options):
    """Validate a Y from X recipe. Returns (curve, model, uncertainty, level)."""
    curve = options.get("Curve") or "Linear"
    if curve not in CURVES:
        raise FieldError("Curve", "Select a linear or nonlinear standard curve.")
    model = None
    if curve == "Nonlinear":
        model = options.get("Model") or FORWARD_MODELS[0]
        if model not in FORWARD_MODELS:
            raise FieldError("Model", _FORWARD_MODEL_ERROR)
    uncertainty = options.get(UNCERTAINTY) or UNCERTAINTIES[0]
    if uncertainty not in UNCERTAINTIES:
        raise FieldError(UNCERTAINTY, "Select None, Mean response or Prediction.")
    if uncertainty != UNCERTAINTIES[0] and curve == "Nonlinear" and model not in FORWARD_INTERVAL_MODELS:
        raise FieldError(UNCERTAINTY, f"Intervals are not available for {model}. Choose None.")
    level = None
    if uncertainty != UNCERTAINTIES[0]:
        raw = options.get(LEVEL, DEFAULT_LEVEL)
        try:
            level = float(raw)
        except (TypeError, ValueError, OverflowError):
            level = np.nan
        if not np.isfinite(level) or not 0 < level < 100:
            raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    if not options.get(UNKNOWN_X):
        raise FieldError(UNKNOWN_X, "Choose a column of unknown X values.")
    return curve, model, uncertainty, level


def _zero_residual(ss, n, observed):
    """Residual SD at rounding level of the responses counts as an exact fit."""
    scale = float(np.max(np.abs(observed))) if len(observed) else 0.0
    return not ss > (64 * np.finfo(float).eps * max(scale, np.finfo(float).tiny))**2 * n


def _variance(gradient, covariance):
    """g C gᵀ per row. Small negative rounding goes to 0, clearly negative values to NaN."""
    variance = np.einsum("ij,jk,ik->i", gradient, covariance, gradient)
    scale = np.einsum("ij,jk,ik->i", np.abs(gradient), np.abs(covariance), np.abs(gradient))
    rounding = variance < 0
    clear = variance < -1e-10 * scale
    variance = np.where(rounding & ~clear, 0.0, variance)
    variance[clear | ~np.isfinite(variance)] = np.nan
    return variance


def _forward_linear(standards, x, y):
    fit = linear(standards, x, y)
    xx = standards[x].to_numpy(dtype=float)
    yy = standards[y].to_numpy(dtype=float)
    n = len(xx)
    center = xx.mean()
    sxx = float((xx - center) @ (xx - center))
    intercept, slope = float(fit["Intercept"]), float(fit["Slope"])
    residual = yy - (intercept + slope * xx)
    ss = float(residual @ residual)
    df = n - 2
    s2 = ss / df if df > 0 else np.nan
    # Parameters are the fitted value at mean(X) and the slope: v(x) = s²[1/n + (x − mean)²/Sxx].
    covariance = np.diag([s2 / n, s2 / sxx]) if np.isfinite(s2) and sxx > 0 else None
    available = covariance is not None and not _zero_residual(ss, n, yy)

    def predict(values):
        return intercept + slope * np.asarray(values, dtype=float)

    def gradient(values):
        values = np.asarray(values, dtype=float)
        return np.column_stack((np.ones_like(values), values - center))

    tables = {"Linear calibration": _report(fit)}
    return predict, gradient, covariance, s2, df, available, tables, fit, None


def _four_pl_gradient(model, theta, values):
    """∂f/∂(Bottom, Top, mid, Hill) for f = B + (T − B)·expit(h·u).

    u = ln x − ln mid (concentration) or ln 10·(x − log mid) (log10 X), d = (T − B)p(1 − p) and the
    gradient is [1 − p, p, d·h·du/dmid, d·u]. At concentration 0 the catalog limit is a plateau:
    u = −∞, p is 0 or 1, and the last two terms are 0 rather than 0·∞.
    """
    bottom, top, mid, hill = theta
    values = np.asarray(values, dtype=float).reshape(-1)
    if _log10_model(model):
        shifted = np.log(10.0) * (values - mid)
        slope = -np.log(10.0)
    else:
        shifted = np.full(values.shape, -np.inf)
        np.log(values, out=shifted, where=values > 0)
        shifted = shifted - np.log(mid)
        slope = -1.0 / mid
    with np.errstate(over="ignore", invalid="ignore"):
        probability = special.expit(hill * shifted)
        change = (top - bottom) * probability * (1.0 - probability)
        finite = np.isfinite(shifted)
        midpoint = np.zeros(values.shape)
        steepness = np.zeros(values.shape)
        midpoint[finite] = change[finite] * hill * slope
        steepness[finite] = change[finite] * shifted[finite]
    return np.column_stack((1.0 - probability, probability, midpoint, steepness))


def _decay_gradient(theta, values):
    _, span, rate = theta
    values = np.asarray(values, dtype=float).reshape(-1)
    decay = np.exp(-rate * values)
    return np.column_stack((np.ones_like(values), decay, -span * values * decay))


def _usable_covariance(covariance, size):
    """The fit's parameter covariance can carry a band.

    Square of the parameter count, finite, symmetric to rounding, positive variances, and a
    correlation matrix that is positive semidefinite up to rounding. The fit itself already
    refuses rank-deficient matrices; these checks keep a band from a matrix that a later
    change could let through.
    """
    if covariance is None or covariance.shape != (size, size) or not np.isfinite(covariance).all():
        return False
    variances = np.diag(covariance)
    if not (variances > 0).all():
        return False
    sd = np.sqrt(variances)
    correlation = covariance / np.outer(sd, sd)
    if not np.allclose(correlation, correlation.T, rtol=0, atol=1e-8):
        return False
    return bool(np.linalg.eigvalsh(0.5 * (correlation + correlation.T)).min() > -1e-8)


def _at_bound(model, theta):
    """Parameters that sit on a finite catalog bound, judged relative to the bound and the estimate.

    The 4PL catalog bounds the concentration midpoint and the Hill slope away from 0 by the
    smallest normal float. A midpoint of 1e-12 is far from that bound in relative terms and keeps
    its band. A parameter within PARAMETER_BOUND of the bound is where the optimizer stopped
    against the constraint, so its covariance is not a local quadratic approximation.
    """
    lower, upper = (np.broadcast_to(np.asarray(bound, dtype=float), np.shape(theta)) for bound in MODELS[model].bounds)
    theta = np.asarray(theta, dtype=float)
    stuck = np.zeros(theta.shape, dtype=bool)
    for bound in (lower, upper):
        finite = np.isfinite(bound)
        gap = np.abs(theta - bound)
        stuck |= finite & (gap <= PARAMETER_BOUND * np.maximum(np.abs(theta), np.abs(bound)))
    return bool(stuck.any())


def _forward_nonlinear(frame, x, y, model, *, standards=None):
    if model == PADE_MODEL:
        fitted = pade.fit_pade(frame, x, y, standards=standards)

        def predict(values):
            return pade.predict_pade(fitted, values)

        tables = {"Calibration parameters": fitted.parameters.copy(), "Fit diagnostics": _report(dict(fitted.diagnostics))}
        return predict, None, None, np.nan, fitted.df, False, tables, None, fitted.curve
    fit = nonlinear(frame, x, y, model)["All"]
    names = MODELS[model].parameters
    theta = tuple(float(fit.parameters.at[name, "Estimate"]) for name in names)
    xx = fit.data[x].to_numpy(dtype=float)
    yy = fit.data[y].to_numpy(dtype=float)
    df = int(fit.diagnostics["df"])
    ss = float(fit.residual_ss)
    s2 = ss / df if df > 0 else np.nan
    covariance = None if fit.covariance is None else np.asarray(fit.covariance, dtype=float)
    available = (df > 0 and np.isfinite(s2) and not _zero_residual(ss, len(xx), yy)
                 and _usable_covariance(covariance, len(theta)))
    if model in _SIGMOID_MODELS:
        available = available and not _at_bound(model, theta)

        def gradient(values):
            if model in _FIVE_PL_MODELS:
                return nonlinear_inverse.five_pl_curve_gradient(model, theta, values)[1]
            return _four_pl_gradient(model, theta, values)
    else:
        available = (available and np.allclose(covariance, covariance.T, rtol=1e-8, atol=0)
                     and theta[2] * float(np.ptp(xx)) > RATE_BOUND)

        def gradient(values):
            return _decay_gradient(theta, values)

    def predict(values):
        return _predict(model, theta, np.asarray(values, dtype=float).reshape(-1))

    tables = {"Calibration parameters": fit.parameters.copy(), "Fit diagnostics": _report(dict(fit.diagnostics))}
    return predict, gradient, covariance, s2, df, available, tables, None, fit.curve


def _band_grid(model, observed):
    """Closed X range of the standards. Concentration bands follow the fit's log grid, with 0 kept."""
    observed = np.asarray(observed, dtype=float)
    xmin, xmax = float(observed.min()), float(observed.max())
    if model in CONCENTRATION_MODELS:
        if xmin == 0:
            grid = np.r_[0.0, np.geomspace(observed[observed > 0].min(), xmax, BAND_POINTS - 1)]
        else:
            grid = np.geomspace(xmin, xmax, BAND_POINTS)
    else:
        grid = np.linspace(xmin, xmax, BAND_POINTS)
    grid[0], grid[-1] = xmin, xmax
    return grid


def predict_standard_curve(frame, x, y, query, curve="Linear", model=None, uncertainty="None", level=None,
                           count=None):
    """Predict Y at unknown X with an optional pointwise mean-response or prediction band.

    With Prediction, ``count`` names a column of replicate counts k: each query's limits are for the
    mean of k new observations, v + s²/k. The Calibration bands sheet and the drawn band stay at k = 1.
    """
    if curve not in CURVES:
        raise FieldError("Curve", "Select a linear or nonlinear standard curve.")
    if curve == "Nonlinear":
        model = model or FORWARD_MODELS[0]
        if model not in FORWARD_MODELS:
            raise FieldError("Model", _FORWARD_MODEL_ERROR)
    else:
        model = None
    if uncertainty not in UNCERTAINTIES:
        raise FieldError(UNCERTAINTY, "Select None, Mean response or Prediction.")
    if uncertainty != UNCERTAINTIES[0] and model is not None and model not in FORWARD_INTERVAL_MODELS:
        raise FieldError(UNCERTAINTY, f"Intervals are not available for {model}. Choose None.")
    banded = uncertainty != UNCERTAINTIES[0]
    if banded and (level is None or not np.isfinite(level) or not 0 < level < 100):
        raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    if not query:
        raise FieldError(UNKNOWN_X, "Choose a column of unknown X values.")
    try:
        standards = complete(frame, [x, y])
    except ValueError as error:
        message = str(error)
        field = "Y" if f'"{y}"' in message and f'"{x}"' not in message else "X"
        raise FieldError(field, message) from error
    if standards.empty:
        raise FieldError("X", "The calibration standards do not define an X interval.")
    samples = complete(frame, [query])[query]
    if samples.empty:
        raise FieldError(UNKNOWN_X, "Enter one or more unknown X values.")
    if model is None:
        predict, gradient, covariance, s2, df, available, tables, fitted, grid_curve = _forward_linear(standards, x, y)
    elif model == PADE_MODEL:
        predict, gradient, covariance, s2, df, available, tables, fitted, grid_curve = _forward_nonlinear(
            frame, x, y, model, standards=standards)
    else:
        calibration_choice_error(frame, x, y, "Nonlinear", model)
        predict, gradient, covariance, s2, df, available, tables, fitted, grid_curve = _forward_nonlinear(
            frame, x, y, model)
    counts = None
    if uncertainty == UNCERTAINTIES[2] and count:
        counts = replicate_counts(frame, count, query, (x, y))
    xmin, xmax = float(standards[x].min()), float(standards[x].max())
    if not np.isfinite([xmin, xmax]).all() or xmin >= xmax:
        raise FieldError("X", "The calibration standards do not define an X interval.")
    available = banded and available
    quantile = float(stats.t.isf((100 - level) / 200, df)) if available else np.nan
    if available and not np.isfinite(quantile):
        available = False
    extra = s2 if uncertainty == UNCERTAINTIES[2] else 0.0

    def limits(values, replicates=1):
        values = np.asarray(values, dtype=float).reshape(-1)
        if not available:
            return np.full(values.shape, np.nan)
        with np.errstate(over="ignore", invalid="ignore"):
            variance = _variance(gradient(values), covariance)
            return quantile * np.sqrt(variance + extra / replicates)

    title_column = _row_title_column(frame, x, y)
    positions = _query_positions(frame, query) if title_column is not None else None
    columns = ["Source row", "X", "Predicted Y", "Status", "Y lower", "Y upper"]
    if title_column is not None:
        columns.insert(1, "Row title")
    values = samples.to_numpy(dtype=float)
    inside = (values >= xmin) & (values <= xmax)
    predicted = np.full(values.shape, np.nan)
    half = np.full(values.shape, np.nan)
    if inside.any():
        predicted[inside] = predict(values[inside])
        half[inside] = limits(values[inside], 1 if counts is None else counts[inside])
    rows = []
    for offset, index in enumerate(samples.index):
        record = {"Source row": index, "X": values[offset], "Predicted Y": np.nan, "Status": OUTSIDE_CALIBRATION,
                  "Y lower": np.nan, "Y upper": np.nan}
        if inside[offset]:
            record["Predicted Y"] = predicted[offset]
            if not banded:
                record["Status"] = IN_RANGE
            elif np.isfinite(half[offset]):
                record.update({"Status": IN_RANGE, "Y lower": predicted[offset] - half[offset],
                               "Y upper": predicted[offset] + half[offset]})
            else:
                record["Status"] = UNCERTAINTY_UNAVAILABLE
        if title_column is not None:
            record["Row title"] = frame[title_column].iloc[int(positions[offset])]
        if counts is not None:
            record[REPLICATES] = int(counts[offset])
        rows.append(record)
    if counts is not None:
        columns.append(REPLICATES)
    output = {PREDICTIONS: pd.DataFrame(rows, columns=columns)}
    if available:
        grid = _band_grid(model, standards[x].to_numpy(dtype=float))
        fitted_grid = predict(grid)
        margin = limits(grid)
        output[BANDS] = pd.DataFrame({"X": grid, "Fit": fitted_grid, "Y lower": fitted_grid - margin,
                                      "Y upper": fitted_grid + margin})
    output.update(tables)
    if grid_curve is None:
        grid_curve = np.column_stack((np.array([xmin, xmax]), predict([xmin, xmax])))
    return StandardCurve(output, curve=np.array(grid_curve, copy=True), linear=fitted, model=model,
                         forward=True, uncertainty=uncertainty, level=level, replicates=counts is not None)
