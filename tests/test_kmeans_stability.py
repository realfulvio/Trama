"""K-means stability: partitions, seeds, projection, budgets, failures, cancellation, sheets and figure."""
from fractions import Fraction
from itertools import combinations, permutations
import json
from pathlib import Path
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from analisi import kmeans_stability as ks
from analisi.field_error import FieldError
from analisi.hartigan_wong import IterationLimitError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse
from tests.test_parallel import ready_workers

DATA = Path(__file__).resolve().parent / "data" / "kmeans_stability"
VARIABLES = ["Marker A", "Marker B"]


def separated():
    return pd.read_csv(DATA / "separated.csv")


def options(**changes):
    values = {"Variables": VARIABLES, "Minimum k": 2, "Maximum k": 3, "Standardize": True, "K-means algorithm": "Lloyd",
              "Seed": 33, "Resamples": 8, "Sample fraction (%)": 80, "Report k": 3, "Seed runs": 0,
              "Show co-assignment matrix": False}
    values.update(changes)
    return values


def oracle(reference, candidate, k):
    """Independent of the engine: pair counting and enumeration of all matchings."""
    a = b = c = t = 0
    for i, j in combinations(range(len(reference)), 2):
        a += reference[i] == reference[j] and candidate[i] == candidate[j]
        b += reference[i] == reference[j]
        c += candidate[i] == candidate[j]
        t += 1
    denominator = (b + c) * t - 2 * b * c
    ari = Fraction(2 * a * t - 2 * b * c, denominator) if denominator else Fraction(1)
    mapping = max(permutations(range(1, k + 1)),
                  key=lambda match: sum(match[r - 1] == o for r, o in zip(reference, candidate, strict=True)))
    remap = {source: target for target, source in enumerate(mapping, 1)}
    aligned = [remap[value] for value in candidate]
    jaccard = []
    for label in range(1, k + 1):
        left = {i for i, value in enumerate(reference) if value == label}
        right = {i for i, value in enumerate(aligned) if value == label}
        jaccard.append(Fraction(len(left & right), len(left | right)))
    return {"ari": ari, "mapping": list(mapping), "jaccard": jaccard, "aligned": aligned}


class PartitionTests(unittest.TestCase):
    def test_manual_cases(self):
        for case in json.loads((DATA / "partition-cases.json").read_text(encoding="utf-8")):
            with self.subTest(case["name"]):
                found = ks.compare_partitions(np.asarray(case["reference"]), np.asarray(case["candidate"]), case["k"])
                expected = case["expected"]
                self.assertEqual(list(found), ["ari", "mapping", "jaccard", "aligned"])
                self.assertEqual(list(found["mapping"]), expected["mapping"])
                self.assertEqual(list(found["aligned"]), expected["aligned"])
                self.assertAlmostEqual(found["ari"], float(Fraction(expected["ari"])), places=14)
                np.testing.assert_allclose(found["jaccard"], [float(Fraction(v)) for v in expected["jaccard"]],
                                           rtol=0, atol=1e-15)

    def test_random_partitions_match_enumeration(self):
        rng = np.random.default_rng(7)
        for trial in range(300):
            k = int(rng.integers(1, 5))
            n = int(rng.integers(k, 12))
            reference = np.r_[np.arange(1, k + 1), rng.integers(1, k + 1, n - k)]
            candidate = np.r_[rng.permutation(np.arange(1, k + 1)), rng.integers(1, k + 1, n - k)]
            rng.shuffle(reference)
            found = ks.compare_partitions(reference, candidate, k)
            expected = oracle(list(reference), list(candidate), k)
            self.assertEqual(list(found["mapping"]), expected["mapping"], trial)
            self.assertEqual(list(found["aligned"]), expected["aligned"], trial)
            self.assertAlmostEqual(found["ari"], float(expected["ari"]), places=13)
            np.testing.assert_allclose(found["jaccard"], [float(v) for v in expected["jaccard"]], atol=1e-15)

    def test_ari_ignores_labels_and_handles_degenerate_partitions(self):
        self.assertEqual(ks.adjusted_rand([1, 1, 2, 2], [7, 7, 3, 3]), 1.0)
        self.assertEqual(ks.adjusted_rand([1, 2, 3], [3, 1, 2]), 1.0)  # all singletons: denominator zero
        self.assertEqual(ks.adjusted_rand([1, 1, 1], [2, 2, 2]), 1.0)  # one group each: denominator zero
        self.assertEqual(ks.adjusted_rand([4], [4]), 1.0)
        self.assertLess(ks.adjusted_rand([1, 1, 2, 2], [1, 2, 1, 2]), 0)

    def test_compare_rejects_bad_input(self):
        for reference, candidate, k in (([1, 2], [1, 2, 2], 2), ([1, 1], [1, 2], 2), ([1, 3], [1, 2], 2),
                                        ([1.5, 2], [1, 2], 2), ([1, 2], [1, 2], 0), ([1, 2], [1, 2], True)):
            with self.subTest(reference=reference, candidate=candidate, k=k), self.assertRaises(ValueError):
                ks.compare_partitions(np.asarray(reference), np.asarray(candidate), k)


