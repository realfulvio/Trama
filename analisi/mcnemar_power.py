"""Exact power and sample size for the two-sided conditional McNemar test.

The test conditions on the number of discordant pairs D. Under the planning model, D is
Binomial(N, r) with r = p01 + p10, and the negative-to-positive count among those pairs is
Binomial(D, q) with q = p01 / r when r > 0. For each D the critical value k is the largest
integer below D/2 such that 2 · Pr(Binomial(D, 1/2) ≤ k) ≤ alpha. Alpha is inclusive. If no
such k exists, that D never rejects. Otherwise the conditional power is Pr(B ≤ k) + Pr(B ≥ D − k),
the two tails added separately. Project power is the average of those conditional probabilities
over D. D = 0 contributes nothing.

The sample-size search visits N = 1, 2, 3, … in that order and stops at the first N whose power
reaches the target, or at 5,000 pairs. A later N can have lower power, so the search does not
jump ahead. Normal approximations and the mid-p test are outside this module.

Lachin (1992), Biometrics 48, 613–621, describes the same conditional design. The critical value
is the rejection rule of the exact p already reported for paired proportions.
"""
from dataclasses import dataclass
from math import isfinite
import re
import threading

import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator
from scipy import stats
from scipy.special import gammaln

from .data import decimal_comma
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .reporting import Result, _plot, _report

METHOD = "Power for paired proportions"
GOAL = "Goal"
ALPHA = "Alpha (%)"
TARGET = "Target power"
PAIRS = "Number of pairs"
P01 = "Negative to positive (%)"
P10 = "Positive to negative (%)"
GRAPH = "Graph"
GOALS = ("Sample size", "Power")
SAMPLE_SIZE, POWER_GOAL = GOALS
CURVE_SHEET = "Power curve"
LIMIT = 5000
ERROR_PREFIX = "mcnemar.power.error."

OPTIONS = {GOAL: GOALS, ALPHA: 5., TARGET: .8, PAIRS: 30, P01: 30., P10: 10., GRAPH: False}
NUMBER_FIELDS = (ALPHA, TARGET, PAIRS, P01, P10)
TABS = {"Design": (GOAL, ALPHA, TARGET, PAIRS),
        "Effect": (P01, P10),
        "Curve": (GRAPH,)}

STATUS_MINIMUM = "Minimum N"
STATUS_NOT_REACHED = "Not reached"
STATUS_POWER = "Power"
STATUS_NONE = "No discordance"
STATUS_NULL = "Null effect"
PREVIOUS = "Power at N−1"

NOTE_NONE = ("There is no discordance, so the exact McNemar test never rejects and the power is 0 "
             "at every N.")
NOTE_NULL = ("The two transition probabilities are equal, so this power is the size of the two-sided "
             "exact McNemar test.")
NOTE_NULL_ABOVE = "No number of pairs can reach a target above alpha when the effect is null."
NOTE_NOT_REACHED = ("The target was not reached. The largest calculated power and its N, within the "
                    "pairs limit, are reported.")

_CHUNK = 64
_SNAP = 256
_SUM_TOLERANCE = 1e-12          # a fraction sum this close to 1 is rescaled; a percent sum uses 1e-8
_PERCENT_TOLERANCE = 1e-8
_UNIT_SLOP = 1e-9
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"[+-]?[0-9]+")


class McNemarPowerCancelled(MonteCarloCancelled):
    """The paired-proportion power search was cancelled before a result was confirmed."""


@dataclass(frozen=True)
class Plan:
    """A checked request. Probabilities are fractions; the recipe keeps the typed percents."""

    goal: str
    p01: float
    p10: float
    alpha: float
    target: float | None
    pairs: int | None
    graph: bool
    alpha_percent: float
    p01_percent: float
    p10_percent: float

    @property
    def discordance(self):
        return self.p01 + self.p10

    @property
    def alternative(self):
        r = self.discordance
        return None if r == 0 else self.p01 / r

    @property
    def null_effect(self):
        return self.discordance > 0 and self.p01 == self.p10


