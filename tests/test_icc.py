"""Intraclass correlation: the four coefficients against exact fractions, edge cases, bootstrap and figures.

The oracles never import the engine's estimator: they recompute the mean squares from the rows with ``fractions``
(or the standard library), and the bootstrap check copies the drawn rows explicitly.
"""
from fractions import Fraction
import json
from pathlib import Path
import pickle
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from analisi import icc
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "icc"
METHOD = icc.METHOD
RATERS = ["Reader A", "Reader B", "Reader C"]
COMBINATIONS = [(d, u) for d in icc.DEFINITIONS for u in icc.UNITS]


def options(**changes):
    return {"Raters": RATERS, "Subject": "Sample", "Definition": "Absolute agreement", "Unit": "Single measure",
            **changes}


def fixture(name):
    return pd.read_csv(DATA / f"{name}.csv")


def exact(rows, definition, unit):
    """McGraw and Wong from the rows of a balanced layout, in exact arithmetic."""
    rows = [[Fraction(value) for value in row] for row in rows]
    n, k = len(rows), len(rows[0])
    grand = sum(map(sum, rows)) / (n * k)
    row_means = [sum(row) / k for row in rows]
    col_means = [sum(row[j] for row in rows) / n for j in range(k)]
    ss_s = k * sum((m - grand) ** 2 for m in row_means)
    ss_r = n * sum((m - grand) ** 2 for m in col_means)
    ss_e = sum((rows[i][j] - row_means[i] - col_means[j] + grand) ** 2 for i in range(n) for j in range(k))
    s, r, e = ss_s / (n - 1), ss_r / (k - 1), ss_e / ((n - 1) * (k - 1))
    if definition == "Absolute agreement":
        denominator = s + (r - e) / n if unit == "Mean of raters" else s + (k - 1) * e + k * (r - e) / n
    else:
        denominator = s if unit == "Mean of raters" else s + (k - 1) * e
    return None if denominator == 0 else (s - e) / denominator, (ss_s, ss_r, ss_e)


def complete_rows(frame, columns=RATERS):
    return [tuple(row) for row in frame[columns].dropna().itertuples(index=False)]


def icc_row(result):
    return result.tables["ICC"].iloc[0]


class PublishedFixtures(unittest.TestCase):
    def test_every_combination_matches_the_frozen_fractions(self):
        expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
        for name, case in expected.items():
            frame = fixture(name)
            for key, value in case["estimates"].items():
                definition, unit = key.split("|")
                with self.subTest(case=name, key=key):
                    row = icc_row(analyse(METHOD, frame, options(Definition=definition, Unit=unit)))
                    self.assertEqual((row["N"], row["Raters"]), (case["n"], case["k"]))
                    self.assertAlmostEqual(row["Estimate"], float(Fraction(value)), delta=1e-12)
                    self.assertEqual(row["Status"], "Estimated")

    def test_oracle_inside_the_test_agrees_with_the_engine(self):
        for name in ("ratings", "shift"):
            for definition, unit in COMBINATIONS:
                with self.subTest(name=name, definition=definition, unit=unit):
                    frame = fixture(name)
                    truth, _ = exact(complete_rows(frame), definition, unit)
                    row = icc_row(analyse(METHOD, frame, options(Definition=definition, Unit=unit)))
                    self.assertAlmostEqual(row["Estimate"], float(truth), delta=1e-12)

    def test_shift_separates_consistency_from_agreement(self):
        frame = fixture("shift")
        self.assertEqual(icc_row(analyse(METHOD, frame, options(Definition="Consistency")))["Estimate"], 1.0)
        absolute = icc_row(analyse(METHOD, frame, options()))["Estimate"]
        self.assertAlmostEqual(absolute, 1 / 16, delta=1e-12)

    def test_default_recipe_is_absolute_agreement_single_measure(self):
        short = {"Raters": RATERS, "Subject": "Sample"}
        row = icc_row(analyse(METHOD, fixture("ratings"), short))
        self.assertEqual((row["Definition"], row["Unit"]), ("Absolute agreement", "Single measure"))
        self.assertAlmostEqual(row["Estimate"], 519 / 557, delta=1e-12)

    def test_registered_next_to_the_other_agreement_analyses(self):
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GROUPS["Group Comparison"])
        group = GROUPS["Group Comparison"]
        self.assertEqual(group.index(METHOD), group.index("Bland–Altman for repeated pairs") + 1)
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(METHODS[METHOD]["Raters"], "Multiple")
        self.assertEqual(METHODS["Bland–Altman"]["Method"][0], "Difference")  # legacy recipes untouched


