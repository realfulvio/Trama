"""Passing–Bablok regression, tangent metric, analytical limits.

The pairwise step follows ``calc_PaBa`` and ``calc_AngleMat_opt`` in mcr 1.3.3.1
(``slope.measure = tangent``, ``method.ci = analytical``). Angles of slopes equal to −1 stay
in the ranking. The rank offset is ``n(angle <= −π/4) + n(angle < −π/4)`` when Kendall's tau
is non-negative, and the opposite count with a minus sign otherwise. An even shifted count
averages the two central slopes, not the two central angles. The intercept is the median of
``Y − bX``, and each interval end of the intercept uses the opposite end of the slope interval.

mcr refuses negative measurements before calling this routine. The slope formula itself does
not, so a negative pair is fitted and the difference is recorded in the notes.
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from scipy import stats

from .analysis_chain import ChainCancelled
from .field_error import FieldError
from .reporting import Result, _plot
from .stats import complete

METHOD = "Passing–Bablok regression"
SHEET = METHOD
CALCULATION = "Calculation"
NOTES = "Notes"
PAIRS = "Pairs"
LEVEL = "Confidence level (%)"
IDENTITY = "Identity line"
X = "X"
Y = "Y"
INTERVAL = "Passing–Bablok analytical (tangent)"
PROCEDURE = ("Tangent metric: pairwise slopes are ordered as angles, the rank is shifted by the "
             "negative slopes, an even shifted count averages the two central slopes, and the "
             "intercept is the median of Y − bX.")
# One float64 per slope is 8 bytes. Two million slopes are 16 MB before the index vectors,
# which is the largest table the timed checks ask for (2,000 pairs need 1,999,000 slopes).
SLOPE_LIMIT = 2_000_000
_MINIMUM = 3
_EPS = 1e-12
_RIGHT = math.pi / 4
IDENTITY_COLOR = "#81919b"

OPTIONS = {X: None, Y: None, LEVEL: 95.0, IDENTITY: False}


@dataclass(frozen=True)
class Fit:
    slope: float | None
    intercept: float | None
    slope_low: float | None
    slope_high: float | None
    intercept_low: float | None
    intercept_high: float | None
    valid_pairs: int
    incomplete_rows: int
    identical_pairs: int
    vertical_slopes: int
    slopes_used: int
    below_minus_one: int
    equal_minus_one: int
    between_minus_one_and_zero: int
    rank_offset: int
    kendall: float | None
    positive: bool
    level: float
    limits_available: bool
    undefined: str


def listed_in_classic(name, current):
    """The classic window does not offer this analysis as a new command."""
    return not (name == METHOD and name != current)


def _stop(cancel):
    if cancel is None:
        return
    stopped = bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())
    if stopped:
        raise ChainCancelled("Passing–Bablok regression cancelled.")


def _c_round(value):
    """``round`` in the mcr C code: half away from zero."""
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def _near(left, right):
    """``diff`` in mcr: exact zeros stay zero, and a 1e-12 relative gap counts as zero."""
    gap = left - right
    if gap == 0.0 or abs(gap) < _EPS * (abs(left) + abs(right)) / 2.0:
        return 0.0
    return gap


def _level(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating)):
        raise FieldError(LEVEL, f"{LEVEL} must be finite and strictly between 0 and 100.")
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 100.0:
        raise FieldError(LEVEL, f"{LEVEL} must be finite and strictly between 0 and 100.")
    return number


def check_dialog(options):
    """Refuse a bad recipe before the worker. Column checks happen with the data."""
    _level(options.get(LEVEL, 95.0))
    identity = options.get(IDENTITY, False)
    if not isinstance(identity, (bool, np.bool_)):
        raise FieldError(IDENTITY, "Identity line must be on or off.")


def format_error(error):
    from .i18n import translate_message
    return translate_message(str(error), "passing.error.")


def _pairs(frame, x_name, y_name):
    if x_name == y_name:
        raise FieldError(Y, "Select two different columns for X and Y.")
    try:
        paired = complete(frame, [x_name, y_name])
    except ValueError as error:
        message = str(error)
        field = Y if y_name in message else X
        raise FieldError(field, message) from error
    incomplete = int(len(frame) - len(paired))
    return paired[x_name].to_numpy(dtype=float), paired[y_name].to_numpy(dtype=float), incomplete


def _near_array(later, earlier):
    gap = later - earlier
    scale = _EPS * (np.abs(later) + np.abs(earlier)) / 2.0
    return np.where((gap == 0.0) | (np.abs(gap) < scale), 0.0, gap)


def _angles(x_values, y_values, positive):
    """Upper-triangle angles. Identical pairs are omitted; a repeated X becomes ±π/2."""
    count = len(x_values)
    left, right = np.triu_indices(count, k=1)
    dx = _near_array(x_values[right], x_values[left])
    dy = _near_array(y_values[right], y_values[left])
    identical = int(np.count_nonzero((dx == 0.0) & (dy == 0.0)))
    vertical = int(np.count_nonzero((dx == 0.0) & (dy != 0.0)))
    finite = dx != 0.0
    angles = np.arctan(dy[finite] / dx[finite])
    if vertical:
        angles = np.concatenate([angles, np.full(vertical, math.pi / 2 if positive else -math.pi / 2)])
    below = int(np.count_nonzero(angles < -_RIGHT))
    equal = int(np.count_nonzero(angles == -_RIGHT))
    between = int(np.count_nonzero((angles > -_RIGHT) & (angles < 0.0)))
    at_one = int(np.count_nonzero(angles == _RIGHT))
    above_one = int(np.count_nonzero(angles > _RIGHT))
    return angles, identical, vertical, below, equal, between, at_one, above_one


def _ends(ordered, n_index):
    """The one or two central angles selected by ``calc_PaBa`` for this shifted count."""
    if n_index <= 0:
        return None
    half = (n_index + 1) // 2
    if n_index % 2 == 0:
        left, right = half - 1, half
        if left < 0 or right >= len(ordered):
            return None
        return float(ordered[left]), float(ordered[right])
    index = half - 1
    if index < 0 or index >= len(ordered):
        return None
    return (float(ordered[index]),)


def _slope_from(ends):
    if ends is None:
        return None
    values = [math.tan(angle) for angle in ends]
    if not all(math.isfinite(value) for value in values):
        return None
    return float(sum(values) / len(values))


def _median(x_values, y_values, slope):
    residuals = np.array([_near(float(y), slope * float(x)) for x, y in zip(x_values, y_values)], dtype=float)
    ordered = np.sort(residuals)
    count = len(ordered)
    half = (count + 1) // 2
    if count % 2 == 0:
        return float(ordered[half - 1] + ordered[half]) / 2.0
    return float(ordered[half - 1])


def fit_values(x_values, y_values, level, cancel=None):
    """Fit one sample. ``level`` is a percent. The limit is checked before any slope array exists."""
    _stop(cancel)
    count = int(len(x_values))
    if count < _MINIMUM:
        raise FieldError(X, f"Passing–Bablok regression needs at least {_MINIMUM} finite pairs; {count} are available.")
    slopes = count * (count - 1) // 2
    if slopes >= SLOPE_LIMIT:
        raise FieldError(X, "Passing–Bablok regression stops before allocating pairwise slopes: "
                         f"{count} complete pairs would need {slopes} slopes, above the limit of {SLOPE_LIMIT}.")
    _stop(cancel)
    kendall = stats.kendalltau(x_values, y_values, variant="b", method="auto")
    tau = float(kendall.statistic)
    positive = bool(math.isfinite(tau) and tau >= 0.0)
    angles, identical, vertical, below, equal, between, at_one, above_one = _angles(x_values, y_values, positive)
    # n(angle <= −π/4) + n(angle < −π/4) when the correlation is non-negative.
    offset = (2 * below + equal) if positive else -(at_one + above_one + above_one)
    undefined = ""
    slope = intercept = None
    low = high = None
    if len(angles) == 0 or not (np.std(x_values) > 0 and np.std(y_values) > 0):
        undefined = "The fit is not defined because X and Y do not both vary."
    else:
        ordered = np.sort(angles)
        slope = _slope_from(_ends(ordered, len(angles) + offset))
        if slope is None:
            undefined = "The shifted median falls outside the pairwise slopes."
        else:
            intercept = _median(x_values, y_values, slope)
            # The same normal quantile mcr passes as pQuantile = qnorm(1 - alpha/2).
            alpha = 1.0 - level / 100.0
            width = _c_round(float(stats.norm.ppf(1.0 - alpha / 2.0))
                             * math.sqrt(count * (count - 1.0) * (2.0 * count + 5.0) / 18.0))
            lower_index = len(angles) - width + offset
            upper_index = len(angles) + width + offset
            # LowestIdx is one past twice the number of angles sitting exactly on the excluded diagonal.
            lowest = 2 * (equal if positive else at_one) + 1
            lower_ok = (lower_index + 1) // 2 >= lowest
            upper_ok = (upper_index + 1) // 2 <= len(angles)
            if lower_ok and upper_ok:
                low = _slope_from(_ends(ordered, lower_index))
                high = _slope_from(_ends(ordered, upper_index))
            if low is None or high is None:
                # One end that cannot be represented clears both, as the C routine sets both to NA.
                low = high = None
    limits = low is not None and high is not None and slope is not None
    intercept_low = _median(x_values, y_values, high) if limits else None
    intercept_high = _median(x_values, y_values, low) if limits else None
    return Fit(slope, intercept, low, high, intercept_low, intercept_high, count, 0, identical, vertical,
               int(len(angles)), below, equal, between, int(offset), None if not math.isfinite(tau) else tau,
               positive, level, limits, undefined)


def _notes(fit, incomplete):
    notes = [PROCEDURE]
    if incomplete:
        notes.append(f"Rows left out because X or Y is missing or excluded: {incomplete}.")
    if fit.identical_pairs:
        notes.append(f"Identical pairs omitted from the slopes: {fit.identical_pairs}.")
    if fit.vertical_slopes:
        notes.append(f"Repeated X values kept as vertical slopes: {fit.vertical_slopes}.")
    if fit.equal_minus_one:
        notes.append(f"Pairwise slopes equal to −1 kept in the ranking: {fit.equal_minus_one}.")
    if fit.kendall is None:
        notes.append("Kendall correlation is not defined, so the rank offset uses the negative-slope side.")
    if fit.undefined:
        notes.append(fit.undefined)
    elif not fit.limits_available:
        notes.append("The confidence limits are not estimable.")
    return notes


def analyse(frame, options, cancel=None):
    """The real entry: validate, fit, and return the sheets and the figure."""
    check_dialog(options)
    _stop(cancel)
    x_name, y_name = options[X], options[Y]
    if x_name not in frame.columns:
        raise FieldError(X, f'X column "{x_name}" is not in the worksheet.')
    if y_name not in frame.columns:
        raise FieldError(Y, f'Y column "{y_name}" is not in the worksheet.')
    level = _level(options.get(LEVEL, 95.0))
    x_values, y_values, incomplete = _pairs(frame, x_name, y_name)
    negatives = int(np.count_nonzero((x_values < 0.0) | (y_values < 0.0)))
    try:
        fit = fit_values(x_values, y_values, level, cancel)
    except FieldError:
        raise
    fit = Fit(fit.slope, fit.intercept, fit.slope_low, fit.slope_high, fit.intercept_low, fit.intercept_high,
              fit.valid_pairs, incomplete, fit.identical_pairs, fit.vertical_slopes, fit.slopes_used,
              fit.below_minus_one, fit.equal_minus_one, fit.between_minus_one_and_zero, fit.rank_offset,
              fit.kendall, fit.positive, level, fit.limits_available, fit.undefined)
    notes = _notes(fit, incomplete)
    if negatives:
        notes.append(f"Negative measurements fitted: {negatives}. mcr 1.3.3.1 stops on a negative value; "
                     "this fit uses the same pairwise slopes.")
    parameters = pd.DataFrame({
        "Parameter": ["Slope", "Intercept"],
        "Estimate": [fit.slope if fit.slope is not None else np.nan,
                     fit.intercept if fit.intercept is not None else np.nan],
        "CI low": [fit.slope_low if fit.slope_low is not None else np.nan,
                   fit.intercept_low if fit.intercept_low is not None else np.nan],
        "CI high": [fit.slope_high if fit.slope_high is not None else np.nan,
                    fit.intercept_high if fit.intercept_high is not None else np.nan],
    })
    details = pd.DataFrame({
        "Item": ["Valid pairs", "Incomplete rows", "Slopes used", "Slopes below −1", "Slopes equal to −1",
                 "Slopes in (−1, 0)", "Vertical slopes", "Identical pairs omitted", "Rank offset",
                 "Kendall tau", "Positive correlation", LEVEL, "Interval", "Procedure"],
        "Value": [fit.valid_pairs, incomplete, fit.slopes_used, fit.below_minus_one, fit.equal_minus_one,
                  fit.between_minus_one_and_zero, fit.vertical_slopes, fit.identical_pairs, fit.rank_offset,
                  fit.kendall if fit.kendall is not None else np.nan,
                  "Yes" if fit.positive else "No", level,
                  INTERVAL if fit.limits_available else "", PROCEDURE],
    })
    pairs = pd.DataFrame({x_name: x_values, y_name: y_values})
    note_frame = pd.DataFrame({"Note": notes})
    figure = _figure(x_name, y_name, x_values, y_values, fit, bool(options.get(IDENTITY, False)))
    return Result({SHEET: parameters, CALCULATION: details, NOTES: note_frame, PAIRS: pairs}, figure)


def _figure(x_name, y_name, x_values, y_values, fit, identity):
    figure, axes = _plot(METHOD, x_name, y_name)
    for label in (axes.xaxis.label, axes.yaxis.label, axes.title):
        label.set_parse_math(False)
    if len(x_values) == 0:
        return figure
    axes.scatter(x_values, y_values, zorder=3)
    if fit.slope is not None and fit.intercept is not None:
        domain = np.array([float(np.min(x_values)), float(np.max(x_values))])
        if domain[0] == domain[1]:
            domain = domain + np.array([-1.0, 1.0])
        axes.plot(domain, fit.intercept + fit.slope * domain, label="Passing–Bablok", zorder=2)
    if identity and len(x_values):
        low = float(min(np.min(x_values), np.min(y_values)))
        high = float(max(np.max(x_values), np.max(y_values)))
        if low == high:
            low, high = low - 1.0, high + 1.0
        axes.plot([low, high], [low, high], linestyle="--", color=IDENTITY_COLOR, label="Identity", zorder=1)
        axes.set_xlim(low, high)
        axes.set_ylim(low, high)
    if axes.get_legend_handles_labels()[0]:
        legend = axes.legend()
        for text in legend.get_texts():
            text.set_parse_math(False)
    return figure
