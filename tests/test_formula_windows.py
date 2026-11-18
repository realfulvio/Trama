"""Regression cases for worksheet statistics scoped to groups and filters."""
import json
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
                    "dataSets": ["a", "b", "c", "d", "e"],
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
                archive.writestr("data/tables/values/data.csv",
                                 "1,x,999,999,999\n3,x,999,999,999\n7,y,999,999,999\n9,y,999,999,999\n")
            data = Dataset(load_tables(project)["Measurements"])
        calculated = ["Group average", "Filtered average", "Running count"]
        self.assertEqual(set(data.formulas), set(calculated))
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3, 2], [3, 3, 1], [8, 8, 2], [8, 8, 1]])
        data.raw.loc[2, "Value"] = 5
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3, 2], [3, 3, 1], [7, 7, 2], [7, 7, 1]])
        with TemporaryDirectory() as directory:
            project = Path(directory) / "imported.alab"
            save_project(project, {"Measurements": data})
            reopened = load_project(project)["Measurements"]
        self.assertEqual(reopened.formulas, data.formulas)
        np.testing.assert_allclose(reopened.frame()[calculated], data.frame()[calculated])
