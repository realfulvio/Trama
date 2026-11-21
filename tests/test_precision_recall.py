"""Precision–recall curve: exact thresholds, AP, labels, rows, the paired bootstrap, errors, budget and cancellation.

The reference is the package oracle (every threshold by a fresh scan, exact fractions) and a brute-force bootstrap
that draws the same PCG64 sequence and evaluates each replicate with the exact-fraction scan.
"""
from fractions import Fraction
import importlib.util
import json
from math import isclose
from pathlib import Path
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from analisi import logistic_validation as lv
from analisi import precision_recall as pr
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse
from tests.test_logistic_validation import OPTIONS as LOGISTIC_OPTIONS, simulated

DATA = Path(__file__).resolve().parent / "data" / "precision_recall"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
_spec = importlib.util.spec_from_file_location("precision_recall_oracle", DATA / "oracle.py")
oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oracle)

OPTIONS = {"Outcome": "Event", "Positive": "case", "Negative": "control", "Score": "Signal A",
           "Second score": "Signal B", "Direction": "Higher is positive", "Second direction": "Lower is positive"}


def run(frame, **options):
    return analyse(pr.METHOD, frame, {**OPTIONS, **options})


def brute_ap(y, score, lower=False):
    """AP by a fresh scan of every threshold with exact fractions."""
    values = [Fraction(float(v)) for v in score]
    positives = sum(y)
    previous, area = Fraction(0), Fraction(0)
    for threshold in sorted(set(values), reverse=not lower):
        predicted = [v <= threshold if lower else v >= threshold for v in values]
        tp = sum(a and b for a, b in zip(y, predicted))
        called = sum(predicted)
        recall = Fraction(tp, positives)
        area += (recall - previous) * Fraction(tp, called)
        previous = recall
    return float(area)


def table(frame_rows, **extra):
    return pd.DataFrame({"Outcome": [r[0] for r in frame_rows], "A": [r[1] for r in frame_rows],
                         "B": [r[2] for r in frame_rows], **extra})


def simulated_scores(n=300, positives=0.1, seed=3):
    rng = np.random.default_rng(seed)
    y = rng.random(n) < positives
    a = np.round(rng.normal(size=n) + 1.2 * y, 1)  # one decimal: many ties
    b = np.round(rng.normal(size=n) - 0.8 * y, 1)
    return pd.DataFrame({"Outcome": np.where(y, "case", "control"), "A": a, "B": b})


SIM = {"Outcome": "Outcome", "Positive": "case", "Negative": "control", "Score": "A", "Second score": "B",
       "Direction": "Higher is positive", "Second direction": "Lower is positive"}


class PackageReferenceTests(unittest.TestCase):
    def test_package_fixture_matches_the_frozen_oracle(self):
        frame = pd.read_csv(DATA / "scores.csv")
        result = run(frame)
        self.assertEqual(oracle.reference(DATA), EXPECTED)
        for name, ok in oracle.verify_candidate(DATA, EXPECTED, analyse, pd):
            self.assertTrue(ok, name)
        summary = result.tables["Summary"]
        self.assertEqual(summary["Score"].tolist(), ["Signal A", "Signal B"])
        self.assertEqual(summary["N"].tolist(), [8, 8])
        self.assertEqual(summary["Positives"].tolist(), [3, 3])
        self.assertTrue(isclose(summary["Prevalence"][0], 3 / 8))
        self.assertTrue(isclose(summary["Average precision"][0], 13 / 18))

    def test_sheets_and_integer_counts(self):
        result = run(pd.read_csv(DATA / "scores.csv"))
        self.assertEqual(list(result.tables), ["Summary", "Thresholds: Signal A", "Thresholds: Signal B",
                                              "Comparison", "Settings", "Excluded rows"])
        thresholds = result.tables["Thresholds: Signal A"]
        self.assertEqual(list(thresholds.columns), pr.THRESHOLD_COLUMNS)
        for name in ("TP", "FP", "TN", "FN"):
            self.assertTrue(pd.api.types.is_integer_dtype(thresholds[name]), name)
        # Seven distinct scores (0.91 is tied); the conventional start (0, 1) is drawn but is not a threshold.
        self.assertEqual(len(thresholds), 7)
        self.assertEqual(thresholds["Threshold"].tolist(), [0.93, 0.91, 0.7, 0.62, 0.55, 0.4, 0.2])

    def test_excluded_rows_report_the_physical_row(self):
        result = run(pd.read_csv(DATA / "scores.csv"))
        excluded = result.tables["Excluded rows"]
        self.assertEqual(excluded["Source row"].tolist(), [9, 10])
        self.assertEqual(excluded["Reason"].tolist(), ["Second score is blank or excluded",
                                                       "Outcome is blank or excluded"])
        settings = result.tables["Settings"]["Value"]
        self.assertEqual(settings["Excluded rows"], 2)
        self.assertEqual(settings["Common samples"], 8)

    def test_one_score_keeps_the_rows_that_have_that_score(self):
        options = {k: v for k, v in OPTIONS.items() if k not in ("Second score", "Second direction")}
        result = analyse(pr.METHOD, pd.read_csv(DATA / "scores.csv"), options)
        self.assertEqual(list(result.tables), ["Summary", "Thresholds: Signal A", "Settings", "Excluded rows"])
        self.assertEqual(result.tables["Summary"]["N"].tolist(), [9])  # row 9 has Signal A
        self.assertEqual(result.tables["Excluded rows"]["Source row"].tolist(), [10])

    def test_empty_rows_are_not_exclusions(self):
        frame = pd.read_csv(DATA / "scores.csv")
        frame.loc[len(frame)] = [11, None, None, None]
        frame.loc[len(frame)] = [12, "  ", np.nan, np.nan]
        self.assertEqual(run(frame).tables["Excluded rows"]["Source row"].tolist(), [9, 10])


