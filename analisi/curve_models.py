"""Equations and starting values for the nonlinear regression catalog."""
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.special import expit, ndtr


@dataclass(frozen=True)
class CurveModel:
    equation: Callable
    parameters: tuple[str, ...]
    initial: Callable
    bounds: tuple
    domain: str | None = None
    log_grid: bool = False
    scale_parameters: bool = True
    required_fixed: tuple[str, ...] = ()
    required_shared: tuple[str, ...] = ()


_POSITIVE = np.finfo(float).tiny


def _normalized_inhibition(x, ic50, slope):
    return 100 * expit(-slope * (np.log(x) - np.log(ic50)))


def _decay(x, plateau, span, rate):
    return plateau + span * np.exp(-rate * x)


def _logistic(x, low, high, midpoint, slope):
    return low + (high - low) * expit((x - midpoint) * slope)


def _hill(x, bottom, top, midpoint, slope):
    log_x = np.full_like(x, -np.inf)
    np.log(x, out=log_x, where=x > 0)
    return bottom + (top - bottom) * expit(slope * (log_x - np.log(midpoint)))


def _stimulation_standard(x, bottom, top, ec50):
    return _hill(x, bottom, top, ec50, 1.)


def _inhibition_standard(x, bottom, top, ic50):
    return _hill(x, bottom, top, ic50, -1.)


def _saturation(x, maximum, midpoint):
    # Calculate the fractional occupancy before multiplying by the response scale.
    return maximum * (x / (midpoint + x))


def _total_binding(x, maximum, midpoint, nonspecific, background):
    return _saturation(x, maximum, midpoint) + nonspecific * x + background


def _association(x, y0, plateau, rate):
    return y0 - (plateau - y0) * np.expm1(-rate * x)


def _growth(x, y0, rate):
    with np.errstate(over="ignore"):
        return np.exp(np.log(y0) + rate * x)


def _gaussian(x, amplitude, mean, sd):
    with np.errstate(over="ignore"):
        return amplitude * np.exp(-.5 * ((x - mean) / sd)**2)


def _decay_initial(x, y):
    plateau = y[np.argmax(x)]
    return plateau, y[np.argmin(x)] - plateau, 1 / np.ptp(x)


def _logistic_initial(x, y):
    return y[np.argmin(x)], y[np.argmax(x)], np.median(x), 4 / np.ptp(x)


def _hill_initial(x, y):
    bottom, top = np.percentile(y, [5, 95])
    return bottom, top, np.median(x[x > 0])


def _saturation_initial(x, y):
    return max(np.max(y), np.ptp(y)), np.median(x[x > 0])


def _binding_initial(x, y):
    x_max = x.max()
    x_min = x.min()
    background = y[np.argmin(x)]
    tail = x >= np.quantile(x, .75)
    tail_slope = (np.polyfit(x[tail] / x_max, y[tail], 1)[0] / x_max
                  if np.ptp(x[tail]) > 0 else 0.)
    span = np.ptp(y)
    midpoint = np.median(x[x > 0])
    nonspecific = np.clip(tail_slope, -span / (x_max - x_min), span / (x_max - x_min))
    maximum = max(np.max(y - background - nonspecific * x), span / 4)
    return maximum, midpoint, nonspecific, background


def _association_initial(x, y):
    return y[np.argmin(x)], y[np.argmax(x)], 1 / np.ptp(x)


def _growth_initial(x, y):
    y_min, y_max = y[np.argmin(x)], y[np.argmax(x)]
    y0 = y_min if y_min > 0 else np.max(np.abs(y)) / 10
    rate = (np.log(y_max) - np.log(y0)) if y_max > y0 else 1.
    return y0, rate / np.ptp(x)


def _gaussian_initial(x, y):
    peak = np.argmax(np.abs(y))
    return y[peak], x[peak], np.ptp(x) / 6


MODELS = {
    "Normalized inhibition": CurveModel(
        _normalized_inhibition, ("IC50", "Hill slope"), lambda x, y: (np.median(x), 1.),
        ((_POSITIVE, -np.inf), np.inf), "positive", log_grid=True, scale_parameters=False),
    "One-phase decay": CurveModel(
        _decay, ("Plateau", "Span", "Rate"), _decay_initial, ((-np.inf, -np.inf, 0.), np.inf),
        "nonnegative", scale_parameters=False),
    "Logistic (4 parameters)": CurveModel(
        _logistic, ("Low", "High", "Midpoint", "Slope"), _logistic_initial,
        ((-np.inf, -np.inf, -np.inf, 0.), np.inf), scale_parameters=False),
    "Stimulation (standard slope)": CurveModel(
        _stimulation_standard, ("Bottom", "Top", "EC50"), _hill_initial,
        ((-np.inf, -np.inf, _POSITIVE), np.inf), "nonnegative", log_grid=True),
    "Stimulation (variable slope)": CurveModel(
        _hill, ("Bottom", "Top", "EC50", "Hill slope"), lambda x, y: (*_hill_initial(x, y), 1.),
        ((-np.inf, -np.inf, _POSITIVE, _POSITIVE), np.inf), "nonnegative", log_grid=True),
    "Inhibition (standard slope)": CurveModel(
        _inhibition_standard, ("Bottom", "Top", "IC50"), _hill_initial,
        ((-np.inf, -np.inf, _POSITIVE), np.inf), "nonnegative", log_grid=True),
    "Inhibition (variable slope)": CurveModel(
        _hill, ("Bottom", "Top", "IC50", "Hill slope"), lambda x, y: (*_hill_initial(x, y), -1.),
        ((-np.inf, -np.inf, _POSITIVE, -np.inf), (np.inf, np.inf, np.inf, -_POSITIVE)),
        "nonnegative", log_grid=True),
    "Michaelis–Menten": CurveModel(
        _saturation, ("Vmax", "Km"), _saturation_initial,
        ((_POSITIVE, _POSITIVE), np.inf), "nonnegative"),
    "One-site specific binding": CurveModel(
        _saturation, ("Bmax", "Kd"), _saturation_initial,
        ((_POSITIVE, _POSITIVE), np.inf), "nonnegative"),
    "One-site total binding": CurveModel(
        _total_binding, ("Bmax", "Kd", "Nonspecific slope", "Background"), _binding_initial,
        ((_POSITIVE, _POSITIVE, -np.inf, -np.inf), np.inf), "nonnegative"),
    "One-phase association": CurveModel(
        _association, ("Y0", "Plateau", "Rate"), _association_initial,
        ((-np.inf, -np.inf, _POSITIVE), np.inf), "nonnegative"),
    "Exponential growth": CurveModel(
        _growth, ("Y0", "Rate"), _growth_initial, ((_POSITIVE, _POSITIVE), np.inf), "nonnegative"),
    "Gaussian": CurveModel(
        _gaussian, ("Amplitude", "Mean", "SD"), _gaussian_initial, ((-np.inf, -np.inf, _POSITIVE), np.inf)),
}

