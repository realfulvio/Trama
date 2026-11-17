import unittest

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.anova import AnovaRM

from analisi import inference


def independent_samples(*samples):
    return pd.DataFrame([(group, value) for group, sample in enumerate(samples) for value in sample],
                        columns=["Group", "Response"])


def matched_samples(values):
    return pd.DataFrame([(subject, group, value) for subject, row in enumerate(values)
                         for group, value in enumerate(row)], columns=["Subject", "Group", "Response"])


class IndependentAnovaTests(unittest.TestCase):
    def test_ordinary_anova_and_tukey_kramer_with_unequal_group_sizes(self):
        samples = ([1., 2., 3.], [3., 4., 5., 7.], [5., 8., 9.])
        result = inference.one_way_anova(independent_samples(*samples), "Response", "Group", posthoc="tukey")
        omnibus = stats.f_oneway(*samples)
        table = result["ANOVA"]
        self.assertAlmostEqual(table.loc["Group", "F"], omnibus.statistic)
        self.assertAlmostEqual(table.loc["Group", "p"], omnibus.pvalue)
        self.assertEqual(table.loc["Residual", "df"], 7)
        tukey = stats.tukey_hsd(*samples)
        pair = result["Multiple comparisons"].loc["0 − 2"]
        self.assertAlmostEqual(pair["Difference"], -16 / 3)
        self.assertAlmostEqual(pair["Adjusted p"], tukey.pvalue[0, 2])
        self.assertAlmostEqual(pair["CI 95% low"], tukey.confidence_interval().low[0, 2])

    def test_welch_anova_and_games_howell_for_unequal_variance(self):
        samples = ([1., 2., 3.], [3., 4., 5., 19., 24.], [7., 8., 9., 10.])
        result = inference.one_way_anova(independent_samples(*samples), "Response", "Group",
                                         method="welch", posthoc="games-howell")
        omnibus = stats.f_oneway(*samples, equal_var=False)
        table = result["ANOVA"].loc["Group"]
        self.assertAlmostEqual(table["F"], omnibus.statistic)
        self.assertAlmostEqual(table["p"], omnibus.pvalue)
        self.assertAlmostEqual(stats.f.sf(table["F"], table["F df1"], table["F df2"]), table["p"])
        games_howell = stats.tukey_hsd(*samples, equal_var=False)
        pair = result["Multiple comparisons"].loc["0 − 1"]
        self.assertAlmostEqual(pair["Adjusted p"], games_howell.pvalue[0, 1])
        self.assertAlmostEqual(pair["CI 95% high"], games_howell.confidence_interval().high[0, 1])

    def test_tukey_uses_the_pooled_error_even_for_singleton_groups(self):
        result = inference.one_way_anova(independent_samples([1.], [3., 4., 5.]), "Response", "Group",
                                         posthoc="tukey")
        pair = result["Multiple comparisons"].loc["0 − 1"]
        self.assertAlmostEqual(pair["Adjusted p"], 2 * stats.t.sf(3 / np.sqrt(4 / 3), 2))

    def test_adjustment_uses_all_pairs_of_welch_tests(self):
        samples = ([1., 2., 3.], [3., 4., 5., 19., 24.], [7., 8., 9., 10.])
        result = inference.one_way_anova(independent_samples(*samples), "Response", "Group",
                                         method="welch", posthoc="bonferroni")
        pair = result["Multiple comparisons"].loc["0 − 2"]
        pvalue = stats.ttest_ind(samples[0], samples[2], equal_var=False).pvalue
        self.assertAlmostEqual(pair["p"], pvalue)
        self.assertAlmostEqual(pair["Adjusted p"], pvalue * 3)

    def test_welch_rejects_inapplicable_tests_and_zero_group_variance(self):
        with self.assertRaisesRegex(ValueError, "post-hoc"):
            inference.one_way_anova(independent_samples([1, 2], [3, 4]), "Response", "Group",
                                    method="welch", posthoc="tukey")
        with self.assertRaisesRegex(ValueError, "positive variance"):
            inference.one_way_anova(independent_samples([1, 1], [2, 3]), "Response", "Group", method="welch")


