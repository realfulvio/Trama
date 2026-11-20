import unittest

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analisi.advanced import anova_comparisons, kmeans_scan
from analisi.stats import kmeans, marginal_comparisons


class ClusterScanTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"x": [0., 1., 10., 11., np.nan]})

    def test_metrics_match_hand_computed_partition(self):
        scan = kmeans_scan(self.frame, ["x"], max_k=4)
        result = scan.metrics.loc[2]
        self.assertAlmostEqual(result["WSS"], 1.)
        self.assertAlmostEqual(result["Silhouette"], 1 - (1 / 10.5 + 1 / 9.5) / 2)
        self.assertAlmostEqual(result["Calinski–Harabasz"], 200.)
        self.assertAlmostEqual(result["Davies–Bouldin"], .1)
        self.assertEqual(scan.recommended_k, 2)
        pd.testing.assert_series_equal(scan.fit.labels, kmeans(self.frame, ["x"], 2).labels)
        self.assertTrue(np.isnan(scan.metrics.loc[1, "Silhouette"]))
        self.assertTrue(np.isnan(scan.metrics.loc[4, "Silhouette"]))

    def test_elbow_uses_scaled_wss_and_reuses_seed(self):
        frame = pd.DataFrame(
            [(x + offset, y) for x, y in [(0., 0.), (20., 0.), (10., 17.32)]
             for offset in (-1, 0, 1)], columns=["x", "y"])
        scan = kmeans_scan(frame, ["x", "y"], max_k=5, standardize=True, seed=7, criterion="elbow")
        same = kmeans_scan(frame, ["x", "y"], max_k=5, standardize=True, seed=7, criterion="elbow")
        self.assertEqual(scan.recommended_k, 3)
        self.assertAlmostEqual(scan.metrics.loc[1, "WSS"], 16.)
        pd.testing.assert_frame_equal(scan.metrics, same.metrics)
        pd.testing.assert_series_equal(scan.fit.labels, same.fit.labels)

    def test_singleton_silhouette_and_identical_observations(self):
        scan = kmeans_scan(pd.DataFrame({"x": [0., 1., 10.]}), ["x"], max_k=2)
        self.assertAlmostEqual(scan.metrics.loc[2, "Silhouette"], (0.9 + 8/9) / 3)
        same = kmeans_scan(pd.DataFrame({"x": [1.] * 3}), ["x"])
        self.assertEqual(same.metrics.index.tolist(), [1])
        self.assertEqual(same.metrics.loc[1, "WSS"], 0)
        self.assertIsNone(same.recommended_k)
        self.assertIsNone(same.fit)

    def test_scan_can_start_above_one(self):
        scan = kmeans_scan(self.frame, ["x"], max_k=8, min_k=2)
        self.assertEqual(scan.metrics.index.tolist(), [2, 3, 4])
        self.assertEqual(scan.recommended_k, 2)
        for min_k in [0, 5, 2.5]:
            with self.assertRaises(ValueError):
                kmeans_scan(self.frame, ["x"], max_k=4, min_k=min_k)
        with self.assertRaisesRegex(ValueError, "distinct"):
            kmeans_scan(self.frame, ["x"], max_k=8, min_k=5)

    def test_gap_uses_seeded_uniform_references_and_one_se_choice(self):
        frame = pd.DataFrame({"x": [0., .1, .2, .3, .4, 10., 10.1, 10.2, 10.3, 10.4]})
        options = {"max_k": 4, "seed": 17, "criterion": "gap", "gap_replicates": 8}
        scan = kmeans_scan(frame, ["x"], **options)
        samples = np.random.default_rng(17).uniform(0, 10.4, (8, 10))
        log_wss = np.log(((samples - samples.mean(axis=1, keepdims=True))**2).sum(axis=1))
        self.assertAlmostEqual(scan.metrics.loc[1, "Gap"],
                               log_wss.mean() - np.log(scan.metrics.loc[1, "WSS"]))
        self.assertAlmostEqual(scan.metrics.loc[1, "Gap SE"],
                               log_wss.std() * np.sqrt(1 + 1/8))
        self.assertEqual(scan.recommended_k, 2)
        self.assertLess(scan.metrics.loc[1, "Gap"],
                        scan.metrics.loc[2, "Gap"] - scan.metrics.loc[2, "Gap SE"])
        self.assertGreaterEqual(scan.metrics.loc[2, "Gap"],
                                scan.metrics.loc[3, "Gap"] - scan.metrics.loc[3, "Gap SE"])
        pd.testing.assert_frame_equal(scan.metrics, kmeans_scan(frame, ["x"], **options).metrics)
        self.assertNotIn("Gap", kmeans_scan(frame, ["x"], max_k=4).metrics)

    def test_gap_rejects_excess_reference_work_and_skips_zero_dispersion(self):
        from analisi.advanced import _check_scan_budget, gap_replicate_limit

        counts = range(1, 9)
        limit = gap_replicate_limit(178, 13, counts)
        self.assertEqual(limit, 36)
        _check_scan_budget(178, 13, counts, True, simulate_gap=True, gap_replicates=limit)
        with self.assertRaisesRegex(ValueError, "budget"):
            _check_scan_budget(178, 13, counts, True, simulate_gap=True, gap_replicates=limit + 1)
        with self.assertRaisesRegex(ValueError, "reference"):
            kmeans_scan(self.frame, ["x"], criterion="gap", gap_replicates=101)
        with self.assertRaisesRegex(ValueError, "budget"):
            kmeans_scan(pd.DataFrame({"x": np.arange(3000)}), ["x"], 20,
                        criterion="gap", gap_replicates=20)
        scan = kmeans_scan(self.frame, ["x"], max_k=4, criterion="gap", gap_replicates=5)
        self.assertTrue(scan.metrics.loc[4, ["Gap", "Gap SE"]].isna().all())
        constant = kmeans_scan(pd.DataFrame({"x": [1., 1., 1.]}), ["x"], criterion="gap")
        self.assertIsNone(constant.recommended_k)
        self.assertTrue(constant.metrics["Gap"].isna().all())

    def test_gap_reference_along_principal_axes(self):
        from analisi.kmeans_options import GAP_PRINCIPAL_AXES, GAP_VARIABLE_RANGES

        # A translated, rotated rectangle with distinct principal axes and
        # exact known side lengths in the input scale.
        rectangle = np.array([[-5., -1.], [-5., 1.], [5., -1.], [5., 1.]])
        rotation = np.array([[.6, -.8], [.8, .6]])
        frame = pd.DataFrame(rectangle @ rotation + [12., -7.], columns=["x", "y"])
        options = dict(max_k=1, criterion="gap", gap_replicates=8, seed=17)
        canonical = kmeans_scan(frame, list(frame), **options)
        variables = kmeans_scan(frame, list(frame), gap_reference=GAP_VARIABLE_RANGES, **options)
        pd.testing.assert_frame_equal(canonical.metrics, variables.metrics, check_exact=True)
        principal = kmeans_scan(frame, list(frame), gap_reference=GAP_PRINCIPAL_AXES, **options)
        references = np.random.default_rng(17).uniform([-5., -1.], [5., 1.], (8, 4, 2))
        log_wss = np.log(((references - references.mean(axis=1, keepdims=True)) ** 2).sum(axis=(1, 2)))
        self.assertAlmostEqual(principal.metrics.loc[1, "WSS"], 104.)
        self.assertAlmostEqual(principal.metrics.loc[1, "Gap"], log_wss.mean() - np.log(104.))
        self.assertAlmostEqual(principal.metrics.loc[1, "Gap SE"], log_wss.std() * np.sqrt(1 + 1 / 8))
        self.assertNotAlmostEqual(principal.metrics.loc[1, "Gap"], variables.metrics.loc[1, "Gap"])

    def test_criteria_and_scan_limits(self):
        frame = self.frame
        for criterion in ["calinski-harabasz", "davies-bouldin"]:
            self.assertEqual(kmeans_scan(frame, ["x"], max_k=2, criterion=criterion).recommended_k, 2)
        self.assertIsNone(kmeans_scan(frame, ["x"], max_k=2, criterion="elbow").recommended_k)
        for max_k in [0, 2.5, 31]:
            with self.assertRaises(ValueError):
                kmeans_scan(frame, ["x"], max_k=max_k)
        with self.assertRaisesRegex(ValueError, "budget"):
            kmeans_scan(pd.DataFrame({"x": np.arange(3001)}), ["x"])


class AnovaComparisonTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            [(a, b, c, 2*a + 3*b + c + 4*a*b + 2*a*c + err)
             for a in (0, 1) for b in (0, 1) for c in (0, 1) for err in (-1, 0, 1)],
            columns=["A", "B", "C", "Y"],
        )
        self.factors = ["A", "B", "C"]

    def posthoc(self, compare, **kwargs):
        return anova_comparisons(self.frame, "Y", self.factors, 3, compare, **kwargs)

    def test_main_effect_agrees_with_existing_balanced_grid(self):
        result = self.posthoc("A")
        old = marginal_comparisons(self.frame, "Y", self.factors, 3, "A")
        self.assertAlmostEqual(result.loc["0 − 1", "Difference"], -5.)
        for column in ["Difference", "SE", "df", "t", "p", "Adjusted p"]:
            np.testing.assert_allclose(result[column], old[column], rtol=1e-13)

    def test_simple_effects_adjust_over_requested_families(self):
        separate = self.posthoc("A", within=["B"], method="bonferroni")
        pooled = self.posthoc("A", within=["B"], method="bonferroni", family="pooled")
        self.assertEqual(separate["Family"].tolist(), ["B=0", "B=1"])
        self.assertEqual(pooled["Family"].tolist(), ["All", "All"])
        np.testing.assert_allclose(separate["Difference"], [-3, -7])
        np.testing.assert_allclose(separate["SE"], np.sqrt(1/3))
        np.testing.assert_allclose(separate["Adjusted p"], separate["p"])
        np.testing.assert_allclose(pooled["Adjusted p"], pooled["p"] * 2)
        expected = stats.t.isf(.05 / 4, 16) * np.sqrt(1/3)
        np.testing.assert_allclose(pooled["CI high"] - pooled["Difference"], expected)
        self.assertTrue(self.posthoc("A", within=["B", "C"], method="holm-sidak")["CI low"].isna().all())

    def test_cell_comparisons_with_control_and_equal_cell_weights(self):
        control = self.posthoc(("A", "B"), control=(0, 0), method="sidak")
        self.assertEqual(len(control), 3)
        np.testing.assert_allclose(control["Difference"], [3., 3., 10.])
        np.testing.assert_allclose(control["Adjusted p"],
                                   multipletests(control["p"], method="sidak")[1])
        self.assertTrue((control["CI high"] > control["Difference"]).all())
        self.assertEqual(len(self.posthoc(("A", "B"))), 6)
        self.assertEqual(len(self.posthoc(("A", "B", "C"))), 28)

    def test_unbalanced_design_uses_equal_weights_and_model_contrast_se(self):
        cell = self.frame.query("A == 0 and B == 0 and C == 0")
        extra = pd.concat([self.frame, cell, cell])
        result = anova_comparisons(extra, "Y", self.factors, 3, "A", method="none")
        # All four cells per A contribute weight 1/4, even the one with 9 observations.
        self.assertAlmostEqual(result.iloc[0]["Difference"], -5.)
        self.assertAlmostEqual(result.iloc[0]["SE"], np.sqrt((20/22) * (7/3 + 1/9)/16))

    def test_tukey_and_dunnett_match_reference_for_one_way(self):
        groups = [[1., 2., 3., 4.], [2., 3., 4.], [4., 6., 8., 9., 10.]]
        frame = pd.DataFrame([(i, value) for i, group in enumerate(groups) for value in group],
                             columns=["A", "Y"])
        tukey = anova_comparisons(frame, "Y", ["A"], 1, "A", method="tukey")
        ci = stats.tukey_hsd(*groups).confidence_interval()
        np.testing.assert_allclose(tukey["Adjusted p"], stats.tukey_hsd(*groups).pvalue[np.triu_indices(3, 1)])
        np.testing.assert_allclose(tukey["CI low"], ci.low[np.triu_indices(3, 1)])
        dunnett = anova_comparisons(frame, "Y", ["A"], 1, "A", method="dunnett", control=0)
        reference = stats.dunnett(*groups[1:], control=groups[0], rng=42)
        np.testing.assert_allclose(dunnett["Adjusted p"], reference.pvalue, atol=5e-4)
        np.testing.assert_allclose(dunnett["CI high"], reference.confidence_interval().high, atol=.02)

    def test_tukey_tail_stays_within_family_probability_bounds(self):
        frame = pd.DataFrame([(a, 100 * a + err) for a in range(3) for err in (-1, 0, 1, -1, 1)],
                             columns=["A", "Y"])
        result = anova_comparisons(frame, "Y", ["A"], 1, "A", method="tukey")
        self.assertTrue((result["Adjusted p"] >= result["p"]).all())
        self.assertTrue((result["Adjusted p"] <= 3 * result["p"]).all())

    def test_validation(self):
        for kwargs in [
            {"within": ["A"]}, {"within": ["unknown"]}, {"control": 6},
            {"method": "unknown"}, {"confidence": 1}, {"family": "unknown"},
            {"method": "tukey", "control": 0}, {"method": "dunnett"},
            {"method": "tukey", "within": ["B"], "family": "pooled"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.posthoc("A", **kwargs)
        with self.assertRaises(ValueError):
            self.posthoc(("A", "B"), control=0)


if __name__ == "__main__":
    unittest.main()
