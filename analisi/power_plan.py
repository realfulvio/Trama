"""Power and sample size from expected means, SDs and an allocation ratio.

``analisi.design`` keeps the one-call power and sample size functions for a standardized effect. This module
adds the planning layer of the Tools dialog: it validates every active option (naming the field to correct),
turns means and SDs into d, d_z or f, keeps an exact A:B ratio for the independent t test, searches the smallest
sample size on the lattice the design allows and draws a power curve. The numbers are the ones of ``design``
whenever the design is balanced; only an unequal allocation uses the noncentral t formula directly.
"""
from dataclasses import dataclass, field
from math import fsum, gcd, hypot, isfinite, sqrt
import re

import numpy as np
import pandas as pd
from scipy import stats

from . import design
from .data import decimal_comma
from .field_error import FieldError
from .processing import TEXT
from .reporting import Result, _plot, _report

METHOD = "Power and sample size"
GOAL, DESIGN, ALPHA, TARGET, SIZE, GROUPS = ("Goal", "Design", "Alpha", "Target power",
                                             "N (per group, if independent)", "ANOVA groups")
STANDARDIZED_EFFECT = "Standardized effect"
EFFECT_INPUT, MEANS = "Effect input", "Means and SD"
INPUT_MODES = (STANDARDIZED_EFFECT, MEANS)
MEAN_A, MEAN_B, NULL_MEAN, COMMON_SD, GROUP_MEANS = "Mean A", "Mean B", "Null mean", "Common SD", "Group means"
PAIRED_SD_INPUT, DIFFERENCE_SD = "Paired SD input", "Difference SD"
SD_A, SD_B, CORRELATION = "SD A", "SD B", "Pair correlation"
DIRECT_SD, MARGINAL_SD = "SD of differences", "Marginal SDs and correlation"
PAIRED_SD_MODES = (DIRECT_SD, MARGINAL_SD)
ALLOCATION, SHOW_CURVE = "Allocation A:B", "Show power curve"
GOALS = ("Sample size", "Power")
DESIGNS = ("One-sample t", "Paired t", "Independent t", "One-way ANOVA")
CURVE_SHEET = "Power curve"
CURVE_POINTS = 200
MAX_GROUP_SIZE = design._POWER_LIMIT
MAX_RATIO_TERM = 100
MIN_MEAN_GROUPS, MAX_MEAN_GROUPS = 2, 20
NUMBER_FIELDS = (STANDARDIZED_EFFECT, ALPHA, TARGET, SIZE, GROUPS, MEAN_A, MEAN_B, NULL_MEAN, COMMON_SD,
                 GROUP_MEANS, DIFFERENCE_SD, SD_A, SD_B, CORRELATION)

# Dialog defaults. The legacy keys keep their order and values; the new keys are appended where they belong.
OPTIONS = {GOAL: GOALS, DESIGN: DESIGNS, ALPHA: .05, TARGET: .8, SIZE: 30, GROUPS: 3,
           ALLOCATION: TEXT,
           EFFECT_INPUT: INPUT_MODES, STANDARDIZED_EFFECT: .5,
           MEAN_A: 10., NULL_MEAN: 0., MEAN_B: 12., COMMON_SD: 4.,
           GROUP_MEANS: TEXT,
           PAIRED_SD_INPUT: PAIRED_SD_MODES, DIFFERENCE_SD: 4., SD_A: 3., SD_B: 4., CORRELATION: .5,
           SHOW_CURVE: False}
TEXT_DEFAULTS = {ALLOCATION: "1:1", GROUP_MEANS: "12; 13.5; 15; 16"}  # shown by the text fields of OPTIONS
TABS = {"Design": (GOAL, DESIGN, ALPHA, TARGET, SIZE, GROUPS, ALLOCATION),
        "Effect": (EFFECT_INPUT, STANDARDIZED_EFFECT, MEAN_A, NULL_MEAN, MEAN_B, COMMON_SD, GROUP_MEANS,
                   PAIRED_SD_INPUT, DIFFERENCE_SD, SD_A, SD_B, CORRELATION),
        "Curve": (SHOW_CURVE,)}

_KEY = {"One-sample t": "one-sample", "Paired t": "paired", "Independent t": "independent",
        "One-way ANOVA": "anova"}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_RATIO = re.compile(r"\s*([0-9]+)\s*:\s*([0-9]+)\s*")
