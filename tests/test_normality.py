import unittest

import numpy as np
import pandas as pd

from analisi.normality import (ALPHA, ANDERSON, DAGOSTINO, LILLIEFORS, QQ_LINE, QQ_PLOT, QQ_SETTINGS, QQ_SHEET,
                               QQ_VARIABLE, SHAPIRO, TESTS, check_options, qq_coordinates)
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Normality tests"
SAMPLE = [1, 2, 3, 4, 6, 9, 10, 12, 15, 18, 25, 45]
EXPECTED = {
    SHAPIRO: (0.8237707988021571, 0.017681958427951807),
    DAGOSTINO: (11.767997296660933, 0.0027836322249859663),
    ANDERSON: (0.7375964239663979, 0.03938164995234705),
    LILLIEFORS: (0.1826375264890639, 0.3330429843534023),
}
ALL_TESTS = {test: True for test in TESTS}


def run(frame, **options):
    return analyse(METHOD, frame, {"Variables": list(frame.columns), **options})


def sheet(result):
    return result.tables[METHOD]


class Oracles(unittest.TestCase):
    def test_reference_values_for_all_four_tests(self):
        result = run(pd.DataFrame({"v": SAMPLE}), **ALL_TESTS)
        table = sheet(result)
        self.assertEqual(table["Test"].tolist(), list(TESTS))
        self.assertEqual(table["N"].tolist(), [12] * 4)
        for _, row in table.iterrows():
            statistic, p = EXPECTED[row["Test"]]
            self.assertAlmostEqual(row["Statistic"], statistic, places=12)
            self.assertAlmostEqual(row["p"], p, places=12)
        self.assertEqual(table["Decision"].tolist(),
                         ["Reject normality", "Reject normality", "Reject normality", "Do not reject normality"])

    def test_clipped_probabilities_do_not_decide_at_unresolved_alpha(self):
        skewed = pd.DataFrame({"v": [0.] * 49 + [1.]})
        table = sheet(run(skewed, **{LILLIEFORS: True, ALPHA: .0001})).set_index("Test")
        self.assertEqual(table.at[LILLIEFORS, "Decision"], "Inconclusive at reported p limit")
        table = sheet(run(skewed, **{ANDERSON: True, ALPHA: 1e-33})).set_index("Test")
        self.assertEqual(table.at[ANDERSON, "Decision"], "Inconclusive at reported p limit")

    def test_location_and_scale_do_not_change_the_tests(self):
        base = sheet(run(pd.DataFrame({"v": SAMPLE}), **ALL_TESTS))
        for shifted in (np.array(SAMPLE) + 1000.0, np.array(SAMPLE) * 37.5, np.array(SAMPLE) * 0.001 - 4):
            other = sheet(run(pd.DataFrame({"v": shifted}), **ALL_TESTS))
            np.testing.assert_allclose(other["Statistic"], base["Statistic"], rtol=1e-9)
            np.testing.assert_allclose(other["p"], base["p"], rtol=1e-8, atol=1e-12)

    def test_extreme_magnitudes_rescale_and_keep_the_same_answer(self):
        base = sheet(run(pd.DataFrame({"v": SAMPLE}), **ALL_TESTS))
        for factor in (1e305, 1e-300):
            table = sheet(run(pd.DataFrame({"v": np.array(SAMPLE) * factor}), **ALL_TESTS))
            np.testing.assert_allclose(table["Statistic"], base["Statistic"], rtol=1e-9)
            np.testing.assert_allclose(table["p"], base["p"], rtol=1e-8)
            self.assertTrue(table["Note"].str.contains("rescaled").all())

    def test_two_sided_extremes_stay_finite(self):
        table = sheet(run(pd.DataFrame({"v": [-1.7e308, -1e308, 0, 3e307, 1e308, 1.7e308, 1.5e308, -1.2e308]}),
                          **ALL_TESTS))
        for _, row in table.iterrows():
            self.assertTrue(np.isfinite(row["Statistic"]) and np.isfinite(row["p"]), row.to_dict())

    def test_ties_use_the_values_as_given(self):
        values = [1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 6, 9]
        table = sheet(run(pd.DataFrame({"v": values}), **ALL_TESTS))
        self.assertTrue((table["N"] == 12).all() and table["Statistic"].notna().all())
        self.assertAlmostEqual(table.iloc[0]["p"], __import__("scipy.stats").stats.shapiro(values).pvalue, places=12)

    def test_default_options_choose_shapiro_only(self):
        defaults = {name: kind for name, kind in METHODS[METHOD].items()}
        self.assertTrue(defaults[SHAPIRO] is True)
        self.assertFalse(any(defaults[test] for test in TESTS[1:]))
        self.assertEqual(defaults[ALPHA], 0.05)
        self.assertEqual(sheet(run(pd.DataFrame({"v": SAMPLE}), **{ALPHA: .05}))["Test"].tolist(), [SHAPIRO])


