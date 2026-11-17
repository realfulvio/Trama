"""In-sample diagnostics, classification and covariate profiles for logistic regression.

The Bernoulli model is fit once. Pearson and deviance residuals use the stable
one-sided forms so a probability at 0 or 1 stays finite when it matches the
outcome. Profile intervals are the expit of a normal interval on the linear
predictor: uncertainty of the conditional mean probability at that profile,
not a prediction interval for a new binary outcome. Fit metrics are in-sample.
"""
import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit

from .processing import FieldError
from .reporting import Result
from .roc import _auc

LOGISTIC_DIAGNOSTICS = "Logistic diagnostics"
LOGISTIC_CUTOFF = "Logistic cutoff"
LOGISTIC_PROFILES = "Logistic profiles"
LOGISTIC_CI = "Logistic confidence (%)"
DIAGNOSTICS_SHEET = "Logistic diagnostics"
CLASSIFICATION_SHEET = "Logistic classification"
METRICS_SHEET = "Logistic fit metrics"
PREDICTIONS_SHEET = "Logistic predictions"
MAX_PROFILES = 12
DEFAULT_CUTOFF = 0.5
DEFAULT_LEVEL = 95.0
TABS = {"Diagnostics and profiles": (
    LOGISTIC_DIAGNOSTICS, LOGISTIC_CUTOFF, LOGISTIC_PROFILES, LOGISTIC_CI)}
_KEYS = (LOGISTIC_DIAGNOSTICS, LOGISTIC_CUTOFF, LOGISTIC_PROFILES, LOGISTIC_CI)
_IN_SAMPLE = ("In-sample: the metrics describe this fit, not new observations.")
_INTERVAL = ("Uncertainty of the conditional mean probability at this profile, "
             "from a normal interval on the linear predictor.")
# A singular Bernoulli variance below this is treated as a boundary probability.
_BOUNDARY = np.finfo(float).tiny


def present(options):
    """True when the recipe carries any logistic-only key. Other families ignore those keys."""
    return any(key in options for key in _KEYS)


def _flag(options):
    if LOGISTIC_DIAGNOSTICS not in options:
        return False
    value = options[LOGISTIC_DIAGNOSTICS]
    if not isinstance(value, bool):
        raise FieldError(LOGISTIC_DIAGNOSTICS, f"{LOGISTIC_DIAGNOSTICS} must be yes or no.")
    return value


def _profiles(options):
    if LOGISTIC_PROFILES not in options or options[LOGISTIC_PROFILES] in (None, (), []):
        return []
    profiles = options[LOGISTIC_PROFILES]
    if not isinstance(profiles, (list, tuple)):
        raise FieldError(LOGISTIC_PROFILES, "Profiles must be a list.")
    return list(profiles)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if np.isfinite(number) else None


def cutoff(options, diagnostics):
    """Finite cutoff in [0, 1]. A missing key keeps 0.5. Ignored unless diagnostics are on."""
    if not diagnostics:
        return DEFAULT_CUTOFF
    if LOGISTIC_CUTOFF not in options or options[LOGISTIC_CUTOFF] in (None, ""):
        return DEFAULT_CUTOFF
    value = _number(options[LOGISTIC_CUTOFF])
    if value is None or not 0 <= value <= 1:
        raise FieldError(LOGISTIC_CUTOFF, "Logistic cutoff must be finite and from 0 to 1.")
    return value


def confidence_level(options, profiles):
    """A level strictly inside (0, 100). A missing key keeps 95%. Ignored without profiles."""
    if not profiles:
        return DEFAULT_LEVEL
    if LOGISTIC_CI not in options or options[LOGISTIC_CI] in (None, ""):
        return DEFAULT_LEVEL
    level = _number(options[LOGISTIC_CI])
    if level is None or not 0 < level < 100:
        raise FieldError(LOGISTIC_CI, "Choose a confidence level strictly between 0 and 100.")
    return level


def validate(options):
    """Check logistic-only keys without fitting. Other keys are left to the regression."""
    diagnostics = _flag(options)
    cutoff(options, diagnostics)
    profiles = _profiles(options)
    if len(profiles) > MAX_PROFILES:
        raise FieldError(LOGISTIC_PROFILES, f"Use at most {MAX_PROFILES} profiles.")
    confidence_level(options, profiles)
    return diagnostics, profiles


