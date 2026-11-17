"""Nonlinear regression can publish runs and lack-of-fit sheets from the fit it already has."""
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import stats as engine
from analisi.fit_quality import REPLICATES, RESIDUAL_VIEW, RUNS
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse


def _curved():
    residual = [5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5]
    x = list(range(12))
    return pd.DataFrame({"X": x, "Y": [10 + 2 * value + error for value, error in zip(x, residual)]})


def _replicates():
    y = [1, 2, 3, 2, 3, 4, 5, 6, 7, 10, 11, 12, 17, 18, 19]
    return pd.DataFrame({"X": [value for value in range(5) for _ in range(3)], "Y": y})


def _base():
    return {"X": "X", "Y": "Y", "Model": "Straight line"}


class FitDispatchTests(unittest.TestCase):
    def test_missing_keys_match_explicit_false_and_do_not_refit(self):
        for name in (RUNS, REPLICATES, RESIDUAL_VIEW):
            self.assertIs(METHODS["Nonlinear regression"][name], False)
        data = _curved()
        legacy = analyse("Nonlinear regression", data, _base())
        off = analyse("Nonlinear regression", data, {**_base(), RUNS: False, REPLICATES: False, RESIDUAL_VIEW: False})
        self.assertEqual(list(legacy.tables), list(off.tables))
        self.assertEqual(len(legacy.figure.axes), 1)
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], off.tables[name])
        with patch.object(engine, "nonlinear", wraps=engine.nonlinear) as calls:
            result = analyse("Nonlinear regression", data, {**_base(), RUNS: True})
        self.assertEqual(calls.call_count, 1)
        for name in legacy.tables:
            pd.testing.assert_frame_equal(legacy.tables[name], result.tables[name])
        metrics = result.tables["Runs test: All"]["Value"].to_dict()
        self.assertEqual(metrics["Status"], "Available")
        self.assertEqual(metrics["Observed runs"], 3)
        self.assertAlmostEqual(metrics["p"], 0.012987012987012988)

    def test_replicates_keep_the_fit_when_runs_are_unavailable(self):
        data = _replicates()
        result = analyse("Nonlinear regression", data, {**_base(), RUNS: True, REPLICATES: True})
        runs = result.tables["Runs test: All"]["Value"].to_dict()
        lack = result.tables["Replicate lack of fit: All"]["Value"].to_dict()
        self.assertEqual(runs["Status"], "Not available")
        self.assertIsNone(runs["p"])
        self.assertIn("replicate", runs["Reason"].lower())
        self.assertEqual(lack["Status"], "Available")
        self.assertAlmostEqual(lack["F"], 14)
        self.assertAlmostEqual(lack["p"], 0.0006523706476901394)
        self.assertIn("Parameters: All", result.tables)

    def test_one_bad_group_does_not_hide_the_other_and_weights_fail_before_the_fit(self):
        curved = _curved()
        ordered = curved.assign(Group="ordered")
        unsorted = curved.iloc[::-1].assign(Group="unsorted")
        grouped = analyse("Nonlinear regression", pd.concat([ordered, unsorted], ignore_index=True),
                          {**_base(), "Group": "Group", RUNS: True})
        self.assertEqual(grouped.tables["Runs test: ordered"].loc["Status", "Value"], "Available")
        self.assertEqual(grouped.tables["Runs test: unsorted"].loc["Status", "Value"], "Not available")
        with patch.object(engine, "nonlinear", wraps=engine.nonlinear) as calls:
            with self.assertRaises(FieldError) as caught:
                analyse("Nonlinear regression", curved, {**_base(), "Weighting": "1/Y²", RUNS: True, REPLICATES: True})
        self.assertEqual(caught.exception.field, RUNS)
        self.assertEqual(calls.call_count, 0)
        with self.assertRaises(FieldError) as only:
            analyse("Nonlinear regression", curved, {**_base(), "Weighting": "1/Y²", REPLICATES: True})
        self.assertEqual(only.exception.field, REPLICATES)
        plain = analyse("Nonlinear regression", curved, {**_base(), "Weighting": "1/Y²"})
        view = analyse("Nonlinear regression", curved, {**_base(), "Weighting": "1/Y²", RESIDUAL_VIEW: True})
        self.assertNotIn("Runs test: All", view.tables)
        for name in plain.tables:
            pd.testing.assert_frame_equal(plain.tables[name], view.tables[name])
        labels = [ax.get_ylabel().lower() for ax in view.figure.axes]
        self.assertTrue(any("resid" in label and "raw" in label for label in labels))

    def test_residual_view_is_opt_in_and_keeps_every_fitted_row(self):
        data = _curved()
        legacy = analyse("Nonlinear regression", data, _base())
        self.assertEqual(len(legacy.figure.axes), 1)
        view = analyse("Nonlinear regression", data, {**_base(), RESIDUAL_VIEW: True})
        self.assertGreaterEqual(len(view.figure.axes), 2)
        panels = [ax for ax in view.figure.axes if "resid" in ax.get_ylabel().lower()]
        self.assertTrue(panels)
        self.assertTrue(any(len(collection.get_offsets()) == len(data)
                            for ax in panels for collection in ax.collections))
        self.assertTrue(any(len(line.get_ydata()) and all(abs(float(y)) < 1e-15 for y in line.get_ydata())
                            for ax in panels for line in ax.lines))
        paired = data.assign(Z=data["Y"] + 1)
        both = analyse("Nonlinear regression", paired, {"X": "X", "Y columns": ["Y", "Z"], "Model": "Straight line",
                                                        RESIDUAL_VIEW: True})
        self.assertGreaterEqual(len(both.figure.axes), 4)


if __name__ == "__main__":
    unittest.main()
