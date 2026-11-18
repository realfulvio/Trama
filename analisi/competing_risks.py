"""Competing risks: cumulative incidence by Aalen–Johansen, Aalen's variance and Gray's k-sample test.

A subject has one time and one status: a censoring code, or one of up to six event codes (causes). The
cumulative incidence of cause k is the probability of failing from k by time t in the presence of the other
causes. For one group, with Y(t) subjects at risk (time >= t, tied censorings included), d_k(t) failures
from k, d(t) = sum of d_k(t), S(0-) = 1 and F_k(0-) = 0:

    F_k(t) = F_k(t-) + S(t-) d_k(t) / Y(t)        S(t) = S(t-) (1 - d(t) / Y(t))

(Aalen & Johansen, 1978). Ties are grouped, so the estimate does not depend on the order of rows. The point
variance is Aalen's delta-method variance with the hypergeometric tie correction used by ``cmprsk::cuminc``:
at each failure time j the martingale contribution of the cause of interest and of the competing causes is

    w_j (t4_j - F t3_j)^2,   cause k:  w = S(j-)^2 c_k d_k / Y^2, t3 = 1 / S(j), t4 = 1 + F_k(j) / S(j)
                             others:   w = S(j-)^2 c_o d_o / Y^2, t3 = 1 / S(j), t4 = F_k(j) / S(j)

with c = (Y - d) / (Y - 1) for d > 1 (otherwise 1) and the terms with S(j) = 0 dropped for the competing causes.
The variance is evaluated at the failure times of cause k and carried to the times in between, which is the
convention of the reference implementation; before the first failure of the cause it is zero.

Gray's test (1988) compares the subdistribution hazard of one cause among G groups. The score of group g is
the sum over failure times of d_1g - nd_1 R_g / sum_h R_h, where R_g = Y_g (1 - F_g1(t-)) / S_g(t-) is the
size of the modified risk set (subjects who failed from a competing cause remain in it, weighted by the
censoring survival, which makes it equal to this expression). Its covariance has a martingale part for the
cause of interest, one for the competing causes, and the correction for estimating the censoring
distribution. The statistic is s' V^-1 s over the first G - 1 groups, referred to chi-square with G - 1 df.
The system is solved, never inverted through a pseudoinverse: a rank-deficient covariance gives no p value.

This module reads no worksheet text and writes nothing. It raises ``FieldError`` for the dialog field that
fixes a problem, and ``CompetingRisksCancelled`` when the caller's Event is set during a long pass.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_float_dtype, is_integer_dtype, is_numeric_dtype
from scipy import stats

from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .processing import _check_integer_precision

CENSORED = 0
MAX_ROWS = 100_000
MAX_GROUPS = 12
MAX_CAUSES = 6
MAX_CURVE_ROWS = 200_000
MAX_QUERIES = 200
MAX_GRAY_WORK = 30_000_000
SINGULAR_TOLERANCE = 1e-10
_CHUNK = 1_500_000


class CompetingRisksCancelled(MonteCarloCancelled):
    """The calculation was cancelled before a result was published."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CompetingRisksCancelled("Competing risks calculation cancelled.")


# ----- reading the worksheet -------------------------------------------------------------------------------------------

@dataclass
class Dataset:
    """Complete cases, sorted by group and time. ``code`` is 0 for censored, 1..K for the declared causes."""
    groups: list
    time: np.ndarray
    code: np.ndarray
    group: np.ndarray
    starts: np.ndarray
    causes: tuple
    complete: int
    omitted: int

    def slice(self, index):
        return slice(self.starts[index], self.starts[index + 1])

    @property
    def sizes(self):
        return np.diff(self.starts)


def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        raise FieldError(role, f"Choose a column for {role}.")
    if name not in frame:
        raise FieldError(role, f'Choose an existing column for {role}: "{name}" is not in the worksheet.')
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        raise FieldError(role, "Worksheet column names must be unique.")
    return column