# Each tuple supplies the extra parameters at the null values, all interior to
# the full model's bounds.
NESTED_MODELS = {
    ("Stimulation (standard slope)", "Stimulation (variable slope)"): (1.,),
    ("Inhibition (standard slope)", "Inhibition (variable slope)"): (-1.,),
    ("One-site specific binding", "One-site total binding"): (0., 0.),
}

# Additional scientific curve equations and explicit parameter conventions.
# Saved IDs and parameter names in MODELS above are part of the project format.
def _spec(equation, parameters, initial, *, positive=(), nonnegative=(), limits=None,
          domain=None, log_grid=False, fixed=(), shared=()):
    names = tuple(parameters.split("|"))
    bounds = {name: (_POSITIVE, np.inf) for name in positive}
    bounds.update({name: (0., np.inf) for name in nonnegative})
    bounds.update(limits or {})
    lower, upper = zip(*(bounds.get(name, (-np.inf, np.inf)) for name in names), strict=True)
    return CurveModel(equation, names, initial, (lower, upper), domain, log_grid,
                      required_fixed=fixed, required_shared=shared)


def _poly_initial(x, y, order):
    # Global fits may have very few distinct values within individual series.
    degree = min(order, np.unique(x).size - 1)
    if not degree:
        return (np.mean(y),) + (0.,) * order
    fit = np.polynomial.Polynomial.fit(x, y, degree)
    # A term below the rounding level of the data cannot change the fit. It starts at exactly
    # zero: a 1e-16 start would become the unit of that coefficient and leave the problem singular.
    # The check is repeated after conversion to the power basis, where a true zero intercept
    # can otherwise reappear as a few ulps and scale the Jacobian to zero.
    limit = 1e-12 * np.max(np.abs(y))
    scaled = np.where(np.abs(fit.coef) <= limit, 0., fit.coef)
    coefficients = np.polynomial.Polynomial(scaled, fit.domain, fit.window).convert().coef
    coefficients = np.where(np.abs(coefficients) <= limit, 0., coefficients)
    return tuple(np.pad(coefficients, (0, order + 1 - len(coefficients))))


def _line(x, intercept, slope):
    return intercept + slope * x


def _line_initial(x, y):
    return _poly_initial(x, y, 1)


def _through_origin_initial(x, y):
    scale = np.max(np.abs(x))
    z = x / scale
    return (float((z @ y) / (z @ z) / scale),)


def _segmental(x, intercept, before, after, x0):
    return _line(x, intercept, before) + (after - before) * np.maximum(x - x0, 0.)


def _segmental_initial(x, y):
    midpoint = np.median(x)
    left, right = x <= midpoint, x >= midpoint
    intercept, before = _line_initial(x[left], y[left])
    _, after = _line_initial(x[right], y[right])
    return intercept, before, after, midpoint


def _hinge(x, intercept, before, after, x0, delta):
    offset = x - x0
    with np.errstate(over="ignore"):
        bend = np.maximum(offset, 0.) + delta * np.log1p(np.exp(-np.abs(offset) / delta))
    return intercept + before * offset + (after - before) * bend


def _semilog_y_initial(x, y):
    valid = y > 0
    if np.unique(x[valid]).size >= 2:
        return _line_initial(x[valid], np.log10(y[valid]))
    return np.log10(max(np.max(np.abs(y)), _POSITIVE)), 1 / np.ptp(x)


def _cdf_initial(x, y, top):
    center = x[np.argmin(np.abs(y - top / 2))]
    return center, np.ptp(x) / 4


def _crossing_initial(x, y):
    intercept, slope = _line_initial(x, y)
    xcross = np.median(x)
    return intercept + slope * xcross, xcross, slope


def _crossing(x, ycross, xcross, slope):
    return ycross + slope * (x - xcross)


_LINES = {
    "Straight line": _spec(_line, "Intercept|Slope", _line_initial),
    "Line through origin": _spec(lambda x, slope: slope * x, "Slope", _through_origin_initial),
    "Line through point": _spec(lambda x, slope, x0, y0: slope * (x - x0) + y0,
                                "Slope|X0|Y0", lambda x, y: (_line_initial(x, y)[1], np.median(x), np.median(y)),
                                fixed=("X0", "Y0")),
    "Horizontal line": _spec(lambda x, mean: np.full_like(x, mean), "Mean",
                             lambda x, y: (np.mean(y),)),
    "Semilog line (log X)": _spec(lambda x, a, b: _line(np.log10(x), a, b), "Intercept|Slope",
                                  lambda x, y: _line_initial(np.log10(x), y), domain="positive", log_grid=True),
    "Semilog line (log Y)": _spec(lambda x, a, b: np.power(10., _line(x, a, b)),
                                  "Intercept|Slope", _semilog_y_initial),
    "Log-log line": _spec(lambda x, a, b: np.power(10., _line(np.log10(x), a, b)), "Intercept|Slope",
                          lambda x, y: _semilog_y_initial(np.log10(x), y), domain="positive", log_grid=True),
    "Segmental linear regression": _spec(_segmental, "Intercept|Slope 1|Slope 2|X0", _segmental_initial),
    "Continuous hinge": _spec(_hinge, "Intercept|Slope 1|Slope 2|X0|Delta",
                              lambda x, y: (*_segmental_initial(x, y), np.ptp(x) / 20),
                              positive=("Delta",), fixed=("Delta",)),
    "Two intersecting lines": _spec(_crossing, "Y cross|X cross|Slope", _crossing_initial,
                                   shared=("Y cross", "X cross")),
}


def _polynomial(order, centered):
    names = "|".join(f"B{i}" for i in range(order + 1))
    if centered:
        def evaluate(x, mean, *coefficients):
            return np.polynomial.polynomial.polyval(x - mean, coefficients)

        def initial(x, y):
            mean = np.mean(x)
            return mean, *_poly_initial(x - mean, y, order)

        return _spec(evaluate, f"Mean X|{names}", initial, fixed=("Mean X",))
    return _spec(_polynomial_eval, names, lambda x, y: _poly_initial(x, y, order))


def _polynomial_eval(x, *coefficients):
    return np.polynomial.polynomial.polyval(x, coefficients)


_POLYNOMIALS = {f"{'Centered polynomial' if centered else 'Polynomial'} (order {order})":
                _polynomial(order, centered) for order in range(1, 7) for centered in (False, True)}


def _delayed_decay(x, y0, plateau, rate, x0):
    return _association(np.maximum(x - x0, 0.), y0, plateau, rate)


def _delayed_initial(x, y):
    y0, plateau, rate = _association_initial(x, y)
    return y0, plateau, rate, np.quantile(x, .15)


def _phase_decay(x, y0, plateau, percent_fast, rate_fast, rate_slow):
    fast = percent_fast / 100
    return plateau + (y0 - plateau) * (fast * np.exp(-rate_fast * x) + (1 - fast) * np.exp(-rate_slow * x))


def _three_phase_decay(x, y0, plateau, percent_fast, slow_of_remainder, rate_fast, rate_medium, rate_slow):
    fast = percent_fast / 100
    slow = (1 - fast) * (slow_of_remainder / 100)
    return plateau + (y0 - plateau) * (fast * np.exp(-rate_fast * x) +
                                       (1 - fast - slow) * np.exp(-rate_medium * x) +
                                       slow * np.exp(-rate_slow * x))