def requested(options):
    """Diagnostics or at least one profile add sheets to the logistic result."""
    return _flag(options) or bool(_profiles(options))


def pearson_residual(observed, probability):
    """(y − p) / sqrt(p(1 − p)), rewritten so a matching boundary probability is 0."""
    y = np.asarray(observed, dtype=float)
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    out = np.empty(y.shape, dtype=float)
    positive = y >= 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        out[positive] = np.sqrt((1.0 - p[positive]) / p[positive])
        out[~positive] = -np.sqrt(p[~positive] / (1.0 - p[~positive]))
    out[positive & (p <= 0.0)] = np.inf
    out[~positive & (p >= 1.0)] = -np.inf
    out[positive & (p >= 1.0)] = 0.0
    out[~positive & (p <= 0.0)] = 0.0
    return out


def deviance_residual(observed, probability):
    """Sign of y − p times sqrt(−2(y ln p + (1 − y) ln(1 − p))), stable at 0 and 1."""
    y = np.asarray(observed, dtype=float)
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    out = np.empty(y.shape, dtype=float)
    positive = y >= 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        matched = np.sqrt(-2.0 * np.log(np.clip(p[positive], _BOUNDARY, 1.0)))
        missed = np.sqrt(-2.0 * np.log(np.clip(1.0 - p[~positive], _BOUNDARY, 1.0)))
    out[positive] = matched
    out[~positive] = -missed
    out[positive & (p <= 0.0)] = np.inf
    out[~positive & (p >= 1.0)] = 0.0
    out[~positive & (p >= 1.0)] = -np.inf
    out[~positive & (p <= 0.0)] = 0.0
    return out


def _log_likelihood(observed, probability):
    """Bernoulli log-likelihood per row. A boundary that matches the outcome contributes 0."""
    y = np.asarray(observed, dtype=float)
    p = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    term = np.empty(y.shape, dtype=float)
    positive = y >= 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        term[positive] = np.log(p[positive])
        term[~positive] = np.log(1.0 - p[~positive])
    term[positive & (p <= 0.0)] = -np.inf
    term[~positive & (p >= 1.0)] = -np.inf
    term[positive & (p >= 1.0)] = 0.0
    term[~positive & (p <= 0.0)] = 0.0
    return term


def auc(observed, probability):
    """Mann–Whitney AUC. Ties between the two outcomes take half credit, as in the ROC curve."""
    y = np.asarray(observed, dtype=float)
    score = np.asarray(probability, dtype=float) + 0.0
    negative = np.sort(score[y < 0.5])
    positive = np.sort(score[y >= 0.5])
    if len(negative) == 0 or len(positive) == 0:
        raise FieldError(LOGISTIC_DIAGNOSTICS, "AUC needs both outcomes 0 and 1.")
    return float(_auc(negative, positive, DEFAULT_LEVEL)[0])


def _diagnostics(fitted, threshold):
    observed = fitted["Observed"].to_numpy(dtype=float)
    probability = fitted["Fitted"].to_numpy(dtype=float)
    classified = probability > threshold
    rows = pd.DataFrame({
        "Source row": fitted.index.to_numpy(),
        "Observed": observed,
        "Probability": probability,
        "Pearson residual": pearson_residual(observed, probability),
        "Deviance residual": deviance_residual(observed, probability),
        "Classified positive": classified,
    })
    counts = np.zeros((2, 2), dtype=int)
    for actual in (0, 1):
        group = observed == actual
        counts[actual, 0] = int((group & ~classified).sum())
        counts[actual, 1] = int((group & classified).sum())
    classification = pd.DataFrame(counts, index=["Actual 0", "Actual 1"],
                                  columns=["Predicted 0", "Predicted 1"])
    log_loss = float(-np.mean(_log_likelihood(observed, probability)))
    positive = observed >= 0.5
    tjur = float(probability[positive].mean() - probability[~positive].mean())
    metrics = pd.DataFrame({
        "Value": [float(np.mean((observed - probability) ** 2)), log_loss, auc(observed, probability), tjur,
                  float(threshold)],
        "Note": [_IN_SAMPLE] * 5,
    }, index=["Brier score", "Log loss", "AUC", "Tjur R²", "Cutoff"])
    return rows, classification, metrics


