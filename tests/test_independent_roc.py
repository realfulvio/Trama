"""Compare independent ROC curves: formulas against exact references, invariants, errors and cancellation."""
from fractions import Fraction
from math import isclose, sqrt
from statistics import NormalDist, mean, variance
import threading
import unittest

import numpy as np
import pandas as pd

from analisi import independent_roc as engine
from analisi.field_error import FieldError
from analisi.monte_carlo import MonteCarloCancelled
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

METHOD = engine.METHOD
HIGHER, LOWER = engine.HIGHER, engine.LOWER
SEED = 20261118

# Synthetic worksheets: A has equal sizes, B has unequal sizes and blank cells.
COHORTS = pd.DataFrame({
    "C_A": [1, 2, 2, 4, 5, None, 0, None], "P_A": [2, 4, 5, 2, 7, 9, None, None],
    "C_B": [7, 6, 4, 8, 5, 7, 9, 5], "P_B": [4, 7, 1, 4, 6, None, 3, 0]})
TIED = pd.DataFrame({"C_A": [0, 0, 1, 2, 3], "P_A": [1, 1, 0, 3, 3], "C_B": [0, 2, 3, 3, 4], "P_B": [1, 0, 2, 4, 2]})
DEGENERATE = pd.DataFrame({"C_A": [1, 1, 2, 3], "P_A": [5, 5, 6, 7], "C_B": [0, 2, 3, 4], "P_B": [5, 5, 6, 7]})


def options(**overrides):
    return {"Control A": "C_A", "Patient A": "P_A", "Control B": "C_B", "Patient B": "P_B",
            "Direction A": HIGHER, "Direction B": HIGHER, "Area": "Full", "Inference": "DeLong",
            "Confidence level (%)": 95, **overrides}


def bootstrap(**overrides):
    return options(Inference="Percentile bootstrap", **{"Bootstrap replicates": 200, "Bootstrap seed": SEED,
                                                        "Save bootstrap": True, **overrides})


def run(frame, **overrides):
    return analyse(METHOD, frame, options(**overrides))


def row(result):
    return result.tables["ROC comparison"].iloc[0]


# ----- exact references ----------------------------------------------------------------------------------------------

def oriented(frame, column, direction):
    sign = 1 if direction == HIGHER else -1
    return sorted(sign * int(value) for value in frame[column].dropna())


def polygon(controls, patients):
    points = [(Fraction(0), Fraction(0))]
    for threshold in sorted(set(controls) | set(patients), reverse=True):
        points.append((Fraction(sum(value >= threshold for value in controls), len(controls)),
                       Fraction(sum(value >= threshold for value in patients), len(patients))))
    return points


def integrate(points, cutoff):
    total = Fraction(0)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 >= cutoff:
            break
        if x1 == x0:
            continue
        right = min(x1, cutoff)
        top = y0 + (right - x0) * (y1 - y0) / (x1 - x0)
        total += (right - x0) * (y0 + top) / 2
    return total


def scaled(area, cutoff, mode):
    if mode == "Standardized partial":
        chance = cutoff * cutoff / 2
        return (1 + (area - chance) / (cutoff - chance)) / 2
    return area


def delong(controls, patients):
    matrix = [[Fraction((p > c) + (p >= c), 2) for c in controls] for p in patients]
    per_patient = [mean(line) for line in matrix]
    per_control = [mean(column) for column in zip(*matrix)]
    return mean(per_patient), variance(per_patient) / len(patients) + variance(per_control) / len(controls)


class Reference:
    """Strata, polygons and areas of a worksheet, enumerated with exact rational numbers."""

    def __init__(self, frame, direction_a=HIGHER, direction_b=HIGHER, mode="Full", cutoff=None):
        self.strata = (oriented(frame, "C_A", direction_a), oriented(frame, "P_A", direction_a),
                       oriented(frame, "C_B", direction_b), oriented(frame, "P_B", direction_b))
        self.mode, self.cutoff = mode, Fraction(1) if mode == "Full" else Fraction(str(cutoff))

    def areas(self, strata=None):
        ca, pa, cb, pb = strata or self.strata
        raw = [integrate(polygon(c, p), self.cutoff) for c, p in ((ca, pa), (cb, pb))]
        return raw, [scaled(value, self.cutoff, self.mode) for value in raw]

    def replicates(self, count, seed):
        rng = np.random.Generator(np.random.PCG64(seed))
        found = []
        for _ in range(count):
            draw = [[values[j] for j in rng.integers(0, len(values), size=len(values))] for values in self.strata]
            found.append(self.areas(draw)[1])
        return found


