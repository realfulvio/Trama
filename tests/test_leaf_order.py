"""Optimal leaf ordering: the exact optimiser against exhaustive search, and the hierarchical clustering sheets."""
import itertools
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage, optimal_leaf_ordering
from scipy.spatial.distance import pdist, squareform

from analisi import leaf_order
from analisi.field_error import FieldError
from analisi.hierarchical_style import _meta, describe_hierarchical_artists
from analisi.hierarchical_workbench import hierarchical_result, hierarchy_graph
from analisi.leaf_order import (LeafOrderCancelled, default_order, layout_tree, optimal_order, order_cost)
from analisi.reporting import Result
from analisi.workbench import analyse

PROFILES = pd.DataFrame({
    "Label": [f"Sample {i}" for i in range(1, 8)],
    "Cold": [17, 20, -21, 21, -16, 5, -22], "Warm": [28, 1, -22, -30, 20, 27, 26],
    "Salt": [-14, -21, -5, -5, -26, 15, 21], "Oxygen": [-18, 20, 12, 1, -10, 25, -22],
    "Light": [18, 1, -6, 28, 15, 20, 29]})
VARIABLES = ["Cold", "Warm", "Salt", "Oxygen", "Light"]
BASE = {"Variables": VARIABLES, "Observation labels": "Label", "Direction": "Rows and columns",
        "Scale columns": "None", "Scale rows": "None", "Linkage": "average", "Distance": "cityblock",
        "Graph output": "Heat map", "Distance matrix": True, "Cophenetic distances": True}
# Distances of four observations on which scipy.cluster.hierarchy.optimal_leaf_ordering is not minimal.
FOUR = np.array([[0, 1.59289013, 1.9528758, 1.29400451],
                 [1.59289013, 0, 1.06537021, 0.94123304],
                 [1.9528758, 1.06537021, 0, 0.83309023],
                 [1.29400451, 0.94123304, 0.83309023, 0]])


def every_order(tree):
    """All orders reachable by swapping the children of nodes: the exhaustive reference."""
    n = len(tree) + 1
    paths = {i: [(i,)] for i in range(n)}
    for index, (left, right, _, _) in enumerate(tree):
        a, b = paths[int(left)], paths[int(right)]
        paths[n + index] = [p for x in a for y in b for p in (x + y, y + x)]
    return paths[2 * n - 2]


def cheapest(tree, matrix):
    return min(order_cost(matrix, np.array(path)) for path in every_order(tree))


