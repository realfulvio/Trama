"""Cohen's kappa engine: categories, orders, the exact statistic, the bootstrap, limits and the sheets."""
from fractions import Fraction
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from statsmodels.stats.inter_rater import cohens_kappa as statsmodels_kappa

from analisi import cohen_kappa as engine
from analisi.cohen_kappa import (AGREEMENT, AGREEMENT_COLUMNS, BOOTSTRAP, COUNTS, EXPECTED, FIRST, INTERVAL,
                                 KappaCancelled, LEVEL, LINEAR, ORDER, QUADRATIC, RESAMPLES, SECOND, SEED,
                                 SETTINGS, SHOW_GRAPH, TOTALS, UNWEIGHTED, WEIGHTING)
from analisi.data import Dataset
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "cohen_kappa"
RATINGS = pd.read_csv(DATA / "ratings.csv")
EXPECTED_JSON = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
LEVELS = ["Mild", "Moderate $", "Severe"]
COUNT_MATRIX = [[8, 2, 1], [1, 7, 2], [0, 3, 6]]
BASE = {FIRST: "Rater A", SECOND: "Rater B", ORDER: LEVELS}
STATSMODELS_WEIGHTS = {UNWEIGHTED: None, LINEAR: "linear", QUADRATIC: "quadratic"}


def run(frame=RATINGS, **changes):
    tables, plan, point = engine.run(frame, {**BASE, **changes})
    return tables, plan, point


def agreement(frame=RATINGS, **changes):
    return run(frame, **changes)[0][AGREEMENT].iloc[0]


def pairs(first, second, a="A", b="B"):
    return pd.DataFrame({a: first, b: second})


def raises(test, field, call, fragment=None):
    with test.assertRaises(FieldError) as raised:
        call()
    test.assertEqual(raised.exception.field, field, str(raised.exception))
    if fragment is not None:
        test.assertIn(fragment, str(raised.exception))
    return str(raised.exception)


