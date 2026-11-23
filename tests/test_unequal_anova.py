import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.oneway import anova_oneway

from analisi import inference
from analisi.processing import FieldError
from analisi.unequal_anova import (CONTROL, DUNNETT_T3, FAMILY, JOINT, LEVEL, PAIRS, TAMHANE, VERSUS_CONTROL,
                                  check_one_way_options, dunnett_t3)
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data" / "unequal-anova.csv"
FIELDS = ["F", "F df1", "F df2", "p"]


def samples(*groups):
    return pd.DataFrame([(f"G{i}", value) for i, group in enumerate(groups) for value in group],
                        columns=["Group", "Y"])


def run(frame, **options):
    return analyse("One-way ANOVA", frame, {"Response": "Y", "Group": "Group", "Method": JOINT,
                                            "Post-hoc": TAMHANE, **options})


class BrownForsytheTests(unittest.TestCase):
    def test_package_oracle(self):
        result = run(pd.read_csv(DATA))
        report = result.tables["ANOVA"].set_index("Method")
        np.testing.assert_allclose(report.loc["Welch one-way ANOVA", FIELDS].astype(float),
                                   [13.87265332380859, 2, 7.522026272909487, .0029937678909164205], rtol=1e-9)
        np.testing.assert_allclose(report.loc["Brown–Forsythe one-way ANOVA", FIELDS].astype(float),
                                   [18.744160177975527, 2, 7.987949235106872, .0009619513866704031], rtol=1e-9)
        pairs = result.tables["Multiple comparisons"]
        self.assertEqual(pairs[["First", "Second"]].values.tolist(), [["A", "B"], ["A", "C"], ["B", "C"]])
        np.testing.assert_allclose(pairs[["Difference", "Adjusted p", "CI low", "CI high"]].to_numpy(float)[0],
                                   [-8.5, .006109005995430185, -13.748998409297613, -3.251001590702386], rtol=1e-9)
        self.assertEqual(list(pairs.columns), ["First", "Second", "Difference", "SE", "df", "Method", "p",
                                               "Adjusted p", "CI low", "CI high", LEVEL])
        self.assertTrue((pairs[LEVEL] == 95).all() and (pairs["Method"] == TAMHANE).all())

    def test_statsmodels_pvalue2_and_unchanged_welch_row(self):
        rng = np.random.default_rng(4)
        groups = [rng.normal(0, 1, 7), rng.normal(1, 3, 12), rng.normal(.5, .5, 5), rng.normal(2, 2, 9)]
        frame = samples(*groups)
        joint = inference.one_way_anova(frame, "Y", "Group", method="welch-bf")["ANOVA"].set_index("Method")
        welch = inference.one_way_anova(frame, "Y", "Group", method="welch")["ANOVA"]
        reference = anova_oneway(groups, use_var="bf")
        row = joint.loc["Brown–Forsythe one-way ANOVA"]
        self.assertAlmostEqual(row["F"], reference.statistic)
        self.assertAlmostEqual(row["F df2"], reference.df_denom)
        self.assertAlmostEqual(row["p"], reference.pvalue2)
        pd.testing.assert_series_equal(joint.loc["Welch one-way ANOVA", FIELDS].astype(float),
                                       welch.iloc[0][FIELDS].astype(float),
                                       check_names=False)

    def test_two_groups_match_welch_t(self):
        a, b = [1., 4, 2, 8, 3], [9., 12, 10, 19, 15, 11, 30]
        result = inference.one_way_anova(samples(a, b), "Y", "Group", method="welch-bf", posthoc="tamhane", level=90)
        welch = stats.ttest_ind(a, b, equal_var=False)
        for _, row in result["ANOVA"].iterrows():
            self.assertAlmostEqual(row["F"], welch.statistic ** 2)
            self.assertAlmostEqual(row["F df2"], welch.df)
            self.assertAlmostEqual(row["p"], welch.pvalue)
        pair = result["Multiple comparisons"].iloc[0]
        self.assertAlmostEqual(pair["Adjusted p"], welch.pvalue)
        low, high = welch.confidence_interval(.90)
        self.assertAlmostEqual(pair["CI low"], low)
        self.assertAlmostEqual(pair["CI high"], high)

    def test_unequal_sizes_and_variances_use_sidak_family(self):
        groups = [[2., 3, 5, 4], [10., 2, 18, 6, 14, 9], [1., 1.5, 1.2, 1.4, 1.1, 1.3, 1.6, 1.2]]
        result = inference.one_way_anova(samples(*groups), "Y", "Group", method="welch", posthoc="tamhane")
        pairs = result["Multiple comparisons"]
        for (i, j), (_, row) in zip([(0, 1), (0, 2), (1, 2)], pairs.iterrows()):
            welch = stats.ttest_ind(groups[i], groups[j], equal_var=False)
            self.assertAlmostEqual(row["df"], welch.df)
            self.assertAlmostEqual(row["p"], welch.pvalue)
            self.assertAlmostEqual(row["Adjusted p"], 1 - (1 - welch.pvalue) ** 3)
            low, high = welch.confidence_interval((1 - .05) ** (1 / 3))
            self.assertAlmostEqual(row["CI low"], low)
            self.assertAlmostEqual(row["CI high"], high)

    def test_shifted_values_and_exclusions(self):
        frame = pd.read_csv(DATA)
        base = run(frame)
        shifted = run(frame.assign(Y=frame.Y + 1e9))
        for name in ("ANOVA", "Multiple comparisons"):
            numeric = base.tables[name].select_dtypes("number").columns.drop(LEVEL, errors="ignore")
            left, right = base.tables[name][numeric].to_numpy(float), shifted.tables[name][numeric].to_numpy(float)
            np.testing.assert_allclose(left, right, rtol=1e-6)
        excluded = frame.copy()
        excluded.loc[len(excluded)] = ["C", np.nan]
        excluded.loc[len(excluded)] = [np.nan, 99]
        pd.testing.assert_frame_equal(run(excluded).tables["ANOVA"], base.tables["ANOVA"])

    def test_group_requirements_name_group_and_field(self):
        for frame, problem in ((samples([1., 2], [3., 3, 3]), "G1 has zero variance"),
                               (samples([1., 2], [4.]), "G1 has a single observation")):
            with self.assertRaisesRegex(FieldError, problem) as raised:
                run(frame)
            self.assertEqual(raised.exception.field, "Response")
            self.assertIn("positive variance", str(raised.exception))

    def test_option_errors_name_their_field(self):
        frame = pd.read_csv(DATA)
        cases = [({"Method": "Ordinary"}, "Post-hoc"), ({"Post-hoc": "Tukey"}, "Post-hoc"),
                 ({LEVEL: 100.0}, LEVEL), ({LEVEL: float("nan")}, LEVEL), ({LEVEL: 0.0}, LEVEL)]
        for options, field in cases:
            with self.subTest(options=options), self.assertRaises(FieldError) as raised:
                run(frame, **options)
            self.assertEqual(raised.exception.field, field)
        check_one_way_options({"Method": "Ordinary", "Post-hoc": "Tukey", LEVEL: 400.0})

    def test_previous_recipes_keep_their_tables(self):
        frame = pd.read_csv(DATA)
        legacy = {"Response": "Y", "Group": "Group", "Method": "Welch", "Post-hoc": "Games–Howell"}
        result = analyse("One-way ANOVA", frame, legacy)
        self.assertEqual(result.tables["ANOVA"]["Method"].tolist(), ["Welch one-way ANOVA"])
        self.assertEqual(list(result.tables["Multiple comparisons"].columns),
                         ["First", "Second", "Difference", "SE", "df", "Method", "Adjusted p",
                          "CI 95% low", "CI 95% high"])
        joint = analyse("One-way ANOVA", frame, {**legacy, "Method": JOINT})
        pd.testing.assert_frame_equal(joint.tables["Multiple comparisons"], result.tables["Multiple comparisons"])


