"""Jackknife t intervals for Deming regression.

The published slope and intercept are always the full-sample fit from
``exploration.deming`` (Y / X error variance). Leave-one-out coefficients are
not a second estimator of that fit. They update the centered moments in O(n),

Sxx_(-i) = Sxx - (n/(n-1)) * (x_i - mean x)^2,

and the same subtraction for Syy and Sxy. The leave-one-out mean is
mean - (value - mean)/(n-1). Each omitted fit then uses the same slope
algebra as ``exploration.deming``. Direct ``deming`` calls are the test
oracle on small samples, not this production path. The standard error is

sqrt((n-1)/n * sum (theta_i - mean of the leave-one-out values)^2).

The interval is a two-sided Student t interval on n-1 degrees of freedom,
centered on the full-sample coefficient. It is not a prediction interval.

Intervals need at least four complete pairs so every omitted fit still has
three. The full-sample fit is kept and the interval is marked unavailable
when a leave-one-out fit is degenerate, or when the number of complete pairs
exceeds ``JACKKNIFE_LIMIT`` (100_000).

An identity line uses one shared domain: the union of observed X and observed
Y. Both axes are limited to that interval, and both the identity segment and
the fitted line are drawn across it, so Y = X spans the cloud instead of only
the observed X range. A steep fit may leave that square; the axis limits stay
on the union of the observations.

Known SDs, several Y series and projections (0.93)
--------------------------------------------------
Every new key is optional. A recipe without them, or with ``Variance ratio``, an empty ``Y series`` and
``Show projections`` off, takes the historical path: ``jackknife_deming`` on the single Y, the same three sheets
and the same figure. ``Known SDs`` turns the two measurement-error SDs into the ratio

lambda = (SD_Y / SD_X)^2,

computed as one division and one square so a common scale of the two SDs cancels before it can underflow or
overflow. The fit depends on the SDs only through lambda. A lambda outside [tiny, 1/tiny] is refused on
``Y error SD`` instead of being rounded to zero or infinity. The SDs describe measurement error, not the
sampling spread of the data.

``Y series`` fits each listed column against the shared X, independently, with its own complete pairs and the same
uncertainty settings. Each fit runs once through ``jackknife_deming``; the tables, the intervals and the figure
reuse it. A series with fewer than three complete pairs or a degenerate fit stops with a ``FieldError`` on
``Y series`` that names the series.

A projection is the point of the fitted line a = intercept, b = slope that minimises
lambda * (x - x*)^2 + (y - y*)^2 for an observed (x, y). With r = y - a - b*x,

x* = x + b*r / (lambda + b^2),    y* = y - lambda*r / (lambda + b^2) (which is a + b*x*).

For |b| > 1 the two weights are formed as (1/b) / (1 + q) and q / (1 + q) with q = (lambda/b)/b, so b^2 never
overflows; for |b| <= 1 the denominator lambda + b^2 cannot overflow. A point on the line (r = 0) is projected onto
itself, a zero-length segment. For lambda = 1 the segments are the Euclidean perpendiculars. Results that are not
finite stop the analysis instead of being drawn.

Paired comparison of two series
-------------------------------
``Compare paired series`` is off unless a recipe asks for it. It needs exactly two Y series and compares
the second with the first on the rows where X and both series are all valid: each row is the same unit
measured twice. The separate series reports keep their own complete pairs. The extra sheet
``Paired comparison`` reports both sample sizes, so a series fitted on 10 pairs and a comparison fitted
on 8 are visible together.

For each coefficient, the estimate is the full-sample Deming fit on those paired rows and the difference
is second minus first. The standard error uses the n leave-one-out differences from
``leave_one_out_coefficients``, deleting the same row from both fits:

sqrt((n-1)/n * sum (delta_i - mean of the deltas)^2).

The interval and the two-sided p use a Student t on n-1 degrees of freedom at the analysis confidence
level. Both p values are individual. The sheet calls the procedure an approximate jackknife (t). At
least 6 paired rows are required. A paired fit that is not defined, a degenerate leave-one-out fit, a
zero standard error or more than ``JACKKNIFE_LIMIT`` paired rows keeps every coefficient that can be
computed and leaves the missing inference blank, with the reason on the sheet. The intercept is the
value at X = 0; the sheet says when 0 lies outside the paired X range.
"""
from dataclasses import dataclass
import numbers

