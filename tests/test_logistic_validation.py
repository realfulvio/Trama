"""Validate binary logistic model: folds, out-of-fold fits, metrics, errors, budgets and cancellation.

The metric checks recompute everything from the exported Predictions sheet with brute-force definitions (pairwise
AUC, the AP sum written out threshold by threshold, −log p), never with the engine's helpers.
"""
from itertools import product
import json
import math
from pathlib import Path
import threading
import unittest

import numpy as np
import pandas as pd
from statsmodels.genmod.families import Binomial
from statsmodels.genmod.generalized_linear_model import GLM

from analisi import logistic_validation as lv
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "logistic_validation"
CASES = json.loads((DATA / "casi.json").read_text(encoding="utf-8"))


def simulated(n=240, seed=4, prevalence_shift=0.0):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"Dose (mg)": rng.normal(size=n), "Età %": rng.normal(50, 10, size=n),
                          "Clinic": rng.choice(["North", "South", "East"], size=n)})
    z = prevalence_shift - .2 + 1.1 * frame["Dose (mg)"] + .03 * (frame["Età %"] - 50) \
        + .7 * (frame["Clinic"] == "South")
    frame["Outcome"] = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(float)
    return frame


OPTIONS = {"Response": "Outcome", "Predictors": ["Dose (mg)", "Età %", "Clinic"],
           "Categorical predictors": ["Clinic"], "Folds": 5, "Seed": 11}


def run(frame, **options):
    return analyse(lv.METHOD, frame, {**OPTIONS, **options})


def brute_auc(y, score):
    positive, negative = score[y == 1], score[y == 0]
    return np.mean([(a > b) + .5 * (a == b) for a, b in product(positive, negative)])


def brute_ap(y, score):
    total, last, ap = y.sum(), 0.0, 0.0
    for cutoff in sorted(set(score), reverse=True):
        hits = y[score >= cutoff]
        recall = hits.sum() / total
        ap += (recall - last) * hits.mean()
        last = recall
    return ap


class FixtureTests(unittest.TestCase):
    def test_published_cases(self):
        frame = pd.read_csv(DATA / "logistic.csv")
        for case in CASES:
            with self.subTest(case=case["name"]):
                tables = analyse(case["method"], frame, case["options"]).tables
                for name, expected in case["tables"].items():
                    self.assertEqual(len(tables[name]), expected["count"], name)
                    for position, row in enumerate(expected["rows"]):
                        for column, value in row.items():
                            self.assertAlmostEqual(float(tables[name].iloc[position][column]), value, places=7,
                                                   msg=f"{name} {position} {column}")