class RepeatedMeasuresTests(unittest.TestCase):
    def test_within_subject_tests_are_invariant_to_subject_offsets(self):
        values = np.array([[0., .5, 2.5], [0., 1., 2.], [0., 1.5, 1.5]])
        shifted = values + np.array([-2.**51, 0, 2.**51])[:, None]
        result = inference.repeated_measures_anova(matched_samples(shifted), "Response", ["Group"], "Subject",
                                                   correction="gg")["ANOVA"].loc["Group"]
        self.assertAlmostEqual(result["F"], 12)
        self.assertAlmostEqual(result["GG ε"], .5)

    def test_one_way_anova_geisser_greenhouse_adjusts_only_test_degrees_of_freedom(self):
        values = np.array([0, 10, 20])[:, None] + [0, 2, 4] + np.outer([-1, 0, 1], [1, 0, -1])
        frame = matched_samples(values).sample(frac=1, random_state=32)
        plain = inference.repeated_measures_anova(frame, "Response", ["Group"], "Subject")["ANOVA"]
        corrected = inference.repeated_measures_anova(frame, "Response", ["Group"], "Subject",
                                                       correction="gg")["ANOVA"]
        row = corrected.loc["Group"]
        self.assertAlmostEqual(plain.loc["Group", "p"], stats.f.sf(12, 2, 4))
        self.assertAlmostEqual(row["SS"], 24)
        self.assertAlmostEqual(row["F"], 12)
        self.assertAlmostEqual(row["GG ε"], 0.5)
        self.assertAlmostEqual(row["p"], stats.f.sf(12, 1, 2))
        self.assertEqual(row["df"], 2)
        self.assertEqual(row["F df1"], 1)
        self.assertEqual(row["F df2"], 2)

    def test_two_way_anova_uses_a_distinct_subject_error_for_each_term(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame([(subject, a, b, rng.normal() + subject * 10 + 2 * a + 3 * b + a * b)
                              for subject in range(5) for a in range(2) for b in range(3)],
                             columns=["Subject", "A", "B", "Response"]).sample(frac=1, random_state=3)
        expected = AnovaRM(frame, "Response", "Subject", within=["A", "B"]).fit().anova_table
        table = inference.repeated_measures_anova(frame, "Response", ["A", "B"], "Subject")["ANOVA"]
        for term in expected.index:
            with self.subTest(term=term):
                self.assertAlmostEqual(table.loc[term, "F"], expected.loc[term, "F Value"])
                self.assertAlmostEqual(table.loc[term, "p"], expected.loc[term, "Pr > F"])
                self.assertAlmostEqual(table.loc[term, "F df2"], expected.loc[term, "Den DF"])
        self.assertAlmostEqual(table["SS"].sum(), ((frame["Response"] - frame["Response"].mean()) ** 2).sum())

    def test_incomplete_or_duplicate_subject_cells_raise(self):
        frame = matched_samples([[1, 2, 4], [3, 5, 8], [1, 5, 8]])
        fixtures = [(frame.iloc[:-1], "complete"),
                    (pd.concat([frame, frame.iloc[:1]]), "duplicate"),
                    (frame.assign(Response=frame["Response"].where(frame.index != 0)), "missing"),
                    (frame.assign(Subject=frame["Subject"].where(frame.index != 0)), "missing")]
        for invalid, message in fixtures:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    inference.repeated_measures_anova(invalid, "Response", ["Group"], "Subject")
                with self.assertRaisesRegex(ValueError, message):
                    inference.friedman(invalid, "Response", "Group", "Subject")

    def test_friedman_exact_p_counts_tied_permutations(self):
        frame = matched_samples([[1, 1, 2], [3, 3, 4]])
        result = inference.friedman(frame, "Response", "Group", "Subject")["Friedman"].iloc[0]
        self.assertAlmostEqual(result["Statistic"], 4)
        self.assertAlmostEqual(result["p"], 1 / 3)
        self.assertEqual(result["p method"], "Exact permutation")

    def test_friedman_uses_chi_square_approximation_for_larger_designs(self):
        values = np.random.default_rng(11).integers(0, 4, size=(16, 3))
        result = inference.friedman(matched_samples(values), "Response", "Group", "Subject")["Friedman"].iloc[0]
        expected = stats.friedmanchisquare(*values.T)
        self.assertAlmostEqual(result["Statistic"], expected.statistic)
        self.assertAlmostEqual(result["p"], expected.pvalue)
        self.assertEqual(result["p method"], "Chi-square approximation")