class SeedAndProjectionTests(unittest.TestCase):
    def test_streams_are_fixed_and_independent(self):
        self.assertEqual(ks.fit_seed(42, 3, 0, ks.REFERENCE),
                         int(np.random.SeedSequence([42, 3, 0, 20]).generate_state(1, dtype=np.uint32)[0]))
        seeds = {ks.fit_seed(42, 3, 1, kind) for kind in (ks.REFERENCE, ks.SUBSAMPLE, ks.SEED_RUN)}
        self.assertEqual(len(seeds), 3)
        draw = np.random.Generator(np.random.PCG64(np.random.SeedSequence([42, 0, 5, 10]))).choice(30, 24, False)
        np.testing.assert_array_equal(ks.sample_positions(42, 5, 30, 24), np.sort(draw))
        self.assertFalse(np.array_equal(ks.sample_positions(42, 5, 30, 24), ks.sample_positions(42, 6, 30, 24)))
        self.assertEqual(ks.sample_size(18, 80), 14)
        self.assertEqual(ks.sample_size(10, 57.3), 5)
        self.assertEqual(ks.sample_size(1000, 57.3), 573)  # decimal value, not the binary approximation

    def test_equidistant_row_goes_to_lower_cluster(self):
        centers = np.array([[1.0, 0.0], [-1.0, 0.0]])
        labels = ks.project(np.array([[0.0, 5.0], [0.9, 0.0], [-3.0, 1.0]]), centers)
        np.testing.assert_array_equal(labels, [1, 1, 2])
        labels = ks.project(np.array([[0.0, 0.0]]), centers[::-1])
        np.testing.assert_array_equal(labels, [1])

    def test_subsample_learns_its_own_scale(self):
        values = np.column_stack([np.arange(20.0), np.r_[np.zeros(10), np.full(10, 50.0)] + np.arange(20) % 3])
        reference = np.r_[np.ones(10, dtype=int), np.full(10, 2)]
        seen = {}
        original = ks.project

        def spy(rows, centers, mean=None, sd=None):
            seen.update(mean=mean, sd=sd)
            return original(rows, centers, mean, sd)

        with mock.patch.object(ks, "project", spy):
            outcome = ks._subsample_task(values, 2, 3, True, 9, {}, 16, reference, True)
        positions = ks.sample_positions(9, 3, 20, 16)
        np.testing.assert_array_equal(seen["mean"], values[positions].mean(axis=0))
        np.testing.assert_array_equal(seen["sd"], values[positions].std(axis=0, ddof=1))
        self.assertEqual(outcome["status"], ks.OK)
        with mock.patch.object(ks, "project", spy):
            ks._subsample_task(values, 2, 3, False, 9, {}, 16, reference, False)
        self.assertIsNone(seen["mean"])


