"""Brunner–Munzel: pair oracle, SciPy p-values, worksheet recipe and large-N budget."""
from fractions import Fraction
from itertools import product
from math import isclose, sqrt
from pathlib import Path
import statistics
import time
import unittest

import numpy as np
import pandas as pd
from scipy.stats import brunnermunzel, t

from analisi import brunner_munzel as bm
from analisi._version import RELEASE_CHANNEL, VERSION
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, analyse

FIXTURE = Path(__file__).resolve().parent / "data" / "brunner_munzel" / "columns.csv"


def fixture():
    frame = pd.read_csv(FIXTURE)
    x = [int(value) for value in frame["Primo"].dropna()]
    y = [int(value) for value in frame["Secondo"].dropna()]
    return frame, x, y


def pair_oracle(x, y):
    wins = sum(left > right for left, right in product(x, y))
    ties = sum(left == right for left, right in product(x, y))
    losses = len(x) * len(y) - wins - ties
    p = Fraction(2 * wins + ties, 2 * len(x) * len(y))
    scores_x = [Fraction(sum(2 * (v > u) + (u == v) for u in y), 2 * len(y)) for v in x]
    scores_y = [Fraction(sum(2 * (v > u) + (u == v) for v in x), 2 * len(x)) for u in y]
    assert statistics.mean(scores_x) == statistics.mean(scores_y) == p
    a = statistics.variance(scores_x) / len(x)
    b = statistics.variance(scores_y) / len(y)
    se = sqrt(a + b)
    df = float((a + b) ** 2 / (a * a / (len(x) - 1) + b * b / (len(y) - 1)))
    signed = float(p - Fraction(1, 2)) / se
    return (wins, ties, losses), float(p), se, df, signed


def run(frame, **options):
    recipe = {
        bm.FIRST: "Primo", bm.SECOND: "Secondo",
        bm.LEVEL: 95.0, bm.ALTERNATIVE: bm.TWO_SIDED,
    }
    recipe.update(options)
    return analyse(bm.METHOD, frame, recipe)


