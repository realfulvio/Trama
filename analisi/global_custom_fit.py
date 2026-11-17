"""Global fit of one user equation across series (shared, local and fixed coefficients).

One predictor X, one response Y and a required Group column. Every series is part of a single
objective; a series is never fitted on its own first. The equation text is parsed by
:mod:`custom_equations`. Nothing the user writes is executed, and a recipe stores only plain
numbers, strings and booleans.

Numerical conventions, inherited and stated here so a later change can be checked against them:

* objective ``sum(((Y - f(X)) / SD) ** 2)`` with ``SD = 1`` when unweighted;
* the solver sees a normalised problem, as in :mod:`custom_fit`: ``SD' = SD / max(SD)``,
  ``reference = max |Y / SD'|`` (or the size of the starting predictions when Y is identically
  zero, else 1), residuals divided by ``SD' * reference``, each free coefficient optimised as
  ``theta / |start|``. A common factor of the SD column cancels. "Weighted residual SS" is
  reported with the SD values as typed;
* ``scipy.optimize.least_squares`` (trf, 3-point Jacobian, then a short dogbox polish when a
  coordinate stops just short of a bound, the same polish as :mod:`global_fit`);
* rank from the SVD of the Jacobian after each column is scaled to unit length. The fit is
  rejected when the smallest singular value is at most ``sqrt(eps)`` times the largest, or a
  column is zero. The covariance comes from that SVD, not from an inversion of the normal
  equations: ``Cov(theta) = (RSSw / df) (Jwᵀ Jw)⁻¹``;
* a free coefficient within ``1e-7`` of a limit, in the optimiser's units and with no absolute
  floor, keeps its estimate, is marked "At bound", and suppresses the whole covariance (the
  conservative rule of the existing global fitter);
* residual variance within ``max((64 * eps) ** 2, TOLERANCE ** 2) * N`` of zero on the
  normalised objective is treated as round-off, not as a real error variance. The solver stops
  when its tolerance is met and can leave a residual far above the smallest float; that leftover
  is reported as exact zero. The test is relative to the normalised objective, so a response of
  size 1e-12 with a real residual is kept. Intervals are then omitted. There is no absolute
  threshold in units of Y. With no free coefficient the reported residual is kept and the
  covariance is empty.
"""
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import optimize, stats

from .custom_equations import (ARITHMETIC, CONDITIONAL, MAX_PARAMETERS, SYNTAXES, ConditionError, compile_equation,
                               curve_with_breaks, syntax_of)
from .custom_fit import (
    BRANCH, DEFAULT_EQUATION, EQUATION_TEXT, LEVEL, MAX_GROUPS, MAX_PAIRS, MIN_POINTS, MAX_POINTS,
    POINTS, SD_COLUMN, SYNTAX, _bound, _number, _values,
)
from . import global_uncertainty as uncertainty
from .field_error import FieldError
from .fit_weights import INVERSE_VARIANCE, UNWEIGHTED
from .parameter_intervals import METHOD as INTERVAL_METHOD, METHODS as INTERVAL_METHODS, PROFILE, WALD, ProfileBudget
from .monte_carlo import MonteCarloCancelled
from .repeated_input import decode_series_constraints
from .reporting import Result, _plot, _report

