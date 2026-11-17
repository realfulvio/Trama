"""Observation diagnostics, residual plots and covariate profiles for multiple linear regression.

Cook's distance and internally studentized residuals require positive residual variance
and leverage below one. PRESS residuals require leverage below one. PRESS is the sum of
squared leave-one-out residuals only when every one of them is defined. Mean and
prediction intervals are pointwise, not simultaneous. Leverage is the diagonal of the
hat matrix from a reduced QR, so the n×n hat matrix is never formed.
"""
import numpy as np
import pandas as pd
from scipy import stats

from . import mlr_weighting
from .processing import FieldError
from .reporting import Result, _plot

LINEAR_DIAGNOSTICS = "Linear diagnostics"
LINEAR_RESIDUAL_PLOT = "Linear residual plot"
LINEAR_PROFILES = "Linear profiles"
LINEAR_CI = "Linear CI (%)"
PLOT_NONE = "None"
PLOT_RESIDUALS = "Residuals vs fitted"
PLOT_ABSOLUTE = "Absolute residuals vs fitted"
PLOT_OBSERVED = "Observed vs fitted"
PLOTS = (PLOT_NONE, PLOT_RESIDUALS, PLOT_ABSOLUTE, PLOT_OBSERVED)
DIAGNOSTICS_SHEET = "Linear diagnostics"
MODEL_SHEET = "Linear model diagnostics"
PREDICTIONS_SHEET = "Linear predictions"
MAX_PROFILES = 12
TABS = {"Diagnostics and predictions": (LINEAR_DIAGNOSTICS, LINEAR_RESIDUAL_PLOT, LINEAR_PROFILES, LINEAR_CI)}
# 1 − h at or below this is treated as a perfect leverage point.
_LEVERAGE_TOLERANCE = 1e-12
# A residual within this relative roundoff tolerance is consistent with an exact fit.
_RESIDUAL_ROUNDOFF = 32 * np.finfo(float).eps
_KEYS = (LINEAR_DIAGNOSTICS, LINEAR_RESIDUAL_PLOT, LINEAR_PROFILES, LINEAR_CI)


def present(options):
    """True when the recipe carries any linear-only key. Other families ignore those keys."""
    return any(key in options for key in _KEYS)


def _flag(options, name):
    if name not in options:
        return False
    value = options[name]
    if not isinstance(value, bool):
        raise FieldError(name, f"{name} must be yes or no.")
    return value


def _plot_choice(options):
    if LINEAR_RESIDUAL_PLOT not in options or options[LINEAR_RESIDUAL_PLOT] in (None, ""):
        return PLOT_NONE
    choice = options[LINEAR_RESIDUAL_PLOT]
    if choice not in PLOTS:
        raise FieldError(LINEAR_RESIDUAL_PLOT, "Choose a residual plot.")
    return choice


def confidence_level(options):
    """Return a level strictly inside (0, 100). A missing key keeps 95%."""
    if LINEAR_CI not in options or options[LINEAR_CI] in (None, ""):
        return 95.0
    raw = options[LINEAR_CI]
    if isinstance(raw, bool):
        level = np.nan
    else:
        try:
            level = float(raw)
        except (TypeError, ValueError, OverflowError):
            level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise FieldError(LINEAR_CI, "Choose a confidence level strictly between 0 and 100.")
    return level


def _profiles(options):
    if LINEAR_PROFILES not in options or options[LINEAR_PROFILES] in (None, (), []):
        return []
    profiles = options[LINEAR_PROFILES]
    if not isinstance(profiles, (list, tuple)):
        raise FieldError(LINEAR_PROFILES, "Profiles must be a list.")
    return list(profiles)


def validate(options):
    """Check the linear-only keys without fitting. Other keys are left to the regression."""
    _flag(options, LINEAR_DIAGNOSTICS)
    _plot_choice(options)
    confidence_level(options)
    profiles = _profiles(options)
    if len(profiles) > MAX_PROFILES:
        raise FieldError(LINEAR_PROFILES, f"Use at most {MAX_PROFILES} profiles.")
    return profiles


def requested(options):
    """Diagnostics, a residual plot, or at least one profile add to the linear result."""
    if _flag(options, LINEAR_DIAGNOSTICS):
        return True
    if _plot_choice(options) != PLOT_NONE:
        return True
    return bool(_profiles(options))


def _leverage(design, root=None):
    """Hat-matrix diagonal from a reduced QR. ``root`` = sqrt(normalised weight) gives wNorm·d'(D'WD)⁻¹d."""
    matrix = np.asarray(design, dtype=float)
    if root is not None:
        matrix = root[:, None] * matrix
    q, _ = np.linalg.qr(matrix, mode="reduced")
    return np.sum(q * q, axis=1)


def _variance(observed, residual, df):
    sse = float(np.dot(residual, residual))
    if not np.isfinite(sse):
        raise FieldError(LINEAR_DIAGNOSTICS, "The residual variance is outside the supported numeric range.")
    spread = float(np.ptp(observed))
    if spread == 0 or np.max(np.abs(residual)) <= _RESIDUAL_ROUNDOFF * spread:
        return 0.0
    return sse / df


