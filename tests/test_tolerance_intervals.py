"""Tolerance intervals (0.93): factors, ranks, row mapping, errors, figure.

The expected numbers do not come from the engine's own helpers. Normal factors come from SciPy's chi-square and
noncentral t functions, distribution-free confidences from a brute-force binomial sum, and the frozen
``tests/data/tolerance_093/expected.json`` holds the values of the independent reference.
"""
import io
import json
import math
import re
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi import tolerance_intervals as ti
from analisi.field_error import FieldError
from analisi.presentation import graph_groups
from analisi.tolerance_intervals import (CONFIDENCE, COVERAGE, DISTRIBUTION, GROUP, SETTINGS, SHOW_GRAPH, SIDES,
                                         TOLERANCE, VARIABLES, tolerance_intervals)
from analisi.workbench import GROUPS, GRAPH_METHODS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "tolerance_093"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
LOTS = pd.read_csv(DATA / "measurements.csv")


def run(frame, **options):
    options.setdefault(VARIABLES, ["Signal"])
    return tolerance_intervals(frame, options)


def table(result):
    return result.tables[TOLERANCE]


def row(result, group=None, variable=None):
    found = table(result)
    if variable is not None:
        found = found[found["Variable"] == variable]
    if group is not None:
        found = found[found["Group"] == group]
    assert len(found) == 1, found
    return found.iloc[0]


def beta_oracle(n, rank, coverage, two_sided):
    """Confidence that order statistics cover ``coverage`` of the population, as a binomial sum."""
    p = coverage / 100
    limit = n - 2 * rank if two_sided else n - rank
    return 100 * sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(0, limit + 1))


