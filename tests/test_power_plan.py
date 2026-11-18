"""Power and sample size from means and SDs: conversions, exact allocation, search, curve and messages.

The oracle here is independent of the module under test: it evaluates the two-sided noncentral t and F tails with
SciPy on the integer lattice and scans for the smallest size, and the packet's frozen expected values.
"""
import json
import tracemalloc
import unittest
from math import hypot, sqrt
from pathlib import Path
from statistics import pstdev

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.power import TTestIndPower

from analisi import design, i18n, power_plan as pp
from analisi.field_error import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "power_from_summary"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
LEGACY = {"Design": "Independent t", "Goal": "Sample size", "Standardized effect": .5, "Alpha": .05,
          "Target power": .8}
BASE = {"Design": "Independent t", "Goal": "Sample size", "Effect input": "Means and SD", "Mean A": 5, "Mean B": 7,
        "Common SD": 4, "Alpha": .05, "Target power": .8}


def run(options):
    return analyse(pp.METHOD, pd.DataFrame(), {"ANOVA groups": 3, "Standardized effect": .5, **options})


def sheet(options):
    return run(options).tables[pp.METHOD]["Value"].to_dict()


def refused(test, options, field, contains=""):
    with test.assertRaises(FieldError) as caught:
        run(options)
    test.assertEqual(caught.exception.field, field, str(caught.exception))
    test.assertIn(contains, str(caught.exception))
    return str(caught.exception)


def t_power(effect, n_a, n_b, alpha):
    df = n_a + n_b - 2
    cutoff = stats.t.isf(alpha / 2, df)
    delta = effect / sqrt(1 / n_a + 1 / n_b)
    lower = stats.nct.cdf(-cutoff, df, delta)
    return stats.nct.sf(cutoff, df, delta) + (lower if lower == lower else 0.0)  # scipy: NaN when delta is large


class PacketCases(unittest.TestCase):
    def test_every_case_matches_the_frozen_oracle(self):
        for name, options in CASES.items():
            with self.subTest(name):
                got = sheet(options)
                for key, want in EXPECTED[name].items():
                    if isinstance(want, str):
                        self.assertEqual(got[key], want, key)
                    else:
                        self.assertAlmostEqual(float(got[key]), want, places=9, msg=f"{name}/{key}")

    def test_legacy_recipe_has_the_historical_sheet_and_no_figure(self):
        result = run(LEGACY)
        self.assertEqual(list(result.tables), [pp.METHOD])
        self.assertIsNone(result.figure)
        self.assertEqual(list(result.tables[pp.METHOD]["Value"].index),
                         ["Design", "Effect size", "Effect measure", "Alpha", "N unit", "Groups", "N", "Total N",
                          "Target power", "Power"])

    def test_explicit_off_keys_equal_absent_keys(self):
        explicit = {**LEGACY, "Effect input": "Standardized effect", "Allocation A:B": "1:1",
                    "Show power curve": False}
        self.assertEqual(sheet(explicit), sheet(LEGACY))
        self.assertEqual(list(run(explicit).tables), [pp.METHOD])


class LegacyParity(unittest.TestCase):
    """The standardized path returns the rows, values and types of the original functions."""

    def test_four_designs_in_both_goals(self):
        keys = {"One-sample t": "one-sample", "Paired t": "paired", "Independent t": "independent",
                "One-way ANOVA": "anova"}
        for label, key in keys.items():
            for effect in (.3, .62):
                options = {"Design": label, "Standardized effect": effect, "Alpha": .05, "ANOVA groups": 4}
                with self.subTest(label=label, goal="Sample size", effect=effect):
                    old = design.sample_size(key, effect, alpha=.05, target=.9, groups=4)
                    new = sheet({**options, "Goal": "Sample size", "Target power": .9})
                    self.assertEqual(list(new), list(old))
                    self.assertEqual(new, old)
                    self.assertEqual([type(value) for value in new.values()], [type(value) for value in old.values()])
                with self.subTest(label=label, goal="Power", effect=effect):
                    old = design.power(key, effect, 37, alpha=.05, groups=4)
                    new = sheet({**options, "Goal": "Power", "N (per group, if independent)": 37})
                    self.assertEqual(new, old)
                    self.assertEqual([type(value) for value in new.values()], [type(value) for value in old.values()])