class FoldTests(unittest.TestCase):
    def test_automatic_folds_follow_the_specification(self):
        frame = simulated()
        plan = lv.prepare(frame, OPTIONS)
        # Independent re-implementation: one generator, outcome 0 then outcome 1, round-robin from fold 1.
        generator = np.random.Generator(np.random.PCG64(11))
        expected = np.zeros(plan.n, dtype=int)
        for outcome in (0, 1):
            positions = [i for i, value in enumerate(plan.y) if value == outcome]
            for order, position in enumerate(generator.permutation(positions)):
                expected[position] = order % 5 + 1
        np.testing.assert_array_equal(plan.assignment, expected)
        for fold in range(1, 6):
            self.assertEqual(set(plan.y[plan.assignment == fold]), {0.0, 1.0})

    def test_same_seed_same_results_other_seed_other_folds(self):
        frame = simulated()
        first, second = run(frame).tables, run(frame).tables
        for name in first:
            pd.testing.assert_frame_equal(first[name], second[name], check_exact=True)
        other = run(frame, Seed=12).tables[lv.PREDICTIONS]
        self.assertFalse(other["Fold"].equals(first[lv.PREDICTIONS]["Fold"]))

    def test_same_results_whatever_the_process_setting(self):
        from analisi import parallel
        frame = simulated()
        reference = run(frame).tables
        original = parallel.process_count
        parallel.process_count = lambda: 4
        try:
            again = run(frame).tables
        finally:
            parallel.process_count = original
        for name in reference:
            pd.testing.assert_frame_equal(reference[name], again[name], check_exact=True)

    def test_editing_one_test_row_leaves_its_own_fit_unchanged(self):
        frame = simulated()
        base = run(frame).tables
        position = 7
        fold = int(base[lv.PREDICTIONS]["Fold"].iloc[position])
        edited = frame.copy()
        edited.loc[position, "Dose (mg)"] += 3.0
        after = run(edited).tables
        before_coefficients = base[lv.COEFFICIENTS].set_index(["Fold", "Term"])["Estimate"]
        after_coefficients = after[lv.COEFFICIENTS].set_index(["Fold", "Term"])["Estimate"]
        pd.testing.assert_series_equal(before_coefficients.loc[fold], after_coefficients.loc[fold], check_exact=True)
        for other in set(range(1, 6)) - {fold}:
            self.assertFalse(before_coefficients.loc[other].equals(after_coefficients.loc[other]))
        # Only the edited row's prediction moves within its fold.
        moved = base[lv.PREDICTIONS]["Logit"] != after[lv.PREDICTIONS]["Logit"]
        same_fold = base[lv.PREDICTIONS]["Fold"] == fold
        self.assertEqual(list(np.flatnonzero(moved & same_fold)), [position])

    def test_fold_column_is_used_as_given(self):
        frame = simulated(n=60)
        frame["My fold"] = np.tile([1, 2, 3], 20)
        tables = run(frame, **{"Validation fold": "My fold", "Folds": 3}).tables
        np.testing.assert_array_equal(tables[lv.PREDICTIONS]["Fold"], frame["My fold"])
        self.assertIn('folds from "My fold"', tables[lv.VALIDATION]["Design"].iloc[0])

    def test_each_fold_fit_uses_only_its_training_rows(self):
        frame = simulated(n=150)
        tables = run(frame, **{"Categorical predictors": [], "Predictors": ["Dose (mg)", "Età %"]}).tables
        folds = tables[lv.PREDICTIONS]["Fold"].to_numpy()
        for fold in range(1, 6):
            train = frame[folds != fold]
            design = np.column_stack([np.ones(len(train)), train["Dose (mg)"], train["Età %"]])
            direct = GLM(train["Outcome"].to_numpy(), design, family=Binomial()).fit().params
            got = tables[lv.COEFFICIENTS].query("Fold == @fold")["Estimate"].to_numpy()
            np.testing.assert_allclose(got, direct, rtol=1e-10)


