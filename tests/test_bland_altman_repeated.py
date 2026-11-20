"""Bland–Altman for repeated pairs: estimator, edge cases, bootstrap and figures.

The oracles never import the engine's estimator: they recompute the variance components from the rows with the
standard library or with fractions, and the bootstrap check copies the drawn subjects' rows explicitly.
"""
from fractions import Fraction
import json
import math
from pathlib import Path
import pickle
from statistics import NormalDist, mean
import threading
import unittest

import numpy as np
import pandas as pd

from analisi import bland_altman_repeated as bar
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "bland_altman_repeated"
METHOD = bar.METHOD


def options(**changes):
    base = {"Subject": "Subject $", "Occasion": "Occasion |", "First": "First", "Second": "Second",
            "Mode": "Difference", "Coverage": 95, "Confidence intervals": "None"}
    base.update(changes)
    return base


def fixture(name):
    return pd.read_csv(DATA / name)


def oracle(groups, coverage=95.0):
    """Bland and Altman (2007) components from lists of differences, standard library only."""
    n, g = sum(map(len, groups)), len(groups)
    bias = mean(value for group in groups for value in group)
    within = sum(sum((d - mean(group)) ** 2 for d in group) for group in groups) / (n - g)
    between_ms = sum(len(group) * (mean(group) - bias) ** 2 for group in groups) / (g - 1)
    divisor = (n * n - sum(len(group) ** 2 for group in groups)) / ((g - 1) * n)
    raw = (between_ms - within) / divisor
    offset = NormalDist().inv_cdf((1 + coverage / 100) / 2) * math.sqrt(within + max(raw, 0.0))
    return {"bias": bias, "within": within, "between": max(raw, 0.0), "raw": raw,
            "lower": bias - offset, "upper": bias + offset}


def groups_of(frame, subject="Subject", first="First", second="Second", logs=False):
    found = {}
    for _, row in frame.iterrows():
        d = math.log(row[first]) - math.log(row[second]) if logs else row[first] - row[second]
        found.setdefault(row[subject], []).append(d)
    return list(found.values())


def agreement(result):
    return result.tables["Agreement"].iloc[0]