class EffectConversion(unittest.TestCase):
    def test_one_sample_independent_and_paired_differences(self):
        self.assertAlmostEqual(sheet({**CASES["one_sample"]})["Effect size"], abs(11.6 - 10) / 2.9, places=14)
        self.assertAlmostEqual(sheet(BASE)["Effect size"], 2 / 4, places=14)
        direct = sheet({"Design": "Paired t", "Goal": "Sample size", "Effect input": "Means and SD", "Mean A": 3,
                        "Mean B": 1, "Difference SD": 2.5, "Alpha": .05, "Target power": .8})
        self.assertEqual(direct["Effect size"], 2 / 2.5)
        self.assertEqual(direct["Difference SD"], 2.5)

    def test_anova_uses_the_population_sd_of_the_means(self):
        means = [12, 13.5, 15, 16]
        got = sheet({**CASES["anova"]})
        self.assertAlmostEqual(got["Effect size"], pstdev(means) / 5, places=14)
        self.assertEqual(got["Groups"], 4)

    def test_marginal_sds_and_correlation_equal_the_direct_difference_sd(self):
        sd = hypot(3 - 4, sqrt(2 * 3 * 4 * (1 - .6)))
        marginal = sheet(CASES["paired"])
        direct = sheet({**CASES["paired"], "Paired SD input": "SD of differences", "Difference SD": sd})
        for key in ("N", "Total N", "Power", "Effect size", "Difference SD"):
            self.assertAlmostEqual(marginal[key], direct[key], places=12, msg=key)
        self.assertAlmostEqual(marginal["Difference SD"], sqrt((3 - 4) ** 2 + 2 * 3 * 4 * (1 - .6)), places=12)

    def test_negative_correlation_and_extremes_stay_finite(self):
        base = {**CASES["paired"], "SD A": 3, "SD B": 3}
        self.assertAlmostEqual(sheet({**base, "Pair correlation": -1})["Difference SD"], 6.0, places=12)
        self.assertAlmostEqual(sheet({**base, "Pair correlation": .5})["Difference SD"], 3.0, places=12)
        self.assertGreater(sheet({**base, "SD B": 3.0000001, "Pair correlation": 1})["Difference SD"], 0)

    def test_huge_values_are_rescaled_instead_of_overflowing(self):
        got = sheet({**BASE, "Mean A": 1e308, "Mean B": -1e308, "Common SD": 1e308})
        self.assertAlmostEqual(got["Effect size"], 2.0, places=12)
        sd = pp.paired_difference_sd(1e200, 1e200, 0.)
        self.assertAlmostEqual(sd / 1e200, sqrt(2), places=12)
        many = [-1e308, 1e308, 0, 1e308]
        effect = pp._population_sd(many)
        self.assertTrue(np.isfinite(effect[0] * effect[1]))

    def test_a_tiny_gap_is_a_positive_effect(self):
        gap = np.nextafter(1.0, 2.0) - 1.0
        got = pp.check_options({**BASE, "Mean A": 1.0, "Mean B": float(np.nextafter(1.0, 2.0)), "Common SD": 1.0})
        self.assertEqual(got.effect, gap)