def _text(value):
    """Group label shown in tables: integral numbers lose their trailing .0, text is untouched."""
    if isinstance(value, (bool, np.bool_)):
        return str(value)
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _show(value):
    return _text(value) if not isinstance(value, str) else repr(value)


def parse_code(text, field, numeric):
    """Canonical key of a typed status code: an exact int for numeric status columns, the literal text otherwise."""
    if not isinstance(text, str):
        raise FieldError(field, f"{field}: a code is written as text, such as \"1\".")
    if not text.strip():
        raise FieldError(field, f"{field}: a code cannot be empty.")
    if not numeric:
        return text
    try:
        code = Decimal(text.strip())
    except InvalidOperation:
        code = Decimal("NaN")
    if not code.is_finite() or code != code.to_integral_value():
        raise FieldError(field, f"{field}: {text!r} must be a whole number for a numeric status column.")
    if not -(2**63) <= code < 2**63:
        raise FieldError(field, f"{field}: {text!r} is outside the 64-bit integer range.")
    return int(code)


def _unique_key(value):
    """Exact key of one distinct cell: an int for integral numbers, ('x', value) for any other number."""
    if isinstance(value, (bool, np.bool_)):
        raise TypeError("bool")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if np.isfinite(number) and number.is_integer():
            return int(number)
        return ("x", number)
    if isinstance(value, str):
        return value
    raise TypeError(type(value).__name__)


def _status_kind(values, name):
    """'number' or 'text' for the status cells of the complete rows; refuse booleans, complex and mixtures."""
    dtype = values.dtype
    if is_bool_dtype(dtype) or is_complex_dtype(dtype):
        raise FieldError("Status", f'Column "{name}" must hold whole-number codes or text, not booleans or complex numbers.')
    if is_integer_dtype(dtype) or is_float_dtype(dtype):
        return "number"
    kinds = set()
    for value in pd.unique(values):
        try:
            key = _unique_key(value)
        except TypeError:
            raise FieldError("Status", f'Column "{name}" must hold whole-number codes or text; '
                                       f"{value!r} is not allowed.") from None
        kinds.add("text" if isinstance(key, str) else "number")
    if len(kinds) > 1:
        raise FieldError("Status", f'Column "{name}" mixes numbers and text. Use one kind of status code.')
    return kinds.pop() if kinds else "text"


