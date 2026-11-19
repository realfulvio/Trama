"""Regression cases for worksheet statistics scoped to groups and filters."""
import json
from math import erf, erfc
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import Dataset, formula, info_references, load_project, load_tables, save_project


class WindowFormulaTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"X": [10, 30, 40, 50, np.nan, 100],
                                   "Category": [1, 1, "1", "1", "1", None],
                                   "Keep": [1, 0, 1, 0, 1, 1]})

    def test_group_statistics_distinguish_text_and_numbers_and_leave_missing_groups_blank(self):
        out = formula(self.frame, '=mean(X) over COL("Category")')
        np.testing.assert_allclose(out, [20, 20, 45, 45, 45, np.nan])
        deviations = formula(self.frame, '=X - (MEAN(X) OVER Category WHERE Keep = 1)')
        np.testing.assert_allclose(deviations, [0, 20, 0, 10, np.nan, np.nan])

    def test_where_uses_only_matching_rows_and_broadcasts_the_result(self):
        count = formula(self.frame, '=COUNT(X) OVER Category WHERE X > INFO("cut")', info={"cut": "35"})
        np.testing.assert_allclose(count, [0, 0, 2, 2, 2, np.nan])
        total = formula(self.frame, "=SUM(X) WHERE Keep = 1")
        np.testing.assert_allclose(total, [150] * 6)
        self.assertEqual(info_references('COUNT(X) OVER Category WHERE X > INFO("Cut")'), {"cut"})
        # The partition is an expression. Missing X is excluded from its own group statistic.
        partition = formula(self.frame.iloc[:4], "MEAN(X) OVER X >= 30")
        np.testing.assert_allclose(partition, [10, 40, 40, 40])
        frame = self.frame.assign(Use=["A", "a", "B", "b", "b", "C"], Lab=[1, "2", None, " ", 3, 4])
        np.testing.assert_allclose(formula(frame, 'MEAN(X) WHERE Use = "a"'), [20] * 6)
        np.testing.assert_allclose(formula(frame, 'COUNT(Lab) OVER Category'), [1, 1, 1, 1, 1, np.nan])
        np.testing.assert_allclose(formula(frame, 'COUNTA(Lab) OVER Category'), [2, 2, 1, 1, 1, np.nan])

    def test_invalid_clauses_are_rejected_as_a_whole(self):
        with self.assertRaisesRegex(ValueError, "nonnegative integer"):
            formula(self.frame, "MEAN(X) OVER Category ORDER BY Keep ROWS -1 PRECEDING")
        with self.assertRaisesRegex(ValueError, "after OVER or WHERE"):
            formula(self.frame, "MEAN(X) OVER Category WHERE")
        with self.assertRaisesRegex(ValueError, "requires a logical expression"):
            formula(self.frame, "MEAN(X) WHERE Keep")

    def test_dispersion_uses_sample_estimates_and_blank_singletons(self):
        expected = np.array([10 * np.sqrt(2), 10 * np.sqrt(2), 5 * np.sqrt(2), 5 * np.sqrt(2), 5 * np.sqrt(2), np.nan])
        np.testing.assert_allclose(formula(self.frame, "STDEV(X) OVER Category"), expected)
        np.testing.assert_allclose(formula(self.frame, "STDERR(X) OVER Category"), expected / np.sqrt(2))
        filtered = formula(self.frame, "STDEV(X) OVER Category WHERE AND(Keep = 1, X > 0)")
        self.assertTrue(np.isnan(filtered).all())

    def test_conditional_aggregates_can_broadcast_or_use_partitioned_rows(self):
        np.testing.assert_allclose(formula(self.frame, "MEANIF(X, X >= 30)"), [55] * 6)
        totals = formula(self.frame, "SUMIF(X, Keep = 1) OVER Category")
        np.testing.assert_allclose(totals, [10, 10, 40, 40, 40, np.nan])
        combined = formula(self.frame, "COUNTIF(X, X >= 30) OVER Category WHERE Keep <> 0")
        np.testing.assert_allclose(combined, [0, 0, 1, 1, 1, np.nan])
        frame = self.frame.assign(Label=["Control", "CONTROL", "Treated", "treated", " ", None])
        np.testing.assert_allclose(formula(frame, 'MAXIF(X, Label = "control")'), [30] * 6)
        self.assertTrue(np.isnan(formula(frame, "MEANIF(X, Keep > 1)")).all())
        np.testing.assert_allclose(formula(frame, "SUMIF(X, Keep > 1)"), [0] * 6)

    def test_column_center_standardize_and_rank_preserve_rows(self):
        frame = pd.DataFrame({"Dose": [3., 1., 3., 7., np.nan, np.inf]}, index=[8, 7, 6, 5, 4, 3])
        center = [-.5, -2.5, -.5, 3.5, np.nan, np.nan]
        np.testing.assert_allclose(formula(frame, "CENTER(Dose)"), center)
        for name in ("STANDARDIZE", "ZSCORE"):
            result = formula(frame, f"{name}(Dose)")
            np.testing.assert_allclose(result, np.asarray(center) / np.sqrt(19 / 3))
            self.assertEqual(result.index.tolist(), frame.index.tolist())
        np.testing.assert_allclose(formula(frame, "RANK(Dose)"), [2.5, 1, 2.5, 4, np.nan, np.nan])
        self.assertTrue(formula(frame.assign(Dose=3.), "ZSCORE(Dose)").isna().all())
        self.assertTrue(np.isposinf(frame.loc[3, "Dose"]))

    def test_scalar_transforms_preserve_domains_and_blank_rows(self):
        frame = pd.DataFrame({"X": [-2.5, 0., .25, 1., 2.5, np.nan]})
        np.testing.assert_allclose(formula(frame, "CEIL(X)"), [-2, 0, 1, 1, 3, np.nan])
        np.testing.assert_allclose(formula(frame, "FLOOR(X)"), [-3, 0, 0, 1, 2, np.nan])
        np.testing.assert_allclose(formula(frame, "INT(X)"), [-2, 0, 0, 1, 2, np.nan])
        np.testing.assert_allclose(formula(frame, "SGN(X)"), [-1, 0, 1, 1, 1, np.nan])
        np.testing.assert_allclose(formula(frame, "SQR(X)"), [6.25, 0, .0625, 1, 6.25, np.nan])
        np.testing.assert_allclose(formula(frame, "LOGIT(X)"), [np.nan, np.nan, -np.log(3), np.nan, np.nan, np.nan])
        np.testing.assert_allclose(formula(frame, "ARCSINH(SINH(X))"), frame["X"])
        np.testing.assert_allclose(formula(frame, "ARCCOSH(COSH(X))"), frame["X"].abs(), atol=1e-14)
        np.testing.assert_allclose(formula(frame, "ARCTANH(TANH(X))"), frame["X"])
        np.testing.assert_allclose(formula(frame, "ARCCOSH(X)"), [np.nan, np.nan, np.nan, 0, 1.566799236972411, np.nan])
        np.testing.assert_allclose(formula(frame, "ARCTANH(X)"), [np.nan, 0, np.log(5 / 3) / 2, np.nan, np.nan, np.nan])

    def test_centering_and_standardizing_large_finite_values(self):
        frame = pd.DataFrame({"X": [1.6e308, 1.2e308]})
        np.testing.assert_allclose(formula(frame, "CENTER(X)"), [2e307, -2e307])
        np.testing.assert_allclose(formula(frame, "STANDARDIZE(X)"), [.5 ** .5, -(.5 ** .5)])

    def test_gamma_functions_leave_poles_overflow_and_blank_inputs_empty(self):
        root_pi = np.sqrt(np.pi)
        frame = pd.DataFrame({"X": [-1.5, -1, -.5, 0, .5, 1, 5, 172, np.nan, np.inf]})
        np.testing.assert_allclose(formula(frame, "GAMMA(X)"),
                                   [4 * root_pi / 3, np.nan, -2 * root_pi, np.nan, root_pi,
                                    1, 24, np.nan, np.nan, np.nan])
        np.testing.assert_allclose(formula(frame, "GAMMALN(X)").iloc[:7],
                                   [np.log(4 * root_pi / 3), np.nan, np.nan, np.nan,
                                    np.log(root_pi), 0, np.log(24)], atol=1e-14)
        self.assertAlmostEqual(formula(frame, "PSI(3)").iloc[0], 1.5 - np.euler_gamma)
        self.assertTrue(formula(frame, "PSI(-2)").isna().all())
        self.assertTrue(np.isfinite(formula(frame, "GAMMALN(X)").iloc[7]))

    def test_regularized_gamma_beta_and_error_functions_use_real_domains(self):
        frame = pd.DataFrame({"X": [-1., 0, .25, 1, 2, np.nan, np.inf]})
        np.testing.assert_allclose(formula(frame, "IGAMMA(1,X)"),
                                   [np.nan, 0, -np.expm1(-.25), -np.expm1(-1), -np.expm1(-2), np.nan, np.nan])
        np.testing.assert_allclose(formula(frame, "IGAMMAC(1,X)"),
                                   [np.nan, 1, np.exp(-.25), np.exp(-1), np.exp(-2), np.nan, np.nan])
        np.testing.assert_allclose(formula(frame, "BETA(2,3)"), [1 / 12] * len(frame))
        self.assertTrue(formula(frame, "BETA(-.5,3)").isna().all())
        np.testing.assert_allclose(formula(frame, "IBETA(2,1,X)"), [np.nan, 0, .0625, 1, np.nan, np.nan, np.nan])
        for name, reference in (("ERF", erf), ("ERFC", erfc)):
            np.testing.assert_allclose(formula(frame, f"{name}(X)"),
                                       [reference(x) if np.isfinite(x) else np.nan for x in frame["X"]])

    def test_bessel_and_percentage_formulas_broadcast_and_preserve_rows(self):
        frame = pd.DataFrame({"X": [-1., .4, 1., 2., np.nan], "Order": [.5, .5, .5, np.nan, .5]},
                             index=[7, 2, 8, 1, 3])
        constant = np.sqrt(2 / (np.pi * frame["X"].iloc[1:3]))
        for name, trig in (("BESSELJ", np.sin), ("BESSELY", lambda x: -np.cos(x))):
            result = formula(frame, f"{name}(Order, X)")
            self.assertEqual(result.index.tolist(), frame.index.tolist())
            np.testing.assert_allclose(result.iloc[1:3], constant * trig(frame["X"].iloc[1:3]))
            self.assertTrue(result.iloc[[0, 3, 4]].isna().all())
        np.testing.assert_allclose(formula(frame, "X*PERC(12.5)"), frame["X"] / 8)
        with self.assertRaisesRegex(ValueError, "Unsupported expression"):
            formula(frame, "IBETA(X,1)")

    def test_normal_distribution_formulas_support_defaults_and_stable_tails(self):
        frame = pd.DataFrame({"X": [-2., 0., 2., 12., np.nan, np.inf]})
        left = [erfc(-x / np.sqrt(2)) / 2 if np.isfinite(x) else np.nan for x in frame["X"]]
        right = [erfc(x / np.sqrt(2)) / 2 if np.isfinite(x) else np.nan for x in frame["X"]]
        np.testing.assert_allclose(formula(frame, "NORMDIST(X)"), left, atol=0)
        np.testing.assert_allclose(formula(frame, "NORMDIST(100+2*X,100,2)"), left, atol=0)
        np.testing.assert_allclose(formula(frame, 'ZDIST(X,"RIGHT")'), right, atol=0)
        np.testing.assert_allclose(formula(frame, 'ZDIST(X,"two")'), 2 * np.minimum(left, right), atol=0)
        np.testing.assert_allclose(formula(frame, 'NORMINV(ZDIST(X,"right"),100,2,"right")').iloc[:4],
                                   100 + 2 * frame["X"].iloc[:4])
        np.testing.assert_allclose(formula(frame, 'ZINV(ZDIST(X,"two"),"two")').iloc[:4],
                                   frame["X"].iloc[:4].abs(), atol=1e-13)
        np.testing.assert_allclose(formula(frame, "ZPDF(X)").iloc[:4],
                                   np.exp(-frame["X"].iloc[:4] ** 2 / 2) / np.sqrt(2 * np.pi), atol=0)
        self.assertAlmostEqual(formula(frame, "NORMPDF(8,8,2)").iloc[0], 1 / (2 * np.sqrt(2 * np.pi)))
        self.assertAlmostEqual(formula(frame, "PROBIT(.5)").iloc[0], 5.)
        self.assertAlmostEqual(formula(frame, "NORMINV(.5,1e308)").iloc[0], 1e308)
        np.testing.assert_allclose(formula(frame, "NORMDIST(1e308,-1e308,1e308)"),
                                   [erfc(-2 / np.sqrt(2)) / 2] * len(frame))

    def test_other_distribution_formulas_match_elementary_special_cases(self):
        frame = pd.DataFrame({"X": [0., 1., 2., 3., 4.]})
        x = frame["X"].to_numpy()
        np.testing.assert_allclose(formula(frame, "TDIST(X,1)"), .5 - np.arctan(x) / np.pi)
        np.testing.assert_allclose(formula(frame, "TPDF(X,1)"), 1 / (np.pi * (1 + x * x)))
        np.testing.assert_allclose(formula(frame, "TINV(.25,1)"), [1 / np.tan(np.pi / 8)] * len(x))
        np.testing.assert_allclose(formula(frame, "CHIDIST(X,2)"), np.exp(-x / 2))
        np.testing.assert_allclose(formula(frame, "CHISQC(X,2)"), -np.expm1(-x / 2))
        np.testing.assert_allclose(formula(frame, "CHIINV(CHIDIST(X,2),2)"), x, atol=1e-14)
        np.testing.assert_allclose(formula(frame, "FDIST(X,2,2)"), 1 / (1 + x))
        np.testing.assert_allclose(formula(frame, "FPDF(X,2,2)"), 1 / (1 + x) ** 2)
        np.testing.assert_allclose(formula(frame, "FINV(FDIST(X,2,2),2,2)"), x, atol=1e-14)
        np.testing.assert_allclose(formula(frame, "FINV(1e-30,2,2)"), [1e30] * len(x))
        np.testing.assert_allclose(formula(frame, "BINOMIAL(X,3,.5)"), [1, .875, .5, .125, 0])

    def test_distribution_formulas_leave_invalid_values_blank(self):
        frame = pd.DataFrame({"X": [0., 1., 2.]})
        for expression in ("NORMDIST(X,0,0)", "TDIST(X,0)", "FINV(X+2,2,2)", "ZINV(-1)",
                           "PROBIT(0)", "BINOMIAL(X,1.5,.5)", "BINOMIAL(X+.5,3,.5)", "FPDF(0,1,3)"):
            with self.subTest(expression=expression):
                self.assertTrue(formula(frame, expression).isna().all())
        with self.assertRaisesRegex(ValueError, '"left", "right" or "two"'):
            formula(frame, 'ZDIST(X,"unknown")')
        with self.assertRaisesRegex(ValueError, "Unsupported expression"):
            formula(frame, "TDIST(X)")

    def test_row_statistics_use_each_groups_filtered_reference(self):
        frame = pd.DataFrame({"X": [6, 3, 9, 3, 1, np.nan, 4, 5],
                              "Group": ["A", "A", "A", "A", "B", "A", "B", None],
                              "Keep": [1, 1, 0, 1, 1, 1, 0, 1]})
        centered = [.75, -2.25, 3.75, -2.25, -1.5, np.nan, 1.5, np.nan]
        np.testing.assert_allclose(formula(frame, "CENTER(X) OVER Group"), centered)
        deviation = np.sqrt([8.25, 8.25, 8.25, 8.25, 4.5, np.nan, 4.5, np.nan])
        for name in ("STANDARDIZE", "ZSCORE"):
            np.testing.assert_allclose(formula(frame, f"{name}(X) OVER Group"), centered / deviation)
        np.testing.assert_allclose(formula(frame, "RANK(X) OVER Group"), [3, 1.5, 4, 1.5, 1, np.nan, 2, np.nan])
        filtered = "OVER Group WHERE Keep = 1"
        np.testing.assert_allclose(formula(frame, f"CENTER(X) {filtered}"), [2, -1, 5, -1, 0, np.nan, 3, np.nan])
        np.testing.assert_allclose(formula(frame, f"RANK(X) {filtered}"), [3, 1.5, 4, 1.5, 1, np.nan, 2, np.nan])
        np.testing.assert_allclose(formula(frame, f"ZSCORE(X) {filtered}"),
                                   np.array([2, -1, 5, -1, np.nan, np.nan, np.nan, np.nan]) / np.sqrt(3))

    def test_row_statistics_use_the_current_row_in_moving_windows(self):
        frame = pd.DataFrame({"X": [5, 7, 2, 2, 1], "Visit": [3, 5, 1, 4, 2],
                              "Keep": [1, 0, 1, 1, 1]}, index=[2, 8, 9, 6, 7])
        clause = "ORDER BY Visit ROWS 1 PRECEDING 1 FOLLOWING"
        centered = np.array([7 / 3, 2.5, .5, -8 / 3, -5 / 3])
        deviation = np.sqrt([13 / 3, 25 / 2, 1 / 2, 19 / 3, 13 / 3])
        result = formula(frame, f"CENTER(X) {clause}")
        self.assertTrue(result.index.equals(frame.index))
        np.testing.assert_allclose(result, centered)
        np.testing.assert_allclose(formula(frame, f"STANDARDIZE(X) {clause}"), centered / deviation)
        np.testing.assert_allclose(formula(frame, f"RANK(X) {clause}"), [3, 2, 2, 1, 1])
        np.testing.assert_allclose(formula(frame, f"RANK(X) WHERE Keep = 1 {clause}"), [3, np.nan, 2, 1, 1])
        np.testing.assert_allclose(formula(frame, "RANK(X) ORDER BY Visit ROWS UNBOUNDED PRECEDING"),
                                   [3, 5, 1, 2.5, 1])
        self.assertTrue(formula(frame, "ZSCORE(X) ROWS 0 PRECEDING").isna().all())

    def test_row_statistics_scale_large_references_without_changing_rank(self):
        frame = pd.DataFrame({"X": [1.6e308, 1.2e308, 1e-100, 0.0], "Group": ["A", "A", "B", "B"]})
        through_end = "ROWS 1 PRECEDING 1 FOLLOWING"
        for clause in ("OVER Group", f"OVER Group {through_end}"):
            np.testing.assert_allclose(formula(frame, f"CENTER(X) {clause}"), [2e307, -2e307, 5e-101, -5e-101],
                                       atol=0)
            np.testing.assert_allclose(formula(frame, f"ZSCORE(X) {clause}"), np.sqrt(.5) * np.array([1, -1, 1, -1]))
            np.testing.assert_allclose(formula(frame, f"RANK(X) {clause}"), [2, 1, 2, 1])
        # A source integer column can still distinguish observations above 2**53.
        precise = pd.DataFrame({"X": [2**53 + 1, 2**53 + 2, 2**53], "Group": ["A"] * 3})
        for clause in ("OVER Group", "ROWS UNBOUNDED PRECEDING UNBOUNDED FOLLOWING"):
            np.testing.assert_allclose(formula(precise, f"RANK(X) {clause}"), [2, 3, 1])

        extremes = pd.DataFrame({"X": [1.7e308, 1e-200, 0., 2e-200, 3e-200]})
        np.testing.assert_allclose(formula(extremes, f"CENTER(X) {through_end}").iloc[2:],
                                   [-1e-200, 1e-200 / 3, 5e-201], atol=0)
        np.testing.assert_allclose(formula(extremes, f"ZSCORE(X) {through_end}").iloc[2:],
                                   [-1., 1. / np.sqrt(21), np.sqrt(.5)])

    def test_ordered_windows_return_to_original_row_order(self):
        frame = self.frame.assign(Visit=[2, 1, 3, 2, 1, 4])
        summed = formula(frame, "SUM(X) OVER Category ORDER BY Visit ROWS UNBOUNDED PRECEDING")
        np.testing.assert_allclose(summed, [40, 30, 90, 50, 0, np.nan])
        remaining = formula(frame, "COUNT(X) OVER Category ORDER BY Visit DESC ROWS UNBOUNDED PRECEDING")
        np.testing.assert_allclose(remaining, [1, 2, 1, 2, 2, np.nan])
        whole = formula(frame, "MEAN(X) OVER Category ORDER BY Visit")
        np.testing.assert_allclose(whole, [20, 20, 45, 45, 45, np.nan])

    def test_window_boundaries_clip_and_filter_before_counting_rows(self):
        frame = pd.DataFrame({"X": [2, 20, 4, 40, 8, 80], "Keep": [1, 0, 1, 0, 1, 0]})
        averaged = formula(frame, "MEAN(X) WHERE Keep = 1 ROWS 1 PRECEDING 1 FOLLOWING")
        np.testing.assert_allclose(averaged, [3, np.nan, 14 / 3, np.nan, 6, np.nan])
        deviation = formula(frame, "STDERR(X) WHERE Keep = 1 ROWS 1 FOLLOWING")
        np.testing.assert_allclose(deviation, [1, np.nan, 2, np.nan, np.nan, np.nan])
        leading = formula(frame, "MAX(X) ROWS UNBOUNDED FOLLOWING")
        np.testing.assert_allclose(leading, [80, 80, 80, 80, 80, 80])

    def test_tied_sort_values_keep_source_order(self):
        frame = pd.DataFrame({"X": [2, 20, 4, 40], "Order": [1, 2, 1, 2]})
        np.testing.assert_allclose(formula(frame, "SUM(X) ORDER BY Order DESC ROWS UNBOUNDED PRECEDING"),
                                   [62, 20, 66, 60])

    def test_ordered_windows_break_ties_by_multiple_expressions(self):
        frame = pd.DataFrame({"X": [2, 20, 4, 40, 8, 80, 160],
                              "Visit": [1, 2, 1, 2, 1, np.nan, np.nan],
                              "Priority": [1, 1, 2, 3, 2, 1, 1]}, index=[8, 3, 2, 5, 7, 4, 1])
        running = ("SUM(X) ORDER BY Visit ASC, IF(Priority > 1, Priority, 0) DESC"
                   " ROWS UNBOUNDED PRECEDING")
        result = formula(frame, running)
        self.assertTrue(result.index.equals(frame.index))
        np.testing.assert_allclose(result, [14, 74, 4, 54, 12, 154, 314])
        np.testing.assert_allclose(formula(frame, f"IF(X <= 10, ({running}), 0)"),
                                   [14, 0, 4, 0, 12, 0, 0])
        np.testing.assert_allclose(formula(frame, "IF(X <= 10, SUM(X) ORDER BY Visit, 0)"),
                                   [314, 0, 314, 0, 314, 0, 0])
        np.testing.assert_allclose(formula(frame, "SUM(X) ORDER BY Visit, Priority DESC"), [314] * 7)
        with self.assertRaisesRegex(ValueError, "sort expression"):
            formula(frame, "SUM(X) ORDER BY Visit,, Priority DESC ROWS 1 PRECEDING")

    def test_project_reopens_with_live_exclusions_and_formula(self):
        data = Dataset(self.frame)
        data.set_formula("Group mean", "MEAN(X) OVER Category")
        data.excluded.add((1, 0))
        with TemporaryDirectory() as directory:
            project = Path(directory) / "groups.alab"
            save_project(project, {"Measurements": data})
            reopened = load_project(project)["Measurements"]
        self.assertEqual(reopened.formulas, data.formulas)
        np.testing.assert_allclose(reopened.frame()["Group mean"], [10, 10, 45, 45, 45, np.nan])

    def test_imported_window_formula_uses_live_original_column_references(self):
        with TemporaryDirectory() as directory:
            project = Path(directory) / "groups.prism"
            with ZipFile(project, "w") as archive:
                def metadata(path, content):
                    archive.writestr(path, json.dumps(content))
                metadata("document.json", {"sheets": {"data": ["live"]}})
                metadata("data/sheets/live/sheet.json", {"title": "Measurements", "table": {
                    "uid": "values", "format": "multivariable", "dataFormat": "y_single",
                    "dataSets": ["a", "b", "c", "d", "e", "f"],
                }})
                metadata("data/sets/a.json", {"title": "Value"})
                metadata("data/sets/b.json", {"title": "2nd group", "currentType": "categorical"})
                metadata("data/sets/c.json", {"title": "Group average", "valuesStorageData": {
                    "@class": "TransformDataSource", "transform": "MEAN(A) OVER B WHERE A >= 2",
                }})
                metadata("data/sets/d.json", {"title": "Filtered average", "valuesStorageData": {
                    "@class": "TransformDataSource", "transform": 'MEANIF(A, AND(A >= 2, B <> "skip")) OVER B',
                }})
                metadata("data/sets/e.json", {"title": "Running count", "valuesStorageData": {
                    "@class": "TransformDataSource",
                    "transform": "COUNT(A) OVER B ORDER BY B ASC, A DESC ROWS UNBOUNDED PRECEDING",
                }})
                metadata("data/sets/f.json", {"title": "Group rank", "valuesStorageData": {
                    "@class": "TransformDataSource", "transform": "RANK(A) OVER B",
                }})
                archive.writestr("data/tables/values/data.csv",
                                 "1,x,999,999,999,999\n3,x,999,999,999,999\n7,y,999,999,999,999\n9,y,999,999,999,999\n")
            data = Dataset(load_tables(project)["Measurements"])
        calculated = ["Group average", "Filtered average", "Running count", "Group rank"]
        self.assertEqual(set(data.formulas), set(calculated))
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3, 2, 1], [3, 3, 1, 2], [8, 8, 2, 1], [8, 8, 1, 2]])
        data.raw.loc[2, "Value"] = 5
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3, 2, 1], [3, 3, 1, 2], [7, 7, 2, 1], [7, 7, 1, 2]])
        with TemporaryDirectory() as directory:
            project = Path(directory) / "imported.alab"
            save_project(project, {"Measurements": data})
            reopened = load_project(project)["Measurements"]
        self.assertEqual(reopened.formulas, data.formulas)
        np.testing.assert_allclose(reopened.frame()[calculated], data.frame()[calculated])
        reopened.raw.loc[2, "Value"] = 10
        np.testing.assert_allclose(reopened.frame()[calculated], [[3, 3, 2, 1], [3, 3, 1, 2],
                                                                 [9.5, 9.5, 1, 2], [9.5, 9.5, 2, 1]])