import numpy as np
import pandas as pd
from scipy import stats

from . import exploration
from .field_error import FieldError
from .reporting import _report
from .stats import complete

JACKKNIFE_LIMIT = 100_000
RESIDUAL_COLUMN = "Vertical residual (Y \u2212 fitted)"
PAIR_COLUMNS = ("Source row", "X", "Y", "Fitted Y", RESIDUAL_COLUMN)
_INTERVALS = ("None", "Jackknife (t)")
_UNAVAILABLE = "Interval unavailable"


def identity_limits(x_values, y_values):
    """Return the shared [low, high] domain for an identity overlay.

    The domain is the union of observed X and observed Y. Draw Y = X and the
    fitted line across it, and show that same interval on both axes.
    """
    observed = np.concatenate((np.asarray(x_values, dtype=float).ravel(),
                               np.asarray(y_values, dtype=float).ravel()))
    return float(np.min(observed)), float(np.max(observed))


def leave_one_out_coefficients(x_values, y_values, error_ratio):
    """Leave-one-out slopes and intercepts, or None if any omitted fit is degenerate."""
    xx = np.asarray(x_values, dtype=float)
    yy = np.asarray(y_values, dtype=float)
    if xx.ndim != 1 or xx.shape != yy.shape or xx.size < 2:
        raise ValueError("Leave-one-out Deming expects paired X and Y values.")
    n = xx.size
    mean_x, mean_y = xx.mean(), yy.mean()
    dx, dy = xx - mean_x, yy - mean_y
    sxx, syy, sxy = dx @ dx, dy @ dy, dx @ dy
    scale = n / (n - 1)
    sxx_i = sxx - scale * dx * dx
    syy_i = syy - scale * dy * dy
    sxy_i = sxy - scale * dx * dy
    varying = (sxx_i > 0) & (syy_i > 0)
    tolerance = np.finfo(float).eps * np.sqrt(np.where(varying, sxx_i * syy_i, 0))
    if np.any(~varying | (np.abs(sxy_i) <= tolerance)):
        return None
    diff = syy_i - error_ratio * sxx_i
    root = np.hypot(diff, 2 * np.sqrt(error_ratio) * sxy_i)
    slopes = np.empty(n)
    # Same slope branches as exploration.deming, including the diff >= 0 split.
    positive = diff >= 0
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes[positive] = (diff[positive] + root[positive]) / (2 * sxy_i[positive])
        slopes[~positive] = 2 * error_ratio * sxy_i[~positive] / (root[~positive] - diff[~positive])
    means_x = mean_x - dx / (n - 1)
    means_y = mean_y - dy / (n - 1)
    intercepts = means_y - slopes * means_x
    if not (np.isfinite(slopes).all() and np.isfinite(intercepts).all()):
        return None
    return slopes, intercepts


def _jackknife_se(values):
    centered = np.asarray(values, dtype=float)
    centered = centered - centered.mean()
    n = centered.size
    return np.sqrt((n - 1) / n * centered @ centered)


def _unavailable(report, status):
    return {**report, "Interval": "Jackknife (t)", "Interval status": f"{_UNAVAILABLE}: {status}"}