class ThresholdTests(unittest.TestCase):
    def test_random_ties_against_exact_scan(self):
        frame = simulated_scores()
        result = analyse(pr.METHOD, frame, SIM)
        y = (frame["Outcome"] == "case").astype(int).tolist()
        a, b = frame["A"], frame["B"]
        summary = result.tables["Summary"]
        self.assertTrue(isclose(summary["Average precision"][0], brute_ap(y, a), rel_tol=1e-12))
        self.assertTrue(isclose(summary["Average precision"][1], brute_ap(y, b, lower=True), rel_tol=1e-12))
        self.assertTrue(isclose(result.tables["Comparison"]["AP difference"][0],
                                brute_ap(y, b, lower=True) - brute_ap(y, a), rel_tol=1e-9, abs_tol=1e-14))
        # Strictest threshold first for each direction; Lower is positive starts at the smallest score.
        self.assertTrue(result.tables["Thresholds: A"]["Threshold"].is_monotonic_decreasing)
        self.assertTrue(result.tables["Thresholds: B"]["Threshold"].is_monotonic_increasing)
        counts = result.tables["Thresholds: A"]
        self.assertTrue((counts["TP"] + counts["FN"] == y.count(1)).all())
        self.assertTrue((counts["FP"] + counts["TN"] == y.count(0)).all())
        self.assertEqual(int(counts["TP"].iloc[-1]), y.count(1))
        self.assertEqual(int(counts["FP"].iloc[-1]), y.count(0))

    def test_imbalanced_sample(self):
        rng = np.random.default_rng(8)
        y = np.zeros(1000, dtype=int)
        y[rng.choice(1000, size=3, replace=False)] = 1
        frame = pd.DataFrame({"Outcome": np.where(y == 1, "case", "control"),
                              "A": np.round(rng.normal(size=1000) + 2 * y, 2)})
        result = analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "case", "Negative": "control",
                                            "Score": "A"})
        summary = result.tables["Summary"].iloc[0]
        self.assertEqual((summary["N"], summary["Positives"]), (1000, 3))
        self.assertTrue(isclose(summary["Prevalence"], 0.003))
        self.assertTrue(isclose(summary["Average precision"], brute_ap(y.tolist(), frame["A"]), rel_tol=1e-12))

    def test_constant_score_gives_the_prevalence(self):
        frame = pd.DataFrame({"Outcome": ["case"] * 3 + ["control"] * 7, "A": [4.2] * 10})
        options = {"Outcome": "Outcome", "Positive": "case", "Negative": "control", "Score": "A"}
        result = analyse(pr.METHOD, frame, options)
        summary = result.tables["Summary"].iloc[0]
        self.assertTrue(isclose(summary["Average precision"], 0.3, rel_tol=1e-15))
        self.assertTrue(isclose(summary["Average precision"], summary["Prevalence"], rel_tol=1e-15))
        thresholds = result.tables["Thresholds: A"]
        self.assertEqual(len(thresholds), 1)
        self.assertEqual(thresholds.iloc[0][["TP", "FP", "TN", "FN"]].tolist(), [3, 7, 0, 0])
        self.assertEqual(summary["ROC AUC"], 0.5)

    def test_permuted_rows_give_the_same_tables_and_intervals(self):
        frame = simulated_scores(120, 0.2)
        options = {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 300, "Bootstrap seed": 5}
        first = analyse(pr.METHOD, frame, options)
        shuffled = frame.sample(frac=1, random_state=11).reset_index(drop=True)
        second = analyse(pr.METHOD, shuffled, options)
        for name in ("Summary", "Thresholds: A", "Thresholds: B", "Comparison"):
            pd.testing.assert_frame_equal(first.tables[name], second.tables[name], check_exact=True, obj=name)

    def test_lower_is_positive_equals_the_negated_score(self):
        frame = simulated_scores(150, 0.25)
        lower = analyse(pr.METHOD, frame, {**SIM, "Direction": "Lower is positive"})
        negated = frame.assign(A=-frame["A"])
        higher = analyse(pr.METHOD, negated, SIM)
        self.assertEqual(lower.tables["Summary"]["Average precision"][0], higher.tables["Summary"]["Average precision"][0])
        thresholds = lower.tables["Thresholds: A"]
        self.assertTrue((thresholds[["TP", "FP", "TN", "FN"]].to_numpy()
                         == higher.tables["Thresholds: A"][["TP", "FP", "TN", "FN"]].to_numpy()).all())
        np.testing.assert_array_equal(thresholds["Threshold"], -higher.tables["Thresholds: A"]["Threshold"])

    def test_agrees_with_the_logistic_validation_on_the_same_scores(self):
        logistic = analyse(lv.METHOD, simulated(), LOGISTIC_OPTIONS)
        predictions = logistic.tables["Predictions"]
        frame = predictions.dropna(subset=["Observed", "Logit"])
        result = analyse(pr.METHOD, frame, {"Outcome": "Observed", "Positive": "1", "Negative": "0",
                                            "Score": "Logit"})
        summary, validation = result.tables["Summary"].iloc[0], logistic.tables["Validation"].iloc[0]
        self.assertTrue(isclose(summary["Average precision"], validation["Average precision"], rel_tol=1e-12))
        self.assertTrue(isclose(summary["ROC AUC"], validation["ROC AUC"], rel_tol=1e-12))
        self.assertTrue(isclose(summary["Prevalence"], validation["Prevalence"], rel_tol=1e-12))


