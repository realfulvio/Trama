"""Compare regression lines: nested F tests, input layouts, field errors and the graph."""
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analisi.compare_lines import COMPARISON, INDIVIDUAL, MODEL_VIEW, NOT_TESTED, TESTED, WIDE, visibility
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

METHOD = "Compare regression lines"
FIXTURE = Path(__file__).with_name("data") / "compare-lines.csv"
LONG = {"X": "X", "Y": "Y", "Group": "Group", "Alpha": .05}


def case(name):
    frame = pd.read_csv(FIXTURE)
    return frame[frame.Case == name].drop(columns="Case").reset_index(drop=True)


def run(frame, **options):
    return analyse(METHOD, frame, {**LONG, **options})


def tests(result):
    return result.tables["Line comparison"].set_index("Comparison")


def summary(result):
    return result.tables["Summary"]["Value"]


class Fixture(unittest.TestCase):
    def test_parallel_lines_have_different_elevations(self):
        result = run(case("Parallel"))
        lines = result.tables["Regression lines"]
        self.assertEqual(lines["Group"].tolist(), ["Control", "Treated"])
        self.assertEqual(lines["N"].tolist(), [4, 4])
        np.testing.assert_allclose(lines[["Intercept", "Slope"]], [[2, 2], [6, 2]], atol=1e-12)
        self.assertAlmostEqual(lines["SSE"].sum(), 12)
        report = tests(result)
        self.assertEqual(report["Status"].tolist(), [TESTED, TESTED])
        np.testing.assert_allclose(report.loc["Slopes", ["F", "df1", "df2", "p"]].astype(float), [0, 1, 4, 1],
                                   atol=1e-12)
        np.testing.assert_allclose(report.loc["Elevations", ["F", "df1", "df2", "p"]].astype(float),
                                   [40 / 3, 1, 5, .0147254010], rtol=1e-8)
        self.assertAlmostEqual(summary(result)["Common slope"], 2)
        self.assertIn("parallel", summary(result)["Conclusion"])

    def test_divergent_lines_skip_elevations_and_cross(self):
        result = run(case("Divergent"))
        lines = result.tables["Regression lines"]
        np.testing.assert_allclose(lines[["Intercept", "Slope"]], [[2, 2], [-2, 6]], atol=1e-12)
        report = tests(result)
        np.testing.assert_allclose(report.loc["Slopes", ["F", "df1", "df2", "p"]].astype(float),
                                   [40 / 3, 1, 4, .0217429785], rtol=1e-8)
        self.assertEqual(report.loc["Elevations", "Status"], NOT_TESTED)
        self.assertTrue(report.loc["Elevations", ["F", "df1", "df2", "p"]].isna().all())
        self.assertEqual(report.index.tolist(), ["Slopes", "Elevations"])
        values = summary(result)
        self.assertAlmostEqual(values["Intersection X"], 1)
        self.assertAlmostEqual(values["Intersection Y"], 4)
        self.assertIn("Within", values["Intersection note"])
        self.assertNotIn("Common slope", values)

    def test_identical_lines(self):
        result = run(case("Identical"))
        np.testing.assert_allclose(result.tables["Regression lines"][["Intercept", "Slope"]], [[2, 2], [2, 2]],
                                   atol=1e-12)
        np.testing.assert_allclose(tests(result)["p"], [1, 1], atol=1e-12)
        self.assertIn("No evidence", summary(result)["Conclusion"])
        self.assertAlmostEqual(summary(result)["Pooled slope"], 2)

    def test_intersection_outside_domain_is_annotated(self):
        frame = case("Divergent")
        frame.loc[frame.Group == "Treated", "X"] += 10
        values = summary(run(frame))
        self.assertIn("Outside", values["Intersection note"])