class MetricTests(unittest.TestCase):
    def test_metrics_recomputed_from_the_exported_vector(self):
        tables = run(simulated()).tables
        rows = tables[lv.PREDICTIONS]
        y, logit, p = rows["Observed"].to_numpy(), rows["Logit"].to_numpy(), rows["Probability"].to_numpy()
        summary = tables[lv.VALIDATION].iloc[0]
        self.assertAlmostEqual(summary["Brier score"], np.mean((p - y) ** 2), places=12)
        self.assertAlmostEqual(summary["Log loss"], np.mean(-np.log(np.where(y == 1, p, 1 - p))), places=10)
        self.assertAlmostEqual(summary["ROC AUC"], brute_auc(y, logit), places=12)
        self.assertAlmostEqual(summary["Average precision"], brute_ap(y, logit), places=12)
        predicted = p >= .5
        self.assertEqual((summary["TN"], summary["FP"], summary["FN"], summary["TP"]),
                         (np.sum((y == 0) & ~predicted), np.sum((y == 0) & predicted),
                          np.sum((y == 1) & ~predicted), np.sum((y == 1) & predicted)))
        matrix = tables[lv.CONFUSION]
        self.assertEqual(list(matrix.index), ["Observed 0", "Observed 1"])
        self.assertEqual(matrix.loc["Observed 1", "Predicted 1"], summary["TP"])
        folds = tables[lv.FOLD_SHEET]
        self.assertEqual(folds["Test N"].sum(), len(rows))
        for _, fold in folds.iterrows():
            members = rows["Fold"] == fold["Fold"]
            self.assertAlmostEqual(fold["Brier score"], np.mean((p[members] - y[members]) ** 2), places=12)

    def test_tied_scores_get_half_credit(self):
        y = np.array([0, 1, 0, 1, 1, 0.])
        score = np.array([1, 1, 2, 2, 3, 0.])
        self.assertAlmostEqual(lv.roc_auc(y, score), brute_auc(y, score))
        self.assertAlmostEqual(lv.average_precision(y, score), brute_ap(y, score))

    def test_extreme_logits_keep_a_finite_exact_log_loss(self):
        y = np.array([0., 1., 1., 0.])
        logit = np.array([-800., 800., -40., 40.])
        terms = lv.log_loss_terms(y, logit)
        np.testing.assert_allclose(terms, [0.0, 0.0, 40.0, 40.0], atol=1e-15)
        self.assertTrue(np.isfinite(terms).all())

    def test_probability_one_falls_in_the_last_bin_and_empty_bins_stay(self):
        y = np.array([1., 1., 0., 0.])
        p = np.array([1.0, .95, .1, 0.0])
        table = lv.calibration_table(y, p, 10)
        self.assertEqual(len(table), 10)
        self.assertEqual(table["N"].tolist(), [1, 1, 0, 0, 0, 0, 0, 0, 0, 2])
        self.assertTrue(np.isnan(table.loc[4, "Mean predicted"]))
        self.assertEqual(table.loc[9, "Lower"], .9)
        self.assertEqual(table.loc[9, "Upper"], 1.0)
        edge = lv.calibration_table(np.array([1., 0.]), np.array([.2, .3]), 10)
        self.assertEqual(edge["N"].tolist(), [0, 0, 1, 1, 0, 0, 0, 0, 0, 0])

    def test_near_boundary_data_without_separation(self):
        # Overlap in every training fold: the MLE exists, probabilities reach 1e-8 and 1 − 1e-8.
        x = np.r_[np.linspace(0, 30, 40), np.linspace(25, 55, 40)]
        y = np.r_[np.zeros(40), np.ones(40)]
        y[[34, 36, 38]], y[[41, 43, 45]] = 1, 0
        tables = analyse(lv.METHOD, pd.DataFrame({"x": x, "y": y}),
                         {"Response": "y", "Predictors": ["x"], "Folds": 4, "Seed": 2}).tables
        rows = tables[lv.PREDICTIONS]
        self.assertLess(rows["Probability"].min(), 1e-7)
        self.assertGreater(rows["Probability"].max(), 1 - 1e-7)
        summary = tables[lv.VALIDATION].iloc[0]
        observed, logit = rows["Observed"].to_numpy(), rows["Logit"].to_numpy()
        naive = np.mean(np.where(observed == 1, -np.log(rows["Probability"]), -np.log1p(-rows["Probability"])))
        self.assertAlmostEqual(summary["Log loss"], naive, places=6)
        self.assertEqual(tables[lv.CALIBRATION]["N"].sum(), 80)

    def test_imbalanced_classes_are_not_reweighted(self):
        frame = simulated(n=600, prevalence_shift=-3.0)
        tables = run(frame, Folds=5).tables
        summary = tables[lv.VALIDATION].iloc[0]
        self.assertLess(summary["Prevalence"], .12)
        self.assertEqual(summary["N"], 600)
        # The out-of-fold mean probability tracks the prevalence: no class weights, no resampling.
        self.assertAlmostEqual(tables[lv.PREDICTIONS]["Probability"].mean(), summary["Prevalence"], delta=.02)

    def test_threshold_bounds(self):
        frame = simulated()
        everything = run(frame, Threshold=0).tables[lv.VALIDATION].iloc[0]
        self.assertEqual((everything["TN"], everything["FN"]), (0, 0))
        nothing = run(frame, Threshold=1).tables[lv.VALIDATION].iloc[0]
        self.assertEqual((nothing["FP"], nothing["TP"]), (0, 0))


