"""Identify outliers in columns of observations: ROUT on a constant model, Grubbs and iterative Grubbs.

Each selected column is screened on its own. Missing and excluded cells are ignored and every result keeps the
1-based row of the worksheet that was analysed. A column that is too short, constant or without a measurable scale
gets a status and does not stop the others. No correction is made across columns.

Grubbs (two-sided)
    ``G = max |y − mean| / SD`` with the sample SD. The critical value is
    ``(n−1)/√n · t/√(n−2+t²)`` with ``t = t_isf(alpha/(2n), n−2)`` and a value is flagged when ``G > G_crit``. The
    single test needs 3 values. The iterative test needs 7 values to start, removes the flagged value, tests again
    and stops at the first value that is not flagged or when fewer than 3 values remain. Alpha applies to each step.
    Equal maxima are resolved by the first source row and reported when the tied value is flagged.

ROUT with a constant model (Motulsky and Brown 2006, rules fixed for TramaStat)
    The location ``mu`` starts at the median. Each iteration takes ``r = y − mu`` and
    ``RSDR = quantile(|r|, .6827) · N/(N−1)`` with linear interpolation, gives each value the Lorentzian weight
    ``1/(1 + (r/RSDR)²)`` and moves ``mu`` to the weighted mean. It converges when the step of ``mu`` is at most
    ``1e-10 · RSDR``, and a final location within 1e-12 of the median (in normalised units) is reported as the
    median itself; after 200 iterations without convergence the column is reported as not converged and nothing
    is flagged. The values are centred on the median and divided by their largest deviation before the fit, so a
    shift or a positive rescaling of the column gives the same flags. A zero RSDR with values that differ means the
    scale is not measurable: nothing is flagged and no estimate is reported.

    The two-sided p of each residual is ``2·t.sf(|r|/RSDR, N−1)``. Residuals are ranked from the smallest p, equal
    |r| forming one block in source order. Only the ``max(1, floor(.30·N))`` most extreme values are candidates and
    a block that crosses that cap is excluded as a whole. The largest k that ends a block and satisfies
    ``p_k < (Q/100)·k/N`` flags the first k values. N is the whole column. ROUT needs 4 values.

Limits: up to 200 variables per run and 100 000 values per column; Grubbs columns are limited to 10 000 values
because the iterative test recomputes the moments after every removal.
"""
from math import floor

import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError, _column
from .reporting import Result

OUTLIERS = "Identify outliers"
ROUT, GRUBBS, ITERATIVE = METHODS = ("ROUT", "Grubbs", "Iterative Grubbs")
VARIABLES, METHOD, Q, ALPHA = "Variables", "Method", "Q (%)", "Alpha"
# Role strings are the ones the workbench uses ("Multiple").
OPTIONS = {VARIABLES: "Multiple", METHOD: METHODS, Q: 1.0, ALPHA: .05}
OUTLIER_SHEET, SUMMARY_SHEET, DATA_SHEET = "Outliers", "Summary", "Processed data"

TESTED, CONSTANT, INSUFFICIENT = "Tested", "Constant", "Insufficient observations"
NO_SCALE, NOT_CONVERGED, TOO_MANY = "Scale not measurable", "Not converged", "Too many observations"

MINIMUM = {ROUT: 4, GRUBBS: 3, ITERATIVE: 7}
MAX_VARIABLES, MAX_VALUES, MAX_GRUBBS_VALUES = 200, 100_000, 10_000
QUANTILE, CAP_FRACTION = .6827, .30
MAX_ITERATIONS, TOLERANCE = 200, 1e-10
TIE = 1e-12

ROUT_COLUMNS = ["Variable", "Source row", "Value", "Step", "Residual", "Residual / RSDR", "p (two-sided)"]
GRUBBS_COLUMNS = ["Variable", "Source row", "Value", "Step", "N", "Mean", "SD", "G", "Critical G"]


def visibility(method):
    """Q applies to ROUT and Alpha to both Grubbs tests."""
    return {Q: method == ROUT, ALPHA: method != ROUT}


def _number(options, name, low, high, message):
    value = options.get(name, OPTIONS[name])
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(name, message)
    value = float(value)
    if not np.isfinite(value) or not low < value < high:
        raise FieldError(name, message)
    return value