@dataclass(frozen=True)
class Scan:
    """Powers at every integer N that was calculated. ``powers[n]`` is the power at n pairs."""

    powers: np.ndarray
    minimum: int | None
    limit: int
    last: int
    max_power: float
    max_n: int


def _fail(field, message):
    raise FieldError(field, message)


def _cancelled(cancel):
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event) or hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    return bool(cancel())


def _check_cancel(cancel):
    if _cancelled(cancel):
        raise McNemarPowerCancelled()


def _engine_number(value, what):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{what} must be a real number.")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{what} must be a real number.") from None
    if not isfinite(value):
        raise ValueError(f"{what} must be finite.")
    return value


def _count(value, what="n"):
    """A Python integer in 1..LIMIT. Bools and floats, including 3.0, are refused."""
    message = f"{what} must be a whole number from 1 to {LIMIT:,}."
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(message)
    if isinstance(value, (int, np.integer)):
        value = int(value)
    else:
        raise ValueError(message)
    if not 1 <= value <= LIMIT:
        raise ValueError(message)
    return value


def _alpha(value):
    value = _engine_number(value, "alpha")
    if not 0 < value < 1:
        raise ValueError("alpha must be strictly between 0 and 1.")
    return value


def _target(value):
    value = _engine_number(value, "target")
    if not 0 < value < 1:
        raise ValueError("target must be strictly between 0 and 1.")
    return value


def _fractions(p01, p10):
    """Transition probabilities in [0, 1]. A sum within 1e-12 above 1 is rescaled; a larger sum is refused."""
    p01 = _engine_number(p01, "p01")
    p10 = _engine_number(p10, "p10")
    if p01 < 0 or p10 < 0 or p01 > 1 or p10 > 1:
        raise ValueError("p01 and p10 must be probabilities from 0 to 1.")
    total = p01 + p10
    if total > 1:
        if total - 1 <= _SUM_TOLERANCE:
            scale = 1 / total
            return p01 * scale, p10 * scale
        raise ValueError("p01 and p10 must be probabilities from 0 to 1 whose sum is at most 1.")
    return p01, p10


def _critical_values(alpha, limit):
    """Yield the critical value and null rejection probability for each D from 1 to limit."""
    numerator, denominator = alpha.as_integer_ratio()
    critical = -1
    cumulative = coefficient = 0
    for discordant in range(1, limit + 1):
        # Pascal's identity advances the cumulative count at the previous critical value.
        cumulative = 2 * cumulative - coefficient
        if critical >= 0:
            coefficient = coefficient * discordant // (discordant - critical)
            next_coefficient = coefficient * (discordant - critical) // (critical + 1)
        else:
            next_coefficient = 1

        # The binomial CDF interlaces for successive D, so the cutoff stays fixed or rises by one.
        # Compare integers to include an exact boundary even when alpha is subnormal.
        half_outcomes = 1 << (discordant - 1)
        if (2 * (critical + 1) < discordant
                and (cumulative + next_coefficient) * denominator <= numerator * half_outcomes):
            critical += 1
            cumulative += next_coefficient
            coefficient = next_coefficient
        yield critical, cumulative / half_outcomes


def _fill_thresholds(k, size, critical_values, start, end):
    for discordant in range(start, end + 1):
        k[discordant], size[discordant] = next(critical_values)


def _thresholds(alpha, limit):
    """k[d] is the largest admissible critical value, or -1. size[d] is 2·F(k) when k exists."""
    k = np.full(limit + 1, -1, dtype=np.int32)
    size = np.zeros(limit + 1)
    _fill_thresholds(k, size, _critical_values(alpha, limit), 1, limit)
    return k, size


