"""Normal/lognormal inference: independent likelihood and transformation oracles."""
import unittest
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit

from analisi.workbench import analyse

SAMPLE = np.array([11., 23, 45, 64, 31, 55, 123])


class DistributionLikelihood(unittest.TestCase):
    def test_eighty_digit_closed_form_fixture(self):
        from analisi.lognormality import compare_distributions
        fixture=json.loads((Path(__file__).parent/'data'/'lognormality_073'/'likelihood.json').read_text())
        got=compare_distributions(np.array(fixture['values'],dtype=float)).set_index('Distribution')
        for name,prefix in (('Normal','normal'),('Lognormal','lognormal')):
            self.assertAlmostEqual(got.loc[name,'Log likelihood'],float(fixture[prefix+'_log_likelihood']),places=11)
            self.assertAlmostEqual(got.loc[name,'Relative weight (%)'],float(fixture[prefix+'_weight_percent']),places=11)

    def test_likelihoods_include_the_log_jacobian_and_mle_variance(self):
        from analisi.lognormality import compare_distributions
        got = compare_distributions(SAMPLE).set_index('Distribution')
        ln = np.log(SAMPLE)
        normal = stats.norm.logpdf(SAMPLE, loc=SAMPLE.mean(), scale=SAMPLE.std(ddof=0)).sum()
        lognormal = stats.norm.logpdf(ln, loc=ln.mean(), scale=ln.std(ddof=0)).sum()-ln.sum()
        self.assertAlmostEqual(got.loc['Normal','Log likelihood'], normal, places=11)
        self.assertAlmostEqual(got.loc['Lognormal','Log likelihood'], lognormal, places=11)
        self.assertAlmostEqual(got.loc['Normal','Relative weight (%)'], 100*expit(normal-lognormal), places=11)
        self.assertAlmostEqual(got['Relative weight (%)'].sum(),100.,places=12)
        for name in ('Normal','Lognormal'):
            self.assertAlmostEqual(got.loc[name,'AIC'],4-2*got.loc[name,'Log likelihood'],places=11)

    def test_unit_changes_leave_relative_weights_invariant(self):
        from analisi.lognormality import compare_distributions
        base = compare_distributions(SAMPLE)['Relative weight (%)'].to_numpy()
        for factor in (1e-200,1e-50,1e50,1e200):
            got = compare_distributions(SAMPLE*factor)
            np.testing.assert_allclose(got['Relative weight (%)'],base,atol=2e-10,rtol=1e-12)

    def test_tiny_representable_log_variation_is_not_constant(self):
        from analisi.lognormality import compare_distributions, centered_logs
        for origin in (1e-200,1.,1e200):
            x=np.array([origin,np.nextafter(origin,np.inf),np.nextafter(origin,-np.inf)])
            values, offset = centered_logs(x)
            self.assertGreater(np.ptp(values),0.)
            got=compare_distributions(x)
            self.assertEqual(set(got['Status']),{'Available'})
            self.assertTrue(np.isfinite(got['Relative weight (%)']).all())

    def test_nonpositive_constant_and_too_short_are_unavailable(self):
        from analisi.lognormality import compare_distributions
        for x in ([1.,2.,0.],[-1.,2.,3.],[2.,2.,2.],[1.,2.]):
            got=compare_distributions(x)
            self.assertEqual(set(got['Status']),{'Unavailable'})
            self.assertTrue(got['Relative weight (%)'].isna().all())
            self.assertTrue(got['Reason'].str.len().gt(0).all())

    def test_unrepresentable_raw_scale_is_disclosed_without_fake_zero(self):
        from analisi.lognormality import compare_distributions
        tiny=np.nextafter(0.,1.)
        got=compare_distributions([tiny,tiny,2*tiny]).set_index('Distribution')
        self.assertEqual(got.loc['Normal','Status'],'Available')
        self.assertTrue(np.isnan(got.loc['Normal','Scale']))
        self.assertTrue(np.isfinite(got.loc['Normal','Log scale']))
        self.assertIn('underflow',got.loc['Normal','Reason'])

    def test_wide_positive_dynamic_range_has_finite_likelihoods(self):
        from analisi.lognormality import compare_distributions
        for values in ([1e-300,1.,1e300],[5e-324,1e-100,1e100,1e308]):
            got=compare_distributions(values)
            self.assertTrue(np.isfinite(got[['Log likelihood','AIC','Relative weight (%)']]).all().all())
            self.assertAlmostEqual(got['Relative weight (%)'].sum(),100.,places=12)


