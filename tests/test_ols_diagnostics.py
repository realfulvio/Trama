"""Multiple linear diagnostics, profiles and residual plots beyond the orthogonal oracle."""
import unittest

import numpy as np
import pandas as pd

from analisi.processing import FieldError
from analisi.workbench import analyse

METHOD = "Multiple regression"


def _fit(frame, **extra):
    options = {"Response": "Y", "Predictors": ["X", "A", "B"], "Categorical predictors": ["A", "B"],
               "Family": "Linear", **extra}
    return analyse(METHOD, frame, options)


class MultipleLinearDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Y": [1., 3, 2, 6, 4, 5, 7, 9],
            "X": [0., 0, 0, 0, 1, 1, 1, 1],
            "A": ["a", "a", "b", "b", "a", "a", "b", "b"],
            "B": ["x", "y", "x", "y", "x", "y", "x", "y"],
        })
        self.frame.index = [4, 9, 10, 15, 16, 20, 21, 30]

    def test_two_categories_keep_row_identity_and_reference_coding(self):
        self.frame.loc[9, "Y"] = np.nan
        result = _fit(self.frame, **{
            "Linear diagnostics": True,
            "Linear profiles": [{"name": "Corner", "values": {"X": 1, "A": "b", "B": "y"}}],
            "Linear CI (%)": 90,
        })
        diagnostics = result.tables["Linear diagnostics"]
        self.assertEqual(diagnostics["Source row"].tolist(), [4, 10, 15, 16, 20, 21, 30])
        self.assertEqual(result.tables["Reference levels"]["Reference"].tolist(), ["a", "x"])
        prediction = result.tables["Linear predictions"].iloc[0]
        self.assertEqual(prediction["Profile"], "Corner")
        self.assertGreater(prediction["Mean CI high"], prediction["Prediction"])
        self.assertGreater(prediction["Prediction interval high"], prediction["Mean CI high"])
        self.assertLess(prediction["Prediction interval low"], prediction["Mean CI low"])

    def test_unknown_level_names_the_profile_and_the_predictor(self):
        with self.assertRaises(FieldError) as caught:
            _fit(self.frame, **{"Linear profiles": [{"name": "Bad", "values": {"X": 0, "A": "z", "B": "x"}}]})
        self.assertEqual(caught.exception.field, "Linear profiles")
        self.assertIn("Bad", str(caught.exception))
        self.assertIn("A", str(caught.exception))

    def test_rank_deficiency_is_unchanged(self):
        frame = pd.DataFrame({"Y": [1., 2, 3, 4], "X": [1., 2, 3, 4], "Z": [2., 4, 6, 8]})
        options = {"Response": "Y", "Predictors": ["X", "Z"], "Categorical predictors": [], "Family": "Linear",
                   "Linear diagnostics": True}
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            analyse(METHOD, frame, options)

    def test_zero_variance_blanks_studentized_residuals_and_keeps_the_fit(self):
        x = np.array([-1., 0, 1, 2])
        frame = pd.DataFrame({"X": x, "Y": 4 + 3 * x})
        options = {"Response": "Y", "Predictors": ["X"], "Categorical predictors": [], "Family": "Linear",
                   "Linear diagnostics": True}
        result = analyse(METHOD, frame, options)
        rows = result.tables["Linear diagnostics"]
        self.assertTrue(rows["Internally studentized residual"].isna().all())
        self.assertTrue(rows["Cook's distance"].isna().all())
        self.assertAlmostEqual(result.tables["Linear model diagnostics"].loc["Residual variance", "Value"], 0)
        np.testing.assert_allclose(rows["PRESS residual"], 0, atol=1e-8)
        self.assertAlmostEqual(result.tables["Linear model diagnostics"].loc["PRESS", "Value"], 0, places=8)
        np.testing.assert_allclose(result.tables["Coefficients"]["Estimate"], [4, 3])
        self.assertIn("blank", result.tables["Linear model diagnostics"]["Note"].iloc[0])

    def test_unit_leverage_blanks_press_without_dropping_the_fit(self):
        frame = pd.DataFrame({"Z": [0., 0, 0, 1], "Y": [1., 2, 3, 8]})
        options = {"Response": "Y", "Predictors": ["Z"], "Categorical predictors": [], "Family": "Linear",
                   "Linear diagnostics": True}
        result = analyse(METHOD, frame, options)
        rows = result.tables["Linear diagnostics"]
        self.assertAlmostEqual(rows["Leverage"].iloc[-1], 1)
        self.assertTrue(np.isnan(rows["PRESS residual"].iloc[-1]))
        self.assertTrue(np.isnan(rows["Cook's distance"].iloc[-1]))
        self.assertTrue(rows["Leverage"].iloc[:-1].notna().all())
        self.assertTrue(np.isnan(result.tables["Linear model diagnostics"].loc["PRESS", "Value"]))
        self.assertIn("Coefficients", result.tables)
        self.assertIn("leverage is one", result.tables["Linear model diagnostics"]["Note"].iloc[0])

    def test_large_offset_and_small_units_keep_residual_diagnostics(self):
        options = {"Linear diagnostics": True}
        reference = _fit(self.frame, **options).tables
        variance = reference["Linear model diagnostics"].loc["Residual variance", "Value"]
        fields = ["Internally studentized residual", "Cook's distance"]
        for multiplier, offset in ((1., 1_000_000.), (1e-8, 0.)):
            with self.subTest(multiplier=multiplier, offset=offset):
                changed = self.frame.assign(Y=self.frame["Y"] * multiplier + offset)
                result = _fit(changed, **options).tables
                observed = result["Linear model diagnostics"].loc["Residual variance", "Value"]
                np.testing.assert_allclose(observed / multiplier**2, variance, rtol=1e-8)
                np.testing.assert_allclose(result["Linear diagnostics"][fields],
                                           reference["Linear diagnostics"][fields], rtol=1e-8, atol=1e-9)

    def test_defaults_match_a_recipe_without_the_new_keys(self):
        base = {"Response": "Y", "Predictors": ["X"], "Categorical predictors": [], "Family": "Linear"}
        frame = self.frame[["Y", "X"]]
        legacy = analyse(METHOD, frame, base)
        same = analyse(METHOD, frame, {**base, "Linear diagnostics": False, "Linear residual plot": "None",
                                       "Linear profiles": [], "Linear CI (%)": 95})
        self.assertEqual(list(legacy.tables), list(same.tables))
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], same.tables[name])
        self.assertIsNone(same.figure)
        plotted = analyse(METHOD, frame, {**base, "Linear residual plot": "Residuals vs fitted"})
        self.assertNotIn("Linear diagnostics", plotted.tables)
        self.assertEqual(list(plotted.tables), list(legacy.tables))
        offsets = plotted.figure.axes[0].collections[0].get_offsets()
        np.testing.assert_allclose(offsets[:, 0], legacy.tables["Fitted values"]["Fitted"])
        self.assertTrue(any(np.allclose(line.get_ydata(), 0) for line in plotted.figure.axes[0].lines))

    def test_confidence_level_and_other_families(self):
        base = {"Response": "Y", "Predictors": ["X"], "Categorical predictors": [], "Family": "Linear"}
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, self.frame[["Y", "X"]], {**base, "Linear CI (%)": 100})
        self.assertEqual(caught.exception.field, "Linear CI (%)")
        logistic = pd.DataFrame({"Y": [0, 1, 0, 1, 1, 0, 1, 0], "X": [0., 1, 0, 1, 0, 1.5, 0.2, 1]})
        plain = analyse(METHOD, logistic, {"Response": "Y", "Predictors": ["X"], "Categorical predictors": [],
                                            "Family": "Logistic"})
        ignored = analyse(METHOD, logistic, {"Response": "Y", "Predictors": ["X"], "Categorical predictors": [],
                                              "Family": "Logistic", "Linear CI (%)": 200, "Linear diagnostics": True})
        pd.testing.assert_frame_equal(plain.tables["Coefficients"], ignored.tables["Coefficients"])
        self.assertNotIn("Linear diagnostics", ignored.tables)
