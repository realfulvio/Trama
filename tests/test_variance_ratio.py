"""Two-sample variance ratio: exact F interval, orientation, and the optional t-test sheet."""
import math
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.field_error import FieldError
from analisi.i18n import set_language
from analisi.lognormal_tests import LOGNORMAL
from analisi.variance_ratio import (
    GRAPH, GRAPH_NONE, GRAPH_SD, GRAPH_VARIANCE, KEYS, LEVEL, METHOD, SHEET, SHOW, analysis,
    compare_variances,
)
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse


A = [0, 2, 4]
B = [0, 1, 2]
CLOSE = dict(rel_tol=1e-9, abs_tol=1e-11)


def close(test, left, right):
    test.assertTrue(math.isclose(float(left), float(right), **CLOSE), (left, right))


class Engine(unittest.TestCase):
    def test_exact_f22_fixture(self):
        result = compare_variances(A, B)
        expected = {
            "N first": 3, "N second": 3, "Variance first": 4.0, "Variance second": 1.0,
            "Variance ratio": 4.0, "SD ratio": 2.0, "F": 4.0, "DFn": 2, "DFd": 2, "p": 0.4,
            "Variance ratio lower": 4 / 39, "Variance ratio upper": 156.0,
            "SD ratio lower": math.sqrt(4 / 39), "SD ratio upper": math.sqrt(156.0),
        }
        for key, value in expected.items():
            close(self, result[key], value)
        self.assertEqual(list(result), list(KEYS))
        # F(2, 2) has a closed form. SciPy is the second oracle, not a looser tolerance.
        self.assertAlmostEqual(stats.f.cdf(4, 2, 2), 0.8, places=12)
        self.assertAlmostEqual(stats.f.ppf(0.975, 2, 2), 39, places=9)

    def test_reversing_groups_reciprocates_estimates_and_keeps_p(self):
        forward = compare_variances(A, B)
        reverse = compare_variances(B, A)
        close(self, reverse["Variance ratio"], 0.25)
        close(self, reverse["SD ratio"], 0.5)
        close(self, reverse["Variance ratio lower"], 1 / 156)
        close(self, reverse["Variance ratio upper"], 39 / 4)
        close(self, reverse["SD ratio lower"], math.sqrt(1 / 156))
        close(self, reverse["SD ratio upper"], math.sqrt(39 / 4))
        close(self, reverse["p"], forward["p"])
        self.assertEqual((reverse["F"], reverse["DFn"], reverse["DFd"]), (4, 2, 2))

    def test_location_and_common_scale_do_not_change_the_ratio(self):
        base = compare_variances(A, B)
        shifted = compare_variances([value + 10 for value in A], [value + 10 for value in B])
        scaled = compare_variances([value * 7 for value in A], [value * 7 for value in B])
        for result in (shifted, scaled):
            close(self, result["Variance ratio"], base["Variance ratio"])
            close(self, result["p"], base["p"])
            close(self, result["Variance ratio lower"], base["Variance ratio lower"])

    def test_unequal_n_matches_the_recorded_scipy_interval(self):
        result = compare_variances([1, 2, 4, 5, 7], [1, 2, 3])
        close(self, result["Variance ratio"], 5.7)
        close(self, result["p"], 0.309573361082206)
        close(self, result["Variance ratio lower"], 0.14522878475379955)
        close(self, result["Variance ratio upper"], 60.699930651839054)
        ratio = result["Variance ratio"]
        lower = ratio / stats.f.ppf(0.975, 4, 2)
        upper = ratio / stats.f.ppf(0.025, 4, 2)
        close(self, result["Variance ratio lower"], lower)
        close(self, result["Variance ratio upper"], upper)
        self.assertEqual((result["DFn"], result["DFd"]), (4, 2))

    def test_folded_f_uses_the_numerator_groups_degrees_of_freedom(self):
        result = compare_variances([0, 1, 2], [0, 2, 4, 6])
        self.assertLess(result["Variance ratio"], 1)
        self.assertEqual((result["DFn"], result["DFd"]), (3, 2))
        close(self, result["F"], 1 / result["Variance ratio"])

    def test_equal_variances_keep_the_first_sample_as_the_numerator(self):
        result = compare_variances([0, 1, 2], [-1, -1, 0, 1, 1])
        close(self, result["Variance ratio"], 1)
        self.assertEqual((result["F"], result["DFn"], result["DFd"]), (1.0, 2, 4))

    def test_scales_keep_ratio_p_and_interval(self):
        for scale in (1e-140, 1e140):
            result = compare_variances([0, 2 * scale, 4 * scale], [0, scale, 2 * scale])
            close(self, result["Variance ratio"], 4)
            close(self, result["p"], 0.4)
            close(self, result["Variance ratio lower"], 4 / 39)
            close(self, result["Variance ratio upper"], 156)
            self.assertTrue(math.isfinite(result["Variance first"]))
            self.assertTrue(math.isfinite(result["Variance second"]))

    def test_underflowed_variance_stays_out_of_the_ratio(self):
        scale = 1e-200
        result = compare_variances([0, 2 * scale, 4 * scale], [0, scale, 2 * scale])
        close(self, result["Variance ratio"], 4)
        close(self, result["p"], 0.4)
        close(self, result["Variance ratio lower"], 4 / 39)
        self.assertTrue(math.isnan(result["Variance first"]))
        self.assertTrue(math.isnan(result["Variance second"]))
        frame = pd.DataFrame({"A": [0, 2 * scale, 4 * scale], "B": [0, scale, 2 * scale]})
        settings = analysis(frame, _options()).tables["Settings"]["Value"]
        self.assertIn("cannot be stored", settings["Scale"])

    def test_non_representable_ratio_names_the_reason(self):
        with self.assertRaises(ValueError) as caught:
            compare_variances([0, 1e200, 2e200], [0, 1e-200, 2e-200])
        self.assertIn("floating-point", str(caught.exception))

    def test_centering_survives_a_large_offset(self):
        offset = 1e8
        result = compare_variances([offset, offset + 2, offset + 4], [0, 2, 4])
        close(self, result["Variance ratio"], 1)
        close(self, result["Variance first"], 4)
        close(self, result["p"], 1)

    def test_lognormal_uses_natural_logs(self):
        result = compare_variances([math.exp(x) for x in (0, 2, 4)], [math.exp(x) for x in (0, 1, 2)],
                                    distribution="Lognormal")
        close(self, result["Variance ratio"], 4)
        close(self, result["p"], 0.4)
        close(self, result["Variance first"], 4)

    def test_missing_values_are_dropped_inside_each_sample(self):
        result = compare_variances([0, 2, 4, None], [None, 0, 1, 2])
        close(self, result["N first"], 3)
        close(self, result["N second"], 3)
        close(self, result["p"], 0.4)
        separate = compare_variances([1, None, 3], [10, 12, None])
        self.assertEqual((separate["N first"], separate["N second"]), (2, 2))

    def test_comma_decimals_text_bool_and_infinity(self):
        result = compare_variances(["0", "2,5", "5"], [0, 1, 2])
        self.assertEqual(result["N first"], 3)
        for sample in ([True, 1, 2], [1, math.inf, 2], [1, "no", 2], [1]):
            with self.assertRaises(ValueError):
                compare_variances(sample, B)
        with self.assertRaises(ValueError):
            compare_variances([1, 1, 1], B)

    def test_invalid_level_distribution_and_bool_flag(self):
        for level in (0, 100, math.nan, True, "95"):
            with self.assertRaises(ValueError):
                compare_variances(A, B, level=level)
        with self.assertRaises(ValueError):
            compare_variances(A, B, distribution="normal")
        with self.assertRaises(ValueError):
            compare_variances([0, 2, 4], [1, 2, 3], distribution="Lognormal")


