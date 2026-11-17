import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import inference


def matched_frame(values):
    return pd.DataFrame([(subject, level, response) for subject, row in enumerate(values)
                         for level, response in enumerate(row)], columns=["Subject", "Time", "Response"])


def mixed_frame():
    values = [(1, 4, 6), (5, 6, 8), (8, 9, None), (11, None, 17),
              (2, 2, 7), (7, 7, 13), (10, None, 15), (13, 17, 17)]
    data = matched_frame(values)
    data["Group"] = np.where(data["Subject"] < 4, "A", "B")
    return data


def two_within_frame():
    rng = np.random.default_rng(50)
    a_random = rng.normal(0, 3, (25, 2))
    b_random = rng.normal(0, 4, (25, 3))
    return pd.DataFrame([
        (subject, time, dose, subject + time + dose * time + rng.normal()
         + a_random[subject, time] + b_random[subject, dose])
        for subject in range(25) for time in range(2) for dose in range(3)
    ], columns=["Subject", "Time", "Dose", "Response"])


class MixedEffectsTests(unittest.TestCase):
    def fit(self, frame, factors=("Time",), **options):
        from analisi.mixed import mixed_effects_anova

        return mixed_effects_anova(frame, "Response", factors, "Subject", **options)

    def test_balanced_one_way_agrees_with_repeated_measures_anova(self):
        data = matched_frame([[1, 3, 5], [4, 5, 10], [7, 12, 13], [13, 13, 17], [17, 20, 21]])
        expected = inference.repeated_measures_anova(data, "Response", ["Time"], "Subject")["ANOVA"]
        result = self.fit(data)
        for field in ("F", "F df1", "F df2", "p"):
            self.assertAlmostEqual(result["Fixed effects"].loc["Time", field], expected.loc["Time", field])
        self.assertEqual(result["Model"].iloc[0]["Subjects partial"], 0)

    def test_unbalanced_mixed_design_matches_independent_reml_fit(self):
        data = mixed_frame()
        result = self.fit(data.drop(index=8), ("Group", "Time"), within=["Time"], posthoc="unadjusted")
        # Independent R reference: nlme::lme(Y ~ 0 + Cell, random = ~1 | Subject)
        # checked by dense REML optimization in log SD coordinates and numerical
        # derivatives supplied to lmerTest::contestMD and contest1D.
        variances = result["Variance components"]["Variance"]
        self.assertAlmostEqual(variances["Subject random intercept"], 22.105411, places=5)
        self.assertAlmostEqual(variances["Residual"], 1.596195, places=5)
        self.assertAlmostEqual(result["Estimated marginal means"].loc["Time=0", "Estimate"], 7.125)
        np.testing.assert_allclose(
            result["Fixed effects"][["F", "F df1", "F df2", "p"]],
            [[.26398995, 1, 6.01584187, .62571211],
             [25.37312893, 2, 9.07796795, .00019190155],
             [.23530526, 2, 9.07796795, .79500334]], rtol=2e-6)
        pair = result["Multiple comparisons"].loc["Time | 0 − 1"]
        np.testing.assert_allclose(pair[["Difference", "SE", "df", "p"]].astype(float),
                                   [-1.58068582, .70637216, 9.07259216, .05180559], rtol=2e-6)
        counts = result["Model"].iloc[0]
        self.assertEqual(counts["Observations used"], 21)
        self.assertEqual(counts["Response rows omitted"], 2)
        self.assertEqual(counts["Subject cells missing"], 3)
        self.assertEqual(counts["Subjects partial"], 3)
        self.assertEqual(counts["Subjects used"], 8)

    def test_three_factor_omnibus_includes_every_interaction(self):
        rng = np.random.default_rng(77)
        a_random = rng.normal(0, 3, (32, 2))
        b_random = rng.normal(0, 4, (32, 2))
        data = pd.DataFrame([
            (subject, subject // 16, time, dose, subject + time + dose * time + rng.normal()
             + a_random[subject, time] + b_random[subject, dose])
            for subject in range(32) for time in range(2) for dose in range(2)
        ], columns=["Subject", "Group", "Time", "Dose", "Response"]).drop(index=[4, 9, 13])
        result = self.fit(data, ("Group", "Time", "Dose"), within=["Time", "Dose"])
        table = result["Fixed effects"]
        self.assertEqual(set(table.index),
                         {"Group", "Time", "Dose", "Group:Time", "Group:Dose", "Time:Dose", "Group:Time:Dose"})
        self.assertTrue((table["F df2"] > 0).all())

    def test_balanced_two_within_model_uses_subject_by_factor_strata(self):
        data = two_within_frame()
        result = self.fit(data, ("Time", "Dose"))
        expected = inference.repeated_measures_anova(data, "Response", ["Time", "Dose"], "Subject")["ANOVA"]
        for field in ("F", "F df1", "F df2", "p"):
            actual = result["Fixed effects"][field]
            np.testing.assert_allclose(actual, expected.loc[actual.index, field], rtol=2e-5)
        self.assertEqual(set(result["Variance components"].index),
                         {"Subject random intercept", "Subject × Time", "Subject × Dose", "Residual"})

    def test_two_within_missing_data_matches_independent_reml_fit(self):
        data = two_within_frame().drop(index=[0, 17, 29, 103, 143])
        result = self.fit(data, ("Time", "Dose"))
        # R reference fits the full dense covariance I, ZZ', Z_Time Z_Time'
        # and Z_Dose Z_Dose', with numerical Hessian and lmerTest contrasts.
        np.testing.assert_allclose(
            result["Variance components"]["Variance"],
            [56.77333541, 8.89477959, 12.60714291, .90405982], rtol=2e-6)
        np.testing.assert_allclose(
            result["Fixed effects"][["F", "F df1", "F df2", "p"]],
            [[9.30946599, 1, 24.03235343, .00548867001],
             [2.11342943, 2, 48.13855643, .13189612282],
             [14.60267211, 2, 43.75100671, .00001386744]], rtol=2e-6)
        self.assertEqual(result["Model"].iloc[0]["Subjects partial"], 5)

    def test_balanced_three_within_includes_all_subject_by_pair_strata(self):
        rng = np.random.default_rng(10)
        dims = 48, 2, 2, 2
        values = np.arange(dims[0])[:, None, None, None] + rng.normal(size=dims)
        values += rng.normal(0, 7, (dims[0], 2, 1, 1))
        values += rng.normal(0, 7, (dims[0], 1, 2, 1))
        values += rng.normal(0, 7, (dims[0], 1, 1, 2))
        values += rng.normal(0, 3, (dims[0], 2, 2, 1))
        values += rng.normal(0, 3, (dims[0], 2, 1, 2))
        values += rng.normal(0, 3, (dims[0], 1, 2, 2))
        values += 2 * np.indices(dims)[1] * np.indices(dims)[2] * np.indices(dims)[3]
        data = pd.DataFrame([(*indices, values[indices]) for indices in np.ndindex(dims)],
                            columns=["Subject", "A", "B", "C", "Response"])
        result = self.fit(data, ("A", "B", "C"))
        actual = result["Fixed effects"]
        for term in actual.index:
            axes = term.split(":")
            # Every term is one-dimensional when all factors are binary;
            # its classic balanced test is the paired t-test on the contrast.
            weights = [[1., -1.] if factor in axes else [.5, .5] for factor in ("A", "B", "C")]
            differences = np.einsum("sabc,a,b,c->s", values, *weights)
            expected = stats.ttest_1samp(differences, 0)
            np.testing.assert_allclose(actual.loc[term, ["F", "F df2", "p"]],
                                       [expected.statistic**2, expected.df, expected.pvalue], rtol=3e-5)
        self.assertEqual(len(result["Variance components"]), 8)

    def test_singletons_are_retained_and_all_missing_subjects_are_counted(self):
        data = mixed_frame().drop(index=[10, 11])
        data = pd.concat([data, pd.DataFrame([(8, 0, np.nan, "A")], columns=data.columns)])
        result = self.fit(data, ("Group", "Time"), within=["Time"])
        subjects = result["Subjects"]
        self.assertEqual(subjects.loc[3, "Observations used"], 1)
        self.assertEqual(subjects.loc[8, "Observations used"], 0)
        self.assertEqual(subjects.loc[8, "Cells missing"], 3)
        self.assertEqual(result["Model"].iloc[0]["Subjects excluded"], 1)

    def test_bonferroni_comparisons_use_contrast_specific_df_and_family_size(self):
        data = mixed_frame()
        result = self.fit(data, ("Group", "Time"), within=["Time"], posthoc="bonferroni")
        pair = result["Multiple comparisons"].loc["Time | 0 − 1"]
        self.assertAlmostEqual(pair["Adjusted p"], min(1, 3 * pair["p"]))
        critical = stats.t.isf(.05 / 6, pair["df"])
        self.assertAlmostEqual(pair["CI 95% high"], pair["Difference"] + critical * pair["SE"])
        self.assertNotAlmostEqual(pair["df"], result["Multiple comparisons"].loc["Time | 0 − 2", "df"])

    def test_simple_effects_compare_cells_and_adjust_within_or_across_strata(self):
        data = mixed_frame()
        options = dict(within=["Time"], posthoc="bonferroni", compare="Time", condition=["Group"])
        separate = self.fit(data, ("Group", "Time"), **options)
        pooled = self.fit(data, ("Group", "Time"), family="pooled", **options)
        index = "Group=A | Time | 0 − 1"
        separated_pair = separate["Multiple comparisons"].loc[index]
        pooled_pair = pooled["Multiple comparisons"].loc[index]
        self.assertEqual(len(separate["Multiple comparisons"]), 6)
        self.assertAlmostEqual(separated_pair["Difference"], 6.25 - 8.10126925)
        self.assertAlmostEqual(separated_pair["Adjusted p"], min(1, 3 * separated_pair["p"]))
        self.assertAlmostEqual(pooled_pair["Adjusted p"], min(1, 6 * separated_pair["p"]))
        self.assertGreater(pooled_pair["CI 95% high"], separated_pair["CI 95% high"])

    def test_zero_subject_variance_reports_singularity_and_no_inferential_df(self):
        data = matched_frame([[2, 9, 14], [3, 11, 11], [4, 7, 14], [5, 7, 13]])
        result = self.fit(data, posthoc="holm")
        self.assertEqual(result["Variance components"].loc["Subject random intercept", "Variance"], 0)
        self.assertIn("singular", result["Model"].iloc[0]["Status"].lower())
        self.assertTrue(np.isnan(result["Fixed effects"].loc["Time", "F df2"]))
        self.assertTrue(result["Multiple comparisons"]["CI 95% high"].isna().all())

    def test_validation_rejects_inconsistent_assignment_duplicate_and_empty_cell(self):
        data = mixed_frame()
        wrong_group = data.copy()
        wrong_group.loc[0, "Group"] = "B"
        no_cell = data.assign(Response=data["Response"].mask((data["Time"] == 2) & (data["Group"] == "A")))
        invalid_cases = [
            (wrong_group, "between-subject"),
            (pd.concat([data, data.iloc[:1]]), "duplicate"),
            (no_cell, "empty.*cell"),
        ]
        for invalid, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.fit(invalid, ("Group", "Time"), within=["Time"])
