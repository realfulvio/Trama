"""Closed inverse sets for a nonlinear standard curve.

S is the set of x in the observed interval where the pointwise asymptotic band
contains the query response. Mean response uses w(x) = q sqrt(g C gᵀ). Prediction
for the mean of k new responses uses w(x) = q sqrt(g C gᵀ + s²/k). C is the
covariance already returned by the fit: it is not multiplied by s² again.

The set can be one closed interval, several disjoint intervals, a single point,
or empty. This is not a likelihood profile, a simultaneous band or a bootstrap,
and nothing outside [low, high] is reported.

The search isolates roots and certifies the gaps. A sign check on a fixed grid
is not accepted as proof that a component is absent. If the evaluation budget
runs out before every gap is certified, the search raises InverseBudgetError
instead of returning a set that might have dropped a component.
"""
from math import log

import numpy as np
from scipy.special import expit
from scipy.stats import t
from scipy.optimize import brentq


DECAY = "One-phase decay"
CONCENTRATION = ("Stimulation (variable slope)", "Inhibition (variable slope)")
LOG10 = ("Stimulation (variable slope, log10 X)", "Inhibition (variable slope, log10 X)")
MODELS = (DECAY, *CONCENTRATION, *LOG10)
MEAN = "Mean response"
PREDICTION = "Prediction"
QUERY_EVALUATIONS = 50_000
STUDY_EVALUATIONS = 5_000_000
_LN10 = log(10.0)
_LEAF = 128 * np.finfo(float).eps


class InverseError(ValueError):
    """The inputs do not define an inverse interval."""


class InverseBudgetError(InverseError):
    """The search could not certify every component within the evaluation budget."""


class SearchAccount:
    """Evaluation counts for one query and for the whole calibration."""

    def __init__(self, query_limit=QUERY_EVALUATIONS, study_limit=STUDY_EVALUATIONS):
        self.query_limit = int(query_limit)
        self.study_limit = int(study_limit)
        self.study = 0
        self.query = 0

    def reset_query(self):
        self.query = 0

    def use(self, count=1):
        self.query += count
        self.study += count
        if self.query > self.query_limit or self.study > self.study_limit:
            raise InverseBudgetError(
                "The interval search could not certify every component within the evaluation budget.")


class _I:
    """Closed real interval. Non-finite bounds mean the enclosure is not usable."""

    __slots__ = ("lo", "hi")

    def __init__(self, lo, hi=None):
        lo = float(lo)
        hi = lo if hi is None else float(hi)
        if hi < lo:
            lo, hi = hi, lo
        self.lo = lo
        self.hi = hi

    def __add__(self, other):
        other = other if isinstance(other, _I) else _I(other)
        return _I(self.lo + other.lo, self.hi + other.hi)

    def __radd__(self, other):
        return self + other

    def __sub__(self, other):
        other = other if isinstance(other, _I) else _I(other)
        return _I(self.lo - other.hi, self.hi - other.lo)

    def __rsub__(self, other):
        return _I(other) - self

    def __mul__(self, other):
        other = other if isinstance(other, _I) else _I(other)
        if not np.isfinite((self.lo, self.hi, other.lo, other.hi)).all():
            return _I(-np.inf, np.inf)
        products = (self.lo * other.lo, self.lo * other.hi, self.hi * other.lo, self.hi * other.hi)
        return _I(min(products), max(products))

    def __rmul__(self, other):
        return self * other

    def __neg__(self):
        return _I(-self.hi, -self.lo)

    def __contains__(self, value):
        return self.lo <= value <= self.hi


class _D:
    """Value and derivative, each an interval enclosure."""

    __slots__ = ("v", "d")

    def __init__(self, value, derivative):
        self.v = value if isinstance(value, _I) else _I(value)
        self.d = derivative if isinstance(derivative, _I) else _I(derivative)


def _dconst(value):
    return _D(value, 0.0)


def _dadd(left, right):
    return _D(left.v + right.v, left.d + right.d)


def _dsub(left, right):
    return _D(left.v - right.v, left.d - right.d)


