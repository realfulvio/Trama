"""Row-wise inference for raw or summarized groups and multiplicity control."""
import unittest

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analisi.processing import FieldError
from analisi.row_tests import (MANN_WHITNEY, MEAN_SD, MEAN_SEM, PAIRED, ROW_TESTS, STUDENT,
                               WELCH, WILCOXON, _bky_q, default_options)
from analisi.workbench import analyse


class RowComparisonTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Row title": ["Week 1", "Week 2", "Missing", "Constant"],
                                   "Control [1]": [4., 9., 2., 5.], "Control [2]": [5., None, None, 5.],
                                   "Control [3]": [8., 6., None, 5.], "Treatment [1]": [1., 2., 3., 5.],
                                   "Treatment [2]": [5., 8., 3., 5.], "Treatment [3]": [5., 4., 2., 5.]})
        self.frame.attrs["table_format"] = "grouped"
        self.options = default_options(self.frame)

    def result(self, **kwargs):
        return analyse(ROW_TESTS, self.frame, {**self.options, **kwargs})

    def test_welch_and_student_reference_with_missing_rows(self):
        for test in (WELCH, STUDENT):
            with self.subTest(test=test):
                result = self.result(Test=test)
                table = result.tables["Row comparisons"]
                for index, left, right in (
                        ("Week 1", [4, 5, 8], [1, 5, 5]),
                        ("Week 2", [9, 6], [2, 8, 4])):
                    expected = stats.ttest_ind(left, right, equal_var=test == STUDENT)
                    np.testing.assert_allclose(table.loc[index, ["Statistic", "df", "p"]].astype(float),
                                               [expected.statistic, expected.df, expected.pvalue], rtol=1e-12)
                    np.testing.assert_allclose(table.loc[index, ["CI lower", "CI upper"]].astype(float),
                                               expected.confidence_interval(), rtol=1e-12)
                self.assertEqual(table.loc["Missing", "Status"], "Insufficient observations")
                self.assertEqual(table.loc["Constant", "Status"], "Variance unavailable")
                self.assertTrue(table.loc[["Missing", "Constant"], "Adjusted p"].isna().all())
                np.testing.assert_allclose(table["Adjusted p"].iloc[:2],
                                           multipletests(table["p"].iloc[:2], method="holm-sidak")[1])
                self.assertEqual(len(result.figure.axes[0].collections[0].get_offsets()), 2)

    def test_pairing_matches_subcolumn_number_instead_of_order(self):
        options = {"First replicates": ["Control [3]", "Control [2]", "Control [1]"],
                   "Second replicates": ["Treatment [1]", "Treatment [3]"], "Test": PAIRED}
        table = self.result(**options).tables["Row comparisons"]
        # The differences are constant, so no t statistic is reported.
        self.assertTrue(pd.isna(table.loc["Week 1", "Statistic"]))
        self.assertEqual(table.loc["Week 1", "Difference"], 3)
        self.assertEqual(table.loc["Week 1", "N first"], 2)
        expected = stats.ttest_rel([9, 6], [2, 4])
        self.assertAlmostEqual(table.loc["Week 2", "Statistic"], expected.statistic)
        self.assertAlmostEqual(table.loc["Week 2", "p"], expected.pvalue)
        with self.assertRaisesRegex(FieldError, "corresponding"):
            self.result(**{**options, "Second replicates": ["Treatment [3]"]})

    def test_rank_tests_use_complete_cases(self):
        result = self.result(Test=MANN_WHITNEY).tables["Row comparisons"]
        expected = stats.mannwhitneyu([9, 6], [2, 8, 4])
        self.assertEqual(result.loc["Week 2", "p"], expected.pvalue)
        result = self.result(Test=WILCOXON).tables["Row comparisons"]
        expected = stats.wilcoxon([7, 2])
        self.assertEqual(result.loc["Week 2", "p"], expected.pvalue)
        self.assertEqual(result.loc["Constant", "p"], 1.)
        self.assertTrue(result["CI lower"].isna().all())

    def test_summary_sd_and_sem_reproduce_raw_welch(self):
        a = np.array([4., 5., 8.])
        b = np.array([1., 5., 5., 9.])
        for format_name, suffix in ((MEAN_SD, "SD"), (MEAN_SEM, "SEM")):
            with self.subTest(format_name=format_name):
                def error(x):
                    return x.std(ddof=1) / (np.sqrt(len(x)) if suffix == "SEM" else 1)
                frame = pd.DataFrame({"A [Mean]": [a.mean()], f"A [{suffix}]": [error(a)], "A [N]": [len(a)],
                                      "B [Mean]": [b.mean()], f"B [{suffix}]": [error(b)], "B [N]": [len(b)]})
                options = default_options(frame)
                self.assertEqual(options["Input format"], format_name)
                table = analyse(ROW_TESTS, frame, options).tables["Row comparisons"]
                expected = stats.ttest_ind(a, b, equal_var=False)
                np.testing.assert_allclose(table[["Statistic", "df", "p"]].iloc[0].astype(float),
                                           [expected.statistic, expected.df, expected.pvalue], rtol=1e-12)
                with self.assertRaisesRegex(FieldError, "test"):
                    analyse(ROW_TESTS, frame, {**options, "Test": PAIRED})
                frame.loc[0, "A [N]"] = 1
                with self.assertRaisesRegex(FieldError, "whole numbers"):
                    analyse(ROW_TESTS, frame, options)

    def test_unmatched_columns_validate_and_keep_populated_rows(self):
        frame = pd.DataFrame({"A [1]": [1., None], "A [2]": [2., None], "A [3]": [None, 7.],
                              "B [1]": [2., None], "B [2]": [5., None]})
        frame.attrs["worksheet_roles"] = {"x": [], "y": [list(frame.columns[:3]), list(frame.columns[3:])]}
        options = {**default_options(frame), "Test": PAIRED}
        table = analyse(ROW_TESTS, frame, options).tables["Row comparisons"]
        self.assertEqual(table.loc["Row 2", "Status"], "Insufficient complete pairs")
        with self.assertRaisesRegex(FieldError, "Choose a column"):
            analyse(ROW_TESTS, frame.drop(columns=["A [3]"]), options)

        frame["A [3]"] = pd.Series([100, "typo"], dtype=object)
        options = default_options(frame)
        self.assertIn("A [3]", options["First replicates"])
        with self.assertRaisesRegex(FieldError, "contains text"):
            analyse(ROW_TESTS, frame, options)

    def test_bky_minimum_discovery_q_and_fixed_threshold_decisions(self):
        values = np.array([.03, .004, .04, .20])
        q = _bky_q(values)
        np.testing.assert_allclose(q, [1 / 24, .016 / .984, 1 / 24, .05333333333333333 / .9466666666666667])
        for threshold in (.01, .02, .035, .05, .06, .9):
            expected = multipletests(values, alpha=threshold, method="fdr_tsbky")[0]
            np.testing.assert_equal(q <= threshold, expected)
        np.testing.assert_allclose(_bky_q(np.array([1e-20, 1e-50])), [5e-21, 2e-50], atol=0, rtol=1e-14)
        self.assertLessEqual(_bky_q(np.array([1 / 21]))[0], .05)
        result = self.result(Correction="Benjamini–Krieger–Yekutieli")
        self.assertIn("q", result.tables["Row comparisons"])
        self.assertIn("Discovery", result.tables["Row comparisons"])
        self.assertNotIn("Adjusted p", result.tables["Row comparisons"])


if __name__ == "__main__":
    unittest.main()