def largest_rank(n, coverage, confidence, two_sided):
    best = None
    for rank in range(1, n // 2 + 1 if two_sided else n + 1):
        if beta_oracle(n, rank, coverage, two_sided) >= confidence - 1e-9:
            best = rank
    return best


def howe_oracle(n, coverage, confidence):
    z = stats.norm.ppf((1 + coverage / 100) / 2)
    return z * math.sqrt((n - 1) * (1 + 1 / n) / stats.chi2.ppf(1 - confidence / 100, n - 1))


def exact_one_sided_oracle(n, coverage, confidence):
    return stats.nct.ppf(confidence / 100, n - 1, stats.norm.ppf(coverage / 100) * math.sqrt(n)) / math.sqrt(n)


class NormalFactors(unittest.TestCase):
    def test_textbook_values(self):
        # n = 10, 95 % of the population, 95 % confidence. Classical tables: exact two-sided 3.379 (Howe's
        # approximation is a little above it, 3.382) and exact one-sided 2.911.
        self.assertAlmostEqual(ti.normal_two_sided_factor(10, 95, 95), 3.381913, places=5)
        self.assertAlmostEqual(ti.normal_two_sided_factor(10, 95, 95), 3.379, delta=0.005)
        self.assertAlmostEqual(ti.normal_one_sided_factor(10, 95, 95), 2.911, places=3)

    def test_two_sided_matches_the_howe_formula(self):
        for n in (2, 3, 5, 12, 60, 500, 20_000):
            for coverage, confidence in ((90, 95), (99, 99), (50, 50), (95, 90), (99.9, 99.9), (10, 80)):
                with self.subTest(n=n, coverage=coverage, confidence=confidence):
                    self.assertAlmostEqual(ti.normal_two_sided_factor(n, coverage, confidence) /
                                           howe_oracle(n, coverage, confidence), 1.0, places=9)

    def test_one_sided_matches_the_noncentral_t_quantile(self):
        for n in (2, 3, 7, 12, 60, 400):
            for coverage, confidence in ((90, 95), (99, 99), (50, 50), (95, 90), (80, 99)):
                with self.subTest(n=n, coverage=coverage, confidence=confidence):
                    expected = exact_one_sided_oracle(n, coverage, confidence)
                    self.assertAlmostEqual(ti.normal_one_sided_factor(n, coverage, confidence), expected,
                                           delta=1e-6 * max(1.0, abs(expected)))

    def test_factors_grow_with_confidence_and_coverage_and_fall_with_n(self):
        for factor in (ti.normal_two_sided_factor, ti.normal_one_sided_factor):
            self.assertLess(factor(30, 90, 90), factor(30, 90, 99))
            self.assertLess(factor(30, 90, 95), factor(30, 99, 95))
            self.assertGreater(factor(10, 90, 95), factor(100, 90, 95))

    def test_frozen_reference_factors(self):
        for lot, values in EXPECTED.items():
            normal = values["normal"]
            with self.subTest(lot=lot):
                self.assertAlmostEqual(ti.normal_two_sided_factor(normal["N"], 90, 95), normal["k2"], places=9)
                self.assertAlmostEqual(ti.normal_one_sided_factor(normal["N"], 90, 95), normal["k1"], places=7)


class DistributionFreeRanks(unittest.TestCase):
    def test_confidence_matches_a_binomial_sum(self):
        for n in (5, 12, 60, 200):
            for coverage in (50, 90, 95, 99):
                for rank in (1, 2, 3):
                    for two_sided in (True, False):
                        if two_sided and 2 * rank > n:
                            continue
                        with self.subTest(n=n, coverage=coverage, rank=rank, two_sided=two_sided):
                            self.assertAlmostEqual(100 * ti.rank_confidence(n, rank, coverage, two_sided),
                                                   beta_oracle(n, rank, coverage, two_sided), places=7)

    def test_rank_is_the_largest_one_that_keeps_the_confidence(self):
        for n in (5, 8, 14, 29, 59, 60, 150):
            for coverage, confidence in ((90, 95), (95, 95), (50, 80), (80, 99), (99, 50)):
                for two_sided in (True, False):
                    with self.subTest(n=n, coverage=coverage, confidence=confidence, two_sided=two_sided):
                        rank, _maximum = ti.distribution_free_rank(n, coverage, confidence, two_sided)
                        self.assertEqual(rank, largest_rank(n, coverage, confidence, two_sided))

    def test_known_sample_sizes_for_the_first_rank(self):
        # Smallest n whose extreme values give 95 % coverage with 95 % confidence: 93 two-sided, 59 one-sided.
        self.assertIsNone(ti.distribution_free_rank(92, 95, 95, True)[0])
        self.assertEqual(ti.distribution_free_rank(93, 95, 95, True)[0], 1)
        self.assertIsNone(ti.distribution_free_rank(58, 95, 95, False)[0])
        self.assertEqual(ti.distribution_free_rank(59, 95, 95, False)[0], 1)

    def test_frozen_reference_ranks(self):
        for lot, values in EXPECTED.items():
            n = values["normal"]["N"]
            for sides, expected in values["rank"].items():
                rank, maximum = ti.distribution_free_rank(n, 90, 95, sides == "Two-sided")
                interval = expected["interval"]
                with self.subTest(lot=lot, sides=sides):
                    if interval is None:
                        self.assertIsNone(rank)
                    else:
                        self.assertEqual(rank, interval["Lower rank"] if interval["Lower rank"] is not None
                                         else n - interval["Upper rank"] + 1)
                    self.assertAlmostEqual(100 * maximum, expected["max"], places=6)


class AnalysisTable(unittest.TestCase):
    def test_normal_two_sided_against_the_frozen_reference(self):
        result = run(LOTS, **{GROUP: "Group"})
        for lot, values in EXPECTED.items():
            normal = values["normal"]
            found = row(result, lot)
            with self.subTest(lot=lot):
                self.assertEqual(found["N"], normal["N"])
                self.assertAlmostEqual(found["Mean"], normal["Mean"], places=9)
                self.assertAlmostEqual(found["SD"], normal["SD"], places=9)
                self.assertAlmostEqual(found["Lower"], normal["two_lower"], places=8)
                self.assertAlmostEqual(found["Upper"], normal["two_upper"], places=8)
                self.assertAlmostEqual(found["k factor"], normal["k2"], places=9)
                self.assertEqual(found["Status"], "OK")
                self.assertIsNone(found["Lower rank"])
                self.assertIsNone(found["Upper rank"])

    def test_normal_one_sided_against_the_frozen_reference(self):
        for sides, key in (("Lower", "one_lower"), ("Upper", "one_upper")):
            result = run(LOTS, **{GROUP: "Group", SIDES: sides})
            for lot, values in EXPECTED.items():
                found = row(result, lot)
                with self.subTest(lot=lot, sides=sides):
                    self.assertAlmostEqual(found["Lower" if sides == "Lower" else "Upper"], values["normal"][key],
                                           places=7)
                    self.assertTrue(np.isnan(found["Upper" if sides == "Lower" else "Lower"]))
                    self.assertAlmostEqual(found["k factor"], values["normal"]["k1"], places=7)

    def test_distribution_free_against_the_frozen_reference(self):
        for sides, values_key in (("Two-sided", "Two-sided"), ("Lower", "Lower"), ("Upper", "Upper")):
            result = run(LOTS, **{GROUP: "Group", SIDES: sides, DISTRIBUTION: "Distribution-free"})
            for lot, values in EXPECTED.items():
                expected = values["rank"][values_key]
                interval = expected["interval"]
                found = row(result, lot)
                with self.subTest(lot=lot, sides=sides):
                    if interval is None:
                        self.assertEqual(found["Status"], "Insufficient sample")
                        for name in ("Lower rank", "Upper rank", "Lower", "Upper", "Achieved confidence (%)"):
                            self.assertTrue(found[name] is None or pd.isna(found[name]), name)
                    else:
                        self.assertEqual(found["Status"], "OK")
                        for name in ("Lower rank", "Upper rank", "Lower", "Upper"):
                            if interval[name] is None:
                                self.assertTrue(found[name] is None or pd.isna(found[name]), name)
                            else:
                                self.assertEqual(found[name], interval[name], name)
                        self.assertAlmostEqual(found["Achieved confidence (%)"], interval["Achieved confidence (%)"],
                                               places=6)
                    self.assertAlmostEqual(found["Maximum confidence (%)"], expected["max"], places=6)

    def test_limits_reported_are_actual_order_statistics(self):
        values = np.array([4.2, 1.1, 9.9, 3.3, 7.7, 2.2, 8.8, 6.6, 5.5, 0.4, 10.1, 3.9])
        frame = pd.DataFrame({"x": values})
        found = row(run(frame, **{VARIABLES: ["x"], DISTRIBUTION: "Distribution-free", COVERAGE: 50, CONFIDENCE: 80}))
        ordered = np.sort(values)
        self.assertEqual(found["Lower"], ordered[found["Lower rank"] - 1])
        self.assertEqual(found["Upper"], ordered[found["Upper rank"] - 1])
        self.assertEqual(found["Lower rank"] + found["Upper rank"], len(values) + 1)

    def test_insufficient_sample_keeps_counts_and_status(self):
        result = run(LOTS.iloc[60:70], **{GROUP: "Group", DISTRIBUTION: "Distribution-free"})
        found = row(result, "Lot B")
        self.assertEqual(found["Status"], "Insufficient sample")
        self.assertEqual(found["N"], 10)
        self.assertTrue(np.isnan(found["Lower"]) and np.isnan(found["Upper"]))
        self.assertIsNone(found["Lower rank"])
        self.assertGreater(found["Maximum confidence (%)"], 0)
        self.assertLess(found["Maximum confidence (%)"], 95)

    def test_single_value_and_constant_sample(self):
        single = row(run(pd.DataFrame({"x": [3.0]}), **{VARIABLES: ["x"]}))
        self.assertEqual((single["N"], single["Status"], single["Mean"]), (1, "Insufficient sample", 3.0))
        self.assertTrue(np.isnan(single["Lower"]) and np.isnan(single["SD"]))
        constant = row(run(pd.DataFrame({"x": [2.0] * 6}), **{VARIABLES: ["x"]}))
        self.assertEqual((constant["N"], constant["Status"], constant["SD"]), (6, "Variance not measurable", 0.0))
        self.assertTrue(np.isnan(constant["Lower"]) and np.isnan(constant["Upper"]))

    def test_empty_group_cell_and_missing_values_do_not_create_rows(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 3.0],
                              "g": ["a", "a", "a", "", None, "b", "b", "b"]})
        result = run(frame, **{VARIABLES: ["x"], GROUP: "g"})
        self.assertEqual(list(table(result)["Group"]), ["a", "b"])
        self.assertEqual(list(table(result)["N"]), [2, 3])
        settings = result.tables[SETTINGS]
        self.assertEqual(settings.loc["Rows without a group (omitted)"].iloc[0], 2)
        self.assertEqual(settings.loc["Missing values omitted (x)"].iloc[0], 1)

    def test_row_mapping_with_interleaved_groups_and_blank_cells(self):
        rng = np.random.default_rng(11)
        a, b, c = rng.normal(10, 2, 40), rng.normal(50, 5, 25), rng.normal(-3, 1, 15)
        groups = np.array(["A"] * 40 + ["B"] * 25 + ["C"] * 15)
        y = np.concatenate([a, b, c])
        order = rng.permutation(len(y))
        frame = pd.DataFrame({"y": y[order], "other": y[order] * 2 + 1, "g": groups[order]})
        frame.loc[frame.index[::13], "y"] = np.nan
        result = run(frame, **{VARIABLES: ["y", "other"], GROUP: "g"})
        for name in ("y", "other"):
            for label in "ABC":
                chosen = frame.loc[frame["g"] == label, name].dropna().to_numpy()
                n = len(chosen)
                mean, sd = chosen.mean(), chosen.std(ddof=1)
                k = howe_oracle(n, 90, 95)
                found = row(result, label, name)
                with self.subTest(variable=name, group=label):
                    self.assertEqual(found["N"], n)
                    self.assertAlmostEqual(found["Mean"], mean, places=9)
                    self.assertAlmostEqual(found["Lower"], mean - k * sd, places=8)
                    self.assertAlmostEqual(found["Upper"], mean + k * sd, places=8)

    def test_row_order_and_group_label_type_do_not_change_the_numbers(self):
        frame = pd.DataFrame({"y": np.arange(1.0, 41.0) ** 1.3, "g": [2, 1] * 20})
        first = run(frame, **{VARIABLES: ["y"], GROUP: "g"})
        shuffled = frame.sample(frac=1, random_state=3)
        second = run(shuffled, **{VARIABLES: ["y"], GROUP: "g"})
        for label in ("1", "2"):
            for name in ("Lower", "Upper", "N"):
                self.assertAlmostEqual(row(first, label)[name], row(second, label)[name], places=9)
        self.assertEqual(sorted(table(first)["Group"]), ["1", "2"])

    def test_text_numbers_and_excluded_style_cells(self):
        frame = pd.DataFrame({"x": ["1.5", " 2.5 ", "3.5", "4.5", "", None, "5.5"]})
        found = row(run(frame, **{VARIABLES: ["x"]}))
        self.assertEqual(found["N"], 5)
        self.assertAlmostEqual(found["Mean"], 3.5)

    def test_shift_and_unit_invariance(self):
        base = run(LOTS, **{GROUP: "Group"})
        scaled = run(LOTS.assign(Signal=LOTS["Signal"] * 1000), **{GROUP: "Group"})
        shifted = run(LOTS.assign(Signal=LOTS["Signal"] + 1e9), **{GROUP: "Group"})
        for lot in ("Lot A", "Lot B"):
            for name in ("Lower", "Upper", "Mean", "SD"):
                self.assertAlmostEqual(row(scaled, lot)[name] / 1000, row(base, lot)[name], places=8)
            self.assertAlmostEqual(row(shifted, lot)["SD"], row(base, lot)["SD"], places=5)
            self.assertAlmostEqual(row(shifted, lot)["Upper"] - row(shifted, lot)["Lower"],
                                   row(base, lot)["Upper"] - row(base, lot)["Lower"], places=4)
            self.assertAlmostEqual(row(shifted, lot)["k factor"], row(base, lot)["k factor"], places=12)

    def test_extreme_scales_stay_finite(self):
        for scale in (1e-200, 1e200):
            found = row(run(pd.DataFrame({"x": np.arange(1.0, 13.0) * scale}), **{VARIABLES: ["x"]}))
            with self.subTest(scale=scale):
                self.assertEqual(found["Status"], "OK")
                self.assertTrue(math.isfinite(found["Lower"]) and math.isfinite(found["Upper"]))
                self.assertAlmostEqual(found["Mean"] / scale, 6.5, places=9)
                self.assertAlmostEqual(found["SD"] / scale, np.arange(1.0, 13.0).std(ddof=1), places=9)

    def test_ties_are_reported_for_the_distribution_free_method(self):
        frame = pd.DataFrame({"x": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0] * 20})
        result = run(frame, **{VARIABLES: ["x"], DISTRIBUTION: "Distribution-free"})
        self.assertIn("Repeated values", result.tables[SETTINGS].index)
        clean = run(pd.DataFrame({"x": np.arange(100.0)}), **{VARIABLES: ["x"], DISTRIBUTION: "Distribution-free"})
        self.assertNotIn("Repeated values", clean.tables[SETTINGS].index)

    def test_very_high_and_low_confidence_keep_ordering(self):
        for confidence in (0.001, 1e-9, 99.999, 100 - 1e-9):
            found = row(run(LOTS[LOTS.Group == "Lot A"], **{CONFIDENCE: confidence}))
            with self.subTest(confidence=confidence):
                self.assertEqual(found["Status"], "OK")
                self.assertLess(found["Lower"], found["Mean"])
                self.assertGreater(found["Upper"], found["Mean"])

    def test_settings_table_describes_the_run(self):
        result = run(LOTS, **{GROUP: "Group", SIDES: "Upper", COVERAGE: 99.0, CONFIDENCE: 90.0})
        settings = result.tables[SETTINGS]["Value"]
        self.assertEqual(settings["Sides"], "Upper")
        self.assertEqual(settings["Population coverage (%)"], 99.0)
        self.assertEqual(settings["Confidence level (%)"], 90.0)
        self.assertEqual(settings["Group"], "Group")
        self.assertIn("exact factor", settings["Method"])