class Tables(unittest.TestCase):
    def setUp(self):
        self.result = analyse(METHOD, fixture("ratings"), options())

    def test_minimum_sheets_and_columns(self):
        tables = self.result.tables
        self.assertEqual(list(tables), ["ICC", "ANOVA components", "Subjects", "Settings", "Excluded rows"])
        self.assertEqual(list(tables["ICC"].columns), ["Definition", "Unit", "Estimate", "N", "Raters", "Status"])
        self.assertEqual(len(tables["ICC"]), 1)
        self.assertEqual(tables["Excluded rows"]["Source row"].tolist(), [6])
        self.assertEqual(tables["Excluded rows"]["Subject"].tolist(), ["S6"])
        self.assertIn("Reader B", tables["Excluded rows"]["Reason"].iloc[0])

    def test_anova_components_match_the_fractions(self):
        _, (ss_s, ss_r, ss_e) = exact(complete_rows(fixture("ratings")), "Absolute agreement", "Single measure")
        table = self.result.tables["ANOVA components"]
        self.assertEqual(table["Source"].tolist(), ["Subjects", "Raters", "Residual"])
        self.assertEqual(table["df"].tolist(), [4, 2, 8])
        for value, truth in zip(table["SS"], (ss_s, ss_r, ss_e), strict=True):
            self.assertAlmostEqual(value, float(truth), delta=1e-9)
        for value, truth, df in zip(table["MS"], (ss_s, ss_r, ss_e), (4, 2, 8), strict=True):
            self.assertAlmostEqual(value, float(truth / df), delta=1e-9)

    def test_subjects_sheet_has_one_row_per_complete_subject(self):
        subjects = self.result.tables["Subjects"]
        self.assertEqual(subjects["Source row"].tolist(), [1, 2, 3, 4, 5])
        self.assertEqual(subjects["Subject"].tolist(), ["S1", "S2", "S3", "S4", "S5"])
        self.assertAlmostEqual(subjects["Mean"].iloc[3], (17 + 21 + 21) / 3)
        self.assertAlmostEqual(subjects["SD"].iloc[0], float(np.std([9, 12, 10], ddof=1)))
        self.assertEqual((subjects["Minimum"].iloc[2], subjects["Maximum"].iloc[2]), (3, 5))

    def test_settings_name_the_model_the_counts_and_the_conditioning(self):
        bootstrapped = analyse(METHOD, fixture("ratings"), options(**{"Bootstrap CI": True, "Seed": 5}))
        settings = dict(bootstrapped.tables["Settings"].itertuples(index=False))
        self.assertEqual(settings["Coefficient"], "ICC(A,1)")
        self.assertEqual((settings["Complete subjects"], settings["Raters"], settings["Excluded rows"]),
                         ("5", "3", "1"))
        self.assertEqual(settings["Rater columns"], "Reader A; Reader B; Reader C")
        self.assertEqual(settings["Inference"], "Conditional on the observed panel of raters")
        self.assertIn("conditional", settings["Note"])
        self.assertEqual(settings["Seed"], "5")
        self.assertIn("linear", settings["Quantile rule"])
        plain = dict(self.result.tables["Settings"].itertuples(index=False))
        self.assertNotIn("Seed", plain)

    def test_no_excluded_sheet_without_exclusions(self):
        self.assertNotIn("Excluded rows", analyse(METHOD, fixture("ratings").iloc[:5], options()).tables)