class PreparationTests(unittest.TestCase):
    def test_rows_keep_frame_positions(self):
        frame = separated().assign(Constant=1.0)
        frame.iloc[2, 0] = np.inf  # infinite: an incomplete row, like a gap
        frame.index = ["same"] * len(frame)  # duplicate labels: positions decide, never labels
        plan = ks.prepare(frame, options(Variables=["Marker A", "Marker B", "Constant"], Standardize=False))
        self.assertEqual(plan.worksheet_rows, 20)
        self.assertEqual(list(plan.rows), [r for r in range(1, 21) if r not in {3, 6, 15}])
        self.assertEqual(plan.n, 17)
        self.assertEqual(plan.sample, 13)
        with self.assertRaises(FieldError) as caught:
            ks.prepare(frame, options(Variables=["Marker A", "Constant"]))
        self.assertEqual(caught.exception.field, "Variables")

    def test_text_and_missing_columns(self):
        frame = separated().assign(Note=["x"] + [None] * 19)
        for variables in (["Marker A", "Note"], ["Marker A", "Absent"], ["Marker A", "Marker A"], [], "Note"):
            with self.subTest(variables), self.assertRaises(FieldError) as caught:
                ks.prepare(frame, options(Variables=variables))
            self.assertEqual(caught.exception.field, "Variables")
        twins = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], columns=["X", "X"])
        with self.assertRaises(FieldError):
            ks.prepare(twins, options(Variables=["X"]))

    def test_field_validation(self):
        frame = separated()
        cases = {"Minimum k": [1, 13, "two", True, 2.5], "Maximum k": [1, 13], "Seed": [-1, 2**32],
                 "Resamples": [4, 2001], "Sample fraction (%)": [49.9, 95.1, float("nan"), "abc", True],
                 "Seed runs": [-1, 101], "Report k": [4, 1], "Standardize": ["yes"],
                 "Show co-assignment matrix": [1], "K-means algorithm": ["Elkan"]}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(FieldError) as caught:
                    ks.prepare(frame, options(**{field: value}))
                self.assertEqual(caught.exception.field, field)
        plan = ks.prepare(frame, options(**{"Sample fraction (%)": "82,5", "Seed": "7"}))
        self.assertEqual((plan.fraction, plan.seed), (82.5, 7))
        with self.assertRaises(FieldError) as caught:
            ks.prepare(frame, options(**{"K-means algorithm": "Hartigan–Wong", "Hartigan–Wong iteration limit": 0}))
        self.assertEqual(caught.exception.field, "Hartigan–Wong iteration limit")

    def test_sample_and_distinct_limits(self):
        frame = pd.DataFrame({"A": [1.0, 2, 3, 4, 5, 6], "B": [6.0, 5, 4, 3, 2, 1]})
        with self.assertRaises(FieldError) as caught:  # 80 % of 6 = 4 rows < Maximum k + 1 = 5; 95 % gives 5
            ks.prepare(frame, options(Variables=["A", "B"], **{"Maximum k": 4, "Report k": 2}))
        self.assertEqual(caught.exception.field, "Sample fraction (%)")
        ks.prepare(frame, options(Variables=["A", "B"], **{"Maximum k": 4, "Report k": 2, "Sample fraction (%)": 95}))
        with self.assertRaises(FieldError) as caught:
            ks.prepare(frame, options(Variables=["A", "B"], **{"Maximum k": 5, "Report k": 2}))
        self.assertEqual(caught.exception.field, "Maximum k")
        repeated = pd.DataFrame({"A": [1.0, 1, 1, 2, 2, 2, 1, 2, 1, 2]})
        with self.assertRaises(FieldError) as caught:
            ks.prepare(repeated, options(Variables=["A"], **{"Maximum k": 3, "Report k": 2}))
        self.assertEqual(caught.exception.field, "Maximum k")

    def test_budgets_refuse_before_any_fit(self):
        frame = separated()
        with mock.patch.object(ks.engine, "kmeans", side_effect=AssertionError("no fit before the checks")):
            for changes, field in (({"Minimum k": 2, "Maximum k": 4, "Resamples": 2000}, "Resamples"),
                                   ({"Maximum k": 4, "Resamples": 1950, "Seed runs": 100}, "Seed runs")):
                with self.subTest(changes), self.assertRaises(FieldError) as caught:
                    analyse(ks.METHOD, frame, options(**changes))
                self.assertEqual(caught.exception.field, field)
        rng = np.random.default_rng(1)
        large = pd.DataFrame(rng.normal(size=(20_001, 1)), columns=["A"])
        with self.assertRaises(FieldError) as caught:
            ks.prepare(large, options(Variables=["A"]))
        self.assertEqual(caught.exception.field, "Variables")
        wide = pd.DataFrame(rng.normal(size=(201, 2)), columns=VARIABLES)
        with self.assertRaises(FieldError) as caught:
            ks.prepare(wide, options(**{"Show co-assignment matrix": True}))
        self.assertEqual(caught.exception.field, "Show co-assignment matrix")
        many = pd.DataFrame(rng.normal(size=(19_000, 32)), columns=[f"V{i}" for i in range(32)])
        with self.assertRaises(FieldError) as caught:  # 19000 × 32 × (2+…+12) × 21 > 600 million
            ks.prepare(many, options(Variables=list(many.columns), **{"Maximum k": 12, "Resamples": 20}))
        self.assertEqual(caught.exception.field, "Resamples")