GLOBAL_CUSTOM_EQUATION = "Global fit custom equation"
PARAMETER_LIST = "Global coefficient list"
SERIES_LIST = "Global series constraints"
WEIGHTINGS = (UNWEIGHTED, INVERSE_VARIANCE)
DEFAULT_LEVEL, DEFAULT_POINTS = 95.0, 201
MAX_FREE_CELLS = 2_000_000
MAX_EVALUATIONS, TOLERANCE = 20_000, 1e-12
RANK_TOLERANCE = float(np.sqrt(np.finfo(float).eps))
BOUND_MARGIN = 1e-7
# Machine round-off on the normalised objective, and the solver's own exit tolerance.
# A perfect curve stops when ftol is met and can still leave a residual SS far above
# the smallest float; that leftover is reported as zero. It is relative to the
# normalised objective, so a response of size 1e-12 with a real residual is kept.
ROUND_OFF = max((64 * np.finfo(float).eps) ** 2, TOLERANCE ** 2)
EXAMPLE_PARAMETERS = (
    {"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False, "shared": False},
    {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False, "shared": True},
)
OPTIONS = {
    "X": None, "Y": None, "Group": None, SYNTAX: SYNTAXES, "Equation": EQUATION_TEXT, "Parameters": PARAMETER_LIST,
    "Series constraints": SERIES_LIST, "Weighting": WEIGHTINGS, SD_COLUMN: "Optional",
    LEVEL: DEFAULT_LEVEL, POINTS: DEFAULT_POINTS, INTERVAL_METHOD: INTERVAL_METHODS,
    # 0.70: response bands. "None" comes first, so a recipe without these keys keeps the five sheets.
    uncertainty.CURVE_BAND: uncertainty.INTERVALS, uncertainty.RESPONSE_LEVEL: uncertainty.DEFAULT_RESPONSE_LEVEL,
    uncertainty.BAND_DRAWING: uncertainty.DRAWINGS,
    # 0.70: predictions for new X. The query columns are read only when Predict responses is on.
    uncertainty.PREDICT: False, uncertainty.QUERY_X: "Optional", uncertainty.QUERY_GROUP: "Optional",
    uncertainty.QUERY_INTERVAL: uncertainty.INTERVALS, uncertainty.QUERY_K: "Optional",
    uncertainty.EXTRAPOLATE: False,
}
TABS = {
    "Equation": (SYNTAX, "Equation"), "Parameters": ("Parameters",),
    "Series constraints": ("Series constraints",), "Output": (INTERVAL_METHOD, LEVEL, POINTS),
    # 0.70: bands of the fitted response and predictions for new X, on a page of their own.
    "Response": (uncertainty.CURVE_BAND, uncertainty.RESPONSE_LEVEL, uncertainty.BAND_DRAWING, uncertainty.PREDICT,
                 uncertainty.QUERY_X, uncertainty.QUERY_GROUP, uncertainty.QUERY_INTERVAL, uncertainty.QUERY_K,
                 uncertainty.EXTRAPOLATE),
}
_OVERRIDE_KEYS = {"fixed", "lower", "upper", "initial"}
_INDEX = ("Scope", "Group", "Parameter")


@dataclass(frozen=True)
class Coefficient:
    name: str
    start: float
    lower: float | None
    upper: float | None
    fixed: bool
    shared: bool


@dataclass(frozen=True)
class Settings:
    x: str
    y: str
    group: str
    sd: str | None
    equation: str
    coefficients: tuple
    weighting: str
    level: float
    points: int
    constraints: tuple
    # 0.70 response outputs; "None" keeps the five original sheets.
    band: str = uncertainty.NONE
    response_level: float | None = None
    drawing: str = uncertainty.FILLED
    queries: object = None
    intervals: str = WALD
    syntax: str = ARITHMETIC


def _flag(record, name, key):
    if key not in record or not isinstance(record[key], (bool, np.bool_)):
        raise FieldError("Parameters", f"{name}: {key} must be true or false.")
    return bool(record[key])


def coefficients_from(records, syntax=ARITHMETIC):
    """Validate Parameters: names, finite starts, strict limits, and exactly one of local/shared/fixed."""
    if not isinstance(records, (list, tuple)):
        raise FieldError("Parameters", "Parameters must be a list of coefficients.")
    if len(records) > MAX_PARAMETERS:
        raise FieldError("Parameters", f"Use at most {MAX_PARAMETERS} coefficients.")
    found, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            raise FieldError("Parameters", "Each coefficient needs a name, a starting value and its limits.")
        name = record.get("name")
        from .custom_equations import check_name
        check_name(name, syntax)
        if name in seen:
            raise FieldError("Parameters", f"The coefficient {name} appears more than once.")
        seen.add(name)
        fixed, shared = _flag(record, name, "fixed"), _flag(record, name, "shared")
        if fixed and shared:
            raise FieldError("Parameters", f"{name}: a coefficient cannot be both fixed and shared.")
        start = record.get("start")
        if not _number(start) or not np.isfinite(start):
            raise FieldError("Parameters", f"{name}: the value must be a finite number." if fixed
                             else f"{name}: the starting value must be a finite number.")
        start = float(start)
        lower, upper = _bound(record.get("lower"), name, "lower"), _bound(record.get("upper"), name, "upper")
        if lower is not None and upper is not None and not lower < upper:
            raise FieldError("Parameters", f"{name}: the lower limit must be smaller than the upper limit.")
        if (lower is not None and start < lower) or (upper is not None and start > upper):
            raise FieldError("Parameters", f"{name}: the value {start:g} lies outside its limits." if fixed
                             else f"{name}: the starting value {start:g} lies outside its limits.")
        found.append(Coefficient(name, start, lower, upper, fixed, shared))
    return tuple(found)


def _constraints_from(records):
    if records is None:
        records = []
    try:
        decoded = decode_series_constraints(list(records))
    except ValueError as error:
        raise FieldError("Series constraints", str(error)) from None
    return tuple((label, dict(parameters)) for label, parameters in decoded.items())


def resolve(frame, options):
    """Validate the recipe against the columns. Does not read data values or run a fit."""
    columns = list(frame.columns)
    x, y, group = options.get("X"), options.get("Y"), options.get("Group") or None
    for field, column in (("X", x), ("Y", y)):
        if column not in columns:
            raise FieldError(field, f"Choose an existing column for {field}.")
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    if group is None or group not in columns or group in (x, y):
        raise FieldError("Group", "Group is required and must be an existing column different from X and Y.")
    weighting = options.get("Weighting", UNWEIGHTED)
    if weighting not in WEIGHTINGS:
        raise FieldError("Weighting", "Choose Unweighted or Inverse variance (column).")
    sd = options.get(SD_COLUMN) or None
    if weighting == INVERSE_VARIANCE:
        if sd is None or sd not in columns:
            raise FieldError(SD_COLUMN, "Choose the column with the relative standard deviations.")
        if sd in (x, y, group):
            raise FieldError(SD_COLUMN, "The SD column must differ from X, Y and Group.")
    else:
        # A leftover SD column is not read, even when it contains text.
        sd = None
    level = options.get(LEVEL, DEFAULT_LEVEL)
    if not _number(level) or not np.isfinite(level) or not 0 < float(level) < 100:
        raise FieldError(LEVEL, "The confidence level must be between 0 and 100 (exclusive).")
    points = options.get(POINTS, DEFAULT_POINTS)
    if (not _number(points) or not np.isfinite(points) or float(points) != int(points)
            or not MIN_POINTS <= int(points) <= MAX_POINTS):
        raise FieldError(POINTS, f"Curve points must be a whole number from {MIN_POINTS} to {MAX_POINTS}.")
    syntax = syntax_of(options.get(SYNTAX))
    coefficients = coefficients_from(options.get("Parameters", ()), syntax)
    compiled = compile_equation(options.get("Equation"), [c.name for c in coefficients], syntax=syntax)
    # A shared coefficient cannot be fixed per series, so in a condition it must be Fixed now. A local one may
    # instead be fixed for every series in Series constraints; _bind checks that once the series are known.
    _free_conditions(compiled, [c.name for c in coefficients if c.shared and not c.fixed])
    constraints = _constraints_from(options.get("Series constraints", []))
    band, response_level, drawing = uncertainty.band_options(options, weighting)
    queries = uncertainty.query_options(options, columns, weighting)
    intervals = options.get(INTERVAL_METHOD, WALD)
    if intervals not in INTERVAL_METHODS:
        raise FieldError(INTERVAL_METHOD, 'Choose Symmetric (Wald) or Profile likelihood.')
    return Settings(x, y, group, sd, str(options.get("Equation")).strip(), coefficients, weighting,
                    float(level), int(points), constraints, band, response_level, drawing, queries, intervals, syntax)


def _free_conditions(compiled, free_names, series=None):
    free = [name for name in compiled.condition_parameters if name in set(free_names)]
    if free and series is None:
        raise FieldError("Parameters", f"{', '.join(free)} appears in a condition of if(...) and must be Fixed: "
                                       "a shared coefficient cannot be a threshold to estimate. This fit uses known "
                                       "thresholds and does not estimate change points.")
    if free:
        raise FieldError("Parameters", f"{', '.join(free)} appears in a condition of if(...) and is not fixed for "
                                       f"series {series!r}: this fit uses known thresholds and does not estimate "
                                       "change points. Mark it Fixed, or give it a fixed value for every series in "
                                       "Series constraints.")


def _condition_coefficients(s):
    """Coefficients read inside a condition (none for Arithmetic recipes)."""
    if s.syntax != CONDITIONAL:
        return ()
    return compile_equation(s.equation, [c.name for c in s.coefficients], syntax=s.syntax).condition_parameters


def _limits(lower, upper):
    return -np.inf if lower is None else float(lower), np.inf if upper is None else float(upper)


def _finite_override(label, name, key, raw):
    if not _number(raw) or not np.isfinite(raw):
        raise FieldError("Series constraints", f"Series {label!r}, {name}: {key} must be a finite number.")
    return float(raw)


def prepare(frame, s):
    """Complete rows per series, in order of first appearance, with the source index kept."""
    rows = frame[s.group].notna()
    distinct = list(pd.unique(frame.loc[rows, s.group]))
    labels = [str(level) for level in distinct]
    if len(set(labels)) != len(labels):
        raise FieldError("Group", "Different group values look the same as text; make them distinct first.")
    if len(labels) > MAX_GROUPS:
        raise FieldError("Group", f"Use at most {MAX_GROUPS} groups.")
    x = _values(frame[s.x], "X", s.x, rows)
    y = _values(frame[s.y], "Y", s.y, rows)
    complete = rows & x.notna() & y.notna()
    sd = None
    if s.sd is not None:
        sd = _values(frame[s.sd], SD_COLUMN, s.sd, complete)
        bad = complete & sd.notna() & ~(sd > 0)
        if bad.any():
            raise FieldError(SD_COLUMN, "The SD column needs positive values on every used row "
                                        f"(source row {sd.index[bad][0]}). Leave a cell empty to skip that row.")
    used = complete & (sd.notna() if sd is not None else True)
    if int(used.sum()) > MAX_PAIRS:
        raise FieldError("Y", f"The analysis supports up to {MAX_PAIRS:,} complete pairs.")
    groups = []
    for label, level in zip(labels, distinct):
        keep = rows & (frame[s.group] == level) & used
        if not keep.any():
            continue
        data = pd.DataFrame({"X": x[keep].to_numpy(), "Y": y[keep].to_numpy()}, index=frame.index[keep])
        if sd is not None:
            data["SD"] = sd[keep].to_numpy()
        groups.append((label, data))
    if len(groups) < 2:
        raise FieldError("Group", "Global fitting needs at least two series with complete observations.")
    if len(groups) > MAX_GROUPS:
        raise FieldError("Group", f"Use at most {MAX_GROUPS} groups.")
    return groups


def _bind(s, labels):
    """Per-series limits, fixed values and starts. Shared limits are the intersection."""
    names = [c.name for c in s.coefficients]
    by_name = {c.name: c for c in s.coefficients}
    lower = {label: {} for label in labels}
    upper = {label: {} for label in labels}
    fixed = {label: {} for label in labels}
    starts = {label: {} for label in labels}
    for label in labels:
        for c in s.coefficients:
            lo, hi = _limits(c.lower, c.upper)
            lower[label][c.name], upper[label][c.name] = lo, hi
            fixed[label][c.name] = c.start if c.fixed else None
            starts[label][c.name] = c.start
    known = set(labels)
    conditioned = set(_condition_coefficients(s))
    for label, parameters in s.constraints:
        text = str(label)
        if text not in known:
            raise FieldError("Series constraints",
                             f"Series {text!r} is not among the series with complete rows. "
                             "Remove that override or correct the name.")
        if not isinstance(parameters, dict):
            raise FieldError("Series constraints", f"Series {text!r}: specify overrides by coefficient.")
        for name, options in parameters.items():
            if name not in by_name:
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name} is not a coefficient of this equation. "
                                 "Remove the override or restore the coefficient.")
            if not isinstance(options, dict) or set(options) - _OVERRIDE_KEYS:
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: use only fixed, lower, upper and initial.")
            coeff = by_name[name]
            if coeff.shared and ({"fixed", "initial"} & set(options)):
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: a shared coefficient cannot have its own fixed value "
                                 "or starting value. Set the common value on Parameters, or stop sharing it.")
            if coeff.fixed and ({"fixed", "initial"} & set(options)):
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: this coefficient is already fixed for every series. "
                                 "Remove the series override.")
            lo, hi = lower[text][name], upper[text][name]
            if "lower" in options:
                lo = max(lo, _finite_override(text, name, "lower", options["lower"]))
            if "upper" in options:
                hi = min(hi, _finite_override(text, name, "upper", options["upper"]))
            if not lo < hi:
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: the lower limit must be smaller than the upper limit.")
            lower[text][name], upper[text][name] = lo, hi
            common_fixed = fixed[text][name]
            if common_fixed is not None and not lo <= common_fixed <= hi:
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: the fixed value {common_fixed:g} lies outside its limits.")
            if "fixed" in options and "initial" in options:
                raise FieldError("Series constraints",
                                 f"Series {text!r}, {name}: a fixed coefficient does not need a starting value.")
            if "fixed" in options:
                value = _finite_override(text, name, "fixed", options["fixed"])
                if not lo <= value <= hi:
                    raise FieldError("Series constraints",
                                     f"Series {text!r}, {name}: the fixed value {value:g} lies outside its limits.")
                fixed[text][name] = value
            if "initial" in options:
                guess = _finite_override(text, name, "initial", options["initial"])
                if not lo <= guess <= hi:
                    raise FieldError("Series constraints",
                                     f"Series {text!r}, {name}: the starting value {guess:g} lies outside its limits.")
                starts[text][name] = guess
    for c in s.coefficients:
        if c.shared:
            lo = max(lower[label][c.name] for label in labels)
            hi = min(upper[label][c.name] for label in labels)
            if not lo < hi:
                raise FieldError("Series constraints",
                                 f"{c.name}: the shared limits do not overlap. Widen a series limit.")
            if not lo <= c.start <= hi:
                raise FieldError("Series constraints",
                                 f"{c.name}: the starting value {c.start:g} lies outside the shared limits. "
                                 "Change the start or the series limits.")
            for label in labels:
                lower[label][c.name], upper[label][c.name] = lo, hi
        elif not c.fixed:
            for label in labels:
                lo, hi = lower[label][c.name], upper[label][c.name]
                if c.name in conditioned and fixed[label][c.name] is None:
                    _free_conditions(SimpleNamespace(condition_parameters=(c.name,)), [c.name], label)
                if fixed[label][c.name] is None and not lo <= starts[label][c.name] <= hi:
                    raise FieldError("Series constraints",
                                     f"Series {label!r}, {c.name}: the starting value {starts[label][c.name]:g} "
                                     "lies outside the limits of this series.")
    return lower, upper, fixed, starts, names


