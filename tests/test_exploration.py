import unittest

import numpy as np
import pandas as pd

from analisi.exploration import LOG_RATIO, area_under_curve, bland_altman, deming, pca, roc
from analisi.processing import FieldError
from analisi.models import regression


class ExplorationTests(unittest.TestCase):
    def test_bland_altman_accepts_percentages_just_below_one_hundred(self):
        frame = pd.DataFrame({"A": [11., 14, 18, 22, 27], "B": [10., 15, 15, 22, 24]})
        level = np.nextafter(100., 0.)
        report, _ = bland_altman(frame, "A", "B", coverage=level, confidence=level, limit_intervals=True)
        self.assertTrue(all(np.isfinite(value) for value in report.values()))
        self.assertLess(report["Lower agreement limit"], report["Bias"])
        self.assertLess(report["Bias"], report["Upper agreement limit"])

    def test_log_ratio_does_not_compute_limit_intervals_when_disabled(self):
        frame = pd.DataFrame({"A": np.exp([-260., -260., 260., 260.]), "B": [1.] * 4})
        report, _ = bland_altman(frame, "A", "B", mode=LOG_RATIO)
        self.assertGreater(report["Lower agreement limit"], 0.)
        self.assertTrue(np.isfinite(report["Upper agreement limit"]))
        self.assertNotIn("Upper limit CI high", report)
        with self.assertRaisesRegex(ValueError, "finite positive"):
            bland_altman(frame, "A", "B", mode=LOG_RATIO, limit_intervals=True)

    def test_roc_counts_ties_as_half_and_keeps_unequal_samples(self):
        frame = pd.DataFrame({"Control": [0, 1, 1], "Patient": [1, 2, np.nan]})
        report, curve = roc(frame, "Control", "Patient", "Higher in patients")
        self.assertAlmostEqual(report["AUC"], 5 / 6)
        self.assertEqual(report["Control N"], 3)
        self.assertEqual(report["Patient N"], 2)
        self.assertEqual(curve.iloc[0]["False positive rate"], 0)
        self.assertEqual(curve.iloc[-1]["True positive rate"], 1)
        self.assertEqual(len(curve), 4)

    def test_bland_altman_pairs_and_agreement(self):
        frame = pd.DataFrame({"a": [3, 5, 7, None], "b": [2, 3, 4, 4]})
        report, points = bland_altman(frame, "a", "b")
        self.assertEqual(report["Bias"], 2)
        self.assertAlmostEqual(report["Lower agreement limit"], .04, places=4)
        self.assertAlmostEqual(report["Upper agreement limit"], 3.96, places=4)
        np.testing.assert_allclose(points["Mean"], [2.5, 4, 5.5])

    D1 = pd.DataFrame({"a": [11, 14, 18, 22, 27], "b": [10, 15, 15, 22, 24]})

    def test_agreement_limit_intervals_match_oracle(self):
        report, _ = bland_altman(self.D1, "a", "b", limit_intervals=True)
        expected = {"Bias": 1.2, "SD": 1.788854382, "Bias CI 95% low": -1.021156084, "Bias CI 95% high": 3.421156084,
                    "Lower agreement limit": -2.306090162, "Upper agreement limit": 4.706090162,
                    "Lower limit CI low": -6.402248729, "Lower limit CI high": 1.790068404,
                    "Upper limit CI low": 0.609931596, "Upper limit CI high": 8.802248729}
        for key, value in expected.items():
            self.assertAlmostEqual(report[key], value, places=8, msg=key)

    def test_distinct_coverage_and_confidence_move_different_quantities(self):
        base, _ = bland_altman(self.D1, "a", "b", limit_intervals=True)
        wide, _ = bland_altman(self.D1, "a", "b", coverage=99, confidence=95, limit_intervals=True)
        sure, _ = bland_altman(self.D1, "a", "b", coverage=95, confidence=99, limit_intervals=True)
        self.assertGreater(wide["Upper agreement limit"], base["Upper agreement limit"])
        self.assertEqual(wide["Bias CI 95% low"], base["Bias CI 95% low"])
        self.assertEqual(sure["Upper agreement limit"], base["Upper agreement limit"])
        self.assertLess(sure["Bias CI 99% low"], base["Bias CI 95% low"])
        self.assertLess(sure["Upper limit CI low"], base["Upper limit CI low"])
        self.assertEqual((sure["Agreement coverage (%)"], sure["Confidence level (%)"]), (95, 99))

    def test_ninety_percent_oracle_uses_neutral_labels(self):
        report, _ = bland_altman(self.D1, "a", "b", coverage=90, confidence=90)
        self.assertAlmostEqual(report["Lower agreement limit"], -1.742403618, places=8)
        self.assertAlmostEqual(report["Upper agreement limit"], 4.142403618, places=8)
        self.assertAlmostEqual(report["Bias CI 90% low"], -0.505477429, places=8)
        self.assertAlmostEqual(report["Bias CI 90% high"], 2.905477429, places=8)
        self.assertFalse([key for key in report if "95" in key])

    def test_legacy_report_keeps_names_and_order(self):
        report, points = bland_altman(self.D1, "a", "b")
        self.assertEqual(list(report), ["N", "Bias", "SD", "Bias CI 95% low", "Bias CI 95% high",
                                        "Lower agreement limit", "Upper agreement limit"])
        self.assertEqual(list(points.columns), ["Mean", "Difference"])

    def test_percentages_and_columns_are_validated_with_field_names(self):
        for field, value in (("Agreement coverage (%)", 0), ("Agreement coverage (%)", 100),
                             ("Confidence level (%)", float("nan")), ("Confidence level (%)", "x")):
            key = {"Agreement coverage (%)": "coverage", "Confidence level (%)": "confidence"}[field]
            with self.assertRaises(FieldError) as caught:
                bland_altman(self.D1, "a", "b", **{key: value})
            self.assertEqual(caught.exception.field, field)
        with self.assertRaises(FieldError) as caught:
            bland_altman(self.D1, "a", "a")
        self.assertEqual(caught.exception.field, "Second")

    def test_log_ratio_matches_oracle_and_inverts(self):
        frame = pd.DataFrame({"a": [1, 2, 8, 16, 5], "b": [2, 2, 4, 4, None]})
        report, points = bland_altman(frame, "a", "b", LOG_RATIO, limit_intervals=True)
        self.assertEqual(report["N"], 4)
        expected = {"Bias": 2 ** .5, "SD of log ratio": .8948491623, "Bias CI 95% low": .3405030776,
                    "Bias CI 95% high": 5.8736620351, "Lower agreement limit": .2448037183,
                    "Upper agreement limit": 8.1698105483, "Lower limit CI low": .0166676842,
                    "Lower limit CI high": 3.5955121222, "Upper limit CI low": .5562489937,
                    "Upper limit CI high": 119.9926744066}
        for key, value in expected.items():
            self.assertAlmostEqual(report[key] / value, 1, places=8, msg=key)
        self.assertAlmostEqual(report["Geometric SD (exp of SD of log ratio)"], np.exp(.8948491623), places=8)
        np.testing.assert_allclose(points[LOG_RATIO], [.5, 1, 2, 4])
        np.testing.assert_allclose(points["Mean"], np.sqrt([2, 4, 32, 64]))
        swapped, _ = bland_altman(frame, "b", "a", LOG_RATIO, limit_intervals=True)
        for low, high in (("Lower agreement limit", "Upper agreement limit"), ("Bias CI 95% low", "Bias CI 95% high"),
                          ("Lower limit CI low", "Upper limit CI high"), ("Lower limit CI high", "Upper limit CI low")):
            self.assertAlmostEqual(swapped[low] * report[high], 1, places=10)
        self.assertAlmostEqual(swapped["Bias"] * report["Bias"], 1, places=10)

    def test_log_ratio_rejects_nonpositive_complete_pair_with_column_and_row(self):
        frame = pd.DataFrame({"a": [1, 2, 0, 4, 5], "b": [2, 2, 4, None, 1]})
        with self.assertRaisesRegex(FieldError, r'"a".*row 3') as caught:
            bland_altman(frame, "a", "b", LOG_RATIO)
        self.assertEqual(caught.exception.field, "First")
        partial = pd.DataFrame({"a": [1, 2, 4, 0], "b": [2, 2, 4, None]})
        self.assertEqual(bland_altman(partial, "a", "b", LOG_RATIO)[0]["N"], 3)
        self.assertEqual(bland_altman(pd.DataFrame({"a": [1, 2, 3, 0.5], "b": [-1, 2, 3, 4]}).iloc[1:], "a", "b",
                                      LOG_RATIO)[0]["N"], 3)

    def test_constant_and_huge_inputs_are_stable(self):
        report, _ = bland_altman(pd.DataFrame({"a": [4., 4., 4.], "b": [2., 2., 2.]}), "a", "b", LOG_RATIO,
                                 limit_intervals=True)
        self.assertEqual((report["Bias"], report["Lower agreement limit"], report["Upper limit CI high"]), (2, 2, 2))
        huge = pd.DataFrame({"a": [1e308, 1.5e308, 1e307], "b": [1e307, 1e308, 1e306]})
        report, _ = bland_altman(huge, "a", "b", LOG_RATIO)
        self.assertTrue(np.isfinite(report["Bias"]))
        with self.assertRaisesRegex(ValueError, "not representable"):
            bland_altman(pd.DataFrame({"a": [1e300, 1e300, 1e300], "b": [1e-300, 1e-300, 1e-300]}), "a", "b", LOG_RATIO)

    def test_public_path_runs_old_recipe_without_new_keys(self):
        from analisi.additional import EXTRA_METHODS, extra_analysis

        result = extra_analysis("Bland–Altman", self.D1, {"First": "a", "Second": "b", "Method": "Difference"})
        self.assertEqual(list(result.tables), ["Agreement", "Paired values"])
        self.assertAlmostEqual(result.tables["Agreement"].loc["Bias CI 95% low"].iloc[0], -1.021156084, places=8)
        labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(labels, ["Bias", "Lower agreement limit", "Upper agreement limit"])
        options = EXTRA_METHODS["Bland–Altman"]
        self.assertEqual(list(options)[:3], ["First", "Second", "Method"])
        self.assertEqual((options["Agreement coverage (%)"], options["Confidence level (%)"],
                          options["Confidence intervals for agreement limits"], options["Show confidence bands"]),
                         (95.0, 95.0, False, False))

    def test_confidence_fields_follow_the_limit_intervals_switch(self):
        from analisi.additional import bland_altman_visibility

        self.assertEqual(set(bland_altman_visibility(False).values()), {False})
        self.assertEqual(bland_altman_visibility(True)["Confidence level (%)"], True)

    def test_public_path_log_ratio_axis_bias_and_two_bands(self):
        from analisi.additional import extra_analysis

        frame = pd.DataFrame({"a": [1, 2, 8, 16], "b": [2, 2, 4, 4]})
        options = {"First": "a", "Second": "b", "Method": LOG_RATIO, "Agreement coverage (%)": 95.,
                   "Confidence level (%)": 95., "Confidence intervals for agreement limits": True,
                   "Show confidence bands": True}
        result = extra_analysis("Bland–Altman", frame, options)
        axis = result.figure.axes[0]
        self.assertEqual(axis.get_yscale(), "log")
        self.assertEqual(axis.get_ylabel(), "First / Second")
        labels = [text.get_text() for text in result.figure.legends[0].get_texts()]
        for label in ("Bias", "Lower limit CI", "Upper limit CI", "Lower agreement limit", "Upper agreement limit"):
            self.assertIn(label, labels)
        self.assertEqual(len(axis.patches), 2)
        report = result.tables["Agreement"].iloc[:, 0]
        self.assertAlmostEqual(report["Bias"], 2 ** .5, places=10)
        options["Show confidence bands"] = False
        off = extra_analysis("Bland–Altman", frame, options).figure
        self.assertEqual(len(off.axes[0].patches), 0)
        self.assertIn("Bias", [text.get_text() for text in off.legends[0].get_texts()])

    def test_signed_auc_splits_segments_at_baseline(self):
        frame = pd.DataFrame({"x": [2, 0, 1], "y": [3, 1, 3]})
        report, points = area_under_curve(frame, "x", "y", baseline=2)
        self.assertEqual(report["Net area"], 1)
        self.assertEqual(report["Area above baseline"], 1.25)
        self.assertEqual(report["Area below baseline"], .25)
        self.assertEqual(list(points["x"]), [0, 1, 2])

    def test_deming_matches_exact_affine_data(self):
        frame = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [7, 5, 3, 1, -1]})
        report, _ = deming(frame, "x", "y", 2.)
        self.assertAlmostEqual(report["Slope"], -2)
        self.assertAlmostEqual(report["Intercept"], 9)

    def test_pca_preserves_input_scale_choice(self):
        frame = pd.DataFrame({"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]})
        parts, loadings, scores = pca(frame, ["a", "b"], True)
        np.testing.assert_allclose(parts["Variance (%)"], [100, 0], atol=1e-12)
        np.testing.assert_allclose(loadings["PC1"], [np.sqrt(.5)] * 2)
        np.testing.assert_allclose(scores["PC2"], 0, atol=1e-12)

    def test_multiple_regression_recovers_continuous_and_categorical_effects(self):
        frame = pd.DataFrame({"x": [1, 2, 3, 4] * 2, "type": ["a"] * 4 + ["b"] * 4})
        noise = np.tile([.2, -.2, -.2, .2], 2)
        frame["y"] = 2 + 3 * frame["x"] + 4 * (frame["type"] == "b") + noise
        tables = regression(frame, "y", ["x", "type"], ["type"], "Linear")
        coeff = tables["Coefficients"]["Estimate"]
        np.testing.assert_allclose(coeff.loc[["Intercept", "x", "type [b]"]], [2, 3, 4])

    def test_logistic_rejects_perfect_separation(self):
        frame = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6], "y": [0, 0, 0, 1, 1, 1]})
        with self.assertRaisesRegex(ValueError, "separat|converg|estim"):
            regression(frame, "y", ["x"], [], "Logistic")
