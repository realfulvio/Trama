"""MacQueen uses updated centroids within each pass through the worksheet."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import advanced, kmeans_options as options
from analisi.field_error import FieldError
from analisi.kmeans_reports import CENTROIDS
from analisi.stats import kmeans
from analisi.workbench import analyse


class MacQueenTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"x": [0., 1., 2., 3., 4., 6.]})
        self.fit_options = {"Variables": ["x"], "Clusters": 2, "Standardize": False, "Seed": 42,
                            options.ALGORITHM: "MacQueen", options.INITIAL_ROWS: "1, 2"}

    def test_sequential_moves_use_new_centroid_in_same_pass(self):
        # A batch reassignment initially moves only 1; the sequential pass moves 1 and 2.
        result = analyse(options.CLUSTERING, self.frame, {**self.fit_options, CENTROIDS: True})
        np.testing.assert_array_equal(result.tables["Assignments"]["Cluster"], [1, 1, 1, 2, 2, 2])
        np.testing.assert_allclose(result.tables["Centers (fitting scale)"]["x"], [1., 13 / 3])
        np.testing.assert_array_equal(result.tables["Initial centroids"]["Initial center"], [0., 1.])
        self.assertAlmostEqual(result.tables["Fit"].loc["Within-cluster SS", "Value"], 20 / 3)
        self.assertEqual(result.tables["Fit"].loc[options.ALGORITHM, "Value"], "MacQueen")

    def test_tiny_iteration_limit_reports_the_editable_field(self):
        with self.assertRaises(FieldError) as failure:
            analyse(options.CLUSTERING, self.frame, {**self.fit_options, "MacQueen iteration limit": 1})
        self.assertEqual(failure.exception.field, "MacQueen iteration limit")
        self.assertIn("MacQueen", str(failure.exception))

    def test_seeded_scan_runs_macqueen_on_gap_references_too(self):
        settings = {**self.fit_options, "Seed": 12, "Criterion": "Gap", "Maximum k": 2, "Gap simulations": 5}
        with patch.object(advanced, "kmeans", wraps=advanced.kmeans) as call:
            first = analyse(options.SELECTION, self.frame, settings)
        second = analyse(options.SELECTION, self.frame, settings)
        self.assertEqual(call.call_count, 12)
        self.assertTrue(all(request.kwargs["algorithm"] == "macqueen" for request in call.call_args_list))
        pd.testing.assert_frame_equal(first.tables["Model metrics"], second.tables["Model metrics"])
        self.assertTrue(np.isfinite(first.tables["Model metrics"]["Gap"]).all())

    def test_translated_and_singleton_fits_preserve_partition(self):
        data = self.frame.copy()
        base = kmeans(data, ["x"], 2, algorithm="macqueen", initial_rows=[0, 1])
        shifted = kmeans(data + 1e14, ["x"], 2, algorithm="macqueen", initial_rows=[0, 1])
        np.testing.assert_array_equal(base.labels, shifted.labels)
        self.assertEqual(base.inertia, shifted.inertia)
        singletons = kmeans(data, ["x"], len(data), algorithm="macqueen", initial_rows=range(5, -1, -1))
        np.testing.assert_array_equal(singletons.labels, [6, 5, 4, 3, 2, 1])
        self.assertEqual(singletons.inertia, 0.)