def _layout(s, labels, lower, upper, fixed, starts):
    """Free coordinates: shared coefficients in declaration order, then each series' local ones."""
    coordinates, scale, bounds_lo, bounds_hi, seeds = [], [], [], [], []
    index = {name: j for j, name in enumerate(c.name for c in s.coefficients)}
    mapping = np.full((len(labels), len(s.coefficients)), -1, dtype=int)
    where = {label: i for i, label in enumerate(labels)}

    def add(scope, group, coeff, lo, hi, seed):
        mapping[where[group] if group is not None else slice(None), index[coeff.name]] = len(coordinates)
        coordinates.append((scope, group, coeff.name))
        unit = 1.0 if seed == 0 else abs(seed)
        scale.append(unit)
        bounds_lo.append(lo)
        bounds_hi.append(hi)
        seeds.append(seed)

    for coeff in s.coefficients:
        if coeff.shared and not coeff.fixed:
            add("Shared", None, coeff, lower[labels[0]][coeff.name], upper[labels[0]][coeff.name], coeff.start)
    for label in labels:
        for coeff in s.coefficients:
            if not coeff.shared and not coeff.fixed and fixed[label][coeff.name] is None:
                add("Local", label, coeff, lower[label][coeff.name], upper[label][coeff.name], starts[label][coeff.name])
    n_free = len(coordinates)
    return coordinates, mapping, np.asarray(scale, dtype=float), np.asarray(bounds_lo), np.asarray(bounds_hi), np.asarray(seeds)