class AllocationSearch(unittest.TestCase):
    def smallest(self, effect, a, b, alpha, target):
        """First multiplier m with n_A = a m, n_B = b m (both at least 2) reaching the target, by scan."""
        for m in range(1, 5000):
            if min(a * m, b * m) < 2:
                continue
            if t_power(effect, a * m, b * m, alpha) >= target:
                return m
        raise AssertionError("scan exhausted")

    def test_minimum_matches_a_scan_for_many_ratios(self):
        for a, b in ((1, 1), (2, 3), (3, 2), (1, 3), (3, 1), (5, 4), (7, 1), (1, 7), (100, 99)):
            for effect, target, alpha in ((.5, .8, .05), (.8, .9, .025), (1.3, .95, .01)):
                expected = self.smallest(effect, a, b, alpha, target)
                got = sheet({"Design": "Independent t", "Goal": "Sample size", "Standardized effect": effect,
                             "Allocation A:B": f"{a}:{b}", "Alpha": alpha, "Target power": target})
                with self.subTest(ratio=f"{a}:{b}", effect=effect):
                    self.assertEqual(got["N"], a * expected)
                    self.assertEqual(got["Total N"], (a + b) * expected)
                    self.assertAlmostEqual(got["Power"], t_power(effect, a * expected, b * expected, alpha), places=11)
                    if (a, b) == (1, 1):
                        self.assertNotIn("N A", got)  # the legacy sheet adds nothing
                    else:
                        self.assertEqual((got["N A"], got["N B"]), (a * expected, b * expected))

    def test_power_at_a_given_size_matches_statsmodels_with_the_ratio(self):
        for a, b, m in ((2, 3, 26), (3, 2, 17), (1, 4, 30), (5, 3, 9)):
            got = sheet({"Design": "Independent t", "Goal": "Power", "Standardized effect": .45,
                         "Allocation A:B": f"{a}:{b}", "Alpha": .05, "N (per group, if independent)": a * m})
            want = TTestIndPower().power(.45, a * m, .05, ratio=b / a)
            self.assertAlmostEqual(got["Power"], want, places=11)
            self.assertEqual((got["N A"], got["N B"], got["Total N"]), (a * m, b * m, (a + b) * m))

    def test_reducible_and_inverted_ratios(self):
        reduced = sheet({**BASE, "Allocation A:B": "4:6"})
        self.assertEqual(reduced, sheet({**BASE, "Allocation A:B": "2:3"}))
        self.assertEqual(reduced["Allocation A:B"], "2:3")
        inverted = sheet({**BASE, "Allocation A:B": "3:2"})
        self.assertEqual((inverted["N A"], inverted["N B"]), (reduced["N B"], reduced["N A"]))
        self.assertAlmostEqual(inverted["Power"], reduced["Power"], places=12)

    def test_minimum_group_size_of_two_applies_to_both_groups(self):
        got = sheet({"Design": "Independent t", "Goal": "Sample size", "Standardized effect": 6.,
                     "Allocation A:B": "1:3", "Alpha": .05, "Target power": .2})
        self.assertEqual((got["N A"], got["N B"]), (2, 6))  # m = 1 would leave group A with one observation

    def test_the_first_available_multiple_can_reach_the_target(self):
        got = sheet({"Design": "Independent t", "Goal": "Sample size", "Standardized effect": 5.,
                     "Allocation A:B": "100:1", "Alpha": .05, "Target power": .5})
        self.assertEqual((got["N A"], got["N B"]), (200, 2))

    def test_power_mode_requires_an_exact_multiple_with_an_example(self):
        message = refused(self, {**BASE, "Goal": "Power", "Allocation A:B": "2:3",
                                 "N (per group, if independent)": 51}, pp.SIZE, "multiple of 2")
        self.assertIn("50 or 52", message)
        self.assertEqual(sheet({**BASE, "Goal": "Power", "Allocation A:B": "2:3",
                                "N (per group, if independent)": 52})["N B"], 78)
        refused(self, {**BASE, "Goal": "Power", "Allocation A:B": "3:1", "N (per group, if independent)": 3},
                pp.SIZE, "smallest N is 6")
        refused(self, {**BASE, "Goal": "Power", "Allocation A:B": "1:100",
                       "N (per group, if independent)": 20000}, pp.SIZE, "limited to 1,000,000")