class DunnettT3Tests(unittest.TestCase):
    def test_all_pairs_at_95_percent(self):
        pairs = run(pd.read_csv(DATA), **{"Post-hoc": DUNNETT_T3}).tables["Multiple comparisons"]
        self.assertEqual(pairs["Method"].tolist(), [DUNNETT_T3] * 3)
        # Independent oracle integrates over the chi-square scale rather than the Gaussian maximum.
        np.testing.assert_allclose(pairs[["df", "Adjusted p", "CI low", "CI high"]].to_numpy(float), [
            [5.520787746170677, .0043098433549039845, -13.463078994630997, -3.5369210053690034],
            [7.941176470588235, .20624308576822747, -4.958008996264526, .9580089962645264],
            [6.248374512353707, .018404009307379787, 1.368633487389845, 11.631366512610155],
        ], rtol=1e-9)
        self.assertEqual(pairs["Distribution df"].tolist(), [6, 8, 6])
        self.assertTrue((pairs["Adjusted p"] >= pairs["p"]).all())

    def test_control_and_prespecified_pairs_use_family_size(self):
        frame = pd.read_csv(DATA)
        control = run(frame, **{"Post-hoc": DUNNETT_T3, FAMILY: VERSUS_CONTROL, CONTROL: "B", LEVEL: 90})
        pairs = control.tables["Multiple comparisons"]
        self.assertEqual(pairs[["First", "Second"]].values.tolist(), [["B", "A"], ["B", "C"]])
        np.testing.assert_allclose(pairs[["Adjusted p", "CI low", "CI high"]].to_numpy(float), [
            [.0029889071931038925, 4.792443241783971, 12.207556758216029],
            [.012857274097013018, 2.6667278289763168, 10.333272171023683],
        ], rtol=1e-9)
        selected = run(frame, **{"Post-hoc": DUNNETT_T3, FAMILY: PAIRS, PAIRS: [["C", "A"], ["A", "B"]], LEVEL: 90})
        pairs = selected.tables["Multiple comparisons"]
        self.assertEqual(pairs[["First", "Second"]].values.tolist(), [["C", "A"], ["A", "B"]])
        np.testing.assert_allclose(pairs["Adjusted p"], [.14827841066699868, .0029889071931038925], rtol=1e-9)

    def test_one_comparison_uses_t_with_the_method_specific_df(self):
        frame = pd.read_csv(DATA)
        for name in (DUNNETT_T3, TAMHANE):
            pairs = run(frame, **{"Post-hoc": name, FAMILY: PAIRS, PAIRS: [["A", "C"]], LEVEL: 90})
            row = pairs.tables["Multiple comparisons"].iloc[0]
            degrees = row.get("Distribution df", row["df"])
            p = 2 * stats.t.sf(abs(row["Difference"] / row["SE"]), degrees)
            half = stats.t.isf(.05, degrees) * row["SE"]
            np.testing.assert_allclose(row[["p", "Adjusted p", "CI low", "CI high"]].to_numpy(float),
                                       [p, p, row["Difference"] - half, row["Difference"] + half], rtol=1e-9)

    def test_reproduces_published_dunnett_t3_table(self):
        # The reference table reports rounded differences, standard errors and Welch df.
        _, adjusted, low, high = dunnett_t3(np.array([-35.87, 35.78]), np.array([11.69, 5.484]),
                                             np.array([7.492, 5.438]), 95)
        np.testing.assert_array_equal(np.round(adjusted, 4), [.0344, .0024])
        np.testing.assert_allclose(low, [-68.61, 18.83], rtol=0, atol=.025)
        np.testing.assert_allclose(high, [-3.122, 52.73], rtol=0, atol=.025)

    def test_scope_errors_name_the_control(self):
        frame = pd.read_csv(DATA)
        for options, field in [
            ({"Method": "Ordinary"}, "Post-hoc"),
            ({LEVEL: 0}, LEVEL),
            ({FAMILY: VERSUS_CONTROL, CONTROL: "Missing"}, CONTROL),
            ({FAMILY: PAIRS, PAIRS: []}, PAIRS),
            ({FAMILY: PAIRS, PAIRS: [["A", "B"], ["B", "A"]]}, PAIRS),
            ({FAMILY: "Other"}, FAMILY),
        ]:
            with self.subTest(options=options), self.assertRaises(FieldError) as error:
                run(frame, **{"Post-hoc": DUNNETT_T3, **options})
            self.assertEqual(error.exception.field, field)


