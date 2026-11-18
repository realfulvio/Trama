"""Silhouettes of a given partition: oracle values, edge cases, budgets, scale, blocks and cancellation."""
from math import dist, fsum, sqrt
from pathlib import Path
from statistics import mean
from threading import Event
import json
import tracemalloc
import unittest
from unittest import mock

import numpy as np
import pandas as pd

import analisi.cluster_silhouette as module
from analisi.analysis_chain import ChainCancelled, result_frame
from analisi.cluster_silhouette import (CLUSTER, CLUSTERS, DISTANCE, GRAPH, LABELS, METHOD, OBSERVATIONS, STANDARDIZE,
                                        SUMMARY, VARIABLES, SilhouetteCancelled, block_rows, captions, default_options,
                                        prepare, scaled_points, silhouette_arrays, suggest_cluster)
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "cluster_silhouette"
FIELDS = ["Source row", "Observation", "Cluster", "Within mean distance", "Nearest other cluster",
          "Nearest mean distance", "Silhouette"]


def options(variables=("X", "Y"), cluster="Group", *, distance="Euclidean", standardize=False, graph=False,
            labels=None):
    return {VARIABLES: list(variables), CLUSTER: cluster, LABELS: labels, DISTANCE: distance,
            STANDARDIZE: standardize, GRAPH: graph}


def read(name):
    return pd.read_csv(DATA / name, keep_default_na=False, na_values=[""])


def scalar_reference(frame, opts):
    """Silhouettes with scalar sums, one pair at a time, from the definition."""
    complete = frame.reset_index(drop=True).dropna(subset=[*opts[VARIABLES], opts[CLUSTER]])
    points = [tuple(map(float, row)) for row in complete[opts[VARIABLES]].itertuples(index=False, name=None)]
    if opts[STANDARDIZE]:
        columns = list(zip(*points))
        centres = [mean(column) for column in columns]
        scales = [sqrt(mean([(x - centre) ** 2 for x in column])) or 1. for column, centre in zip(columns, centres)]
        points = [tuple((x - c) / s for x, c, s in zip(row, centres, scales)) for row in points]
    groups = complete[opts[CLUSTER]].tolist()
    order = list(dict.fromkeys(groups))

    def distance(a, b):
        return dist(a, b) if opts[DISTANCE] == "Euclidean" else fsum(abs(x - y) for x, y in zip(a, b))

    rows = []
    for i, (vector, own) in enumerate(zip(points, groups)):
        same = [distance(vector, points[j]) for j in range(len(points)) if groups[j] == own and j != i]
        a = mean(same) if same else None
        b, rival = min(((mean([distance(vector, p) for p, g in zip(points, groups) if g == other]), other)
                        for other in order if other != own), key=lambda pair: pair[0])
        rows.append([complete.index[i] + 1, own, a, rival, b,
                     (b - a) / max(a, b) if a is not None and max(a, b) else 0.])
    return rows


