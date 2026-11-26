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
REPLICATE_LACK_OF_FIT = "Replicate lack-of-fit test"
PLOT_NONE = "None"
PLOT_RESIDUALS = "Residuals vs fitted"
PLOT_ABSOLUTE = "Absolute residuals vs fitted"
PLOT_OBSERVED = "Observed vs fitted"
PLOTS = (PLOT_NONE, PLOT_RESIDUALS, PLOT_ABSOLUTE, PLOT_OBSERVED)
DIAGNOSTICS_SHEET = "Linear diagnostics"
MODEL_SHEET = "Linear model diagnostics"
PREDICTIONS_SHEET = "Linear predictions"
LACK_OF_FIT_SHEET = "Lack of fit on replicates"
COMPONENT_RESIDUAL = "Residual"
COMPONENT_PURE = "Pure error"
COMPONENT_LACK = "Lack of fit"
LACK_OF_FIT_COMPONENTS = (COMPONENT_RESIDUAL, COMPONENT_PURE, COMPONENT_LACK)
NOTE_WEIGHTS = ("The replicate lack-of-fit test needs an unweighted ordinary least squares fit. "
                "With weights it is not calculated.")
NOTE_NONFINITE = "The replicate lack-of-fit test needs finite predictors, observations and residuals."
NOTE_RESIDUALS = "The stored residuals do not agree with the fit, so lack of fit was not calculated."
NOTE_PREDICTIONS = ("Predictions for the same predictor combination do not agree, so lack of fit was not calculated.")
NOTE_NEGATIVE = ("The lack-of-fit sum of squares is negative beyond the numeric tolerance, "
                 "so F and p were not calculated.")
NOTE_NO_REPLICATES = "The replicate lack-of-fit test needs repeated predictor combinations."
NOTE_NO_DEGREES = ("The replicate lack-of-fit test needs more distinct predictor combinations than the rank of the fit.")
NOTE_ZERO_BOTH = "Pure error is zero and lack of fit is zero, so F and p are not available."
NOTE_ZERO_PURE = "Pure error is zero while lack of fit is positive, so F and p are not available."
NOTE_CLAMPED = ("A tiny negative lack-of-fit sum of squares was set to zero. "
                "Comparison of lack of fit with the variation among replicates that share every predictor.")
NOTE_AVAILABLE = "Comparison of lack of fit with the variation among replicates that share every predictor."
_NOTE_KEYS = {
    NOTE_WEIGHTS: "mlr.lof.note.weights",
    NOTE_NONFINITE: "mlr.lof.note.nonfinite",
    NOTE_RESIDUALS: "mlr.lof.note.residuals",
    NOTE_PREDICTIONS: "mlr.lof.note.predictions",
    NOTE_NEGATIVE: "mlr.lof.note.negative",
    NOTE_NO_REPLICATES: "mlr.lof.note.no_replicates",
    NOTE_NO_DEGREES: "mlr.lof.note.no_degrees",
    NOTE_ZERO_BOTH: "mlr.lof.note.zero_both",
    NOTE_ZERO_PURE: "mlr.lof.note.zero_pure",
    NOTE_CLAMPED: "mlr.lof.note.clamped",
    NOTE_AVAILABLE: "mlr.lof.note.available",
}
_COMPONENT_KEYS = {
    COMPONENT_RESIDUAL: "mlr.lof.component.residual",
    COMPONENT_PURE: "mlr.lof.component.pure",
    COMPONENT_LACK: "mlr.lof.component.lack",
}
HEADER_KEYS = {
    "Component": "mlr.lof.column.component",
    "SS": "mlr.lof.column.ss",
    "df": "mlr.lof.column.df",
    "MS": "mlr.lof.column.ms",
    "F": "mlr.lof.column.f",
    "p": "mlr.lof.column.p",
    "N": "mlr.lof.column.n",
    "Distinct combinations": "mlr.lof.column.combinations",
    "Rank": "mlr.lof.column.rank",
    "Replicate groups": "mlr.lof.column.groups",
    "Note": "mlr.lof.column.note",
}
LABEL_KEYS = {REPLICATE_LACK_OF_FIT: "mlr.lof.field"}
MAX_PROFILES = 12
TABS = {"Diagnostics and predictions": (LINEAR_DIAGNOSTICS, LINEAR_RESIDUAL_PLOT, LINEAR_PROFILES, LINEAR_CI,
                                        REPLICATE_LACK_OF_FIT)}
