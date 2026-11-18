"""Restricted mean survival time (RMST) up to a declared horizon, for one cohort or two independent cohorts.

The RMST of a group is the area under its Kaplan–Meier curve S from 0 to the horizon τ, the mean event-free time
up to τ. Rows are grouped by time: at a time t with n subjects at risk (time >= t, tied censorings included) and
d events, S drops by the factor 1 - d / n, so the physical order of the rows never matters and an event at time
0 already lowers the curve at the origin. With the cuts 0 < t_1 < ... < t_k < τ at the distinct event times
inside the horizon, each interval [t_j, t_j+1) contributes the rectangle (t_j+1 - t_j) S(t_j). A censoring
without events changes the later risk sets and never the height of a rectangle; an event exactly at τ counts
among the events through the horizon and drops the drawn curve at its end point, with no area after it.

The variance is the integrated Greenwood sum

    Var = sum over event times t < τ of  d / [n (n - d)] · A(t)^2,     A(t) = area from t to τ,

where A comes from one backward cumulative sum of the rectangles (no quadratic covariance matrix). A time at
which every subject at risk has the event leaves no area after it, so its term is zero. The interval is the
two-sided Wald interval estimate ± z·SE on the original scale, kept as it is even beyond the theoretical
limits. When SE is exactly 0 the limits stay empty with status ``Zero variance``.

Two independent groups are reported as compared − reference (variances add, null value 0) and compared /
reference on the log scale (delta-method SE sqrt[(SE_c / RMST_c)^2 + (SE_r / RMST_r)^2], interval
exponentiated, null log ratio 0). The calculation runs in units of τ so that changing the time unit rescales
every time-valued output and leaves the ratio and every p value as they are.

This module reads the worksheet, never writes it, and raises ``FieldError`` naming the dialog field to correct.
Messages come from ``rmst_text`` so the dialog can show them in Italian.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from numbers import Real
from statistics import NormalDist

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_float_dtype, is_integer_dtype, is_numeric_dtype

from .field_error import FieldError
from .reporting import _report
from .rmst_text import MESSAGES

METHOD = "Restricted mean survival time"
TIME, STATUS, GROUP, REFERENCE = "Time", "Status", "Group", "Reference group"
EVENT_CODE, CENSOR_CODE = "Event code", "Censor code"
HORIZON, LEVEL, SHOW_GRAPH = "Horizon", "Confidence level (%)", "Show graph"
DEFAULTS = {EVENT_CODE: "1", CENSOR_CODE: "0", LEVEL: 95.0, SHOW_GRAPH: True}
ALL = "All"  # canonical group of a recipe without a Group column
MAX_ROWS = 50_000  # complete rows across both groups

RMST_SHEET, COMPARISON_SHEET, STEPS_SHEET, SETTINGS_SHEET = (
    "RMST", "RMST comparison", "Integration steps", "Settings")
RMST_COLUMNS = ["Group", "N", "Events through horizon", "Max follow-up", "Horizon", "RMST", "SE", "CI lower",
                "CI upper", "Status"]
COMPARISON_COLUMNS = ["Contrast", "Compared group", "Reference group", "Estimate", "Inference SE", "Scale",
                      "CI lower", "CI upper", "p", "Status"]
STEP_COLUMNS = ["Group", "Left", "Right", "Survival", "Area"]
OK, ZERO_VARIANCE, UNDEFINED_RATIO, NO_LOG = "OK", "Zero variance", "Undefined ratio", "Log inference unavailable"
DIFFERENCE, RATIO, IDENTITY, LOG = "Difference", "Ratio", "Identity", "Log"


def fail(field, key, **values):
    raise FieldError(field, MESSAGES[key].format(field=field, **values))


def show_number(value):
    """A number as the user would have typed it: 3.0 is 3, other values keep every digit."""
    value = float(value)
    if math.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def group_text(value):
    """A group label as shown in sheets and legends: integral numbers lose their trailing .0, text stays."""
    if isinstance(value, (float, np.floating)) and math.isfinite(value) and float(value).is_integer() \
            and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _shown(value):
    return repr(value) if isinstance(value, str) else group_text(value)


# ----- the recipe ------------------------------------------------------------------------------------------------------

def _real(value):
    """A finite real number that is not a boolean, or None."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _code_text(value, field):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (str, int, np.integer)):
        fail(field, "code_type")
    text = str(value)
    if not text.strip():
        fail(field, "code_empty")
    return text


