"""Independent raw-data oracles for inference from sufficient statistics."""
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.processing import FieldError
from analisi.summary_anova import METHOD, summary_anova


class SummaryAnovaTests(unittest.TestCase):
    samples = ([1., 2, 4, 5], [3., 5, 8], [6., 7, 9, 11, 12])

    def data(self, scale=1.):
        return pd.DataFrame({"group": ["A", "B", "C"],
                             "mean": [np.mean(x)*scale for x in self.samples],
                             "sd": [np.std(x, ddof=1)*abs(scale) for x in self.samples],
                             "n": list(map(len, self.samples))})

    def options(self, **extra):
        return {"Input": "Groups in rows", "Group": "group", "Mean": "mean",
                "Dispersion": "sd", "Sample size": "n", "Dispersion type": "SD",
                "Post-hoc": "Tukey", "Confidence level (%)": 95., **extra}

    def test_raw_f_and_tukey_oracles(self):
        result = summary_anova(self.data(), self.options())
        omnibus = stats.f_oneway(*self.samples)
        row = result.tables["ANOVA"].iloc[0]
        self.assertAlmostEqual(row["F"], omnibus.statistic, places=12)
        self.assertAlmostEqual(row["p"], omnibus.pvalue, places=14)
        raw = stats.tukey_hsd(*self.samples)
        comparisons = result.tables["Multiple comparisons"]
        for k, (i, j) in enumerate(((0, 1), (0, 2), (1, 2))):
            self.assertAlmostEqual(comparisons.iloc[k]["Adjusted p"], raw.pvalue[i,j], places=12)
            self.assertAlmostEqual(comparisons.iloc[k]["CI lower"], raw.confidence_interval().low[i,j], places=10)

    def test_analytical_sums_of_squares(self):
        data = pd.DataFrame({"mean": [2., 4., 6.], "sd": [1., 1., 1.], "n": [3, 3, 3]})
        table = summary_anova(data, self.options(Group=None)).tables["ANOVA"]
        self.assertAlmostEqual(table.iloc[0]["SS"], 24.)
        self.assertAlmostEqual(table.iloc[1]["SS"], 6.)
        self.assertAlmostEqual(table.iloc[0]["F"], 12.)
        self.assertAlmostEqual(table.iloc[0]["p"], .008)

    def test_sem_and_cv_agree_with_sd(self):
        expected = summary_anova(self.data(), self.options()).tables["ANOVA"]
        for kind in ("SEM", "CV (%)"):
            frame = self.data()
            frame["sd"] /= np.sqrt(frame.n) if kind == "SEM" else frame["mean"]/100
            got = summary_anova(frame, self.options(**{"Dispersion type": kind})).tables["ANOVA"]
            np.testing.assert_allclose(got["F"], expected["F"], rtol=1e-13, equal_nan=True)

    def test_summary_subcolumns_and_source_row(self):
        data = self.data()
        wide = pd.DataFrame({f"{r.group} [{role}]": [np.nan, getattr(r, field)]
                            for r in data.itertuples() for role, field in (("Mean", "mean"), ("SD", "sd"), ("N", "n"))})
        opts = {"Input": "Summary subcolumns", "Summary row": 2, "Variables": list(wide),
                "Dispersion type": "SD", "Post-hoc": "None"}
        got = summary_anova(wide, opts)
        self.assertEqual(got.tables["Summaries used"]["Source row"].tolist(), [2, 2, 2])
        self.assertAlmostEqual(got.tables["ANOVA"].iloc[0]["F"], stats.f_oneway(*self.samples).statistic)

    def test_unit_invariance_extreme_and_negative(self):
        expected = summary_anova(self.data(), self.options()).tables["ANOVA"].iloc[0]
        for scale in (1e-200, 1e200, -3):
            result = summary_anova(self.data(scale), self.options())
            self.assertAlmostEqual(result.tables["ANOVA"].iloc[0]["F"], expected["F"], places=11)
            self.assertAlmostEqual(result.tables["ANOVA"].iloc[0]["p"], expected["p"], places=14)
            if abs(scale) != 3:
                self.assertTrue(pd.isna(result.tables["ANOVA"].iloc[0]["SS"]))
                self.assertTrue(result.tables["ANOVA"].iloc[0]["Note"])

    def test_input_is_not_mutated(self):
        frame = self.data(); before = frame.copy(deep=True)
        summary_anova(frame, self.options())
        pd.testing.assert_frame_equal(frame, before)

    def test_sample_size_never_expands_observations(self):
        frame = self.data(); frame.n = [10**9, 10**9, 10**9]
        result = summary_anova(frame, self.options(**{"Post-hoc": "None"}))
        self.assertEqual(len(result.tables["Summaries used"]), 3)
        self.assertEqual(result.tables["ANOVA"].iloc[1]["df"], 3*10**9-3)

    def test_missing_triplet_omits_only_that_group(self):
        frame = self.data(); frame.loc[1, "sd"] = np.nan
        result = summary_anova(frame, self.options())
        self.assertEqual(result.tables["Summaries used"]["Source row"].tolist(), [1, 3])
        self.assertEqual(result.tables["Omitted groups"]["Source row"].tolist(), [2])
        self.assertAlmostEqual(result.tables["ANOVA"].iloc[0]["F"], stats.f_oneway(self.samples[0], self.samples[2]).statistic)

    def test_invalid_values_name_fields(self):
        for column, value, field in (("sd", -1, "Dispersion"), ("sd", np.inf, "Dispersion"),
                                     ("n", 1, "Sample size"), ("n", 3.1, "Sample size"),
                                     ("n", True, "Sample size"), ("mean", "bad", "Mean")):
            frame = self.data().astype(object); frame.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(FieldError) as error:
                summary_anova(frame, self.options())
            self.assertEqual(error.exception.field, field)

    def test_distinct_roles_required(self):
        with self.assertRaises(FieldError):
            summary_anova(self.data(), self.options(Dispersion="mean"))

    def test_n_above_integer_precision_is_never_rounded_down(self):
        for value in (2**53+1, str(2**53+1), "3.0000000000000001"):
            frame = self.data().astype(object); frame.loc[0,"n"] = value
            with self.subTest(value=value), self.assertRaises(FieldError):
                summary_anova(frame,self.options())

    def test_equal_display_labels_still_represent_separate_groups(self):
        frame = self.data(); frame["group"] = [1,"1",True]
        result = summary_anova(frame,self.options())
        self.assertEqual(len(result.tables["Summaries used"]),3)
        self.assertEqual(len(result.tables["Multiple comparisons"]),3)

    def test_summary_missing_or_duplicate_roles_rejected(self):
        frame = pd.DataFrame({"A [Mean]":[2],"A [SD]":[1],"B [Mean]":[5],"B [SD]":[1]})
        with self.assertRaises(FieldError) as error:
            summary_anova(frame,{"Input":"Summary subcolumns","Variables":list(frame)})
        self.assertEqual(error.exception.field,"Variables")

    def test_budget_level_and_cv_zero(self):
        for option in ({"Confidence level (%)":0},{"Confidence level (%)":100},{"Confidence level (%)":True},
                       {"Confidence level (%)":np.nextafter(0.,1.)}):
            with self.assertRaises(FieldError): summary_anova(self.data(),self.options(**option))
        frame = self.data(); frame.loc[0,"mean"] = 0
        with self.assertRaises(FieldError): summary_anova(frame,self.options(**{"Dispersion type":"CV (%)"}))

    def test_zero_pooled_variance_rejected_individual_zero_allowed(self):
        data = self.data(); data.loc[0, "sd"] = 0
        self.assertTrue(np.isfinite(summary_anova(data, self.options()).tables["ANOVA"].iloc[0]["F"]))
        data.sd = 0
        with self.assertRaises(FieldError) as error: summary_anova(data, self.options())
        self.assertEqual(error.exception.field, "Dispersion")

    def test_confidence_level_changes_interval_not_p(self):
        a = summary_anova(self.data(), self.options()).tables["Multiple comparisons"]
        b = summary_anova(self.data(), self.options(**{"Confidence level (%)":90})).tables["Multiple comparisons"]
        np.testing.assert_array_equal(a["Adjusted p"], b["Adjusted p"])
        self.assertTrue((b["CI lower"] > a["CI lower"]).all())

    def test_holm_bonferroni_and_no_posthoc(self):
        for choice in ("Holm", "Bonferroni", "None"):
            result = summary_anova(self.data(), self.options(**{"Post-hoc":choice}))
            self.assertEqual("Multiple comparisons" in result.tables, choice != "None")
            if choice != "None":
                table = result.tables["Multiple comparisons"]
                self.assertTrue((table["Adjusted p"] >= table.p).all())
                self.assertNotIn("CI lower", table)

    def test_dispatcher_and_roundtrip(self):
        from analisi.workbench import analyse
        from analisi.data import Dataset, save_project, load_project
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory)/"summary.alab"
            save_project(path, {"Summary": Dataset(self.data(), analyses=[(METHOD,self.options())])})
            datasets = load_project(path)
            restored = datasets["Summary"]
            method, options = restored.analyses[0]
            result = analyse(method, restored.frame(), options)
            self.assertEqual(len(result.figure.axes), 1)