class Rejections(unittest.TestCase):
    def test_allocation_syntax(self):
        for text in ("0:1", "1.5:2", "2:3:4", "1:101", "101:1", "a:b", "2", ":3", "2:", "-1:2", "", " ", "2/3"):
            with self.subTest(text):
                refused(self, {**BASE, "Allocation A:B": text}, pp.ALLOCATION, "two whole numbers")
        refused(self, {**BASE, "Allocation A:B": 1.5}, pp.ALLOCATION)
        self.assertEqual(sheet({**BASE, "Allocation A:B": " 2 : 3 "})["Allocation A:B"], "2:3")

    def test_paired_correlation_and_sds(self):
        paired = dict(CASES["paired"])
        refused(self, {**paired, "Pair correlation": 1.0001}, pp.CORRELATION, "between -1 and 1")
        refused(self, {**paired, "Pair correlation": -1.5}, pp.CORRELATION, "between -1 and 1")
        refused(self, {**paired, "SD A": 3, "SD B": 3, "Pair correlation": 1}, pp.CORRELATION, "zero")
        refused(self, {**paired, "SD A": 0}, pp.SD_A, "greater than 0")
        refused(self, {**paired, "SD B": -1}, pp.SD_B, "greater than 0")
        refused(self, {**paired, "Paired SD input": "SD of differences", "Difference SD": 0}, pp.DIFFERENCE_SD,
                "greater than 0")
        refused(self, {**paired, "Paired SD input": "Nonsense"}, pp.PAIRED_SD_INPUT)
        refused(self, {**paired, "SD A": 1.7e308, "SD B": 1.7e308, "Pair correlation": -1}, pp.SD_A, "range")

    def test_equal_means_and_unusable_effects(self):
        refused(self, {**BASE, "Mean B": 5}, pp.MEAN_A, "zero")
        refused(self, {**CASES["one_sample"], "Mean A": 10}, pp.MEAN_A, "zero")
        refused(self, {**CASES["anova"], "Group means": "3; 3; 3"}, pp.GROUP_MEANS, "all equal")
        refused(self, {**BASE, "Common SD": 0}, pp.COMMON_SD, "greater than 0")
        refused(self, {**BASE, "Common SD": -2}, pp.COMMON_SD, "greater than 0")
        refused(self, {**BASE, "Common SD": 1e-320}, pp.MEAN_A, "range")
        refused(self, {**BASE, "Mean A": "x"}, pp.MEAN_A, "must be a number")
        refused(self, {**BASE, "Mean A": float("nan")}, pp.MEAN_A, "finite")
        refused(self, {**BASE, "Mean B": float("inf")}, pp.MEAN_B, "finite")
        refused(self, {**BASE, "Mean B": True}, pp.MEAN_B, "must be a number")
        refused(self, {**BASE, "Mean B": None}, pp.MEAN_B, "must be a number")

    def test_group_means_list_validates_every_element(self):
        anova = dict(CASES["anova"])
        refused(self, {**anova, "Group means": "1; ;3"}, pp.GROUP_MEANS, "item 2 is empty")
        refused(self, {**anova, "Group means": "1;2;"}, pp.GROUP_MEANS, "item 3 is empty")
        refused(self, {**anova, "Group means": "1\n\n3"}, pp.GROUP_MEANS, "item 2 is empty")
        refused(self, {**anova, "Group means": ";1;2"}, pp.GROUP_MEANS, "item 1 is empty")
        refused(self, {**anova, "Group means": "1; x; 3"}, pp.GROUP_MEANS, "item 2 (x) must be a number")
        refused(self, {**anova, "Group means": "1; 1e999; 3"}, pp.GROUP_MEANS, "must be finite")
        refused(self, {**anova, "Group means": "1_0; 2"}, pp.GROUP_MEANS, "item 1")
        refused(self, {**anova, "Group means": "5"}, pp.GROUP_MEANS, "1 found")
        refused(self, {**anova, "Group means": ""}, pp.GROUP_MEANS, "0 found")
        refused(self, {**anova, "Group means": ";".join(str(i) for i in range(21))}, pp.GROUP_MEANS, "21 found")
        refused(self, {**anova, "Group means": 7}, pp.GROUP_MEANS)
        self.assertEqual(sheet({**anova, "Group means": ";".join(str(i) for i in range(20))})["Groups"], 20)

    def test_a_comma_is_a_decimal_mark_never_a_separator(self):
        comma = sheet({**CASES["anova"], "Group means": "12; 13,5\n15;16"})
        self.assertEqual(comma, sheet(CASES["anova"]))
        self.assertEqual(comma["Group means"], "12; 13.5; 15; 16")
        self.assertEqual(sheet({**BASE, "Common SD": "4,5"})["Common SD"], 4.5)
        self.assertEqual(pp.parse_means("13,5; 1,5e1"), [13.5, 15.0])

    def test_alpha_target_and_n_edges(self):
        for value in (0, 1, -.1, 1.5, "abc", float("nan"), True):
            refused(self, {**BASE, "Alpha": value}, pp.ALPHA)
            refused(self, {**BASE, "Target power": value}, pp.TARGET)
        for value in (1, 1.0, 2.5, 1_000_001, "1.5", "x", True, None):
            refused(self, {**BASE, "Goal": "Power", "N (per group, if independent)": value}, pp.SIZE,
                    "whole number")
        self.assertEqual(sheet({**BASE, "Alpha": 1e-12, "Target power": 1 - 1e-12})["Target power"], 1 - 1e-12)
        self.assertEqual(sheet({**BASE, "Goal": "Power", "N (per group, if independent)": "40"})["N"], 40)

    def test_budget_is_checked_with_the_limit_in_the_message(self):
        message = refused(self, {**BASE, "Mean B": 5.001}, pp.TARGET, "limit of 1,000,000")
        self.assertIn("Target power", message)
        self.assertLess(sheet({**BASE, "Goal": "Power", "N (per group, if independent)": 1_000_000,
                               "Mean B": 5.01})["Power"], 1)

    def test_bad_choices_name_their_field(self):
        refused(self, {**BASE, "Goal": "Both"}, pp.GOAL, "Choose a valid value")
        refused(self, {**BASE, "Design": "Chi-square"}, pp.DESIGN, "Choose a valid value")
        refused(self, {**BASE, "Effect input": "Odds ratio"}, pp.EFFECT_INPUT, "Choose a valid value")
        refused(self, {**BASE, "Show power curve": "yes"}, pp.SHOW_CURVE, "Choose a valid value")
        refused(self, {"Goal": "Sample size", "Alpha": .05, "Target power": .8}, pp.DESIGN)

    def test_standardized_effect_messages_keep_their_wording(self):
        refused(self, {**LEGACY, "Standardized effect": 0}, pp.STANDARDIZED_EFFECT, "Effect size must be positive")
        refused(self, {**LEGACY, "Standardized effect": "x"}, pp.STANDARDIZED_EFFECT, "must be a number")
        refused(self, {**LEGACY, "Design": "One-way ANOVA", "ANOVA groups": 1}, pp.GROUPS, "from 2 to 1,000,000")

    def test_inactive_fields_never_block(self):
        junk = {"Mean A": "bad", "Mean B": None, "Common SD": -1, "Group means": 5, "Allocation A:B": "9:9:9",
                "Difference SD": "x", "Pair correlation": 7, "N (per group, if independent)": "x"}
        self.assertEqual(sheet({**LEGACY, "Design": "One-sample t", **junk}), sheet({**LEGACY, "Design": "One-sample t"}))
        no_allocation = {**BASE, "Design": "Paired t", "Allocation A:B": "bad", "Common SD": "x", "Group means": "?",
                         "Paired SD input": "SD of differences", "Difference SD": 2, "SD A": "bad", "SD B": "bad",
                         "Pair correlation": "bad", "Standardized effect": "bad", "N (per group, if independent)": "bad"}
        self.assertEqual(sheet(no_allocation)["Difference SD"], 2.0)