class PublishedFixtures(unittest.TestCase):
    def test_every_case_of_the_package_matches(self):
        cases = json.loads((DATA / "casi.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                tables = analyse(case["method"], fixture(case["csv"]), case["options"]).tables
                for name, expected in case["tables"].items():
                    self.assertEqual(len(tables[name]), expected["count"])
                    for position, row in enumerate(expected["rows"]):
                        for column, value in row.items():
                            self.assertAlmostEqual(tables[name].iloc[position][column], value, delta=1e-9)

    def test_registered_like_the_other_agreement_analyses(self):
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GROUPS["Group Comparison"])
        self.assertEqual(GROUPS["Group Comparison"].index(METHOD), GROUPS["Group Comparison"].index("Bland–Altman") + 1)
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(METHODS["Bland–Altman"]["Method"][0], "Difference")  # legacy recipe untouched


class Estimator(unittest.TestCase):
    def test_unequal_design_against_the_standard_library(self):
        frame = fixture("unequal.csv")
        for mode in ("Difference", "Log ratio"):
            with self.subTest(mode=mode):
                logs = mode == "Log ratio"
                expected = oracle(groups_of(frame, "Subject $", logs=logs))
                row = agreement(analyse(METHOD, frame, options(Mode=mode)))
                shown = math.exp if logs else float
                self.assertAlmostEqual(row["Bias"], shown(expected["bias"]), places=12)
                self.assertAlmostEqual(row["Within-subject variance"], expected["within"], places=12)
                self.assertAlmostEqual(row["Between-subject variance"], expected["between"], places=12)
                self.assertAlmostEqual(row["Lower agreement limit"], shown(expected["lower"]), places=12)
                self.assertAlmostEqual(row["Upper agreement limit"], shown(expected["upper"]), places=12)
                self.assertEqual((row["Pairs"], row["Subjects"], row["df within"], row["df between"]), (10, 4, 6, 3))

    def test_swapping_first_and_second(self):
        frame = fixture("unequal.csv")
        for mode in ("Difference", "Log ratio"):
            with self.subTest(mode=mode):
                direct = agreement(analyse(METHOD, frame, options(Mode=mode)))
                reverse = agreement(analyse(METHOD, frame, options(Mode=mode, First="Second", Second="First")))
                if mode == "Difference":
                    self.assertAlmostEqual(reverse["Bias"], -direct["Bias"], places=12)
                    self.assertAlmostEqual(reverse["Lower agreement limit"], -direct["Upper agreement limit"], places=12)
                    self.assertAlmostEqual(reverse["Upper agreement limit"], -direct["Lower agreement limit"], places=12)
                else:
                    self.assertAlmostEqual(reverse["Bias"], 1 / direct["Bias"], places=12)
                    self.assertAlmostEqual(reverse["Lower agreement limit"], 1 / direct["Upper agreement limit"],
                                           places=12)
                    self.assertAlmostEqual(reverse["Upper agreement limit"], 1 / direct["Lower agreement limit"],
                                           places=12)
                for name in ("Within-subject variance", "Between-subject variance"):
                    self.assertAlmostEqual(reverse[name], direct[name], places=12)

    def test_subject_with_one_pair_contributes_to_bias_and_between(self):
        frame = fixture("unequal.csv")
        result = analyse(METHOD, frame, options())
        subjects = result.tables["Subjects"].set_index("Subject")
        self.assertEqual(subjects.loc["S02", "Pairs"], 1)
        self.assertTrue(math.isnan(subjects.loc["S02", "Within-subject SD"]))
        self.assertEqual(subjects["Pairs"].tolist(), [3, 1, 2, 4])
        self.assertEqual(subjects["First source row"].tolist(), [1, 4, 5, 7])

    def test_negative_between_component_is_set_to_zero_and_reported(self):
        # Subject means almost equal, large within-subject spread: MS between < MS within.
        frame = pd.DataFrame({"Subject": ["a", "a", "b", "b", "c", "c"], "First": [12, 8, 11, 9, 13, 7],
                              "Second": [10] * 6})
        row = agreement(analyse(METHOD, frame, options(Subject="Subject", Occasion=None)))
        expected = oracle(groups_of(frame))
        self.assertLess(expected["raw"], 0)
        self.assertEqual(row["Between-subject variance"], 0.0)
        self.assertAlmostEqual(row["Between-subject variance (unconstrained)"], expected["raw"], places=12)
        self.assertEqual(row["Between-subject estimate"], bar.BOUNDARY)
        self.assertIn("set to 0", row["Note"])
        self.assertAlmostEqual(row["Upper agreement limit"], expected["upper"], places=12)

    def test_zero_dispersion_gives_limits_equal_to_the_bias(self):
        frame = pd.DataFrame({"Subject": list("aabbcc"), "First": [5., 6, 7, 8, 9, 10], "Second": [3., 4, 5, 6, 7, 8]})
        row = agreement(analyse(METHOD, frame, options(Subject="Subject", Occasion=None)))
        self.assertEqual(row["Bias"], 2.0)
        self.assertEqual(row["Within-subject variance"], 0.0)
        self.assertEqual(row["Between-subject variance"], 0.0)
        self.assertEqual(row["Lower agreement limit"], 2.0)
        self.assertEqual(row["Upper agreement limit"], 2.0)

    def test_large_nearly_constant_values_keep_their_variance(self):
        base = 1e9
        tiny = [0.5, 0.25, 0.75, 0.125, 0.375, 0.625, 1.5, 1.25]
        subjects = list("aabbccdd")
        frame = pd.DataFrame({"Subject": subjects, "First": [base + t for t in tiny], "Second": [base] * 8})
        row = agreement(analyse(METHOD, frame, options(Subject="Subject", Occasion=None)))
        groups = {}
        for s, t in zip(subjects, tiny):
            groups.setdefault(s, []).append(Fraction(t))
        within = sum(sum((d - sum(v) / len(v)) ** 2 for d in v) for v in groups.values()) / (8 - 4)
        self.assertAlmostEqual(row["Within-subject variance"], float(within), delta=1e-15)

    def test_coverage_changes_only_the_multiplier(self):
        frame = fixture("balanced.csv")
        row = agreement(analyse(METHOD, frame, options(Coverage=90)))
        expected = oracle(groups_of(frame, "Subject $"), coverage=90)
        self.assertAlmostEqual(row["Upper agreement limit"], expected["upper"], places=12)
        self.assertAlmostEqual(row["z"], NormalDist().inv_cdf(.95), places=12)


class Input(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"Patient ID #": ["P 1", "P 1", "P 2", "P 2", "P 3", "P 3", None, "P 4"],
                             "Visit": [1, 2, 1, 2, 1, 2, None, 1],
                             "Method A (mg/dl)": [10., 11, 12, np.nan, 14, 15, None, 9],
                             "Method B (mg/dl)": [9., 10, 12, 13, 12, 14, None, 8]})

    def recipe(self, **changes):
        return options(**{"Subject": "Patient ID #", "Occasion": "Visit", "First": "Method A (mg/dl)",
                          "Second": "Method B (mg/dl)", **changes})

    def test_incomplete_pairs_are_listed_and_empty_rows_ignored(self):
        result = analyse(METHOD, self.frame(), self.recipe())
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [1, 2, 3, 5, 6, 8])
        excluded = result.tables["Excluded rows"]
        self.assertEqual(excluded.to_dict("records"),
                         [{"Source row": 4, "Subject": "P 2", "Occasion": "2", "Reason": "First is blank or excluded"}])
        self.assertEqual(agreement(result)["Excluded rows"], 1)
        self.assertEqual(result.tables["Pairs"]["Occasion"].tolist(), ["1", "2", "1", "1", "2", "1"])

    def test_without_exclusions_there_is_no_excluded_sheet(self):
        self.assertNotIn("Excluded rows", analyse(METHOD, fixture("balanced.csv"), options()).tables)

    def test_missing_subject_is_an_exclusion_too(self):
        frame = self.frame()
        frame.loc[1, "Patient ID #"] = "  "
        excluded = analyse(METHOD, frame, self.recipe()).tables["Excluded rows"]
        self.assertEqual(excluded.iloc[0]["Reason"], "Subject is blank or excluded")
        self.assertEqual(excluded.iloc[0]["Source row"], 2)

    def test_subject_names_are_literal(self):
        frame = pd.DataFrame({"Subject": ["1", 1, "1", 1.0, "1 ", "1 "], "First": [1., 2, 3, 4, 5, 7],
                              "Second": [0.] * 6})
        result = analyse(METHOD, frame, options(Subject="Subject", Occasion=None))
        subjects = result.tables["Subjects"]
        self.assertEqual(subjects["Subject"].tolist(), ["1", "1", "1 "])  # text "1", number 1, text "1 "
        self.assertEqual(subjects["Pairs"].tolist(), [2, 2, 2])

    def test_text_and_infinite_values_name_field_and_row(self):
        for bad in ("abc", np.inf):
            frame = self.frame().astype({"Method B (mg/dl)": object})
            frame.loc[4, "Method B (mg/dl)"] = bad
            with self.subTest(bad=bad), self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, self.recipe())
            self.assertEqual(raised.exception.field, "Second")
            self.assertIn("row 5", str(raised.exception))

    def test_log_ratio_rejects_non_positive_values(self):
        frame = self.frame()
        frame.loc[2, "Method A (mg/dl)"] = 0.0
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, self.recipe(Mode="Log ratio"))
        self.assertEqual(raised.exception.field, "First")
        self.assertIn("row 3", str(raised.exception))

    def test_duplicate_subject_and_occasion(self):
        frame = self.frame()
        frame.loc[1, "Visit"] = 1
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, self.recipe())
        self.assertEqual(raised.exception.field, "Occasion")
        self.assertIn("rows 1 and 2", str(raised.exception))
        # Without the occasion the same rows are two repeated pairs.
        self.assertEqual(agreement(analyse(METHOD, frame, self.recipe(Occasion=None)))["Pairs"], 6)

    def test_duplicate_of_an_excluded_pair_is_allowed(self):
        frame = self.frame()
        frame.loc[3, "Visit"] = 1  # row 4 is incomplete, so subject P 2 still has one pair at visit 1
        self.assertEqual(agreement(analyse(METHOD, frame, self.recipe()))["Pairs"], 6)

    def test_each_subject_with_one_pair_cannot_identify_the_within_variance(self):
        frame = pd.DataFrame({"Subject": list("abcd"), "First": [1., 2, 3, 5], "Second": [0.] * 4})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, options(Subject="Subject", Occasion=None))
        self.assertEqual(raised.exception.field, "Subject")
        self.assertIn("No subject has two complete pairs", str(raised.exception))

    def test_at_least_three_subjects(self):
        frame = pd.DataFrame({"Subject": list("aabb"), "First": [1., 2, 3, 5], "Second": [0.] * 4})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, options(Subject="Subject", Occasion=None))
        self.assertIn("At least 3 subjects", str(raised.exception))

    def test_recipe_checks_name_their_field(self):
        frame = fixture("balanced.csv")
        cases = [({"Second": "First"}, "Second"), ({"Occasion": "First"}, "Occasion"),
                 ({"Mode": "Ratio"}, "Mode"), ({"Coverage": 100}, "Coverage"), ({"Coverage": True}, "Coverage"),
                 ({"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 198}, "Bootstrap replicates"),
                 ({"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 20001},
                  "Bootstrap replicates"),
                 ({"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 500.0},
                  "Bootstrap replicates"),
                 ({"Confidence intervals": "Subject bootstrap", "Seed": 2**32}, "Seed"),
                 ({"Confidence intervals": "Subject bootstrap", "Confidence level (%)": 0}, "Confidence level (%)"),
                 ({"Graph": "Other"}, "Graph"), ({"Subject": "Missing"}, "Subject")]
        for change, field in cases:
            with self.subTest(change=change), self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, options(**change))
            self.assertEqual(raised.exception.field, field)

    def test_hidden_bootstrap_fields_are_not_validated(self):
        result = analyse(METHOD, fixture("balanced.csv"), options(**{"Bootstrap replicates": -1, "Seed": "x"}))
        self.assertEqual(agreement(result)["Interval status"], bar.NOT_REQUESTED)

    def test_canonical_recipe_defaults(self):
        self.assertEqual(bar.OPTIONS["Mode"][0], "Difference")
        self.assertEqual(bar.OPTIONS["Confidence intervals"][0], "None")
        self.assertEqual(bar.OPTIONS["Coverage"], 95.0)
        recipe = bar.normalized_options(options(**{"Confidence intervals": "Subject bootstrap",
                                                   "Bootstrap replicates": "999", "Seed": "4294967295",
                                                   "Coverage": "90,5"}))
        self.assertEqual((recipe["Bootstrap replicates"], recipe["Seed"], recipe["Coverage"]), (999, 2**32 - 1, 90.5))
        self.assertNotIn("Seed", bar.normalized_options(options(Seed=3)))


class Ratios(unittest.TestCase):
    def test_limits_outside_the_ratio_range_stay_empty(self):
        frame = pd.DataFrame({"Subject": list("aabbcc"),
                              "First": [1e100, 1e-100, 1e100, 1e-100, 1e100, 1e-100], "Second": [1.] * 6})
        row = agreement(analyse(METHOD, frame, options(Subject="Subject", Occasion=None, Mode="Log ratio",
                                                       Coverage=99.9)))
        self.assertTrue(math.isnan(row["Upper agreement limit"]))
        self.assertTrue(math.isnan(row["Lower agreement limit"]))
        self.assertTrue(np.isfinite(row["Upper limit (log)"]) and row["Upper limit (log)"] > 709)
        self.assertIn("cannot be represented", row["Note"])
        self.assertAlmostEqual(row["Bias"], 1.0)


class Bootstrap(unittest.TestCase):
    def recipe(self, **changes):
        return options(**{"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 499, "Seed": 11,
                          **changes})

    def test_replicates_match_an_explicit_copy_of_the_rows(self):
        frame = fixture("unequal.csv")
        for mode in ("Difference", "Log ratio"):
            with self.subTest(mode=mode):
                plan = bar.prepare(frame, self.recipe(Mode=mode))
                replicates = bar.bootstrap(plan, processes=1)
                rng = np.random.Generator(np.random.PCG64(11))
                subjects = list(dict.fromkeys(frame["Subject $"]))
                for number in range(plan.settings.replicates):
                    drawn = rng.integers(0, len(subjects), size=len(subjects))
                    copies = [frame[frame["Subject $"] == subjects[i]].assign(**{"Subject $": f"copy {k}"})
                              for k, i in enumerate(drawn)]
                    groups = groups_of(pd.concat(copies), "Subject $", logs=mode == "Log ratio")
                    if sum(map(len, groups)) == len(groups):
                        self.assertTrue(np.isnan(replicates[number]).all())
                        continue
                    expected = oracle(groups)
                    np.testing.assert_allclose(replicates[number],
                                               [expected["bias"], expected["lower"], expected["upper"]],
                                               rtol=1e-12, atol=1e-12)

    def test_percentiles_counts_and_metadata(self):
        frame = fixture("unequal.csv")
        result = analyse(METHOD, frame, self.recipe())
        row = agreement(result)
        plan = bar.prepare(frame, self.recipe())
        replicates = bar.bootstrap(plan, processes=1)
        valid = np.isfinite(replicates).all(axis=1)
        low, high = np.quantile(replicates[valid, 0], [.025, .975], method="linear")
        self.assertAlmostEqual(row["Bias CI low"], low, places=12)
        self.assertAlmostEqual(row["Bias CI high"], high, places=12)
        self.assertEqual(row["Bootstrap valid"], int(valid.sum()))
        self.assertEqual(row["Interval status"], bar.INTERVAL_OK)
        self.assertEqual(row["Seed"], 11)
        self.assertLess(row["Lower limit CI low"], row["Lower limit CI high"])

    def test_same_seed_same_result_and_order_independent_of_blocks(self):
        frame = fixture("balanced.csv")
        plan = bar.prepare(frame, self.recipe(**{"Bootstrap replicates": 1000}))
        serial = bar.bootstrap(plan, processes=1)
        np.testing.assert_array_equal(serial, bar.bootstrap(plan, processes=1))
        # Splitting into blocks (as the pool does) restores each block's exact generator state.
        jobs, rng = [], np.random.Generator(np.random.PCG64(11))
        for size in (1, 333, 256, 410):
            jobs.append(bar._replicate_block(plan.sizes, plan.means, plan.squares, plan.reference,
                                             rng.bit_generator.state, size, bar.critical(95), None))
            for _ in range(size):
                rng.integers(0, plan.g, size=plan.g)
        np.testing.assert_array_equal(np.concatenate(jobs), serial)

    def test_too_few_valid_replicates_leave_the_intervals_empty(self):
        # Seven single-pair subjects and one subject with two pairs: most replicates miss the repeated subject.
        frame = pd.DataFrame({"Subject": ["a", "a", *"bcdefgh"], "First": [1., 2, 3, 4, 2, 6, 1, 3, 5],
                              "Second": [0.] * 9})
        row = agreement(analyse(METHOD, frame, options(Subject="Subject", Occasion=None,
                                                       **{"Confidence intervals": "Subject bootstrap",
                                                          "Bootstrap replicates": 400, "Seed": 1})))
        self.assertEqual(row["Interval status"], bar.TOO_FEW_VALID)
        self.assertLess(row["Bootstrap valid"], 360)
        self.assertTrue(math.isnan(row["Bias CI low"]))
        self.assertTrue(np.isfinite(row["Bias"]))
        self.assertIn("left empty", row["Note"])
        self.assertTrue(row["Invalid replicates"][0].isdigit())

    def test_cancel_before_and_during_the_bootstrap(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(bar.BlandAltmanRepeatedCancelled):
            analyse(METHOD, fixture("balanced.csv"), self.recipe(), cancel=cancel)
        self.assertTrue(bar.cancellable(METHOD, self.recipe()))
        self.assertFalse(bar.cancellable(METHOD, options()))


class Figures(unittest.TestCase):
    def test_pairs_view_is_native_and_editable(self):
        result = analyse(METHOD, fixture("unequal.csv"), options(**{"Confidence intervals": "Subject bootstrap",
                                                                     "Bootstrap replicates": 199}))
        axes = result.figure.axes[0]
        gids = {artist.get_gid() for artist in axes.get_children() if artist.get_gid()}
        self.assertTrue({"ba-repeated:points", "ba-repeated:bias", "ba-repeated:lower", "ba-repeated:upper",
                         "ba-repeated:neutral", "ba-repeated:bias-band"} <= gids)
        self.assertIn("10 pairs, 4 subjects", axes.get_title())
        self.assertEqual(axes.get_yscale(), "linear")

    def test_log_ratio_view_uses_a_ratio_axis(self):
        result = analyse(METHOD, fixture("unequal.csv"), options(Mode="Log ratio"))
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_yscale(), "log")
        neutral = next(a for a in axes.get_lines() if a.get_gid() == "ba-repeated:neutral")
        self.assertEqual(neutral.get_ydata()[0], 1.0)

    def test_subject_diagnostics(self):
        result = analyse(METHOD, fixture("unequal.csv"), options(Graph="Subject diagnostics"))
        axes = result.figure.axes[0]
        points = next(a for a in axes.collections if a.get_gid() == "ba-repeated:subject-points")
        self.assertEqual(len(points.get_offsets()), 3)  # S02 has one pair
        self.assertTrue(any("one pair" in text.get_text() for text in result.figure.legends[0].get_texts()))

    def test_result_survives_pickling(self):
        result = analyse(METHOD, fixture("unequal.csv"), options(Mode="Log ratio"))
        copy = pickle.loads(pickle.dumps(result))
        pd.testing.assert_frame_equal(copy.tables["Agreement"], result.tables["Agreement"])


if __name__ == "__main__":
    unittest.main()