def _options(**changes):
    options = {"First": "A", "Second": "B", LEVEL: 95.0, "Distribution": "Normal", GRAPH: GRAPH_NONE}
    options.update(changes)
    return options


class DialogResult(unittest.TestCase):
    def test_dispatcher_table_and_optional_figure(self):
        frame = pd.DataFrame({"A": A, "B": B})
        result = analyse(METHOD, frame, _options())
        self.assertEqual(list(result.tables), [SHEET, "Summary", "Settings"])
        close(self, result.tables[SHEET].at["p", "Value"], 0.4)
        self.assertIsNone(result.figure)
        self.assertNotIn(METHOD, GRAPH_METHODS)
        self.assertEqual(list(result.tables[SHEET].index), list(KEYS))
        drawn = analyse(METHOD, frame, _options(**{GRAPH: GRAPH_VARIANCE}))
        line = next(artist for artist in drawn.figure.axes[0].lines if artist.get_gid() == "variance-ratio:interval")
        lower = drawn.tables[SHEET].at["Variance ratio lower", "Value"]
        upper = drawn.tables[SHEET].at["Variance ratio upper", "Value"]
        self.assertEqual(list(line.get_xdata()), [lower, upper])
        self.assertEqual(drawn.figure.axes[0].get_xscale(), "log")
        reference = next(artist for artist in drawn.figure.axes[0].lines
                         if artist.get_gid() == "variance-ratio:reference")
        self.assertEqual(list(reference.get_xdata()), [1, 1])
        self.assertEqual(drawn.figure.axes[0]._tramastat_numeric_axes, ("x",))
        sd = analyse(METHOD, frame, _options(**{GRAPH: GRAPH_SD}))
        sd_line = next(artist for artist in sd.figure.axes[0].lines if artist.get_gid() == "variance-ratio:interval")
        self.assertEqual(list(sd_line.get_xdata()), [
            sd.tables[SHEET].at["SD ratio lower", "Value"], sd.tables[SHEET].at["SD ratio upper", "Value"]])

    def test_field_errors_name_the_control(self):
        frame = pd.DataFrame({"A": A, "B": B, "C": [1, 1, 1]})
        cases = (
            (_options(Second="A"), "Second", "different"),
            (_options(**{LEVEL: 100}), LEVEL, "less than 100"),
            (_options(**{LEVEL: True}), LEVEL, "finite"),
            (_options(Distribution="nope"), "Distribution", "Normal"),
            (_options(**{GRAPH: "box"}), GRAPH, "SD ratio"),
            (_options(First="Missing"), "First", "not in the worksheet"),
            (_options(Second="C"), "Second", "zero variance"),
            (_options(Distribution="Lognormal"), "First", "strictly positive"),
        )
        for options, field, snippet in cases:
            with self.subTest(field=field, snippet=snippet):
                with self.assertRaises(FieldError) as caught:
                    analysis(frame, options)
                self.assertEqual(caught.exception.field, field)
                self.assertIn(snippet, str(caught.exception))

    def test_summary_records_orientation_missing_counts_and_literal_labels(self):
        frame = pd.DataFrame({"Dose A": [0, None, 2, 4], "Dose B": [0, 1, None, 2]})
        tables = analysis(frame, {"First": "Dose A", "Second": "Dose B", LEVEL: 90,
                                   "Distribution": "Normal", GRAPH: GRAPH_NONE}).tables
        summary = tables["Summary"]["Value"]
        self.assertEqual(summary["Missing first"], 1)
        self.assertEqual(summary["Missing second"], 1)
        self.assertEqual(summary["Orientation"], "Dose A / Dose B")
        self.assertEqual(summary["First"], "Dose A")
        settings = tables["Settings"]["Value"]
        self.assertIn("Not a Wald interval", settings["Interval"])
        self.assertEqual(settings[LEVEL], 90)



class AlongsideMeanTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"Y": [0, 2, 4, 0, 1, 2], "G": ["A", "A", "A", "B", "B", "B"]})

    def t_options(self, **changes):
        options = {"Design": "Welch", "Response": "Y", "Group": "G", "Subject": None, "Null mean": 0.0}
        options.update(changes)
        return options

    def test_absent_and_false_leave_the_t_test_unchanged(self):
        frame = self.frame()
        plain = analyse("t-test", frame, self.t_options())
        explicit = analyse("t-test", frame, self.t_options(**{SHOW: False}))
        self.assertEqual(list(plain.tables), ["t-test"])
        self.assertEqual(list(explicit.tables), ["t-test"])
        pd.testing.assert_series_equal(plain.tables["t-test"]["Value"], explicit.tables["t-test"]["Value"])
        student = analyse("t-test", frame, self.t_options(Design="Student", **{SHOW: True}))
        welch = analyse("t-test", frame, self.t_options(**{SHOW: True}))
        pd.testing.assert_series_equal(student.tables["t-test"]["Value"],
                                        analyse("t-test", frame, self.t_options(Design="Student")).tables["t-test"]["Value"])
        close(self, welch.tables[SHEET].at["p", "Value"], 0.4)
        close(self, student.tables[SHEET].at["p", "Value"], 0.4)
        self.assertEqual(list(welch.tables[SHEET].index), list(KEYS))

    def test_a_constant_group_keeps_the_t_result_and_explains(self):
        frame = self.frame()
        frame.loc[frame["G"] == "B", "Y"] = 1
        result = analyse("t-test", frame, self.t_options(**{SHOW: True}))
        self.assertIn("t", result.tables["t-test"].index)
        self.assertEqual(list(result.tables[SHEET].index), ["Reason"])
        self.assertIn("zero variance", result.tables[SHEET].at["Reason", "Value"])
        self.assertNotIn("p", result.tables[SHEET].index)

    def test_paired_and_one_sample_ignore_the_flag(self):
        paired = pd.DataFrame({"Y": [1, 2, 4, 3, 6, 5], "G": ["A", "B"] * 3, "S": [1, 1, 2, 2, 3, 3]})
        options = {"Design": "Paired", "Response": "Y", "Group": "G", "Subject": "S", "Null mean": 0.0, SHOW: True}
        result = analyse("t-test", paired, options)
        self.assertEqual(list(result.tables), ["t-test"])
        one = analyse("t-test", pd.DataFrame({"Y": [1.0, 2, 4]}),
                      {"Design": "One-sample", "Response": "Y", "Group": None, "Subject": None,
                       "Null mean": 0.0, SHOW: "not a bool"})
        self.assertEqual(list(one.tables), ["t-test"])

    def test_unpaired_rejects_a_non_boolean_flag(self):
        with self.assertRaises(FieldError) as caught:
            analyse("t-test", self.frame(), self.t_options(**{SHOW: "yes"}))
        self.assertEqual(caught.exception.field, SHOW)

    def test_lognormal_unpaired_uses_the_callers_level_and_paired_ignores_the_flag(self):
        frame = pd.DataFrame({"P": [math.exp(x) for x in (0, 2, 4)], "Q": [math.exp(x) for x in (0, 1, 2)]})
        options = {"First": "P", "Second": "Q", "Design": "Welch", "Report ratio": "First / Second",
                   "Null ratio": 1.0, "Hypothetical geometric mean": 1.0, LEVEL: 90.0,
                   "Alternative": "Two-sided", "Log base": "10", GRAPH: "None", "Pairing correlation": False,
                   SHOW: True}
        result = analyse(LOGNORMAL, frame, options)
        self.assertEqual(list(result.tables["Lognormal test"].columns)[:1], ["N first"])
        close(self, result.tables[SHEET].at["p", "Value"], 0.4)
        close(self, result.tables[SHEET].at["Variance ratio", "Value"], 4)
        ratio = result.tables[SHEET].at["Variance ratio", "Value"]
        close(self, result.tables[SHEET].at["Variance ratio lower", "Value"], ratio / stats.f.ppf(0.95, 2, 2))
        quiet = analyse(LOGNORMAL, frame, {**options, "Design": "Paired", SHOW: True, "Pairing correlation": True})
        self.assertNotIn(SHEET, quiet.tables)
        failed = frame.assign(Q=[1, 1, 1])
        explained = analyse(LOGNORMAL, failed, options)
        self.assertIn("zero variance", explained.tables[SHEET].at["Reason", "Value"])
        self.assertTrue(math.isfinite(explained.tables["Lognormal test"].at[0, "t"]))

    def test_menu_order_keeps_the_existing_prefix(self):
        self.assertEqual(GROUPS["Group Comparison"][:4],
                         ("t-test", "Paired t-test (columns)", "Lognormal t-test", METHOD))
        self.assertIs(METHODS["t-test"][SHOW], False)
        self.assertEqual(METHODS[METHOD][GRAPH][0], GRAPH_NONE)


if __name__ == "__main__":
    unittest.main()