class RowTests(unittest.TestCase):
    def test_incomplete_rows_keep_their_source_position(self):
        frame = simulated(n=80)
        frame.index = np.arange(1000, 1080)[::-1]  # pandas labels must never leak into Source row
        frame.iloc[3, frame.columns.get_loc("Dose (mg)")] = np.nan
        frame.iloc[9, frame.columns.get_loc("Clinic")] = None
        frame.iloc[12, frame.columns.get_loc("Outcome")] = np.nan
        rows = run(frame).tables[lv.PREDICTIONS]
        self.assertEqual(rows["Source row"].tolist(), list(range(1, 81)))
        incomplete = rows[rows["Status"] == lv.INCOMPLETE]
        self.assertEqual(incomplete["Source row"].tolist(), [4, 10, 13])
        self.assertTrue(incomplete[["Fold", "Logit", "Probability", "Predicted"]].isna().all().all())
        self.assertEqual(run(frame).tables[lv.VALIDATION].iloc[0]["N"], 77)


class ErrorTests(unittest.TestCase):
    def assertField(self, field, frame, text=None, **options):
        with self.assertRaises(FieldError) as caught:
            run(frame, **options)
        self.assertEqual(caught.exception.field, field, str(caught.exception))
        if text:
            self.assertIn(text, str(caught.exception))
        return caught.exception

    def test_one_class(self):
        frame = simulated()
        frame["Outcome"] = 1.0
        self.assertField("Response", frame, "both outcomes")

    def test_response_outside_zero_one(self):
        frame = simulated()
        frame.loc[5, "Outcome"] = 2
        self.assertField("Response", frame, "source row 6")

    def test_separation_names_the_fold(self):
        frame = pd.DataFrame({"x": np.r_[np.arange(10), np.arange(9, 19)], "y": np.r_[np.zeros(10), np.ones(10)]})
        with self.assertRaises(FieldError) as caught:
            analyse(lv.METHOD, frame, {"Response": "y", "Predictors": ["x"], "Folds": 2})
        self.assertEqual(caught.exception.field, "Predictors")
        self.assertRegex(str(caught.exception), r"^Fold \d: the training rows are separated")

    def test_rare_level_absent_from_training(self):
        frame = simulated(n=100)
        frame.loc[4, "Clinic"] = "Island"
        error = self.assertField("Categorical predictors", frame, 'level "Island" of "Clinic"')
        self.assertIn("test rows but not in the training rows", str(error))
        # Checked before any fit: the dialog's cheap check finds it too.
        with self.assertRaises(FieldError):
            lv.prepare(frame, OPTIONS)

    def test_rare_level_with_one_outcome_is_named(self):
        frame = simulated(n=100)
        frame.loc[[4, 9], "Clinic"] = "Island"
        frame.loc[[4, 9], "Outcome"] = 1.0
        frame["F"] = np.tile([1, 2, 3, 4], 25)
        frame.loc[4, "F"], frame.loc[9, "F"] = 2, 3  # each Island row has the other one in its training rows
        error = self.assertField("Categorical predictors", frame, None, **{"Validation fold": "F", "Folds": 4})
        self.assertEqual(str(error), 'Fold 1: every training row with level "Island" of "Clinic" has outcome 1 '
                                     "(quasi-complete separation). Merge rare levels, or change the folds or the seed.")

    def test_malformed_fold_column(self):
        frame = simulated(n=60)
        for codes, text in (([1, 2, 3] * 19 + [1, 2, 4], "not a whole number from 1 to 3"),
                            ([1, 2, 3] * 19 + [1, 2, 1.5], "not a whole number"),
                            ([1, 2] * 30, "Fold 3 has no usable rows"),
                            ([1, 2, 3] * 19 + [1, 2, np.nan], "has no fold code")):
            frame["F"] = codes
            with self.subTest(text=text):
                self.assertField("Validation fold", frame, text, **{"Validation fold": "F", "Folds": 3})
        frame["F"] = np.where(frame["Outcome"] == 1, 1, np.tile([2, 3], 30))
        self.assertField("Validation fold", frame, "need both outcomes", **{"Validation fold": "F", "Folds": 3})
        frame["F"] = ["one"] * 60
        self.assertField("Validation fold", frame, "contains text", **{"Validation fold": "F", "Folds": 3})

    def test_too_few_rows_per_outcome(self):
        frame = simulated(n=30, prevalence_shift=-4)
        events = int(frame["Outcome"].sum())
        self.assertField("Folds", frame, f"has {events}", Folds=events + 1)

    def test_option_ranges(self):
        frame = simulated(n=40)
        for field, value in (("Folds", 1), ("Folds", 21), ("Seed", -1), ("Seed", 2**32), ("Threshold", 1.5),
                             ("Calibration bins", 2), ("Calibration bins", 21), ("Folds", True)):
            with self.subTest(field=field, value=value):
                self.assertField(field, frame, **{field: value})
        self.assertField("Graph view", frame, **{"Graph view": "Pie"})

    def test_roles(self):
        frame = simulated(n=40)
        self.assertField("Predictors", frame, Predictors=["Outcome"], **{"Categorical predictors": []})
        self.assertField("Categorical predictors", frame, **{"Categorical predictors": ["Età %"],
                                                             "Predictors": ["Dose (mg)"]})
        self.assertField("Validation fold", frame, **{"Validation fold": "Dose (mg)"})
        frame["Clinic"] = "One"
        self.assertField("Categorical predictors", frame, "needs 2 to 100 levels")

    def test_budgets(self):
        frame = pd.DataFrame({"y": np.tile([0., 1.], 20)})
        for index in range(32):
            frame[f"x{index}"] = np.random.default_rng(index).normal(size=40)
        self.assertField("Predictors", frame, "33 coefficients", Response="y",
                         Predictors=[f"x{i}" for i in range(32)], **{"Categorical predictors": []})
        large = pd.DataFrame({"y": np.tile([0., 1.], 25_001), "x": np.zeros(50_002)})
        self.assertField("Predictors", large, "at most 50000", Response="y", Predictors=["x"],
                         **{"Categorical predictors": []})

    def test_rank_deficient(self):
        frame = simulated(n=50)
        frame["Copy"] = frame["Dose (mg)"] * 2
        self.assertField("Predictors", frame, "rank deficient", Predictors=["Dose (mg)", "Copy"],
                         **{"Categorical predictors": []})