class LargeEffects(unittest.TestCase):
    """scipy returns NaN for the lower noncentral tail of large effects; the plan must still be computed."""

    def test_large_effects_are_planned_for_every_t_design(self):
        for kind in ("One-sample t", "Paired t", "Independent t"):
            for effect in (8, 20, 100):
                with self.subTest(design=kind, effect=effect):
                    got = sheet({"Design": kind, "Goal": "Sample size", "Standardized effect": effect,
                                 "Alpha": .05, "Target power": .99})
                    self.assertGreaterEqual(got["Power"], .99)
                    self.assertLessEqual(got["N"], 3)
                    figure = run({"Design": kind, "Goal": "Sample size", "Standardized effect": effect,
                                  "Alpha": .05, "Target power": .99, "Show power curve": True})
                    self.assertIn(pp.CURVE_SHEET, figure.tables)

    def test_large_effects_from_means_and_unequal_allocation(self):
        got = sheet({**BASE, "Mean A": 10, "Mean B": 50, "Common SD": 5, "Target power": .9})
        self.assertAlmostEqual(got["Effect size"], 8.0)
        self.assertGreaterEqual(got["Power"], .9)
        unequal = sheet({"Design": "Independent t", "Goal": "Sample size", "Standardized effect": 1.3,
                         "Allocation A:B": "100:99", "Alpha": .01, "Target power": .95})
        self.assertEqual((unequal["N A"], unequal["N B"]), (100, 99))

    def test_an_extreme_alpha_never_raises_a_range_error(self):
        got = sheet({**BASE, "Alpha": 1e-12, "Target power": 1 - 1e-12})
        self.assertGreater(got["N"], 100)


