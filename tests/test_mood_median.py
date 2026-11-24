"""Mood median test: SciPy cross-check, ties, Yates, worksheet recipe and large values."""
from math import isclose
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from scipy.stats import median_test as scipy_median_test

from analisi import mood_median as mood
from analisi._version import RELEASE_CHANNEL, VERSION
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, analyse

FIXTURE = Path(__file__).resolve().parent / "data" / "mood_median" / "mood.csv"


def fixture():
    frame = pd.read_csv(FIXTURE)
    samples = [[int(value) for value in frame[name].dropna()] for name in "ABC"]
    return frame, samples


def run(frame, columns=None, **options):
    recipe = {
        mood.VARIABLES: list(columns or "ABC"),
        mood.TIES: mood.BELOW,
        mood.YATES: False,
    }
    recipe.update(options)
    return analyse(mood.METHOD, frame, recipe)


class ContractTests(unittest.TestCase):
    def test_version_stays_on_the_base_release(self):
        self.assertEqual((VERSION, RELEASE_CHANNEL), ("0.102.0", "beta"))

    def test_catalogue_lists_the_method_after_kruskal(self):
        group = GROUPS["Group Comparison"]
        self.assertIn(mood.METHOD, group)
        self.assertEqual(group[group.index("Kruskal–Wallis") + 1], mood.METHOD)

    def test_fixture_matches_scipy_for_two_and_three_samples(self):
        frame, samples = fixture()
        for count, correction in ((3, False), (2, False), (2, True)):
            columns = list("ABC"[:count])
            for rule in mood.TIE_RULES:
                values = scipy_median_test(*samples[:count], ties=rule.lower(), correction=correction)
                result = run(frame, columns, **{mood.TIES: rule, mood.YATES: correction})
                row = result.tables[mood.RESULT_SHEET].iloc[0]
                table = result.tables[mood.COUNTS_SHEET]
                self.assertEqual(row["Pooled median"], values.median)
                self.assertEqual(row["df"], count - 1)
                self.assertTrue(isclose(row["Chi-square"], values.statistic, abs_tol=1e-12))
                self.assertTrue(isclose(row["P"], values.pvalue, abs_tol=1e-12))
                self.assertEqual(table["Sample"].tolist(), columns)
                self.assertEqual(table["Above"].tolist(), values.table[0].tolist())
                self.assertEqual(table["Below"].tolist(), values.table[1].tolist())
                self.assertIn(mood.SETTINGS_SHEET, result.tables)

    def test_tied_column_is_observed_before_the_rule(self):
        frame, samples = fixture()
        center = 3
        expected = [sum(value == center for value in group) for group in samples]
        for rule in mood.TIE_RULES:
            table = run(frame, **{mood.TIES: rule}).tables[mood.COUNTS_SHEET]
            self.assertEqual(table["Tied"].tolist(), expected)

    def test_unequal_lengths_and_three_tie_rules(self):
        frame, samples = fixture()
        self.assertEqual([len(group) for group in samples], [5, 4, 4])
        for rule in mood.TIE_RULES:
            row = run(frame, **{mood.TIES: rule}).tables[mood.RESULT_SHEET].iloc[0]
            self.assertFalse(pd.isna(row["P"]))
            self.assertEqual(row["Pooled median"], 3)

    def test_constant_ignore_keeps_median_without_inference(self):
        frame = pd.DataFrame({"A": [1, 1], "B": [1, 1]})
        result = run(frame, "AB", **{mood.TIES: mood.IGNORE})
        row = result.tables[mood.RESULT_SHEET].iloc[0]
        self.assertEqual(row["Pooled median"], 1)
        self.assertTrue(pd.isna(row["P"]))
        self.assertTrue(pd.isna(row["Chi-square"]))
        self.assertTrue(pd.isna(row["df"]))
        counts = result.tables[mood.COUNTS_SHEET]
        self.assertEqual(counts["Above"].tolist(), [0, 0])
        self.assertEqual(counts["Below"].tolist(), [0, 0])
        self.assertEqual(counts["Tied"].tolist(), [2, 2])
        settings = result.tables[mood.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Inference"], "Not available")

    def test_all_equal_below_also_empties_inference(self):
        frame = pd.DataFrame({
            "A": [2, 2, 2, np.nan],
            "B": [2, 2, np.nan, np.nan],
            "C": [2, 2, 2, 2],
        })
        row = run(frame, **{mood.TIES: mood.BELOW}).tables[mood.RESULT_SHEET].iloc[0]
        self.assertEqual(row["Pooled median"], 2)
        self.assertTrue(pd.isna(row["P"]))

    def test_ignore_emptying_one_group(self):
        # Median 2: A has only ties, B has values on both sides.
        frame = pd.DataFrame({"A": [2, 2, 2, np.nan], "B": [1, 2, 3, 4]})
        result = run(frame, "AB", **{mood.TIES: mood.IGNORE})
        row = result.tables[mood.RESULT_SHEET].iloc[0]
        counts = result.tables[mood.COUNTS_SHEET]
        self.assertEqual(row["Pooled median"], 2)
        self.assertTrue(pd.isna(row["P"]))
        self.assertEqual(counts.loc[0, "Above"] + counts.loc[0, "Below"], 0)
        self.assertEqual(int(counts.loc[0, "Tied"]), 3)

    def test_duplicate_column_names_and_exclusions(self):
        frame = pd.DataFrame([[1, 2], [2, 3], [3, 4], [4, 5]], columns=["A", "A"])
        with self.assertRaises(FieldError) as raised:
            analyse(mood.METHOD, frame, {mood.VARIABLES: ["A", "A"], mood.TIES: mood.BELOW, mood.YATES: False})
        self.assertEqual(raised.exception.field, mood.VARIABLES)

    def test_missing_local_strings_and_booleans(self):
        frame = pd.DataFrame({
            "A": ["1,5", "", "2,0", "3", None],
            "B": ["0", "1,0", "2", "4,5", "9"],
            "C": [3, 4, 5, 7, np.nan],
        })
        result = run(frame)
        row = result.tables[mood.RESULT_SHEET].iloc[0]
        self.assertFalse(pd.isna(row["P"]))
        settings = result.tables[mood.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Missing or excluded cells, A"], 2)
        with self.assertRaises(FieldError) as raised:
            analyse(mood.METHOD, pd.DataFrame({"A": [True, False, True], "B": [1, 2, 3]}),
                    {mood.VARIABLES: ["A", "B"], mood.TIES: mood.BELOW, mood.YATES: False})
        self.assertEqual(raised.exception.field, mood.VARIABLES)

    def test_yates_only_with_two_samples(self):
        frame, _ = fixture()
        two = run(frame, "AB", **{mood.YATES: True}).tables[mood.SETTINGS_SHEET]["Value"]
        three = run(frame, **{mood.YATES: True}).tables[mood.SETTINGS_SHEET]["Value"]
        self.assertTrue(two["Yates applied"])
        self.assertFalse(three["Yates applied"])
        self.assertIn("Yates note", three.index)

    def test_settings_report_low_expected_frequency(self):
        frame, _ = fixture()
        settings = run(frame).tables[mood.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Inference"], "Available")
        self.assertLess(float(settings["Minimum expected frequency"]), 5.0)
        self.assertIn("Expected frequencies", settings.index)

    def test_large_values_stay_stable(self):
        scale = 1e12
        frame = pd.DataFrame({
            "A": [1 * scale, 2 * scale, 3 * scale, 3 * scale, 4 * scale],
            "B": [2 * scale, 3 * scale, 5 * scale, 6 * scale, np.nan],
            "C": [3 * scale, 4 * scale, 5 * scale, 7 * scale, np.nan],
        })
        samples = [frame[name].dropna().to_numpy() for name in "ABC"]
        row = run(frame).tables[mood.RESULT_SHEET].iloc[0]
        reference = scipy_median_test(*samples, ties="below", correction=False)
        self.assertTrue(isclose(row["Pooled median"], reference.median, rel_tol=0, abs_tol=0))
        self.assertTrue(isclose(row["Chi-square"], reference.statistic, abs_tol=1e-9))
        self.assertTrue(isclose(row["P"], reference.pvalue, abs_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