class FixtureTests(unittest.TestCase):
    def test_the_three_weightings_give_the_exact_fractions(self):
        for weighting in (UNWEIGHTED, LINEAR, QUADRATIC):
            row = agreement(**{WEIGHTING: weighting})
            exact = Fraction(EXPECTED_JSON["exact_scores"][weighting])
            self.assertEqual(row["Kappa"], float(exact), weighting)
            self.assertEqual(row["Kappa"], EXPECTED_JSON["scores"][weighting], weighting)
            self.assertEqual(Fraction(row["Kappa"]).limit_denominator(1000), exact)
            self.assertEqual((row["Complete pairs"], row["Incomplete pairs"]), (30, 2))
            self.assertEqual(row["Observed agreement"], 0.7)
            self.assertEqual(row["Status"], "OK")
            self.assertTrue(np.isnan(row["CI lower"]) and np.isnan(row["CI upper"]))
            self.assertTrue(np.isnan(row["Valid resamples"]))

    def test_statsmodels_agrees_on_the_same_order(self):
        tables, plan, _ = run()
        for weighting, wt in STATSMODELS_WEIGHTS.items():
            ours = agreement(**{WEIGHTING: weighting})["Kappa"]
            reference = statsmodels_kappa(plan.counts, wt=wt).kappa
            self.assertAlmostEqual(ours, reference, places=12, msg=weighting)

    def test_statsmodels_agrees_on_a_larger_table(self):
        rng = np.random.default_rng(11)
        first = rng.integers(0, 6, 400)
        second = np.clip(first + rng.integers(-2, 3, 400), 0, 5)
        frame = pairs(first, second)
        for weighting, wt in STATSMODELS_WEIGHTS.items():
            tables, plan, point = engine.run(frame, {FIRST: "A", SECOND: "B", WEIGHTING: weighting,
                                                     ORDER: [0, 1, 2, 3, 4, 5]})
            self.assertEqual(plan.labels, ["0", "1", "2", "3", "4", "5"])
            self.assertAlmostEqual(point, statsmodels_kappa(plan.counts, wt=wt).kappa, places=12, msg=weighting)

    def test_sheets_orientation_names_and_totals(self):
        tables, plan, _ = run()
        self.assertEqual(list(tables), [AGREEMENT, COUNTS, EXPECTED, TOTALS, SETTINGS])
        self.assertEqual(list(tables[AGREEMENT].columns), AGREEMENT_COLUMNS)
        self.assertEqual(list(tables[AGREEMENT].index), ["Rater A × Rater B"])
        counts = tables[COUNTS]
        self.assertEqual((counts.index.name, counts.columns.name), ("Rater A", "Rater B"))
        self.assertEqual(list(counts.index), LEVELS)
        self.assertEqual(list(counts.columns), LEVELS)
        self.assertEqual(counts.to_numpy().tolist(), COUNT_MATRIX)
        expected = tables[EXPECTED].to_numpy()
        matrix = np.array(COUNT_MATRIX)
        np.testing.assert_allclose(expected, np.outer(matrix.sum(1), matrix.sum(0)) / 30)
        self.assertAlmostEqual(expected.sum(), 30.0, places=12)
        totals = tables[TOTALS]
        self.assertEqual(totals.index.name, "Category")
        self.assertEqual(totals["Rater A"].tolist(), [11, 10, 9])
        self.assertEqual(totals["Rater B"].tolist(), [9, 12, 9])

    def test_the_settings_sheet_documents_the_run(self):
        tables, _, _ = run(**{WEIGHTING: QUADRATIC, INTERVAL: BOOTSTRAP, RESAMPLES: 199, SEED: 2 ** 64 - 1})
        settings = tables[SETTINGS]["Value"]
        self.assertEqual(settings.index.name, "Setting")
        self.assertEqual(settings["Matrix orientation"], "Rows are the first rating, columns the second rating")
        self.assertEqual([settings[f"Category {i}"] for i in (1, 2, 3)], LEVELS)
        self.assertEqual(settings["Category order"], "Explicit")
        self.assertEqual(settings["Seed"], 2 ** 64 - 1)
        self.assertEqual(settings["Resamples"], 199)
        self.assertIn("Fleiss", settings["Not included"])
        plain = run(**{ORDER: []})[0][SETTINGS]["Value"]
        self.assertTrue(plain["Category order"].startswith("Automatic"))
        self.assertNotIn("Seed", plain.index)

    def test_the_worksheet_is_not_changed(self):
        frame = RATINGS.copy(deep=True)
        before = frame.copy(deep=True)
        for weighting in (UNWEIGHTED, QUADRATIC):
            engine.run(frame, {**BASE, WEIGHTING: weighting, INTERVAL: BOOTSTRAP, RESAMPLES: 199})
        pd.testing.assert_frame_equal(frame, before)

    def test_swapping_the_columns_transposes_the_matrix(self):
        for weighting in (UNWEIGHTED, LINEAR, QUADRATIC):
            left, _, a = run(**{WEIGHTING: weighting})
            right, _, b = run(**{WEIGHTING: weighting, FIRST: "Rater B", SECOND: "Rater A"})
            self.assertEqual(a, b, weighting)
            self.assertEqual(left[COUNTS].to_numpy().T.tolist(), right[COUNTS].to_numpy().tolist())
            self.assertEqual(right[COUNTS].index.name, "Rater B")
            self.assertEqual(left[TOTALS]["Rater A"].tolist(), right[TOTALS]["Rater A"].tolist())
            self.assertEqual(list(right[AGREEMENT].index), ["Rater B × Rater A"])