def _variables(frame, options):
    names = options.get(VARIABLES)
    if not isinstance(names, (list, tuple)) or not names:
        raise FieldError(VARIABLES, "Select at least one column for Variables.")
    if any(not isinstance(name, str) or name not in frame for name in names) or len(set(names)) != len(names):
        raise FieldError(VARIABLES, "Choose distinct existing columns for Variables.")
    if len(names) > MAX_VARIABLES:
        raise FieldError(VARIABLES, f"Select at most {MAX_VARIABLES} columns for Variables.")
    if not frame.columns.is_unique:
        raise FieldError(VARIABLES, "Worksheet column names must be unique.")
    return list(names)


def check_options(frame, options):
    """Validate the fields before any column is read. Returns (variables, method, threshold)."""
    names = _variables(frame, options)
    method = options.get(METHOD, ROUT)
    if method not in METHODS:
        raise FieldError(METHOD, "Choose ROUT, Grubbs or Iterative Grubbs.")
    if method == ROUT:
        threshold = _number(options, Q, 0, 100, "Q (%) must be a number greater than 0 and less than 100.")
    else:
        threshold = _number(options, ALPHA, 0, 1, "Alpha must be a number greater than 0 and less than 1.")
    return names, method, threshold


def _normalised(values):
    """Values centred on the median and divided by the largest deviation, with the centre and the scale."""
    centre = float(np.median(values))
    spread = float(np.max(np.abs(values - centre)))
    return (values - centre) / spread, centre, spread


def _rsdr(residuals):
    n = len(residuals)
    return float(np.quantile(np.abs(residuals), QUANTILE)) * n / (n - 1)


def _fit(scaled, max_iterations):
    """IRLS on normalised values. Returns (mu, rsdr, iterations, converged); rsdr is 0 when not measurable."""
    mu, iterations = 0.0, 0
    while iterations < max_iterations:
        residuals = scaled - mu
        scale = _rsdr(residuals)
        if scale <= 0:
            return mu, 0.0, iterations, False
        weights = 1 / (1 + (residuals / scale) ** 2)
        updated = float(np.sum(weights * scaled) / np.sum(weights))
        iterations += 1
        step, mu = abs(updated - mu), updated
        if step <= TOLERANCE * scale:
            return mu, _rsdr(scaled - mu), iterations, True
    return mu, _rsdr(scaled - mu), iterations, False


def robust_location(values, max_iterations=MAX_ITERATIONS):
    """Lorentzian IRLS fit of a constant. Returns (location, rsdr, iterations, converged) in the data units.

    ``rsdr`` is 0 when the scale is not measurable. ``values`` must not be constant.
    """
    scaled, centre, spread = _normalised(np.asarray(values, dtype=float))
    mu, scale, iterations, converged = _fit(scaled, max_iterations)
    return centre + spread * mu, spread * scale, iterations, converged


def _blocks(sorted_abs):
    """True where rank k (index k−1) ends a block of equal |r|. Normalised residuals are at most about 1 in size."""
    ends = np.ones(len(sorted_abs), dtype=bool)
    ends[:-1] = sorted_abs[1:] < sorted_abs[:-1] - TIE
    return ends


def rout(values, q, max_iterations=MAX_ITERATIONS):
    """Screen one column with ROUT. Returns (summary fields, flagged positions in source order, per-position stats)."""
    n = len(values)
    scaled, centre, spread = _normalised(np.asarray(values, dtype=float))
    mu, scaled_rsdr, iterations, converged = _fit(scaled, max_iterations)
    if abs(mu) < TIE:
        mu = 0.0  # Rounding noise of a symmetric weighted mean: the location is the median.
    summary = {"Location": centre + spread * mu, "RSDR": spread * scaled_rsdr, "Candidates": max(1, floor(CAP_FRACTION * n)),
               "Iterations": iterations, "Converged": "Yes" if converged else "No"}
    if scaled_rsdr <= 0:
        return {**summary, "Location": np.nan, "RSDR": np.nan, "Converged": "", "Status": NO_SCALE}, [], {}
    if not converged:
        return {**summary, "Status": NOT_CONVERGED}, [], {}
    # Residuals in the normalised units keep the ranking free of the column's offset and magnitude.
    residuals = scaled - mu
    magnitude = np.abs(residuals)
    order = np.argsort(-magnitude, kind="stable")
    ratio = magnitude / scaled_rsdr
    p = 2 * stats.t.sf(ratio, n - 1)
    ends = _blocks(magnitude[order])
    cap = summary["Candidates"]
    flagged = 0
    for k in range(1, cap + 1):
        if ends[k - 1] and p[order[k - 1]] < (q / 100) * k / n:
            flagged = k
    positions = sorted(int(i) for i in order[:flagged])
    details = {i: {"Step": 1, "Residual": residuals[i] * spread, "Residual / RSDR": residuals[i] / scaled_rsdr,
                   "p (two-sided)": p[i]} for i in positions}
    return {**summary, "Status": TESTED}, positions, details


