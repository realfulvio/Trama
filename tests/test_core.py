import json
import math
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi import (
    Dataset, describe, ellipse, factorial_anova, formula, hierarchical, kmeans,
    linear, load_tables, nonlinear, survival, t_test,
)


class ImportTests(unittest.TestCase):
    def test_csv_preserves_zero_padded_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.csv"
            path.write_text("id,value\n001,1.2\n1,3.4\n", encoding="utf-8")
            frame = load_tables(path)["ids"]
            self.assertEqual(frame["id"].tolist(), ["001", "1"])
            self.assertEqual(frame["value"].tolist(), [1.2, 3.4])

    def test_legacy_uses_metadata_and_has_no_header_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.prism"
            with ZipFile(path, "w") as archive:
                archive.writestr("document.json", json.dumps({"sheets": {"data": ["sheet"]}}))
                archive.writestr("data/sheets/sheet/sheet.json", json.dumps({
                    "title": "My Data", "table": {
                        "uid": "table", "format": "multivariable", "dataFormat": "y_single",
                        "dataSets": ["id", "value"],
                    },
                }))
                archive.writestr("data/sets/id.json", '{"title":"ID","dataType":"text"}')
                archive.writestr("data/sets/value.json", '{"title":"Value","dataType":"numeric"}')
                archive.writestr("data/tables/table/data.csv", "NA,2\n002,\n")
            frame = load_tables(path)["My Data"]
            self.assertEqual(list(frame), ["ID", "Value"])
            self.assertEqual(list(frame["ID"]), ["NA", "002"])
            self.assertEqual(frame["Value"].iloc[0], 2)
            self.assertTrue(pd.isna(frame["Value"].iloc[1]))


