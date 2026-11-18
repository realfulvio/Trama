"""ANCOVA with adjusted means (0.90): engine contract, numerics, validation, figures and wording.

Synthetic data only. The frozen oracle in ``tests/data/ancova/expected.json`` was produced by statsmodels formula
OLS on the three small fixtures next to it. The other expectations are recomputed here from statsmodels and from
explicit algebra, never from the engine.
"""
from copy import deepcopy
from itertools import combinations
import json
from math import isclose
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy import stats

from analisi import i18n
from analisi.ancova import (ADJUSTMENTS, ANCOVA, COMPARISON_MODES, DOMAINS, ERRORS, GRAPHS, MAX_GROUPS, MAX_ROWS,
                            OPTIONS, SLOPE_MODELS, format_error, group_choices, reference_value, visibility)
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "ancova"
ORACLE = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
# name, file, slope model, reference, level, comparisons, control, adjustment
CASES = (
    ("pooled", "unbalanced.csv", "Common", None, 95, "All pairs", None, "Holm"),
    ("cross_left", "crossing.csv", "By group", 2, 90, "Against control", "Blue", "None"),
    ("cross_right", "crossing.csv", "By group", 4, 95, "All pairs", None, "Bonferroni"),
    ("extrapolated", "separated.csv", "Common", 3, 95, "None", None, "None"),
)
SHEETS = ("ANCOVA model", "ANCOVA tests", "Adjusted means", "ANCOVA contrasts", "ANCOVA fitted")


def opts(**overrides):
    return {"Response": "Y", "Covariate": "X", "Group": "Group", "Slope model": "Common", "Reference X": None,
            "Reference domain": "Common range", "Confidence level (%)": 95, "Comparisons": "All pairs",
            "Adjustment": "Holm", "Graph": "Fitted lines", **overrides}


def fixture(name):
    return pd.read_csv(DATA / name)


