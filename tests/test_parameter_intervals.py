"""Independent extra-SS oracles and dispatcher compatibility for parameter CIs."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi import stats as engine
from analisi.processing import FieldError
from analisi.workbench import analyse

METHOD = 'Parameter intervals'
LEVEL = 'Parameter confidence level (%)'
WALD, PROFILE = 'Symmetric (Wald)', 'Profile likelihood'
BASE = {'X': 'X', 'Y columns': ['Y'], 'Grouping variables': [], 'Model': 'Straight line',
        'Weighting': 'Unweighted'}
X = np.arange(8., dtype=float)
Y = np.array([1.2, 2.8, 4.2, 5.9, 7.1, 8.7, 10.4, 12.])


def run(data=None, **options):
    return analyse('Nonlinear regression', pd.DataFrame({'X': X, 'Y': Y}) if data is None else data,
                   {**BASE, **options})


class ParameterIntervalContract(unittest.TestCase):
    def test_profile_is_a_real_option_and_linear_intervals_match_ols(self):
        from analisi.workbench import METHODS
        self.assertIn(METHOD, METHODS['Nonlinear regression'])
        for level in (90., 95., 99.):
            result = run(**{METHOD: PROFILE, LEVEL: level})
            table = result.tables['Parameters: All']
            design = np.column_stack([np.ones(len(X)), X])
            beta = np.linalg.lstsq(design, Y, rcond=None)[0]
            residual = Y - design @ beta
            se = np.sqrt(np.diag(np.linalg.inv(design.T @ design)) * (residual @ residual) / (len(X)-2))
            delta = stats.t.ppf((1+level/100)/2, len(X)-2) * se
            np.testing.assert_allclose(table[f'CI {level:g}% low'], beta-delta, rtol=2e-5, atol=1e-8)
            np.testing.assert_allclose(table[f'CI {level:g}% high'], beta+delta, rtol=2e-5, atol=1e-8)
            self.assertIn('Parameter CI status: All', result.tables)

    def test_legacy_wald95_is_identical_and_does_not_profile(self):
        legacy = run()
        modern = run(**{METHOD: WALD, LEVEL: 95.})
        self.assertEqual(list(legacy.tables), list(modern.tables))
        for title in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[title], modern.tables[title], check_exact=True)

    def test_nondefault_wald_level_uses_existing_fit_covariance(self):
        result = run(**{METHOD: WALD, LEVEL: 90.})
        table = result.tables['Parameters: All']
        delta = stats.t.ppf(.95, len(X)-2) * table['SE'].to_numpy()
        np.testing.assert_allclose(table['CI 90% low'], table['Estimate']-delta)
        self.assertNotIn('CI 95% low', table)

    def test_profile_only_refits_nuisance_not_original_point_estimates(self):
        with patch('analisi.stats.nonlinear', wraps=engine.nonlinear) as fitting:
            result = run(**{METHOD: PROFILE})
            self.assertEqual(fitting.call_count, 1)
        original = run()
        for col in ('Estimate', 'SE'):
            pd.testing.assert_series_equal(result.tables['Parameters: All'][col], original.tables['Parameters: All'][col])
        pd.testing.assert_frame_equal(result.tables['Fit: All'], original.tables['Fit: All'])
        np.testing.assert_array_equal(result.figure.axes[0].lines[0].get_xydata(), original.figure.axes[0].lines[0].get_xydata())

    def test_decay_rate_limits_match_independent_linear_nuisance_oracle(self):
        x = np.arange(0., 6.5, .5)
        y = 2+8*np.exp(-.7*x) + np.array([.15,-.12,.2,-.14,.08,.17,-.11,.05,-.07,.12,-.15,.08,-.04])
        data = pd.DataFrame({'X': x, 'Y': y})
        result = run(data, **{'Model':'One-phase decay', METHOD:PROFILE})
        table = result.tables['Parameters: All']
        rate = table.loc['Rate','Estimate']
        def sse(k):
            a = np.column_stack([np.ones(len(x)), np.exp(-k*x)])
            residual = y-a@np.linalg.lstsq(a,y,rcond=None)[0]
            return float(residual@residual)
        minimum = optimize.minimize_scalar(sse,bounds=(.1,2),method='bounded',options={'xatol':1e-14}).fun
        target = minimum*(1+stats.f.ppf(.95,1,len(x)-3)/(len(x)-3))
        low = optimize.brentq(lambda k:sse(k)-target,.1,rate)
        high = optimize.brentq(lambda k:sse(k)-target,rate,2)
        self.assertGreater(abs((high-rate)-(rate-low)),1e-5)
        np.testing.assert_allclose(table.loc['Rate',['CI 95% low','CI 95% high']].to_numpy(float),[low,high],rtol=3e-5)

    def test_four_parameter_midpoint_matches_separable_least_squares_oracle(self):
        x = np.geomspace(.01, 100., 21)
        y = 1+9/(1+(2/x)**1.3)+.12*np.sin(np.arange(len(x))*1.7)
        result = run(pd.DataFrame({'X':x,'Y':y}), **{'Model':'Stimulation (variable slope)', METHOD:PROFILE})
        table = result.tables['Parameters: All']
        mid = table.loc['EC50','Estimate']
        def profile_ss(midpoint):
            def ss(log_slope):
                h = 1/(1+(midpoint/x)**np.exp(log_slope))
                design = np.column_stack([np.ones(len(x)),h])
                residual = y-design@np.linalg.lstsq(design,y,rcond=None)[0]
                return residual@residual
            return optimize.minimize_scalar(ss,bounds=(-3.,3.),method='bounded',
                                            options={'xatol':1e-12}).fun
        best = optimize.minimize_scalar(profile_ss,bounds=(1.,3.),method='bounded',
                                        options={'xatol':1e-12}).fun
        target = best*(1+stats.f.ppf(.95,1,len(x)-4)/(len(x)-4))
        roots = [optimize.brentq(lambda m:profile_ss(m)-target,a,b)
                 for a,b in ((1.,mid),(mid,3.))]
        np.testing.assert_allclose(table.loc['EC50',['CI 95% low','CI 95% high']].to_numpy(float),
                                   roots, rtol=3e-5)
        self.assertTrue(result.tables['Parameter CI status: All']['Lower status'].eq('Profile root').all())

    def test_profile_rejects_unsupported_weighting_on_its_field(self):
        for weighting in ('1/abs(Y)', '1/Y²', 'Inverse variance (column)', '1/abs(Yfit)', '1/Yfit²'):
            with self.subTest(weighting=weighting),self.assertRaises(FieldError) as cm:
                run(**{METHOD:PROFILE,'Weighting':weighting})
            self.assertEqual(cm.exception.field, 'Weighting')

    def test_invalid_level_and_method_do_not_run_the_fit(self):
        for key,value in ((LEVEL,0),(LEVEL,100),(LEVEL,'nan'),(LEVEL,float('inf')),(LEVEL,True),(METHOD,'unknown')):
            with self.subTest(value=value),patch('analisi.stats.nonlinear') as fitter,self.assertRaises(FieldError):
                run(**{key:value})
            fitter.assert_not_called()



class ParameterIntervalEdges(unittest.TestCase):
    def test_one_parameter_profile_is_analytic_without_nuisance_refits(self):
        with patch('analisi.parameter_intervals.optimize.least_squares', side_effect=AssertionError('No nuisance parameters')):
            result = run(**{'Model':'Horizontal line', METHOD:PROFILE})
        table = result.tables['Parameters: All']
        half = stats.t.ppf(.975,len(Y)-1)*np.std(Y,ddof=1)/np.sqrt(len(Y))
        np.testing.assert_allclose(table.loc['Mean',['CI 95% low','CI 95% high']].to_numpy(float),[np.mean(Y)-half,np.mean(Y)+half],rtol=2e-6)

    def test_complete_cases_and_grouped_responses_use_separate_profiles(self):
        data = pd.DataFrame({'X':np.tile(X,2),'Y':np.r_[Y,Y+3], 'G':['A']*8+['B']*8})
        data.loc[2,'Y'] = np.nan
        result = run(data, **{METHOD:PROFILE,'Grouping variables':['G']})
        for name in ('A','B'):
            expected = run(data[data.G==name].dropna(), **{METHOD:PROFILE})
            pd.testing.assert_frame_equal(result.tables[f'Parameters: {name}'],expected.tables['Parameters: All'])
            pd.testing.assert_frame_equal(result.tables[f'Parameter CI status: {name}'],expected.tables['Parameter CI status: All'])

    def test_small_response_units_keep_the_same_standardized_limits(self):
        first = run(**{METHOD:PROFILE}).tables['Parameters: All']
        for factor in (1e-8,1e7):
            other = run(pd.DataFrame({'X':X,'Y':Y*factor}),**{METHOD:PROFILE}).tables['Parameters: All']
            np.testing.assert_allclose(other.to_numpy(float)/factor,first.to_numpy(float),rtol=3e-5,atol=1e-7)

    def test_budget_exhaustion_keeps_estimates_and_does_not_substitute_wald(self):
        original = run().tables['Parameters: All']
        with patch('analisi.parameter_intervals.MAX_EVALUATIONS',1):
            result = run(**{METHOD:PROFILE})
        actual = result.tables['Parameters: All']
        self.assertTrue(actual[['CI 95% low','CI 95% high']].isna().all().all())
        pd.testing.assert_frame_equal(actual[['Estimate','SE']],original[['Estimate','SE']])
        status = result.tables['Parameter CI status: All']
        self.assertTrue(status['Lower reason'].str.contains('budget').all())

    def test_failed_nuisance_fit_is_explicit_and_never_returns_a_false_bound(self):
        with patch('analisi.parameter_intervals.optimize.least_squares',side_effect=ValueError('Solver did not converge')):
            result = run(**{METHOD:PROFILE})
        status = result.tables['Parameter CI status: All']
        self.assertEqual(set(status['Lower status']), {'Unavailable'})
        self.assertTrue(result.tables['Parameters: All']['CI 95% low'].isna().all())
        self.assertTrue(status['Lower reason'].str.contains('Solver did not converge').all())

    def test_explicit_profile_does_not_modify_confirmed_fit_frames_or_covariance(self):
        from analisi.parameter_intervals import Settings,parameter_outputs
        fit = engine.nonlinear(pd.DataFrame({'X':X,'Y':Y}), 'X','Y','Straight line')['All']
        before = [frame.copy(deep=True) for frame in (fit.parameters,fit.data,fit.residuals)]
        covariance = fit.covariance.copy()
        parameter_outputs(fit,'Straight line',Settings(PROFILE,95))
        for actual,expected in zip((fit.parameters,fit.data,fit.residuals),before):pd.testing.assert_frame_equal(actual,expected,check_exact=True)
        np.testing.assert_array_equal(fit.covariance,covariance)

    def test_reaching_a_parameter_bound_is_not_reported_as_a_profile_root(self):
        from analisi.parameter_intervals import Settings,parameter_outputs
        from analisi.curve_models import CurveModel,MODELS
        spec = CurveModel(lambda x,mean:np.full_like(x,mean),('Mean',),lambda x,y:(max(.01,np.mean(y)),),((0.,),(np.inf,)))
        data = pd.DataFrame({'X':np.arange(6.),'Y':[-.3,.2,.5,-.2,.1,.3]})
        with patch.dict(MODELS,{'Bounded mean':spec}):
            fit = engine.nonlinear(data,'X','Y','Bounded mean')['All']
            params,status = parameter_outputs(fit,'Bounded mean',Settings(PROFILE,95))
        self.assertEqual(params.loc['Mean','CI 95% low'],0)
        self.assertEqual(status.loc['Mean','Lower status'],'Parameter bound')
        self.assertEqual(status.loc['Mean','Upper status'],'Profile root')
        self.assertIn('bound',status.loc['Mean','Lower reason'])

    def test_no_search_bracket_is_not_labeled_infinite(self):
        with patch('analisi.parameter_intervals.MAX_EXPANSIONS',0):
            result = run(**{METHOD:PROFILE})
        table = result.tables['Parameters: All']
        self.assertTrue(table['CI 95% high'].isna().all())
        reason = result.tables['Parameter CI status: All']['Upper reason']
        self.assertTrue(reason.str.contains('not bracketed').all())
        self.assertFalse(reason.str.contains('infinite').any())

    def test_profile_cancellation_propagates_without_partial_results(self):
        import threading
        from analisi.monte_carlo import MonteCarloCancelled
        from analisi.parameter_intervals import ProfileBudget
        event = threading.Event()
        original = ProfileBudget.consume
        count = 0
        def consume(budget, n):
            nonlocal count
            count += 1
            if count == 4:
                event.set()
            return original(budget, n)
        with patch.object(ProfileBudget, 'consume', consume), self.assertRaises(MonteCarloCancelled):
            analyse('Nonlinear regression', pd.DataFrame({'X': X, 'Y': Y}),
                    {**BASE, METHOD: PROFILE}, cancel=event)
        self.assertEqual(count, 4)

    def test_all_responses_share_one_request_budget(self):
        from analisi.parameter_intervals import ProfileBudget
        calls=[]
        original=ProfileBudget.consume
        def consume(budget,n):
            calls.append(id(budget));return original(budget,n)
        data=pd.DataFrame({'X':X,'Y':Y,'Other':2*Y+1})
        with patch.object(ProfileBudget,'consume',consume):
            result=run(data,**{METHOD:PROFILE,'Y columns':['Y','Other']})
        self.assertGreater(len(calls),10)
        self.assertEqual(len(set(calls)),1)
        self.assertTrue(any('Parameter CI status' in name for name in result.tables))


if __name__ == '__main__':
    unittest.main()