class UnequalSummaryTests(SummaryAnovaTests):
    """Welch, original Brown–Forsythe F* and all-pairs comparisons from summaries only."""

    def welch(self, **extra):
        return self.options(**{"Group": "Group", "Mean": "Mean", "Dispersion": "SD", "Sample size": "N",
                               "Post-hoc": "None", "Method": "Welch", **extra})

    def fixture(self):
        return pd.DataFrame({"Group": list("ABC"), "Mean": [10., 15., 18.], "SD": [2., 5., 3.], "N": [8, 12, 6]})

    def test_welch_matches_statsmodels_and_the_raw_engine(self):
        from statsmodels.stats.oneway import anova_oneway
        from analisi.inference import one_way_anova
        rng = np.random.default_rng(11)
        samples = [rng.normal(mean, sd, size) for mean, sd, size in ((0, 1, 8), (1, 3, 11), (-1, 2, 7))]
        frame = pd.DataFrame({"group": np.repeat(list("ABC"), [len(x) for x in samples]),
                              "y": np.concatenate(samples)})
        raw = one_way_anova(frame, "y", "group", method="welch")["ANOVA"].iloc[0]
        summary = pd.DataFrame({"group": list("ABC"),
                                "mean": [sample.mean() for sample in samples],
                                "sd": [sample.std(ddof=1) for sample in samples],
                                "n": [len(sample) for sample in samples]})
        result = summary_anova(summary, self.welch(**{"Group": "group", "Mean": "mean",
                                                      "Dispersion": "sd", "Sample size": "n"}))
        row = result.tables["ANOVA"].iloc[0]
        reference = anova_oneway(samples, use_var="unequal")
        for got, want in ((row["F"], raw["F"]), (row["F df2"], raw["F df2"]), (row["p"], raw["p"]),
                          (row["F"], reference.statistic), (row["p"], reference.pvalue)):
            self.assertAlmostEqual(got, want, places=8)
        self.assertNotIn("SS", result.tables["ANOVA"])
        self.assertNotIn("Pooled mean CI lower", result.tables["Summaries used"])
        self.assertEqual(result.tables["ANOVA"]["Term"].tolist(), ["Welch"])

    def test_equal_sizes_keep_the_welch_correction(self):
        data = pd.DataFrame({"mean": [1., 2., 4.], "sd": [1., 2., 3.], "n": [10, 10, 10]})
        columns = {"Group": None, "Mean": "mean", "Dispersion": "sd", "Sample size": "n"}
        welch = summary_anova(data, self.welch(**columns)).tables["ANOVA"].iloc[0]["F"]
        ordinary = summary_anova(data, self.options(**columns, **{"Post-hoc": "None"})).tables["ANOVA"].iloc[0]["F"]
        self.assertNotAlmostEqual(welch, ordinary, places=3)

    def test_two_groups_match_welch_t_squared(self):
        data = self.fixture().iloc[:2]
        variance = data.SD.to_numpy()**2 / data.N.to_numpy()
        statistic = (data.Mean.iloc[0] - data.Mean.iloc[1]) / np.sqrt(variance.sum())
        row = summary_anova(data, self.welch()).tables["ANOVA"].iloc[0]
        self.assertAlmostEqual(row["F"], statistic**2, places=10)
        self.assertEqual(row["F df1"], 1)

    def test_joint_reports_original_brown_forsythe_without_weighted_sums(self):
        from analisi.unequal_anova import brown_forsythe
        data = self.fixture()
        result = summary_anova(data, self.welch(**{"Method": "Welch and Brown–Forsythe"}))
        table = result.tables["ANOVA"]
        self.assertEqual(table["Term"].tolist(), ["Welch", "Brown–Forsythe"])
        self.assertEqual(list(table.columns), ["Term", "F", "F df1", "F df2", "p"])
        sizes, means, variances = data.N.to_numpy(float), data.Mean.to_numpy(float), data.SD.to_numpy(float)**2
        statistic, df1, df2, probability = brown_forsythe(sizes, means, variances)
        brown = table.iloc[1]
        self.assertAlmostEqual(brown["F"], statistic, places=8)
        self.assertAlmostEqual(brown["F df2"], df2, places=8)
        self.assertAlmostEqual(brown["p"], probability, places=8)
        self.assertEqual(brown["F df1"], df1)

    def test_games_howell_and_tamhane_use_pair_specific_se_and_df(self):
        data = self.fixture()
        level = 90
        for choice in ("Games–Howell", "Tamhane T2"):
            table = summary_anova(data, self.welch(**{"Post-hoc": choice, "Confidence level (%)": level})).tables["Multiple comparisons"]
            self.assertEqual(table["Method"].tolist(), [choice] * 3)
            self.assertEqual(list(table["Confidence level (%)"]), [level] * 3)
            self.assertGreater(table["df"].nunique(), 1)
            self.assertGreater(table["SE"].nunique(), 1)
            self.assertTrue(((table["Significant"]) == (table["Adjusted p"] < 1 - level / 100)).all())
        holm = summary_anova(data, self.welch(**{"Post-hoc": "Holm"})).tables["Multiple comparisons"]
        bonferroni = summary_anova(data, self.welch(**{"Post-hoc": "Bonferroni"})).tables["Multiple comparisons"]
        from statsmodels.stats.multitest import multipletests
        np.testing.assert_allclose(holm["Adjusted p"], multipletests(holm["p"], method="holm")[1])
        np.testing.assert_allclose(bonferroni["Adjusted p"], multipletests(bonferroni["p"], method="bonferroni")[1])
        self.assertNotIn("CI lower", holm)
        self.assertNotIn("CI lower", bonferroni)
        wide = summary_anova(data, self.welch(**{"Post-hoc": "Games–Howell", "Confidence level (%)": 90})).tables["Multiple comparisons"]
        narrow = summary_anova(data, self.welch(**{"Post-hoc": "Games–Howell"})).tables["Multiple comparisons"]
        np.testing.assert_array_equal(wide["p"], narrow["p"])
        self.assertTrue((wide["CI upper"] - wide["CI lower"] < narrow["CI upper"] - narrow["CI lower"]).all())

    def test_level_changes_pointwise_intervals_not_the_omnibus(self):
        low = summary_anova(self.fixture(), self.welch(**{"Confidence level (%)": 90}))
        high = summary_anova(self.fixture(), self.welch())
        np.testing.assert_array_equal(low.tables["ANOVA"]["F"], high.tables["ANOVA"]["F"])
        self.assertTrue((low.tables["Summaries used"]["Mean CI lower"] > high.tables["Summaries used"]["Mean CI lower"]).all())
        segments = high.figure.axes[0].containers[0].lines[2][0].get_segments()
        used = high.tables["Summaries used"]
        np.testing.assert_allclose([segment[:, 1] for segment in segments],
                                   np.column_stack((used["Mean CI lower"], used["Mean CI upper"])))
        self.assertIn("pointwise", high.figure.axes[0].get_legend().get_texts()[0].get_text().lower())
        self.assertNotIn("pooled", high.figure.axes[0].get_legend().get_texts()[0].get_text().lower())

    def test_scale_offset_and_conversion_keep_welch_finite(self):
        base = summary_anova(self.fixture(), self.welch()).tables["ANOVA"].iloc[0]
        for factor in (1e-120, 1e120, -4):
            frame = self.fixture()
            frame[["Mean", "SD"]] *= factor
            frame["SD"] = frame["SD"].abs()
            got = summary_anova(frame, self.welch()).tables["ANOVA"].iloc[0]
            self.assertAlmostEqual(got["F"], base["F"], places=7)
            self.assertAlmostEqual(got["p"], base["p"], places=8)
            self.assertTrue(np.isfinite([got["F"], got["F df2"], got["p"]]).all())
        offset = self.fixture()
        step = np.float64(2) ** 490
        origin = np.float64(2) ** 530
        offset["Mean"] = origin + np.array([0., 1., 2.]) * step
        offset["SD"] = step
        moved = pd.DataFrame({"Group": list("ABC"), "Mean": [0., 1., 2.], "SD": [1., 1., 1.], "N": offset.N})
        got = summary_anova(offset, self.welch()).tables["ANOVA"].iloc[0]
        want = summary_anova(moved, self.welch()).tables["ANOVA"].iloc[0]
        self.assertAlmostEqual(got["F"], want["F"], places=7)
        self.assertTrue(np.isfinite(got["p"]))
        sem = self.fixture()
        sem["SD"] = sem.SD / np.sqrt(sem.N)
        self.assertAlmostEqual(summary_anova(sem, self.welch(**{"Dispersion type": "SEM"})).tables["ANOVA"].iloc[0]["F"],
                               base["F"], places=8)

    def test_incompatible_choices_and_zero_dispersion_name_fields(self):
        data = self.fixture()
        cases = (({"Method": "bogus"}, "Method"), ({"Post-hoc": "Tukey"}, "Post-hoc"),
                 ({"Method": "Ordinary", "Post-hoc": "Games–Howell"}, "Post-hoc"),
                 ({"Method": "Ordinary", "Post-hoc": "Tamhane T2"}, "Post-hoc"))
        for extra, field in cases:
            with self.subTest(extra=extra), self.assertRaises(FieldError) as error:
                summary_anova(data, self.welch(**extra))
            self.assertEqual(error.exception.field, field)
        data.loc[0, "SD"] = 0
        with self.assertRaises(FieldError) as error:
            summary_anova(data, self.welch())
        self.assertEqual(error.exception.field, "Dispersion")
        ordinary = self.fixture()
        ordinary.loc[0, "SD"] = 0
        columns = {"Group": "Group", "Mean": "Mean", "Dispersion": "SD", "Sample size": "N"}
        self.assertTrue(np.isfinite(summary_anova(ordinary, self.options(**columns)).tables["ANOVA"].iloc[0]["F"]))

    def test_missing_method_matches_explicit_ordinary(self):
        columns = {"Group": "Group", "Mean": "Mean", "Dispersion": "SD", "Sample size": "N", "Post-hoc": "None"}
        implicit = summary_anova(self.fixture(), self.options(**columns))
        explicit = summary_anova(self.fixture(), self.options(**columns, **{"Method": "Ordinary"}))
        for name in implicit.tables:
            pd.testing.assert_frame_equal(implicit.tables[name], explicit.tables[name])
        self.assertIn("SS", implicit.tables["ANOVA"])
        self.assertIn("Pooled mean CI lower", implicit.tables["Summaries used"])
        self.assertIn("pooled variance", implicit.figure.axes[0].get_legend().get_texts()[0].get_text())

    def test_omitted_middle_group_keeps_original_rows_and_ignores_its_zero_sd(self):
        frame = self.fixture()
        missing = pd.DataFrame([{"Group": "missing", "Mean": 100., "SD": 0., "N": None}])
        frame = pd.concat([frame.iloc[:1], missing, frame.iloc[1:]], ignore_index=True)
        result = summary_anova(frame, self.welch(**{"Post-hoc": "Games–Howell"}))
        self.assertEqual(result.tables["Summaries used"]["Source row"].tolist(), [1, 3, 4])
        self.assertEqual(result.tables["Omitted groups"]["Source row"].tolist(), [2])
        self.assertEqual(result.tables["Multiple comparisons"]["First source row"].tolist(), [1, 1, 3])

    def test_duplicate_names_two_and_thirty_groups_and_large_n(self):
        frame = self.fixture()
        frame["Group"] = [1, "1", True]
        self.assertEqual(len(summary_anova(frame, self.welch(**{"Post-hoc": "Tamhane T2"})).tables["Multiple comparisons"]), 3)
        many = pd.DataFrame({"Mean": np.linspace(0, 5, 30), "SD": np.linspace(1, 2, 30), "N": np.full(30, 4)})
        result = summary_anova(many, self.welch(Group=None, **{"Post-hoc": "Bonferroni"}))
        self.assertEqual(len(result.tables["Summaries used"]), 30)
        self.assertEqual(len(result.tables["Multiple comparisons"]), 435)
        self.assertEqual(result.figure.axes[0].get_xticks().size, 30)
        too_many = pd.DataFrame({"Mean": np.arange(31.), "SD": np.ones(31), "N": np.full(31, 3)})
        with self.assertRaises(FieldError) as error:
            summary_anova(too_many, self.welch(Group=None))
        self.assertEqual(error.exception.field, "Mean")
        huge = self.fixture()
        huge["N"] = 10**9
        result = summary_anova(huge, self.welch())
        self.assertEqual(len(result.tables["Summaries used"]), 3)
        self.assertTrue(np.isfinite(result.tables["ANOVA"].iloc[0]["F df2"]))

    def test_equal_means_and_separated_means_reach_the_probability_bounds(self):
        equal = pd.DataFrame({"Mean": [5., 5., 5.], "SD": [1., 2., 3.], "N": [6, 7, 8]})
        row = summary_anova(equal, self.welch(Group=None, **{"Post-hoc": "Games–Howell"})).tables
        self.assertAlmostEqual(row["ANOVA"].iloc[0]["p"], 1)
        self.assertTrue((row["Multiple comparisons"]["p"] == 1).all())
        apart = pd.DataFrame({"Mean": [0., 1e13], "SD": [1e-3, 1e-3], "N": [12, 12]})
        compared = summary_anova(apart, self.welch(Group=None, **{"Post-hoc": "Tamhane T2"})).tables["Multiple comparisons"].iloc[0]
        self.assertEqual(compared["p"], 0)
        self.assertEqual(compared["Adjusted p"], 0)
        self.assertTrue(bool(compared["Significant"]))

    def test_settings_state_the_summary_assumptions(self):
        settings = summary_anova(self.fixture(), self.welch(**{"Post-hoc": "Holm"})).tables["Settings"]
        text = " ".join(map(str, settings["Value"]))
        self.assertIn("independent", text)
        self.assertIn("paired dependence", text)
        self.assertIn("normality", text)
        self.assertIn("distribution", text)
        self.assertIn("Holm", text)
        self.assertIn("95", text)

    def test_subcolumns_and_cv_match_the_row_input(self):
        data = self.fixture()
        expected = summary_anova(data, self.welch()).tables["ANOVA"].iloc[0]["F"]
        wide = pd.DataFrame({f"{row.Group} [{column}]": [getattr(row, column)]
                            for row in data.itertuples() for column in ("Mean", "SD", "N")})
        got = summary_anova(wide, {"Input": "Summary subcolumns", "Variables": list(wide), "Summary row": 1,
                                   "Dispersion type": "SD", "Method": "Welch", "Post-hoc": "None"})
        self.assertAlmostEqual(got.tables["ANOVA"].iloc[0]["F"], expected, places=8)
        cv = data.copy()
        cv["SD"] = 100 * cv.SD / cv.Mean
        self.assertAlmostEqual(summary_anova(cv, self.welch(**{"Dispersion type": "CV (%)"})).tables["ANOVA"].iloc[0]["F"],
                               expected, places=8)

