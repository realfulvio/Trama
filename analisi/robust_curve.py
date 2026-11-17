"""Robust curve fit: Cauchy, Huber or Soft L1 loss with a fixed or pilot-estimated residual scale (0.73 candidate).

A vertical residual ``r = Y - f(X; theta)`` is divided by a scale ``s > 0`` and ``u = r / s`` is penalised by
``sum rho(u**2)``, a dimensionless sum, with ``s`` held **fixed during the final fit**:

* Cauchy: ``rho(z) = log1p(z)``, influence weight ``d rho / d z = 1 / (1 + z)``;
* Soft L1: ``rho(z) = 2 (sqrt(1 + z) - 1)``, weight ``1 / sqrt(1 + z)``;
* Huber: ``rho(z) = z`` for ``|u| <= 1`` and ``2 |u| - 1`` otherwise, weight ``1`` or ``1 / |u|``.

The influence weights are diagnostics of how strongly a point was down-weighted. They are not probabilities,
they are not reused as weights of a second regression and they are not an outlier test: every observation stays
in the fit, in the graph and in the source. No standard error, covariance, confidence interval, p value, AICc or
robust R² is reported; ``RSDR`` is a descriptive spread of the final residuals, never a standard error.

Scale: ``Fixed`` uses the typed ``Residual scale``. ``Pilot MAD`` first runs an ordinary, unweighted least-squares
fit from the same starting values and sets ``s = 1.482602218505602 * median(|r - median(r)|)`` from its residuals.
If that is zero, the linear .6827 quantile of ``|r|`` is used (Scale source "Absolute residual quantile
fallback"), then the median of the nonzero ``|r|`` ("Positive residual fallback"). When every pilot residual is
zero the pilot is the result (scale 0, objective 0, weights 1, Status "Exact pilot"). Only genuinely zero computed
residuals are treated as zero: a large Y offset must not erase representable residual variation.
A pilot that does not converge is an error; there is no silent fall back to ordinary
least squares.

Numerics fixed by this module (documented in the pull request): the solver is ``scipy.optimize.least_squares``
(trf, bounds, 3-point Jacobian, tolerances ``TOLERANCE``) on the residuals ``u`` with its own ``loss`` and
``f_scale=1`` (its ``cost`` equals half of the reported objective and is never reported); every free parameter is
optimised as ``theta / |start|`` (1 for a zero start) so absolute tolerances cannot depend on units; the pilot works
on ``Y / max|Y|``; the final model must have a numerically full-rank Jacobian after its columns are scaled to unit
length (``RANK_TOLERANCE``), otherwise the fit is reported as not identifiable instead of returning an arbitrary
curve. ``Maximum evaluations`` limits each optimisation stage; "Evaluations" adds the stages together.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from . import stats as engine
from .category_graphs import COLORS
from .field_error import FieldError
from .reporting import Result, _plot

ROBUST_CURVE = "Robust curve fit"
CAUCHY, HUBER, SOFT_L1 = LOSSES = ("Cauchy", "Huber", "Soft L1")
FIXED, PILOT_MAD = SCALE_METHODS = ("Fixed", "Pilot MAD")
CURVE, RESIDUALS, WEIGHTS = DISPLAYS = ("Curve", "Residuals", "Weights")
HORIZONTAL = "Horizontal line"
MODELS = ("Straight line", *(name for name, spec in engine.MODELS.items()
                             if name != "Straight line" and not (spec.required_fixed or spec.required_shared)))

# Recipe fields (the canonical English names); the dialog kind of the initial-parameter table is INITIAL_LIST.
X, Y_COLUMNS, GROUP, MODEL, LOSS, SCALE_METHOD, RESIDUAL_SCALE = (
    "X", "Y columns", "Group", "Model", "Loss", "Scale method", "Residual scale")
INITIAL, EVALUATIONS, THRESHOLD, COMPARE, DISPLAY = (
    "Initial parameters", "Maximum evaluations", "Low weight threshold", "Compare ordinary fit", "Graph display")
INITIAL_LIST = "Initial parameter list"
ERROR_PREFIX = "analysis.robust_curve.error."  # catalog prefix of the engine messages (see i18n.translate_message)
# "Multiple" and "Optional" are the dialog's own kind names for column pickers (see workbench).
OPTIONS = {X: None, Y_COLUMNS: "Multiple", GROUP: "Optional", MODEL: MODELS, LOSS: LOSSES, SCALE_METHOD: SCALE_METHODS,
           RESIDUAL_SCALE: 1.0, INITIAL: INITIAL_LIST, EVALUATIONS: 20_000, THRESHOLD: 0.25, COMPARE: False,
           DISPLAY: DISPLAYS}
DEFAULTS = {MODEL: MODELS[0], LOSS: CAUCHY, SCALE_METHOD: FIXED, RESIDUAL_SCALE: 1.0, INITIAL: {}, EVALUATIONS: 20_000,
            THRESHOLD: 0.25, COMPARE: False, DISPLAY: CURVE}
# Pages of the dialog: Variables (data, model, starting values), Loss and scale (the Options page), Output.
VARIABLE_FIELDS = (X, Y_COLUMNS, GROUP, MODEL, INITIAL)
OUTPUT_FIELDS = (THRESHOLD, COMPARE, DISPLAY)

MAX_FITS, MAX_PAIRS, MAX_PARAMETERS = 24, 100_000, 12
MIN_EVALUATIONS, MAX_EVALUATIONS = 50, 100_000
CURVE_POINTS = 201
TOLERANCE, RANK_TOLERANCE = 1e-12, 1e-8
MAD_FACTOR, QUANTILE = 1.482602218505602, 0.6827
EXACT_STATUS, CONVERGED = "Exact pilot", "Converged"
MAD_SOURCE, QUANTILE_SOURCE, POSITIVE_SOURCE = "Pilot MAD", "Absolute residual quantile fallback", "Positive residual fallback"
UNAVAILABLE = "Not available"
INFERENCE_NOTE = ("Descriptive only: no standard errors, confidence intervals or p values. Influence weights show how "
                  "strongly a point was down-weighted; they are not an outlier test.")
TABLES = ("Robust parameters", "Robust fit", "Robust residuals", "Robust curve")
ORDINARY = "Ordinary comparison"
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
SOURCE_LIMIT = 1e100  # A trial step outside the domain is rejected by this finite residual instead of poisoning the solver.


# ----- losses ----------------------------------------------------------------------------------------------------------

def loss_values(u, loss):
    """``(rho, weight)`` of the dimensionless residuals ``u`` for one of the three losses (stable for tiny and huge u)."""
    u = np.asarray(u, dtype=float)
    a = np.abs(u)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if loss == CAUCHY:
            rho = np.where(a < 1e100, np.log1p(a * a), 2 * np.log(a))
            return rho, 1 / (1 + a * a)
        if loss == SOFT_L1:
            h = np.hypot(1.0, u)
            # 2 (h - 1) = 2 z / (h + 1): no cancellation near zero, and a * (2 a / (h + 1)) cannot overflow early.
            return a * (2 * a / (h + 1)), 1 / h
        if loss == HUBER:
            return np.where(a <= 1, a * a, 2 * a - 1), np.where(a <= 1, 1.0, 1 / np.maximum(a, np.finfo(float).tiny))
    raise ValueError(loss)


# ----- options ---------------------------------------------------------------------------------------------------------

def _real(value):
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, Real) and not isinstance(value, complex)


def _tuple_of(value):
    return (value,) if isinstance(value, str) else tuple(value) if isinstance(value, (list, tuple)) else ()


@dataclass(frozen=True)
class Settings:
    x: str
    ys: tuple
    group: str | None
    model: str
    loss: str
    scale_method: str
    scale: float | None
    initial: dict | None
    evaluations: int
    threshold: float
    compare: bool
    display: str


def _column(frame, name, field):
    if not isinstance(name, str) or not name:
        raise FieldError(field, f"Choose a column for {field}.")
    if name not in frame.columns:
        raise FieldError(field, f'Choose an existing column for {field}: "{name}" is not in the worksheet.')
    if isinstance(frame[name], pd.DataFrame):
        raise FieldError(field, "Worksheet column names must be unique.")


def _choice(options, field, choices, message):
    value = options.get(field, DEFAULTS[field])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(field, message)
    return value


def initial_from(spec, values):
    """Validate the saved starting values against the parameter names and limits of ``spec``.

    ``{}`` (or None) means "use the catalog starting values". Any other dictionary must name every parameter of the
    model, and only those. Raises FieldError("Initial parameters"); ``error.parameter`` names the offending parameter.
    """
    if values is None or values == {}:
        return None
    if not isinstance(values, dict):
        raise FieldError(INITIAL, "Initial parameters must list parameter names and values; leave it empty to use the "
                                  "catalog values.")
    names = spec.parameters
    missing = [name for name in names if name not in values]
    unknown = [str(name) for name in values if name not in names]
    if missing or unknown:
        error = FieldError(INITIAL, ("Initial parameters must give every parameter of the model; missing: "
                                     + ", ".join(missing) + ".") if missing else
                           "Initial parameters name unknown parameters for this model: " + ", ".join(unknown) + ".")
        error.parameter = (missing or unknown)[0]
        raise error
    lower, upper = _bounds(spec)
    checked = {}
    for name, low, high in zip(names, lower, upper, strict=True):
        value = values[name]
        if not _real(value) or not np.isfinite(float(value)):
            error = FieldError(INITIAL, f"Initial parameter {name} must be a finite number.")
            error.parameter = name
            raise error
        value = float(value)
        if not low <= value <= high:
            error = FieldError(INITIAL, f"Initial parameter {name} = {value:g} lies outside its limits "
                                        f"({low:g} to {high:g}).")
            error.parameter = name
            raise error
        checked[name] = value
    return checked


def resolve(frame, options):
    """Validate the recipe against the worksheet columns and return Settings. Inactive fields are ignored.

    Partial recipes take the defaults of :data:`DEFAULTS`; keys of other methods are ignored. No data value is read.
    """
    o = {**DEFAULTS, **{key: value for key, value in options.items() if key in OPTIONS}}
    x = o.get(X)
    _column(frame, x, X)
    ys = _tuple_of(o.get(Y_COLUMNS))
    if not ys:
        raise FieldError(Y_COLUMNS, "Choose at least one Y column.")
    for name in ys:
        _column(frame, name, Y_COLUMNS)
    for name in dict.fromkeys(ys):
        if ys.count(name) > 1:
            raise FieldError(Y_COLUMNS, f'Y columns must be distinct: "{name}" is chosen more than once.')
    if x in ys:
        raise FieldError(Y_COLUMNS, f'X and Y columns must be different: "{x}" is both.')
    group = o.get(GROUP) or None
    if group is not None:
        _column(frame, group, GROUP)
        if group == x or group in ys:
            raise FieldError(GROUP, f'Group must differ from X and the Y columns: "{group}" is already used.')
    model = _choice(o, MODEL, MODELS, "Model: choose a supported model of the catalog.")
    loss = _choice(o, LOSS, LOSSES, "Loss: choose Cauchy, Huber or Soft L1.")
    method = _choice(o, SCALE_METHOD, SCALE_METHODS, "Scale method: choose Fixed or Pilot MAD.")
    scale = None
    if method == FIXED:
        scale = o[RESIDUAL_SCALE]
        if not _real(scale) or not np.isfinite(float(scale)) or not float(scale) > 0:
            raise FieldError(RESIDUAL_SCALE, "Residual scale must be a finite number greater than 0.")
        scale = float(scale)
    evaluations = o[EVALUATIONS]
    if (not isinstance(evaluations, (Integral, float)) or isinstance(evaluations, (bool, np.bool_))
            or not np.isfinite(evaluations) or evaluations != int(evaluations)
            or not MIN_EVALUATIONS <= evaluations <= MAX_EVALUATIONS):
        raise FieldError(EVALUATIONS, f"Maximum evaluations must be a whole number from {MIN_EVALUATIONS} to "
                                      f"{MAX_EVALUATIONS}.")
    threshold = o[THRESHOLD]
    if not _real(threshold) or not np.isfinite(float(threshold)) or not 0 < float(threshold) < 1:
        raise FieldError(THRESHOLD, "Low weight threshold must be a finite number greater than 0 and less than 1.")
    compare = o[COMPARE]
    if not isinstance(compare, (bool, np.bool_)):
        raise FieldError(COMPARE, "Compare ordinary fit must be true or false.")
    display = _choice(o, DISPLAY, DISPLAYS, "Graph display: choose Curve, Residuals or Weights.")
    initial = initial_from(engine.MODELS[model], o[INITIAL])
    return Settings(x, ys, group, model, loss, method, scale, initial, int(evaluations), float(threshold),
                    bool(compare), display)


# ----- data ------------------------------------------------------------------------------------------------------------

@dataclass
class FitData:
    series: str
    level: object
    label: str
    positions: np.ndarray
    x: np.ndarray
    y: np.ndarray


def _numbers(frame, name, role, rows):
    """Float values of the used rows. Text, complex and infinite cells in them name the role and the source row."""
    column = frame[name]
    chosen = column.iloc[rows]
    if chosen.dtype.kind == "c" or (chosen.dtype == object and any(isinstance(v, (complex, np.complexfloating))
                                                                 for v in chosen)):
        raise FieldError(role, f'Column "{name}" contains complex values.')
    numeric = pd.to_numeric(chosen, errors="coerce") if chosen.dtype.kind != "b" else pd.Series(np.nan, index=chosen.index)
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    text = ~np.isfinite(values) & ~np.isinf(values)
    if text.any():
        raise FieldError(role, f'Column "{name}" contains non-numeric values (first at source row '
                               f"{int(rows[np.flatnonzero(text)[0]])}).")
    if np.isinf(values).any():
        raise FieldError(role, f'Column "{name}" contains infinite values (first at source row '
                               f"{int(rows[np.flatnonzero(np.isinf(values))[0]])}).")
    return values


def _label(series, level, grouped):
    return f"{series} · {level}" if grouped else series


def prepare(frame, s):
    """Complete rows of every (Y column, Group level) fit, in the order of the recipe. Never fits anything.

    The source position of each row is its zero-based position in ``frame``, whatever the pandas index holds.
    """
    present_x = frame[s.x].notna().to_numpy()
    in_group = frame[s.group].notna().to_numpy() if s.group else np.ones(len(frame), dtype=bool)
    used = {name: np.flatnonzero(present_x & in_group & frame[name].notna().to_numpy()) for name in s.ys}
    total = sum(len(rows) for rows in used.values())
    if total == 0:
        raise FieldError(Y_COLUMNS, "No complete X and Y pairs.")
    if total > MAX_PAIRS:
        raise FieldError(Y_COLUMNS, f"The analysis supports up to {MAX_PAIRS:,} complete pairs; found {total:,}.")
    plan, count = [], 0
    for name in s.ys:
        rows = used[name]
        if not len(rows):
            raise FieldError(Y_COLUMNS, f'Column "{name}" has no complete X and Y pairs.')
        if s.group:
            codes, levels = pd.factorize(frame[s.group].iloc[rows], sort=False)
            parts = [(levels[i], rows[codes == i]) for i in range(len(levels))]
        else:
            parts = [("All", rows)]
        count += len(parts)
        plan.append((name, parts))
    if count > MAX_FITS:
        raise FieldError(GROUP if s.group else Y_COLUMNS,
                         f"The analysis supports up to {MAX_FITS} fits (Y columns × groups); found {count}.")
    fits = []
    for name, parts in plan:
        rows = used[name]
        x_all, y_all = _numbers(frame, s.x, X, rows), _numbers(frame, name, Y_COLUMNS, rows)
        offset = {int(p): i for i, p in enumerate(rows)}
        for level, positions in parts:
            take = np.array([offset[int(p)] for p in positions])
            fits.append(FitData(name, level, _label(name, level, bool(s.group)), positions, x_all[take], y_all[take]))
    return fits


# ----- model helpers ----------------------------------------------------------------------------------------------------

def _bounds(spec):
    count = len(spec.parameters)
    lower, upper = (np.broadcast_to(np.asarray(bound, dtype=float), (count,)).copy() for bound in spec.bounds)
    return lower, upper


def _predict(spec, x, values):
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.broadcast_to(np.asarray(spec.equation(x, *values), dtype=float), x.shape)


def _catalog_start(spec, fit):
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            values = np.asarray(spec.initial(fit.x, fit.y), dtype=float)
        except (ValueError, TypeError, FloatingPointError, IndexError, ZeroDivisionError):
            values = np.full(len(spec.parameters), np.nan)
    lower, upper = _bounds(spec)
    if values.shape != lower.shape or not np.isfinite(values).all() or ((values < lower) | (values > upper)).any():
        raise FieldError(INITIAL, f"The catalog starting values cannot be calculated from these data ({fit.label}); "
                                  "enter starting values.")
    return values


def proposed_initial(frame, options):
    """Catalog starting values of the first fit, as ``{parameter: value}``; empty when they cannot be calculated.

    The dialog shows them in the table of starting values. Never raises, never fits.
    """
    try:
        s = resolve(frame, {**options, INITIAL: {}})
        fit = prepare(frame, s)[0]
        spec = engine.MODELS[s.model]
        _domain(s.model, spec, fit)
        return dict(zip(spec.parameters, (float(v) for v in _catalog_start(spec, fit)), strict=True))
    except (FieldError, ValueError, KeyError, IndexError):
        return {}


def _domain(model, spec, fit):
    if spec.domain == "positive" and np.any(fit.x <= 0):
        i = int(np.flatnonzero(fit.x <= 0)[0])
        raise FieldError(X, f"{model} requires positive X values; {fit.label} has X = {fit.x[i]:g} at source row "
                            f"{int(fit.positions[i])}.")
    if spec.domain == "nonnegative" and np.any(fit.x < 0):
        i = int(np.flatnonzero(fit.x < 0)[0])
        raise FieldError(X, f"{model} requires nonnegative X values; {fit.label} has X = {fit.x[i]:g} at source row "
                            f"{int(fit.positions[i])}.")


def _check_fit(s, spec, fit):
    """Everything known before the optimizer runs for one fit. Returns the starting values."""
    n, p = len(fit.x), len(spec.parameters)
    if p > MAX_PARAMETERS:
        raise FieldError(MODEL, f"{s.model} has more than {MAX_PARAMETERS} parameters.")
    if n <= p:
        raise FieldError(MODEL, f"{fit.label}: {n} complete pairs cannot estimate {p} parameters; the model needs "
                                "more pairs than parameters.")
    distinct = len(np.unique(fit.x))
    if distinct < p and s.model != HORIZONTAL:
        raise FieldError(MODEL, f"{fit.label}: {distinct} distinct X values cannot estimate {p} parameters.")
    _domain(s.model, spec, fit)
    start = (np.array([s.initial[name] for name in spec.parameters]) if s.initial is not None
             else _catalog_start(spec, fit))
    predicted = _predict(spec, fit.x, start)
    if not np.isfinite(predicted).all():
        i = int(np.flatnonzero(~np.isfinite(predicted))[0])
        raise FieldError(INITIAL, f"The model is not defined at the starting values for {fit.label} at X = "
                                  f"{fit.x[i]:g} (source row {int(fit.positions[i])}). Change the starting values.")
    return start


def check_options(frame, options):
    """Everything detectable before the worker runs; the dialog calls this on Run. No fit is performed."""
    s = resolve(frame, options)
    spec = engine.MODELS[s.model]
    fits = prepare(frame, s)
    for fit in fits:
        _check_fit(s, spec, fit)
    return s


# ----- optimisation -----------------------------------------------------------------------------------------------------

def _solve(function, start, lower, upper, loss, evaluations):
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return least_squares(function, start, bounds=(lower, upper), method="trf", jac="3-point", x_scale="jac",
                             loss=loss, f_scale=1.0, xtol=TOLERANCE, ftol=TOLERANCE, gtol=TOLERANCE,
                             max_nfev=evaluations)


def _identifiable(spec, x, q, units, lower, upper):
    """Jacobian of the model in scaled parameters has full rank after its columns are scaled to unit length."""
    columns = []
    for i in range(len(q)):
        h = 1e-6 * max(1.0, abs(q[i]))
        high, low = q.copy(), q.copy()
        high[i], low[i] = min(q[i] + h, upper[i]), max(q[i] - h, lower[i])
        if high[i] == low[i]:
            return False
        columns.append((_predict(spec, x, high * units) - _predict(spec, x, low * units)) / (high[i] - low[i]))
    jacobian = np.column_stack(columns)
    norm = np.linalg.norm(jacobian, axis=0)
    if not np.isfinite(jacobian).all() or (norm == 0).any() or not np.isfinite(norm).all():
        return False
    singular = np.linalg.svd(jacobian / norm, compute_uv=False)
    return bool(singular[-1] > RANK_TOLERANCE * singular[0])


@dataclass
class Ordinary:
    """An ordinary fit. ``reason`` is the English text of the comparison table; ``code`` names the cause."""
    ok: bool
    parameters: np.ndarray | None = None
    raw_ss: float = np.nan
    reason: str = ""
    evaluations: int = 0
    code: str = ""


def _ordinary(spec, fit, start, units, lower, upper, evaluations):
    """Unweighted least squares from the same scaled start, on Y / max|Y|. Returns an Ordinary; never raises."""
    reference = float(np.max(np.abs(fit.y))) or 1.0

    def function(q):
        value = (fit.y - _predict(spec, fit.x, q * units)) / reference
        return np.where(np.isfinite(value), value, SOURCE_LIMIT)

    try:
        result = _solve(function, start / units, lower / units, upper / units, "linear", evaluations)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return Ordinary(False, reason="the ordinary fit could not be estimated reliably", code="estimate")
    if result.status <= 0:
        return Ordinary(False, reason=f"the ordinary fit did not converge within {evaluations} evaluations",
                        evaluations=int(result.nfev), code="converge")
    parameters = result.x * units
    if not _identifiable(spec, fit.x, result.x, units, lower / units, upper / units):
        return Ordinary(False, reason="the model is not identifiable from these data", evaluations=int(result.nfev),
                        code="identifiable")
    residual = fit.y - _predict(spec, fit.x, parameters)
    return Ordinary(True, parameters, float(residual @ residual), "", int(result.nfev))


@dataclass
class Solution:
    fit: FitData
    parameters: np.ndarray
    predicted: np.ndarray
    residual: np.ndarray
    standardized: np.ndarray
    weight: np.ndarray
    low: np.ndarray
    scale: float
    source: str
    objective: float
    raw_ss: float
    rsdr: float
    evaluations: int
    status: str
    grid: np.ndarray
    curve: np.ndarray
    ordinary: Ordinary | None = None
    ordinary_curve: np.ndarray | None = None


def _grid(spec, x):
    if spec.log_grid and x.min() > 0:
        return np.geomspace(x.min(), x.max(), CURVE_POINTS)
    return np.linspace(x.min(), x.max(), CURVE_POINTS)


def _solve_fit(s, spec, fit, start):
    """One robust fit. Raises FieldError naming the field to change; returns a Solution."""
    n, p = len(fit.x), len(spec.parameters)
    units = np.where(start == 0, 1.0, np.abs(start))
    lower, upper = (b / units for b in _bounds(spec))
    q0 = start / units
    pilot, scale, source, status = None, s.scale, FIXED, CONVERGED
    evaluations = 0
    if s.scale_method == PILOT_MAD:
        pilot = _ordinary(spec, fit, start, units, *_bounds(spec), s.evaluations)
        if not pilot.ok:
            if pilot.code == "converge":
                raise FieldError(EVALUATIONS, f"{fit.label}: the ordinary pilot fit did not converge within "
                                              f"{s.evaluations} evaluations.")
            if pilot.code == "identifiable":
                raise FieldError(MODEL, f"{fit.label}: the ordinary pilot fit is not identifiable from these data.")
            raise FieldError(MODEL, f"{fit.label}: the ordinary pilot fit could not be estimated reliably.")
        evaluations += pilot.evaluations
        q0 = pilot.parameters / units
        residual = fit.y - _predict(spec, fit.x, pilot.parameters)
        cleaned = residual
        scale, source = MAD_FACTOR * float(np.median(np.abs(cleaned - np.median(cleaned)))), MAD_SOURCE
        if scale == 0:
            scale, source = float(np.quantile(np.abs(cleaned), QUANTILE, method="linear")), QUANTILE_SOURCE
        if scale == 0 and np.any(cleaned != 0):
            scale, source = float(np.median(np.abs(cleaned[cleaned != 0]))), POSITIVE_SOURCE
        if not np.isfinite(scale):
            raise FieldError(Y_COLUMNS, f"{fit.label}: the pilot residual scale is not finite.")
    exact = scale == 0
    if exact:
        q, parameters, status, source = q0, pilot.parameters, EXACT_STATUS, EXACT_STATUS
    else:
        def function(q):
            value = (fit.y - _predict(spec, fit.x, q * units)) / scale
            return np.where(np.isfinite(value), value, SOURCE_LIMIT)

        try:
            result = _solve(function, q0, lower, upper, {CAUCHY: "cauchy", HUBER: "huber", SOFT_L1: "soft_l1"}[s.loss],
                            s.evaluations)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            raise FieldError(INITIAL if s.scale_method == FIXED else MODEL,
                             f"{fit.label}: the robust fit could not be estimated reliably.") from None
        if result.status <= 0:
            raise FieldError(EVALUATIONS, f"{fit.label}: the optimizer did not converge within {s.evaluations} "
                                          "evaluations. Increase Maximum evaluations or change the starting values.")
        evaluations += int(result.nfev)
        q = np.clip(result.x, lower, upper)
        parameters = q * units
    predicted = _predict(spec, fit.x, parameters)
    if not np.isfinite(predicted).all():
        raise FieldError(MODEL, f"{fit.label}: the robust fit could not be estimated reliably.")
    if not _identifiable(spec, fit.x, parameters / units, units, lower, upper):
        raise FieldError(MODEL, f"{fit.label}: the model is not identifiable from these data (the parameters "
                                "cannot be estimated separately). Choose a simpler model.")
    residual = fit.y - predicted
    if exact:
        standardized, weight, rho = np.zeros(n), np.ones(n), np.zeros(n)
        cleaned = np.zeros(n)
    else:
        standardized = residual / scale
        rho, weight = loss_values(standardized, s.loss)
        cleaned = residual
    objective, raw_ss = float(np.sum(rho)), float(residual @ residual)
    if not np.isfinite([objective, raw_ss]).all():
        raise FieldError(RESIDUAL_SCALE if s.scale_method == FIXED else MODEL,
                         f"{fit.label}: the loss exceeds the numerical range; check the residual scale and the units.")
    rsdr = float(np.quantile(np.abs(cleaned), QUANTILE, method="linear")) * n / (n - p)
    grid = _grid(spec, fit.x)
    curve = _predict(spec, grid, parameters)
    solution = Solution(fit, parameters, predicted, residual, standardized, weight, weight < s.threshold, float(scale),
                        source, objective, raw_ss, rsdr, evaluations, status, grid, curve)
    return solution, units, pilot


def _compare(s, spec, solution, units, pilot, start):
    """The ordinary least-squares fit on the same sample; reuses the pilot when it is the same fit."""
    bounds = _bounds(spec)
    ordinary = pilot if pilot is not None else _ordinary(spec, solution.fit, start, units, *bounds, s.evaluations)
    solution.ordinary = ordinary
    if ordinary.ok:
        solution.ordinary_curve = _predict(spec, solution.grid, ordinary.parameters)


def fit_all(frame, s):
    """Fit every (Y column, Group level). Nothing is shown or stored until every fit succeeded."""
    spec = engine.MODELS[s.model]
    fits = prepare(frame, s)
    starts = [_check_fit(s, spec, fit) for fit in fits]
    solutions = []
    for fit, start in zip(fits, starts, strict=True):
        solution, units, pilot = _solve_fit(s, spec, fit, start)
        if s.compare:
            _compare(s, spec, solution, units, pilot, start)
        solutions.append(solution)
    return solutions


# ----- tables -----------------------------------------------------------------------------------------------------------

def _levels(items):
    """A Group column that keeps the original level objects (numbers stay numbers, text stays text)."""
    return pd.Series(list(items))


def tables(frame, s, solutions):
    spec = engine.MODELS[s.model]
    names = spec.parameters
    p_series, p_group, p_name, p_value = [], [], [], []
    summary = []
    r_cols = {key: [] for key in ("Series", "Group", "Source row", "Source index", "X", "Observed", "Predicted", "Residual",
                                  "Standardized residual", "Influence weight", "Low weight")}
    c_series, c_group, c_x, c_y = [], [], [], []
    for sol in solutions:
        fit, n = sol.fit, len(sol.fit.x)
        for name, value in zip(names, sol.parameters, strict=True):
            p_series.append(fit.series), p_group.append(fit.level), p_name.append(name), p_value.append(float(value))
        summary.append({"Series": fit.series, "Group": fit.level, "N": n, "Free parameters": len(names), "Loss": s.loss,
                        "Residual scale": sol.scale, "Scale source": sol.source, "Robust objective": sol.objective,
                        "Raw residual SS": sol.raw_ss, "RSDR": sol.rsdr, "Low weight count": int(sol.low.sum()),
                        "Evaluations": sol.evaluations, "Status": sol.status, "Inference note": INFERENCE_NOTE})
        r_cols["Series"] += [fit.series] * n
        r_cols["Group"] += [fit.level] * n
        r_cols["Source row"] += [int(i) for i in fit.positions]
        r_cols["Source index"] += list(frame.index.take(fit.positions))
        r_cols["X"] += sol.fit.x.tolist()
        r_cols["Observed"] += sol.fit.y.tolist()
        r_cols["Predicted"] += sol.predicted.tolist()
        r_cols["Residual"] += sol.residual.tolist()
        r_cols["Standardized residual"] += sol.standardized.tolist()
        r_cols["Influence weight"] += sol.weight.tolist()
        r_cols["Low weight"] += [bool(v) for v in sol.low]
        c_series += [fit.series] * CURVE_POINTS
        c_group += [fit.level] * CURVE_POINTS
        c_x += sol.grid.tolist()
        c_y += sol.curve.tolist()
    fit_table = pd.DataFrame(summary)
    fit_table["Group"] = _levels(row["Group"] for row in summary)
    out = {
        "Robust parameters": pd.DataFrame({"Series": p_series, "Group": _levels(p_group), "Parameter": p_name,
                                           "Estimate": p_value}),
        "Robust fit": fit_table,
        "Robust residuals": pd.DataFrame({key: (_levels(v) if key in {"Group", "Source index"} else v)
                                          for key, v in r_cols.items()}),
        "Robust curve": pd.DataFrame({"Series": c_series, "Group": _levels(c_group), "X": c_x, "Predicted": c_y}),
    }
    if s.compare:
        rows = []
        for sol in solutions:
            ordinary = sol.ordinary
            for name, robust, value in zip(names, sol.parameters, ordinary.parameters if ordinary.ok
                                           else [np.nan] * len(names), strict=True):
                rows.append({"Series": sol.fit.series, "Group": sol.fit.level, "Parameter": name,
                             "Robust estimate": float(robust), "Ordinary estimate": float(value),
                             "Robust raw residual SS": sol.raw_ss, "Ordinary raw residual SS": ordinary.raw_ss,
                             "Ordinary status": CONVERGED if ordinary.ok else UNAVAILABLE,
                             "Reason": "" if ordinary.ok else ordinary.reason})
        table = pd.DataFrame(rows)
        table["Group"] = _levels(row["Group"] for row in rows)
        out[ORDINARY] = table
    return out


# ----- figure -----------------------------------------------------------------------------------------------------------

def _unique_labels(solutions):
    labels, seen = [], set()
    for sol in solutions:
        label = sol.fit.label
        while label in seen:
            label += " (2)"
        seen.add(label)
        labels.append(label)
    return labels


def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def figure(s, solutions):
    ys = list(dict.fromkeys(sol.fit.series for sol in solutions))
    labels = _unique_labels(solutions)
    ylabel = {CURVE: ys[0] if len(ys) == 1 else "Value", RESIDUALS: "Residual", WEIGHTS: "Influence weight"}[s.display]
    title = f"{ROBUST_CURVE} · {s.model} · {s.loss}" + ("" if s.display == CURVE else f" · {s.display}")
    fig, axes = _plot(title, s.x, ylabel)
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label)
    low_label = f"Low weight (< {s.threshold:g})"
    low_drawn = False
    pending, entries = [], []  # legend entries are kept here: matplotlib drops labels that start with an underscore
    for index, (sol, label) in enumerate(zip(solutions, labels, strict=True)):
        color, marker = COLORS[index % len(COLORS)], MARKERS[(index // len(COLORS)) % len(MARKERS)]
        x = sol.fit.x
        value = {CURVE: sol.fit.y, RESIDUALS: sol.residual, WEIGHTS: sol.weight}[s.display]
        entries.append((axes.scatter(x, value, s=30, color=color, marker=marker, label=label, zorder=3), label))
        pending.append((sol, color, marker, value))
    if s.display == CURVE:
        for sol, color, _, _ in pending:
            axes.plot(sol.grid, sol.curve, color=color, linewidth=1.8, label="_nolegend_", zorder=2)
        for sol, color, _, _ in pending:
            if sol.ordinary is not None and sol.ordinary_curve is not None:
                axes.plot(sol.grid, sol.ordinary_curve, color=color, linewidth=1.3, linestyle="--",
                          label="_nolegend_", zorder=2)
    if s.display in (CURVE, RESIDUALS):
        for sol, color, _, value in pending:
            if sol.low.any():
                ring = axes.scatter(sol.fit.x[sol.low], value[sol.low], s=130, facecolors="none", edgecolors=color,
                                    linewidths=1.6, label="_nolegend_" if low_drawn else low_label, zorder=4)
                if not low_drawn:
                    entries.append((ring, low_label))
                low_drawn = True
    if s.display == RESIDUALS:
        axes.axhline(0, color="#6b7785", linewidth=1.0, linestyle=":", zorder=1)
    if s.display == WEIGHTS:
        axes.set_ylim(0, 1.05)
        line = axes.axhline(s.threshold, color="#8a3b12", linewidth=1.2, linestyle="--", zorder=1,
                            label=f"Threshold {s.threshold:g}")
        entries.append((line, line.get_label()))
    handles, names = [handle for handle, _ in entries], [name for _, name in entries]
    if s.compare and s.display == CURVE and any(sol.ordinary_curve is not None for sol in solutions):
        from matplotlib.lines import Line2D
        handles.append(Line2D([], [], color="#44515e", linestyle="--", linewidth=1.3))
        names.append("Ordinary fit (dashed)")
    # Always outside the axes: an outlier is exactly the point a legend inside the plot would cover.
    legend = axes.legend(handles, names, fontsize=8.5, frameon=True, framealpha=.92, loc="upper left",
                         bbox_to_anchor=(1.01, 1.0))
    _plain(legend.get_title(), *legend.get_texts())
    return fig


# ----- analysis ---------------------------------------------------------------------------------------------------------

def robust_curve(frame, options):
    """The analysis behind ``analyse("Robust curve fit", …)``. The worksheet and its attrs are never modified."""
    s = resolve(frame, options)
    solutions = fit_all(frame, s)
    return Result(tables(frame, s, solutions), figure(s, solutions))
