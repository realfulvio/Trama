"""Independent raw-observation and sufficient-statistic oracles."""
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.processing import FieldError
from analisi.summary_ttest import METHOD, summary_ttest


class SummaryTTestTests(unittest.TestCase):
    samples = ([1., 2., 4., 5.], [3., 5., 8.])

    def data(self, scale=1.):
        return pd.DataFrame({'Group':['A','B'], 'Mean':[np.mean(x)*scale for x in self.samples],
                             'SD':[np.std(x,ddof=1)*abs(scale) for x in self.samples], 'N':[4,3]})

    def options(self, **extra):
        return {'Input':'Groups in rows','Group':'Group','Mean':'Mean','Dispersion':'SD',
                'Sample size':'N','Dispersion type':'SD','Design':'Welch',
                'Confidence level (%)':95.,'Null difference':0., **extra}

    def result(self, data=None, **options):
        return summary_ttest(self.data() if data is None else data, self.options(**options))

    def test_raw_data_oracle_and_confidence_interval(self):
        for design in ('Welch','Student'):
            with self.subTest(design=design):
                row=self.result(Design=design).tables['t-test'].iloc[0]
                raw=stats.ttest_ind(*self.samples,equal_var=design=='Student')
                interval=raw.confidence_interval()
                np.testing.assert_allclose(row[['t','p','df','CI lower','CI upper']].to_numpy(float),
                    [raw.statistic,raw.pvalue,raw.df,interval.low,interval.high],rtol=2e-13)

    def test_two_group_anova_identity(self):
        from analisi.summary_anova import summary_anova
        row=self.result(Design='Student').tables['t-test'].iloc[0]
        anova=summary_anova(self.data(),self.options(**{'Post-hoc':'None'})).tables['ANOVA'].iloc[0]
        self.assertAlmostEqual(row['t']**2,anova['F'],places=13)
        self.assertAlmostEqual(row['p'],anova['p'],places=13)

    def test_null_difference_and_direction(self):
        row=self.result(**{'Null difference':2.}).tables['t-test'].iloc[0]
        base=self.result().tables['t-test'].iloc[0]
        self.assertAlmostEqual(row['t'],(base['Difference']-2)/base['SE'])
        self.assertEqual(row['CI lower'],base['CI lower'])
        reverse=self.result(self.data().iloc[::-1]).tables['t-test'].iloc[0]
        self.assertAlmostEqual(reverse['t'],-base['t'])
        self.assertAlmostEqual(reverse['CI lower'],-base['CI upper'])
        self.assertEqual(reverse['First'],'B')

    def test_sem_cv_and_subcolumns(self):
        expected=self.result().tables['t-test'].iloc[0]
        for kind in ('SEM','CV (%)'):
            data=self.data();data.SD /= np.sqrt(data.N) if kind=='SEM' else data.Mean/100
            row=self.result(data,**{'Dispersion type':kind}).tables['t-test'].iloc[0]
            self.assertAlmostEqual(row['t'],expected['t'])
        data=self.data()
        wide=pd.DataFrame({f'{r.Group} [{role}]':[np.nan,getattr(r,role)]
                           for r in data.itertuples() for role in ('Mean','SD','N')})
        result=summary_ttest(wide,{'Input':'Summary subcolumns','Variables':list(wide),'Summary row':2})
        self.assertAlmostEqual(result.tables['t-test'].iloc[0]['t'],expected['t'])
        self.assertEqual(result.tables['Summaries used']['Source row'].tolist(),[2,2])

    def test_extreme_units(self):
        for design in ('Student','Welch'):
            base=self.result(Design=design).tables['t-test'].iloc[0]
            for scale in (1e-200,1e200,-3.):
                with self.subTest(design=design,scale=scale):
                    row=self.result(self.data(scale),Design=design).tables['t-test'].iloc[0]
                    np.testing.assert_allclose(row[['p','df']].to_numpy(float),base[['p','df']].to_numpy(float),rtol=2e-13)
                    self.assertAlmostEqual(row['t'],base['t']*np.sign(scale))

    def test_shift_invariance_and_equal_huge_means(self):
        frame=self.data();frame.Mean += 1e5
        self.assertAlmostEqual(self.result(frame).tables['t-test'].iloc[0]['p'],
                               self.result().tables['t-test'].iloc[0]['p'],places=10)
        frame.Mean=[1e200,1e200];frame.SD=[1.,2.]
        row=self.result(frame).tables['t-test'].iloc[0]
        self.assertEqual(row['p'],1.)
        self.assertGreater(row['SE'],0.)

    def test_display_overflow_does_not_erase_scaled_inference(self):
        frame=self.data();frame.Mean=[1e308,-1e308];frame.SD=[1e308,1e308]
        row=self.result(frame).tables['t-test'].iloc[0]
        self.assertTrue(np.isfinite(row[['t','p','df']].to_numpy(float)).all())
        self.assertTrue(np.isnan(row['Difference']))
        self.assertTrue(row['Note'])

    def test_one_zero_sd_and_two_zero_sd(self):
        frame=self.data();frame.loc[0,'SD']=0.
        row=self.result(frame).tables['t-test'].iloc[0]
        self.assertAlmostEqual(row['df'],2.)
        frame.SD=0.
        with self.assertRaises(FieldError) as error:self.result(frame)
        self.assertEqual(error.exception.field,'Dispersion')
        self.assertNotIn('ANOVA',str(error.exception))

    def test_level_changes_ci_not_p(self):
        a=self.result().tables['t-test'].iloc[0]
        b=self.result(**{'Confidence level (%)':90}).tables['t-test'].iloc[0]
        self.assertEqual(a['p'],b['p']);self.assertLess(a['CI lower'],b['CI lower'])

    def test_exactly_two_used_groups_and_omission_provenance(self):
        frame=pd.concat([self.data().iloc[:1],pd.DataFrame({'Group':['missing'],'Mean':[1.],'SD':[np.nan],'N':[4]}),self.data().iloc[1:]],ignore_index=True)
        result=self.result(frame)
        self.assertEqual(result.tables['Summaries used']['Source row'].tolist(),[1,3])
        self.assertEqual(result.tables['Omitted groups']['Source row'].tolist(),[2])
        frame.loc[1,'SD']=1.
        with self.assertRaises(FieldError) as error:self.result(frame)
        self.assertEqual(error.exception.field,'Mean')

    def test_invalid_design_null_n_and_level(self):
        for options,field in (({'Design':'Paired'},'Design'),({'Null difference':np.inf},'Null difference'),
                              ({'Null difference':True},'Null difference'),({'Confidence level (%)':100},'Confidence level (%)')):
            with self.subTest(options=options),self.assertRaises(FieldError) as error:self.result(**options)
            self.assertEqual(error.exception.field,field)
        for n in ('3.0000000000000001',str(2**53+1),True):
            frame=self.data().astype(object);frame.loc[0,'N']=n
            with self.subTest(n=n),self.assertRaises(FieldError):self.result(frame)

    def test_large_sample_counts_do_not_expand_observations(self):
        frame=self.data();frame.N=[10**12,10**12]
        result=self.result(frame)
        self.assertEqual(len(result.tables['Summaries used']),2)
        self.assertGreater(result.tables['t-test'].iloc[0]['df'],1e12)

    def test_input_unchanged(self):
        frame=self.data();before=frame.copy(deep=True);self.result(frame)
        pd.testing.assert_frame_equal(frame,before)

    def test_dispatch_and_project_roundtrip(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from analisi.workbench import analyse,GRAPH_METHODS
        from analisi.data import Dataset,save_project,load_project
        self.assertIn(METHOD,GRAPH_METHODS)
        with TemporaryDirectory() as directory:
            path=Path(directory)/'summary.alab'
            save_project(path,{'Summary':Dataset(self.data(),analyses=[(METHOD,self.options())])})
            dataset=load_project(path)['Summary'];method,options=dataset.analyses[0]
            result=analyse(method,dataset.frame(),options)
            pd.testing.assert_frame_equal(result.tables['t-test'],self.result().tables['t-test'])
            self.assertEqual(len(result.figure.axes),1)