def _interior(seed, lo, hi):
    """Trust-region starts on a bound take a negligible first step. Move just inside; the bound stays."""
    if lo < seed < hi:
        return seed
    if np.isfinite(lo) and np.isfinite(hi):
        return 0.5 * (lo + hi)
    offset = max(abs(lo if np.isfinite(lo) else hi), abs(seed), 1.0)
    moved = lo + 0.1 * offset if np.isfinite(lo) else hi - 0.1 * offset
    if not lo < moved < hi:
        raise FieldError("Parameters", "The limits leave no usable interior starting value.")
    return moved


def _defined(predicted, data, at_start):
    position = int(np.flatnonzero(~np.isfinite(predicted))[0])
    when = "with the starting values" if at_start else "at the solution"
    label = data["label"]
    raise FieldError("Equation", f"Group {label}: the equation is not defined {when} at "
                                 f"X = {data['X'][position]:g} (source row {data['rows'][position]}). "
                                 "Check divisions, logarithms and roots.")


def _condition_error(part, error):
    raise FieldError("Equation", f"Group {part['label']}: A condition of if(...) is not defined at "
                                 f"X = {error.x:g} (source row {_source(part['rows'][error.position])}): one side of "
                                 "a comparison is not a finite number. Check divisions, logarithms and roots in "
                                 "the condition.") from None