def _fill_conditional(cond, k, q, size, start, end):
    """Conditional rejection probability for D = start..end. q of 0 or 1 rejects whenever k exists."""
    if start > end:
        return
    ks = k[start:end + 1]
    if q == 0 or q == 1:
        cond[start:end + 1] = (ks >= 0).astype(float)
        return
    if q == 0.5:
        cond[start:end + 1] = size[start:end + 1]
        return
    ds = np.arange(start, end + 1)
    ok = ks >= 0
    tail = np.zeros(ds.size)
    if np.any(ok):
        left = np.asarray(stats.binom.cdf(ks[ok], ds[ok], q), dtype=np.float64)
        right = np.asarray(stats.binom.sf(ds[ok] - ks[ok] - 1, ds[ok], q), dtype=np.float64)
        both = left + right
        both = np.where(np.isfinite(both), both, 0)
        tail[ok] = np.clip(both, 0, 1)
    cond[start:end + 1] = tail


def _conditional(k, q, size):
    cond = np.zeros(k.size)
    if k.size > 1:
        _fill_conditional(cond, k, q, size, 1, k.size - 1)
    return cond


def _binomial_pmf(n, r):
    """Binomial(n, r) probabilities, scaled from the log so a tiny r does not underflow to a zero sum."""
    d = np.arange(n + 1, dtype=np.float64)
    logp = gammaln(n + 1) - gammaln(d + 1) - gammaln(n - d + 1)
    if r <= 0:
        logp[1:] = -np.inf
    else:
        logp += d * np.log(r)
    if r >= 1:
        logp[:-1] = -np.inf
    else:
        logp += (n - d) * np.log1p(-r)
    finite = np.isfinite(logp)
    if not finite.any():
        raise ValueError("Power calculation is outside the supported numeric range.")
    logp = logp - logp[finite].max()
    pmf = np.exp(logp)
    pmf[~finite] = 0
    total = float(pmf.sum())
    if not isfinite(total) or total <= 0:
        raise ValueError("Power calculation is outside the supported numeric range.")
    pmf /= total
    return pmf


def _unit(power):
    if not isfinite(power):
        raise ValueError("Power calculation is outside the supported numeric range.")
    if power < 0:
        if power > -_UNIT_SLOP:
            return 0.0
        raise ValueError("Power calculation is outside the supported numeric range.")
    if power > 1:
        if power < 1 + _UNIT_SLOP:
            return 1.0
        raise ValueError("Power calculation is outside the supported numeric range.")
    return float(power)


def _power_from(pmf, cond):
    return _unit(float(np.dot(pmf, cond)))


def exact_power(n, p01, p10, alpha=0.05):
    """Power of the exact two-sided McNemar test at ``n`` pairs.

    ``p01``, ``p10`` and ``alpha`` are fractions. ``n`` is an integer from 1 to 5,000.
    """
    n = _count(n)
    p01, p10 = _fractions(p01, p10)
    alpha = _alpha(alpha)
    r = p01 + p10
    if r == 0:
        return 0.0
    k, size = _thresholds(alpha, n)
    cond = _conditional(k, p01 / r, size)
    if r == 1:
        return _unit(float(cond[n]))
    return _power_from(_binomial_pmf(n, r), cond)


def _advance(src, dst, n, r):
    """Write Binomial(n, r) into ``dst`` from Binomial(n − 1, r) in ``src``. Returns the unnormalised sum."""
    one = 1 - r
    dst[0] = one * src[0]
    if n > 1:
        dst[1:n] = one * src[1:n] + r * src[:n - 1]
    dst[n] = r * src[n - 1]
    return float(dst[:n + 1].sum())


