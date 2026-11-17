"""Detailed Correlation: numeric contract, source rows and the legacy sheet.

Gold numbers are the frozen fixture ``expected.json``. This file does not import the packet oracle.
"""
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi.correlation_details import correlation_statistics
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "correlation_details"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
BY_ID = {case["id"]: case for case in CASES}


def close(got, expected, case, key):
    if expected is None:
        assert pd.isna(got), (case, key, got)
        return
    if isinstance(expected, float):
        assert math.isclose(got, expected, rel_tol=2e-11, abs_tol=2e-13), (case, key, got, expected)
        return
    assert got == expected, (case, key, got, expected)


def gold(case_id, **overrides):
    case = BY_ID[case_id]
    return correlation_statistics(
        case["x"], case["y"],
        method=overrides.get("method", case.get("method", "Pearson")),
        alternative=overrides.get("alternative", case.get("alternative", "Two-sided")),
        confidence=overrides.get("confidence", case.get("confidence", 95)),
        p_method=overrides.get("p_method", case.get("p_method", "Automatic")),
    )


class CorrelationStatistics(unittest.TestCase):
    def test_frozen_cases(self):
        for case_id, expected in EXPECTED.items():
            got = gold(case_id)
            for key, value in expected.items():
                close(got[key], value, case_id, key)
            if got["CI method"] == "Unavailable":
                self.assertTrue(got["Reason"])
            if case_id.startswith("spearman") or case_id.startswith("kendall"):
                self.assertIsNone(got["R²"])

    def test_inputs_are_not_mutated(self):
        case = BY_ID["pearson-95"]
        x, y = np.array(case["x"], dtype=float), np.array(case["y"], dtype=float)
        original = x.copy(), y.copy()
        gold("pearson-95")
        correlation_statistics(x, y)
        np.testing.assert_array_equal(x, original[0])
        np.testing.assert_array_equal(y, original[1])

    def test_small_resolvable_variation_is_not_constant(self):
        got = gold("pearson-small-resolvable")
        self.assertGreater(abs(got["Coefficient"]), 0)
        self.assertEqual(got["P method"], "Pearson beta")

    def test_perfect_interval_is_degenerate(self):
        got = gold("pearson-perfect")
        self.assertEqual((got["Lower"], got["Upper"], got["CI method"]), (1.0, 1.0, "Fisher z"))

    def test_three_pairs_omit_the_interval(self):
        got = gold("pearson-three-no-ci")
        self.assertIn("below 4", got["Reason"])
        self.assertEqual(got["CI method"], "Unavailable")

    def test_spearman_alternatives_differ_and_have_no_interval(self):
        two, positive, negative = gold("spearman-ties-two"), gold("spearman-ties-positive"), gold("spearman-ties-negative")
        self.assertNotEqual(two["p"], positive["p"])
        self.assertNotEqual(two["Coefficient"], negative["Coefficient"])
        for got in (two, positive, negative):
            self.assertEqual(got["P method"], "Exact")
            self.assertIsNone(got["Lower"])
            self.assertIn("below 11", got["Reason"])

    def test_automatic_above_the_budget_says_why(self):
        got = gold("spearman-11-ci")
        self.assertEqual((got["P method"], got["CI method"]), ("Approximate", "Bonett–Wright"))
        self.assertIn("exact budget", got["Reason"])

    def test_exact_above_the_budget_is_a_field_error(self):
        with self.assertRaises(FieldError) as caught:
            gold("spearman-11-ci", p_method="Exact")
        self.assertEqual(caught.exception.field, "Spearman p values")
        self.assertIn("9", str(caught.exception))

    def test_kendall_declares_the_asymptotic_method_and_no_interval(self):
        got = gold("kendall-ties", p_method="Exact")
        self.assertEqual(got["P method"], "Kendall asymptotic")
        self.assertEqual(got["CI method"], "Unavailable")
        self.assertIn("Kendall", got["Reason"])

    def test_bad_level_and_short_input(self):
        case = BY_ID["pearson-95"]
        for level in (0, 100, "abc", float("inf")):
            with self.assertRaises(FieldError) as caught:
                correlation_statistics(case["x"], case["y"], confidence=level)
            self.assertEqual(caught.exception.field, "Confidence level (%)")
        with self.assertRaises(ValueError):
            correlation_statistics([1, 2], [1, 2])
        with self.assertRaises(ValueError):
            correlation_statistics([1, 1, 1], [1, 2, 3])


