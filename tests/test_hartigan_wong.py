"""Hartigan-Wong regressions with external reference fits and numeric edge cases."""
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi.hartigan_wong import fit_hartigan_wong
from analisi.stats import kmeans


DATA = Path(__file__).parent / "data"


class HartiganWongTests(unittest.TestCase):
    def test_wine_with_explicit_initial_centers_matches_r_stats(self):
        values = np.loadtxt(DATA / "wine.data", delimiter=",")[:, 1:]
        frame = pd.DataFrame(values)
        columns = list(frame.columns)
        oracle = json.loads((DATA / "hartigan_wong_oracle.json").read_text(encoding="utf-8"))
        for reference in oracle["cases"]:
            with self.subTest(k=len(reference["initial_rows"])):
                result = kmeans(frame, columns, len(reference["initial_rows"]), standardize=True,
                                algorithm="hartigan-wong", initial_rows=reference["initial_rows"])
                np.testing.assert_array_equal(result.labels, reference["labels"])
                np.testing.assert_allclose(result.centers, reference["centers"], rtol=1e-12, atol=1e-12)
                self.assertAlmostEqual(result.inertia, sum(reference["within_sum_squares"]), places=10)

    def test_seeded_hartigan_wong_is_reproducible_without_changing_lloyd(self):
        frame = pd.DataFrame({"value": [1., 2., 3., 6., 7., 8., 10., 11., 12.]})
        historical = kmeans(frame, ["value"], 3)
        explicit = kmeans(frame, ["value"], 3, algorithm="lloyd")
        pd.testing.assert_series_equal(historical.labels, explicit.labels)
        one = kmeans(frame, ["value"], 3, algorithm="hartigan-wong")
        two = kmeans(frame, ["value"], 3, algorithm="hartigan-wong")
        pd.testing.assert_series_equal(one.labels, two.labels)
        self.assertEqual(one.inertia, 6.0)

    def test_large_translation_preserves_partition_and_sum_of_squares(self):
        data = np.array([0., 1., 2., 12., 13., 14., 26., 27.])[:, None]
        fit = fit_hartigan_wong(data, [0, 3, 7])
        shifted = fit_hartigan_wong(data + 1e14, [0, 3, 7])
        np.testing.assert_array_equal(shifted.labels, fit.labels)
        np.testing.assert_array_equal(shifted.within, fit.within)
        np.testing.assert_allclose(shifted.centers - 1e14, fit.centers, atol=0.008, rtol=0)

    def test_duplicate_and_outside_initial_rows(self):
        data = np.array([1, 2, 1, 6])[:, None]
        with self.assertRaisesRegex(ValueError, "distinct"):
            fit_hartigan_wong(data, [0, 2])
        with self.assertRaisesRegex(ValueError, "outside"):
            fit_hartigan_wong(data, [-1, 1])
        with self.assertRaisesRegex(ValueError, "outside"):
            fit_hartigan_wong(data, [0, 4])

    def test_single_cluster_and_singletons(self):
        data = np.array([1., 2., 6.])[:, None]
        one = fit_hartigan_wong(data, [1])
        np.testing.assert_allclose(one.within, [14.])
        np.testing.assert_allclose(one.centers, [[3.]])
        all_clusters = fit_hartigan_wong(data, [2, 1, 0])
        np.testing.assert_array_equal(all_clusters.labels, [2, 1, 0])
        np.testing.assert_array_equal(all_clusters.within, [0., 0., 0.])