# ----- formulas ------------------------------------------------------------------------------------------------------

class FullAreaTests(unittest.TestCase):
    def test_hand_values_and_delong_inference(self):
        result = run(COHORTS, **{"Direction B": LOWER})
        summary = row(result)
        self.assertEqual([summary[name] for name in ("Control A N", "Patient A N", "Control B N", "Patient B N")],
                         [6, 6, 8, 7])
        self.assertAlmostEqual(summary["Area A"], 7 / 9, places=14)
        self.assertAlmostEqual(summary["Area B"], 93 / 112, places=14)
        self.assertAlmostEqual(summary["Difference"], 7 / 9 - 93 / 112, places=14)
        self.assertAlmostEqual(summary["Variance of difference"], 0.030543604677320667, places=14)
        self.assertAlmostEqual(summary["p"], 0.7635261444243495, places=10)
        self.assertEqual(summary["Status"], engine.STATUS_DELONG)
        critical = NormalDist().inv_cdf(.975)
        self.assertAlmostEqual(summary["Lower"], summary["Difference"] - critical * summary["SE"], places=12)
        self.assertAlmostEqual(summary["Upper"], summary["Difference"] + critical * summary["SE"], places=12)

    def test_polygon_area_equals_the_mann_whitney_probability_and_the_variance_is_delong(self):
        rng = np.random.default_rng(5)
        for _ in range(25):
            sizes = rng.integers(2, 8, size=4)
            frame = pd.DataFrame({name: pd.Series(rng.integers(0, 6, size=size)) for name, size in
                                  zip(("C_A", "P_A", "C_B", "P_B"), sizes)})
            reference = Reference(frame)
            (pair_a, var_a), (pair_b, var_b) = (delong(reference.strata[0], reference.strata[1]),
                                                delong(reference.strata[2], reference.strata[3]))
            summary = row(run(frame))
            self.assertAlmostEqual(summary["Area A"], float(pair_a), places=13)
            self.assertAlmostEqual(summary["Area B"], float(pair_b), places=13)
            self.assertAlmostEqual(summary["Variance of difference"], float(var_a + var_b), places=13)

    def test_swapping_markers_changes_the_sign_and_exchanges_the_limits(self):
        swapped = {"Control A": "C_B", "Patient A": "P_B", "Control B": "C_A", "Patient B": "P_A"}
        first, second = row(run(COHORTS)), row(run(COHORTS, **swapped))
        self.assertAlmostEqual(first["Difference"], -second["Difference"], places=14)
        self.assertAlmostEqual(first["Lower"], -second["Upper"], places=13)
        self.assertAlmostEqual(first["Upper"], -second["Lower"], places=13)
        self.assertAlmostEqual(first["Z"], -second["Z"], places=13)
        self.assertAlmostEqual(first["p"], second["p"], places=13)
        self.assertAlmostEqual(first["Variance of difference"], second["Variance of difference"], places=15)

    def test_a_lower_direction_on_negated_data_is_the_higher_direction(self):
        negated = -COHORTS
        high = row(run(COHORTS, **{"Direction B": HIGHER}))
        low = row(run(negated, **{"Direction B": LOWER, "Direction A": LOWER}))
        for name in ("Area A", "Area B", "Difference", "Variance of difference", "p"):
            self.assertAlmostEqual(high[name], low[name], places=14)
        curves = run(negated, **{"Direction A": LOWER, "Direction B": LOWER}).tables
        original = run(COHORTS).tables
        np.testing.assert_allclose(curves["ROC curve A"]["Threshold"].to_numpy()[1:],
                                   -original["ROC curve A"]["Threshold"].to_numpy()[1:])

    def test_equal_distributions_with_ties_give_one_half(self):
        frame = pd.DataFrame({name: [3, 3, 3, 3] for name in ("C_A", "P_A", "C_B", "P_B")})
        summary = row(run(frame))
        self.assertEqual((summary["Area A"], summary["Area B"], summary["Difference"]), (.5, .5, 0))
        self.assertEqual(summary["Status"], engine.STATUS_ZERO)

    def test_zero_variance_keeps_the_estimates_and_leaves_the_inference_empty(self):
        summary = row(run(DEGENERATE))
        self.assertEqual((summary["Area A"], summary["Area B"], summary["Difference"],
                          summary["Variance of difference"], summary["SE"]), (1, 1, 0, 0, 0))
        for name in ("Z", "p", "Lower", "Upper"):
            self.assertTrue(np.isnan(summary[name]), name)
        self.assertEqual(summary["Status"], engine.STATUS_ZERO)
        self.assertIn("not defined", summary["Note"])

    def test_the_interval_is_cut_at_one(self):
        frame = pd.DataFrame({"C_A": [0, 1, 2, 3], "P_A": [10, 11, 12, 1], "C_B": [0, 1, 2, 3], "P_B": [1, 1, 1, 1]})
        summary = row(run(frame, **{"Confidence level (%)": 99.9}))
        self.assertLessEqual(summary["Upper"], 1.0)
        self.assertGreaterEqual(summary["Lower"], -1.0)

    def test_a_very_small_p_value_is_not_rounded_to_one_or_nan(self):
        frame = pd.DataFrame({"C_A": np.arange(40.0), "P_A": np.arange(40.0) + 100,
                              "C_B": np.arange(40.0), "P_B": np.arange(40.0) + 20})
        summary = row(run(frame))
        self.assertTrue(0 <= summary["p"] <= 1)

    def test_curve_sheets_have_the_origin_and_one_row_per_distinct_oriented_score(self):
        tables = run(COHORTS, **{"Direction B": LOWER}).tables
        curve = tables["ROC curve B"]
        self.assertTrue(np.isnan(curve["Threshold"].iloc[0]))
        self.assertEqual(list(curve.iloc[0, 1:]), [0, 0])
        self.assertEqual(list(curve.iloc[-1, 1:]), [1, 1])
        # Lower in patients: the oriented order runs from the lowest original score upwards.
        self.assertEqual(list(curve["Threshold"].iloc[1:]), sorted(curve["Threshold"].iloc[1:]))
        self.assertEqual(len(curve), 1 + len(set(COHORTS["C_B"].dropna()) | set(COHORTS["P_B"].dropna())))