class Curve(unittest.TestCase):
    def check(self, options):
        result = run({**options, "Show power curve": True})
        plan = pp.check_options({**options, "Show power curve": True})
        lattice = pp.Lattice(plan)
        curve = result.tables[pp.CURVE_SHEET]
        rows = result.tables[pp.METHOD]["Value"]
        self.assertTrue(2 <= len(curve) <= 200, len(curve))
        self.assertTrue(curve["N"].is_monotonic_increasing and curve["N"].is_unique)
        self.assertIn(rows["N"], curve["N"].tolist())
        if plan.goal == "Sample size" and rows["N"] > lattice.sizes(lattice.low)[0]:
            self.assertIn(rows["N"] - lattice.a, curve["N"].tolist())  # the feasible predecessor
        for row in curve.to_dict("records"):
            index = row["N"] // lattice.a
            self.assertEqual(row["N"], lattice.a * index)
            self.assertGreaterEqual(index, lattice.low)
            self.assertLessEqual(row["N A"] if plan.independent else row["N"], 1_000_000)
            self.assertAlmostEqual(row["Power"], lattice.power(index), places=14)
            if plan.independent:
                self.assertEqual((row["N A"], row["N B"]), (lattice.a * index, lattice.b * index))
                self.assertEqual(row["Total N"], row["N A"] + row["N B"])
        columns = ["N", "Total N", "Power"] + (["N A", "N B"] if plan.independent else [])
        self.assertEqual(list(curve.columns), columns)
        line = [line for line in result.figure.axes[0].lines if list(line.get_xdata()) == curve["Total N"].tolist()]
        self.assertTrue(line)
        self.assertEqual(result.figure.axes[0].get_ylim(), (0.0, 1.0))
        return result, curve

    def test_every_design_and_goal(self):
        for name, options in CASES.items():
            with self.subTest(name):
                self.check(options)
        self.check({**LEGACY, "Design": "One-way ANOVA", "ANOVA groups": 5})
        self.check({**LEGACY, "Goal": "Power", "N (per group, if independent)": 80})
        self.check({**BASE, "Allocation A:B": "3:7", "Show power curve": True})

    def test_small_n_shows_every_integer(self):
        result, curve = self.check({**LEGACY, "Standardized effect": 2.0, "Design": "One-sample t"})
        self.assertEqual(curve["N"].tolist(), list(range(2, 2 + len(curve))))

    def test_curve_does_not_change_the_summary_sheet(self):
        for options in (CASES["allocation"], CASES["paired"], LEGACY):
            without = run(options).tables[pp.METHOD]
            with_curve = run({**options, "Show power curve": True}).tables[pp.METHOD]
            pd.testing.assert_frame_equal(without, with_curve)

    def test_search_and_curve_do_not_allocate_a_million_rows(self):
        tracemalloc.start()
        try:
            for options in ({**BASE, "Mean B": 5.01, "Goal": "Power", "N (per group, if independent)": 1_000_000},
                            {**LEGACY, "Standardized effect": .003, "Goal": "Power",
                             "N (per group, if independent)": 900_000},
                            {**BASE, "Mean B": 5.05, "Allocation A:B": "2:1"}):
                result = run({**options, "Show power curve": True})
                self.assertLessEqual(len(result.tables[pp.CURVE_SHEET]), 200)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 40_000_000, peak)

    def test_curve_covers_the_chosen_size_even_when_the_result_is_late(self):
        result, curve = self.check({**BASE, "Goal": "Power", "Allocation A:B": "2:3",
                                    "N (per group, if independent)": 5000, "Mean B": 5.3})
        self.assertEqual(curve["N"].iloc[-1] >= 5000, True)


