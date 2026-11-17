"""Parameter intervals from a confirmed independent nonlinear least-squares fit.

Profile endpoints invert a one-parameter extra-SS F test. The original fit is
never replaced: only nuisance parameters are optimized at each trial value.
The limits are local to the profile search around the confirmed estimate;
this is not a simultaneous region or enumeration of disconnected branches.
"""
from dataclasses import dataclass
import warnings

import numpy as np
import pandas as pd
from scipy import optimize, stats

from .curve_models import MODELS
from .field_error import FieldError
from .fit_weights import (UNWEIGHTED, INVERSE_VARIANCE, NONLINEAR_WEIGHTINGS,
                         FITTED_WEIGHTINGS, INFERENCE_WEIGHTS, uses_observed_y, observed_scales)
from .monte_carlo import MonteCarloCancelled

METHOD, LEVEL = 'Parameter intervals', 'Parameter confidence level (%)'
WALD, PROFILE = METHODS = ('Symmetric (Wald)', 'Profile likelihood')
OPTIONS = {METHOD: METHODS, LEVEL: 95.0}
LABEL_KEYS = {METHOD: 'parameter_ci.method', LEVEL: 'parameter_ci.level'}
CHOICE_KEYS = {WALD: 'parameter_ci.wald', PROFILE: 'parameter_ci.profile'}
STATUS = 'Parameter CI status'
MAX_POINTS, MAX_PARAMETERS = 5000, 8
MAX_EVALUATIONS, MAX_VALUES = 20000, 10_000_000
MAX_EXPANSIONS = 32


@dataclass(frozen=True)
class Settings:
    method: str
    level: float


def validate_profile_data(frame, options, roles):
    """Check used observed values/SDs without fitting on the dialog thread."""
    if options.get(METHOD) != PROFILE:
        return
    weighting = options.get('Weighting', UNWEIGHTED)
    if weighting != INVERSE_VARIANCE and not uses_observed_y(weighting):
        return
    from .stats import complete
    x = options.get('X')
    responses, groups = roles['Y columns'], roles['Grouping variables']
    sigma = options.get('SD column')
    if weighting == INVERSE_VARIANCE and (sigma not in frame or sigma in [x, *responses, *groups]):
        raise FieldError('SD column', 'Choose a separate column of positive relative standard deviations.')
    for response in responses:
        used = complete(frame.reset_index(drop=True), [x, response], groups)
        if uses_observed_y(weighting):
            observed_scales(used[response].to_numpy(float), weighting)
        else:
            scales = pd.to_numeric(frame[sigma].iloc[used.index], errors='coerce')
            if np.iscomplexobj(scales.to_numpy()):
                raise FieldError('SD column', 'Choose positive finite SDs for every complete observation.')
            scales = scales.to_numpy(dtype=float, na_value=np.nan)
            if not np.isfinite(scales).all() or (scales <= 0).any():
                raise FieldError('SD column', 'Choose positive finite SDs for every complete observation.')


def settings(options):
    method = options.get(METHOD, WALD)
    if method not in METHODS:
        raise FieldError(METHOD, 'Choose Symmetric (Wald) or Profile likelihood.')
    raw = options.get(LEVEL, 95.)
    try:
        value = float(raw.replace(',', '.').strip() if isinstance(raw, str) else raw)
    except (ValueError, TypeError, OverflowError):
        value = np.nan
    if isinstance(raw, (bool, np.bool_)) or not np.isfinite(value) or not 0 < value < 100:
        raise FieldError(LEVEL, 'Choose a finite parameter confidence level strictly between 0 and 100.')
    if method == PROFILE:
        if options.get('Weighting', UNWEIGHTED) not in NONLINEAR_WEIGHTINGS:
            raise FieldError('Weighting', 'Choose a supported regression weighting.')
        model = MODELS.get(options.get('Model'))
        if model is not None and len(model.parameters) > MAX_PARAMETERS:
            raise FieldError(METHOD, f'Profile intervals support at most {MAX_PARAMETERS} free parameters per fit.')
    return Settings(method, value)


class Unavailable(Exception):
    pass


class BudgetExceeded(Unavailable):
    pass


class ProfileBudget:
    """One bounded residual-evaluation budget shared by every fit in a request."""
    def __init__(self, cancel=None):
        self.evaluations = 0
        self.values = 0
        self.cancel = cancel

    def consume(self, n):
        if self.cancel is not None and self.cancel.is_set():
            raise MonteCarloCancelled('Parameter profile calculation cancelled.')
        self.evaluations += 1
        self.values += n
        if self.evaluations > MAX_EVALUATIONS or self.values > MAX_VALUES:
            raise BudgetExceeded('Profile refitting budget exceeded; no substitute interval was used.')