_LIMIT = f"{MAX_GROUP_SIZE:,}"


def _fail(field, message):
    raise FieldError(field, message)


def _real(value, name, *, label=None):
    """A finite float from a number or from text with a decimal point or comma."""
    label = label or name
    if isinstance(value, (bool, np.bool_)):
        _fail(name, f"{label} must be a number.")
    if isinstance(value, str):
        text = decimal_comma(value.strip())
        if not _NUMBER.fullmatch(text):
            _fail(name, f"{label} must be a number.")
        value = float(text)
    else:
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            _fail(name, f"{label} must be a number.")
    if not isfinite(value):
        _fail(name, f"{label} must be finite.")
    return value


def _whole(value, name, low, high, *, label=None):
    """An int in [low, high] from an int or from integer text. Floats, even 3.0, are not accepted."""
    label = label or name
    message = f"{label} must be a whole number from {low:,} to {high:,}."
    if isinstance(value, (bool, np.bool_)):
        _fail(name, message)
    if isinstance(value, str):
        text = value.strip()
        if not _INTEGER.fullmatch(text):
            _fail(name, message)
        value = int(text)
    elif isinstance(value, (int, np.integer)):
        value = int(value)
    else:
        _fail(name, message)
    if not low <= value <= high:
        _fail(name, message)
    return value


def _probability(value, name):
    value = _real(value, name)
    if not 0 < value < 1:
        _fail(name, f"{name} must be strictly between 0 and 1.")
    return value


def _choice(options, name, allowed, default):
    value = options.get(name, default)
    if value not in allowed:
        _fail(name, f"Choose a valid value for {name}.")
    return value


def _canonical(value):
    """Locale-free text of a float: the shortest round-trip form, without a useless trailing .0."""
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def _scale(*values):
    return max(abs(value) for value in values)


def _ratio_of(numerator, denominator):
    """numerator / denominator, or a ValueError message when the quotient leaves the float range."""
    with np.errstate(all="ignore"):
        quotient = numerator / denominator
    return quotient if isfinite(quotient) else None


def _difference_effect(first, second, sd, *, what):
    """abs(first - second) / sd without intermediate overflow; errors name the zero or unbounded effect."""
    with np.errstate(all="ignore"):
        gap = abs(first - second)
        if isfinite(gap):
            effect = _ratio_of(gap, sd)
        else:  # opposite huge means: scale by the larger one before subtracting
            scale = _scale(first, second)
            share = _ratio_of(scale, sd)  # scale / sd, kept apart so that the two huge means do not overflow
            effect = None if share is None else abs(first / scale - second / scale) * share
    if first == second:
        raise ValueError(f"The effect is zero: {what}.")
    if effect is None or not isfinite(effect):
        raise ValueError("The effect cannot be computed: the means and the SD give a value outside the "
                         "supported numeric range.")
    if effect <= 0:
        raise ValueError("The effect cannot be computed: the difference is too small compared with the SD.")
    return effect


def parse_means(text, name=GROUP_MEANS):
    """Group means from text separated by semicolons or new lines; every item, empty ones too, is checked.

    A comma belongs to the number (13,5), so it never separates items. Returns a list of floats.
    """
    if isinstance(text, (list, tuple, np.ndarray)):
        items = [str(value) if isinstance(value, str) else value for value in text]
    elif isinstance(text, str):
        stripped = text.strip()
        items = re.split(r";|\r\n|\r|\n", stripped) if stripped else []
    else:
        _fail(name, f"{name} must be a list of numbers separated by semicolons or new lines.")
    values = []
    for position, item in enumerate(items, start=1):
        if isinstance(item, str) and not item.strip():
            _fail(name, f"{name}: item {position} is empty. Separate the means with semicolons or new lines.")
        text_item = item.strip() if isinstance(item, str) else item
        try:
            values.append(_real(text_item, name))
        except FieldError as error:
            shown = text_item if isinstance(text_item, str) else repr(text_item)
            kind = "finite" if "finite" in str(error) else "a number"
            _fail(name, f"{name}: item {position} ({shown}) must be {kind}.")
    if not MIN_MEAN_GROUPS <= len(values) <= MAX_MEAN_GROUPS:
        _fail(name, f"{name} must list from {MIN_MEAN_GROUPS} to {MAX_MEAN_GROUPS} means; {len(values)} found.")
    return values