class OptimalOrderTests(unittest.TestCase):
    def check(self, data, method="average", metric="euclidean"):
        distances = pdist(data, metric=metric)
        tree = linkage(distances, method=method)
        matrix = squareform(distances)
        order, cost = optimal_order(tree, distances)
        self.assertEqual(sorted(order), list(range(len(data))))
        self.assertAlmostEqual(cost, order_cost(matrix, order), places=12)
        self.assertAlmostEqual(cost, cheapest(tree, matrix), places=9)
        # Swapping children only: same merges, heights and sizes, and the layout reads left to right.
        layout = layout_tree(tree, order)
        np.testing.assert_array_equal(np.sort(layout[:, :2], axis=1), np.sort(tree[:, :2], axis=1))
        np.testing.assert_array_equal(layout[:, 2:], tree[:, 2:])
        np.testing.assert_array_equal(default_order(layout), order)
        again, _ = optimal_order(tree, distances)
        np.testing.assert_array_equal(again, order)
        return order

    def test_matches_exhaustive_search_on_random_trees(self):
        rng = np.random.default_rng(5)
        recipes = [("average", m) for m in ("euclidean", "cityblock", "chebyshev", "cosine", "correlation")]
        recipes += [("complete", "cityblock"), ("single", "euclidean"), ("weighted", "chebyshev"),
                    ("ward", "euclidean"), ("centroid", "euclidean"), ("median", "euclidean")]
        for trial in range(240):
            method, metric = recipes[trial % len(recipes)]
            n = int(rng.integers(2, 9))
            data = rng.normal(size=(n, 4)) if trial % 2 else rng.integers(-3, 4, size=(n, 4)).astype(float)
            with self.subTest(trial=trial, method=method, metric=metric):
                if not np.isfinite(pdist(data, metric=metric)).all():
                    continue
                self.check(data, method, metric)

    def test_ties_repeated_rows_and_two_leaves(self):
        self.check(np.array([[0.], [0.], [0.], [1.]]), "single", "cityblock")
        self.check(np.array([[1., 2.], [1., 2.], [5., 5.]]))
        self.check(np.array([[0., 0.], [1., 1.]]))
        np.testing.assert_array_equal(self.check(np.array([[0., 0.], [3., 4.]])), [0, 1])
        equal = np.array([[2., 2.]] * 5)
        tree = linkage(pdist(equal), "average")
        np.testing.assert_array_equal(optimal_order(tree, pdist(equal))[0], default_order(tree))  # all orders tie

    def test_a_tree_where_scipy_is_not_minimal(self):
        distances = squareform(FOUR)
        tree = linkage(distances, "average")
        order, cost = optimal_order(tree, distances)
        self.assertAlmostEqual(cost, 1.29400451 + 0.83309023 + 1.06537021, places=9)
        self.assertAlmostEqual(cost, cheapest(tree, FOUR), places=9)
        scipy_cost = order_cost(FOUR, leaves_list(optimal_leaf_ordering(tree, distances)))
        self.assertGreaterEqual(scipy_cost, cost - 1e-12)  # scipy 1.18 gives 3.727 here; never below the minimum

    def test_an_optimal_default_is_left_alone_and_scale_does_not_matter(self):
        data = np.array([[0.], [1.], [3.], [7.], [8.], [12.]])
        distances = pdist(data)
        tree = layout_tree(linkage(distances, "average"), optimal_order(linkage(distances, "average"), distances)[0])
        for scale in (1e-300, 1., 1e150):
            order, _ = optimal_order(tree, distances * scale)
            np.testing.assert_array_equal(order, default_order(tree))

    def test_cancellation_stops_between_blocks(self):
        rng = np.random.default_rng(1)
        data = rng.normal(size=(60, 3))
        distances = pdist(data)
        tree = linkage(distances, "average")
        flag = threading.Event()
        flag.set()
        with self.assertRaises(LeafOrderCancelled):
            optimal_order(tree, distances, cancel=flag)

        class Trips:
            calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls > 20

        trips = Trips()
        with self.assertRaises(LeafOrderCancelled):
            optimal_order(tree, distances, cancel=trips)
        self.assertGreater(trips.calls, 20)
        self.assertEqual(len(optimal_order(tree, distances, cancel=threading.Event())[0]), 60)

    def test_one_hundred_leaves_are_exact_enough_to_beat_every_greedy_pass(self):
        rng = np.random.default_rng(9)
        data = rng.normal(size=(100, 6))
        distances = pdist(data)
        tree = linkage(distances, "average")
        matrix = squareform(distances)
        _, cost = optimal_order(tree, distances)
        self.assertLess(cost, order_cost(matrix, default_order(tree)))
        scipy_cost = order_cost(matrix, leaves_list(optimal_leaf_ordering(tree, distances)))
        self.assertLessEqual(cost, scipy_cost + 1e-9)