class Validation(unittest.TestCase):
    def check(self, field, frame=LOTS, **options):
        options.setdefault(VARIABLES, ["Signal"])
        with self.assertRaises(FieldError) as caught:
            tolerance_intervals(frame, options)
        self.assertEqual(caught.exception.field, field, str(caught.exception))
        return str(caught.exception)

    def test_variables(self):
        self.check(VARIABLES, **{VARIABLES: []})
        self.check(VARIABLES, **{VARIABLES: None})
        self.check(VARIABLES, **{VARIABLES: "Signal"})
        self.check(VARIABLES, **{VARIABLES: ["Missing"]})
        self.check(VARIABLES, **{VARIABLES: ["Signal", "Signal"]})
        wide = pd.DataFrame({f"c{i}": np.arange(10.0) for i in range(25)})
        self.check(VARIABLES, wide, **{VARIABLES: list(wide)})

    def test_group(self):
        self.check(GROUP, **{GROUP: "Missing"})
        self.check(GROUP, **{GROUP: "Signal"})
        many = pd.DataFrame({"x": np.arange(60.0), "g": np.arange(60)})
        self.check(GROUP, many, **{VARIABLES: ["x"], GROUP: "g"})

    def test_percentages_and_choices(self):
        for field in (COVERAGE, CONFIDENCE):
            for bad in (0, 100, -1, 101, math.nan, math.inf, "90", None, True, 1e-320 * 0 + 100.0000001):
                with self.subTest(field=field, value=bad):
                    self.check(field, **{field: bad})
        self.check(DISTRIBUTION, **{DISTRIBUTION: "Gamma"})
        self.check(SIDES, **{SIDES: "Both"})
        self.check(SHOW_GRAPH, **{SHOW_GRAPH: "yes"})

    def test_non_numeric_and_non_finite_values(self):
        text = pd.DataFrame({"x": ["1", "2", "three", "4"]})
        self.assertIn("Source row 2", self.check(VARIABLES, text, **{VARIABLES: ["x"]}))
        infinite = pd.DataFrame({"x": [1.0, 2.0, np.inf, 4.0]})
        self.assertIn("Source row 2", self.check(VARIABLES, infinite, **{VARIABLES: ["x"]}))
        boolean = pd.DataFrame({"x": [True, False, True]})
        self.check(VARIABLES, boolean, **{VARIABLES: ["x"]})

    def test_a_bad_value_outside_the_used_rows_is_ignored(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0], "g": ["a", "a", "a", "a", None]})
        frame["x"] = frame["x"].astype(object)
        frame.loc[4, "x"] = "not a number"
        found = run(frame, **{VARIABLES: ["x"], GROUP: "g"})
        self.assertEqual(row(found, "a")["N"], 4)

    def test_budgets(self):
        big = pd.DataFrame({"x": np.zeros(100_001)})
        self.assertIn("100,000", self.check(VARIABLES, big, **{VARIABLES: ["x"]}))
        pairs = pd.DataFrame({f"c{i}": np.arange(10.0) % 5 for i in range(24)})
        pairs["g"] = np.arange(10)
        self.check(GROUP, pairs, **{VARIABLES: [c for c in pairs if c != "g"], GROUP: "g"})

    def test_budget_applies_to_rows_in_a_group_not_to_the_whole_sheet(self):
        frame = pd.DataFrame({"x": np.arange(100_001.0), "g": ["a"] * 99_000 + ["b"] * 1_001})
        self.check(VARIABLES, frame, **{VARIABLES: ["x"], GROUP: "g"})

    def test_errors_leave_the_input_untouched(self):
        frame = LOTS.copy()
        with self.assertRaises(FieldError):
            tolerance_intervals(frame, {VARIABLES: ["Signal"], COVERAGE: 100})
        pd.testing.assert_frame_equal(frame, LOTS)