class MissingAndExcludedTests(unittest.TestCase):
    def test_a_pair_with_a_missing_rating_is_left_out_once(self):
        frame = pairs(["x", None, np.nan, "", "  ", "y", None, "x", "y"],
                      ["x", "y", "x", "y", "x", None, None, "y", "y"])
        row = agreement(frame, **{FIRST: "A", SECOND: "B", ORDER: []})
        self.assertEqual((row["Complete pairs"], row["Incomplete pairs"]), (3, 6))

    def test_excluded_cells_of_integer_columns_become_missing(self):
        raw = pd.DataFrame({"A": [1, 2, 3, 1, 2, 3, 1], "B": [1, 2, 3, 2, 2, 3, 9]})
        data = Dataset(raw, excluded={(6, 1), (0, 0)})
        masked = data.frame(mask_excluded=True)
        self.assertEqual(str(masked["A"].dtype), "Int64")
        tables, plan, point = engine.run(masked, {FIRST: "A", SECOND: "B"})
        self.assertEqual((plan.complete, plan.incomplete), (5, 2))
        self.assertEqual(plan.labels, ["1", "2", "3"])
        self.assertNotIn("9", plan.labels)
        pd.testing.assert_frame_equal(data.raw, raw)

    def test_excluded_logical_and_text_cells(self):
        # Logical values in an object column (a bool column cannot hold an excluded cell in Dataset.frame).
        raw = pd.DataFrame({"A": [True, False, True, False, True], "B": ["T", "F", "T", "T", "F"]}, dtype=object)
        flags = pd.Series([True, False, True, True, False], dtype=object)
        masked = Dataset(raw.assign(B=flags), excluded={(4, 1)}).frame(mask_excluded=True)
        _, plan, _ = engine.run(masked, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["False", "True"])
        self.assertEqual((plan.complete, plan.incomplete), (4, 1))
        masked = Dataset(raw, excluded={(0, 0), (1, 1)}).frame(mask_excluded=True)
        tables, plan, _ = engine.run(masked.assign(A=masked["A"].map({True: "T", False: "F"}, na_action="ignore")),
                                     {FIRST: "A", SECOND: "B"})
        self.assertEqual((plan.complete, plan.incomplete), (3, 2))

    def test_a_masked_float_column_and_pandas_na(self):
        frame = pairs(pd.array([1.0, None, 2.0, 2.0], dtype="Float64"), pd.array([1, 1, pd.NA, 2], dtype="Int64"))
        _, plan, _ = engine.run(frame, {FIRST: "A", SECOND: "B"})
        self.assertEqual((plan.complete, plan.incomplete, plan.labels), (2, 2, ["1", "2"]))

    def test_too_few_complete_pairs(self):
        frame = pairs(["x", None, "y"], ["x", "y", None])
        message = raises(self, FIRST, lambda: engine.check_options(frame, {FIRST: "A", SECOND: "B"}))
        self.assertEqual(message, "Cohen's kappa needs at least 2 complete pairs; found 1.")


class LabelTests(unittest.TestCase):
    def test_text_and_numbers_stay_apart(self):
        frame = pairs(["01", 1, 1.0, "01", 2.5], [1, "01", 1, "01", 1e20])
        _, plan, _ = engine.run(frame, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["1", "2.5", "1e+20", "01"])
        self.assertEqual(plan.counts.sum(), 5)

    def test_whole_numbers_and_negative_zero_are_written_without_decimals(self):
        frame = pairs([1.0, 2.0, -0.0, 0.0, 3.25], [1, 2, 0, -0.0, 3.25])
        _, plan, point = engine.run(frame, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["0", "1", "2", "3.25"])
        self.assertEqual(point, 1.0)

    def test_the_automatic_order(self):
        frame = pairs(["b", "A", True, 10, 2, "a", "B", False], ["B", "a", True, 10, 2, "A", "b", False])
        _, plan, _ = engine.run(frame, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["2", "10", "False", "True", "A", "a", "B", "b"])

    def test_logical_columns(self):
        frame = pairs([True, True, False, False], [True, False, False, False])
        _, plan, _ = engine.run(frame, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["False", "True"])
        self.assertEqual(plan.counts.tolist(), [[2, 0], [1, 1]])
        only_true = pairs([True, True], [True, True])
        _, plan, point = engine.run(only_true, {FIRST: "A", SECOND: "B"})
        self.assertEqual(plan.labels, ["True"])
        self.assertTrue(np.isnan(point))

    def test_a_text_and_a_number_with_the_same_label_are_refused(self):
        message = raises(self, SECOND, lambda: engine.check_options(pairs([1, 2, 1], ["1", 2, 1]),
                                                                      {FIRST: "A", SECOND: "B"}))
        self.assertEqual(message, 'The text "1" and a number are different categories with the same label. '
                                  'Use one type in both columns or change the text.')
        raises(self, FIRST, lambda: engine.check_options(pairs([1, "1", 2], [1, 2, 2]), {FIRST: "A", SECOND: "B"}))
        message = raises(self, SECOND, lambda: engine.check_options(pairs([True, False], ["True", False]),
                                                                      {FIRST: "A", SECOND: "B"}))
        self.assertIn('The text "True" and a logical value', message)

    def test_values_that_are_not_categories(self):
        message = raises(self, FIRST, lambda: engine.check_options(pairs([1.0, np.inf, 2.0], [1.0, 2.0, 2.0]),
                                                                     {FIRST: "A", SECOND: "B"}))
        self.assertEqual(message, 'Source row 2: the value inf in column "A" is not a finite number.')
        message = raises(self, SECOND, lambda: engine.check_options(pairs(["x", "y", "x"], ["x", -np.inf, "y"]),
                                                                      {FIRST: "A", SECOND: "B"}))
        self.assertEqual(message, 'Source row 2: the value -inf in column "B" is not a finite number.')
        message = raises(self, SECOND, lambda: engine.check_options(pairs(["x", "y"], ["x", [1, 2]]),
                                                                      {FIRST: "A", SECOND: "B"}))
        self.assertEqual(message, 'Source row 2: the value [1, 2] in column "B" must be text or a finite number.')
        raises(self, FIRST, lambda: engine.check_options(pairs(np.array([1 + 1j, 2]), [1, 2]),
                                                          {FIRST: "A", SECOND: "B"}), "must be text or a finite")

    def test_worksheet_text_stays_literal(self):
        frame = pairs(["$x$", "{a}", "$x$"], ["{a}", "{a}", "$x$"], a="Rater {1}", b="Rater $2$")
        tables, plan, _ = engine.run(frame, {FIRST: "Rater {1}", SECOND: "Rater $2$"})
        self.assertEqual(plan.labels, ["$x$", "{a}"])
        self.assertEqual(list(tables[AGREEMENT].index), ["Rater {1} × Rater $2$"])