def fixed_fit(failures=()):
    """A deterministic stand-in for analisi.stats.kmeans on the separated fixture: the three true groups."""
    original = ks._fit

    def fit(values, k, standardize, seed, fit_kwargs):
        for condition, error in failures:
            if condition(values, k, seed):
                raise error
        return original(values, k, standardize, seed, fit_kwargs)
    return fit


# One process: these tests patch the engine in this process and count one progress step per fit.
@mock.patch.dict("os.environ", {"TRAMA_PROCESSES": "1"})
class CalculationTests(unittest.TestCase):
    def test_separated_groups_are_perfectly_stable(self):
        result = analyse(ks.METHOD, separated(), options(**{"Show co-assignment matrix": True, "Seed runs": 2}))
        summary = result.tables["Stability summary"]
        self.assertEqual(list(summary.index), [2, 3])
        self.assertEqual(summary.loc[3, "Median ARI"], 1.0)
        self.assertEqual(summary.loc[3, "Median OOB ARI"], 1.0)
        matrix = result.tables["Co-assignment"]
        values = matrix.to_numpy(dtype=float)
        np.testing.assert_array_equal(values, values.T)
        np.testing.assert_array_equal(np.diag(values), 1.0)
        self.assertTrue(((values >= 0) & (values <= 1)).all())
        self.assertEqual(list(matrix.index), [r for r in range(1, 21) if r not in {6, 15}])
        self.assertEqual(matrix.index.name, "Worksheet row")
        settings = result.tables["Settings"]["Value"]
        self.assertEqual(settings["Incomplete rows"], 2)
        self.assertIn("not confidence intervals", settings["Interpretation"])
        centers = result.tables["Reference centers"]
        three = centers[centers["k"] == 3]
        self.assertEqual(sorted(np.round(three.loc[three["Variable"] == "Marker A", "Center"]).astype(int)),
                         [-100, 0, 100])

    def test_prefix_is_stable_for_more_replicates_other_k_and_seed_runs(self):
        frame = pd.read_csv(DATA / "overlapped.csv")
        base = analyse(ks.METHOD, frame, options(**{"Maximum k": 4, "Resamples": 6, "Report k": 2}))
        more = analyse(ks.METHOD, frame, options(**{"Maximum k": 4, "Resamples": 11, "Report k": 2, "Seed runs": 3}))
        shifted = analyse(ks.METHOD, frame, options(**{"Minimum k": 3, "Maximum k": 5, "Resamples": 6,
                                                        "Report k": 3}))
        scores, extra = base.tables["Resample scores"], more.tables["Resample scores"]
        pd.testing.assert_frame_equal(scores, extra[extra["Replicate"] <= 6].reset_index(drop=True))
        for k in (3, 4):
            pd.testing.assert_frame_equal(scores[scores["k"] == k].reset_index(drop=True),
                                          shifted.tables["Resample scores"].query("k == @k").reset_index(drop=True))
        np.testing.assert_array_equal(
            base.tables["Reference centers"].query("k == 3")["Fitting center"],
            shifted.tables["Reference centers"].query("k == 3")["Fitting center"])

    def test_failed_replicates_and_k_are_reported_in_order(self):
        frame = separated()

        def failing_replicate(values, k, seed):
            return k == 3 and seed == ks.fit_seed(33, 3, 2, ks.SUBSAMPLE)

        def failing_reference(values, k, seed):
            return k == 2 and seed == ks.fit_seed(33, 2, 0, ks.REFERENCE)

        fit = fixed_fit([(failing_replicate, ValueError("K-means did not converge to non-empty clusters.")),
                         (failing_reference, ValueError("Too many clusters for the number of distinct observations."))])
        with mock.patch.object(ks, "_fit", fit):
            result = analyse(ks.METHOD, frame, options(**{"Show co-assignment matrix": True, "Seed runs": 1}))
        summary = result.tables["Stability summary"]
        self.assertTrue(summary.loc[2, "Status"].startswith("Reference fit failed: Too many clusters"))
        self.assertEqual(summary.loc[2, "Valid resamples"], 0)
        self.assertTrue(np.isnan(summary.loc[2, "Median ARI"]))
        self.assertEqual(summary.loc[3, "Valid resamples"], 7)
        self.assertEqual(summary.loc[3, "Status"], "OK")
        scores = result.tables["Resample scores"]
        self.assertEqual(list(scores["k"]), [3] * 8)
        self.assertEqual(list(scores["Replicate"]), list(range(1, 9)))
        failed = scores.iloc[1]
        self.assertEqual(failed["Status"], "K-means did not converge to non-empty clusters.")
        self.assertTrue(np.isnan(failed["ARI"]) and np.isnan(failed["OOB ARI"]))
        self.assertTrue((result.tables["Assignment stability"]["Valid resamples"] == 7).all())
        self.assertTrue((result.tables["Cluster stability"]["Valid resamples"] == 7).all())
        self.assertEqual(list(result.tables["Cluster stability"]["k"]), [3, 3, 3])
        self.assertEqual(set(result.tables["Reference centers"]["k"]), {3})
        self.assertEqual(list(result.tables["Seed sensitivity"]["k"]), [3])
        self.assertFalse(summary["Status"].astype(str).str.lower().eq("nan").any())
        self.assertEqual(summary["Median ARI"].dtype, float)

    def test_report_k_without_reference_has_no_invented_matrix(self):
        def failing_reference(values, k, seed):
            return k == 3 and seed == ks.fit_seed(33, 3, 0, ks.REFERENCE)

        with mock.patch.object(ks, "_fit", fixed_fit([(failing_reference, ValueError("Cannot fit."))])):
            result = analyse(ks.METHOD, separated(), options(**{"Show co-assignment matrix": True}))
        self.assertNotIn("Co-assignment", result.tables)
        self.assertNotIn("Assignment stability", result.tables)
        self.assertIn("Cannot fit.", result.tables["Settings"].loc["Co-assignment", "Value"])
        self.assertEqual(len(result.figure.axes), 1)

    def test_no_valid_replicate_for_report_k(self):
        def every_subsample(values, k, seed):
            return k == 3 and len(values) == 14

        with mock.patch.object(ks, "_fit", fixed_fit([(every_subsample, ValueError("Cannot fit."))])):
            result = analyse(ks.METHOD, separated(), options(**{"Show co-assignment matrix": True}))
        summary = result.tables["Stability summary"]
        self.assertEqual(summary.loc[3, "Status"], ks.NO_VALID)
        self.assertNotIn("Co-assignment", result.tables)
        assignments = result.tables["Assignment stability"]
        self.assertTrue(assignments["Agreement"].isna().all())
        self.assertTrue((assignments["Valid resamples"] == 0).all())
        jaccard = result.tables["Cluster stability"].query("k == 3")
        self.assertTrue(jaccard["Median Jaccard"].isna().all())
        gaps = [patch for patch in result.figure.axes[0].patches if patch.get_gid() == "kstab-gap"]
        self.assertEqual(len(gaps), 1)  # k = 3 has no valid replicate: a hatched gap, no invented point

    def test_every_reference_failing_is_a_recoverable_error(self):
        with mock.patch.object(ks, "_fit", side_effect=ValueError("Cannot fit.")):
            with self.assertRaises(ValueError) as caught:
                analyse(ks.METHOD, separated(), options())
        self.assertNotIsInstance(caught.exception, FieldError)
        self.assertIn("Cannot fit.", str(caught.exception))
        with mock.patch.object(ks, "_fit", side_effect=IterationLimitError("Hartigan–Wong reached the maximum "
                                                                           "number of iterations.")):
            with self.assertRaises(FieldError) as caught:
                analyse(ks.METHOD, separated(), options())
        self.assertEqual(caught.exception.field, "Hartigan–Wong iteration limit")

    def test_constant_sample_is_an_invalid_replicate(self):
        values = np.r_[np.zeros(19), 5.0]  # constant whenever a sample leaves out the last row
        frame = pd.DataFrame({"A": values, "B": np.arange(20.0)})
        result = analyse(ks.METHOD, frame, options(Variables=["A", "B"], **{"Maximum k": 2, "Report k": 2,
                                                                          "Resamples": 30}))
        statuses = result.tables["Resample scores"]["Status"]
        self.assertIn(ks.CONSTANT_SAMPLE, set(statuses))
        valid = (statuses == "OK").sum()
        self.assertEqual(result.tables["Stability summary"].loc[2, "Valid resamples"], valid)

    def test_programming_errors_propagate(self):
        with mock.patch.object(ks, "project", side_effect=TypeError("bug")):
            with self.assertRaises(TypeError):
                analyse(ks.METHOD, separated(), options())

    def test_cancel_between_fits_and_progress(self):
        event = threading.Event()
        steps = []

        def progress(done, total):
            steps.append((done, total))
            if done == 5:
                event.set()

        with self.assertRaises(ks.KMeansStabilityCancelled):
            ks.analysis(separated(), options(), cancel=event, progress=progress)
        self.assertEqual(steps[-1][0], 5)
        steps.clear()
        ks.analysis(separated(), options(**{"Seed runs": 2}), progress=lambda d, t: steps.append((d, t)))
        self.assertEqual(steps[-1], (2 * (1 + 8 + 2), 2 * (1 + 8 + 2)))
        with self.assertRaises(InterruptedError):
            analyse(ks.METHOD, separated(), options(), cancel=lambda: True)

    def test_matrix_not_allocated_when_off(self):
        plan = ks.prepare(separated(), options())
        reference = {"status": "OK", "labels": np.repeat([1, 2, 3], 6)}
        self.assertIsNone(ks._Collector(plan, 3, reference).shared)
        self.assertIsNotNone(ks._Collector(plan, 3, reference).agree)
        self.assertIsNone(ks._Collector(plan, 2, reference).agree)
        plan = ks.prepare(separated(), options(**{"Show co-assignment matrix": True}))
        self.assertEqual(ks._Collector(plan, 3, reference).shared.dtype, np.int64)

    def test_figure_panels_and_scale(self):
        result = analyse(ks.METHOD, separated(), options(**{"Show co-assignment matrix": True, "Seed runs": 2}))
        figure = result.figure
        axes = figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "Number of clusters (k)")
        self.assertEqual([line.get_gid() for line in axes.lines], ["kstab-median", "kstab-seeds"])
        self.assertEqual(figure.axes[1].images[0].get_clim(), (0, 1))
        self.assertIn("k = 3", figure.axes[1].get_title())
        off = analyse(ks.METHOD, separated(), options())
        self.assertEqual(len(off.figure.axes), 1)

    def test_catalog_and_existing_methods(self):
        self.assertEqual(GROUPS["Clustering"][:3], ("K-means clustering", "K-means model selection", ks.METHOD))
        self.assertIn(ks.METHOD, GRAPH_METHODS)
        self.assertEqual(list(METHODS[ks.METHOD]), list(ks.OPTIONS))
        self.assertEqual(METHODS["K-means clustering"]["Clusters"], 2)


