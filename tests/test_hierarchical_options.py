import unittest

import numpy as np
import pandas as pd

from analisi import hierarchical


class HierarchicalOptionsTests(unittest.TestCase):
    def test_legacy_group_count_and_sample_standardization(self):
        frame = pd.DataFrame({"x": [0, 0, 3, 3], "y": [0, 1, 0, 1]})
        raw = hierarchical(frame, ["x", "y"], 2)
        self.assertEqual(raw.labels.tolist(), [1, 1, 2, 2])
        np.testing.assert_allclose(raw.tree[:, 2], [1, 1, (3 + np.sqrt(10)) / 2])

        fit = hierarchical(frame, ["x", "y"], 2, True, "average", "euclidean")
        expected = [[-1, -1], [-1, 1], [1, -1], [1, 1]]
        np.testing.assert_allclose(fit.scaled, np.sqrt(.75) * np.asarray(expected))
        self.assertEqual(fit.labels.nunique(), 2)

        override = hierarchical(frame, ["x", "y"], 2, True, column_scale="none")
        np.testing.assert_array_equal(override.tree, raw.tree)

    def test_column_standardization_precedes_row_centering(self):
        frame = pd.DataFrame({"x": [0, 1, 2, np.nan], "y": [10, 30, 20, 1e9]},
                             index=["r0", "r1", "r2", "missing"])
        fit = hierarchical(frame, ["x", "y"], None, column_scale="standardize",
                           row_scale="center")
        self.assertIsNone(fit.labels)
        self.assertEqual(fit.scaled.index.tolist(), ["r0", "r1", "r2"])
        np.testing.assert_allclose(fit.scaled, [[0, 0], [-.5, .5], [.5, -.5]])
        np.testing.assert_allclose(fit.distances, np.sqrt(.5) * np.array([1, 1, 2]))

    def test_column_clustering_transposes_after_scaling(self):
        frame = pd.DataFrame({"x": [1, 3, 5], "y": [2, 6, 10], "z": [7, 3, 2]},
                             index=["a", "b", "c"])
        fit = hierarchical(frame, ["z", "x", "y"], 2, axis="columns", column_scale="center")
        pd.testing.assert_frame_equal(fit.data, frame[["z", "x", "y"]].astype(float).T)
        self.assertEqual(fit.scaled.index.tolist(), ["a", "b", "c"])
        self.assertEqual(fit.scaled.columns.tolist(), ["z", "x", "y"])
        np.testing.assert_allclose(fit.scaled, [[3, -2, -4], [-1, 0, 0], [-2, 2, 4]])
        np.testing.assert_allclose(fit.distances, [np.sqrt(42), np.sqrt(86), np.sqrt(8)])
        self.assertEqual(fit.labels.index.tolist(), ["z", "x", "y"])
        self.assertEqual(fit.labels.tolist(), [1, 2, 2])

    def test_cut_height_excludes_equal_merges_and_numbers_groups_by_input_order(self):
        frame = pd.DataFrame({"x": [30, 0, 31, 1]})
        exact = hierarchical(frame, ["x"], None, cut_height=1)
        self.assertEqual(exact.labels.tolist(), [1, 2, 3, 4])
        above = hierarchical(frame, ["x"], None, cut_height=np.nextafter(1., np.inf))
        self.assertEqual(above.labels.tolist(), [1, 2, 1, 2])

    def test_identical_rows_have_valid_zero_distances(self):
        frame = pd.DataFrame({"x": [1, 1, 1]})
        zero = hierarchical(frame, ["x"], None, cut_height=0)
        np.testing.assert_array_equal(zero.distances, [0, 0, 0])
        self.assertEqual(zero.labels.tolist(), [1, 2, 3])
        self.assertEqual(hierarchical(frame, ["x"], None, cut_height=.1).labels.tolist(), [1, 1, 1])

    def test_group_count_handles_an_inverted_centroid_merge(self):
        frame = pd.DataFrame({"x": [0, 2, 1], "y": [0, 0, 1.8]})
        fit = hierarchical(frame, ["x", "y"], 2, linkage="centroid")
        np.testing.assert_allclose(fit.tree[:, 2], [2, 1.8])
        self.assertEqual(fit.labels.tolist(), [1, 1, 2])

    def test_pearson_distance_matches_one_minus_correlation(self):
        frame = pd.DataFrame([[1, 2, 3], [2, 4, 6], [3, 2, 1]], columns=list("xyz"))
        fit = hierarchical(frame, list(frame), 2, metric="correlation", row_scale="standardize")
        np.testing.assert_allclose(fit.distances, [0, 2, 2], atol=1e-15)
        np.testing.assert_allclose(fit.scaled, [[-1, 0, 1], [-1, 0, 1], [1, 0, -1]])
        self.assertEqual(fit.labels.tolist(), [1, 1, 2])

    def test_undefined_distances_and_standardization_raise(self):
        frame = pd.DataFrame([[.1, .1, .1], [0, 0, 0], [1, 2, 3]], columns=list("xyz"))
        for options, message in (({"metric": "correlation"}, "constant"),
                                 ({"metric": "cosine"}, "zero"),
                                 ({"row_scale": "standardize"}, "constant"),
                                 ({"linkage": "ward", "metric": "correlation"}, "Euclidean")):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                hierarchical(frame, list(frame), 2, **options)

    def test_centered_constant_row_has_zero_cosine_norm(self):
        frame = pd.DataFrame([[.1, .1, .1], [1, 2, 3], [2, 3, 1]], columns=list("xyz"))
        with self.assertRaisesRegex(ValueError, "zero"):
            hierarchical(frame, list(frame), 2, metric="cosine", row_scale="center")

    def test_invalid_counts_heights_axes_and_scaling_raise(self):
        frame = pd.DataFrame({"x": [1, 2, 3], "y": [7, 8, 9]})
        for count, options in ((0, {}), (3, {"axis": "columns"}), (1.5, {}), (True, {}),
                               (None, {"cut_height": np.inf}), (None, {"cut_height": -.01}),
                               (2, {"cut_height": .1}), (2, {"axis": "both"}),
                               (2, {"column_scale": "range"})):
            with self.subTest(count=count, options=options), self.assertRaises(ValueError):
                hierarchical(frame, list(frame), count, **options)

    def test_finite_input_and_observation_bound_for_each_axis(self):
        frame = pd.DataFrame({"x": [1, np.inf, 3]})
        with self.assertRaisesRegex(ValueError, "infinite"):
            hierarchical(frame, ["x"], None)

        many = pd.DataFrame(np.arange(3001.))
        for data, axis in ((many, "rows"), (many.T, "columns")):
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, "3000"):
                hierarchical(data, list(data), None, axis=axis)
