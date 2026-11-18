"""Row-relative statistics evaluated against each worksheet window."""

import numpy as np
import pandas as pd

ROW_STATISTICS = {"CENTER", "STANDARDIZE", "ZSCORE", "RANK"}


def _centered(values, reference, standardize):
    finite = reference[np.isfinite(reference)]
    if not finite.size:
        return np.full_like(values, np.nan)
    scale = np.max(np.abs(finite))
    exponent = np.frexp(scale)[1]
    sample = np.ldexp(finite, -exponent)
    # At similar magnitudes this subtraction preserves increments even when
    # the physical-scale average is rounded to one of two neighboring values.
    origin = sample[0]
    offsets = sample - origin
    average = offsets.mean()
    with np.errstate(over="ignore", invalid="ignore"):
        offsets_from_mean = np.ldexp(values, -exponent) - origin - average
        if not standardize:
            physical = np.ldexp(offsets_from_mean, exponent)
            # Values outside a filtered reference can be larger than its scale.
            return np.where(np.isfinite(offsets_from_mean), physical, values - np.ldexp(origin + average, exponent))
    deviation = offsets.std(ddof=1) if finite.size > 1 else 0.0
    return offsets_from_mean / deviation if deviation else np.full_like(values, np.nan)


def _rolling_centered(values, window, standardize):
    finite = values[np.isfinite(values)]
    if not finite.size:
        return np.full_like(values, np.nan)
    exponent = np.frexp(np.max(np.abs(finite)))[1]
    scaled = np.ldexp(values, -exponent)
    sample = np.ldexp(finite, -exponent)
    # Shifting improves accuracy for a common baseline. Keep small values
    # distinct if the data cover a large dynamic range.
    origin = sample[0] if (np.min(np.abs(sample)) >= 0.25 and
                           np.all(np.signbit(sample) == np.signbit(sample[0]))) else 0.0
    offsets = scaled - origin
    rolling = pd.Series(offsets).rolling(window)
    means = rolling.mean().to_numpy()
    diff = offsets - means
    if standardize:
        deviations = rolling.std().to_numpy()
        result = np.divide(diff, deviations, out=np.full_like(diff, np.nan), where=deviations > 0)
    else:
        result = np.ldexp(diff, exponent)
    raw_windows = pd.Series(values).rolling(window)
    low, high = raw_windows.min().to_numpy(), raw_windows.max().to_numpy()
    # Recompute windows whose local scale is far below the group's
    # scale, or whose incremental variance cannot represent their range.
    small = (np.frexp(np.maximum(np.abs(low), np.abs(high)))[1] < exponent - 450) & (low != high)
    if standardize:
        scaled_range = np.ldexp(high, -exponent) - np.ldexp(low, -exponent)
        count = rolling.count().to_numpy()
        lower_bound = np.divide(scaled_range, np.sqrt(2 * np.maximum(count - 1, 1)))
        small |= (low != high) & (count > 1) & (
            ~np.isfinite(deviations) | (deviations < lower_bound * 0.99) | (deviations > scaled_range))
    # Constant windows have exactly zero difference and undefined Z scores.
    result[low == high] = np.nan if standardize else 0.0
    if np.any(small):
        starts, stops = window.get_window_bounds(len(values))
        for position in np.flatnonzero(small & np.isfinite(values)):
            result[position] = _centered(values[position:position + 1], values[starts[position]:stops[position]],
                                         standardize)[0]
    result[~np.isfinite(values)] = np.nan
    return result


def _ranks(values, reference):
    sample = np.sort(reference[np.isfinite(reference)])
    result = np.full(len(values), np.nan)
    if sample.size:
        present = np.isfinite(values)
        lower = np.searchsorted(sample, values[present], side="left")
        upper = np.searchsorted(sample, values[present], side="right")
        result[present] = lower + (np.maximum(upper - lower, 1) + 1) / 2
    return result


def _rolling_ranks(values, window):
    present = np.isfinite(values)
    distinct, inverse = np.unique(values[present], return_inverse=True)
    keys = np.zeros(len(values), dtype=np.intp)
    keys[present] = inverse + 1
    keys = keys.tolist()
    counts = [0] * (len(distinct) + 1)
    result = np.full(len(values), np.nan)
    starts, stops = window.get_window_bounds(len(values))

    def adjust(key, amount):
        while 0 < key < len(counts):
            counts[key] += amount
            key += key & -key

    def prefix(key):
        total = 0
        while key:
            total += counts[key]
            key -= key & -key
        return total

    # The Fenwick tree tracks multiplicities as both bounds advance. A query
    # ranks the current row even if the window includes following rows.
    previous_start = previous_stop = 0
    for position, (start, stop) in enumerate(zip(starts.tolist(), stops.tolist(), strict=True)):
        for row in range(previous_start, start):
            adjust(keys[row], -1)
        for row in range(previous_stop, stop):
            adjust(keys[row], 1)
        previous_start, previous_stop = start, stop
        key = keys[position]
        if key:
            lower = prefix(key - 1)
            result[position] = lower + (prefix(key) - lower + 1) / 2
    return result


def row_statistic(name, values, reference, window=None):
    if name == "RANK":
        return _rolling_ranks(values, window) if window is not None else _ranks(values, reference)
    standardize = name != "CENTER"
    if window is not None:
        return _rolling_centered(values, window, standardize)
    return _centered(values, reference, standardize)
