import math
import unittest

import pandas as pd

from analisi.processing import FieldError
from analisi.workbench import analyse


class RankComparisons(unittest.TestCase):
    def test_kruskal_tied_ranks_and_bonferroni_family(self):
        frame = pd.DataFrame({"Value": [1, 2, 2, 3, 3, 4, 4, 5, 6, None],
                              "Arm": ["A"] * 3 + ["B"] * 3 + ["C"] * 3 + ["Ignore"]})
        options = {"Response": "Value", "Group": "Arm", "Dunn comparisons": "All pairs"}
        result = analyse("Kruskal–Wallis", frame, options)
        pairs = result.tables["Dunn comparisons"]
        self.assertEqual(list(zip(pairs["First"], pairs["Second"])), [("A", "B"), ("A", "C"), ("B", "C")])
        pair = pairs.iloc[1]
        z = (35 / 6) / math.sqrt(4.875)
        p = math.erfc(z / math.sqrt(2))
        self.assertAlmostEqual(pair["Mean rank first"], 2)
        self.assertAlmostEqual(pair["Mean rank second"], 47 / 6)
        self.assertAlmostEqual(pair["z"], z)
        self.assertAlmostEqual(pair["p"], p)
        self.assertAlmostEqual(pair["Adjusted p"], 3 * p)
        control = analyse("Kruskal–Wallis", frame, {**options, "Dunn comparisons": "Versus control",
                                                  "Control group": "A"}).tables["Dunn comparisons"]
        self.assertEqual(control["First"].tolist(), ["A", "A"])
        self.assertAlmostEqual(control.iloc[1]["Adjusted p"], 2 * p)
        legacy = analyse("Kruskal–Wallis", frame, {"Response": "Value", "Group": "Arm"})
        self.assertEqual(list(legacy.tables), ["Kruskal–Wallis"])
        pd.testing.assert_frame_equal(legacy.tables["Kruskal–Wallis"], result.tables["Kruskal–Wallis"])

    def test_friedman_ranks_within_subject_after_shuffling(self):
        frame = pd.DataFrame([(subject, label, value)
                              for subject, row in enumerate(([1, 2, 3], [5, 5, 7], [10, 9, 11], [2, 4, 3]))
                              for label, value in zip(("A", "B", "C"), row)],
                             columns=["Subject ID", "Arm", "Value"]).sample(frac=1, random_state=8)
        options = {"Response": "Value", "Group": "Arm", "Subject": "Subject ID", "Dunn comparisons": "Versus control",
                   "Control group": "A", "Dunn adjustment": "Uncorrected", "Dunn alpha": .1}
        pairs = analyse("Friedman", frame, options).tables["Dunn comparisons"]
        pair = pairs.loc[pairs["Second"].eq("C")].iloc[0]
        z = 1.375 / math.sqrt(.5)
        self.assertAlmostEqual(pair["Mean rank first"], 1.375)
        self.assertAlmostEqual(pair["Mean rank second"], 2.75)
        self.assertAlmostEqual(pair["z"], z)
        self.assertAlmostEqual(pair["Adjusted p"], math.erfc(z / math.sqrt(2)))
        self.assertTrue(pair["Significant"])

    def test_control_and_alpha_errors_name_the_field(self):
        frame = pd.DataFrame({"Y": [1, 2, 3, 4, 5, 6], "Arm": list("AABBCC")})
        options = {"Response": "Y", "Group": "Arm", "Dunn comparisons": "Versus control"}
        for fields, expected in (({"Control group": "Absent"}, "Control group"),
                                 ({"Control group": "A", "Dunn alpha": 1.0}, "Dunn alpha")):
            with self.subTest(field=expected):
                with self.assertRaises(FieldError) as caught:
                    analyse("Kruskal–Wallis", frame, {**options, **fields})
                self.assertEqual(caught.exception.field, expected)

    def test_selected_pairs_preserve_order_and_define_correction_family(self):
        frame = pd.DataFrame({"Y": [1, 2, 3, 4, 5, 6, 7, 8], "Arm": list("AABBCCDD")})
        options = {"Response": "Y", "Group": "Arm", "Dunn comparisons": "Selected pairs",
                   "Selected pairs": [["D", "A"], ["C", "A"]]}
        pairs = analyse("Kruskal–Wallis", frame, options).tables["Dunn comparisons"]
        self.assertEqual(list(zip(pairs["First"], pairs["Second"])), [("D", "A"), ("C", "A")])
        self.assertAlmostEqual(pairs.at[0, "Rank difference"], 6)
        self.assertAlmostEqual(pairs.at[0, "Adjusted p"], 2 * math.erfc(6 / math.sqrt(12)))
        for invalid in ([], [["A", "A"]], [["A", "Z"]], [["A", "B"], ["B", "A"]], ["AB"]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FieldError) as caught:
                    analyse("Kruskal–Wallis", frame, {**options, "Selected pairs": invalid})
                self.assertEqual(caught.exception.field, "Selected pairs")

    def test_selected_friedman_pair_uses_all_within_subject_ranks(self):
        frame = pd.DataFrame([(subject, label, value)
                              for subject, row in enumerate(([1, 2, 3], [5, 5, 7], [10, 9, 11], [2, 4, 3]))
                              for label, value in zip("ABC", row)], columns=["Subject", "Group", "Y"])
        opts = {"Response": "Y", "Group": "Group", "Subject": "Subject", "Dunn comparisons": "Selected pairs",
                "Selected pairs": [["C", "A"]]}
        result = analyse("Friedman", frame, opts).tables["Dunn comparisons"]
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.at[0, "Adjusted p"], math.erfc(1.375))