def _population_sd(values):
    """Population SD of the group means, computed on values rescaled to avoid overflow; None when all are equal."""
    if min(values) == max(values):
        return None
    scale = _scale(*values)
    scaled = [value / scale for value in values]
    base = scaled[0]
    shifted = [value - base for value in scaled]
    mean = fsum(shifted) / len(shifted)
    variance = fsum((value - mean) ** 2 for value in shifted) / len(shifted)
    if not variance > 0:
        return None
    return sqrt(variance), scale


def paired_difference_sd(sd_a, sd_b, correlation):
    """SD of the paired difference, sqrt((SD A - SD B)^2 + 2 SD A SD B (1 - rho)), without overflow."""
    scale = max(sd_a, sd_b)
    first, second = sd_a / scale, sd_b / scale
    cross = max(2 * first * second * (1 - correlation), 0.)
    result = hypot(first - second, sqrt(cross)) * scale
    return result


def ratio_text(a, b):
    return f"{a}:{b}"


def parse_allocation(value, name=ALLOCATION):
    """Two whole numbers from 1 to 100 reduced by their greatest common divisor."""
    message = (f"{name} must be two whole numbers from 1 to {MAX_RATIO_TERM}, separated by a colon, "
               f"for example 2:3.")
    if not isinstance(value, str):
        _fail(name, message)
    match = _RATIO.fullmatch(value)
    if not match:
        _fail(name, message)
    a, b = int(match.group(1)), int(match.group(2))
    if not (1 <= a <= MAX_RATIO_TERM and 1 <= b <= MAX_RATIO_TERM):
        _fail(name, message)
    divisor = gcd(a, b)
    return a // divisor, b // divisor


@dataclass
class Plan:
    """Validated request. ``options`` is the canonical form saved in the recipe."""
    options: dict
    key: str
    goal: str
    effect: float
    groups: int
    alpha: float
    target: float | None
    size: int | None
    ratio: tuple
    curve: bool
    summary: bool
    provenance: dict = field(default_factory=dict)

    @property
    def independent(self):
        return self.key == "independent"

    @property
    def unequal(self):
        return self.independent and self.ratio != (1, 1)


def active(options):
    """The option names that matter for this request; the rest never block the calculation."""
    options = options or {}
    mode = options.get(EFFECT_INPUT, STANDARDIZED_EFFECT)
    kind = options.get(DESIGN)
    names = {GOAL, DESIGN, ALPHA, EFFECT_INPUT, SHOW_CURVE}
    names.add(TARGET if options.get(GOAL, GOALS[0]) == "Sample size" else SIZE)
    if mode == MEANS:
        if kind == "One-sample t":
            names |= {MEAN_A, NULL_MEAN, COMMON_SD}
        elif kind == "Paired t":
            names |= {MEAN_A, MEAN_B, PAIRED_SD_INPUT}
            names |= ({DIFFERENCE_SD} if options.get(PAIRED_SD_INPUT, DIRECT_SD) == DIRECT_SD
                      else {SD_A, SD_B, CORRELATION})
        elif kind == "Independent t":
            names |= {MEAN_A, MEAN_B, COMMON_SD}
        elif kind == "One-way ANOVA":
            names |= {GROUP_MEANS, COMMON_SD}
    else:
        names.add(STANDARDIZED_EFFECT)
        if kind == "One-way ANOVA":
            names.add(GROUPS)
    if kind == "Independent t":
        names.add(ALLOCATION)
    return names


def visibility(options):
    """Show/hide map for the dialog, from the current values of its controls."""
    shown = active(options)
    return {name: name in shown for name in (TARGET, SIZE, GROUPS, ALLOCATION, STANDARDIZED_EFFECT, MEAN_A,
                                             NULL_MEAN, MEAN_B, COMMON_SD, GROUP_MEANS, PAIRED_SD_INPUT,
                                             DIFFERENCE_SD, SD_A, SD_B, CORRELATION)}


