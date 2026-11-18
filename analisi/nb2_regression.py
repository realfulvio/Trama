"""Negative binomial (NB2) regression for overdispersed counts, with an optional exposure offset.

Model, for every complete row i:

    log μ_i = x_i'β + log(exposure_i),      Var(Y_i) = μ_i + α μ_i²,      α > 0.

``Fitted rate`` is μ / exposure, so multiplying every exposure by c only moves the intercept by −log(c).

Two dispersion modes:

* **Fixed** — α is given (1e-6 to 1000). β is the maximum likelihood estimate of the GLM with known
  dispersion (scale 1) and its covariance is the inverse Fisher information X'WX, W = μ / (1 + αμ).
* **Estimated ML** — β and α maximise the full NB2 likelihood together. α is found on the profile
  likelihood: a grid over 1e-6…1000 locates the highest point, the profile score in α is solved inside
  that bracket, and the covariance of β is the β block of the inverse *observed* information of the
  joint parameter (β, α). A surface whose highest point lies on the edge of that range (the Poisson
  boundary α → 0 included), a fit that does not converge or an unusable Hessian raise a FieldError on
  ``Dispersion mode`` with the reason; an α stopped at a limit is never reported as an estimate.

Wald intervals and p values use the standard normal; the IRR interval is the exponential of the limits on
the log scale. The log likelihood keeps every normalising constant (the same value as
``scipy.stats.nbinom.logpmf``), AIC = −2ℓ + 2k with k = number of β plus one for Estimated ML, and the
Pearson residual is (y − μ)/√V.

Rows follow the worksheet mask: a row is used when the response, every predictor and the exposure (when
chosen) are present. A count of 0 is a value, an empty cell is missing. A present cell that does not suit
its role (a fractional or negative count, text in a numeric predictor, an exposure of 0, a negative or an
infinite one) is a FieldError on that control, also when the recipe was typed by hand. ``Source row`` is the
physical position of the row in the worksheet, from 1, whatever the pandas index.

The numerical work avoids the cancellations of the textbook formulas near the Poisson limit: the α score
and its derivative are written with ψ(y + 1/α) − ψ(1/α) as exact finite sums (a cumulative table over the
counts), and log(1+u) − u/(1+u) uses its series for small u = αμ.
"""
from dataclasses import dataclass
from numbers import Real

import numpy as np
import pandas as pd
from scipy import linalg, optimize, special
from scipy.stats import norm

from .field_error import FieldError
from .models import _design
from .reporting import Result, _plot

NB2 = METHOD = "Negative binomial regression"
RESPONSE, PREDICTORS, CATEGORIES, EXPOSURE = "Response", "Predictors", "Categorical predictors", "Exposure"
MODE, ALPHA, LEVEL, PLOT = "Dispersion mode", "Dispersion alpha", "Confidence level (%)", "Residual plot"
ESTIMATED, FIXED = MODES = ("Estimated ML", "Fixed")
DEFAULT_ALPHA, DEFAULT_LEVEL = 0.5, 95.0
ALPHA_MIN, ALPHA_MAX = 1e-6, 1000.0
MAX_ROWS, MAX_COEFFICIENTS, MAX_PREDICTORS, MAX_LEVELS = 50_000, 32, 8, 100

# Column roles use the registry markers of workbench.METHODS; the first entry of a choice is its default.
OPTIONS = {RESPONSE: None, PREDICTORS: "Multiple", CATEGORIES: "Multiple (optional)", EXPOSURE: "Optional",
           MODE: MODES, ALPHA: DEFAULT_ALPHA, LEVEL: DEFAULT_LEVEL, PLOT: False}
DATA_FIELDS = (RESPONSE, PREDICTORS, CATEGORIES, EXPOSURE)
OPTION_FIELDS = (MODE, ALPHA, LEVEL, PLOT)