def synthetic(groups=4, seed=90, unbalanced=True):
    """A long table: a different line and a different number of points for every group, with noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(groups):
        count = 5 + (3 * k % 4 if unbalanced else 0)
        x = np.sort(rng.uniform(1, 9, count))
        y = 4 + 1.5 * k + (1.2 + 0.1 * k) * x + rng.normal(0, 0.6, count)
        rows += [(xi, yi, f"G{k}") for xi, yi in zip(x, y)]
    return pd.DataFrame(rows, columns=["X", "Y", "Group"])


def check_close(testcase, actual, expected, where, rel=1e-9):
    testcase.assertEqual(len(actual), len(expected), where)
    for index, (row, want) in enumerate(zip(actual, expected, strict=True)):
        for key, value in want.items():
            got = row[key]
            label = f"{where}[{index}].{key}"
            if isinstance(value, str) or isinstance(value, bool):
                testcase.assertEqual(got, value, label)
            else:
                testcase.assertTrue(isclose(got, value, rel_tol=rel, abs_tol=1e-12), f"{label}: {got} != {value}")


class FrozenOracle(unittest.TestCase):
    def test_every_case_matches_the_statsmodels_oracle(self):
        for name, file_name, mode, reference, level, comparisons, control, adjustment in CASES:
            domain = "Allow extrapolation" if name == "extrapolated" else "Common range"
            result = analyse(ANCOVA, fixture(file_name), opts(**{
                "Slope model": mode, "Reference X": reference, "Reference domain": domain,
                "Confidence level (%)": level, "Comparisons": comparisons, "Control group": control,
                "Adjustment": adjustment}))
            self.assertEqual(("ANCOVA contrasts" in result.tables), comparisons != "None", name)
            for sheet, rows in ORACLE[name].items():
                check_close(self, result.tables[sheet].to_dict("records"), rows, f"{name}/{sheet}")

    def test_sheet_order_and_status(self):
        result = analyse(ANCOVA, fixture("unbalanced.csv"), opts())
        self.assertEqual(list(result.tables), ["ANCOVA model", "ANCOVA tests", "Adjusted means", "ANCOVA contrasts",
                                               "ANCOVA fitted"])
        model = result.tables["ANCOVA model"]
        self.assertEqual(list(model.columns), ["N", "Groups", "Residual df", "RSS", "MSE", "Reference X",
                                               "Common lower", "Common upper", "Slope model", "Status", "Note"])
        self.assertEqual(model.loc[0, "Status"], "OK")
        self.assertEqual(model.loc[0, "Slope model"], "Common")
        self.assertIn("independent", model.loc[0, "Note"])
        self.assertTrue((result.tables["Adjusted means"]["Status"] == "OK").all())
        self.assertEqual(analyse(ANCOVA, fixture("unbalanced.csv"), opts(Comparisons="None")).tables.keys() & {"ANCOVA contrasts"},
                         set())

    def test_catalogue_registers_the_method_before_results_exist(self):
        self.assertIn(ANCOVA, METHODS)
        self.assertIn(ANCOVA, GROUPS["Group Comparison"])
        self.assertIn(ANCOVA, GRAPH_METHODS)
        self.assertEqual(list(METHODS[ANCOVA]), ["Response", "Covariate", "Group", "Slope model", "Reference X",
                                                 "Reference domain", "Comparisons", "Control group", "Adjustment",
                                                 "Confidence level (%)", "Graph"])
        self.assertEqual(METHODS[ANCOVA] is OPTIONS, True)
        self.assertEqual(OPTIONS["Slope model"], SLOPE_MODELS)
        self.assertEqual(OPTIONS["Reference domain"], DOMAINS)
        self.assertEqual(OPTIONS["Comparisons"], COMPARISON_MODES)
        self.assertEqual(OPTIONS["Adjustment"], ADJUSTMENTS)
        self.assertEqual(OPTIONS["Graph"], GRAPHS)

    def test_the_legacy_line_comparison_is_unchanged(self):
        result = analyse("Compare regression lines", fixture("crossing.csv"),
                         {"Input": "Long table", "X": "X", "Y": "Y", "Group": "Group"})
        self.assertEqual(list(result.tables), ["Regression lines", "Line comparison", "Summary"])
        np.testing.assert_allclose(result.tables["Regression lines"]["Slope"], [102 / 35, -2.6])

    def test_known_exact_contrasts_at_two_references(self):
        left = analyse(ANCOVA, fixture("crossing.csv"), opts(**{"Slope model": "By group", "Reference X": 2}))
        right = analyse(ANCOVA, fixture("crossing.csv"), opts(**{"Slope model": "By group", "Reference X": 4}))
        self.assertAlmostEqual(left.tables["ANCOVA contrasts"].loc[0, "Difference"], 43 / 105, places=12)
        self.assertAlmostEqual(right.tables["ANCOVA contrasts"].loc[0, "Difference"], 1201 / 105, places=12)


class Independent(unittest.TestCase):
    """Random unbalanced data against statsmodels, for both estimators and several levels and references."""

    def expected(self, frame, mode, reference, level):
        groups = list(pd.unique(frame.Group))
        data = frame.assign(z=frame.X - reference, g=pd.Categorical(frame.Group, categories=groups))
        common = smf.ols("Y ~ C(g) + z", data).fit()
        separate = smf.ols("Y ~ C(g) * z", data).fit()
        fit = common if mode == "Common" else separate
        null = smf.ols("Y ~ z" if mode == "Common" else "Y ~ z:C(g)", data).fit()
        at = pd.DataFrame({"g": groups, "z": 0.0})
        summary = fit.get_prediction(at).summary_frame(alpha=1 - level / 100)
        design = np.asarray(build_design_matrices([fit.model.data.model_spec], at)[0])
        contrasts = []
        for i, j in combinations(range(len(groups)), 2):
            test = fit.t_test(design[i] - design[j])
            effect, se = float(test.effect.item()), float(test.sd.item())
            margin = se * stats.t.isf((1 - level / 100) / 2, fit.df_resid)
            contrasts.append({"Difference": effect, "SE": se, "Lower": effect - margin, "Upper": effect + margin,
                              "t": float(test.tvalue.item()), "p": float(test.pvalue.item())})
        slopes = fit.predict(at.assign(z=1)).to_numpy() - summary["mean"].to_numpy()
        means = [{"Mean": row["mean"], "SE": row["mean_se"], "Lower": row["mean_ci_lower"],
                  "Upper": row["mean_ci_upper"], "Slope": slope} for (_, row), slope in zip(summary.iterrows(), slopes)]
        tests = [{"F": float(values[0]), "p": float(values[1]), "Denominator df": respective.df_resid}
                 for values, respective in ((separate.compare_f_test(common), separate), (fit.compare_f_test(null), fit))]
        return means, contrasts, tests, fit

    def test_means_tests_and_contrasts_follow_statsmodels(self):
        for groups, seed in ((3, 1), (5, 2), (7, 3)):
            frame = synthetic(groups, seed)
            for mode in SLOPE_MODELS:
                for reference, level in ((None, 95), (4.0, 80), (5.5, 99.5)):
                    ref = float(frame.X.mean()) if reference is None else reference
                    means, contrasts, tests, fit = self.expected(frame, mode, ref, level)
                    result = analyse(ANCOVA, frame, opts(**{"Slope model": mode, "Reference X": reference,
                                                            "Confidence level (%)": level, "Adjustment": "None",
                                                            "Reference domain": "Allow extrapolation"}))
                    where = f"{groups} groups, {mode}, ref {reference}, level {level}"
                    check_close(self, result.tables["Adjusted means"].to_dict("records"), means, where, rel=1e-8)
                    check_close(self, result.tables["ANCOVA contrasts"].to_dict("records"), contrasts, where, rel=1e-8)
                    check_close(self, result.tables["ANCOVA tests"].to_dict("records"), tests, where, rel=1e-8)
                    model = result.tables["ANCOVA model"].loc[0]
                    self.assertTrue(isclose(model["RSS"], fit.ssr, rel_tol=1e-9), where)
                    self.assertTrue(isclose(model["MSE"], fit.mse_resid, rel_tol=1e-9), where)
                    self.assertEqual(model["Residual df"], fit.df_resid, where)

    def test_fitted_and_residuals_add_up_to_the_observed(self):
        frame = synthetic(4)
        result = analyse(ANCOVA, frame, opts(**{"Slope model": "By group"}))
        fitted = result.tables["ANCOVA fitted"]
        np.testing.assert_allclose(fitted["Observed"] + 0, fitted["Fitted"] + fitted["Residual"], rtol=1e-12)
        np.testing.assert_allclose(fitted["Observed"], frame["Y"])
        self.assertAlmostEqual(float(fitted["Residual"].sum()), 0.0, places=9)
        self.assertAlmostEqual(float((fitted["Residual"] ** 2).sum()), result.tables["ANCOVA model"].loc[0, "RSS"], places=9)

    def test_the_common_and_separate_estimators_differ_when_slopes_differ(self):
        common = analyse(ANCOVA, fixture("crossing.csv"), opts(**{"Reference X": 3})).tables
        separate = analyse(ANCOVA, fixture("crossing.csv"), opts(**{"Reference X": 3, "Slope model": "By group"})).tables
        self.assertNotAlmostEqual(common["ANCOVA model"].loc[0, "RSS"], separate["ANCOVA model"].loc[0, "RSS"])
        self.assertFalse(np.allclose(common["Adjusted means"]["Mean"], separate["Adjusted means"]["Mean"]))
        self.assertEqual(common["Adjusted means"]["Slope"].nunique(), 1)
        self.assertEqual(separate["Adjusted means"]["Slope"].nunique(), 2)
        # The equal-slopes test is a diagnostic: it is identical for both estimators.
        self.assertEqual(common["ANCOVA tests"].loc[0, "F"], separate["ANCOVA tests"].loc[0, "F"])


class Groups(unittest.TestCase):
    def frame(self):
        return fixture("unbalanced.csv")

    def test_first_appearance_order_and_the_source_index_are_kept(self):
        frame = self.frame()
        frame["Group"] = frame["Group"].map({"A": "zebra", "B": "mango", "C": "apple"})
        frame.index = frame.index * 10 + 100
        result = analyse(ANCOVA, frame, opts())
        self.assertEqual(result.tables["Adjusted means"]["Group"].tolist(), ["zebra", "mango", "apple"])
        self.assertEqual(result.tables["ANCOVA fitted"]["Source row"].tolist(), frame.dropna().index.tolist())

    def test_rows_with_a_missing_value_leave_the_fit_and_keep_their_source_row(self):
        frame = synthetic(4)
        frame.index = frame.index + 1000
        damaged = frame.copy()
        damaged.loc[1005, "Y"] = np.nan
        damaged.loc[1013, "X"] = np.nan
        damaged.loc[1020, "Group"] = None
        damaged.loc[1021, "Group"] = "   "
        result = analyse(ANCOVA, damaged, opts(**{"Reference domain": "Allow extrapolation"}))
        gone = {1005, 1013, 1020, 1021}
        self.assertEqual(set(result.tables["ANCOVA fitted"]["Source row"]), set(frame.index) - gone)
        reference = analyse(ANCOVA, frame.drop(index=list(gone)), opts(**{"Reference domain": "Allow extrapolation"}))
        np.testing.assert_allclose(result.tables["Adjusted means"]["Mean"], reference.tables["Adjusted means"]["Mean"])
        self.assertEqual(result.tables["ANCOVA model"].loc[0, "N"], len(frame) - 4)

    def test_levels_with_the_same_text_but_other_types_are_different_groups(self):
        frame = self.frame()
        frame["Group"] = pd.Series(frame["Group"].map({"A": 1, "B": "1", "C": 1.0}), dtype=object)
        result = analyse(ANCOVA, frame, opts())
        # 1 and 1.0 are one group; the text 1 is another. Their labels tell the type.
        self.assertEqual(result.tables["Adjusted means"]["Group"].tolist(), ["1 (number)", "1 (text)"])
        complete = frame.dropna()
        self.assertEqual(result.tables["Adjusted means"]["N"].tolist(),
                         [int(complete.Group.isin([1, 1.0]).sum()), int((complete.Group == "1").sum())])
        frame["Group"] = frame["Group"].map({1: True}).where(frame["Group"] == 1, other="True")
        result = analyse(ANCOVA, frame, opts())
        self.assertEqual(sorted(result.tables["Adjusted means"]["Group"]), ["True (logical)", "True (text)"])

    def test_control_group_is_found_by_label_or_by_typed_value(self):
        frame = self.frame()
        frame["Group"] = pd.Series(frame["Group"].map({"A": 1, "B": "1", "C": 1.0}), dtype=object)
        for control in ("1 (number)", 1, 1.0):
            result = analyse(ANCOVA, frame, opts(Comparisons="Against control", **{"Control group": control}))
            self.assertEqual(result.tables["ANCOVA contrasts"].loc[0, ["First", "Second"]].tolist(),
                             ["1 (text)", "1 (number)"], control)
        text = analyse(ANCOVA, frame, opts(Comparisons="Against control", **{"Control group": "1"}))
        self.assertEqual(text.tables["ANCOVA contrasts"].loc[0, "Second"], "1 (text)")
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, frame.assign(Group=frame["Group"].map({1: "x1", "1": "x1 "})),
                    opts(Comparisons="Against control", **{"Control group": "x"}))
        self.assertEqual(raised.exception.field, "Control group")

    def test_control_group_errors(self):
        for control, key in ((None, "control_missing"), ("", "control_missing"), ("Z", "control_unknown")):
            with self.assertRaises(FieldError) as raised:
                analyse(ANCOVA, self.frame(), opts(Comparisons="Against control", **{"Control group": control}))
            self.assertEqual(raised.exception.field, "Control group", control)
            self.assertEqual(str(raised.exception), ERRORS[key].format(control=control), control)
        # Outside Against control the control group is ignored, even when it is nonsense.
        analyse(ANCOVA, self.frame(), opts(**{"Control group": "Z"}))

    def test_the_result_does_not_depend_on_the_order_of_the_rows(self):
        frame = synthetic(4)
        shuffled = frame.sample(frac=1, random_state=7)
        for mode in SLOPE_MODELS:
            first = analyse(ANCOVA, frame, opts(**{"Slope model": mode, "Reference X": 4.5})).tables
            second = analyse(ANCOVA, shuffled, opts(**{"Slope model": mode, "Reference X": 4.5})).tables
            one = first["Adjusted means"].set_index("Group").sort_index()
            two = second["Adjusted means"].set_index("Group").sort_index()
            np.testing.assert_allclose(one[["Mean", "SE", "Lower", "Upper", "Slope"]],
                                       two[["Mean", "SE", "Lower", "Upper", "Slope"]], rtol=1e-9)
            for column in ("F", "p"):
                np.testing.assert_allclose(first["ANCOVA tests"][column], second["ANCOVA tests"][column], rtol=1e-9)
            self.assertTrue(isclose(first["ANCOVA model"].loc[0, "RSS"], second["ANCOVA model"].loc[0, "RSS"], rel_tol=1e-9))

    def test_twelve_groups_are_the_most_and_fifty_thousand_rows_the_limit(self):
        rng = np.random.default_rng(12)
        frame = pd.DataFrame({"X": rng.uniform(0, 10, 36), "Group": np.repeat([f"g{k}" for k in range(12)], 3)})
        frame["Y"] = frame.X + rng.normal(size=36)
        result = analyse(ANCOVA, frame, opts(**{"Reference domain": "Allow extrapolation"}))
        self.assertEqual(result.tables["ANCOVA model"].loc[0, "Groups"], MAX_GROUPS)
        self.assertEqual(len(result.tables["ANCOVA contrasts"]), 66)
        extra = pd.concat([frame, pd.DataFrame({"X": [1., 2., 3.], "Y": [1., 2., 4.], "Group": "g12"})])
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, extra, opts(**{"Reference domain": "Allow extrapolation"}))
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("Group", ERRORS["many_groups"].format(maximum=MAX_GROUPS, count=13)))
        big = pd.DataFrame({"X": rng.uniform(0, 10, MAX_ROWS + 1), "Group": rng.choice(["a", "b"], MAX_ROWS + 1)})
        big["Y"] = big.X + rng.normal(size=len(big))
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, big, opts())
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("Group", ERRORS["many_rows"].format(maximum="50,000", count="50,001")))
        self.assertEqual(analyse(ANCOVA, big.iloc[:MAX_ROWS], opts()).tables["ANCOVA model"].loc[0, "N"], MAX_ROWS)

    def test_group_choices_for_the_dialog(self):
        frame = self.frame()
        columns = {"Response": "Y", "Covariate": "X", "Group": "Group"}
        self.assertEqual(group_choices(frame, columns), ["A", "B", "C"])
        self.assertEqual(group_choices(frame, {**columns, "Group": "X"}), [])
        self.assertEqual(group_choices(frame, {**columns, "Response": None}), [])
        self.assertEqual(group_choices(frame.rename(columns={"X": "Y"}), columns), [])
        many = pd.DataFrame({"X": np.arange(60.), "Y": np.arange(60.), "Group": [f"g{k}" for k in range(60)]})
        self.assertEqual(len(group_choices(many, columns)), 24)
        mixed = frame.assign(Group=pd.Series(frame["Group"].map({"A": 1, "B": "1", "C": 1.0}), dtype=object))
        self.assertEqual(group_choices(mixed, columns), ["1 (number)", "1 (text)"])
        self.assertEqual(group_choices(frame.assign(Y="text"), columns), [])


class Reference(unittest.TestCase):
    def two_supports(self):
        # A spans 0-2 and B spans 2-100: the common range is the single value 2 and the mean of X is far outside it.
        return pd.DataFrame({"X": [0., 1., 2., 2., 3., 100.], "Y": [1., 2.5, 2., 3., 5., 9.5],
                             "Group": ["A"] * 3 + ["B"] * 3})

    def test_the_reference_may_sit_on_the_edge_of_the_common_range(self):
        model = analyse(ANCOVA, self.two_supports(), opts(**{"Reference X": 2})).tables["ANCOVA model"].loc[0]
        self.assertEqual((model["Common lower"], model["Common upper"], model["Reference X"]), (2, 2, 2))

    def test_automatic_reference_outside_a_non_empty_range_is_reported_on_the_reference(self):
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, self.two_supports(), opts())
        self.assertEqual(raised.exception.field, "Reference X")
        self.assertEqual(str(raised.exception), ERRORS["outside_auto"].format(reference="18", low="2", high="2"))
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, self.two_supports(), opts(**{"Reference X": 2.5}))
        self.assertEqual(str(raised.exception), ERRORS["outside"].format(reference="2.5", low="2", high="2"))
        result = analyse(ANCOVA, self.two_supports(), opts(**{"Reference domain": "Allow extrapolation"}))
        self.assertEqual(result.tables["Adjusted means"]["Extrapolated"].tolist(), [True, False])
        self.assertAlmostEqual(result.tables["ANCOVA model"].loc[0, "Reference X"], 18.0)

    def test_disjoint_supports_need_the_explicit_opt_in(self):
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, fixture("separated.csv"), opts())
        self.assertEqual(raised.exception.field, "Reference domain")
        self.assertEqual(str(raised.exception), ERRORS["empty_range"].format(low="5", high="2"))
        result = analyse(ANCOVA, fixture("separated.csv"), opts(**{"Reference domain": "Allow extrapolation", "Reference X": 1}))
        means = result.tables["Adjusted means"]
        self.assertEqual(means["Extrapolated"].tolist(), [False, True])
        model = result.tables["ANCOVA model"].loc[0]
        self.assertGreater(model["Common lower"], model["Common upper"])

    def test_the_reference_changes_the_means_but_not_the_common_fit(self):
        frame = synthetic(4)
        one = analyse(ANCOVA, frame, opts(**{"Reference X": 4.5})).tables
        two = analyse(ANCOVA, frame, opts(**{"Reference X": 6, "Reference domain": "Allow extrapolation"})).tables
        for column in ("RSS", "MSE", "Residual df"):
            self.assertTrue(isclose(one["ANCOVA model"].loc[0, column], two["ANCOVA model"].loc[0, column], rel_tol=1e-9))
        np.testing.assert_allclose(one["Adjusted means"]["Slope"], two["Adjusted means"]["Slope"], rtol=1e-9)
        np.testing.assert_allclose(one["ANCOVA tests"]["F"], two["ANCOVA tests"]["F"], rtol=1e-8)
        np.testing.assert_allclose(two["Adjusted means"]["Mean"] - one["Adjusted means"]["Mean"],
                                   1.5 * one["Adjusted means"]["Slope"], rtol=1e-8)
        # Parallel lines: every difference between groups is the same at any reference.
        np.testing.assert_allclose(one["ANCOVA contrasts"]["Difference"], two["ANCOVA contrasts"]["Difference"], rtol=1e-8)
        np.testing.assert_allclose(one["ANCOVA contrasts"]["p"], two["ANCOVA contrasts"]["p"], rtol=1e-7)

    def test_the_separate_slope_differences_do_depend_on_the_reference(self):
        frame = fixture("crossing.csv")
        left = analyse(ANCOVA, frame, opts(**{"Slope model": "By group", "Reference X": 1})).tables
        right = analyse(ANCOVA, frame, opts(**{"Slope model": "By group", "Reference X": 4})).tables
        self.assertTrue(isclose(left["ANCOVA model"].loc[0, "RSS"], right["ANCOVA model"].loc[0, "RSS"], rel_tol=1e-9))
        self.assertLess(left["ANCOVA contrasts"].loc[0, "Difference"], right["ANCOVA contrasts"].loc[0, "Difference"])

    def test_reference_text_accepts_a_decimal_comma_and_blank(self):
        self.assertIsNone(reference_value({}))
        self.assertIsNone(reference_value({"Reference X": None}))
        self.assertIsNone(reference_value({"Reference X": "  "}))
        self.assertEqual(reference_value({"Reference X": "3,5"}), 3.5)
        self.assertEqual(reference_value({"Reference X": " -2.25e1 "}), -22.5)
        self.assertEqual(reference_value({"Reference X": 4}), 4.0)
        for bad in ("abc", "1,2,3", "inf", "nan", float("nan"), float("inf"), True, [3], "1e999", 10 ** 400):
            with self.assertRaises(FieldError, msg=repr(bad)) as raised:
                reference_value({"Reference X": bad})
            self.assertEqual(raised.exception.field, "Reference X")
        decimal = analyse(ANCOVA, fixture("unbalanced.csv"), opts(**{"Reference X": "3,5"}))
        self.assertEqual(decimal.tables["ANCOVA model"].loc[0, "Reference X"], 3.5)

    def test_a_far_reference_is_a_stable_error_not_a_wrong_answer(self):
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, synthetic(3), opts(**{"Reference X": 1e9, "Reference domain": "Allow extrapolation"}))
        self.assertEqual(raised.exception.field, "Reference X")
        self.assertIn("1000000000", str(raised.exception))


class Numerics(unittest.TestCase):
    def test_affine_units_of_the_covariate_and_the_response(self):
        frame = synthetic(4)
        base = analyse(ANCOVA, frame, opts()).tables
        scaled = frame.assign(X=frame.X * 1e-9 + 8e-9, Y=frame.Y * 1e6 - 5e5)
        other = analyse(ANCOVA, scaled, opts()).tables
        np.testing.assert_allclose(other["Adjusted means"]["Mean"], base["Adjusted means"]["Mean"] * 1e6 - 5e5, rtol=1e-9)
        np.testing.assert_allclose(other["Adjusted means"]["SE"], base["Adjusted means"]["SE"] * 1e6, rtol=1e-9)
        np.testing.assert_allclose(other["Adjusted means"]["Slope"], base["Adjusted means"]["Slope"] * 1e15, rtol=1e-8)
        np.testing.assert_allclose(other["ANCOVA tests"][["F", "p"]], base["ANCOVA tests"][["F", "p"]], rtol=1e-8)
        self.assertTrue(isclose(other["ANCOVA model"].loc[0, "RSS"], base["ANCOVA model"].loc[0, "RSS"] * 1e12, rel_tol=1e-9))

    def test_a_large_offset_in_the_covariate_does_not_cost_accuracy(self):
        frame = synthetic(3)
        base = analyse(ANCOVA, frame, opts()).tables
        shifted = analyse(ANCOVA, frame.assign(X=frame.X + 1e8), opts()).tables
        np.testing.assert_allclose(shifted["Adjusted means"][["Mean", "SE", "Slope"]],
                                   base["Adjusted means"][["Mean", "SE", "Slope"]], rtol=1e-6)
        np.testing.assert_allclose(shifted["ANCOVA tests"][["F", "p"]], base["ANCOVA tests"][["F", "p"]], rtol=1e-6)

    def test_an_exact_fit_has_zero_errors_and_no_inference(self):
        x = np.array([0., 1., 2., 3., 4., 5.])
        frame = pd.DataFrame({"X": np.tile(x, 2), "Y": np.r_[5 + 2 * x, 8 + 2 * x], "Group": ["A"] * 6 + ["B"] * 6})
        for scale in (1e-9, 1.0, 1e9):
            for mode in SLOPE_MODELS:
                result = analyse(ANCOVA, frame.assign(Y=frame.Y * scale), opts(**{"Slope model": mode, "Reference X": 2.5})).tables
                label = f"{mode} x{scale}"
                self.assertEqual(result["ANCOVA model"].loc[0, "Status"], "Exact fit", label)
                means = result["Adjusted means"]
                np.testing.assert_allclose(means["Mean"], np.array([10., 13.]) * scale, rtol=1e-9)
                self.assertTrue((means["SE"] == 0).all(), label)
                self.assertTrue(means[["Lower", "Upper"]].isna().all().all(), label)
                self.assertTrue((means["Status"] == "Exact fit").all(), label)
                tests = result["ANCOVA tests"]
                self.assertTrue(tests[["F", "p"]].isna().all().all(), label)
                self.assertTrue((tests["Status"] == "Exact fit").all(), label)
                contrast = result["ANCOVA contrasts"].loc[0]
                self.assertAlmostEqual(contrast["Difference"], -3 * scale, delta=1e-9 * scale)
                self.assertEqual(contrast["SE"], 0.0)
                self.assertTrue(np.isnan(contrast[["Lower", "Upper", "t", "p", "Adjusted p"]].astype(float)).all(), label)
                self.assertEqual(result["ANCOVA model"].loc[0, "RSS"], 0.0)
                self.assertIn("exact", result["ANCOVA model"].loc[0, "Note"])

    def test_noise_at_any_scale_is_not_an_exact_fit(self):
        frame = synthetic(3)
        base = analyse(ANCOVA, frame, opts()).tables
        for scale in (1e-12, 1e12):
            result = analyse(ANCOVA, frame.assign(Y=frame.Y * scale), opts()).tables
            self.assertEqual(result["ANCOVA model"].loc[0, "Status"], "OK", scale)
            np.testing.assert_allclose(result["ANCOVA tests"][["F", "p"]], base["ANCOVA tests"][["F", "p"]], rtol=1e-8)

    def test_a_group_that_is_exactly_linear_does_not_make_the_fit_exact(self):
        frame = synthetic(3)
        line = frame.Group == "G0"
        frame.loc[line, "Y"] = 3 + 2 * frame.loc[line, "X"]
        result = analyse(ANCOVA, frame, opts(**{"Slope model": "By group"})).tables
        self.assertEqual(result["ANCOVA model"].loc[0, "Status"], "OK")
        self.assertGreater(result["Adjusted means"].loc[1, "SE"], 0)
        self.assertGreater(result["Adjusted means"].loc[0, "SE"], 0)

    def test_a_constant_response_is_an_exact_fit(self):
        frame = synthetic(3).assign(Y=7.0)
        result = analyse(ANCOVA, frame, opts()).tables
        self.assertEqual(result["ANCOVA model"].loc[0, "Status"], "Exact fit")
        np.testing.assert_allclose(result["Adjusted means"]["Mean"], 7.0)
        np.testing.assert_allclose(result["Adjusted means"]["Slope"], 0.0, atol=1e-12)

    def test_values_that_overflow_are_reported_not_returned(self):
        frame = synthetic(3)
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, frame.assign(Y=frame.Y * 1e300 + np.r_[1e308, np.zeros(len(frame) - 1)]), opts())
        self.assertIn(raised.exception.field, ("Reference X", "Response"))


class Contrasts(unittest.TestCase):
    def tables(self, adjustment, comparisons="All pairs", frame=None, **extra):
        frame = synthetic(5) if frame is None else frame
        return analyse(ANCOVA, frame, opts(Adjustment=adjustment, Comparisons=comparisons, **extra)).tables

    def test_holm_is_a_step_down_over_the_ordered_p_values(self):
        table = self.tables("Holm")["ANCOVA contrasts"]
        p = table["p"].to_numpy()
        order = np.argsort(p)
        running, expected = 0.0, np.empty_like(p)
        for rank, index in enumerate(order):
            running = max(running, min(1.0, (len(p) - rank) * p[index]))
            expected[index] = running
        np.testing.assert_allclose(table["Adjusted p"], expected, rtol=1e-12)
        self.assertTrue((table["Adjusted p"] >= table["p"] - 1e-15).all())

    def test_bonferroni_none_and_a_single_comparison(self):
        bonferroni = self.tables("Bonferroni")["ANCOVA contrasts"]
        np.testing.assert_allclose(bonferroni["Adjusted p"], np.minimum(1, bonferroni["p"] * len(bonferroni)), rtol=1e-12)
        none = self.tables("None")["ANCOVA contrasts"]
        np.testing.assert_array_equal(none["Adjusted p"], none["p"])
        two = synthetic(2)
        for adjustment in ADJUSTMENTS:
            single = self.tables(adjustment, frame=two)["ANCOVA contrasts"]
            self.assertEqual(len(single), 1)
            self.assertEqual(single.loc[0, "Adjusted p"], single.loc[0, "p"], adjustment)

    def test_the_correction_changes_only_the_adjusted_p(self):
        reference = self.tables("None")
        for adjustment in ("Holm", "Bonferroni"):
            other = self.tables(adjustment)
            for sheet in reference:
                if sheet == "ANCOVA contrasts":
                    pd.testing.assert_frame_equal(other[sheet].drop(columns="Adjusted p"),
                                                  reference[sheet].drop(columns="Adjusted p"))
                else:
                    pd.testing.assert_frame_equal(other[sheet], reference[sheet])

    def test_the_comparison_modes_pick_their_pairs(self):
        pairs = self.tables("Holm")["ANCOVA contrasts"][["First", "Second"]].values.tolist()
        self.assertEqual(pairs, [list(pair) for pair in combinations([f"G{k}" for k in range(5)], 2)])
        against = self.tables("Holm", "Against control", **{"Control group": "G2"})["ANCOVA contrasts"]
        self.assertEqual(against[["First", "Second"]].values.tolist(),
                         [["G0", "G2"], ["G1", "G2"], ["G3", "G2"], ["G4", "G2"]])
        self.assertNotIn("ANCOVA contrasts", self.tables("Holm", "None"))

    def test_the_contrast_interval_uses_the_full_covariance_of_the_means(self):
        # With a common slope the adjusted means share the slope's error, so their covariance is not zero and the
        # interval of a difference is not the one a pooled-SE shortcut would give.
        frame = synthetic(3)
        table = analyse(ANCOVA, frame, opts(**{"Reference X": 2, "Reference domain": "Allow extrapolation"})).tables
        first, second = table["Adjusted means"].loc[0], table["Adjusted means"].loc[1]
        naive = np.hypot(first["SE"], second["SE"])
        self.assertNotAlmostEqual(table["ANCOVA contrasts"].loc[0, "SE"], naive, places=3)
        row = table["ANCOVA contrasts"].loc[0]
        self.assertAlmostEqual(row["Difference"], first["Mean"] - second["Mean"], places=10)
        half = stats.t.isf(0.025, row["df"]) * row["SE"]
        self.assertAlmostEqual(row["Upper"] - row["Lower"], 2 * half, places=10)
        self.assertAlmostEqual(row["t"], row["Difference"] / row["SE"], places=10)

    def test_the_confidence_level_widens_every_interval(self):
        narrow = analyse(ANCOVA, synthetic(3), opts(**{"Confidence level (%)": 80})).tables
        wide = analyse(ANCOVA, synthetic(3), opts(**{"Confidence level (%)": 99})).tables
        for sheet in ("Adjusted means", "ANCOVA contrasts"):
            self.assertTrue(((wide[sheet]["Upper"] - wide[sheet]["Lower"]) > (narrow[sheet]["Upper"] - narrow[sheet]["Lower"])).all())
        pd.testing.assert_series_equal(narrow["ANCOVA contrasts"]["p"], wide["ANCOVA contrasts"]["p"])


class Validation(unittest.TestCase):
    def raises(self, frame, options, where, key=None, **values):
        with self.assertRaises(FieldError) as raised:
            analyse(ANCOVA, frame, options)
        self.assertEqual(raised.exception.field, where, str(raised.exception))
        if key is not None:
            self.assertEqual(str(raised.exception), ERRORS[key].format(**values))

    def base(self):
        return fixture("unbalanced.csv")

    def test_roles(self):
        self.raises(self.base(), opts(Response=None), "Response", "choose", field="Response")
        self.raises(self.base(), opts(Covariate=""), "Covariate", "choose", field="Covariate")
        self.raises(self.base(), opts(Group=None), "Group", "choose", field="Group")
        self.raises(self.base(), opts(Response="Nope"), "Response", "exists", field="Response", column="Nope")
        self.raises(self.base(), opts(Covariate=3), "Covariate", "exists", field="Covariate", column=3)
        # A repeated column is reported on its second use, in the order Response, Covariate, Group.
        self.raises(self.base(), opts(Covariate="Y"), "Covariate", "different", field="Covariate", column="Y")
        self.raises(self.base(), opts(Group="Y"), "Group", "different", field="Group", column="Y")
        self.raises(self.base(), opts(Group="X"), "Group", "different", field="Group", column="X")
        self.raises(self.base(), opts(Response="X", Covariate="X", Group="X"), "Covariate", "different",
                    field="Covariate", column="X")

    def test_duplicate_worksheet_columns(self):
        frame = pd.DataFrame([[1., 2., 3., "a"]] * 6, columns=["X", "Y", "Y", "Group"])
        self.raises(frame, opts(), "Response", "unique")

    def test_choices_and_level(self):
        self.raises(self.base(), opts(**{"Slope model": "Nope"}), "Slope model", "slope_model")
        self.raises(self.base(), opts(**{"Reference domain": "Nope"}), "Reference domain", "domain")
        self.raises(self.base(), opts(Comparisons="Nope"), "Comparisons", "comparisons")
        self.raises(self.base(), opts(Adjustment="Tukey"), "Adjustment", "adjustment")
        self.raises(self.base(), opts(Graph="Nope"), "Graph", "graph")
        self.raises(self.base(), opts(**{"Slope model": 3}), "Slope model", "slope_model")
        for level in (0, 100, -5, 120, "abc", None, float("nan"), float("inf"), True):
            if level is None:
                continue
            self.raises(self.base(), opts(**{"Confidence level (%)": level}), "Confidence level (%)", "level")
        analyse(ANCOVA, self.base(), opts(**{"Confidence level (%)": "99,5"}))
        analyse(ANCOVA, self.base(), opts(**{"Confidence level (%)": 0.5}))

    def test_data_types_and_precision(self):
        frame = self.base()
        self.raises(frame.assign(X=["a"] * len(frame)), opts(), "Covariate", "text", column="X")
        self.raises(frame.assign(X=np.where(frame.index == 0, np.inf, frame.X)), opts(), "Covariate", "text", column="X")
        self.raises(frame.assign(Y=pd.Series(["x"] + [1.0] * (len(frame) - 1), dtype=object)), opts(), "Response", "text",
                    column="Y")
        self.raises(frame.assign(Y=frame.Y + 0j), opts(), "Response", "complex", column="Y")
        self.raises(frame.assign(X=2 ** 60 + np.arange(len(frame), dtype="int64")), opts(), "Covariate", "precision",
                    column="X")
        # Text that is a clean number is data, not an error.
        analyse(ANCOVA, frame.assign(X=frame.X.astype(str)), opts())

    def test_group_sizes_and_covariate_spread(self):
        frame = self.base()
        self.raises(frame.assign(Group="A"), opts(), "Group", "few_groups", minimum=2, count=1)
        small = pd.concat([frame, pd.DataFrame({"X": [1., 2.], "Y": [1., 2.], "Group": ["Z", "Z"]})])
        self.raises(small, opts(), "Group", "few_rows", group="Z", count=2, minimum=3)
        flat = frame.copy()
        flat.loc[flat.Group == "B", "X"] = 2.0
        self.raises(flat, opts(), "Covariate", "constant", group="B")
        # Values closer than a few units in the last place cannot be told apart either.
        near = frame.copy()
        near["X"] = near["X"] + 1e6
        near.loc[near.Group == "A", "X"] = 1e6 + np.arange((near.Group == "A").sum()) * 1e-12
        self.raises(near, opts(**{"Reference domain": "Allow extrapolation"}), "Covariate", "constant", group="A")

    def test_nothing_usable_in_the_columns(self):
        frame = self.base()
        self.raises(frame.assign(Group=None), opts(), "Group", "few_groups", minimum=2, count=0)
        self.raises(frame.assign(Y=np.nan), opts(), "Group", "few_groups", minimum=2, count=0)
        self.raises(frame.iloc[0:0], opts(), "Group", "few_groups", minimum=2, count=0)

    def test_the_input_frame_is_never_modified(self):
        frame = synthetic(4)
        frame.loc[2, "Y"] = np.nan
        before = frame.copy(deep=True)
        analyse(ANCOVA, frame, opts(Comparisons="Against control", **{"Control group": "G1", "Reference domain": "Allow extrapolation"}))
        pd.testing.assert_frame_equal(frame, before)


class Figures(unittest.TestCase):
    def gids(self, figure):
        axes = figure.axes[0]
        found = {child.get_gid() for child in axes.get_children() if child.get_gid()}
        return found

    def test_fitted_lines(self):
        result = analyse(ANCOVA, fixture("crossing.csv"), opts(**{"Slope model": "By group"}))
        self.assertEqual(len(result.figure.axes), 1)
        axes = result.figure.axes[0]
        gids = self.gids(result.figure)
        for group in ("Red", "Blue"):
            for part in ("points", "line", "mean"):
                self.assertIn(f"ancova:{part}:text:{group}", gids)
        self.assertIn("ancova:reference", gids)
        self.assertFalse(any(gid.startswith("ancova:extension:") for gid in gids))
        self.assertEqual((axes.get_xlabel(), axes.get_ylabel()), ("X", "Y"))
        self.assertEqual(axes._tramastat_numeric_axes, ("x", "y"))

    def test_the_extrapolated_part_of_a_line_is_drawn_apart(self):
        result = analyse(ANCOVA, fixture("separated.csv"), opts(**{"Reference domain": "Allow extrapolation", "Reference X": 1}))
        gids = self.gids(result.figure)
        self.assertIn("ancova:extension:text:B", gids)
        self.assertNotIn("ancova:extension:text:A", gids)

    def test_adjusted_means_and_residuals(self):
        for view, expected in (("Adjusted means", ("mean", "interval")), ("Residuals", ("residuals", "zero"))):
            result = analyse(ANCOVA, fixture("crossing.csv"), opts(Graph=view))
            self.assertEqual(len(result.figure.axes), 1, view)
            gids = self.gids(result.figure)
            for part in expected:
                self.assertTrue(any(gid.startswith(f"ancova:{part}") for gid in gids), (view, part))
        means = analyse(ANCOVA, fixture("crossing.csv"), opts(Graph="Adjusted means")).figure.axes[0]
        self.assertEqual(means._tramastat_categorical_axes, ("x",))
        self.assertEqual([label.get_text() for label in means.get_xticklabels()], ["Red", "Blue"])
        residuals = analyse(ANCOVA, fixture("crossing.csv"), opts(Graph="Residuals")).figure.axes[0]
        self.assertEqual((residuals.get_xlabel(), residuals.get_ylabel()), ("Fitted", "Residual"))

    def test_the_extrapolation_warning_of_the_adjusted_means_view(self):
        result = analyse(ANCOVA, fixture("separated.csv"), opts(Graph="Adjusted means", **{
            "Reference domain": "Allow extrapolation", "Reference X": 1}))
        self.assertIn("ancova:warning", self.gids(result.figure))
        quiet = analyse(ANCOVA, fixture("unbalanced.csv"), opts(Graph="Adjusted means"))
        self.assertNotIn("ancova:warning", self.gids(quiet.figure))

    def test_a_dollar_sign_in_a_name_stays_text(self):
        frame = fixture("crossing.csv").rename(columns={"X": "$dose", "Y": "$effect"}).assign(Group=lambda f: f["Group"] + "$")
        result = analyse(ANCOVA, frame, opts(Response="$effect", Covariate="$dose"))
        axes = result.figure.axes[0]
        self.assertEqual((axes.get_xlabel(), axes.get_ylabel()), (r"\$dose", r"\$effect"))

    def test_every_view_exists_for_both_estimators(self):
        for mode in SLOPE_MODELS:
            for view in GRAPHS:
                self.assertIsNotNone(analyse(ANCOVA, synthetic(3), opts(Graph=view, **{"Slope model": mode})).figure)


class Wording(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.active_language())

    def test_every_sentence_of_the_engine_has_an_italian_version(self):
        for key, text in ERRORS.items():
            english = i18n.CATALOGS["en"]["ancova.error." + key]
            italian = i18n.CATALOGS["it"]["ancova.error." + key]
            self.assertEqual(english, text, key)
            self.assertNotEqual(english, italian, key)
            self.assertEqual(i18n.placeholders(english), i18n.placeholders(italian), key)
        for key in i18n.CATALOGS["en"]:
            if key.startswith("ancova."):
                self.assertIn(key, i18n.CATALOGS["it"], key)
                self.assertEqual(i18n.placeholders(i18n.CATALOGS["en"][key]), i18n.placeholders(i18n.CATALOGS["it"][key]), key)
        for key in i18n.CATALOGS["it"]:
            if key.startswith("ancova.error."):
                self.assertIn(key.removeprefix("ancova.error."), ERRORS, key)

    def test_errors_are_shown_with_the_caption_of_their_field(self):
        error = FieldError("Slope model", ERRORS["slope_model"])
        i18n.set_language("en")
        self.assertEqual(format_error(error), ERRORS["slope_model"])
        i18n.set_language("it")
        shown = format_error(error)
        self.assertIn("Modello delle pendenze", shown)
        self.assertNotEqual(shown, ERRORS["slope_model"])
        self.assertEqual(shown.count("Modello delle pendenze"), 1)
        # A field name inside a sentence is translated; the column named in it is not.
        choose = format_error(FieldError("Covariate", ERRORS["choose"].format(field="Covariate")))
        self.assertIn("Covariata", choose)
        missing = format_error(FieldError("Response", ERRORS["exists"].format(field="Response", column="Mean")))
        self.assertIn('"Mean"', missing)
        self.assertIn("Risposta", missing)
        group = format_error(FieldError("Group", ERRORS["few_rows"].format(group="Mean", count=2, minimum=3)))
        self.assertIn('"Mean"', group)
        self.assertIsNone(format_error(FieldError("Alpha", "Alpha must be a number between 0 and 1.")))
        self.assertIsNone(format_error(ValueError("x")))

    def test_the_dialog_captions_are_catalogued(self):
        from analisi.i18n import KEY_BY_LABEL
        labels = [ANCOVA, *OPTIONS, *SLOPE_MODELS, *DOMAINS, *COMPARISON_MODES, *ADJUSTMENTS, *GRAPHS]
        i18n.set_language("it")
        for label in labels:
            self.assertIn(label, KEY_BY_LABEL, label)
        self.assertEqual(i18n.ui("Covariate"), "Covariata")
        self.assertEqual(i18n.ui("Adjusted means"), "Medie aggiustate")
        i18n.set_language("en")
        for label in labels:
            self.assertEqual(i18n.ui(label), label)

    def test_visibility_of_the_dependent_fields(self):
        self.assertEqual(visibility("All pairs"), {"Control group": False, "Adjustment": True})
        self.assertEqual(visibility("Against control"), {"Control group": True, "Adjustment": True})
        self.assertEqual(visibility("None"), {"Control group": False, "Adjustment": False})


class Recipes(unittest.TestCase):
    def test_options_survive_a_json_round_trip(self):
        """A saved recipe is plain JSON: numbers, text and null only."""
        saved = opts(Comparisons="Against control", **{"Control group": "Blue", "Reference X": 3.5, "Slope model": "By group",
                                                       "Confidence level (%)": 90.0, "Reference domain": "Allow extrapolation"})
        again = json.loads(json.dumps(saved))
        first = analyse(ANCOVA, fixture("crossing.csv"), deepcopy(saved)).tables
        second = analyse(ANCOVA, fixture("crossing.csv"), again).tables
        for sheet in first:
            pd.testing.assert_frame_equal(first[sheet], second[sheet])


if __name__ == "__main__":
    unittest.main()