class Recipe(unittest.TestCase):
    def test_canonical_numbers_whatever_the_decimal_mark(self):
        typed = {**BASE, "Mean A": "5,25", "Common SD": "4,5", "Alpha": "0,05", "Target power": "0,8",
                 "Allocation A:B": "2:3", "Show power curve": False}
        plan = pp.check_options(typed)
        recipe = pp.normalized_options(typed, plan)
        self.assertEqual(recipe["Mean A"], 5.25)
        self.assertEqual(recipe["Common SD"], 4.5)
        self.assertEqual((recipe["Alpha"], recipe["Target power"]), (.05, .8))
        self.assertEqual(json.loads(json.dumps(recipe)), recipe)
        self.assertEqual(sheet(recipe), sheet(typed))

    def test_group_means_text_is_canonical(self):
        plan = pp.check_options({**CASES["anova"], "Group means": " 12;13,5 \r\n 15 ; 1.6e1 "})
        self.assertEqual(plan.options["Group means"], "12; 13.5; 15; 16")

    def test_only_active_options_are_kept(self):
        junk = {**BASE, "Standardized effect": "bad", "Group means": "x", "Goal": "Sample size",
                "N (per group, if independent)": "bad", "Difference SD": "bad"}
        plan = pp.check_options(junk)
        recipe = pp.normalized_options(junk, plan)
        self.assertNotIn("Standardized effect", recipe)
        self.assertNotIn("N (per group, if independent)", recipe)
        self.assertNotIn("Group means", recipe)
        self.assertEqual(recipe["Effect input"], "Means and SD")

    def test_visibility_by_design_goal_and_input(self):
        def shown(**options):
            return {name for name, visible in pp.visibility(options).items() if visible}
        self.assertEqual(shown(Goal="Sample size", Design="Independent t"),
                         {"Target power", "Allocation A:B", "Standardized effect"})
        self.assertEqual(shown(Goal="Power", Design="One-way ANOVA"),
                         {"N (per group, if independent)", "ANOVA groups", "Standardized effect"})
        self.assertEqual(shown(Design="One-way ANOVA", **{"Effect input": "Means and SD"}),
                         {"Target power", "Group means", "Common SD"})
        self.assertEqual(shown(Design="Paired t", **{"Effect input": "Means and SD", "Paired SD input":
                                                      "Marginal SDs and correlation"}),
                         {"Target power", "Mean A", "Mean B", "Paired SD input", "SD A", "SD B", "Pair correlation"})
        self.assertEqual(shown(Design="Paired t", **{"Effect input": "Means and SD"}),
                         {"Target power", "Mean A", "Mean B", "Paired SD input", "Difference SD"})
        self.assertEqual(shown(Design="One-sample t", **{"Effect input": "Means and SD"}),
                         {"Target power", "Mean A", "Null mean", "Common SD"})

    def test_results_carry_provenance_and_assumptions_only_on_new_paths(self):
        legacy = sheet(LEGACY)
        self.assertNotIn("Assumptions", legacy)
        self.assertNotIn("Effect source", legacy)
        new = sheet(CASES["allocation"])
        self.assertEqual(new["Effect source"], "Means and SD")
        self.assertEqual((new["Mean A"], new["Mean B"], new["Common SD"]), (5.0, 7.0, 4.0))
        self.assertIn("fixed allocation 2:3", new["Assumptions"].lower())
        self.assertIn("Prospective", new["Power basis"])
        unequal = sheet(CASES["allocation_power"])
        self.assertEqual(unequal["Effect source"], "Standardized effect")
        self.assertEqual(unequal["Design"], "Independent t test with a fixed allocation")
        equal = sheet({**CASES["allocation"], "Allocation A:B": "1:1"})
        self.assertEqual(equal["Design"], "Equal-size independent t test")
        self.assertEqual((equal["N A"], equal["N B"], equal["Allocation A:B"]), (equal["N"], equal["N"], "1:1"))