def _phase_decay_initial(x, y):
    y0, plateau, rate = _association_initial(x, y)
    return y0, plateau, 50., 8 * rate, rate


def _three_phase_decay_initial(x, y):
    y0, plateau, rate = _association_initial(x, y)
    return y0, plateau, 35., 46., 20 * rate, 4 * rate, .5 * rate


def _two_phase_association(x, y0, span_fast, span_slow, rate_fast, rate_slow):
    return y0 - span_fast * np.expm1(-rate_fast * x) - span_slow * np.expm1(-rate_slow * x)


def _two_phase_association_initial(x, y):
    y0, plateau, rate = _association_initial(x, y)
    span = (plateau - y0) / 2
    return y0, span, span, 8 * rate, rate


_EXPONENTIAL = {
    "Plateau then one-phase decay": _spec(_delayed_decay, "Y0|Plateau|Rate|X0", _delayed_initial,
                                         positive=("Rate",), domain="nonnegative", fixed=("X0",)),
    "Two-phase decay": _spec(_phase_decay, "Y0|Plateau|Percent fast|K fast|K slow", _phase_decay_initial,
                              positive=("K fast", "K slow"), limits={"Percent fast": (0., 100.)},
                              domain="nonnegative"),
    "Three-phase decay": _spec(_three_phase_decay, "Y0|Plateau|Percent fast|Slow % of remainder|K fast|K medium|K slow",
                                _three_phase_decay_initial, positive=("K fast", "K medium", "K slow"),
                                limits={"Percent fast": (0., 100.), "Slow % of remainder": (0., 100.)},
                                domain="nonnegative"),
    "Plateau then one-phase association": _spec(_delayed_decay, "Y0|Plateau|Rate|X0", _delayed_initial,
                                                positive=("Rate",), domain="nonnegative", fixed=("X0",)),
    "Two-phase association": _spec(_two_phase_association, "Y0|Span fast|Span slow|K fast|K slow",
                                    _two_phase_association_initial, positive=("K fast", "K slow"),
                                    domain="nonnegative"),
}


def _growth_plateau_initial(x, y):
    ymax = max(np.max(y), _POSITIVE) * 1.1
    y0 = max(y[np.argmin(x)], ymax * .01)
    return y0, ymax, 3 / np.ptp(x)


def _gompertz(x, y0, ymax, rate):
    return np.exp(np.log(ymax) + (np.log(y0) - np.log(ymax)) * np.exp(-rate * x))


def _logistic_growth(x, y0, ymax, rate):
    return ymax / (1 + (ymax / y0 - 1) * np.exp(-rate * x))


def _beta_growth(x, peak, te, tm_fraction):
    # Fit the fraction Tm/Te to preserve 0 < Tm < Te.
    ratio = x / te
    gap = 1 - tm_fraction
    taper = 1 + (1 - ratio) / gap
    with np.errstate(divide="ignore", over="ignore"):
        log_magnitude = np.log(peak) + np.log(np.abs(taper)) + _log_positive(ratio) / gap
        return np.sign(taper) * np.exp(log_magnitude)


def _beta_growth_initial(x, y):
    peak = max(np.max(y), .1 * np.max(np.abs(y)), _POSITIVE)
    te = max(x[np.argmax(y)], .1 * x.max())
    return peak, te, .5


_GROWTH = {
    "Exponential growth (log population)": _spec(_line, "Log Y0|Rate", _line_initial, domain="nonnegative"),
    "Exponential growth to plateau": MODELS["One-phase association"],
    "Gompertz growth": _spec(_gompertz, "Y0|YM|Rate", _growth_plateau_initial,
                            positive=("Y0", "YM", "Rate"), domain="nonnegative"),
    "Logistic growth": _spec(_logistic_growth, "Y0|YM|Rate", _growth_plateau_initial,
                            positive=("Y0", "YM", "Rate"), domain="nonnegative"),
    "Beta growth and decline": _spec(
        _beta_growth, "Ym|Te|Tm / Te", _beta_growth_initial, positive=("Ym", "Te"),
        limits={"Tm / Te": (_POSITIVE, np.nextafter(1., 0.))}, domain="nonnegative"),
}


def _lorentzian(x, amplitude, center, width):
    with np.errstate(over="ignore"):
        return amplitude / (1 + ((x - center) / width)**2)


def _double_peak(equation):
    def evaluate(x, a1, center1, width1, a2, center2, width2):
        return equation(x, a1, center1, width1) + equation(x, a2, center2, width2)
    return evaluate


def _double_peak_initial(x, y):
    # Split at a trough between peaks, with a quantile fallback for unresolved peaks.
    order = np.argsort(x)
    xx, yy = x[order], y[order]
    strength = np.abs(yy)
    a, b = np.searchsorted(xx, np.quantile(xx, [.2, .8]))
    split = a + np.argmin(strength[a:b]) if b > a else len(xx) // 2
    left = np.argmax(strength[:split + 1])
    right = split + np.argmax(strength[split:])
    if xx[left] == xx[right]:
        left, right = np.searchsorted(xx, np.quantile(xx, [.3, .7]))
    width = np.ptp(xx) / 9
    return yy[left], xx[left], width, yy[right], xx[right], width


def _lognormal(x, a, geomean, geosd):
    logx = np.log(x)
    return a * np.exp(-.5 * ((logx - np.log(geomean)) / np.log(geosd))**2 - logx)


def _lognormal_initial(x, y):
    lx = np.log(x)
    width = np.ptp(lx) / 6
    peak = np.argmax(np.abs(y))
    return y[peak] * x[peak], np.exp(lx[peak] + width**2), np.exp(width)


_DISTRIBUTIONS = {
    "Sum of two Gaussians": _spec(_double_peak(_gaussian), "Amplitude 1|Mean 1|SD 1|Amplitude 2|Mean 2|SD 2",
                                  _double_peak_initial, positive=("SD 1", "SD 2")),
    "Lognormal": _spec(_lognormal, "A|Geometric mean|Geometric SD", _lognormal_initial, positive=("Geometric mean",),
                        limits={"Geometric SD": (np.nextafter(1., np.inf), np.inf)}, domain="positive", log_grid=True),
    "Cumulative Gaussian (percent)": _spec(lambda x, mean, sd: 100 * ndtr((x - mean) / sd), "Mean|SD",
                                           lambda x, y: _cdf_initial(x, y, 100.), positive=("SD",)),
    "Cumulative Gaussian (fraction)": _spec(lambda x, mean, sd: ndtr((x - mean) / sd), "Mean|SD",
                                            lambda x, y: _cdf_initial(x, y, 1.), positive=("SD",)),
    "Cumulative Gaussian (count)": _spec(lambda x, mean, sd, n: n * ndtr((x - mean) / sd), "Mean|SD|N",
                                         lambda x, y: (*_cdf_initial(x, y, np.max(y)), np.max(y)),
                                         positive=("SD", "N"), fixed=("N",)),
    "Lorentzian": _spec(_lorentzian, "Amplitude|Center|Width", _gaussian_initial, positive=("Width",)),
    "Sum of two Lorentzians": _spec(_double_peak(_lorentzian),
                                    "Amplitude 1|Center 1|Width 1|Amplitude 2|Center 2|Width 2",
                                    _double_peak_initial, positive=("Width 1", "Width 2")),
}


