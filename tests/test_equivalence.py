"""Equivalence test (TOST): the pure statistics, the four designs through the dispatcher, edge cases and the figure.

Expected numbers come from ``tests/equivalence_oracle.py`` (direct sample moments and SciPy's Student-t
functions, no Trama code) and from the frozen ``expected.json`` it wrote.
"""
import json
import math
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi.equivalence import EQUIVALENT, NOT_DEMONSTRATED, UNAVAILABLE, tost_from_summary
from analisi.equivalence_workbench import (DESIGNS, EQUIVALENCE, ONE_SAMPLE, OPTIONS, PAIRED, STUDENT, WELCH,
                                           equivalence_test, visibility)
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, GRAPH_METHODS, METHODS, analyse
from tests import equivalence_oracle as oracle

DATA = Path(__file__).parent / "data" / "equivalence_071"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
SUMMARY_KEYS = {"Difference": "difference", "SE": "se", "df": "df", "CI level (%)": "ci_level", "CI lower": "ci_lower",
                "CI upper": "ci_upper", "t lower": "t_lower", "p lower": "p_lower", "t upper": "t_upper",
                "p upper": "p_upper", "p TOST": "p_tost"}


def fixture(name):
    return pd.read_csv(DATA / name)


def zone(lower=-.12, upper=.12, alpha=.05):
    return {"Lower margin": lower, "Upper margin": upper, "Alpha": alpha}


def one_sample(**changes):
    return {"Design": ONE_SAMPLE, "Response": "Response", "Reference": 0.0, **zone(-.06, .06), **changes}


def paired(**changes):
    return {"Design": PAIRED, "First": "First", "Second": "Second", **zone(-.08, .12), **changes}


def independent(design, **changes):
    return {"Design": design, "First": "First", "Second": "Second", **zone(), **changes}


def summary(result):
    return result.tables["Equivalence summary"].iloc[0]


def run(frame, options):
    return equivalence_test(frame, options)


