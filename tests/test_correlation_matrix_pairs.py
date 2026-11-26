"""The correlation matrix does each column's work once, and gives the numbers of the pair-by-pair loop bit for bit.

``reference`` is the loop of Trama 0.112, kept here unchanged: for every pair it copies the complete rows of the
whole matrix, takes the two columns and ranks them again. The engine must return exactly its tables.
"""
from itertools import combinations
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from scipy import stats

from analisi import correlation_matrix as engine
from analisi.workbench import analyse


def reference(frame, options):
    """Coefficients, p values, limits and p value types as the 0.112 loop calculated them."""
    names = options["Variables"]
    spearman = options.get("Method", "Pearson") == "Spearman"
    alternative = engine.ALTERNATIVES[options.get("Alternative", "Two-sided")]
    exact_wanted = options.get("Spearman p values", engine.P_VALUES[0]) == engine.P_VALUES[0]
    critical = stats.norm.isf((100 - options.get("Confidence level (%)", 95.)) / 200)
    matrix = np.column_stack([engine._column(frame, name, "Variables") for name in names])
    finite = np.isfinite(matrix)
    if options.get("Missing values", engine.MISSING[0]) == engine.MISSING[1]:
        complete = finite.all(axis=1)
        matrix, finite = matrix[complete], finite[complete]
    valid = finite.astype(np.int64)
    counts = valid.T @ valid
    r, p, lower, upper = (np.full(counts.shape, np.nan) for _ in range(4))
    p_type = np.full(counts.shape, "", dtype=object)
    exact_keys, remaining = set(), engine.EXACT_WORK_BUDGET
    for index, n in enumerate(counts.diagonal()):
        observed = matrix[finite[:, index], index]
        if n >= 3 and observed.min() != observed.max():
            r[index, index] = 1.
    for i, j in combinations(range(len(names)), 2):
        n = counts[i, j]
        if n < 3:
            continue
        x, y = matrix[finite[:, i] & finite[:, j]][:, [i, j]].T
        if x.min() == x.max() or y.min() == y.max():
            continue
        if spearman:
            x, y = stats.rankdata(x), stats.rankdata(y)
        coefficient, probability = engine._coefficient_and_p(x, y, alternative)
        if spearman:
            label = "Approximate"
            if exact_wanted and n <= engine.MAX_EXACT_N:
                scores_x, scores_y = engine._rank_scores(x), engine._rank_scores(y)
                key = engine._exact_key(scores_x, scores_y)
                cost = n * (1 << (n - 1))
                if key in exact_keys or cost <= remaining:
                    if key not in exact_keys:
                        remaining -= cost
                        exact_keys.add(key)
                    probability = engine._permutation_p(key, int(scores_x @ scores_y), alternative)
                    label = "Exact"
            p_type[i, j] = p_type[j, i] = label
        r[i, j] = r[j, i] = coefficient
        p[i, j] = p[j, i] = probability
        low, high = engine._confidence_interval(coefficient, n, critical, spearman)
        lower[i, j] = lower[j, i] = low
        upper[i, j] = upper[j, i] = high
    return {"Coefficients": r, "P values": p, "Sample sizes": counts, "Confidence limits (lower)": lower,
            "Confidence limits (upper)": upper, "R²": r**2, **({"P value type": p_type} if spearman else {})}


def table(rows, columns, seed, *, missing=0., integers=False):
    rng = np.random.default_rng(seed)
    latent = rng.normal(size=(rows, 2))
    values = latent @ rng.normal(size=(2, columns)) + rng.normal(size=(rows, columns))
    if integers:  # many ties
        values = np.round(values * 2)
    if missing:
        values[rng.random(values.shape) < missing] = np.nan
    return pd.DataFrame(values, columns=[f"V{index + 1}" for index in range(columns)])