COEFFICIENTS, MODEL_FIT, FITTED, REFERENCES = "Coefficients", "Model fit", "Fitted values", "Reference levels"
COEFFICIENT_COLUMNS = ["Estimate", "SE", "p", "Lower", "Upper", "IRR", "IRR lower", "IRR upper"]
FIT_COLUMNS = ["N", "Incomplete rows", "Dispersion mode", "Alpha", "Parameters", "Log likelihood", "AIC",
               "Covariance"]
FITTED_COLUMNS = ["Source row", "Observed", "Exposure", "Fitted count", "Fitted rate", "Variance",
                  "Pearson residual"]
FISHER = "Fisher information (alpha fixed)"
OBSERVED = "Observed information (joint beta and alpha)"
FIGURE_TITLE = "Negative binomial residuals"

# Profile grid of Estimated ML: quarter decades over the supported range of alpha.
_GRID = np.log(np.logspace(np.log10(ALPHA_MIN), np.log10(ALPHA_MAX), 37))
_MAX_NEWTON = 100
_TABLE_LIMIT = 200_000


class _NoConvergence(Exception):
    """The coefficients of a fit with fixed alpha did not converge (separation or a degenerate design)."""


@dataclass(frozen=True)
class Settings:
    response: str
    predictors: tuple
    categories: tuple
    exposure: str | None
    mode: str
    alpha: float | None
    level: float
    plot: bool


@dataclass
class Prepared:
    rows: np.ndarray          # physical positions (0-based) of the complete rows
    y: np.ndarray
    exposure: np.ndarray
    design: pd.DataFrame      # Intercept and the expanded predictor columns, in the term order of the report
    references: dict
    total: int


# ----- options -------------------------------------------------------------------------------------------------------

def _column(frame, options, field, *, optional=False):
    value = options.get(field)
    if optional and (value is None or value == ""):
        return None
    if not isinstance(value, str) or not value:
        raise FieldError(field, f"Choose a column for {field}.")
    if value not in frame.columns:
        raise FieldError(field, f'Column "{value}" is not in the table.')
    return value


def _columns(frame, options, field, *, optional=False):
    value = options.get(field)
    if value is None and optional:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)) or not all(
            isinstance(name, str) and name for name in value):
        raise FieldError(field, f"{field}: choose columns of the table.")
    if len(set(value)) != len(value):
        raise FieldError(field, f"{field}: choose each column once.")
    for name in value:
        if name not in frame.columns:
            raise FieldError(field, f'Column "{name}" is not in the table.')
    return tuple(value)


def _real(options, field, default):
    value = options.get(field, default)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(field, f"{field} must be a number.")
    value = float(value)
    if not np.isfinite(value):
        raise FieldError(field, f"{field} must be finite.")
    return value


def settings(frame, options):
    """Validate the recipe against the worksheet columns; no cell is read and nothing is fitted."""
    response = _column(frame, options, RESPONSE)
    predictors = _columns(frame, options, PREDICTORS)
    if not 1 <= len(predictors) <= MAX_PREDICTORS:
        raise FieldError(PREDICTORS, "Choose from 1 to 8 predictors.")
    if response in predictors:
        raise FieldError(PREDICTORS, "The response cannot also be a predictor.")
    categories = _columns(frame, options, CATEGORIES, optional=True)
    if not set(categories) <= set(predictors):
        raise FieldError(CATEGORIES, "Categorical predictors must be chosen among the predictors.")
    categories = tuple(name for name in predictors if name in categories)
    exposure = _column(frame, options, EXPOSURE, optional=True)
    if exposure is not None and (exposure == response or exposure in predictors):
        raise FieldError(EXPOSURE, "Exposure must be a column distinct from the response and the predictors.")
    mode = options.get(MODE, ESTIMATED)
    if not isinstance(mode, str) or mode not in MODES:
        raise FieldError(MODE, "Choose Estimated ML or Fixed.")
    alpha = None
    if mode == FIXED:
        alpha = _real(options, ALPHA, DEFAULT_ALPHA)
        if not ALPHA_MIN <= alpha <= ALPHA_MAX:
            raise FieldError(ALPHA, "Dispersion alpha must be from 0.000001 to 1000.")
    level = _real(options, LEVEL, DEFAULT_LEVEL)
    if not 0 < level < 100:
        raise FieldError(LEVEL, "Confidence level (%) must be strictly between 0 and 100.")
    plot = options.get(PLOT, False)
    if not isinstance(plot, (bool, np.bool_)):
        raise FieldError(PLOT, "Residual plot must be on or off.")
    return Settings(response, predictors, categories, exposure, mode, alpha, level, bool(plot))