class RowsAndColumns(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"S": list("abcdef"), "A": [1., 2, 3, 4, 5, 6], "B": [2., 2, 5, 4, 7, 6],
                             "C": [1., 3, 3, 6, 5, 8]})

    def run_icc(self, frame, **changes):
        return analyse(METHOD, frame, {"Raters": ["A", "B", "C"], **changes})

    def test_a_blank_nan_or_excluded_cell_leaves_the_whole_row_out(self):
        frame = self.frame()
        frame = frame.astype({"B": object})
        frame.loc[1, "B"] = ""
        frame.loc[3, "C"] = np.nan
        result = self.run_icc(frame, Subject="S")
        self.assertEqual(result.tables["Excluded rows"]["Source row"].tolist(), [2, 4])
        self.assertEqual(result.tables["Subjects"]["Source row"].tolist(), [1, 3, 5, 6])
        truth, _ = exact([(1, 2, 1), (3, 5, 3), (5, 7, 5), (6, 6, 8)], "Absolute agreement", "Single measure")
        self.assertAlmostEqual(icc_row(result)["Estimate"], float(truth), delta=1e-12)

    def test_an_empty_worksheet_row_is_not_reported(self):
        frame = pd.concat([self.frame(), pd.DataFrame({"S": [None], "A": [np.nan], "B": [np.nan], "C": [np.nan]})],
                          ignore_index=True)
        result = self.run_icc(frame, Subject="S")
        self.assertNotIn("Excluded rows", result.tables)
        self.assertEqual(icc_row(result)["N"], 6)

    def test_row_position_is_the_identity_not_the_label(self):
        frame = self.frame()
        same = frame.assign(S="same")
        blank = frame.assign(S=None)
        base = icc_row(self.run_icc(frame))["Estimate"]
        for variant in (same, blank, frame.assign(S=[1, 1, 2, 2, 3, 3])):
            self.assertEqual(icc_row(self.run_icc(variant, Subject="S"))["Estimate"], base)
        self.assertEqual(self.run_icc(same, Subject="S").tables["Subjects"]["Subject"].tolist(), ["same"] * 6)

    def test_numbers_as_text_are_read_but_other_text_is_refused(self):
        texts = ["1", "2,0", " 3 ", "4", "5", "6"]
        frame = self.frame().assign(A=pd.Series(texts, dtype=object))
        self.assertEqual(icc_row(self.run_icc(frame))["N"], 6)
        for bad, message in (("abc", "row 2"), (float("inf"), "row 2"), ("-inf", "row 2"), (True, "row 2")):
            frame = self.frame().assign(A=pd.Series([texts[0], bad, *texts[2:]], dtype=object))
            with self.subTest(bad=bad), self.assertRaises(FieldError) as caught:
                self.run_icc(frame)
            self.assertEqual(caught.exception.field, "Raters")
            self.assertIn(message, str(caught.exception))

    def test_boolean_and_oversized_values_are_refused(self):
        frame = self.frame().assign(A=[True, False, True, False, True, False])
        with self.assertRaises(FieldError):
            self.run_icc(frame)
        with self.assertRaises(FieldError) as caught:
            self.run_icc(self.frame().assign(B=[1., 2, 3, 4, 5, 1e101]))
        self.assertIn("1e100", str(caught.exception))

    def test_negative_measurements_are_valid(self):
        frame = self.frame()
        shifted = frame.assign(A=frame["A"] - 50, B=frame["B"] - 50, C=frame["C"] - 50)
        self.assertAlmostEqual(icc_row(self.run_icc(shifted))["Estimate"], icc_row(self.run_icc(frame))["Estimate"],
                               delta=1e-12)

    def test_recipe_and_data_errors_name_their_field(self):
        frame = self.frame()
        cases = [({"Raters": ["A"]}, "Raters"), ({"Raters": ["A", "A", "B"]}, "Raters"),
                 ({"Raters": "A"}, "Raters"), ({"Raters": ["A", "Zed"]}, "Raters"),
                 ({"Subject": "A"}, "Subject"), ({"Subject": "Zed"}, "Subject"),
                 ({"Definition": "x"}, "Definition"), ({"Unit": "x"}, "Unit"), ({"Bootstrap CI": "yes"}, "Bootstrap CI"),
                 ({"Profile graph": 1}, "Profile graph"),
                 ({"Bootstrap CI": True, "Bootstrap replicates": 198}, "Bootstrap replicates"),
                 ({"Bootstrap CI": True, "Bootstrap replicates": 5001}, "Bootstrap replicates"),
                 ({"Bootstrap CI": True, "Bootstrap replicates": 2.5}, "Bootstrap replicates"),
                 ({"Bootstrap CI": True, "Seed": -1}, "Seed"), ({"Bootstrap CI": True, "Seed": 2**64}, "Seed"),
                 ({"Bootstrap CI": True, "Confidence level (%)": 100}, "Confidence level (%)"),
                 ({"Bootstrap CI": True, "Confidence level (%)": 0}, "Confidence level (%)")]
        for change, field in cases:
            with self.subTest(change=change), self.assertRaises(FieldError) as caught:
                self.run_icc(frame, **({"Raters": ["A", "B", "C"]} | change))
            self.assertEqual(caught.exception.field, field)
        with self.assertRaises(FieldError) as caught:
            self.run_icc(frame.iloc[:2])
        self.assertIn("At least 3 complete rows", str(caught.exception))
        incomplete = frame.copy()
        incomplete.loc[[0, 1, 2], "A"] = np.nan
        self.assertEqual(icc_row(self.run_icc(incomplete))["N"], 3)  # three complete rows are enough
        incomplete.loc[3, "A"] = np.nan
        with self.assertRaises(FieldError):
            self.run_icc(incomplete)
        with self.assertRaises(FieldError):
            self.run_icc(pd.concat([frame, frame["A"].rename("A")], axis=1))  # a duplicated column name

    def test_seed_is_read_as_an_exact_integer_up_to_uint64(self):
        typed = icc.normalized_options({"Raters": ["A", "B"], "Bootstrap CI": True, "Seed": "18446744073709551615"})
        self.assertEqual(typed["Seed"], 2**64 - 1)
        self.assertNotIn("Seed", icc.normalized_options({"Raters": ["A", "B"], "Seed": 3}))

    def test_limits_of_the_matrix(self):
        with self.assertRaises(FieldError):
            icc.read_settings({"Raters": [f"c{i}" for i in range(icc.MAX_RATERS + 1)]})


