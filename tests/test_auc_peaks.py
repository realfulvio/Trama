import unittest

import numpy as np
import pandas as pd

from analisi import auc_peaks as ap
from analisi.additional import EXTRA_METHODS, extra_analysis
from analisi.exploration import area_under_curve
from analisi.processing import FieldError


def run(x, y, baseline=0, mode=ap.BOTH, height=10, width=0):
    frame = pd.DataFrame({"x": x, "y": y})
    return ap.area_peaks(frame, "x", "y", baseline, mode, height, width)


class AreaPeaksTest(unittest.TestCase):
    def test_sign_change_at_shared_point(self):
        totals, peaks, *_ = run([0, 1, 2, 3, 4], [0, 2, 0, -2, 0])
        self.assertEqual(list(peaks["Side"]), ["Above", "Below"])
        self.assertEqual(list(peaks["Start X"]), [0, 2])
        self.assertEqual(list(peaks["End X"]), [2, 4])
        self.assertEqual(list(peaks["Height"]), [2, 2])
        self.assertEqual(list(peaks["Duration"]), [2, 2])
        self.assertEqual(list(peaks["Area"]), [2, 2])
        self.assertEqual(list(peaks["Signed area"]), [2, -2])
        self.assertEqual(list(peaks["Truncated"]), ["No", "No"])
        self.assertEqual((totals["Net area"], totals["Total area (geometric)"], totals["Retained peak area"]), (0, 4, 4))
        np.testing.assert_allclose(peaks["Fraction of retained area (%)"], [50, 50])

    def test_above_only_and_minimum_width(self):
        totals, peaks, *_ = run([0, 1, 2, 3, 4], [0, 2, 0, -2, 0], mode=ap.ABOVE)
        self.assertEqual((len(peaks), totals["Retained peak area"], totals["Total area (geometric)"]), (1, 2, 4))
        totals, peaks, *_ = run([0, 1, 2, 3, 4], [0, 2, 0, -2, 0], width=2)
        self.assertEqual(len(peaks), 2)
        totals, peaks, *_ = run([0, 1, 2, 3, 4], [0, 2, 0, -2, 0], width=2.01)
        self.assertTrue(peaks.empty)
        self.assertEqual((totals["Total area (geometric)"], totals["Retained peak area"], totals["Net area"]), (4, 0, 0))

    def test_crossing_is_interpolated_and_both_edges_truncated(self):
        for y, baseline in (([1, -3], 0), ([11, 7], 10)):
            totals, peaks, *_ = run([0, 2], y, baseline)
            np.testing.assert_allclose(peaks["End X"][0], .5)
            np.testing.assert_allclose(peaks["Area"], [.25, 2.25])
            np.testing.assert_allclose(peaks["Signed area"], [.25, -2.25])
            self.assertEqual(list(peaks["Truncated"]), ["Start", "End"])
            self.assertAlmostEqual(totals["Net area"], -2)
            self.assertEqual(totals["Total area (geometric)"], 2.5)

    def test_height_threshold_accepts_equality(self):
        x, y = [0, 1, 2, 3, 4], [0, 2, 0, 1, 0]
        self.assertEqual(list(run(x, y, height=60)[1]["Peak X"]), [1])
        self.assertEqual(list(run(x, y, height=50)[1]["Peak X"]), [1, 3])
        totals = run(x, y, height=60)[0]
        self.assertEqual((totals["Area above baseline"], totals["Retained peak area"]), (3.0, 2.0))

    def test_baseline_plateau_separates_without_extra_peak(self):
        _, peaks, *_ = run([0, 1, 2, 3, 4, 5, 6], [0, 2, 0, 0, 0, 1, 0])
        self.assertEqual(list(peaks["Peak X"]), [1, 5])
        # A single touching point splits a same-sign run into two regions.
        _, peaks, *_ = run([0, 1, 2, 3, 4], [1, 2, 0, 2, 1])
        self.assertEqual(len(peaks), 2)

    def test_series_on_baseline_has_no_peaks(self):
        totals, peaks, *_ = run([0, 1, 2], [3, 3, 3], baseline=3)
        self.assertEqual((totals["Total area (geometric)"], totals["Retained peak area"], len(peaks)), (0, 0, 0))
        self.assertEqual(list(peaks.columns), ap.COLUMNS)

    def test_fractions_are_blank_without_retained_area(self):
        self.assertTrue(run([0, 1, 2], [0, 0, 0])[1].empty)
        table = ap.peak_table([])
        self.assertTrue(table.empty)

    def test_pairs_and_duplicates_follow_current_method(self):
        frame = pd.DataFrame({"x": [3, 0, 1, 2, 4], "y": [0, 0, 2, np.nan, 0]})
        totals, peaks, data, *_ = ap.area_peaks(frame, "x", "y", 0, ap.BOTH, 10, 0)
        self.assertEqual(list(data["x"]), [0, 1, 3, 4])
        np.testing.assert_allclose(peaks["Area"], [3.0])  # 0->2 over 1, then 2->0 over 2
        self.assertEqual(totals["N"], 4)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            run([0, 1, 1], [0, 1, 2])

    def test_totals_match_the_existing_calculation(self):
        rng = np.random.default_rng(3)
        frame = pd.DataFrame({"x": np.arange(40.), "y": rng.normal(size=40).cumsum()})
        old, _ = area_under_curve(frame, "x", "y", .5)
        totals, peaks, _, found, _ = ap.area_peaks(frame, "x", "y", .5, ap.BOTH, 0, 0)
        for key in old:
            self.assertEqual(totals[key], old[key])
        np.testing.assert_allclose(sum(r["sign"] * r["area"] for r in found), old["Net area"])
        np.testing.assert_allclose(peaks["Area"].sum(), old["Area above baseline"] + old["Area below baseline"])

    def test_off_returns_the_previous_totals_sheet(self):
        frame = pd.DataFrame({"x": [0, 1, 2], "y": [1, 3, 1]})
        old = {"Baseline": 0, "X": "x", "Y": "y"}
        result = extra_analysis("Area under curve", frame, old)
        self.assertEqual(list(result.tables), ["Area under curve", "Data"])
        self.assertEqual(list(result.tables["Area under curve"].index),
                         ["Baseline", "Area above baseline", "Area below baseline", "Net area", "X min", "X max", "N"])
        self.assertIsNotNone(result.figure)

    def test_new_recipe_lists_peaks_and_options(self):
        self.assertEqual(EXTRA_METHODS["Area under curve"][ap.PEAKS], ap.MODES)
        self.assertEqual(EXTRA_METHODS["Area under curve"][ap.HEIGHT], 10.0)
        frame = pd.DataFrame({"x": [0, 1, 2, 3, 4], "y": [0, 2, 0, 1, 0]})
        options = {"X": "x", "Y": "y", "Baseline": 0.0, ap.PEAKS: ap.ABOVE, ap.HEIGHT: 60.0, ap.WIDTH: 0.0}
        result = extra_analysis("Area under curve", frame, options)
        self.assertEqual(list(result.tables), ["Area under curve", "Peaks", "Data"])
        self.assertEqual(len(result.tables["Peaks"]), 1)
        labels = [t.get_text() for t in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(labels, ["Retained above", "Excluded"])
        self.assertEqual([line.get_linestyle() for line in result.figure.axes[0].lines].count("--"), 1)

    def test_many_peaks_share_collections_without_joining_regions(self):
        x = np.arange(201)
        frame = pd.DataFrame({"x": x, "y": np.where(x % 2, np.where(x % 4 == 1, 2, -2), 0)})
        result = extra_analysis("Area under curve", frame, {"X": "x", "Y": "y", "Baseline": 0., ap.PEAKS: ap.BOTH})
        self.assertEqual(len(result.tables["Peaks"]), 100)
        collections = result.figure.axes[0].collections
        self.assertEqual(len(collections), 2)
        self.assertEqual([len(collection.get_paths()) for collection in collections], [50, 50])

    def test_option_validation_names_the_field(self):
        for options, field in (({ap.PEAKS: "Maybe"}, ap.PEAKS), ({ap.PEAKS: ap.BOTH, ap.HEIGHT: 120}, ap.HEIGHT),
                               ({ap.PEAKS: ap.BOTH, ap.HEIGHT: "x"}, ap.HEIGHT),
                               ({ap.PEAKS: ap.BOTH, ap.WIDTH: -1}, ap.WIDTH)):
            with self.assertRaises(FieldError) as raised:
                ap.check_options(options)
            self.assertEqual(raised.exception.field, field)
        self.assertEqual(ap.check_options({ap.PEAKS: ap.BOTH}), (ap.BOTH, 10.0, 0.0))
        self.assertEqual(ap.check_options({})[0], ap.OFF)


if __name__ == "__main__":
    unittest.main()