def visibility(mode):
    """Dispersion alpha is used, shown and validated only for Fixed."""
    return {ALPHA: mode == FIXED}


# ----- cells ---------------------------------------------------------------------------------------------------------

def _missing(series):
    """Empty cells: NaN/None and text made only of spaces. A zero is a value."""
    missing = np.array(series.isna(), dtype=bool)
    if series.dtype == object or pd.api.types.is_string_dtype(series.dtype):
        blank = series.map(lambda value: isinstance(value, str) and not value.strip())
        missing |= blank.to_numpy(dtype=bool)
    return missing


def _numbers(series, field, name):
    values = pd.to_numeric(series, errors="coerce")
    if np.iscomplexobj(values.to_numpy()):
        raise FieldError(field, f'Column "{name}" contains complex data.')
    return values.to_numpy(dtype=float, na_value=np.nan)


def _shown(series, position):
    value = series.iloc[position]
    return repr(value) if isinstance(value, str) else str(value)


def _first_bad(bad, series, field, template, column):
    """The first present cell that does not suit its role, by its physical row from 1."""
    if bad.any():
        position = int(np.flatnonzero(bad)[0])
        raise FieldError(field, template.format(column=column, row=position + 1, value=_shown(series, position)))


def prepare(frame, s):
    """Complete rows, the response, the exposure and the design, checking every present cell first."""
    present = {}
    numeric = {}
    response = frame[s.response]
    present[s.response] = ~_missing(response)
    y = _numbers(response, RESPONSE, s.response)
    with np.errstate(invalid="ignore"):
        counts = np.isfinite(y) & (y >= 0) & (np.floor(y) == y)
    _first_bad(present[s.response] & ~counts, response, RESPONSE,
               'Response "{column}" needs whole counts of 0 or more (row {row}: {value}).', s.response)
    for name in s.predictors:
        series = frame[name]
        present[name] = ~_missing(series)
        if name in s.categories:
            continue
        values = _numbers(series, PREDICTORS, name)
        _first_bad(present[name] & ~np.isfinite(values), series, PREDICTORS,
                   'Predictor "{column}" needs finite numbers (row {row}: {value}).', name)
        numeric[name] = values
    exposure = np.ones(len(frame))
    if s.exposure is not None:
        series = frame[s.exposure]
        present[s.exposure] = ~_missing(series)
        values = _numbers(series, EXPOSURE, s.exposure)
        with np.errstate(invalid="ignore"):
            valid = np.isfinite(values) & (values > 0)
        _first_bad(present[s.exposure] & ~valid, series, EXPOSURE,
                   'Exposure "{column}" needs finite values greater than 0 (row {row}: {value}).', s.exposure)
        exposure = values
    complete = np.logical_and.reduce(list(present.values()))
    rows = np.flatnonzero(complete)
    if not len(rows):
        raise FieldError(RESPONSE, "No row has a response, every predictor and the exposure.")
    if len(rows) > MAX_ROWS:
        raise FieldError(RESPONSE, f"The model would use {len(rows):,} complete rows; the limit is 50,000.")
    y = y[rows]
    if not (y > 0).any():
        raise FieldError(RESPONSE, "Negative binomial regression needs at least one observed event "
                                   "(a count above 0).")
    # Budget of the expanded design before it is built.
    columns = {}
    coefficients = 1
    for name in s.predictors:
        if name in s.categories:
            values = frame[name].iloc[rows].reset_index(drop=True)
            levels = values.astype(str).nunique()
            if not 2 <= levels <= MAX_LEVELS:
                raise FieldError(CATEGORIES, f'Categorical predictor "{name}" must have 2 to 100 levels '
                                             "among the complete rows.")
            coefficients += levels - 1
            columns[name] = values
        else:
            coefficients += 1
            columns[name] = numeric[name][rows]
    if coefficients > MAX_COEFFICIENTS:
        field = CATEGORIES if s.categories else PREDICTORS
        raise FieldError(field, f"The model has {coefficients} coefficients; the limit is 32.")
    if len(rows) <= coefficients:
        raise FieldError(PREDICTORS, f"The model has {coefficients} coefficients for {len(rows)} complete rows. "
                                     "Use fewer predictors or more rows.")
    try:
        design, references = _design(pd.DataFrame(columns), list(s.predictors), list(s.categories), True)
    except ValueError as error:
        raise FieldError(PREDICTORS, str(error)) from error
    return Prepared(rows, y, exposure[rows], design, references, len(frame))