class PartialAreaTests(unittest.TestCase):
    def test_hand_values_with_ties(self):
        areas = row(run(TIED, **{"Area": "Partial", "Maximum FPR": .35, "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(areas["Area A"], .10, places=14)
        self.assertAlmostEqual(areas["Area B"], .05, places=14)
        standardized = row(run(TIED, **{"Area": "Standardized partial", "Maximum FPR": .35,
                                         "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(standardized["Area A"], 0.5670995670995671, places=13)
        self.assertAlmostEqual(standardized["Area B"], 0.4805194805194805, places=13)
        self.assertLess(standardized["Area B"], .5)
        self.assertAlmostEqual(standardized["Raw area A"], .10, places=14)
        self.assertAlmostEqual(standardized["Difference"], standardized["Area A"] - standardized["Area B"], places=14)

    def test_a_cutoff_through_diagonal_ties_interpolates_the_segment(self):
        summary = row(run(TIED, **{"Area": "Partial", "Maximum FPR": .15, "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(summary["Raw area A"], .0225, places=14)
        self.assertAlmostEqual(summary["Raw area B"], .01125, places=14)

    def test_random_worksheets_match_the_exact_polygon(self):
        rng = np.random.default_rng(11)
        for _ in range(40):
            sizes = rng.integers(2, 9, size=4)
            frame = pd.DataFrame({name: pd.Series(rng.integers(0, 5, size=size)) for name, size in
                                  zip(("C_A", "P_A", "C_B", "P_B"), sizes)})
            directions = [HIGHER, LOWER][int(rng.integers(0, 2))], [HIGHER, LOWER][int(rng.integers(0, 2))]
            cutoff = float(rng.choice([.05, .2, .35, .5, .75, .99]))
            for mode in ("Full", "Partial", "Standardized partial"):
                reference = Reference(frame, *directions, mode, cutoff)
                raw, adjusted = reference.areas()
                request = options(**{"Direction A": directions[0], "Direction B": directions[1], "Area": mode,
                                     "Maximum FPR": cutoff, "Inference": engine.BOOTSTRAP,
                                     "Bootstrap replicates": 200})
                summary = row(analyse(METHOD, frame, request))
                self.assertAlmostEqual(summary["Raw area A"], float(raw[0]), places=13)
                self.assertAlmostEqual(summary["Raw area B"], float(raw[1]), places=13)
                self.assertAlmostEqual(summary["Area A"], float(adjusted[0]), places=13)
                self.assertAlmostEqual(summary["Area B"], float(adjusted[1]), places=13)

    def test_the_whole_range_equals_the_full_area_and_cutoffs_near_the_ends_are_stable(self):
        full = row(run(COHORTS))
        near_one = row(run(COHORTS, **{"Area": "Partial", "Maximum FPR": 1 - 1e-12, "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(near_one["Raw area A"], full["Area A"], places=10)
        near_one = row(run(COHORTS, **{"Area": "Standardized partial", "Maximum FPR": 1 - 1e-9,
                                       "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(near_one["Area A"], full["Area A"], places=6)
        tiny = row(run(COHORTS, **{"Area": "Partial", "Maximum FPR": 1e-9, "Inference": engine.BOOTSTRAP}))
        self.assertTrue(0 <= tiny["Raw area A"] <= 1e-9)
        self.assertTrue(0 <= tiny["Raw area B"] <= 1e-9)

    def test_vertical_steps_before_and_after_the_cutoff_add_no_area(self):
        # A perfect marker climbs vertically at FPR 0; one that only separates late stays under the diagonal.
        frame = pd.DataFrame({"C_A": [1, 2, 3], "P_A": [10, 11, 12], "C_B": [10, 11, 12], "P_B": [1, 2, 3]})
        summary = row(run(frame, **{"Area": "Partial", "Maximum FPR": .5, "Inference": engine.BOOTSTRAP}))
        self.assertAlmostEqual(summary["Raw area A"], .5, places=14)
        self.assertAlmostEqual(summary["Raw area B"], 0, places=14)
        self.assertAlmostEqual(row(run(frame, **{"Area": "Standardized partial", "Maximum FPR": .5,
                                                 "Inference": engine.BOOTSTRAP}))["Area A"], 1, places=14)

    def test_the_standardized_area_is_one_half_on_the_diagonal_and_one_for_a_perfect_curve(self):
        self.assertAlmostEqual(engine.standardize(.5 * .3 * .3, .3), .5)
        self.assertAlmostEqual(engine.standardize(.3, .3), 1)
        self.assertLess(engine.standardize(.01, .3), .5)


# ----- bootstrap -----------------------------------------------------------------------------------------------------

class BootstrapTests(unittest.TestCase):
    def test_replicates_match_the_exact_resampling_with_the_published_stream(self):
        frame = pd.DataFrame({"C_A": [0, 0, 1, 2, 3, 5], "P_A": [1, 1, 0, 3, 3, 4], "C_B": [0, 2, 3, 3, 4, 4],
                              "P_B": [1, 0, 2, 4, 2, 6]})
        for mode, cutoff in (("Full", None), ("Partial", .3), ("Standardized partial", .6)):
            result = analyse(METHOD, frame, bootstrap(**{"Area": mode, "Maximum FPR": cutoff}))
            expected = Reference(frame, mode=mode, cutoff=cutoff).replicates(200, SEED)
            found = result.tables["ROC bootstrap"]
            np.testing.assert_allclose(found[["Area A", "Area B"]].to_numpy(), np.array(expected, dtype=float),
                                       atol=1e-13)
            np.testing.assert_allclose(found["Difference"], found["Area A"] - found["Area B"], atol=1e-15)
            self.assertEqual(list(found["Replicate"]), list(range(1, 201)))

    def test_summary_is_the_percentile_interval_of_the_difference(self):
        result = run(COHORTS, **{"Inference": engine.BOOTSTRAP, "Bootstrap replicates": 300, "Bootstrap seed": 3,
                                 "Save bootstrap": True, "Confidence level (%)": 90})
        differences = result.tables["ROC bootstrap"]["Difference"].to_numpy()
        summary = row(result)
        low, high = np.quantile(differences, [.05, .95], method="linear")
        self.assertAlmostEqual(summary["Lower"], low, places=14)
        self.assertAlmostEqual(summary["Upper"], high, places=14)
        self.assertAlmostEqual(summary["Variance of difference"], float(np.var(differences, ddof=1)), places=14)
        self.assertAlmostEqual(summary["SE"], sqrt(summary["Variance of difference"]), places=14)
        self.assertTrue(np.isnan(summary["Z"]) and np.isnan(summary["p"]))
        self.assertEqual((summary["Bootstrap replicates"], summary["Bootstrap seed"]), (300, 3))
        self.assertEqual(summary["Status"], engine.STATUS_BOOTSTRAP)
        self.assertIn("percentile", summary["Note"])

    def test_saving_the_replicates_does_not_change_the_summary(self):
        saved = run(COHORTS, **{"Inference": engine.BOOTSTRAP, "Bootstrap seed": 8, "Save bootstrap": True})
        kept = run(COHORTS, **{"Inference": engine.BOOTSTRAP, "Bootstrap seed": 8, "Save bootstrap": False})
        self.assertIn("ROC bootstrap", saved.tables)
        self.assertNotIn("ROC bootstrap", kept.tables)
        pd.testing.assert_frame_equal(saved.tables["ROC comparison"], kept.tables["ROC comparison"])

    def test_prefix_row_permutation_and_seed(self):
        short = analyse(METHOD, COHORTS, bootstrap(**{"Bootstrap replicates": 200})).tables["ROC bootstrap"]
        long = analyse(METHOD, COHORTS, bootstrap(**{"Bootstrap replicates": 260})).tables["ROC bootstrap"]
        pd.testing.assert_frame_equal(short, long.iloc[:200])
        reversed_rows = analyse(METHOD, COHORTS.iloc[::-1], bootstrap()).tables["ROC bootstrap"]
        pd.testing.assert_frame_equal(short, reversed_rows)
        other = analyse(METHOD, COHORTS, bootstrap(**{"Bootstrap seed": SEED + 1})).tables["ROC bootstrap"]
        self.assertTrue((other["Difference"] != short["Difference"]).any())

    def test_a_constant_distribution_gives_a_point_interval_with_a_degeneration_note(self):
        frame = pd.DataFrame({"C_A": [1, 1, 1], "P_A": [2, 2, 2], "C_B": [3, 3, 3], "P_B": [4, 4, 4]})
        summary = row(analyse(METHOD, frame, bootstrap()))
        self.assertEqual((summary["Variance of difference"], summary["SE"], summary["Difference"]), (0, 0, 0))
        self.assertEqual(summary["Lower"], summary["Upper"])
        self.assertEqual(summary["Status"], engine.STATUS_CONSTANT)
        self.assertIn("single point", summary["Note"])
        self.assertNotEqual(engine.STATUS_CONSTANT, engine.STATUS_ZERO)

    def test_the_budget_is_checked_before_any_sample_is_drawn(self):
        big = pd.concat([TIED] * 251, ignore_index=True)       # 5 020 observations
        original = engine._bootstrap
        engine._bootstrap = lambda *args, **kwargs: self.fail("the bootstrap must not start")
        try:
            with self.assertRaises(FieldError) as caught:
                analyse(METHOD, big, bootstrap(**{"Bootstrap replicates": 1000}))
            self.assertEqual(caught.exception.field, "Bootstrap replicates")
            self.assertIn("5,000,000", str(caught.exception))
        finally:
            engine._bootstrap = original
        # The same data fits with fewer replicates.
        self.assertIn("ROC bootstrap", analyse(METHOD, big, bootstrap(**{"Bootstrap replicates": 900})).tables)

    def test_the_budget_ignores_the_replicates_of_a_delong_calculation(self):
        big = pd.concat([TIED] * 251, ignore_index=True)
        result = analyse(METHOD, big, options(**{"Bootstrap replicates": 10_000}))
        self.assertEqual(row(result)["Status"], engine.STATUS_DELONG)


class CancellationTests(unittest.TestCase):
    def test_an_event_that_is_already_set_stops_both_inferences_before_any_work(self):
        cancelled = threading.Event()
        cancelled.set()
        for request in (bootstrap(), options()):
            with self.assertRaises(engine.IndependentRocCancelled):
                analyse(METHOD, COHORTS, request, cancel=cancelled)
        self.assertTrue(issubclass(engine.IndependentRocCancelled, MonteCarloCancelled))

    def test_the_event_is_read_between_blocks_and_after_the_last_one(self):
        class CancelAfter:
            """An event that turns on after a number of reads: the worker must keep looking at it."""

            def __init__(self, reads):
                self.reads, self.count = reads, 0

            def is_set(self):
                self.count += 1
                return self.count > self.reads

        frame = pd.concat([COHORTS] * 40, ignore_index=True)        # 1 080 observations: blocks of 46 replicates
        for reads in (1, 3, 8):
            event = CancelAfter(reads)
            with self.assertRaises(engine.IndependentRocCancelled):
                analyse(METHOD, frame, bootstrap(**{"Bootstrap replicates": 400}), cancel=event)
            self.assertGreater(event.count, reads)
        # A calculation that is never cancelled still publishes everything.
        free = CancelAfter(10 ** 9)
        result = analyse(METHOD, frame, bootstrap(**{"Bootstrap replicates": 400}), cancel=free)
        self.assertEqual(len(result.tables["ROC bootstrap"]), 400)
        self.assertGreaterEqual(free.count, 400 // 46 + 2)

    def test_cancelling_a_thread_stops_a_long_bootstrap_quickly(self):
        frame = pd.concat([COHORTS] * 300, ignore_index=True)       # 15 000 observations, B = 300
        cancelled, outcome = threading.Event(), []

        def work():
            try:
                analyse(METHOD, frame, bootstrap(**{"Bootstrap replicates": 300}), cancel=cancelled)
            except engine.IndependentRocCancelled:
                outcome.append("cancelled")
            else:
                outcome.append("finished")

        thread = threading.Thread(target=work)
        thread.start()
        cancelled.set()
        thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ["cancelled"])


# ----- fields and errors ---------------------------------------------------------------------------------------------

class FieldErrorTests(unittest.TestCase):
    def field(self, frame=COHORTS, expected=None, **overrides):
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, frame, options(**overrides))
        if expected is not None:
            self.assertEqual(caught.exception.field, expected, str(caught.exception))
        return str(caught.exception)

    def partial(self, **overrides):
        return {"Area": "Partial", "Inference": engine.BOOTSTRAP, "Maximum FPR": .3, **overrides}

    def test_column_selection_errors_name_the_field_of_the_second_use(self):
        self.field(expected="Patient B", **{"Patient B": "C_A"})
        self.field(expected="Control B", **{"Control B": "P_A"})
        self.field(expected="Patient A", **{"Patient A": "C_A"})
        self.field(expected="Control A", **{"Control A": "missing"})
        self.field(expected="Patient B", **{"Patient B": ""})
        self.field(expected="Patient A", **{"Patient A": None})
        self.assertIn("already used for Control A", self.field(expected="Patient A", **{"Patient A": "C_A"}))

    def test_a_sample_with_fewer_than_two_values_names_its_column_field(self):
        frame = COHORTS.copy()
        frame.loc[1:, "P_B"] = np.nan
        self.field(frame, "Patient B")
        frame = COHORTS.copy()
        frame["C_A"] = [1.0] + [np.nan] * 7
        self.field(frame, "Control A")
        # Another column keeping its values does not hide the problem.
        frame["C_A"] = [1.0, 2.0] + [np.nan] * 6
        self.assertEqual(row(run(frame))["Control A N"], 2)

    def test_text_and_infinite_values_name_their_field(self):
        text = COHORTS.astype({"P_A": object})
        text.loc[0, "P_A"] = "abc"
        self.assertIn("text or infinite", self.field(text, "Patient A"))
        infinite = COHORTS.astype({"C_B": float})
        infinite.loc[0, "C_B"] = np.inf
        self.field(infinite, "Control B")
        complex_values = COHORTS.astype({"C_A": object})
        complex_values.loc[0, "C_A"] = 1 + 2j
        self.field(complex_values, "Control A")

    def test_integers_beyond_double_precision_are_refused(self):
        frame = pd.DataFrame({"C_A": [2 ** 60, 2 ** 60 + 1], "P_A": [1, 2], "C_B": [1, 2], "P_B": [3, 4]})
        self.assertIn("precision", self.field(frame, "Control A"))

    def test_cutoff_direction_inference_and_level_errors(self):
        for cutoff in (0, 1, -.1, 1.5, float("nan"), float("inf"), None, "abc", "", True):
            self.field(expected="Maximum FPR", **self.partial(**{"Maximum FPR": cutoff}))
        self.field(expected="Direction A", **{"Direction A": "Automatic"})
        self.field(expected="Direction B", **{"Direction B": None})
        self.field(expected="Area", Area="Everything")
        self.field(expected="Inference", Inference="Permutation")
        self.field(expected="Inference", **{"Area": "Partial", "Maximum FPR": .3})
        self.field(expected="Inference", **{"Area": "Standardized partial", "Maximum FPR": .3})
        for level in (0, 100, -5, 120, float("nan"), "x"):
            self.field(expected="Confidence level (%)", **{"Confidence level (%)": level})

    def test_a_decimal_comma_is_accepted_for_the_cutoff_and_the_level(self):
        comma = row(run(TIED, **self.partial(**{"Maximum FPR": "0,15", "Confidence level (%)": "90,5"})))
        dot = row(run(TIED, **self.partial(**{"Maximum FPR": .15, "Confidence level (%)": 90.5})))
        pd.testing.assert_series_equal(comma, dot)

    def test_replicates_and_seed_must_be_whole_numbers_in_range(self):
        for replicates in (199, 10_001, 200.5, 250.0, -300, "x", None, True, float("nan")):
            self.field(expected="Bootstrap replicates", **self.partial(**{"Bootstrap replicates": replicates}))
        for seed in (-1, 2 ** 32, 1.5, 3.0, "x", None, True):
            self.field(expected="Bootstrap seed", **self.partial(**{"Bootstrap seed": seed}))
        self.field(expected="Save bootstrap", **self.partial(**{"Save bootstrap": "yes"}))
        self.assertEqual(row(analyse(METHOD, TIED, bootstrap(**{"Bootstrap seed": 2 ** 32 - 1}))
                             )["Bootstrap seed"], 2 ** 32 - 1)
        self.assertEqual(row(analyse(METHOD, TIED, bootstrap(**{"Bootstrap seed": "12"})))["Bootstrap seed"], 12)

    def test_inactive_fields_are_neither_read_nor_validated(self):
        reference = row(run(COHORTS))
        for hidden in ({"Maximum FPR": None}, {"Maximum FPR": "abc"}, {"Maximum FPR": 7},
                       {"Bootstrap replicates": 1.5, "Bootstrap seed": -4, "Save bootstrap": "x"}):
            pd.testing.assert_series_equal(row(run(COHORTS, **hidden)), reference, check_exact=True)

    def test_the_total_number_of_observations_is_limited(self):
        too_many = pd.DataFrame({name: np.arange(25_001.0) for name in ("C_A", "P_A", "C_B", "P_B")})
        self.assertIn("100,000", self.field(too_many, "Control A"))
        with self.assertRaises(FieldError):
            analyse(METHOD, too_many, bootstrap())
        # Exactly at the limit is accepted, with DeLong too.
        limit = pd.DataFrame({name: np.arange(25_000.0) for name in ("C_A", "P_A", "C_B", "P_B")})
        self.assertEqual(row(run(limit))["Status"], engine.STATUS_DELONG)

    def test_options_must_be_a_mapping(self):
        with self.assertRaises(FieldError):
            engine.check_options(COHORTS, None)

    def test_check_options_returns_the_typed_settings_and_sizes(self):
        settings, sizes = engine.check_options(COHORTS, options(**self.partial(**{
            "Maximum FPR": "0,3", "Bootstrap replicates": "250", "Bootstrap seed": "7", "Save bootstrap": True})))
        self.assertEqual((settings["Maximum FPR"], settings["Bootstrap replicates"], settings["Bootstrap seed"]),
                         (.3, 250, 7))
        self.assertEqual(sizes, {"Control A": 6, "Patient A": 6, "Control B": 8, "Patient B": 7})
        typed = engine.normalized_options(options(**self.partial(**{
            "Maximum FPR": "0,3", "Bootstrap replicates": "250", "Bootstrap seed": "7"})), settings)
        self.assertEqual((typed["Maximum FPR"], typed["Bootstrap replicates"], typed["Bootstrap seed"]), (.3, 250, 7))


# ----- registration and figure ---------------------------------------------------------------------------------------

class RegistrationAndFigureTests(unittest.TestCase):
    def test_the_method_is_registered_with_its_defaults(self):
        self.assertIn(METHOD, GROUPS["Group Comparison"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(list(METHODS[METHOD])[:4], ["Control A", "Patient A", "Control B", "Patient B"])
        self.assertEqual(METHODS[METHOD]["Area"], engine.AREAS)
        self.assertEqual(METHODS[METHOD]["Inference"], engine.INFERENCES)
        self.assertEqual(engine.visibility("Full", "DeLong"),
                         {"Maximum FPR": False, "Bootstrap replicates": False, "Bootstrap seed": False,
                          "Save bootstrap": False})
        self.assertEqual(engine.visibility("Partial", engine.BOOTSTRAP)["Maximum FPR"], True)
        self.assertEqual(engine.proposed_inference("Partial", "DeLong"), engine.BOOTSTRAP)
        self.assertEqual(engine.proposed_inference("Full", "DeLong"), "DeLong")
        self.assertTrue(engine.cancellable(METHOD, {"Inference": engine.BOOTSTRAP}))
        self.assertFalse(engine.cancellable(METHOD, {"Inference": "DeLong"}))
        self.assertFalse(engine.cancellable("Compare paired ROC curves", {"Inference": engine.BOOTSTRAP}))

    def test_the_figure_shows_the_band_the_cutoff_and_both_curves(self):
        result = analyse(METHOD, TIED, options(**{"Area": "Partial", "Maximum FPR": .35,
                                                  "Inference": engine.BOOTSTRAP, "Bootstrap replicates": 200}))
        axes, = result.figure.axes
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), ((0, 1), (0, 1)))
        by_gid = {artist.get_gid(): artist for artist in (*axes.lines, *axes.patches) if artist.get_gid()}
        self.assertEqual(set(by_gid), {"independent-roc:curve-a", "independent-roc:curve-b",
                                       "independent-roc:diagonal", "independent-roc:band", "independent-roc:cutoff"})
        self.assertEqual(list(by_gid["independent-roc:cutoff"].get_xdata()), [.35, .35])
        band = by_gid["independent-roc:band"]
        self.assertEqual((band.get_x(), band.get_x() + band.get_width()), (0, .35))
        for letter, sheet in (("a", "ROC curve A"), ("b", "ROC curve B")):
            line = by_gid[f"independent-roc:curve-{letter}"]
            curve = result.tables[sheet]
            np.testing.assert_allclose(line.get_xdata(), curve["False positive rate"])
            np.testing.assert_allclose(line.get_ydata(), curve["True positive rate"])
        legend = [text.get_text() for text in axes.get_legend().get_texts()]
        self.assertTrue(any("A (P_A vs C_A): pAUC 0.1" in text for text in legend), legend)
        self.assertIn("pAUC (FPR ≤ 0.35)", axes.get_title())
        self.assertTrue(all(not text.get_parse_math() for text in axes.get_legend().get_texts()))

    def test_a_full_area_graph_has_no_band_or_cutoff(self):
        axes, = run(COHORTS).figure.axes
        gids = {artist.get_gid() for artist in (*axes.lines, *axes.patches)}
        self.assertNotIn("independent-roc:band", gids)
        self.assertNotIn("independent-roc:cutoff", gids)
        self.assertIn("AUC 0.7778", [text.get_text() for text in axes.get_legend().get_texts()][0])

    def test_column_names_with_dollar_signs_stay_literal(self):
        frame = COHORTS.rename(columns={"P_A": "$P_A$", "C_A": "$C_A$"})
        result = analyse(METHOD, frame, options(**{"Control A": "$C_A$", "Patient A": "$P_A$"}))
        axes, = result.figure.axes
        self.assertTrue(all(not text.get_parse_math() for text in axes.get_legend().get_texts()))
        self.assertIn("$P_A$ vs $C_A$", axes.get_legend().get_texts()[0].get_text())

    def test_the_existing_roc_methods_are_untouched(self):
        paired = analyse("Compare paired ROC curves", TIED, {
            "Control A": "C_A", "Patient A": "P_A", "Control B": "C_B", "Patient B": "P_B",
            "Direction A": HIGHER, "Direction B": HIGHER})
        self.assertEqual(list(paired.tables), ["Paired ROC comparison", "Curve points A", "Curve points B"])
        self.assertTrue(isclose(paired.tables["Paired ROC comparison"]["Value"]["AUC A"], .60))
        single = analyse("ROC curve", TIED, {"Control": "C_A", "Patient": "P_A", "Direction": HIGHER})
        self.assertIn("ROC summary", single.tables)


if __name__ == "__main__":
    unittest.main()