def _dmul(left, right):
    return _D(left.v * right.v, left.d * right.v + left.v * right.d)


def _dexp(value):
    with np.errstate(over="ignore"):
        low, high = np.exp(value.v.lo), np.exp(value.v.hi)
    image = _I(low, high)
    return _D(image, image * value.d)


def _dexpit(value):
    image = _I(float(expit(value.v.lo)), float(expit(value.v.hi)))
    return _D(image, _p_one_minus(image) * value.d)


def _dlog(value):
    if not np.isfinite((value.v.lo, value.v.hi)).all() or value.v.lo <= 0:
        return _D(_I(-np.inf, np.inf), _I(-np.inf, np.inf))
    image = _I(log(value.v.lo), log(value.v.hi))
    slope = _I(1.0 / value.v.hi, 1.0 / value.v.lo)
    return _D(image, slope * value.d)


def _dmax0(value):
    """Enclosure of max(v, 0) and of its derivative."""
    if value.v.hi < 0:
        return _dconst(0.0)
    if value.v.lo >= 0:
        return value
    return _D(_I(0.0, value.v.hi), _I(min(0.0, value.d.lo), max(0.0, value.d.hi)))


def _p_one_minus(probability):
    """Exact range of p(1-p) for p in an interval."""
    def at(point):
        return point * (1.0 - point)

    low, high = probability.lo, probability.hi
    samples = [at(low), at(high)]
    if low <= 0.5 <= high:
        samples.append(0.25)
    return _I(min(samples), max(samples))


def _usable(dual):
    return np.isfinite((dual.v.lo, dual.v.hi, dual.d.lo, dual.d.hi)).all()


def _log10(model):
    return model in LOG10


def _concentration(model):
    return model in CONCENTRATION