def _scan(p01, p10, alpha, max_pairs, target, cancel):
    """Power at N = 1, 2, … until the target is reached or ``max_pairs`` is exhausted.

    Thresholds and conditional probabilities are filled in blocks as N grows, so a search that
    stops at a small N does not build the table out to the limit. Cancellation is checked between
    blocks and between successive N.
    """
    r = p01 + p10
    powers = np.zeros(max_pairs + 1)
    if r == 0:
        last = 1
        return Scan(powers[:last + 1], None, max_pairs, last, 0.0, 1)
    q = p01 / r
    k = np.full(max_pairs + 1, -1, dtype=np.int32)
    size = np.zeros(max_pairs + 1)
    cond = np.zeros(max_pairs + 1)
    critical_values = _critical_values(alpha, max_pairs)
    prepared = 0
    src = np.zeros(max_pairs + 1)
    dst = np.zeros(max_pairs + 1)
    src[0] = 1
    point = r == 1
    minimum = None
    max_power = 0.0
    max_n = 1
    for n in range(1, max_pairs + 1):
        _check_cancel(cancel)
        if n > prepared:
            end = min(max_pairs, max(n, prepared + _CHUNK))
            _fill_thresholds(k, size, critical_values, prepared + 1, end)
            _fill_conditional(cond, k, q, size, prepared + 1, end)
            prepared = end
        if point:
            power = _unit(float(cond[n]))
        else:
            total = _advance(src, dst, n, r)
            if not isfinite(total) or total <= 0 or n % _SNAP == 0:
                dst[:n + 1] = _binomial_pmf(n, r)
            else:
                dst[:n + 1] /= total
            power = _power_from(dst[:n + 1], cond[:n + 1])
            src, dst = dst, src
        powers[n] = power
        if power > max_power:
            max_power = power
            max_n = n
        if target is not None and power >= target:
            minimum = n
            return Scan(powers[:n + 1].copy(), minimum, max_pairs, n, max_power, max_n)
    return Scan(powers.copy(), minimum, max_pairs, max_pairs, max_power, max_n)


def minimum_pairs(p01, p10, target, alpha=0.05, *, max_pairs=LIMIT, cancel=None):
    """Smallest N whose exact power reaches ``target``, or None when none does within ``max_pairs``.

    Probabilities and ``target`` are fractions. The search is increasing in N and stops at the first
    success. Cancellation raises ``McNemarPowerCancelled`` and does not return a candidate N.
    """
    p01, p10 = _fractions(p01, p10)
    alpha = _alpha(alpha)
    target = _target(target)
    max_pairs = _count(max_pairs, "max_pairs")
    if p01 + p10 == 0:
        return None
    return _scan(p01, p10, alpha, max_pairs, target, cancel).minimum


def _dialog_real(value, name):
    if isinstance(value, (bool, np.bool_)):
        _fail(name, f"{name} must be a number.")
    if isinstance(value, str):
        text = decimal_comma(value.strip())
        if not _NUMBER.fullmatch(text):
            _fail(name, f"{name} must be a number.")
        try:
            value = float(text)
        except ValueError:
            _fail(name, f"{name} must be a number.")
    else:
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            _fail(name, f"{name} must be a number.")
    if not isfinite(value):
        _fail(name, f"{name} must be finite.")
    return value


def _percent(value, name, *, strict):
    number = _dialog_real(value, name)
    if strict:
        if not 0 < number < 100:
            _fail(name, f"{name} must be a percentage strictly between 0 and 100.")
    elif not 0 <= number <= 100:
        _fail(name, f"{name} must be a percentage from 0 to 100, including 0 and 100.")
    return number


def _pairs(value):
    message = f"{PAIRS} must be a whole number from 1 to {LIMIT:,}."
    if isinstance(value, (bool, np.bool_)):
        _fail(PAIRS, message)
    if isinstance(value, str):
        text = value.strip()
        if not _INTEGER.fullmatch(text):
            _fail(PAIRS, message)
        value = int(text)
    elif isinstance(value, (int, np.integer)):
        value = int(value)
    else:
        _fail(PAIRS, message)
    if not 1 <= value <= LIMIT:
        _fail(PAIRS, message)
    return value