def _grubbs_step(scaled, alpha):
    n = len(scaled)
    mean, sd = scaled.mean(), scaled.std(ddof=1)
    scores = np.abs(scaled - mean) / sd
    best = int(np.argmax(scores))
    tied = np.flatnonzero(scores >= scores[best] * (1 - TIE))
    t = stats.t.isf(alpha / (2 * n), n - 2)
    critical = (n - 1) / np.sqrt(n) * t / np.sqrt(n - 2 + t * t)
    return best, tied, float(scores[best]), float(critical), mean, sd


def grubbs(values, alpha, iterative=False):
    """Screen one column with Grubbs. Returns (summary fields, flagged positions in detection order, stats)."""
    scaled, centre, spread = _normalised(np.asarray(values, dtype=float))
    alive = np.arange(len(scaled))
    flagged, details, notes = [], {}, []
    g = critical = np.nan
    while len(alive) >= 3:
        part = scaled[alive]
        if np.ptp(part) == 0:
            notes.append("Remaining values are constant.")
            break
        best, tied, g, critical, mean, sd = _grubbs_step(part, alpha)
        hit = g > critical
        if hit and len(tied) > 1:
            rows = ", ".join(str(alive[i] + 1) for i in tied)
            notes.append(f"Step {len(flagged) + 1}: equal maxima in rows {rows}; the first source row was taken.")
        if not hit:
            break
        position = int(alive[best])
        flagged.append(position)
        details[position] = {"Step": len(flagged), "N": len(alive), "Mean": centre + spread * mean, "SD": spread * sd,
                             "G": g, "Critical G": critical}
        if not iterative:
            break
        alive = np.delete(alive, best)
    summary = {"Alpha (each step)" if iterative else "Alpha": alpha, "Last G": g, "Last critical G": critical,
               "Note": " ".join(notes), "Status": TESTED}
    return summary, flagged, details


def _column_values(frame, name):
    numbers = _column(frame, name, VARIABLES).to_numpy(dtype=float)
    keep = np.flatnonzero(np.isfinite(numbers))
    return numbers, keep


def identify_outliers(frame, options):
    names, method, threshold = check_options(frame, options)
    columns = {name: _column_values(frame, name) for name in names}
    found, summaries, processed = [], [], frame.copy()
    for name in names:
        numbers, keep = columns[name]
        values = numbers[keep]
        n = len(values)
        limit = MAX_VALUES if method == ROUT else MAX_GRUBBS_VALUES
        if n < MINIMUM[method]:
            status = INSUFFICIENT
        elif n > limit:
            status = TOO_MANY
        elif np.ptp(values) == 0:
            status = CONSTANT
        else:
            status = None
        if status is not None:
            summaries.append({"Variable": name, "N": n, "Flagged": 0, "Status": status})
            continue
        if method == ROUT:
            summary, flagged, details = rout(values, threshold)
        else:
            summary, flagged, details = grubbs(values, threshold, iterative=method == ITERATIVE)
        summaries.append({"Variable": name, "N": n, "Flagged": len(flagged), **summary})
        for position in flagged:
            source = int(keep[position])
            found.append({"Variable": name, "Source row": source + 1, "Value": values[position],
                          **details[position]})
        if flagged:
            rows = keep[flagged]
            cleaned = numbers.copy()
            cleaned[rows] = np.nan
            processed[name] = pd.Series(cleaned, index=frame.index, name=name)
    columns = ROUT_COLUMNS if method == ROUT else GRUBBS_COLUMNS
    table = pd.DataFrame(found, columns=columns)
    table["Source row"] = table["Source row"].astype(int)
    table["Step"] = table["Step"].astype(int)
    summary = pd.DataFrame(summaries)
    first = ["Variable", "N", "Flagged", "Status"]
    summary = summary[first + [c for c in summary.columns if c not in first]]
    summary["Flagged"] = summary["Flagged"].astype(int)
    for name in ("Candidates", "Iterations"):
        if name in summary:
            summary[name] = summary[name].astype("Int64")
    if "Note" in summary:
        summary["Note"] = summary["Note"].fillna("")
    return Result({OUTLIER_SHEET: table, SUMMARY_SHEET: summary, DATA_SHEET: processed})