def _effect_from_means(kind, options, canonical):
    """Effect size and provenance rows for the means-and-SD input."""
    extras = {"Effect source": MEANS}
    if kind == "One-sample t":
        mean = canonical[MEAN_A] = _real(options.get(MEAN_A), MEAN_A)
        null = canonical[NULL_MEAN] = _real(options.get(NULL_MEAN), NULL_MEAN)
        sd = canonical[COMMON_SD] = _positive_sd(options.get(COMMON_SD), COMMON_SD)
        effect = _difference_effect(mean, null, sd, what="Mean A equals the null mean")
        extras.update({MEAN_A: mean, NULL_MEAN: null, COMMON_SD: sd})
        return effect, extras, 1
    if kind == "Paired t":
        mean_a = canonical[MEAN_A] = _real(options.get(MEAN_A), MEAN_A)
        mean_b = canonical[MEAN_B] = _real(options.get(MEAN_B), MEAN_B)
        mode = canonical[PAIRED_SD_INPUT] = _choice(options, PAIRED_SD_INPUT, PAIRED_SD_MODES, DIRECT_SD)
        if mode == DIRECT_SD:
            sd = canonical[DIFFERENCE_SD] = _positive_sd(options.get(DIFFERENCE_SD), DIFFERENCE_SD)
            extras.update({PAIRED_SD_INPUT: mode})
        else:
            sd_a = canonical[SD_A] = _positive_sd(options.get(SD_A), SD_A)
            sd_b = canonical[SD_B] = _positive_sd(options.get(SD_B), SD_B)
            rho = canonical[CORRELATION] = _real(options.get(CORRELATION), CORRELATION)
            if not -1 <= rho <= 1:
                _fail(CORRELATION, f"{CORRELATION} must be between -1 and 1.")
            sd = paired_difference_sd(sd_a, sd_b, rho)
            if not isfinite(sd):
                _fail(SD_A, "The SD of the paired difference is outside the supported numeric range.")
            if not sd > 0:
                _fail(CORRELATION, "The SD of the paired difference is zero: SD A equals SD B and the "
                                   "correlation is 1. Choose a correlation below 1.")
            extras.update({PAIRED_SD_INPUT: mode, SD_A: sd_a, SD_B: sd_b, CORRELATION: rho})
        extras.update({MEAN_A: mean_a, MEAN_B: mean_b, DIFFERENCE_SD: sd})
        effect = _difference_effect(mean_b, mean_a, sd, what="Mean A equals Mean B")
        return effect, extras, 1
    if kind == "Independent t":
        mean_a = canonical[MEAN_A] = _real(options.get(MEAN_A), MEAN_A)
        mean_b = canonical[MEAN_B] = _real(options.get(MEAN_B), MEAN_B)
        sd = canonical[COMMON_SD] = _positive_sd(options.get(COMMON_SD), COMMON_SD)
        effect = _difference_effect(mean_b, mean_a, sd, what="Mean A equals Mean B")
        extras.update({MEAN_A: mean_a, MEAN_B: mean_b, COMMON_SD: sd})
        return effect, extras, 2
    values = parse_means(options.get(GROUP_MEANS))
    canonical[GROUP_MEANS] = "; ".join(_canonical(value) for value in values)
    sd = canonical[COMMON_SD] = _positive_sd(options.get(COMMON_SD), COMMON_SD)
    spread = _population_sd(values)
    if spread is None:
        _fail(GROUP_MEANS, "The group means are all equal, so the effect is zero.")
    population, scale = spread
    effect = _ratio_of(population * scale, sd)
    if effect is None or not isfinite(effect) or effect <= 0:
        _fail(COMMON_SD, "The effect cannot be computed: the means and the SD give a value outside the "
                         "supported numeric range.")
    extras.update({GROUP_MEANS: canonical[GROUP_MEANS], COMMON_SD: sd})
    return effect, extras, len(values)


def _positive_sd(value, name):
    value = _real(value, name)
    if not value > 0:
        _fail(name, f"{name} must be greater than 0.")
    return value


