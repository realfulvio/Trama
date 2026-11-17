"""Joint profiles: independent design-matrix and separable-decay references."""
from threading import Event
from unittest import TestCase
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi import global_custom_fit as engine, global_uncertainty as response
from analisi.field_error import FieldError
from analisi.fit_weights import INVERSE_VARIANCE
from analisi.monte_carlo import MonteCarloCancelled
from analisi.parameter_intervals import METHOD, PROFILE, WALD
from analisi.workbench import analyse


FRAME = pd.DataFrame({'X': np.tile(np.arange(6.), 2),
                      'Y': [1.1, 2.8, 5.2, 6.9, 9.1, 10.9, 4.8, 7.1, 8.9, 11.2, 12.8, 15.2],
                      'Group': ['A']*6+['B']*6,
                      'SD': [1., 2., 1., 2., 1., 2., .8, 1.5, 1.1, 1.8, .9, 2.1]})
PARAMETERS = [{'name': 'A', 'start': 1., 'fixed': False, 'shared': False},
              {'name': 'B', 'start': 2., 'fixed': False, 'shared': True}]
RECIPE = {'X': 'X', 'Y': 'Y', 'Group': 'Group', 'Equation': 'A+B*X', 'Parameters': PARAMETERS,
          'Series constraints': [], 'Weighting': 'Unweighted', 'Confidence level (%)': 95., 'Curve points': 21}
STATUS = 'Parameter CI status'


def fit(frame=FRAME, **options):
    return analyse(engine.GLOBAL_CUSTOM_EQUATION, frame, {**RECIPE, METHOD: PROFILE, **options})


