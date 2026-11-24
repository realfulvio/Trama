"""Yuen's two-sample trimmed-mean test: contract, worksheet recipe and the untouched Welch and permutation results."""
import math
from pathlib import Path
import time
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import yuen
from analisi.field_error import FieldError
from analisi.i18n import set_language, ui
from analisi.mean_permutation import METHOD as PERMUTATION_METHOD
from analisi.workbench import GRAPH_METHODS, GROUPS, analyse
from analisi.yuen_text import text

CASES = (
    ([1, 2, 3, 4, 100], [2, 4, 5, 6, 8, 201], 0.2),
    ([1, 2, 3, 4, 5], [2, 4, 5, 6, 8, 201], 0.0),
    ([2] * 5, [3, 4, 5, 7, 9], 0.2),
    ([1, 3, 5, 8, 12, 14, 18, 30, 200, 400], [-70, -9, -1, 2, 3, 5, 7, 9, 10, 100], 0.3),
)
EXAMPLE = Path(__file__).resolve().parent / "data" / "yuen" / "columns.csv"

# Snapshots of the engines this change must not touch. A = [1, 2, 3, 4, 100], B = [2, 4, 5, 6, 8, 201].
WELCH = {
    "First": "A", "Second / null": "B", "N first": 5, "N second": 6,
    "Mean first": 22.0, "Mean second": 37.666666666666664, "Difference": -15.666666666666664,
    "t": -0.41167137476691973, "df": 7.9383442350304545, "p": 0.6914709487741075,
    "CI 95% low": -103.54330819793029, "CI 95% high": 72.20997486459694,
    "Cohen's d": -0.23605476735485062,
}
PERMUTATION_ROW = {
    "N first": 5, "N second": 6, "Mean first": 22.0, "Mean second": 37.666666666666664,
    "Mean difference": -15.666666666666664, "Alternative": "Two-sided", "p": 0.7445887445887446,
    "Tail count": 344, "Draws": 462, "Mode used": "Exact",
}


def oracle(a, b, trim, level):
    def summary(values):
        n = len(values)
        g = math.floor(n * trim)
        h = n - 2 * g
        ordered = sorted(values)
        central = ordered[g:n - g]
        winsor = [central[0]] * g + central + [central[-1]] * g
        mean = math.fsum(winsor) / n
        component = math.fsum((item - mean) ** 2 for item in winsor) / (h * (h - 1))
        return math.fsum(central) / h, component, h
    mean_a, d_a, h_a = summary(a)
    mean_b, d_b, h_b = summary(b)
    difference = mean_a - mean_b
    se = math.sqrt(d_a + d_b)
    df = (d_a + d_b) ** 2 / (d_a ** 2 / (h_a - 1) + d_b ** 2 / (h_b - 1))
    statistic = difference / se
    half = stats.t.ppf((1 + level) / 2, df) * se
    return {
        "difference": difference, "se": se, "df": df, "statistic": statistic,
        "pvalue": 2 * stats.t.sf(abs(statistic), df), "ci_lower": difference - half,
        "ci_upper": difference + half, "h_a": h_a, "h_b": h_b,
    }


def columns(a, b, **options):
    width = max(len(a), len(b))
    frame = pd.DataFrame({
        "A": list(a) + [None] * (width - len(a)),
        "B": list(b) + [None] * (width - len(b)),
    })
    recipe = {
        yuen.INPUT: yuen.COLUMNS, yuen.FIRST: "A", yuen.SECOND: "B",
        yuen.TRIM: 20.0, yuen.LEVEL: 95.0, yuen.REVERSE: False,
    }
    recipe.update(options)
    return analyse(yuen.METHOD, frame, recipe)


def effect(result):
    return result.tables[yuen.EFFECT_SHEET]["Value"]


def groups(result):
    return result.tables[yuen.GROUPS_SHEET].set_index("Role")


