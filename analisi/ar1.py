"""Marginal AR(1) restricted likelihood for one ordered within-subject factor.

Subjects are independent. Within a subject the marginal covariance is
``sigma² rho**|i-j|`` on the confirmed visit indices, including a gap where a
visit in that order was not observed. There is no random intercept. The profile
is accumulated from subject blocks, so the working matrices stay the size of one
subject's visits and of the fixed effects.
"""
from dataclasses import dataclass

import numpy as np
from scipy import linalg, optimize

from .field_error import FieldError

SUBJECT_EFFECTS = "Subject random effects"
AR1 = "AR(1) for ordered visits"
COVARIANCE = "Covariance structure"
VISIT_ORDER = "Visit order"
WALD_DF = "Wald (approximate residual df)"

ONE_WITHIN = "AR(1) needs exactly one within-subject factor."
ORDER_REQUIRED = "Confirm the full visit order. List each observed visit once."
ORDER_REPEATED = "Visit order lists a visit more than once."
ORDER_MISMATCH = "Visit order must list each observed visit once."
NO_CORRELATION = "These data have no information to estimate the within-subject correlation."
UNKNOWN_STRUCTURE = "Choose subject random effects or AR(1) for ordered visits."

REASON_LIMIT = "The correlation is at a limit and is not estimable."
REASON_VARIANCE = "No measurable residual variation for the mixed model."
REASON_DF = "Residual degrees of freedom are zero."
REASON_RANK = "The fixed effects do not have full rank, so the model is not estimable."
REASON_CORRELATION = "The correlation is not estimable."
CANCELLED = "The mixed-model fit was cancelled."

_PENALTY = 1e300


class MixedModelCancelled(Exception):
    """The worker's cancel flag was set during an AR(1) fit."""


@dataclass
class Ar1Fit:
    beta: np.ndarray | None
    covariance: np.ndarray | None
    sigma2: float
    rho: float
    df: int
    reason: str | None


def format_error(error):
    """The engine's English message in the language of the interface."""
    from .i18n import translate_message

    return translate_message(str(error), "mixed.error.")


def stopped(cancel):
    if cancel is None:
        return False
    flag = getattr(cancel, "is_set", None)
    return bool(flag() if flag is not None else cancel())


def within_subject_correlation(times, rho):
    """Correlation of one subject. ``times`` are indices in the confirmed order."""
    times = np.asarray(times, dtype=int)
    lag = np.abs(times[:, None] - times[None, :])
    magnitude = np.power(float(abs(rho)), lag, dtype=float)
    if rho < 0:
        magnitude = np.where(lag % 2, -magnitude, magnitude)
    np.fill_diagonal(magnitude, 1.0)
    return magnitude


def align_visit_order(requested, levels):
    """Return ``levels`` in the confirmed order, or raise a field error."""
    levels = list(levels)
    if requested is None or requested == "" or (isinstance(requested, (list, tuple)) and not requested):
        raise FieldError(VISIT_ORDER, ORDER_REQUIRED)
    if isinstance(requested, str):
        text = requested.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        items = [part.strip().strip("'\"") for part in text.split(",")]
        items = [part for part in items if part]
    elif isinstance(requested, (list, tuple)):
        items = list(requested)
    else:
        raise FieldError(VISIT_ORDER, ORDER_REQUIRED)
    texts = [str(item).strip() for item in items]
    if len(texts) != len(set(texts)):
        raise FieldError(VISIT_ORDER, ORDER_REPEATED)
    by_text = {}
    for level in levels:
        key = str(level)
        if key in by_text and by_text[key] != level:
            raise FieldError(VISIT_ORDER, ORDER_MISMATCH)
        by_text[key] = level
    if set(texts) != set(by_text):
        raise FieldError(VISIT_ORDER, ORDER_MISMATCH)
    return [by_text[key] for key in texts]


def _patterns(y, cells, subjects, times):
    y = np.asarray(y, dtype=float)
    cells = np.asarray(cells, dtype=int)
    subjects = np.asarray(subjects, dtype=int)
    times = np.asarray(times, dtype=int)
    order = np.lexsort((times, subjects))
    y, cells, subjects, times = y[order], cells[order], subjects[order], times[order]
    splits = np.flatnonzero(np.diff(subjects)) + 1
    grouped = {}
    for index in np.split(np.arange(len(y)), splits):
        key = tuple(int(value) for value in times[index])
        grouped.setdefault(key, []).append((cells[index], y[index]))
    patterns = []
    for key, rows in grouped.items():
        patterns.append((
            np.asarray(key, dtype=int),
            np.vstack([item[0] for item in rows]),
            np.vstack([item[1] for item in rows]),
        ))
    return patterns


