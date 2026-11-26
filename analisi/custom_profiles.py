"""Extra-SS parameter profiles for a confirmed safe custom-equation fit."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import coefficient_links as links
from .fit_weights import UNWEIGHTED
from .parameter_intervals import METHOD, PROFILE, profile_limits


def apply_profiles(fit, settings, compiled, budget):
    """Replace only custom CI columns; keep point fit, SEs, residuals and curve.

    Fixed coefficients are part of the equation closure, not optimizer
    coordinates. Supplied SDs are the original complete-row relative scales.
    One request-wide budget (and cancellation event) spans every group.
    """
    table = fit['parameters']
    free = [c for c in settings.coefficients if not c.fixed and c.link is None]
    fixed = {c.name: c.start for c in settings.coefficients if c.fixed or c.link is not None}
    plan = getattr(settings, 'plan', None)
    status = pd.DataFrame({
        'Method': PROFILE, 'Confidence level (%)': settings.level,
        'df': fit['summary']['df'], 'Lower status': 'Fixed', 'Upper status': 'Fixed',
        'Lower reason': 'The coefficient is fixed; no confidence interval is estimated.',
        'Upper reason': 'The coefficient is fixed; no confidence interval is estimated.',
    }, index=table.index)
    if free:
        names = [c.name for c in free]

        def equation(x, *parameters):
            values = {**fixed, **dict(zip(names, parameters, strict=True))}
            return compiled.evaluate(x, plan.apply(values) if plan else values)

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
    if plan:
        _map_linked(table, status, plan, [c.name for c in free])
    # Fixed parameter intervals were already NaN in the confirmed fit.
    status['Weighting'] = settings.weighting
    status['Inference'] = ('Unweighted residuals' if settings.weighting == UNWEIGHTED
                            else 'Supplied relative SDs, held fixed')
    fit['summary'][METHOD] = PROFILE
    fit['summary']['Inference'] = status['Inference'].iloc[0] if len(status) else 'No free coefficients'
    return status


def _map_linked(table, status, plan, free):
    """Profile limits of a linked coefficient: the root's limits through the link, ends swapped when the
    factor is negative. Open or unavailable ends stay as they are; a constant link has no interval."""
    for target in plan.order:
        root, factor, offset = plan.root(target)
        if factor == 0 or root not in free:
            reason = 'The link makes this coefficient constant; no confidence interval is estimated.'
            status.loc[target, ['Lower status', 'Upper status']] = ['Fixed', 'Fixed']
            status.loc[target, ['Lower reason', 'Upper reason']] = [reason, reason]
            table.loc[target, ['CI lower', 'CI upper']] = [np.nan, np.nan]
            continue
        limits, kinds, reasons = links.map_interval(
            table.loc[root, ['CI lower', 'CI upper']].to_numpy(dtype=float),
            status.loc[root, ['Lower status', 'Upper status']].tolist(),
            status.loc[root, ['Lower reason', 'Upper reason']].tolist(), factor, offset)
        table.loc[target, ['CI lower', 'CI upper']] = limits
        status.loc[target, ['Lower status', 'Upper status']] = kinds
        status.loc[target, ['Lower reason', 'Upper reason']] = [
            reason or f'Mapped from the profile of {root} through {plan.formula(target)}.' for reason in reasons]
