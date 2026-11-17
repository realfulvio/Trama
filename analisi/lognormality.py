"""Independent Gaussian/lognormal likelihoods with unit-invariant model weights."""
from math import log, pi

import numpy as np
import pandas as pd
from scipy.special import expit

DISTRIBUTION = "Distribution"
DISTRIBUTIONS = ("Normal", "Lognormal", "Both")
COMPARE = "Compare distributions"
LOG_TESTS = "Lognormality tests"
COMPARISON = "Distribution comparison"
LOG_QQ = "Lognormal Q–Q coordinates"
LOG_SETTINGS = "Lognormal Q–Q settings"


def centered_logs(values):
    """ln(x / max(x)) without losing representable variation near max(x).

    Use log1p for close values, log differences across large dynamic ranges.
    The returned offset is ln(max(x)); tests use centered values because normality
    tests are invariant to a common location shift.
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("Lognormal calculations require finite strictly positive values.")
    anchor = values.max()
    offset = float(np.log(anchor))
    relative = (values-anchor)/anchor
    result = np.log(values)-offset
    near = abs(relative) < .5
    result[near] = np.log1p(relative[near])
    return result, offset


def _log_sd(values):
    """Logarithm of the MLE SD, retaining subnormal representable variation."""
    origin = .5*values.min()+.5*values.max()
    shifted = values-origin
    scale = max(abs(shifted))
    if scale == 0:
        return None
    unit = shifted/scale
    centered = unit-unit.mean()
    variance = np.mean(centered*centered)
    return float(np.log(scale)+.5*np.log(variance)) if variance > 0 else None


def compare_distributions(values):
    """Two estimated parameters per model; model weights are not p/posterior values.

    Both log likelihoods are on the original observation scale (the lognormal
    density includes -sum(log(x))). Their difference is evaluated after analytic
    cancellation of the data-unit offset, rather than subtracting two large logs.
    """
    x = np.asarray(values, dtype=float)
    n = len(x)
    reason = ("At least three finite observations are required." if x.ndim != 1 or n < 3 or not np.isfinite(x).all()
              else "Lognormal distributions require strictly positive observations." if np.any(x <= 0)
              else "All observations are identical; finite maximum-likelihood scales are unavailable." if x.min() == x.max()
              else "")
    columns = ["Distribution", "N", "Location", "Scale", "Log scale", "Parameter units", "Log likelihood", "AIC", "Delta AIC",
               "Relative weight (%)", "Status", "Reason"]
    if reason:
        return pd.DataFrame([{**dict.fromkeys(columns,np.nan),"Distribution":name,"N":n,
                              "Status":"Unavailable","Reason":reason,"Parameter units":""}
                             for name in ("Normal","Lognormal")], columns=columns)
    anchor = x.max()
    q = (x-anchor)/anchor
    logs, offset = centered_logs(x)
    normal_scale, log_scale = _log_sd(q), _log_sd(logs)
    if normal_scale is None or log_scale is None:
        raise ArithmeticError("Representable variation was lost while fitting the distributions.")
    mean_log = float(logs.mean())
    constant = .5*(log(2*pi)+1)
    log_likelihoods = (-n*(constant+offset+normal_scale), -n*(constant+offset+log_scale+mean_log))
    # Unit changes cancel exactly here. Both models estimate two parameters, so
    # the AIC penalty is the same. The normalized likelihood equals AIC weighting.
    difference = n*(mean_log+log_scale-normal_scale)
    weights = (100*expit(difference),100*expit(-difference))
    deltas = (max(0.,-2*difference),max(0.,2*difference))
    locations = (float(anchor+anchor*q.mean()),offset+mean_log)
    scales = (float(anchor*np.exp(normal_scale)),float(np.exp(log_scale)))
    log_scales = (offset+normal_scale,log_scale)
    return pd.DataFrame([{"Distribution":name,"N":n,"Location":locations[i],
                          "Scale":scales[i] if scales[i] > 0 else np.nan,"Log scale":log_scales[i],
                          "Parameter units":"Original observations" if i == 0 else "Natural logarithms",
                          "Log likelihood":log_likelihoods[i],"AIC":4-2*log_likelihoods[i],
                          "Delta AIC":deltas[i],"Relative weight (%)":float(weights[i]),"Status":"Available",
                          "Reason":"Relative support among these two fitted models only; not a p value or probability of truth."
                          + (" The scale has underflow in displayed units; use Log scale." if scales[i] == 0 else "")}
                         for i,name in enumerate(("Normal","Lognormal"))],columns=columns)
