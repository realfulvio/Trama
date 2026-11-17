"""Fit custom equation: least squares for an equation typed by the user (0.61).

One predictor X, one response Y, optional grouping with an independent fit per group. Coefficients are
free or fixed, with optional bounds and starting values. Intervals are asymptotic t intervals from the
scaled Jacobian at the solution, or optional extra-SS profile intervals. The equation text is
parsed by :mod:`custom_equations`; nothing user-written is ever executed, and the recipe stores only
plain numbers, strings and booleans.

Conventions fixed by this module (documented in the pull request):

* objective: sum(((Y - f(X)) / SD) ** 2) with SD = 1 when unweighted, solved by
  ``scipy.optimize.least_squares`` (trf, bounds, 3-point Jacobian) with at most ``MAX_EVALUATIONS``
  residual evaluations (the finite-difference Jacobian is not counted) and tolerances ``TOLERANCE``;
* an optimizer that does not converge inside the budget is an error on Parameters, not a result;
* Jacobian rank: columns are scaled to unit length and the fit is rejected when the smallest singular
  value is at most ``RANK_TOLERANCE`` times the largest (or a column is zero);
* the solver works on a normalised problem so that its absolute tolerances cannot depend on units:
  residuals are divided by ``SD' * reference`` with ``SD' = SD / max(SD)`` and ``reference = max|Y / SD'|``
  (the common factor of the SD column cancels exactly, and the response is of order one; when Y is
  identically zero the reference is the size of the predictions at the starting values, then 1), and
  each free coefficient is optimised as ``theta / scale`` with ``scale = |start|`` (1 for a zero start).
  Covariance and SE are transformed back to the original units; "Weighted residual SS" is always reported with the SD as given;
* a free coefficient within ``BOUND_TOLERANCE`` of a limit, measured in the units of the coefficient
  against max(|estimate|, |limit|, SE) and with no absolute floor, keeps its estimate but has no SE or
  interval, and its Status is "At bound".
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import least_squares

from .custom_equations import MAX_PARAMETERS, check_name, compile_equation
from .field_error import FieldError
from .fit_weights import INVERSE_VARIANCE, UNWEIGHTED
from .reporting import Result, _plot, _report
from .parameter_intervals import (METHOD as INTERVAL_METHOD, METHODS as INTERVAL_METHODS,
                                  WALD, PROFILE, MAX_PARAMETERS as PROFILE_PARAMETERS,
                                  MAX_POINTS as PROFILE_POINTS, ProfileBudget)

CUSTOM_EQUATION = "Fit custom equation"
PARAMETER_LIST = "Coefficient list"  # Dialog kind of the Parameters field.
EQUATION_TEXT = "Equation text"  # Dialog kind of the Equation field.
WEIGHTINGS = (UNWEIGHTED, INVERSE_VARIANCE)
LEVEL, POINTS, SD_COLUMN = "Confidence level (%)", "Curve points", "SD column"
DEFAULT_LEVEL, DEFAULT_POINTS = 95.0, 201
MIN_POINTS, MAX_POINTS = 20, 10_000
MAX_GROUPS, MAX_PAIRS = 12, 100_000
MAX_EVALUATIONS, TOLERANCE = 5_000, 1e-12
RANK_TOLERANCE, BOUND_TOLERANCE = 1e-8, 1e-8
EXAMPLE_PARAMETERS = ({"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                      {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False})
DEFAULT_EQUATION = "A + B*X"
# "Optional" is the dialog's own kind name for an optional column (see workbench).
OPTIONS = {"X": None, "Y": None, "Group": "Optional", "Equation": EQUATION_TEXT, "Parameters": PARAMETER_LIST,
           "Weighting": WEIGHTINGS, SD_COLUMN: "Optional", INTERVAL_METHOD: INTERVAL_METHODS,
           LEVEL: DEFAULT_LEVEL, POINTS: DEFAULT_POINTS}
TABS = {"Equation": ("Equation",), "Parameters": ("Parameters",), "Output": (INTERVAL_METHOD, LEVEL, POINTS)}


@dataclass(frozen=True)
class Coefficient:
    name: str
    start: float
    lower: float | None
    upper: float | None
    fixed: bool


@dataclass(frozen=True)
class Settings:
    x: str
    y: str
    group: str | None
    sd: str | None
    equation: str
    coefficients: tuple
    weighting: str
    level: float
    points: int
    intervals: str


def _number(value):
    return not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.integer, np.floating))


def _bound(value, name, which):
    if value is None or value == "":
        return None
    if not _number(value) or not np.isfinite(value):
        raise FieldError("Parameters", f"{name}: the {which} limit must be a finite number or empty.")
    return float(value)


def _where(label, message):
    """Messages about one group start with its name; the single unnamed group is All."""
    return message if label == "All" else f"Group {label}: {message}"


def coefficients_from(records):
    """Validate the Parameters recipe field: names, finite starts, strict limits, feasible values."""
    if not isinstance(records, (list, tuple)):
        raise FieldError("Parameters", "Parameters must be a list of coefficients.")
    if len(records) > MAX_PARAMETERS:
        raise FieldError("Parameters", f"Use at most {MAX_PARAMETERS} coefficients.")
    found, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            raise FieldError("Parameters", "Each coefficient needs a name, a starting value and its limits.")
        name = record.get("name")
        check_name(name)
        if name in seen:
            raise FieldError("Parameters", f"The coefficient {name} appears more than once.")
        seen.add(name)
        fixed = record.get("fixed", False)
        if not isinstance(fixed, (bool, np.bool_)):
            raise FieldError("Parameters", f"{name}: Fixed must be true or false.")
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
        found.append(Coefficient(name, start, lower, upper, bool(fixed)))
    return tuple(found)


def resolve(frame, options):
    """Validate the recipe against the columns of ``frame`` and return Settings. No data values are read."""
    columns = list(frame.columns)
    x, y, group, sd = options.get("X"), options.get("Y"), options.get("Group") or None, options.get(SD_COLUMN) or None
    for field, column in (("X", x), ("Y", y)):
        if column not in columns:
            raise FieldError(field, f"Choose an existing column for {field}.")
    if x == y:
        raise FieldError("Y", "Select distinct columns for X and Y.")
    if group is not None and (group not in columns or group in (x, y)):
        raise FieldError("Group", "Group must be an existing column different from X and Y.")
    weighting = options.get("Weighting", UNWEIGHTED)
    if weighting not in WEIGHTINGS:
        raise FieldError("Weighting", "Choose Unweighted or Inverse variance (column).")
    if weighting == INVERSE_VARIANCE:
        if sd is None or sd not in columns:
            raise FieldError(SD_COLUMN, "Choose the column with the relative standard deviations.")
        if sd in (x, y, group):
            raise FieldError(SD_COLUMN, "The SD column must differ from X, Y and Group.")
    else:
        sd = None
    level = options.get(LEVEL, DEFAULT_LEVEL)
    if not _number(level) or not 0 < level < 100:
        raise FieldError(LEVEL, "The confidence level must be between 0 and 100 (exclusive).")
    points = options.get(POINTS, DEFAULT_POINTS)
    # Finiteness first: int(nan) and int(inf) raise ValueError/OverflowError that carry no field.
    if (not _number(points) or not np.isfinite(points) or points != int(points)
            or not MIN_POINTS <= points <= MAX_POINTS):
        raise FieldError(POINTS, f"Curve points must be a whole number from {MIN_POINTS} to {MAX_POINTS}.")
    coefficients = coefficients_from(options.get("Parameters", ()))
    intervals = options.get(INTERVAL_METHOD, WALD)
    if intervals not in INTERVAL_METHODS:
        raise FieldError(INTERVAL_METHOD, "Choose Symmetric (Wald) or Profile likelihood.")
    if intervals == PROFILE and sum(not c.fixed for c in coefficients) > PROFILE_PARAMETERS:
        raise FieldError(INTERVAL_METHOD, f"Profile intervals support at most {PROFILE_PARAMETERS} free parameters per fit.")
    equation = options.get("Equation")
    compile_equation(equation, [c.name for c in coefficients])
    return Settings(x, y, group, sd, equation.strip(), coefficients, weighting, float(level), int(points), intervals)


def _values(series, field, label, rows):
    """Floats from a column: empty cells stay missing, text and infinity are errors, never imputed."""
    values = pd.to_numeric(series, errors="coerce")
    text = rows & series.notna() & values.isna()
    if text.any():
        raise FieldError(field, f"Column {label} contains non-numeric values (first at source row "
                                f"{series.index[text][0]}).")
    values = values.astype(float)
    if (rows & np.isinf(values)).any():
        raise FieldError(field, f"Column {label} contains infinite values.")
    return values


def prepare(frame, s):
    """Complete rows per group, keeping the source order and index. Returns [(label, data, skipped)]."""
    if s.group is None:
        rows, levels = pd.Series(True, index=frame.index), [("All", None)]
    else:
        rows = frame[s.group].notna()
        distinct = list(pd.unique(frame.loc[rows, s.group]))
        labels = [str(level) for level in distinct]
        if len(set(labels)) != len(labels):
            raise FieldError("Group", "Different group values look the same as text; make them distinct first.")
        if len(labels) > MAX_GROUPS:
            raise FieldError("Group", f"Use at most {MAX_GROUPS} groups.")
        if not labels:
            raise FieldError("Group", "The group column has no values.")
        levels = list(zip(labels, distinct))
    x, y = _values(frame[s.x], "X", s.x, rows), _values(frame[s.y], "Y", s.y, rows)
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
    for label, level in levels:
        member = rows if level is None else rows & (frame[s.group] == level)
        keep = member & used
        data = pd.DataFrame({"X": x[keep], "Y": y[keep]})
        if sd is not None:
            data["SD"] = sd[keep]
        if s.intervals == PROFILE and any(not c.fixed for c in s.coefficients) and len(data) > PROFILE_POINTS:
            raise FieldError(INTERVAL_METHOD, f"Profile intervals support at most {PROFILE_POINTS} complete observations per fit.")
        groups.append((label, data, int((member & ~used).sum())))
    return groups


def _undefined(label, data, predicted, at_start):
    position = int(np.flatnonzero(~np.isfinite(predicted))[0])
    when = "with the starting values" if at_start else "at the solution"
    return FieldError("Equation", _where(label, f"The equation is not defined {when} at X = {data['X'].iloc[position]:g} "
                                                f"(source row {data.index[position]}). Check divisions, logarithms and roots."))


def check_domain(frame, s):
    """Dialog check: parse, then evaluate at the starting values on every used X. Never runs a fit."""
    compiled = compile_equation(s.equation, [c.name for c in s.coefficients])
    start = {c.name: c.start for c in s.coefficients}
    for label, data, _ in prepare(frame, s):
        if len(data):
            predicted = compiled.evaluate(data["X"].to_numpy(), start)
            if not np.isfinite(predicted).all():
                raise _undefined(label, data, predicted, True)
    return compiled


def check_options(frame, options):
    """Everything detectable before the worker runs; the dialog calls this from Check equation and OK."""
    s = resolve(frame, options)
    check_domain(frame, s)
    return s


def _fit_group(label, data, s, compiled):
    x, y = data["X"].to_numpy(), data["Y"].to_numpy()
    sd = data["SD"].to_numpy() if "SD" in data else np.ones(len(data))
    free = [c for c in s.coefficients if not c.fixed]
    fixed = {c.name: c.start for c in s.coefficients if c.fixed}
    n, p = len(data), len(free)
    if n == 0:
        raise FieldError("Y", _where(label, "No complete X and Y pairs."))
    if p and n <= p:
        raise FieldError("Parameters", _where(label, f"{n} complete rows cannot estimate {p} free coefficients; "
                                                     "fix some coefficients or add data."))

    def predicted(theta):
        return compiled.evaluate(x, {**fixed, **dict(zip((c.name for c in free), theta))})

    # Normalised problem (see the module docstring). The SD column is first divided by its largest value, a
    # finite common factor, so everything below is independent of the unit in which the relative SDs were
    # typed. Then the response scale is chosen: max|Y / SD| when Y is not identically zero, otherwise the
    # size of the predictions at the starting values, and 1 as the last resort. None of the three depends on
    # the common factor of SD, and the divisor stays fixed for the whole fit.
    start = np.array([c.start for c in free], dtype=float)
    scale = np.where(start == 0, 1.0, np.abs(start))
    sd_unit = sd / np.max(sd)
    with np.errstate(all="ignore"):
        reference = float(np.max(np.abs(y / sd_unit)))
        if reference == 0:
            reference = float(np.max(np.abs(predicted(start) / sd_unit)))
    if not np.isfinite(reference) or reference == 0:
        reference = 1.0
    divisor = sd_unit * reference
    # divisor = sd * factor: the normalised residual SS is the SD-weighted one divided by factor ** 2.
    factor = reference / float(np.max(sd))

    def residuals(u):
        value = (y - predicted(u * scale)) / divisor
        # A trial step outside the domain is rejected by a huge residual instead of poisoning the solver.
        return np.where(np.isfinite(value), value, 1e150)

    first = (y - predicted(start)) / sd
    if not np.isfinite(first).all():
        raise _undefined(label, data, y - predicted(start), True)
    converged = "Not applicable"
    jacobian = np.empty((n, 0))
    theta = start
    if p:
        lower = np.array([-np.inf if c.lower is None else c.lower for c in free]) / scale
        upper = np.array([np.inf if c.upper is None else c.upper for c in free]) / scale
        solution = least_squares(residuals, start / scale, bounds=(lower, upper), method="trf", jac="3-point",
                                 x_scale="jac", xtol=TOLERANCE, ftol=TOLERANCE, gtol=TOLERANCE,
                                 max_nfev=MAX_EVALUATIONS)
        if solution.status <= 0:
            raise FieldError("Parameters", _where(label, f"The fit did not converge within {MAX_EVALUATIONS:,} "
                                                         "evaluations. Change the starting values or limits, "
                                                         "or fix some coefficients."))
        theta, jacobian, converged = solution.x * scale, solution.jac, True
    fitted = predicted(theta)
    if not np.isfinite(fitted).all():
        raise _undefined(label, data, fitted, False)
    resid = y - fitted
    weighted = resid / sd
    wsse, df = float(np.sum(weighted ** 2)), n - p
    estimates = {c.name: c.start for c in s.coefficients}
    estimates.update({c.name: float(v) for c, v in zip(free, theta)})
    status, notes = {c.name: "Fixed" if c.fixed else "Free" for c in s.coefficients}, []
    se = {c.name: np.nan for c in s.coefficients}
    if p:
        norm = np.linalg.norm(jacobian, axis=0)
        suggestion = _where(label, "The coefficients are not identifiable from these data (the Jacobian is "
                                   "rank deficient). Fix or remove coefficients, or check the equation.")
        if not np.isfinite(jacobian).all() or (norm == 0).any():
            raise FieldError("Parameters", suggestion)
        singular = np.linalg.svd(jacobian / norm, compute_uv=False)
        if singular[-1] <= RANK_TOLERANCE * singular[0]:
            raise FieldError("Parameters", suggestion)
        # The Jacobian is of the normalised residuals with respect to theta / scale. Its inverse cross-product
        # times the normalised residual SS / df is the covariance of theta / scale; scaling it by the
        # coefficient scales returns the covariance in the original units. The normalising factor cancels, so
        # this is the usual inv(J'J) * WSSE / df of the unnormalised problem.
        scaled = np.linalg.inv((jacobian / norm).T @ (jacobian / norm)) / np.outer(norm, norm)
        covariance = scaled * np.outer(scale, scale) * (wsse / factor ** 2) / df
        for c, value in zip(free, np.sqrt(np.diag(covariance))):
            se[c.name] = float(value)
        for c in free:
            typical = max(abs(estimates[c.name]), se[c.name])
            for limit, word in ((c.lower, "lower"), (c.upper, "upper")):
                margin = BOUND_TOLERANCE * max(typical, abs(limit)) if limit is not None else 0.0
                if limit is not None and abs(estimates[c.name] - limit) <= margin:
                    status[c.name] = "At bound"
                    se[c.name] = np.nan
                    inference_note = ("no Wald SE is reported for it; see the profile endpoint status."
                                      if s.intervals == PROFILE else "no SE or interval is reported for it.")
                    notes.append(f"{c.name} is at its {word} limit ({limit:g}); {inference_note}")
    half = stats.t.ppf((1 + s.level / 100) / 2, df) if df > 0 else np.nan
    names = [c.name for c in s.coefficients]
    parameters = pd.DataFrame({
        "Estimate": [estimates[name] for name in names], "SE": [se[name] for name in names],
        "CI lower": [estimates[name] - half * se[name] for name in names],
        "CI upper": [estimates[name] + half * se[name] for name in names],
        "Status": [status[name] for name in names]}, index=pd.Index(names, name="Parameter"))
    summary = {"N": n, "Free parameters": p, "df": df, "Residual SS": float(np.sum(resid ** 2)),
               "Weighted residual SS": wsse}
    if df > 0:
        summary["Weighted residual SD" if "SD" in data else "Residual SD"] = float(np.sqrt(wsse / df))
    summary.update({"Equation": s.equation, "Weighting": s.weighting, LEVEL: s.level, "Skipped rows": None,
                    "Converged": converged})
    if notes:
        summary["Note"] = " ".join(notes)
    residual_table = pd.DataFrame({"X": x, "Observed": y, "Predicted": fitted, "Residual": resid,
                                   "Weighted residual": weighted},
                                  # A plain Index, never a RangeIndex: Use Result as Data keeps the source rows.
                                  index=pd.Index(data.index.to_numpy(), name="Source row"))
    grid = np.linspace(x.min(), x.max(), s.points)
    curve = compiled.evaluate(grid, estimates)
    if not np.isfinite(curve).all():
        bad = int(np.flatnonzero(~np.isfinite(curve))[0])
        raise FieldError("Equation", _where(label, f"The equation is not defined on the drawn curve at X = {grid[bad]:g}."))
    fit = {"parameters": parameters, "summary": summary, "residuals": residual_table,
           "curve": pd.DataFrame({"X": grid, "Predicted": curve}), "data": data}
    if s.intervals == PROFILE and p:
        # Curvature supplies search units even when a coefficient is on a
        # bound. Its displayed Wald SE remains unavailable; a one-sided
        # profile still refits all nuisance coefficients inside their limits.
        fit["profile_units"] = np.sqrt(np.diag(covariance))
    return fit


def _title(text):
    return "Custom equation: " + (text if len(text) <= 70 else text[:67] + "…")


def custom_fit(frame, options, *, cancel=None):
    """The analysis behind ``analyse("Fit custom equation", …)``."""
    s = resolve(frame, options)
    budget = ProfileBudget(cancel)
    compiled = compile_equation(s.equation, [c.name for c in s.coefficients])
    groups = prepare(frame, s)
    figure, axes = _plot(_title(s.equation), s.x, s.y)
    tables = {}
    for label, data, skipped in groups:
        fit = _fit_group(label, data, s, compiled)
        profile_status = None
        if s.intervals == PROFILE:
            from .custom_profiles import apply_profiles
            profile_status = apply_profiles(fit, s, compiled, budget)
        fit["summary"]["Skipped rows"] = skipped
        dots = axes.scatter(fit["data"]["X"], fit["data"]["Y"], label=label)
        axes.plot(fit["curve"]["X"], fit["curve"]["Predicted"], color=dots.get_facecolor()[0])
        tables[f"Parameters: {label}"] = fit["parameters"]
        tables[f"Fit: {label}"] = _report(fit["summary"]).rename_axis("Metric")
        tables[f"Residuals: {label}"] = fit["residuals"]
        tables[f"Curve: {label}"] = fit["curve"]
        if profile_status is not None:
            tables[f"Parameter CI status: {label}"] = profile_status
    if len(groups) > 1:
        axes.legend()
    return Result(tables, figure)