def prepare(frame, time, status, group, censor, events):
    """Complete cases of the three roles, recoded and sorted. Raises FieldError naming the field to correct."""
    if len(frame) > MAX_ROWS:
        raise FieldError("Time", f"Competing risks reads up to {MAX_ROWS:,} rows; this worksheet has {len(frame):,}.")
    time_column = _column(frame, time, "Time")
    status_column = _column(frame, status, "Status")
    group_column = _column(frame, group, "Group") if group else None
    names = {"Time": time, "Status": status, "Group": group or None}
    chosen = [(role, name) for role, name in names.items() if name]
    for index, (role, name) in enumerate(chosen):
        for earlier, other in chosen[:index]:
            if name == other:
                raise FieldError(role, f"Choose different columns for {earlier} and {role}.")
    if not isinstance(events, (list, tuple)) or not 1 <= len(events) <= MAX_CAUSES:
        raise FieldError("Event codes", f"Event codes: enter 1 to {MAX_CAUSES} codes.")
    if not isinstance(censor, str):
        raise FieldError("Censor code", "Censor code: enter a code.")
    present = time_column.notna() & status_column.notna()
    if group_column is not None:
        present &= group_column.notna()
    complete = int(present.sum())
    omitted = len(frame) - complete
    if complete == 0:
        empty = "Group" if group_column is not None and not group_column.notna().any() else (
            "Status" if not status_column.notna().any() else "Time")
        raise FieldError(empty, "No complete rows: every row misses the time, the status or the group.")
    rows = np.flatnonzero(present.to_numpy())
    labels = frame.index[rows]
    # Time: real finite numbers >= 0, read from the complete rows only.
    raw = time_column.iloc[rows]
    if is_bool_dtype(raw.dtype) or is_complex_dtype(raw.dtype) or not (
            is_numeric_dtype(raw.dtype) or raw.dtype == object):
        raise FieldError("Time", f'Column "{time}" must be numeric.')
    try:
        values = raw.to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError):
        raise FieldError("Time", f'Column "{time}" must be numeric.') from None
    if is_integer_dtype(raw.dtype):
        _check_integer_precision(raw, values, "Time")
    elif raw.dtype == object:
        if any(isinstance(value, (bool, np.bool_)) for value in raw):
            raise FieldError("Time", f'Column "{time}" must be numeric.')
        large = np.isfinite(values) & (values >= 2**53)
        for original, value in zip(raw.iloc[large], values[large], strict=True):
            if isinstance(original, (str, int, np.integer, Decimal)):
                exact = Decimal(str(original))
                if exact != Decimal(value):
                    raise FieldError("Time", f'Column "{time}" contains integers outside the supported precision.')
    bad = ~np.isfinite(values) | (values < 0)
    if bad.any():
        at = int(np.flatnonzero(bad)[0])
        raise FieldError("Time", f"Source row {labels[at]}: time {values[at]:g} must be a finite number of 0 or more.")
    # Status: one kind of code, compared on what the column really holds.
    cells = status_column.iloc[rows]
    kind = _status_kind(cells, status)
    numeric = kind == "number"
    censor_key = parse_code(censor, "Censor code", numeric)
    event_keys = []
    for text in events:
        key = parse_code(text, "Event codes", numeric)
        if key == censor_key:
            raise FieldError("Censor code", f"Censor code and event code {text!r} are the same status. "
                                            "Use different codes.")
        if key in event_keys:
            raise FieldError("Event codes", f"Event codes: {text!r} repeats an earlier code "
                                            "(the same status written twice).")
        event_keys.append(key)
    codes_unique, uniques = pd.factorize(cells, sort=False)
    lookup = {censor_key: CENSORED, **{key: index for index, key in enumerate(event_keys, 1)}}
    mapped = np.empty(len(uniques), dtype=np.int64)
    for position, value in enumerate(uniques):
        try:
            key = _unique_key(value)
        except TypeError:
            raise FieldError("Status", f"Status {value!r} is not allowed.") from None
        mapped[position] = lookup.get(key, -1)
    code = mapped[codes_unique]
    unknown = code < 0
    if unknown.any():
        at = int(np.flatnonzero(unknown)[0])
        raise FieldError("Status", f"Source row {labels[at]}: status {_show(cells.iloc[at])} is neither the "
                                   "censor code nor one of the event codes.")
    # Groups: first occurrence among the complete rows, shown as text.
    if group_column is not None:
        group_codes, levels = pd.factorize(group_column.iloc[rows], sort=False)
        names_shown = [_text(level) for level in levels]
        if len(set(names_shown)) != len(names_shown):
            raise FieldError("Group", "Group names must stay distinct when written as text.")
        if len(levels) > MAX_GROUPS:
            raise FieldError("Group", f"Competing risks compares up to {MAX_GROUPS} groups; "
                                      f"column {group!r} has {len(levels)}.")
        index = group_codes.astype(np.int64)
    else:
        names_shown, index = ["All"], np.zeros(len(rows), dtype=np.int64)
    order = np.lexsort((values, index))
    sizes = np.bincount(index, minlength=len(names_shown))
    return Dataset(names_shown, values[order], code[order], index[order], np.r_[0, np.cumsum(sizes)],
                   tuple(events), complete, omitted)


# ----- cumulative incidence --------------------------------------------------------------------------------------------

@dataclass
class GroupCurves:
    """Step functions of one group at its distinct observed times (all arrays aligned, right-continuous)."""
    label: str
    n: int
    times: np.ndarray
    at_risk: np.ndarray
    events: np.ndarray
    all_events: np.ndarray
    censored: np.ndarray
    survival: np.ndarray
    incidence: np.ndarray
    variance: np.ndarray