class OrderTests(unittest.TestCase):
    def test_an_explicit_order_reorders_both_axes(self):
        order = ["Severe", "Mild", "Moderate $"]
        tables, plan, point = run(**{ORDER: order})
        self.assertEqual(list(tables[COUNTS].index), order)
        self.assertEqual(list(tables[COUNTS].columns), order)
        self.assertEqual(tables[COUNTS].to_numpy().tolist(), [[6, 0, 3], [1, 8, 2], [2, 1, 7]])
        self.assertEqual(point, agreement(**{ORDER: []})["Kappa"])
        self.assertTrue(plan.explicit)

    def test_weighted_kappa_depends_on_the_order(self):
        straight = agreement(**{WEIGHTING: LINEAR})["Kappa"]
        reversed_ = agreement(**{WEIGHTING: LINEAR, ORDER: LEVELS[::-1]})["Kappa"]
        shuffled = agreement(**{WEIGHTING: LINEAR, ORDER: ["Moderate $", "Mild", "Severe"]})["Kappa"]
        self.assertEqual(straight, reversed_)
        self.assertNotEqual(straight, shuffled)

    def test_weighted_kappa_needs_an_order(self):
        for weighting in (LINEAR, QUADRATIC):
            message = raises(self, ORDER, lambda: run(**{WEIGHTING: weighting, ORDER: []}))
            self.assertEqual(message, f"Category order: {weighting} weights need an order that lists every "
                                      "category once.")

    def test_an_order_saved_in_a_recipe_that_no_longer_matches_the_data(self):
        recipe = {**BASE, WEIGHTING: QUADRATIC}
        engine.check_options(RATINGS, recipe)
        grown = pd.concat([RATINGS, pd.DataFrame({"Rater A": ["Critical"], "Rater B": ["Severe"]})])
        message = raises(self, ORDER, lambda: engine.check_options(grown, recipe))
        self.assertEqual(message, 'Category order: list every category once; missing "Critical".')
        shrunk = RATINGS[RATINGS["Rater A"] != "Severe"].replace("Severe", "Mild")
        message = raises(self, ORDER, lambda: engine.check_options(shrunk, recipe))
        self.assertEqual(message, 'Category order: "Severe" is not a category of the complete pairs.')
        message = raises(self, ORDER, lambda: run(**{ORDER: ["Mild", "Mild", "Severe"]}))
        self.assertEqual(message, 'Category order: "Mild" appears more than once.')

    def test_numbers_and_logical_values_in_an_order(self):
        frame = pairs([1, 2, 3, 2.5], [1, 2, 3, 2.5])
        _, plan, _ = engine.run(frame, {FIRST: "A", SECOND: "B", WEIGHTING: LINEAR, ORDER: [3, 2.5, "2", 1.0]})
        self.assertEqual(plan.labels, ["3", "2.5", "2", "1"])
        _, plan, _ = engine.run(pairs([True, False], [False, True]), {FIRST: "A", SECOND: "B", ORDER: [True, False]})
        self.assertEqual(plan.labels, ["True", "False"])

    def test_an_order_that_is_not_a_list(self):
        self.assertEqual(raises(self, ORDER, lambda: run(**{ORDER: "Mild, Severe"})),
                         "Category order: enter a list of categories.")
        self.assertEqual(raises(self, ORDER, lambda: run(**{ORDER: ["Mild", None]})),
                         "Category order: item 2 must be a category name.")
        raises(self, ORDER, lambda: run(**{ORDER: ["Mild", float("nan")]}))
        self.assertEqual(engine.read_order(None), [])

    def test_missing_names_are_listed_up_to_six(self):
        frame = pairs(list("abcdefghij"), list("abcdefghij"))
        message = raises(self, ORDER, lambda: engine.check_options(frame, {FIRST: "A", SECOND: "B", ORDER: ["a"]}))
        self.assertTrue(message.endswith('missing "b", "c", "d", "e", "f", "g" and 3 more.'), message)