class Translation(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.active_language())

    def triggers(self):
        paired = dict(CASES["paired"])
        anova = dict(CASES["anova"])
        return [
            {**BASE, "Mean B": 5}, {**CASES["one_sample"], "Mean A": 10},
            {**BASE, "Common SD": 0}, {**BASE, "Mean A": "x"}, {**BASE, "Mean A": float("nan")},
            {**BASE, "Alpha": 2}, {**BASE, "Goal": "Both"}, {**LEGACY, "Standardized effect": 0},
            {**LEGACY, "Standardized effect": "x"}, {**LEGACY, "Design": "One-way ANOVA", "ANOVA groups": 1},
            {**BASE, "Goal": "Power", "N (per group, if independent)": 1.5},
            {**BASE, "Allocation A:B": "2:3:4"},
            {**BASE, "Goal": "Power", "Allocation A:B": "2:3", "N (per group, if independent)": 51},
            {**BASE, "Goal": "Power", "Allocation A:B": "3:1", "N (per group, if independent)": 3},
            {**BASE, "Goal": "Power", "Allocation A:B": "3:1", "N (per group, if independent)": 4},
            {**BASE, "Goal": "Power", "Allocation A:B": "1:100", "N (per group, if independent)": 20000},
            {**paired, "Pair correlation": 2}, {**paired, "SD A": 3, "SD B": 3, "Pair correlation": 1},
            {**paired, "SD A": 1.7e308, "SD B": 1.7e308, "Pair correlation": -1},
            {**BASE, "Common SD": 1e-320}, {**BASE, "Mean B": 5.001},
            {**anova, "Group means": "1; ;3"}, {**anova, "Group means": "1;2;"}, {**anova, "Group means": "1; x; 3"},
            {**anova, "Group means": "1; 1e999; 3"}, {**anova, "Group means": "5"}, {**anova, "Group means": "3;3"},
            {**anova, "Group means": 7},
        ]

    def test_every_engine_message_has_an_italian_form(self):
        from analisi.i18n import translate_message
        for options in self.triggers():
            with self.assertRaises(FieldError) as caught:
                run(options)
            english = str(caught.exception)
            i18n.set_language("it")
            italian = translate_message(english, "power.error.", {"field": i18n.ui})
            i18n.set_language("en")
            with self.subTest(english):
                self.assertNotEqual(italian, english)
                self.assertNotIn("{", italian)

    def test_the_examples_of_the_multiple_rule_are_localized(self):
        from analisi.i18n import translate_message
        i18n.set_language("it")
        two = translate_message("N must be a multiple of 2 to keep Allocation 2:3 exact, for example 50 or 52.",
                                "power.error.")
        one = translate_message("N must be a multiple of 3 to keep Allocation 3:1 exact, for example 6.",
                                "power.error.")
        self.assertTrue(two.endswith("per esempio 50 o 52."), two)
        self.assertTrue(one.endswith("per esempio 6."), one)

    def test_catalog_pairs_are_complete(self):
        from analisi import power_plan_text as text
        self.assertEqual(set(text.EN), set(text.IT))
        for key in text.EN:
            self.assertEqual(set(i18n.placeholders(text.EN[key])), set(i18n.placeholders(text.IT[key])), key)
        i18n.set_language("it")
        for caption in text.CAPTIONS:  # a caption the interface already translated keeps that wording
            self.assertTrue(i18n.ui(caption), caption)
            self.assertNotIn("{", i18n.ui(caption))


if __name__ == "__main__":
    unittest.main()
