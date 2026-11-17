import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import analisi.outlier_screening as screening
from analisi.operations import grubbs as legacy_grubbs
from analisi.outlier_screening import (ALPHA, CONSTANT, INSUFFICIENT, ITERATIVE, NO_SCALE, NOT_CONVERGED, OUTLIERS,
                                       Q, ROUT, GRUBBS, check_options, rout, visibility)
from analisi.processing import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

FIXTURE = Path(__file__).parent / "data" / "outliers-screening.csv"
RSDR = 3.8287636363636364
INLIERS = [-2, -1.5, -1, -.5, 0, .5, 1, 1.5, 2.]


def run(frame, method=ROUT, **options):
    return analyse(OUTLIERS, frame, {"Variables": list(frame.columns), "Method": method, **options})


def rows(result, variable=None):
    table = result.tables["Outliers"]
    if variable is not None:
        table = table[table["Variable"] == variable]
    return table["Source row"].tolist()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(FIXTURE)

    def test_rout_flags_the_two_spikes_with_the_reference_scale(self):
        before = self.frame.copy(deep=True)
        result = run(self.frame, **{Q: 1.0})
        flags = result.tables["Outliers"]
        self.assertEqual(flags["Variable"].tolist()[:2], ["Spikes", "Spikes"])
        self.assertEqual(rows(result, "Spikes"), [1, 12])
        self.assertEqual(flags.loc[flags.Variable == "Spikes", "Value"].tolist(), [-60, 60])
        self.assertEqual(rows(result, "Clean"), [])
        summary = result.tables["Summary"].set_index("Variable")
        for name in ("Clean", "Spikes"):
            self.assertAlmostEqual(summary.loc[name, "RSDR"], RSDR, places=9)
            self.assertEqual(summary.loc[name, "Location"], 0)
            self.assertEqual(summary.loc[name, "Converged"], "Yes")
            self.assertEqual(summary.loc[name, "Candidates"], 3)
        self.assertEqual(summary.loc["Constant", "Status"], CONSTANT)
        self.assertEqual(summary.loc["Sparse", "Status"], INSUFFICIENT)
        self.assertEqual(summary.loc["Spikes", "Flagged"], 2)
        clean = result.tables["Processed data"]
        self.assertEqual(len(clean), len(self.frame))
        self.assertEqual(clean["Spikes"].isna().tolist(), [True] + [False] * 10 + [True])
        pd.testing.assert_series_equal(clean["Clean"], before["Clean"])
        pd.testing.assert_frame_equal(self.frame, before)

    def test_iterative_grubbs_reports_detection_order(self):
        result = run(self.frame[["Grubbs chain"]], ITERATIVE, **{ALPHA: .05})
        table = result.tables["Outliers"]
        self.assertEqual(table["Source row"].tolist(), [9, 8])
        self.assertEqual(table["Step"].tolist(), [1, 2])
        self.assertEqual(table["N"].tolist(), [9, 8])
        summary = result.tables["Summary"].iloc[0]
        self.assertEqual(summary["Alpha (each step)"], .05)
        self.assertEqual(result.tables["Processed data"]["Grubbs chain"].isna().sum(), 12 - 9 + 2)

    def test_single_grubbs_matches_the_legacy_test(self):
        for column in ("Grubbs chain", "Spikes", "Clean"):
            with self.subTest(column=column):
                old = legacy_grubbs(self.frame, column, .05)
                new = run(self.frame[[column]], GRUBBS, **{ALPHA: .05})
                summary = new.tables["Summary"].iloc[0]
                self.assertAlmostEqual(summary["Last G"], old["G"], places=12)
                self.assertAlmostEqual(summary["Last critical G"], old["Critical G"], places=12)
                self.assertEqual(summary["Flagged"], int(old["Flagged"]))
                if old["Flagged"]:
                    self.assertEqual(rows(new), [int(old["Candidate row"]) + 1])

    def test_iterative_needs_seven_values_and_single_three(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 90.]})
        self.assertEqual(run(frame, ITERATIVE).tables["Summary"]["Status"].iloc[0], INSUFFICIENT)
        self.assertEqual(run(frame[:2], GRUBBS).tables["Summary"]["Status"].iloc[0], INSUFFICIENT)
        self.assertEqual(run(frame[:3], GRUBBS).tables["Summary"]["Status"].iloc[0], "Tested")
        self.assertEqual(run(frame[:3], ROUT).tables["Summary"]["Status"].iloc[0], INSUFFICIENT)