class PoolTests(unittest.TestCase):
    """The shared process pool (``analisi.parallel``) gives the tables of the serial loop."""

    def run_with(self, processes, frame, recipe, **keywords):
        seen, original = [], ks.run_tasks

        def recording(*args, **kwargs):
            outcomes = original(*args, **kwargs)
            seen.extend(outcomes)
            return outcomes

        with mock.patch.dict("os.environ", {"TRAMA_PROCESSES": str(processes)}), \
                mock.patch.object(ks, "run_tasks", side_effect=recording):
            if processes > 1:
                ready_workers()  # a request reaches the workers only once they are ready
            result = ks.analysis(frame, recipe, **keywords)
        return result, seen

    def test_one_two_and_three_processes_give_the_same_tables(self):
        frame = pd.read_csv(DATA / "overlapped.csv")
        recipe = options(**{"Maximum k": 4, "Resamples": 20, "Seed runs": 2, "Report k": 3,
                            "Show co-assignment matrix": True})
        serial, seen = self.run_with(1, frame, recipe)
        self.assertEqual(seen, [])  # one process: the loop on this thread
        for processes in (2, 3):
            result, seen = self.run_with(processes, frame, recipe)
            self.assertTrue(any(outcome.remote for outcome in seen), processes)
            self.assertEqual(list(result.tables), list(serial.tables))
            for name, table in serial.tables.items():
                pd.testing.assert_frame_equal(result.tables[name], table, check_exact=True, obj=name)

    def test_invalid_replicates_on_the_pool_match_the_loop(self):
        values = np.r_[np.zeros(19), 5.0]
        frame = pd.DataFrame({"A": values, "B": np.arange(20.0)})
        recipe = options(Variables=["A", "B"], **{"Maximum k": 2, "Report k": 2, "Resamples": 30})
        serial, _ = self.run_with(1, frame, recipe)
        pooled, seen = self.run_with(2, frame, recipe)
        self.assertTrue(any(outcome.remote for outcome in seen))
        pd.testing.assert_frame_equal(pooled.tables["Resample scores"], serial.tables["Resample scores"],
                                      check_exact=True)

    def test_cancel_on_the_pool_publishes_nothing(self):
        event = threading.Event()
        steps = []

        def progress(done, total):
            steps.append(done)
            event.set()  # once the two reference fits are done

        with self.assertRaises(ks.KMeansStabilityCancelled):
            self.run_with(2, separated(), options(**{"Resamples": 200}), cancel=event, progress=progress)
        self.assertEqual(max(steps), 2)  # no block of subsample fits was counted after the cancel


if __name__ == "__main__":
    unittest.main()
