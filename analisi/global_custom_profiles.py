"""Extra-SS profiles of the free coordinates of one confirmed joint equation fit.

A shared coefficient occupies one coordinate. Every nuisance refit uses all
complete observations of every series, with fixed per-series values held fixed.
These are individual intervals, local to the profile search, not simultaneous
regions or an enumeration of disconnected solutions.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .field_error import FieldError
from . import coefficient_links as links
from .fit_weights import UNWEIGHTED
from .parameter_intervals import METHOD, PROFILE, STATUS, MAX_POINTS, profile_limits

MAX_FREE_PARAMETERS = 32


def check_budget(observations, parameters):
    """Count the joint fit, including shared coordinates only once."""
    if parameters > MAX_FREE_PARAMETERS:
        raise FieldError(METHOD, f'Global profile intervals support at most {MAX_FREE_PARAMETERS} free coordinates.')
    if observations > MAX_POINTS:
        raise FieldError(METHOD, f'Global profile intervals support at most {MAX_POINTS} complete observations in total.')


def apply_profiles(result, solved, settings, compiled, packed, budget):
    """Replace parameter limits only. Keep the original response inference intact."""
    table = result.tables['Parameters']
    p = solved['p']
    status = table[['Scope', 'Group', 'Parameter']].copy()
    status['Method'] = PROFILE
    status['Confidence level (%)'] = settings.level
    status['df'] = solved['df']
    status['Lower status'] = status['Upper status'] = 'Fixed'
    status['Lower reason'] = status['Upper reason'] = 'The coefficient is fixed; no confidence interval is estimated.'
    inference = ('Unweighted residuals' if settings.weighting == UNWEIGHTED
                 else 'Supplied relative SDs, held fixed')
    if p:
        estimates = solved['values']*solved['scale']

        def equation(_positions, *parameters):
            pieces = []
            for series, (part, confirmed) in enumerate(zip(packed, solved['maps'], strict=True)):
                values = confirmed.copy()
                for coefficient, name in enumerate(solved['names']):
                    slot = solved['mapping'][series, coefficient]
                    if slot >= 0:
                        values[name] = parameters[slot]
                if solved.get('complete') is not None:
                    values = solved['complete'](values)
                pieces.append(compiled.evaluate(part['X'], values))
            return np.concatenate(pieces)

        observed = np.concatenate([part['Y'] for part in packed])
        confirmed = SimpleNamespace(
            parameters=pd.DataFrame({'Estimate': estimates, 'SE': solved['profile_units']}),
            residuals=pd.DataFrame({'X': np.arange(solved['n'], dtype=float), 'Observed': observed,
                                    'Residual': observed-np.concatenate(solved['pieces'])}),
            diagnostics={'Weighting': settings.weighting},
            residual_scales=np.concatenate([part['SD'] for part in packed]) if settings.sd is not None else None)
        spec = SimpleNamespace(equation=equation, bounds=solved['bounds'])
        limits, kinds, reasons = profile_limits(confirmed, spec, settings.level, budget,
                                                max_parameters=MAX_FREE_PARAMETERS)
        # The parameter table starts with the joint free coordinates, in solver order.
        table.loc[:p-1, ['CI low', 'CI high']] = limits
        status.loc[:p-1, ['Lower status', 'Upper status']] = kinds
        status.loc[:p-1, ['Lower reason', 'Upper reason']] = reasons
    _map_linked(table, status, solved, settings)
    status['Weighting'] = settings.weighting
    status['Inference'] = inference
    result.tables[STATUS] = status
    summary = result.tables['Global fit']
    summary.loc[METHOD, 'Value'] = PROFILE
    summary.loc['Inference', 'Value'] = (
        f'Individual joint extra-SS profile limits; df = {solved["n"]} - {p} = {solved["df"]}. '
        f'{inference}. See Parameter CI status for bounds and unavailable limits. '
        'SEs, covariance and response intervals retain the original joint-Wald rules.'
        if p else solved['reason'])


def _map_linked(table, status, solved, settings):
    """Linked rows: the root coordinate's profile through the link, ends swapped for a negative factor."""
    from .global_custom_fit import linked_entries
    for entry in linked_entries(settings, solved):
        row = table.index[(table['Status'] == links.LINKED) & (table['Parameter'] == entry['name'])
                          & ((table['Group'] == entry['group']) if entry['group'] is not None
                             else table['Group'].isna())][0]
        slot = entry['slot']
        if slot < 0:
            reason = 'The link makes this coefficient constant in this series; no confidence interval is estimated.'
            status.loc[row, ['Lower status', 'Upper status']] = ['Fixed', 'Fixed']
            status.loc[row, ['Lower reason', 'Upper reason']] = [reason, reason]
            table.loc[row, ['CI low', 'CI high']] = [np.nan, np.nan]
            continue
        limits, kinds, reasons = links.map_interval(
            table.loc[slot, ['CI low', 'CI high']].to_numpy(dtype=float),
            status.loc[slot, ['Lower status', 'Upper status']].tolist(),
            status.loc[slot, ['Lower reason', 'Upper reason']].tolist(), entry['factor'], entry['offset'])
        table.loc[row, ['CI low', 'CI high']] = limits
        status.loc[row, ['Lower status', 'Upper status']] = kinds
        status.loc[row, ['Lower reason', 'Upper reason']] = [
            reason or f'Mapped from the profile of {table.loc[slot, "Parameter"]} through {entry["relation"]}.'
            for reason in reasons]