def check_options(options):
    """Validate the active options of a request and return the plan; raises FieldError naming the field."""
    options = dict(options)
    canonical = {}
    goal = canonical[GOAL] = _choice(options, GOAL, GOALS, GOALS[0])
    label = canonical[DESIGN] = _choice(options, DESIGN, DESIGNS, None)
    key = _KEY[label]
    mode = canonical[EFFECT_INPUT] = _choice(options, EFFECT_INPUT, INPUT_MODES, STANDARDIZED_EFFECT)
    provenance = {}
    summary = mode == MEANS
    groups = {"one-sample": 1, "paired": 1, "independent": 2}.get(key)
    if summary:
        try:
            effect, provenance, count = _effect_from_means(label, options, canonical)
        except ValueError as error:
            if isinstance(error, FieldError):
                raise
            _fail(_effect_field(label), str(error))
        groups = count if key == "anova" else groups
    else:
        effect = canonical[STANDARDIZED_EFFECT] = _real(options.get(STANDARDIZED_EFFECT, .5),
                                                        STANDARDIZED_EFFECT, label="Effect size")
        if effect <= 0:
            _fail(STANDARDIZED_EFFECT, f"Effect size must be positive ({design._DESIGNS[key][1]}).")
        if key == "anova":
            groups = canonical[GROUPS] = _whole(options.get(GROUPS, 3), GROUPS, 2, MAX_GROUP_SIZE,
                                                label="Groups")
    alpha = canonical[ALPHA] = _probability(options.get(ALPHA), ALPHA)
    target = size = None
    if goal == "Sample size":
        target = canonical[TARGET] = _probability(options.get(TARGET), TARGET)
    else:
        size = canonical[SIZE] = _whole(options.get(SIZE), SIZE, 2, MAX_GROUP_SIZE, label="Sample size")
    ratio = (1, 1)
    if key == "independent":
        ratio = parse_allocation(options.get(ALLOCATION, "1:1"))
        canonical[ALLOCATION] = ratio_text(*ratio)
        if size is not None and ratio != (1, 1):
            _check_allocated_size(size, ratio)
    curve = options.get(SHOW_CURVE, False)
    if not isinstance(curve, (bool, np.bool_)):
        _fail(SHOW_CURVE, f"Choose a valid value for {SHOW_CURVE}.")
    canonical[SHOW_CURVE] = bool(curve)
    return Plan(canonical, key, goal, effect, groups, alpha, target, size, ratio, bool(curve), summary, provenance)


def _effect_field(label):
    """The first field of the effect: where the focus goes when its numbers cannot be used."""
    if isinstance(label, Plan):
        if not label.summary:
            return STANDARDIZED_EFFECT
        label = {value: name for name, value in _KEY.items()}[label.key]
    return {"One-sample t": MEAN_A, "Paired t": MEAN_A, "Independent t": MEAN_A, "One-way ANOVA": GROUP_MEANS}[label]