class EdgeCases(unittest.TestCase):
    def test_constant_data_leave_the_estimate_empty_with_a_reason(self):
        frame = pd.DataFrame({"A": [7.] * 5, "B": [7.] * 5, "C": [7.] * 5})
        for definition, unit in COMBINATIONS:
            with self.subTest(definition=definition, unit=unit):
                row = icc_row(analyse(METHOD, frame, {"Raters": ["A", "B", "C"], "Definition": definition,
                                                      "Unit": unit}))
                self.assertTrue(np.isnan(row["Estimate"]))
                self.assertTrue(row["Status"].startswith("Not estimated"))
                self.assertIn("denominator is zero", row["Status"])

    def test_identical_subjects_with_different_raters(self):
        frame = pd.DataFrame({"A": [1., 1, 1, 1], "B": [2., 2, 2, 2]})
        absolute = icc_row(analyse(METHOD, frame, {"Raters": ["A", "B"]}))
        self.assertEqual(absolute["Estimate"], 0.0)  # no subject variation, rater effect only
        consistency = icc_row(analyse(METHOD, frame, {"Raters": ["A", "B"], "Definition": "Consistency"}))
        self.assertTrue(np.isnan(consistency["Estimate"]))
        self.assertIn("zero", consistency["Status"])

    def test_negative_coefficients_are_reported(self):
        rows = [(1, 5), (5, 1), (3, 4), (4, 3), (2, 6), (6, 2)]
        frame = pd.DataFrame(rows, columns=["A", "B"])
        for definition, unit in COMBINATIONS:
            truth, _ = exact(rows, definition, unit)
            row = icc_row(analyse(METHOD, frame, {"Raters": ["A", "B"], "Definition": definition, "Unit": unit}))
            if unit == "Single measure" or definition == "Consistency":
                self.assertLess(truth, 0, (definition, unit))
            self.assertAlmostEqual(row["Estimate"], float(truth), delta=1e-12)
            self.assertEqual(row["Status"], "Estimated")
        note = dict(analyse(METHOD, frame, {"Raters": ["A", "B"]}).tables["Settings"].itertuples(index=False))
        self.assertIn("negative", note["Note"])

    def test_scaling_and_shifting_every_measurement_keeps_the_icc(self):
        rng = np.random.default_rng(11)
        base = rng.normal(size=(30, 1)) * 4 + rng.normal(size=(30, 4))
        base[:, 2] += 1.5
        reference = {c: icc_row(analyse(METHOD, pd.DataFrame(base, columns=list("ABCD")),
                                        {"Raters": list("ABCD"), "Definition": c[0], "Unit": c[1]}))["Estimate"]
                     for c in COMBINATIONS}
        for factor, shift in ((1e-150, 0.), (1e-8, 5e-8), (1e30, 0.), (1e90, 1e92), (-3.7, 0.), (1., 1e9), (1., -1e12)):
            frame = pd.DataFrame(base * factor + shift, columns=list("ABCD"))
            for (definition, unit), expected in reference.items():
                with self.subTest(factor=factor, shift=shift, key=(definition, unit)):
                    row = icc_row(analyse(METHOD, frame, {"Raters": list("ABCD"), "Definition": definition,
                                                          "Unit": unit}))
                    self.assertEqual(row["Status"], "Estimated")
                    # a shift of 1e9 (1e12) leaves ~1e-7 (1e-4) absolute resolution on measurements of size 1: the
                    # rounding of the input itself, not of the engine
                    tolerance = 1e-3 if abs(shift) >= 1e12 else 1e-7 if abs(shift) >= 1e9 else 1e-11
                    self.assertAlmostEqual(row["Estimate"], expected, delta=tolerance)

    def test_components_are_reported_in_the_units_of_the_data(self):
        frame = fixture("ratings")
        scaled = frame.assign(**{name: frame[name] * 1e50 for name in RATERS})
        base = analyse(METHOD, frame, options()).tables["ANOVA components"]
        big = analyse(METHOD, scaled, options()).tables["ANOVA components"]
        for column in ("SS", "MS"):
            np.testing.assert_allclose(big[column], base[column] * 1e100, rtol=1e-12)

    def test_tiny_data_keep_the_icc_even_when_squares_are_not_representable(self):
        frame = fixture("ratings")
        tiny = frame.assign(**{name: frame[name] * 1e-200 for name in RATERS})
        result = analyse(METHOD, tiny, options())
        self.assertAlmostEqual(icc_row(result)["Estimate"], 519 / 557, delta=1e-12)
        note = dict(result.tables["Settings"].itertuples(index=False))["Note"]
        self.assertIn("smallest representable", note)

    def test_a_negative_denominator_still_reports_the_formula_with_a_note(self):
        # Absolute agreement, mean of raters: MSo + (MSr − MSe) / n < 0 when the subjects do not differ.
        rows = [(1, 9), (2, 8), (3, 7), (4, 6), (9, 1), (8, 2)]
        frame = pd.DataFrame(rows, columns=["A", "B"])
        truth, _ = exact(rows, "Absolute agreement", "Mean of raters")
        result = analyse(METHOD, frame, {"Raters": ["A", "B"], "Unit": "Mean of raters"})
        self.assertAlmostEqual(icc_row(result)["Estimate"], float(truth), delta=1e-12)
        self.assertIn("denominator is negative", dict(result.tables["Settings"].itertuples(index=False))["Note"])

    def test_the_minimum_layout_works(self):
        frame = pd.DataFrame({"A": [1., 2, 4], "B": [2., 2, 5]})
        truth, _ = exact([(1, 2), (2, 2), (4, 5)], "Absolute agreement", "Single measure")
        self.assertAlmostEqual(icc_row(analyse(METHOD, frame, {"Raters": ["A", "B"]}))["Estimate"], float(truth),
                               delta=1e-12)

    def test_the_order_of_the_raters_does_not_change_the_estimate_but_is_kept(self):
        frame = fixture("ratings")
        forward = analyse(METHOD, frame, options())
        backward = analyse(METHOD, frame, options(Raters=RATERS[::-1]))
        self.assertAlmostEqual(icc_row(forward)["Estimate"], icc_row(backward)["Estimate"], delta=1e-13)
        self.assertEqual(dict(backward.tables["Settings"].itertuples(index=False))["Rater columns"],
                         "Reader C; Reader B; Reader A")
        ticks = [text.get_text() for text in backward.figure.axes[0].get_xticklabels()]
        self.assertEqual(ticks, RATERS[::-1])

    def test_integer_and_object_columns(self):
        frame = fixture("shift")
        as_object = frame.astype({name: object for name in RATERS})
        self.assertEqual(icc_row(analyse(METHOD, as_object, options()))["Estimate"],
                         icc_row(analyse(METHOD, frame, options()))["Estimate"])

    def test_options_are_not_modified(self):
        recipe = options(**{"Bootstrap CI": True, "Seed": 3})
        before = json.dumps(recipe, sort_keys=True)
        analyse(METHOD, fixture("ratings"), recipe)
        self.assertEqual(json.dumps(recipe, sort_keys=True), before)