def check_options(frame, options):
    """Every check the dialog can make without fitting: recipe, cells, budgets and the rank of the design."""
    s = settings(frame, options)
    prepare(frame, s)
    return s


# ----- likelihood pieces ---------------------------------------------------------------------------------------------

def loglik_rows(y, mu, alpha):
    """log NB2 pmf with every constant, written to stay accurate for small and large alpha."""
    r = 1.0 / alpha
    u = alpha * mu
    with np.errstate(divide="ignore", invalid="ignore"):
        counts = np.where(y > 0, y * (np.log(u) - np.log1p(u)), 0.0)
    return -special.betaln(r, y + 1.0) - np.log(r + y) - r * np.log1p(u) + counts


def _f(u):
    """log(1+u) − u/(1+u), series below 1e-3."""
    small = u < 1e-3
    series = sum((-1) ** n * (n - 1) / n * u ** n for n in range(2, 9))
    with np.errstate(invalid="ignore"):
        direct = np.log1p(u) - u / (1 + u)
    return np.where(small, series, direct)


def _h(u):
    """u²/(1+u)² − 2 f(u), the derivative pattern of f(u)/α² in α; series below 1e-3."""
    small = u < 1e-3
    series = sum((-1) ** n * (n - 1) * (n - 2) / n * u ** n for n in range(3, 10))
    with np.errstate(invalid="ignore"):
        direct = u ** 2 / (1 + u) ** 2 - 2 * (np.log1p(u) - u / (1 + u))
    return np.where(small, series, direct)


def _count_sums(y, alpha, second=False):
    """Σ_{k<y} 1/(1+αk), Σ k/(1+αk) and, with ``second``, Σ k/(1+αk)², Σ k²/(1+αk)² for every count."""
    counts = y.astype(np.int64)
    sums = [np.zeros(len(y)) for _ in range(4 if second else 2)]
    small = counts <= _TABLE_LIMIT
    if small.any():
        top = int(counts[small].max())
        k = np.arange(top, dtype=float)
        q = 1.0 / (1.0 + alpha * k)
        tables = [q, k * q] + ([k * q * q, k * k * q * q] if second else [])
        for target, table in zip(sums, tables, strict=True):
            target[small] = np.concatenate(([0.0], np.cumsum(table)))[counts[small]]
    if (~small).any():
        # Very large counts: the digamma form, exact for integers and accurate when y is large.
        r, big = 1.0 / alpha, y[~small]
        a0 = r * (special.digamma(big + r) - special.digamma(r))
        sums[0][~small] = a0
        sums[1][~small] = r * (big - a0)
        if second:
            b0 = r * r * (special.polygamma(1, r) - special.polygamma(1, big + r))
            sums[2][~small] = r * (a0 - b0)
            sums[3][~small] = r * r * (big - 2 * a0 + b0)
    return sums


def alpha_score(y, mu, alpha):
    """∂ℓ/∂α summed over the rows, at fixed μ."""
    u = alpha * mu
    a0, a1 = _count_sums(y, alpha)
    return float(np.sum(_f(u) / alpha ** 2 + (a1 - mu * a0) / (1 + u)))