class Settings:
    """The recipe read and checked before any worksheet value is looked at."""

    def __init__(self, options):
        get = lambda key: options.get(key, DEFAULTS.get(key))
        self.time, self.status = options.get(TIME), options.get(STATUS)
        group = options.get(GROUP)
        self.group = group if isinstance(group, str) and group else None
        if group not in (None, "") and not isinstance(group, str):
            fail(GROUP, "choose", role=GROUP)
        self.reference = options.get(REFERENCE)
        self.event = _code_text(get(EVENT_CODE), EVENT_CODE)
        self.censor = _code_text(get(CENSOR_CODE), CENSOR_CODE)
        level = _real(get(LEVEL))
        if level is None or not 0 < level < 100:
            fail(LEVEL, "level")
        self.level = level
        self.horizon = self._horizon(options.get(HORIZON))
        show = get(SHOW_GRAPH)
        if not isinstance(show, (bool, np.bool_)):
            fail(SHOW_GRAPH, "show_graph")
        self.show_graph = bool(show)

    @staticmethod
    def _horizon(value):
        if value is None or (isinstance(value, str) and not value.strip()):
            fail(HORIZON, "horizon_empty")
        number = _real(value)
        if number is None or number <= 0:
            fail(HORIZON, "horizon_number")
        return number

    @property
    def z(self):
        return -NormalDist().inv_cdf((100 - self.level) / 200)


# ----- the worksheet ---------------------------------------------------------------------------------------------------

@dataclass
class Cohort:
    """The complete rows of one group, sorted by time, with events as booleans."""
    label: str
    time: np.ndarray
    event: np.ndarray

    @property
    def longest(self):
        return float(self.time[-1])


@dataclass
class Dataset:
    cohorts: list
    complete: int
    incomplete: int


def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        fail(role, "choose", role=role)
    if name not in frame:
        fail(role, "exists", role=role, name=name)
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        fail(role, "unique")
    return column


def _key(value):
    """Exact key of one status cell: an int for integral numbers, ('x', value) for other numbers, text as is."""
    if isinstance(value, (bool, np.bool_)):
        raise TypeError("bool")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() else ("x", number)
    if isinstance(value, str):
        return value
    raise TypeError(type(value).__name__)


def _status_numeric(cells, name):
    """True for whole-number codes, False for text; booleans, complex values and mixtures are refused."""
    dtype = cells.dtype
    if is_bool_dtype(dtype) or is_complex_dtype(dtype):
        fail(STATUS, "status_type", name=name)
    if is_integer_dtype(dtype) or is_float_dtype(dtype):
        return True
    kinds = set()
    for value in pd.unique(cells):
        try:
            key = _key(value)
        except TypeError:
            fail(STATUS, "status_value", name=name, shown=_shown(value))
        kinds.add(isinstance(key, str))
    if len(kinds) > 1:
        fail(STATUS, "status_mixed", name=name)
    return not kinds.pop() if kinds else False


def _parse_code(text, field, numeric):
    if not numeric:
        return text
    try:
        code = Decimal(text.strip())
    except InvalidOperation:
        code = Decimal("NaN")
    if not code.is_finite() or code != code.to_integral_value():
        fail(field, "code_whole", shown=repr(text))
    if not -(2**63) <= code < 2**63:
        fail(field, "code_range", shown=repr(text))
    return int(code)


def _times(raw, name, labels):
    if is_bool_dtype(raw.dtype) or is_complex_dtype(raw.dtype) or not (
            is_numeric_dtype(raw.dtype) or raw.dtype == object):
        fail(TIME, "time_type", name=name)
    if raw.dtype == object and any(isinstance(value, (bool, np.bool_, str)) for value in raw):
        fail(TIME, "time_type", name=name)
    try:
        values = raw.to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError):
        fail(TIME, "time_type", name=name)
    large = np.isfinite(values) & (np.abs(values) >= 2**53)
    if large.any() and (is_integer_dtype(raw.dtype) or raw.dtype == object):
        for original, value in zip(raw.iloc[large], values[large], strict=True):
            if isinstance(original, (int, np.integer, Decimal)) and Decimal(int(original)) != Decimal(value):
                fail(TIME, "time_precision", name=name)
    bad = ~np.isfinite(values) | (values < 0)
    if bad.any():
        at = int(np.flatnonzero(bad)[0])
        fail(TIME, "time_value", row=labels[at], shown=show_number(values[at]))
    return values


