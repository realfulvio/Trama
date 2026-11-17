"""Extra-SS parameter profiles for a confirmed safe custom-equation fit."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .fit_weights import UNWEIGHTED
from .parameter_intervals import METHOD, PROFILE, profile_limits


def apply_profiles(fit, settings, compiled, budget):
    """Replace only custom CI columns; keep point fit, SEs, residuals and curve.

    Fixed coefficients are part of the equation closure, not optimizer
    coordinates. Supplied SDs are the original complete-row relative scales.
    One request-wide budget (and cancellation event) spans every group.
    """
    table = fit['parameters']
    free = [c for c in settings.coefficients if not c.fixed]
    fixed = {c.name: c.start for c in settings.coefficients if c.fixed}
    status = pd.DataFrame({
        'Method': PROFILE, 'Confidence level (%)': settings.level,
        'df': fit['summary']['df'], 'Lower status': 'Fixed', 'Upper status': 'Fixed',
        'Lower reason': 'The coefficient is fixed; no confidence interval is estimated.',
        'Upper reason': 'The coefficient is fixed; no confidence interval is estimated.',
    }, index=table.index)
    if free:
        names = [c.name for c in free]

        def equation(x, *parameters):
            return compiled.evaluate(x, {**fixed, **dict(zip(names, parameters, strict=True))})

        spec = SimpleNamespace(equation=equation, bounds=(
            [-np.inf if c.lower is None else c.lower for c in free],
            [np.inf if c.upper is None else c.upper for c in free]))
        profile_parameters = table.loc[names].copy()
        profile_parameters['SE'] = fit['profile_units']
        confirmed = SimpleNamespace(parameters=profile_parameters, residuals=fit['residuals'],
                                    diagnostics={'Weighting': settings.weighting},
                                    residual_scales=fit['data']['SD'].to_numpy(copy=True)
                                    if settings.sd is not None else None)
        limits, kinds, reasons = profile_limits(confirmed, spec, settings.level, budget)
        table.loc[names, ['CI lower', 'CI upper']] = limits
        status.loc[names, ['Lower status', 'Upper status']] = kinds
        status.loc[names, ['Lower reason', 'Upper reason']] = reasons
    # Fixed parameter intervals were already NaN in the confirmed fit.
    status['Weighting'] = settings.weighting
    status['Inference'] = ('Unweighted residuals' if settings.weighting == UNWEIGHTED
                            else 'Supplied relative SDs, held fixed')
    fit['summary'][METHOD] = PROFILE
    fit['summary']['Inference'] = status['Inference'].iloc[0] if len(status) else 'No free coefficients'
    return status