def _ratio(numerator, denominator, where):
    out = np.zeros(numerator.shape, dtype=np.longdouble)
    np.divide(numerator, denominator, out=out, where=where)
    return out


def _variance(at_risk, events, all_events, previous, current, incidence):
    """Aalen variance of one cause at every distinct time, carried between failures of that cause."""
    long = np.longdouble
    risk = at_risk.astype(long)
    own = events.astype(long)
    other = (all_events - events).astype(long)
    s_prev, s_cur, f_cur = previous.astype(long), current.astype(long), incidence.astype(long)
    alive = s_cur > 0
    has_own, has_other = own > 0, (other > 0) & alive

    def tie(count):
        factor = np.ones_like(risk)
        many = count > 1
        factor[many] = 1 - (count[many] - 1) / (risk[many] - 1)
        return factor

    inverse = _ratio(np.ones_like(s_cur), s_cur, alive)
    w_own = np.where(has_own, s_prev ** 2 * tie(own) * own / risk ** 2, 0)
    w_other = np.where(has_other, s_prev ** 2 * tie(other) * other / risk ** 2, 0)
    t4_own = 1 + inverse * f_cur
    t4_other = inverse * f_cur
    p = np.cumsum(w_own * t4_own ** 2 + w_other * t4_other ** 2)
    q = np.cumsum(w_own * inverse * t4_own + w_other * inverse * t4_other)
    r = np.cumsum(w_own * inverse ** 2 + w_other * inverse ** 2)
    at_event = p + f_cur ** 2 * r - 2 * f_cur * q
    at_event = np.where(at_event < 0, 0, at_event)
    # Carry the value of the last failure of this cause forward; zero before the first.
    last = np.maximum.accumulate(np.where(has_own, np.arange(len(risk)), -1))
    return np.where(last >= 0, at_event[np.maximum(last, 0)], 0).astype(float)


def group_curves(label, time, code, n_causes):
    """Aalen–Johansen curves of one group from its sorted times and codes. Ties are grouped, rows are not looped."""
    n = len(time)
    first = np.flatnonzero(np.r_[True, time[1:] != time[:-1]])
    times = time[first]
    at_risk = n - first
    position = np.repeat(np.arange(len(first)), np.diff(np.r_[first, n]))
    counts = np.bincount(position * (n_causes + 1) + code, minlength=len(first) * (n_causes + 1))
    counts = counts.reshape(len(first), n_causes + 1)
    censored, events = counts[:, 0], counts[:, 1:].T
    all_events = events.sum(axis=0)
    survival = np.cumprod(1.0 - all_events / at_risk)
    previous = np.r_[1.0, survival[:-1]]
    incidence = np.cumsum(previous * events / at_risk, axis=1)
    # Rounding can leave the mass at 1 + 1e-16; nothing larger is a rounding error.
    incidence = np.where((incidence > 1) & (incidence < 1 + 1e-9), 1.0, incidence)
    variance = np.vstack([_variance(at_risk, events[k], all_events, previous, survival, incidence[k])
                          for k in range(n_causes)])
    return GroupCurves(label, n, times, at_risk, events, all_events, censored, survival, incidence, variance)


def curve_rows(dataset):
    """Rows of the Cumulative incidence sheet: group, time, then declared cause."""
    return sum(len(group) * len(dataset.causes) for group in _distinct_times(dataset))


def _distinct_times(dataset):
    for index in range(len(dataset.groups)):
        yield np.unique(dataset.time[dataset.slice(index)])


def check_curve_budget(dataset):
    rows = curve_rows(dataset)
    if rows > MAX_CURVE_ROWS:
        raise FieldError("Time", f"The curve sheet would have {rows:,} rows (groups × distinct times × causes); "
                                 f"the limit is {MAX_CURVE_ROWS:,}. Round the times or use fewer causes or groups.")
    return rows


def cumulative_incidence(dataset, cancel=None):
    check_curve_budget(dataset)
    curves = []
    for index, label in enumerate(dataset.groups):
        check_cancel(cancel)
        part = dataset.slice(index)
        curves.append(group_curves(label, dataset.time[part], dataset.code[part], len(dataset.causes)))
    return curves


