"""Partial correlation against the frozen sample, including the degenerate cases."""
from math import sqrt
from pathlib import Path
import json
import time
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset
from analisi.field_error import FieldError
from analisi.partial_correlation import (CANCELLED, COEFFICIENTS, COVARIATES, HOLM, METHOD, PAIRS, SAMPLE,
                                         SCATTER, VARIABLES, PartialCorrelationCancelled, analyse)
from analisi.point_style import point_map
from analisi.workbench import analyse as dispatch


ROOT = Path(__file__).resolve().parent / "data" / "correlazione-parziale"
TARGETS = ["X", "Y", "W"]


def sample():
    return pd.read_csv(ROOT / "campione.csv")


def expected():
    return json.loads((ROOT / "atteso.json").read_text(encoding="utf-8"))


def masked(frame, identifiers=("escludere",)):
    data = Dataset(frame.copy())
    for identifier in identifiers:
        row = int(np.flatnonzero(data.raw["ID"].to_numpy() == identifier)[0])
        for column in range(data.raw.shape[1]):
            data.excluded.add((row, column))
    return data.frame(mask_excluded=True)


def recipe(controls, method="Pearson", variables=None, holm=True, scatter=False):
    return {VARIABLES: list(variables or TARGETS), COVARIATES: list(controls), "Method": method,
            HOLM: holm, SCATTER: scatter}


class PartialCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.frame = masked(sample())

    def test_the_four_frozen_cases_match_the_reference(self):
        cases = expected()
        self.assertAlmostEqual(cases[1]["coppie"][0]["r"], -1 / sqrt(5), delta=1e-12)
        for case in cases:
            with self.subTest(method=case["metodo"], controls=case["controlli"]):
                result = analyse(self.frame, recipe(case["controlli"], case["metodo"]))
                summary = result.tables[SAMPLE]["Value"]
                self.assertEqual(int(summary["N"]), case["N"])
                self.assertEqual(int(summary["df"]), case["gdl"])
                self.assertEqual(int(summary["Excluded rows"]), 1)
                self.assertEqual(int(summary["Incomplete rows"]), 0 if case["controlli"] == ["Z1"] else 1)
                pairs = result.tables[PAIRS]
                self.assertEqual(len(pairs), len(case["coppie"]))
                for index, want in enumerate(case["coppie"]):
                    row = pairs.iloc[index]
                    self.assertEqual([row["Variable 1"], row["Variable 2"]], want["variabili"])
                    np.testing.assert_allclose(row["r"], want["r"], rtol=1e-8, atol=1e-10)
                    np.testing.assert_allclose(row["p"], want["p"], rtol=1e-8, atol=1e-10)
                    np.testing.assert_allclose(row["Holm p"], want["p_holm"], rtol=1e-8, atol=1e-10)
                    if want["IC95"] is None:
                        self.assertTrue(np.isnan(row["CI low"]))
                        self.assertTrue(np.isnan(row["CI high"]))
                    else:
                        np.testing.assert_allclose([row["CI low"], row["CI high"]], want["IC95"], rtol=1e-8, atol=1e-10)
                matrix = result.tables[COEFFICIENTS]
                self.assertEqual(list(matrix.index), TARGETS)
                np.testing.assert_allclose(np.diag(matrix), 1.0)
                self.assertEqual(result.figure.axes[0].images[0].get_clim(), (-1.0, 1.0))
                if case["metodo"] == "Spearman":
                    self.assertIn("approximate", summary["p values"])
                    self.assertEqual(summary["Confidence interval"], "Not estimated")
                else:
                    self.assertNotIn("approximate", summary["p values"])

    def test_control_order_and_row_order_keep_the_coefficient(self):
        original = analyse(self.frame, recipe(["Z1", "Z2"]))
        reversed_controls = analyse(self.frame, recipe(["Z2", "Z1"]))
        pd.testing.assert_frame_equal(original.tables[COEFFICIENTS], reversed_controls.tables[COEFFICIENTS])
        complete = sample().iloc[:8].sample(frac=1, random_state=3)
        shuffled = analyse(complete, recipe(["Z1", "Z2"], holm=False))
        pd.testing.assert_series_equal(original.tables[PAIRS]["r"].reset_index(drop=True),
                                        shuffled.tables[PAIRS]["r"].reset_index(drop=True))

    def test_one_missing_value_leaves_every_pair_on_the_same_rows(self):
        frame = self.frame.copy()
        frame.attrs["excluded_cells"] = set(self.frame.attrs["excluded_cells"])
        frame.loc[0, "X"] = np.nan
        result = analyse(frame, recipe(["Z1", "Z2"], holm=False))
        self.assertEqual(int(result.tables[SAMPLE]["Value"]["N"]), 7)
        self.assertEqual(set(result.tables[PAIRS]["N"]), {7})
        self.assertEqual(int(result.tables[SAMPLE]["Value"]["Incomplete rows"]), 2)

    def test_constant_duplicate_rank_and_the_two_degree_limits(self):
        rng = np.random.default_rng(2)
        base = pd.DataFrame({"X": rng.normal(size=12), "Y": rng.normal(size=12), "Z": rng.normal(size=12)})
        constant = base.assign(C=1.0)
        with self.assertRaises(FieldError) as caught:
            analyse(constant, recipe(["Z", "C"], variables=["X", "Y"], holm=False))
        self.assertEqual(caught.exception.field, COVARIATES)
        self.assertIn("constant", str(caught.exception))
        duplicate = base.assign(Z2=base["Z"])
        with self.assertRaises(FieldError) as caught:
            analyse(duplicate, recipe(["Z", "Z2"], variables=["X", "Y"], holm=False))
        self.assertIn("repeats", str(caught.exception))
        linked = pd.DataFrame({"X": rng.normal(size=12), "Y": rng.normal(size=12),
                               "Z1": rng.normal(size=12)})
        linked["Z2"] = 2.0 * linked["Z1"]
        with self.assertRaises(FieldError) as caught:
            analyse(linked, recipe(["Z1", "Z2"], variables=["X", "Y"], holm=False))
        self.assertIn("full rank", str(caught.exception))
        short = base.iloc[:3]
        with self.assertRaises(FieldError) as caught:
            analyse(short, recipe(["Z"], variables=["X", "Y"], holm=False))
        self.assertIn("N − k − 2", str(caught.exception))
        edge = base.iloc[:4]
        result = analyse(edge, recipe(["Z"], variables=["X", "Y"], holm=False))
        row = result.tables[PAIRS].iloc[0]
        self.assertEqual(int(row["df"]), 1)
        self.assertTrue(np.isfinite(row["r"]) and np.isfinite(row["p"]))
        self.assertTrue(np.isnan(row["CI low"]))
        self.assertIn("N − k − 3", row["Note"])

    def test_a_perfect_line_and_a_variable_explained_by_the_covariates(self):
        rng = np.random.default_rng(4)
        z = rng.normal(size=16)
        x = rng.normal(size=16)
        perfect = pd.DataFrame({"X": x, "Y": x.copy(), "Z": z})
        result = analyse(perfect, recipe(["Z"], variables=["X", "Y"], holm=False))
        row = result.tables[PAIRS].iloc[0]
        self.assertEqual(row["r"], 1.0)
        self.assertEqual(row["p"], 0.0)
        self.assertTrue(np.isnan(row["CI low"]))
        self.assertIn("Fisher", row["Note"])
        explained = pd.DataFrame({"X": x, "Y": z.copy(), "W": rng.normal(size=16), "Z": z})
        result = analyse(explained, recipe(["Z"], variables=["X", "Y", "W"], holm=False))
        pairs = result.tables[PAIRS].set_index(["Variable 1", "Variable 2"])
        self.assertTrue(np.isnan(pairs.loc[("X", "Y"), "r"]))
        self.assertTrue(np.isnan(pairs.loc[("Y", "W"), "p"]))
        self.assertIn("Y", pairs.loc[("X", "Y"), "Note"])
        self.assertTrue(np.isfinite(pairs.loc[("X", "W"), "r"]))
        self.assertEqual(result.tables[SAMPLE]["Value"]["Not estimable"], "Y")

    def test_the_residual_scatter_keeps_the_source_rows(self):
        result = analyse(self.frame, recipe(["Z1", "Z2"], variables=["X", "Y"], scatter=True))
        heat, drawn = result.figure.axes[0], result.figure.axes[1]
        self.assertEqual(heat.images[0].get_clim(), (-1.0, 1.0))
        mapped = point_map(drawn.collections[0])
        self.assertEqual(list(mapped.rows), list(range(1, 9)))
        self.assertEqual(mapped.recipe, ("X", "Y"))
        with self.assertRaises(FieldError) as caught:
            analyse(self.frame, recipe(["Z1"], scatter=True))
        self.assertEqual(caught.exception.field, SCATTER)

    def test_text_overlap_and_cancel(self):
        with self.assertRaises(FieldError) as caught:
            analyse(self.frame, recipe(["Z1"], variables=["X", "ID"], holm=False))
        self.assertIn("ID", str(caught.exception))
        with self.assertRaises(FieldError) as caught:
            analyse(self.frame, recipe(["X"], variables=["X", "Y"], holm=False))
        self.assertIn("both", str(caught.exception))
        with self.assertRaises(PartialCorrelationCancelled) as caught:
            analyse(self.frame, recipe(["Z1", "Z2"]), cancel=lambda: True)
        self.assertEqual(str(caught.exception), CANCELLED)

    def test_the_example_project_reopens_and_an_edit_moves_the_coefficient(self):
        from analisi.data import load_project
        data = load_project(ROOT.parents[2] / "docs" / "examples" / "partial-correlation-campione.alab")["Campione"]
        self.assertEqual(data.analyses[0][1][VARIABLES], TARGETS)
        self.assertEqual(data.analyses[0][1][COVARIATES], ["Z1", "Z2"])
        frame = data.frame(mask_excluded=True)
        result = analyse(frame, data.analyses[0][1])
        self.assertAlmostEqual(float(result.tables[PAIRS].iloc[0]["r"]), -1 / sqrt(5), delta=1e-10)
        self.assertEqual(int(result.tables[SAMPLE]["Value"]["Excluded rows"]), 1)
        edited = frame.copy()
        edited.attrs["excluded_cells"] = set(frame.attrs["excluded_cells"])
        edited.loc[0, "Y"] = float(edited.loc[0, "Y"]) + 5
        moved = float(analyse(edited, data.analyses[0][1]).tables[PAIRS].iloc[0]["r"])
        self.assertGreater(abs(moved - float(result.tables[PAIRS].iloc[0]["r"])), 1e-6)
        again = Dataset(frame.copy())
        again.excluded = set(data.excluded)
        again.excluded.add((0, 1))
        again_frame = again.frame(mask_excluded=True)
        dropped = analyse(again_frame, data.analyses[0][1])
        self.assertEqual(int(dropped.tables[SAMPLE]["Value"]["N"]), 7)
        self.assertEqual(int(dropped.tables[SAMPLE]["Value"]["Excluded rows"]), 2)

    def test_dispatch_and_a_large_table(self):
        result = dispatch(METHOD, self.frame, recipe(["Z1", "Z2"], holm=False))
        self.assertAlmostEqual(float(result.tables[PAIRS].iloc[0]["r"]), -1 / sqrt(5), delta=1e-10)
        rng = np.random.default_rng(5)
        n = 50_000
        controls = {f"Z{index}": rng.normal(size=n) for index in range(4)}
        targets = {f"Y{index}": rng.normal(size=n) for index in range(8)}
        wide = pd.DataFrame({**targets, **controls})
        started = time.perf_counter()
        fitted = analyse(wide, recipe(list(controls), variables=list(targets), holm=True))
        elapsed = time.perf_counter() - started
        print(f"Partial correlation 50000x8x4: {elapsed:.3f}s")
        self.assertLess(elapsed, 15.0)
        self.assertEqual(int(fitted.tables[SAMPLE]["Value"]["N"]), n)
        self.assertEqual(len(fitted.tables[PAIRS]), 28)
        self.assertTrue(np.isfinite(fitted.tables[PAIRS]["r"]).all())


if __name__ == "__main__":
    unittest.main()