def _roles(frame, settings):
    time = _column(frame, settings.time, TIME)
    status = _column(frame, settings.status, STATUS)
    group = _column(frame, settings.group, GROUP) if settings.group else None
    chosen = [(TIME, settings.time), (STATUS, settings.status)] + ([(GROUP, settings.group)] if group is not None else [])
    for index, (role, name) in enumerate(chosen):
        for earlier, other in chosen[:index]:
            if name == other:
                fail(role, "different", first=earlier, role=role)
    return time, status, group


def group_levels(frame, options):
    """Group labels of the complete rows in order of first appearance, for the dialog; [] when not available."""
    try:
        settings = Settings({**options, HORIZON: 1.0})
        time, status, group = _roles(frame, settings)
    except (FieldError, TypeError):
        return []
    if group is None:
        return []
    present = time.notna() & status.notna() & group.notna()
    _, levels = pd.factorize(group[present], sort=False)
    return list(dict.fromkeys(group_text(level) for level in levels))


def prepare(frame, settings):
    """Complete rows of the active roles, parsed and split into cohorts (reference first). Raises FieldError."""
    time, status, group = _roles(frame, settings)
    present = time.notna() & status.notna()
    if group is not None:
        present &= group.notna()
    rows = np.flatnonzero(present.to_numpy())
    complete = len(rows)
    if complete == 0:
        fail(GROUP if group is not None and not group.notna().any() else STATUS if not status.notna().any()
             else TIME, "no_complete")
    if complete > MAX_ROWS:
        fail(TIME, "rows", limit=f"{MAX_ROWS:,}", count=f"{complete:,}")
    labels = frame.index[rows]
    values = _times(time.iloc[rows], settings.time, labels)
    cells = status.iloc[rows]
    numeric = _status_numeric(cells, settings.status)
    event_key = _parse_code(settings.event, EVENT_CODE, numeric)
    censor_key = _parse_code(settings.censor, CENSOR_CODE, numeric)
    if event_key == censor_key:
        fail(CENSOR_CODE, "same_codes")
    codes, uniques = pd.factorize(cells, sort=False)
    mapped = np.empty(len(uniques), dtype=np.int8)
    for position, value in enumerate(uniques):
        try:
            key = _key(value)
        except TypeError:
            fail(STATUS, "status_value", name=settings.status, shown=_shown(value))
        mapped[position] = 1 if key == event_key else 0 if key == censor_key else -1
    flags = mapped[codes]
    if (flags < 0).any():
        at = int(np.flatnonzero(flags < 0)[0])
        fail(STATUS, "unknown_status", row=labels[at], shown=_shown(cells.iloc[at]))
    event = flags == 1
    if group is None:
        order = np.argsort(values, kind="stable")
        cohorts = [Cohort(ALL, values[order], event[order])]
    else:
        index, levels = pd.factorize(group.iloc[rows], sort=False)
        names = [group_text(level) for level in levels]
        if len(set(names)) != len(names):
            fail(GROUP, "group_text")
        if len(names) != 2:
            fail(GROUP, "group_count", name=settings.group, count=len(names))
        reference = settings.reference
        if isinstance(reference, (int, float, np.integer, np.floating)) and not isinstance(reference, (bool, np.bool_)):
            reference = group_text(reference)
        if reference is None or reference == "":
            fail(REFERENCE, "reference_empty", first_group=names[0], second_group=names[1])
        if not isinstance(reference, str) or reference not in names:
            fail(REFERENCE, "reference_unknown", name=str(reference), first_group=names[0], second_group=names[1])
        cohorts = []
        for position in (names.index(reference), 1 - names.index(reference)):
            chosen = np.flatnonzero(index == position)
            order = chosen[np.argsort(values[chosen], kind="stable")]
            cohorts.append(Cohort(names[position], values[order], event[order]))
    return Dataset(cohorts, complete, len(frame) - complete)


def check_horizon(settings, dataset):
    """The horizon is at most the shortest of the longest observed times; equality is accepted."""
    limit, cohort = min((c.longest, i) for i, c in enumerate(dataset.cohorts))
    name = dataset.cohorts[cohort].label
    single = len(dataset.cohorts) == 1
    if limit <= 0:
        fail(HORIZON, "horizon_none_one") if single else fail(HORIZON, "horizon_none", name=name)
    if settings.horizon > limit:
        values = {"value": show_number(settings.horizon), "limit": show_number(limit)}
        fail(HORIZON, "horizon_beyond_one", **values) if single else fail(HORIZON, "horizon_beyond", name=name,
                                                                             **values)
    return limit


