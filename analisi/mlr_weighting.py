"""Fixed observation weights for the Gaussian family of Multiple regression.

The weights come from the observed data and never from fitted values, so this is ordinary weighted least squares
and not an IRLS: 1/|Y|, 1/Y², 1/|Y|^K, 1/SD² or a positive weight column. Everything is carried on a log scale
first, normalised to a maximum of 1 and only then turned into the weights used by the fit, so a common factor on
the weights or the SDs (1e±150) or an SD of 1e-200 cannot overflow, underflow or change a coefficient, an SE, an
interval or any dimensionless diagnostic.

Variance model: Var(y_i) = sigma² / wNorm_i with wNorm = w / max(w); sigma² is therefore the variance of a
observation that carries the largest weight. The fit solves sqrt(wNorm)·D b ≈ sqrt(wNorm)·y with statsmodels WLS
(SVD pseudo-inverse) after a rank check on that weighted matrix; the normal equations are never inverted.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import WLS

from . import models
from .processing import FieldError
from .stats import complete

GAUSSIAN_WEIGHTING = "Gaussian weighting"
EXPONENT = "Weight exponent K"
SD_COLUMN = "Gaussian SD column"
WEIGHT_COLUMN = "Gaussian weight column"
FUTURE_PRECISION = "Weighted prediction intervals"

UNWEIGHTED = "Unweighted"
ABS_Y = "1/abs(Y)"
Y_SQUARED = "1/Y²"
ABS_Y_POWER = "1/abs(Y)^K"
INVERSE_VARIANCE = "Inverse variance (SD column)"
FROM_COLUMN = "Weight column"
MODES = (UNWEIGHTED, ABS_Y, Y_SQUARED, ABS_Y_POWER, INVERSE_VARIANCE, FROM_COLUMN)
DEFAULT_EXPONENT = 1.0
KEYS = (GAUSSIAN_WEIGHTING, EXPONENT, SD_COLUMN, WEIGHT_COLUMN, FUTURE_PRECISION)
WEIGHTS_SHEET = "Linear weights"
# A normalised weight below the smallest normal double would lose precision or collapse to zero.
_SMALLEST = np.finfo(float).tiny


@dataclass(frozen=True)
class Weights:
    """Weights of the fitted rows, in the order of the fit."""
    mode: str
    exponent: float | None
    index: np.ndarray
    observed: np.ndarray
    log_weight: np.ndarray
    relative_log: np.ndarray
    normalized: np.ndarray
    raw: np.ndarray
    log_max: float

    @property
    def root(self):
        return np.sqrt(self.normalized)

    def future_sd(self, residual_variance, weight):
        """Combine the variance and weight exponents before taking the SD.

        The raw weight ratio, or even its product with the variance, may
        overflow while the future SD and confidence endpoints remain finite.
        """
        if residual_variance == 0:
            return 0.
        return float(np.exp(.5*(np.log(residual_variance) + self.log_max - np.log(weight))))


def mode(options):
    """The chosen weighting. A missing key or an empty choice keeps the historical unweighted fit."""
    if GAUSSIAN_WEIGHTING not in options or options[GAUSSIAN_WEIGHTING] in (None, ""):
        return UNWEIGHTED
    choice = options[GAUSSIAN_WEIGHTING]
    if not isinstance(choice, str) or choice not in MODES:
        raise FieldError(GAUSSIAN_WEIGHTING, "Choose Unweighted, 1/abs(Y), 1/Y², 1/abs(Y)^K, "
                                             "Inverse variance (SD column) or Weight column.")
    return choice


def weighted(options):
    return mode(options) != UNWEIGHTED


def exponent(options):
    """K of 1/|Y|^K: any finite number, 1 when the key is missing."""
    if EXPONENT not in options or options[EXPONENT] in (None, ""):
        return DEFAULT_EXPONENT
    raw = options[EXPONENT]
    try:
        value = np.nan if isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError, OverflowError):
        value = np.nan
    if not np.isfinite(value):
        raise FieldError(EXPONENT, "Weight exponent K must be a finite number.")
    return value


def future_precision(options):
    """True when profiles carry the precision of a future observation."""
    if FUTURE_PRECISION not in options:
        return False
    value = options[FUTURE_PRECISION]
    if not isinstance(value, bool):
        raise FieldError(FUTURE_PRECISION, f"{FUTURE_PRECISION} must be yes or no.")
    return value


def validate(options):
    """Check the Gaussian keys that the chosen mode uses, without reading data. Returns the mode."""
    choice = mode(options)
    if choice == ABS_Y_POWER:
        exponent(options)
    if choice != UNWEIGHTED:
        future_precision(options)
    return choice


def _column(options, key, response, predictors, frame):
    column = options.get(key)
    if column in (None, ""):
        raise FieldError(key, f"Choose a column for {key}.")
    if not isinstance(column, str) or column not in frame.columns:
        raise FieldError(key, f"Choose an existing column for {key}.")
    if column == response or column in predictors:
        raise FieldError(key, f"{key} must be a column distinct from the response and the predictors.")
    return column


def _precision(frame, data, mask, column, key, positive_label):
    """Precision values of the complete rows. Missing rows leave the fit; present bad values name their row."""
    series = frame[column].iloc[np.flatnonzero(mask)]
    numeric = pd.to_numeric(series, errors="coerce")
    if np.iscomplexobj(numeric.to_numpy()):
        raise FieldError(key, f'Column "{column}" contains complex data.')
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    present = series.notna().to_numpy()
    with np.errstate(invalid="ignore"):
        invalid = present & ~(np.isfinite(values) & (values > 0))
    if invalid.any():
        first = int(np.flatnonzero(invalid)[0])
        raise FieldError(key, f'Column "{column}" needs finite {positive_label} greater than 0 '
                              f"(source row {series.index[first]}: {series.iloc[first]!r}).")
    return values, present


def _log_weights(choice, k, observed, precision, index):
    """(log weight in raw units or NaN when not representable, log weight relative to the largest, at most 0).

    Weights from Y take the differences of the logs first and multiply by the exponent afterwards: equal weights
    stay equal for any K, and no inf - inf can appear. Adding 0.0 turns a -0.0 into 0.0 (the sheet never shows "-0").
    """
    if choice in (INVERSE_VARIANCE, FROM_COLUMN):
        raw = (-2.0 * np.log(precision) if choice == INVERSE_VARIANCE else np.log(precision)) + 0.0
        return raw, raw - raw.max() + 0.0 if len(raw) else raw
    power = {ABS_Y: 1.0, Y_SQUARED: 2.0, ABS_Y_POWER: k}[choice]
    if power == 0:
        return np.zeros(len(observed)), np.zeros(len(observed))
    magnitude = np.abs(observed)
    if (magnitude == 0).any():
        row = index[int(np.flatnonzero(magnitude == 0)[0])]
        raise FieldError(GAUSSIAN_WEIGHTING, f"The {choice} weighting cannot be used with a Y value of zero "
                                             f"(source row {row}).")
    with np.errstate(all="ignore"):
        logs = np.log(magnitude)
        # The largest weight sits at the smallest |Y| for a positive power and at the largest |Y| for a negative one.
        reference = logs.min() if power > 0 else logs.max()
        relative = -power * (logs - reference) + 0.0
        raw = relative - power * reference
    return np.where(np.isfinite(raw), raw, np.nan), relative


def _raw(choice, k, observed, precision, log_weight):
    """Weight in raw units, or NaN where the double range cannot hold it."""
    with np.errstate(all="ignore"):
        if choice == FROM_COLUMN:
            raw = precision.copy()
        elif choice == INVERSE_VARIANCE:
            raw = 1.0 / (precision * precision)
        else:
            raw = np.abs(observed) ** -{ABS_Y: 1.0, Y_SQUARED: 2.0, ABS_Y_POWER: k}[choice]
    return np.where(np.isfinite(raw) & (raw >= _SMALLEST), raw, np.nan)


def prepare(frame, options):
    """The complete, weighted rows of the fit, with their categories learned only from those rows.

    Rows lacking the response, a predictor or a category leave first; a precision column is read only on the
    survivors (a bad value on an already incomplete row is not examined), and a missing precision removes its
    row. The index of the source worksheet is kept and the worksheet is never modified.
    """
    choice = validate(options)
    if choice == UNWEIGHTED:
        raise ValueError("Choose a Gaussian weighting.")
    response, predictors = options["Response"], options["Predictors"]
    categories = options["Categorical predictors"]
    k = exponent(options) if choice == ABS_Y_POWER else None
    column = key = None
    if choice in (INVERSE_VARIANCE, FROM_COLUMN):
        key = SD_COLUMN if choice == INVERSE_VARIANCE else WEIGHT_COLUMN
        column = _column(options, key, response, predictors, frame)
    numeric = [response, *[name for name in predictors if name not in categories]]
    if not predictors or not set(categories).issubset(predictors):
        raise ValueError("Choose predictors and identify any categorical predictors from that list.")
    data = complete(frame, numeric, categories)
    names = [*numeric, *categories]
    mask = frame.loc[:, names].notna().to_numpy().all(axis=1)
    if int(mask.sum()) != len(data):
        raise ValueError("The complete rows of the model could not be identified.")
    precision = np.full(len(data), np.nan)
    if column is not None:
        precision, kept = _precision(frame, data, mask, column, key,
                                     "SD values" if choice == INVERSE_VARIANCE else "weights")
        data, precision = data.loc[kept], precision[kept]
    observed = data[response].to_numpy(dtype=float)
    field = EXPONENT if choice == ABS_Y_POWER else GAUSSIAN_WEIGHTING
    log_weight, relative = _log_weights(choice, k, observed, precision, data.index.to_numpy())
    if not np.isfinite(relative).all():
        raise FieldError(key or field, f"The {choice} weights are outside the numeric range.")
    with np.errstate(under="ignore"):
        normalized = np.exp(relative)
    if not (np.isfinite(normalized).all() and (normalized >= _SMALLEST).all()):
        raise FieldError(key or field, "The ratio between the largest and the smallest weight is outside the "
                                       "numeric range: a weight would be zero relative to the largest one.")
    log_max = float(log_weight[relative == 0][0]) if np.isfinite(log_weight[relative == 0]).any() else np.nan
    return data, Weights(choice, k, data.index.to_numpy(), observed, log_weight, relative, normalized,
                         _raw(choice, k, observed, precision, log_weight), log_max)


def weights_table(weights):
    table = pd.DataFrame({"Source row": weights.index, "Observed": weights.observed, "Weight": weights.raw,
                          "Normalized weight": weights.normalized, "Log weight": weights.log_weight,
                          "Relative log weight": weights.relative_log})
    blank_log, blank_raw = np.isnan(weights.log_weight), np.isnan(weights.raw)
    if blank_log.any() or blank_raw.any():
        table["Note"] = np.select(
            [blank_log, blank_raw],
            ["Raw weight and its log are outside the double range; use Relative log weight (log of the weight "
             "relative to the largest) and Normalized weight.",
             "Raw weight is outside the double range; use Log weight and Normalized weight."], "")
    return table


def _model_rows(weights):
    rows = {"Gaussian weighting": weights.mode}
    if weights.exponent is not None:
        rows[EXPONENT] = weights.exponent
    if weights.mode in (ABS_Y, Y_SQUARED, ABS_Y_POWER):
        rows["Inference"] = ("Weights come from the observed Y, an empirical choice: standard errors and intervals "
                             "are conditional on those fixed weights and do not include the uncertainty of "
                             "choosing them; exact coverage or robustness is not promised.")
    rows["Variance units"] = ("Var(y) = sigma² / normalized weight; the residual variance is sigma² for the "
                              "observation with the largest weight (normalized weight 1).")
    rows["R² basis"] = "Weighted R², from the weights normalized to a maximum of 1."
    rows["AIC basis"] = ("Gaussian log likelihood of the fixed weights normalized to a maximum of 1; compare it only "
                         "between models fitted to the same rows with the same weights, never with an unweighted AIC.")
    return rows


def weighted_linear_fit(frame, options):
    """One weighted least-squares fit. Same tuple as ``models.linear_fit`` plus the :class:`Weights`."""
    data, weights = prepare(frame, options)
    response, predictors = options["Response"], options["Predictors"]
    try:
        design, references = models._design(data, predictors, options["Categorical predictors"], True)
    except ValueError as error:
        raise FieldError("Predictors", str(error)) from error
    root = weights.root
    if np.linalg.matrix_rank(root[:, None] * design.to_numpy()) < design.shape[1]:
        raise FieldError("Predictors", "The model is rank deficient after weighting. Remove redundant predictors "
                         "or check the weights.")
    observed = data[response]
    try:
        model = WLS(observed, design, weights=weights.normalized).fit()
    except np.linalg.LinAlgError as error:
        raise ValueError("Could not estimate the model reliably. Check separation and predictor variance.") from error
    if int(model.model.rank) < design.shape[1]:
        raise FieldError("Predictors", "The model is rank deficient after weighting. Remove redundant predictors "
                         "or check the weights.")
    tables = models._report(model, design, references, len(frame), False)
    summary = tables["Model"]["Value"].to_dict()
    summary.update(_model_rows(weights))
    tables["Model"] = pd.DataFrame.from_dict(summary, orient="index", columns=["Value"])
    prediction = np.asarray(model.fittedvalues)
    tables["Fitted values"] = pd.DataFrame({"Observed": observed, "Fitted": prediction,
                                            "Residual": observed - prediction})
    tables[WEIGHTS_SHEET] = weights_table(weights)
    return (tables, model, design, references, data), weights