class Bootstrap(unittest.TestCase):
    def frame(self):
        rng = np.random.default_rng(5)
        subject = rng.normal(size=(24, 1)) * 3
        return pd.DataFrame(subject + rng.normal(size=(24, 3)) + [0, .5, -.4], columns=RATERS).round(3)

    def recipe(self, **changes):
        return {"Raters": RATERS, "Bootstrap CI": True, "Bootstrap replicates": 199, "Seed": 17, **changes}

    def reference(self, frame, recipe):
        """Percentile interval from explicit copies of the drawn rows, one exact fraction oracle per replicate."""
        rows = complete_rows(frame)
        n = len(rows)
        rng = np.random.Generator(np.random.PCG64(recipe["Seed"]))
        values = []
        for _ in range(recipe["Bootstrap replicates"]):
            drawn = [rows[i] for i in rng.integers(0, n, size=n)]
            truth, _ = exact(drawn, recipe.get("Definition", "Absolute agreement"),
                             recipe.get("Unit", "Single measure"))
            values.append(np.nan if truth is None else float(truth))
        values = np.asarray(values)
        valid = values[np.isfinite(values)]
        alpha = 1 - recipe.get("Confidence level (%)", 95.0) / 100
        return np.quantile(valid, [alpha / 2, 1 - alpha / 2], method="linear"), len(valid)

    def test_interval_equals_the_percentiles_of_explicitly_copied_rows(self):
        frame = self.frame()
        for change in ({}, {"Definition": "Consistency", "Unit": "Mean of raters", "Confidence level (%)": 90.0}):
            recipe = self.recipe(**change)
            with self.subTest(change=change):
                row = icc_row(analyse(METHOD, frame, recipe))
                (low, high), valid = self.reference(frame, recipe)
                self.assertAlmostEqual(row["CI low"], low, delta=1e-9)
                self.assertAlmostEqual(row["CI high"], high, delta=1e-9)
                self.assertEqual(row["Interval status"], "Percentile interval")
                settings = dict(analyse(METHOD, frame, recipe).tables["Settings"].itertuples(index=False))
                self.assertEqual(settings["Valid replicates"], str(valid))

    def test_same_seed_same_numbers_other_seed_other_numbers(self):
        frame = self.frame()
        first = analyse(METHOD, frame, self.recipe()).tables
        again = analyse(METHOD, frame, self.recipe()).tables
        other = analyse(METHOD, frame, self.recipe(Seed=18)).tables
        pd.testing.assert_frame_equal(first["ICC"], again["ICC"], check_exact=True)
        self.assertNotEqual(first["ICC"]["CI low"].iloc[0], other["ICC"]["CI low"].iloc[0])
        self.assertEqual(first["ICC"]["Estimate"].iloc[0], other["ICC"]["Estimate"].iloc[0])

    def test_interval_columns_only_with_the_bootstrap(self):
        plain = analyse(METHOD, self.frame(), {"Raters": RATERS}).tables["ICC"]
        self.assertNotIn("CI low", plain.columns)

    def test_too_few_valid_replicates_leave_the_interval_empty(self):
        # Consistency of the mean needs MSo > 0, and three of the four row means are equal: about 32 % of replicates
        # draw only those rows and have no variation between subjects.
        frame = pd.DataFrame({"A": [1., 2, 3, 10], "B": [3., 2, 1, 10]})
        recipe = {"Raters": ["A", "B"], "Definition": "Consistency", "Unit": "Mean of raters",
                  "Bootstrap CI": True, "Bootstrap replicates": 1000, "Seed": 4}
        result = analyse(METHOD, frame, recipe)
        row = icc_row(result)
        self.assertEqual(row["Interval status"], "Too few valid replicates")
        self.assertTrue(np.isnan(row["CI low"]) and np.isnan(row["CI high"]))
        self.assertFalse(np.isnan(row["Estimate"]))
        self.assertIn("left empty", dict(result.tables["Settings"].itertuples(index=False))["Note"])

    def test_invalid_replicates_are_counted_but_do_not_stop_the_interval(self):
        frame = pd.DataFrame({"A": [1., 2, 3, 10, 12], "B": [3., 2, 1, 10, 14], "C": [2., 2, 2, 11, 13]})
        recipe = {"Raters": ["A", "B", "C"], "Definition": "Consistency", "Unit": "Mean of raters",
                  "Bootstrap CI": True, "Bootstrap replicates": 400, "Seed": 8}
        result = analyse(METHOD, frame, recipe)
        valid = int(dict(result.tables["Settings"].itertuples(index=False))["Valid replicates"])
        self.assertLess(valid, 400)
        self.assertGreaterEqual(valid, 0.8 * 400)
        self.assertEqual(icc_row(result)["Interval status"], "Percentile interval")

    def test_budget_is_checked_before_any_sample_is_drawn(self):
        frame = pd.DataFrame(np.random.default_rng(0).normal(size=(20_000, 3)), columns=list("ABC"))
        recipe = {"Raters": list("ABC"), "Bootstrap CI": True, "Bootstrap replicates": 400}
        with mock.patch.object(icc, "bootstrap", side_effect=AssertionError("nothing is resampled")):
            with self.assertRaises(FieldError) as caught:
                analyse(METHOD, frame, recipe)
        self.assertEqual(caught.exception.field, "Bootstrap replicates")
        self.assertIn("24,000,000", str(caught.exception))
        recipe["Bootstrap replicates"] = 333  # 333 × 20 000 × 3 = 19 980 000 cells: inside the budget
        with mock.patch.object(icc, "bootstrap", return_value=np.linspace(0, 1, 333)):
            self.assertEqual(icc_row(analyse(METHOD, frame, recipe))["Interval status"], "Percentile interval")

    def test_cancel(self):
        frame = self.frame()
        stop = threading.Event()
        stop.set()
        for run in (lambda: analyse(METHOD, frame, self.recipe(), cancel=stop),
                    lambda: icc.bootstrap(icc.prepare(frame, self.recipe()), stop, processes=1)):
            with self.assertRaises(icc.IccCancelled) as caught:
                run()
            self.assertIsInstance(caught.exception, MonteCarloCancelled)
            self.assertIsInstance(caught.exception, InterruptedError)

    def test_cancel_between_blocks_of_a_long_job(self):
        frame = pd.DataFrame(np.random.default_rng(1).normal(size=(4000, 4)), columns=list("ABCD"))
        recipe = {"Raters": list("ABCD"), "Bootstrap CI": True, "Bootstrap replicates": 1200}
        stop = threading.Event()
        threading.Timer(.05, stop.set).start()
        with self.assertRaises(icc.IccCancelled):
            icc.bootstrap(icc.prepare(frame, recipe), stop, processes=1)

    def test_cancellable_only_with_the_bootstrap(self):
        self.assertTrue(icc.cancellable(METHOD, {"Bootstrap CI": True}))
        self.assertFalse(icc.cancellable(METHOD, {}))
        self.assertFalse(icc.cancellable("t-test", {"Bootstrap CI": True}))