def horizon_limit(frame, options):
    """The largest usable horizon for the dialog hint, or None while the other fields are incomplete."""
    try:
        settings = Settings({**options, HORIZON: 1.0})
        dataset = prepare(frame, settings)
    except (FieldError, TypeError):
        return None
    limit = min(cohort.longest for cohort in dataset.cohorts)
    return limit if limit > 0 else None


# ----- one group -------------------------------------------------------------------------------------------------------

@dataclass
class Estimate:
    label: str
    n: int
    events: int  # events at times <= τ
    longest: float
    rmst: float
    se: float
    left: np.ndarray
    right: np.ndarray
    survival: np.ndarray
    area: np.ndarray
    end: float  # S at τ, after the events at τ (the end point of the drawn curve)


def integrate(cohort, tau):
    """Kaplan–Meier rectangles from 0 to τ and the integrated Greenwood variance; O(n) after the sort."""
    times, first, counts = np.unique(cohort.time, return_index=True, return_counts=True)
    deaths = np.add.reduceat(cohort.event.astype(np.int64), first)
    n = len(cohort.time)
    at_risk = n - np.concatenate(([0], np.cumsum(counts)[:-1]))
    inside = (deaths > 0) & (times < tau)
    event_times, d, risk = times[inside], deaths[inside], at_risk[inside]
    survival = np.cumprod((risk - d) / risk)  # (n - d) / n rounds once, unlike 1 - d / n
    if len(event_times) and event_times[0] == 0:
        start, interior, heights = survival[0], event_times[1:], survival[1:]
        cut_of_event = np.arange(len(event_times))
    else:
        start, interior, heights = 1.0, event_times, survival
        cut_of_event = np.arange(1, len(event_times) + 1)
    left = np.concatenate(([0.0], interior))
    right = np.concatenate((interior, [tau]))
    height = np.concatenate(([start], heights))
    area = (right - left) * height
    # Unit-free rectangles keep the squares of the variance in range for any time unit.
    scaled = (right / tau - left / tau) * height
    residual = np.cumsum(scaled[::-1])[::-1]
    survivors = risk - d
    factor = np.divide(d, risk * survivors.astype(float), out=np.zeros(len(d)), where=survivors > 0)
    variance = float(np.sum(factor * residual[cut_of_event] ** 2))
    at_tau = (times == tau) & (deaths > 0)
    end = float(height[-1])
    if at_tau.any():
        k = int(np.flatnonzero(at_tau)[0])
        end *= (at_risk[k] - deaths[k]) / at_risk[k]
    events = int(cohort.event[cohort.time <= tau].sum())
    return Estimate(cohort.label, n, events, cohort.longest, math.fsum(area.tolist()), tau * math.sqrt(variance),
                    left, right, height, area, end)


# ----- comparisons -----------------------------------------------------------------------------------------------------

def _p(statistic):
    return math.erfc(abs(statistic) / math.sqrt(2))


def contrasts(compared, reference, z):
    """Difference and ratio rows: compared − reference on the identity scale, compared / reference on the log."""
    a, b = compared.rmst, reference.rmst
    delta = a - b
    se = math.hypot(compared.se, reference.se)
    difference = {"Estimate": delta, "Inference SE": se, "Scale": IDENTITY, "CI lower": math.nan,
                  "CI upper": math.nan, "p": math.nan, "Status": ZERO_VARIANCE}
    if se > 0:
        difference.update({"CI lower": delta - z * se, "CI upper": delta + z * se, "p": _p(delta / se),
                           "Status": OK})
    ratio = {"Estimate": math.nan, "Inference SE": math.nan, "Scale": LOG, "CI lower": math.nan,
             "CI upper": math.nan, "p": math.nan, "Status": UNDEFINED_RATIO}
    value = a / b if b > 0 else math.inf
    if math.isfinite(value):
        ratio.update({"Estimate": value, "Status": NO_LOG})
        if a > 0:
            log_ratio = math.log(a) - math.log(b)
            log_se = math.hypot(compared.se / a, reference.se / b)
            ratio.update({"Inference SE": log_se, "Status": ZERO_VARIANCE})
            if log_se > 0 and math.isfinite(log_se):
                ratio.update({"CI lower": math.exp(log_ratio - z * log_se),
                              "CI upper": math.exp(log_ratio + z * log_se),
                              "p": _p(log_ratio / log_se), "Status": OK})
    return {DIFFERENCE: difference, RATIO: ratio}


