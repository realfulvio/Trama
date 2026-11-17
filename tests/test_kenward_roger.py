import unittest

import numpy as np
import pandas as pd

from analisi.inference import repeated_measures_anova
from analisi.mixed import _design, _fit_reml, mixed_effects_anova
from test_mixed import matched_frame, mixed_frame, two_within_frame


# Reference values use independent dense REML in R 4.6.2, followed by
# pbkrtest's vcovAdj_internal() and .KR_adjust() (bb7c4f9).
def fit(data, factors, **kwargs):
    return mixed_effects_anova(data, "Response", factors, "Subject",
                               inference="kenward-roger", **kwargs)


def assert_omnibus(result, expected):
    fields = ["F", "F df1", "F df2", "p", "F scaling"]
    np.testing.assert_allclose(result["Fixed effects"][fields], expected, rtol=3e-6)


class KenwardRogerTests(unittest.TestCase):
    def test_marginal_means_and_pairs_use_adjusted_se_and_contrast_df(self):
        result = fit(mixed_frame(), ["Group", "Time"], within=["Time"], posthoc="unadjusted")
        self.assertEqual(result["Model"].iloc[0]["Denominator df"], "Kenward–Roger")
        fields = ["Estimate", "SE", "df", "CI 95% low", "CI 95% high"]
        np.testing.assert_allclose(
            result["Estimated marginal means"].loc["Group=A", fields].astype(float),
            [8.37022491, 2.38692307, 6.00583774, 2.53101044, 14.20943938], rtol=3e-6)
        np.testing.assert_allclose(
            result["Fixed estimates"].loc[0, fields].astype(float),
            [6.25, 2.43421480, 6.49021452, .40106388, 12.09893612], rtol=3e-6)
        fields = ["Difference", "SE", "df", "p", "CI 95% low", "CI 95% high"]
        np.testing.assert_allclose(
            result["Multiple comparisons"].loc["Time | 0 − 1", fields].astype(float),
            [-1.58068593, .70735781, 9.04599072, .05215420, -3.17960121, .01822935], rtol=3e-6)

    def test_balanced_low_df_matches_exact_anova(self):
        for levels in (3, 4, 5):
            with self.subTest(levels=levels):
                data = matched_frame([[1, 3, 5, 7, 9][:levels], [7, 8, 12, 15, 17][:levels]])
                expected = repeated_measures_anova(data, "Response", ["Time"], "Subject")["ANOVA"]
                actual = fit(data, ["Time"])["Fixed effects"]
                fields = ["F", "F df1", "F df2", "p"]
                np.testing.assert_allclose(actual[fields], expected.loc[actual.index, fields], rtol=3e-6)
                self.assertEqual(actual.loc["Time", "F scaling"], 1.)

    def test_multi_df_tests_apply_f_scaling(self):
        rng = np.random.default_rng(242)
        values = rng.normal(0, 2, (21, 1)) + rng.normal(0, 3, (21, 5)) + np.arange(5)
        groups = np.searchsorted([2, 14], np.arange(21), side="right")
        values[groups == 1] += 4
        data = pd.DataFrame([
            (subject, groups[subject], time, values[subject, time])
            for subject, time in np.ndindex(values.shape)
            if (time == 0 or subject in {0, 1, 3, 14}
                or (subject % 3 == 0 and time <= 2) or (subject >= 14 and time >= 3))
        ], columns=["Subject", "Group", "Time", "Response"])
        result = fit(data, ["Group", "Time"], within=["Time"])
        assert_omnibus(result, [
            [3.1188212094, 2, 13.7405993809, .07642261218, .99498705169],
            [.7868721754, 4, 30.6550634932, .54261884575, .99969133055],
            [.8009666827, 8, 30.5638642674, .60641757800, .99934154139],
        ])

    def test_two_within_factors_adjust_covariance_off_diagonal(self):
        data = two_within_frame().drop(index=[0, 17, 29, 103, 143]).sort_values(["Time", "Dose", "Subject"])
        factors = ("Time", "Dose")
        y, cell, subjects, _, _ = _design(data, "Response", factors, "Subject", factors)
        fitted = _fit_reml(y, cell, subjects, (2, 3), factors, factors, inference="kenward-roger")
        np.testing.assert_allclose(
            fitted.kr.covariance[0] * fitted.scale**2,
            [3.171517797, 2.626642486, 2.626724555, 2.775219144, 2.270933428, 2.271197727], rtol=3e-6)
        assert_omnibus(fit(data, factors), [
            [9.3092043549, 1, 23.9981498119, .00549481163, 1],
            [2.1133845782, 2, 48.0041042639, .13193218676, .99999991498],
            [14.5886550611, 2, 43.4474699115, .000014223055, .99999983410],
        ])

    def test_three_within_factors_use_all_eight_variance_components(self):
        rng = np.random.default_rng(10)
        dims = (48, 2, 2, 2)
        values = np.arange(dims[0])[:, None, None, None] + rng.normal(size=dims)
        for shape in [(2, 1, 1), (1, 2, 1), (1, 1, 2), (2, 2, 1), (2, 1, 2), (1, 2, 2)]:
            values += rng.normal(0, 7 if shape.count(2) == 1 else 3, (dims[0], *shape))
        indices = np.indices(dims)
        values += 2 * indices[1] * indices[2] * indices[3]
        data = pd.DataFrame([(*index, values[index]) for index in np.ndindex(dims)],
                            columns=["Subject", "A", "B", "C", "Response"])
        data = data.drop(index=[1, 17, 59, 77, 109, 164, 194, 225, 255, 303, 335, 344, 375])
        assert_omnibus(fit(data, ["A", "B", "C"]), [
            [7.5156893879, 1, 46.9980352565, .00862369712, 1],
            [.9000512758, 1, 46.9992539855, .34762088179, 1],
            [.3591098255, 1, 46.9989369324, .55187896351, 1],
            [1.0977697407, 1, 47.0475841455, .30010898302, 1],
            [.03091337545, 1, 46.9518321815, .86118991651, 1],
            [.17509951773, 1, 46.9507972585, .67752685899, 1],
            [14.1192950014, 1, 37.7833433735, .000578857683, 1],
        ])

    def test_zero_random_variance_suppresses_kenward_roger_inference(self):
        data = matched_frame([[2, 9, 14], [3, 11, 11], [4, 7, 14], [5, 7, 13]])
        result = fit(data, ["Time"], posthoc="unadjusted")
        self.assertIn("zero", result["Model"].iloc[0]["Status"])
        self.assertEqual(result["Model"].iloc[0]["Denominator df"], "Unavailable")
        self.assertTrue(result["Fixed effects"][["F", "F df2", "p", "F scaling"]].isna().all().all())
        self.assertTrue(result["Fixed estimates"]["Estimate"].notna().all())
        self.assertTrue(result["Fixed estimates"][["SE", "df", "CI 95% low"]].isna().all().all())
        self.assertTrue(result["Multiple comparisons"][["SE", "df", "t", "Adjusted p"]].isna().all().all())

    def test_unidentifiable_components_suppress_inference(self):
        data = two_within_frame()
        data = data[data.Time == data.Subject % 2]
        result = fit(data, ["Time", "Dose"])
        model = result["Model"].iloc[0]
        self.assertEqual(model["Denominator df"], "Unavailable")
        self.assertIn("identifiable", model["Status"])
        self.assertTrue(result["Fixed effects"]["p"].isna().all())

    def test_rejects_unknown_inference_method(self):
        with self.assertRaisesRegex(ValueError, "Unknown.*inference"):
            mixed_effects_anova(mixed_frame(), "Response", ["Group", "Time"], "Subject",
                                within=["Time"], inference="unknown")