def _sine(x, amplitude, wavelength, phase):
    return amplitude * np.sin(2 * np.pi * (x / wavelength) + phase)


def _sine_initial(x, y, *, baseline=False):
    # Coarse least-squares period search also handles uneven sampling. Scan on
    # at most 256 X locations so starting a fit remains bounded on large tables.
    xx, inverse = np.unique(x, return_inverse=True)
    yy = np.bincount(inverse, weights=y) / np.bincount(inverse)
    if len(xx) > 256:
        take = np.linspace(0, len(xx) - 1, 256).astype(int)
        xx, yy = xx[take], yy[take]
    period = np.ptp(xx)
    scaled = (xx - xx[0]) / period
    best = (np.inf, 1., np.array([1., 0., 0.]))
    for frequency in np.linspace(.5, min(16., len(xx) / 2), 80):
        angle = 2 * np.pi * frequency * scaled
        columns = [np.sin(angle), np.cos(angle)]
        if baseline:
            columns.append(np.ones(len(xx)))
        design = np.column_stack(columns)
        coefficients = np.linalg.lstsq(design, yy, rcond=None)[0]
        error = np.linalg.norm(yy - design @ coefficients)
        if error < best[0]:
            best = error, frequency, coefficients
    _, frequency, coefficients = best
    amplitude = np.hypot(*coefficients[:2])
    wavelength = period / frequency
    phase = np.arctan2(coefficients[1], coefficients[0]) - 2 * np.pi * (xx[0] / wavelength)
    return max(amplitude, _POSITIVE), wavelength, np.remainder(phase + np.pi, 2 * np.pi) - np.pi


_WAVES = {
    "Standard sine wave": _spec(_sine, "Amplitude|Wavelength|Phase shift", _sine_initial,
                                 positive=("Amplitude", "Wavelength")),
    "Damped sine wave": _spec(lambda x, a, w, p, k: _sine(x, a, w, p) * np.exp(-k * x),
                               "Amplitude|Wavelength|Phase shift|Rate",
                               lambda x, y: (*_sine_initial(x, y), .2 / np.ptp(x)),
                               positive=("Amplitude", "Wavelength"), nonnegative=("Rate",), domain="nonnegative"),
    "Sine wave with baseline": _spec(lambda x, a, w, p, b: b + _sine(x, a, w, p),
                                      "Amplitude|Wavelength|Phase shift|Baseline",
                                      lambda x, y: (*_sine_initial(x, y, baseline=True), np.mean(y)),
                                      positive=("Amplitude", "Wavelength")),
    "Sinc wave": _spec(lambda x, a, w: a * np.sinc(2 * x / w), "Amplitude|Wavelength",
                        lambda x, y: (y[np.argmin(np.abs(x))], np.ptp(x) / 2),
                        positive=("Wavelength",)),
}


def _linear_quadratic(x, alpha, beta):
    return np.exp(-x * (alpha + beta * x))


def _linear_quadratic_initial(x, y):
    valid = (x > 0) & (y > 0)
    if np.unique(x[valid]).size >= 2:
        intercept, slope = _line_initial(x[valid], -np.log(y[valid]) / x[valid])
        return max(intercept, .01 / x.max()), max(slope, .01 / x.max()**2)
    return .2 / x.max(), .2 / x.max()**2


_OTHER = {
    "Boltzmann sigmoid": _spec(lambda x, low, high, midpoint, dx: _logistic(x, low, high, midpoint, 1 / dx),
                                "Bottom|Top|V50|dV", lambda x, y: (*_logistic_initial(x, y)[:3], np.ptp(x) / 4),
                                positive=("dV",)),
    "Power series": _spec(lambda x, a, b, c, d: a * np.power(x, b) + c * np.power(x, d), "A|B|C|D",
                          lambda x, y: (np.median(y) / 2, .5, np.median(y) / 2, 1.5),
                          domain="positive", log_grid=True),
    "Linear-quadratic cell survival": _spec(_linear_quadratic, "Alpha|Beta", _linear_quadratic_initial,
                                            nonnegative=("Alpha", "Beta"), domain="nonnegative"),
    "Linear-quadratic cell survival (percent)": _spec(
        lambda x, a, b: 100 * _linear_quadratic(x, a, b), "Alpha|Beta",
        lambda x, y: _linear_quadratic_initial(x, y / 100),
        nonnegative=("Alpha", "Beta"), domain="nonnegative"),
}


_LN10 = np.log(10.)


def _log_positive(x):
    result = np.full_like(x, -np.inf)
    return np.log(x, where=x > 0, out=result)


def _dose_variable(log_x, bottom, top, log_midpoint, slope):
    return bottom + (top - bottom) * expit(slope * (log_x - log_midpoint))


def _dose_space(logarithmic):
    if logarithmic:
        return lambda x, mid: _LN10 * (x - mid)
    return lambda x, mid: _log_positive(x) - np.log(mid)