class FigureTests(unittest.TestCase):
    def figure(self, frame=LOTS, **options):
        options.setdefault(SHOW_GRAPH, True)
        return run(frame, **options).figure

    def gids(self, figure):
        return [line.get_gid() for axes in figure.axes for line in axes.lines if line.get_gid()]

    def test_no_figure_unless_requested(self):
        self.assertIsNone(run(LOTS).figure)
        self.assertIsNotNone(self.figure())

    def test_two_sided_has_one_gid_interval_per_group_and_panel(self):
        figure = self.figure(**{VARIABLES: ["Signal", "Shifted"], GROUP: "Group"})
        self.assertEqual(len(figure.axes), 2)
        self.assertEqual(self.gids(figure), [f"tolerance-interval-{i}" for i in range(1, 5)])
        for axes, name in zip(figure.axes, ("Signal", "Shifted")):
            self.assertEqual(axes.get_title(), name)
            for line in axes.lines:
                x = np.asarray(line.get_xdata(), dtype=float)
                self.assertEqual(len(x), 2)
                self.assertLess(x[0], x[1])

    def test_interval_coordinates_equal_the_table(self):
        result = run(LOTS, **{GROUP: "Group", SHOW_GRAPH: True})
        lines = [line for line in result.figure.axes[0].lines if line.get_gid()]
        for line, (_, found) in zip(lines, table(result).iterrows()):
            self.assertAlmostEqual(line.get_xdata()[0], found["Lower"])
            self.assertAlmostEqual(line.get_xdata()[1], found["Upper"])

    def test_one_sided_uses_a_directional_symbol_and_a_single_coordinate(self):
        for sides, marker in (("Lower", ">"), ("Upper", "<")):
            figure = self.figure(**{GROUP: "Group", SIDES: sides})
            lines = [line for line in figure.axes[0].lines if line.get_gid()]
            self.assertEqual(len(lines), 2)
            for line in lines:
                self.assertTrue(line.get_gid().startswith("tolerance-limit-"))
                self.assertEqual(line.get_marker(), marker)
                self.assertEqual(len(line.get_xdata()), 1)

    def test_unavailable_rows_are_labelled_not_drawn_and_no_coordinate_is_infinite(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 5.0, 5.0, 5.0], "g": ["a"] * 8 + ["b"] * 3})
        figure = self.figure(frame, **{VARIABLES: ["x"], GROUP: "g"})
        self.assertEqual(len(self.gids(figure)), 1)
        self.assertTrue(any("Variance not measurable" in text.get_text() for text in figure.axes[0].texts))
        for axes in figure.axes:
            for line in axes.lines:
                self.assertTrue(np.isfinite(np.asarray(line.get_xdata(), dtype=float)).all())
                self.assertTrue(np.isfinite(np.asarray(line.get_ydata(), dtype=float)).all())
            self.assertTrue(all(math.isfinite(v) for v in axes.get_xlim() + axes.get_ylim()))

    def test_nothing_to_draw_still_gives_a_figure(self):
        figure = self.figure(pd.DataFrame({"x": [1.0]}), **{VARIABLES: ["x"]})
        self.assertEqual(self.gids(figure), [])
        self.assertTrue(all(math.isfinite(v) for v in figure.axes[0].get_xlim()))

    def test_extreme_values_are_drawn_with_a_displayed_exponent(self):
        figure = self.figure(pd.DataFrame({"x": np.arange(1.0, 13.0) * 1e200}), **{VARIABLES: ["x"]})
        axes = figure.axes[0]
        self.assertIn("2^", axes.get_xlabel())
        self.assertTrue(all(math.isfinite(v) for v in axes.get_xlim()))

    def test_many_variables_layout(self):
        frame = pd.DataFrame({f"v{i}": np.arange(1.0, 21.0) + i for i in range(9)})
        figure = self.figure(frame, **{VARIABLES: list(frame)})
        self.assertEqual(len(figure.axes), 9)
        self.assertEqual(len(self.gids(figure)), 9)

    def test_svg_keeps_the_gids_and_the_text_is_not_mathtext(self):
        figure = self.figure(pd.DataFrame({"$x$": np.arange(1.0, 13.0), "g": ["$a$"] * 6 + ["b"] * 6}),
                             **{VARIABLES: ["$x$"], GROUP: "g"})
        buffer = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            figure.savefig(buffer, format="svg")
        svg = buffer.getvalue()
        for number in (1, 2):
            self.assertIn(f'id="tolerance-interval-{number}"', svg)
        self.assertIn("$x$", figure.axes[0].get_title())

    def test_inspector_groups_cover_every_drawn_group(self):
        figure = self.figure(**{VARIABLES: ["Signal", "Shifted"], GROUP: "Group"})
        groups = graph_groups(figure.axes[0])
        self.assertEqual([group.name for group in groups], ["Lot A", "Lot B"])
        self.assertTrue(all(len(group.artists) == 2 for group in groups))

    def test_style_updates_recolor_a_group_in_every_panel_without_recalculating(self):
        from analisi.presentation import apply_style, capture_defaults, validated_style
        figure = self.figure(**{VARIABLES: ["Signal", "Shifted"], GROUP: "Group"})
        capture_defaults(figure)
        lines = {name: [line for axes in figure.axes for line in axes.lines if line.get_color() == name]
                 for name in ("#1b6e8f",)}
        self.assertEqual(len(lines["#1b6e8f"]), 2, "Lot A is drawn once per panel")
        style = {"groups": {"tolerance:Lot A": {"color": "#9b4174"}}}
        apply_style(figure, validated_style(style))
        self.assertEqual(sum(line.get_color() == "#9b4174" for axes in figure.axes for line in axes.lines), 2)
        self.assertEqual(sum(line.get_color() == "#c2571a" for axes in figure.axes for line in axes.lines), 2)
        apply_style(figure, validated_style({"groups": {"tolerance:Lot A": {"visible": False}}}))
        self.assertEqual(sum(line.get_visible() for axes in figure.axes for line in axes.lines if line.get_gid()), 2)
        apply_style(figure, validated_style({"title": "Custom title"}))
        self.assertEqual(figure.axes[0].get_title(), "Custom title")
        with self.assertRaises(ValueError):
            validated_style({"groups": {"unknown:Lot A": {"color": "#9b4174"}}})