def estimate_at(curves, cause, query):
    """Right-continuous estimate and variance at ``query`` times; ``beyond`` marks times after the last follow-up."""
    query = np.asarray(query, dtype=float)
    position = np.searchsorted(curves.times, query, side="right") - 1
    seen = position >= 0
    safe = np.maximum(position, 0)
    estimate = np.where(seen, curves.incidence[cause][safe], 0.0)
    variance = np.where(seen, curves.variance[cause][safe], 0.0)
    return estimate, variance, query > curves.times[-1]


def interval(estimate, variance, level):
    """Two-sided Wald limits truncated to [0, 1]; nan where the limits are not defined."""
    z = stats.norm.ppf(1 - (1 - level / 100.0) / 2)
    estimate, variance = np.asarray(estimate, dtype=float), np.asarray(variance, dtype=float)
    usable = (estimate > 0) & (estimate < 1) & (variance > 0) & np.isfinite(variance)
    margin = z * np.sqrt(np.where(usable, variance, 0.0))
    lower = np.where(usable, np.maximum(estimate - margin, 0.0), np.nan)
    upper = np.where(usable, np.minimum(estimate + margin, 1.0), np.nan)
    return lower, upper


# ----- Gray's test -----------------------------------------------------------------------------------------------------

@dataclass
class GrayResult:
    statistic: float | None = None
    df: int | None = None
    p: float | None = None
    reason: str = ""

    @property
    def available(self):
        return self.statistic is not None


def gray_work(dataset, group_sets, n_causes):
    """Planned work, sum over comparisons of G² × U × K, where U counts the distinct times of the comparison."""
    total = 0
    for members in group_sets:
        times = len(np.unique(np.concatenate([dataset.time[dataset.slice(g)] for g in members])))
        total += len(members) ** 2 * times * n_causes
    return total


def pair_sets(n_groups):
    return [(a, b) for a in range(n_groups) for b in range(a + 1, n_groups)]


def check_gray_budget(dataset, pairwise):
    """Refuse a comparison too large for the budget before any allocation, naming the field that fits it back."""
    groups = len(dataset.groups)
    if groups < 2:
        return 0
    sets = [tuple(range(groups))] + (pair_sets(groups) if pairwise else [])
    work = gray_work(dataset, sets, len(dataset.causes))
    if work <= MAX_GRAY_WORK:
        return work
    if pairwise and gray_work(dataset, sets[:1], len(dataset.causes)) <= MAX_GRAY_WORK:
        raise FieldError("Gray tests", f"Pairwise Gray tests need {work:,} units of work; the limit is "
                                       f"{MAX_GRAY_WORK:,}. Use Omnibus only.")
    detail = f"The Gray test needs {work:,} units of work (groups² × distinct times × causes); the limit is {MAX_GRAY_WORK:,}."
    if groups > 4:
        raise FieldError("Group", f"{detail} Compare fewer groups.")
    if len(dataset.causes) > 2:
        raise FieldError("Event codes", f"{detail} Declare fewer causes.")
    raise FieldError("Time", f"{detail} Round the times so that fewer distinct values remain.")