class Rout(unittest.TestCase):
    def test_shift_and_positive_scale_keep_the_flags(self):
        frame = pd.read_csv(FIXTURE)[["Spikes", "Grubbs chain"]]
        base = run(frame)
        moved = run(frame * 3.5 + 1e6)
        self.assertEqual(rows(moved), rows(base))
        a, b = base.tables["Summary"], moved.tables["Summary"]
        np.testing.assert_allclose(b["RSDR"], a["RSDR"] * 3.5, rtol=1e-9)
        np.testing.assert_allclose(b["Location"], a["Location"] * 3.5 + 1e6, rtol=1e-12)
        np.testing.assert_allclose(moved.tables["Outliers"]["p (two-sided)"], base.tables["Outliers"]["p (two-sided)"],
                                   rtol=1e-6)

    def test_excluded_and_missing_cells_keep_row_identity_and_are_not_flagged(self):
        frame = pd.read_csv(FIXTURE)[["Spikes"]]
        masked = frame.copy()
        masked.loc[0, "Spikes"] = np.nan          # an excluded cell arrives masked
        result = run(masked)
        self.assertNotIn(1, rows(result))
        self.assertEqual(result.tables["Summary"]["N"].iloc[0], 11)
        processed = result.tables["Processed data"]["Spikes"]
        self.assertTrue(np.isnan(processed.iloc[0]))
        for row in rows(result):
            self.assertEqual(masked["Spikes"].iloc[row - 1], result.tables["Outliers"].set_index("Source row").loc[row, "Value"])

    def test_cap_limits_candidates_to_thirty_percent(self):
        values = np.r_[INLIERS, [100, 150, 200, 250]]
        _, flagged, _ = rout(values, 1)
        self.assertEqual(flagged, [10, 11, 12])
        try:
            screening.CAP_FRACTION = .5
            self.assertEqual(rout(values, 1)[1], [9, 10, 11, 12])
        finally:
            screening.CAP_FRACTION = .30

    def test_a_tie_block_crossing_the_cap_is_excluded_whole(self):
        self.assertEqual(rout(np.r_[INLIERS, [100] * 4], 1)[1], [])
        self.assertEqual(rout(np.r_[INLIERS, [200, 100, 100, 100]], 1)[1], [9])
        self.assertEqual(rout(np.r_[INLIERS, [-100, 100, 0, 0]], 1)[1], [9, 10])

    def test_duplicated_outliers_are_flagged_together(self):
        frame = pd.DataFrame({"v": INLIERS + [80, 80, 0.25]})
        self.assertEqual(rows(run(frame)), [10, 11])

    def test_zero_scale_with_variability_has_no_estimate(self):
        result = run(pd.DataFrame({"v": [5.] * 9 + [9.]}))
        summary = result.tables["Summary"].iloc[0]
        self.assertEqual(summary["Status"], NO_SCALE)
        self.assertTrue(np.isnan(summary["RSDR"]) and np.isnan(summary["Location"]))
        self.assertEqual(rows(result), [])

    def test_not_converged_flags_nothing(self):
        summary, flagged, _ = rout(np.array([1, 2, 3, 4, 5, 6, 30.]), 1, max_iterations=1)
        self.assertEqual((summary["Status"], summary["Converged"], flagged), (NOT_CONVERGED, "No", []))
        summary, flagged, _ = rout(np.array([1, 2, 3, 4, 5, 6, 30.]), 1)
        self.assertEqual(summary["Converged"], "Yes")
        self.assertLess(summary["Iterations"], 200)

    def test_rows_follow_source_order(self):
        frame = pd.DataFrame({"v": [300.] + INLIERS + [-120.]})
        result = run(frame)
        self.assertEqual(rows(result), [1, 11])