def _level(level):
    try:
        level = float(level)
    except (TypeError, ValueError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise ValueError("Confidence level (%) must be finite and strictly between 0 and 100.")
    return level


def jackknife_deming(frame, x, y, error_ratio=1.0, *, intervals="None", level=95.0):
    """Full-sample Deming fit, optional jackknife t intervals, and pair residuals.

    ``intervals`` is ``"None"`` or ``"Jackknife (t)"``. With intervals off, the
    report is exactly the dictionary ``exploration.deming`` returns. ``pairs``
    always lists complete pairs in source order.
    """
    if intervals not in _INTERVALS:
        raise ValueError('Parameter intervals must be "None" or "Jackknife (t)".')
    report, points = exploration.deming(frame, x, y, error_ratio)
    xx = np.array(points[x].to_numpy(dtype=float), copy=True)
    yy = np.array(points[y].to_numpy(dtype=float), copy=True)
    fitted = report["Intercept"] + report["Slope"] * xx
    pairs = pd.DataFrame({
        "Source row": np.array(points.index, copy=True),
        "X": xx,
        "Y": yy,
        "Fitted Y": fitted,
        RESIDUAL_COLUMN: yy - fitted,
    })
    if intervals == "None":
        return report, points, pairs
    level = _level(level)
    n = len(points)
    if n > JACKKNIFE_LIMIT:
        return _unavailable(report, "the jackknife work limit was exceeded."), points, pairs
    if n < 4:
        return _unavailable(report, "at least 4 complete pairs are required."), points, pairs
    replicates = leave_one_out_coefficients(xx, yy, error_ratio)
    if replicates is None:
        return _unavailable(report, "a leave-one-out fit is degenerate."), points, pairs
    slopes, intercepts = replicates
    critical = stats.t.isf((100 - level) / 200, n - 1)
    enriched = {**report, "Interval": "Jackknife (t)", "Confidence level (%)": level, "df": n - 1}
    for name, estimate, replicates_ in (("Slope", report["Slope"], slopes),
                                        ("Intercept", report["Intercept"], intercepts)):
        standard_error = _jackknife_se(replicates_)
        half = critical * standard_error
        enriched[f"{name} SE"] = standard_error
        enriched[f"{name} CI low"] = estimate - half
        enriched[f"{name} CI high"] = estimate + half
    return enriched, points, pairs


# ---------------------------------------------------------------------------
# 0.93: known SDs, several Y series and projections.
# ---------------------------------------------------------------------------
UNCERTAINTY = "Uncertainty input"
VARIANCE_RATIO = "Variance ratio"
KNOWN_SDS = "Known SDs"
UNCERTAINTY_CHOICES = (VARIANCE_RATIO, KNOWN_SDS)
RATIO = "Y / X error variance"
X_SD = "X error SD"
Y_SD = "Y error SD"
Y_SERIES = "Y series"
PROJECTIONS = "Show projections"
INTERVAL_METHOD = "Parameter intervals"
LEVEL = "Confidence level (%)"
SERIES_LIMIT = 12
PAIRED = "Compare paired series"
PAIRED_SHEET = "Paired comparison"
PAIRED_MINIMUM = 6
PAIRED_INTERVAL = "Approximate jackknife (t)"
PAIRED_P_NOTE = "Individual two-sided p values; they are not adjusted across the two coefficients."
EXTENDED_KEYS = (UNCERTAINTY, X_SD, Y_SD, Y_SERIES, PROJECTIONS)
SERIES_COLUMN = "Series"
PROJECTED_COLUMNS = ("Projected X", "Projected Y")
# lambda must be a normal float in both directions, so swapping X and Y stays representable too.
RATIO_LOW = float(np.finfo(float).tiny)
RATIO_HIGH = 1.0 / RATIO_LOW
_INTERVAL_COLUMNS = ("Interval", LEVEL, "df", "Slope SE", "Slope CI low", "Slope CI high",
                     "Intercept SE", "Intercept CI low", "Intercept CI high")


@dataclass(frozen=True)
class Settings:
    """The validated request. ``extended`` is False for every recipe the earlier versions could write."""
    x: str
    y: str | None
    series: tuple[str, ...] | None
    ratio: float | None
    x_sd: float | None
    y_sd: float | None
    intervals: str
    level: float
    projections: bool
    extended: bool
    paired: bool = False


@dataclass
class SeriesFit:
    """One fitted series, ready to draw: complete pairs, the line and the optional projected points."""
    name: str
    x: np.ndarray
    y: np.ndarray
    slope: float
    intercept: float
    projected_x: np.ndarray | None = None
    projected_y: np.ndarray | None = None


@dataclass
class Fit:
    settings: Settings
    tables: dict
    series: list[SeriesFit]


def _real(value):
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def _positive(options, key, *, required_text=None):
    """A finite number greater than zero, or a FieldError on ``key``."""
    if options.get(key) is None:
        raise FieldError(key, required_text or f"{key} is required.")
    value = options[key]
    if not _real(value) or not np.isfinite(value) or value <= 0:
        raise FieldError(key, f"{key} must be finite and greater than 0.")
    return float(value)


def known_ratio(x_sd, y_sd):
    """lambda = (SD_Y / SD_X)^2 from two positive finite SDs, or a FieldError on ``Y error SD``."""
    with np.errstate(all="ignore"):
        quotient = np.float64(y_sd) / np.float64(x_sd)
        ratio = float(quotient * quotient)
    if not np.isfinite(ratio) or not RATIO_LOW <= ratio <= RATIO_HIGH:
        raise FieldError(Y_SD, "The squared ratio of the error SDs cannot be represented. "
                               "Check Y error SD against X error SD.")
    return ratio


def _series_names(frame, options):
    raw = options.get(Y_SERIES)
    if raw is None:
        return None
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise FieldError(Y_SERIES, "Y series must be a list of column names.")
    names = tuple(raw)
    if not names:
        return None
    if not all(isinstance(name, str) for name in names):
        raise FieldError(Y_SERIES, "Y series must be a list of column names.")
    if len(names) > SERIES_LIMIT:
        raise FieldError(Y_SERIES, f"Y series accepts at most {SERIES_LIMIT} columns.")
    seen = set()
    for name in names:
        if name in seen:
            raise FieldError(Y_SERIES, f'Y series lists "{name}" more than once.')
        seen.add(name)
    x = options.get("X")
    if x in seen:
        raise FieldError(Y_SERIES, f'Y series cannot include the X column "{x}".')
    for name in names:
        if name not in frame.columns:
            raise FieldError(Y_SERIES, f'Y series column "{name}" is not in the worksheet.')
    return names


def _paired_flag(options):
    """False when the recipe does not ask. Anything other than on or off is a field error."""
    if PAIRED not in options:
        return False
    flag = options[PAIRED]
    if not isinstance(flag, (bool, np.bool_)):
        raise FieldError(PAIRED, "Compare paired series must be on or off.")
    return bool(flag)


def uses_extension(options):
    """True when a recipe uses known SDs, at least one Y series, or projections."""
    return bool(options.get(UNCERTAINTY) == KNOWN_SDS or options.get(Y_SERIES) or options.get(PROJECTIONS))


def read_settings(frame, options):
    """Validate the new keys. Recipes that do not use them keep every legacy value untouched."""
    mode = options.get(UNCERTAINTY, VARIANCE_RATIO)
    if mode not in UNCERTAINTY_CHOICES:
        raise FieldError(UNCERTAINTY, "Uncertainty input must be Variance ratio or Known SDs.")
    projections = options.get(PROJECTIONS, False)
    if not isinstance(projections, (bool, np.bool_)):
        raise FieldError(PROJECTIONS, "Show projections must be on or off.")
    series = _series_names(frame, options)
    paired = _paired_flag(options)
    if paired and (series is None or len(series) != 2):
        raise FieldError(PAIRED, "The paired comparison needs exactly two Y series. "
                                 "The second is compared with the first.")
    known = mode == KNOWN_SDS
    intervals = options.get(INTERVAL_METHOD, "None")
    level = options.get(LEVEL, 95.0)
    extended = known or series is not None or bool(projections)
    if not extended:
        # The historical request: the dialog and jackknife_deming own its checks and messages.
        return Settings(options["X"], options["Y"], None, options.get(RATIO), None, None, intervals, level,
                        False, False)
    x = options["X"]
    if x not in frame.columns:
        raise FieldError("X", f'X column "{x}" is not in the worksheet.')
    if intervals not in _INTERVALS:
        raise FieldError(INTERVAL_METHOD, 'Parameter intervals must be "None" or "Jackknife (t)".')
    if intervals == "Jackknife (t)" or paired:
        try:
            level = _level(level)
        except ValueError as error:
            raise FieldError(LEVEL, str(error)) from error
    if known:
        x_sd = _positive(options, X_SD, required_text="X error SD is required with Known SDs.")
        y_sd = _positive(options, Y_SD, required_text="Y error SD is required with Known SDs.")
        ratio = known_ratio(x_sd, y_sd)
    else:
        x_sd = y_sd = None
        ratio = _positive(options, RATIO, required_text="Y / X error variance is required.")
    y = None if series is not None else options["Y"]
    return Settings(x, y, series, ratio, x_sd, y_sd, intervals, level, bool(projections), True, paired)


def check_dialog(frame, options):
    """Refuse a bad Deming recipe before the worker. The historical wording stays."""
    if options.get(UNCERTAINTY, VARIANCE_RATIO) == VARIANCE_RATIO:
        ratio = options[RATIO]
        if not _real(ratio) or not np.isfinite(ratio) or ratio <= 0:
            raise FieldError(RATIO, f"{RATIO} must be finite and greater than 0.")
    if options.get(INTERVAL_METHOD) == "Jackknife (t)":
        level = options.get(LEVEL)
        if level is None or not _real(level) or not np.isfinite(level) or not 0 < float(level) < 100:
            raise FieldError(LEVEL, f"{LEVEL} must be finite and strictly between 0 and 100.")
    if uses_extension(options) or _paired_flag(options):
        read_settings(frame, options)


def prune_paired(options, saved):
    """Leave the paired key out of a recipe that never had it and still has it off."""
    saved = saved if isinstance(saved, dict) else {}
    if PAIRED not in saved and options.get(PAIRED) is False:
        options.pop(PAIRED, None)
    return options


def format_error(error):
    """The Deming message in the active language. Unlisted sentences stay in English."""
    from .i18n import translate_message, ui
    return translate_message(str(error), "deming.error.", convert={"field": ui})


def project_points(x_values, y_values, slope, intercept, ratio):
    """Project observed pairs onto y = intercept + slope * x in the metric lambda*(dx)^2 + (dy)^2.

    Returns the projected X and Y arrays. See the module docstring for the closed form and its overflow
    handling. Non-finite input, a lambda outside [RATIO_LOW, RATIO_HIGH] or a non-representable result raise
    ValueError; they are never turned into NaN segments.
    """
    xx = np.asarray(x_values, dtype=float)
    yy = np.asarray(y_values, dtype=float)
    if xx.ndim != 1 or xx.shape != yy.shape:
        raise ValueError("Projections expect paired X and Y values.")
    if not (np.isfinite(xx).all() and np.isfinite(yy).all() and np.isfinite(slope) and np.isfinite(intercept)):
        raise ValueError("Projections need finite data and a finite fitted line.")
    if not (np.isfinite(ratio) and RATIO_LOW <= ratio <= RATIO_HIGH):
        raise ValueError("Projections need an error variance ratio between "
                         f"{RATIO_LOW:.3g} and {RATIO_HIGH:.3g}.")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        residual = yy - (intercept + slope * xx)
        if abs(slope) <= 1.0:
            denominator = ratio + slope * slope
            along_x = slope / denominator
            share = ratio / denominator
        else:
            # b * b may overflow here; q = lambda / b^2 is formed with two divisions instead.
            q = (ratio / slope) / slope
            along_x = (1.0 / slope) / (1.0 + q)
            share = q / (1.0 + q)
        projected_x = xx + along_x * residual
        projected_y = yy - share * residual
    if not (np.isfinite(projected_x).all() and np.isfinite(projected_y).all()):
        raise ValueError("The projected points are outside the representable range.")
    return projected_x, projected_y


def _with_known_sds(report, settings):
    """Insert the two SDs after the ratio of a single-series report."""
    if settings.x_sd is None:
        return report
    out = {}
    for key, value in report.items():
        out[key] = value
        if key == "Y / X measurement error variance":
            out[X_SD], out[Y_SD] = settings.x_sd, settings.y_sd
    return out


def _single_fit(frame, settings):
    report, points, pairs = jackknife_deming(
        frame, settings.x, settings.y, settings.ratio, intervals=settings.intervals, level=settings.level)
    fit = SeriesFit(settings.y, np.array(pairs["X"].to_numpy(), copy=True), np.array(pairs["Y"].to_numpy(), copy=True),
                    report["Slope"], report["Intercept"])
    if settings.projections:
        try:
            fit.projected_x, fit.projected_y = project_points(fit.x, fit.y, fit.slope, fit.intercept, settings.ratio)
        except ValueError as error:
            raise FieldError(PROJECTIONS, str(error)) from error
        pairs[PROJECTED_COLUMNS[0]] = fit.projected_x
        pairs[PROJECTED_COLUMNS[1]] = fit.projected_y
    tables = {"Deming regression": _report(_with_known_sds(report, settings)), "Data": points, "Pairs": pairs}
    return Fit(settings, tables, [fit])


def _fit_one_series(frame, settings, name):
    """One independent fit; every failure names the series and stays on ``Y series``."""
    try:
        data = complete(frame, [settings.x, name])
    except ValueError as error:
        if f'Column "{settings.x}"' in str(error):
            raise FieldError("X", str(error)) from error
        raise FieldError(Y_SERIES, f'Series "{name}" contains non-numeric or infinite data.') from error
    if len(data) < 3:
        raise FieldError(Y_SERIES, f'Series "{name}" has {len(data)} complete pairs of X and Y; at least 3 are needed.')
    try:
        with np.errstate(all="ignore"):
            report, _, pairs = jackknife_deming(data, settings.x, name, settings.ratio,
                                                intervals=settings.intervals, level=settings.level)
    except ValueError as error:
        raise FieldError(Y_SERIES, f'Series "{name}" cannot be fitted: X and Y must both vary, '
                                   "with a nonzero covariance.") from error
    if not (np.isfinite(report["Slope"]) and np.isfinite(report["Intercept"])):
        raise FieldError(Y_SERIES, f'Series "{name}" has values outside the range the Deming fit can represent.')
    fit = SeriesFit(name, np.array(pairs["X"].to_numpy(), copy=True), np.array(pairs["Y"].to_numpy(), copy=True),
                    report["Slope"], report["Intercept"])
    if settings.projections:
        try:
            fit.projected_x, fit.projected_y = project_points(fit.x, fit.y, fit.slope, fit.intercept, settings.ratio)
        except ValueError as error:
            raise FieldError(Y_SERIES, f'The projected points of series "{name}" are outside the '
                                       "representable range.") from error
    return report, pairs, fit


def _series_report(rows, settings):
    columns = [SERIES_COLUMN, "N", "Slope", "Intercept", "Y / X measurement error variance"]
    if settings.intervals == "Jackknife (t)":
        columns += list(_INTERVAL_COLUMNS)
        if any("Interval status" in row for row in rows):
            columns.append("Interval status")
    table = pd.DataFrame(rows, columns=columns)
    if "Interval status" in table:
        table["Interval status"] = table["Interval status"].fillna("")
    return table


PAIRED_COLUMNS = (
    "Coefficient", "First series", "Second series", "First N", "Second N", "Paired N",
    "First", "Second", "Difference", "SE", "df", "CI low", "CI high", "Individual p",
    "Interval", "p note", "Status", "Y / X measurement error variance", "Confidence level (%)",
)
_PAIRED_BLANK = ("First", "Second", "Difference", "SE", "df", "CI low", "CI high", "Individual p")
_EXTRAPOLATED = "The intercept is the value at X = 0, outside the observed paired X range."
_ZERO_SE = "The jackknife standard error is zero, so the inference is unavailable."
_DEGENERATE_PAIRED = ("A leave-one-out fit is degenerate, so the standard error and the inference "
                      "are unavailable.")
_WORK_LIMIT_PAIRED = ("The jackknife work limit of {limit} paired rows was exceeded, so the standard "
                      "error and the inference are unavailable.")


def _stop_if_cancelled(cancel):
    """``cancel`` is the worker's ``threading.Event``, or a callable in a test."""
    if cancel is None:
        return
    stopped = bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())
    if stopped:
        from .analysis_chain import ChainCancelled
        raise ChainCancelled("Deming paired comparison cancelled.")