def _dose_models(logarithmic):
    space = _dose_space(logarithmic)
    suffix = ", log10 X" if logarithmic else ""
    prefix = "Log " if logarithmic else ""
    domain = None if logarithmic else "nonnegative"
    options = {"domain": domain, "log_grid": not logarithmic}
    initial = (lambda x, y: (*np.percentile(y, [5, 95]), np.median(x))) if logarithmic else _hill_initial
    def variable(x, bottom, top, mid, hill):
        return _dose_variable(space(x, mid), bottom, top, 0., hill)

    def normalized(x, mid, hill):
        return 100 * expit(hill * space(x, mid))

    catalog = {}
    for action, slope, mid in (("Stimulation", 1., "EC50"), ("Inhibition", -1., "IC50")):
        midpoint = f"{prefix}{mid}"
        positive_mid = () if logarithmic else (midpoint,)
        slope_limits = (_POSITIVE, np.inf) if slope > 0 else (-np.inf, -_POSITIVE)

        def standard(x, bottom, top, mid, hill=slope):
            return variable(x, bottom, top, mid, hill)

        def normalized_standard(x, mid, hill=slope):
            return normalized(x, mid, hill)

        if logarithmic:
            catalog[f"{action} (standard slope{suffix})"] = _spec(
                standard, f"Bottom|Top|{midpoint}", initial, **options)
            catalog[f"{action} (variable slope{suffix})"] = _spec(
                variable, f"Bottom|Top|{midpoint}|Hill slope", lambda x, y, hill=slope: (*initial(x, y), hill),
                limits={"Hill slope": slope_limits}, **options)
        catalog[f"Normalized {action.lower()} (standard slope{suffix})"] = _spec(
            normalized_standard, midpoint, lambda x, y: (initial(x, y)[2],), positive=positive_mid, **options)
        # The earlier normalized inhibition entry exposes the opposite slope
        # convention and excludes zero. Keep its saved ID and offer the signed
        # concentration model as a separate choice.
        catalog[f"Normalized {action.lower()} (variable slope{suffix})"] = _spec(
            normalized, f"{midpoint}|Hill slope", lambda x, y, hill=slope: (initial(x, y)[2], hill),
            positive=positive_mid, limits={"Hill slope": slope_limits}, **options)

    def asymmetric(x, bottom, top, mid, slope, symmetry):
        # log(expm1(z)) for z > 0, including the large-z limit.
        z = np.log(2.) / symmetry
        with np.errstate(over="ignore", under="ignore", divide="ignore"):
            adjustment = z + np.log(-np.expm1(-z))
            fraction = np.exp(-symmetry * np.logaddexp(0., adjustment - slope * space(x, mid)))
        return bottom + (top - bottom) * fraction

    def asym_initial(x, y):
        bottom, top, midpoint = initial(x, y)
        slope = 1. if y[np.argmax(x)] >= y[np.argmin(x)] else -1.
        return bottom, top, midpoint, slope, 1.

    def initial_midpoints(x):
        values = x if logarithmic else x[x > 0]
        return tuple(np.quantile(values, [.3, .7]))

    def biphasic(x, bottom, top, mid1, mid2, slope1, slope2, fraction):
        occupied = fraction * expit(slope1 * space(x, mid1)) + (1 - fraction) * expit(slope2 * space(x, mid2))
        return bottom + (top - bottom) * occupied

    def biphasic_initial(x, y):
        low, high, _ = initial(x, y)
        sign = 1. if y[np.argmax(x)] >= y[np.argmin(x)] else -1.
        return low, high, *initial_midpoints(x), sign, sign, .5

    def bell(x, plateau1, dip, plateau2, mid1, mid2, slope1, slope2):
        return dip + (plateau1 - dip) * expit(slope1 * space(x, mid1)) + (
            plateau2 - dip) * expit(-slope2 * space(x, mid2))

    def bell_initial(x, y):
        left, right = y[np.argmin(x)], y[np.argmax(x)]
        lower, upper = np.quantile(x, [.35, .65])
        inside = (x >= lower) & (x <= upper)
        center = np.median(y[inside]) if inside.any() else np.median(y)
        return right, center, left, *initial_midpoints(x), 1., 1.

    def ec_anything(x, bottom, top, ecf, slope, fraction):
        offset = np.log(fraction) - np.log(100 - fraction)
        return bottom + (top - bottom) * expit(slope * space(x, ecf) + offset)

    def schild(x, bottom, top, mid, slope, pa2, schild_slope, antagonist):
        with np.errstate(divide="ignore"):
            shift = np.logaddexp(0., schild_slope * (np.log(antagonist) + _LN10 * pa2))
        return bottom + (top - bottom) * expit(slope * (space(x, mid) - shift))

    def allosteric(x, bottom, top, mid, slope, kb, alpha, antagonist):
        with np.errstate(divide="ignore"):
            log_ratio = np.log(antagonist) - (_LN10 * kb if logarithmic else np.log(kb))
            log_alpha = _LN10 * alpha if logarithmic else np.log(alpha)
        shift = np.logaddexp(0., log_ratio) - np.logaddexp(0., log_ratio + log_alpha)
        return bottom + (top - bottom) * expit(slope * (space(x, mid) - shift))

    def operational(x, basal, effectmax, ka, tau, slope):
        log_ratio = np.logaddexp(0., -space(x, ka))
        log_tau = tau * _LN10 if logarithmic else np.log(tau)
        return basal + (effectmax - basal) * expit(slope * (log_tau - log_ratio))

    def operational_initial(x, y):
        low, high, mid = initial(x, y)
        return low, high + .2 * (high - low), mid, 0. if logarithmic else 1., 1.

    def absolute_ic50(x, top_excess, bottom_gap, ic50, steepness, baseline):
        # Gaps keep the midpoint between the curve's asymptotes throughout
        # optimization. The midpoint is relative to the control baseline.
        top_gap = top_excess / 2
        bottom = baseline + top_gap - bottom_gap
        log_odds = np.log(bottom_gap) - np.log(top_gap)
        return bottom + (top_gap + bottom_gap) * expit(log_odds - steepness * space(x, ic50))

    def absolute_ic50_initial(x, y):
        bottom, top, midpoint = initial(x, y)
        span = max(top - bottom, _POSITIVE)
        return span, span / 2, midpoint, 1., bottom

    qualifier = " (log10 X)" if logarithmic else " (concentration X)"
    ec = f"{prefix}EC50"
    ec1, ec2 = f"{ec} 1", f"{ec} 2"
    ka, tau = f"{prefix}KA", f"{prefix}Tau"
    kb, alpha = f"{prefix}KB", f"{prefix}Alpha"
    absolute = f"{prefix}Absolute IC50"
    ec_positive = () if logarithmic else (ec,)
    pair_positive = () if logarithmic else (ec1, ec2)
    catalog.update({
        f"Asymmetric dose-response{qualifier}": _spec(asymmetric, f"Bottom|Top|{ec}|Hill slope|Asymmetry",
                                                       asym_initial, positive=(*ec_positive, "Asymmetry"), **options),
        f"Biphasic dose-response{qualifier}": _spec(biphasic, f"Bottom|Top|{ec1}|{ec2}|Hill slope 1|Hill slope 2|Fraction",
                                                    biphasic_initial, positive=pair_positive,
                                                    limits={"Fraction": (0., 1.)}, **options),
        f"Bell-shaped dose-response{qualifier}": _spec(
            bell, f"Plateau 1|Dip|Plateau 2|{ec1}|{ec2}|Hill slope 1|Hill slope 2",
            bell_initial, positive=(*pair_positive, "Hill slope 1", "Hill slope 2"), **options),
        f"ECanything{qualifier}": _spec(ec_anything, f"Bottom|Top|{prefix}ECF|Hill slope|F",
                                        lambda x, y: (*asym_initial(x, y)[:4], 50.),
                                        positive=() if logarithmic else ("ECF",),
                                        limits={"F": (_POSITIVE, np.nextafter(100., 0.))}, fixed=("F",), **options),
        f"Gaddum/Schild EC50 shift{qualifier}": _spec(schild, f"Bottom|Top|{ec}|Hill slope|pA2|Schild slope|B",
                                                       lambda x, y: (*initial(x, y), 1., 8., 1., 1e-8),
                                                       positive=(*ec_positive, "Hill slope", "Schild slope"),
                                                       nonnegative=("B",), fixed=("B",), **options),
        f"Allosteric EC50 shift{qualifier}": _spec(
            allosteric, f"Bottom|Top|{ec}|Hill slope|{kb}|{alpha}|B",
            lambda x, y: (*initial(x, y), 1., -8. if logarithmic else 1e-8, -1. if logarithmic else .1, 1e-8),
            positive=("Hill slope",) if logarithmic else (*ec_positive, "Hill slope", kb, alpha),
            nonnegative=("B",), fixed=("B",), **options),
        f"Operational model (depletion){qualifier}": _spec(
            operational, f"Basal|Effect max|{ka}|{tau}|Transducer slope", operational_initial,
            positive=("Transducer slope",) if logarithmic else (ka, tau, "Transducer slope"), **options),
        f"Absolute IC50{qualifier}": _spec(
            absolute_ic50, f"Top above baseline|Half-response above bottom|{absolute}|Hill steepness|Baseline",
            absolute_ic50_initial, fixed=("Baseline",),
            positive=("Top above baseline", "Half-response above bottom", "Hill steepness") +
                     (() if logarithmic else (absolute,)), **options),
    })
    return catalog