def _check_allocated_size(size, ratio):
    a, b = ratio
    if size % a:
        lower, upper = size // a * a, (size // a + 1) * a
        start = f"N must be a multiple of {a} to keep Allocation {a}:{b} exact, for example "
        if lower >= 2 and lower * b // a >= 2:
            _fail(SIZE, f"{start}{lower} or {upper}.")
        _fail(SIZE, f"{start}{upper}.")
    other = size // a * b
    if other < 2:
        smallest = a * -(-2 // b)
        _fail(SIZE, f"Each group needs at least 2 observations: Allocation {a}:{b} gives Group B only {other} "
                    f"with this N. The smallest N is {smallest}.")
    if other > MAX_GROUP_SIZE:
        _fail(SIZE, f"Each group is limited to {_LIMIT} observations: Allocation {a}:{b} gives Group B "
                    f"{other:,} with this N.")


def normalized_options(options, plan):
    """The recipe: the canonical value of every active option, in the dialog order."""
    keep = active({**options, **plan.options})
    ordered = [name for tab in TABS.values() for name in tab] + [GOAL, DESIGN, EFFECT_INPUT]
    return {name: plan.options[name] for name in dict.fromkeys(ordered) if name in keep and name in plan.options}


# ---------------------------------------------------------------------------------------------------------
# Power on the design lattice: index k is a multiplier m for the independent ratio, N otherwise.

def _t_power(delta, df, alpha):
    """Power of a two-sided t test with noncentrality ``delta`` (> 0) and ``df`` degrees of freedom.

    scipy sometimes returns NaN for the lower tail (large noncentrality or an extreme cutoff). That tail is at
    most min(alpha / 2, normal tail beyond -delta), about 1e-13 in the cases where scipy gives up, so it is
    left out and the power is never overstated.
    """
    cutoff = stats.t.isf(alpha / 2, df)
    try:
        with np.errstate(all="ignore"):
            upper = float(stats.nct.sf(cutoff, df, delta))
            lower = float(stats.nct.cdf(-cutoff, df, delta))
            achieved = upper + (lower if isfinite(lower) else 0.0)
    except OverflowError as error:
        raise ValueError("Power calculation is outside the supported numeric range.") from error
    if not 0 <= achieved <= 1:
        raise ValueError("Power calculation is outside the supported numeric range.")
    return achieved


class Lattice:
    """The feasible sample sizes of one request: n = k for balanced designs, (a k, b k) for an A:B ratio."""

    def __init__(self, plan):
        self.plan = plan
        a, b = plan.ratio
        self.a, self.b = (a, b) if plan.independent else (1, 1)
        self.low = max(-(-2 // self.a), -(-2 // self.b)) if plan.independent else 2
        self.high = MAX_GROUP_SIZE // max(self.a, self.b)
        if plan.unequal:
            self._compute = self._unequal_power
        else:
            self._library, _ = design._power_calculator(plan.key, plan.effect, plan.alpha,
                                                        plan.groups if plan.key == "anova" else 3)
            self._compute = self._balanced_power
        self._cache = {}

    def sizes(self, index):
        return self.a * index, self.b * index

    def total(self, index):
        if self.plan.key == "anova":
            return index * self.plan.groups
        a, b = self.sizes(index)
        return a + b if self.plan.independent else a

    def power(self, index):
        if index not in self._cache:
            self._cache[index] = self._compute(index)
        return self._cache[index]

    def _balanced_power(self, index):
        """Library power for the balanced designs; a t test whose noncentral lower tail scipy cannot evaluate
        (large effects) is recomputed with ``_t_power``, which returns the same value wherever both work."""
        try:
            return self._library(index)
        except ValueError:
            if self.plan.key == "anova":
                raise
        if self.plan.key == "independent":
            return _t_power(self.plan.effect * sqrt(index / 2), 2 * index - 2, self.plan.alpha)
        return _t_power(self.plan.effect * sqrt(index), index - 1, self.plan.alpha)

    def _unequal_power(self, index):
        n_a, n_b = self.sizes(index)
        return _t_power(self.plan.effect / sqrt(1 / n_a + 1 / n_b), n_a + n_b - 2, self.plan.alpha)

    def smallest(self, target):
        """Smallest index with power >= target: geometric growth, then bisection, then the predecessor check."""
        low, high = self.low - 1, self.low
        achieved = self.power(high)
        while achieved < target:
            if high >= self.high:
                _fail(TARGET, f"Target power exceeds the sample size limit of {_LIMIT}.")
            low, high = high, min(2 * high, self.high)
            achieved = self.power(high)
        while high - low > 1:
            middle = (low + high) // 2
            candidate = self.power(middle)
            if candidate >= target:
                high, achieved = middle, candidate
            else:
                low = middle
        # The requested predecessor must really miss the target; a rounding wobble would otherwise hide it.
        while high > self.low and self.power(high - 1) >= target:
            high -= 1
            achieved = self.power(high)
        return high, achieved

    def reaching(self, level):
        """First index whose power is at least ``level``, or the last feasible one."""
        high = self.low
        while self.power(high) < level and high < self.high:
            high = min(2 * high, self.high)
        low = max(self.low, high // 2)
        while low < high:
            middle = (low + high) // 2
            if self.power(middle) >= level:
                high = middle
            else:
                low = middle + 1
        return high


def _curve_indices(lattice, chosen, extra):
    """At most CURVE_POINTS distinct ascending indices, always including the chosen one, its predecessor and
    both ends of the shown range."""
    last = min(lattice.high, max(lattice.reaching(.999), chosen + max(1, chosen // 5)))
    first = lattice.low
    required = {first, last, chosen, *extra}
    required = {index for index in required if first <= index <= last}
    if last - first + 1 <= CURVE_POINTS:
        return list(range(first, last + 1))
    spare = CURVE_POINTS - len(required)
    grid = np.unique(np.round(np.geomspace(first, last, spare)).astype(int)) if spare > 0 else np.array([], int)
    points = sorted({*required, *(int(index) for index in grid)})
    while len(points) > CURVE_POINTS:  # rounding can only add points that were already required: trim spares
        for index in points[1:-1]:
            if index not in required:
                points.remove(index)
                break
        else:
            break
    return points


def curve_table(plan, lattice, chosen, extra=()):
    indices = _curve_indices(lattice, chosen, extra)
    rows = []
    for index in indices:
        n_a, n_b = lattice.sizes(index)
        row = {"N": n_a, "Total N": lattice.total(index), "Power": lattice.power(index)}
        if plan.independent:
            row.update({"N A": n_a, "N B": n_b})
        rows.append(row)
    return pd.DataFrame(rows)


def curve_figure(plan, table, result_row):
    figure, axes = _plot("Power curve", "Total N", "Power")
    axes.plot(table["Total N"], table["Power"], color="#2f6f9f", linewidth=2, label="Power")
    axes.axhline(0, color="none")
    if plan.target is not None:
        axes.axhline(plan.target, color="#aa5440", linestyle="--", linewidth=1,
                     label=f"Target power {plan.target:g}")
    axes.plot([result_row["Total N"]], [result_row["Power"]], "o", color="#aa5440", zorder=3,
              label=f"Chosen N = {result_row['Total N']:,} (power {result_row['Power']:.3f})")
    axes.set_ylim(0, 1)
    axes.set_xlim(left=0)
    axes.legend(loc="lower right")
    axes._tramastat_numeric_axes = ("x", "y")
    return figure


# ---------------------------------------------------------------------------------------------------------

_ASSUMPTIONS = {
    "one-sample": "Two-sided one-sample t test.",
    "paired": "Two-sided paired t test on the SD of the differences.",
    "independent": "Two-sided independent t test (Student: common SD in both groups).",
    "anova": "One-way F test with a common SD and balanced groups.",
}


def summary_rows(plan, base):
    """The result sheet: the legacy rows of the balanced calculation, then provenance for the new paths."""
    rows = dict(base)
    if plan.summary or plan.unequal:
        rows["Effect source"] = MEANS if plan.summary else STANDARDIZED_EFFECT
        for name, value in plan.provenance.items():
            if name != "Effect source":
                rows[name] = value
        if plan.independent:
            n_a, n_b = rows["N"], rows["N"] // plan.ratio[0] * plan.ratio[1]
            rows.update({"N A": n_a, "N B": n_b, "Allocation A:B": ratio_text(*plan.ratio)})
        assumptions = _ASSUMPTIONS[plan.key]
        rows["Assumptions"] = assumptions + (f" Fixed allocation {ratio_text(*plan.ratio)}." if plan.unequal else "")
        rows["Power basis"] = "Prospective, from the design inputs"
    return rows


def analysis(options):
    """The dispatcher entry: tables, and the power curve sheet and figure when asked."""
    plan = options if isinstance(options, Plan) else check_options(options)
    try:
        return _analyse(plan)
    except FieldError:
        raise
    except ValueError as error:  # a numeric range failure of the power function belongs to the effect
        _fail(_effect_field(plan), str(error))


def _analyse(plan):
    lattice = Lattice(plan)
    if plan.size is not None:
        chosen = plan.size // lattice.a
        achieved = lattice.power(chosen)
        predecessor = ()
    else:
        chosen, achieved = lattice.smallest(plan.target)
        predecessor = (chosen - 1,) if chosen > lattice.low else ()
    settings = _settings(plan)
    n_a = lattice.sizes(chosen)[0]
    base = {**settings, "N": n_a, "Total N": lattice.total(chosen)}
    if plan.target is not None:
        base["Target power"] = plan.target
    base["Power"] = achieved
    tables = {METHOD: _report(summary_rows(plan, base))}
    figure = None
    if plan.curve:
        table = curve_table(plan, lattice, chosen, predecessor)
        tables[CURVE_SHEET] = table
        figure = curve_figure(plan, table, {"Total N": base["Total N"], "Power": achieved})
    return Result(tables, figure)


def _settings(plan):
    """The leading rows. Balanced designs reuse the legacy ones; a fixed allocation needs its own wording."""
    _, settings = design._power_calculator(plan.key, plan.effect, plan.alpha,
                                           plan.groups if plan.key == "anova" else 3)
    if plan.unequal:
        settings = {**settings, "Design": "Independent t test with a fixed allocation", "N unit": "Group A"}
    return settings