class ContractTests(unittest.TestCase):
    def test_summary_matches_the_oracle_and_scipy_in_both_orders(self):
        self.assertAlmostEqual(oracle(*CASES[0], 0.9)["difference"], -2.75)
        for left, right, trim in CASES:
            for first, second in ((left, right), (right, left)):
                expected = oracle(first, second, trim, 0.9)
                actual = yuen.yuen_summary(first, second, trim=trim, level=0.9)
                reference = stats.ttest_ind(first, second, equal_var=False, trim=trim)
                for key, value in expected.items():
                    self.assertTrue(math.isclose(actual[key], value, rel_tol=5e-12, abs_tol=5e-13), key)
                self.assertAlmostEqual(actual["statistic"], reference.statistic, places=12)
                self.assertAlmostEqual(actual["pvalue"], reference.pvalue, places=12)

    def test_both_constant_samples_keep_the_difference_and_drop_the_inference(self):
        summary = yuen.yuen_summary([1] * 5, [2] * 5, trim=0.2, level=0.9)
        self.assertEqual(summary["difference"], -1)
        self.assertEqual(summary["se"], 0)
        self.assertIsNone(summary["pvalue"])
        self.assertIsNone(summary["df"])
        self.assertIsNone(summary["statistic"])
        self.assertIsNone(summary["ci_lower"])
        self.assertIsNone(summary["ci_upper"])
        result = columns([1] * 5, [2] * 5)
        sheet = effect(result)
        self.assertEqual(sheet["Inference"], "Not available")
        self.assertEqual(sheet["Reason"], yuen.REASON_SE)
        self.assertIsNone(sheet["p"])
        self.assertEqual(result.figure, None)

    def test_one_constant_sample_still_has_a_standard_error(self):
        summary = yuen.yuen_summary([2] * 5, [3, 4, 5, 7, 9], trim=0.2, level=0.9)
        self.assertGreater(summary["se"], 0)
        self.assertIsNotNone(summary["pvalue"])

    def test_decimal_floor_keeps_an_exact_percentage(self):
        self.assertEqual(yuen.removed_per_tail(100, 0.29), 29)
        self.assertEqual(math.floor(100 * 0.29), 28)
        self.assertEqual(yuen.removed_per_tail(200, 0.145), 29)
        self.assertEqual(yuen.removed_per_tail(5, 0.2), 1)
        values = list(range(1, 101))
        result = columns(values, [item + 1 for item in values], **{yuen.TRIM: 29.0})
        self.assertEqual(int(groups(result).loc["First", "Removed per tail"]), 29)
        self.assertEqual(int(groups(result).loc["First", "Effective N"]), 42)

    def test_short_samples_are_refused_before_a_division(self):
        with self.assertRaises(ValueError):
            yuen.yuen_summary([1, 2, 3], [1, 2, 3, 4], trim=0.4)
        with self.assertRaises(FieldError) as short:
            columns([1], [1, 2, 3, 4])
        self.assertIs(short.exception.field, yuen.FIRST)
        with self.assertRaises(FieldError) as trimmed:
            columns([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], **{yuen.TRIM: 40.0})
        self.assertIs(trimmed.exception.field, yuen.TRIM)
        self.assertIn("at least 2", str(trimmed.exception))

    def test_a_large_offset_stays_finite(self):
        base = float(2 ** 50)
        summary = yuen.yuen_summary(
            [base + 1, base + 2, base + 3, base + 4, base + 100],
            [base + 3, base + 4, base + 5, base + 7, base + 9],
            trim=0.2, level=0.9,
        )
        self.assertTrue(math.isfinite(summary["difference"]))
        self.assertGreater(summary["se"], 0)
        self.assertTrue(math.isfinite(summary["df"]))

    def test_an_overflow_names_the_sample(self):
        with self.assertRaises(FieldError) as error:
            columns([1e308, -1e308, 1e308, -1e308, 0.0], [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertIs(error.exception.field, yuen.FIRST)

    def test_fifty_thousand_observations_per_group(self):
        generator = np.random.default_rng(0)
        first = generator.normal(size=50_000)
        second = generator.normal(size=50_000) + 0.2
        started = time.perf_counter()
        summary = yuen.yuen_summary(first, second, trim=0.2, level=0.95)
        elapsed = time.perf_counter() - started
        print(f"yuen 50000+50000: {elapsed:.3f}s effective N {summary['h_a']}+{summary['h_b']}")
        self.assertEqual((summary["h_a"], summary["h_b"]), (30_000, 30_000))
        self.assertLess(elapsed, 5.0)
        self.assertTrue(math.isfinite(summary["pvalue"]))


class WorksheetTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_registration_keeps_the_locked_group_menu(self):
        menu = GROUPS["Group Comparison"]
        self.assertEqual(menu[:4], ("t-test", "Paired t-test (columns)", "Lognormal t-test", "Compare two variances"))
        self.assertEqual(menu[menu.index(PERMUTATION_METHOD) + 1], yuen.METHOD)
        self.assertNotIn(yuen.METHOD, GRAPH_METHODS)
        self.assertEqual(ui(yuen.METHOD), yuen.METHOD)
        set_language("it")
        self.assertEqual(ui(yuen.METHOD), "Test di Yuen per medie troncate")

    def test_columns_report_the_filter_and_the_direction(self):
        result = columns([1, 2, 3, 4, 100, None], [2, 4, 5, 6, 8, 201])
        table = groups(result)
        self.assertEqual(int(table.loc["First", "N before filter"]), 6)
        self.assertEqual(int(table.loc["First", "N after filter"]), 5)
        self.assertEqual(int(table.loc["Second", "N after filter"]), 6)
        self.assertEqual(int(table.loc["First", "Removed per tail"]), 1)
        self.assertEqual(int(table.loc["First", "Effective N"]), 3)
        sheet = effect(result)
        self.assertEqual(sheet["First"], "A")
        self.assertEqual(sheet["Second"], "B")
        self.assertAlmostEqual(sheet["Difference"], -2.75)
        self.assertEqual(sheet["Inference"], "Available")
        self.assertNotIn("Reason", sheet)
        swapped = columns([1, 2, 3, 4, 100], [2, 4, 5, 6, 8, 201], **{
            yuen.FIRST: "B", yuen.SECOND: "A"})
        self.assertAlmostEqual(effect(swapped)["Difference"], -effect(result)["Difference"])
        reversed_samples = columns([1, 2, 3, 4, 100], [2, 4, 5, 6, 8, 201], **{yuen.REVERSE: True})
        self.assertAlmostEqual(effect(reversed_samples)["Difference"], -effect(result)["Difference"])
        self.assertEqual(result.figure, None)

    def test_trim_zero_matches_welch(self):
        frame = pd.DataFrame({"A": [1, 2, 3, 4, 100, None], "B": [2, 4, 5, 6, 8, 201]})
        welch = analyse("t-test", frame, {
            "Design": "Welch", yuen.INPUT: yuen.COLUMNS, yuen.FIRST: "A", yuen.SECOND: "B",
            yuen.LEVEL: 95.0,
        }).tables["t-test"]["Value"].to_dict()
        for key, value in WELCH.items():
            self.assertAlmostEqual(welch[key], value, places=12)
        trimmed = effect(columns([1, 2, 3, 4, 100], [2, 4, 5, 6, 8, 201], **{yuen.TRIM: 0.0, yuen.LEVEL: 95.0}))
        reference = stats.ttest_ind([1, 2, 3, 4, 100], [2, 4, 5, 6, 8, 201], equal_var=False)
        self.assertAlmostEqual(trimmed["Difference"], welch["Difference"], places=10)
        self.assertAlmostEqual(trimmed["t"], welch["t"], places=10)
        self.assertAlmostEqual(trimmed["df"], welch["df"], places=10)
        self.assertAlmostEqual(trimmed["p"], welch["p"], places=10)
        self.assertAlmostEqual(trimmed["t"], reference.statistic, places=10)
        self.assertAlmostEqual(trimmed["CI low"], welch["CI 95% low"], places=8)
        self.assertAlmostEqual(trimmed["CI high"], welch["CI 95% high"], places=8)

    def test_grouped_values_keep_the_saved_group_order(self):
        frame = pd.DataFrame({
            "Value": [1, 2, 3, 4, 100, None, 2, 4, 5, 6, 8, 201, 9],
            "Group": ["Control", "Control", "Control", "Control", "Control", "Control",
                      "Treated", "Treated", "Treated", "Treated", "Treated", "Treated", ""],
        })
        recipe = {yuen.INPUT: yuen.GROUPED, yuen.RESPONSE: "Value", yuen.GROUP: "Group", yuen.TRIM: 20.0}
        result = analyse(yuen.METHOD, frame, recipe)
        self.assertEqual(recipe[yuen.GROUP_ORDER], ["Control", "Treated"])
        table = groups(result)
        self.assertEqual(int(table.loc["First", "N before filter"]), 6)
        self.assertEqual(int(table.loc["First", "N after filter"]), 5)
        self.assertEqual(int(table.loc["Second", "N after filter"]), 6)
        self.assertAlmostEqual(effect(result)["Difference"], -2.75)
        recipe[yuen.GROUP_ORDER] = ["Treated", "Control"]
        flipped = analyse(yuen.METHOD, frame, recipe)
        self.assertEqual(effect(flipped)["First"], "Treated")
        self.assertAlmostEqual(effect(flipped)["Difference"], 2.75)
        self.assertEqual(recipe[yuen.GROUP_ORDER], ["Treated", "Control"])

    def test_a_comma_decimal_is_a_number_and_text_names_its_row(self):
        frame = pd.DataFrame({"A": ["1,5", "2,5", "3,5", "4,5", "10,5"], "B": ["2", "4", "5", "8", "9"]})
        result = columns(["1,5", "2,5", "3,5", "4,5", "10,5"], ["2", "4", "5", "8", "9"])
        self.assertAlmostEqual(groups(result).loc["First", "Trimmed mean"], (2.5 + 3.5 + 4.5) / 3)
        broken = pd.DataFrame({"A": [1, 2, "x", 4, 5], "B": [2, 4, 5, 6, 8]})
        with self.assertRaises(FieldError) as error:
            analyse(yuen.METHOD, broken, {
                yuen.INPUT: yuen.COLUMNS, yuen.FIRST: "A", yuen.SECOND: "B", yuen.TRIM: 20.0,
            })
        self.assertIs(error.exception.field, yuen.FIRST)
        self.assertIn("source row 3", str(error.exception))
        set_language("it")
        shown = yuen.describe_error(error.exception)
        self.assertIn("Prima misura", shown)
        self.assertIn("riga 3", shown)
        level = yuen.describe_error(FieldError(yuen.LEVEL, text("yuen.error.level")))
        self.assertIn("confidenza", level.lower())

    def test_bad_percentages_name_the_field(self):
        for field, value in ((yuen.TRIM, 50), (yuen.TRIM, -1), (yuen.LEVEL, 0), (yuen.LEVEL, 100), (yuen.TRIM, True)):
            with self.assertRaises(FieldError) as error:
                columns([1, 2, 3, 4, 5], [2, 3, 4, 5, 6], **{field: value})
            self.assertIs(error.exception.field, field)
        with self.assertRaises(FieldError) as groups_error:
            analyse(yuen.METHOD, pd.DataFrame({"Value": [1, 2, 3, 4], "Group": ["A", "A", "B", "C"]}), {
                yuen.INPUT: yuen.GROUPED, yuen.RESPONSE: "Value", yuen.GROUP: "Group",
            })
        self.assertIs(groups_error.exception.field, yuen.GROUP)

    def test_the_example_file_is_the_column_pair_with_an_outlier(self):
        frame = pd.read_csv(EXAMPLE)
        result = analyse(yuen.METHOD, frame, {
            yuen.INPUT: yuen.COLUMNS, yuen.FIRST: "Control", yuen.SECOND: "Treated",
            yuen.TRIM: 20.0, yuen.LEVEL: 95.0,
        })
        self.assertAlmostEqual(effect(result)["Difference"], -2.75)
        self.assertEqual(int(groups(result).loc["First", "Removed per tail"]), 1)

    def test_the_previous_welch_and_exact_permutation_results_are_unchanged(self):
        frame = pd.DataFrame({"A": [1, 2, 3, 4, 100, None], "B": [2, 4, 5, 6, 8, 201]})
        welch = analyse("t-test", frame, {
            "Design": "Welch", "Sample format": "Two measurement columns",
            "First measurement": "A", "Second measurement": "B", "Confidence level (%)": 95,
        }).tables["t-test"]["Value"].to_dict()
        for key, value in WELCH.items():
            self.assertAlmostEqual(welch[key], value, places=12)
        permutation = analyse(PERMUTATION_METHOD, frame, {
            "First": "A", "Second": "B", "Design": "Independent", "Alternative": "Two-sided",
            "Method": "Exact", "Show graph": False, "Keep draws": False,
        }).tables["Permutation results"].iloc[0].to_dict()
        for key, value in PERMUTATION_ROW.items():
            if isinstance(value, str):
                self.assertEqual(permutation[key], value)
            else:
                self.assertAlmostEqual(permutation[key], value, places=12)


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 is not installed")
        cls.app = QApplication.instance() or QApplication(["trama-yuen-tests", "-platform", "offscreen"])

    def tearDown(self):
        set_language("en")

    def test_italian_comma_is_canonical_in_the_recipe_and_a_bad_level_stays_open(self):
        from PySide6.QtWidgets import QLineEdit

        from trama_qt.analysis_dialog import AnalysisDialog

        set_language("it")
        frame = pd.DataFrame({"Control": [1, 2, 3, 4, 100, None], "Treated": [2, 4, 5, 6, 8, 201]})
        dialog = AnalysisDialog(None, frame, current=(yuen.METHOD, {}))
        self.assertEqual(dialog.tabs.tabText(0), "Dati")
        self.assertEqual(dialog.tabs.tabText(1), "Test")
        trim = dialog.controls[yuen.TRIM][1]
        level = dialog.controls[yuen.LEVEL][1]
        self.assertIsInstance(trim, QLineEdit)
        self.assertEqual(trim.text(), "20")
        self.assertEqual(level.text(), "95")
        dialog.show()
        self.app.processEvents()
        trim.setText("20,5")
        level.setText("101")
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertEqual(dialog.error_field, yuen.LEVEL)
        self.assertIn("confidenza", dialog.banner.text().lower())
        self.assertEqual(dialog.controls[yuen.FIRST][1].currentData(), "Control")
        level.setText("95")
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        recipe = dialog.result[1]
        self.assertEqual(recipe[yuen.TRIM], 20.5)
        self.assertEqual(recipe[yuen.LEVEL], 95.0)
        self.assertNotIn(yuen.RESPONSE, recipe)
        dialog.deleteLater()
        self.app.processEvents()