_CONCENTRATION_DOSE = _dose_models(False)
_LOG_DOSE = _dose_models(True)


def _occupancy(x, midpoint, slope):
    return expit(slope * (_log_positive(x) - np.log(midpoint)))


def _two_site(x, bmax1, kd1, bmax2, kd2):
    return _saturation(x, bmax1, kd1) + _saturation(x, bmax2, kd2)


def _two_site_initial(x, y):
    maximum, midpoint = _saturation_initial(x, y)
    return maximum / 2, midpoint / 5, maximum / 2, midpoint * 5


def _two_site_total_initial(x, y):
    maximum, midpoint, slope, background = _binding_initial(x, y)
    return maximum / 2, midpoint / 5, maximum / 2, midpoint * 5, slope, background


def _allosteric_midpoint(kd, modulator, kb, log_alpha):
    with np.errstate(divide="ignore"):
        log_ratio = np.log(modulator) - kb
    shift = np.logaddexp(0., log_ratio) - np.logaddexp(0., log_ratio + log_alpha)
    return np.log(kd) + shift


def _allosteric_binding(x, bmax, kd, log_kb, log_alpha, modulator):
    apparent_log_kd = _allosteric_midpoint(kd, modulator, _LN10 * log_kb, _LN10 * log_alpha)
    return bmax * expit(_log_positive(x) - apparent_log_kd)


def _ligand_depletion(x, bmax, kd, nonspecific, activity, volume):
    kd_cpm = kd * (1000 * activity * volume)
    # Positive smaller root, expressed without subtracting close quantities.
    factor = 1 + nonspecific
    b = factor * kd_cpm + (1 + 2 * nonspecific) * x + bmax
    c = x * (nonspecific * (kd_cpm + x) + bmax)
    discriminant = (x - kd_cpm * factor - bmax)**2 + 4 * x * kd_cpm * factor
    return 2 * c / (b + np.sqrt(discriminant))


_BINDING = {
    "Two-site specific binding": _spec(_two_site, "Bmax 1|Kd 1|Bmax 2|Kd 2", _two_site_initial,
                                        positive=("Bmax 1", "Kd 1", "Bmax 2", "Kd 2"), domain="nonnegative"),
    "Two-site total binding": _spec(
        lambda x, b1, k1, b2, k2, ns, background: _two_site(x, b1, k1, b2, k2) + ns * x + background,
        "Bmax 1|Kd 1|Bmax 2|Kd 2|Nonspecific slope|Background", _two_site_total_initial,
        positive=("Bmax 1", "Kd 1", "Bmax 2", "Kd 2"), domain="nonnegative"),
    "Specific binding with Hill slope": _spec(
        lambda x, bmax, kd, hill: bmax * _occupancy(x, kd, hill),
        "Bmax|Kd|Hill slope", lambda x, y: (*_saturation_initial(x, y), 1.),
        positive=("Bmax", "Kd", "Hill slope"), domain="nonnegative"),
    "One-site total binding with depletion": _spec(
        _ligand_depletion, "Bmax|Kd (nM)|NS|Specific activity|Volume",
        lambda x, y: (max(np.max(y), np.ptp(y)), .1, .05, 1., 1.),
        positive=("Bmax", "Kd (nM)", "Specific activity", "Volume"), nonnegative=("NS",),
        domain="nonnegative", fixed=("Specific activity", "Volume")),
    "Allosteric saturation binding": _spec(
        _allosteric_binding, "Bmax|Kd hot|Log KB|Log alpha|Modulator",
        lambda x, y: (*_saturation_initial(x, y), np.log10(np.median(x[x > 0])), -1., 1.),
        positive=("Bmax", "Kd hot"), nonnegative=("Modulator",),
        domain="nonnegative", fixed=("Modulator",)),
}


def _competition_initial(x, y):
    return *np.percentile(y, [5, 95]), np.median(x)


def _competition_two_initial(x, y):
    bottom, top, _ = _competition_initial(x, y)
    return bottom, top, *np.quantile(x, [.25, .75]), .5


def _competition_two(x, bottom, top, midpoint1, midpoint2, fraction):
    occupancy = fraction * expit(_LN10 * (midpoint1 - x)) + (1 - fraction) * expit(_LN10 * (midpoint2 - x))
    return bottom + (top - bottom) * occupancy


def _ki_to_ic50(log_ki, hot, hot_kd):
    return log_ki + np.log1p(hot / hot_kd) / _LN10


def _competition_two_ki(x, bottom, top, log_ki1, log_ki2, fraction, hot, hot_kd1, hot_kd2):
    return _competition_two(x, bottom, top, _ki_to_ic50(log_ki1, hot, hot_kd1),
                            _ki_to_ic50(log_ki2, hot, hot_kd2), fraction)


def _homologous_competition(x, bmax, log_kd, hot, ns):
    log_others = np.logaddexp(_LN10 * (x + 9), _LN10 * (log_kd + 9))
    return bmax * expit(np.log(hot) - log_others) + ns * hot


def _allosteric_competition(x, y0, log_kb, log_alpha, hot, hot_kd):
    log_ratio = _LN10 * (x - log_kb)
    shift = np.logaddexp(0., log_ratio) - np.logaddexp(0., log_ratio + _LN10 * log_alpha)
    log_odds = np.log(hot) - np.log(hot_kd)
    ratio = np.logaddexp(0., -log_odds) - np.logaddexp(0., shift - log_odds)
    return y0 * np.exp(ratio)


def _competitive_depletion(x, bmax, log_ki, ns, hot, hot_kd, activity, volume):
    # Use the smaller positive root of the ligand mass balance. Scale
    # the quadratic to handle both near-total and negligible competition.
    log_kd_cpm = (np.log(1000.) + np.log(hot_kd) + np.log(activity) + np.log(volume) +
                  np.logaddexp(0., _LN10 * (x - log_ki)))
    log_hot, log_bmax = np.log(hot), np.log(bmax)
    scale = np.maximum(log_kd_cpm, max(log_hot, log_bmax))
    added = np.exp(log_hot - scale)
    capacity = np.exp(log_bmax - scale)
    kd = np.exp(log_kd_cpm - scale)
    free_fraction = 1 / (1 + ns)
    bound_fraction = ns * free_fraction
    capacity *= free_fraction
    b = kd + (1 + bound_fraction) * added + capacity
    discriminant = (added * free_fraction - kd - capacity)**2 + 4 * added * kd * free_fraction
    return hot * (2 * (bound_fraction * (kd + added) + capacity) / (b + np.sqrt(discriminant)))


