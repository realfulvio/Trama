import unittest

import numpy as np
import pandas as pd

from analisi import regression_range as rr
from analisi.field_error import FieldError
from analisi.fit_weights import INVERSE_VARIANCE
from analisi.workbench import analyse


class RegressionRangeTests(unittest.TestCase):
    def test_linear_fit_uses_only_inclusive_bounds_and_keeps_source_rows(self):
        frame = pd.DataFrame({"X": [0., 1., 2., 3., 4., 5.], "Y": [12., 3., 4., 6., 9., -20.]},
                             index=[10, 4, 4, 16, 20, 2])
        options = {"X": "X", "Y": "Y", "Residual diagnostics": True, "Band": "Confidence (mean)"}
        subset = frame.iloc[1:5]
        reference = analyse("Linear regression", subset, options)
        fitted = analyse("Linear regression", frame, {
            **options, rr.FIT_MIN: 1, rr.FIT_MAX: 4, rr.CURVE_MIN: -2, rr.CURVE_MAX: 6, rr.CURVE_POINTS: 9,
        })
        pd.testing.assert_frame_equal(fitted.tables["Regression"].loc[reference.tables["Regression"].index],
                                      reference.tables["Regression"])
        pd.testing.assert_frame_equal(fitted.tables["Residuals"], reference.tables["Residuals"])
        curve = fitted.tables[rr.CURVE_SHEET]
        np.testing.assert_array_equal(curve["X"], np.arange(-2, 7))
        self.assertEqual(curve["Extrapolated"].tolist(), [True, True, True, False, False, False, False, True, True])
        np.testing.assert_array_equal(fitted.figure.axes[0].lines[0].get_ydata(), curve["Predicted"])
        np.testing.assert_array_equal(fitted.tables["Pointwise confidence band"]["X"], curve["X"])
        self.assertEqual(frame.index.tolist(), [10, 4, 4, 16, 20, 2])

    def test_extra_observations_only_change_the_scatter(self):
        frame = pd.DataFrame({"X": range(6), "Y": [12, 3, 5, 6, 9, "bad value"]})
        options = {"X": "X", "Y": "Y", rr.FIT_MIN: 1, rr.FIT_MAX: 4, "Residual diagnostics": True}
        baseline = analyse("Linear regression", frame, options)
        plotted = analyse("Linear regression", frame, {**options, rr.SHOW_OUTSIDE: True})
        for sheet in ("Regression", "Residuals"):
            pd.testing.assert_frame_equal(plotted.tables[sheet], baseline.tables[sheet])
        np.testing.assert_array_equal(plotted.figure.axes[0].collections[0].get_offsets(),
                                      [[0, 12], [1, 3], [2, 5], [3, 6], [4, 9]])
        np.testing.assert_array_equal(plotted.figure.axes[0].lines[0].get_xydata(),
                                      baseline.figure.axes[0].lines[0].get_xydata())

    def test_weighted_nonlinear_fit_uses_the_same_range_for_diagnostics_and_curves(self):
        x = np.arange(10.)
        y = 2. + 5. * np.exp(-x / 3.) + np.array([3, .1, -.02, .08, .02, -.03, .04, -.04, .02, -4])
        sd = np.r_[0., np.ones(8), -1.]
        frame = pd.DataFrame({"X": x, "Y": y, "SD": sd})
        options = {"X": "X", "Y columns": ["Y"], "Model": "One-phase decay",
                   "Weighting": INVERSE_VARIANCE, "SD column": "SD"}
        reference = analyse("Nonlinear regression", frame.iloc[1:9], options)
        fitted = analyse("Nonlinear regression", frame, {
            **options, rr.FIT_MIN: 1, rr.FIT_MAX: 8, rr.CURVE_MIN: 0, rr.CURVE_MAX: 9, rr.CURVE_POINTS: 5,
        })
        for sheet in ("Parameters: All", "Residuals: All"):
            pd.testing.assert_frame_equal(fitted.tables[sheet], reference.tables[sheet])
        curve = fitted.tables[f"{rr.CURVE_SHEET}: All"]
        np.testing.assert_array_equal(curve["X"], [0., 2.25, 4.5, 6.75, 9.])
        self.assertEqual(curve["Extrapolated"].tolist(), [True, False, False, False, True])
        np.testing.assert_array_equal(fitted.figure.axes[0].lines[0].get_ydata(), curve["Predicted"])

    def test_sample_count_only_resamples_and_blank_ranges_preserve_the_recipe(self):
        data = pd.DataFrame({"X": np.arange(12.),
                             "Y": 2 + 5 * np.exp(-np.arange(12.) / 3) + .03 * np.sin(np.arange(12.))})
        options = {"X": "X", "Y columns": ["Y"], "Model": "One-phase decay", "Band": "Confidence (mean)"}
        prior = analyse("Nonlinear regression", data, options)
        blank = {**options, **dict.fromkeys(rr.FIELDS, "")}
        self.assertEqual(rr.normalize(blank), {})
        self.assertEqual(blank, options)
        newer = analyse("Nonlinear regression", data, {**blank, rr.CURVE_POINTS: 20})
        pd.testing.assert_frame_equal(newer.tables["Parameters: All"], prior.tables["Parameters: All"])
        self.assertEqual(len(newer.tables["Band: All"]), 20)
        self.assertEqual(newer.tables["Band: All"]["X"].tolist(),
                         newer.tables[f"{rr.CURVE_SHEET}: All"]["X"].tolist())

    def test_nonlinear_multiresponse_plot_uses_extra_observations_per_group_only(self):
        x = np.arange(10.)
        y = 2. + 5. * np.exp(-x / 3.) + .03 * np.sin(x)
        frame = pd.DataFrame({
            "X": np.tile(x, 2), "Y": np.r_[y, y + 3], "Z": np.r_[2 * y, 3 * y],
            "Condition": ["A"] * 10 + ["B"] * 10, "Batch": ["One"] * 20,
        })
        frame = frame.astype({"Z": object})
        frame.iat[0, 2] = "invalid outside fit"
        options = {"X": "X", "Y columns": ["Y", "Z"], "Grouping variables": ["Condition", "Batch"],
                   "Model": "One-phase decay", rr.FIT_MIN: 1., rr.FIT_MAX: 8., "Residuals versus X": True}
        fitted = analyse("Nonlinear regression", frame, options)
        plotted = analyse("Nonlinear regression", frame, {**options, rr.SHOW_OUTSIDE: True})
        for sheet in ("Parameters", "Residuals"):
            pd.testing.assert_frame_equal(fitted.tables[sheet], plotted.tables[sheet])
        plot_y, residual_y, plot_z, residual_z = plotted.figure.axes
        self.assertEqual([len(series.get_offsets()) for series in plot_y.collections], [10, 10])
        self.assertEqual([len(series.get_offsets()) for series in plot_z.collections], [9, 10])
        for panel in (residual_y, residual_z):
            self.assertEqual([len(series.get_offsets()) for series in panel.collections], [8, 8])

    def test_bad_values_identify_the_field_and_numbers_are_canonical(self):
        for option, field in (({rr.FIT_MIN: float("inf")}, rr.FIT_MIN),
                              ({rr.CURVE_POINTS: "2.5"}, rr.CURVE_POINTS),
                              ({rr.CURVE_POINTS: "two"}, rr.CURVE_POINTS),
                              ({rr.FIT_MIN: 4, rr.FIT_MAX: 1}, rr.FIT_MAX),
                              ({rr.CURVE_MIN: 4, rr.CURVE_MAX: 4}, rr.CURVE_MAX)):
            with self.subTest(option=option), self.assertRaises(FieldError) as error:
                rr.ranges(option)
            self.assertEqual(error.exception.field, field)
        options = {rr.FIT_MIN: " 0,25 ", rr.FIT_MAX: "", rr.CURVE_POINTS: "12"}
        self.assertEqual(rr.normalize(options), {rr.FIT_MIN: .25, rr.CURVE_POINTS: 12})
        self.assertEqual(options, {rr.FIT_MIN: .25, rr.CURVE_POINTS: 12})
        with self.assertRaises(FieldError) as error:
            rr.fitting_rows(pd.DataFrame({"X": [0, 1]}), "X", {rr.FIT_MIN: 2})
        self.assertEqual(error.exception.field, rr.FIT_MIN)