def _as_vector(values, size, what):
    try:
        vector = np.asarray(values, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        raise InverseError(what) from None
    if vector.shape != (size,) or not np.isfinite(vector).all():
        raise InverseError(what)
    return vector


def _validate(model, parameters, covariance, residual_variance, df, response, low, high,
              uncertainty, level, replicates):
    if model not in MODELS:
        raise InverseError("Unknown calibration model for inverse intervals.")
    size = 3 if model == DECAY else 4
    if model == DECAY:
        theta = _as_vector(parameters, 3, "Parameters must be three finite numbers for One-phase decay.")
    else:
        theta = _as_vector(parameters, 4, "Parameters must be four finite numbers for a variable-slope 4PL.")
        if not _log10(model) and not theta[2] > 0:
            raise InverseError("The concentration midpoint must be strictly positive.")
    try:
        matrix = np.asarray(covariance, dtype=float)
    except (TypeError, ValueError):
        raise InverseError("Covariance must be a finite symmetric positive semidefinite matrix.") from None
    if matrix.shape != (size, size) or not np.isfinite(matrix).all():
        raise InverseError("Covariance must be a finite symmetric positive semidefinite matrix.")
    scale = float(np.max(np.abs(matrix)))
    # Covariance has response/parameter units: an absolute floor would accept
    # an entirely negative covariance after a harmless change of units.
    if scale:
        normalized = matrix / scale
        tolerance = 32 * size * np.finfo(float).eps
        if float(np.max(np.abs(normalized - normalized.T))) > tolerance:
            raise InverseError("Covariance must be a finite symmetric positive semidefinite matrix.")
        symmetric = 0.5 * normalized + 0.5 * normalized.T
        if float(np.linalg.eigvalsh(symmetric).min()) < -tolerance:
            raise InverseError("Covariance must be a finite symmetric positive semidefinite matrix.")
        if not np.array_equal(matrix, matrix.T):
            matrix = symmetric * scale
    try:
        variance = float(residual_variance)
        degrees = float(df)
        level = float(level)
        answer = float(response)
        left, right = float(low), float(high)
    except (TypeError, ValueError, OverflowError):
        raise InverseError("Inverse interval inputs must be finite numbers.") from None
    if not np.isfinite(variance) or variance < 0:
        raise InverseError("Residual variance must be finite and at least 0.")
    if not np.isfinite(degrees) or degrees <= 0:
        raise InverseError("Residual degrees of freedom must be greater than 0.")
    if not np.isfinite(level) or not 0 < level < 100:
        raise InverseError("Confidence level must be strictly between 0 and 100.")
    if isinstance(replicates, bool) or not isinstance(replicates, (int, np.integer, float, np.floating)):
        raise InverseError("Replicate count must be a whole number from 1 to 9007199254740992.")
    if isinstance(replicates, (float, np.floating)):
        if not np.isfinite(replicates) or replicates != np.trunc(replicates):
            raise InverseError("Replicate count must be a whole number from 1 to 9007199254740992.")
    count = int(replicates)
    if not 1 <= count <= 2**53:
        raise InverseError("Replicate count must be a whole number from 1 to 9007199254740992.")
    if uncertainty not in (MEAN, PREDICTION):
        raise InverseError("Select Mean response or Prediction.")
    if not np.isfinite((answer, left, right)).all() or left > right:
        raise InverseError("The response and the X interval must be finite, with the low end at or below the high end.")
    if _concentration(model) and left < 0:
        raise InverseError("A concentration model requires a nonnegative X interval.")
    quantile = float(t.ppf((1.0 + level / 100.0) / 2.0, degrees))
    if not np.isfinite(quantile):
        raise InverseError("Confidence level must be strictly between 0 and 100.")
    extra = 0.0 if uncertainty == MEAN else variance / count
    return theta, matrix, answer, left, right, quantile * quantile, extra


def _evaluate(model, theta, values):
    """Curve and parameter gradient. At concentration 0 the limit is a plateau, not 0·∞."""
    values = np.asarray(values, dtype=float).reshape(-1)
    if model == DECAY:
        plateau, span, rate = theta
        decay = np.exp(-rate * values)
        curve = plateau + span * decay
        gradient = np.column_stack((np.ones(values.shape), decay, -span * values * decay))
        return curve, gradient
    bottom, top, mid, hill = theta
    if _log10(model):
        shifted = _LN10 * (values - mid)
        slope = -_LN10
    else:
        shifted = np.full(values.shape, -np.inf)
        np.log(values, out=shifted, where=values > 0)
        shifted = shifted - log(float(mid))
        slope = -1.0 / float(mid)
    probability = expit(hill * shifted)
    change = (top - bottom) * probability * (1.0 - probability)
    finite = np.isfinite(shifted)
    midpoint = np.zeros(values.shape)
    steepness = np.zeros(values.shape)
    midpoint[finite] = change[finite] * hill * slope
    steepness[finite] = change[finite] * shifted[finite]
    curve = bottom + (top - bottom) * probability
    gradient = np.column_stack((1.0 - probability, probability, midpoint, steepness))
    return curve, gradient


def _curve_dual(model, theta, variable):
    if model == DECAY:
        plateau, span, rate = (float(part) for part in theta)
        decay = _dexp(_dmul(_dconst(-rate), variable))
        curve = _dadd(_dconst(plateau), _dmul(_dconst(span), decay))
        gradient = (_dconst(1.0), decay, _dmul(_dconst(-span), _dmul(variable, decay)))
        return curve, gradient
    bottom, top, mid, hill = (float(part) for part in theta)
    if _log10(model):
        shifted = _dmul(_dconst(_LN10), _dsub(variable, _dconst(mid)))
        slope = -_LN10
    else:
        shifted = _dsub(_dlog(variable), _dconst(log(mid)))
        slope = -1.0 / mid
    probability = _dexpit(_dmul(_dconst(hill), shifted))
    complement = _dsub(_dconst(1.0), probability)
    change = _dmul(_dconst(top - bottom), _dmul(probability, complement))
    curve = _dadd(_dconst(bottom), _dmul(_dconst(top - bottom), probability))
    gradient = (complement, probability, _dmul(change, _dconst(hill * slope)), _dmul(change, shifted))
    return curve, gradient


def _quadratic(gradient, covariance):
    total = _dconst(0.0)
    size = len(gradient)
    for row in range(size):
        for column in range(row, size):
            coefficient = float(covariance[row, column])
            if row != column:
                coefficient *= 2.0
            if coefficient == 0.0:
                continue
            total = _dadd(total, _dmul(_dconst(coefficient), _dmul(gradient[row], gradient[column])))
    return total


def _criterion_dual(model, theta, covariance, response, q2, extra, left, right):
    variable = _D(_I(left, right), 1.0)
    curve, gradient = _curve_dual(model, theta, variable)
    variance = _dmax0(_quadratic(gradient, covariance))
    if extra:
        variance = _dadd(variance, _dconst(extra))
    spread = _dmul(_dconst(q2), variance)
    difference = _dsub(curve, _dconst(response))
    return _dsub(_dmul(difference, difference), spread)


def _point_estimate(model, theta, response):
    """Closed-form inverse of the fitted curve, or None when the response is off the asymptotes."""
    response = float(response)
    if model == DECAY:
        plateau, span, rate = (float(part) for part in theta)
        if span == 0 or rate == 0:
            return None
        ratio = (response - plateau) / span
        if ratio <= 0:
            return None
        return -log(ratio) / rate
    bottom, top, mid, hill = (float(part) for part in theta)
    span = top - bottom
    if span == 0 or hill == 0:
        return None
    fraction = (response - bottom) / span
    if not 0 < fraction < 1:
        return None
    shift = log(fraction / (1.0 - fraction)) / hill
    if _log10(model):
        return mid + shift / _LN10
    return mid * np.exp(shift)


def _lipschitz_bounds(left_value, right_value, slope, width):
    """Lower and upper bounds of a function whose derivative stays within ±slope."""
    if not np.isfinite(slope) or slope < 0:
        return -np.inf, np.inf
    if slope == 0 or width == 0:
        return min(left_value, right_value), max(left_value, right_value)
    toward_low = (left_value - right_value + slope * width) / (2.0 * slope)
    toward_low = min(max(toward_low, 0.0), width)
    lower = left_value - slope * toward_low
    toward_high = (right_value - left_value + slope * width) / (2.0 * slope)
    toward_high = min(max(toward_high, 0.0), width)
    upper = left_value + slope * toward_high
    return lower, upper


def _root(function, left, right, left_value, right_value, account):
    if left_value == 0:
        return float(left)
    if right_value == 0:
        return float(right)

    def counted(point):
        account.use()
        return function(point)

    try:
        return float(brentq(counted, left, right, xtol=_LEAF, rtol=_LEAF, maxiter=200))
    except ValueError:
        return float(left if abs(left_value) <= abs(right_value) else right)


def _leaf(function, left, right, account):
    account.use(2)
    left_value, right_value = function(left), function(right)
    middle = 0.5 * (left + right)
    account.use()
    middle_value = function(middle)
    if left_value <= 0 and right_value <= 0 and middle_value <= 0:
        return [(left, right)]
    if left_value <= 0 < right_value and middle_value <= 0:
        return [(left, _root(function, left, right, left_value, right_value, account))]
    if right_value <= 0 < left_value and middle_value <= 0:
        return [(_root(function, left, right, left_value, right_value, account), right)]
    pieces = []
    if left_value <= 0 and middle_value > 0:
        pieces.append((left, _root(function, left, middle, left_value, middle_value, account)))
    elif left_value > 0 >= middle_value:
        pieces.append((_root(function, left, middle, left_value, middle_value, account), middle))
    if middle_value <= 0 and right_value > 0:
        pieces.append((middle, _root(function, middle, right, middle_value, right_value, account)))
    elif middle_value > 0 >= right_value:
        pieces.append((_root(function, middle, right, middle_value, right_value, account), right))
    if not pieces and middle_value <= 0:
        pieces.append((middle, middle))
    return pieces


def _merge(pieces, low, high):
    pieces = sorted((float(left), float(right)) for left, right in pieces if right >= left)
    scale = max(1.0, abs(low), abs(high))
    snap = 128 * np.finfo(float).eps * scale
    merged = []
    for left, right in pieces:
        if abs(left - low) <= snap:
            left = low
        if abs(right - high) <= snap:
            right = high
        if right < left:
            left = right = low if abs(left - low) <= snap else left
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return [(left, right) for left, right in merged]


def _search(model, theta, covariance, response, low, high, q2, extra, account):
    span = high - low
    if not np.isfinite(span):
        raise InverseBudgetError("The interval search could not certify every component within the evaluation budget.")

    def original(unit):
        return low if unit == 0.0 else high if unit == 1.0 else low + span * unit

    # Search in a dimensionless [0,1] coordinate. Root, leaf and merging
    # tolerances must not turn distinct components into one when X uses small units.
    def function(point):
        curve, gradient = _evaluate(model, theta, [original(point)])
        variance = float(gradient[0] @ covariance @ gradient[0])
        if variance < 0:
            variance = 0.0
        return float((curve[0] - response) ** 2 - q2 * (variance + extra))

    def certify(left, right, left_value, right_value):
        account.use()
        dual = _criterion_dual(model, theta, covariance, response, q2, extra,
                               original(left), original(right))
        if not _usable(dual):
            return None
        if dual.v.lo > 0 and left_value > 0 and right_value > 0:
            return "out"
        if dual.v.hi <= 0 and left_value <= 0 and right_value <= 0:
            return "in"
        slope = max(abs(dual.d.lo), abs(dual.d.hi)) * span
        lower, upper = _lipschitz_bounds(left_value, right_value, slope, right - left)
        if lower > 0 and left_value > 0 and right_value > 0:
            return "out"
        if upper <= 0 and left_value <= 0 and right_value <= 0:
            return "in"
        return None

    inside = []
    pending = [(0.0, 1.0)]
    point = _point_estimate(model, theta, response)
    estimate = (point - low) / span if point is not None else None
    if estimate is not None and 0.0 < estimate < 1.0:
        pending = [(0.0, estimate), (estimate, 1.0)]
    while pending:
        left, right = pending.pop()
        width = right - left
        scale = max(1.0, abs(left), abs(right))
        account.use(2)
        left_value, right_value = function(left), function(right)
        if width <= _LEAF * scale:
            inside.extend(_leaf(function, left, right, account))
            continue
        kind = certify(left, right, left_value, right_value)
        if kind == "out":
            continue
        if kind == "in":
            inside.append((left, right))
            continue
        middle = 0.5 * (left + right)
        if estimate is not None and left < estimate < right:
            middle = estimate
        pending.append((middle, right))
        pending.append((left, middle))
    pieces = _merge(inside, 0.0, 1.0)
    if estimate is not None and 0.0 <= estimate <= 1.0:
        account.use()
        at_estimate = function(estimate)
        tolerance = 1e-8 * (1.0 + response * response)
        contained = any(left - 1e-9 <= estimate <= right + 1e-9
                        for left, right in pieces)
        if at_estimate <= tolerance and not contained:
            raise InverseBudgetError("The interval search did not contain the point estimate.")
    return [(original(left), original(right)) for left, right in pieces]


def inverse_band_components(model, parameters, covariance, residual_variance, df, response, low, high,
                            uncertainty="Mean response", level=95.0, replicates=1, account=None):
    """Return the disjoint closed components of the inverse set, ordered from left to right.

    ``account`` accumulates evaluations across queries of one calibration. Without it, each call
    has its own query budget and does not affect later calls.
    """
    theta, matrix, answer, left, right, q2, extra = _validate(
        model, parameters, covariance, residual_variance, df, response, low, high, uncertainty, level, replicates)
    if account is None:
        account = SearchAccount()
    else:
        account.reset_query()
    if left == right:
        account.use()
        curve, gradient = _evaluate(model, theta, [left])
        variance = float(gradient[0] @ matrix @ gradient[0])
        value = (curve[0] - answer) ** 2 - q2 * (max(variance, 0.0) + extra)
        return [(left, right)] if value <= 0 else []
    return _search(model, theta, matrix, answer, left, right, q2, extra, account)
