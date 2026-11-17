import unittest

import numpy as np
import pandas as pd

from analisi.repeated_input import curve_input, mixed_input


class CurveInputTests(unittest.TestCase):
    def test_wide_replicates_merge_by_series_and_convert_log_dose(self):
        frame = pd.DataFrame({"dose": [-7, -6], "A [1]": [1, 2], "A [2]": [3, np.nan], "B": [5, 6]})
        data, _, _, _ = curve_input(frame, {"Input format": "Wide XY", "X": "dose",
                                            "Y columns": ["A [1]", "A [2]", "B"],
                                            "X values": "Log10 concentrations"})
        self.assertEqual(data["Series"].tolist(), ["A", "A", "A", "A", "B", "B"])
        np.testing.assert_allclose(data["X"], np.tile([1e-7, 1e-6], 3))
        self.assertTrue(pd.isna(data["Response"].iloc[3]))

    def test_fit_means_keeps_one_row_per_x_and_series(self):
        frame = pd.DataFrame({"x": [1, 2], "A [1]": [1, 2], "A [2]": [3, np.nan],
                              "B": [5, 6], "sd": [2., 3.]})
        data, _, _, _ = curve_input(frame, {"Input format": "Wide XY", "X": "x",
                                            "Y columns": ["A [1]", "A [2]", "B"],
                                            "Replicates": "Means at each X",
                                            "Weighting": "Inverse variance (column)", "SD column": "sd"})
        self.assertEqual(data["Series"].tolist(), ["A", "A", "B", "B"])
        np.testing.assert_allclose(data["Response"], [2, 2, 5, 6])
        np.testing.assert_allclose(data["SD"], [np.sqrt(2), 3, 2, 3])

    def test_weighted_mean_rejects_missing_sd(self):
        frame = pd.DataFrame({"x": [1, 2], "y": [1, 2], "g": ["a", "b"], "sd": [np.nan, 2.]})
        with self.assertRaisesRegex(ValueError, "positive"):
            curve_input(frame, {"X": "x", "Y": "y", "Series": "g", "SD column": "sd",
                                "Weighting": "Inverse variance (column)", "Replicates": "Means at each X"})


class MixedInputTests(unittest.TestCase):
    def test_wide_preserves_partial_subject_and_order(self):
        frame = pd.DataFrame({"baseline": [5, 9], "followup": [7, np.nan], "arm": ["a", "b"]})
        result, response, within, between, subject = mixed_input(
            frame, {"Input format": "Wide repeated measures",
                    "Measurement columns": ["baseline", "followup"], "Between factors": ["arm"]})
        self.assertEqual(len(result), 4)
        self.assertEqual(within, ["Condition"])
        self.assertEqual(between, ["arm"])
        self.assertEqual(result[subject].tolist(), [1, 2, 1, 2])
        self.assertEqual(result[within[0]].tolist(), ["baseline", "baseline", "followup", "followup"])
        self.assertTrue(pd.isna(result[response].iloc[3]))

    def test_grouped_columns_match_subjects_within_each_row(self):
        frame = pd.DataFrame({"Strain": ["Wild", "Tame"], "Before [1]": [5, 9], "Before [2]": [3, 7],
                              "After [1]": [7, np.nan], "After [2]": [4, 8]})
        result, response, within, between, subject = mixed_input(
            frame, {"Input format": "Grouped replicate table", "Row labels": "Strain",
                    "Measurement columns": frame.columns[1:].tolist(), "Repeat across": "Columns only"})
        self.assertEqual(within, ["Column series"])
        self.assertEqual(between, ["Strain"])
        self.assertEqual(result[subject].nunique(), 4)
        self.assertEqual(result[subject].iloc[0], result[subject].iloc[4])
        self.assertNotEqual(result[subject].iloc[0], result[subject].iloc[1])
        self.assertTrue(pd.isna(result[response].iloc[5]))

    def test_grouped_both_factors_share_subject_replicate(self):
        frame = pd.DataFrame({"time": ["T1", "T2"], "Drug [1]": [2, 3], "Placebo [1]": [1, 1],
                              "Drug [2]": [4, 5], "Placebo [2]": [2, 2]})
        result, _, within, between, subject = mixed_input(
            frame, {"Input format": "Grouped replicate table", "Row labels": "time",
                    "Measurement columns": frame.columns[1:].tolist(), "Repeat across": "Rows and columns"})
        self.assertEqual(within, ["time", "Column series"])
        self.assertEqual(between, [])
        self.assertEqual(result.groupby(subject).size().tolist(), [4, 4])

    def test_restart_ids_resolves_nested_identifiers_without_ambiguity(self):
        frame = pd.DataFrame({"response": [3, 4, 5, 6], "subject": [1] * 4,
                              "time": ["pre", "post"] * 2, "arm": ["a", "a", "b", "b"]})
        result, _, _, _, subject = mixed_input(
            frame, {"Y": "response", "Subject": "subject", "Within factors": ["time"],
                    "Between factors": ["arm"], "Subject IDs": "Restart within between groups"})
        self.assertEqual(result[subject].nunique(), 2)
        self.assertEqual(result[subject].iloc[0], result[subject].iloc[1])
        self.assertNotEqual(result[subject].iloc[0], result[subject].iloc[2])