class LognormalDispatcher(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'A':np.exp(np.linspace(-2,2,12)), 'B':np.arange(12.)})

    def test_old_recipe_tables_and_geometry_are_unchanged(self):
        options={'Variables':['A'],'Shapiro–Wilk':True,'Q–Q plot':True}
        base=analyse('Normality tests',self.frame(),options)
        new=analyse('Normality tests',self.frame(),{**options,'Distribution':'Normal','Compare distributions':False})
        self.assertEqual(list(base.tables),list(new.tables))
        for name in base.tables:pd.testing.assert_frame_equal(base.tables[name],new.tables[name])
        np.testing.assert_array_equal(base.figure.axes[0].collections[0].get_offsets(),new.figure.axes[0].collections[0].get_offsets())

    def test_four_tests_on_logs_match_existing_normality(self):
        from analisi.normality import TESTS
        frame=self.frame()[['A']]
        options={'Variables':['A'],**dict.fromkeys(TESTS,True)}
        base=analyse('Normality tests',np.log(frame),options).tables['Normality tests']
        got=analyse('Normality tests',frame,{**options,'Distribution':'Lognormal'}).tables['Lognormality tests']
        np.testing.assert_allclose(got[['Statistic','p']],base[['Statistic','p']],rtol=3e-12,atol=1e-12)
        self.assertTrue(all('normality' not in str(s).replace('lognormality','') for s in got['Decision']))

    def test_invalid_log_column_does_not_hide_normal_or_other_columns(self):
        got=analyse('Normality tests',self.frame(),{'Variables':['A','B'],'Distribution':'Both','Compare distributions':True})
        self.assertIn('Normality tests',got.tables)
        self.assertIn('Distribution comparison',got.tables)
        log=got.tables['Lognormality tests'].set_index('Variable')
        self.assertEqual(log.loc['B','Decision'],'Not tested')
        self.assertIn('positive',log.loc['B','Note'])
        self.assertTrue(np.isfinite(log.loc['A','p']))

    def test_both_qq_panels_track_missing_source_rows(self):
        frame=self.frame(); frame.loc[3,'A']=np.nan
        got=analyse('Normality tests',frame,{'Variables':['A'],'Distribution':'Both','Q–Q plot':True,'Q–Q variable':'A'})
        self.assertEqual(len(got.figure.axes),2)
        table=got.tables['Lognormal Q–Q coordinates']
        self.assertNotIn(4,table['Source row'].tolist())
        self.assertEqual(len(table),11)
        self.assertIn('Log offset',got.tables['Lognormal Q–Q settings'].index)

    def test_dual_qq_legends_and_axis_labels_fit_a_small_native_viewport(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        got=analyse('Normality tests',self.frame(),{'Variables':['A'],'Distribution':'Both','Q–Q plot':True})
        figure=got.figure
        figure.set_size_inches(7.24,3.44)
        canvas=FigureCanvasAgg(figure);canvas.draw()
        renderer=canvas.get_renderer()
        left,right=figure.axes
        self.assertLess(left.get_legend().get_window_extent(renderer).x1,right.bbox.x0)
        for axis in figure.axes:
            bounds=axis.xaxis.label.get_window_extent(renderer)
            self.assertGreaterEqual(bounds.x0,0)
            self.assertLessEqual(bounds.x1,figure.bbox.width)

    def test_comparison_weights_follow_source_edit(self):
        frame=self.frame()
        options={'Variables':['A'],'Compare distributions':True}
        before=analyse('Normality tests',frame,options).tables['Distribution comparison']['Relative weight (%)']
        frame.loc[4,'A']=30.
        after=analyse('Normality tests',frame,options).tables['Distribution comparison']['Relative weight (%)']
        self.assertFalse(np.allclose(before,after))