def _paired_table(rows):
    table = pd.DataFrame(rows, columns=PAIRED_COLUMNS)
    for name in ("Coefficient", "First series", "Second series", "Interval", "p note", "Status"):
        table[name] = table[name].fillna("").astype(object)
    return table


def _paired_base(settings, fits, paired_n):
    first, second = settings.series
    counted = {fit.name: len(fit.x) for fit in fits}
    return {
        "First series": first, "Second series": second,
        "First N": int(counted[first]), "Second N": int(counted[second]), "Paired N": int(paired_n),
        "Y / X measurement error variance": settings.ratio, "Confidence level (%)": settings.level,
    }


def _paired_status(settings, fits, paired_n, status):
    """Two rows, one per coefficient, with the counts and a reason instead of an inference."""
    base = _paired_base(settings, fits, paired_n)
    rows = []
    for coefficient in ("Slope", "Intercept"):
        row = {**base, "Coefficient": coefficient, "Interval": "", "p note": "", "Status": status}
        for name in _PAIRED_BLANK:
            row[name] = np.nan
        rows.append(row)
    return _paired_table(rows)


def _paired_line(x_values, y_values, ratio):
    report, _points = exploration.deming(pd.DataFrame({"X": x_values, "Y": y_values}), "X", "Y", float(ratio))
    slope, intercept = float(report["Slope"]), float(report["Intercept"])
    if not (np.isfinite(slope) and np.isfinite(intercept)):
        raise ValueError("The paired coefficients are outside the representable range.")
    return slope, intercept


