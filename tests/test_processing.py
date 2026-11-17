"""Numerical oracles and edge cases for the Data Processing analyses."""
from pathlib import Path
import tempfile
import time
import unittest
import warnings

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from analisi.data import Dataset, load_project, save_project
from analisi.processing import COMBINED_TOTALS, WILSON_BROWN, FieldError
from analisi.workbench import analyse

E = np.nan

CONCENTRATIONS = "Transform concentrations (X)"
BASELINE = "Remove baseline and column math"
PRUNE = "Prune rows"
FRACTION = "Fraction of total"


def concentrations(**options):
    return {"X": "X", "Replace zero X": False, "Zero replacement (original units)": 1e-11,
            "Change units": "No change", "Unit factor": 1.0, "Logarithm": "None", **options}


def baseline(**options):
    return {"Data columns": ["Y"], "Baseline column": None, "X": None, "Row titles": None,
            "Baseline": "Baseline column, same row", "Rows for baseline (K)": 1, "Drop baseline rows": False,
            "Operation": "Difference: Y − baseline", **options}


def prune(**options):
    return {"X": "X", "Method": "Keep rows within an X range", "X minimum (blank = no limit)": "",
            "X maximum (blank = no limit)": "", "Rows per group (K)": 2,
            "Average only rows above an X threshold": False, "X threshold": 0.0, **options}


def fraction(**options):
    return {"Variables": ["A", "B"], "Row titles": None, "Divide by": "Column total", "Show as": "Fractions",
            "Confidence interval": "None", "Confidence level (%)": 95.0, **options}


class ProcessingCase(unittest.TestCase):
    def run_strict(self, method, frame, options):
        """Run with warnings as errors and check that the source frame is untouched."""
        before = frame.copy(deep=True)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                return analyse(method, frame, options)
        finally:
            pd.testing.assert_frame_equal(frame, before)

    def assert_field_error(self, field, method, frame, options):
        with self.assertRaises(FieldError) as raised:
            self.run_strict(method, frame, options)
        self.assertEqual(raised.exception.field, field)
        return str(raised.exception)


class TransformConcentrationsTests(ProcessingCase):
    def test_replacement_units_then_log10(self):
        frame = pd.DataFrame({"X": [0, 1e-9, 1e-8, E], "Y": [1.5, 2.5, E, 4.5]})
        result = self.run_strict(CONCENTRATIONS, frame, concentrations(
            **{"Replace zero X": True, "Change units": "Multiply by", "Unit factor": 1e9, "Logarithm": "Log10"}))
        data = result.tables["Transformed data"]
        np.testing.assert_allclose(data["X"], [-2, 0, 1, E])
        pd.testing.assert_series_equal(data["Y"], frame["Y"])
        self.assertEqual(list(data.columns), ["X", "Y"])

    def test_natural_log_without_replacement_blanks_zero_and_ignores_disabled_factor(self):
        frame = pd.DataFrame({"X": [0, 1, np.e ** 2], "Y": [1, 2, 3]})
        for factor in (1.0, 1e6, 0.0):
            result = self.run_strict(CONCENTRATIONS, frame, concentrations(Logarithm="Natural log",
                                                                             **{"Unit factor": factor}))
            np.testing.assert_allclose(result.tables["Transformed data"]["X"], [E, 0, 2])
        self.assertEqual(result.tables["Notes"].loc["Zero X left blank", "Value"], 1)

    def test_negative_x_in_log_mode_becomes_blank_and_is_reported(self):
        frame = pd.DataFrame({"X": [-10, 0, 10, 100], "Y": [1, 2, 3, 4]})
        result = self.run_strict(CONCENTRATIONS, frame, concentrations(Logarithm="Log10"))
        values = result.tables["Transformed data"]["X"]
        np.testing.assert_allclose(values, [E, E, 1, 2])
        self.assertFalse(np.isinf(values).any())
        notes = result.tables["Notes"]["Value"]
        self.assertEqual((notes["Negative X left blank"], notes["Zero X left blank"]), (1, 1))

    def test_division_and_unit_change_without_log(self):
        frame = pd.DataFrame({"X": [0, 500, 2000.]})
        result = self.run_strict(CONCENTRATIONS, frame, concentrations(
            **{"Change units": "Divide by", "Unit factor": 1000.}))
        np.testing.assert_allclose(result.tables["Transformed data"]["X"], [0, .5, 2])

    def test_excluded_row_and_replicates_stay_blank_not_zero(self):
        raw = pd.DataFrame({"X": [0., 1., 10., 100.], "Drug [1]": [1., 2., 3., 4.], "Drug [2]": [1.1, 2.1, 3.1, 4.1]})
        dataset = Dataset(raw, excluded={(2, 0), (2, 1), (2, 2)})
        frame = dataset.frame(mask_excluded=True)
        result = self.run_strict(CONCENTRATIONS, frame, concentrations(
            **{"Replace zero X": True, "Zero replacement (original units)": .1, "Logarithm": "Log10"}))
        data = result.tables["Transformed data"]
        np.testing.assert_allclose(data["X"].astype(float), [-1, 0, E, 2])
        self.assertTrue(data.loc[2, ["Drug [1]", "Drug [2]"]].isna().all())
        np.testing.assert_allclose(data["Drug [2]"].astype(float), [1.1, 2.1, E, 4.1])
        self.assertEqual(dataset.raw.loc[2, "X"], 10.)

    def test_invalid_factors_are_rejected_with_their_field(self):
        frame = pd.DataFrame({"X": [1., 2.]})
        for units, factor in (("Divide by", 0.), ("Multiply by", -2.), ("Multiply by", np.inf), ("Divide by", "x")):
            message = self.assert_field_error("Unit factor", CONCENTRATIONS, frame,
                                              concentrations(**{"Change units": units, "Unit factor": factor}))
            self.assertIn("Unit factor", message)
        self.assert_field_error("Zero replacement (original units)", CONCENTRATIONS, frame, concentrations(
            **{"Replace zero X": True, "Zero replacement (original units)": 0.}))
        self.assert_field_error("Unit factor", CONCENTRATIONS, pd.DataFrame({"X": [1e300]}),
                                concentrations(**{"Change units": "Multiply by", "Unit factor": 1e300}))
        self.assert_field_error("X", CONCENTRATIONS, pd.DataFrame({"X": ["a", "1"]}), concentrations())