class TostContract(unittest.TestCase):
    """The pure function against the oracle's own numbers."""

    def assert_oracle(self, name):
        e = EXPECTED[name]
        got = tost_from_summary(e["difference"], e["se"], e["df"], e["lower_margin"], e["upper_margin"], e["alpha"])
        for key in ("ci_level", "ci_lower", "ci_upper", "t_lower", "p_lower", "t_upper", "p_upper", "p_tost"):
            self.assertAlmostEqual(got[key], e[key], places=12, msg=(name, key))
        self.assertEqual(got["conclusion"], e["conclusion"])

    def test_one_sample_oracle(self):
        self.assert_oracle("one_sample")

    def test_paired_oracle(self):
        self.assert_oracle("paired")

    def test_student_oracle(self):
        self.assert_oracle("independent_student")

    def test_welch_oracle(self):
        self.assert_oracle("independent_welch")

    def test_tost_and_interval_conclusions_agree(self):
        e = EXPECTED["one_sample"]
        self.assertGreater(e["ci_lower"], e["lower_margin"])
        self.assertLess(e["ci_upper"], e["upper_margin"])
        self.assertLess(e["p_lower"], e["alpha"])
        self.assertLess(e["p_upper"], e["alpha"])

    def test_non_significance_is_not_equivalence(self):
        e = EXPECTED["independent_welch"]
        ordinary_p = 2 * stats.t.sf(abs(e["difference"] / e["se"]), e["df"])
        self.assertGreater(ordinary_p, .05)
        self.assertGreaterEqual(e["p_tost"], e["alpha"])
        self.assertEqual(e["conclusion"], NOT_DEMONSTRATED)

    def test_student_and_welch_keep_their_own_variance_models(self):
        pooled, welch = EXPECTED["independent_student"], EXPECTED["independent_welch"]
        self.assertNotAlmostEqual(pooled["se"], welch["se"], places=8)
        self.assertNotAlmostEqual(pooled["df"], welch["df"], places=8)

    def test_exact_boundary_is_not_equivalent(self):
        df, alpha = 10, .05
        critical = float(stats.t.ppf(1 - alpha, df))
        got = tost_from_summary(0., 1., df, -critical, 100., alpha)
        self.assertAlmostEqual(got["p_lower"], alpha, places=13)
        self.assertNotEqual(got["conclusion"], EQUIVALENT)
        mirrored = tost_from_summary(0., 1., df, -100., critical, alpha)
        self.assertNotEqual(mirrored["conclusion"], EQUIVALENT)

    def test_just_inside_the_boundary_is_equivalent(self):
        df, alpha = 10, .05
        critical = float(stats.t.ppf(1 - alpha, df))
        self.assertEqual(tost_from_summary(0., 1., df, -critical * 1.0001, critical * 1.0001, alpha)["conclusion"],
                         EQUIVALENT)
        self.assertEqual(tost_from_summary(0., 1., df, -critical * .9999, critical * 1.0001, alpha)["conclusion"],
                         NOT_DEMONSTRATED)

    def test_invalid_inputs_are_rejected(self):
        cases = [(1., 0., 10., -.2, .2, .05), (1., 1., 0., -.2, .2, .05), (1., 1., 10., 0., .2, .05),
                 (1., 1., 10., -.2, 0., .05), (1., 1., 10., -.2, .2, 0.), (1., 1., 10., -.2, .2, .5)]
        for args in cases:
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                tost_from_summary(*args)

    def test_non_finite_and_non_numeric_inputs_are_rejected(self):
        nan, inf = math.nan, math.inf
        for args in [(nan, 1., 10., -.2, .2, .05), (1., nan, 10., -.2, .2, .05), (1., inf, 10., -.2, .2, .05),
                     (1., 1., nan, -.2, .2, .05), (1., 1., inf, -.2, .2, .05), (1., 1., 10., -inf, .2, .05),
                     (1., 1., 10., -.2, inf, .05), (1., 1., 10., -.2, .2, nan), (1., -1., 10., -.2, .2, .05),
                     (1., 1., -3., -.2, .2, .05), (1., 1., 10., .2, -.2, .05), (1., 1., 10., -.2, .2, -.01)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                tost_from_summary(*args)
        for args in [("1", 1., 10., -.2, .2, .05), (True, 1., 10., -.2, .2, .05), (1., 1., 10., -.2, .2, None),
                     (1., 1., 10., -.2, .2, False)]:
            with self.subTest(args=args), self.assertRaises(TypeError):
                tost_from_summary(*args)

    def test_unrepresentable_results_are_refused_not_zeroed(self):
        with self.assertRaises(ValueError):
            tost_from_summary(1e308, 1e-300, 10., -.2, .2, .05)
        with self.assertRaises(ValueError):
            tost_from_summary(1., 1e308, 10., -1e308, 1e308, .05)

    def test_extreme_tails_have_no_spurious_nan_or_one(self):
        far = tost_from_summary(0., 1e-3, 5., -.5, .5, .05)
        self.assertEqual(far["conclusion"], EQUIVALENT)
        self.assertTrue(0 < far["p_lower"] < 1e-12 and 0 < far["p_upper"] < 1e-12)
        miss = tost_from_summary(50., 1., 5., -1., 1., .05)
        self.assertEqual(miss["conclusion"], NOT_DEMONSTRATED)
        self.assertEqual(miss["p_tost"], miss["p_upper"])
        self.assertTrue(miss["p_upper"] > 1 - 1e-6 and np.isfinite(miss["p_lower"]))

    def test_alpha_sets_level_and_critical_value(self):
        for alpha in (.01, .025, .1, .2, .49):
            got = tost_from_summary(.3, .1, 12., -1., 1., alpha)
            self.assertAlmostEqual(got["ci_level"], 100 * (1 - 2 * alpha))
            half = stats.t.ppf(1 - alpha, 12) * .1
            self.assertAlmostEqual(got["ci_upper"] - got["ci_lower"], 2 * half, places=12)

    def test_asymmetric_margins_and_mirror_symmetry(self):
        a = tost_from_summary(.4, .2, 9., -.3, 1.5, .05)
        b = tost_from_summary(-.4, .2, 9., -1.5, .3, .05)
        self.assertAlmostEqual(a["p_lower"], b["p_upper"], places=13)
        self.assertAlmostEqual(a["p_upper"], b["p_lower"], places=13)
        self.assertAlmostEqual(a["p_tost"], b["p_tost"], places=13)
        self.assertAlmostEqual(a["ci_lower"], -b["ci_upper"], places=13)
        self.assertEqual(a["conclusion"], b["conclusion"])

    def test_the_oracle_still_regenerates_the_frozen_numbers(self):
        built = oracle.build()
        for name in ("one_sample", "paired", "independent_student", "independent_welch"):
            for key, value in EXPECTED[name].items():
                if value is None:
                    self.assertIsNone(built[name][key], (name, key))
                elif isinstance(value, str):
                    self.assertEqual(built[name][key], value, (name, key))
                else:
                    self.assertAlmostEqual(built[name][key], value, places=12, msg=(name, key))


class Designs(unittest.TestCase):
    """Each design through the dispatcher, against the oracle."""

    def check(self, name, result):
        row, e = summary(result), EXPECTED[name]
        for column, key in SUMMARY_KEYS.items():
            np.testing.assert_allclose(row[column], e[key], rtol=1e-12, atol=1e-300, err_msg=(name, column))
        self.assertEqual(row["Conclusion"], e["conclusion"])
        self.assertEqual(row["Status / Reason"], "OK")
        self.assertEqual(row["N first"], e["n_first"])
        if e["n_second"] is None:
            self.assertIsNone(row["N second"])
        else:
            self.assertEqual(row["N second"], e["n_second"])
        self.assertEqual((row["Lower margin"], row["Upper margin"], row["Alpha"]),
                         (e["lower_margin"], e["upper_margin"], e["alpha"]))

    def test_one_sample(self):
        self.check("one_sample", run(fixture("one_sample.csv"), one_sample()))

    def test_paired(self):
        self.check("paired", run(fixture("paired.csv"), paired()))

    def test_student(self):
        self.check("independent_student", run(fixture("independent.csv"), independent(STUDENT)))

    def test_welch(self):
        self.check("independent_welch", run(fixture("independent.csv"), independent(WELCH)))

    def test_dispatcher_matches_direct_call(self):
        frame = fixture("paired.csv")
        pd.testing.assert_frame_equal(analyse(EQUIVALENCE, frame, paired()).tables["Equivalence summary"],
                                      run(frame, paired()).tables["Equivalence summary"])

    def test_labels_and_the_reference_label(self):
        row = summary(run(fixture("one_sample.csv"), one_sample(Reference=.5, **zone(-1, 1))))
        self.assertEqual((row["Design"], row["First label"], row["Second label"]),
                         (ONE_SAMPLE, "Response", "Reference (0.5)"))
        self.assertIsNone(row["N second"])
        row = summary(run(fixture("paired.csv"), paired()))
        self.assertEqual((row["First label"], row["Second label"]), ("First", "Second"))
        self.assertEqual(row["Difference"], EXPECTED["paired"]["difference"])

    def test_reference_zero_is_valid_and_orients_sample_minus_reference(self):
        frame = fixture("one_sample.csv")
        zero = summary(run(frame, one_sample(Reference=0.0)))
        shifted = summary(run(frame, one_sample(Reference=.01, **zone(-.07, .05))))
        self.assertAlmostEqual(zero["Difference"] - .01, shifted["Difference"], places=14)
        self.assertAlmostEqual(zero["Difference"], EXPECTED["one_sample"]["difference"], places=14)
        self.assertAlmostEqual(zero["p TOST"], summary(run(frame, one_sample(Reference=.01, **zone(-.07, .05)))
                                                       )["p TOST"], places=12)

    def test_student_and_welch_on_homoscedastic_and_heteroscedastic_data(self):
        rng = np.random.default_rng(71)
        for label, sd1, sd2, n1, n2 in (("homoscedastic", 1.0, 1.0, 12, 9), ("heteroscedastic", .5, 3.0, 12, 7),
                                        ("unbalanced", .5, 3.0, 5, 30)):
            first, second = rng.normal(10, sd1, n1), rng.normal(10.2, sd2, n2)
            frame = pd.DataFrame({"First": pd.Series(first), "Second": pd.Series(second)})
            for design in (STUDENT, WELCH):
                with self.subTest(label=label, design=design):
                    got = summary(run(frame, independent(design, **zone(-2, 2))))
                    want = oracle.independent(list(first), list(second), -2, 2, .05, design)
                    for column, key in SUMMARY_KEYS.items():
                        np.testing.assert_allclose(got[column], want[key], rtol=1e-10, err_msg=column)
                    self.assertEqual(got["Conclusion"], want["conclusion"])
                    self.assertEqual((got["N first"], got["N second"]), (n1, n2))
        # Different variance models give different SE and df on unequal spreads.
        pooled = summary(run(frame, independent(STUDENT, **zone(-2, 2))))
        welch = summary(run(frame, independent(WELCH, **zone(-2, 2))))
        self.assertNotAlmostEqual(pooled["SE"], welch["SE"], places=6)
        self.assertEqual(pooled["df"], n1 + n2 - 2)
        self.assertLess(welch["df"], pooled["df"])

    def test_one_sided_variance_zero_still_gives_a_welch_test(self):
        frame = pd.DataFrame({"First": pd.Series([1., 1, 1, 1]), "Second": pd.Series([1.1, 0.9, 1.2, 1.05, 0.95])})
        row = summary(run(frame, independent(WELCH, **zone(-1, 1))))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # SciPy warns about the constant sample
            want = oracle.independent([1., 1, 1, 1], [1.1, 0.9, 1.2, 1.05, 0.95], -1, 1, .05, "Welch")
        self.assertEqual(row["Status / Reason"], "OK")
        np.testing.assert_allclose([row["SE"], row["df"], row["p TOST"]], [want["se"], want["df"], want["p_tost"]],
                                   rtol=1e-10)

    def test_swapping_first_and_second_with_mirrored_margins_swaps_the_two_tests(self):
        for design, frame in ((PAIRED, fixture("paired.csv")), (WELCH, fixture("independent.csv")),
                              (STUDENT, fixture("independent.csv"))):
            with self.subTest(design=design):
                a = summary(run(frame, {"Design": design, "First": "First", "Second": "Second", **zone(-.3, .2)}))
                b = summary(run(frame, {"Design": design, "First": "Second", "Second": "First", **zone(-.2, .3)}))
                self.assertAlmostEqual(a["Difference"], -b["Difference"], places=13)
                self.assertAlmostEqual(a["SE"], b["SE"], places=13)
                self.assertAlmostEqual(a["p lower"], b["p upper"], places=12)
                self.assertAlmostEqual(a["p upper"], b["p lower"], places=12)
                self.assertAlmostEqual(a["t lower"], -b["t upper"], places=12)
                self.assertAlmostEqual(a["CI lower"], -b["CI upper"], places=12)
                self.assertEqual(a["Conclusion"], b["Conclusion"])

    def test_alpha_changes_level_and_can_change_the_decision(self):
        frame = fixture("independent.csv")
        strict = summary(run(frame, independent(WELCH, **zone(-.14, .3, .01))))
        loose = summary(run(frame, independent(WELCH, **zone(-.14, .3, .2))))
        self.assertAlmostEqual(strict["CI level (%)"], 98.0)
        self.assertAlmostEqual(loose["CI level (%)"], 60.0)
        self.assertLess(loose["CI upper"] - loose["CI lower"], strict["CI upper"] - strict["CI lower"])
        self.assertEqual((strict["Conclusion"], loose["Conclusion"]), (NOT_DEMONSTRATED, EQUIVALENT))

    def test_interval_contained_in_zone_agrees_with_both_p_values(self):
        for frame, options in ((fixture("one_sample.csv"), one_sample()), (fixture("paired.csv"), paired()),
                               (fixture("independent.csv"), independent(WELCH)),
                               (fixture("independent.csv"), independent(STUDENT, **zone(-.2, .35)))):
            row = summary(run(frame, options))
            inside = row["Lower margin"] < row["CI lower"] and row["CI upper"] < row["Upper margin"]
            both = row["p lower"] < row["Alpha"] and row["p upper"] < row["Alpha"]
            self.assertEqual(inside, both)
            self.assertEqual(row["Conclusion"] == EQUIVALENT, both)

    def test_scale_invariance_across_units(self):
        frame = fixture("paired.csv")
        base = summary(run(frame, paired()))
        for factor in (1e-250, 1e250, 1e-8, 1e8):
            with self.subTest(factor=factor):
                scaled = frame * factor
                got = summary(run(scaled, paired(**zone(-.08 * factor, .12 * factor))))
                self.assertEqual(got["Conclusion"], base["Conclusion"])
                np.testing.assert_allclose([got["t lower"], got["t upper"], got["p TOST"], got["df"]],
                                           [base["t lower"], base["t upper"], base["p TOST"], base["df"]], rtol=1e-9)
                np.testing.assert_allclose(got["Difference"], base["Difference"] * factor, rtol=1e-12)


class MissingDataAndRows(unittest.TestCase):
    def test_independent_missing_cells_are_removed_per_group(self):
        frame = fixture("independent.csv")
        self.assertEqual(frame["Second"].notna().sum(), 8)
        row = summary(run(frame, independent(WELCH)))
        self.assertEqual((row["N first"], row["N second"]), (15, 8))

    def test_paired_missing_cells_remove_the_whole_pair(self):
        frame = fixture("paired.csv")
        self.assertEqual(frame["First"].notna().sum(), 8)      # the last row has no Second: not a pair
        result = run(frame, paired())
        row = summary(result)
        self.assertEqual((row["N first"], row["N second"]), (7, 7))
        data = result.tables["Data used"]
        self.assertEqual(data["Source row"].tolist(), list(range(7)))
        self.assertEqual(list(data.columns), ["Source row", "First", "Second", "Difference"])
        np.testing.assert_allclose(data["Difference"], np.round(frame["First"][:7] - frame["Second"][:7], 12))
        # An isolated First cell never becomes a pair: dropping one row's Second leaves six pairs.
        gap = frame.copy()
        gap.loc[3, "Second"] = np.nan
        self.assertEqual(summary(run(gap, paired()))["N first"], 6)
        self.assertEqual(run(gap, paired()).tables["Data used"]["Source row"].tolist(), [0, 1, 2, 4, 5, 6])

    def test_incomplete_pair_with_unusable_cell_is_ignored_until_complete(self):
        frame = fixture("paired.csv").astype({"First": object})
        frame.loc[9, "First"] = "n.d."            # row 9 has no Second: not a pair, so it is never read
        self.assertEqual(summary(run(frame, paired()))["N first"], 7)

    def test_source_rows_keep_the_original_index(self):
        frame = fixture("independent.csv")
        frame.index = [f"r{i}" for i in range(len(frame))]
        frame.loc["r2", "First"] = np.nan                                # excluded cell: not in the counts
        result = run(frame, independent(STUDENT))
        data = result.tables["Data used"]
        self.assertEqual(summary(result)["N first"], 14)
        first_rows = data.loc[data["Sample"] == "First", "Source row"].tolist()
        self.assertEqual(first_rows[:3], ["r0", "r1", "r3"])
        self.assertNotIn("r2", first_rows)
        self.assertEqual(data.loc[data["Sample"] == "Second", "Source row"].tolist(), [f"r{i}" for i in range(8)])
        self.assertEqual(list(data.columns), ["Source row", "Sample", "Value"])

    def test_the_worksheet_is_never_modified(self):
        for frame, options in ((fixture("paired.csv"), paired()), (fixture("independent.csv"), independent(WELCH)),
                               (fixture("one_sample.csv"), one_sample())):
            before = frame.copy(deep=True)
            run(frame, options)
            pd.testing.assert_frame_equal(frame, before)

    def test_decimal_comma_text_and_missing_markers(self):
        frame = pd.DataFrame({"First": ["10,2", "9.8", " ", None, "10.4"], "Second": ["10", "10,1", "9.9", "", "9.9"]})
        row = summary(run(frame, paired(**zone(-1, 1))))
        want = oracle.paired([10.2, 9.8, 10.4], [10., 10.1, 9.9], -1, 1, .05)
        self.assertEqual(row["N first"], 3)
        np.testing.assert_allclose(row["SE"], want["se"], rtol=1e-12)


class EdgeCases(unittest.TestCase):
    def assert_unavailable(self, row, reason=None):
        self.assertEqual(row["Conclusion"], UNAVAILABLE)
        self.assertNotEqual(row["Status / Reason"], "OK")
        if reason:
            self.assertIn(reason, row["Status / Reason"])
        for column in ("t lower", "p lower", "t upper", "p upper", "p TOST", "CI lower", "CI upper"):
            self.assertTrue(np.isnan(row[column]), column)

    def test_constant_data_has_zero_se_and_no_invented_p(self):
        for options, frame, n in ((one_sample(**zone(-1, 1)), pd.DataFrame({"Response": [.1, .1, .1, .1]}), (4, None)),
                                  (independent(STUDENT, **zone(-1, 1)),
                                   pd.DataFrame({"First": pd.Series([2., 2, 2]), "Second": pd.Series([1., 1, 1, 1])}), (3, 4)),
                                  (independent(WELCH, **zone(-1, 1)),
                                   pd.DataFrame({"First": pd.Series([2., 2, 2]), "Second": pd.Series([1., 1, 1, 1])}), (3, 4)),
                                  (paired(**zone(-1, 1)),
                                   pd.DataFrame({"First": [2., 3, 4, 5.5], "Second": [1., 2, 3, 4.5]}), (4, 4))):
            with self.subTest(design=options["Design"]):
                result = run(frame, options)
                row = summary(result)
                self.assert_unavailable(row, "standard error is zero")
                self.assertEqual((row["N first"], row["N second"]), n)
                self.assertTrue(np.isfinite(row["Difference"]) and row["SE"] == 0)
                self.assertEqual(result.tables["Equivalence tests"]["Null rejected"].tolist(),
                                 ["Not available"] * 2)

    def test_representable_paired_variation_is_not_silently_removed(self):
        frame = pd.DataFrame({"First": [2.0, 3.0, 4.0, 5.5], "Second": [1.9, 2.9, 3.9, 5.4]})   # 0.1 up to rounding
        row = summary(run(frame, paired(**zone(-1, 1))))
        self.assertEqual(row["Status / Reason"], "OK")
        self.assertGreater(row["SE"], 0)

    def test_overflowing_difference_is_unavailable_with_counts_kept(self):
        frame = pd.DataFrame({"First": [1.7e308, 1.6e308, 1.5e308], "Second": [-1.7e308, -1.6e308, -1.4e308]})
        row = summary(run(frame, paired(**zone(-1, 1))))
        self.assert_unavailable(row, "outside the floating-point range")
        self.assertEqual((row["N first"], row["N second"]), (3, 3))

    def test_one_sample_reference_overflow_is_unavailable(self):
        row = summary(run(pd.DataFrame({"Response": [1.7e308, 1.6e308, 1.65e308]}),
                          one_sample(Reference=-1.7e308, **zone(-1, 1))))
        self.assert_unavailable(row, "outside the floating-point range")

    def test_huge_values_do_not_overflow_the_variance(self):
        frame = pd.DataFrame({"First": [1e200, 2e200, 3e200, 1.5e200], "Second": [1.1e200, 1.9e200, 3.2e200, 1.4e200]})
        got = summary(run(frame, paired(**zone(-1e200, 1e200))))
        want = oracle.paired(list(frame.First / 1e200), list(frame.Second / 1e200), -1, 1, .05)
        self.assertEqual(got["Status / Reason"], "OK")
        np.testing.assert_allclose(got["t lower"], want["t_lower"], rtol=1e-12)

    def test_figure_for_unavailable_inference_does_not_claim_anything(self):
        result = run(pd.DataFrame({"Response": [.1, .1, .1]}), one_sample(**zone(-1, 1)))
        axes = result.figure.axes[0]
        self.assertIn(UNAVAILABLE, axes.get_title())
        self.assertNotIn("Equivalent", axes.get_title().replace("Equivalence", ""))
        self.assertFalse([line for line in axes.lines if line.get_gid() == "tost:estimate"])      # no interval
        self.assertFalse(any("CI" in text.get_text() for text in axes.get_legend().get_texts()))
        self.assertTrue(any(UNAVAILABLE in t.get_text() for t in axes.texts))


class Validation(unittest.TestCase):
    def assert_field(self, frame, options, field, text=None):
        with self.assertRaises(FieldError) as raised:
            run(frame, options)
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        if text:
            self.assertIn(text, str(raised.exception))
        return str(raised.exception)

    def test_zone_and_alpha_errors_name_their_own_field(self):
        frame = fixture("paired.csv")
        for changes, field in (({"Lower margin": 0.0}, "Lower margin"), ({"Lower margin": .05}, "Lower margin"),
                               ({"Upper margin": 0.0}, "Upper margin"), ({"Upper margin": -.1}, "Upper margin"),
                               ({"Lower margin": math.nan}, "Lower margin"), ({"Upper margin": math.inf}, "Upper margin"),
                               ({"Lower margin": -math.inf}, "Lower margin"), ({"Lower margin": "-1"}, "Lower margin"),
                               ({"Upper margin": True}, "Upper margin"), ({"Lower margin": None}, "Lower margin"),
                               ({"Alpha": 0.0}, "Alpha"), ({"Alpha": .5}, "Alpha"), ({"Alpha": .6}, "Alpha"),
                               ({"Alpha": -.1}, "Alpha"), ({"Alpha": math.nan}, "Alpha"), ({"Alpha": "x"}, "Alpha"),
                               ({"Alpha": False}, "Alpha"), ({"Alpha": None}, "Alpha")):
            with self.subTest(changes=changes):
                self.assert_field(frame, paired(**changes), field)

    def test_the_default_zone_is_rejected_until_declared(self):
        frame = fixture("paired.csv")
        options = {"Design": PAIRED, "First": "First", "Second": "Second"}
        for field, value in OPTIONS.items():
            if field in ("Lower margin", "Upper margin", "Alpha"):
                options[field] = value
        self.assert_field(frame, options, "Lower margin", "below zero")

    def test_inverted_margins_name_the_misplaced_one(self):
        frame = fixture("paired.csv")
        self.assert_field(frame, paired(**zone(.1, -.1)), "Lower margin", "below zero")
        self.assert_field(frame, paired(**zone(-.1, -.05)), "Upper margin", "above zero")

    def test_design_reference_and_column_roles(self):
        paired_frame, one = fixture("paired.csv"), fixture("one_sample.csv")
        self.assert_field(paired_frame, paired(Design="Welchh"), "Design")
        self.assert_field(paired_frame, paired(Design=None), "Design")
        for value in (math.nan, math.inf, "0", True, None):
            self.assert_field(one, one_sample(Reference=value), "Reference")
        self.assert_field(one, one_sample(Response=""), "Response", "Choose a column")
        self.assert_field(one, one_sample(Response="Missing"), "Response", "is not in the worksheet")
        self.assert_field(paired_frame, paired(First="Nope"), "First", "is not in the worksheet")
        self.assert_field(paired_frame, paired(Second="Nope"), "Second", "is not in the worksheet")
        self.assert_field(paired_frame, paired(Second=""), "Second", "Choose a column")

    def test_first_and_second_must_differ(self):
        for design in (PAIRED, STUDENT, WELCH):
            with self.subTest(design=design):
                self.assert_field(fixture("paired.csv"), {"Design": design, "First": "First", "Second": "First",
                                                          **zone()}, "Second", "different columns")

    def test_not_enough_data(self):
        self.assert_field(pd.DataFrame({"Response": [1.0, np.nan, np.nan]}), one_sample(), "Response", "at least two")
        self.assert_field(pd.DataFrame({"Response": [np.nan, np.nan]}), one_sample(), "Response", "0 found")
        self.assert_field(pd.DataFrame({"First": [1., np.nan, 3], "Second": [np.nan, 2, 4]}), paired(), "First",
                          "two complete pairs; 1 found")
        self.assert_field(pd.DataFrame({"First": [1., 2, 3], "Second": [4., np.nan, np.nan]}), independent(WELCH),
                          "Second", "at least two")
        self.assert_field(pd.DataFrame({"First": [1., np.nan, np.nan], "Second": [4., 5, 6]}), independent(STUDENT),
                          "First", "at least two")

    def test_unusable_cells_name_column_and_source_row(self):
        frame = pd.DataFrame({"First": [1., 2, np.inf, 4], "Second": [1.5, "abc", 3, 4]}, index=[10, 11, 12, 13])
        text = self.assert_field(frame, independent(WELCH), "First", "Source row 12")
        self.assertIn('"First"', text)
        text = self.assert_field(frame.assign(First=[1., 2, 3, 4]), independent(WELCH), "Second", "Source row 11")
        self.assertIn("is not a finite number", text)
        many = pd.DataFrame({"Response": [1., np.inf, -np.inf, 4]})
        self.assertIn("(2 cells are unusable)", self.assert_field(many, one_sample(), "Response"))
        self.assert_field(pd.DataFrame({"Response": [True, 2., 3]}), one_sample(), "Response", "Source row 0")

    def test_duplicate_column_names_are_refused_on_the_field(self):
        frame = pd.DataFrame([[1., 2., 3.], [2., 3., 4.], [3., 5., 6.]], columns=["A", "A", "B"])
        self.assert_field(frame, paired(First="A", Second="B"), "First", "unique")
        self.assert_field(frame, paired(First="B", Second="A"), "Second", "unique")

    def test_inactive_fields_are_ignored_even_when_stale(self):
        one, two = fixture("one_sample.csv"), fixture("paired.csv")
        stale = summary(run(one, one_sample(First=None, Second="Not a column", Design=ONE_SAMPLE)))
        self.assertEqual(stale["Conclusion"], EXPECTED["one_sample"]["conclusion"])
        stale = summary(run(two, paired(Reference="garbage", Response="Not a column")))
        self.assertEqual(stale["Conclusion"], EXPECTED["paired"]["conclusion"])
        stale = summary(run(fixture("independent.csv"), independent(STUDENT, Reference=math.nan, Response=None)))
        self.assertEqual(stale["Conclusion"], EXPECTED["independent_student"]["conclusion"])

    def test_visibility_follows_the_design(self):
        self.assertEqual(visibility(ONE_SAMPLE), {"Response": True, "Reference": True, "First": False, "Second": False})
        for design in (PAIRED, STUDENT, WELCH):
            self.assertEqual(visibility(design), {"Response": False, "Reference": False, "First": True, "Second": True})


class Catalog(unittest.TestCase):
    def test_registered_once_under_group_comparison_with_canonical_defaults(self):
        self.assertEqual(GROUPS["Group Comparison"].count(EQUIVALENCE), 1)
        self.assertEqual(sum(EQUIVALENCE in names for names in GROUPS.values()), 1)
        self.assertIn(EQUIVALENCE, GRAPH_METHODS)
        spec = METHODS[EQUIVALENCE]
        self.assertEqual(spec["Design"], DESIGNS)
        self.assertEqual(spec["Design"][0], ONE_SAMPLE)
        self.assertEqual(spec["Alpha"], .05)
        self.assertEqual(list(spec), ["Design", "Response", "Reference", "First", "Second", "Lower margin",
                                      "Upper margin", "Alpha"])


class Figure(unittest.TestCase):
    def test_estimate_interval_margins_and_zero_are_drawn_and_labelled(self):
        result = run(fixture("independent.csv"), independent(WELCH))
        axes = result.figure.axes[0]
        gids = {child.get_gid() for child in axes.get_children() if child.get_gid()}
        self.assertTrue({"tost:zone", "tost:lower", "tost:upper", "tost:zero", "tost:estimate"} <= gids, gids)
        row = summary(result)
        self.assertIn("First − Second", axes.get_xlabel())
        self.assertIn(row["Conclusion"], axes.get_title())
        low, high = axes.get_xlim()
        for value in (row["Lower margin"], row["Upper margin"], 0.0, row["CI lower"], row["CI upper"]):
            self.assertTrue(low < value < high, (low, high, value))
        lines = {child.get_gid(): child for child in axes.get_children() if child.get_gid()}
        self.assertEqual(lines["tost:lower"].get_xdata()[0], row["Lower margin"])
        self.assertEqual(lines["tost:upper"].get_xdata()[0], row["Upper margin"])
        self.assertEqual(lines["tost:zero"].get_xdata()[0], 0)
        self.assertEqual(lines["tost:estimate"].get_xdata()[0], row["Difference"])
        # Not only color: margins are dashed, zero is dotted, the zone is a labelled patch, the interval has caps.
        self.assertNotEqual(lines["tost:lower"].get_linestyle(), lines["tost:zero"].get_linestyle())
        texts = " ".join(text.get_text() for text in axes.texts)
        self.assertIn("Lower margin", texts)
        self.assertIn("Upper margin", texts)
        self.assertIn("Equivalence zone", " ".join(t.get_text() for t in axes.get_legend().get_texts()))

    def test_one_sample_axis_names_the_sample_minus_reference_orientation(self):
        axes = run(fixture("one_sample.csv"), one_sample()).figure.axes[0]
        self.assertIn("Sample − Reference", axes.get_xlabel())
        self.assertIn("Equivalent", axes.get_title())

    def test_title_never_says_equivalent_when_the_table_does_not(self):
        result = run(fixture("independent.csv"), independent(WELCH))
        self.assertEqual(summary(result)["Conclusion"], NOT_DEMONSTRATED)
        title = result.figure.axes[0].get_title()
        self.assertIn(NOT_DEMONSTRATED, title)
        self.assertNotIn(" Equivalent", title)


class ResultSheets(unittest.TestCase):
    def test_sheets_and_columns(self):
        result = run(fixture("paired.csv"), paired())
        self.assertEqual(list(result.tables), ["Equivalence summary", "Equivalence tests", "Data used", "Settings"])
        self.assertEqual(list(result.tables["Equivalence summary"].columns),
                         ["Design", "First label", "Second label", "N first", "N second", "Difference", "SE", "df",
                          "Lower margin", "Upper margin", "Alpha", "CI level (%)", "CI lower", "CI upper", "t lower",
                          "p lower", "t upper", "p upper", "p TOST", "Conclusion", "Status / Reason"])
        self.assertEqual(len(result.tables["Equivalence summary"]), 1)

    def test_the_two_one_sided_tests_are_explicit_and_agree_with_the_summary(self):
        result = run(fixture("independent.csv"), independent(WELCH))
        tests, row = result.tables["Equivalence tests"], summary(result)
        self.assertEqual(len(tests), 2)
        self.assertEqual(tests["Test"].tolist(), ["Lower", "Upper"])
        self.assertEqual(tests["Null hypothesis"].tolist(), ["First − Second ≤ -0.12", "First − Second ≥ 0.12"])
        self.assertEqual(tests["Alternative"].tolist(), ["First − Second > -0.12", "First − Second < 0.12"])
        self.assertEqual(tests["t"].tolist(), [row["t lower"], row["t upper"]])
        self.assertEqual(tests["p"].tolist(), [row["p lower"], row["p upper"]])
        self.assertEqual(tests["Alpha"].tolist(), [.05, .05])
        self.assertEqual(tests["Null rejected"].tolist(), ["Yes", "No"])
        self.assertEqual(set(tests["df"]), {row["df"]})

    def test_one_sample_tests_use_the_sample_minus_reference_sign(self):
        tests = run(fixture("one_sample.csv"), one_sample()).tables["Equivalence tests"]
        self.assertTrue(tests["Null hypothesis"].str.startswith("Sample − Reference").all())
        self.assertEqual(tests["Null rejected"].tolist(), ["Yes", "Yes"])

    def test_settings_record_the_scope_and_the_margins(self):
        settings = run(fixture("one_sample.csv"), one_sample()).tables["Settings"]["Value"]
        self.assertEqual((settings["Design"], settings["Difference"], settings["Reference"]),
                         (ONE_SAMPLE, "Sample − Reference", 0.0))
        self.assertEqual((settings["First"], settings["Second"], settings["Response"]),
                         ("Not used", "Not used", "Response"))
        for left_out in ("Non-inferiority", "summary mean/SD/N", "multiple-comparison"):
            self.assertIn(left_out, settings["Not included"])


class LegacyUnchanged(unittest.TestCase):
    """Results recorded from the code before this analysis existed, for the analyses it sits beside."""

    def test_existing_t_tests_and_lognormal_results_are_identical(self):
        snapshot = json.loads((DATA / "legacy_ttests.json").read_text(encoding="utf-8"))
        data = {"one_sample": fixture("one_sample.csv"), "paired": fixture("paired.csv"),
                "independent": fixture("independent.csv")}
        long = pd.DataFrame({"Response": pd.concat([data["independent"].First,
                                                    data["independent"].Second.dropna()]).to_numpy(),
                             "Group": ["A"] * 15 + ["B"] * 8})
        frames = {"t-test one-sample": data["one_sample"], "t-test paired columns": data["paired"],
                  "t-test welch": long, "t-test student": long,
                  "lognormal paired": data["paired"].assign(First=data["paired"].First + 1,
                                                            Second=data["paired"].Second + 1)}
        for name, record in snapshot.items():
            with self.subTest(name=name):
                result = analyse(record["method"], frames[name], record["options"])
                self.assertEqual(sorted(result.tables), sorted(record["tables"]))
                for sheet, expected in record["tables"].items():
                    got = json.loads(result.tables[sheet].to_json(orient="split", date_format="iso",
                                                                   double_precision=15))
                    self.assertEqual(got, expected, (name, sheet))

    def test_existing_recipes_and_menu_entries_are_untouched(self):
        self.assertEqual(METHODS["t-test"], {"Design": ("Welch", "Student", "Paired", "One-sample"),
                                             "Response": None, "Group": METHODS["t-test"]["Group"],
                                             "Subject": METHODS["t-test"]["Subject"], "Null mean": 0.0,
                                             "Show variance comparison": False})
        self.assertEqual(METHODS["Paired t-test (columns)"], {"First": None, "Second": None})
        self.assertEqual(GROUPS["Group Comparison"][:3], ("t-test", "Paired t-test (columns)", "Lognormal t-test"))


if __name__ == "__main__":
    unittest.main()
