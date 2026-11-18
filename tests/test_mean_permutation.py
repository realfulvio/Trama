"""Permutation test for mean difference: exact counts against rational enumeration, Monte Carlo draws, budgets."""
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import mean_permutation as mp
from analisi.data import Dataset, load_project, save_project
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "mean_permutation"
INDEPENDENT = pd.read_csv(DATA / "independent.csv")
PAIRED = pd.read_csv(DATA / "paired.csv")


def run(frame, **options):
    return mp.permutation_test(frame, {"First": "First", "Second": "Second", "Show graph": False, **options})


def row(result):
    return result.tables[mp.RESULTS_SHEET].iloc[0]


def settings(result):
    return result.tables[mp.SETTINGS_SHEET]["Value"]


def rational_reference(first, second, paired):
    """Every assignment with exact fractions: (observed, statistics in enumeration order)."""
    a, b = [Fraction(x) for x in first], [Fraction(x) for x in second]
    if paired:
        differences = [x - y for x, y in zip(a, b, strict=True)]
        null = [sum(d * s for d, s in zip(differences, signs)) / len(a)
                for signs in product((-1, 1), repeat=len(a))]
        return sum(differences) / len(a), null
    pool = a + b
    null = []
    for chosen in combinations(range(len(pool)), len(a)):
        inside = set(chosen)
        x = [pool[i] for i in chosen]
        y = [pool[i] for i in range(len(pool)) if i not in inside]
        null.append(sum(x) / len(x) - sum(y) / len(y))
    return sum(a) / len(a) - sum(b) / len(b), null


def tail_counts(observed, null):
    return {mp.TWO_SIDED: sum(abs(x) >= abs(observed) for x in null),
            mp.GREATER: sum(x >= observed for x in null),
            mp.LESS: sum(x <= observed for x in null)}


def frame_of(first, second):
    size = max(len(first), len(second))
    pad = lambda values: list(values) + [np.nan] * (size - len(values))  # noqa: E731
    return pd.DataFrame({"First": pad(first), "Second": pad(second)})


