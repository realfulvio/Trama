"""Independent OLS/WLS and separable-exponential references for typed profiles."""
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from io import StringIO
from pathlib import Path
import json

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi.custom_fit import CUSTOM_EQUATION, check_options
from analisi.field_error import FieldError
from analisi.fit_weights import INVERSE_VARIANCE
from analisi.monte_carlo import MonteCarloCancelled
from analisi.parameter_intervals import METHOD, PROFILE, WALD
from analisi.workbench import analyse


FRAME = pd.DataFrame({'X': np.arange(5.), 'Y': [1., 3., 3., 5., 7.], 'SD': [.7, 1., 1.4, .8, 1.2]})
PARAMETERS = [{'name': 'A', 'start': 1., 'fixed': False}, {'name': 'B', 'start': 1., 'fixed': False}]
RECIPE = {'X': 'X', 'Y': 'Y', 'Equation': 'A+B*X', 'Parameters': PARAMETERS,
          'Weighting': 'Unweighted', 'Confidence level (%)': 95., 'Curve points': 51}
STATUS = 'Parameter CI status: All'


def result(frame=FRAME, **options):
    return analyse(CUSTOM_EQUATION, frame, {**RECIPE, METHOD: PROFILE, **options})


class CustomParameterProfileTests(TestCase):
    def test_linear_profiles_match_exact_t_intervals_at_three_levels_and_two_weightings(self):
        for weighting in ('Unweighted', INVERSE_VARIANCE):
            sd = np.ones(len(FRAME)) if weighting == 'Unweighted' else FRAME.SD.to_numpy()
            design = np.column_stack((np.ones(len(FRAME)), FRAME.X)) / sd[:, None]
            response = FRAME.Y.to_numpy() / sd
            beta = np.linalg.lstsq(design, response, rcond=None)[0]
            residual = response-design@beta
            se = np.sqrt(np.diag(np.linalg.inv(design.T@design))*(residual@residual)/3)
            for level in (90., 95., 99.):
                with self.subTest(weighting=weighting, level=level):
                    r = result(**{'Weighting': weighting, 'SD column': 'SD', 'Confidence level (%)': level})
                    self.assertIn(STATUS, r.tables)
                    table = r.tables['Parameters: All']
                    half = stats.t.ppf((1+level/100)/2, 3)*se
                    np.testing.assert_allclose(table[['CI lower', 'CI upper']],
                                               beta[:, None]+half[:, None]*[-1, 1], rtol=2e-5, atol=2e-6)
                    self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Profile root').all().all())

    def test_fixed_coefficient_is_not_refitted_or_counted_as_free(self):
        options = {'Parameters': [{'name': 'A', 'start': .5, 'fixed': True}, PARAMETERS[1]]}
        r = result(**options)
        self.assertIn(STATUS, r.tables)
        table = r.tables['Parameters: All']
        self.assertEqual(table.loc['A', 'Estimate'], .5)
        self.assertTrue(table.loc['A', ['CI lower', 'CI upper']].isna().all())
        self.assertEqual(r.tables[STATUS].loc['A', 'Lower status'], 'Fixed')
        beta = np.dot(FRAME.X, FRAME.Y-.5)/np.dot(FRAME.X, FRAME.X)
        sse = np.sum((FRAME.Y-.5-beta*FRAME.X)**2)
        half = stats.t.ppf(.975, 4)*np.sqrt(sse/4/np.dot(FRAME.X, FRAME.X))
        np.testing.assert_allclose(table.loc['B', ['CI lower', 'CI upper']].to_numpy(float),
                                   [beta-half, beta+half], rtol=2e-5)
        self.assertEqual(r.tables[STATUS].loc['B', 'df'], 4)

    def test_all_fixed_equation_reports_fixed_endpoints_without_inference(self):
        r = result(**{'Parameters': [{'name': 'A', 'start': 1., 'fixed': True},
                                    {'name': 'B', 'start': 1., 'fixed': True}]})
        self.assertIn(STATUS, r.tables)
        self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Fixed').all().all())
        np.testing.assert_array_equal(r.tables['Parameters: All'].Estimate, [1., 1.])

    def test_parameter_bounds_truncate_the_connected_confidence_set(self):
        r = result(**{'Parameters': [{**PARAMETERS[0], 'lower': 0., 'upper': 1.2}, PARAMETERS[1]]})
        self.assertIn(STATUS, r.tables)
        np.testing.assert_allclose(r.tables['Parameters: All'].loc['A', ['CI lower', 'CI upper']].to_numpy(float), [0., 1.2])
        self.assertTrue((r.tables[STATUS].loc['A', ['Lower status', 'Upper status']] == 'Parameter bound').all())

    def test_decay_rate_profile_matches_separable_projection_not_wald(self):
        x = np.arange(9.)/2
        y = 1.5+7*np.exp(-.6*x)+np.array([.1, -.18, .08, .04, -.09, .12, -.05, .07, -.04])
        frame = pd.DataFrame({'X': x, 'Y': y})
        def projected_ss(rate):
            v = np.exp(-rate*x)
            amplitude = np.dot(v, y-1.5)/np.dot(v, v)
            return float(np.sum((y-1.5-amplitude*v)**2))
        minimum = optimize.minimize_scalar(projected_ss, bounds=(.1, 2.), method='bounded',
                                          options={'xatol': 1e-13})
        threshold = minimum.fun*(1+stats.f.ppf(.95, 1, 7)/7)
        roots = [optimize.brentq(lambda k: projected_ss(k)-threshold, .1, minimum.x),
                 optimize.brentq(lambda k: projected_ss(k)-threshold, minimum.x, 2.)]
        options = {'Equation': 'C+A*exp(-K*X)', 'Parameters': [
            {'name': 'C', 'start': 1.5, 'fixed': True},
            {'name': 'A', 'start': 6., 'fixed': False, 'lower': 0.},
            {'name': 'K', 'start': .5, 'fixed': False, 'lower': 0.}]}
        r = result(frame, **options)
        self.assertIn(STATUS, r.tables)
        table = r.tables['Parameters: All']
        np.testing.assert_allclose(table.loc['K', ['CI lower', 'CI upper']].to_numpy(float), roots, rtol=2e-5)
        lo, hi = table.loc['K', ['CI lower', 'CI upper']]
        self.assertGreater(abs((hi-table.loc['K', 'Estimate'])-(table.loc['K', 'Estimate']-lo)), 1e-4)

    def test_common_sd_units_leave_weighted_profile_limits_unchanged(self):
        original = result(**{'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'})
        self.assertIn(STATUS, original.tables)
        for factor in (1e-100, 1e100):
            r = result(FRAME.assign(SD=FRAME.SD*factor), **{'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'})
            np.testing.assert_allclose(r.tables['Parameters: All'][['Estimate', 'CI lower', 'CI upper']],
                                       original.tables['Parameters: All'][['Estimate', 'CI lower', 'CI upper']], rtol=3e-5)

    def test_unknown_interval_method_is_rejected_on_its_field(self):
        with self.assertRaises(FieldError) as caught:
            check_options(FRAME, {**RECIPE, METHOD: 'invented'})
        self.assertEqual(caught.exception.field, METHOD)

    def test_cancellation_event_reaches_the_profile_worker(self):
        event = Event(); event.set()
        with self.assertRaises(MonteCarloCancelled):
            analyse(CUSTOM_EQUATION, FRAME, {**RECIPE, METHOD: PROFILE}, cancel=event)

    def test_active_bound_can_have_a_one_sided_profile_without_inventing_a_wald_se(self):
        frame = FRAME.assign(Y=FRAME.Y-2.)
        r = result(frame, **{'Parameters': [{**PARAMETERS[0], 'lower': 0.}, PARAMETERS[1]]})
        self.assertIn(STATUS, r.tables)
        table, status = r.tables['Parameters: All'], r.tables[STATUS]
        self.assertEqual(table.loc['A', 'Status'], 'At bound')
        self.assertTrue(np.isnan(table.loc['A', 'SE']))
        self.assertEqual(table.loc['A', 'CI lower'], 0.)
        self.assertGreater(table.loc['A', 'CI upper'], 0.)
        self.assertEqual(status.loc['A', 'Lower status'], 'Parameter bound')
        self.assertEqual(status.loc['A', 'Upper status'], 'Profile root')
        self.assertTrue(np.isfinite(table.loc['B', ['CI lower', 'CI upper']].to_numpy(float)).all())

    def test_exhausted_budget_reports_unavailable_limits_and_keeps_point_estimates(self):
        old = analyse(CUSTOM_EQUATION, FRAME, RECIPE)
        with patch('analisi.parameter_intervals.MAX_EVALUATIONS', 1):
            r = result()
        self.assertIn(STATUS, r.tables)
        np.testing.assert_array_equal(r.tables['Parameters: All'].Estimate, old.tables['Parameters: All'].Estimate)
        self.assertTrue(r.tables['Parameters: All'][['CI lower', 'CI upper']].isna().all().all())
        self.assertTrue(r.tables[STATUS]['Lower reason'].str.contains('budget').all())

    def test_grouped_duplicate_indices_and_incomplete_sd_keep_the_same_fits(self):
        frame = pd.concat([FRAME.assign(Group='B'), FRAME.assign(Group='A', Y=FRAME.Y+3)])
        frame.iloc[1, frame.columns.get_loc('SD')] = np.nan
        options = {'Group': 'Group', 'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'}
        old = analyse(CUSTOM_EQUATION, frame, {**RECIPE, **options})
        r = result(frame, **options)
        self.assertIn('Parameter CI status: B', r.tables)
        self.assertIn('Parameter CI status: A', r.tables)
        for label in ('B', 'A'):
            np.testing.assert_array_equal(r.tables[f'Parameters: {label}'].Estimate,
                                          old.tables[f'Parameters: {label}'].Estimate)
            pd.testing.assert_frame_equal(r.tables[f'Residuals: {label}'], old.tables[f'Residuals: {label}'])
            pd.testing.assert_frame_equal(r.tables[f'Curve: {label}'], old.tables[f'Curve: {label}'])
        self.assertEqual(len(r.tables['Residuals: B']), 4)
        self.assertEqual(len(r.tables['Residuals: A']), 5)

    def test_default_and_explicit_wald_keep_the_legacy_four_sheets(self):
        old = analyse(CUSTOM_EQUATION, FRAME, RECIPE)
        explicit = analyse(CUSTOM_EQUATION, FRAME, {**RECIPE, METHOD: WALD})
        self.assertEqual(list(old.tables), ['Parameters: All', 'Fit: All', 'Residuals: All', 'Curve: All'])
        self.assertEqual(list(old.tables), list(explicit.tables))
        for name in old.tables:
            pd.testing.assert_frame_equal(old.tables[name], explicit.tables[name], check_exact=True)

    def test_default_results_match_the_captured_075_tables(self):
        snapshots = json.loads((Path(__file__).parent/'data/custom_profiles_076/legacy-075.json').read_text())
        for case, extra in [('unweighted', {}), ('weighted', {'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'})]:
            r = analyse(CUSTOM_EQUATION, FRAME, {**RECIPE, **extra})
            self.assertEqual(list(r.tables), list(snapshots[case]))
            for name, encoded in snapshots[case].items():
                expected = pd.read_json(StringIO(encoded), orient='split')
                # Finite-difference Jacobians vary slightly across BLAS builds;
                # native 0.75 and the candidate were also compared bit-for-bit.
                pd.testing.assert_frame_equal(r.tables[name], expected, check_dtype=False,
                                               check_names=False, atol=2e-10, rtol=2e-9)

    def test_tiny_coefficient_units_preserve_profile_limits(self):
        frame = FRAME.assign(Y=FRAME.Y*1e-15)
        parameters = [{**p, 'start': 1e-15} for p in PARAMETERS]
        r = result(frame, **{'Parameters': parameters})
        self.assertIn(STATUS, r.tables)
        design = np.column_stack([np.ones(5), FRAME.X])
        # beta=(1, 1.4), residuals=(0, .6, -.8, -.2, .4), SSE=1.2.
        se = np.sqrt(np.diag(np.linalg.inv(design.T@design))*1.2/3)*1e-15
        half = stats.t.ppf(.975, 3)*se
        np.testing.assert_allclose(r.tables['Parameters: All'][['CI lower', 'CI upper']],
                                   np.array([1., 1.4])[:, None]*1e-15+half[:, None]*[-1, 1],
                                   rtol=3e-5, atol=1e-25)

    def test_exact_fit_keeps_its_estimate_without_false_finite_endpoints(self):
        r = result(FRAME.assign(Y=1.), **{'Equation': 'A', 'Parameters': [PARAMETERS[0]]})
        self.assertIn(STATUS, r.tables)
        self.assertEqual(r.tables['Parameters: All'].loc['A', 'Estimate'], 1.)
        self.assertTrue(r.tables['Parameters: All'][['CI lower', 'CI upper']].isna().all().all())
        self.assertEqual(r.tables[STATUS].loc['A', 'Lower status'], 'Unavailable')
        self.assertTrue(r.tables[STATUS].loc['A', 'Lower reason'])