def _prediction_table(model, design, references, data, predictors, categories, profiles, level):
    if not 1 <= len(profiles) <= MAX_PROFILES:
        raise FieldError(LOGISTIC_PROFILES, f"Use from 1 to {MAX_PROFILES} profiles.")
    present_levels = {name: set(data[name].astype(str)) for name in categories}
    names, rows = [], []
    for number, profile in enumerate(profiles, 1):
        if not isinstance(profile, dict) or not isinstance(profile.get("values"), dict):
            raise FieldError(LOGISTIC_PROFILES, f"Profile {number} is not a valid profile.")
        label = str(profile.get("name", "")).strip()
        if not label:
            raise FieldError(LOGISTIC_PROFILES, f"Profile {number} needs a name.")
        if label in names:
            raise FieldError(LOGISTIC_PROFILES, f'Profile names must be distinct: "{label}" appears twice.')
        values = profile["values"]
        unknown = [name for name in values if name not in predictors]
        if unknown:
            raise FieldError(LOGISTIC_PROFILES, f'Profile "{label}" sets {unknown[0]!r}, which is not a predictor.')
        row = {"Intercept": 1.0}
        for name in predictors:
            if name not in values:
                raise FieldError(LOGISTIC_PROFILES, f'Profile "{label}" needs a value for {name}.')
            if name in categories:
                level_name = str(values[name])
                if level_name not in present_levels[name]:
                    raise FieldError(LOGISTIC_PROFILES,
                                     f'Profile "{label}": {values[name]!r} is not a category of {name}.')
                if level_name != references[name]:
                    row[f"{name} [{level_name}]"] = 1.0
            else:
                number_value = _number(values[name])
                if number_value is None:
                    raise FieldError(LOGISTIC_PROFILES, f'Profile "{label}": {name} needs a finite number.')
                row[name] = number_value
        names.append(label)
        rows.append([row.get(column, 0.0) for column in design.columns])
    coded = np.asarray(rows, dtype=float)
    beta = np.asarray(model.params, dtype=float)
    # Inverse binomial information at the fitted probabilities. cov_params() on this
    # statsmodels build is a few ulps away from X' diag(p(1-p)) X and misses the fixture.
    probability = np.clip(np.asarray(model.fittedvalues, dtype=float), 0.0, 1.0)
    weights = probability * (1.0 - probability)
    information = np.asarray(design, dtype=float).T @ (weights[:, None] * np.asarray(design, dtype=float))
    try:
        covariance = np.linalg.inv(information)
    except np.linalg.LinAlgError as error:
        raise FieldError(LOGISTIC_PROFILES, "A profile probability is not representable for this fit.") from error
    eta = coded @ beta
    spread = np.einsum("ij,jk,ik->i", coded, covariance, coded)
    critical = float(stats.norm.ppf(0.5 + level / 200.0))
    if not (np.isfinite(eta).all() and np.isfinite(spread).all() and np.isfinite(critical)):
        raise FieldError(LOGISTIC_PROFILES, "A profile probability is not representable for this fit.")
    se = np.sqrt(np.clip(spread, 0.0, None))
    return pd.DataFrame({
        "Profile": names,
        "Linear predictor": eta,
        "SE linear predictor": se,
        "Probability": expit(eta),
        "CI low": expit(eta - critical * se),
        "CI high": expit(eta + critical * se),
        "Interval": _INTERVAL,
    })


def logistic_result(options, fit):
    """Sheets for one logistic fit. ``fit`` is ``models.logistic_fit`` so the base tables are not rebuilt."""
    diagnostics, profiles = validate(options)
    tables, model, design, references, data = fit
    tables = dict(tables)
    if diagnostics:
        rows, classification, metrics = _diagnostics(tables["Fitted values"], cutoff(options, True))
        tables[DIAGNOSTICS_SHEET] = rows
        tables[CLASSIFICATION_SHEET] = classification
        tables[METRICS_SHEET] = metrics
    if profiles:
        tables[PREDICTIONS_SHEET] = _prediction_table(
            model, design, references, data, options["Predictors"], options["Categorical predictors"], profiles,
            confidence_level(options, profiles))
    return Result(tables)
