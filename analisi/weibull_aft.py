"""Weibull accelerated-failure-time regression with right censoring.

The time of subject i is Weibull with scale exp(eta_i), eta_i = x_i beta, and shape k > 0:

    S(t | x) = exp(-exp(k (log t - eta_i)))        S(0 | x) = 1

so that exp(beta_j) is a *time ratio*: a ratio above 1 stretches the distribution of times for comparable
predictors. With delta_i = 1 for an event and 0 for a censored time, r_i = log t_i - eta_i and z_i = k r_i, the
log likelihood contributed by one row is

    delta_i [log k - log t_i + z_i] - exp(z_i).

The fit maximises it over beta (shape fixed) or over (beta, log k) (shape estimated) with a damped Newton method
and analytic derivatives. Work is done on log times, centred, and on predictors that are centred and scaled, so
changing the unit of time only moves the intercept and rows with very large or very small times are harmless.
The covariance is the inverse of the observed information in the parametrisation that was fitted, carried to the
reported coefficients by a linear map. Wald intervals and p values use it; time ratios are their exponentials.

This module reads a worksheet frame and returns tables. It never changes the frame and has no interface code.
It raises ``FieldError`` naming the dialog field to correct. A model without a finite maximum (a level that has no
event, a shape at the edge of its range, an information matrix that cannot be inverted) is an error attributed to
Predictors or Shape mode: there is no automatic fall back to another shape.
"""
from dataclasses import dataclass
import numbers

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype
from scipy import linalg, stats
from scipy.special import logsumexp

from .cox_outputs import CENSOR_VALUE, EVENT_VALUE, _matches, _missing, _number
from .field_error import FieldError
from .weibull_aft_text import MESSAGES

METHOD = "Weibull AFT regression"
TIME, EVENT = "Time", "Event"
PREDICTORS, CATEGORICAL = "Predictors", "Categorical predictors"
SHAPE_MODE, SHAPE, LEVEL = "Shape mode", "Shape", "Confidence level (%)"
PROFILES, TIMES, SHOW_GRAPH = "Profiles", "Times", "Show graph"
NAME, VALUES = "Name", "Values"
ESTIMATED, FIXED = SHAPE_MODES = ("Estimated ML", "Fixed")

MAX_ROWS = 40_000
MAX_PREDICTORS = 8
MAX_COEFFICIENTS = 24
MAX_PROFILES = 12
MAX_CURVE_PAIRS = 5_000
DEFAULT_POINTS = 101
SHAPE_MIN, SHAPE_MAX = 0.05, 50.0
DEFAULTS = {EVENT_VALUE: "1", CENSOR_VALUE: "0", SHAPE_MODE: ESTIMATED, SHAPE: 1.5, LEVEL: 95.0}

MAX_ITERATIONS = 200
CONVERGENCE = 1e-13      # Newton decrement, relative to 1 + |log likelihood|
CONDITION_LIMIT = 1e-10  # smallest over largest eigenvalue of the observed information
DESIGN_CONDITION = 1e-8  # smallest over largest singular value of the scaled design: below it, collinear
LOG_SHAPE_WINDOW = (np.log(1e-3), np.log(1e3))  # the iterates may roam here; the answer must lie in the range above

COEFFICIENT_COLUMNS = ["Estimate", "SE", "p", "Lower", "Upper", "Time ratio", "Ratio lower", "Ratio upper"]
FIT_COLUMNS = ["N", "Events", "Censored", "Incomplete rows", "Shape mode", "Shape", "Parameters", "Log likelihood",
               "AIC", "Confidence level (%)", "Shape lower", "Shape upper"]
FITTED_COLUMNS = ["Source row", "Time", "Event", "Median time", "Survival at time"]
CURVE_COLUMNS = ["Profile", "Time", "Survival", "Extrapolated"]
COEFFICIENTS_SHEET, FIT_SHEET, FITTED_SHEET = "Coefficients", "Model fit", "Fitted survival"
CURVES_SHEET, REFERENCE_SHEET = "Survival curves", "Reference levels"