class ExtremePrecisionRegressionTests(unittest.TestCase):
    def test_finite_precisions_with_overflowing_sum_match_decimal_oracle(self):
        from decimal import Decimal as D, localcontext
        with localcontext() as context:
            context.prec = 90
            means = [D('.49'), D('.5'), D('-.5')]
            sd = [D('2e-154'), D('2e-154'), D(1)]
            weights = [D(4) / error**2 for error in sd]
            fractions = [weight / sum(weights) for weight in weights]
            center = sum(weight * mean for weight, mean in zip(fractions, means))
            correction = sum((1 - weight)**2 / 3 for weight in fractions)
            expected_f = sum(weight * (mean-center)**2 for weight, mean in zip(weights, means)) / 2 / (1+correction/4)
            expected_df = 8 / (3*correction)
        for factor in (1., 1e80, 1e-80):
            with self.subTest(factor=factor):
                frame = pd.DataFrame({'Mean':np.array([.49,.5,-.5])*factor,
                                      'SD':np.array([2e-154,2e-154,1.])*factor, 'N':[4,4,4]})
                options = {'Mean':'Mean','Dispersion':'SD','Sample size':'N',
                           'Method':'Welch','Post-hoc':'Holm'}
                with np.errstate(over='raise', invalid='raise'):
                    result = summary_anova(frame, options)
                row = result.tables['ANOVA'].iloc[0]
                np.testing.assert_allclose([row['F'],row['F df2']],
                                           [float(expected_f),float(expected_df)],rtol=2e-12)
                pairs = result.tables['Multiple comparisons']
                self.assertAlmostEqual(pairs.iloc[0]['df'],6.)
                self.assertTrue(np.isfinite(pairs[['df','p','Adjusted p']]).all().all())