class Figures(unittest.TestCase):
    def test_profile_graph_follows_the_order_and_is_optional(self):
        result = analyse(METHOD, fixture("ratings"), options())
        axes = result.figure.axes[0]
        self.assertEqual([text.get_text() for text in axes.get_xticklabels()], RATERS)
        self.assertEqual(len([line for line in axes.lines if line.get_gid() == "icc:subject"]), 5)
        self.assertIsNone(analyse(METHOD, fixture("ratings"), options(**{"Profile graph": False})).figure)

    def test_many_rows_limit_the_visible_lines_and_say_so(self):
        frame = pd.DataFrame(np.random.default_rng(2).normal(size=(500, 3)), columns=RATERS)
        result = analyse(METHOD, frame, {"Raters": RATERS})
        axes = result.figure.axes[0]
        self.assertEqual(len([line for line in axes.lines if line.get_gid() == "icc:subject"]), icc.MAX_LINES)
        legend = " ".join(text.get_text() for text in result.figure.legends[0].get_texts())
        self.assertIn(f"{icc.MAX_LINES} of 500", legend)
        self.assertEqual(len(result.tables["Subjects"]), 500)  # the sheets keep every row

    def test_figure_pickles_and_text_is_not_math(self):
        figure = analyse(METHOD, fixture("ratings"), options()).figure
        self.assertIsNotNone(pickle.loads(pickle.dumps(figure)))
        weird = fixture("ratings").rename(columns={"Reader A": "$x$ a"})
        figure = analyse(METHOD, weird, options(Raters=["$x$ a", "Reader B", "Reader C"])).figure
        self.assertEqual(figure.axes[0].get_xticklabels()[0].get_text(), "$x$ a")
        self.assertFalse(figure.axes[0].get_xticklabels()[0].get_parse_math())


