"""Consensus of 17 internal indices for k-means model selection."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced
from analisi import cluster_consensus as cc
from analisi.advanced import _cluster_scores, kmeans_scan
from analisi.data import Dataset, load_project, save_project
from analisi.stats import Clusters
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data"
WINE_LABELS = (
    "1111111111111111111111111111111111111111111111111111111111133233333333333133333333323333333333313333333333"
    "333333333333233133333333222222222222222222222222222222222222222222222222")
NAN_FREE_INDICES = (cc.C_INDEX, cc.CALINSKI, cc.DAVIES_RMS, cc.DUNN, cc.GAMMA, cc.GPLUS, cc.MCCLAIN_RAO,
                    cc.POINT_BISERIAL, cc.RATKOWSKY, cc.SILHOUETTE, cc.TAU)


def measures(values, labels):
    return cc.partition_indices(np.asarray(values, dtype=float).reshape(len(labels), -1), labels)


def brute_concordance(within, between):
    concordant = sum(w < b for w in within for b in between)
    discordant = sum(w > b for w in within for b in between)
    return concordant, discordant


class PartitionIndexTests(unittest.TestCase):
    def test_hand_computed_partition(self):
        result = measures([0., 1., 4., 5.], [1, 1, 2, 2])
        expected = {
            "WSS": 1, "BSS": 16, "TSS": 17, cc.BALL_HALL: .5, cc.C_INDEX: 0, cc.CALINSKI: 32,
            cc.DAVIES_RMS: .25, cc.DUNN: 3, cc.GAMMA: 1, cc.GPLUS: 0, cc.TAU: 8 / 15, cc.MCCLAIN_RAO: .25,
            cc.POINT_BISERIAL: 3 / np.sqrt(14 / 5) * np.sqrt(8) / 6, cc.RATKOWSKY: np.sqrt(8 / 17),
            cc.SILHOUETTE: 0.746031746031746, cc.MEAN_WITHIN: 1, cc.MEAN_BETWEEN: 4,
        }
        for name, value in expected.items():
            with self.subTest(index=name):
                self.assertAlmostEqual(result[name], value, places=14)

    def test_ties_between_within_and_between_distances_are_ignored(self):
        # w = [1], b = [2, 1]: one concordant pair and one tie.
        result = measures([0., 1., 2.], [1, 1, 2])
        self.assertEqual(result[cc.GAMMA], 1)
        self.assertAlmostEqual(result[cc.TAU], 1 / 3)
        self.assertEqual(result[cc.GPLUS], 0)

    def test_coincident_centers_leave_davies_bouldin_empty(self):
        result = measures([0., 2., 1., 1.], [1, 1, 2, 2])
        self.assertTrue(np.isnan(result[cc.DAVIES_RMS]))
        self.assertEqual(result[cc.CALINSKI], 0)
        self.assertEqual(result["BSS"], 0)

    def test_singleton_silhouette_is_zero(self):
        result = measures([0., 1., 10.], [1, 1, 2])
        self.assertAlmostEqual(result[cc.SILHOUETTE], (.9 + 8 / 9) / 3)

    def test_all_distances_equal(self):
        result = measures(np.eye(4), [1, 1, 2, 2])
        for name in (cc.C_INDEX, cc.GAMMA, cc.POINT_BISERIAL):
            self.assertTrue(np.isnan(result[name]), name)
        self.assertEqual(result[cc.GPLUS], 0)
        self.assertEqual(result[cc.TAU], 0)
        self.assertAlmostEqual(result[cc.DUNN], 1)
        self.assertAlmostEqual(result[cc.MCCLAIN_RAO], 1)

    def test_duplicate_rows_have_no_within_spread(self):
        result = measures([0., 0., 5., 5.], [1, 1, 2, 2])
        self.assertEqual(result["WSS"], 0)
        self.assertTrue(np.isnan(result[cc.DUNN]))
        self.assertTrue(np.isnan(result[cc.CALINSKI]))
        self.assertEqual(result[cc.C_INDEX], 0)
        self.assertEqual(result[cc.DAVIES_RMS], 0)

    def test_one_cluster_and_one_cluster_per_observation(self):
        single = measures([0., 1., 4., 5.], [1, 1, 1, 1])
        self.assertEqual(single[cc.BALL_HALL], 17)
        self.assertEqual(single[cc.RATKOWSKY], 0)
        for name in (cc.C_INDEX, cc.CALINSKI, cc.DAVIES_RMS, cc.DUNN, cc.GAMMA, cc.GPLUS, cc.TAU,
                     cc.MCCLAIN_RAO, cc.POINT_BISERIAL, cc.SILHOUETTE):
            self.assertTrue(np.isnan(single[name]), name)
        every = measures([0., 1., 4., 5.], [1, 2, 3, 4])
        self.assertEqual(every["WSS"], 0)
        self.assertEqual(every[cc.DAVIES_RMS], 0)
        self.assertAlmostEqual(every[cc.RATKOWSKY], .5)
        for name in (cc.C_INDEX, cc.CALINSKI, cc.DUNN, cc.GAMMA, cc.GPLUS, cc.TAU, cc.MCCLAIN_RAO,
                     cc.POINT_BISERIAL, cc.SILHOUETTE):
            self.assertTrue(np.isnan(every[name]), name)

    def test_ratkowsky_skips_constant_unscaled_variables(self):
        values = np.column_stack([[0., 1., 4., 5.], [7.] * 4])
        self.assertAlmostEqual(cc.partition_indices(values, [1, 1, 2, 2])[cc.RATKOWSKY], np.sqrt(8 / 17))
        constant = cc.partition_indices(np.full((3, 2), 7.), [1, 1, 2])
        self.assertTrue(np.isnan(constant[cc.RATKOWSKY]))
        scan = kmeans_scan(pd.DataFrame({"x": [0., 1., 4., 5.], "c": 7.}), ["x", "c"], max_k=2,
                           criterion="consensus", gap_replicates=5)
        self.assertAlmostEqual(scan.metrics.loc[2, cc.RATKOWSKY], np.sqrt(8 / 17))

    def test_missing_values_are_rejected_by_pure_measures(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            measures([0., np.nan, 4., 5.], [1, 1, 2, 2])
        with self.assertRaisesRegex(ValueError, "label"):
            cc.partition_indices(np.array([[0.], [1.], [4.], [5.]]), [1, 1, 2])

    def test_searchsorted_concordance_matches_brute_force(self):
        rng = np.random.default_rng(3)
        for trial in range(40):
            n = rng.integers(4, 12)
            values = rng.integers(0, 4, size=(n, 2)).astype(float)  # many ties
            labels = rng.integers(0, rng.integers(2, 4), size=n)
            pairs = cc.PairDistances(values)
            within, between = pairs.split(labels)
            with self.subTest(trial=trial):
                self.assertEqual(cc.concordance(within, between), brute_concordance(within, between))
                np.testing.assert_array_equal(np.sort(between), between)
                self.assertEqual(len(within) + len(between), n * (n - 1) // 2)

    def test_silhouette_matches_existing_metric(self):
        rng = np.random.default_rng(8)
        values = rng.normal(size=(25, 3))
        labels = np.r_[0, 1, 2, rng.integers(0, 3, size=22)]
        centers = np.vstack([values[labels == g].mean(axis=0) for g in range(3)])
        fit = Clusters(pd.DataFrame(values), pd.Series(labels + 1), pd.DataFrame(centers), 1.)
        square = cc.squareform(cc.pdist(values))
        existing = _cluster_scores(values, square, fit)[0]
        self.assertAlmostEqual(cc.partition_indices(values, labels)[cc.SILHOUETTE], existing, places=13)


class VoteTests(unittest.TestCase):
    def test_krzanowski_lai_scales_wss_by_dimension(self):
        wss = {1: 100., 2: 42., 3: 20., 4: 18.}
        table, _ = cc.consensus_table({}, wss, n=10, dimensions=2)
        # With p = 2, the scaled WSS is [100, 84, 60, 72].
        self.assertAlmostEqual(table.loc[2, cc.KRZANOWSKI_LAI], 16 / 24)
        self.assertAlmostEqual(table.loc[3, cc.KRZANOWSKI_LAI], 24 / 12)
        self.assertTrue(np.isnan(table.loc[4, cc.KRZANOWSKI_LAI]))

    def test_extremes_ties_and_missing_values(self):
        self.assertEqual(cc.vote_extreme(pd.Series({2: .5, 3: .5, 4: .1}), True)[0], 2)
        self.assertEqual(cc.vote_extreme(pd.Series({1: 9., 2: .5, 3: .7}), True)[0], 3)
        self.assertEqual(cc.vote_extreme(pd.Series({1: -9., 2: .5, 3: np.nan}), False)[0], 2)
        self.assertIsNone(cc.vote_extreme(pd.Series({1: 1., 2: np.nan}), True)[0])

    def test_ball_hall(self):
        self.assertEqual(cc.vote_ball_hall(pd.Series({2: 8., 3: 3., 4: 2.})), (3, ""))
        # k = 1 is a reference only, and 3 is missing so 2 has no right neighbour.
        self.assertEqual(cc.vote_ball_hall(pd.Series({1: 99., 2: 8., 4: 2., 5: 1.9}))[0], 5)
        self.assertIsNone(cc.vote_ball_hall(pd.Series({2: 8., 4: 2.}))[0])

    def test_hartigan(self):
        self.assertEqual(cc.vote_hartigan(pd.Series({2: 52., 3: 14., 4: 10.}))[0], 3)
        k, note = cc.vote_hartigan(pd.Series({2: 1., 3: 2., 4: 3.}))
        self.assertIsNone(k)
        self.assertIn("No positive drop", note)
        k, note = cc.vote_hartigan(pd.Series({2: 5., 3: np.nan}))
        self.assertIsNone(k)
        self.assertIn("consecutive", note)

    def test_frey(self):
        self.assertEqual(cc.vote_frey(pd.Series({2: .34, 3: .58, 4: .03}))[0], 2)
        self.assertEqual(cc.vote_frey(pd.Series({1: .1, 2: 1.4, 3: .58, 4: np.nan}))[0], 3)
        self.assertEqual(cc.vote_frey(pd.Series({2: 1.4, 3: np.nan}))[1], "No ratio below 1")
        self.assertIsNone(cc.vote_frey(pd.Series({2: np.nan}))[0])

    def test_trace_w(self):
        self.assertEqual(cc.vote_trace_w(pd.Series({1: 100., 2: 40., 3: 30., 4: 25.}))[0], 2)
        self.assertIsNone(cc.vote_trace_w(pd.Series({2: 40., 3: 30.}))[0])
        self.assertIsNone(cc.vote_trace_w(pd.Series({1: 30., 2: 20., 3: 10.}))[0])
        # Without k = 3 only k = 5 has both neighbours.
        self.assertEqual(cc.vote_trace_w(pd.Series({1: 100., 2: 40., 4: 30., 5: 20., 6: 19.}))[0], 5)

    def test_gap_one_standard_error_rule(self):
        gap = pd.Series({1: .5, 2: 1., 3: 1.1, 4: 1.3})
        se = pd.Series({1: .1, 2: .2, 3: .2, 4: .2})
        self.assertEqual(cc.vote_gap(gap, se), (2, ""))
        self.assertEqual(gap.idxmax(), 4)
        # k = 1 would satisfy the rule but cannot be a candidate.
        self.assertEqual(cc.vote_gap(pd.Series({1: 2., 2: 1., 3: .5}), pd.Series(.01, index=[1, 2, 3]))[0], 2)
        k, note = cc.vote_gap(pd.Series({1: 1., 2: 2., 3: 3.}), pd.Series(.01, index=[1, 2, 3]))
        self.assertEqual(k, 3)
        self.assertIn("Fallback", note)
        self.assertIsNone(cc.vote_gap(pd.Series({1: 1., 2: np.nan}), pd.Series({1: .1, 2: .1}))[0])

    def test_tally_ties_and_abstention(self):
        votes = pd.DataFrame({"Recommended k": pd.array([2, 4, None, 4, 2], dtype="Int64")})
        summary = cc.tally(votes, [1, 2, 3, 4])
        self.assertEqual(summary["recommended"], 2)
        self.assertEqual(summary["tied"], [2, 4])
        self.assertEqual(summary["voting"], 4)
        self.assertEqual(summary["abstaining"], 1)
        self.assertEqual(summary["counts"].to_dict(), {2: 2, 3: 0, 4: 2})
        silent = cc.tally(pd.DataFrame({"Recommended k": pd.array([None] * 3, dtype="Int64")}), [1, 2])
        self.assertIsNone(silent["recommended"])
        self.assertEqual(silent["tied"], [])

    def test_index_votes_from_injected_table(self):
        ks = [1, 2, 3, 4]
        table = pd.DataFrame(np.nan, index=pd.Index(ks, name="k"), columns=[*cc.INDEX_COLUMNS, "Gap SE"])
        table[cc.SILHOUETTE] = [np.nan, .2, .6, .4]
        table[cc.C_INDEX] = [np.nan, .3, .1, .2]
        table[cc.BALL_HALL] = [50., 8., 3., 2.]
        table[cc.FREY] = [np.nan, 1.2, .5, np.nan]
        votes = cc.index_votes(table)
        self.assertEqual(votes.index.tolist(), list(cc.INDEX_COLUMNS))
        self.assertEqual(votes.loc[cc.SILHOUETTE, "Recommended k"], 3)
        self.assertAlmostEqual(votes.loc[cc.SILHOUETTE, "Value"], .6)
        self.assertEqual(votes.loc[cc.C_INDEX, "Recommended k"], 3)
        self.assertEqual(votes.loc[cc.BALL_HALL, "Recommended k"], 3)
        self.assertEqual(votes.loc[cc.FREY, "Recommended k"], 3)
        self.assertTrue(pd.isna(votes.loc[cc.DUNN, "Recommended k"]))
        self.assertTrue(votes.loc[cc.DUNN, "Note"])
        self.assertEqual(cc.tally(votes, ks)["recommended"], 3)


class WineReferenceTests(unittest.TestCase):
    """UCI Wine (doi:10.24432/C5PC7J), original order, class column removed."""

    @classmethod
    def setUpClass(cls):
        raw = pd.read_csv(DATA / "wine.data", header=None)
        cls.frame = raw.iloc[:, 1:].set_axis([f"v{i}" for i in range(1, 14)], axis=1)
        values = cls.frame.to_numpy(dtype=float)
        cls.values = (values - values.mean(axis=0)) / values.std(axis=0, ddof=1)
        cls.labels = np.array([int(c) for c in WINE_LABELS])

    def test_reference_sample(self):
        self.assertEqual(self.frame.shape, (178, 13))
        self.assertEqual(np.bincount(self.labels)[1:].tolist(), [62, 51, 65])

    def test_fixed_partition_matches_reference_indices(self):
        result = cc.partition_indices(self.values, self.labels)
        expected = {
            "WSS": 1270.7491153118078, cc.BALL_HALL: 423.5830384372693, cc.C_INDEX: 0.1224826122194792,
            cc.CALINSKI: 70.94000800315116, cc.DAVIES_RMS: 1.4681431955799333, cc.DUNN: 0.23225671390419228,
            cc.GAMMA: 0.7493440913943652, cc.GPLUS: 0.0556783028453761, cc.MCCLAIN_RAO: 0.6600266503500886,
            cc.POINT_BISERIAL: 0.6153557685453426, cc.RATKOWSKY: 0.38632477592229125,
            cc.SILHOUETTE: 0.2848589191898987, cc.TAU: 0.33290423902746746,
        }
        for name, value in expected.items():
            with self.subTest(index=name):
                self.assertAlmostEqual(result[name], value, delta=1e-11 * max(1, abs(value)))

    def test_scan_is_repeatable_and_consistent(self):
        options = {"max_k": 5, "standardize": True, "seed": 42, "criterion": "consensus", "gap_replicates": 5}
        columns = list(self.frame)
        scan = kmeans_scan(self.frame, columns, **options)
        again = kmeans_scan(self.frame, columns, **options)
        pd.testing.assert_frame_equal(scan.metrics, again.metrics)
        pd.testing.assert_frame_equal(scan.votes, again.votes)
        pd.testing.assert_series_equal(scan.fit.labels, again.fit.labels)
        self.assertEqual(scan.metrics.columns.tolist(), ["WSS", *cc.INDEX_COLUMNS, "Gap SE"])
        self.assertEqual(scan.recommended_k, 3)
        self.assertEqual(scan.selection["counts"].sum(), scan.selection["voting"])
        self.assertEqual(scan.selection["voting"] + scan.selection["abstaining"], 17)
        # The current fit reaches the reference k = 3 partition.
        crosstab = pd.crosstab(scan.fit.labels.to_numpy(), self.labels)
        self.assertTrue(((crosstab > 0).sum(axis=1) == 1).all())
        self.assertAlmostEqual(scan.metrics.loc[3, "WSS"], 1270.7491153118078, places=9)


class ScanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"x": [0., .1, .2, .3, .4, 10., 10.1, 10.2, 10.3, 10.4, 20., 20.2]})

    def test_each_observed_fit_runs_once_and_gap_budget_is_counted(self):
        calls = []
        original = advanced.kmeans

        def counted(frame, columns, count, *args, **kwargs):
            calls.append((frame, count))
            return original(frame, columns, count, *args, **kwargs)

        with patch.object(advanced, "kmeans", counted):
            scan = kmeans_scan(self.frame, ["x"], max_k=4, criterion="consensus", gap_replicates=5)
        observed = calls[0][0]
        self.assertEqual([count for frame, count in calls if frame is observed], [1, 2, 3, 4])
        self.assertEqual(len(calls), 4 + 5 * 4)
        pd.testing.assert_series_equal(scan.fit.labels, original(self.frame, ["x"], scan.recommended_k).labels)

    def test_invalid_parameters_are_rejected_before_fitting(self):
        with patch.object(advanced, "kmeans", side_effect=AssertionError("fitted")):
            for kwargs in ({"gap_replicates": 4}, {"gap_replicates": True}, {"max_k": 31}, {"min_k": 0}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    kmeans_scan(self.frame, ["x"], **{"max_k": 4, "criterion": "consensus", **kwargs})
            with self.assertRaisesRegex(ValueError, "budget"):
                kmeans_scan(pd.DataFrame({"x": np.arange(3000.)}), ["x"], 20, criterion="consensus")

    def test_existing_criteria_keep_their_values(self):
        consensus = kmeans_scan(self.frame, ["x"], max_k=5, criterion="consensus", gap_replicates=8)
        silhouette = kmeans_scan(self.frame, ["x"], max_k=5)
        gap = kmeans_scan(self.frame, ["x"], max_k=5, criterion="gap", gap_replicates=8)
        self.assertEqual(silhouette.metrics.columns.tolist(),
                         ["WSS", "Silhouette", "Calinski–Harabasz", "Davies–Bouldin"])
        for name in ("WSS", "Silhouette", "Calinski–Harabasz"):
            pd.testing.assert_series_equal(consensus.metrics[name], silhouette.metrics[name])
        pd.testing.assert_series_equal(consensus.metrics["Gap"], gap.metrics["Gap"])
        pd.testing.assert_series_equal(consensus.metrics["Gap SE"], gap.metrics["Gap SE"])
        self.assertIsNone(silhouette.votes)
        self.assertEqual(consensus.recommended_k, 3)

    def test_k_one_never_wins_and_missing_neighbour_abstains(self):
        scan = kmeans_scan(self.frame, ["x"], max_k=3, criterion="consensus", gap_replicates=5)
        self.assertTrue(scan.metrics.loc[1, list(NAN_FREE_INDICES)].isna().all())
        self.assertNotIn(1, scan.selection["counts"].index)
        self.assertTrue(np.isnan(scan.metrics.loc[3, cc.FREY]))
        self.assertTrue(np.isnan(scan.metrics.loc[3, cc.HARTIGAN]))
        self.assertTrue(np.isnan(scan.metrics.loc[3, cc.KRZANOWSKI_LAI]))
        self.assertFalse((scan.votes["Recommended k"].dropna() < 2).any())

    def test_terminal_partition_reports_and_votes_only_defined_indices(self):
        frame = pd.DataFrame({"x": [0., 5.]})
        scan = kmeans_scan(frame, ["x"], max_k=2, criterion="consensus", gap_replicates=5)
        self.assertEqual(scan.metrics.loc[2, cc.DAVIES_RMS], 0.)
        self.assertAlmostEqual(scan.metrics.loc[2, cc.RATKOWSKY], 1 / np.sqrt(2))
        self.assertTrue(scan.metrics.loc[2, [cc.SILHOUETTE, cc.CALINSKI, cc.C_INDEX, cc.DUNN, cc.GAP]].isna().all())
        self.assertEqual(scan.votes["Recommended k"].dropna().to_dict(), {cc.DAVIES_RMS: 2, cc.RATKOWSKY: 2})
        self.assertEqual(scan.recommended_k, 2)
        self.assertEqual(scan.fit.labels.nunique(), 2)
        legacy = kmeans_scan(frame, ["x"], max_k=2, criterion="davies-bouldin")
        self.assertIsNone(legacy.recommended_k)
        self.assertTrue(np.isnan(legacy.metrics.loc[2, "Davies–Bouldin"]))

    def test_consensus_computes_pairwise_distances_once(self):
        with patch.object(advanced, "pdist", wraps=advanced.pdist) as standalone:
            with patch.object(cc, "pdist", wraps=cc.pdist) as cached:
                kmeans_scan(self.frame, ["x"], max_k=4, criterion="consensus", gap_replicates=5)
        self.assertEqual(standalone.call_count + cached.call_count, 1)

    def test_gap_reference_failure_leaves_the_other_votes_available(self):
        a = 1.
        b = np.nextafter(a, np.inf)
        c = np.nextafter(b, np.inf)
        frame = pd.DataFrame({"x": [a, a, b, c]})
        options = {"max_k": 2, "seed": 2, "gap_replicates": 5}
        scan = kmeans_scan(frame, ["x"], criterion="consensus", **options)
        self.assertEqual(scan.recommended_k, 2)
        self.assertTrue(pd.isna(scan.votes.loc[cc.GAP, "Recommended k"]))
        self.assertTrue(np.isnan(scan.metrics.loc[2, cc.GAP]))
        self.assertTrue(np.isnan(scan.metrics.loc[2, "Gap SE"]))
        with self.assertRaises(ValueError):
            kmeans_scan(frame, ["x"], criterion="gap", **options)

    def test_zero_wss_calinski_abstains_with_blank_consensus_cell(self):
        frame = pd.DataFrame({"x": [0., 0., 5., 5.]})
        scan = kmeans_scan(frame, ["x"], max_k=2, criterion="consensus", gap_replicates=5)
        self.assertTrue(np.isnan(scan.metrics.loc[2, cc.CALINSKI]))
        self.assertTrue(pd.isna(scan.votes.loc[cc.CALINSKI, "Recommended k"]))
        legacy = kmeans_scan(frame, ["x"], max_k=2, criterion="calinski-harabasz")
        self.assertTrue(np.isinf(legacy.metrics.loc[2, cc.CALINSKI]))

    def test_no_candidates_leaves_diagnostics(self):
        scan = kmeans_scan(self.frame, ["x"], max_k=1, criterion="consensus", gap_replicates=5)
        self.assertIsNone(scan.recommended_k)
        self.assertIsNone(scan.fit)
        self.assertEqual(scan.selection["abstaining"], 17)
        self.assertEqual(scan.metrics.columns.tolist(), ["WSS", *cc.INDEX_COLUMNS, "Gap SE"])
        self.assertEqual(scan.metrics.index.tolist(), [1])


class WorkbenchConsensusTests(unittest.TestCase):
    def setUp(self):
        points = [(x + dx, y + dy) for x, y in [(0, 0), (6, 0), (3, 5)]
                  for dx, dy in [(-.3, -.2), (.2, -.3), (.3, .2), (-.2, .3), (0, 0)]]
        frame = pd.DataFrame(points, columns=["a", "b"])
        frame.loc[len(frame)] = [np.nan, 1.]
        self.frame = frame.set_axis(range(100, 100 + len(frame)))
        self.options = {"Variables": ["a", "b"], "Minimum k": 1, "Maximum k": 5, "Standardize": True,
                        "Seed": 42, "Criterion": "Consensus (17 indices)", "Gap simulations": 5}

    def test_result_sheets_and_vote_chart(self):
        result = analyse("K-means model selection", self.frame, self.options)
        self.assertEqual(list(result.tables), ["Cluster metrics", "Consensus votes", "Selection", "Assignments"])
        selection = result.tables["Selection"]["Value"]
        self.assertEqual(selection["Suggested k"], 3)
        self.assertEqual(selection["Indices voting"] + selection["Indices abstaining"], 17)
        self.assertEqual(result.tables["Consensus votes"].columns.tolist(), ["Rule", "Recommended k", "Value", "Note"])
        assignments = result.tables["Assignments"]
        self.assertEqual(assignments.index.tolist(), list(range(100, 115)))
        self.assertEqual(assignments["Cluster"].nunique(), 3)
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_title(), "K-means consensus votes")
        self.assertEqual(axes.get_ylabel(), "Votes")
        self.assertEqual(len(axes.patches), 4)  # k = 2..5
        self.assertEqual(sum(bar.get_height() for bar in axes.patches), selection["Indices voting"])

    def test_no_votes_keeps_diagnostics(self):
        result = analyse("K-means model selection", self.frame, {**self.options, "Maximum k": 1})
        self.assertNotIn("Assignments", result.tables)
        self.assertIsNone(result.tables["Selection"].loc["Suggested k", "Value"])
        self.assertIn("Cluster metrics", result.tables)

    def test_assignments_preserve_a_source_variable_named_cluster(self):
        frame = self.frame.rename(columns={"a": "Cluster", "b": "Cluster (assigned)"})
        options = {**self.options, "Variables": list(frame)}
        result = analyse("K-means model selection", frame, options)
        assignments = result.tables["Assignments"]
        pd.testing.assert_frame_equal(assignments.loc[:, list(frame)], frame.dropna())
        self.assertEqual(len(assignments.columns), 3)
        self.assertEqual(assignments.iloc[:, -1].nunique(), 3)

    def test_saved_recipes_reopen_with_the_same_values(self):
        single = {**self.options, "Criterion": "Silhouette"}
        legacy = {"Variables": ["a", "b"], "Maximum k": 4, "Standardize": True, "Seed": 42, "Criterion": "Elbow"}
        recipes = [single, legacy, self.options]
        before = [analyse("K-means model selection", self.frame, options).tables for options in recipes]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clusters.alab"
            data = Dataset(self.frame.reset_index(drop=True))
            data.analyses.extend(("K-means model selection", options) for options in recipes)
            save_project(path, {"Clusters": data})
            loaded = load_project(path)["Clusters"]
        self.assertEqual(loaded.analyses, data.analyses)
        for (method, options), tables in zip(loaded.analyses, before):
            after = analyse(method, loaded.frame(), options).tables
            self.assertEqual(list(after), list(tables))
            for name in tables:
                if name != "Assignments":
                    pd.testing.assert_frame_equal(after[name], tables[name])
            self.assertEqual(after["Assignments"]["Cluster"].tolist(), tables["Assignments"]["Cluster"].tolist())


if __name__ == "__main__":
    unittest.main()