class FrozenFixtures(unittest.TestCase):
    """The synthetic fixtures with values frozen from an independent scalar oracle."""

    def setUp(self):
        self.expected = json.loads((DATA / "expected.json").read_text(encoding="utf8"))
        self.cases = {
            "euclidean": ("observations.csv", "Euclidean", False, True),
            "manhattan": ("observations.csv", "Manhattan", False, False),
            "standardize": ("observations.csv", "Euclidean", True, False),
            "tied-rivals": ("ties.csv", "Manhattan", False, False),
        }

    def result(self, name):
        filename, distance, standardize, graph = self.cases[name]
        frame = read(filename)
        # A non-positional row index must never leak into the source rows.
        frame.index = [7] * len(frame)
        return analyse(METHOD, frame, options(distance=distance, standardize=standardize, graph=graph,
                                              labels="Name"))

    def test_points_clusters_and_summary_match_the_frozen_values(self):
        for name, expected in self.expected.items():
            with self.subTest(name):
                result = self.result(name)
                points = result.tables[OBSERVATIONS]
                self.assertEqual(list(points.columns), FIELDS)
                self.assertEqual(len(points), len(expected["observations"]))
                for row, reference in zip(points.to_numpy(dtype=object).tolist(), expected["observations"]):
                    self.assertEqual(row[:3], reference[:3])
                    self.assertEqual(row[4], reference[4])
                    for got, want in ((row[3], reference[3]), (row[5], reference[5]), (row[6], reference[6])):
                        if want is None:
                            self.assertTrue(pd.isna(got))
                        else:
                            self.assertAlmostEqual(got, want, places=11)
                clusters = result.tables[CLUSTERS]
                self.assertEqual(list(clusters.columns), ["Cluster", "N", "Mean silhouette", "Negative samples"])
                for row, reference in zip(clusters.to_numpy(dtype=object).tolist(), expected["clusters"]):
                    self.assertEqual([row[0], row[1], row[3]], [reference[0], reference[1], reference[3]])
                    self.assertAlmostEqual(row[2], reference[2], places=11)
                summary = result.tables[SUMMARY]["Value"]
                for key, value in expected["summary"].items():
                    self.assertAlmostEqual(summary[key], value, places=11)
                self.assertIsNone(result.figure) if not self.cases[name][3] else self.assertIsNotNone(result.figure)

    def test_negative_value_singleton_and_literal_dollar_are_kept(self):
        result = self.result("euclidean")
        points = result.tables[OBSERVATIONS].set_index("Source row")
        self.assertLess(points.loc[3, "Silhouette"], 0)
        self.assertEqual(points.loc[3, "Observation"], "")
        self.assertEqual(points.loc[1, "Observation"], "Original $A")
        self.assertEqual(points.loc[8, "Silhouette"], 0)
        self.assertTrue(pd.isna(points.loc[8, "Within mean distance"]))
        self.assertEqual(points.loc[8, "Nearest other cluster"], "B")
        self.assertEqual(result.tables[CLUSTERS].set_index("Cluster").loc["A", "Negative samples"], 1)

    def test_summary_names_the_distance_and_the_scale(self):
        summary = self.result("standardize").tables[SUMMARY]["Value"]
        self.assertEqual(summary["Distance"], "Euclidean")
        self.assertEqual(summary["Scale"], module.STANDARDIZED_UNITS)
        self.assertEqual(self.result("manhattan").tables[SUMMARY]["Value"]["Scale"], module.ORIGINAL_UNITS)
        self.assertEqual(summary["Dropped rows"], 2)

    def test_exact_ties_choose_the_first_cluster_in_order_of_appearance(self):
        points = self.result("tied-rivals").tables[OBSERVATIONS]
        self.assertEqual(points["Nearest other cluster"].tolist()[:2], ["Right", "Right"])
        # The same points with the rivals in the opposite order of appearance.
        frame = read("ties.csv")
        flipped = pd.concat([frame.iloc[:2], frame.iloc[[4, 5, 2, 3]]], ignore_index=True)
        again = analyse(METHOD, flipped, options(distance="Manhattan", labels="Name")).tables[OBSERVATIONS]
        self.assertEqual(again["Nearest other cluster"].tolist()[:2], ["Left", "Left"])