def _evaluate_part(compiled, part, parameters):
    """Predictions of one series; a condition that cannot be evaluated names its group and source row."""
    try:
        with np.errstate(all="ignore"):
            return np.asarray(compiled.evaluate(part["X"], parameters), dtype=float)
    except ConditionError as error:
        _condition_error(part, error)


def _arrays(groups):
    packed = []
    for label, data in groups:
        packed.append({
            "label": label,
            "X": data["X"].to_numpy(dtype=float),
            "Y": data["Y"].to_numpy(dtype=float),
            "SD": data["SD"].to_numpy(dtype=float) if "SD" in data else np.ones(len(data)),
            "rows": data.index.to_numpy(),
        })
    return packed


def _parameter_maps(s, labels, fixed, theta, mapping, scale):
    """One value per coefficient per series, from the free vector and the fixed numbers."""
    original = theta * scale
    maps = []
    for i, label in enumerate(labels):
        values = {}
        for j, coeff in enumerate(s.coefficients):
            slot = mapping[i, j]
            if slot >= 0:
                values[coeff.name] = float(original[slot])
            elif fixed[label][coeff.name] is not None:
                values[coeff.name] = float(fixed[label][coeff.name])
            else:
                values[coeff.name] = coeff.start
        maps.append(values)
    return maps


def _rank_and_covariance(jacobian, scale, wsse, factor, df):
    norms = np.linalg.norm(jacobian, axis=0)
    if not np.isfinite(jacobian).all() or not np.isfinite(norms).all() or np.any(norms == 0):
        raise FieldError("Parameters", "The coefficients are not identifiable from these data (the Jacobian is "
                                       "rank deficient). Fix or remove coefficients, or check the equation.")
    _, singular, vt = np.linalg.svd(jacobian / norms, full_matrices=False)
    if singular[-1] <= RANK_TOLERANCE * singular[0]:
        raise FieldError("Parameters", "The coefficients are not identifiable from these data (the Jacobian is "
                                       "rank deficient). Fix or remove coefficients, or check the equation.")
    inverse = ((vt.T * (1.0 / singular**2)) @ vt) / np.outer(norms, norms)
    covariance = inverse * np.outer(scale, scale) * (wsse / factor**2) / df
    if not np.isfinite(covariance).all() or np.any(np.diag(covariance) < 0):
        raise FieldError("Parameters", "The covariance of the global fit exceeds the numerical range.")
    return covariance


def _active(values, lower, upper, se):
    typical = np.maximum(np.abs(values), 0.0 if se is None else se)
    mask = np.zeros(len(values), dtype=bool)
    for bound in (lower, upper):
        finite = np.isfinite(bound)
        margin = BOUND_MARGIN * np.maximum(typical[finite], np.abs(bound[finite]))
        mask[finite] |= np.abs(values[finite] - bound[finite]) <= margin
    return mask


def _minimize(residual, start, lower, upper, *, max_evaluations=MAX_EVALUATIONS, method="trf"):
    message = ("The fit did not converge. Change the starting values or limits, or fix some coefficients.")
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        try:
            solution = optimize.least_squares(
                residual, start, bounds=(lower, upper), jac="3-point", x_scale="jac", method=method,
                max_nfev=max_evaluations, ftol=TOLERANCE if method == "trf" else None,
                xtol=TOLERANCE, gtol=TOLERANCE)
        except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as error:
            raise FieldError("Parameters", message) from error
    if not solution.success or not np.isfinite(solution.x).all():
        raise FieldError("Parameters", message)
    return solution


def _polish(residual, solution, lower, upper):
    # Same short dogbox step as global_fit: trf can stop about sqrt(tol) short of a bound.
    slope = np.linalg.norm(solution.jac, axis=0)
    threshold = 4 * np.sqrt(TOLERANCE * max(1.0, solution.cost))
    for distance, gradient in ((solution.x - lower, solution.grad), (upper - solution.x, -solution.grad)):
        if np.any((distance > 0) & (distance * slope <= threshold) & (gradient > 0)):
            return _minimize(residual, solution.x, lower, upper, max_evaluations=100, method="dogbox")
    return solution


