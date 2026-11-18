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

    def test_order_and_invalid_clauses_are_rejected_as_a_whole(self):
        with self.assertRaisesRegex(ValueError, "ORDER BY and ROWS"):
            formula(self.frame, "MEAN(X) OVER Category ORDER BY Keep ROWS 1 PRECEDING")
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
                    "dataSets": ["a", "b", "c", "d"],
                }})
                metadata("data/sets/a.json", {"title": "Value"})
                metadata("data/sets/b.json", {"title": "2nd group", "currentType": "categorical"})
                metadata("data/sets/c.json", {"title": "Group average", "valuesStorageData": {
                    "@class": "TransformDataSource", "transform": "MEAN(A) OVER B WHERE A >= 2",
                }})
                metadata("data/sets/d.json", {"title": "Filtered average", "valuesStorageData": {
                    "@class": "TransformDataSource", "transform": 'MEANIF(A, AND(A >= 2, B <> "skip")) OVER B',
                }})
                archive.writestr("data/tables/values/data.csv", "1,x,999,999\n3,x,999,999\n7,y,999,999\n9,y,999,999\n")
            data = Dataset(load_tables(project)["Measurements"])
        calculated = ["Group average", "Filtered average"]
        self.assertEqual(set(data.formulas), set(calculated))
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3], [3, 3], [8, 8], [8, 8]])
        data.raw.loc[2, "Value"] = 5
        np.testing.assert_allclose(data.frame()[calculated], [[3, 3], [3, 3], [7, 7], [7, 7]])