def error(field, key, **values):
    """FieldError on ``field`` whose text is MESSAGES[key] (see weibull_aft_text) with the values copied literally."""
    return FieldError(field, MESSAGES[key].format(**{"field": field, **values}))


# ----- options ----------------------------------------------------------------------------------------------------------

def _real(value):
    """A finite float from a real number (not a bool), else None."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if np.isfinite(number) else None


def _typed(value):
    if isinstance(value, float) and np.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class Settings:
    """The recipe read and checked before any worksheet value is looked at."""

    def __init__(self, options):
        get = lambda key: options.get(key, DEFAULTS.get(key))
        self.options = options
        self.time, self.event = options.get(TIME), options.get(EVENT)
        self.predictors = self._columns(options.get(PREDICTORS), PREDICTORS)
        self.categorical = self._columns(options.get(CATEGORICAL), CATEGORICAL)
        self.mode = get(SHAPE_MODE)
        if not isinstance(self.mode, str) or self.mode not in SHAPE_MODES:
            raise error(SHAPE_MODE, "shape_mode")
        self.fixed = self.mode == FIXED
        self.shape = self._shape(get(SHAPE)) if self.fixed else None
        self.level = self._level(get(LEVEL))
        show = options.get(SHOW_GRAPH, False)
        if not isinstance(show, (bool, np.bool_)):
            raise error(SHOW_GRAPH, "show_graph")
        self.show_graph = bool(show)
        self.profiles = self._profiles(options.get(PROFILES))
        self.times = self._times(options.get(TIMES))

    @staticmethod
    def _columns(value, field):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)) or not all(isinstance(name, str) and name for name in value):
            raise error(field, "columns_list")
        return list(value)

    @staticmethod
    def _shape(value):
        number = _real(value)
        if number is None or not SHAPE_MIN <= number <= SHAPE_MAX:
            raise error(SHAPE, "shape_number", low=f"{SHAPE_MIN:g}", high=f"{SHAPE_MAX:g}")
        return number

    @staticmethod
    def _level(value):
        number = _real(value)
        if number is None or not 0 < number < 100:
            raise error(LEVEL, "level")
        return number

    @staticmethod
    def _profiles(value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise error(PROFILES, "profiles_list")
        if len(value) > MAX_PROFILES:
            raise error(PROFILES, "profiles_many", limit=MAX_PROFILES, count=len(value))
        return list(value)

    @staticmethod
    def _times(value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise error(TIMES, "times_list")
        out = []
        for position, item in enumerate(value, 1):
            number = _real(item)
            if number is None or number < 0:
                raise error(TIMES, "times_value", position=position,
                            shown=item if isinstance(item, str) else _typed(item))
            if out and number <= out[-1]:
                raise error(TIMES, "times_order", position=position, shown=_typed(number), previous=_typed(out[-1]))
            out.append(number)
        return out


# ----- worksheet --------------------------------------------------------------------------------------------------------

@dataclass
class Data:
    """The complete rows, in worksheet order, with the coded predictors still in their own units."""
    settings: Settings
    source: np.ndarray        # 1-based physical position in the worksheet
    time: np.ndarray
    event: np.ndarray         # bool
    total: int                # worksheet rows
    terms: list               # coefficient names, intercept first
    design: np.ndarray        # rows x terms, original units
    continuous: np.ndarray    # bool per term: scaled during the fit
    references: dict
    levels: dict              # categorical predictor -> sorted levels (text)
    raw_levels: dict          # categorical predictor -> distinct raw values of the rows used

    @property
    def n(self):
        return len(self.time)

    @property
    def maximum_time(self):
        return float(self.time.max())


def standardise(design, continuous):
    """Centre and scale the continuous terms; dummy terms and the intercept stay as they are."""
    centre = np.where(continuous, design.mean(axis=0), 0.0)
    scale = np.where(continuous, design.std(axis=0), 1.0)
    return centre, scale, (design - centre) / scale


def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        raise error(role, "choose", role=role)
    if name not in frame:
        raise error(role, "exists", role=role, name=name)
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        raise error(role, "unique")
    return column


def _numbers(column, name, role):
    """Float values of a column, NaN for empty cells. Text that is not a number, booleans and infinities are errors."""
    if is_bool_dtype(column.dtype) or is_complex_dtype(column.dtype):
        raise error(role, "numeric_type", name=name)
    if column.dtype == object and any(isinstance(value, (bool, np.bool_)) for value in column):
        raise error(role, "numeric_type", name=name)
    values = pd.to_numeric(column, errors="coerce").to_numpy(dtype=float)
    if (column.notna().to_numpy() & ~np.isfinite(values)).any():
        raise error(role, "numeric", name=name)
    return values


def _status_code(options, field):
    value = options.get(field, DEFAULTS[field])
    if _missing(value):
        raise error(field, "code_missing")
    return value


def _status(frame, settings):
    """1 for the event value, 0 for the censor value, NaN for empty cells; the rules and the matching of Cox regression.

    Codes are compared as the type of the column (numbers for a numeric column, text otherwise). Rows are counted by
    their position in the worksheet, not by their index labels.
    """
    name = settings.event
    raw = frame[name].reset_index(drop=True)
    event, censor = _status_code(settings.options, EVENT_VALUE), _status_code(settings.options, CENSOR_VALUE)
    if is_complex_dtype(raw.dtype):
        raise error(EVENT, "status_complex", name=name)
    numeric = is_numeric_dtype(raw.dtype)
    if numeric:
        for field, code in ((EVENT_VALUE, event), (CENSOR_VALUE, censor)):
            if _number(code) is None:
                raise error(field, "code_numeric", name=name)
    is_event, is_censor = _matches(raw, event, EVENT_VALUE, name), _matches(raw, censor, CENSOR_VALUE, name)
    same = str(event).strip() == str(censor).strip() or (numeric and _number(event) == _number(censor))
    if same or (is_event & is_censor).any():
        raise error(CENSOR_VALUE, "status_same")
    present = np.fromiter((not _missing(value) for value in raw), dtype=bool, count=len(raw))
    unknown = present & ~(is_event | is_censor)
    codes = pd.unique(pd.Series([str(value) for value in raw[present]], dtype=object))
    shown = ", ".join(repr(code) for code in codes[:8]) + (", …" if len(codes) > 8 else "")
    if unknown.any():
        row = int(np.flatnonzero(unknown)[0])
        raise error(EVENT, "status_unknown", row=row + 1, name=name, value=repr(str(raw.iloc[row])), shown=shown)
    if present.any() and not is_event.any():
        raise error(EVENT, "status_no_event", name=name, value=repr(str(event)), shown=shown)
    return np.where(is_event, 1.0, np.where(is_censor, 0.0, np.nan))


def read_data(frame, settings):
    """Complete rows of Time, Event and the predictors, coded; budgets are checked before the matrix is built."""
    if len(frame) > MAX_ROWS:
        raise error(TIME, "rows", limit=f"{MAX_ROWS:,}", count=f"{len(frame):,}")
    time_column = _column(frame, settings.time, TIME)
    event_column = _column(frame, settings.event, EVENT)
    if settings.time == settings.event:
        raise error(EVENT, "different", first=TIME, role=EVENT)
    predictors = settings.predictors
    if len(predictors) > MAX_PREDICTORS:
        raise error(PREDICTORS, "predictors_many", limit=MAX_PREDICTORS, count=len(predictors))
    for position, name in enumerate(predictors):
        if name in predictors[:position]:
            raise error(PREDICTORS, "predictors_repeat", name=name)
        _column(frame, name, PREDICTORS)
        if name == settings.time:
            raise error(PREDICTORS, "time_predictor")
        if name == settings.event:
            raise error(PREDICTORS, "event_predictor")
    for name in settings.categorical:
        if name not in predictors:
            raise error(CATEGORICAL, "categorical_subset", name=name)
    del event_column
    time_all = _numbers(time_column, settings.time, TIME)
    status = _status(frame, settings)
    present = ~np.isnan(time_all) & ~np.isnan(status)
    values, labels = {}, {}
    for name in predictors:
        column = frame[name]
        if name in settings.categorical:
            labels[name] = column
            present &= column.notna().to_numpy()
        else:
            values[name] = _numbers(column, name, PREDICTORS)
            present &= ~np.isnan(values[name])
    rows = np.flatnonzero(present)
    if not len(rows):
        empty = TIME if np.isnan(time_all).all() else EVENT if np.isnan(status).all() else PREDICTORS
        raise error(empty, "no_complete")
    time = time_all[rows]
    bad = ~(time > 0)
    if bad.any():
        at = int(np.flatnonzero(bad)[0])
        raise error(TIME, "time_value", row=int(rows[at]) + 1, value=f"{time[at]:g}")
    event = status[rows] == 1
    if not event.any():
        raise error(EVENT, "no_events")
    # Coefficient budget from the levels alone, before any column of the matrix exists.
    levels, raw_levels, count = {}, {}, 1
    for name in predictors:
        if name in settings.categorical:
            used = labels[name].iloc[rows]
            raw_levels[name] = list(pd.unique(used))
            levels[name] = sorted(pd.unique(used.astype(str)).tolist())
            if len(levels[name]) < 2:
                raise error(CATEGORICAL, "levels", name=name)
            count += len(levels[name]) - 1
        else:
            count += 1
    if count > MAX_COEFFICIENTS:
        raise error(PREDICTORS, "coefficients", count=count, limit=MAX_COEFFICIENTS)
    terms, columns, continuous, references = ["Intercept"], [np.ones(len(rows))], [False], {}
    for name in predictors:
        if name in settings.categorical:
            text = labels[name].iloc[rows].astype(str)
            references[name] = levels[name][0]
            for level in levels[name][1:]:
                terms.append(f"{name} [{level}]")
                columns.append((text == level).to_numpy(dtype=float))
                continuous.append(False)
        else:
            terms.append(name)
            columns.append(values[name][rows])
            continuous.append(True)
    for position, term in enumerate(terms):
        if term in terms[:position]:
            raise error(PREDICTORS, "duplicate", term=term)
    design = np.column_stack(columns)
    # Identification that can be decided before the fit: a term that is constant, and a term whose lowest or highest
    # value is the only one found among the events (a level without events, a group that is wholly censored).
    for position, term in enumerate(terms[1:], 1):
        column = design[:, position]
        if column.min() == column.max():
            raise error(PREDICTORS, "collinear", term=term)
        on_events = column[event]
        for extreme, edge in (("lowest", column.min()), ("highest", column.max())):
            if (on_events == edge).all():
                raise error(PREDICTORS, f"extreme_{extreme}", term=term, value=f"{edge:g}")
    singular = np.linalg.svd(standardise(design, np.array(continuous))[2], compute_uv=False)
    if singular.shape[0] < len(terms) or singular[-1] <= DESIGN_CONDITION * singular[0]:
        raise error(PREDICTORS, "collinear_combination")
    return Data(settings, rows + 1, time, event, len(frame), terms, design, np.array(continuous), references,
                levels, raw_levels)


# ----- profiles and requested times -------------------------------------------------------------------------------------

def _category(data, name, value, profile):
    levels = data.levels[name]
    if isinstance(value, str) and value in levels:
        return value
    number = _number(value)
    for original in data.raw_levels[name]:
        if str(original) == str(value) or (number is not None and _number(original) == number):
            return str(original)
    raise error(PROFILES, "profile_level", name=profile, value=repr(value), predictor=name, levels=", ".join(levels))


def profile_rows(data):
    """Names and design rows of the profiles, coded exactly as the fit: same dummy columns, same reference level."""
    settings = data.settings
    names, rows = [], []
    for number, profile in enumerate(settings.profiles, 1):
        if not isinstance(profile, dict) or not isinstance(profile.get(VALUES), dict):
            raise error(PROFILES, "profile_object", number=number)
        name = profile.get(NAME)
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            raise error(PROFILES, "profile_name", number=number)
        if name in names:
            raise error(PROFILES, "profile_repeat", name=name)
        values = profile[VALUES]
        for predictor in values:
            if predictor not in settings.predictors:
                raise error(PROFILES, "profile_unknown", name=name, predictor=predictor)
        row = {"Intercept": 1.0}
        for predictor in settings.predictors:
            if predictor not in values or _missing(values[predictor]):
                raise error(PROFILES, "profile_missing", name=name, predictor=predictor)
            if predictor in settings.categorical:
                level = _category(data, predictor, values[predictor], name)
                for other in data.levels[predictor][1:]:
                    row[f"{predictor} [{other}]"] = float(level == other)
            else:
                number_value = _number(values[predictor])
                if number_value is None:
                    raise error(PROFILES, "profile_number", name=name, predictor=predictor)
                row[predictor] = number_value
        names.append(name)
        rows.append([row[term] for term in data.terms])
    return names, np.asarray(rows, dtype=float).reshape(len(names), len(data.terms))


def curve_times(data):
    """The requested times, or 101 points from 0 to the longest observed time."""
    settings = data.settings
    if settings.times:
        return np.asarray(settings.times, dtype=float)
    return np.linspace(0.0, data.maximum_time, DEFAULT_POINTS)


class Plan:
    """Everything that can be checked without fitting: roles, codes, budgets, profiles, times and the graph."""

    def __init__(self, settings, data, names, rows, times):
        self.settings, self.data, self.profile_names, self.profile_design, self.times = (
            settings, data, names, rows, times)


def check_options(frame, options):
    """Every value, role and budget that can be decided without a fit; raises FieldError."""
    settings = Settings(options)
    data = read_data(frame, settings)
    names, rows = profile_rows(data)
    if settings.show_graph and not names:
        raise error(PROFILES, "graph_profiles", graph=SHOW_GRAPH)
    times = curve_times(data) if names else np.zeros(0)
    if len(names) * len(times) > MAX_CURVE_PAIRS:
        raise error(TIMES, "pairs", count=f"{len(names) * len(times):,}", limit=f"{MAX_CURVE_PAIRS:,}")
    return Plan(settings, data, names, rows, times)


# ----- likelihood -------------------------------------------------------------------------------------------------------

class Likelihood:
    """Log likelihood, gradient and Hessian in (beta, log k) or in beta alone, on centred log times."""

    def __init__(self, z, centred, log_time, event, fixed_shape):
        self.z, self.centred, self.log_time, self.delta = z, centred, log_time, event.astype(float)
        self.fixed_shape = fixed_shape
        self.p = z.shape[1]
        self.size = self.p + (fixed_shape is None)

    def rho_of(self, theta):
        return np.log(self.fixed_shape) if self.fixed_shape is not None else float(theta[self.p])

    def __call__(self, theta, hessian=True):
        """(log likelihood, gradient, Hessian), or None when the point is outside the representable range."""
        p, rho = self.p, self.rho_of(theta)
        k = np.exp(rho)
        residual = self.centred - self.z @ theta[:p]
        z = k * residual
        with np.errstate(over="ignore", invalid="ignore"):
            weight = np.exp(z)
            log_likelihood = float(np.sum(self.delta * (rho - self.log_time + z)) - weight.sum())
        if not (np.isfinite(log_likelihood) and np.isfinite(weight).all()):
            return None
        excess = weight - self.delta
        gradient = np.empty(self.size)
        gradient[:p] = k * (self.z.T @ excess)
        if not hessian and self.fixed_shape is not None:
            return log_likelihood, gradient, None
        if self.fixed_shape is None:
            gradient[p] = np.sum(self.delta + (self.delta - weight) * z)
        if not hessian:
            return log_likelihood, gradient, None
        matrix = np.empty((self.size, self.size))
        matrix[:p, :p] = -(k * k) * (self.z.T * weight) @ self.z
        if self.fixed_shape is None:
            cross = k * (self.z.T @ (weight * (1 + z) - self.delta))
            matrix[:p, p] = matrix[p, :p] = cross
            matrix[p, p] = np.sum(z * self.delta - weight * z - weight * z * z)
        if not (np.isfinite(gradient).all() and np.isfinite(matrix).all()):
            return None
        return log_likelihood, gradient, matrix


def _solve(information, gradient, damping):
    """Newton direction of the damped system, or None when it is not positive definite."""
    scale = np.maximum(np.diag(information), 1e-300)
    try:
        factor = linalg.cho_factor(information + damping * np.diag(scale), check_finite=False)
    except linalg.LinAlgError:
        return None
    return linalg.cho_solve(factor, gradient, check_finite=False)


class _Stalled(ValueError):
    """The iterations stopped without a maximum; ``theta`` is the last point reached."""

    def __init__(self, reason, theta):
        super().__init__(reason)
        self.theta = theta


def maximise(likelihood, theta):
    """Damped Newton ascent. Returns (theta, log likelihood, iterations); raises ValueError('diverged' | 'iterations')."""
    state = likelihood(theta)
    if state is None:
        raise ValueError("diverged")
    value, gradient, hessian = state
    damping = 0.0
    final = False
    for iteration in range(1, MAX_ITERATIONS + 1):
        information = -hessian
        step = _solve(information, gradient, 0.0)
        if step is not None and not final:
            decrement = 0.5 * float(gradient @ step)
            if decrement <= CONVERGENCE * (1 + abs(value)):
                final = True  # one more full step makes the estimate accurate to rounding
        accepted = False
        trials = 0
        while trials < 60:
            trials += 1
            direction = step if damping == 0.0 and step is not None else _solve(information, gradient, damping)
            if direction is None:
                damping = max(damping * 10, 1e-6)
                step = None
                continue
            candidate = theta + direction
            if likelihood.fixed_shape is None and not LOG_SHAPE_WINDOW[0] < candidate[-1] < LOG_SHAPE_WINDOW[1]:
                damping = max(damping * 10, 1e-6)
                step = None
                continue
            trial = likelihood(candidate)
            if trial is not None and (trial[0] >= value or final and trial[0] >= value - 1e-9 * (1 + abs(value))):
                theta, (value, gradient, hessian), accepted = candidate, trial, True
                damping = damping / 10 if damping > 1e-8 else 0.0
                break
            damping = max(damping * 10, 1e-6)
            step = None
        if not accepted:
            if final:
                return theta, value, iteration
            raise _Stalled("iterations", theta)
        if final:
            return theta, value, iteration
        if not np.abs(theta).max() < 1e7:
            raise ValueError("diverged")
    raise _Stalled("iterations", theta)


@dataclass
class Fit:
    data: Data
    shape: float
    estimated: bool
    log_shape_se: float
    beta: np.ndarray         # coefficients in the units of the worksheet
    covariance: np.ndarray   # of the coefficients, same units
    eta: np.ndarray          # linear predictor of each row used
    log_likelihood: float
    parameters: int
    iterations: int
    standardisation: tuple   # (centre, scale) of every term and the shift of log time, to evaluate new rows

    @property
    def aic(self):
        return -2 * self.log_likelihood + 2 * self.parameters

    def linear_predictor(self, rows):
        """Linear predictor of design rows given in worksheet units, evaluated on the scaled terms."""
        centre, scale, shift, beta_z = self.standardisation
        return shift + ((rows - centre) / scale) @ beta_z


def _start(z, centred, event, shape):
    """Intercept-only maximum at the starting shape: a safe point for the Newton iterations."""
    p = z.shape[1]
    theta = np.zeros(p)
    d = max(int(event.sum()), 1)
    theta[0] = (logsumexp(shape * centred) - np.log(d)) / shape
    return theta


def fit_weibull(data):
    """One maximum-likelihood fit with the shape of ``data.settings``. Raises FieldError when no usable maximum."""
    settings = data.settings
    log_time = np.log(data.time)
    shift = float(log_time.mean())
    centred = log_time - shift
    centre, scale, z = standardise(data.design, data.continuous)
    likelihood = Likelihood(z, centred, log_time, data.event, settings.shape if settings.fixed else None)
    if settings.fixed:
        shape0 = settings.shape
    else:
        spread = float(centred.std())
        if not spread > 0:
            # Identical times: the likelihood rises without limit as the shape grows.
            raise error(SHAPE_MODE, "shape_edge", low=f"{SHAPE_MIN:g}", high=f"{SHAPE_MAX:g}")
        shape0 = float(np.clip(np.pi / np.sqrt(6) / spread, 0.2, 5.0))
    theta0 = _start(z, centred, data.event, shape0)
    if not settings.fixed:
        theta0 = np.r_[theta0, np.log(shape0)]
    attributed = PREDICTORS if len(data.terms) > 1 else SHAPE_MODE
    try:
        theta, value, iterations = maximise(likelihood, theta0)
    except ValueError as problem:
        if str(problem) == "iterations":
            if not settings.fixed and not np.log(SHAPE_MIN) < problem.theta[-1] < np.log(SHAPE_MAX):
                # The shape ran off its range: the likelihood rises without limit as the shape grows or shrinks.
                raise error(SHAPE_MODE, "shape_edge", low=f"{SHAPE_MIN:g}", high=f"{SHAPE_MAX:g}") from None
            raise error(attributed, "not_converged", limit=MAX_ITERATIONS) from None
        raise error(attributed, "diverged") from None
    p = len(data.terms)
    beta_z = theta[:p]
    k = settings.shape if settings.fixed else float(np.exp(theta[p]))
    if not settings.fixed and not SHAPE_MIN * (1 + 1e-9) < k < SHAPE_MAX * (1 - 1e-9):
        raise error(SHAPE_MODE, "shape_edge", low=f"{SHAPE_MIN:g}", high=f"{SHAPE_MAX:g}")
    # Observed information at the maximum, in the fitted parametrisation, and its inverse.
    state = likelihood(theta)
    information = -state[2]
    eigenvalues = np.linalg.eigvalsh(information)
    if not (np.isfinite(eigenvalues).all() and eigenvalues[0] > 0):
        raise error(attributed, "information")
    if eigenvalues[0] / eigenvalues[-1] < CONDITION_LIMIT:
        raise error(attributed, "conditioning")
    covariance_z = linalg.cho_solve(linalg.cho_factor(information), np.eye(information.shape[0]))
    # Back to the worksheet units: beta = A beta_z + (shift, 0, ...), so Cov = A Cov_z A'.
    transform = np.diag(1.0 / scale)
    transform[0, 1:] = -(centre[1:] / scale[1:])
    beta = transform @ beta_z
    beta[0] += shift
    covariance = transform @ covariance_z[:p, :p] @ transform.T
    log_shape_se = float(np.sqrt(covariance_z[p, p])) if not settings.fixed else float("nan")
    eta = shift + z @ beta_z
    parameters = p + (0 if settings.fixed else 1)
    if not (np.isfinite(beta).all() and np.isfinite(covariance).all() and np.isfinite(eta).all()
            and (np.diag(covariance) > 0).all()):
        raise error(attributed, "not_finite")
    return Fit(data, k, not settings.fixed, log_shape_se, beta, covariance, eta, value, parameters, iterations,
               (centre, scale, shift, beta_z))


# ----- tables -----------------------------------------------------------------------------------------------------------

def survival(time, eta, shape):
    """S(t | eta) with S = 1 at t = 0, kept inside [0, 1]."""
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        hazard = np.exp(shape * (np.log(time) - eta))
        return np.clip(np.exp(-hazard), 0.0, 1.0)


def median_time(eta, shape):
    with np.errstate(over="ignore", under="ignore"):
        return np.exp(eta + np.log(np.log(2.0)) / shape)


def coefficient_table(fit):
    data, level = fit.data, fit.data.settings.level
    se = np.sqrt(np.diag(fit.covariance))
    critical = float(stats.norm.ppf(1 - (1 - level / 100) / 2))
    estimate = fit.beta
    wald = estimate / se
    p = 2 * stats.norm.sf(np.abs(wald))
    lower, upper = estimate - critical * se, estimate + critical * se
    with np.errstate(over="ignore"):
        ratios = np.exp(np.column_stack([estimate, lower, upper]))
    if not np.isfinite(ratios).all():
        raise error(TIME, "range")
    table = pd.DataFrame(np.column_stack([estimate, se, p, lower, upper, ratios]), index=data.terms,
                         columns=COEFFICIENT_COLUMNS)
    return table


def fit_table(fit):
    data, settings = fit.data, fit.data.settings
    lower = upper = float("nan")
    if fit.estimated:
        critical = float(stats.norm.ppf(1 - (1 - settings.level / 100) / 2))
        centre = np.log(fit.shape)
        lower, upper = (float(np.exp(centre - critical * fit.log_shape_se)),
                        float(np.exp(centre + critical * fit.log_shape_se)))
    row = {"N": data.n, "Events": int(data.event.sum()), "Censored": int((~data.event).sum()),
           "Incomplete rows": data.total - data.n, "Shape mode": settings.mode, "Shape": fit.shape,
           "Parameters": fit.parameters, "Log likelihood": fit.log_likelihood, "AIC": fit.aic,
           "Confidence level (%)": settings.level, "Shape lower": lower, "Shape upper": upper}
    return pd.DataFrame([row], columns=FIT_COLUMNS)


def fitted_table(fit):
    data = fit.data
    median = median_time(fit.eta, fit.shape)
    if not (np.isfinite(median).all() and (median > 0).all()):
        raise error(TIME, "range")
    return pd.DataFrame({"Source row": data.source.astype(np.int64), "Time": data.time,
                         "Event": data.event.astype(np.int64), "Median time": median,
                         "Survival at time": survival(data.time, fit.eta, fit.shape)})[FITTED_COLUMNS]


def curve_table(fit, plan):
    """Survival of every profile at the requested times; a point estimate, extrapolated beyond the longest time."""
    etas = np.array([float(fit.linear_predictor(row)) for row in plan.profile_design])
    times = plan.times
    beyond = times > fit.data.maximum_time
    names, stacked = [], []
    for name, eta in zip(plan.profile_names, etas):
        names.append(np.full(len(times), name, dtype=object))
        stacked.append(survival(times, eta, fit.shape))
    return pd.DataFrame({"Profile": np.concatenate(names), "Time": np.tile(times, len(etas)),
                         "Survival": np.concatenate(stacked),
                         "Extrapolated": np.tile(np.where(beyond, "Yes", "No").astype(object), len(etas))})[CURVE_COLUMNS]


def reference_table(data):
    return pd.DataFrame.from_dict(data.references, orient="index", columns=["Reference"])


def run(frame, options):
    """Check everything, fit once and return (tables, plan, fit)."""
    plan = check_options(frame, options)
    fit = fit_weibull(plan.data)
    tables = {COEFFICIENTS_SHEET: coefficient_table(fit), FIT_SHEET: fit_table(fit), FITTED_SHEET: fitted_table(fit)}
    if plan.profile_names:
        tables[CURVES_SHEET] = curve_table(fit, plan)
    if plan.data.references:
        tables[REFERENCE_SHEET] = reference_table(plan.data)
    return tables, plan, fit