# ----- sheets ----------------------------------------------------------------------------------------------------------

def rmst_table(estimates, settings):
    z = settings.z
    rows = []
    for e in estimates:
        lower = e.rmst - z * e.se if e.se > 0 else math.nan
        upper = e.rmst + z * e.se if e.se > 0 else math.nan
        rows.append((e.label, e.n, e.events, e.longest, settings.horizon, e.rmst, e.se, lower, upper,
                     OK if e.se > 0 else ZERO_VARIANCE))
    table = pd.DataFrame(rows, columns=RMST_COLUMNS)
    return table.astype({"Group": object, "N": np.int64, "Events through horizon": np.int64, "Status": object})


def comparison_table(estimates, settings):
    reference, compared = estimates
    rows = []
    for name, values in contrasts(compared, reference, settings.z).items():
        rows.append({"Contrast": name, "Compared group": compared.label, "Reference group": reference.label,
                     **values})
    table = pd.DataFrame(rows, columns=COMPARISON_COLUMNS)
    numbers = ("Estimate", "Inference SE", "CI lower", "CI upper", "p")
    return table.astype({**dict.fromkeys(numbers, float), "Contrast": object, "Compared group": object,
                         "Reference group": object, "Scale": object, "Status": object})


def steps_table(estimates):
    parts = [pd.DataFrame({"Group": np.full(len(e.left), e.label, dtype=object), "Left": e.left, "Right": e.right,
                           "Survival": e.survival, "Area": e.area}) for e in estimates]
    return pd.concat(parts, ignore_index=True)[STEP_COLUMNS]


def settings_table(settings, dataset, limit):
    labels = [cohort.label for cohort in dataset.cohorts]
    values = {
        "Time column": settings.time,
        "Status column": settings.status,
        "Group column": settings.group or f"None (single cohort {ALL})",
        "Reference group": labels[0] if settings.group else "",
        "Compared group": labels[1] if settings.group else "",
        "Event code": settings.event,
        "Censor code": settings.censor,
        "Horizon": settings.horizon,
        "Largest usable horizon": limit,
        "Confidence level (%)": settings.level,
        "Complete rows": dataset.complete,
        "Incomplete rows": dataset.incomplete,
        "Estimator": "Kaplan–Meier; rows tied in time form one step and the number at risk counts every subject "
                     "with a time of at least t, tied censorings included. RMST is the exact area under the "
                     "step curve from 0 to the horizon.",
        "Variance": "Integrated Greenwood sum over the event times before the horizon.",
        "Confidence intervals": "Asymptotic two-sided Wald intervals on the original scale, not truncated; they "
                                "can be fragile with few events. Empty when SE is 0.",
        "Comparison": "Independent groups: difference compared − reference (variances added) and ratio "
                      "compared / reference with delta-method inference on the log scale; two-sided normal "
                      "p values against 0 (difference) and log ratio 0." if settings.group else "None (one cohort)",
        "Not included": "Covariates, bootstrap, delayed entry, competing risks and multiple comparisons.",
    }
    return _report(values)


# ----- analysis --------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    settings: Settings
    dataset: Dataset
    limit: float


def check_options(frame, options):
    """Every value, role and budget that can be checked without integrating; raises FieldError."""
    settings = Settings(options)
    dataset = prepare(frame, settings)
    limit = check_horizon(settings, dataset)
    return Plan(settings, dataset, limit)


def run(frame, options):
    """The sheets of the analysis and the estimates for the figure."""
    plan = check_options(frame, options)
    settings = plan.settings
    estimates = [integrate(cohort, settings.horizon) for cohort in plan.dataset.cohorts]
    tables = {RMST_SHEET: rmst_table(estimates, settings)}
    if len(estimates) == 2:
        tables[COMPARISON_SHEET] = comparison_table(estimates, settings)
    tables[STEPS_SHEET] = steps_table(estimates)
    tables[SETTINGS_SHEET] = settings_table(settings, plan.dataset, plan.limit)
    return tables, plan, estimates