class DetailedCorrelationResult(unittest.TestCase):
    def test_catalog_keeps_correlation_and_adds_nothing_to_the_matrix(self):
        self.assertIn("Detailed results", METHODS["Correlation"])
        self.assertEqual(METHODS["Correlation"]["Detailed results"], False)
        self.assertEqual(GROUPS["Data Exploration and Summary"][3:7], (
            "Correlation", "Correlate against control", "Compare independent correlations", "Correlation matrix"))
        self.assertIn("Correlation", GRAPH_METHODS)

    def test_legacy_sheet_ignores_hidden_fields(self):
        frame = pd.DataFrame({"X": BY_ID["pearson-95"]["x"], "Y": BY_ID["pearson-95"]["y"]})
        plain = {"X": "X", "Y": "Y", "Method": "Pearson"}
        dirty = {**plain, "Detailed results": False, "Alternative": "nope", "Confidence level (%)": "abc",
                 "Spearman p values": "Exact"}
        left, right = analyse("Correlation", frame, plain), analyse("Correlation", frame, dirty)
        string_flag = analyse("Correlation", frame, {**plain, "Detailed results": "yes"})
        for result in (left, right, string_flag):
            self.assertEqual(list(result.tables), ["Correlation"])
            self.assertEqual(list(result.tables["Correlation"].index), ["N", "Coefficient", "p"])
        pd.testing.assert_series_equal(left.tables["Correlation"]["Value"], right.tables["Correlation"]["Value"])
        pd.testing.assert_series_equal(left.tables["Correlation"]["Value"], string_flag.tables["Correlation"]["Value"])
        np.testing.assert_allclose(left.figure.axes[0].collections[0].get_offsets(),
                                   right.figure.axes[0].collections[0].get_offsets())
        self.assertEqual(len(left.figure.axes[0].collections), 1)

    def test_same_column_is_a_field_error_only_when_detailed(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4], "Y": [1, 2, 4, 3]})
        with self.assertRaises(ValueError):
            analyse("Correlation", frame, {"X": "X", "Y": "X", "Method": "Pearson"})
        with self.assertRaises(FieldError) as caught:
            analyse("Correlation", frame, {"X": "X", "Y": "X", "Method": "Pearson", "Detailed results": True})
        self.assertEqual(caught.exception.field, "Y")

    def test_source_row_keeps_the_frame_index(self):
        values = BY_ID["pearson-95"]
        frame = pd.DataFrame({"X": values["x"], "Y": values["y"]}, index=[2, 5, 9, 10, 11, 40])
        frame.loc[9, "Y"] = np.nan
        result = analyse("Correlation", frame, {"X": "X", "Y": "Y", "Method": "Pearson", "Detailed results": True,
                                                "Confidence level (%)": 90, "Alternative": "Positive"})
        sheet = result.tables["Correlation"]["Value"]
        self.assertEqual(int(sheet["N"]), 5)
        self.assertEqual(sheet["P method"], "Pearson beta")
        self.assertEqual(sheet["CI method"], "Fisher z")
        self.assertEqual(result.tables["Settings"]["Value"]["Alternative"], "Positive")
        self.assertEqual(result.tables["Settings"]["Value"]["Confidence level (%)"], 90)
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [2, 5, 10, 11, 40])
        self.assertNotIn("Ranks", result.tables)
        self.assertEqual(list(result.tables["Correlation"].index[:3]), ["N", "Coefficient", "p"])
        settings = result.tables["Settings"]["Value"]
        self.assertIn("two-sided", settings["Confidence intervals"])
        self.assertEqual(int(settings["Rows omitted (incomplete pairs)"]), 1)

    def test_duplicate_string_index_and_literal_name(self):
        frame = pd.DataFrame({"$x$": [1.0, 2.0, 3.0, 4.0], "Y": [1.0, 3.0, 2.0, 5.0]}, index=pd.Index(["a", "a", "b", "c"]))
        before = frame.copy(deep=True)
        result = analyse("Correlation", frame, {"X": "$x$", "Y": "Y", "Method": "Spearman", "Detailed results": True,
                                                "Spearman p values": "Exact"})
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), ["a", "a", "b", "c"])
        self.assertEqual(result.tables["Ranks"]["Source row"].tolist(), ["a", "a", "b", "c"])
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "$x$")
        self.assertFalse(axes.xaxis.label.get_parse_math())
        self.assertFalse(axes.title.get_parse_math())
        offsets = axes.collections[0].get_offsets()
        np.testing.assert_allclose(offsets[:, 0], frame["$x$"])
        self.assertEqual(len(axes.lines), 0)

    def test_text_and_infinity_name_the_column(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4], "Y": [1, 2, "no", 4]})
        with self.assertRaises(FieldError) as caught:
            analyse("Correlation", frame, {"X": "X", "Y": "Y", "Method": "Pearson", "Detailed results": True})
        self.assertEqual(caught.exception.field, "Y")
        frame = pd.DataFrame({"X": [1, np.inf, 3, 4], "Y": [1, 2, 3, 4]})
        with self.assertRaises(FieldError) as caught:
            analyse("Correlation", frame, {"X": "X", "Y": "Y", "Method": "Kendall", "Detailed results": True})
        self.assertEqual(caught.exception.field, "X")

    def test_exact_nine_runs_and_reports_exact(self):
        frame = pd.read_csv(DATA / "exact-nine.csv")
        result = analyse("Correlation", frame, {"X": "X", "Y": "Y", "Method": "Spearman", "Detailed results": True,
                                                "Spearman p values": "Exact", "Alternative": "Two-sided"})
        sheet = result.tables["Correlation"]["Value"]
        self.assertEqual((int(sheet["N"]), sheet["P method"]), (9, "Exact"))
        self.assertTrue(pd.isna(sheet["Lower"]))
        self.assertEqual(len(result.tables["Pairs"]), 9)


if __name__ == "__main__":
    unittest.main()