def _diagnostics(fitted, leverage, df, terms, weights=None):
    residual = fitted["Residual"].to_numpy(dtype=float)
    observed = fitted["Observed"].to_numpy(dtype=float)
    # Weighted fit: variance, studentised residual and Cook use sqrt(wNorm)·r; PRESS residuals stay raw.
    scaled = residual if weights is None else weights.root * residual
    variance_observed = observed
    if weights is not None:
        # Compare roundoff in the same weighted space as the residuals. A large raw response with
        # little precision must not make a measurable weighted residual look like an exact fit.
        # Center before weighting: the weighted intercept is sqrt(w), rather than a constant column.
        mean = float(np.dot(weights.normalized / weights.normalized.sum(), observed))
        variance_observed = weights.root * (observed - mean)
    s2 = _variance(variance_observed, scaled, df)
    gap = 1.0 - leverage
    perfect = gap <= _LEVERAGE_TOLERANCE
    press = np.full(len(residual), np.nan)
    defined = ~perfect
    if defined.any():
        press[defined] = residual[defined] / gap[defined]
    student = np.full(len(residual), np.nan)
    cook = np.full(len(residual), np.nan)
    usable = defined & (s2 > 0)
    if usable.any():
        scale = np.sqrt(s2)
        student[usable] = scaled[usable] / (scale * np.sqrt(gap[usable]))
        cook[usable] = scaled[usable]**2 * leverage[usable] / (terms * s2 * gap[usable]**2)
    rows = pd.DataFrame({
        "Source row": fitted.index.to_numpy(),
        "Leverage": leverage,
        "Internally studentized residual": student,
        "Cook's distance": cook,
        "PRESS residual": press,
    })
    press_sum = np.nan if not np.isfinite(press).all() else float(np.dot(press, press))
    values, labels = [float(df), float(s2), press_sum], ["Residual df", "Residual variance", "PRESS"]
    if weights is not None:
        values.append(np.nan if not np.isfinite(press).all() else float(np.dot(weights.normalized, press * press)))
        labels.append("Weighted PRESS")
    summary = pd.DataFrame({"Value": values}, index=labels)
    notes = []
    if weights is not None:
        notes.append("Weighted fit: the residual variance is sigma² for normalized weight 1; studentized residuals "
                     "and Cook's distance use sqrt(normalized weight)·residual; PRESS residuals stay in raw units "
                     "and Weighted PRESS = sum(normalized weight · PRESS residual²).")
    if np.isnan(student).any() or np.isnan(cook).any():
        notes.append("Internally studentized residuals and Cook's distance are blank where the "
                     "residual variance is zero or leverage is one.")
    if np.isnan(press).any():
        notes.append("PRESS residuals and PRESS are blank where leverage is one.")
    if notes:
        summary["Note"] = " ".join(notes)
    return rows, summary


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if np.isfinite(number) else None


def _profile_weight(label, profile, key="weight"):
    """Raw precision of a future observation, in the units of the training weights."""
    value = _number(profile.get(key)) if key in profile else None
    if value is None or value <= 0:
        raise FieldError(LINEAR_PROFILES, f'Profile "{label}" needs a finite weight greater than 0 in the '
                                          "units of the training weights.")
    return value


def _profile_inputs(columns, references, data, predictors, categories, profiles, *, weighted=False, future=False):
    if len(profiles) > MAX_PROFILES:
        raise FieldError(LINEAR_PROFILES, f"Use at most {MAX_PROFILES} profiles.")
    present_levels = {name: set(data[name].astype(str)) for name in categories}
    names, rows, precisions = [], [], []
    for number, profile in enumerate(profiles, 1):
        if not isinstance(profile, dict) or not isinstance(profile.get("values"), dict):
            raise FieldError(LINEAR_PROFILES, f"Profile {number} is not a valid profile.")
        label = str(profile.get("name", "")).strip()
        if not label:
            raise FieldError(LINEAR_PROFILES, f"Profile {number} needs a name.")
        if label in names:
            raise FieldError(LINEAR_PROFILES, f'Profile names must be distinct: "{label}" appears twice.')
        values = profile["values"]
        unknown = [name for name in values if name not in predictors]
        if unknown:
            raise FieldError(LINEAR_PROFILES, f'Profile "{label}" sets {unknown[0]!r}, which is not a predictor.')
        row = {"Intercept": 1.0}
        for name in predictors:
            if name not in values:
                raise FieldError(LINEAR_PROFILES, f'Profile "{label}" needs a value for {name}.')
            if name in categories:
                level_name = str(values[name])
                if level_name not in present_levels[name]:
                    raise FieldError(LINEAR_PROFILES, f'Profile "{label}": {values[name]!r} is not a category of {name}.')
                if level_name != references[name]:
                    row[f"{name} [{level_name}]"] = 1.0
            else:
                number_value = _number(values[name])
                if number_value is None:
                    raise FieldError(LINEAR_PROFILES, f'Profile "{label}": {name} needs a finite number.')
                row[name] = number_value
        if weighted and future:
            precisions.append(_profile_weight(label, profile))
        names.append(label)
        rows.append([row.get(column, 0.0) for column in columns])
    return names, np.asarray(rows, dtype=float), precisions