class StatisticTests(unittest.TestCase):
    def test_a_single_category_leaves_kappa_undefined(self):
        frame = pairs(["A"] * 4, ["A"] * 4)
        for interval in ("None", BOOTSTRAP):
            row = agreement(frame, **{FIRST: "A", SECOND: "B", ORDER: [], INTERVAL: interval, RESAMPLES: 199})
            self.assertEqual(row["Observed agreement"], 1.0)
            self.assertTrue(np.isnan(row["Kappa"]))
            self.assertEqual(row["Status"], "Undefined kappa")
            self.assertTrue(np.isnan(row["Valid resamples"]))

    def test_one_rater_with_a_single_category_gives_zero(self):
        frame = pairs(["A"] * 4, ["A", "B", "A", "B"])
        self.assertEqual(agreement(frame, **{FIRST: "A", SECOND: "B", ORDER: []})["Kappa"], 0.0)

    def test_systematic_disagreement_is_negative(self):
        frame = pairs(["x", "y"] * 5, ["y", "x"] * 5)
        row = agreement(frame, **{FIRST: "A", SECOND: "B", ORDER: []})
        self.assertEqual((row["Observed agreement"], row["Kappa"]), (0.0, -1.0))
        three = pairs(["a", "b", "c", "a", "b", "c"], ["b", "c", "a", "c", "a", "b"])
        for weighting in (UNWEIGHTED, LINEAR, QUADRATIC):
            point = agreement(three, **{FIRST: "A", SECOND: "B", ORDER: ["a", "b", "c"], WEIGHTING: weighting})["Kappa"]
            self.assertLess(point, 0, weighting)

    def test_the_point_value_is_the_rounded_exact_quotient(self):
        rng = np.random.default_rng(3)
        for _ in range(50):
            size = int(rng.integers(2, 7))
            counts = rng.integers(0, 40, (size, size))
            counts[0, 0] += 1
            for weighting in (UNWEIGHTED, LINEAR, QUADRATIC):
                weights = engine.costs(size, weighting)
                n = int(counts.sum())
                observed = Fraction(int((weights * counts).sum()), n)
                expected = Fraction(int(counts.sum(1) @ weights @ counts.sum(0)), n * n)
                exact = 1 - observed / expected if expected else None
                value = engine.kappa(counts, weights)
                if exact is None:
                    self.assertTrue(np.isnan(value))
                else:
                    self.assertEqual(value, float(exact))

    def test_costs(self):
        self.assertEqual(engine.costs(3, UNWEIGHTED).tolist(), [[0, 1, 1], [1, 0, 1], [1, 1, 0]])
        self.assertEqual(engine.costs(3, LINEAR).tolist(), [[0, 1, 2], [1, 0, 1], [2, 1, 0]])
        self.assertEqual(engine.costs(3, QUADRATIC).tolist(), [[0, 1, 4], [1, 0, 1], [4, 1, 0]])


