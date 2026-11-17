"""Weighting choices for nonlinear fits: weights from a column, from the observed Y or from the fitted curve.

``Compare nonlinear models`` keeps ``stats.FIT_WEIGHTINGS``. For a residual r = Y - f(X) the observed modes
minimise sum(r² / |Y|) and sum(r² / Y²), i.e. a scale of sqrt(|Y|) and |Y| on the residual, with the Y of each
observation. The fitted modes ``1/abs(Yfit)`` and ``1/Yfit²`` use the same scales from the fitted curve
and iterate (IRLS): an unweighted fit, then at most 50 weighted refits, each with the scales of the previous fit
held fixed. The scales of the last refit are the final frozen weights used for inference and comparisons.
"""
import numpy as np

from .field_error import FieldError

UNWEIGHTED = "Unweighted"
INVERSE_VARIANCE = "Inverse variance (column)"
ONE_OVER_ABS_Y = "1/abs(Y)"
ONE_OVER_Y_SQUARED = "1/Y²"
ONE_OVER_ABS_YFIT = "1/abs(Yfit)"
ONE_OVER_YFIT_SQUARED = "1/Yfit²"
OBSERVED_WEIGHTINGS = (ONE_OVER_ABS_Y, ONE_OVER_Y_SQUARED)
FITTED_WEIGHTINGS = (ONE_OVER_ABS_YFIT, ONE_OVER_YFIT_SQUARED)
# The independent fit and the global fit list the same six choices.
NONLINEAR_WEIGHTINGS = (UNWEIGHTED, INVERSE_VARIANCE, *OBSERVED_WEIGHTINGS, *FITTED_WEIGHTINGS)
GLOBAL_WEIGHTINGS = NONLINEAR_WEIGHTINGS
# Exponent applied to |Y| or |Yfit| to get the residual scale.
_SCALE_POWER = {ONE_OVER_ABS_Y: 0.5, ONE_OVER_Y_SQUARED: 1.0,
                ONE_OVER_ABS_YFIT: 0.5, ONE_OVER_YFIT_SQUARED: 1.0}

# IRLS convention of TramaStat: a completed unweighted fit, then at most this many weighted refits.
MAX_WEIGHT_REFITS = 50
# Relative tolerance on the free parameters (internal solver units, scale at least 1).
PARAMETER_TOLERANCE = 1e-8
# Absolute tolerance on the median-centred log of the scales.
SCALE_TOLERANCE = 1e-8
INFERENCE_WEIGHTS = "Final frozen weights"


def uses_observed_y(weighting):
    return weighting in OBSERVED_WEIGHTINGS


def uses_fitted_y(weighting):
    return weighting in FITTED_WEIGHTINGS


def observed_scales(y, weighting):
    """Residual scales for a weighting from the observed Y of complete observations.

    Raises FieldError on the Weighting field when a response is zero or a scale leaves the numeric range.
    """
    values = np.asarray(y, dtype=float)
    if (values == 0).any():
        raise FieldError("Weighting", f"The {weighting} weighting cannot be used with a Y value of zero. "
                                      "Choose another weighting or exclude that observation.")
    with np.errstate(all="ignore"):
        scales = np.abs(values) ** _SCALE_POWER[weighting]
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise FieldError("Weighting", f"The Y values are outside the numeric range for the {weighting} weighting.")
    return scales


def fitted_scales(fitted, weighting):
    """Residual scales from the values of the fitted curve at the observed X.

    The observed Y can be zero; the fitted value cannot. Raises FieldError on the Weighting field.
    """
    values = np.asarray(fitted, dtype=float)
    if not np.isfinite(values).all():
        raise FieldError("Weighting", f"The fitted curve is outside the numeric range for the {weighting} weighting.")
    if (values == 0).any():
        raise FieldError("Weighting", f"The {weighting} weighting cannot be used when the fitted curve is zero at an "
                                      "observation. Choose another weighting or exclude that observation.")
    with np.errstate(all="ignore"):
        scales = np.abs(values) ** _SCALE_POWER[weighting]
    if not np.isfinite(scales).all() or (scales <= 0).any():
        raise FieldError("Weighting", f"The fitted values are outside the numeric range for the {weighting} weighting.")
    return scales


def _centred_log(scales):
    logs = np.log(scales)
    return logs - np.median(logs)


def iterate_weights(weighting, initial, refit, fitted, free, units):
    """Iteratively reweighted least squares from a completed unweighted fit.

    ``initial`` is the unweighted result. ``refit(result, scales)`` returns a weighted fit with the scales held
    fixed, started at the previous result. ``fitted(result)`` gives the fitted values at every observation and
    ``free(result)`` the free parameters (fixed ones are left out), measured in ``units`` of the solver.
    Returns ``(result, refits, scales)`` where ``scales`` are the frozen scales of the last refit.
    Raises FieldError on the Weighting field when the criteria are not met within MAX_WEIGHT_REFITS refits.
    """
    result = initial
    previous = np.asarray(free(result), dtype=float)
    scales = fitted_scales(fitted(result), weighting)
    units = np.asarray(units, dtype=float)
    for refits in range(1, MAX_WEIGHT_REFITS + 1):
        result = refit(result, scales)
        current = np.asarray(free(result), dtype=float)
        proposed = fitted_scales(fitted(result), weighting)
        parameters = np.abs(current - previous) / units
        parameters_stable = bool(np.all(parameters <= PARAMETER_TOLERANCE * np.maximum(1., np.abs(current) / units)))
        scales_stable = bool(np.all(np.abs(_centred_log(proposed) - _centred_log(scales)) <= SCALE_TOLERANCE))
        if parameters_stable and scales_stable:
            return result, refits, scales
        previous, scales = current, proposed
    raise FieldError("Weighting", f"The {weighting} weighting did not converge within {MAX_WEIGHT_REFITS} weighted "
                                  "refits. Choose another weighting or different starting values.")


# Catalog key of the sentence shown under the Weighting field.
NOTE_KEYS = {UNWEIGHTED: "weighting.note.unweighted", INVERSE_VARIANCE: "weighting.note.inverse_variance",
             ONE_OVER_ABS_Y: "weighting.note.abs_y", ONE_OVER_Y_SQUARED: "weighting.note.y_squared",
             ONE_OVER_ABS_YFIT: "weighting.note.abs_yfit", ONE_OVER_YFIT_SQUARED: "weighting.note.yfit_squared"}