# 1 − h at or below this is treated as a perfect leverage point.
_LEVERAGE_TOLERANCE = 1e-12
# A residual within this relative roundoff tolerance is consistent with an exact fit.
_RESIDUAL_ROUNDOFF = 32 * np.finfo(float).eps
_KEYS = (LINEAR_DIAGNOSTICS, LINEAR_RESIDUAL_PLOT, LINEAR_PROFILES, LINEAR_CI, REPLICATE_LACK_OF_FIT)


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
    _flag(options, REPLICATE_LACK_OF_FIT)
    _plot_choice(options)
    confidence_level(options)
    profiles = _profiles(options)
    if len(profiles) > MAX_PROFILES:
        raise FieldError(LINEAR_PROFILES, f"Use at most {MAX_PROFILES} profiles.")
    return profiles


def requested(options):
    """Diagnostics, a residual plot, a profile, or the replicate lack-of-fit test add to the linear result."""
    if _flag(options, LINEAR_DIAGNOSTICS) or _flag(options, REPLICATE_LACK_OF_FIT):
        return True
    if _plot_choice(options) != PLOT_NONE:
        return True
    return bool(_profiles(options))


def _blank(value):
    try:
        return value is None or bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def show_component(value):
    """Component name in the active language. The stored label stays English."""
    from .i18n import tr
    if _blank(value):
        return ""
    key = _COMPONENT_KEYS.get(value)
    return tr(key) if key else str(value)


def show_note(value):
    """Lack-of-fit note in the active language. The stored sentence stays English."""
    from .i18n import tr
    if _blank(value) or value == "":
        return ""
    key = _NOTE_KEYS.get(value)
    return tr(key) if key else str(value)


def _sum_squares_tolerance(*terms):
    """Absolute tolerance for a sum of squares. Tiny negatives inside it are numeric noise."""
    finite = [abs(float(term)) for term in terms if np.isfinite(term)]
    scale = max(finite, default=0.0)
    return float(128 * np.finfo(float).eps * scale)


def _whole_rank(rank):
    if isinstance(rank, bool) or isinstance(rank, (float, np.floating)) and not float(rank).is_integer():
        return None
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return None
    if value < 0 or int(rank) != rank:
        return None
    return value


def _optional_int(value):
    if value is None:
        return pd.NA
    return int(value)


def _mean_square(ss, df):
    if ss is None or df is None or df <= 0 or not np.isfinite(ss):
        return np.nan
    return float(ss) / int(df)


def _lack_frame(*, n, distinct, rank, groups, residual_ss, pure_ss, lack_ss, df_resid, df_pure, df_lack,
                note, f_value, p_value):
    """One sheet: residual, pure error and lack of fit, with N, U and the replicate groups on the first row."""
    residual_missing = residual_ss is None or not np.isfinite(residual_ss)
    notes = [note, note, note] if residual_missing else ["", "", note or ""]
    frame = pd.DataFrame({
        "SS": [np.nan if residual_ss is None else residual_ss,
               np.nan if pure_ss is None else pure_ss,
               np.nan if lack_ss is None else lack_ss],
        "df": pd.array([_optional_int(df_resid), _optional_int(df_pure), _optional_int(df_lack)], dtype="Int64"),
        "MS": [_mean_square(residual_ss, df_resid), _mean_square(pure_ss, df_pure), _mean_square(lack_ss, df_lack)],
        "F": [np.nan, np.nan, np.nan if f_value is None else f_value],
        "p": [np.nan, np.nan, np.nan if p_value is None else p_value],
        "N": pd.array([_optional_int(n), pd.NA, pd.NA], dtype="Int64"),
        "Distinct combinations": pd.array([_optional_int(distinct), pd.NA, pd.NA], dtype="Int64"),
        "Rank": pd.array([_optional_int(rank), pd.NA, pd.NA], dtype="Int64"),
        "Replicate groups": pd.array([_optional_int(groups), pd.NA, pd.NA], dtype="Int64"),
        "Note": notes,
    }, index=pd.Index(LACK_OF_FIT_COMPONENTS, name="Component"))
    return frame


