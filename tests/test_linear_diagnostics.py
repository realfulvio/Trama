"""Residual diagnostics and pointwise bands for simple linear regression."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.collections import PathCollection, PolyCollection

from analisi.processing import FieldError
from analisi.stats import linear
from analisi.workbench import analyse

X = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
Y = np.array([1.0, 3.0, 2.0, 5.0, 7.0])
RESIDUALS = np.array([0.2, 0.8, -1.6, 0.0, 0.6])
LEVERAGE = np.array([0.6, 0.3, 0.2, 0.3, 0.6])
COOK = RESIDUALS**2 * LEVERAGE / (2 * 1.2 * (1 - LEVERAGE)**2)


def _frame(x=X, y=Y):
    return pd.DataFrame({"X": np.array(x, dtype=float), "Y": np.array(y, dtype=float)})


def _run(frame, **options):
    return analyse("Linear regression", frame, {"X": "X", "Y": "Y", **options})


class LinearDiagnosticsTests(unittest.TestCase):
    def test_level_just_below_one_hundred_has_finite_limits(self):
        level = np.nextafter(100., 0.)
        result = _run(_frame(), Band="Confidence (mean)", **{"Confidence level (%)": level})
        band = result.tables["Pointwise confidence band"]
        self.assertTrue(np.isfinite(band[["Lower", "Upper"]]).to_numpy().all())
        self.assertTrue((band["Lower"] < band["Fitted Y"]).all())
        self.assertTrue((band["Fitted Y"] < band["Upper"]).all())

    def test_legacy_recipe_keeps_one_sheet_and_the_fitted_line(self):
        frame = _frame()
        original = frame.copy(deep=True)
        result = _run(frame)
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(list(result.tables), ["Regression"])
        expected = linear(frame, "X", "Y")
        sheet = result.tables["Regression"]["Value"]
        self.assertEqual(list(sheet.index), list(expected))
        for key, value in expected.items():
            self.assertEqual(sheet[key], value)
        self.assertNotIn("Diagnostics note", sheet.index)
        axes = result.figure.axes[0]
        self.assertEqual(len(result.figure.axes), 1)
        self.assertEqual(axes.get_title(), "Linear regression")
        self.assertEqual(axes.get_xlabel(), "X")
        self.assertEqual(axes.get_ylabel(), "Y")
        self.assertEqual(len(axes.lines), 1)
        self.assertEqual(axes.lines[0].get_color(), "#bc4040")
        self.assertEqual([type(artist) for artist in axes.collections], [PathCollection])
        domain = np.array([frame["X"].min(), frame["X"].max()])
        np.testing.assert_allclose(axes.lines[0].get_xdata(), domain)
        np.testing.assert_allclose(axes.lines[0].get_ydata(), expected["Intercept"] + expected["Slope"] * domain)

    def test_level_is_not_required_when_the_band_is_off(self):
        result = _run(_frame(), Band="None", **{"Confidence level (%)": 0, "Graph": "Fit"})
        self.assertEqual(list(result.tables), ["Regression"])
        self.assertEqual(len(result.figure.axes[0].lines), 1)

    def test_fixture_diagnostics_leverage_and_cook(self):
        frame = _frame()
        original = frame.copy(deep=True)
        result = _run(frame, **{"Residual diagnostics": True})
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(list(result.tables), ["Regression", "Residuals"])
        summary = result.tables["Regression"]["Value"]
        self.assertNotIn("Diagnostics note", summary.index)
        self.assertAlmostEqual(summary["Intercept"], 0.8)
        self.assertAlmostEqual(summary["Slope"], 1.4)
        table = result.tables["Residuals"]
        self.assertEqual(list(table.columns), [
            "Source row", "X", "Y", "Fitted Y", "Residual", "Leverage",
            "Internally studentized residual", "Cook's distance"])
        self.assertEqual(table["Source row"].tolist(), [0, 1, 2, 3, 4])
        np.testing.assert_allclose(table["Residual"], RESIDUALS, atol=1e-12)
        np.testing.assert_allclose(table["Leverage"], LEVERAGE, atol=1e-12)
        np.testing.assert_allclose(table["Cook's distance"], COOK, rtol=1e-10, atol=1e-12)
        self.assertAlmostEqual(np.sum(np.square(table["Residual"])), 3.6, places=12)
        s = np.sqrt(1.2)
        expected_student = RESIDUALS / (s * np.sqrt(1 - LEVERAGE))
        np.testing.assert_allclose(table["Internally studentized residual"], expected_student, rtol=1e-10, atol=1e-12)
        # The high-influence row stays in the table; nothing is marked excluded.
        self.assertEqual(len(table), len(frame))
        self.assertGreater(table["Cook's distance"].max(), 0.5)

    def test_studentized_leverage_and_cook_match_statsmodels(self):
        table = _run(_frame(), **{"Residual diagnostics": True}).tables["Residuals"]
        model = sm.OLS(Y, sm.add_constant(X)).fit()
        influence = model.get_influence()
        np.testing.assert_allclose(table["Leverage"], influence.hat_matrix_diag, rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(table["Internally studentized residual"], influence.resid_studentized_internal,
                                   rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(table["Cook's distance"], influence.cooks_distance[0], rtol=1e-10, atol=1e-12)

    def test_rows_follow_source_order_including_incomplete_pairs(self):
        frame = _frame([0, np.nan, 1, 2, 3, 4], [1, 9, 3, 2, 5, 7])
        frame.index = [10, 11, 12, 13, 14, 15]
        frame["Note"] = list("abcdef")
        original = frame.copy(deep=True)
        table = _run(frame, **{"Residual diagnostics": True}).tables["Residuals"]
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(table["Source row"].tolist(), [10, 12, 13, 14, 15])
        np.testing.assert_allclose(table["X"], X)
        np.testing.assert_allclose(table["Residual"], RESIDUALS, atol=1e-12)
        shuffled = _frame().iloc[[4, 2, 0, 3, 1]]
        ordered = _run(shuffled, **{"Residual diagnostics": True}).tables["Residuals"]
        self.assertEqual(ordered["Source row"].tolist(), [4, 2, 0, 3, 1])
        np.testing.assert_allclose(ordered["X"], [4, 2, 0, 3, 1])
        np.testing.assert_allclose(ordered["Cook's distance"], COOK[[4, 2, 0, 3, 1]], rtol=1e-10, atol=1e-12)

    def test_translated_x_keeps_leverage_and_cook(self):
        base = _run(_frame(), **{"Residual diagnostics": True}).tables["Residuals"]
        shifted = _run(_frame(X + 1e8, Y), **{"Residual diagnostics": True})
        moved = shifted.tables["Residuals"]
        self.assertAlmostEqual(shifted.tables["Regression"].loc["Slope", "Value"], 1.4)
        np.testing.assert_allclose(moved["Leverage"], base["Leverage"], rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(moved["Cook's distance"], base["Cook's distance"], rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(moved["Internally studentized residual"], base["Internally studentized residual"],
                                   rtol=1e-10, atol=1e-12)
        self.assertNotIn("Diagnostics note", shifted.tables["Regression"].index)

    def test_perfect_line_blanks_scaled_residuals_and_explains_them(self):
        perfect = _frame(X, 2 * X + 3)
        result = _run(perfect, **{"Residual diagnostics": True, "Band": "Confidence (mean)"})
        table = result.tables["Residuals"]
        np.testing.assert_allclose(table["Residual"], 0, atol=1e-12)
        np.testing.assert_allclose(table["Leverage"], LEVERAGE, atol=1e-12)
        self.assertTrue(table["Internally studentized residual"].isna().all())
        self.assertTrue(table["Cook's distance"].isna().all())
        note = result.tables["Regression"].loc["Diagnostics note", "Value"]
        self.assertIsInstance(note, str)
        self.assertIn("blank", note)
        band = result.tables["Pointwise confidence band"]
        self.assertTrue(np.allclose(band["Upper"], band["Lower"]))
        np.testing.assert_allclose(band["Lower"], band["Fitted Y"], atol=1e-12)
        self.assertNotIn("prediction", band["Band"].iloc[0].lower())
        self.assertIn("pointwise", band["Band"].iloc[0].lower())
        self.assertIn("not simultaneous", band["Band"].iloc[0].lower())

    def test_unit_leverage_stays_in_the_table_with_scaled_residuals_blank(self):
        frame = _frame([0, 0, 1], [1, 3, 2])
        table = _run(frame, **{"Residual diagnostics": True}).tables["Residuals"]
        self.assertEqual(len(table), 3)
        np.testing.assert_allclose(table["Leverage"], [0.5, 0.5, 1], atol=1e-12)
        np.testing.assert_allclose(table["Residual"], [-1, 1, 0], atol=1e-12)
        self.assertTrue(table["Internally studentized residual"].iloc[:2].notna().all())
        self.assertTrue(pd.isna(table["Internally studentized residual"].iloc[2]))
        self.assertTrue(table["Cook's distance"].iloc[:2].notna().all())
        self.assertTrue(pd.isna(table["Cook's distance"].iloc[2]))
        self.assertIn("Diagnostics note", _run(frame, **{"Residual diagnostics": True}).tables["Regression"].index)

    def test_mean_band_at_the_fixture_center(self):
        result = _run(_frame(), **{"Band": "Confidence (mean)", "Confidence level (%)": 95})
        self.assertEqual(list(result.tables), ["Regression", "Pointwise confidence band"])
        band = result.tables["Pointwise confidence band"]
        self.assertNotIn("prediction", " ".join(band.columns).lower())
        self.assertNotIn("prediction", band["Band"].iloc[0].lower())
        row = band.loc[np.isclose(band["X"], 2)].iloc[0]
        np.testing.assert_allclose(row["Fitted Y"], 3.6, atol=1e-12)
        np.testing.assert_allclose([row["Lower"], row["Upper"]], [2.040926, 5.159074], atol=1e-6)
        np.testing.assert_allclose(band["Fitted Y"] - band["Lower"], band["Upper"] - band["Fitted Y"], atol=1e-10)
        axes = result.figure.axes[0]
        polys = [artist for artist in axes.collections if isinstance(artist, PolyCollection)]
        points = [artist for artist in axes.collections if isinstance(artist, PathCollection)]
        self.assertEqual(len(polys), 1)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(polys[0].get_alpha(), 0.15)
        self.assertEqual(len(axes.lines), 1)

    def test_prediction_band_and_residual_graph_share_one_figure(self):
        result = _run(_frame(), **{
            "Residual diagnostics": True,
            "Band": "Prediction (new observation)",
            "Confidence level (%)": 95,
            "Graph": "Residuals vs fitted",
        })
        self.assertEqual(list(result.tables), ["Regression", "Residuals", "Pointwise prediction band"])
        band = result.tables["Pointwise prediction band"]
        row = band.loc[np.isclose(band["X"], 2)].iloc[0]
        np.testing.assert_allclose(row["Fitted Y"], 3.6, atol=1e-12)
        np.testing.assert_allclose([row["Lower"], row["Upper"]], [-0.218936, 7.418936], atol=1e-6)
        self.assertIn("new observation", band["Band"].iloc[0].lower())
        self.assertIn("pointwise", band["Band"].iloc[0].lower())
        self.assertEqual(len(result.figure.axes), 1)
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "Fitted Y")
        self.assertEqual(axes.get_ylabel(), "Residual")
        self.assertTrue(any(np.allclose(line.get_ydata(), 0) for line in axes.lines))
        self.assertFalse(any(isinstance(artist, PolyCollection) for artist in axes.collections))
        np.testing.assert_allclose(axes.collections[0].get_offsets()[:, 1], RESIDUALS, atol=1e-12)

    def test_invalid_level_is_rejected_before_plotting(self):
        frame = _frame()
        for level in (0, 100, -5, "abc", float("nan"), float("inf")):
            with self.subTest(level=level):
                with patch("analisi.linear_diagnostics._plot", side_effect=AssertionError("plotted too soon")):
                    with self.assertRaises(FieldError) as caught:
                        _run(frame, **{"Band": "Confidence (mean)", "Confidence level (%)": level})
                self.assertEqual(caught.exception.field, "Confidence level (%)")
                self.assertIn("between", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