def _solve(compiled, packed, s, labels, lower, upper, fixed, starts, *, cancel=None):
    """Joint least squares. ``packed`` rows stay in source order inside each series."""
    coordinates, mapping, scale, bound_lo, bound_hi, seeds = _layout(s, labels, lower, upper, fixed, starts)
    n_obs = sum(len(part["X"]) for part in packed)
    n_free = len(coordinates)
    if n_free and n_obs <= n_free:
        raise FieldError("Parameters", f"{n_obs} complete rows cannot estimate {n_free} free coefficients; "
                                       "fix some coefficients or add data.")
    if n_obs * n_free > MAX_FREE_CELLS:
        raise FieldError("Parameters", "The global fit exceeds the dense Jacobian budget. "
                                       "Use fewer rows or share more coefficients.")
    xs = [part["X"] for part in packed]
    ys = [part["Y"] for part in packed]
    sds = [part["SD"] for part in packed]
    y = np.concatenate(ys)
    sd = np.concatenate(sds)
    sd_max = float(np.max(sd))
    sd_unit = sd / sd_max
    with np.errstate(all="ignore"):
        reference = float(np.max(np.abs(y / sd_unit))) if len(y) else 0.0
    # Divisor of the normalised residual. ``factor`` converts it back to the typed SD.
    factor_holder = {"value": 1.0}

    def predict_all(values):
        maps = _parameter_maps(s, labels, fixed, values, mapping, scale)
        pieces = []
        for part, parameters in zip(packed, maps):
            with np.errstate(all="ignore"):
                pieces.append(np.asarray(compiled.evaluate(part["X"], parameters), dtype=float))
        return maps, pieces

    def residual(values):
        if cancel is not None and cancel.is_set():
            raise MonteCarloCancelled('Parameter profile calculation cancelled.')
        _, pieces = predict_all(values)
        stacked = np.concatenate(pieces) if pieces else np.empty(0)
        value = (y - stacked) / (sd_unit * factor_holder["reference"])
        return np.where(np.isfinite(value), value, 1e150)

    # Conditions read X and fixed values only: checked once here, they hold for every step of the solver.
    for part, parameters in zip(packed, _parameter_maps(s, labels, fixed, seeds / scale if n_free else np.empty(0),
                                                        mapping, scale)):
        _evaluate_part(compiled, part, parameters)
    if reference == 0:
        _, pieces = predict_all(seeds / scale if n_free else np.empty(0))
        with np.errstate(all="ignore"):
            guess = np.concatenate(pieces) if pieces else np.empty(0)
            reference = float(np.max(np.abs(guess / sd_unit))) if len(guess) else 0.0
    if not np.isfinite(reference) or reference == 0:
        reference = 1.0
    factor_holder["reference"] = reference
    factor = reference / sd_max
    start = np.array([_interior(seed, lo, hi) for seed, lo, hi in zip(seeds, bound_lo, bound_hi)], dtype=float)
    # Normalised bounds. An infinite limit stays infinite.
    lower_u = np.divide(bound_lo, scale, out=np.full(n_free, -np.inf), where=np.isfinite(bound_lo))
    upper_u = np.divide(bound_hi, scale, out=np.full(n_free, np.inf), where=np.isfinite(bound_hi))
    # Seeds were in original units; the solver moves theta / scale.
    start_u = start / scale if n_free else start
    if n_free:
        # Confirm the starting point itself is defined, before the solver replaces bad steps.
        _, pieces = predict_all(seeds / scale)
        stacked = np.concatenate(pieces)
        if not np.isfinite(stacked).all():
            offset = 0
            for part, piece in zip(packed, pieces):
                if not np.isfinite(piece).all():
                    _defined(piece, part, True)
            _defined(stacked, packed[0], True)
        solution = _polish(residual, _minimize(residual, start_u, lower_u, upper_u), lower_u, upper_u)
        values, jacobian = solution.x, solution.jac
    else:
        values, jacobian = np.empty(0), np.empty((n_obs, 0))
    maps, pieces = predict_all(values)
    for part, piece in zip(packed, pieces):
        if len(piece) and not np.isfinite(piece).all():
            _defined(piece, part, False)
    predicted = np.concatenate(pieces) if pieces else np.empty(0)
    resid = y - predicted
    weighted = resid / sd
    rss = float(resid @ resid)
    wsse = float(weighted @ weighted)
    if not np.isfinite([rss, wsse]).all():
        raise FieldError("Parameters", "The residual sum of squares exceeds the numerical range.")
    df = n_obs - n_free
    normalised = residual(values) if n_obs else np.empty(0)
    # Replace the sentinel used for rejected steps: at the solution every residual must be real.
    if n_obs and not np.isfinite((y - predicted) / (sd_unit * reference)).all():
        raise FieldError("Equation", "The equation is not defined at the solution.")
    numerical_zero = bool(n_free) and float(normalised @ normalised) <= ROUND_OFF * n_obs
    if numerical_zero:
        rss, wsse = 0.0, 0.0
    has_variance = bool(n_free) and not numerical_zero
    if n_free:
        covariance = _rank_and_covariance(jacobian, scale, wsse, factor, df)
        se_u = np.sqrt(np.diag(covariance)) / scale
        active = _active(values, lower_u, upper_u, se_u if has_variance else None)
    else:
        covariance = np.empty((0, 0))
        active = np.zeros(0, dtype=bool)
    # Search units from the same joint Jacobian, before the conservative Wald
    # rule suppresses the covariance at a bound. Never use them as reported SEs.
    profile_units = np.sqrt(np.diag(covariance)).copy() if s.intervals == PROFILE else None
    infer = bool(n_free) and has_variance and not active.any()
    if n_free and not infer:
        covariance = np.full((n_free, n_free), np.nan)
    se = np.sqrt(np.diag(covariance)) if n_free else np.empty(0)
    if not infer:
        se = np.full(n_free, np.nan)
    if not n_free:
        reason = "Every coefficient is fixed. The curve and residuals are evaluated; there are no standard errors or intervals."
    elif active.any():
        reason = ("A coefficient is at a bound. Standard errors, confidence intervals and the covariance "
                  "are omitted for every free coefficient.")
    elif not has_variance:
        reason = ("Residual variance is within round-off of zero on the normalised objective "
                  "(the larger of (64 machine eps) squared and the solver tolerance squared, "
                  "times the number of observations, with no absolute threshold in units of Y). "
                  "Intervals are omitted.")
    else:
        reason = "Asymptotic t intervals from the joint weighted Jacobian at the chosen confidence level."
    half = float(stats.t.ppf((1 + s.level / 100) / 2, df)) if infer and df > 0 else np.nan
    return {
        "maps": maps, "pieces": pieces, "coordinates": coordinates, "active": active, "covariance": covariance,
        "se": se, "half": half, "rss": rss, "wsse": wsse, "n": n_obs, "p": n_free, "df": df, "infer": infer,
        "reason": reason, "scale": scale, "values": values,
        # Context for response bands: coordinate of each (series, coefficient), physical limits per coordinate.
        "mapping": mapping, "names": [c.name for c in s.coefficients], "bounds": (bound_lo, bound_hi),
        "profile_units": profile_units,
    }