class ContractTests(unittest.TestCase):
    def test_version_stays_on_the_base_release(self):
        self.assertEqual((VERSION, RELEASE_CHANNEL), ("0.101.0", "beta"))

    def test_catalogue_lists_the_method_after_mann_whitney(self):
        group = GROUPS["Group Comparison"]
        self.assertIn(bm.METHOD, group)
        self.assertEqual(group[group.index("Mann–Whitney") + 1], bm.METHOD)

    def test_fixture_matches_the_pair_oracle_and_scipy(self):
        frame, x, y = fixture()
        counts, probability, se, df, signed = pair_oracle(x, y)
        self.assertEqual(counts, (12, 2, 16))
        self.assertEqual(probability, float(Fraction(13, 30)))
        self.assertTrue(isclose(signed, -.34464834191427834, rel_tol=1e-12))
        for alternative in bm.ALTERNATIVES:
            row = run(frame, **{bm.ALTERNATIVE: alternative}).tables[bm.RESULT_SHEET].iloc[0]
            scipy = brunnermunzel(x, y, alternative=alternative.lower())
            self.assertEqual((row["Nx"], row["Ny"]), (5, 6))
            self.assertEqual((row["Wins"], row["Ties"], row["Losses"]), counts)
            self.assertTrue(isclose(row["Probability"], probability, rel_tol=1e-12))
            self.assertTrue(isclose(row["SE"], se, rel_tol=1e-12))
            self.assertTrue(isclose(row["T"], signed, rel_tol=1e-12))
            self.assertTrue(isclose(row["df"], df, rel_tol=1e-12))
            self.assertTrue(isclose(row["P"], scipy.pvalue, rel_tol=1e-10, abs_tol=1e-10))
            width = t.ppf(.975, df) * se
            self.assertTrue(isclose(row["Lower"], max(0, probability - width), rel_tol=1e-10, abs_tol=1e-10))
            self.assertTrue(isclose(row["Upper"], min(1, probability + width), rel_tol=1e-10, abs_tol=1e-10))
            self.assertTrue(isclose(row["T"], -scipy.statistic, rel_tol=1e-10, abs_tol=1e-10))

    def test_swapping_samples_flips_probability_and_t(self):
        frame, x, y = fixture()
        counts, probability, se, df, signed = pair_oracle(x, y)
        row = run(frame, **{bm.FIRST: "Secondo", bm.SECOND: "Primo"}).tables[bm.RESULT_SHEET].iloc[0]
        scipy = brunnermunzel(y, x, alternative="two-sided")
        self.assertEqual((row["Nx"], row["Ny"]), (6, 5))
        self.assertEqual((row["Wins"], row["Ties"], row["Losses"]), counts[::-1])
        self.assertTrue(isclose(row["Probability"], 1 - probability, rel_tol=1e-12))
        self.assertTrue(isclose(row["T"], -signed, rel_tol=1e-12))
        self.assertTrue(isclose(row["SE"], se, rel_tol=1e-12))
        self.assertTrue(isclose(row["df"], df, rel_tol=1e-12))
        self.assertTrue(isclose(row["P"], scipy.pvalue, rel_tol=1e-10, abs_tol=1e-10))
        width = t.ppf(.975, df) * se
        expected_p = 1 - probability
        self.assertTrue(isclose(row["Lower"], max(0, expected_p - width), rel_tol=1e-10, abs_tol=1e-10))
        self.assertTrue(isclose(row["Upper"], min(1, expected_p + width), rel_tol=1e-10, abs_tol=1e-10))

    def test_degenerate_cases_keep_probability_without_inference(self):
        options = {bm.FIRST: "Primo", bm.SECOND: "Secondo", bm.LEVEL: 95.0, bm.ALTERNATIVE: bm.TWO_SIDED}
        for level, probability in ((3, .5), (2, 1.)):
            same = pd.DataFrame({"Primo": [3, 3, 3], "Secondo": [level, level, level]})
            row = analyse(bm.METHOD, same, options).tables[bm.RESULT_SHEET].iloc[0]
            self.assertEqual(row["Probability"], probability)
            self.assertEqual(row["SE"], 0.0)
            for name in ("T", "df", "P", "Lower", "Upper"):
                self.assertTrue(pd.isna(row[name]), name)
            settings = analyse(bm.METHOD, same, options).tables[bm.SETTINGS_SHEET]["Value"]
            self.assertEqual(settings["Inference"], "Not available")

    def test_one_zero_variance_component_still_infers(self):
        frame = pd.DataFrame({"Primo": [1, 1, 1, 1], "Secondo": [0, 1, 2, 3]})
        row = run(frame).tables[bm.RESULT_SHEET].iloc[0]
        self.assertFalse(pd.isna(row["T"]))
        self.assertFalse(pd.isna(row["P"]))
        self.assertGreater(row["SE"], 0)

    def test_missing_local_strings_and_booleans(self):
        frame = pd.DataFrame({
            "Primo": ["1,5", "", "2,0", "3", None],
            "Secondo": ["0", "1,0", "2", "4,5", "9"],
        })
        row = run(frame).tables[bm.RESULT_SHEET].iloc[0]
        self.assertEqual((row["Nx"], row["Ny"]), (3, 5))
        settings = run(frame).tables[bm.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["Missing or excluded cells, First sample"], 2)
        with self.assertRaises(FieldError) as raised:
            analyse(bm.METHOD, pd.DataFrame({"Primo": [True, False, True], "Secondo": [1, 2, 3]}),
                    {bm.FIRST: "Primo", bm.SECOND: "Secondo", bm.LEVEL: 95.0, bm.ALTERNATIVE: bm.TWO_SIDED})
        self.assertEqual(raised.exception.field, bm.FIRST)

    def test_same_column_and_bad_level_name_the_field(self):
        frame, _, _ = fixture()
        with self.assertRaises(FieldError) as same:
            run(frame, **{bm.SECOND: "Primo"})
        self.assertEqual(same.exception.field, bm.SECOND)
        with self.assertRaises(FieldError) as level:
            run(frame, **{bm.LEVEL: 101})
        self.assertEqual(level.exception.field, bm.LEVEL)

    def test_settings_carry_orientation_and_small_sample_note(self):
        frame, _, _ = fixture()
        settings = run(frame).tables[bm.SETTINGS_SHEET]["Value"]
        self.assertEqual(settings["First sample"], "Primo")
        self.assertEqual(settings["Second sample"], "Secondo")
        self.assertEqual(settings["Alternative"], bm.TWO_SIDED)
        self.assertIn("Small samples", settings.index)
        self.assertEqual(settings["Inference"], "Available")

    def test_large_samples_stay_linear_in_memory_and_time(self):
        generator = np.random.default_rng(0)
        first = generator.normal(size=50_000)
        second = generator.normal(size=50_000)
        # About 20% ties: copy a block of the first sample into the second.
        second[:10_000] = first[:10_000]
        started = time.perf_counter()
        summary = bm.relative_effect(first, second, level=0.95, alternative=bm.TWO_SIDED)
        elapsed = time.perf_counter() - started
        self.assertEqual(summary["Nx"], 50_000)
        self.assertEqual(summary["Ny"], 50_000)
        self.assertGreater(summary["Ties"], 0)
        self.assertFalse(pd.isna(summary["P"]))
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