class AgainstTheDefinition(unittest.TestCase):
    def test_random_partitions_match_the_scalar_oracle_for_both_metrics_and_scales(self):
        rng = np.random.default_rng(20261118)
        for trial in range(12):
            n, p = int(rng.integers(6, 40)), int(rng.integers(1, 5))
            frame = pd.DataFrame(rng.normal(size=(n, p)) * rng.uniform(.5, 30, size=p),
                                 columns=[f"v{i}" for i in range(p)])
            labels = rng.integers(0, 4, size=n)
            labels[:2] = [0, 1]
            frame["g"] = pd.Series(labels).map(lambda value: f"c{value}")
            frame.iloc[int(rng.integers(0, n)), 0] = np.nan
            for distance in ("Euclidean", "Manhattan"):
                for standardize in (False, True):
                    opts = options(frame.columns[:p], "g", distance=distance, standardize=standardize)
                    got = analyse(METHOD, frame, opts).tables[OBSERVATIONS]
                    want = scalar_reference(frame, opts)
                    with self.subTest(trial=trial, distance=distance, standardize=standardize):
                        self.assertEqual(got["Source row"].tolist(), [row[0] for row in want])
                        self.assertEqual(got["Cluster"].tolist(), [row[1] for row in want])
                        self.assertEqual(got["Nearest other cluster"].tolist(), [row[3] for row in want])
                        np.testing.assert_allclose(got["Silhouette"], [row[5] for row in want], rtol=1e-9, atol=1e-11)
                        np.testing.assert_allclose(got["Nearest mean distance"], [row[4] for row in want],
                                                   rtol=1e-9, atol=1e-11)

    def test_the_input_frame_is_not_changed(self):
        frame = read("observations.csv")
        before = frame.copy(deep=True)
        analyse(METHOD, frame, options(labels="Name", graph=True))
        pd.testing.assert_frame_equal(frame, before)

    def test_coincident_points_and_constant_columns_give_zero(self):
        frame = pd.DataFrame({"X": [2, 2, 2, 2], "Y": [4, 4, 4, 4], "Group": list("aabb")})
        for standardize in (False, True):
            table = analyse(METHOD, frame, options(distance="Manhattan", standardize=standardize)).tables[OBSERVATIONS]
            self.assertEqual(table["Silhouette"].tolist(), [0, 0, 0, 0])
            self.assertEqual(table["Nearest mean distance"].tolist(), [0, 0, 0, 0])
        constant = pd.DataFrame({"X": [0., 1, 8, 9], "Y": [.1] * 4, "Group": list("aabb")})
        scaled = analyse(METHOD, constant, options(standardize=True)).tables[OBSERVATIONS]
        plain = analyse(METHOD, constant, options(variables=("X",), standardize=True)).tables[OBSERVATIONS]
        np.testing.assert_allclose(scaled["Silhouette"], plain["Silhouette"], atol=1e-12)

    def test_standardizing_uses_the_population_sd_of_the_complete_rows(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 10, 11, 12, 99.], "Y": [5., 6, 7, 5, 6, np.nan, 5],
                              "Group": list("aaabbbb")})
        table = analyse(METHOD, frame, options(standardize=True)).tables[OBSERVATIONS]
        self.assertEqual(table["Source row"].tolist(), [1, 2, 3, 4, 5, 7])
        want = scalar_reference(frame, options(standardize=True))
        np.testing.assert_allclose(table["Silhouette"], [row[5] for row in want], rtol=1e-9)