class LabelAndRowTests(unittest.TestCase):
    def test_labels_are_compared_literally(self):
        frame = pd.DataFrame({"Outcome": pd.Series(["01", "1", "01", "1", "1", "01"], dtype=object),
                              "A": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]})
        options = {"Outcome": "Outcome", "Positive": "01", "Negative": "1", "Score": "A"}
        summary = analyse(pr.METHOD, frame, options).tables["Summary"].iloc[0]
        self.assertEqual((summary["N"], summary["Positives"]), (6, 3))
        swapped = analyse(pr.METHOD, frame, {**options, "Positive": "1", "Negative": "01"}).tables["Summary"].iloc[0]
        self.assertEqual(swapped["Positives"], 3)
        self.assertNotEqual(summary["Average precision"], swapped["Average precision"])
        with self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, {**options, "Positive": "1", "Negative": "0"})
        self.assertEqual(caught.exception.field, "Outcome")
        self.assertIn('"01" in row 1', str(caught.exception))

    def test_numeric_outcomes_match_their_typed_label(self):
        frame = pd.DataFrame({"Outcome": [1, 0, 1, 0, 0, 1.0], "A": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]})
        summary = analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "1", "Negative": "0",
                                             "Score": "A"}).tables["Summary"].iloc[0]
        self.assertEqual((summary["N"], summary["Positives"]), (6, 3))

    def test_text_labels_are_not_trimmed_or_case_folded(self):
        frame = pd.DataFrame({"Outcome": ["Case", "case", "control", "control"], "A": [4.0, 3.0, 2.0, 1.0]})
        with self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "case", "Negative": "control",
                                       "Score": "A"})
        self.assertIn('"Case" in row 1', str(caught.exception))

    def test_unknown_label_in_a_row_without_scores_is_still_reported(self):
        frame = pd.DataFrame({"Outcome": ["case", "control", "case", "control", "oops"],
                              "A": [4.0, 3.0, 2.0, 1.0, None]})
        with self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "case", "Negative": "control",
                                       "Score": "A"})
        self.assertEqual(caught.exception.field, "Outcome")
        self.assertIn("row 5", str(caught.exception))

    def test_first_occurrence_of_a_foreign_label(self):
        frame = pd.DataFrame({"Outcome": ["case", "x", "control", "y"], "A": [1.0, 2.0, 3.0, 4.0]})
        with self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "case", "Negative": "control",
                                       "Score": "A"})
        self.assertIn('"x" in row 2', str(caught.exception))

    def test_decimal_comma_text_scores(self):
        frame = pd.DataFrame({"Outcome": ["case", "control", "case", "control"],
                              "A": ["0,9", "0,2", "0,7", "0,4"]})
        summary = analyse(pr.METHOD, frame, {"Outcome": "Outcome", "Positive": "case", "Negative": "control",
                                             "Score": "A"}).tables["Summary"].iloc[0]
        self.assertEqual(summary["Average precision"], 1.0)