def _profile(fit, model, level, budget):
    return profile_limits(fit, MODELS[model], level, budget)


def profile_limits(fit, spec, level, budget=None, *, max_parameters=None):
    """Profile a confirmed fit using explicit equation and parameter bounds.

    ``spec.equation(X, *free_parameters)`` includes any fixed coefficients in
    its closure. The parameter and residual tables describe that same fit;
    no point estimation or weight estimation is performed here.
    """
    budget = budget if budget is not None else ProfileBudget()
    parameter_limit = MAX_PARAMETERS if max_parameters is None else max_parameters
    estimates = fit.parameters['Estimate'].to_numpy(float)
    se = fit.parameters['SE'].to_numpy(float)
    n, p = len(fit.residuals), len(estimates)
    intervals = np.full((p, 2), np.nan)
    kinds = np.full((p, 2), 'Unavailable', dtype=object)
    reasons = np.full((p, 2), '', dtype=object)
    df = n-p
    if p > parameter_limit:
        reasons[:] = f'Profile intervals support at most {parameter_limit} free parameters per fit.'
        return intervals, kinds, reasons
    if n > MAX_POINTS:
        reasons[:] = f'Profile intervals support at most {MAX_POINTS} complete observations per fit.'
        return intervals, kinds, reasons
    if df <= 0 or not np.isfinite(se).all() or (se <= 0).any():
        reasons[:] = 'Positive residual degrees of freedom and finite nonzero parameter uncertainty are required.'
        return intervals, kinds, reasons
    x = fit.residuals['X'].to_numpy(float)
    y = fit.residuals['Observed'].to_numpy(float)
    raw_residual = fit.residuals['Residual'].to_numpy(float)
    precision = None
    if fit.diagnostics.get('Weighting', UNWEIGHTED) != UNWEIGHTED:
        scales = getattr(fit, 'residual_scales', None)
        if scales is None or np.shape(scales) != (n,):
            reasons[:] = 'The confirmed fit does not retain aligned residual scales for weighted profiling.'
            return intervals, kinds, reasons
        try:
            scales = np.asarray(scales, dtype=float)
        except (TypeError, ValueError, OverflowError):
            reasons[:] = 'The confirmed residual scales must be finite and strictly positive.'
            return intervals, kinds, reasons
        if not np.isfinite(scales).all() or (scales <= 0).any():
            reasons[:] = 'The confirmed residual scales must be finite and strictly positive.'
            return intervals, kinds, reasons
        # Only relative weights enter the extra-SS ratio. Keep multipliers <= 1
        # so a common change in SD units cannot overflow the profiling objective.
        precision = scales.min()/scales
        if (precision <= 0).any():
            reasons[:] = 'The relative residual scales exceed the weighted profile numeric range.'
            return intervals, kinds, reasons
        raw_residual = raw_residual*precision
    residual_scale = np.max(np.abs(raw_residual))
    if not np.isfinite(residual_scale) or residual_scale <= 0:
        reasons[:] = 'The confirmed fit has no measurable residual scatter.'
        return intervals, kinds, reasons
    # Center coordinates on the confirmed estimate and use its SE as units.
    # This preserves tiny coefficients and avoids subtracting two O(1) roots.
    units = np.maximum(se, 32*np.abs(np.spacing(np.abs(estimates))))
    lower = np.broadcast_to(np.asarray(spec.bounds[0], float), estimates.shape)
    upper = np.broadcast_to(np.asarray(spec.bounds[1], float), estimates.shape)
    with np.errstate(over='ignore', invalid='ignore'):
        lo, hi = (lower-estimates)/units, (upper-estimates)/units
    def residual(q):
        budget.consume(n)
        parameters = estimates + units*q
        with np.errstate(all='ignore'), warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            predicted = np.asarray(spec.equation(x, *parameters), float)
            r = y-predicted
            if precision is not None:
                r = r*precision
            r = r/residual_scale
        if r.shape != y.shape or not np.isfinite(r).all():
            raise Unavailable('The profile left the finite model domain.')
        return r

    try:
        base_residual = residual(np.zeros(p))
        base = float(base_residual@base_residual)
        critical = stats.f.ppf(level/100, 1, df)
        target = base*(1+critical/df)
        if not np.isfinite(target) or target <= base or base <= 0:
            raise Unavailable('The profile threshold is outside the supported numeric range.')
    except Unavailable as error:
        reasons[:] = str(error)
        return intervals, kinds, reasons

    for k in range(p):
        nuisance = np.arange(p) != k
        cache = {0.: base-target}

        def distance(value):
            if value in cache:
                return cache[value]
            trial = np.zeros(p)
            trial[k] = value

            def constrained(q):
                trial[nuisance] = q
                return residual(trial)

            if nuisance.any():
                # Every solve starts at the confirmed nuisance estimates. A
                # failed local optimum is never accepted as a confidence root.
                start = np.clip(np.zeros(p-1), lo[nuisance], hi[nuisance])
                solution = optimize.least_squares(constrained, start, bounds=(lo[nuisance], hi[nuisance]),
                    jac='3-point', ftol=1e-10, xtol=1e-10, gtol=1e-10, max_nfev=1000)
                if not solution.success:
                    raise Unavailable('The nuisance-parameter refit did not converge.')
                r = solution.fun
            else:
                r = residual(trial)
            ss = float(r@r)
            if not np.isfinite(ss):
                raise Unavailable('The profile residual sum of squares is not finite.')
            if ss < base*(1-1e-6):
                raise Unavailable('A better fit was found while profiling; refine the point fit first.')
            cache[value] = ss-target
            return cache[value]

        for side, direction, limit in ((0, -1., lo[k]), (1, 1., hi[k])):
            try:
                previous = 0.
                for exponent in range(MAX_EXPANSIONS):
                    trial = direction*2.**exponent
                    trial = max(trial, limit) if side == 0 else min(trial, limit)
                    value = distance(trial)
                    if value >= 0:
                        a, b = sorted((previous, trial))
                        root = optimize.brentq(distance, a, b, xtol=1e-8, rtol=1e-10)
                        intervals[k, side] = estimates[k] + units[k]*root
                        kinds[k, side] = 'Profile root'
                        break
                    if trial == limit:
                        intervals[k, side] = lower[k] if side == 0 else upper[k]
                        kinds[k, side] = 'Parameter bound'
                        reasons[k, side] = 'The connected confidence set reaches the model parameter bound.'
                        break
                    previous = trial
                else:
                    reasons[k, side] = 'A finite confidence endpoint was not bracketed within the search budget.'
            except (Unavailable, ValueError, RuntimeError, FloatingPointError, OverflowError) as error:
                reasons[k, side] = str(error)
    return intervals, kinds, reasons


