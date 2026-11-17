"""Independent acceptance checks for optional linear regression point intervals."""
import importlib
import unittest

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from analisi.processing import FieldError
from analisi.workbench import analyse


SHEET = "Linear estimates"
FORWARD = "Y confidence interval at X"
INVERSE = "X confidence interval at Y"
X_VALUE, Y_VALUE = "X value", "Y value"
LEVEL = "Confidence level (%)"
DATA = pd.DataFrame({"X": [0., 1., 2., 3., 4.], "Y": [1., 3., 2., 5., 7.]})


def run(frame=DATA, **options):
    return analyse("Linear regression", frame, {"X": "X", "Y": "Y", **options})


class LinearPointEstimatesTests(unittest.TestCase):
    def estimates(self, frame=DATA, **options):
        result = run(frame, **options)
        self.assertIn(SHEET, result.tables, "the requested optional confidence intervals are missing")
        return result.tables[SHEET]

    def test_forward_mean_interval_agrees_with_independent_ols(self):
        table = self.estimates(**{FORWARD: True, X_VALUE: 2.})
        oracle = sm.OLS(DATA.Y, sm.add_constant(DATA.X)).fit().get_prediction([[1., 2.]]).summary_frame()
        self.assertEqual(table.Direction.tolist(), ["Y from X"])
        np.testing.assert_allclose(table[["Estimate", "Lower", "Upper"]].iloc[0],
                                   oracle[["mean", "mean_ci_lower", "mean_ci_upper"]].iloc[0], rtol=1e-12)
        self.assertEqual(table["Confidence set"].iloc[0], "Bounded")
        # At this distance only the fitted slope and its uncertainty contribute
        # at float64 precision. X/Sx itself exceeds the Windows numeric range.
        extreme = DATA.assign(X=DATA.X*1e-150, Y=DATA.Y*1e-100)
        row = self.estimates(extreme, **{FORWARD: True, X_VALUE: 1e170}).iloc[0]
        half = stats.t.isf(.025, 3)*np.sqrt(.12)*1e220
        np.testing.assert_allclose([row.Estimate, row.Lower, row.Upper],
                                   [1.4e220, 1.4e220-half, 1.4e220+half], rtol=3e-12)

    def test_inverse_x_intercept_is_asymmetric_and_matches_band_boundary(self):
        table = self.estimates(**{INVERSE: True, Y_VALUE: 0.})
        self.assertEqual(len(table), 1)
        row = table.iloc[0]
        self.assertAlmostEqual(row.Estimate, -4/7)
        self.assertEqual(row["Confidence set"], "Bounded")
        self.assertGreater(row.Estimate - row.Lower, row.Upper - row.Estimate)
        fit = sm.OLS(DATA.Y, sm.add_constant(DATA.X)).fit()
        for x in [row.Lower, row.Upper]:
            predicted = fit.get_prediction([[1., x]]).summary_frame().iloc[0]
            self.assertAlmostEqual(min(abs(predicted.mean_ci_lower), abs(predicted.mean_ci_upper)), 0., places=10)

    def test_inverse_query_recovers_the_best_fit_crossing(self):
        table = self.estimates(**{INVERSE: True, Y_VALUE: 3.6})
        self.assertAlmostEqual(table.Estimate.iloc[0], 2.)
        self.assertLess(table.Lower.iloc[0], 2.)
        self.assertGreater(table.Upper.iloc[0], 2.)

    def test_both_directions_use_one_fit_and_one_optional_sheet(self):
        result = run(**{FORWARD: True, INVERSE: True, X_VALUE: 2., Y_VALUE: 0.})
        self.assertIn(SHEET, result.tables)
        self.assertEqual(list(result.tables), ["Regression", SHEET])
        self.assertEqual(result.tables[SHEET].Direction.tolist(), ["Y from X", "X from Y"])

    def test_legacy_and_explicit_off_leave_all_results_and_artists_unchanged(self):
        legacy = run(Band="Confidence (mean)", **{"Residual diagnostics": True})
        disabled = run(Band="Confidence (mean)", **{"Residual diagnostics": True, FORWARD: False, INVERSE: False,
                                                     X_VALUE: float("nan"), Y_VALUE: float("inf")})
        self.assertEqual(list(legacy.tables), list(disabled.tables))
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], disabled.tables[name])
        np.testing.assert_array_equal(legacy.figure.axes[0].lines[0].get_xydata(),
                                      disabled.figure.axes[0].lines[0].get_xydata())

    def test_query_changes_do_not_refit_or_change_the_graph(self):
        first = run(**{INVERSE: True, Y_VALUE: 0.})
        second = run(**{INVERSE: True, Y_VALUE: 5.})
        self.assertIn(SHEET, first.tables)
        pd.testing.assert_frame_equal(first.tables["Regression"], second.tables["Regression"])
        np.testing.assert_array_equal(first.figure.axes[0].lines[0].get_xydata(),
                                      second.figure.axes[0].lines[0].get_xydata())

    def test_weak_slope_can_give_two_unbounded_components(self):
        frame = pd.DataFrame({"X": [-2., -1., 0., 1., 2.], "Y": [-1., 0., 2., 0., -1.]})
        table = self.estimates(frame, **{INVERSE: True, Y_VALUE: 5.})
        self.assertEqual(table["Confidence set"].tolist(), ["Two unbounded intervals"]*2)
        self.assertEqual(table.Component.tolist(), [1, 2])
        self.assertTrue(np.isneginf(table.Lower.iloc[0]))
        self.assertTrue(np.isposinf(table.Upper.iloc[1]))
        self.assertLess(table.Upper.iloc[0], table.Lower.iloc[1])
        self.assertTrue(table.Estimate.isna().all())

    def test_horizontal_fit_can_cover_all_real_values(self):
        frame = pd.DataFrame({"X": [-2., -1., 0., 1., 2.], "Y": [-1., 0., 2., 0., -1.]})
        row = self.estimates(frame, **{INVERSE: True, Y_VALUE: 0.}).iloc[0]
        self.assertEqual(row["Confidence set"], "All real values")
        self.assertTrue(np.isneginf(row.Lower) and np.isposinf(row.Upper))
        self.assertTrue(pd.isna(row.Estimate))
        self.assertIn("horizontal", row.Note.lower())

    def test_perfect_horizontal_fit_reports_empty_or_all_real_sets(self):
        frame = pd.DataFrame({"X": [0., 1., 2., 3.], "Y": [4.]*4})
        empty = self.estimates(frame, **{INVERSE: True, Y_VALUE: 0.}).iloc[0]
        self.assertEqual(empty["Confidence set"], "Empty")
        self.assertTrue(pd.isna(empty.Estimate) and pd.isna(empty.Lower) and pd.isna(empty.Upper))
        whole = self.estimates(frame, **{INVERSE: True, Y_VALUE: 4.}).iloc[0]
        self.assertEqual(whole["Confidence set"], "All real values")

    def test_perfect_line_has_a_singleton_confidence_interval(self):
        frame = pd.DataFrame({"X": [0., 1., 2., 3.], "Y": [2., 4., 6., 8.]})
        row = self.estimates(frame, **{INVERSE: True, Y_VALUE: 0.}).iloc[0]
        np.testing.assert_allclose([row.Estimate, row.Lower, row.Upper], [-1., -1., -1.])

    def test_negative_slope_and_response_rescaling(self):
        baseline = self.estimates(**{INVERSE: True, Y_VALUE: 0.})
        for factor in [-1., 1e-12, 1e12, 1e-200, 1e150]:
            frame = DATA.assign(Y=DATA.Y * factor)
            got = self.estimates(frame, **{INVERSE: True, Y_VALUE: 0.})
            np.testing.assert_allclose(got[["Estimate", "Lower", "Upper"]],
                                       baseline[["Estimate", "Lower", "Upper"]], rtol=2e-12)

    def test_x_units_and_large_translation(self):
        baseline = self.estimates(**{INVERSE: True, Y_VALUE: 0.})
        for factor, shift in [(1e-9, 0.), (1., 1e9)]:
            got = self.estimates(DATA.assign(X=DATA.X*factor+shift), **{INVERSE: True, Y_VALUE: 0.})
            np.testing.assert_allclose(got[["Estimate", "Lower", "Upper"]],
                                       baseline[["Estimate", "Lower", "Upper"]]*factor+shift,
                                       rtol=1e-14, atol=1e-15 if not shift else 2e-6)

    def test_far_inverse_query_preserves_the_interval_topology(self):
        # Mean/intercept shifts are below one ulp of this extrapolation. The
        # limits therefore equal Y divided by the two slope confidence limits.
        row = self.estimates(DATA.assign(Y=DATA.Y*1e-200), **{INVERSE: True, Y_VALUE: 1e100}).iloc[0]
        t = stats.t.isf(.025, 3)
        self.assertEqual(row["Confidence set"], "Bounded")
        np.testing.assert_allclose([row.Estimate, row.Lower, row.Upper],
                                   [1e300/1.4, 1e300/(1.4+t*np.sqrt(.12)),
                                    1e300/(1.4-t*np.sqrt(.12))], rtol=3e-12)

    def test_extrapolation_is_explicit_and_not_clipped_to_observed_range(self):
        row = self.estimates(**{FORWARD: True, X_VALUE: 20.}).iloc[0]
        self.assertAlmostEqual(row.Estimate, 28.8)
        self.assertIn("extrapolat", row.Note.lower())

    def test_invalid_active_values_name_the_field(self):
        for flag, field in [(FORWARD, X_VALUE), (INVERSE, Y_VALUE)]:
            for value in [float("nan"), float("inf"), -float("inf"), "bad"]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(FieldError) as caught:
                        run(**{flag: True, field: value})
                    self.assertEqual(caught.exception.field, field)
        for level in [0., 100., float("inf")]:
            with self.assertRaises(FieldError) as caught:
                run(**{FORWARD: True, LEVEL: level})
            self.assertEqual(caught.exception.field, LEVEL)

    def test_level_applies_to_estimates_without_a_graph_band(self):
        first = self.estimates(**{FORWARD: True, X_VALUE: 2., LEVEL: 90.}).iloc[0]
        second = self.estimates(**{FORWARD: True, X_VALUE: 2., LEVEL: 99.}).iloc[0]
        self.assertEqual(first[LEVEL], 90.)
        self.assertLess(first.Upper-first.Lower, second.Upper-second.Lower)

    def test_quadratic_boundary_keeps_half_lines_and_tiny_nonzero_coefficients(self):
        spec = importlib.util.find_spec("analisi.linear_estimates")
        self.assertIsNotNone(spec, "the independent real-line confidence-set solver is missing")
        solve = importlib.import_module("analisi.linear_estimates").quadratic_confidence_set
        pieces, kind = solve(0., 2., -4.)
        self.assertEqual(kind, "Half-line")
        self.assertEqual(pieces, [(-np.inf, 2.)])
        pieces, kind = solve(1e-30, 0., -1.)
        self.assertEqual(kind, "Bounded")
        np.testing.assert_allclose(pieces, [(-1e15, 1e15)])
        pieces, kind = solve(-1., 2., -1.)
        self.assertEqual(kind, "All real values")