def _outside_zero(x_values):
    low, high = float(np.min(x_values)), float(np.max(x_values))
    return not low <= 0.0 <= high


def paired_comparison(frame, settings, fits, cancel=None):
    """One sheet: second series minus first, on the rows where X and both series are valid."""
    _stop_if_cancelled(cancel)
    first_name, second_name = settings.series
    try:
        paired = complete(frame, [settings.x, first_name, second_name])
    except ValueError as error:
        raise FieldError(PAIRED, str(error)) from error
    count = len(paired)
    if count < PAIRED_MINIMUM:
        return _paired_status(settings, fits, count,
                              f"At least {PAIRED_MINIMUM} paired rows are required; {count} are available.")
    x_values = paired[settings.x].to_numpy(dtype=float)
    series_values = {first_name: paired[first_name].to_numpy(dtype=float),
                     second_name: paired[second_name].to_numpy(dtype=float)}
    lines, problems = {}, []
    for name, values in series_values.items():
        try:
            lines[name] = _paired_line(x_values, values, settings.ratio)
        except ValueError as error:
            problems.append((name, str(error)))
    if problems:
        detail = "; ".join(f'"{name}": {message}' for name, message in problems)
        return _paired_status(settings, fits, count, f"The paired fit is not defined. {detail}")
    first_line, second_line = lines[first_name], lines[second_name]
    extrapolated = _outside_zero(x_values)
    base = _paired_base(settings, fits, count)
    if count > JACKKNIFE_LIMIT:
        reason = _WORK_LIMIT_PAIRED.format(limit=JACKKNIFE_LIMIT)
        replicates = None
    else:
        _stop_if_cancelled(cancel)
        omitted = [leave_one_out_coefficients(x_values, series_values[name], settings.ratio)
                   for name in (first_name, second_name)]
        if omitted[0] is None or omitted[1] is None:
            reason = _DEGENERATE_PAIRED
            replicates = None
        else:
            reason = ""
            replicates = (omitted[1][0] - omitted[0][0], omitted[1][1] - omitted[0][1])
    degrees = count - 1
    critical = float(stats.t.isf((100.0 - settings.level) / 200.0, degrees)) if replicates is not None else np.nan
    rows = []
    for index, coefficient in enumerate(("Slope", "Intercept")):
        first, second = first_line[index], second_line[index]
        difference = second - first
        status = []
        standard_error = np.nan
        if replicates is None:
            status.append(reason)
        else:
            standard_error = float(_jackknife_se(replicates[index]))
            if not np.isfinite(standard_error):
                status.append("The jackknife standard error is not finite, so the inference is unavailable.")
            elif standard_error == 0.0:
                status.append(_ZERO_SE)
        if coefficient == "Intercept" and extrapolated:
            status.append(_EXTRAPOLATED)
        ran = replicates is not None and np.isfinite(standard_error)
        row = {**base, "Coefficient": coefficient, "First": first, "Second": second,
               "Difference": difference, "SE": standard_error,
               "Interval": PAIRED_INTERVAL if ran else "", "p note": "", "Status": " ".join(status)}
        for name in ("df", "CI low", "CI high", "Individual p"):
            row[name] = np.nan
        if replicates is not None and np.isfinite(standard_error) and standard_error > 0.0:
            half = critical * standard_error
            low, high = difference - half, difference + half
            probability = float(2.0 * stats.t.sf(abs(difference / standard_error), degrees))
            if np.isfinite(low) and np.isfinite(high) and np.isfinite(probability):
                row.update({"df": degrees, "CI low": low, "CI high": high, "Individual p": probability,
                            "Interval": PAIRED_INTERVAL, "p note": PAIRED_P_NOTE})
            else:
                row["Status"] = " ".join([*status, "The interval cannot be represented as finite numbers."])
        rows.append(row)
    return _paired_table(rows)