class _Track:
    """Step functions of one group, evaluated at any time without touching the subjects again."""

    def __init__(self, time, code, n_causes):
        self.n, self.times = len(time), time
        failed = code > 0
        self.failure = np.unique(time[failed])
        size = len(self.failure)
        where = np.searchsorted(self.failure, time[failed])
        counts = np.bincount((code[failed] - 1) * size + where, minlength=n_causes * size).reshape(n_causes, size)
        risk = self.n - np.searchsorted(time, self.failure, side="left")
        total = counts.sum(axis=0)
        survival = np.cumprod(1.0 - total / np.maximum(risk, 1)) if size else np.ones(0)
        previous = np.r_[1.0, survival[:-1]] if size else np.ones(0)
        incidence = np.cumsum(previous * counts / np.maximum(risk, 1), axis=1) if size else np.zeros((n_causes, 0))
        self.survival = np.r_[1.0, survival]
        self.incidence = np.hstack([np.zeros((n_causes, 1)), incidence])
        self.total = np.r_[total, 0]
        self.counts = np.hstack([counts, np.zeros((n_causes, 1), dtype=counts.dtype)])

    def at(self, grid, cause):
        left = np.searchsorted(self.failure, grid, side="left")
        right = np.searchsorted(self.failure, grid, side="right")
        failing = right > left
        return {"risk": self.n - np.searchsorted(self.times, grid, side="left"),
                "s_before": self.survival[left], "s_after": self.survival[right],
                "f_before": self.incidence[cause][left],
                "own": np.where(failing, self.counts[cause][left], 0),
                "events": np.where(failing, self.total[left], 0)}