def _source(value):
    return value.item() if hasattr(value, "item") else value


def _curve(compiled, parameters, x, points, label=None):
    grid = np.linspace(float(np.min(x)), float(np.max(x)), points)
    try:
        with np.errstate(all="ignore"):
            predicted = np.asarray(compiled.evaluate(grid, parameters), dtype=float)
    except ConditionError as error:
        prefix = "" if label is None else f"Group {label}: "
        raise FieldError("Equation", f"{prefix}A condition of if(...) is not defined on the drawn curve at "
                                     f"X = {error.x:g}.") from None
    if not np.isfinite(predicted).all():
        bad = int(np.flatnonzero(~np.isfinite(predicted))[0])
        raise FieldError("Equation", f"The equation is not defined on the drawn curve at X = {grid[bad]:g}.")
    return grid, predicted


def _queries(frame, s, labels):
    """Active query rows (empty without Predict responses) and how many need an interval."""
    if s.queries is None:
        return None, 0
    rows = uncertainty.prepare_queries(frame, s.queries, s.group, labels)
    return rows, len(rows) if s.queries.interval != uncertainty.NONE else 0


def _tables(compiled, packed, solved, s, queries=None):
    rows = []
    # Shared free coefficients, then each series (local and individually fixed), then common fixed values.
    seen = set()
    for scope, group, name in solved["coordinates"]:
        slot = solved["coordinates"].index((scope, group, name))
        estimate = float(solved["values"][slot] * solved["scale"][slot])
        status = "At bound" if solved["active"][slot] else "Estimated"
        se = float(solved["se"][slot])
        half = solved["half"]
        rows.append({"Scope": scope, "Group": group, "Parameter": name, "Estimate": estimate, "SE": se,
                     "CI low": estimate - half * se, "CI high": estimate + half * se, "Status": status})
        seen.add((scope, group, name))
    for part, parameters in zip(packed, solved["maps"]):
        for coeff in s.coefficients:
            if coeff.shared or coeff.fixed:
                continue
            key = ("Fixed", part["label"], coeff.name)
            if key in seen or any(row["Parameter"] == coeff.name and row["Group"] == part["label"]
                                  for row in rows):
                continue
            rows.append({"Scope": "Fixed", "Group": part["label"], "Parameter": coeff.name,
                         "Estimate": parameters[coeff.name], "SE": np.nan, "CI low": np.nan, "CI high": np.nan,
                         "Status": "Fixed"})
    for coeff in s.coefficients:
        if coeff.fixed:
            rows.append({"Scope": "Fixed", "Group": None, "Parameter": coeff.name, "Estimate": coeff.start,
                         "SE": np.nan, "CI low": np.nan, "CI high": np.nan, "Status": "Fixed"})
    parameters = pd.DataFrame(rows, columns=["Scope", "Group", "Parameter", "Estimate", "SE", "CI low", "CI high", "Status"])
    summary = _report({
        "Observations": solved["n"], "Series": len(packed), "Free parameters": solved["p"],
        "DF residual": solved["df"], "Residual SS": solved["rss"], "Weighted residual SS": solved["wsse"],
        LEVEL: s.level, "Weighting": s.weighting, "Inference": solved["reason"], "Equation": s.equation,
    })
    if solved["coordinates"]:
        index = pd.MultiIndex.from_tuples(solved["coordinates"], names=_INDEX)
        covariance = pd.DataFrame(solved["covariance"], index=index, columns=index)
    else:
        empty = pd.MultiIndex.from_arrays([[], [], []], names=_INDEX)
        covariance = pd.DataFrame(index=empty, columns=empty)
    residual_rows, curve_rows, curves, branches = [], [], [], []
    for part, parameters_map, piece in zip(packed, solved["maps"], solved["pieces"]):
        for row, x, y, pred, scale in zip(part["rows"], part["X"], part["Y"], piece, part["SD"]):
            residual_rows.append({"Source row": _source(row), "Group": part["label"], "X": float(x), "Y": float(y),
                                  "Predicted": float(pred), "Residual": float(y - pred),
                                  "SD": 1.0 if s.sd is None else float(scale)})
        grid, curve = _curve(compiled, parameters_map, part["X"], s.points, part["label"])
        curves.append((part["label"], grid, curve))
        if s.syntax == CONDITIONAL:
            # Path labels, not estimates; the fixed thresholds decide them.
            codes = compiled.branch_codes(grid, parameters_map)
            branches.append(codes)
            for x, pred, code in zip(grid, curve, codes):
                curve_rows.append({"Group": part["label"], "X": float(x), "Predicted": float(pred),
                                   BRANCH: int(code)})
        else:
            for x, pred in zip(grid, curve):
                curve_rows.append({"Group": part["label"], "X": float(x), "Predicted": float(pred)})
    tables = {
        "Parameters": parameters,
        "Global fit": summary,
        "Covariance": covariance,
        "Residuals": pd.DataFrame(residual_rows),
        "Curve": pd.DataFrame(curve_rows),
    }
    drawn = None
    if s.band != uncertainty.NONE:
        bands, settings, drawn = uncertainty.band_tables(compiled, solved, curves, s.band, s.response_level)
        if branches:
            # The band follows the branches of its curve: no polygon or edge crosses a jump.
            bands.insert(bands.columns.get_loc("Predicted") + 1, BRANCH, np.concatenate(branches).astype(int))
            drawn = [(label, *curve_with_breaks(grid, lower, codes), curve_with_breaks(grid, upper, codes)[1])
                     for (label, grid, lower, upper), codes in zip(drawn, branches)]
        tables[uncertainty.BANDS_SHEET] = bands
        tables[uncertainty.BAND_SETTINGS_SHEET] = settings
    if queries is not None:
        tables[uncertainty.PREDICTIONS_SHEET] = uncertainty.prediction_table(compiled, solved, packed, queries,
                                                                             s.queries)
    figure, axes = _plot("Global fit custom equation", s.x, s.y)
    lines = []
    for index, (part, (_, grid, curve)) in enumerate(zip(packed, curves)):
        color = axes._get_lines.get_next_color()
        axes.scatter(part["X"], part["Y"], color=color, label=part["label"])
        if branches:
            # Separators only in the drawn line; the Curve sheet keeps the sampled points.
            grid, curve = curve_with_breaks(grid, curve, branches[index])
        lines.extend(axes.plot(grid, curve, color=color))
    if drawn is not None:
        uncertainty.draw_bands(axes, drawn, lines, s.drawing)
    axes.legend()
    return Result(tables, figure)