class Grubbs(unittest.TestCase):
    def test_tie_at_maximum_takes_first_row_and_is_reported(self):
        frame = pd.DataFrame({"v": list(np.linspace(-1, 1, 21)) + [-30, 30]})
        result = run(frame, ITERATIVE)
        self.assertEqual(rows(result), [22, 23])
        self.assertIn("equal maxima in rows 22, 23", result.tables["Summary"]["Note"].iloc[0])

    def test_stops_at_first_value_not_flagged(self):
        frame = pd.DataFrame({"v": [10, 11, 9, 10.5, 9.5, 10.2, 9.8, 14, 40.]})
        result = run(frame, ITERATIVE)
        table = result.tables["Outliers"]
        self.assertEqual(table["Step"].tolist(), list(range(1, len(table) + 1)))
        self.assertTrue((table["G"] > table["Critical G"]).all())
        self.assertLess(result.tables["Summary"]["Last G"].iloc[0], result.tables["Summary"]["Last critical G"].iloc[0])


class Validation(unittest.TestCase):
    frame = pd.DataFrame({"a": [1, 2, 3, 4, 5.], "b": ["1", "2", "x", "4", "5"]})

    def assert_field(self, field, **options):
        with self.assertRaises(FieldError) as raised:
            analyse(OUTLIERS, self.frame, {"Variables": ["a"], "Method": ROUT, **options})
        self.assertEqual(raised.exception.field, field)
        return str(raised.exception)

    def test_q_and_alpha_ranges(self):
        for bad in (0, 100, -1, float("nan"), "1", True):
            with self.subTest(q=bad):
                self.assert_field(Q, **{Q: bad})
        for bad in (0, 1, 1.5):
            with self.subTest(alpha=bad):
                self.assert_field(ALPHA, Method=GRUBBS, **{ALPHA: bad})
        # The unused threshold is not checked.
        analyse(OUTLIERS, self.frame, {"Variables": ["a"], "Method": ROUT, Q: 5, ALPHA: 7})
        self.assert_field("Method", Method="Dixon")

    def test_text_in_a_column_names_it(self):
        message = self.assert_field("Variables", Variables=["a", "b"])
        self.assertIn('"b"', message)
        self.assert_field("Variables", Variables=["a", "a"])
        self.assert_field("Variables", Variables=[])

    def test_infinite_values_are_rejected(self):
        frame = pd.DataFrame({"c": [1, 2, np.inf, 4, 5.]})
        with self.assertRaises(FieldError):
            analyse(OUTLIERS, frame, {"Variables": ["c"], "Method": ROUT})

    def test_visibility_and_catalog(self):
        self.assertEqual(visibility(ROUT), {Q: True, ALPHA: False})
        self.assertEqual(visibility(ITERATIVE), {Q: False, ALPHA: True})
        self.assertIn(OUTLIERS, GROUPS["Data Processing"])
        self.assertIn("Outlier test (Grubbs)", GROUPS["Data Processing"])
        self.assertEqual(METHODS[OUTLIERS][Q], 1.0)
        self.assertEqual(METHODS[OUTLIERS][ALPHA], .05)
        self.assertEqual(check_options(self.frame, {"Variables": ["a"], "Method": ROUT}), (["a"], ROUT, 1.0))

    def test_legacy_grubbs_recipe_keeps_its_sheet(self):
        frame = pd.read_csv(FIXTURE)
        result = analyse("Outlier test (Grubbs)", frame, {"Response": "Grubbs chain", "Alpha": .05})
        self.assertEqual(list(result.tables), ["Grubbs' test"])
        report = result.tables["Grubbs' test"]["Value"]
        self.assertEqual((report["Candidate row"], report["Flagged"]), ("8", True))


if __name__ == "__main__":
    unittest.main()
