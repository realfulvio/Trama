"""Copy into repository tests; copy fixtures into tests/data/pca_retention_070."""
from pathlib import Path
import json,unittest
import pandas as pd
import numpy as np
from analisi.workbench import analyse
DATA=Path(__file__).parent/'data/pca_retention_070'
class PacketContract(unittest.TestCase):
 def test_numeric_cases(self):
  recipes=json.loads((DATA/'recipes.json').read_text());expected=json.loads((DATA/'expected.json').read_text())
  for name,o in recipes.items():
   with self.subTest(case=name):
    frame=pd.DataFrame(json.loads((DATA/(name+'.json')).read_text()))
    r=analyse('Principal component analysis',frame,o)
    if 'Principal component analysis'=='Principal component analysis':
     t=r.tables['PCA selection'];e=expected[name]
     np.testing.assert_allclose(t['Eigenvalue'],e['eigenvalues'],rtol=2e-7,atol=max(e['eigenvalues'])*1e-9)
     self.assertEqual(int(t['Retained'].sum()),e['count'])
    else:
     t=r.tables['Lognormal test'].iloc[0]
     for key in ('t','df','p','Geometric ratio','Lower','Upper'):
      value=expected[name][key]
      if value is None:self.assertTrue(pd.isna(t[key]))
      else:np.testing.assert_allclose(t[key],value,rtol=2e-7,atol=abs(value)*1e-9)