class RegistrationTests(unittest.TestCase):
    def test_the_method_is_listed_with_its_canonical_options(self):
        self.assertIn(mp.METHOD, GROUPS["Group Comparison"])
        self.assertIn(mp.METHOD, GRAPH_METHODS)
        self.assertEqual(METHODS[mp.METHOD], {
            "First": None, "Second": None, "Design": ("Independent", "Paired"),
            "Alternative": ("Two-sided", "Greater", "Less"), "Method": ("Auto", "Exact", "Monte Carlo"),
            "Resamples": 9999, "Seed": 0, "Keep draws": False, "Show graph": True})

    def test_the_workbench_passes_the_cancel_event(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(mp.PermutationCancelled):
            analyse(mp.METHOD, INDEPENDENT, {"First": "First", "Second": "Second"}, cancel=event)


class ExactTests(unittest.TestCase):
    def test_the_fixtures_match_rational_enumeration(self):
        for frame, design in ((INDEPENDENT, mp.INDEPENDENT), (PAIRED, mp.PAIRED)):
            if design == mp.PAIRED:
                complete = frame.dropna()
                first, second = complete["First"], complete["Second"]
            else:
                first, second = frame["First"].dropna(), frame["Second"].dropna()
            observed, null = rational_reference(first, second, design == mp.PAIRED)
            counts = tail_counts(observed, null)
            for alternative, count in counts.items():
                with self.subTest(design=design, alternative=alternative):
                    result = run(frame, Design=design, Alternative=alternative, **{"Keep draws": True})
                    values = row(result)
                    self.assertEqual(values["Tail count"], count)
                    self.assertEqual(values["Draws"], len(null))
                    self.assertAlmostEqual(values["p"], count / len(null), places=15)
                    self.assertEqual(values["Mode used"], mp.EXACT)
                    self.assertAlmostEqual(values["Mean difference"], float(observed), places=12)
                    np.testing.assert_allclose(result.tables[mp.DRAWS_SHEET]["Statistic"], [float(x) for x in null],
                                               rtol=0, atol=1e-12)

    def test_random_small_samples_with_ties_and_unequal_sizes(self):
        rng = np.random.default_rng(20261118)
        for case in range(24):
            n_first, n_second = rng.integers(2, 8, size=2)
            first = rng.integers(-3, 4, size=n_first).astype(float) / 4
            second = rng.integers(-3, 4, size=n_second).astype(float) / 4
            observed, null = rational_reference(first, second, False)
            for alternative, count in tail_counts(observed, null).items():
                with self.subTest(case=case, alternative=alternative, sizes=(n_first, n_second)):
                    values = row(run(frame_of(first, second), Alternative=alternative, Method="Exact"))
                    self.assertEqual(values["Tail count"], count)
                    self.assertEqual(values["Draws"], len(null))

    def test_random_pairs_with_zero_differences(self):
        rng = np.random.default_rng(7)
        for case in range(16):
            size = int(rng.integers(2, 11))
            first = rng.integers(0, 5, size=size).astype(float)
            second = first + rng.integers(-2, 3, size=size)
            observed, null = rational_reference(first, second, True)
            for alternative, count in tail_counts(observed, null).items():
                with self.subTest(case=case, alternative=alternative):
                    values = row(run(frame_of(first, second), Design="Paired", Alternative=alternative,
                                     Method="Exact"))
                    self.assertEqual(values["Tail count"], count)
                    self.assertEqual(values["Draws"], 2 ** size)

    def test_one_sided_p_values_agree_with_scipy(self):
        first, second = np.array([1.5, 3., 4.25, 7., 2.]), np.array([-2., 0., 1., 5.5, 6., .5])

        def difference(x, y, axis):
            return np.mean(x, axis=axis) - np.mean(y, axis=axis)

        for alternative, side in ((mp.GREATER, "greater"), (mp.LESS, "less")):
            with self.subTest(alternative=alternative):
                expected = stats.permutation_test((first, second), difference, permutation_type="independent",
                                                  alternative=side, n_resamples=np.inf, vectorized=True).pvalue
                self.assertAlmostEqual(row(run(frame_of(first, second), Alternative=alternative))["p"], expected,
                                       places=12)
                paired = stats.permutation_test((first, second[:5]), difference, permutation_type="samples",
                                                alternative=side, n_resamples=np.inf, vectorized=True).pvalue
                self.assertAlmostEqual(row(run(frame_of(first, second[:5]), Design="Paired",
                                               Alternative=alternative))["p"], paired, places=12)

    def test_two_sided_counts_absolute_values_not_twice_the_smaller_tail(self):
        first, second = [0., 0., 0., 9.], [1., 2.]
        observed, null = rational_reference(first, second, False)
        counts = tail_counts(observed, null)
        values = row(run(frame_of(first, second), Alternative=mp.TWO_SIDED))
        self.assertEqual(values["Tail count"], counts[mp.TWO_SIDED])
        doubled = min(1.0, 2 * min(counts[mp.GREATER], counts[mp.LESS]) / len(null))
        self.assertNotAlmostEqual(values["p"], doubled)

    def test_swapping_the_columns_mirrors_the_test(self):
        swapped = INDEPENDENT.rename(columns={"First": "Second", "Second": "First"})
        greater = row(run(INDEPENDENT, Alternative=mp.GREATER))
        less = row(run(swapped, Alternative=mp.LESS))
        self.assertEqual(greater["Tail count"], less["Tail count"])
        self.assertEqual(greater["p"], less["p"])
        self.assertEqual(greater["Mean difference"], -less["Mean difference"])
        both = row(run(swapped))
        self.assertEqual(both["p"], row(run(INDEPENDENT))["p"])

    def test_constant_samples_give_p_one(self):
        for design in mp.DESIGNS:
            with self.subTest(design=design):
                values = row(run(frame_of([4., 4., 4.], [4., 4., 4.]), Design=design))
                self.assertEqual(values["Mean difference"], 0.0)
                self.assertEqual(values["p"], 1.0)
                self.assertEqual(values["Tail count"], values["Draws"])

    def test_a_common_offset_changes_nothing(self):
        for frame, design in ((INDEPENDENT, mp.INDEPENDENT), (PAIRED, mp.PAIRED)):
            with self.subTest(design=design):
                plain = run(frame, Design=design, **{"Keep draws": True})
                shifted = run(frame + 2.0 ** 40, Design=design, **{"Keep draws": True})
                for name in ("Tail count", "Draws", "p", "Mean difference"):
                    self.assertEqual(row(plain)[name], row(shifted)[name], name)
                pd.testing.assert_frame_equal(plain.tables[mp.DRAWS_SHEET], shifted.tables[mp.DRAWS_SHEET])

    def test_decimal_values_close_to_the_observed_count_as_ties(self):
        # 0.1 + 0.2 style rounding must not drop the observed assignment or its mirror from the tail.
        first, second = [.1, .2, .7], [.3, .4, .3]
        observed, null = rational_reference([Fraction(str(x)) for x in first],
                                            [Fraction(str(x)) for x in second], False)
        for alternative, count in tail_counts(observed, null).items():
            with self.subTest(alternative=alternative):
                self.assertEqual(row(run(frame_of(first, second), Alternative=alternative))["Tail count"], count)


class MonteCarloTests(unittest.TestCase):
    def test_independent_draws_are_one_choice_call_per_resample(self):
        values = row(run(INDEPENDENT, Method="Monte Carlo", Resamples=205, Seed=7301, **{"Keep draws": True}))
        result = run(INDEPENDENT, Method="Monte Carlo", Resamples=205, Seed=7301, **{"Keep draws": True})
        first, second = INDEPENDENT["First"].dropna().to_numpy(), INDEPENDENT["Second"].to_numpy()
        pool = np.concatenate((first, second))
        rng = np.random.Generator(np.random.PCG64(7301))
        expected = []
        for _ in range(205):
            mask = np.zeros(len(pool), bool)
            mask[rng.choice(len(pool), len(first), replace=False)] = True
            expected.append(pool[mask].mean() - pool[~mask].mean())
        draws = result.tables[mp.DRAWS_SHEET]
        self.assertEqual(draws["Draw"].tolist(), list(range(1, 206)))
        np.testing.assert_allclose(draws["Statistic"], expected, rtol=0, atol=1e-12)
        observed = first.mean() - second.mean()
        count = int(np.sum(np.abs(expected) >= abs(observed) - 1e-9))
        self.assertEqual(values["Tail count"], count)
        self.assertEqual(values["p"], (count + 1) / 206)
        self.assertEqual(values["Draws"], 205)
        self.assertEqual(values["Mode used"], mp.MONTE_CARLO)

    def test_paired_draws_are_one_integers_call_per_resample(self):
        result = run(PAIRED, Design="Paired", Method="Monte Carlo", Resamples=199, Seed=11, **{"Keep draws": True})
        complete = PAIRED.dropna()
        differences = (complete["First"] - complete["Second"]).to_numpy()
        rng = np.random.Generator(np.random.PCG64(11))
        expected = [np.where(rng.integers(0, 2, size=len(differences), dtype="int64") == 1,
                             differences, -differences).mean() for _ in range(199)]
        np.testing.assert_allclose(result.tables[mp.DRAWS_SHEET]["Statistic"], expected, rtol=0, atol=1e-12)

    def test_more_resamples_keep_the_earlier_draws_exactly(self):
        for frame, design in ((INDEPENDENT, mp.INDEPENDENT), (PAIRED, mp.PAIRED),
                              (frame_of(np.arange(30.), np.arange(5., 40.)), mp.INDEPENDENT)):
            with self.subTest(design=design, size=len(frame)):
                short = run(frame, Design=design, Method="Monte Carlo", Resamples=199, Seed=2**64 - 1,
                            **{"Keep draws": True}).tables[mp.DRAWS_SHEET]
                long = run(frame, Design=design, Method="Monte Carlo", Resamples=1000, Seed=2**64 - 1,
                           **{"Keep draws": True}).tables[mp.DRAWS_SHEET]
                pd.testing.assert_frame_equal(long.iloc[:199], short)

    def test_the_seed_changes_the_draws_and_is_reported_as_text(self):
        options = {"Method": "Monte Carlo", "Resamples": 199, "Keep draws": True}
        zero, other = run(INDEPENDENT, Seed=0, **options), run(INDEPENDENT, Seed=1, **options)
        self.assertFalse(zero.tables[mp.DRAWS_SHEET].equals(other.tables[mp.DRAWS_SHEET]))
        self.assertEqual(settings(zero)["Seed"], "0")
        self.assertEqual(settings(run(INDEPENDENT, Seed=2**64 - 1, **options))["Seed"], "18446744073709551615")
        self.assertEqual(settings(zero)["Monte Carlo correction"], "p = (tail count + 1) / (resamples + 1)")

    def test_auto_enumerates_small_samples_and_simulates_large_ones(self):
        small = row(run(INDEPENDENT))
        self.assertEqual((small["Mode used"], small["Draws"]), (mp.EXACT, 126))
        large = row(run(frame_of(np.arange(18.), np.arange(3., 21.)), Resamples=199))
        self.assertEqual((large["Mode used"], large["Draws"]), (mp.MONTE_CARLO, 199))
        pairs = row(run(frame_of(np.arange(17.), np.arange(17.) + 1), Design="Paired", Resamples=199))
        self.assertEqual((pairs["Mode used"], pairs["Draws"]), (mp.EXACT, 2 ** 17))
        pairs = row(run(frame_of(np.arange(18.), np.arange(18.) + 1), Design="Paired", Resamples=199))
        self.assertEqual((pairs["Mode used"], pairs["Draws"]), (mp.MONTE_CARLO, 199))

    def test_exact_ignores_resamples_and_seed(self):
        values = row(run(INDEPENDENT, Method="Exact", Resamples="nonsense", Seed=-1))
        self.assertEqual(values["Draws"], 126)
        table = settings(run(INDEPENDENT, Method="Exact"))
        self.assertNotIn("Seed", table.index)
        self.assertEqual(table["Assignments enumerated"], 126)


class InputTests(unittest.TestCase):
    def assert_field(self, field, call, *fragments):
        with self.assertRaises(FieldError) as raised:
            call()
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        for fragment in fragments:
            self.assertIn(fragment, str(raised.exception))
        return str(raised.exception)

    def test_blank_and_excluded_cells_are_dropped_and_counted(self):
        frame = pd.DataFrame({"First": pd.array([1, 3, pd.NA, 7, 2], dtype="Int64"),
                              "Second": [-2., 0., 1., np.nan, 6.]})
        result = run(frame)
        self.assertEqual((row(result)["N first"], row(result)["N second"]), (4, 4))
        self.assertEqual(settings(result)["Missing or excluded cells, First"], 1)
        self.assertEqual(settings(result)["Missing or excluded cells, Second"], 1)
        paired = run(frame, Design="Paired")
        self.assertEqual(row(paired)["N first"], 3)
        self.assertEqual(settings(paired)["Incomplete or excluded pairs omitted"], 2)

    def test_text_cells_name_the_sample_and_the_row(self):
        frame = pd.DataFrame({"First": ["1", " 2,5 ", "3", ""], "Second": [1., 2., 3., 4.]})
        self.assertEqual(row(run(frame))["N first"], 3)
        message = self.assert_field("Second", lambda: run(frame.assign(Second=[1, "x", 2, 3])), "source row 2", "(x)")
        self.assertEqual(message, "Second: source row 2 is not a number (x).")
        self.assert_field("First", lambda: run(frame.assign(First=[1., np.inf, 2., 3.])), "source row 2", "finite")
        self.assert_field("First", lambda: run(frame.assign(First=[1, 2**60, 2, 3])), "cannot be represented")
        self.assert_field("Second", lambda: run(frame.assign(Second=[True, False, True, False])), "not a number")
        self.assert_field("Second", lambda: run(frame.assign(Second=["1", "nan", "2", "3"])), "finite")

    def test_sizes_and_columns(self):
        self.assert_field("Second", lambda: run(frame_of([1., 2.], [3.])), "at least 2 values")
        self.assert_field("First", lambda: run(frame_of([1., 2.], [3.]), Design="Paired"), "at least 2 complete")
        self.assert_field("First", lambda: run(frame_of(np.ones(25_001), np.ones(25_000))), "50,000")
        self.assert_field("First", lambda: run(frame_of(np.ones(25_001), np.ones(25_001)), Design="Paired"),
                          "25,000 complete pairs; 25,001 found")
        self.assert_field("Second", lambda: run(INDEPENDENT, Second="First"), "different from First")
        self.assert_field("First", lambda: run(INDEPENDENT, First=None), "Choose a column for First.")
        self.assert_field("Second", lambda: run(INDEPENDENT, Second="Missing"), '"Missing" is not in the worksheet')
        duplicated = INDEPENDENT.copy()
        duplicated.columns = ["First", "First"]
        self.assert_field("First", lambda: mp.permutation_test(duplicated, {"First": "First", "Second": "X"}),
                          "unique")

    def test_options_name_their_field(self):
        self.assert_field("Design", lambda: run(INDEPENDENT, Design="Unpaired"), "listed options")
        self.assert_field("Alternative", lambda: run(INDEPENDENT, Alternative="Both"), "listed options")
        self.assert_field("Method", lambda: run(INDEPENDENT, Method="Bootstrap"), "listed options")
        self.assert_field("Keep draws", lambda: run(INDEPENDENT, **{"Keep draws": "yes"}), "on or off")
        for bad in (198, 100_001, 999.5, True, "9999"):
            self.assert_field("Resamples", lambda bad=bad: run(INDEPENDENT, Method="Monte Carlo", Resamples=bad),
                              "199 to 100,000")
        for bad in (-1, 2**64, 1.0, True, "7"):
            self.assert_field("Seed", lambda bad=bad: run(INDEPENDENT, Method="Monte Carlo", Seed=bad),
                              "18446744073709551615")
        # Auto may simulate, so it checks the simulation fields as well.
        self.assert_field("Seed", lambda: run(INDEPENDENT, Seed=-1), "whole number")

    def test_budgets_name_method_and_resamples(self):
        many = frame_of(np.arange(18.), np.arange(18.))
        self.assert_field("Method", lambda: run(many, Method="Exact"), "200,000 assignments")
        # C(40, 2) = 780 assignments × 40 values is within both exact limits.
        self.assertEqual(row(run(frame_of(np.arange(38.), [1., 2.]), Method="Exact"))["Draws"], 780)
        work = frame_of(np.arange(600.), [1., 2.])  # C(602, 2) = 180,901 assignments × 602 values
        self.assert_field("Method", lambda: run(work, Method="Exact"), "10,000,000 operations")
        auto = row(run(work, Resamples=199))
        self.assertEqual(auto["Mode used"], mp.MONTE_CARLO)
        big = frame_of(np.arange(25_000.), np.arange(25_000.))
        message = self.assert_field("Resamples", lambda: run(big, Resamples=1001), "1,001 × 50,000 = 50,050,000",
                                    "Use 1,000 resamples or fewer.")
        self.assertTrue(message.startswith("Resamples: Monte Carlo allows at most 50,000,000 operations"))

    def test_the_worksheet_is_not_changed(self):
        frame = INDEPENDENT.copy()
        run(frame, Method="Monte Carlo", Resamples=199, **{"Show graph": True})
        pd.testing.assert_frame_equal(frame, INDEPENDENT)

    def test_check_options_and_preview_do_not_enumerate(self):
        chosen, steps = mp.check_options(INDEPENDENT, {"First": "First", "Second": "Second"})
        self.assertEqual((chosen["mode"], steps["used"], steps["assignments"], steps["units"]), ("Auto", "Exact", 126, 9))
        self.assertIsNone(mp.preview(INDEPENDENT, {"First": "First", "Second": "First"}))
        self.assertEqual(mp.preview(frame_of(np.arange(30.), np.arange(30.)), {"First": "First", "Second": "Second"})
                         ["used"], mp.MONTE_CARLO)


class CancelTests(unittest.TestCase):
    class Countdown:
        """Reports cancellation after a number of checks, as a click during the run would."""

        def __init__(self, checks):
            self.checks = checks

        def is_set(self):
            self.checks -= 1
            return self.checks < 0

    def test_both_modes_stop_between_blocks(self):
        cases = ((frame_of(np.arange(10.), np.arange(10.)), {"Method": "Exact"}),
                 (frame_of(np.arange(17.), np.arange(17.)), {"Design": "Paired", "Method": "Exact"}),
                 (frame_of(np.arange(40.), np.arange(40.)), {"Method": "Monte Carlo", "Resamples": 5000}),
                 (frame_of(np.arange(40.), np.arange(40.)), {"Design": "Paired", "Method": "Monte Carlo",
                                                            "Resamples": 5000}))
        for frame, options in cases:
            for checks in (0, 2):
                with self.subTest(options=options, checks=checks):
                    with self.assertRaises(mp.PermutationCancelled):
                        mp.permutation_test(frame, {"First": "First", "Second": "Second", **options},
                                            cancel=self.Countdown(checks))

    def test_the_cancellation_is_a_monte_carlo_cancellation(self):
        from analisi.monte_carlo import MonteCarloCancelled

        self.assertTrue(issubclass(mp.PermutationCancelled, MonteCarloCancelled))
        self.assertTrue(mp.cancellable(mp.METHOD, {}))
        self.assertFalse(mp.cancellable("t-test", {}))


class ReportTests(unittest.TestCase):
    def test_sheets_settings_and_draws(self):
        result = run(PAIRED, Design="Paired", **{"Keep draws": True})
        self.assertEqual(list(result.tables), [mp.RESULTS_SHEET, mp.SETTINGS_SHEET, mp.DRAWS_SHEET])
        self.assertEqual(list(result.tables[mp.RESULTS_SHEET].columns), mp.RESULT_COLUMNS)
        table = settings(result)
        self.assertEqual(table.index.name, "Setting")
        self.assertEqual(table["Method requested"], "Auto")
        self.assertEqual(table["Method used"], "Exact")
        self.assertEqual(table["Statistic"], "mean(First) − mean(Second)")
        self.assertEqual(table["Tail rule"], "|Statistic| ≥ |observed|, ties included")
        self.assertIn("no confidence interval", table["Interval"])
        self.assertAlmostEqual(table["Tie tolerance"], 2.0 ** -36 * 5)
        self.assertNotIn(mp.DRAWS_SHEET, run(PAIRED, Design="Paired").tables)

    def test_the_graph_is_native_with_the_observed_line(self):
        result = run(INDEPENDENT, **{"Show graph": True})
        axes = result.figure.axes[0]
        self.assertFalse(getattr(axes, "_tramastat_non_native", False))
        self.assertEqual(axes._tramastat_numeric_axes, ("x", "y"))
        lines = {line.get_gid(): line for line in axes.lines}
        np.testing.assert_allclose(lines[mp.OBSERVED_GID].get_xdata(), [1.75, 1.75])
        np.testing.assert_allclose(lines[mp.MIRROR_GID].get_xdata(), [-1.75, -1.75])
        self.assertEqual(sum(patch.get_height() for patch in axes.patches), 126)
        summary = next(text for text in axes.texts if text.get_gid() == mp.SUMMARY_GID).get_text()
        self.assertIn("Exact · 126 assignments", summary)
        self.assertIn("57 in tail", summary)
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()],
                         [mp.NULL_LABEL, mp.OBSERVED_LABEL, mp.MIRROR_LABEL])
        one_sided = run(INDEPENDENT, Alternative="Greater", **{"Show graph": True}).figure.axes[0]
        self.assertNotIn(mp.MIRROR_GID, {line.get_gid() for line in one_sided.lines})
        self.assertIsNone(run(INDEPENDENT).figure)

    def test_histogram_bins_have_positive_width(self):
        for statistics in (np.zeros(5), np.array([-1e-300, 1e-300]), np.arange(10.) / 4,
                           np.random.default_rng(1).normal(size=999)):
            with self.subTest(size=len(statistics)):
                edges = mp.bin_edges(statistics, 1e-12)
                self.assertTrue(np.all(np.diff(edges) > 0))
                self.assertLessEqual(len(edges), 122)
                self.assertLessEqual(edges[0], statistics.min())
                self.assertGreaterEqual(edges[-1], statistics.max())

    def test_the_recipe_keeps_a_64_bit_seed_after_save_and_reopen(self):
        options = {"First": "First", "Second": "Second", "Design": "Independent", "Alternative": "Two-sided",
                   "Method": "Monte Carlo", "Resamples": 199, "Seed": 2**64 - 1, "Keep draws": True,
                   "Show graph": False}
        first = mp.permutation_test(INDEPENDENT, options)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "permutation.alab"
            save_project(path, {"Data": Dataset(INDEPENDENT.copy(), analyses=[(mp.METHOD, options)])})
            loaded = load_project(path)["Data"]
        (method, saved), = loaded.analyses
        self.assertEqual((method, saved), (mp.METHOD, options))
        self.assertIs(type(saved["Seed"]), int)
        again = mp.permutation_test(loaded.frame(), saved)
        pd.testing.assert_frame_equal(again.tables[mp.DRAWS_SHEET], first.tables[mp.DRAWS_SHEET])


if __name__ == "__main__":
    unittest.main()
