"""Four-parameter logistic inverse calibration, inside the observed standard range.

Response columns are the algebraic 4PL, not the catalog equation under test.
"""
import unittest

import numpy as np
import pandas as pd

from analisi.curve_models import MODELS
from analisi.nonlinear_calibration import (CONCENTRATION_4PL, IN_RANGE, LOG10_4PL, OUT_OF_RANGE, POWER_COLUMN,
                                           calibration_choice_error, interpolate_standard_curve)
from analisi.processing import FieldError
from analisi.workbench import analyse


def concentration_response(x, bottom, top, mid, hill):
    """Bottom + (Top − Bottom) / (1 + (Mid / x)^Hill), with the x = 0 limit written out."""
    x = np.asarray(x, dtype=float)
    y = np.empty(x.shape, dtype=float)
    # Stimulation (hill > 0) falls to Bottom. Inhibition (hill < 0) rises to Top.
    y[x == 0] = bottom if hill > 0 else top
    positive = x > 0
    ratio = (mid / x[positive]) ** hill
    y[positive] = bottom + (top - bottom) / (1.0 + ratio)
    return y


def log10_response(x, bottom, top, log_mid, hill):
    """Bottom + (Top − Bottom) / (1 + 10^(Hill · (logMid − x))). X is already log10."""
    x = np.asarray(x, dtype=float)
    return bottom + (top - bottom) / (1.0 + np.power(10.0, hill * (log_mid - x)))