class Domains(unittest.TestCase):
    def test_each_test_reports_its_domain_per_column(self):
        frame = pd.DataFrame({
            "two": [1.0, 2.0] + [np.nan] * 10,
            "three": [1.0, 2.0, 4.0] + [np.nan] * 9,
            "five": [1.0, 2.0, 4.0, 7.0, 8.5] + [np.nan] * 7,
            "seven": [1.0, 2.0, 4.0, 7.0, 8.5, 11.0, 12.5] + [np.nan] * 5,
            "eight": [1.0, 2.0, 4.0, 7.0, 8.5, 11.0, 12.5, 20.0] + [np.nan] * 4,
        })
        table = sheet(run(frame, **ALL_TESTS))
        ran = {(row["Variable"], row["Test"]) for _, row in table.iterrows() if row["Decision"] != "Not tested"}
        self.assertEqual({test for name, test in ran if name == "two"}, set())
        self.assertEqual({test for name, test in ran if name == "three"}, {SHAPIRO})
        self.assertEqual({test for name, test in ran if name == "five"}, {SHAPIRO, LILLIEFORS})
        self.assertEqual({test for name, test in ran if name == "seven"}, {SHAPIRO, LILLIEFORS})
        self.assertEqual({test for name, test in ran if name == "eight"}, set(TESTS))
        skipped = table[table["Decision"] == "Not tested"]
        self.assertTrue(skipped["Note"].str.len().gt(0).all())
        self.assertTrue(skipped["p"].isna().all() and skipped["Statistic"].isna().all())

    def test_shapiro_limit_leaves_the_other_tests_running(self):
        values = np.random.default_rng(3).normal(size=5001)
        table = sheet(run(pd.DataFrame({"v": values}), **ALL_TESTS))
        shapiro = table[table["Test"] == SHAPIRO].iloc[0]
        self.assertEqual(shapiro["Decision"], "Not tested")
        self.assertIn("5000", shapiro["Note"])
        self.assertTrue(table[table["Test"] != SHAPIRO]["p"].notna().all())
        edge = sheet(run(pd.DataFrame({"v": values[:5000]}), **{SHAPIRO: True}))
        self.assertTrue(edge["p"].notna().all())

    def test_constant_and_empty_columns_give_reasons_and_other_columns_run(self):
        frame = pd.DataFrame({"flat": [3.0] * 10, "empty": [np.nan] * 10, "ok": SAMPLE[:10]})
        table = sheet(run(frame, **ALL_TESTS))
        flat = table[table["Variable"] == "flat"]
        self.assertTrue((flat["Decision"] == "Not tested").all())
        self.assertTrue(flat["Note"].str.contains("identical").all())
        self.assertTrue(table[table["Variable"] == "empty"]["Note"].str.contains("No numeric").all())
        self.assertTrue((table[table["Variable"] == "empty"]["N"] == 0).all())
        self.assertTrue(table[table["Variable"] == "ok"]["p"].notna().all())

    def test_excluded_cells_are_missing(self):
        frame = pd.DataFrame({"v": SAMPLE + [None, None]})
        self.assertEqual(sheet(run(frame, **ALL_TESTS))["N"].tolist(), [12] * 4)

    def test_ordered_by_variable_then_test(self):
        frame = pd.DataFrame({"b": SAMPLE, "a": SAMPLE})
        table = sheet(run(frame, **ALL_TESTS))
        self.assertEqual(table["Variable"].tolist(), ["b"] * 4 + ["a"] * 4)
        self.assertEqual(table["Test"].tolist(), list(TESTS) * 2)

    def test_notes_describe_approximate_p_values(self):
        table = sheet(run(pd.DataFrame({"v": SAMPLE}), **ALL_TESTS)).set_index("Test")
        self.assertIn("Approximate", table.loc[ANDERSON, "Note"])
        self.assertIn("Tabulated", table.loc[LILLIEFORS, "Note"])
        values = np.exp(np.random.default_rng(1).normal(size=300) * 3)
        far = sheet(run(pd.DataFrame({"v": values}), **{SHAPIRO: False, LILLIEFORS: True}))
        self.assertIn("table ends", far.loc[0, "Note"])