class RemoveBaselineTests(ProcessingCase):
    def test_row_baseline_subtract_and_divide(self):
        frame = pd.DataFrame({"Y": [10., 14., 18.], "Base": [2., 4., E]})
        got = self.run_strict(BASELINE, frame, baseline(**{"Baseline column": "Base"}))
        np.testing.assert_allclose(got.tables["Processed data"]["Y"], [8, 10, E])
        got = self.run_strict(BASELINE, frame, baseline(**{"Baseline column": "Base",
                                                           "Operation": "Ratio: Y / baseline"}))
        np.testing.assert_allclose(got.tables["Processed data"]["Y"], [5, 3.5, E])

    def test_sum_product_fractional_and_percent(self):
        frame = pd.DataFrame({"Y": [10., 14.], "Base": [2., 4.]})
        expected = {"Sum: Y + baseline": [12, 18], "Product: Y × baseline": [20, 56],
                    "Fractional difference: (Y − baseline) / baseline": [4, 2.5],
                    "Percent difference: 100 × (Y − baseline) / baseline": [400, 250]}
        for operation, values in expected.items():
            got = self.run_strict(BASELINE, frame, baseline(**{"Baseline column": "Base", "Operation": operation}))
            np.testing.assert_allclose(got.tables["Processed data"]["Y"], values, err_msg=operation)

    def test_mean_of_first_rows_and_dropping_reference_rows_keeps_x_and_titles(self):
        frame = pd.DataFrame({"Time": [0., 1., 2.], "Label": ["pre", "early", "late"], "Y": [10., 14., 18.]})
        options = baseline(**{"Baseline": "Mean of first K rows", "Rows for baseline (K)": 2, "X": "Time",
                              "Row titles": "Label"})
        got = self.run_strict(BASELINE, frame, options).tables
        np.testing.assert_allclose(got["Processed data"]["Y"], [-2, 2, 6])
        self.assertEqual(got["Notes"].loc["Baseline of Y", "Value"], 12)
        dropped = self.run_strict(BASELINE, frame, {**options, "Drop baseline rows": True}).tables["Processed data"]
        self.assertEqual(dropped.to_dict("list"), {"Label": ["late"], "Time": [2.], "Y": [6.]})

    def test_last_row_baseline_with_k_one(self):
        frame = pd.DataFrame({"Y": [10., 14., 18.]})
        got = self.run_strict(BASELINE, frame, baseline(Baseline="Mean of last K rows"))
        np.testing.assert_allclose(got.tables["Processed data"]["Y"], [-8, -4, 0])

    def test_linear_baseline_predicts_missing_reference(self):
        frame = pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [10., 20., 30., 40.], "Base": [3., E, 7., 9.]})
        got = self.run_strict(BASELINE, frame, baseline(**{"Baseline": "Linear fit of baseline column vs X",
                                                           "Baseline column": "Base", "X": "X"})).tables
        np.testing.assert_allclose(got["Linear baseline"]["Predicted baseline"], [3, 5, 7, 9])
        np.testing.assert_allclose(got["Processed data"]["Y"], [7, 15, 23, 31])
        self.assertAlmostEqual(got["Notes"].loc["Slope", "Value"], 2)
        self.assertAlmostEqual(got["Notes"].loc["Intercept", "Value"], 1)

    def test_linear_baseline_leaves_rows_without_x_blank_and_does_not_impute_y(self):
        frame = pd.DataFrame({"X": [1., 2., E, 4.], "Y": [10., E, 30., 40.], "Base": [3., 5., 7., 9.]})
        got = self.run_strict(BASELINE, frame, baseline(**{"Baseline": "Linear fit of baseline column vs X",
                                                           "Baseline column": "Base", "X": "X"}))
        np.testing.assert_allclose(got.tables["Processed data"]["Y"], [7, E, E, 31])

    def test_linear_baseline_needs_enough_pairs_and_distinct_x(self):
        options = baseline(**{"Baseline": "Linear fit of baseline column vs X", "Baseline column": "Base", "X": "X"})
        few = pd.DataFrame({"X": [1., 2., 3.], "Y": [1., 2., 3.], "Base": [1., E, 2.]})
        self.assert_field_error("Baseline column", BASELINE, few, options)
        flat = pd.DataFrame({"X": [2., 2., 2.], "Y": [1., 2., 3.], "Base": [1., 2., 3.]})
        self.assert_field_error("Baseline column", BASELINE, flat, options)
        self.assert_field_error("X", BASELINE, flat, {**options, "X": None})

    def test_linear_baseline_diagnostics_preserve_x_with_colliding_name(self):
        frame = pd.DataFrame({"Observed baseline": [1, 2, 3], "Base": [2, 4, 6], "Y": [3, 5, 7]})
        options = baseline(Baseline="Linear fit of baseline column vs X", X="Observed baseline",
                           **{"Baseline column": "Base"})
        table = self.run_strict(BASELINE, frame, options).tables["Linear baseline"]
        self.assertEqual(table.shape[1], 3)
        self.assertEqual(table.iloc[:, 0].tolist(), [1, 2, 3])
        self.assertEqual(table.iloc[:, 1].tolist(), [2, 4, 6])

    def test_baseline_rejects_integer_values_that_would_lose_precision(self):
        frame = pd.DataFrame({"Y": [2**53 + 1], "Base": [2**53]})
        self.assert_field_error("Data columns", BASELINE, frame, baseline(**{"Baseline column": "Base"}))

    def test_baseline_mean_does_not_overflow_on_finite_equal_values(self):
        frame = pd.DataFrame({"Y": [1e308, 1e308]})
        options = baseline(Baseline="Mean of first K rows", Operation="Ratio: Y / baseline",
                           **{"Rows for baseline (K)": 2})
        got = self.run_strict(BASELINE, frame, options)
        self.assertEqual(got.tables["Processed data"]["Y"].tolist(), [1., 1.])

    def test_alternate_pairing_uses_table_order(self):
        frame = pd.DataFrame({"A": [1., 2.], "B": [10., 20.], "C": [3., 4.], "D": [30., 40.]})
        got = self.run_strict(BASELINE, frame, baseline(**{"Data columns": ["D", "B", "C", "A"],
                                                           "Baseline": "Alternate columns: A, C, E… are baselines"}))
        data = got.tables["Processed data"]
        self.assertEqual(list(data.columns), ["B", "D"])
        np.testing.assert_allclose(data[["B", "D"]], [[9, 27], [18, 36]])
        got = self.run_strict(BASELINE, frame, baseline(**{"Data columns": ["A", "B", "C", "D"],
                                                           "Baseline": "Alternate columns: B, D, F… are baselines"}))
        np.testing.assert_allclose(got.tables["Processed data"][["A", "C"]], [[-9, -27], [-18, -36]])
        self.assert_field_error("Data columns", BASELINE, frame, baseline(
            **{"Data columns": ["A", "B", "C"], "Baseline": "Alternate columns: A, C, E… are baselines"}))

    def test_zero_denominator_is_blank_and_counted(self):
        frame = pd.DataFrame({"Y": [10., 5., 0.], "Base": [0., 5., 0.]})
        got = self.run_strict(BASELINE, frame, baseline(**{"Baseline column": "Base",
                                                           "Operation": "Ratio: Y / baseline"})).tables
        np.testing.assert_allclose(got["Processed data"]["Y"], [E, 1, E])
        self.assertEqual(got["Notes"].loc["Zero denominators left blank", "Value"], 2)

    def test_errors_for_missing_references_and_k_range_leave_data_intact(self):
        frame = pd.DataFrame({"Y": [E, E, 3.], "Base": [E, E, E]})
        self.assert_field_error("Baseline column", BASELINE, frame, baseline(**{"Baseline column": "Base"}))
        first = baseline(**{"Baseline": "Mean of first K rows", "Rows for baseline (K)": 2})
        self.assert_field_error("Rows for baseline (K)", BASELINE, frame, first)
        for k in (0, 4, 1.5):
            self.assert_field_error("Rows for baseline (K)", BASELINE, frame, {**first, "Rows for baseline (K)": k})
        self.assert_field_error("Data columns", BASELINE, frame, baseline(**{"Data columns": ["Y"],
                                                                            "Baseline column": "Y"}))
        self.assert_field_error("Data columns", BASELINE, frame, baseline(**{"Data columns": []}))

    def test_partial_failure_leaves_no_output_and_source_untouched(self):
        frame = pd.DataFrame({"Y": [1., 2.], "Z": [E, E]})
        self.assert_field_error("Rows for baseline (K)", BASELINE, frame,
                                baseline(**{"Data columns": ["Y", "Z"], "Baseline": "Mean of first K rows"}))


