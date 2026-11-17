"""Pointwise confidence and prediction bands for the Nonlinear regression catalog (0.61).

The bands reuse the Fit that Nonlinear regression has already computed: this module never refits.
``Fit.covariance`` is already multiplied by the residual variance, so the variance of the fitted
curve at X is ``g(X)ᵀ C g(X)`` with ``g = ∂f/∂θ`` and no further SSE/df factor::

    mean:        f(x) ± t · sqrt(g'Cg)
    prediction:  f(x) ± t · sqrt(g'Cg + SSE/df)        (unweighted fits only)

with ``t`` the two-sided Student quantile on the fit's df. Both are pointwise, not simultaneous; the
prediction band is for a single new observation, not for the mean of k replicates.

Weightings: Unweighted allows both bands. The observed-Y and fitted-Y weightings allow the mean band,
conditioned on the covariance and the final frozen weights of the confirmed fit (the weights are not
iterated again). Inverse variance (SD column) is refused, because the SD exists only at the observations.

A band is unavailable, with the fit and its sheets kept, when df ≤ 0, the covariance is missing or not
finite, the gradient cannot be computed on the grid, a free parameter sits on a bound, or the fit is
numerically perfect (SSE ≤ 1e-12 × the centred SST).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .curve_models import MODELS
from .fit_weights import (FITTED_WEIGHTINGS, INFERENCE_WEIGHTS, INVERSE_VARIANCE, OBSERVED_WEIGHTINGS, UNWEIGHTED)
from .processing import FieldError

BAND, LEVEL, DRAWING = "Band", "Confidence level (%)", "Band drawing"
BAND_NONE, BAND_MEAN, BAND_PREDICTION = BANDS = ("None", "Confidence (mean)", "Prediction (new observation)")
FILLED, LINES = DRAWINGS = ("Filled", "Lines")
OPTIONS = {BAND: BANDS, LEVEL: 95.0, DRAWING: DRAWINGS}
BAND_SHEET, STATUS_SHEET = "Band", "Band status"
GID = "band:"
FILL_ALPHA = .15

# Interface captions and choices; recipes keep the English keys and values.
LABEL_KEYS = {BAND: "bands.field.band", LEVEL: "bands.field.level", DRAWING: "bands.field.drawing"}
CHOICE_KEYS = {BAND_NONE: "bands.choice.none", BAND_MEAN: "bands.choice.mean",
               BAND_PREDICTION: "bands.choice.prediction", FILLED: "bands.choice.filled", LINES: "bands.choice.lines"}

COLUMNS = ["X", "Predicted", "SE mean", "Lower", "Upper"]
STATUS_COLUMNS = ["Status", "Reason", BAND, LEVEL, "Inference"]
# Residual SS at or below this fraction of the centred total SS is a numerically perfect fit.
PERFECT_FIT = 1e-12
# A free parameter is on a bound within this fraction of its own size, or of its standard error.
BOUND_RELATIVE, BOUND_SE = 1e-8, 1e-6
# Variance below -NEGATIVE × Σ|gᵢCᵢⱼgⱼ| is an inference failure; smaller negatives are rounding.
NEGATIVE = 1e-10
CENTRAL_STEP, ONE_SIDED_STEP = 6e-6, 1e-4


class BandUnavailable(Exception):
    """The band cannot be built for this group; the message is shown as the Reason."""


@dataclass
class Band:
    table: pd.DataFrame
    ok: bool
    reason: str
    inference: str


def band_settings(options):
    """Return ``(band, level, drawing)`` or ``None`` when the band is off. Raises FieldError on a bad field.

    Level and drawing are read only when a band is requested, so stale or invalid values are ignored
    with Band=None or absent.
    """
    band = options.get(BAND, BAND_NONE) or BAND_NONE
    if band == BAND_NONE:
        return None
    if band not in BANDS:
        raise FieldError(BAND, "Choose None, Confidence (mean) or Prediction (new observation).")
    raw = options.get(LEVEL, 95.0)
    if isinstance(raw, str):
        raw = raw.replace(",", ".").strip()
    try:
        level = float(raw) if not isinstance(raw, (bool, np.bool_)) else np.nan
    except (TypeError, ValueError, OverflowError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise FieldError(LEVEL, "Choose a confidence level strictly between 0 and 100.")
    drawing = options.get(DRAWING, FILLED) or FILLED
    if drawing not in DRAWINGS:
        raise FieldError(DRAWING, "Choose Filled or Lines.")
    weighting = options.get("Weighting", UNWEIGHTED)
    if weighting == INVERSE_VARIANCE:
        raise FieldError(BAND, "A band needs the variance of a future observation, which the SD column does not "
                               "define along the curve. Use Unweighted, or an observed-Y or fitted-Y weighting "
                               "with the mean band.")
    if band == BAND_PREDICTION and weighting != UNWEIGHTED:
        raise FieldError(BAND, "The prediction band is available only for Unweighted fits. Choose the mean band "
                               "or Unweighted.")
    return band, level, drawing


def check_band_options(options):
    """Validate the band fields without fitting. The dialog calls this so errors stay on their field."""
    return band_settings(options)


def _line(x, intercept, slope):
    return np.column_stack([np.ones_like(x), x])


def _decay(x, plateau, span, rate):
    z = np.exp(-rate * x)
    return np.column_stack([np.ones_like(x), z, -span * x * z])


# Derivatives in the model's own parameter order. Everything else uses controlled finite differences.
ANALYTIC = {"Straight line": _line, "One-phase decay": _decay}


def _bounds(model, count):
    """Lower and upper limits per coefficient; a scalar limit applies to all of them."""
    return tuple(np.broadcast_to(np.asarray(bound, dtype=float), (count,)) for bound in MODELS[model].bounds)


def finite_difference_gradient(model, x, theta, se):
    """∂f/∂θ by central differences scaled to each coefficient; one-sided (second order) near a bound.

    X is never perturbed. The step follows max(|θᵢ|, SEᵢ) so coefficients of different size and a
    coefficient equal to zero are both handled. Raises BandUnavailable when no admissible step exists.
    """
    spec = MODELS[model]
    lower, upper = _bounds(model, len(theta))
    x = np.asarray(x, dtype=float)
    theta = np.asarray(theta, dtype=float)
    gradient = np.empty((len(x), len(theta)))
    for i, value in enumerate(theta):
        scale = max(abs(value), se[i] if np.isfinite(se[i]) else 0.)
        if not scale > 0 or not np.isfinite(scale):
            raise BandUnavailable("The gradient cannot be scaled for a coefficient.")
        down, up = value - lower[i], upper[i] - value

        def at(offset):
            shifted = theta.copy()
            shifted[i] = value + offset
            with np.errstate(all="ignore"):
                return np.asarray(spec.equation(x, *shifted), dtype=float)

        step = CENTRAL_STEP * scale
        if min(down, up) > step:
            gradient[:, i] = (at(step) - at(-step)) / (2 * step)
            continue
        room, sign = (up, 1.) if up >= down else (down, -1.)
        step = min(ONE_SIDED_STEP * scale, room / 4)
        if not step > 0:
            raise BandUnavailable("No admissible step for the gradient at a coefficient limit.")
        gradient[:, i] = sign * (-3 * at(0.) + 4 * at(sign * step) - at(sign * 2 * step)) / (2 * step)
    return gradient


def gradient(model, x, theta, se):
    if model in ANALYTIC:
        with np.errstate(all="ignore"):
            return ANALYTIC[model](np.asarray(x, dtype=float), *theta)
    return finite_difference_gradient(model, x, theta, se)


def _on_bound(model, theta, se):
    lower, upper = _bounds(model, len(theta))
    for name, value, low, high, error in zip(MODELS[model].parameters, theta, lower, upper, se):
        for limit in (low, high):
            if not np.isfinite(limit):
                continue
            distance = abs(value - limit)
            if distance <= BOUND_RELATIVE * max(abs(value), abs(limit)) or (np.isfinite(error) and distance <= BOUND_SE * error):
                return name
    return None


def _inference(band, weighting):
    base = "Pointwise confidence band for the mean response" if band == BAND_MEAN \
        else "Pointwise prediction band for one new observation"
    if weighting in FITTED_WEIGHTINGS:
        return f"{base}; {INFERENCE_WEIGHTS.lower()} of the confirmed fit"
    if weighting in OBSERVED_WEIGHTINGS:
        return f"{base}; observed-Y weights of the confirmed fit"
    return base


def _empty():
    return pd.DataFrame(columns=COLUMNS, dtype=float).rename_axis("Point")


def fit_band(fit, model, y, band, level, weighting=UNWEIGHTED):
    """Band of one confirmed Fit on the same X grid as ``fit.curve``. Never raises for a numerical reason."""
    inference = _inference(band, weighting)
    try:
        table = _band_table(fit, model, y, band, level)
    except BandUnavailable as reason:
        return Band(_empty(), False, str(reason), inference)
    return Band(table, True, "", inference)


def _band_table(fit, model, y, band, level):
    df = fit.diagnostics.get("df")
    sse = float(fit.residual_ss)
    covariance = fit.covariance
    if df is None or df <= 0:
        raise BandUnavailable("The fit has no residual degrees of freedom.")
    if covariance is None or not np.isfinite(covariance).all():
        raise BandUnavailable("The parameter covariance is missing or not finite.")
    observed = fit.data[y].to_numpy(dtype=float)
    total = float(((observed - observed.mean())**2).sum())
    if sse == 0 or (total > 0 and sse <= PERFECT_FIT * total):
        raise BandUnavailable("The fit is numerically perfect, so the residual variance is zero.")
    theta = fit.parameters["Estimate"].to_numpy(dtype=float)
    se = fit.parameters["SE"].to_numpy(dtype=float)
    stuck = _on_bound(model, theta, se)
    if stuck:
        raise BandUnavailable(f"The free parameter {stuck} sits on a bound, so its covariance is not reliable.")
    grid, predicted = fit.curve[:, 0], fit.curve[:, 1]
    g = gradient(model, grid, theta, se)
    if g.shape != (len(grid), len(theta)) or not np.isfinite(g).all():
        raise BandUnavailable("The gradient is not finite on the curve grid.")
    terms = (g @ covariance) * g
    variance = terms.sum(axis=1)
    magnitude = ((np.abs(g) @ np.abs(covariance)) * np.abs(g)).sum(axis=1)
    if (variance < -NEGATIVE * magnitude).any():
        raise BandUnavailable("The curve variance is substantially negative: the covariance is not valid.")
    variance = np.maximum(variance, 0.)
    spread = variance + (sse / df if band == BAND_PREDICTION else 0.)
    half = stats.t.ppf((1 + level / 100) / 2, df) * np.sqrt(spread)
    if not (np.isfinite(half).all() and np.isfinite(predicted).all()):
        raise BandUnavailable("The band is not finite on the curve grid.")
    table = pd.DataFrame({"X": grid, "Predicted": predicted, "SE mean": np.sqrt(variance),
                          "Lower": predicted - half, "Upper": predicted + half})
    return table.rename_axis("Point")


def draw_band(axes, table, color, label, drawing):
    """Filled area or two limit lines, below the points and out of the legend, with a stable gid."""
    gid = f"{GID}{label}"
    x, lower, upper = table["X"].to_numpy(), table["Lower"].to_numpy(), table["Upper"].to_numpy()
    if drawing == FILLED:
        axes.fill_between(x, lower, upper, color=color, alpha=FILL_ALPHA, linewidth=0, label="_nolegend_",
                          zorder=.5, gid=gid)
        return
    for edge, side in ((lower, "lower"), (upper, "upper")):
        axes.plot(x, edge, color=color, linestyle="--", linewidth=1., label="_nolegend_", zorder=.5,
                  gid=f"{gid}:{side}")


def band_outputs(fits, model, y, settings, weighting, axes, colors):
    """Draw every available band and return ``(sheets by label, status table)``."""
    band, level, drawing = settings
    sheets, rows = {}, {}
    for label, fit in fits.items():
        result = fit_band(fit, model, y, band, level, weighting)
        sheets[label] = result.table
        rows[label] = {"Status": "OK" if result.ok else "Not available", "Reason": result.reason, BAND: band,
                       LEVEL: level, "Inference": result.inference}
        if result.ok:
            draw_band(axes, result.table, colors[label], label, drawing)
    status = pd.DataFrame.from_dict(rows, orient="index", columns=STATUS_COLUMNS).rename_axis("Group")
    return sheets, status