def analyse_fit(frame, options, cancel=None):
    """Fit, tabulate and prepare the drawing data for Deming regression, legacy or extended."""
    settings = read_settings(frame, options)
    if settings.paired:
        _stop_if_cancelled(cancel)
    if not settings.extended:
        report, points, pairs = jackknife_deming(frame, settings.x, settings.y, options["Y / X error variance"],
                                                 intervals=settings.intervals, level=settings.level)
        fit = SeriesFit(settings.y, np.array(pairs["X"].to_numpy(), copy=True),
                        np.array(pairs["Y"].to_numpy(), copy=True), report["Slope"], report["Intercept"])
        tables = {"Deming regression": _report(report), "Data": points, "Pairs": pairs}
        return Fit(settings, tables, [fit])
    if settings.series is None:
        return _single_fit(frame, settings)
    rows, data, all_pairs, fits = [], [], [], []
    for name in settings.series:
        report, pairs, fit = _fit_one_series(frame, settings, name)
        rows.append({SERIES_COLUMN: name, **report})
        data.append(pd.DataFrame({SERIES_COLUMN: name, "X": fit.x, "Y": fit.y}))
        pairs.insert(0, SERIES_COLUMN, name)
        if fit.projected_x is not None:
            pairs[PROJECTED_COLUMNS[0]] = fit.projected_x
            pairs[PROJECTED_COLUMNS[1]] = fit.projected_y
        all_pairs.append(pairs)
        fits.append(fit)
    tables = {"Deming regression": _series_report(rows, settings),
              "Data": pd.concat(data, ignore_index=True),
              "Pairs": pd.concat(all_pairs, ignore_index=True)}
    if settings.paired:
        tables[PAIRED_SHEET] = paired_comparison(frame, settings, fits, cancel)
    return Fit(settings, tables, fits)