def _alpha_curvature(y, mu, alpha):
    """∂²ℓ/∂α² summed over the rows, at fixed μ."""
    u = alpha * mu
    a0, a1, d1, d2 = _count_sums(y, alpha, second=True)
    g = a1 - mu * a0
    dg = -(d2 - mu * d1)
    return float(np.sum(_h(u) / alpha ** 3 + dg / (1 + u) - g * mu / (1 + u) ** 2))


# ----- fits ----------------------------------------------------------------------------------------------------------

def _beta_objective(eta, y, alpha):
    """The part of ℓ that depends on β (η = Xβ + offset)."""
    with np.errstate(over="ignore", invalid="ignore"):
        value = float(np.sum(y * eta - (y + 1.0 / alpha) * np.log1p(alpha * np.exp(eta))))
    return value if np.isfinite(value) else -np.inf


def _start(X, y, offset, alpha):
    mu = (y + y.mean()) / 2
    w = np.sqrt(mu / (1 + alpha * mu))
    beta, *_ = np.linalg.lstsq(X * w[:, None], (np.log(mu) - offset) * w, rcond=None)
    return beta


def fit_beta(X, y, offset, alpha, start=None):
    """Maximum likelihood β at fixed α by Newton steps on the observed information, with step halving.

    ℓ(β) is strictly concave for a full-rank design, so the observed information is positive definite
    everywhere. Convergence is declared on the size of a full Newton step; a coefficient that keeps drifting
    (a category whose counts are all zero) never satisfies it and raises _NoConvergence.
    """
    beta = _start(X, y, offset, alpha) if start is None else np.array(start, dtype=float)
    eta = X @ beta + offset
    objective = _beta_objective(eta, y, alpha)
    if not np.isfinite(objective) and start is not None:
        return fit_beta(X, y, offset, alpha)
    if not np.isfinite(objective):
        raise _NoConvergence("the starting values are outside the numeric range")
    for _ in range(_MAX_NEWTON):
        with np.errstate(over="ignore"):
            mu = np.exp(eta)
        u = alpha * mu
        gradient = X.T @ ((y - mu) / (1 + u))
        weight = mu * (1 + alpha * y) / (1 + u) ** 2
        information = (X * weight[:, None]).T @ X
        try:
            factor = linalg.cho_factor(information, check_finite=True)
        except (linalg.LinAlgError, ValueError) as error:
            raise _NoConvergence("the information matrix is singular") from error
        step = linalg.cho_solve(factor, gradient)
        size = float(np.max(np.abs(step)))
        if not np.isfinite(size):
            raise _NoConvergence("the Newton step is not finite")
        scale = 1.0 + float(np.max(np.abs(beta)))
        if size <= 1e-11 * scale:
            return beta
        t = 1.0
        while t > 1e-12:
            candidate = beta + t * step
            candidate_eta = X @ candidate + offset
            value = _beta_objective(candidate_eta, y, alpha)
            if value >= objective - 1e-12 * (1 + abs(objective)):
                break
            t /= 2
        else:
            if size <= 1e-8 * scale:
                return beta
            raise _NoConvergence("no step increases the likelihood")
        beta, eta, objective = candidate, candidate_eta, value
        if t == 1.0 and size <= 1e-10 * scale:
            return beta
    raise _NoConvergence(f"the coefficients did not converge in {_MAX_NEWTON} Newton steps")