class BootstrapTests(unittest.TestCase):
    def test_the_oracle_interval(self):
        row = agreement(**{WEIGHTING: QUADRATIC, INTERVAL: BOOTSTRAP, RESAMPLES: 199, SEED: 2701})
        truth = EXPECTED_JSON["bootstrap"]
        self.assertEqual(int(row["Valid resamples"]), truth["Valid resamples"])
        self.assertEqual(row["CI lower"], truth["CI lower"])
        self.assertEqual(row["CI upper"], truth["CI upper"])
        self.assertEqual(row["Status"], "OK")

    def test_the_rare_table_has_too_few_valid_resamples(self):
        frame = pairs(["A"] * 20 + ["B"], ["A"] * 20 + ["B"])
        row = agreement(frame, **{FIRST: "A", SECOND: "B", ORDER: ["A", "B"], INTERVAL: BOOTSTRAP,
                                  RESAMPLES: 199, SEED: 2701})
        self.assertEqual(row["Kappa"], 1.0)
        self.assertEqual(int(row["Valid resamples"]), EXPECTED_JSON["rare"]["Valid resamples"])
        self.assertTrue(np.isnan(row["CI lower"]) and np.isnan(row["CI upper"]))
        self.assertEqual(row["Status"], "Too few valid resamples")

    def test_the_same_seed_repeats_the_interval_and_the_block_size_does_not_matter(self):
        options = {WEIGHTING: LINEAR, INTERVAL: BOOTSTRAP, RESAMPLES: 523, SEED: 99}
        first, second = agreement(**options), agreement(**options)
        self.assertEqual((first["CI lower"], first["CI upper"]), (second["CI lower"], second["CI upper"]))
        with patch.object(engine, "BLOCK", 7):
            small = agreement(**options)
        self.assertEqual((first["CI lower"], first["CI upper"]), (small["CI lower"], small["CI upper"]))
        other = agreement(**{**options, SEED: 100})
        self.assertNotEqual((first["CI lower"], first["CI upper"]), (other["CI lower"], other["CI upper"]))

    def test_a_higher_level_gives_a_wider_interval(self):
        options = {WEIGHTING: QUADRATIC, INTERVAL: BOOTSTRAP, RESAMPLES: 999, SEED: 5}
        narrow, wide = agreement(**options, **{LEVEL: 80.0}), agreement(**options, **{LEVEL: 99.0})
        self.assertLess(wide["CI lower"], narrow["CI lower"])
        self.assertGreater(wide["CI upper"], narrow["CI upper"])
        self.assertLessEqual(narrow["CI lower"], narrow["Kappa"])

    def test_cancel_before_and_during_the_bootstrap(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(KappaCancelled):
            engine.run(RATINGS, {**BASE, INTERVAL: BOOTSTRAP, RESAMPLES: 999}, cancel=stop)
        self.assertTrue(issubclass(KappaCancelled, MonteCarloCancelled))

        class Later:
            calls = 0

            def is_set(self):
                self.calls += 1
                return self.calls > 2

        later = Later()
        with self.assertRaises(KappaCancelled):
            engine.run(RATINGS, {**BASE, INTERVAL: BOOTSTRAP, RESAMPLES: 2000}, cancel=later)
        self.assertEqual(later.calls, 3)

    def test_the_dispatcher_passes_the_cancel_request(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(KappaCancelled):
            analyse("Cohen's kappa", RATINGS, {**BASE, INTERVAL: BOOTSTRAP, RESAMPLES: 199}, cancel=stop)
        result = analyse("Cohen's kappa", RATINGS, {**BASE, INTERVAL: BOOTSTRAP, RESAMPLES: 199},
                         cancel=threading.Event())
        self.assertEqual(result.tables[AGREEMENT].iloc[0]["Status"], "OK")

    def test_percentile_interval(self):
        numerators, denominators = np.r_[np.arange(10), [0]], np.r_[np.ones(10, dtype=int), [0]]
        self.assertEqual(engine.percentile_interval(numerators, denominators, 50.0, 11), ((2.25, 6.75), 10))
        self.assertEqual(engine.percentile_interval(numerators, denominators, 50.0, 12), (None, 10))
        self.assertEqual(engine.percentile_interval([0], [0], 95.0, 1), (None, 0))

    def test_the_interpolation_is_exact_where_floats_tie(self):
        # Two different fractions that round to the same float, listed in the wrong exact order.
        third = Fraction(1, 3)
        below = Fraction(float(third)) - Fraction(1, 2 ** 80)
        self.assertEqual(float(third), float(below))
        values = [third, below, Fraction(2, 3)]
        numerators = np.array([value.numerator for value in values], dtype=object)
        denominators = np.array([value.denominator for value in values], dtype=object)
        interval, valid = engine.percentile_interval(numerators, denominators, 50.0, 3)
        self.assertEqual(valid, 3)
        position = Fraction(2) / 4
        self.assertEqual(interval[0], float(below + position * (third - below)))

    def test_the_interval_matches_an_exact_reference(self):
        counts = np.array([[30, 4, 1, 0], [5, 22, 6, 1], [1, 7, 25, 3], [0, 1, 4, 18]])
        for weighting, level in ((UNWEIGHTED, 95.0), (LINEAR, 90.0), (QUADRATIC, 99.0)):
            weights = engine.costs(4, weighting)
            numerators, denominators = engine.bootstrap(counts, weights, 401, 17)
            exact = sorted(Fraction(int(a), int(b)) for a, b in zip(numerators, denominators) if b)
            bounds = []
            for share in ((100 - Fraction(level)) / 200, (100 + Fraction(level)) / 200):
                position = (len(exact) - 1) * share
                low = int(position)
                high = min(low + 1, len(exact) - 1)
                bounds.append(float(exact[low] + (position - low) * (exact[high] - exact[low])))
            interval, valid = engine.percentile_interval(numerators, denominators, level, 401)
            self.assertEqual(valid, len(exact))
            self.assertEqual(interval, tuple(bounds), weighting)
            draws = np.random.Generator(np.random.PCG64(17))
            first = draws.multinomial(int(counts.sum()), counts.ravel() / counts.sum()).reshape(4, 4)
            self.assertEqual(Fraction(int(numerators[0]), int(denominators[0])),
                             Fraction(engine.kappa(first, weights)).limit_denominator(10 ** 9))


class RecipeTests(unittest.TestCase):
    def check(self, **changes):
        return engine.check_options(RATINGS, {**BASE, **changes})

    def test_columns(self):
        self.assertEqual(raises(self, FIRST, lambda: self.check(**{FIRST: None})), "Choose a column for First rating.")
        self.assertEqual(raises(self, SECOND, lambda: self.check(**{SECOND: "Nope"})),
                         'Choose an existing column for Second rating: "Nope" is not in the worksheet.')
        self.assertEqual(raises(self, SECOND, lambda: self.check(**{SECOND: "Rater A"})),
                         "Choose a column different from First rating for Second rating.")
        duplicated = RATINGS.copy()
        duplicated.columns = ["Rater A", "Rater A"]
        self.assertEqual(raises(self, FIRST, lambda: engine.check_options(duplicated, BASE)),
                         "Worksheet column names must be unique.")
        self.assertEqual(raises(self, FIRST, lambda: engine.check_options(RATINGS, "not a dict")),
                         "Choose a column for First rating.")

    def test_choices_and_flags(self):
        raises(self, WEIGHTING, lambda: self.check(**{WEIGHTING: "linear"}), "choose one of the listed options")
        raises(self, INTERVAL, lambda: self.check(**{INTERVAL: "Wald"}))
        self.assertEqual(raises(self, SHOW_GRAPH, lambda: self.check(**{SHOW_GRAPH: "yes"})),
                         "Show graph must be on or off.")
        self.assertTrue(self.check(**{SHOW_GRAPH: np.bool_(False)}).settings.show_graph is False)

    def test_bootstrap_fields_are_read_only_with_the_bootstrap(self):
        plan = self.check(**{LEVEL: "abc", RESAMPLES: -3, SEED: "x"})
        self.assertIsNone(plan.settings.resamples)
        on = {INTERVAL: BOOTSTRAP}
        for value in (0, 100, float("nan"), "95", True):
            raises(self, LEVEL, lambda: self.check(**on, **{LEVEL: value}))
        self.assertEqual(self.check(**on, **{LEVEL: 99.9}).settings.level, 99.9)
        for value in (198, 20_001, 1999.0, True, "1999"):
            self.assertEqual(raises(self, RESAMPLES, lambda: self.check(**on, **{RESAMPLES: value})),
                             "Resamples must be a whole number from 199 to 20,000.")
        self.assertEqual(self.check(**on, **{RESAMPLES: np.int64(20_000)}).settings.resamples, 20_000)
        for value in (-1, 2 ** 64, 1.5, False):
            self.assertEqual(raises(self, SEED, lambda: self.check(**on, **{SEED: value})),
                             f"Seed must be a whole number from 0 to {2 ** 64 - 1}.")
        self.assertEqual(self.check(**on, **{SEED: 2 ** 64 - 1}).settings.seed, 2 ** 64 - 1)

    def test_missing_keys_take_their_defaults(self):
        plan = engine.check_options(RATINGS, {FIRST: "Rater A", SECOND: "Rater B"})
        settings = plan.settings
        self.assertEqual((settings.weighting, settings.interval, settings.show_graph), (UNWEIGHTED, "None", True))
        self.assertEqual(plan.labels, LEVELS)
        self.assertFalse(plan.explicit)

    def test_pair_and_category_budgets(self):
        many = pairs(np.zeros(50_001), np.zeros(50_001))
        self.assertEqual(raises(self, FIRST, lambda: engine.check_options(many, {FIRST: "A", SECOND: "B"})),
                         "Cohen's kappa reads up to 50,000 complete pairs; found 50,001.")
        limit = pairs(np.arange(50_000) % 20, np.arange(50_000) % 20)
        self.assertEqual(engine.check_options(limit, {FIRST: "A", SECOND: "B"}).size, 20)
        wide = pairs(np.arange(21), np.arange(21))
        self.assertEqual(raises(self, FIRST, lambda: engine.check_options(wide, {FIRST: "A", SECOND: "B"})),
                         "Cohen's kappa supports up to 20 categories; the complete pairs have 21.")
        raises(self, FIRST, lambda: engine.observed_categories(many, "A", "B"), "50,000")

    def test_observed_categories_follow_the_automatic_order(self):
        self.assertEqual(engine.observed_categories(RATINGS, "Rater A", "Rater B"), LEVELS)
        raises(self, SECOND, lambda: engine.observed_categories(RATINGS, "Rater A", "Rater A"))


class PairedComparisonTests(unittest.TestCase):
    def test_the_paired_t_test_is_unchanged_and_matches_the_same_rows(self):
        table = pd.DataFrame({"A": [5, 8, None, 10], "B": [2, 7, 3, 6]})
        result = analyse("Paired t-test (columns)", table, {"First": "A", "Second": "B"}).tables["t-test"]["Value"]
        self.assertEqual([result["N first"], result["df"]], [3, 2])
        self.assertAlmostEqual(result["t"], 8 / np.sqrt(7))
        kappa = analyse("Cohen's kappa", table, {FIRST: "A", SECOND: "B"}).tables[AGREEMENT].iloc[0]
        self.assertEqual((kappa["Complete pairs"], kappa["Incomplete pairs"]), (3, 1))

    def test_an_excluded_cell_drops_the_same_pair_in_both_analyses(self):
        raw = pd.DataFrame({"A": [5, 8, 4, 10, 7], "B": [2, 7, 3, 6, 7]})
        masked = Dataset(raw, excluded={(2, 0)}).frame(mask_excluded=True)
        result = analyse("Paired t-test (columns)", masked, {"First": "A", "Second": "B"}).tables["t-test"]["Value"]
        kappa = analyse("Cohen's kappa", masked, {FIRST: "A", SECOND: "B"}).tables[AGREEMENT].iloc[0]
        self.assertEqual(result["N first"], 4)
        self.assertEqual((kappa["Complete pairs"], kappa["Incomplete pairs"]), (4, 1))


if __name__ == "__main__":
    unittest.main()