def _unavailable_frame(n, note):
    return _lack_frame(n=n, distinct=None, rank=None, groups=None, residual_ss=None, pure_ss=None, lack_ss=None,
                       df_resid=None, df_pure=None, df_lack=None, note=note, f_value=None, p_value=None)


def _group_codes(predictors, categories):
    """Codes for exact equality of the whole predictor combination. No pairwise comparison."""
    columns = {}
    for index, name in enumerate(predictors.columns):
        if name in categories:
            columns[index] = predictors[name].astype(str).to_numpy()
        else:
            columns[index] = pd.to_numeric(predictors[name], errors="coerce").to_numpy(dtype=float)
    keys = pd.DataFrame(columns)
    if not keys.shape[1]:
        return np.zeros(len(keys), dtype=np.int64), True
    numeric = [column for index, column in columns.items()
               if predictors.columns[index] not in categories]
    finite = not numeric or all(np.isfinite(column).all() for column in numeric)
    codes, _ = pd.factorize(pd.MultiIndex.from_frame(keys), sort=False)
    return np.asarray(codes, dtype=np.int64), finite


def _assess_sums(sse, pure, df_pure, df_lack):
    """Split the residual sum of squares. A tiny negative lack of fit is numeric noise; a larger one is not."""
    tau = _sum_squares_tolerance(sse, pure)
    lack = float(sse - pure)
    clamped = False
    if -tau <= lack < 0:
        lack = 0.0
        clamped = True
    if lack < -tau:
        return None, NOTE_NEGATIVE, None, None
    if df_pure <= 0:
        return lack, NOTE_NO_REPLICATES, None, None
    if df_lack <= 0:
        return lack, NOTE_NO_DEGREES, None, None
    if pure <= 0:
        reason = NOTE_ZERO_BOTH if lack <= 0 else NOTE_ZERO_PURE
        return lack, reason, None, None
    ratio = (lack / df_lack) / (pure / df_pure)
    if not np.isfinite(ratio):
        return lack, NOTE_NONFINITE, None, None
    probability = float(stats.f.sf(ratio, df_lack, df_pure))
    if not np.isfinite(probability):
        return lack, NOTE_NONFINITE, None, None
    return lack, NOTE_CLAMPED if clamped else NOTE_AVAILABLE, float(ratio), probability


