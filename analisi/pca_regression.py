"""Principal component regression on the retained scores of the PCA fit.

The PCA is the one the analysis already estimated: every row that is complete in the predictors, in
the table order, with the response left out. Its retained components give the scores, and the
response is regressed on ``[1, score_1 .. score_k]`` by ordinary least squares over the rows that
also have a finite response. Rows with a missing or excluded response keep their place in the PCA
and still receive a fitted value and pointwise intervals.

The slopes on the scores are carried back to the units of the original columns with
B = diag(1/s) V_k, where s are the sample deviations (one for a centered-only PCA) and V_k the
retained eigenvectors. The original slopes are beta = B b and the original intercept is
b0 - mu' beta, so the coefficient transformation is

    T = [[1, -mu' B], [0, B]],     beta_original = T b,     Cov = T C T'.

Inference uses Student's t with n - k - 1 degrees of freedom and is conditional on the estimated
projection: the PCA eigenvectors are treated as fixed. Mean and prediction limits are pointwise.

Row identity and row position are kept apart. ``Source row`` carries the table index, which may be
text or repeated; predictors, scores and the response are matched by their position in the mask of
complete predictor rows, never by a join on the index.

The fit is an SVD of the column-equilibrated design. With A = Z D = U S V' and D = diag(1/|z_j|),
the coefficients are b = D V S^-1 U'y and (Z'Z)^-1 = W W' for W = D V S^-1, so every variance is a
sum of squares and cannot come out negative from roundoff.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from . import exploration, pca_retention
from .data import decimal_comma
from .field_error import FieldError
from .reporting import _plot

ENABLE = "Principal component regression"
RESPONSE = "PCR response"
CONFIDENCE = "PCR confidence (%)"
PLOT = "PCR plot"
KEEP, OBSERVED, RESIDUALS = "Keep PCA", "Observed vs fitted", "Residuals vs fitted"
PLOTS = (KEEP, OBSERVED, RESIDUALS)
DEFAULT_CONFIDENCE = 95.0
OPTION_NAMES = frozenset((ENABLE, RESPONSE, CONFIDENCE, PLOT))
DEPENDENT = (RESPONSE, CONFIDENCE, PLOT)
TABS = {"Regression": (ENABLE, RESPONSE, CONFIDENCE, PLOT)}
LABEL_KEYS = {
    "Regression": "analysis.pca.regression.tab",
    ENABLE: "analysis.pca.regression.enable",
    RESPONSE: "analysis.pca.regression.response",
    CONFIDENCE: "analysis.pca.regression.confidence",
    PLOT: "analysis.pca.regression.plot",
}
CHOICE_KEYS = {
    KEEP: "analysis.pca.regression.plot.keep",
    OBSERVED: "analysis.pca.regression.plot.observed",
    RESIDUALS: "analysis.pca.regression.plot.residuals",
}

COEFFICIENTS = "PCR coefficients"
SCORE_COEFFICIENTS = "PCR scores coefficients"
MODEL = "PCR model"
FITTED = "PCR fitted values"
SHEETS = (COEFFICIENTS, SCORE_COEFFICIENTS, MODEL, FITTED)

NOTE = ("The PCA is estimated once, on every row that is complete in the predictors, and the response does not "
        "enter it. The fit regresses the response on the retained scores over the rows that also have a response. "
        "Inference is conditional on that estimated projection. Mean and prediction limits are pointwise: they "
        "describe one row at a time and are not simultaneous bands.")

# A design whose smallest scaled singular value falls below this multiple of the roundoff is rank deficient.
_RANK_FACTOR = 16
# A residual below this multiple of the response magnitude, in units of the roundoff, is an exact fit.
_EXACT_FACTOR = 64


@dataclass(frozen=True)
class Config:
    """Validated PCR request: the response column, the confidence level in percent and the plot choice."""
    response: str
    level: float
    plot: str


@dataclass
class Regression:
    """The PCR sheets, appended after the PCA sheets, and the figure when a PCR plot replaces the PCA one."""
    tables: dict
    figure: object = None


def _flag(value, field):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise FieldError(field, f"{field} must be on or off.")


def requested(options):
    """True only when the recipe explicitly turned PCR on. Dependent keys are ignored while it is off."""
    if ENABLE not in options:
        return False
    return _flag(options[ENABLE], ENABLE)


def _level(value):
    if isinstance(value, (bool, np.bool_)) or value is None:
        number = np.nan
    else:
        try:
            number = float(decimal_comma(value) if isinstance(value, str) else value)
        except (TypeError, ValueError, OverflowError):
            number = np.nan
    if not np.isfinite(number) or not 0 < number < 100:
        raise FieldError(CONFIDENCE, f"{CONFIDENCE} must be greater than 0 and less than 100.")
    return float(number)


def _plot_choice(value):
    if value in (None, ""):
        return KEEP
    if value not in PLOTS:
        raise FieldError(PLOT, f"Choose a {PLOT}.")
    return value


def settings(frame, options):
    """Validate the PCR keys without calculating anything. None when PCR is off.

    The dependent keys are read only after the switch is on, so a stale or invalid value saved with PCR
    off never raises.
    """
    if not requested(options):
        return None
    predictors = list(options["Variables"])
    response = options.get(RESPONSE)
    if not isinstance(response, str) or not response:
        raise FieldError(RESPONSE, f"Choose a column for {RESPONSE}.")
    if response not in frame:
        raise FieldError(RESPONSE, f'Column "{response}" is not in the table.')
    if response in predictors:
        raise FieldError(RESPONSE, f"{RESPONSE} must be a column that is not one of the PCA variables.")
    level = _level(options.get(CONFIDENCE, DEFAULT_CONFIDENCE))
    return Config(response, level, _plot_choice(options.get(PLOT)))


def predictor_mask(frame, predictors):
    """Rows kept by the PCA filter, in table order."""
    mask = np.ones(len(frame), dtype=bool)
    for name in predictors:
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
        mask &= frame[name].notna().to_numpy() & np.isfinite(values)
    return mask


def retained_components(parts, retention):
    """Names of the components the regression uses, in the order of the PCA selection sheet.

    A criterion other than All follows the Retained flags of the PCA selection sheet. Without that sheet
    (All, or a recipe with no selection key) every component of numerically positive rank is used.
    """
    names = list(parts.index)
    sheet = retention.tables.get(pca_retention.SELECTION_SHEET)
    if sheet is None:
        flags = pca_retention.living(parts["Eigenvalue"].to_numpy(dtype=float))
    else:
        flags = sheet["Retained"].to_numpy(dtype=bool)
    kept = [name for name, flag in zip(names, flags) if flag]
    if not kept:
        raise FieldError(pca_retention.SELECTION,
                         f"{pca_retention.SELECTION} retains no components, so there is nothing to regress on.")
    return kept


def _response_values(frame, mask, config):
    """Numeric response for the rows of the mask, NaN where it is empty. Text or infinity is an error."""
    series = frame[config.response]
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    present = series.notna().to_numpy()
    bad = mask & present & ~np.isfinite(numeric)
    if bad.any():
        row = int(np.flatnonzero(bad)[0]) + 1
        raise FieldError(RESPONSE, f'Column "{config.response}" has a non-numeric or infinite value in row {row}. '
                                   "Empty cells are allowed; text and infinity are not.")
    return numeric[mask]


def _range_error():
    return FieldError(RESPONSE, "The values are outside the supported numeric range for this regression.")


def _least_squares(design, y):
    """Coefficients and the factor W with (Z'Z)^-1 = W W', after checking n > columns and full rank."""
    rows, columns = design.shape
    if rows <= columns:
        raise FieldError(RESPONSE, f"{RESPONSE} needs more than {columns} rows with a response for "
                                   f"{columns - 1} component(s); {rows} found.")
    with np.errstate(all="ignore"):
        norms = np.linalg.norm(design, axis=0)
    if not np.isfinite(norms).all():
        raise _range_error()
    if (norms == 0).any():
        raise FieldError(RESPONSE, f"The rows with a response lose rank: the {columns - 1} retained score(s) "
                                   "and the intercept are not independent on them.")
    try:
        with np.errstate(all="ignore"):
            u, singular, vt = np.linalg.svd(design / norms, full_matrices=False)
    except np.linalg.LinAlgError:
        raise _range_error() from None
    if not np.isfinite(singular).all():
        raise _range_error()
    tolerance = _RANK_FACTOR * max(design.shape) * np.finfo(float).eps
    if singular[-1] <= singular[0] * tolerance:
        raise FieldError(RESPONSE, f"The rows with a response lose rank: the {columns - 1} retained score(s) "
                                   "and the intercept are not independent on them.")
    w = (vt.T / singular) / norms[:, None]
    with np.errstate(all="ignore"):
        coefficients = w @ (u.T @ y)
    return coefficients, w


def _coefficient_table(terms, estimate, variance, df, critical):
    se = np.sqrt(variance)
    with np.errstate(all="ignore"):
        t = np.where(se > 0, estimate / se, np.nan)
        p = np.where(np.isfinite(t), 2 * stats.t.sf(np.abs(t), df), np.nan)
    return pd.DataFrame({"Term": terms, "Estimate": estimate, "SE": se, "Lower": estimate - critical * se,
                         "Upper": estimate + critical * se, "t": t, "p": p})


def _figure(view, fitted, observed, residual):
    if view == OBSERVED:
        figure, axes = _plot(OBSERVED, "Fitted", "Observed")
        axes.scatter(fitted, observed)
        low, high = float(min(fitted.min(), observed.min())), float(max(fitted.max(), observed.max()))
        axes.plot([low, high], [low, high], color="#667085", linewidth=1, zorder=1)
        return figure
    figure, axes = _plot(RESIDUALS, "Fitted", "Residual")
    axes.scatter(fitted, residual)
    axes.axhline(0, color="#667085", linewidth=1, zorder=1)
    return figure


def regress(frame, options, config, parts, eigenvectors, scores, retention):
    """PCR sheets and, for an Observed or Residuals plot, the figure; reuses the PCA fit already estimated."""
    predictors = list(eigenvectors.index)
    standardize = bool(options["Standardize"])
    mask = predictor_mask(frame, predictors)
    if int(mask.sum()) != len(scores):
        raise ValueError("PCA row filter did not match the score rows.")
    names = retained_components(parts, retention)
    count = len(names)
    means, divisors, _ = exploration.pca_moments(frame, predictors, standardize)
    basis = eigenvectors[names].to_numpy(dtype=float)
    projected = scores[names].to_numpy(dtype=float)
    response = _response_values(frame, mask, config)
    used = np.isfinite(response)

    design_all = np.column_stack((np.ones(len(projected)), projected))
    coefficients, w = _least_squares(design_all[used], response[used])
    y = response[used]
    df = len(y) - count - 1

    with np.errstate(all="ignore"):
        fitted = design_all @ coefficients
        residual = y - fitted[used]
        scale = float(np.max(np.abs(y)))
        exact = bool(np.max(np.abs(residual)) <= _EXACT_FACTOR * np.finfo(float).eps * scale)
        if exact:
            residual = np.zeros_like(residual)
        sse = float(residual @ residual)
        mse = sse / df
        sst = 0.0 if np.ptp(y) == 0 else float(np.sum((y - y.mean()) ** 2))

        slopes = basis / divisors[:, None]
        transform = np.zeros((len(predictors) + 1, count + 1))
        transform[0, 0] = 1.0
        transform[0, 1:] = -(means @ slopes)
        transform[1:, 1:] = slopes
        original = transform @ coefficients
        original_variance = mse * np.sum((transform @ w) ** 2, axis=1)
        score_variance = mse * np.sum(w ** 2, axis=1)
        projection = design_all @ w
        mean_variance = mse * np.sum(projection ** 2, axis=1)
        critical = float(stats.t.isf((100 - config.level) / 200, df))
        mean_half = critical * np.sqrt(mean_variance)
        prediction_half = critical * np.sqrt(mean_variance + mse)

        if sst == 0:
            r_squared = adjusted = f_value = p_value = np.nan
        else:
            r_squared = min(1.0, max(0.0, 1.0 - sse / sst))
            adjusted = 1.0 - mse / (sst / (len(y) - 1))
            if mse == 0:
                f_value, p_value = np.inf, 0.0
            else:
                f_value = max(sst - sse, 0.0) / count / mse
                p_value = float(stats.f.sf(f_value, count, df))
    finite = (coefficients, original, original_variance, score_variance, fitted, mean_half, prediction_half,
              np.array([sse, mse, critical]))
    if not all(np.isfinite(values).all() for values in finite):
        raise _range_error()

    source = frame.index.to_numpy()[mask]
    observed_all = np.where(used, response, np.nan)
    residual_all = np.full(len(fitted), np.nan)
    residual_all[used] = residual
    tables = {
        COEFFICIENTS: _coefficient_table(["Intercept", *predictors], original, original_variance, df, critical),
        SCORE_COEFFICIENTS: _coefficient_table(["Intercept", *names], coefficients, score_variance, df, critical),
        MODEL: pd.DataFrame({
            "PCA rows": [int(mask.sum())], "Regression rows": [int(used.sum())], "Components": [count],
            "Model df": [count], "Residual df": [df], "SSE": [sse], "MSE": [mse], "R squared": [r_squared],
            "Adjusted R squared": [adjusted], "F": [f_value], "p": [p_value], "Confidence (%)": [config.level],
            "Note": [NOTE],
        }),
        FITTED: pd.DataFrame({
            "Source row": source, "Observed": observed_all, "Fitted": fitted, "Residual": residual_all,
            "Used in fit": used, "Mean lower": fitted - mean_half, "Mean upper": fitted + mean_half,
            "Prediction lower": fitted - prediction_half, "Prediction upper": fitted + prediction_half,
        }),
    }
    figure = None
    if config.plot != KEEP:
        figure = _figure(config.plot, fitted[used], response[used], residual)
    return Regression(tables, figure)