class DunnettControlTests(unittest.TestCase):
    def test_ordinary_dunnett_against_scipy(self):
        frame = pd.read_csv(DATA)
        a, b, c = [frame.loc[frame.Group == name, "Y"].to_numpy() for name in ("A", "B", "C")]
        result = run(frame, **{"Method": "Ordinary", "Post-hoc": "Dunnett", CONTROL: "B", LEVEL: 90})
        rows = result.tables["Multiple comparisons"]
        self.assertEqual(rows[["First", "Second"]].values.tolist(), [["B", "A"], ["B", "C"]])
        reference = stats.dunnett(a, c, control=b, rng=42)
        intervals = reference.confidence_interval(.90)
        np.testing.assert_allclose(rows["Adjusted p"], reference.pvalue, atol=5e-4)
        np.testing.assert_allclose(rows["CI low"], -intervals.high, atol=.02)
        np.testing.assert_allclose(rows["CI high"], -intervals.low, atol=.02)
        self.assertEqual(rows[LEVEL].tolist(), [90, 90])

    def test_dunnett_requires_a_control_and_equal_variances(self):
        frame = pd.read_csv(DATA)
        for method, field in ((JOINT, "Post-hoc"), ("Ordinary", CONTROL)):
            with self.subTest(method=method), self.assertRaises(FieldError) as error:
                run(frame, **{"Method": method, "Post-hoc": "Dunnett"})
            self.assertEqual(error.exception.field, field)


if __name__ == "__main__":
    unittest.main()