class SummaryAndCatalog(unittest.TestCase):
    def test_summary_counts_without_raising(self):
        frame = fixture("ratings")
        self.assertEqual(icc.summary(frame, {"Raters": RATERS}), {"complete": 5, "excluded": 1, "raters": 3})
        self.assertEqual(icc.summary(frame, {"Raters": ["Reader A", "Nope"]}),
                         {"complete": 6, "excluded": 0, "raters": 1})
        self.assertEqual(icc.summary(frame, {}), {"complete": 0, "excluded": 0, "raters": 0})

    def test_every_error_message_has_an_italian_catalog_entry(self):
        from analisi.i18n import set_language, translate_message
        frame = fixture("ratings")
        triggers = [({"Raters": "A"}, frame), ({"Raters": ["A"]}, frame), ({"Raters": ["Reader A", "Reader A"]}, frame),
                    ({"Raters": ["Reader A", "Nope"]}, frame), ({"Subject": "Reader A"}, frame),
                    ({"Definition": "x"}, frame), ({"Bootstrap CI": True, "Confidence level (%)": 100}, frame),
                    ({"Bootstrap CI": True, "Bootstrap replicates": 10}, frame),
                    ({"Bootstrap CI": True, "Bootstrap replicates": 5000},
                     pd.DataFrame(np.zeros((6000, 3)), columns=RATERS)),
                    ({}, frame.iloc[:2]), ({}, frame.assign(**{"Reader A": ["x"] * 6})),
                    ({}, frame.assign(**{"Reader A": [1., 2, 3, 4, 5, np.inf]})),
                    ({}, frame.assign(**{"Reader A": [1., 2, 3, 4, 5, 1e200]}))]
        set_language("it")
        try:
            for change, data in triggers:
                with self.subTest(change=change), self.assertRaises(FieldError) as caught:
                    icc.check_options(data, {"Raters": RATERS, **change})
                message = str(caught.exception)
                self.assertNotEqual(translate_message(message, icc.ERROR_PREFIX), message, message)
        finally:
            set_language("en")


if __name__ == "__main__":
    unittest.main()