class Options(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"a": SAMPLE, "b": SAMPLE[::-1], "t": list("abcdefghijkl")})

    def assertField(self, field, **options):
        with self.assertRaises(FieldError) as caught:
            run(self.frame()[["a", "b"]], **options)
        self.assertEqual(caught.exception.field, field)

    def test_alpha_must_be_finite_and_between_zero_and_one(self):
        for bad in (0, 1, -.1, 1.5, float("nan"), float("inf"), "0.05", None, True):
            self.assertField(ALPHA, **{ALPHA: bad})
        self.assertEqual(sheet(run(self.frame()[["a"]], **{ALPHA: .5})).loc[0, "Decision"], "Reject normality")
        self.assertEqual(sheet(run(self.frame()[["a"]], **{ALPHA: .01})).loc[0, "Decision"],
                         "Do not reject normality")

    def test_one_chosen_test_must_remain(self):
        self.assertField(SHAPIRO, **{test: False for test in TESTS})

    def test_flags_must_be_booleans(self):
        self.assertField(ANDERSON, **{ANDERSON: "yes"})
        self.assertField(QQ_PLOT, **{QQ_PLOT: 1})

    def test_variables_are_checked(self):
        frame = self.frame()
        for variables in ([], None, ["missing"], ["a", "a"]):
            with self.assertRaises(FieldError) as caught:
                analyse(METHOD, frame, {"Variables": variables, SHAPIRO: True})
            self.assertEqual(caught.exception.field, "Variables")

    def test_text_column_is_rejected_by_name(self):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, self.frame(), {"Variables": ["a", "t"], SHAPIRO: True})
        self.assertEqual(caught.exception.field, "Variables")
        self.assertIn('"t"', str(caught.exception))

    def test_infinite_values_are_rejected(self):
        with self.assertRaises(FieldError):
            run(pd.DataFrame({"v": SAMPLE[:-1] + [float("inf")]}), **ALL_TESTS)

    def test_duplicate_worksheet_names_are_rejected(self):
        frame = pd.DataFrame([SAMPLE, SAMPLE]).T
        frame.columns = ["v", "v"]
        with self.assertRaises(FieldError):
            analyse(METHOD, frame, {"Variables": ["v"], SHAPIRO: True})

    def test_check_options_matches_the_engine(self):
        check_options(self.frame(), {"Variables": ["a"], SHAPIRO: True})
        with self.assertRaises(FieldError) as caught:
            check_options(self.frame(), {"Variables": ["a", "b"], QQ_PLOT: True})
        self.assertEqual(caught.exception.field, QQ_VARIABLE)


class Legacy(unittest.TestCase):
    def test_recipes_without_new_options_keep_the_shapiro_sheet(self):
        frame = pd.DataFrame({"a": SAMPLE, "b": SAMPLE[::-1]})
        result = analyse(METHOD, frame, {"Variables": ["a", "b"]})
        self.assertEqual(list(result.tables), ["Normality"])
        table = result.tables["Normality"]
        self.assertEqual(table.index.name, "Variable")
        self.assertEqual(list(table.columns), ["N", "Shapiro–Wilk W", "p"])
        self.assertAlmostEqual(table.loc["a", "Shapiro–Wilk W"], EXPECTED[SHAPIRO][0], places=12)
        self.assertIsNone(result.figure)

    def test_legacy_recipes_still_reject_a_constant_column(self):
        with self.assertRaises(ValueError):
            analyse(METHOD, pd.DataFrame({"a": [1.0] * 5}), {"Variables": ["a"]})

    def test_any_new_option_selects_the_new_sheet(self):
        result = analyse(METHOD, pd.DataFrame({"a": SAMPLE}), {"Variables": ["a"], ALPHA: .05})
        self.assertEqual(list(result.tables), [METHOD])