class CancelTests(unittest.TestCase):
    def test_cancel_between_folds(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(lv.LogisticValidationCancelled) as caught:
            analyse(lv.METHOD, simulated(), OPTIONS, cancel=cancel)
        self.assertIsInstance(caught.exception, MonteCarloCancelled)
        self.assertIsInstance(caught.exception, InterruptedError)

    def test_cancel_after_some_folds(self):
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 2

        with self.assertRaises(lv.LogisticValidationCancelled):
            analyse(lv.METHOD, simulated(), OPTIONS, cancel=cancel)
        self.assertEqual(len(calls), 3)


class CatalogTests(unittest.TestCase):
    def test_registered(self):
        self.assertIn(lv.METHOD, GROUPS["Regression and Curves"])
        self.assertIn(lv.METHOD, GRAPH_METHODS)
        self.assertEqual(METHODS[lv.METHOD], lv.OPTIONS)

    def test_views_draw_their_panels(self):
        frame = simulated()
        for view, panels in ((lv.CALIBRATION_VIEW, 1), (lv.ROC_VIEW, 1), (lv.PR_VIEW, 1), (lv.ALL_VIEWS, 3)):
            with self.subTest(view=view):
                figure = run(frame, **{"Graph view": view}).figure
                self.assertEqual(len(figure.axes), panels)
        calibration = run(frame).figure.axes[0]
        labels = [text.get_text() for text in calibration.get_legend().get_texts()]
        self.assertTrue(any("area ∝ N" in label and "N = 240" in label for label in labels), labels)

    def test_legacy_logistic_family_still_uses_the_shared_fit(self):
        frame = simulated()
        legacy = analyse("Multiple regression", frame, {**OPTIONS, "Family": "Logistic"}).tables
        design = np.column_stack([np.ones(len(frame)), frame["Dose (mg)"], frame["Età %"],
                                  frame["Clinic"] == "North", frame["Clinic"] == "South"]).astype(float)
        direct = GLM(frame["Outcome"].to_numpy(), design, family=Binomial()).fit(maxiter=100).params
        np.testing.assert_allclose(legacy["Coefficients"]["Estimate"].to_numpy(), direct, rtol=1e-12)


if __name__ == "__main__":
    unittest.main()