def check_weighted_profiles(data, options):
    """Pure field checks before submission; no fit, QR or covariance on Tk."""
    profiles = validate(options)
    categories = options["Categorical predictors"]
    references = {name: min(data[name].astype(str)) for name in categories if len(data)}
    _profile_inputs([], references, data, options["Predictors"], categories, profiles,
                    weighted=True, future=mlr_weighting.future_precision(options))


def _prediction_table(model, design, references, data, predictors, categories, profiles, level,
                      weights=None, future=False):
    names, coded, precisions = _profile_inputs(design.columns, references, data, predictors, categories, profiles,
                                               weighted=weights is not None, future=future)
    mean = coded @ np.asarray(model.params, dtype=float)
    covariance = np.asarray(model.cov_params(), dtype=float)
    spread = np.einsum("ij,jk,ik->i", coded, covariance, coded)
    s2 = float(model.mse_resid)
    critical = float(stats.t.ppf(0.5 + level / 200.0, model.df_resid))
    if not (np.isfinite(mean).all() and np.isfinite(spread).all() and np.isfinite(critical) and np.isfinite(s2)):
        raise FieldError(LINEAR_PROFILES, "A profile prediction is not representable for this fit.")
    mean_half = critical * np.sqrt(np.clip(spread, 0, None))
    if weights is not None:
        # A new observation needs its own precision: Var = spread + sigma² · maxTrainingWeight / weight.
        if future and not np.isfinite(weights.log_max):
            raise FieldError(LINEAR_PROFILES, "The raw weight scale of the training data is outside the numeric "
                                              "range, so profile weights in raw units cannot be compared with it.")
        if future:
            with np.errstate(all="ignore"):
                future_sd = np.array([weights.future_sd(s2, value) for value in precisions])
                prediction_half = critical * np.hypot(np.sqrt(np.clip(spread, 0, None)), future_sd)
            if not np.isfinite(prediction_half).all():
                raise FieldError(LINEAR_PROFILES, "A profile weight puts the future observation variance outside "
                                                  "the numeric range.")
        else:
            prediction_half = np.full(len(mean), np.nan)
    else:
        prediction_half = critical * np.sqrt(np.clip(s2 + spread, 0, None))
    table = pd.DataFrame({
        "Profile": names,
        "Prediction": mean,
        "Mean CI low": mean - mean_half,
        "Mean CI high": mean + mean_half,
        "Prediction interval low": mean - prediction_half,
        "Prediction interval high": mean + prediction_half,
    })
    if weights is not None and not future:
        table["Note"] = ("Prediction interval blank: with weighted data the variance of a new observation needs its "
                         'precision; set "Weighted prediction intervals" and a weight for each profile.')
    return table


def _figure(fitted, choice, weights=None):
    observed = fitted["Observed"].to_numpy(dtype=float)
    predicted = fitted["Fitted"].to_numpy(dtype=float)
    residual = fitted["Residual"].to_numpy(dtype=float)
    raw = " (raw units)" if weights is not None else ""
    if choice == PLOT_ABSOLUTE:
        vertical, ylabel = np.abs(residual), "Absolute residual" + raw
    elif choice == PLOT_OBSERVED:
        vertical, ylabel = observed, "Observed"
    else:
        vertical, ylabel = residual, "Residual" + raw
    figure, axes = _plot(choice, "Fitted", ylabel)
    axes.scatter(predicted, vertical)
    if choice == PLOT_OBSERVED:
        low = float(min(predicted.min(), vertical.min()))
        high = float(max(predicted.max(), vertical.max()))
        axes.plot([low, high], [low, high], color="#667085", linewidth=1, zorder=1)
    else:
        axes.axhline(0, color="#667085", linewidth=1, zorder=1)
    return figure


def linear_result(options, fit, weights=None):
    """Sheets for one multiple linear fit. ``fit`` is ``models.linear_fit`` so the base tables are not rebuilt.

    ``weights`` (mlr_weighting.Weights) marks a weighted fit built by ``weighted_linear_fit`` from the same fit."""
    validate(options)
    tables, model, design, references, data = fit
    level = confidence_level(options)
    profiles = _profiles(options)
    if _flag(options, LINEAR_DIAGNOSTICS):
        rows, summary = _diagnostics(tables["Fitted values"], _leverage(design, None if weights is None else weights.root),
                                     int(model.df_resid), design.shape[1], weights)
        tables[DIAGNOSTICS_SHEET] = rows
        tables[MODEL_SHEET] = summary
    if profiles:
        future = weights is not None and mlr_weighting.future_precision(options)
        tables[PREDICTIONS_SHEET] = _prediction_table(
            model, design, references, data, options["Predictors"], options["Categorical predictors"], profiles, level,
            weights, future)
    choice = _plot_choice(options)
    figure = _figure(tables["Fitted values"], choice, weights) if choice != PLOT_NONE else None
    return Result(tables, figure)