class LeafOrderSheetTests(unittest.TestCase):
    def run_method(self, frame=PROFILES, **options):
        return analyse("Hierarchical clustering", frame, {**BASE, **options})

    def test_default_and_missing_key_keep_every_sheet_and_the_figure(self):
        missing, default = self.run_method(), self.run_method(**{"Leaf ordering": "Default"})
        self.assertEqual(list(missing.tables), list(default.tables))
        for key in missing.tables:
            pd.testing.assert_frame_equal(missing.tables[key], default.tables[key])
        self.assertFalse([key for key in missing.tables if "leaf order" in key.lower()])
        before = describe_hierarchical_artists(missing.figure)
        after = describe_hierarchical_artists(default.figure)
        for key in ("row", "column"):
            self.assertEqual(before[key]["leaf_order"], after[key]["leaf_order"])

    def test_optimal_sheets_costs_and_invariants(self):
        base, result = self.run_method(), self.run_method(**{"Leaf ordering": "Optimal"})
        for axis, original, best in (("Row", 559., 520.), ("Column", 519., 492.)):
            report = result.tables[f"{axis} leaf order"]
            self.assertEqual(list(report.columns), ["Position", "Label", "Input index", "Distance from previous"])
            self.assertEqual(report["Position"].tolist(), list(range(1, len(report) + 1)))
            self.assertTrue(np.isnan(report["Distance from previous"].iloc[0]))
            self.assertAlmostEqual(report["Distance from previous"].iloc[1:].sum(), best)
            labels = PROFILES["Label"].tolist() if axis == "Row" else VARIABLES
            self.assertEqual([labels[i - 1] for i in report["Input index"]], report["Label"].tolist())
            costs = result.tables["Leaf order costs"].set_index("Axis").loc[axis]
            self.assertEqual((costs["Original cost"], costs["Final cost"], costs["Leaves"]),
                             (original, best, len(report)))
            for key in base.tables:
                if key.startswith(axis + " "):
                    pd.testing.assert_frame_equal(base.tables[key], result.tables[key])  # merges, assignments, matrices
        self.assertEqual(set(result.tables) - set(base.tables),
                         {"Row leaf order", "Column leaf order", "Leaf order costs"})

    def test_a_single_axis_still_names_its_sheet_by_axis(self):
        rows = self.run_method(**{"Leaf ordering": "Optimal", "Direction": "Rows"})
        columns = self.run_method(**{"Leaf ordering": "Optimal", "Direction": "Columns"})
        self.assertIn("Row leaf order", rows.tables)
        self.assertNotIn("Column leaf order", rows.tables)
        self.assertIn("Column leaf order", columns.tables)
        self.assertEqual(rows.tables["Leaf order costs"]["Axis"].tolist(), ["Row"])

    def test_the_figure_the_linked_graphs_and_the_cells_follow_the_report(self):
        result = self.run_method(**{"Leaf ordering": "Optimal"})
        meta = describe_hierarchical_artists(result.figure)
        for axis, key in (("Row", "row"), ("Column", "column")):
            report = result.tables[f"{axis} leaf order"]
            self.assertEqual([i + 1 for i in meta[key]["leaf_order"]], report["Input index"].tolist())
        scaled = PROFILES[VARIABLES].to_numpy(float)
        rows, cols = meta["row"]["leaf_order"], meta["column"]["leaf_order"]
        np.testing.assert_array_equal(np.asarray(meta["heatmap"]["image"].get_array()), scaled[np.ix_(rows, cols)])
        # A linked graph restyles or turns the dendrogram without another fit.
        for output, orientation in (("Dendrogram", "Vertical"), ("Dendrogram", "Horizontal"), ("Heat map", "Vertical")):
            frame = result.tables["Row Merges"]
            frame.attrs.update(result_context_of(result, "Row Merges"))
            linked = hierarchy_graph(frame, {"Graph output": output, "Dendrogram orientation": orientation})
            linked_meta = describe_hierarchical_artists(linked.figure)
            self.assertEqual(linked_meta["row"]["leaf_order"], meta["row"]["leaf_order"])

    def test_cluster_assignments_keep_their_numbers(self):
        for options in ({"Row cut": "Count", "Clusters": 3}, {"Row cut": "Cut height", "Row cut height": 200.}):
            base = self.run_method(**options)
            result = self.run_method(**options, **{"Leaf ordering": "Optimal"})
            pd.testing.assert_frame_equal(base.tables["Row Assignments"], result.tables["Row Assignments"])

    def test_scale_metric_and_exclusions(self):
        frame = PROFILES.copy()
        frame.loc[2, "Salt"] = np.nan  # an excluded observation leaves the leaves, the input index stays 1..6
        for options in ({"Scale columns": "Standardize", "Scale rows": "Center", "Distance": "euclidean"},
                        {"Distance": "cosine"}, {"Distance": "correlation", "Linkage": "complete"}):
            with self.subTest(options):
                result = self.run_method(frame, **{"Leaf ordering": "Optimal", **options})
                report = result.tables["Row leaf order"]
                self.assertEqual(len(report), 6)
                self.assertNotIn("Sample 3", report["Label"].tolist())
                self.assertEqual(sorted(report["Input index"]), list(range(1, 7)))
                costs = result.tables["Leaf order costs"].set_index("Axis").loc["Row"]
                self.assertLessEqual(costs["Final cost"], costs["Original cost"] + 1e-9)

    def test_duplicate_and_unusual_labels_are_never_used_as_identity(self):
        frame = PROFILES.copy()
        frame["Label"] = ["=A1", "dup", "dup", "a|b", "'quoted'", "dup", "[x]"]
        frame.loc[1, VARIABLES] = frame.loc[2, VARIABLES].to_numpy()  # two identical observations
        result = self.run_method(frame, **{"Leaf ordering": "Optimal", "Direction": "Rows"})
        report = result.tables["Row leaf order"]
        self.assertEqual(sorted(report["Input index"]), list(range(1, 8)))
        self.assertEqual(report["Label"].tolist(), [frame["Label"][i - 1] for i in report["Input index"]])
        self.assertEqual(sorted(report["Label"]), sorted(frame["Label"]))

    def test_two_observations_and_unknown_choice(self):
        two = PROFILES.iloc[:2]
        result = self.run_method(two, **{"Leaf ordering": "Optimal", "Direction": "Rows"})
        self.assertEqual(result.tables["Row leaf order"]["Input index"].tolist(), [1, 2])
        with self.assertRaises(FieldError) as raised:
            self.run_method(**{"Leaf ordering": "Best"})
        self.assertEqual(raised.exception.field, "Leaf ordering")

    def test_size_limit_is_checked_before_the_ordering_allocates(self):
        with mock.patch.object(leaf_order, "MAX_LEAVES", 5), \
                mock.patch.object(leaf_order, "optimal_order", side_effect=AssertionError("allocated")):
            with self.assertRaises(FieldError) as raised:
                self.run_method(**{"Leaf ordering": "Optimal", "Direction": "Rows"})
            self.assertEqual(raised.exception.field, "Leaf ordering")
            self.assertIn("limited to 5 leaves", str(raised.exception))
            self.run_method(**{"Leaf ordering": "Default", "Direction": "Rows"})  # Default is never limited

    def test_a_long_dendrogram_keeps_every_leaf_caption_in_the_registered_metadata(self):
        # Above 55 leaves the axis shows every n-th caption; the figure metadata must still name all the leaves
        # (the base release raised IndexError here, with the Default order too).
        rows = pd.DataFrame(np.random.default_rng(3).normal(size=(130, 4)), columns=list("ABCD"))
        rows.insert(0, "Label", [f"Row {i}" for i in range(130)])
        recipe = {"Variables": list("ABCD"), "Observation labels": "Label", "Direction": "Rows",
                  "Graph output": "Dendrogram"}
        for ordering in ("Default", "Optimal"):
            for orientation in ("Vertical", "Horizontal"):
                with self.subTest(ordering=ordering, orientation=orientation):
                    result = analyse("Hierarchical clustering", rows,
                                     {**recipe, "Leaf ordering": ordering, "Dendrogram orientation": orientation})
                    order = describe_hierarchical_artists(result.figure)["row"]["leaf_order"]
                    self.assertEqual(sorted(order), list(range(130)))
                    registered = _meta(result.figure)["components"]["row"]["leaf_labels"]
                    self.assertEqual(list(registered), [f"Row {i}" for i in order])

    def test_a_cancelled_calculation_returns_nothing(self):
        flag = threading.Event()
        flag.set()
        with self.assertRaises(LeafOrderCancelled):
            analyse("Hierarchical clustering", PROFILES, {**BASE, "Leaf ordering": "Optimal"}, cancel=flag)
        self.assertIsInstance(analyse("Hierarchical clustering", PROFILES, {**BASE, "Leaf ordering": "Optimal"},
                                      cancel=threading.Event()), Result)


def result_context_of(result, table):
    from analisi.analysis_chain import RESULT_CONTEXT
    return {RESULT_CONTEXT: result.table_contexts[table]}


if __name__ == "__main__":
    unittest.main()