class SameNumbersTests(unittest.TestCase):
    def assert_same(self, frame, **options):
        options = {"Variables": list(frame), **options}
        expected = reference(frame, options)
        tables = analyse(engine.CORRELATION_MATRIX, frame, {**options, "R² heat map": False}).tables
        for name, values in expected.items():
            found = tables[name].to_numpy()
            if values.dtype == object:
                self.assertTrue((found == values).all(), name)
            else:  # bit for bit: the same doubles, missing in the same cells
                self.assertTrue(np.array_equal(found, values, equal_nan=True), name)

    def test_every_method_and_tail_without_missing_values(self):
        frame = table(400, 7, seed=1)
        for method in engine.METHODS:
            for alternative in engine.ALTERNATIVES:
                with self.subTest(method=method, alternative=alternative):
                    self.assert_same(frame, Method=method, Alternative=alternative)

    def test_missing_values_pairwise_and_listwise(self):
        frame = table(300, 6, seed=2, missing=.08)
        frame.iloc[:, 1] = table(300, 1, seed=3).iloc[:, 0]  # one column without gaps beside columns with gaps
        for method in engine.METHODS:
            for missing in engine.MISSING:
                with self.subTest(method=method, missing=missing):
                    self.assert_same(frame, Method=method, **{"Missing values": missing})

    def test_ties_and_exact_spearman_p_values(self):
        for rows, seed in ((9, 4), (14, 5), (17, 6), (18, 7)):
            frame = table(rows, 5, seed=seed, integers=True)
            for p_values in engine.P_VALUES:
                with self.subTest(rows=rows, p_values=p_values):
                    self.assert_same(frame, Method="Spearman", **{"Spearman p values": p_values})

    def test_constant_short_and_empty_columns_stay_blank(self):
        frame = table(40, 5, seed=8)
        frame["Constant"] = 3.5
        frame["Two values"] = np.r_[1., 2., np.full(38, np.nan)]
        frame["Constant where paired"] = np.r_[np.full(20, 7.), np.arange(20.)]
        frame.loc[20:, "V1"] = np.nan  # paired with the column above, only its constant half is left
        for method in engine.METHODS:
            with self.subTest(method=method):
                self.assert_same(frame, Method=method)

    def test_large_and_tiny_magnitudes(self):
        frame = table(250, 4, seed=9)
        frame["Large"] = 1e15 + frame["V1"]
        frame["Tiny"] = 1e-290 * frame["V2"]
        for method in engine.METHODS:
            with self.subTest(method=method):
                self.assert_same(frame, Method=method, **{"Confidence level (%)": 99.})

    def test_a_large_table(self):
        frame = table(20_000, 12, seed=10, missing=.001)
        for method in engine.METHODS:
            with self.subTest(method=method):
                self.assert_same(frame, Method=method, **{"Spearman p values": "Approximate"})


class WorkDoneOnceTests(unittest.TestCase):
    """What made 32 variables on 60 000 rows take 9 s: every pair ranked and centred both of its columns again."""

    def calls(self, name, frame, **options):
        with mock.patch.object(engine, name, wraps=getattr(engine, name)) as counted:
            analyse(engine.CORRELATION_MATRIX, frame, {"Variables": list(frame), "R² heat map": False, **options})
        return counted.call_count

    def test_a_column_without_gaps_is_ranked_once(self):
        frame = table(200, 10, seed=11)
        with mock.patch.object(engine.stats, "rankdata", wraps=stats.rankdata) as ranked:
            analyse(engine.CORRELATION_MATRIX, frame, {"Variables": list(frame), "Method": "Spearman",
                                                       "R² heat map": False})
        self.assertEqual(ranked.call_count, 10)  # not twice for each of the 45 pairs

    def test_a_column_without_gaps_is_centred_once(self):
        frame = table(200, 10, seed=12)
        for method in engine.METHODS:
            with self.subTest(method=method):
                self.assertEqual(self.calls("_unit_centered", frame, Method=method), 10)

    def test_only_the_column_that_loses_rows_is_done_again(self):
        frame = table(200, 6, seed=13)
        frame.loc[:9, "V1"] = np.nan  # V1 has gaps: its five partners lose ten rows each, V1 itself none
        self.assertEqual(self.calls("_unit_centered", frame, Method="Pearson"), 6 + 5)
        with mock.patch.object(engine.stats, "rankdata", wraps=stats.rankdata) as ranked:
            analyse(engine.CORRELATION_MATRIX, frame, {"Variables": list(frame), "Method": "Spearman",
                                                       "R² heat map": False})
        self.assertEqual(ranked.call_count, 6 + 5)

    def test_listwise_rows_are_shared_by_every_pair(self):
        frame = table(200, 6, seed=14, missing=.05)
        self.assertEqual(self.calls("_unit_centered", frame, Method="Pearson", **{"Missing values": "Listwise complete"}), 6)


if __name__ == "__main__":
    unittest.main()
