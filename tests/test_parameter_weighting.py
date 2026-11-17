"""Independent WLS/IRLS oracles for conditional weighted parameter intervals."""
from dataclasses import replace
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi import stats as engine
from analisi.fit_weights import (UNWEIGHTED, INVERSE_VARIANCE, OBSERVED_WEIGHTINGS,
                                 FITTED_WEIGHTINGS, INFERENCE_WEIGHTS)
from analisi.parameter_intervals import METHOD, LEVEL, PROFILE, WALD, Settings, parameter_outputs
from analisi.workbench import analyse

X = np.arange(8.)
Y = np.array([2.2,3.5,6.1,6.9,9.5,10.3,13.1,14.])
SD = np.array([.7,1.2,.9,1.7,.8,1.5,1.1,2.])
BASE = {'X':'X','Y columns':['Y'],'Grouping variables':[], 'Model':'Straight line'}
FRAME = pd.DataFrame({'X':X,'Y':Y,'SD':SD})


def line_oracle(x,y,weighting,sd=None):
    design=np.column_stack([np.ones(len(x)),x])
    beta=np.linalg.lstsq(design,y,rcond=None)[0]
    for _ in range(500):
        if weighting == UNWEIGHTED:scale=np.ones(len(x))
        elif weighting == INVERSE_VARIANCE:scale=np.asarray(sd)
        else:
            source=design@beta if weighting in FITTED_WEIGHTINGS else y
            scale=np.abs(source)**(.5 if weighting in ('1/abs(Y)','1/abs(Yfit)') else 1.)
        updated=np.linalg.lstsq(design/scale[:,None],y/scale,rcond=None)[0]
        if weighting not in FITTED_WEIGHTINGS or np.max(np.abs(updated-beta))<1e-12:
            beta=updated;break
        beta=updated
    else:raise AssertionError('Independent IRLS oracle failed')
    return fixed_line_oracle(x,y,scale)


def fixed_line_oracle(x,y,scale):
    design=np.column_stack([np.ones(len(x)),x]);a=design/scale[:,None];b=y/scale
    beta=np.linalg.lstsq(a,b,rcond=None)[0]
    residual=b-a@beta
    covariance=np.linalg.inv(a.T@a)*(residual@residual)/(len(x)-2)
    return beta,np.sqrt(np.diag(covariance)),scale


def run(frame=FRAME,weighting=INVERSE_VARIANCE,**options):
    return analyse('Nonlinear regression',frame,{**BASE,'Weighting':weighting,'SD column':'SD',METHOD:PROFILE,**options})


