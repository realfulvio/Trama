"""Compare two independent Pearson correlations on the Fisher z scale."""
import math
import unittest
from pathlib import Path

import pandas as pd
from scipy import stats

from analisi.correlation_details import COMPARE_INDEPENDENT, independent_correlation_test
from analisi.field_error import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data" / "correlation_details"


def run(frame, **options):
    base = {"X": "X", "Y": "Y", "Group": "Group", "Alternative": "Two-sided", "Confidence level (%)": 95,
            "Show intervals": True}
    base.update(options)
    return analyse(COMPARE_INDEPENDENT, frame, base)


def fisher(r1, n1, r2, n2, alternative="Two-sided", level=95.0):
    z = (math.atanh(r1) - math.atanh(r2)) / math.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
    if alternative == "Two-sided":
        probability = 2 * stats.norm.sf(abs(z))
    elif alternative == "Positive":
        probability = stats.norm.sf(z)
    else:
        probability = stats.norm.cdf(z)
    return z, probability


class IndependentTest(unittest.TestCase):
    def test_available_comparison_matches_the_fisher_formula(self):
        got = independent_correlation_test(0.4, 20, 0.1, 24, alternative="Positive", confidence=90)
        z, probability = fisher(0.4, 20, 0.1, 24, "Positive", 90)
        self.assertTrue(math.isclose(got["Z"], z, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(got["p"], probability, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(got["Difference"], 0.3))
        self.assertEqual(got["Status"], "Available")
        self.assertLess(got["Z lower"], got["Fisher z difference"])
        self.assertGreater(got["Z upper"], got["Fisher z difference"])
        # The reported interval is the z difference, not tanh of that interval.
        self.assertNotAlmostEqual(got["Z upper"], math.tanh(got["Z upper"]))

    def test_perfect_coefficient_keeps_the_difference_and_drops_inference(self):
        got = independent_correlation_test(1, 12, 0.2, 15)
        self.assertEqual(got["Status"], "Unavailable")
        self.assertEqual(got["Difference"], 0.8)
        self.assertIsNone(got["p"])
        self.assertIsNone(got["Fisher z difference"])
        self.assertIn("±1", got["Reason"])

    def test_bad_level(self):
        with self.assertRaises(FieldError) as caught:
            independent_correlation_test(0.2, 10, 0.3, 10, confidence=0)
        self.assertEqual(caught.exception.field, "Confidence level (%)")


class IndependentResult(unittest.TestCase):
    def test_groups_follow_first_appearance_and_pairs_keep_every_row(self):
        frame = pd.read_csv(DATA / "independent.csv")
        before = frame.copy(deep=True)
        result = run(frame)
        pd.testing.assert_frame_equal(frame, before)
        groups = result.tables["Groups"]
        self.assertEqual(groups["Group"].tolist(), ["Lab A", "Lab B"])
        self.assertEqual(groups["N"].tolist(), [6, 8])
        self.assertGreater(groups.loc[0, "Coefficient"], 0)
        self.assertEqual(len(result.tables["Pairs"]), len(frame))
        comparison = result.tables["Comparison"]["Value"]
        self.assertEqual(comparison["Status"], "Available")
        z, probability = fisher(groups.loc[0, "Coefficient"], 6, groups.loc[1, "Coefficient"], 8)
        self.assertTrue(math.isclose(comparison["Z"], z, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(comparison["p"], probability, rel_tol=1e-12, abs_tol=1e-12))
        self.assertTrue(math.isclose(comparison["Difference"], groups.loc[0, "Coefficient"] - groups.loc[1, "Coefficient"]))
        settings = " ".join(map(str, result.tables["Settings"]["Value"].tolist()))
        self.assertIn("Fisher z difference", settings)
        self.assertNotIn("tanh", settings.casefold())
        labels = [tick.get_text() for tick in result.figure.axes[0].get_yticklabels()]
        self.assertEqual(labels, ["Lab A", "Lab B"])
        self.assertEqual(result.figure.axes[0].get_xlim(), (-1, 1))

    def test_one_and_text_one_are_different_groups(self):
        frame = pd.DataFrame({
            "X": [1, 2, 3, 4, 1, 2, 3, 4],
            "Y": [1, 2, 4, 3, 4, 3, 2, 1],
            "Group": [1, 1, 1, 1, "1", "1", "1", "1"],
        })
        groups = run(frame).tables["Groups"]["Group"].tolist()
        self.assertEqual(groups, [1, "1"])
        self.assertIsInstance(groups[0], (int, float))
        self.assertIsInstance(groups[1], str)

    def test_bool_is_not_one(self):
        frame = pd.DataFrame({
            "X": [1, 2, 3, 4, 1, 2, 3, 4],
            "Y": [1, 3, 2, 4, 4, 2, 3, 1],
            "Group": [True, True, True, True, 1, 1, 1, 1],
        })
        groups = run(frame).tables["Groups"]["Group"].tolist()
        self.assertEqual(groups[0], True)
        self.assertEqual(groups[1], 1)
        self.assertIsNot(type(groups[0]), type(groups[1]))

    def test_missing_group_is_counted_and_a_third_group_is_rejected(self):
        frame = pd.DataFrame({
            "X": [1, 2, 3, 4, 5, 1, 2, 3, 4],
            "Y": [1, 2, 3, 4, 5, 2, 1, 4, 3],
            "Group": ["A", "A", "A", "A", None, "B", "B", "B", "B"],
        })
        result = run(frame)
        self.assertEqual(result.tables["Groups"]["Group"].tolist(), ["A", "B"])
        self.assertEqual(int(result.tables["Settings"]["Value"]["Rows omitted (missing group)"]), 1)
        frame.loc[8, "Group"] = "C"
        with self.assertRaises(FieldError) as caught:
            run(frame)
        self.assertEqual(caught.exception.field, "Group")
        self.assertIn("3 were found", str(caught.exception))

    def test_short_group_repeated_role_and_perfect_coefficient(self):
        short = pd.DataFrame({"X": [1, 2, 3, 4, 5], "Y": [1, 2, 3, 4, 5], "Group": ["A", "A", "B", "B", "B"]})
        with self.assertRaises(FieldError) as caught:
            run(short)
        self.assertEqual(caught.exception.field, "Group")
        with self.assertRaises(FieldError) as caught:
            run(short, X="X", Y="X")
        self.assertEqual(caught.exception.field, "Y")
        with self.assertRaises(FieldError) as caught:
            run(short, Group="X")
        self.assertEqual(caught.exception.field, "Group")
        perfect = pd.DataFrame({
            "X": [1, 2, 3, 4, 1, 2, 3, 4],
            "Y": [1, 2, 3, 4, 2, 1, 4, 3],
            "Group": ["A", "A", "A", "A", "B", "B", "B", "B"],
        })
        result = run(perfect, **{"Show intervals": False})
        groups = result.tables["Groups"]
        self.assertEqual(list(groups["Coefficient"]), [1.0, groups.loc[1, "Coefficient"]])
        self.assertEqual(groups.loc[0, "Lower"], 1.0)
        comparison = result.tables["Comparison"]["Value"]
        self.assertEqual(comparison["Status"], "Unavailable")
        self.assertTrue(pd.isna(comparison["p"]))
        self.assertAlmostEqual(comparison["Difference"], 1 - groups.loc[1, "Coefficient"])
        self.assertIn("Fisher z difference", result.tables["Settings"]["Value"]["Comparison interval"])
        axes = result.figure.axes[0]
        gids = {artist.get_gid() for artist in (*axes.lines, *axes.collections) if artist.get_gid()}
        self.assertIn("corr:coefficients", gids)
        self.assertNotIn("corr:intervals", gids)
        self.assertFalse(any(tick.get_parse_math() for tick in axes.get_yticklabels()))


if __name__ == "__main__":
    unittest.main()
