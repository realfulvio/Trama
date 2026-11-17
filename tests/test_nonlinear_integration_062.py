"""Bands and fit-quality additions share one fit and survive multi-panel output."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import stats as engine
from analisi.workbench import analyse


class CombinedNonlinearTests(unittest.TestCase):
    def setUp(self):
        x = np.repeat(np.arange(6.), 3)
        self.frame = pd.DataFrame({'X': x, 'Y': 2 + 1.5*x + np.tile([-.2, .05, .3], 6)})
        self.options = {'X': 'X', 'Y columns': ['Y'], 'Grouping variables': [],
                        'Model': 'Straight line', 'Weighting': 'Unweighted'}

    def test_band_quality_and_residual_panel_reuse_one_fit(self):
        baseline = analyse('Nonlinear regression', self.frame, self.options)
        with patch('analisi.workbench.engine.nonlinear', wraps=engine.nonlinear) as fit:
            result = analyse('Nonlinear regression', self.frame, {
                **self.options, 'Band': 'Confidence (mean)', 'Runs test': True,
                'Replicate lack of fit': True, 'Residuals versus X': True})
        self.assertEqual(fit.call_count, 1)
        for name in ('Parameters: All', 'Fit: All', 'Residuals: All'):
            pd.testing.assert_frame_equal(result.tables[name], baseline.tables[name])
        self.assertIn('Band: All', result.tables)
        self.assertIn('Runs test: All', result.tables)
        self.assertIn('Replicate lack of fit: All', result.tables)
        self.assertEqual(len(result.figure.axes), 2)
        self.assertGreater(len(result.figure.axes[0].collections), 1)
        self.assertEqual(len(result.figure.axes[1].collections), 1)

    def test_multiple_responses_keep_each_band_and_each_diagnostic(self):
        frame = self.frame.assign(Z=self.frame.Y*2 + np.tile([.02, -.03, .01], 6))
        result = analyse('Nonlinear regression', frame, {
            **self.options, 'Y columns': ['Y', 'Z'], 'Band': 'Prediction (new observation)',
            'Replicate lack of fit': True, 'Residuals versus X': True})
        self.assertEqual(len(result.figure.axes), 4)
        self.assertTrue(any('Band' in title for title in result.tables))
        self.assertTrue(any('Replicate lack of fit' in title for title in result.tables))
