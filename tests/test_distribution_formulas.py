"""Probability, density and quantile functions in worksheet formulas."""
import json
import math
from pathlib import Path
import re
from statistics import NormalDist
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from analisi.data import FUNCTIONS, Dataset, formula, load_project, load_tables, save_project
from analisi.distribution_formulas import DISTRIBUTION_FUNCTIONS
from analisi.select_transform import select_transform

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "distribution-formulas.md"
NORMAL = NormalDist()


def upper_normal(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


class DistributionFormulaTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Score": [-2., -1., 0., 1., 2., 9., np.nan],
            "Tail": [" left", "RIGHT ", "two", "One", "unknown", "right", ""],
            "Probability": [0.025, 0.5, 0.975, 0., 1., 1e-20, np.nan],
            "Spread": [2., 1., 0., -1., 0.5, 1., np.nan],
        }, index=[30, 7, 18, 12, 21, 10, 99])

    def evaluate(self, expression, frame=None):
        frame = self.frame if frame is None else frame
        before = frame.copy(deep=True)
        result = formula(frame, expression)
        self.assertTrue(result.index.equals(frame.index))
        pd.testing.assert_frame_equal(frame, before)
        return result.to_numpy(dtype=float)

    def assertValues(self, actual, expected, rtol=1e-13):
        self.assertEqual(len(actual), len(expected))
        for position, (got, want) in enumerate(zip(actual, expected, strict=True)):
            with self.subTest(position=position):
                if want is None:
                    self.assertTrue(math.isnan(got), got)
                elif want == 0:
                    self.assertLessEqual(abs(got), 1e-15)
                else:
                    self.assertLessEqual(abs(got - want), rtol * abs(want), (got, want))

    def test_registration_shares_the_worksheet_function_table(self):
        for name, entry in DISTRIBUTION_FUNCTIONS.items():
            self.assertIs(FUNCTIONS[name], entry)
        self.assertEqual(FUNCTIONS["ABS"][0], 1)
        self.assertEqual(FUNCTIONS["IF"][0], 3)

    def test_names_are_case_insensitive_and_defaults_apply(self):
        expected = [NORMAL.cdf(value) for value in (-2, -1, 0, 1, 2, 9)] + [None]
        for expression in ("NORMDIST(Score)", "normdist(Score, 0)", "NormDist(Score, 0, 1)",
                           'NORMDIST(Score, 0, 1, "LEFT")', "ZDIST(Score)", "=zdist(Score, ' left ')"):
            with self.subTest(expression=expression):
                self.assertValues(self.evaluate(expression), expected)

    def test_tail_column_is_read_row_by_row(self):
        values = self.evaluate("ZDIST(Score, Tail)")
        self.assertValues(values, [NORMAL.cdf(-2), upper_normal(-1), 1, upper_normal(1), None,
                                   upper_normal(9), None])
        conditional = self.evaluate('NORMDIST(Score, 0, 1, IF(Score > 0, "right", "left"))')
        self.assertValues(conditional, [NORMAL.cdf(-2), NORMAL.cdf(-1), 0.5, upper_normal(1),
                                        upper_normal(2), upper_normal(9), None])
        numeric_tail = self.evaluate("ZDIST(Score, Probability)")
        self.assertTrue(np.isnan(numeric_tail).all())

    def test_unknown_literal_tail_or_text_argument_is_a_formula_error(self):
        for expression in ('ZDIST(Score, "three")', "ZDIST(Score, 1)", 'NORMINV(Probability, 0, 1, " ")',
                           "NORMDIST(Score, 0, 1, True)"):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, "tail must be"):
                formula(self.frame, expression)
        with self.assertRaisesRegex(ValueError, "needs numbers"):
            formula(self.frame, 'NORMDIST("1")')
        with self.assertRaisesRegex(ValueError, "needs numbers"):
            formula(self.frame, 'TDIST(Score, IF(1 > 0, "a", "b"))')

    def test_wrong_argument_count_is_a_formula_error(self):
        cases = {"NORMPDF(Score, 0, 1, 2)": "NORMPDF takes 1 to 3 arguments", "ZPDF()": "ZPDF takes 1 argument",
                 "TDIST(Score)": "TDIST takes 2 arguments", "BINOMIAL(1, 2)": "BINOMIAL takes 3 arguments",
                 'NORMDIST(Score, 0, 1, "left", 5)': "NORMDIST takes 1 to 4 arguments"}
        for expression, message in cases.items():
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, message):
                formula(self.frame, expression)
        # Other names keep their previous contract and message.
        with self.assertRaisesRegex(ValueError, "Unsupported expression"):
            formula(self.frame, "ABS(Score, 2)")

    def test_symmetric_tails_and_their_inverses(self):
        z = np.array([-3.5, -0.2, 0., 0.7, 6.])
        frame = pd.DataFrame({"z": z, "x": 10 + 3 * z})
        self.assertValues(self.evaluate('NORMDIST(x, 10, 3, "one")', frame), [upper_normal(abs(v)) for v in z])
        self.assertValues(self.evaluate('ZDIST(z, "two")', frame), [2 * upper_normal(abs(v)) for v in z])
        p = pd.DataFrame({"p": [1e-300, 0.01, 0.5, 0.75, 1.]})
        self.assertValues(self.evaluate('ZINV(p, "one")', p),
                          [-NORMAL.inv_cdf(1e-300), -NORMAL.inv_cdf(0.01), 0, None, None])
        self.assertValues(self.evaluate('NORMINV(p, 10, 3, "two")', p),
                          [10 - 3 * NORMAL.inv_cdf(5e-301), 10 - 3 * NORMAL.inv_cdf(0.005),
                           10 - 3 * NORMAL.inv_cdf(0.25), 10 - 3 * NORMAL.inv_cdf(0.375), 10])
        self.assertValues(self.evaluate('ZINV(p, "right")', p),
                          [-NORMAL.inv_cdf(1e-300), -NORMAL.inv_cdf(0.01), 0, -NORMAL.inv_cdf(0.75), None])
        # Probability and inverse agree on every tail.
        for tail in ("left", "right", "one", "two"):
            with self.subTest(tail=tail):
                round_trip = self.evaluate(f'ZDIST(ZINV(p, "{tail}"), "{tail}")', p)
                finite = ~np.isnan(round_trip)
                # Near 1e-300 the tail amplifies the quantile's rounding by about z squared.
                np.testing.assert_allclose(round_trip[finite], p["p"].to_numpy()[finite], rtol=1e-12)

    def test_small_tails_keep_relative_precision(self):
        frame = pd.DataFrame({"x": [37.], "k": [60.]})
        cases = {
            'NORMDIST(x, 0, 1, "right")': upper_normal(37),
            'ZDIST(-x, "two")': 2 * upper_normal(37),
            "ERFC(26)": math.erfc(26),
            "ZINV(1e-300, \"right\")": -NORMAL.inv_cdf(1e-300),
            "TDIST(1e12, 1)": 1 / (math.pi * 1e12),
            "TINV(1e-200, 1)": 1 / math.tan(math.pi * 0.5e-200),
            "CHIDIST(1300, 2)": math.exp(-650),
            "CHIINV(1e-280, 2)": -2 * math.log(1e-280),
            "FDIST(1e250, 2, 2)": 1 / (1 + 1e250),
            "FINV(1e-250, 2, 2)": 1e250 - 1,
            "BINOMIAL(k, k, 0.001)": 1e-180,
            "PROBIT(1e-20)": 5 + NORMAL.inv_cdf(1e-20),
            # Beyond the range where the SciPy t and beta routines keep their tails.
            "TDIST(1e200, 1)": 1 / (math.pi * 1e200),
            "TPDF(1e150, 1)": 1 / (math.pi * 1e300),
            "TINV(1e-300, 1)": 2 / (math.pi * 1e-300),
            "TINV(1e-250, 2)": 1e125,
            "FINV(1e-300, 2, 2)": 1e300,
            "FPDF(1e200, 1, 1)": 1 / (math.pi * 1e300),
            # The upper tail of F(2, 2) is 1 / (1 + x), so p close to 1 gives x = (1 - p) / p.
            "FINV(1 - 1e-9, 2, 2)": (1 - (1 - 1e-9)) / (1 - 1e-9),
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertValues(self.evaluate(expression, frame), [expected], rtol=1e-12)
        # A quantile beyond the double range is blank.
        self.assertTrue(np.isnan(self.evaluate("TINV(1e-200, 0.5)", frame)).all())

    def test_normal_distribution_avoids_overflow_before_scaling(self):
        frame = pd.DataFrame({"x": [1.5e308]})
        self.assertValues(self.evaluate('NORMDIST(x, -1.5e308, 1.5e308, "right")', frame),
                          [upper_normal(2)])
        density = math.exp(-2) / math.sqrt(2 * math.pi) / 1.5e308
        self.assertValues(self.evaluate("NORMPDF(x, -1.5e308, 1.5e308)", frame), [density], rtol=1e-12)

    def test_normal_density_keeps_a_finite_result_after_scaling(self):
        frame = pd.DataFrame({"x": [4e-299]})
        expected = math.exp(-800 - math.log(1e-300)) / math.sqrt(2 * math.pi)
        self.assertValues(self.evaluate("NORMPDF(x, 0, 1e-300)", frame), [expected], rtol=1e-12)

    def test_two_tail_normal_quantile_accepts_subnormal_probability(self):
        from scipy.special import log_ndtr

        probability = math.ulp(0.0)
        frame = pd.DataFrame({"p": [probability]})
        quantile, = self.evaluate('ZINV(p, "two")', frame)
        self.assertTrue(math.isfinite(quantile))
        self.assertAlmostEqual(log_ndtr(-quantile), math.log(probability) - math.log(2), places=11)

    def test_closed_forms_for_t_chi_square_f_and_binomial(self):
        x = pd.DataFrame({"x": [0., 0.5, 3., 40.]})
        values = x["x"].tolist()
        self.assertValues(self.evaluate("TDIST(x, 2)", x), [0.5 * (1 - v / math.sqrt(2 + v * v)) for v in values])
        self.assertValues(self.evaluate("TPDF(x, 2)", x), [(2 + v * v) ** -1.5 for v in values])
        self.assertValues(self.evaluate("CHISQC(x, 2)", x), [-math.expm1(-v / 2) for v in values])
        self.assertValues(self.evaluate("FPDF(x, 2, 2)", x), [(1 + v) ** -2 for v in values])
        self.assertValues(self.evaluate("FPDF(x, 4, 2)", x), [8 * v / (1 + 2 * v) ** 3 for v in values])
        self.assertValues(self.evaluate("TINV(0.05, 1e6)", x), [-NORMAL.inv_cdf(0.025)] * 4, rtol=3e-6)
        # F(1, df) is t squared and chi-square(1) is z squared.
        self.assertValues(self.evaluate("FINV(0.05, 1, 30)", x), self.evaluate("TINV(0.05, 30) ^ 2", x))
        self.assertValues(self.evaluate("CHIINV(1e-9, 1)", x), self.evaluate('ZINV(1e-9, "two") ^ 2', x))
        counts = pd.DataFrame({"k": [0., 1., 3., 10., 11., 2.5, -1.]})
        expected = [sum(math.comb(10, j) * 0.3 ** j * 0.7 ** (10 - j) for j in range(int(k), 11))
                    if k == int(k) and 0 <= k <= 10 else None for k in counts["k"]]
        self.assertValues(self.evaluate("BINOMIAL(k, 10, 0.3)", counts), expected)
        self.assertValues(self.evaluate("BINOMIAL(0, 0, 0.4) + BINOMIAL(3, 3, 1) + BINOMIAL(2, 5, 0)", counts),
                          [2] * 7)

    def test_domains_leave_only_the_offending_rows_blank(self):
        frame = pd.DataFrame({"x": [1., -1., 2., np.nan, 3.], "df": [3., 3., 0., 3., -2.]})
        upper = math.erfc(math.sqrt(0.5)) + math.sqrt(2 / math.pi) * math.exp(-0.5)
        self.assertValues(self.evaluate("CHIDIST(x, df)", frame), [upper, None, None, None, None])
        self.assertValues(self.evaluate("NORMDIST(Score, 2, Spread, \"right\")"),
                          [upper_normal(-2), upper_normal(-3), None, None, upper_normal(0), upper_normal(7), None])
        cases = ["NORMINV(0, 0, 1)", "NORMINV(1, 0, 1)", "PROBIT(1)", "ZINV(0.6, \"one\")", "ZINV(1.01, \"two\")",
                 "TINV(0, 3)", "CHIINV(1.5, 2)", "FINV(-0.1, 2, 3)", "BINOMIAL(2, 1, 0.5)", "BINOMIAL(1, 3, 1.5)",
                 "BINOMIAL(1, 3.5, 0.5)", "FDIST(-1, 2, 3)", "FPDF(0, 1, 3)", "TPDF(1, 0)", "NORMPDF(0, 0, 0)",
                 "ERF(1e999)", "ZDIST(1e999)", "NORMDIST(1, 1e999)"]
        for expression in cases:
            with self.subTest(expression=expression):
                self.assertTrue(np.isnan(self.evaluate(expression)).all())
        self.assertValues(self.evaluate("TINV(1, 3) + CHIINV(1, 3) + FINV(1, 2, 3)"), [0] * 7)

    def test_scalars_broadcast_against_columns(self):
        constant = self.evaluate("CHIINV(0.25, 2)")
        self.assertValues(constant, [-2 * math.log(0.25)] * 7)
        mixed = self.evaluate("NORMINV(0.975, Score, 2)")
        self.assertValues(mixed, [value + 2 * NORMAL.inv_cdf(0.975) for value in (-2, -1, 0, 1, 2, 9)] + [None])
        nested = self.evaluate("ZPDF(ZINV(ZDIST(Score)))")
        # The left tail at 9 rounds to exactly 1, whose left quantile is infinite: that row is blank.
        self.assertValues(nested, [math.exp(-v * v / 2) / math.sqrt(2 * math.pi) for v in (-2, -1, 0, 1, 2)]
                          + [None, None], rtol=1e-9)

    def test_text_columns_are_read_as_numbers_where_possible(self):
        frame = pd.DataFrame({"Value": ["1", "abc", "", "2.5"]})
        self.assertValues(self.evaluate("ZPDF(Value)", frame),
                          [math.exp(-0.5) / math.sqrt(2 * math.pi), None, None,
                           math.exp(-3.125) / math.sqrt(2 * math.pi)])

    def test_complexity_limit_is_unchanged(self):
        expression = " + ".join(["ZDIST(Score)"] * 40)
        with self.assertRaisesRegex(ValueError, "too complex"):
            formula(self.frame, expression)

    def test_previous_formulas_still_work(self):
        frame = pd.DataFrame({"Group": ["a", "a", "b"], "Value": [1., 3., 5.]})
        self.assertEqual(formula(frame, "ABS(Value - 4) + POWER(2, 3)").tolist(), [11., 9., 9.])
        self.assertEqual(formula(frame, "MEAN(Value) OVER Group").tolist(), [2., 2., 5.])
        self.assertEqual(formula(frame, "ZDIST(Value - (MEAN(Value) OVER Group)) * 2").tolist()[2], 1.0)
        self.assertEqual(formula(frame, 'IF(Value > 2, "hi", "lo")').tolist(), ["lo", "hi", "hi"])


class DistributionFormulaWorksheetTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)

    def test_dataset_recalculates_after_edits_and_exclusions_and_reopens(self):
        data = Dataset(pd.DataFrame({"Statistic": [1., 2.5, 4.], "df": [3., 3., 3.]}))
        data.set_formula("P", "TDIST(Statistic, df) * 2")
        data.set_formula("Critical", "TINV(0.05, df)")
        data.raw.loc[0, "Statistic"] = 3
        data.excluded.add((2, 1))
        current = data.frame()
        # Two-sided t probability with 3 df in closed form.
        t = 3.0
        two_sided = 1 - 2 / math.pi * (math.atan(t / math.sqrt(3)) + t * math.sqrt(3) / (3 + t * t))
        self.assertAlmostEqual(current["P"][0], two_sided, places=14)
        self.assertTrue(math.isnan(current["P"][2]))
        self.assertTrue(math.isnan(current["Critical"][2]))
        self.assertEqual(current["df"].tolist(), [3., 3., 3.])
        project = self.path / "distributions.alab"
        save_project(project, {"Table": data})
        reopened = load_project(project)["Table"]
        self.assertEqual(reopened.formulas, data.formulas)
        # Reopened numeric columns may use the nullable dtype; the values must match.
        pd.testing.assert_frame_equal(reopened.frame(), current, check_dtype=False)

    def test_unknown_literal_tail_is_rejected_before_storing(self):
        data = Dataset(pd.DataFrame({"z": [1., 2.]}))
        with self.assertRaisesRegex(ValueError, "tail must be"):
            data.set_formula("P", 'ZDIST(z, "upper")')
        self.assertEqual(data.formulas, {})

    def write_archive(self, transforms):
        source = self.path / "distributions.prism"
        sets = {"a": {"title": "Measured score"}}
        for index, (title, transform) in enumerate(transforms):
            sets[f"c{index}"] = {"title": title, "valuesStorageData": {
                "@class": "TransformDataSource", "transform": transform}}
        with ZipFile(source, "w") as archive:
            archive.writestr("document.json", json.dumps({"sheets": {"data": ["synthetic"]}}))
            archive.writestr("data/sheets/synthetic/sheet.json", json.dumps({"title": "Scores", "table": {
                "uid": "values", "format": "multivariable", "dataFormat": "y_single", "dataSets": list(sets)}}))
            for uid, metadata in sets.items():
                archive.writestr(f"data/sets/{uid}.json", json.dumps(metadata))
            stored = ",".join(["999"] * len(transforms))
            archive.writestr("data/tables/values/data.csv", "".join(f"{v},{stored}\n" for v in (0, 1, 2)))
        return source

    def test_imported_formula_stays_live_and_editable(self):
        source = self.write_archive([("Upper probability", 'NORMDIST(A, 0, 1, "right")'),
                                     ("Density", "normpdf(A)")])
        sheet = Dataset(load_tables(source)["Scores"])
        self.assertEqual(list(sheet.raw), ["Measured score"])
        # The column letter becomes a reference to the linked column, the tail literal is kept.
        recipe = sheet.formulas["Upper probability"]
        self.assertRegex(recipe, r"^=NORMDIST\s*\(COL\s*\('Measured score'\)\s*,\s*0\s*,\s*1\s*,\s*\"right\"\s*\)$")
        np.testing.assert_allclose(sheet.frame()["Upper probability"], [0.5, upper_normal(1), upper_normal(2)],
                                   rtol=1e-14)
        sheet.raw.loc[1, "Measured score"] = 0
        sheet.excluded.add((2, 0))
        frame = sheet.frame()
        self.assertEqual(frame["Upper probability"].tolist()[:2], [0.5, 0.5])
        self.assertTrue(math.isnan(frame["Upper probability"][2]))
        sheet.set_formula("Upper probability", 'NORMDIST(COL("Measured score"), 0, 1, "two")')
        self.assertEqual(sheet.frame()["Upper probability"].tolist()[:2], [1.0, 1.0])
        project = self.path / "imported.alab"
        save_project(project, {"Scores": sheet})
        self.assertEqual(load_project(project)["Scores"].formulas, sheet.formulas)

    def test_imported_formula_outside_the_contract_keeps_stored_values(self):
        source = self.write_archive([("Bad tail", 'ZDIST(A, "upper")'), ("Bad arity", "TDIST(A)")])
        frame = load_tables(source)["Scores"]
        self.assertEqual(frame["Bad tail"].tolist(), [999, 999, 999])
        self.assertEqual(frame["Bad arity"].tolist(), [999, 999, 999])
        self.assertFalse(Dataset(frame).formulas)
        self.assertIn("Bad tail, Bad arity", frame.attrs["import_warnings"][0])

    def test_select_and_transform_uses_the_same_engine(self):
        data = pd.DataFrame({"t": [0., 2., 4.], "df": [5., 5., 5.]})
        result = select_transform(data, {"Variables": ["t"], "Calculated variables": [
            {"name": "P two-sided", "expression": "2 * TDIST(t, df)"}]}).tables["Selected data"]
        np.testing.assert_allclose(result["P two-sided"], 2 * formula(data, "TDIST(t, df)"), rtol=0)
        with self.assertRaisesRegex(ValueError, "tail must be"):
            select_transform(data, {"Calculated variables": [{"name": "Bad", "expression": 'ZDIST(t, "upper")'}]})


class DistributionGuideTests(unittest.TestCase):
    def test_guide_examples_reproduce(self):
        rows = re.findall(r"^\| `(=[^`]+)` \| ([-0-9.e]+|blank) \|", GUIDE.read_text(encoding="utf-8"), re.M)
        self.assertGreaterEqual(len(rows), 12)
        frame = pd.DataFrame({"Score": [1.0]})
        for expression, shown in rows:
            with self.subTest(expression=expression):
                value = float(formula(frame, expression)[0])
                if shown == "blank":
                    self.assertTrue(math.isnan(value))
                else:
                    digits = len(shown.split("e")[0].split(".")[-1]) if "." in shown else 0
                    tolerance = 0.5 * 10 ** -digits * (10 ** int(shown.split("e")[1]) if "e" in shown else 1)
                    self.assertLessEqual(abs(value - float(shown)), tolerance * 1.0000001, value)


if __name__ == "__main__":
    unittest.main()