class ErrorTests(unittest.TestCase):
    def check(self, field, text=None, frame=None, **options):
        frame = pd.read_csv(DATA / "scores.csv") if frame is None else frame
        with self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, {**OPTIONS, **options})
        self.assertEqual(caught.exception.field, field)
        if text:
            self.assertIn(text, str(caught.exception))

    def test_single_class(self):
        frame = pd.DataFrame({"Event": ["case"] * 4, "Signal A": [1.0, 2, 3, 4]})
        self.check("Outcome", "All 4 complete rows are Positive", frame, **{"Second score": None})
        frame["Event"] = "control"
        self.check("Outcome", "All 4 complete rows are Negative", frame, **{"Second score": None})

    def test_a_single_class_after_incomplete_rows_are_left_out(self):
        frame = pd.DataFrame({"Event": ["case", "case", "control", "control"], "Signal A": [1.0, 2, None, None]})
        self.check("Outcome", "All 2 complete rows are Positive", frame, **{"Second score": None})

    def test_no_complete_row(self):
        frame = pd.DataFrame({"Event": ["case", "control"], "Signal A": [None, None]})
        self.check("Outcome", "No row has an Outcome", frame, **{"Second score": None})

    def test_infinite_score(self):
        frame = pd.read_csv(DATA / "scores.csv")
        frame.loc[2, "Signal A"] = np.inf
        self.check("Score", "not a finite number in row 3", frame)
        frame = pd.read_csv(DATA / "scores.csv")
        frame.loc[1, "Signal B"] = -np.inf
        self.check("Second score", "not a finite number in row 2", frame)

    def test_text_score(self):
        frame = pd.read_csv(DATA / "scores.csv").astype({"Signal A": object})
        frame.loc[3, "Signal A"] = "n/a"
        self.check("Score", "not a finite number in row 4", frame)

    def test_recipe_errors_name_their_field(self):
        self.check("Outcome", None, **{"Outcome": ""})
        self.check("Score", 'already used for Outcome', **{"Score": "Event"})
        self.check("Second score", 'already used for Score', **{"Second score": "Signal A"})
        self.check("Positive", "Enter the exact label", **{"Positive": ""})
        self.check("Positive", "Enter the exact label", **{"Positive": "   "})
        self.check("Negative", "Enter the exact label", **{"Negative": None})
        self.check("Negative", "different labels", **{"Negative": "case"})
        self.check("Direction", None, **{"Direction": "Up"})
        self.check("Second direction", None, **{"Second direction": 3})
        self.check("Outcome", "is not in the table", **{"Outcome": "Nope"})
        self.check("Bootstrap CI", None, **{"Bootstrap CI": "yes"})

    def test_bootstrap_settings(self):
        base = {"Bootstrap CI": True}
        self.check("Bootstrap replicates", "from 199 to 10,000", **base, **{"Bootstrap replicates": 198})
        self.check("Bootstrap replicates", "from 199 to 10,000", **base, **{"Bootstrap replicates": 10_001})
        self.check("Bootstrap replicates", None, **base, **{"Bootstrap replicates": 199.5})
        self.check("Bootstrap replicates", None, **base, **{"Bootstrap replicates": True})
        self.check("Bootstrap seed", None, **base, **{"Bootstrap seed": -1})
        self.check("Bootstrap seed", None, **base, **{"Bootstrap seed": 2**64})
        self.check("Confidence level (%)", None, **base, **{"Confidence level (%)": 100})
        self.check("Confidence level (%)", None, **base, **{"Confidence level (%)": 0})
        self.check("Confidence level (%)", None, **base, **{"Confidence level (%)": "x"})
        ok = {**OPTIONS, **base, "Bootstrap replicates": "199", "Bootstrap seed": str(2**64 - 1),
              "Confidence level (%)": "90,5"}
        self.assertEqual(pr.read_settings(ok).seed, 2**64 - 1)
        self.assertEqual(pr.read_settings(ok).level, 90.5)

    def test_hidden_bootstrap_fields_are_not_validated(self):
        result = run(pd.read_csv(DATA / "scores.csv"), **{"Bootstrap replicates": "garbage", "Bootstrap seed": -5})
        self.assertNotIn("Bootstrap replicates", result.tables["Settings"]["Value"])

    def test_budget_is_checked_before_any_draw(self):
        rows = 4001
        frame = pd.DataFrame({"Outcome": ["case", "control"] * (rows // 2) + ["case"],
                              "A": np.arange(rows, dtype=float)})
        options = {"Outcome": "Outcome", "Positive": "case", "Negative": "control", "Score": "A",
                   "Bootstrap CI": True, "Bootstrap replicates": 10_000, "Bootstrap seed": 1}
        with mock.patch.object(np.random, "PCG64", side_effect=AssertionError("drew")), \
                self.assertRaises(FieldError) as caught:
            analyse(pr.METHOD, frame, options)
        self.assertEqual(caught.exception.field, "Bootstrap replicates")
        self.assertIn("10,000 × 4,001 exceeds the limit of 20,000,000", str(caught.exception))
        # Exactly at the limit is allowed (2,000 samples × 10,000 replicates).
        pr.prepare(frame.iloc[:2000], options)

    def test_non_mapping_options(self):
        with self.assertRaises(ValueError):
            pr.read_settings(["x"])


class BootstrapTests(unittest.TestCase):
    BOOT = {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 250, "Bootstrap seed": 7,
            "Confidence level (%)": 90}

    def reference(self, frame, options):
        """The documented sequence, replicate by replicate, with the exact-fraction scan."""
        y = (frame["Outcome"] == "case").to_numpy()
        a, b = frame["A"].to_numpy(), frame["B"].to_numpy()
        # Canonical order: by the oriented first score, then the oriented second score, inside each class.
        key_a, key_b = a, -b
        positive = np.flatnonzero(y)
        negative = np.flatnonzero(~y)
        positive = positive[np.lexsort((key_b[positive], key_a[positive]))]
        negative = negative[np.lexsort((key_b[negative], key_a[negative]))]
        rng = np.random.Generator(np.random.PCG64(options["Bootstrap seed"]))
        out = []
        for _ in range(options["Bootstrap replicates"]):
            drawn = np.r_[positive[rng.integers(0, len(positive), size=len(positive))],
                          negative[rng.integers(0, len(negative), size=len(negative))]]
            yy = y[drawn].astype(int).tolist()
            out.append((brute_ap(yy, a[drawn]), brute_ap(yy, b[drawn], lower=True)))
        return np.array(out)

    def test_replicates_follow_the_documented_sequence(self):
        frame = simulated_scores(70, 0.2, seed=2)
        options = {**self.BOOT, "Bootstrap replicates": 199}
        replicates = self.reference(frame, options)
        result = analyse(pr.METHOD, frame, options)
        alpha = 0.1
        summary, comparison = result.tables["Summary"], result.tables["Comparison"]
        for number in (0, 1):
            low, high = np.quantile(replicates[:, number], [alpha / 2, 1 - alpha / 2], method="linear")
            self.assertTrue(isclose(summary["AP lower"][number], low, rel_tol=1e-12, abs_tol=1e-14))
            self.assertTrue(isclose(summary["AP upper"][number], high, rel_tol=1e-12, abs_tol=1e-14))
        low, high = np.quantile(replicates[:, 1] - replicates[:, 0], [alpha / 2, 1 - alpha / 2], method="linear")
        self.assertTrue(isclose(comparison["Difference lower"][0], low, rel_tol=1e-9, abs_tol=1e-12))
        self.assertTrue(isclose(comparison["Difference upper"][0], high, rel_tol=1e-9, abs_tol=1e-12))

    def test_same_seed_same_numbers_other_seed_other_numbers(self):
        frame = simulated_scores()
        first, again = analyse(pr.METHOD, frame, self.BOOT), analyse(pr.METHOD, frame, self.BOOT)
        other = analyse(pr.METHOD, frame, {**self.BOOT, "Bootstrap seed": 8})
        for name in ("Summary", "Comparison"):
            pd.testing.assert_frame_equal(first.tables[name], again.tables[name], check_exact=True)
        self.assertNotEqual(first.tables["Summary"]["AP lower"][0], other.tables["Summary"]["AP lower"][0])

    def test_block_size_does_not_change_the_replicates(self):
        frame = simulated_scores(90, 0.2)
        baseline = analyse(pr.METHOD, frame, self.BOOT)
        for values in (1, 90, 1000, 10**7):
            with mock.patch.object(pr, "BLOCK_VALUES", values):
                again = analyse(pr.METHOD, frame, self.BOOT)
            for name in ("Summary", "Comparison"):
                pd.testing.assert_frame_equal(baseline.tables[name], again.tables[name], check_exact=True,
                                              obj=f"{name} at block {values}")

    def test_first_replicates_do_not_depend_on_how_many_are_requested(self):
        frame = simulated_scores(60, 0.25)
        plan = pr.prepare(frame, {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 199, "Bootstrap seed": 4})
        longer = pr.prepare(frame, {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 400, "Bootstrap seed": 4})
        np.testing.assert_array_equal(pr.bootstrap(plan), pr.bootstrap(longer)[:, :199])

    def test_two_identical_scores_have_a_zero_difference_everywhere(self):
        frame = simulated_scores(80, 0.2).assign(B=lambda f: f["A"])
        options = {**SIM, "Direction": "Higher is positive", "Second direction": "Higher is positive",
                   "Bootstrap CI": True, "Bootstrap replicates": 300, "Bootstrap seed": 3}
        plan = pr.prepare(frame, options)
        replicates = pr.bootstrap(plan)
        np.testing.assert_array_equal(replicates[0], replicates[1])
        comparison = analyse(pr.METHOD, frame, options).tables["Comparison"].iloc[0]
        self.assertEqual((comparison["AP difference"], comparison["Difference lower"],
                          comparison["Difference upper"]), (0.0, 0.0, 0.0))

    def test_single_score_bootstrap_has_no_comparison(self):
        frame = simulated_scores()
        options = {key: value for key, value in self.BOOT.items() if key not in ("Second score", "Second direction")}
        result = analyse(pr.METHOD, frame, options)
        self.assertNotIn("Comparison", result.tables)
        summary = result.tables["Summary"]
        self.assertEqual(list(summary.columns[-2:]), ["AP lower", "AP upper"])
        self.assertLessEqual(summary["AP lower"][0], summary["Average precision"][0] + 0.2)
        self.assertLess(summary["AP lower"][0], summary["AP upper"][0])

    def test_without_the_bootstrap_there_are_no_interval_columns(self):
        result = run(pd.read_csv(DATA / "scores.csv"))
        self.assertNotIn("AP lower", result.tables["Summary"])
        self.assertNotIn("Difference lower", result.tables["Comparison"])

    def test_every_replicate_matches_the_point_estimate_on_its_own_draw(self):
        """The fast per-threshold counts equal ``average_precision`` of the same drawn samples."""
        frame = simulated_scores(50, 0.3, seed=9)
        plan = pr.prepare(frame, {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 199, "Bootstrap seed": 2})
        replicates = pr.bootstrap(plan)
        oriented = [plan.oriented(0)[0], plan.oriented(1)[0]]
        positive, negative = np.flatnonzero(plan.y == 1), np.flatnonzero(plan.y == 0)
        order = (np.lexsort((oriented[1][positive], oriented[0][positive])),
                 np.lexsort((oriented[1][negative], oriented[0][negative])))
        positive, negative = positive[order[0]], negative[order[1]]
        rng = np.random.Generator(np.random.PCG64(2))
        for replicate in range(199):
            drawn = np.r_[positive[rng.integers(0, len(positive), size=len(positive))],
                          negative[rng.integers(0, len(negative), size=len(negative))]]
            for number in (0, 1):
                self.assertTrue(isclose(replicates[number, replicate],
                                        lv.average_precision(plan.y[drawn], oriented[number][drawn]),
                                        rel_tol=1e-12), (replicate, number))

    def test_cancel_before_and_during_the_bootstrap(self):
        frame = simulated_scores(200, 0.2)
        options = {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 2000, "Bootstrap seed": 1}
        event = threading.Event()
        event.set()
        with self.assertRaises(MonteCarloCancelled):
            analyse(pr.METHOD, frame, options, cancel=event)
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 3

        with mock.patch.object(pr, "BLOCK_VALUES", 1000), self.assertRaises(pr.PrecisionRecallCancelled):
            analyse(pr.METHOD, frame, options, cancel=cancel)
        self.assertGreater(len(calls), 3)
        self.assertTrue(issubclass(pr.PrecisionRecallCancelled, InterruptedError))

    def test_cancellable_only_with_the_bootstrap(self):
        self.assertTrue(pr.cancellable(pr.METHOD, {"Bootstrap CI": True}))
        self.assertFalse(pr.cancellable(pr.METHOD, {"Bootstrap CI": False}))
        self.assertFalse(pr.cancellable(pr.METHOD, {}))
        self.assertFalse(pr.cancellable("t-test", {"Bootstrap CI": True}))


class FigureAndRegistrationTests(unittest.TestCase):
    def test_registration(self):
        self.assertIn(pr.METHOD, METHODS)
        self.assertIn(pr.METHOD, GRAPH_METHODS)
        self.assertIn(pr.METHOD, GROUPS["Group Comparison"])
        self.assertEqual(METHODS[pr.METHOD], pr.OPTIONS)

    def test_staircase_area_is_the_average_precision(self):
        frame = simulated_scores(100, 0.15)
        plan = pr.prepare(frame, SIM)
        for number in (0, 1):
            curve = pr.build_curve(plan, number)
            x, y = pr.staircase(curve)
            self.assertEqual((x[0], y[0]), (0.0, 1.0))
            area = float(np.sum(np.diff(x) * y[1:]))
            self.assertTrue(isclose(area, curve.ap, rel_tol=1e-12))
            self.assertEqual(x[-1], 1.0)

    def test_figure_lines_and_labels(self):
        frame = pd.read_csv(DATA / "scores.csv")
        figure = run(frame).figure
        axes = figure.axes[0]
        gids = [line.get_gid() for line in axes.lines]
        self.assertEqual(gids[:3], ["precision-recall:curve-a", "precision-recall:curve-b",
                                    "precision-recall:prevalence"])
        labels = [text.get_text() for text in figure.legends[0].get_texts()]
        self.assertTrue(labels[0].startswith("Signal A: AP 0.7222"), labels)
        self.assertIn("Prevalence 0.375 (3 positives)", labels)
        self.assertTrue(any(text.startswith("AP difference (second − first score)") for text in labels))
        self.assertEqual(axes.get_xlabel(), "Recall")
        self.assertEqual(axes.get_ylabel(), "Precision")
        self.assertEqual(len(axes.patches) + len(axes.collections), 0)  # no bands
        self.assertEqual(axes.get_ylim(), (0, 1.02))
        self.assertEqual(axes.get_title(), "Precision–recall curve · 8 samples")

    def test_bootstrap_interval_is_text_in_the_legend_not_a_band(self):
        frame = simulated_scores()
        figure = analyse(pr.METHOD, frame, {**SIM, "Bootstrap CI": True, "Bootstrap replicates": 199}).figure
        axes = figure.axes[0]
        self.assertEqual(len(axes.patches) + len(axes.collections), 0)
        self.assertIn("95% CI", figure.legends[0].get_texts()[0].get_text())

    def test_figure_is_vector_exportable_and_pickles(self):
        import io
        import pickle
        figure = run(pd.read_csv(DATA / "scores.csv")).figure
        for fmt in ("svg", "pdf"):
            buffer = io.BytesIO()
            figure.savefig(buffer, format=fmt)
            self.assertGreater(buffer.tell(), 1000)
        pickle.dumps(figure)


if __name__ == "__main__":
    unittest.main()