class WeightedParameterIntervals(unittest.TestCase):
    def test_all_fixed_and_fitted_weightings_match_conditional_wls_intervals(self):
        for mode in (INVERSE_VARIANCE,*OBSERVED_WEIGHTINGS,*FITTED_WEIGHTINGS):
            for level in (90.,95.,99.):
                with self.subTest(mode=mode,level=level):
                    table=run(weighting=mode,**{LEVEL:level}).tables['Parameters: All']
                    beta,se,_=line_oracle(X,Y,mode,SD)
                    half=stats.t.isf((100-level)/200,len(X)-2)*se
                    np.testing.assert_allclose(table.Estimate,beta,rtol=3e-6,atol=1e-7)
                    np.testing.assert_allclose(table[f'CI {level:g}% low'],beta-half,rtol=4e-5,atol=2e-7)
                    np.testing.assert_allclose(table[f'CI {level:g}% high'],beta+half,rtol=4e-5,atol=2e-7)

    def test_negative_response_weights_use_magnitudes(self):
        for mode in (*OBSERVED_WEIGHTINGS,*FITTED_WEIGHTINGS):
            table=run(FRAME.assign(Y=-Y),weighting=mode).tables['Parameters: All']
            beta,se,_=line_oracle(X,-Y,mode)
            half=stats.t.isf(.025,len(X)-2)*se
            np.testing.assert_allclose(table['CI 95% low'],beta-half,rtol=4e-5)
            np.testing.assert_allclose(table['CI 95% high'],beta+half,rtol=4e-5)

    def test_sd_common_scale_does_not_change_profile(self):
        expected=run().tables['Parameters: All']
        for factor in (1e-100,1e100):
            actual=run(FRAME.assign(SD=SD*factor)).tables['Parameters: All']
            np.testing.assert_allclose(actual,expected,rtol=3e-5,atol=1e-7)

    def test_original_irls_is_run_once_and_profiles_do_not_iterate_weights_again(self):
        with patch('analisi.stats.iterate_weights',wraps=engine.iterate_weights) as irls:
            report=run(weighting=FITTED_WEIGHTINGS[1])
        self.assertEqual(irls.call_count,1)
        self.assertIn('Parameter CI status: All',report.tables)

    def test_fit_retains_an_independent_readonly_copy_of_exact_frozen_scales(self):
        scales=np.array([.8,1.,1.3,.9,2.,1.5,1.1,1.7])
        fit,_=engine._fit_once(FRAME,'X','Y','Straight line','All',None,
                               weighting=FITTED_WEIGHTINGS[1],frozen=scales,precise=True)
        self.assertFalse(np.shares_memory(scales,fit.residual_scales))
        np.testing.assert_array_equal(fit.residual_scales,scales)
        self.assertFalse(fit.residual_scales.flags.writeable)
        with patch('analisi.fit_weights.fitted_scales',side_effect=AssertionError('Weights must remain frozen')):
            table,status=parameter_outputs(fit,'Straight line',Settings(PROFILE,95))
        beta,se,_=fixed_line_oracle(X,Y,scales)
        half=stats.t.isf(.025,len(X)-2)*se
        np.testing.assert_allclose(table['CI 95% low'],beta-half,rtol=3e-5)
        self.assertEqual(set(status['Inference']),{INFERENCE_WEIGHTS})

    def test_missing_scales_never_silently_produces_unweighted_intervals(self):
        fit=engine.nonlinear(FRAME,'X','Y','Straight line',weighting=INVERSE_VARIANCE,sigma='SD')['All']
        table,status=parameter_outputs(replace(fit,residual_scales=None),'Straight line',Settings(PROFILE,95))
        self.assertTrue(table[['CI 95% low','CI 95% high']].isna().all().all())
        self.assertTrue(status['Lower reason'].str.contains('scales').all())
        pd.testing.assert_series_equal(table.Estimate,fit.parameters.Estimate)

    def test_invalid_stored_scales_are_unavailable_with_point_fit_preserved(self):
        fit=engine.nonlinear(FRAME,'X','Y','Straight line',weighting=INVERSE_VARIANCE,sigma='SD')['All']
        for bad in (np.ones(3),np.zeros(len(X)),np.full(len(X),np.inf),-SD,np.array(["bad"]*len(X))):
            with self.subTest(scales=bad):
                table,status=parameter_outputs(replace(fit,residual_scales=bad),'Straight line',Settings(PROFILE,95))
                self.assertTrue(table['CI 95% low'].isna().all())
                self.assertEqual(set(status['Lower status']),{'Unavailable'})

    def test_duplicate_source_indices_complete_cases_and_groups_keep_scale_alignment(self):
        frame=pd.concat([FRAME.assign(G='A'),FRAME.assign(Y=Y+4,G='B')],ignore_index=True)
        frame.index=['same']*len(frame)
        frame.iloc[2,frame.columns.get_loc('Y')]=np.nan
        report=run(frame,**{'Grouping variables':['G']})
        for group in ('A','B'):
            part=frame[frame.G==group].dropna()
            beta,se,_=line_oracle(part.X.to_numpy(),part.Y.to_numpy(),INVERSE_VARIANCE,part.SD.to_numpy())
            half=stats.t.isf(.025,len(part)-2)*se
            np.testing.assert_allclose(report.tables[f'Parameters: {group}']['CI 95% low'],beta-half,rtol=4e-5)

    def test_default_weighted_wald95_is_unchanged(self):
        for mode in (INVERSE_VARIANCE,*OBSERVED_WEIGHTINGS,*FITTED_WEIGHTINGS):
            frame=FRAME.copy()
            original=analyse('Nonlinear regression',frame,{**BASE,'Weighting':mode,'SD column':'SD'})
            report=run(weighting=mode,**{METHOD:WALD})
            self.assertEqual(list(original.tables),list(report.tables))
            for name,table in original.tables.items():pd.testing.assert_frame_equal(table,report.tables[name],check_exact=True)

    def test_weighted_decay_rate_matches_separable_nuisance_oracle(self):
        x=np.arange(0.,6.5,.5);sigma=.5+.1*x
        y=2+8*np.exp(-.7*x)+np.array([.15,-.12,.2,-.14,.08,.17,-.11,.05,-.07,.12,-.15,.08,-.04])
        report=run(pd.DataFrame({'X':x,'Y':y,'SD':sigma}),**{'Model':'One-phase decay'})
        def ss(rate):
            a=np.column_stack([np.ones(len(x)),np.exp(-rate*x)])/sigma[:,None]
            b=y/sigma;r=b-a@np.linalg.lstsq(a,b,rcond=None)[0]
            return r@r
        minimum=optimize.minimize_scalar(ss,bounds=(.1,2),method='bounded',options={'xatol':1e-12}).fun
        target=minimum*(1+stats.f.ppf(.95,1,len(x)-3)/(len(x)-3))
        estimate=report.tables['Parameters: All'].loc['Rate','Estimate']
        roots=[optimize.brentq(lambda k:ss(k)-target,a,b) for a,b in ((.1,estimate),(estimate,2))]
        np.testing.assert_allclose(report.tables['Parameters: All'].loc['Rate',['CI 95% low','CI 95% high']].to_numpy(float),roots,rtol=4e-5)

    def test_weighted_inference_is_identified_in_status(self):
        for mode in (INVERSE_VARIANCE,*OBSERVED_WEIGHTINGS,*FITTED_WEIGHTINGS):
            with self.subTest(mode=mode):
                status=run(weighting=mode).tables['Parameter CI status: All']
                self.assertEqual(set(status['Weighting']),{mode})
                self.assertTrue(status['Inference'].str.len().gt(0).all())
                if mode in FITTED_WEIGHTINGS:self.assertEqual(set(status['Inference']),{INFERENCE_WEIGHTS})


if __name__=='__main__':unittest.main()