def parameter_outputs(fit, model, config, *, budget=None):
    """Return an independent parameter frame and optional per-parameter status.

    The exact legacy frame is returned unchanged for Wald/95. Bounds, failed
    searches and budget exhaustion are explicit; no failed profile becomes a
    Wald interval and no finite search is described as proof of infinity.
    """
    if config.method == WALD and config.level == 95.:
        return fit.parameters, None
    level = float(config.level)
    table = fit.parameters.drop(columns=['CI 95% low', 'CI 95% high']).copy()
    if config.method == PROFILE:
        limits, kinds, reasons = _profile(fit, model, level, budget if budget is not None else ProfileBudget())
    else:
        delta = stats.t.isf((100-level)/200, fit.diagnostics['df'])*table['SE'].to_numpy(float)
        limits = table['Estimate'].to_numpy(float)[:,None] + delta[:,None]*np.array([-1.,1.])
        kinds = np.full(limits.shape, 'Wald', dtype=object)
        reasons = np.full(limits.shape, '', dtype=object)
        point = table['Estimate'].to_numpy(float)
        invalid = (~np.isfinite(limits).all(axis=1) | (table['SE'].to_numpy(float) <= 0)
                   | (limits[:, 0] >= point) | (limits[:, 1] <= point))
        limits[invalid] = np.nan; kinds[invalid] = 'Unavailable'
        reasons[invalid] = 'Finite nonzero parameter uncertainty is required.'
    label = str(int(level)) if level.is_integer() else repr(level)
    table[f'CI {label}% low'], table[f'CI {label}% high'] = limits[:,0], limits[:,1]
    status = pd.DataFrame({'Method':config.method, LEVEL:level, 'df':fit.diagnostics['df'],
                           'Lower status':kinds[:,0], 'Upper status':kinds[:,1],
                           'Lower reason':reasons[:,0], 'Upper reason':reasons[:,1]}, index=fit.parameters.index)
    weighting = fit.diagnostics.get('Weighting', UNWEIGHTED)
    if weighting != UNWEIGHTED:
        status['Weighting'] = weighting
        status['Inference'] = (INFERENCE_WEIGHTS if weighting in FITTED_WEIGHTINGS else
                               'Supplied relative SDs, held fixed' if weighting == INVERSE_VARIANCE else
                               'Observed Y weights, held fixed')
    return table, status