def _profile(patterns, rho, n_cells, df, cancel):
    """Profiled REML objective and, when the rho is usable, the GLS quantities."""
    if stopped(cancel):
        raise MixedModelCancelled(CANCELLED)
    gram = np.zeros((n_cells, n_cells))
    rhs = np.zeros(n_cells)
    logdet = 0.0
    prepared = []
    for times, cells, response in patterns:
        count, width = response.shape
        try:
            lower = linalg.cholesky(within_subject_correlation(times, rho), lower=True, check_finite=False)
        except linalg.LinAlgError:
            return None
        diagonal = np.diag(lower)
        if np.any(diagonal <= 0) or not np.isfinite(diagonal).all():
            return None
        logdet += count * 2 * np.log(diagonal).sum()
        inverse = linalg.solve_triangular(lower, np.eye(width), lower=True, check_finite=False)
        precision = inverse.T @ inverse
        np.add.at(rhs, cells, response @ precision)
        for left in range(width):
            for right in range(width):
                np.add.at(gram, (cells[:, left], cells[:, right]), precision[left, right])
        prepared.append((cells, response, inverse))
    gram = (gram + gram.T) / 2
    try:
        factor = linalg.cho_factor(gram, lower=True, check_finite=False)
    except linalg.LinAlgError:
        return None
    diagonal = np.diag(factor[0])
    if np.any(diagonal <= 0) or not np.isfinite(diagonal).all():
        return None
    beta = linalg.cho_solve(factor, rhs, check_finite=False)
    logdet += 2 * np.log(diagonal).sum()
    rss = 0.0
    for cells, response, inverse in prepared:
        whitened = (response - beta[cells]) @ inverse.T
        rss += float(np.sum(whitened * whitened))
    sigma2 = rss / df
    if not np.isfinite(sigma2) or sigma2 <= np.finfo(float).eps ** 2:
        return None
    objective = df * np.log(sigma2) + logdet
    if not np.isfinite(objective):
        return None
    covariance = sigma2 * linalg.cho_solve(factor, np.eye(n_cells), check_finite=False)
    return objective, beta, sigma2, covariance


def fit_ar1(y, cells, subjects, times, n_cells, *, cancel=None):
    """REML estimates in the original response units, or a reason with empty estimates."""
    if stopped(cancel):
        raise MixedModelCancelled(CANCELLED)
    y = np.asarray(y, dtype=float)
    df = int(len(y) - n_cells)
    failed = Ar1Fit(None, None, np.nan, np.nan, df, REASON_DF)
    if df <= 0:
        return failed
    origin = float(y[0])
    centered = y - origin
    scale = float(np.max(np.abs(centered)))
    if not np.isfinite(scale) or scale == 0.0:
        return Ar1Fit(None, None, np.nan, np.nan, df, REASON_VARIANCE)
    patterns = _patterns(centered / scale, cells, subjects, times)

    def objective(rho):
        profile = _profile(patterns, float(rho), n_cells, df, cancel)
        return _PENALTY if profile is None else profile[0]

    grid = np.linspace(-0.98, 0.98, 50)
    scores = np.array([objective(rho) for rho in grid])
    if not np.isfinite(scores).any() or float(scores.min()) >= _PENALTY / 10:
        return Ar1Fit(None, None, np.nan, np.nan, df, REASON_RANK)
    optimum = optimize.minimize_scalar(
        objective, bounds=(-0.999, 0.999), method="bounded", options={"xatol": 1e-12})
    candidates = [float(grid[int(np.argmin(scores))])]
    if optimum.success and np.isfinite(optimum.x):
        candidates.append(float(optimum.x))
    best = None
    rho = candidates[0]
    for candidate in candidates:
        profile = _profile(patterns, candidate, n_cells, df, cancel)
        if profile is not None and (best is None or profile[0] < best[0]):
            best = profile
            rho = float(candidate)
    if best is None:
        return Ar1Fit(None, None, np.nan, np.nan, df, REASON_CORRELATION)
    value, beta, sigma2, covariance = best
    left = objective(-0.999)
    right = objective(0.999)
    margin = 1e-3
    if abs(rho) >= 0.998 or left <= value + margin or right <= value + margin:
        return Ar1Fit(None, None, np.nan, np.nan, df, REASON_LIMIT)
    beta = origin + scale * beta
    covariance = covariance * scale ** 2
    sigma2 = sigma2 * scale ** 2
    if not np.isfinite(beta).all() or not np.isfinite(covariance).all() or not np.isfinite(sigma2):
        return Ar1Fit(None, None, np.nan, np.nan, df, REASON_VARIANCE)
    return Ar1Fit(beta, covariance, float(sigma2), rho, df, None)