_COMPETITION = {
    "One-site competition (log IC50)": _LOG_DOSE["Inhibition (standard slope, log10 X)"],
    "One-site competition (log Ki)": _spec(
        lambda x, bottom, top, log_ki, hot, hot_kd: _dose_variable(
            _LN10 * x, bottom, top, _LN10 * _ki_to_ic50(log_ki, hot, hot_kd), -1.),
        "Bottom|Top|Log Ki|Hot (nM)|Hot Kd (nM)", lambda x, y: (*_competition_initial(x, y), 1., 1.),
        positive=("Hot (nM)", "Hot Kd (nM)"), fixed=("Hot (nM)", "Hot Kd (nM)")),
    "Two-site competition (log IC50)": _spec(
        _competition_two, "Bottom|Top|Log IC50 1|Log IC50 2|Fraction 1", _competition_two_initial,
        limits={"Fraction 1": (0., 1.)}),
    "Two-site competition (log Ki)": _spec(
        _competition_two_ki, "Bottom|Top|Log Ki 1|Log Ki 2|Fraction 1|Hot (nM)|Hot Kd 1 (nM)|Hot Kd 2 (nM)",
        lambda x, y: (*_competition_two_initial(x, y), 1., 1., 1.),
        positive=("Hot (nM)", "Hot Kd 1 (nM)", "Hot Kd 2 (nM)"), limits={"Fraction 1": (0., 1.)},
        fixed=("Hot (nM)", "Hot Kd 1 (nM)", "Hot Kd 2 (nM)")),
    "One-site competition with depletion": _spec(
        _competitive_depletion, "Bmax|Log Ki|NS|Hot (cpm)|Hot Kd (nM)|Specific activity|Volume",
        lambda x, y: (max(np.max(y), np.ptp(y), _POSITIVE), np.median(x), .05, 1000., 1., 1., 1.),
        positive=("Bmax", "Hot (cpm)", "Hot Kd (nM)", "Specific activity", "Volume"), nonnegative=("NS",),
        fixed=("Hot (cpm)", "Hot Kd (nM)", "Specific activity", "Volume")),
    "Homologous one-site competition": _spec(
        _homologous_competition, "Bmax|Log Kd|Hot (nM)|NS",
        lambda x, y: (max(np.max(y), np.ptp(y)), np.median(x), 1., .1),
        positive=("Bmax", "Hot (nM)"), nonnegative=("NS",), fixed=("Hot (nM)",)),
    "Allosteric competition": _spec(
        _allosteric_competition, "Y0|Log KB|Log alpha|Hot (nM)|Hot Kd (nM)",
        lambda x, y: (y[np.argmin(x)], np.median(x), -1., 1., 1.),
        positive=("Hot (nM)", "Hot Kd (nM)"), fixed=("Hot (nM)", "Hot Kd (nM)")),
}


def _association_binding(x, bmax, kon, koff, hot_nm):
    collision = kon * (hot_nm * 1e-9)
    rate = collision + koff
    return _association(x, 0., bmax * (collision / rate), rate)


def _association_binding_initial(x, y):
    rate = 1 / np.ptp(x)
    return 2 * max(np.max(y), np.ptp(y)), rate * 1e9, rate, 1.


def _association_dissociation(x, bmax, kon, koff, hot_nm, time0, background):
    association = _association_binding(np.minimum(x, time0), bmax, kon, koff, hot_nm)
    return background + association * np.exp(-koff * np.maximum(x - time0, 0.))


def _competitive_binding_kinetics(x, bmax, k3, k4, k1, k2, hot_nm, cold_nm):
    hot, cold = k1 * (hot_nm * 1e-9), k3 * (cold_nm * 1e-9)
    if cold == 0:
        return _association_binding(x, bmax, k1, k2, hot_nm)
    scale = max(hot, cold, k2, k4)
    a, b, off_hot, off_cold = hot / scale, cold / scale, k2 / scale, k4 / scale
    ka, kb = a + off_hot, b + off_cold
    gap = np.hypot(ka - kb, 2 * np.sqrt(a) * np.sqrt(b))
    fast = (ka + kb + gap) / 2
    determinant = a * off_cold + b * off_hot + off_hot * off_cold
    slow = determinant / fast
    time = scale * x
    # Rewrite the difference of exponentials around the slower phase and
    # use the determinant for the smaller eigenvalue to avoid subtraction.
    equilibrium = a * off_cold / determinant
    rise = equilibrium * -np.expm1(-slow * time)
    transient = (a * (1 - off_cold / fast) * np.exp(-slow * time) *
                 (-np.expm1(-gap * time) / gap))
    return bmax * (rise + transient)


def _competitive_kinetics_initial(x, y):
    bmax, kon, koff, _ = _association_binding_initial(x, y)
    return max(bmax, _POSITIVE), kon, koff, kon, koff, 1., 1.


_KINETICS = {
    "One-phase binding dissociation": _spec(
        _association, "Y0|NS|Rate", _association_initial, positive=("Rate",), domain="nonnegative"),
    "Association kinetics (one ligand concentration)": _spec(
        _association_binding, "Bmax|Kon|Koff|Hot (nM)", _association_binding_initial,
        positive=("Bmax", "Kon", "Koff", "Hot (nM)"), domain="nonnegative", fixed=("Koff", "Hot (nM)")),
    # Kon and Koff cannot be estimated jointly from a single association curve.
    "Association kinetics (multiple ligand concentrations)": _spec(
        _association_binding, "Bmax|Kon|Koff|Hot (nM)", _association_binding_initial,
        positive=("Bmax", "Kon", "Koff", "Hot (nM)"), domain="nonnegative", fixed=("Hot (nM)",)),
    "Association then dissociation": _spec(
        _association_dissociation, "Bmax|Kon|Koff|Hot (nM)|Time 0|NS",
        lambda x, y: (*_association_binding_initial(x, y), x[np.argmax(y)], y[np.argmin(x)]),
        positive=("Bmax", "Kon", "Koff", "Hot (nM)", "Time 0"), domain="nonnegative",
        fixed=("Hot (nM)", "Time 0")),
    "Kinetics of competitive binding": _spec(
        _competitive_binding_kinetics, "Bmax|K3|K4|K1|K2|Hot (nM)|Cold (nM)", _competitive_kinetics_initial,
        positive=("Bmax", "K3", "K4", "K1", "K2", "Hot (nM)"), nonnegative=("Cold (nM)",),
        domain="nonnegative", fixed=("K1", "K2", "Hot (nM)", "Cold (nM)"), shared=("Bmax", "K3", "K4")),
}


def _substrate_inhibition(x, vmax, km, ki):
    with np.errstate(divide="ignore", over="ignore"):
        return vmax / (1 + km / x + x / ki)


def _morrison(x, v0, ki, et, substrate, km):
    apparent = ki * (1 + substrate / km)
    numerator = et + x + apparent
    discriminant = (et - x)**2 + apparent * (2 * (et + x) + apparent)
    inhibited = 2 * x / (numerator + np.sqrt(discriminant))
    return v0 * (1 - inhibited)