class AnalysisTests(unittest.TestCase):
    def test_t_test_pairs_by_subject_and_rejects_duplicates(self):
        frame = pd.DataFrame({"s": [3, 1, 2, 1, 2, 3], "g": list("aaabbb"),
                              "y": [6, 5, 4, 1, 3, 4]})
        result = t_test(frame, "y", "g", "paired", subject="s", order=("a", "b"))
        self.assertAlmostEqual(result["Difference"], 7 / 3)
        self.assertAlmostEqual(result["t"], 7 / np.sqrt(7))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            t_test(pd.concat([frame, frame.iloc[:1]]), "y", "g", "paired", subject="s")

    def test_balanced_factorial_anova(self):
        rows = [(a, b, 2 * a + 3 * b + err)
                for a in [0, 1] for b in [0, 1] for err in [-1, 0, 1]]
        frame = pd.DataFrame(rows, columns=["A a", "B b", "Y"])
        result = factorial_anova(frame, "Y", ["A a", "B b"], 2)
        self.assertAlmostEqual(result.loc["A a", "F"], 12)
        self.assertAlmostEqual(result.loc["A a:B b", "F"], 0)
        with self.assertRaisesRegex(ValueError, "rank"):
            factorial_anova(frame[(frame["A a"] == 0) | (frame["B b"] == 0)], "Y", ["A a", "B b"], 2)

    def test_kaplan_meier_uses_risk_set_at_tied_censor(self):
        data = pd.DataFrame({"time": [1, 1, 2, 3], "event": [0, 1, 1, 0]})
        result, comparison = survival(data, "time", "event")
        curve = result["All"]
        self.assertEqual(list(curve["At risk"]), [4, 2, 1])
        np.testing.assert_allclose(curve["Survival"], [.75, .375, .375])
        self.assertIsNone(comparison)
        with self.assertRaisesRegex(ValueError, "0.*1"):
            survival(data.assign(event=[1, 0, 2, 0]), "time", "event")

    def test_normalized_dose_response(self):
        x = np.geomspace(.1, 100, 30)
        y = 100 / (1 + (x / 8) ** 1.4)
        fits = nonlinear(pd.DataFrame({"dose": x, "response": y}), "dose", "response",
                         "Normalized inhibition")
        self.assertAlmostEqual(fits["All"].parameters.loc["IC50", "Estimate"], 8, places=5)
        self.assertAlmostEqual(fits["All"].parameters.loc["Hill slope", "Estimate"], 1.4, places=5)

    def test_unidentifiable_logistic_model_is_rejected(self):
        x = [0, 1, 2, 3, 1e10, 1e10 + 1, 1e10 + 2, 1e10 + 3]
        data = pd.DataFrame({"dose": x, "response": [0] * 4 + [1] * 4})
        with self.assertRaisesRegex(ValueError, "reliably"):
            nonlinear(data, "dose", "response", "Logistic (4 parameters)")

    def test_formula_does_not_change_column_names_or_allow_complex_values(self):
        data = pd.DataFrame({"A^2": [2, 3]})
        self.assertEqual(formula(data, '=COL("A^2")^2').tolist(), [4., 9.])
        with self.assertRaisesRegex(ValueError, "Complex"):
            formula(data, "=(-1)^.5")

    def test_cluster_assignment_and_dendrogram(self):
        data = pd.DataFrame({"x": [0, .1, 9, 9.1], "y": [0, .2, 9, 9.2]})
        km = kmeans(data, ["x", "y"], 2)
        labels = km.labels.to_numpy()
        self.assertEqual(labels[0], labels[1])
        self.assertEqual(labels[2], labels[3])
        self.assertNotEqual(labels[0], labels[2])
        hc = hierarchical(data, ["x", "y"], 2)
        self.assertEqual(hc.tree.shape, (3, 4))
        self.assertAlmostEqual(hc.tree[0, 2], np.sqrt(.05))

    def test_confidence_ellipse_is_centered_and_closed(self):
        points = np.array([[-1, 0], [1, 0], [0, 2], [0, -2]])
        contour = ellipse(points, .95)
        np.testing.assert_allclose(contour[0], contour[-1], atol=1e-10)
        np.testing.assert_allclose(contour[:-1].mean(axis=0), [0, 0], atol=1e-10)
        self.assertGreater(np.ptp(contour[:, 1]), np.ptp(contour[:, 0]))

    def test_confidence_ellipses_are_invariant_to_units_on_each_axis(self):
        points = np.array([[-1., -1.], [-1., 1.], [1., 1.], [1., -1.]])
        for units in (np.array([1e-9, 1e9]), np.array([1e-165, 1e165])):
            center = np.array([5., -4.]) * units
            for kind, radius in (("mean", math.sqrt(19)), ("data", math.sqrt(-8 * math.log(.05) / 3))):
                with self.subTest(x_units=units[0], kind=kind):
                    contour = (ellipse(points * units + center, .95, kind) - center) / units
                    np.testing.assert_allclose(np.linalg.norm(contour, axis=1), radius, rtol=1e-12)
                    np.testing.assert_allclose(contour[0], contour[-1], atol=1e-12)
        collinear = np.array([[0., 0.], [1e-165, 1e165], [2e-165, 2e165]])
        with self.assertRaisesRegex(ValueError, "collinear"):
            ellipse(collinear)

    def test_calculated_column_updates_after_edit(self):
        data = Dataset(pd.DataFrame({"Sample mass": [4., 12.], "ratio": [2., 3.]}))
        data.set_formula("Adjusted", '=COL("Sample mass") / ratio')
        self.assertEqual(data.frame()["Adjusted"].tolist(), [2., 4.])
        data.raw.loc[0, "ratio"] = 4
        self.assertEqual(data.frame()["Adjusted"].tolist(), [1., 4.])
        with self.assertRaises(ValueError):
            data.set_formula("ratio", 'Adjusted + 1')
        self.assertNotIn("ratio", data.formulas)
        with self.assertRaises(ValueError):
            formula(data.raw, "__import__('os').getcwd()")

    def test_summary_and_regression(self):
        data = pd.DataFrame({"x": [1, 2, 3, 4], "y": [3, 5, 7, 9]})
        self.assertAlmostEqual(describe(data, ["y"]).loc["y", "Mean"], 6)
        self.assertAlmostEqual(linear(data, "x", "y")["Slope"], 2)


if __name__ == "__main__":
    unittest.main()
