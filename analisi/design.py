"""Power for balanced study designs and reproducible data simulation."""
from math import isfinite
from operator import index

import numpy as np
import pandas as pd
from statsmodels.stats.power import FTestAnovaPower, TTestIndPower, TTestPower


_POWER_LIMIT = 1_000_000
_SIMULATION_LIMIT = 100_000
_DESIGNS = {
    "one-sample": ("One-sample t test", "Cohen's d", "Observations", 1, TTestPower),
    "paired": ("Paired t test", "Cohen's d_z", "Pairs", 1, TTestPower),
    "independent": ("Equal-size independent t test", "Cohen's d", "Per group", 2, TTestIndPower),
    "anova": ("Balanced one-way ANOVA", "Cohen's f", "Per group", None, FTestAnovaPower),
}


def _number(value, label):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label} must be finite.") from error
    if not isfinite(value):
        raise ValueError(f"{label} must be finite.")
    return value


def _integer(value, label, minimum, maximum):
    message = f"{label} must be an integer from {minimum:,} to {maximum:,}."
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(message)
    try:
        value = index(value)
    except TypeError as error:
        raise ValueError(message) from error
    if not minimum <= value <= maximum:
        raise ValueError(message)
    return value


def _probability(value, label, *, endpoints=False):
    value = _number(value, label)
    if endpoints:
        if not 0 <= value <= 1:
            raise ValueError(f"{label} must be between 0 and 1.")
    elif not 0 < value < 1:
        raise ValueError(f"{label} must be strictly between 0 and 1.")
    return value


def _power_calculator(design, effect_size, alpha, groups):
    if design not in _DESIGNS:
        raise ValueError("Select a supported power analysis design.")
    name, measure, unit, count, model_class = _DESIGNS[design]
    effect_size = _number(effect_size, "Effect size")
    if effect_size <= 0:
        raise ValueError(f"Effect size must be positive ({measure}).")
    alpha = _probability(alpha, "Alpha")
    groups = _integer(groups, "Groups", 2, _POWER_LIMIT) if count is None else count
    model = model_class()

    def calculate(n):
        try:
            if design == "anova":
                achieved = model.power(effect_size, n * groups, alpha, k_groups=groups)
            else:
                achieved = model.power(effect_size, n, alpha)
        except OverflowError as error:
            raise ValueError("Power calculation is outside the supported numeric range.") from error
        if not 0 <= achieved <= 1:
            raise ValueError("Power calculation is outside the supported numeric range.")
        return float(achieved)

    return calculate, {"Design": name, "Effect size": effect_size, "Effect measure": measure,
                       "Alpha": alpha, "N unit": unit, "Groups": groups}


def power(design, effect_size, n, *, alpha=.05, groups=3):
    """Calculate power for a two-sided t test or a balanced one-way F test.

    Use the standardized difference from zero, difference of paired means
    divided by the SD of differences (d_z), pooled-SD standardized difference,
    or Cohen's f for ANOVA, respectively. N is subjects, pairs, or per group.
    """
    n = _integer(n, "Sample size", 2, _POWER_LIMIT)
    calculate, settings = _power_calculator(design, effect_size, alpha, groups)
    return {**settings, "N": n, "Total N": n * settings["Groups"], "Power": calculate(n)}


def sample_size(design, effect_size, *, alpha=.05, target=.80, groups=3):
    """Find the smallest integer N whose achieved power reaches the target."""
    target = _probability(target, "Target power")
    calculate, settings = _power_calculator(design, effect_size, alpha, groups)
    low, high = 1, 2
    achieved = calculate(high)
    while achieved < target:
        if high == _POWER_LIMIT:
            raise ValueError(f"Target power exceeds the sample size limit of {_POWER_LIMIT:,}.")
        low, high = high, min(2 * high, _POWER_LIMIT)
        achieved = calculate(high)
    while high - low > 1:
        middle = (low + high) // 2
        candidate = calculate(middle)
        if candidate >= target:
            high, achieved = middle, candidate
        else:
            low = middle
    return {**settings, "N": high, "Total N": high * settings["Groups"],
            "Target power": target, "Power": achieved}


def simulate(kind, n, *, seed=None, mean=0., sd=1., x_min=0., x_max=1.,
             intercept=0., slope=1., p_a=.5, p_b=.5):
    """Generate a normal column, noisy linear XY series, or 2 × 2 count table.

    XY uses evenly spaced X values and Gaussian Y errors. Contingency tables
    split N between rows, with an extra observation in A when N is odd.
    """
    if kind not in {"normal", "xy", "contingency"}:
        raise ValueError("Select normal, XY or contingency simulation.")
    n = _integer(n, "Sample size", 1 if kind == "normal" else 2, _SIMULATION_LIMIT)
    if seed is not None:
        seed = _integer(seed, "Seed", 0, 2**64 - 1)
    rng = np.random.default_rng(seed)
    if kind == "contingency":
        probabilities = [_probability(p_a, "Group A success probability", endpoints=True),
                         _probability(p_b, "Group B success probability", endpoints=True)]
        counts = np.array([(n + 1) // 2, n // 2])
        successes = rng.binomial(counts, probabilities)
        return pd.DataFrame({"Group": ["A", "B"], "Success": successes, "Failure": counts - successes})

    sd = _number(sd, "SD")
    if sd < 0:
        raise ValueError("SD must be nonnegative.")
    if kind == "normal":
        frame = pd.DataFrame({"Value": rng.normal(_number(mean, "Mean"), sd, n)})
    else:
        x_min, x_max = _number(x_min, "X minimum"), _number(x_max, "X maximum")
        if x_max <= x_min:
            raise ValueError("X maximum must exceed X minimum.")
        slope, intercept = _number(slope, "Slope"), _number(intercept, "Intercept")
        with np.errstate(over="ignore", invalid="ignore"):
            x = np.linspace(x_min, x_max, n)
            y = intercept + slope * x + rng.normal(0, sd, n)
        frame = pd.DataFrame({"X": x, "Y": y})
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Simulated values are outside the supported numeric range.")
    return frame