def check_options(frame, options):
    """Names, syntax, limits, series and the budget. Evaluates the start, and does not fit."""
    s = resolve(frame, options)
    groups = prepare(frame, s)
    labels = [label for label, _ in groups]
    lower, upper, fixed, starts, _ = _bind(s, labels)
    coordinates, *_rest = _layout(s, labels, lower, upper, fixed, starts)
    n_obs = sum(len(data) for _, data in groups)
    n_free = len(coordinates)
    if s.intervals == PROFILE:
        from .global_custom_profiles import check_budget
        check_budget(n_obs, n_free)
    if n_free and n_obs <= n_free:
        raise FieldError("Parameters", f"{n_obs} complete rows cannot estimate {n_free} free coefficients; "
                                       "fix some coefficients or add data.")
    if n_obs * n_free > MAX_FREE_CELLS:
        raise FieldError("Parameters", "The global fit exceeds the dense Jacobian budget. "
                                       "Use fewer rows or share more coefficients.")
    _, propagated = _queries(frame, s, [label for label, _ in groups])
    uncertainty.check_budget(len(groups), s.points, s.band, propagated, n_free)
    compiled = compile_equation(s.equation, [c.name for c in s.coefficients], syntax=s.syntax)
    packed = _arrays(groups)
    scale = _rest[1]
    mapping = _rest[0]
    seeds = _rest[4]
    maps = _parameter_maps(s, labels, fixed, seeds / scale if n_free else np.empty(0), mapping, scale)
    for part, parameters in zip(packed, maps):
        predicted = _evaluate_part(compiled, part, parameters)
        if len(predicted) and not np.isfinite(predicted).all():
            _defined(predicted, part, True)
    return s


def series_in(frame, options):
    """Series labels for the dialog. Column problems return no labels; the engine names them on Run."""
    try:
        s = resolve(frame, options)
        return [label for label, _ in prepare(frame, s)]
    except (ValueError, OverflowError):
        return []


def global_custom_fit(frame, options, *, cancel=None):
    """The analysis behind ``analyse("Global fit custom equation", …)``."""
    s = resolve(frame, options)
    groups = prepare(frame, s)
    labels = [label for label, _ in groups]
    lower, upper, fixed, starts, _ = _bind(s, labels)
    queries, propagated = _queries(frame, s, labels)
    coordinates = _layout(s, labels, lower, upper, fixed, starts)[0]
    budget = None
    if s.intervals == PROFILE:
        from .global_custom_profiles import check_budget
        check_budget(sum(len(data) for _, data in groups), len(coordinates))
        budget = ProfileBudget(cancel)
        if cancel is not None and cancel.is_set():
            raise MonteCarloCancelled('Parameter profile calculation cancelled.')
    uncertainty.check_budget(len(groups), s.points, s.band, propagated, len(coordinates))
    compiled = compile_equation(s.equation, [c.name for c in s.coefficients], syntax=s.syntax)
    packed = _arrays(groups)
    solved = _solve(compiled, packed, s, labels, lower, upper, fixed, starts,
                    cancel=cancel if s.intervals == PROFILE else None)
    result = _tables(compiled, packed, solved, s, queries)
    if s.intervals == PROFILE:
        from .global_custom_profiles import apply_profiles
        apply_profiles(result, solved, s, compiled, packed, budget)
    return result