class Robustness(unittest.TestCase):
    def test_shifted_x_and_reversed_rows_leave_tests_unchanged(self):
        base = tests(run(case("Parallel")))
        shifted = case("Parallel").assign(X=lambda f: f.X + 1e6).iloc[::-1].reset_index(drop=True)
        result = run(shifted)
        self.assertEqual(result.tables["Regression lines"]["Group"].tolist(), ["Treated", "Control"])
        np.testing.assert_allclose(tests(result)[["F", "p"]].astype(float), base[["F", "p"]].astype(float),
                                   rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(result.tables["Regression lines"]["Slope"], [2, 2], atol=1e-7)
        np.testing.assert_allclose(result.tables["Regression lines"]["Intercept"], [6 - 2e6, 2 - 2e6], rtol=1e-12)

    def test_three_groups_match_independent_ols(self):
        rng = np.random.default_rng(7)
        x = np.tile(np.arange(6.), 3)
        group = np.repeat(["a", "b", "c"], 6)
        y = 1 + np.array([.5, .7, .6]).repeat(6) * x + rng.normal(0, .4, 18) + np.repeat([0, 1, 2], 6)
        frame = pd.DataFrame({"X": x, "Y": y, "Group": group})
        full = smf.ols("Y ~ C(Group) * X", frame).fit()
        parallel = smf.ols("Y ~ C(Group) + X", frame).fit()
        identical = smf.ols("Y ~ X", frame).fit()
        result = run(frame, Alpha=.001)
        lines = result.tables["Regression lines"]
        self.assertAlmostEqual(lines["SSE"].sum(), full.ssr, places=9)
        report = tests(result)
        f = ((parallel.ssr - full.ssr) / 2) / (full.ssr / full.df_resid)
        np.testing.assert_allclose(report.loc["Slopes", ["F", "df1", "df2"]].astype(float), [f, 2, 12], rtol=1e-9)
        if report.loc["Slopes", "p"] >= .001:
            g = ((identical.ssr - parallel.ssr) / 2) / (parallel.ssr / parallel.df_resid)
            np.testing.assert_allclose(report.loc["Elevations", ["F", "df1", "df2"]].astype(float), [g, 2, 14],
                                       rtol=1e-9)
        for name, row in lines.set_index("Group").iterrows():
            single = smf.ols("Y ~ X", frame[frame.Group == name]).fit()
            np.testing.assert_allclose([row.Intercept, row.Slope], single.params, rtol=1e-10)
            np.testing.assert_allclose([row["Intercept SE"], row["Slope SE"]], single.bse, rtol=1e-9)

    def test_wide_layout_uses_every_replicate(self):
        long = case("Divergent")
        wide = pd.DataFrame({"X": [0., 1, 2, 3], "Control": [3., 2, 7, 8], "Treated": [-1., 2, 11, 16]})
        a, b = run(long), analyse(METHOD, wide, {"Input": WIDE, "X": "X", "Y columns": ["Control", "Treated"]})
        pd.testing.assert_frame_equal(a.tables["Line comparison"], b.tables["Line comparison"])
        pd.testing.assert_frame_equal(a.tables["Regression lines"], b.tables["Regression lines"])

    def test_wide_replicate_subcolumns_and_duplicate_x(self):
        wide = pd.DataFrame({"X": [0., 0, 1, 2, 3], "C [1]": [3., 4, 2, 7, 8], "C [2]": [2., np.nan, 3, 6, 9],
                             "T [1]": [7., 6, 6, 11, 12], "T [2]": [8., 7, 5, 10, np.nan]})
        wide.attrs["worksheet_roles"] = {"x": ["X"], "y": [["C [1]", "C [2]"], ["T [1]", "T [2]"]]}
        options = {"Input": WIDE, "X": "X", "Y columns": ["C [1]", "C [2]", "T [1]", "T [2]"]}
        result = analyse(METHOD, wide, options)
        lines = result.tables["Regression lines"]
        self.assertEqual(lines["Group"].tolist(), ["C", "T"])
        self.assertEqual(lines["N"].tolist(), [9, 9])
        long = pd.DataFrame({"X": [0, 0, 0, 1, 1, 2, 2, 3, 3] + [0, 0, 0, 0, 1, 1, 2, 2, 3],
                             "Y": [3, 2, 4, 2, 3, 7, 6, 8, 9, 7, 8, 6, 7, 6, 5, 11, 10, 12],
                             "Group": ["C"] * 9 + ["T"] * 9})
        pd.testing.assert_frame_equal(tests(result), tests(run(long)))
        # Excluding one replicate cell (masked as missing) drops only that observation.
        masked = wide.copy()
        masked.attrs = wide.attrs
        masked.loc[4, "T [1]"] = np.nan
        self.assertEqual(analyse(METHOD, masked, options).tables["Regression lines"]["N"].tolist(), [9, 8])

    def test_ordinary_wide_columns_are_separate_series(self):
        wide = pd.DataFrame({"X": [0., 1, 2, 3], "A [1]": [1., 2, 4, 3], "A [2]": [2., 2, 3, 5], "B": [0., 3, 5, 9]})
        result = analyse(METHOD, wide, {"Input": WIDE, "X": "X", "Y columns": ["A [1]", "A [2]", "B"]})
        self.assertEqual(result.tables["Regression lines"]["Group"].tolist(), ["A [1]", "A [2]", "B"])

    def test_incomplete_rows_are_left_out(self):
        frame = case("Parallel")
        frame.loc[len(frame)] = [None, 9, 9]
        frame.loc[len(frame)] = ["Control", np.nan, 5]
        frame.loc[len(frame)] = ["Control", 4, np.nan]
        np.testing.assert_allclose(tests(run(frame))["p"], tests(run(case("Parallel")))["p"], equal_nan=True)


class Errors(unittest.TestCase):
    def assertField(self, field, frame, **options):
        with self.assertRaises(FieldError) as raised:
            run(frame, **options)
        self.assertEqual(raised.exception.field, field)
        return str(raised.exception)

    def test_field_errors(self):
        frame = case("Parallel")
        for alpha in (0, 1, -.1, float("nan"), float("inf"), "x", True):
            self.assertField("Alpha", frame, Alpha=alpha)
        constant = frame.assign(X=lambda f: np.where(f.Group == "Treated", 1., f.X))
        self.assertIn("single X", self.assertField("X", constant))
        short = frame.drop(index=[4, 5]).reset_index(drop=True)
        self.assertIn('"Treated" has 2', self.assertField("Group", short))
        self.assertIn("at least two groups", self.assertField("Group", frame[frame.Group == "Control"]))
        text = frame.astype({"Y": object})
        text.loc[2, "Y"] = "seven"
        self.assertField("Y", text)
        self.assertField("X", frame.assign(X=lambda f: f.X.replace(3, np.inf)))
        self.assertField("Group", frame, Group="X")
        exact = frame.assign(Y=lambda f: 1 + f.X)
        self.assertField("Group", exact)
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"Input": WIDE, "X": "X", "Y columns": ["X", "Y"]})
        self.assertEqual(raised.exception.field, "Y columns")