class FourPLCalibrationTests(unittest.TestCase):
    def test_c1_increasing_concentration_inverts_inside_the_observed_domain(self):
        x = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y = concentration_response(x, 2.0, 18.0, 4.0, 2.0)
        at_32 = 2.0 + 16.0 * 1024.0 / 1040.0
        unknown = [2.0, np.nan, 5.2, np.nan, 10.0, 14.8, at_32, 17.9]
        frame = pd.DataFrame({"Row titles": list("ABCDEFGH"), "Dose": x, "Signal": y, "Unknown": unknown},
                             index=np.arange(3, 11))
        result = interpolate_standard_curve(frame, "Dose", "Signal", "Unknown", "Nonlinear",
                                            "Stimulation (variable slope)")
        table = result.tables["Interpolated values"]
        self.assertEqual(list(table.columns),
                         ["Source row", "Row title", "Response", "Interpolated X", "Status", "Domain low", "Domain high"])
        self.assertNotIn(POWER_COLUMN, table.columns)
        self.assertEqual(table["Source row"].tolist(), [3, 5, 7, 8, 9, 10])
        self.assertEqual(table["Row title"].tolist(), ["A", "C", "E", "F", "G", "H"])
        solved = table["Interpolated X"].to_numpy(dtype=float)
        np.testing.assert_allclose(solved[:5], [0.0, 2.0, 4.0, 8.0, 32.0], atol=1e-5, rtol=0)
        self.assertTrue(np.isnan(solved[5]))
        self.assertNotEqual(solved[5], 0.0)
        self.assertEqual(table["Status"].tolist(), [IN_RANGE, IN_RANGE, IN_RANGE, IN_RANGE, IN_RANGE, OUT_OF_RANGE])
        self.assertTrue((table["Domain low"] == 0.0).all())
        self.assertTrue((table["Domain high"] == 32.0).all())
        parameters = result.tables["Calibration parameters"]
        self.assertEqual(list(parameters.index), ["Bottom", "Top", "EC50", "Hill slope"])
        np.testing.assert_allclose(parameters["Estimate"], [2.0, 18.0, 4.0, 2.0], atol=1e-5, rtol=0)
        self.assertLess(17.9, 18.0)
        self.assertGreater(17.9, at_32)

        drawn = analyse("Interpolate a standard curve", frame, {
            "X": "Dose", "Y": "Signal", "Unknown responses": "Unknown", "Curve": "Nonlinear",
            "Model": "Stimulation (variable slope)"}).figure.axes[0]
        self.assertEqual([text.get_text() for text in drawn.get_legend().get_texts()],
                         ["Standards", "Stimulation (variable slope)", "Estimates"])
        self.assertEqual(len(drawn.collections[1].get_offsets()), 5)
        self.assertFalse(np.any(np.isclose(drawn.collections[1].get_offsets()[:, 1], 17.9)))

    def test_c2_log10_inhibition_keeps_the_entered_x_unit(self):
        x = np.array([-4.0, -3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 1.0])
        y = log10_response(x, 5.0, 45.0, -1.0, -1.5)
        query_x = np.array([-4.0, -2.25, -1.0, 0.5, 1.0])
        unknown = np.full(x.shape, np.nan)
        unknown[:5] = log10_response(query_x, 5.0, 45.0, -1.0, -1.5)
        unknown[5] = 45.0
        unknown[6] = 5.0
        frame = pd.DataFrame({"Row titles": list("ABCDEFGH"), "log dose": x, "Signal": y, "Unknown": unknown})
        model = "Inhibition (variable slope, log10 X)"
        result = interpolate_standard_curve(frame, "log dose", "Signal", "Unknown", "Nonlinear", model)
        table = result.tables["Interpolated values"]
        self.assertEqual(list(table.columns),
                         ["Source row", "Row title", "Response", "Interpolated X", POWER_COLUMN, "Status",
                          "Domain low", "Domain high"])
        solved = table["Interpolated X"].to_numpy(dtype=float)
        np.testing.assert_allclose(solved[:5], query_x, atol=1e-5, rtol=0)
        self.assertTrue(np.isnan(solved[5:]).all())
        self.assertFalse(np.any(solved[5:] == 0))
        self.assertEqual(table["Status"].tolist(), [IN_RANGE] * 5 + [OUT_OF_RANGE, OUT_OF_RANGE])
        power = table[POWER_COLUMN].to_numpy(dtype=float)
        np.testing.assert_allclose(power[:5], np.power(10.0, query_x), atol=1e-8, rtol=0)
        self.assertTrue(np.isnan(power[5:]).all())
        self.assertFalse(np.any(np.isclose(solved[:5], np.power(10.0, query_x), equal_nan=True)))
        parameters = result.tables["Calibration parameters"]
        self.assertEqual(list(parameters.index), ["Bottom", "Top", "Log IC50", "Hill slope"])
        np.testing.assert_allclose(parameters["Estimate"], [5.0, 45.0, -1.0, -1.5], atol=1e-5, rtol=0)
        self.assertGreater(result.curve[0, 1], result.curve[-1, 1])
        self.assertLess(result.curve[0, 0], 0)
        self.assertEqual(result.tables["Fit diagnostics"].at["N", "Value"], 8)

        drawn = analyse("Interpolate a standard curve", frame, {
            "X": "log dose", "Y": "Signal", "Unknown responses": "Unknown", "Curve": "Nonlinear",
            "Model": model}).figure.axes[0]
        self.assertEqual(drawn.get_xscale(), "linear")
        offsets = drawn.collections[1].get_offsets()
        self.assertEqual(len(offsets), 5)
        self.assertLess(offsets[:, 0].min(), 0)
        self.assertLess(offsets[:, 0].max(), 2)
        self.assertGreater(drawn.lines[0].get_ydata()[0], drawn.lines[0].get_ydata()[-1])

    def test_c3_inhibition_on_concentration_includes_the_zero_limit(self):
        x = np.array([0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0])
        y = concentration_response(x, 3.0, 15.0, 5.0, -1.0)
        self.assertEqual(y[0], 15.0)
        unknown = np.full(x.shape, np.nan)
        unknown[0] = 15.0
        unknown[1] = float(concentration_response(5.0, 3.0, 15.0, 5.0, -1.0))
        unknown[2] = 3.0
        frame = pd.DataFrame({"X": x, "Y": y, "Unknown": unknown})
        model = "Inhibition (variable slope)"
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", model)
        table = result.tables["Interpolated values"]
        np.testing.assert_allclose(table["Interpolated X"].iloc[:2], [0.0, 5.0], atol=1e-5, rtol=0)
        self.assertTrue(np.isnan(table["Interpolated X"].iloc[2]))
        self.assertEqual(table["Status"].tolist(), [IN_RANGE, IN_RANGE, OUT_OF_RANGE])
        self.assertEqual(list(result.tables["Calibration parameters"].index), ["Bottom", "Top", "IC50", "Hill slope"])
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"], [3.0, 15.0, 5.0, -1.0],
                                   atol=1e-5, rtol=0)
        # The catalog limit at zero is part of the equation, and it is Top for inhibition.
        self.assertEqual(MODELS[model].equation(np.array([0.0]), 3.0, 15.0, 5.0, -1.0).item(), 15.0)

    def test_c3_stimulation_on_log10_x_allows_negative_log_concentrations(self):
        x = np.array([-3.0, -2.0, -1.0, 0.0, 0.5, 1.0, 2.0])
        y = log10_response(x, 1.0, 11.0, 0.0, 1.2)
        unknown = np.full(x.shape, np.nan)
        unknown[0] = float(log10_response(-1.5, 1.0, 11.0, 0.0, 1.2))
        unknown[1] = float(log10_response(-3.0, 1.0, 11.0, 0.0, 1.2))
        frame = pd.DataFrame({"X": x, "Y": y, "Unknown": unknown})
        model = "Stimulation (variable slope, log10 X)"
        result = interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", model)
        table = result.tables["Interpolated values"]
        np.testing.assert_allclose(table["Interpolated X"], [-1.5, -3.0], atol=1e-5, rtol=0)
        np.testing.assert_allclose(table[POWER_COLUMN], [10 ** -1.5, 10 ** -3.0], rtol=1e-6, atol=0)
        self.assertEqual(list(result.tables["Calibration parameters"].index),
                         ["Bottom", "Top", "Log EC50", "Hill slope"])
        np.testing.assert_allclose(result.tables["Calibration parameters"]["Estimate"], [1.0, 11.0, 0.0, 1.2],
                                   atol=1e-4, rtol=0)
        self.assertLess(result.curve[0, 1], result.curve[-1, 1])

    def test_c3_constant_negative_short_duplicate_excluded_and_empty_standard(self):
        x = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y = concentration_response(x, 2.0, 18.0, 4.0, 2.0)
        model = "Stimulation (variable slope)"
        flat = pd.DataFrame({"X": x, "Y": np.full(x.shape, 6.0), "Unknown": np.full(x.shape, 6.0)})
        with self.assertRaisesRegex(ValueError, "zero variation"):
            interpolate_standard_curve(flat, "X", "Y", "Unknown", "Nonlinear", model)
        negative = pd.DataFrame({"X": np.array([-1.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]),
                                 "Y": y, "Unknown": 10.0})
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            interpolate_standard_curve(negative, "X", "Y", "Unknown", "Nonlinear", model)
        short = pd.DataFrame({"X": [1.0, 2.0, 4.0], "Y": concentration_response([1.0, 2.0, 4.0], 2, 18, 4, 2),
                              "Unknown": 10.0})
        with self.assertRaisesRegex(ValueError, "distinct X"):
            interpolate_standard_curve(short, "X", "Y", "Unknown", "Nonlinear", model)

        same = float(concentration_response(2.0, 2.0, 18.0, 4.0, 2.0))
        unknown = [same, np.nan, same, np.nan, np.nan, np.nan, np.nan, np.nan]
        duplicated = pd.DataFrame({"X": x, "Y": y, "Unknown": unknown}, index=np.arange(20, 28))
        table = interpolate_standard_curve(duplicated, "X", "Y", "Unknown", "Nonlinear", model).tables[
            "Interpolated values"]
        self.assertEqual(table["Source row"].tolist(), [20, 22])
        np.testing.assert_allclose(table["Interpolated X"], [2.0, 2.0], atol=1e-5, rtol=0)

        excluded = unknown.copy()
        excluded[2] = np.nan
        hidden = pd.DataFrame({"X": x, "Y": y, "Unknown": excluded})
        kept = interpolate_standard_curve(hidden, "X", "Y", "Unknown", "Nonlinear", model).tables[
            "Interpolated values"]
        self.assertEqual(kept["Source row"].tolist(), [0])

        censored = y.copy()
        censored[-1] = np.nan
        unknown = np.full(x.shape, np.nan)
        unknown[0] = float(concentration_response(8.0, 2.0, 18.0, 4.0, 2.0))
        unknown[1] = float(concentration_response(32.0, 2.0, 18.0, 4.0, 2.0))
        trimmed = pd.DataFrame({"X": x, "Y": censored, "Unknown": unknown})
        trimmed_table = interpolate_standard_curve(trimmed, "X", "Y", "Unknown", "Nonlinear", model).tables[
            "Interpolated values"]
        self.assertEqual(trimmed_table["Domain high"].iloc[0], 16.0)
        self.assertEqual(trimmed_table["Status"].tolist(), [IN_RANGE, OUT_OF_RANGE])
        np.testing.assert_allclose(trimmed_table["Interpolated X"].iloc[:1], [8.0], atol=1e-5, rtol=0)
        self.assertTrue(np.isnan(trimmed_table["Interpolated X"].iloc[1]))

    def test_dialog_choice_names_the_field_for_domain_and_shape_problems(self):
        x = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y = concentration_response(x, 2.0, 18.0, 4.0, 2.0)
        model = "Stimulation (variable slope)"
        negative = pd.DataFrame({"X": np.r_[-1.0, x[1:]], "Y": y})
        with self.assertRaises(FieldError) as domain:
            calibration_choice_error(negative, "X", "Y", "Nonlinear", model)
        self.assertEqual(domain.exception.field, "Model")
        short = pd.DataFrame({"X": [1.0, 2.0, 4.0], "Y": [2.0, 5.0, 10.0]})
        with self.assertRaises(FieldError) as few:
            calibration_choice_error(short, "X", "Y", "Nonlinear", model)
        self.assertEqual(few.exception.field, "X")
        flat = pd.DataFrame({"X": x, "Y": np.full(x.shape, 4.0)})
        with self.assertRaises(FieldError) as constant:
            calibration_choice_error(flat, "X", "Y", "Nonlinear", model)
        self.assertEqual(constant.exception.field, "Y")
        calibration_choice_error(pd.DataFrame({"X": x, "Y": y}), "X", "Y", "Linear", model)
        calibration_choice_error(pd.DataFrame({"X": x, "Y": y}), "X", "Y", "Nonlinear", "One-phase decay")

    def test_a_saturated_step_does_not_invent_a_concentration(self):
        x = np.array([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y = np.where(x < 4.0, 2.0, 18.0)
        unknown = np.full(x.shape, np.nan)
        unknown[0] = 10.0
        frame = pd.DataFrame({"X": x, "Y": y, "Unknown": unknown})
        with self.assertRaisesRegex(FieldError, "between the two plateaus") as caught:
            interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "Stimulation (variable slope)")
        self.assertEqual(caught.exception.field, "Y")

    def test_a_numerically_flat_curve_has_no_imputed_concentration(self):
        # The asymptotes are not separable, so the fit is refused. No table, and no zero.
        x = np.array([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
        y = 5.0 + 1e-10 * x
        unknown = np.array([5.0, np.nan, 5.0, np.nan, np.nan, np.nan, np.nan, 4.0])
        with self.assertRaisesRegex(ValueError, "could not estimate the regression reliably"):
            interpolate_standard_curve(pd.DataFrame({"X": x, "Y": y, "Unknown": unknown}), "X", "Y", "Unknown",
                                       "Nonlinear", "Stimulation (variable slope)")

    def test_catalog_ids_are_the_recipe_names(self):
        self.assertEqual(CONCENTRATION_4PL, ("Stimulation (variable slope)", "Inhibition (variable slope)"))
        self.assertEqual(LOG10_4PL, ("Stimulation (variable slope, log10 X)", "Inhibition (variable slope, log10 X)"))
        for name in (*CONCENTRATION_4PL, *LOG10_4PL):
            self.assertIn(name, MODELS)
            self.assertEqual(len(MODELS[name].parameters), 4)


if __name__ == "__main__":
    unittest.main()