def canonical(value):
    """Short locale-free text of a dialog number, without a trailing .0."""
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def effect_preview(p01, p10):
    """Percentage-point difference and discordance percent, or None while either entry is not a number."""
    try:
        first = _dialog_real(p01, P01)
        second = _dialog_real(p10, P10)
    except FieldError:
        return None
    return first - second, first + second


def visibility(options):
    """Target power belongs to the sample-size goal; the number of pairs belongs to the power goal."""
    sample = (options or {}).get(GOAL, SAMPLE_SIZE) == SAMPLE_SIZE
    return {TARGET: sample, PAIRS: not sample}


def check_options(options):
    """Validate the active fields and return a plan. A FieldError names the field to correct.

    Percents are checked before they are divided by 100, so 33.3 and 66.7 are accepted. The inactive
    goal field is ignored. r = 0 is a valid design, not an error.
    """
    options = dict(options or {})
    goal = options.get(GOAL, SAMPLE_SIZE)
    if goal not in GOALS:
        _fail(GOAL, "Choose Sample size or Power for Goal.")
    alpha_percent = _percent(options.get(ALPHA, OPTIONS[ALPHA]), ALPHA, strict=True)
    alpha = alpha_percent / 100
    if alpha == 0:
        _fail(ALPHA, f"{ALPHA} is too small to represent.")
    p01_percent = _percent(options.get(P01, OPTIONS[P01]), P01, strict=False)
    p10_percent = _percent(options.get(P10, OPTIONS[P10]), P10, strict=False)
    if p01_percent + p10_percent > 100 + _PERCENT_TOLERANCE:
        _fail(P10, f"{P01} and {P10} add up to more than 100.")
    # Divide after the percent check. A sum that passed 100 by at most the percent tolerance is scaled
    # back to 1 so the fraction rule, which only forgives 1e-12, does not reject 33.3 + 66.7.
    p01, p10 = p01_percent / 100, p10_percent / 100
    total = p01 + p10
    if total > 1:
        p01, p10 = p01 / total, p10 / total
    target = pairs = None
    if goal == SAMPLE_SIZE:
        target = _dialog_real(options.get(TARGET, OPTIONS[TARGET]), TARGET)
        if not 0 < target < 1:
            _fail(TARGET, f"{TARGET} must be strictly between 0 and 1.")
    else:
        pairs = _pairs(options.get(PAIRS, OPTIONS[PAIRS]))
    graph = options.get(GRAPH, False)
    if isinstance(graph, (np.bool_,)):
        graph = bool(graph)
    if not isinstance(graph, bool):
        _fail(GRAPH, f"{GRAPH} must be on or off.")
    return Plan(goal, p01, p10, alpha, target, pairs, graph,
                alpha_percent, p01_percent, p10_percent)


def normalized_options(options):
    """Recipe values in dialog order. The inactive goal field is omitted; percents stay percents."""
    plan = options if isinstance(options, Plan) else check_options(options)
    values = {GOAL: plan.goal, ALPHA: plan.alpha_percent, P01: plan.p01_percent, P10: plan.p10_percent,
              GRAPH: plan.graph}
    if plan.goal == SAMPLE_SIZE:
        values[TARGET] = plan.target
    else:
        values[PAIRS] = plan.pairs
    ordered = [name for names in TABS.values() for name in names]
    return {name: values[name] for name in ordered if name in values}


def _status(plan, scan):
    if plan.discordance == 0:
        return STATUS_NONE
    if plan.null_effect:
        return STATUS_NULL
    if plan.goal == POWER_GOAL:
        return STATUS_POWER
    if scan.minimum is not None:
        return STATUS_MINIMUM
    return STATUS_NOT_REACHED


def _notes(plan, reached):
    notes = []
    if plan.discordance == 0:
        notes.append(NOTE_NONE)
    elif plan.null_effect:
        notes.append(NOTE_NULL)
        if plan.goal == SAMPLE_SIZE and plan.target > plan.alpha:
            notes.append(NOTE_NULL_ABOVE)
    if plan.goal == SAMPLE_SIZE and not reached and plan.discordance > 0:
        notes.append(NOTE_NOT_REACHED)
    return " ".join(notes)