class ExactKruskalWallis(unittest.TestCase):
    def result(self, values, labels, method=None):
        frame = pd.DataFrame({"Y": values, "Arm": list(labels)})
        options = {"Response": "Y", "Group": "Arm"}
        if method:
            options["Kruskal–Wallis p value"] = method
        return analyse("Kruskal–Wallis", frame, options).tables["Kruskal–Wallis"].iloc[:, 0]

    def test_exact_small_samples_with_and_without_ties(self):
        # For separated groups of size 2, six of the 90 allocations are at the observed maximum.
        for values, statistic in (([1, 2, 3, 4, 5, 6], 32/7), ([1, 1, 2, 2, 3, 3], 5.)):
            with self.subTest(values=values):
                result = self.result(values, "AABBCC", "Automatic")
                self.assertAlmostEqual(result["Statistic"], statistic)
                self.assertAlmostEqual(result["p"], 1/15)
                self.assertEqual(result["p method"], "Exact permutation")
        # The zero statistic has a tail probability of one. Ties must be included in the tail.
        self.assertEqual(self.result([1, 3, 2, 2, 1, 3], "AABBCC", "Exact permutation")["p"], 1.)

    def test_legacy_chi_square_and_automatic_fallback(self):
        old = self.result(list(range(1, 7)), "AABBCC")
        self.assertEqual(old["p method"], "Chi-square approximation")
        self.assertAlmostEqual(old["p"], math.exp(-16/7))
        values = list(range(24))
        labels = "A" * 8 + "B" * 8 + "C" * 8
        auto = self.result(values, labels, "Automatic")
        explicit = self.result(values, labels, "Chi-square approximation")
        pd.testing.assert_series_equal(auto, explicit)
        with self.assertRaises(FieldError) as caught:
            self.result(values, labels, "Exact permutation")
        self.assertEqual(caught.exception.field, "Kruskal–Wallis p value")

    def test_published_wind_auction_example(self):
        # Holt and Sullivan (2023), Table 6 and section 4.2.
        data = [-.61, -3.64, .82, 1.39, 3.84, 1.04, 3.17, 3.97, .22, -.24, .42, 1.13]
        result = self.result(data, "AAAABBBBCCCC", "Automatic")
        self.assertAlmostEqual(result["Statistic"], 5.69, places=2)
        self.assertAlmostEqual(result["p"], 1686/34650)