class Dispatcher(unittest.TestCase):
    def test_registered_in_the_catalog_next_to_descriptive_statistics(self):
        group = GROUPS["Data Exploration and Summary"]
        self.assertEqual(group[group.index("Descriptive statistics") + 1], TOLERANCE)
        self.assertIn(TOLERANCE, METHODS)
        self.assertEqual(METHODS[TOLERANCE][VARIABLES], "Multiple")
        self.assertEqual(METHODS[TOLERANCE][GROUP], "Optional")
        self.assertEqual(METHODS[TOLERANCE][COVERAGE], 90.0)
        self.assertEqual(METHODS[TOLERANCE][CONFIDENCE], 95.0)
        self.assertIs(METHODS[TOLERANCE][SHOW_GRAPH], False)

    def test_analyse_dispatches_and_matches_the_direct_call(self):
        options = {VARIABLES: ["Signal"], GROUP: "Group"}
        pd.testing.assert_frame_equal(analyse(TOLERANCE, LOTS, options).tables[TOLERANCE],
                                      tolerance_intervals(LOTS, options).tables[TOLERANCE])

    def test_defaults_apply_when_an_option_is_missing(self):
        defaults = run(LOTS)
        explicit = run(LOTS, **{DISTRIBUTION: "Normal", SIDES: "Two-sided", COVERAGE: 90.0, CONFIDENCE: 95.0})
        pd.testing.assert_frame_equal(table(defaults), table(explicit))

    def test_legacy_descriptive_statistics_and_normality_are_unchanged(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, 4.0, 8.0, 16.0], "y": [2.0, 3.0, 5.0, 7.0, 11.0]})
        described = analyse("Descriptive statistics", frame, {"Variables": ["x", "y"]})
        self.assertEqual(list(described.tables), ["Summary"])
        self.assertAlmostEqual(float(described.tables["Summary"].loc["x", "Mean"]), 6.2)
        normal = analyse("Normality tests", frame, {"Variables": ["x"]})
        self.assertAlmostEqual(float(normal.tables["Normality"].loc["x", "Shapiro–Wilk W"]),
                               stats.shapiro(frame["x"]).statistic)

    def test_graph_only_when_requested(self):
        self.assertNotIn(TOLERANCE, GRAPH_METHODS)
        result = analyse(TOLERANCE, LOTS, {VARIABLES: ["Signal"], SHOW_GRAPH: True})
        self.assertIsNotNone(result.figure)

    def test_error_messages_are_english_templates_the_dialog_translates(self):
        from analisi import i18n
        pattern = re.compile(r"^tolerance\.error\.")
        keys = [key for key in i18n._IT if pattern.match(key)]
        self.assertTrue(keys)
        for key in keys:
            self.assertIn(key, i18n._EN)


if __name__ == "__main__":
    unittest.main()