def _profile_ml(X, y, offset):
    """Estimated ML: (β, α) at the interior maximum of the profile likelihood, or a FieldError."""
    state = {"beta": None}

    def evaluate(theta):
        alpha = float(np.exp(theta))
        try:
            beta = fit_beta(X, y, offset, alpha, state["beta"])
        except _NoConvergence as error:
            raise FieldError(MODE, "Estimated ML did not converge: the coefficients do not settle. Check "
                                   "categories or predictor ranges whose counts are all zero.") from error
        state["beta"] = beta
        mu = np.exp(X @ beta + offset)
        return float(np.sum(loglik_rows(y, mu, alpha))), alpha_score(y, mu, alpha), beta

    profile = [evaluate(theta) for theta in _GRID]
    values = np.array([item[0] for item in profile])
    if not np.isfinite(values).all():
        raise FieldError(MODE, "Estimated ML did not converge: the likelihood is not finite over the range of alpha.")
    best = int(np.argmax(values))
    if best == 0:
        raise FieldError(MODE, "Estimated ML has no interior maximum: the likelihood keeps increasing toward "
                               "alpha = 0, the Poisson boundary (the counts are not overdispersed). Use Fixed "
                               "dispersion or Poisson regression.")
    if best == len(_GRID) - 1:
        raise FieldError(MODE, f"Estimated ML has no interior maximum: the likelihood keeps increasing beyond "
                               f"alpha = {ALPHA_MAX:g}. Use Fixed dispersion.")
    low, high = _GRID[best - 1], _GRID[best + 1]
    score_low, score_high = profile[best - 1][1], profile[best + 1][1]
    state["beta"] = profile[best][2]
    try:
        if score_low > 0 > score_high:
            theta = optimize.brentq(lambda t: evaluate(t)[1], low, high, xtol=1e-14, rtol=4 * np.finfo(float).eps,
                                    maxiter=200)
        else:
            found = optimize.minimize_scalar(lambda t: -evaluate(t)[0], bounds=(low, high), method="bounded",
                                             options={"xatol": 1e-12, "maxiter": 500})
            if not found.success:
                raise RuntimeError(found.message)
            theta = float(found.x)
    except (RuntimeError, ValueError) as error:
        if isinstance(error, FieldError):
            raise
        raise FieldError(MODE, "Estimated ML did not converge while solving for alpha.") from error
    alpha = float(np.exp(theta))
    if not ALPHA_MIN * (1 + 1e-9) < alpha < ALPHA_MAX * (1 - 1e-9):
        raise FieldError(MODE, f"Estimated ML stopped at alpha = {alpha:.6g}, a limit of the supported range, so "
                               "it is not an estimate. Use Fixed dispersion.")
    state["beta"] = profile[best][2]
    _, _, beta = evaluate(theta)
    return beta, alpha


def _observed_information(X, y, mu, alpha):
    """−Hessian of ℓ in (β, α)."""
    u = alpha * mu
    beta_block = (X * (mu * (1 + alpha * y) / (1 + u) ** 2)[:, None]).T @ X
    cross = X.T @ (mu * (y - mu) / (1 + u) ** 2)
    information = np.empty((X.shape[1] + 1,) * 2)
    information[:-1, :-1] = beta_block
    information[:-1, -1] = information[-1, :-1] = cross
    information[-1, -1] = -_alpha_curvature(y, mu, alpha)
    return information


def _inverse(information, field, template):
    """The covariance, or a FieldError naming why the information matrix cannot be inverted."""
    reason = None
    if not np.isfinite(information).all():
        reason = "not finite"
    else:
        eigenvalues = np.linalg.eigvalsh(information)
        if eigenvalues[0] <= 0:
            reason = "not positive definite"
        elif eigenvalues[-1] > 1e14 * eigenvalues[0]:
            reason = "nearly singular"
    if reason is not None:
        raise FieldError(field, template.format(reason=reason))
    return linalg.cho_solve(linalg.cho_factor(information), np.eye(len(information)))


# ----- analysis ------------------------------------------------------------------------------------------------------