def build_lack_of_fit_table(observed, predicted, residual, predictors, categories, rank):
    """Lack of fit against pure error for one unweighted fit.

    Rows that share every predictor, numeric or categorical, form one group. The pure-error
    sum of squares is the variation around the group means. Lack of fit is the residual sum
    of squares minus that pure error. Groups are formed by sorting, not by comparing every pair.
    """
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    residual = np.asarray(residual, dtype=float)
    count = int(observed.shape[0])
    rank_value = _whole_rank(rank)
    predictors = predictors.reset_index(drop=True)
    if (rank_value is None or len(predicted) != count or len(residual) != count or len(predictors) != count
            or count == 0 or not np.isfinite(np.concatenate([observed, predicted, residual])).all()):
        return _unavailable_frame(count, NOTE_NONFINITE)
    codes, finite = _group_codes(predictors, set(categories))
    if not finite or not np.isfinite(codes).all():
        return _unavailable_frame(count, NOTE_NONFINITE)
    order = np.argsort(codes, kind="mergesort")
    ordered_codes = codes[order]
    breaks = np.flatnonzero(ordered_codes[1:] != ordered_codes[:-1]) + 1 if count > 1 else np.array([], dtype=int)
    starts = np.r_[0, breaks]
    counts = np.diff(np.r_[starts, count])
    distinct = int(len(counts))
    replicate_groups = int(np.count_nonzero(counts > 1))
    ordered_y = observed[order]
    ordered_fit = predicted[order]
    # Center around an observed value first. A large common offset can round away
    # a group mean even when the small differences between replicates are exact.
    local = ordered_y - np.repeat(ordered_y[starts], counts)
    means = np.add.reduceat(local, starts) / counts
    centered = local - np.repeat(means, counts)
    pure = float(centered @ centered)
    fit_max = np.maximum.reduceat(ordered_fit, starts)
    fit_min = np.minimum.reduceat(ordered_fit, starts)
    tolerance = 128 * np.finfo(float).eps * np.maximum(np.abs(fit_max), np.abs(fit_min))
    df_pure = count - distinct
    df_lack = distinct - rank_value
    df_resid = count - rank_value
    if np.any((fit_max - fit_min) > tolerance):
        sse = float(residual @ residual)
        return _lack_frame(n=count, distinct=distinct, rank=rank_value, groups=replicate_groups,
                           residual_ss=sse, pure_ss=pure, lack_ss=None, df_resid=df_resid, df_pure=df_pure,
                           df_lack=df_lack, note=NOTE_PREDICTIONS, f_value=None, p_value=None)
    gap = np.max(np.abs(residual - (observed - predicted)))
    if gap > _sum_squares_tolerance(np.max(np.abs(observed)), np.max(np.abs(predicted)), np.max(np.abs(residual))):
        return _lack_frame(n=count, distinct=distinct, rank=rank_value, groups=replicate_groups,
                           residual_ss=None, pure_ss=None, lack_ss=None, df_resid=df_resid, df_pure=df_pure,
                           df_lack=df_lack, note=NOTE_RESIDUALS, f_value=None, p_value=None)
    sse = float(residual @ residual)
    if not np.isfinite(sse) or not np.isfinite(pure):
        return _unavailable_frame(count, NOTE_NONFINITE)
    lack, note, ratio, probability = _assess_sums(sse, pure, df_pure, df_lack)
    return _lack_frame(n=count, distinct=distinct, rank=rank_value, groups=replicate_groups, residual_ss=sse,
                       pure_ss=pure, lack_ss=lack, df_resid=df_resid, df_pure=df_pure, df_lack=df_lack, note=note,
                       f_value=ratio, p_value=probability)


def lack_of_fit_sheet(options, fitted, data, rank, weights=None):
    """The replicate lack-of-fit sheet for one multiple linear fit, or the reason it is not available."""
    count = int(len(fitted))
    if weights is not None:
        return _unavailable_frame(count, NOTE_WEIGHTS)
    # The fit builds both tables in the same complete-case order. Looking up
    # rows by label would multiply rows when the source has non-unique labels.
    if not data.index.equals(fitted.index):
        return _unavailable_frame(count, NOTE_RESIDUALS)
    predictors = data.loc[:, list(options["Predictors"])]
    return build_lack_of_fit_table(
        fitted["Observed"].to_numpy(dtype=float), fitted["Fitted"].to_numpy(dtype=float),
        fitted["Residual"].to_numpy(dtype=float), predictors, options["Categorical predictors"], rank)


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
    if _flag(options, REPLICATE_LACK_OF_FIT):
        rank = int(round(float(model.nobs - model.df_resid)))
        tables[LACK_OF_FIT_SHEET] = lack_of_fit_sheet(options, tables["Fitted values"], data, rank, weights)
    return Result(tables, figure)