class Catalog(unittest.TestCase):
    def test_catalog_and_visibility(self):
        self.assertIn(METHOD, GROUPS["Regression and Curves"])
        self.assertEqual(GROUPS["Regression and Curves"].index(METHOD), 1)
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertIn("Alpha", METHODS[METHOD])
        self.assertEqual(visibility(WIDE), {"Y": False, "Group": False, "Y columns": True})
        self.assertEqual(visibility("Long table"), {"Y": True, "Group": True, "Y columns": False})

    def test_graph_and_model_view(self):
        divergent = run(case("Divergent"))
        axes = divergent.figure.axes[0]
        gids = sorted(line.get_gid() for line in axes.lines)
        self.assertEqual(gids, ["lines:line:Control", "lines:line:Treated"])
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()], ["Control", "Treated"])
        x, y = axes.lines[1].get_data()
        np.testing.assert_allclose(x, [0, 3])
        np.testing.assert_allclose(y, [-2, 16])
        parallel = run(case("Parallel"), **{MODEL_VIEW: COMPARISON})
        slopes = [np.diff(line.get_ydata())[0] / np.diff(line.get_xdata())[0]
                  for line in parallel.figure.axes[0].lines]
        np.testing.assert_allclose(slopes, [2, 2])
        identical = run(case("Identical"), **{MODEL_VIEW: COMPARISON})
        self.assertEqual([line.get_gid() for line in identical.figure.axes[0].lines], ["lines:line:pooled"])
        # The individual estimates stay in the sheet whatever the graph shows.
        pd.testing.assert_frame_equal(identical.tables["Regression lines"],
                                      run(case("Identical"), **{MODEL_VIEW: INDIVIDUAL}).tables["Regression lines"])

    def test_linear_regression_unchanged(self):
        result = analyse("Linear regression", case("Parallel"), {"X": "X", "Y": "Y"})
        self.assertIsNotNone(result.figure)


if __name__ == "__main__":
    unittest.main()
