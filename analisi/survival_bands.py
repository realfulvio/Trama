"""Kaplan–Meier simultaneous bands: conservative log-log Hall–Wellner.

For each curve, N is the number of subjects at the start (after filters and exclusions). At every distinct time
with ``d`` events among ``Y`` at risk, the survival step is ``1 − d/Y`` and the Greenwood factor ``G`` grows by
``d / (Y (Y − d))``. For ``0 < S < 1`` the limits are ``g(z ± w)`` with ``g(z) = exp(−exp(z))``,
``z = log(−log S)`` and ``w = c (1 + N G) / (sqrt(N) |log S|)``; ``c`` is the upper ``alpha`` quantile of the
supremum of the absolute Brownian bridge over the whole interval [0, 1] (``scipy.stats.kstwobign.isf``). That
interval is the package's conservative choice; a narrower one gives a different, smaller constant. The nominal
level refers to the times of **one** curve: the bands of several groups carry no joint coverage claim.

Nothing here refits: the risk sets, events and survival steps are the ones the pointwise Kaplan–Meier already
holds in ``analisi.stats.survival`` (events before censors at tied times). Quantities are fractions.
"""
import numpy as np
import pandas as pd
from scipy import stats

SIMULTANEOUS = "Hall–Wellner simultaneous band"
SHEET = "Simultaneous confidence bands"
LOWER, UPPER = "Simultaneous CI lower", "Simultaneous CI upper"
AVAILABLE, UNAVAILABLE = "Available", "Unavailable"
COLUMNS = ("Group", "Time", "At risk", "Events", "Survival", "Greenwood factor", LOWER, UPPER, "Status", "Reason")

NO_EVENT = "Survival is 1 because no event has occurred yet; the log-log band is not defined."
EXHAUSTED = ("Survival is zero (every subject at risk had the event); "
             "the Greenwood sum is not finite and the log-log band is not defined.")
NOT_FINITE = "The Greenwood sum is not finite; the log-log band is not defined."


def critical_value(level):
    """Upper-tail Kolmogorov quantile of the Brownian bridge supremum for a confidence level in percent."""
    if not np.isfinite(level) or not 0 < level < 100:
        raise ValueError("The confidence level must be between 0 and 100.")
    return float(stats.kstwobign.isf(1 - level / 100))


def _g(values):
    """``exp(−exp(z))`` without overflow warnings: a huge ``z`` gives 0, a very negative one gives 1."""
    with np.errstate(over="ignore", under="ignore"):
        return np.exp(-np.exp(values))


def band_frame(curve, level):
    """Greenwood factor, limits, status and reason for every distinct time of one Kaplan–Meier curve."""
    critical = critical_value(level)
    risk = curve["At risk"].to_numpy(dtype=float)
    events = curve["Events"].to_numpy(dtype=float)
    survival = curve["Survival"].to_numpy(dtype=float)
    initial = risk[0]
    with np.errstate(divide="ignore", invalid="ignore"):
        step = np.where(events == 0, 0., np.where(risk > events, events / (risk * (risk - events)), np.inf))
    greenwood = np.cumsum(step)
    available = (survival > 0) & (survival < 1) & np.isfinite(greenwood)
    lower, upper = np.full(len(curve), np.nan), np.full(len(curve), np.nan)
    if available.any():
        log_survival = np.log(survival[available])
        center = np.log(-log_survival)
        width = critical * (1 + initial * greenwood[available]) / (np.sqrt(initial) * np.abs(log_survival))
        lower[available], upper[available] = _g(center + width), _g(center - width)
    reason = np.where(available, "", np.where(survival == 1, NO_EVENT,
                                              np.where(survival == 0, EXHAUSTED, NOT_FINITE)))
    return pd.DataFrame({
        "Time": curve["Time"].to_numpy(), "At risk": curve["At risk"].to_numpy(), "Events": curve["Events"].to_numpy(),
        "Survival": survival, "Greenwood factor": np.where(np.isfinite(greenwood), greenwood, np.nan),
        LOWER: lower, UPPER: upper, "Status": np.where(available, AVAILABLE, UNAVAILABLE), "Reason": reason})


def join_bands(frames):
    """The canonical sheet from ``{group: band_frame}``: one row per group and distinct time, in dict order."""
    return pd.concat([frame.assign(Group=str(label)) for label, frame in frames.items()],
                     ignore_index=True)[list(COLUMNS)]


def band_sheet(curves, level):
    return join_bands({label: band_frame(curve, level) for label, curve in curves.items()})