def _enzyme_inhibition(x, vmax, km, ki, inhibitor, *, mode, alpha=1.):
    before = 1 + inhibitor / ki if mode != "uncompetitive" else 1.
    after = 1 + inhibitor / (alpha * ki) if mode != "competitive" else 1.
    with np.errstate(divide="ignore", over="ignore"):
        return vmax / (after + before * (km / x))


def _enzyme_inhibition_initial(x, y):
    vmax, km = _saturation_initial(x, y)
    return vmax, km, km, km


_ENZYMES = {
    "Michaelis–Menten (kcat)": _spec(
        lambda x, kcat, km, et: et * _saturation(x, kcat, km),
        "kcat|Km|Et", lambda x, y: (*_saturation_initial(x, y), 1.),
        positive=("kcat", "Km", "Et"), domain="nonnegative", fixed=("Et",)),
    "Allosteric sigmoidal enzyme kinetics": _spec(
        lambda x, vmax, midpoint, hill: vmax * _occupancy(x, midpoint, hill),
        "Vmax|K half|Hill slope", lambda x, y: (*_saturation_initial(x, y), 1.),
        positive=("Vmax", "K half", "Hill slope"), domain="nonnegative"),
    "Substrate inhibition": _spec(
        _substrate_inhibition, "Vmax|Km|Ki",
        lambda x, y: (2 * max(np.max(y), np.ptp(y)), np.median(x[x > 0]) / 3, np.max(x)),
        positive=("Vmax", "Km", "Ki"), domain="nonnegative"),
    "Mixed-model enzyme inhibition": _spec(
        lambda x, v, km, ki, i, a: _enzyme_inhibition(x, v, km, ki, i, mode="mixed", alpha=a),
        "Vmax|Km|Ki|Inhibitor|Alpha", lambda x, y: (*_enzyme_inhibition_initial(x, y), 1.),
        positive=("Vmax", "Km", "Ki", "Alpha"), nonnegative=("Inhibitor",),
        domain="nonnegative", fixed=("Inhibitor",)),
    "Morrison tight-binding inhibition": _spec(
        _morrison, "V0|Ki|Et|Substrate|Km", lambda x, y: (max(np.max(y), np.ptp(y)), np.median(x[x > 0]), 1., 1., 1.),
        positive=("V0", "Ki", "Et", "Km"), nonnegative=("Substrate",),
        domain="nonnegative", fixed=("Et", "Substrate", "Km")),
}
for _mechanism in ("competitive", "noncompetitive", "uncompetitive"):
    _ENZYMES[f"{_mechanism.capitalize()} enzyme inhibition"] = _spec(
        lambda x, v, km, ki, i, mechanism=_mechanism: _enzyme_inhibition(x, v, km, ki, i, mode=mechanism),
        "Vmax|Km|Ki|Inhibitor", _enzyme_inhibition_initial,
        positive=("Vmax", "Km", "Ki"), nonnegative=("Inhibitor",), domain="nonnegative", fixed=("Inhibitor",))


def _classic_decay_initial(x, y):
    y0, plateau, rate = _association_initial(x, y)
    span = (y0 - plateau) / 2
    return plateau, span, span, 8 * rate, rate


def _classic_sine_initial(x, y):
    amplitude, wavelength, phase = _sine_initial(x, y, baseline=True)
    return np.mean(y), amplitude, 2 * np.pi / wavelength, phase


def _classic_gaussian_initial(x, y):
    amplitude, mean, sd = _gaussian_initial(x, y)
    return amplitude * sd * np.sqrt(2 * np.pi), mean, sd


_CLASSIC = {
    "Classic two-phase decay": _spec(
        lambda x, plateau, a, b, k1, k2: plateau + a * np.exp(-k1 * x) + b * np.exp(-k2 * x),
        "Plateau|Span 1|Span 2|K1|K2", _classic_decay_initial, positive=("K1", "K2"), domain="nonnegative"),
    "Classic one-phase association": _spec(
        lambda x, ymax, rate: _association(x, 0., ymax, rate), "Y max|Rate",
        lambda x, y: _association_initial(x, y)[1:], positive=("Rate",), domain="nonnegative"),
    "Classic two-phase association": _spec(
        lambda x, a, b, k1, k2: _two_phase_association(x, 0., a, b, k1, k2),
        "Y max 1|Y max 2|K1|K2", lambda x, y: _two_phase_association_initial(x, y)[1:],
        positive=("K1", "K2"), domain="nonnegative"),
    "Classic sine wave (angular frequency)": _spec(
        lambda x, baseline, amplitude, frequency, phase: baseline + amplitude * np.sin(frequency * x + phase),
        "Baseline|Amplitude|Angular frequency|Phase shift", _classic_sine_initial,
        positive=("Amplitude", "Angular frequency")),
    "Classic Gaussian (area)": _spec(
        lambda x, area, mean, sd: _gaussian(x, area / (sd * np.sqrt(2 * np.pi)), mean, sd),
        "Area|Mean|SD", _classic_gaussian_initial, positive=("SD",)),
}


_FAMILIES = {
    "Dose-response · concentration X": (
        ("Normalized inhibition", "Stimulation (standard slope)", "Stimulation (variable slope)",
         "Inhibition (standard slope)", "Inhibition (variable slope)"), _CONCENTRATION_DOSE),
    "Dose-response · log10 X": ((), _LOG_DOSE),
    "Exponential": (("One-phase decay", "One-phase association"), _EXPONENTIAL),
    "Growth": (("Exponential growth",), _GROWTH),
    "Binding · saturation": (("One-site specific binding", "One-site total binding"), _BINDING),
    "Binding · competition": ((), _COMPETITION),
    "Binding · kinetics": ((), _KINETICS),
    "Enzyme kinetics": (("Michaelis–Menten",), _ENZYMES),
    "Lines and segmented fits": ((), _LINES),
    "Polynomials": ((), _POLYNOMIALS),
    "Gaussian and other distributions": (("Gaussian",), _DISTRIBUTIONS),
    "Sine and sinc waves": ((), _WAVES),
    "Other equations": (("Logistic (4 parameters)",), _OTHER),
    "Classic equations": ((), _CLASSIC),
}

MODEL_GROUPS = {group: (*old, *added) for group, (old, added) in _FAMILIES.items()}
for _, _additional in _FAMILIES.values():
    MODELS.update(_additional)


# Null values are interior to the extended model's bounds, with the
# restricted model's parameters first in the same order.
NESTED_MODELS.update({
    ("Stimulation (standard slope, log10 X)", "Stimulation (variable slope, log10 X)"): (1.,),
    ("Inhibition (standard slope, log10 X)", "Inhibition (variable slope, log10 X)"): (-1.,),
    ("Normalized stimulation (standard slope)", "Normalized stimulation (variable slope)"): (1.,),
    ("Normalized inhibition (standard slope)", "Normalized inhibition (variable slope)"): (-1.,),
    ("Normalized stimulation (standard slope, log10 X)", "Normalized stimulation (variable slope, log10 X)"): (1.,),
    ("Normalized inhibition (standard slope, log10 X)", "Normalized inhibition (variable slope, log10 X)"): (-1.,),
    ("One-site specific binding", "Specific binding with Hill slope"): (1.,),
})