def fit(frame, options):
    """Validate and fit once. Returns the settings, the prepared data and the estimates on the original scale."""
    s = settings(frame, options)
    data = prepare(frame, s)
    X = data.design.to_numpy(dtype=float)
    # Columns are rescaled by their largest magnitude for the solver; estimates and covariance are scaled back.
    scale = np.max(np.abs(X), axis=0)
    scale[scale == 0] = 1.0
    scaled = X / scale
    offset = np.log(data.exposure)
    y = data.y
    if s.mode == FIXED:
        alpha = s.alpha
        try:
            beta = fit_beta(scaled, y, offset, alpha)
        except _NoConvergence as error:
            raise FieldError(PREDICTORS, "The regression did not converge. Check categories or predictor ranges "
                                         "whose counts are all zero.") from error
        mu = np.exp(scaled @ beta + offset)
        fisher = (scaled * (mu / (1 + alpha * mu))[:, None]).T @ scaled
        covariance = _inverse(fisher, PREDICTORS, "The Fisher information is {reason} at the estimate, so the "
                                                  "standard errors are not identifiable for these data.")
        covariance_type, parameters = FISHER, X.shape[1]
    else:
        beta, alpha = _profile_ml(scaled, y, offset)
        mu = np.exp(scaled @ beta + offset)
        covariance = _inverse(_observed_information(scaled, y, mu, alpha), MODE,
                              "Estimated ML: the Hessian is {reason} at the estimate, so alpha and the standard "
                              "errors are not identifiable for these data.")
        covariance = covariance[:-1, :-1]
        covariance_type, parameters = OBSERVED, X.shape[1] + 1
    beta = beta / scale
    covariance = covariance / np.outer(scale, scale)
    return s, data, beta, covariance, alpha, mu, covariance_type, parameters


def _tables(s, data, beta, covariance, alpha, mu, covariance_type, parameters):
    se = np.sqrt(np.diag(covariance))
    z = norm.ppf(0.5 + s.level / 200)
    lower, upper = beta - z * se, beta + z * se
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        coefficients = pd.DataFrame({"Estimate": beta, "SE": se, "p": 2 * norm.sf(np.abs(beta / se)),
                                     "Lower": lower, "Upper": upper, "IRR": np.exp(beta),
                                     "IRR lower": np.exp(lower), "IRR upper": np.exp(upper)},
                                    index=data.design.columns)
    if not np.isfinite(coefficients.to_numpy(dtype=float)).all():
        raise FieldError(PREDICTORS, "The estimates or their exponentials are outside the supported numeric range. "
                                     "Rescale the predictors.")
    y = data.y
    variance = mu + alpha * mu ** 2
    log_likelihood = float(np.sum(loglik_rows(y, mu, alpha)))
    fitted = pd.DataFrame({"Source row": data.rows + 1, "Observed": y, "Exposure": data.exposure,
                           "Fitted count": mu, "Fitted rate": mu / data.exposure, "Variance": variance,
                           "Pearson residual": (y - mu) / np.sqrt(variance)})
    if not (np.isfinite(fitted.to_numpy(dtype=float)).all() and np.isfinite(log_likelihood)):
        raise FieldError(PREDICTORS, "The fitted values are outside the supported numeric range. "
                                     "Rescale the predictors or the exposure.")
    model = pd.DataFrame([[len(y), data.total - len(y), s.mode, alpha, parameters, log_likelihood,
                           -2 * log_likelihood + 2 * parameters, covariance_type]],
                         columns=FIT_COLUMNS, index=["NB2"])
    tables = {COEFFICIENTS: coefficients, MODEL_FIT: model, FITTED: fitted}
    if data.references:
        tables[REFERENCES] = pd.DataFrame.from_dict(data.references, orient="index", columns=["Reference"])
    return tables


def residual_figure(fitted):
    """Pearson residual against the fitted count, with the zero reference, from the computed sheet."""
    figure, axes = _plot(FIGURE_TITLE, "Fitted count", "Pearson residual")
    axes.scatter(fitted["Fitted count"].to_numpy(float), fitted["Pearson residual"].to_numpy(float), zorder=2)
    axes.axhline(0, color="#7f8c99", linewidth=1, zorder=1)
    return figure


def analysis(frame, options):
    """One fit per call: the sheets and, when asked, the residual figure drawn from the same fit."""
    fitted = fit(frame, options)
    tables = _tables(*fitted)
    figure = residual_figure(tables[FITTED]) if fitted[0].plot else None
    return Result(tables, figure)