class QQ(unittest.TestCase):
    def test_four_values_have_the_expected_quantiles(self):
        table = qq_coordinates(np.array([4.0, 1.0, 3.0, 2.0]), np.array([1, 2, 3, 4]))
        np.testing.assert_allclose(table["Theoretical quantile"],
                                   [-1.15034938, -0.31863936, 0.31863936, 1.15034938], atol=1e-8)
        self.assertEqual(table["Observed value"].tolist(), [1, 2, 3, 4])
        self.assertEqual(table["Source row"].tolist(), [2, 4, 3, 1])
        self.assertEqual(table["Plotting position"].tolist(), [.125, .375, .625, .875])
        self.assertEqual(table["Rank"].tolist(), [1, 2, 3, 4])

    def test_ties_keep_source_row_order(self):
        table = qq_coordinates(np.array([2.0, 1.0, 2.0, 2.0, 1.0]), np.array([5, 6, 8, 9, 12]))
        self.assertEqual(table["Source row"].tolist(), [6, 12, 5, 8, 9])

    def run_qq(self, frame, **options):
        return run(frame, **{QQ_PLOT: True, **options})

    def test_sheet_uses_the_chosen_column_and_skips_missing_rows(self):
        frame = pd.DataFrame({"first": [10, 20, 30, 40, 50], "second": [5, np.nan, 1, 9, 2]})
        result = self.run_qq(frame, **{QQ_VARIABLE: "second"})
        self.assertEqual(list(result.tables), [METHOD, QQ_SHEET, QQ_SETTINGS])
        table = result.tables[QQ_SHEET]
        self.assertEqual(table["Observed value"].tolist(), [1, 2, 5, 9])
        self.assertEqual(table["Source row"].tolist(), [3, 5, 1, 4])
        np.testing.assert_allclose(table["Theoretical quantile"],
                                   [-1.15034938, -0.31863936, 0.31863936, 1.15034938], atol=1e-8)
        self.assertEqual(result.tables[QQ_SETTINGS].loc["Variable", "Value"], "second")
        self.assertEqual(result.figure.axes[0].get_ylabel(), "Observed value (second)")
        self.assertTrue(table.dtypes.map(pd.api.types.is_numeric_dtype).all())

    def test_figure_points_and_reference_line(self):
        frame = pd.DataFrame({"v": SAMPLE})
        result = self.run_qq(frame)
        axes = result.figure.axes[0]
        offsets = np.asarray(axes.collections[0].get_offsets())
        table = result.tables[QQ_SHEET]
        np.testing.assert_allclose(offsets[:, 0], table["Theoretical quantile"])
        np.testing.assert_allclose(offsets[:, 1], table["Observed value"])
        line, = axes.lines
        x0, y0 = line.get_xy1()
        self.assertAlmostEqual(line.get_slope(), np.std(SAMPLE, ddof=1), places=9)
        self.assertAlmostEqual(y0 - line.get_slope() * x0, np.mean(SAMPLE), places=9)
        labels = [text.get_text() for text in axes.get_legend().get_texts()]
        self.assertTrue(any("Fitted normal: mean 12.5" in label and "× quantile" in label for label in labels))

    def test_line_is_optional(self):
        result = self.run_qq(pd.DataFrame({"v": SAMPLE}), **{QQ_LINE: False})
        axes = result.figure.axes[0]
        self.assertEqual(len(axes.lines), 0)
        self.assertIsNone(axes.get_legend())
        self.assertEqual(result.tables[QQ_SETTINGS].loc["Reference line", "Value"], "Not drawn")

    def test_constant_column_draws_points_without_a_line(self):
        result = self.run_qq(pd.DataFrame({"v": [2.0] * 6}))
        self.assertEqual(len(result.figure.axes[0].lines), 0)
        self.assertIn("variance", result.tables[QQ_SETTINGS].loc["Reference line", "Value"])

    def test_variable_must_be_explicit_when_several_are_selected(self):
        frame = pd.DataFrame({"a": SAMPLE, "b": SAMPLE})
        with self.assertRaises(FieldError) as caught:
            self.run_qq(frame)
        self.assertEqual(caught.exception.field, QQ_VARIABLE)
        with self.assertRaises(FieldError):
            self.run_qq(frame, **{QQ_VARIABLE: "zzz"})
        with self.assertRaises(FieldError):
            run(frame[["a"]], **{QQ_PLOT: True, QQ_VARIABLE: "b"})
        self.assertEqual(self.run_qq(frame[["a"]]).tables[QQ_SETTINGS].loc["Variable", "Value"], "a")

    def test_too_few_values_name_the_field(self):
        with self.assertRaises(FieldError) as caught:
            self.run_qq(pd.DataFrame({"v": [1.0, 2.0, np.nan]}))
        self.assertEqual(caught.exception.field, QQ_VARIABLE)

    def test_no_figure_without_the_option(self):
        result = run(pd.DataFrame({"v": SAMPLE}), **{QQ_PLOT: False})
        self.assertIsNone(result.figure)
        self.assertEqual(list(result.tables), [METHOD])

    def test_exports_png_and_svg(self):
        import io

        figure = self.run_qq(pd.DataFrame({"v": SAMPLE})).figure
        png, svg = io.BytesIO(), io.BytesIO()
        figure.savefig(png, format="png", dpi=100)
        figure.savefig(svg, format="svg")
        self.assertTrue(png.getvalue().startswith(b"\x89PNG"))
        self.assertIn(b"<svg", svg.getvalue())

    def test_extreme_values_keep_a_finite_line(self):
        result = self.run_qq(pd.DataFrame({"v": np.array(SAMPLE) * 1e305}))
        mean = float(result.tables[QQ_SETTINGS].loc["Mean", "Value"])
        self.assertAlmostEqual(mean / 1e305, 12.5, places=9)
        self.assertEqual(len(result.figure.axes[0].lines), 1)


if __name__ == "__main__":
    unittest.main()
