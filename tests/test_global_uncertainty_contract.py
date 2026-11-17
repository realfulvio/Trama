"""Candidate acceptance tests; copy into the repository's tests directory.
Copy fixtures/ to tests/data/global_uncertainty/ without changing its JSON files.
These assertions use independent stored numerical expectations, not production helpers.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from analisi.workbench import analyse
from analisi.field_error import FieldError

HERE=Path(__file__).resolve().parent
DATA=HERE/'data/global_uncertainty'
if not DATA.exists():DATA=HERE.parent/'fixtures'  # Running this template beside the packet.
RECIPES=json.loads((DATA/'recipes.json').read_text())
EXPECTED=json.loads((DATA/'expected.json').read_text())
METHOD='Global fit custom equation'

def data(name):return pd.DataFrame(json.loads((DATA/(name+'.json')).read_text()))
def opts(name,**overrides):
 settings=copy.deepcopy(RECIPES[name])
 settings.update({'Curve band':'Confidence','Band drawing':'Filled','Response level (%)':90.,'Predict responses':True,'Query X':'Query X','Query group':'Query group','Query replicate count':'Query k','Query interval':'Confidence','Allow extrapolation':False})
 settings.update(overrides);return settings

def run(name,**overrides):return analyse(METHOD,data(name),opts(name,**overrides))

class GlobalUncertaintyContract(unittest.TestCase):
 def assertClose(self,a,b):np.testing.assert_allclose(a,b,rtol=3e-6,atol=0,equal_nan=True)
 def assertBand(self,name,kind='Confidence'):
  r=run(name,**{'Curve band':kind});self.assertIn('Curve bands',r.tables)
  t=r.tables['Curve bands'];expected=EXPECTED[name]['curves'];self.assertEqual(len(t),len(expected))
  for group in dict.fromkeys(row['Group'] for row in expected):
   actual=t[t['Group'].astype(str)==group].sort_values('X');ref=[v for v in expected if v['Group']==group]
   self.assertEqual(len(actual),len(ref))
   for col,key in [('X','X'),('Predicted','Predicted'),('SE mean','SE mean'),('Lower',kind+' lower'),('Upper',kind+' upper')]:
    with self.subTest(case=name,group=group,column=col):self.assertClose(actual[col],[x[key] for x in ref])
  return r

 def test_linear_joint_covariance(self):self.assertBand('linear-shared')
 def test_prediction_uses_global_df_and_rss(self):self.assertBand('linear-shared','Prediction')
 def test_fixed_parameter_of_one_series(self):self.assertBand('linear-fixed')
 def test_nonlinear_shared_rate(self):self.assertBand('decay-shared')
 def test_small_response_keeps_real_variance(self):self.assertBand('linear-small-y')
 def test_large_x_units_keep_response_uncertainty(self):self.assertBand('decay-large-x')
 def test_empty_label_is_a_real_group(self):self.assertBand('linear-empty-label')

 def test_one_logical_fit_for_all_outputs(self):
  import analisi.global_custom_fit as engine
  with patch.object(engine,'_solve',wraps=engine._solve) as fitting:
   r=run('linear-shared')
  self.assertIn('Curve bands',r.tables);self.assertIn('Predictions',r.tables);self.assertEqual(fitting.call_count,1)

 def test_response_level_does_not_change_parameter_intervals(self):
  a=analyse(METHOD,data('linear-shared'),RECIPES['linear-shared'])
  b=run('linear-shared',**{'Response level (%)':99.})
  self.assertIn('Curve bands',b.tables)
  for name in ('Parameters','Global fit','Covariance','Residuals','Curve'):
   pd.testing.assert_frame_equal(a.tables[name],b.tables[name],check_exact=False,rtol=3e-7,atol=1e-300)

 def test_prediction_of_average_k_preserves_mean_se(self):
  r=run('linear-shared',**{'Query interval':'Prediction'});self.assertIn('Predictions',r.tables)
  t=r.tables['Predictions'].set_index('Source row');a,b=t.loc[0],t.loc[8]
  self.assertClose(a['SE mean'],b['SE mean']);self.assertClose([a['k'],b['k']],[1,4])
  self.assertLess(b['Upper']-b['Lower'],a['Upper']-a['Lower'])
  for index in (0,8):
   ex=EXPECTED['linear-shared']['queries'][index]
   self.assertClose([t.loc[index,'Lower'],t.loc[index,'Upper']],[ex['Prediction lower'],ex['Prediction upper']])

 def test_query_statuses_and_provenance(self):
  df=data('linear-shared');df.index=200+13*np.arange(len(df))
  r=analyse(METHOD,df,opts('linear-shared'));self.assertIn('Predictions',r.tables)
  t=r.tables['Predictions'];ref=EXPECTED['linear-shared']['queries']
  self.assertEqual(t['Source row'].tolist(),list(df.index[:len(ref)]));self.assertEqual(t['Status'].tolist(),[v['Status'] for v in ref])

 def test_extrapolation_is_per_series_and_flagged(self):
  r=run('linear-shared',**{'Allow extrapolation':True});self.assertIn('Predictions',r.tables)
  q=r.tables['Predictions'].set_index('Source row');self.assertEqual(q.loc[4,'Status'],'Extrapolated')
  self.assertTrue(q.loc[4,'Extrapolated']);self.assertClose(q.loc[4,'Predicted'],EXPECTED['linear-shared']['queries'][4]['Predicted'])

 def test_model_singularity_does_not_discard_other_queries(self):
  r=run('rational-domain',**{'Allow extrapolation':True});self.assertIn('Predictions',r.tables)
  q=r.tables['Predictions'];self.assertEqual(q['Status'].tolist(),['Undefined model','Extrapolated','OK'])
  self.assertTrue(pd.isna(q.iloc[0]['Predicted']));self.assertTrue(np.isfinite(q.iloc[1:]['Predicted'].to_numpy(dtype=float)).all())

 def test_unavailable_intervals_keep_the_point_estimate(self):
  for name in ('linear-perfect','all-fixed','active-bound'):
   with self.subTest(case=name):
    r=run(name);self.assertIn('Curve bands',r.tables);self.assertTrue(r.tables['Curve bands']['Lower'].isna().all())
    q=r.tables['Predictions'];q=q[q['Status']=='Interval unavailable'];self.assertGreater(len(q),0)
    self.assertTrue(q['Predicted'].notna().all());self.assertTrue(q['Lower'].isna().all())

 def test_field_errors_use_canonical_keys(self):
  for overrides,field in [({'Response level (%)':0},'Response level (%)'),({'Query X':'absent'},'Query X'),({'Query group':'absent'},'Query group')]:
   with self.subTest(field=field):
    with self.assertRaises(FieldError) as caught:run('linear-shared',**overrides)
    self.assertEqual(caught.exception.field,field)

 def test_invalid_k_and_ignored_k_for_confidence(self):
  df=data('linear-shared');df['Query k']=df['Query k'].astype(object);df.loc[0,'Query k']=1.5
  with self.assertRaises(FieldError) as caught:analyse(METHOD,df,opts('linear-shared',**{'Query interval':'Prediction'}))
  self.assertEqual(caught.exception.field,'Query replicate count')
  r=analyse(METHOD,df,opts('linear-shared'));self.assertIn('Predictions',r.tables)
  self.assertTrue(r.tables['Predictions']['k'].isna().all())

 def test_query_edit_does_not_change_fit(self):
  before=run('linear-shared');self.assertIn('Predictions',before.tables)
  df=data('linear-shared');df.loc[0,'Query X']=2.
  after=analyse(METHOD,df,opts('linear-shared'))
  pd.testing.assert_frame_equal(before.tables['Parameters'],after.tables['Parameters'])
  self.assertNotEqual(before.tables['Predictions'].iloc[0]['Predicted'],after.tables['Predictions'].iloc[0]['Predicted'])

 def test_legacy_recipes_keep_five_sheets_and_ignore_hidden_query_fields(self):
  expected=json.loads((DATA/'legacy-snapshot.json').read_text())
  for name,legacy in expected.items():
   with self.subTest(case=name):
    o=copy.deepcopy(RECIPES[name]);o.update({'Curve band':'None','Predict responses':False,'Response level (%)':'inactive','Query X':'missing','Query group':'missing','Query interval':'Prediction'})
    r=analyse(METHOD,data(name),o);self.assertEqual(list(r.tables),legacy['sheets'])
    self.assertEqual(len(r.figure.axes),legacy['axes'])
    for sheet,table in r.tables.items():self.assertEqual(list(table.columns),legacy['tables'][sheet]['columns']) if sheet!='Covariance' else None

if __name__=='__main__':unittest.main()