class PruneRowsTests(ProcessingCase):
    frame = pd.DataFrame({"X": [3, 1, 2, 5, 4], "Y": [30, 10, 20, 50, 40]})

    def test_inclusive_x_range_keeps_source_order(self):
        got = self.run_strict(PRUNE, self.frame, prune(**{"X minimum (blank = no limit)": "2",
                                                          "X maximum (blank = no limit)": "4"}))
        self.assertEqual(got.tables["Pruned data"].to_dict("list"), {"X": [3, 2, 4], "Y": [30, 20, 40]})
        got = self.run_strict(PRUNE, self.frame, prune(**{"X minimum (blank = no limit)": "3,5"}))
        self.assertEqual(got.tables["Pruned data"]["X"].tolist(), [5, 4])

    def test_average_groups_with_partial_tail(self):
        got = self.run_strict(PRUNE, self.frame, prune(Method="Average every K rows (sorted by X)"))
        data = got.tables["Pruned data"]
        np.testing.assert_allclose(data["X"], [1.5, 3.5, 5])
        np.testing.assert_allclose(data["Y"].astype(float), [15, 35, 50])
        self.assertEqual(got.tables["Notes"].loc["Incomplete last group (rows)", "Value"], 1)

    def test_numeric_strings_in_x_are_averaged_numerically(self):
        frame = pd.DataFrame({"X": pd.array(["3", "1", "2"], dtype="string"), "Y": [30, 10, 20]})
        options = prune(Method="Average every K rows (sorted by X)")
        table = self.run_strict(PRUNE, frame, options).tables["Pruned data"]
        self.assertEqual(table["X"].tolist(), [1.5, 3.])

    def test_large_integer_x_range_and_sort_distinguish_adjacent_values(self):
        edge = 2**53
        frame = pd.DataFrame({"X": pd.array([edge + 1, edge, edge + 2, None], dtype="Int64"),
                              "Y": [20, 10, 30, 40]})
        options = prune(**{"X minimum (blank = no limit)": f"{edge}.0",
                           "X maximum (blank = no limit)": f"{edge}.5"})
        tables = self.run_strict(PRUNE, frame, options).tables
        self.assertEqual(tables["Pruned data"]["Y"].tolist(), [10])
        self.assertEqual(tables["Notes"].loc["X maximum", "Value"], f"{edge}.5")
        options = prune(Method="Average every K rows (sorted by X)")
        table = self.run_strict(PRUNE, frame, options).tables["Pruned data"]
        self.assertEqual(table["Y"].tolist(), [15., 30.])
        options = prune(Method="Average every K rows (sorted by X)", **{
            "Average only rows above an X threshold": True, "X threshold": str(edge)})
        table = self.run_strict(PRUNE, frame, options).tables["Pruned data"]
        self.assertEqual(table["Y"].tolist(), [10., 25.])

    def test_prune_reports_oversized_group_count_as_field_error(self):
        options = prune(Method="Average every K rows (sorted by X)", **{"Rows per group (K)": 10**20})
        self.assert_field_error("Rows per group (K)", PRUNE, self.frame, options)

    def test_prune_reports_overflowing_group_means(self):
        frame = pd.DataFrame({"X": [1, 2], "Y": [1e308, 1e308]})
        self.assert_field_error("Rows per group (K)", PRUNE, frame,
                                prune(Method="Average every K rows (sorted by X)"))

    def test_threshold_keeps_lower_rows_whole(self):
        got = self.run_strict(PRUNE, self.frame, prune(**{"Method": "Average every K rows (sorted by X)",
                                                          "Average only rows above an X threshold": True,
                                                          "X threshold": 2.}))
        data = got.tables["Pruned data"]
        np.testing.assert_allclose(data["X"], [1, 2, 3.5, 5])
        np.testing.assert_allclose(data["Y"].astype(float), [10, 20, 35, 50])

    def test_ties_missing_values_titles_and_blank_x(self):
        frame = pd.DataFrame({"Title": ["a", "b", "c", "d", "e", "f"], "X": [2., 1., 2., E, 2., 3.],
                              "Y": [E, 10., 30., 99., 50., E], "Z": [1., 2., 3., 4., 5., 6.]})
        got = self.run_strict(PRUNE, frame, prune(Method="Average every K rows (sorted by X)"))
        data = got.tables["Pruned data"]
        # Stable order by X: b(1), a(2), c(2), e(2), f(3); row d has a blank X and is dropped.
        np.testing.assert_allclose(data["X"], [1.5, 2, 3])
        np.testing.assert_allclose(data["Y"].astype(float), [10, 40, E])
        np.testing.assert_allclose(data["Z"].astype(float), [1.5, 4, 6])
        self.assertTrue(data["Title"].iloc[:2].isna().all())
        self.assertEqual(data["Title"].iloc[2], "f")
        self.assertEqual(got.tables["Notes"].loc["Rows with blank X dropped", "Value"], 1)
        ranged = self.run_strict(PRUNE, frame, prune(**{"X maximum (blank = no limit)": "2"})).tables["Pruned data"]
        self.assertEqual(ranged["Title"].tolist(), ["a", "b", "c", "e"])

    def test_identical_x_values(self):
        frame = pd.DataFrame({"X": [1., 1., 1.], "Y": [1., 2., 6.]})
        got = self.run_strict(PRUNE, frame, prune(**{"Method": "Average every K rows (sorted by X)",
                                                     "Rows per group (K)": 3}))
        self.assertEqual(got.tables["Pruned data"].to_dict("list"), {"X": [1.], "Y": [3.]})

    def test_invalid_options(self):
        average = prune(Method="Average every K rows (sorted by X)")
        for k in (1, 0, 2.5, True):
            self.assert_field_error("Rows per group (K)", PRUNE, self.frame, {**average, "Rows per group (K)": k})
        self.assert_field_error("X maximum (blank = no limit)", PRUNE, self.frame, prune(
            **{"X minimum (blank = no limit)": "4", "X maximum (blank = no limit)": "2"}))
        self.assert_field_error("X minimum (blank = no limit)", PRUNE, self.frame, prune())
        self.assert_field_error("X minimum (blank = no limit)", PRUNE, self.frame,
                                prune(**{"X minimum (blank = no limit)": "abc"}))

    def test_large_table_is_vectorized(self):
        rows = 400_000
        generator = np.random.default_rng(3)
        frame = pd.DataFrame({"X": generator.permutation(rows).astype(float),
                              "A": generator.normal(size=rows), "B": generator.normal(size=rows),
                              "Label": pd.array(["x"] * rows, dtype="string")})
        start = time.perf_counter()
        got = analyse(PRUNE, frame, prune(**{"Method": "Average every K rows (sorted by X)",
                                             "Rows per group (K)": 10}))
        ranged = analyse(PRUNE, frame, prune(**{"X minimum (blank = no limit)": "10",
                                                "X maximum (blank = no limit)": "1000"}))
        self.assertLess(time.perf_counter() - start, 5)
        data = got.tables["Pruned data"]
        self.assertEqual(len(data), rows // 10)
        np.testing.assert_allclose(data["X"].iloc[:2], [4.5, 14.5])
        self.assertEqual(len(ranged.tables["Pruned data"]), 991)


class FractionOfTotalTests(ProcessingCase):
    table = pd.DataFrame({"A": [6, 79], "B": [3, 12]})

    def test_column_row_and_grand_totals(self):
        expected = {"Column total": 6 / 85, "Row total": 6 / 9, "Grand total": 6 / 100}
        for mode, value in expected.items():
            got = self.run_strict(FRACTION, self.table, fraction(**{"Divide by": mode}))
            first = next(iter(got.tables.values()))
            self.assertAlmostEqual(first.iloc[0, 0], value)
            self.assertEqual(first.shape, (2, 2))
        got = self.run_strict(FRACTION, self.table, fraction(**{"Divide by": "Column total", "Show as": "Percentages"}))
        np.testing.assert_allclose(got.tables["Percent of column total"], [[600 / 85, 300 / 15], [7900 / 85, 1200 / 15]])

    def test_all_three_returns_named_tables_and_note(self):
        got = self.run_strict(FRACTION, self.table, fraction(**{"Divide by": "All three (separate tables)"}))
        self.assertEqual(list(got.tables)[:3], ["Fraction of column total", "Fraction of row total",
                                                "Fraction of grand total"])
        self.assertIn("Presentation", got.tables["Notes"].index)
        self.assert_field_error("Confidence interval", FRACTION, self.table, fraction(
            **{"Divide by": "All three (separate tables)", "Confidence interval": "Clopper–Pearson (exact)"}))

    def test_combined_table_keeps_row_titles_and_each_denominator(self):
        data = self.table.assign(**{"A · row total": ["first", "second"]})
        options = {"Row titles": "A · row total", "Show as": "Percentages"}
        combined = self.run_strict(FRACTION, data, fraction(**options, **{"Divide by": COMBINED_TOTALS})).tables
        separate = self.run_strict(FRACTION, data, fraction(
            **options, **{"Divide by": "All three (separate tables)"})).tables
        table = combined["Percent of all totals"]
        self.assertEqual(list(combined), ["Percent of all totals", "Totals", "Notes"])
        self.assertEqual(table["A · row total"].tolist(), ["first", "second"])
        for column in ("A", "B"):
            for denominator in ("column", "row", "grand"):
                name = f"{column} · {denominator} total"
                if name == "A · row total":
                    name += " (ratio)"
                np.testing.assert_allclose(table[name], separate[f"Percent of {denominator} total"][column])

    def test_wilson_brown_uses_poisson_only_at_the_documented_limits(self):
        from scipy.stats import poisson

        for n, k, change in ((50, 0, False), (50, 1, True), (50, 2, True), (50, 3, False),
                             (51, 3, True), (51, 4, False), (51, 51, False), (2, 1, True)):
            with self.subTest(n=n, k=k):
                counts = pd.DataFrame({"A": [k, n - k], "B": [np.nan, 0]})
                tables = self.run_strict(FRACTION, counts, fraction(**{"Confidence interval": WILSON_BROWN})).tables
                lo, hi = (tables[name]["A"].to_numpy() for name in ("Lower 95% limit", "Upper 95% limit"))
                self.assertAlmostEqual(lo[0], 1 - hi[1])
                if change:
                    self.assertAlmostEqual(poisson.cdf(k - 1, lo[0] * n), .95)
                else:
                    self.assertAlmostEqual(lo[0], binomtest(k, n).proportion_ci(method="wilson").low)
                self.assertTrue(tables["Lower 95% limit"]["B"].isna().all())
                self.assertTrue(tables["Upper 95% limit"]["B"].isna().all())

    def test_wilson_brown_rejects_confidence_that_can_invert_limits(self):
        counts = pd.DataFrame({"A": [1, 1], "B": [1, 1]})
        self.assert_field_error("Confidence level (%)", FRACTION, counts, fraction(
            **{"Confidence interval": WILSON_BROWN, "Confidence level (%)": 25.}))
        tables = self.run_strict(FRACTION, counts, fraction(
            **{"Confidence interval": WILSON_BROWN, "Confidence level (%)": 50.})).tables
        self.assertAlmostEqual(tables["Lower 50% limit"].iat[0, 0], -np.log(.5) / 2)
        self.assertAlmostEqual(tables["Upper 50% limit"].iat[0, 0], 1 + np.log(.5) / 2)

    def test_intervals_match_reference_and_scipy(self):
        exact = self.run_strict(FRACTION, self.table, fraction(**{"Confidence interval": "Clopper–Pearson (exact)"}))
        wilson = self.run_strict(FRACTION, self.table, fraction(**{"Confidence interval":
                                                                   "Wilson (no continuity correction)",
                                                                   "Show as": "Percentages"}))
        np.testing.assert_allclose([exact.tables["Lower 95% limit"].iloc[0, 0], exact.tables["Upper 95% limit"].iloc[0, 0]],
                                   [0.0263439303, 0.1473334588], atol=1e-10)
        np.testing.assert_allclose([wilson.tables["Lower 95% limit"].iloc[0, 0],
                                    wilson.tables["Upper 95% limit"].iloc[0, 0]],
                                   [3.27509631, 14.55605936], atol=1e-8)
        counts = pd.DataFrame({"A": [0, 7, 3, 0], "B": [5, 0, 2, 0]})
        for method, label in (("exact", "Clopper–Pearson (exact)"), ("wilson", "Wilson (no continuity correction)")):
            for level in (90., 99.):
                got = self.run_strict(FRACTION, counts, fraction(**{"Confidence interval": label,
                                                                    "Confidence level (%)": level}))
                for column, n in (("A", 10), ("B", 7)):
                    for row, k in enumerate(counts[column]):
                        ci = binomtest(int(k), n).proportion_ci(level / 100, method)
                        np.testing.assert_allclose(
                            [got.tables[f"Lower {level:g}% limit"].loc[row, column],
                             got.tables[f"Upper {level:g}% limit"].loc[row, column]],
                            [ci.low, ci.high], atol=1e-10, err_msg=f"{method} {level} {column}{row}")

    def test_k_equals_n_zero_total_and_blank_cells(self):
        counts = pd.DataFrame({"Title": ["r1", "r2", "r3"], "A": [4, 0, E], "B": [0, 0, E]})
        got = self.run_strict(FRACTION, counts, fraction(**{"Divide by": "Row total", "Row titles": "Title",
                                                            "Confidence interval": "Clopper–Pearson (exact)"}))
        table = got.tables["Fraction of row total"]
        self.assertEqual(table["Title"].tolist(), ["r1", "r2", "r3"])
        np.testing.assert_allclose(table[["A", "B"]], [[1, 0], [E, E], [E, E]])
        self.assertEqual(got.tables["Upper 95% limit"].loc[0, "A"], 1)
        self.assertEqual(got.tables["Lower 95% limit"].loc[0, "B"], 0)
        self.assertTrue(got.tables["Lower 95% limit"].loc[1:, ["A", "B"]].isna().all().all())

    def test_interval_rejections(self):
        for bad in ({"A": [1.5, 2]}, {"A": [-1, 2]}):
            self.assert_field_error("Confidence interval", FRACTION, pd.DataFrame(bad),
                                    fraction(Variables=["A"], **{"Confidence interval": "Clopper–Pearson (exact)"}))
        for level in (0., 100., 120.):
            self.assert_field_error("Confidence level (%)", FRACTION, self.table, fraction(
                **{"Confidence interval": "Wilson (no continuity correction)", "Confidence level (%)": level}))
        # Fractional and negative values are fine without intervals.
        got = self.run_strict(FRACTION, pd.DataFrame({"A": [1.5, -0.5, 1.]}), fraction(Variables=["A"]))
        np.testing.assert_allclose(got.tables["Fraction of column total"]["A"], [.75, -.25, .5])

    def test_replicate_subcolumns_are_rejected_with_a_reason(self):
        table = pd.DataFrame({"Control [1]": [1, 2], "Control [2]": [3, 4]})
        message = self.assert_field_error("Variables", FRACTION, table,
                                          fraction(Variables=["Control [1]", "Control [2]"]))
        self.assertIn("subcolumn", message)

    def test_imported_summary_subcolumns_are_rejected(self):
        names = ("Drug [CV%]", "Drug [Center]", "Drug [Plus]", "Drug [Minus]", "Drug [Value]", "Drug [SD] (2)")
        for name in names:
            with self.subTest(name=name):
                self.assert_field_error("Variables", FRACTION, pd.DataFrame({name: [1, 2]}),
                                        fraction(Variables=[name]))

    def test_fraction_rejects_an_overflowing_total(self):
        frame = pd.DataFrame({"A": [1e308, 1e308]})
        self.assert_field_error("Divide by", FRACTION, frame, fraction(Variables=["A"]))

    def test_near_hundred_percent_intervals_are_finite(self):
        frame = pd.DataFrame({"A": [1, 2]})
        for interval in ("Wilson (no continuity correction)", "Clopper–Pearson (exact)"):
            with self.subTest(interval=interval):
                got = self.run_strict(FRACTION, frame, fraction(Variables=["A"], **{
                    "Confidence interval": interval, "Confidence level (%)": 99.99999999999999}))
                lower = next(table["A"] for name, table in got.tables.items() if name.startswith("Lower"))
                upper = next(table["A"] for name, table in got.tables.items() if name.startswith("Upper"))
                self.assertTrue(((lower > 0) & (lower < 1/3)).all())
                self.assertTrue(((upper > 2/3) & (upper <= 1)).all())
                self.assertLess(upper.iloc[0], 1.)


class RecipeTests(unittest.TestCase):
    def test_recipes_save_reopen_and_follow_source_edits(self):
        raw = pd.DataFrame({"X": [0., 1e-9, 1e-8], "Y": [10., 14., 18.], "Base": [2., 4., 6.],
                            "A": [6, 79, 15], "B": [3, 12, 5]})
        recipes = [
            (CONCENTRATIONS, concentrations(**{"Replace zero X": True, "Change units": "Multiply by",
                                               "Unit factor": 1e9, "Logarithm": "Log10"})),
            (BASELINE, baseline(**{"Baseline column": "Base", "X": "X"})),
            (PRUNE, prune(Method="Average every K rows (sorted by X)")),
            (FRACTION, fraction(**{"Confidence interval": "Wilson (no continuity correction)"})),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "processing.alab"
            save_project(path, {"Data": Dataset(raw.copy(), analyses=list(recipes))})
            loaded = load_project(path)["Data"]
        self.assertEqual(loaded.analyses, recipes)
        before = {method: analyse(method, loaded.frame(mask_excluded=True), options) for method, options in recipes}
        loaded.raw.loc[1, "Y"] = 24.
        loaded.raw.loc[0, "A"] = 16
        snapshot = loaded.raw.copy()
        after = {method: analyse(method, loaded.frame(mask_excluded=True), options) for method, options in recipes}
        pd.testing.assert_frame_equal(loaded.raw, snapshot)
        self.assertEqual(after[BASELINE].tables["Processed data"]["Y"].tolist(), [8., 20., 12.])
        self.assertEqual(before[BASELINE].tables["Processed data"]["Y"].tolist(), [8., 10., 12.])
        self.assertAlmostEqual(after[FRACTION].tables["Fraction of column total"].loc[0, "A"], 16 / 110)
        np.testing.assert_allclose(after[PRUNE].tables["Pruned data"]["Y"], [17, 18])
        transformed = after[CONCENTRATIONS].tables["Transformed data"]
        self.assertEqual(transformed["Y"].tolist(), [10., 24., 18.])
        pd.testing.assert_series_equal(transformed["Base"], raw["Base"], check_dtype=False)


if __name__ == "__main__":
    unittest.main()