class Labels(unittest.TestCase):
    def labelled(self, groups):
        return pd.DataFrame({"X": [0., 1, 5, 6], "Y": [0., 1, 5, 6], "Group": pd.Series(groups, dtype=object)})

    def test_number_and_text_labels_are_different_clusters_and_keep_their_values(self):
        result = analyse(METHOD, self.labelled([1, 1, "1", "1"]), options())
        clusters = result.tables[CLUSTERS]
        self.assertEqual(len(clusters), 2)
        self.assertEqual([type(value) for value in clusters["Cluster"]], [int, str])
        points = result.tables[OBSERVATIONS]
        self.assertEqual([type(value) for value in points["Nearest other cluster"]], [str, str, int, int])

    def test_caption_texts_are_told_apart_only_when_they_collide(self):
        self.assertEqual(captions(["A", "B"]), ["A", "B"])
        self.assertEqual(captions([1, "1"]), ["1 (number)", "1 (text)"])
        self.assertEqual(len(set(captions([1, "1", "1 (text)", "1 (number)"]))), 4)
        figure = analyse(METHOD, self.labelled([1, 1, "1", "1"]), options(graph=True)).figure
        texts = [label.get_text() for label in figure.axes[0].get_yticklabels()]
        self.assertTrue(texts[0] != texts[1] and all("1" in text for text in texts), texts)

    def test_unsupported_labels_are_field_errors_on_cluster(self):
        for bad in ([True, True, False, False], ["a", "a", " ", " "], [1., 1., np.inf, np.inf],
                    [1, 1, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01")]):
            with self.subTest(bad=bad), self.assertRaises(FieldError) as raised:
                analyse(METHOD, self.labelled(bad), options())
            self.assertEqual(raised.exception.field, CLUSTER)

    def test_rows_without_a_cluster_or_with_a_missing_value_are_dropped_and_counted(self):
        frame = pd.DataFrame({"X": [0., 1, 5, 6, np.nan, 3], "Y": [0., 1, 5, 6, 1, 3],
                              "Group": ["a", "a", "b", "b", "b", None]})
        result = analyse(METHOD, frame, options())
        self.assertEqual(result.tables[OBSERVATIONS]["Source row"].tolist(), [1, 2, 3, 4])
        self.assertEqual(result.tables[SUMMARY]["Value"]["Dropped rows"], 2)

    def test_a_missing_observation_name_does_not_drop_the_row(self):
        frame = read("observations.csv")
        table = analyse(METHOD, frame, options(labels="Name")).tables[OBSERVATIONS]
        self.assertEqual(table["Observation"].tolist(), ["Original $A", "a2", "", "b1", "b2", "b3", "single"])

    def test_cluster_values_of_a_numeric_column_stay_numbers(self):
        frame = pd.DataFrame({"X": [0., 1, 5, 6], "Y": [0., 1, 5, 6], "Group": [3, 3, 7, 7]})
        table = analyse(METHOD, frame, options()).tables[OBSERVATIONS]
        self.assertEqual(table["Cluster"].tolist(), [3, 3, 7, 7])
        self.assertEqual(table["Nearest other cluster"].tolist(), [7, 7, 3, 3])


class Validation(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"X": [0., 1, 2, 9, 10, 11], "Y": [1., 0, 2, 9, 11, 10], "Z": range(6),
                                   "Group": list("aabbcc"), "Name": list("uvwxyz")})

    def assert_field(self, field, **changes):
        base = options(("X", "Y"), "Group")
        base.update(changes)
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, self.frame, base)
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        return str(raised.exception)

    def test_roles_must_be_distinct_existing_columns(self):
        self.assert_field(CLUSTER, **{CLUSTER: "X"})
        self.assert_field(LABELS, **{LABELS: "Group"})
        self.assert_field(LABELS, **{LABELS: "X"})
        self.assert_field(VARIABLES, **{VARIABLES: ["X", "X"]})
        self.assert_field(VARIABLES, **{VARIABLES: []})
        self.assert_field(VARIABLES, **{VARIABLES: ["missing"]})
        self.assert_field(CLUSTER, **{CLUSTER: None})
        self.assert_field(CLUSTER, **{CLUSTER: "missing"})
        self.assert_field(LABELS, **{LABELS: "missing"})

    def test_at_most_32_variables(self):
        wide = pd.DataFrame(np.arange(40.).reshape(4, 10).repeat(4, axis=1), columns=[f"c{i}" for i in range(40)])
        wide["g"] = list("aabb")
        analyse(METHOD, wide, options(wide.columns[:32], "g"))
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, wide, options(wide.columns[:33], "g"))
        self.assertEqual(raised.exception.field, VARIABLES)

    def test_choices_and_flags_are_checked(self):
        self.assert_field(DISTANCE, **{DISTANCE: "Chebyshev"})
        self.assert_field(STANDARDIZE, **{STANDARDIZE: "yes"})
        self.assert_field(GRAPH, **{GRAPH: 1})

    def test_text_and_infinite_values_in_a_variable_are_a_field_error(self):
        for bad in ("abc", np.inf):
            self.frame = self.frame.astype({"X": object})
            self.frame.loc[2, "X"] = bad
            self.assert_field(VARIABLES)

    def test_the_number_of_clusters_must_be_between_2_and_n_minus_1(self):
        self.frame["Group"] = "a"
        self.assert_field(CLUSTER)
        self.frame["Group"] = list("abcdef")
        self.assert_field(CLUSTER)
        self.frame["Group"] = list("abcdea")
        analyse(METHOD, self.frame, options())
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, self.frame.iloc[:2], options())
        self.assertEqual(raised.exception.field, CLUSTER)

    def test_row_and_scalar_budgets_are_checked_before_any_distance_is_allocated(self):
        with mock.patch.object(module, "cdist", side_effect=AssertionError("distances allocated")):
            big = pd.DataFrame({"X": np.arange(5001.), "Y": 0., "Group": ["a", "b"] * 2500 + ["a"]})
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, big, options())
            self.assertEqual(raised.exception.field, VARIABLES)
            # 5 000 rows are allowed with up to 8 variables; a ninth exceeds N² · p = 200 000 000.
            wide = pd.DataFrame(np.zeros((5000, 9)), columns=[f"c{i}" for i in range(9)])
            wide["g"] = ["a", "b"] * 2500
            with self.assertRaises(FieldError) as raised:
                prepare(wide, options(wide.columns[:9], "g"))
            self.assertEqual(raised.exception.field, VARIABLES)
            prepare(wide, options(wide.columns[:8], "g"))

    def test_the_graph_has_its_own_smaller_budget(self):
        rows = module.MAX_GRAPH_ROWS + 1
        frame = pd.DataFrame({"X": np.arange(float(rows)), "Y": 0., "Group": ["a", "b"] * (rows // 2) + ["a"]})
        with self.assertRaises(FieldError) as raised:
            prepare(frame, options(graph=True))
        self.assertEqual(raised.exception.field, GRAPH)
        self.assertIn("Turn Graph off", str(raised.exception))
        result = analyse(METHOD, frame, options(graph=False))
        self.assertEqual(len(result.tables[OBSERVATIONS]), rows)
        self.assertIsNone(result.figure)

    def test_the_dialog_check_does_not_compute_distances(self):
        with mock.patch.object(module, "cdist", side_effect=AssertionError("distances computed")):
            module.check_options(self.frame, options())


class Scale(unittest.TestCase):
    def frame(self, factor):
        return pd.DataFrame({"X": np.array([0., 1, 2, 9, 10, 12]) * factor,
                             "Y": np.array([1., 0, 3, 9, 11, 10]) * factor, "Group": list("aabbbb")})

    def test_a_power_of_two_rescaling_gives_identical_silhouettes_and_scaled_distances(self):
        base = analyse(METHOD, self.frame(1.), options()).tables[OBSERVATIONS]
        for exponent in (-1000, -300, 300, 1000):
            with self.subTest(exponent=exponent):
                table = analyse(METHOD, self.frame(2. ** exponent), options()).tables[OBSERVATIONS]
                np.testing.assert_array_equal(table["Silhouette"], base["Silhouette"])
                np.testing.assert_allclose(table["Nearest mean distance"],
                                           np.ldexp(base["Nearest mean distance"], exponent), rtol=1e-12)

    def test_extreme_magnitudes_do_not_overflow_or_underflow(self):
        for factor in (1e-200, 1e200, 1e-307):
            table = analyse(METHOD, self.frame(factor), options(distance="Manhattan")).tables[OBSERVATIONS]
            self.assertTrue(np.isfinite(table["Silhouette"]).all(), factor)
            self.assertTrue(np.isfinite(table["Nearest mean distance"]).all(), factor)
        # Standardizing removes the scale: the silhouettes of a column in 1e200 units equal the plain ones.
        small = analyse(METHOD, self.frame(1.), options(standardize=True)).tables[OBSERVATIONS]
        huge = analyse(METHOD, self.frame(1e200), options(standardize=True)).tables[OBSERVATIONS]
        np.testing.assert_allclose(huge["Silhouette"], small["Silhouette"], rtol=1e-12)
        np.testing.assert_allclose(huge["Nearest mean distance"], small["Nearest mean distance"], rtol=1e-12)

    def test_distances_that_cannot_be_represented_are_a_field_error_on_variables(self):
        frame = pd.DataFrame({"X": [-1.7e308, -1.6e308, 1.6e308, 1.7e308], "Y": 0., "Group": list("aabb")})
        for distance in ("Euclidean", "Manhattan"):
            with self.subTest(distance=distance), self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, options(distance=distance))
            self.assertEqual(raised.exception.field, VARIABLES)
        # The same data standardized have ordinary distances.
        analyse(METHOD, frame, options(standardize=True))

    def test_scaled_points_are_small_and_restore_the_distances(self):
        matrix = np.array([[1e300, -2e300], [3e299, 4e300]])
        points, exponent = scaled_points(matrix, False)
        self.assertLess(np.abs(points).max(), 1)
        np.testing.assert_array_equal(np.ldexp(points, exponent), matrix)
        standard, none = scaled_points(matrix, True)
        self.assertEqual(none, 0)
        np.testing.assert_allclose(standard.mean(axis=0), 0, atol=1e-12)
        np.testing.assert_allclose(standard.std(axis=0), 1)


class Blocks(unittest.TestCase):
    def test_every_block_size_gives_the_same_numbers(self):
        rng = np.random.default_rng(5)
        points = rng.normal(size=(97, 3))
        membership = rng.integers(0, 6, size=97)
        membership[:2] = [0, 1]
        reference = silhouette_arrays(points, membership, 6, "Euclidean")
        for rows in (1, 2, 13, 96, 97, 500):
            for left, right in zip(reference, silhouette_arrays(points, membership, 6, "Euclidean",
                                                                rows_per_block=rows)):
                np.testing.assert_array_equal(left, right)

    def test_block_rows_keep_the_distance_arrays_within_32_mib(self):
        for rows, clusters in ((5000, 2), (5000, 4999), (2000, 1000), (3, 2)):
            step = block_rows(rows, clusters)
            self.assertGreaterEqual(step, 1)
            self.assertLessEqual(step * 8 * (rows + 2 * clusters), 32 * 2**20 + 8 * (rows + 2 * clusters))

    def test_many_small_clusters_use_one_distance_per_pair(self):
        rows = 600
        rng = np.random.default_rng(8)
        points = rng.normal(size=(rows, 2))
        membership = np.arange(rows) // 2  # 300 clusters of two
        with mock.patch.object(module, "cdist", wraps=module.cdist) as spy:
            silhouette_arrays(points, membership, 300, "Manhattan")
        calls = spy.call_count
        self.assertEqual(calls, -(-rows // block_rows(rows, 300)))
        self.assertTrue(all(call.args[0].shape[0] <= block_rows(rows, 300) for call in spy.call_args_list))

    def test_peak_memory_stays_within_the_block_budget(self):
        rows = 3000
        rng = np.random.default_rng(9)
        points = rng.normal(size=(rows, 4))
        membership = rng.integers(0, 12, size=rows)
        membership[:2] = [0, 1]
        tracemalloc.start()
        silhouette_arrays(points, membership, 12, "Euclidean")
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        self.assertLess(peak, 40 * 2**20)


class StepCounter:
    """A cancel event that fires on the n-th time the worker asks."""

    def __init__(self, after):
        self.after, self.asked = after, 0

    def is_set(self):
        self.asked += 1
        return self.asked > self.after


class Cancellation(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"X": np.arange(60.), "Y": np.arange(60.) % 7, "Group": ["a", "b", "c"] * 20})

    def test_an_event_that_is_already_set_stops_before_any_work(self):
        cancel = Event()
        cancel.set()
        with mock.patch.object(module, "cdist", side_effect=AssertionError("started")):
            with self.assertRaises(ChainCancelled):
                analyse(METHOD, self.frame, options(), cancel=cancel)

    def test_the_exception_is_also_the_desktop_cancel_exception(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(MonteCarloCancelled):
            analyse(METHOD, self.frame, options(), cancel=cancel)
        self.assertTrue(issubclass(SilhouetteCancelled, ChainCancelled))

    def test_the_event_is_read_before_every_block_and_before_the_result(self):
        with mock.patch.object(module, "BLOCK_BYTES", 8 * (60 + 6) * 7):
            self.assertEqual(block_rows(60, 3), 7)
            counter = StepCounter(after=10**6)
            analyse(METHOD, self.frame, options(), cancel=counter)
            blocks = -(-60 // 7)
            # One read on entry, one per block, one when the arrays are ready, one before the result.
            self.assertEqual(counter.asked, 1 + blocks + 1 + 1)
            for after in range(0, blocks + 2):
                with self.subTest(after=after), self.assertRaises(ChainCancelled):
                    analyse(METHOD, self.frame, options(), cancel=StepCounter(after))

    def test_a_calculation_without_an_event_is_not_cancellable(self):
        self.assertEqual(len(analyse(METHOD, self.frame, options(), cancel=None).tables[OBSERVATIONS]), 60)

    def test_the_stop_latency_is_one_block(self):
        rows = 2500
        frame = pd.DataFrame({"X": np.arange(float(rows)), "Y": np.arange(rows) % 11, "Group": np.arange(rows) % 4})
        with mock.patch.object(module, "BLOCK_BYTES", 8 * (rows + 8) * 100):
            self.assertEqual(block_rows(rows, 4), 100)
            counter = StepCounter(after=6)
            with mock.patch.object(module, "cdist", wraps=module.cdist) as spy:
                with self.assertRaises(ChainCancelled):
                    analyse(METHOD, frame, options(), cancel=counter)
        # The entry read and five block reads passed; the seventh read stopped the sixth block before its distances.
        self.assertEqual(spy.call_count, 5)
        self.assertEqual(counter.asked, 7)


class Graph(unittest.TestCase):
    def result(self, **extra):
        frame = read("observations.csv")
        return analyse(METHOD, frame, options(graph=True, labels="Name", **extra))

    def test_bars_follow_the_cluster_sheet_and_rise_with_the_silhouette(self):
        result = self.result()
        axes = result.figure.axes[0]
        self.assertEqual(len(result.figure.axes), 1)
        widths = [float(patch.get_width()) for patch in axes.patches]
        points = result.tables[OBSERVATIONS]
        expected = []
        for cluster in result.tables[CLUSTERS]["Cluster"]:
            block = points[points["Cluster"] == cluster].sort_values(["Silhouette", "Source row"])
            expected.extend(block["Silhouette"])
        self.assertEqual(widths, expected)
        self.assertEqual(axes.get_xlim(), (-1, 1))
        lines = [line for line in axes.lines if line.get_xdata()[0] == line.get_xdata()[-1]]
        self.assertEqual(sorted(round(float(line.get_xdata()[0]), 9) for line in lines),
                         sorted([0., round(float(result.tables[SUMMARY]["Value"]["Mean silhouette"]), 9)]))

    def test_the_first_cluster_is_on_top_and_blocks_have_a_margin(self):
        axes = self.result().figure.axes[0]
        containers = [container for container in axes.containers]
        self.assertEqual([len(container.patches) for container in containers], [3, 3, 1])
        bottoms = [[patch.get_y() + patch.get_height() / 2 for patch in container.patches] for container in containers]
        self.assertGreater(min(bottoms[0]), max(bottoms[1]))
        self.assertGreater(min(bottoms[1]), max(bottoms[2]))
        self.assertGreaterEqual(min(bottoms[0]) - max(bottoms[1]), 2)
        self.assertEqual(bottoms[0], sorted(bottoms[0]))

    def test_captions_keep_a_dollar_sign_as_text(self):
        frame = pd.DataFrame({"X": [0., 1, 5, 6], "Y": [0., 1, 5, 6], "Group": ["$A$", "$A$", "B$", "B$"]})
        figure = analyse(METHOD, frame, options(graph=True)).figure
        axes = figure.axes[0]
        labels = [text.get_text() for text in axes.get_yticklabels()]
        self.assertIn(r"\$A\$" + "\nn = 2", labels)
        figure.canvas.draw()  # No mathtext parse error.
        self.assertIsNotNone(figure.axes[0].get_legend())

    def test_the_graph_is_a_native_series_graph_with_numeric_value_axis(self):
        from analisi.presentation import graph_series
        figure = self.result().figure
        axes = figure.axes[0]
        self.assertEqual(axes._tramastat_numeric_axes, ("x",))
        self.assertEqual(axes._tramastat_categorical_axes, ("y",))
        kinds = [series.kind for series in graph_series(axes)]
        self.assertEqual(kinds.count("bar"), 3)

    def test_many_small_clusters_label_a_readable_subset(self):
        rows = 200
        frame = pd.DataFrame({"X": np.arange(float(rows)), "Y": np.arange(rows) % 5, "Group": np.arange(rows) // 2})
        figure = analyse(METHOD, frame, options(graph=True)).figure
        labels = figure.axes[0].get_yticklabels()
        self.assertLessEqual(len(labels), module.MAX_CAPTIONS)
        self.assertIn("labelled", figure.axes[0].get_ylabel())
        figure.canvas.draw()


class Linked(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame({"X": [0., 1, 2, 10, 11, 13, np.nan], "Y": [1., 0, 1, 11, 10, 12, 3]})

    def test_the_assignments_table_of_a_kmeans_result_is_a_valid_input(self):
        source = analyse("K-means clustering", self.raw, {VARIABLES: ["X", "Y"], "Clusters": 2,
                                                         "Standardize": False, "Seed": 42})
        original = source.tables["Assignments"].copy(deep=True)
        frame = result_frame(source, "Assignments")
        chosen = default_options(frame)
        self.assertEqual(chosen[CLUSTER], "Cluster")
        self.assertNotIn("Cluster", chosen[VARIABLES])
        result = analyse(METHOD, frame, {**options(chosen[VARIABLES], "Cluster")})
        self.assertEqual(result.tables[OBSERVATIONS]["Source row"].tolist(), list(range(1, 7)))
        pd.testing.assert_frame_equal(original, source.tables["Assignments"])

    def test_the_row_assignments_of_a_hierarchical_result_are_a_valid_input(self):
        source = analyse("Hierarchical clustering", self.raw.dropna(), {
            VARIABLES: ["X", "Y"], "Direction": "Rows", "Row cut": "Count", "Clusters": 2,
            "Linkage": "average", "Distance": "euclidean"})
        name = next(title for title in source.tables if title.endswith("Assignments"))
        frame = result_frame(source, name)
        chosen = default_options(frame)
        self.assertTrue(chosen[CLUSTER].startswith("Cluster"), chosen)
        result = analyse(METHOD, frame, options(chosen[VARIABLES], chosen[CLUSTER]))
        self.assertEqual(len(result.tables[OBSERVATIONS]), len(frame))

    def test_changed_assignments_give_changed_silhouettes(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 10, 11, 13], "Y": [1., 0, 1, 11, 10, 12],
                              "Cluster": [1, 1, 1, 2, 2, 2]})
        good = analyse(METHOD, frame, options(cluster="Cluster")).tables[SUMMARY]["Value"]["Mean silhouette"]
        frame["Cluster"] = [1, 2, 1, 2, 1, 2]
        mixed = analyse(METHOD, frame, options(cluster="Cluster")).tables[SUMMARY]["Value"]["Mean silhouette"]
        self.assertGreater(good, .8)
        self.assertLess(mixed, 0)


class Suggestions(unittest.TestCase):
    def test_the_evident_assignment_column_is_suggested(self):
        self.assertEqual(suggest_cluster(["X", "Y", "Cluster"]), "Cluster")
        self.assertEqual(suggest_cluster(["Cluster", "X", "Cluster (assigned)"]), "Cluster (assigned)")
        self.assertEqual(suggest_cluster(["a", "Group"]), "Group")
        self.assertIsNone(suggest_cluster(["a", "b"]))

    def test_defaults_keep_the_choice_and_leave_the_cluster_out_of_the_variables(self):
        frame = pd.DataFrame({"X": [1., 2, 3], "Cluster": [1, 1, 2], "Name": list("abc")})
        self.assertEqual(default_options(frame), {VARIABLES: ["X"], CLUSTER: "Cluster"})
        self.assertEqual(default_options(pd.DataFrame({"a": [1., 2], "b": [3., 4]})), {VARIABLES: ["a", "b"]})


class Registration(unittest.TestCase):
    def test_the_method_is_listed_with_its_fields_under_clustering(self):
        self.assertIn(METHOD, GROUPS["Clustering"])
        self.assertEqual(list(METHODS[METHOD]), [VARIABLES, CLUSTER, LABELS, DISTANCE, STANDARDIZE, GRAPH])
        self.assertEqual(METHODS[METHOD][DISTANCE], ("Euclidean", "Manhattan"))
        self.assertIs(METHODS[METHOD][STANDARDIZE], False)
        self.assertIs(METHODS[METHOD][GRAPH], True)

    def test_the_graph_request_defaults_to_on(self):
        self.assertTrue(module.requested_graph({}))
        self.assertFalse(module.requested_graph({GRAPH: False}))


if __name__ == "__main__":
    unittest.main()