def _blocks(size, width):
    step = max(1, _CHUNK // max(1, width))
    return [slice(start, min(start + step, size)) for start in range(0, size, step)]


def _statistic(tracks, cause, cancel):
    """Score vector and covariance of Gray's test for the given groups, or a reason it cannot be formed."""
    g = len(tracks)
    grid = np.unique(np.concatenate([track.failure for track in tracks]))
    if len(grid) == 0:
        return None, None, None, "No subject has an event."
    fields = [track.at(grid, cause) for track in tracks]
    column = lambda key, dtype=float: np.column_stack([field[key] for field in fields]).astype(dtype)
    risk, s_before, s_after = column("risk"), column("s_before"), column("s_after")
    f_before, own, events = column("f_before"), column("own"), column("events")
    nd1 = own.sum(axis=1)
    if nd1.sum() == 0:
        return None, None, None, "No subject has an event of this cause."
    other = events - own
    nd2 = other.sum(axis=1)
    active = risk > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(active, risk / s_before, 0.0)
        total_h = h.sum(axis=1)
        modified = h * (1 - f_before)
        total_r = modified.sum(axis=1)
        pooled = np.cumsum(nd1 / total_h)
        pooled_before = np.r_[0.0, pooled[:-1]]
        weight = np.where(nd1 > 0, nd1 / (total_h * (1 - pooled_before)), 0.0)
        score = np.sum(own - nd1[:, None] * modified / total_r[:, None], axis=0)[:g - 1]
        alive = s_after > 0
        t4_own = np.where(alive, 1 - (1 - pooled[:, None]) / np.where(alive, s_after, 1), 1.0)
        denominator = total_h[:, None] * s_before - 1
        t5_own = np.where(nd1[:, None] > 1, 1 - (nd1[:, None] - 1) / denominator, 1.0)
        t3_own = np.where(active & (nd1[:, None] > 0),
                          t5_own * s_before * nd1[:, None] / (total_h[:, None] * risk), 0.0)
        t4_other = np.where(alive, (1 - pooled[:, None]) / np.where(alive, s_after, 1), 0.0)
        t5_other = np.where(other > 1, 1 - (other - 1) / (risk - 1), 1.0)
        t3_other = np.where(alive & (other > 0), t5_other * s_before ** 2 * other / risk ** 2, 0.0)
    valid = [score, weight, t4_own, t3_own, t4_other, t3_other, total_h, h]
    if not all(np.isfinite(item).all() for item in valid):
        return None, None, None, "The comparison is not numerically computable (a risk set or survival is degenerate)."
    divisor = np.where(total_h > 0, total_h, 1.0)

    def block_a(block):
        # h_i (H - h_i) / H and -h_i h_j / H: exactly zero whenever a group is out of the risk set.
        a = -h[block, :, None] * h[block, None, :] / divisor[block, None, None]
        a[:, np.arange(g), np.arange(g)] = h[block] * (total_h[block, None] - h[block]) / divisor[block, None]
        return a[:, :g - 1, :]

    def running_blocks():
        """Running sums C_ik(u) of the weighted A matrix; the last carry is the total, by the same additions."""
        carry = np.zeros((g - 1, g))
        for block in _blocks(len(grid), g * g):
            check_cancel(cancel)
            a = block_a(block)
            running = carry + np.cumsum(weight[block, None, None] * a, axis=0)
            carry = running[-1]
            yield block, a, running

    total_c = np.zeros((g - 1, g))
    for _, _, running in running_blocks():
        total_c = running[-1]
    covariance = np.zeros((g - 1, g - 1))
    magnitude = np.zeros(g - 1)
    for block, a, running in running_blocks():
        tail = total_c[None] - running
        own_term = a + t4_own[block, None, :] * tail
        other_term = t4_other[block, None, :] * tail
        for term, scale in ((own_term, t3_own[block]), (other_term, t3_other[block])):
            # The tie correction can be negative in the reference formulas, so the weight is not split into a square root.
            left = term.transpose(0, 2, 1).reshape(-1, g - 1)
            right = (term * scale[:, None, :]).transpose(0, 2, 1).reshape(-1, g - 1)
            covariance += left.T @ right
            magnitude += np.einsum("uik,uk->i", term * term, np.abs(scale))
    return score, covariance, magnitude, ""


def _solve(score, covariance, groups, magnitude=None):
    """Chi-square statistic from a linear solve. Rank is judged on the correlation scale, never by a pseudoinverse.

    ``magnitude`` is the sum of the absolute contributions to each variance: a variance that is only rounding
    noise against it is zero, which makes the comparison singular instead of giving a statistic from noise.
    """
    covariance = (covariance + covariance.T) / 2
    variance = np.diag(covariance)
    magnitude = np.abs(variance) if magnitude is None else magnitude
    if (not np.isfinite(covariance).all() or not np.isfinite(score).all()
            or (variance <= SINGULAR_TOLERANCE * magnitude).any() or (variance <= 0).any()):
        return GrayResult(reason="The covariance matrix is singular: some group carries no information on this cause.")
    scale = np.sqrt(variance)
    scaled = covariance / np.outer(scale, scale)
    values = np.linalg.svd(scaled, compute_uv=False)
    if values[-1] <= SINGULAR_TOLERANCE * values[0]:
        return GrayResult(reason="The covariance matrix is singular (its rank is lower than the number of groups minus 1).")
    try:
        solved = np.linalg.solve(scaled, score / scale)
    except np.linalg.LinAlgError:
        return GrayResult(reason="The covariance matrix could not be solved.")
    statistic = float((score / scale) @ solved)
    if not np.isfinite(statistic) or statistic < 0:
        return GrayResult(reason="The score statistic is not a valid chi-square value.")
    return GrayResult(statistic, groups - 1, float(stats.chi2.sf(statistic, groups - 1)))


def gray_test(dataset, cause, members, tracks=None, cancel=None):
    """Gray's rho = 0 test of one declared cause (index) among the groups in ``members`` (indices)."""
    if len(members) < 2:
        return GrayResult(reason="Gray's test needs at least two groups.")
    check_cancel(cancel)
    n_causes = len(dataset.causes)
    chosen = [tracks[g] if tracks is not None else _Track(
        dataset.time[dataset.slice(g)], dataset.code[dataset.slice(g)], n_causes) for g in members]
    score, covariance, magnitude, reason = _statistic(chosen, cause, cancel)
    if reason:
        return GrayResult(reason=reason)
    return _solve(score, covariance, len(members), magnitude)


def gray_tracks(dataset):
    n_causes = len(dataset.causes)
    return [_Track(dataset.time[dataset.slice(g)], dataset.code[dataset.slice(g)], n_causes)
            for g in range(len(dataset.groups))]


def holm(p_values):
    """Holm adjustment of the available p values only; None stays None. Order is preserved."""
    available = [(p, i) for i, p in enumerate(p_values) if p is not None]
    adjusted = [None] * len(p_values)
    running, m = 0.0, len(available)
    for rank, (p, i) in enumerate(sorted(available)):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[i] = running
    return adjusted