class GlobalCustomProfileTests(TestCase):
    def test_joint_linear_profiles_match_exact_t_intervals_with_global_df(self):
        design = np.column_stack([FRAME.X, (FRAME.Group == 'A').astype(float), (FRAME.Group == 'B').astype(float)])
        for weighting in ('Unweighted', INVERSE_VARIANCE):
            sd = np.ones(len(FRAME)) if weighting == 'Unweighted' else FRAME.SD.to_numpy()
            matrix, y = design/sd[:, None], FRAME.Y.to_numpy()/sd
            beta = np.linalg.lstsq(matrix, y, rcond=None)[0]
            residual = y-matrix@beta
            se = np.sqrt(np.diag(np.linalg.inv(matrix.T@matrix))*(residual@residual)/9)
            for level in (90., 95., 99.):
                with self.subTest(weighting=weighting, level=level):
                    r = fit(**{'Weighting': weighting, 'SD column': 'SD', 'Confidence level (%)': level})
                    self.assertIn(STATUS, r.tables)
                    half = stats.t.ppf((1+level/100)/2, 9)*se
                    np.testing.assert_allclose(r.tables['Parameters'][['CI low', 'CI high']],
                                               beta[:, None]+half[:, None]*[-1, 1], rtol=3e-5, atol=3e-6)
                    self.assertTrue((r.tables[STATUS]['df'] == 9).all())
                    self.assertEqual(r.tables[STATUS]['Scope'].tolist(), ['Shared', 'Local', 'Local'])
                    self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Profile root').all().all())

    def test_global_and_series_fixed_coefficients_are_excluded_from_df(self):
        params = [*PARAMETERS, {'name': 'C', 'start': 1., 'fixed': True, 'shared': False}]
        options = {'Equation': 'C+A+B*X', 'Parameters': params,
                   'Series constraints': [{'series': 'A', 'parameters': {'A': {'fixed': .4}}}]}
        r = fit(**options)
        self.assertIn(STATUS, r.tables)
        design = np.column_stack([FRAME.X, (FRAME.Group == 'B').astype(float)])
        offset = np.where(FRAME.Group == 'A', 1.4, 1.)
        beta = np.linalg.lstsq(design, FRAME.Y-offset, rcond=None)[0]
        error = FRAME.Y-offset-design@beta
        delta = stats.t.ppf(.975, 10)*np.sqrt(np.diag(np.linalg.inv(design.T@design))*(error@error)/10)
        p = r.tables['Parameters']
        np.testing.assert_allclose(p.iloc[:2][['CI low', 'CI high']], beta[:, None]+delta[:, None]*[-1, 1], rtol=3e-5)
        self.assertTrue((r.tables[STATUS]['df'] == 10).all())
        self.assertTrue((r.tables[STATUS].iloc[2:][['Lower status', 'Upper status']] == 'Fixed').all().all())
        self.assertTrue(p.iloc[2:][['CI low', 'CI high']].isna().all().all())

    def test_shared_parameter_profile_respects_the_intersection_of_series_bounds(self):
        constraints = [{'series': 'A', 'parameters': {'B': {'lower': 1.995}}},
                       {'series': 'B', 'parameters': {'B': {'upper': 2.005}}}]
        r = fit(**{'Series constraints': constraints})
        self.assertIn(STATUS, r.tables)
        np.testing.assert_allclose(r.tables['Parameters'].iloc[0][['CI low', 'CI high']].to_numpy(float), [1.995, 2.005])
        self.assertTrue((r.tables[STATUS].iloc[0][['Lower status', 'Upper status']] == 'Parameter bound').all())

    def test_shared_decay_rate_matches_joint_separable_projection(self):
        x = np.arange(8.)/2
        noise = np.array([.1, -.14, .08, -.07, .06, -.1, .05, .02])
        y1, y2 = 1.5+7*np.exp(-.6*x)+noise, 1.5+11*np.exp(-.6*x)-noise*.8
        frame = pd.DataFrame({'X': np.tile(x, 2), 'Y': np.r_[y1, y2], 'Group': ['A']*8+['B']*8})
        def objective(rate):
            v = np.exp(-rate*x)
            return sum(float(np.sum((y-1.5-v*np.dot(v, y-1.5)/np.dot(v, v))**2)) for y in (y1, y2))
        minimum = optimize.minimize_scalar(objective, bounds=(.1, 2.), method='bounded', options={'xatol': 1e-13})
        threshold = minimum.fun*(1+stats.f.ppf(.95, 1, 13)/13)
        roots = [optimize.brentq(lambda k: objective(k)-threshold, .1, minimum.x),
                 optimize.brentq(lambda k: objective(k)-threshold, minimum.x, 2.)]
        params = [{'name': 'A', 'start': 8., 'fixed': False, 'shared': False, 'lower': 0.},
                  {'name': 'K', 'start': .5, 'fixed': False, 'shared': True, 'lower': 0.},
                  {'name': 'C', 'start': 1.5, 'fixed': True, 'shared': False}]
        r = fit(frame, **{'Equation': 'C+A*exp(-K*X)', 'Parameters': params})
        self.assertIn(STATUS, r.tables)
        np.testing.assert_allclose(r.tables['Parameters'].iloc[0][['CI low', 'CI high']].to_numpy(float), roots, rtol=3e-5)
        self.assertTrue((r.tables[STATUS]['df'] == 13).all())

    def test_more_than_eight_joint_coordinates_use_the_global_profile_budget(self):
        x = np.arange(4.)
        frame = pd.concat([pd.DataFrame({'X': x, 'Y': i+2*x+[.1, -.1, -.1, .1], 'Group': str(i)})
                           for i in range(9)], ignore_index=True)
        r = fit(frame)
        self.assertIn(STATUS, r.tables)
        self.assertEqual(len(r.tables[STATUS]), 10)
        self.assertTrue(np.isfinite(r.tables['Parameters'][['CI low', 'CI high']]).all().all())
        self.assertTrue((r.tables[STATUS]['df'] == 26).all())

    def test_weighted_profiles_are_invariant_to_common_sd_units(self):
        r = fit(**{'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'})
        self.assertIn(STATUS, r.tables)
        for factor in (1e-100, 1e100):
            changed = fit(FRAME.assign(SD=FRAME.SD*factor), **{'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'})
            np.testing.assert_allclose(changed.tables['Parameters'][['Estimate', 'CI low', 'CI high']],
                                       r.tables['Parameters'][['Estimate', 'CI low', 'CI high']], rtol=3e-5)

    def test_tiny_coefficients_preserve_physical_units(self):
        reference = fit()
        factor = 1e-12
        r = fit(FRAME.assign(Y=FRAME.Y*factor), **{
            'Parameters': [{**c, 'start': c['start']*factor} for c in PARAMETERS]})
        np.testing.assert_allclose(r.tables['Parameters'][['Estimate', 'CI low', 'CI high']]/factor,
                                   reference.tables['Parameters'][['Estimate', 'CI low', 'CI high']], rtol=3e-5)

    def test_all_shared_and_all_local_coordinates_use_the_joint_residual_variance(self):
        for shared in (True, False):
            params = [{**c, 'shared': shared} for c in PARAMETERS]
            design = (np.column_stack([np.ones(len(FRAME)), FRAME.X]) if shared else np.column_stack([
                (FRAME.Group == 'A').astype(float), FRAME.X*(FRAME.Group == 'A'),
                (FRAME.Group == 'B').astype(float), FRAME.X*(FRAME.Group == 'B')]))
            beta = np.linalg.lstsq(design, FRAME.Y, rcond=None)[0]
            resid = FRAME.Y-design@beta
            df = len(FRAME)-len(beta)
            delta = stats.t.isf(.025, df)*np.sqrt(np.diag(np.linalg.inv(design.T@design))*(resid@resid)/df)
            r = fit(**{'Parameters': params})
            np.testing.assert_allclose(r.tables['Parameters'][['CI low', 'CI high']],
                                       beta[:, None]+delta[:, None]*[-1, 1], rtol=3e-5)
            self.assertTrue((r.tables[STATUS]['df'] == df).all())

    def test_profile_cancellation_is_propagated_through_the_global_dispatcher(self):
        cancel = Event(); cancel.set()
        with self.assertRaises(MonteCarloCancelled):
            analyse(engine.GLOBAL_CUSTOM_EQUATION, FRAME, {**RECIPE, METHOD: PROFILE}, cancel=cancel)

    def test_profile_budget_preflight_counts_total_used_rows(self):
        large = pd.concat([FRAME]*417, ignore_index=True)
        with self.assertRaises(FieldError) as caught:
            engine.check_options(large, {**RECIPE, METHOD: PROFILE})
        self.assertEqual(caught.exception.field, METHOD)
        unused = pd.DataFrame({'X': 1., 'Y': [None]*6000, 'Group': 'A'})
        self.assertIsNotNone(engine.check_options(pd.concat([FRAME, unused], ignore_index=True), {**RECIPE, METHOD: PROFILE}))

    def test_unknown_profile_method_is_a_field_error(self):
        with self.assertRaises(FieldError) as caught:
            engine.check_options(FRAME, {**RECIPE, METHOD: 'invented'})
        self.assertEqual(caught.exception.field, METHOD)

    def test_wald_and_response_outputs_remain_unchanged(self):
        options = {**RECIPE, response.CURVE_BAND: response.CONFIDENCE, response.RESPONSE_LEVEL: 90.}
        old = analyse(engine.GLOBAL_CUSTOM_EQUATION, FRAME, options)
        symmetric = analyse(engine.GLOBAL_CUSTOM_EQUATION, FRAME, {**options, METHOD: WALD})
        for name in old.tables:
            pd.testing.assert_frame_equal(old.tables[name], symmetric.tables[name], check_exact=True)
        profiled = fit(**{response.CURVE_BAND: response.CONFIDENCE, response.RESPONSE_LEVEL: 90.})
        self.assertIn(STATUS, profiled.tables)
        for name in ('Covariance', 'Residuals', 'Curve', response.BANDS_SHEET, response.BAND_SETTINGS_SHEET):
            pd.testing.assert_frame_equal(old.tables[name], profiled.tables[name], check_exact=True)

    def test_bound_profiles_keep_original_covariance_rule_and_identify_the_endpoint(self):
        constraints = [{'series': 'A', 'parameters': {'B': {'upper': 1.9}}}]
        r = fit(**{'Parameters': [{**PARAMETERS[0]}, {**PARAMETERS[1], 'start': 1.8}],
                   'Series constraints': constraints})
        parameters = r.tables['Parameters']
        self.assertEqual(parameters.iloc[0]['Status'], 'At bound')
        self.assertTrue(parameters.SE.isna().all())
        self.assertTrue(r.tables['Covariance'].isna().all().all())
        self.assertTrue(np.isfinite(parameters[['CI low', 'CI high']]).all().all())
        self.assertEqual(r.tables[STATUS].iloc[0]['Upper status'], 'Parameter bound')
        self.assertAlmostEqual(parameters.iloc[0]['CI high'], 1.9)

    def test_all_fixed_and_roundoff_perfect_fits_do_not_invent_uncertainty(self):
        fixed = [{**c, 'fixed': True, 'shared': False} for c in PARAMETERS]
        r = fit(**{'Parameters': fixed})
        self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Fixed').all().all())
        self.assertTrue(r.tables['Parameters'][['CI low', 'CI high']].isna().all().all())
        perfect = FRAME.assign(Y=np.where(FRAME.Group == 'A', 1., 5.)+2*FRAME.X)
        r = fit(perfect)
        self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Unavailable').all().all())
        self.assertTrue(r.tables['Parameters'][['CI low', 'CI high']].isna().all().all())

    def test_exhausted_budget_marks_limits_unavailable_without_wald_substitution(self):
        with patch('analisi.parameter_intervals.MAX_EVALUATIONS', 1):
            r = fit()
        self.assertTrue(r.tables['Parameters'][['CI low', 'CI high']].isna().all().all())
        self.assertTrue((r.tables[STATUS][['Lower status', 'Upper status']] == 'Unavailable').all().all())
        self.assertTrue(r.tables[STATUS]['Lower reason'].str.contains('budget').all())
        self.assertTrue(np.isfinite(r.tables['Parameters'].Estimate).all())

    def test_joint_coordinate_budget_is_checked_before_a_fit(self):
        params = [{'name': chr(65+i), 'start': 1., 'fixed': False, 'shared': False} for i in range(8)]
        frame = pd.concat([pd.DataFrame({'X': np.arange(10.), 'Y': np.arange(10.), 'Group': str(i)})
                           for i in range(5)], ignore_index=True)
        options = {**RECIPE, METHOD: PROFILE, 'Parameters': params,
                   'Equation': '+'.join(f'{c["name"]}*X**{i}' for i, c in enumerate(params))}
        with patch.object(engine, '_solve', side_effect=AssertionError('Budget must be checked first')):
            for action in (engine.check_options, engine.global_custom_fit):
                with self.assertRaises(FieldError) as error:
                    action(frame, options)
                self.assertEqual(error.exception.field, METHOD)
                self.assertIn('32', str(error.exception))

    def test_missing_sd_and_duplicate_source_rows_keep_one_confirmed_fit(self):
        frame = FRAME.iloc[[0, 6, 1, 7, 2, 8, 3, 9, 4, 10, 5, 11]].copy()
        frame.index = [4, 4, 8, 8, 10, 10, 20, 20, 30, 30, 40, 40]
        frame.iloc[2, frame.columns.get_loc('SD')] = np.nan
        options = {'Weighting': INVERSE_VARIANCE, 'SD column': 'SD'}
        original = frame.copy(deep=True)
        with patch.object(engine, '_solve', wraps=engine._solve) as solve:
            r = fit(frame, **options)
        self.assertEqual(solve.call_count, 1)
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(r.tables['Residuals']['Source row'].tolist(), [4, 10, 20, 30, 40, 4, 8, 10, 20, 30, 40])
        self.assertTrue((r.tables[STATUS]['df'] == 8).all())
        self.assertTrue(np.isfinite(r.tables['Parameters'][['CI low', 'CI high']]).all().all())
