import unittest

import numpy as np
import pandas as pd

from analisi import pca_graphs, pca_reports, pca_retention
from analisi.workbench import analyse


class PcaReportsTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Response": [6., 2., 8., 5., np.nan, 10.],
            "Measure $": [3., 4., 2., 4., 8., 9.],
            "Time": [1., 2., 3., 5., 6., 8.],
        }, index=[12, 1, 1, 3, 4, 11])

    def run_pca(self, standardize, **opts):
        return analyse("Principal component analysis", self.frame, {
            "Variables": list(self.frame), "Standardize": standardize, **opts,
        })

    def test_requested_reports_match_complete_input_and_fitted_axes(self):
        keys = dict.fromkeys(pca_reports.OPTIONS, True)
        for standardize in (False, True):
            with self.subTest(standardize=standardize):
                old = self.run_pca(standardize).tables
                report = self.run_pca(standardize, **keys).tables
                for name, values in old.items():
                    pd.testing.assert_frame_equal(report[name], values)
                clean = self.frame.dropna()
                transformed = clean - clean.mean()
                if standardize:
                    transformed /= clean.std(ddof=1)
                source = report[pca_reports.INPUT_SHEET]
                self.assertEqual(source["Source row"].tolist(), list(clean.index))
                np.testing.assert_allclose(source[list(clean)], transformed, atol=1e-12)
                matrix = clean.corr() if standardize else clean.cov()
                np.testing.assert_allclose(report[pca_reports.MATRIX_SHEET].set_index("Variable"),
                                           matrix, atol=1e-12)
                correlations = np.corrcoef(clean.to_numpy().T, old["Scores"].to_numpy().T)
                np.testing.assert_allclose(report[pca_reports.CORRELATIONS].set_index("Variable"),
                                           correlations[:3, 3:], atol=1e-12)
                np.testing.assert_allclose(report[pca_reports.VARIABLES].set_index("Variable"),
                                           old["Eigenvectors"] ** 2, atol=1e-12)
                values = old["Scores"].to_numpy() ** 2
                cases = report[pca_reports.CASES]
                self.assertEqual(cases["Source row"].tolist(), list(clean.index))
                np.testing.assert_allclose(cases.drop(columns="Source row"),
                                           values / values.sum(axis=0), atol=1e-12)

    def test_retained_axes_and_rank_deficient_reports(self):
        self.frame["Dependent"] = 2 * self.frame["Response"]
        flags = {pca_reports.VARIABLES: True, pca_reports.CASES: True, pca_reports.CORRELATIONS: True}
        options = {pca_graphs.GRAPH: pca_graphs.SCORES, **flags}
        report = self.run_pca(True, **options).tables
        for name in flags:
            self.assertTrue(report[name]["PC4"].isna().all())
        self.assertEqual(len(report[pca_reports.CASES]), 5)
        options.update({pca_retention.SELECTION: pca_retention.FIXED, pca_retention.RETAINED: 1})
        report = self.run_pca(True, **options).tables
        self.assertEqual(list(report[pca_reports.CASES]), ["Source row", "PC1"])
        for name in (pca_reports.VARIABLES, pca_reports.CORRELATIONS):
            self.assertEqual(list(report[name]), ["Variable", "PC1"])

    def test_one_dimensional_graphs_keep_the_requested_reports(self):
        flags = dict.fromkeys(pca_reports.OPTIONS, True)
        baseline = self.run_pca(True, **flags)
        for view in (pca_graphs.SCREE, pca_graphs.PROPORTION):
            with self.subTest(view=view):
                result = self.run_pca(True, **{pca_graphs.GRAPH: view, **flags})
                for name in baseline.tables:
                    pd.testing.assert_frame_equal(result.tables[name], baseline.tables[name])

    def test_literal_names_and_switches_are_preserved(self):
        self.frame = self.frame.rename(columns={"Time": "Source row", "Response": "Variable"})
        off = self.run_pca(False, **dict(pca_reports.OPTIONS)).tables
        self.assertEqual(list(off), ["Explained variance", "Eigenvectors", "Scores"])
        single = self.run_pca(False, **{pca_reports.INPUT: True, pca_reports.MATRIX: True}).tables
        self.assertEqual(list(single)[3:], [pca_reports.INPUT_SHEET, pca_reports.MATRIX_SHEET])
        for name in list(single)[3:]:
            self.assertTrue(single[name].columns.is_unique)
            self.assertIn("Variable", single[name])