def _flat_zero(plan):
    """Power is identically 0, so the curve does not run the search."""
    last = plan.pairs if plan.goal == POWER_GOAL else LIMIT
    return Scan(np.zeros(last + 1), None, LIMIT, last, 0.0, 1)


def _figure(table, target, chosen, power):
    figure, axes = _plot("Power curve", "N", "Power")
    axes.plot(table["N"], table["Power"], color="#2f6f9f", linewidth=2, label="Power")
    if target is not None:
        axes.axhline(target, color="#aa5440", linestyle="--", linewidth=1, label=f"Target power {target:g}")
    axes.plot([chosen], [power], "o", color="#aa5440", zorder=3, label=f"N = {chosen:,} (power {power:.3f})")
    axes.set_ylim(0, 1)
    axes.set_xlim(left=0)
    axes.xaxis.set_major_locator(MaxNLocator(integer=True))
    axes.legend(loc="best")
    axes._tramastat_numeric_axes = ("x", "y")
    return figure


def _report_rows(plan, scan):
    reached = plan.goal == POWER_GOAL or scan.minimum is not None
    if plan.goal == POWER_GOAL:
        n = plan.pairs
        power = float(scan.powers[n]) if plan.discordance else 0.0
        previous = None
    elif scan.minimum is not None:
        n = scan.minimum
        power = float(scan.powers[n])
        previous = float(scan.powers[n - 1]) if n > 1 else None
    else:
        n = scan.max_n
        power = float(scan.max_power)
        previous = None
    rows = {"Result": _status(plan, scan), "N": n, "Power": power}
    if previous is not None:
        rows[PREVIOUS] = previous
    rows.update({"Alpha": plan.alpha, "Discordance": plan.discordance,
                 "Expected difference": (plan.p01_percent - plan.p10_percent) / 100,
                 "Alternative": plan.alternative,
                 "Negative to positive": plan.p01, "Positive to negative": plan.p10})
    if plan.target is not None:
        rows["Target power"] = plan.target
    if plan.goal == SAMPLE_SIZE and scan.minimum is None:
        rows["Maximum power"] = float(scan.max_power)
        rows["N at maximum"] = scan.max_n
    rows["Pairs limit"] = LIMIT
    note = _notes(plan, reached if plan.discordance else False)
    if note:
        rows["Note"] = note
    return rows, n, power


def analysis(frame, options, cancel=None):
    """The dispatcher entry. The worksheet is ignored: the plan does not read data.

    The sample-size goal searches until the target or the 5,000-pair limit. The power goal calculates
    every integer from 1 through the requested N, which is what the curve draws.
    """
    del frame
    plan = options if isinstance(options, Plan) else check_options(options)
    if plan.discordance == 0:
        scan = _flat_zero(plan)
    elif plan.goal == SAMPLE_SIZE:
        scan = _scan(plan.p01, plan.p10, plan.alpha, LIMIT, plan.target, cancel)
    else:
        scan = _scan(plan.p01, plan.p10, plan.alpha, plan.pairs, None, cancel)
    rows, chosen, _power = _report_rows(plan, scan)
    tables = {METHOD: _report(rows)}
    figure = None
    if plan.graph:
        table = pd.DataFrame({"N": np.arange(1, scan.last + 1, dtype=int),
                              "Power": np.asarray(scan.powers[1:scan.last + 1], dtype=float)})
        tables[CURVE_SHEET] = table
        if plan.goal == POWER_GOAL:
            marker = chosen
        elif scan.minimum is None:
            marker = scan.max_n
        else:
            marker = scan.minimum
        figure = _figure(table, plan.target, marker, float(scan.powers[marker]))
    return Result(tables, figure)
