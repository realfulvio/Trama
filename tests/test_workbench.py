import gc
from math import isclose, sqrt
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.workbench import GEOMETRIC_MEAN, METHODS, analyse


class WorkbenchTests(unittest.TestCase):
    def test_run_produces_table_and_exportable_chart(self):
        frame = pd.DataFrame({"x": [1, 2, 3], "y": [3, 5, 7]})
        result = analyse("Linear regression", frame, {"X": "x", "Y": "y"})
        self.assertEqual(result.tables["Regression"].loc["Slope", "Value"], 2)
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "plot.png"
            result.figure.savefig(png)
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_csv_export_keeps_nested_subject_ids_and_sanitizes_index(self):
        import csv
        from tramastat import safe_csv

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.csv"
            indexed = pd.DataFrame({"N": [3, 4]}, index=pd.Index(
                [("A", 1), ("B", 1)], tupleize_cols=False, name="=Subject"))
            safe_csv(path, indexed, index=True)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["'=Subject", "N"])
            self.assertEqual(rows[1], ["('A', 1)", "3"])
            indexed.index = pd.MultiIndex.from_tuples([("=A", 1), ("B", 1)], names=["Group", "ID"])
            safe_csv(path, indexed, index=True)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["Group", "ID", "N"])
            self.assertEqual(rows[1], ["'=A", "1", "3"])

    def test_save_round_trip_retains_calculated_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.alab"
            data = Dataset(pd.DataFrame({"count": [2., np.nan], "id": ["007", "NA"]}))
            data.set_formula("scaled", "=count * 3")
            data.analyses.append(("Descriptive statistics", {"Variables": ["count"]}))
            save_project(path, {"Experiment": data})
            loaded = load_project(path)["Experiment"]
            self.assertEqual(loaded.analyses, data.analyses)
            self.assertEqual(loaded.frame()["scaled"].iloc[0], 6)
            self.assertTrue(pd.isna(loaded.raw["count"].iloc[1]))
            self.assertEqual(loaded.raw["id"].tolist(), ["007", "NA"])
            loaded.raw.loc[0, "count"] = 5
            self.assertEqual(loaded.frame()["scaled"].iloc[0], 15)

    def test_descriptive_geometric_mean_and_edge_cases(self):
        self.assertEqual(METHODS["Descriptive statistics"][GEOMETRIC_MEAN], False)
        frame = pd.DataFrame({
            "Positive": [1., 2., 4., None],
            "Zero": [1., 0., 4., None],
            "Negative": [1., -1., 4., None],
            "Single": [7., None, None, None],
            "Constant": [9., 9., 9., None],
            "Overflow": [1e-80, 1e80, None, None],
        })
        base = {"Variables": list(frame)}
        legacy = analyse("Descriptive statistics", frame, base).tables["Summary"]
        off = analyse("Descriptive statistics", frame, {**base, GEOMETRIC_MEAN: False}).tables["Summary"]
        pd.testing.assert_frame_equal(off, legacy)
        self.assertEqual(list(legacy), ["N", "Missing", "Mean", "SD", "SEM", "Median", "Q1", "Q3", "Min", "Max"])

        result = analyse("Descriptive statistics", frame, {**base, GEOMETRIC_MEAN: True}).tables["Summary"]
        numeric = ["Geometric mean", "Geometric 95% CI low", "Geometric 95% CI high"]
        self.assertEqual(list(result), [*legacy, *numeric, "Geometric note"])
        pd.testing.assert_frame_equal(result[list(legacy)], legacy)

        quantile = sqrt(2) * .95 / sqrt(1 - .95**2)
        expected = [2., 2.**(1 - quantile / sqrt(3)), 2.**(1 + quantile / sqrt(3))]
        for col, val in zip(numeric, expected, strict=True):
            self.assertTrue(isclose(result.loc["Positive", col], val, rel_tol=1e-12))
        self.assertEqual(result.loc["Positive", "Geometric note"], "")

        for col in numeric:
            self.assertTrue(isclose(result.loc["Constant", col], 9., rel_tol=1e-12))
        self.assertEqual(result.loc["Constant", "Geometric note"], "")

        self.assertTrue(isclose(result.loc["Single", "Geometric mean"], 7., rel_tol=1e-12))
        self.assertTrue(result.loc["Single", numeric[1:]].isna().all())
        self.assertTrue(result.loc[["Zero", "Negative"], numeric].isna().all().all())
        self.assertTrue(isclose(result.loc["Overflow", "Geometric mean"], 1., rel_tol=1e-12))
        self.assertTrue(result.loc["Overflow", numeric[1:]].isna().all())
        for row_name in ("Zero", "Negative", "Single", "Overflow"):
            note = result.loc[row_name, "Geometric note"]
            self.assertIsInstance(note, str)
            self.assertTrue(note.strip())

    def test_descriptive_geometric_dialog_exclusion_and_project_roundtrip(self):
        try:
            import tkinter as tk
            from tramastat import AnalysisDialog, App
        except ImportError as error:
            self.skipTest(f"Tk unavailable: {error}")

        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        root.withdraw()
        app = App(root)
        errors = []
        app.error = errors.append
        try:
            def wait():
                deadline = time.monotonic() + 20

                def check():
                    if app.pending is None or time.monotonic() >= deadline:
                        root.quit()
                    else:
                        root.after(10, check)

                # Tk must process cross-thread callbacks while the calculation worker is active.
                root.after(0, check)
                root.mainloop()
                self.assertIsNone(app.pending, "Calculation timed out")
                self.assertEqual(errors, [])

            frame = pd.DataFrame({"Values": [0., 1., 2., 4.], "Constant": [9., 9., 9., np.nan]})
            app._add_tables({"Synthetic": frame})

            def check_and_enable(dialog):
                kind, var = dialog.controls[GEOMETRIC_MEAN]
                self.assertIs(kind, False)
                self.assertFalse(var.get())
                var.set(True)
                dialog.ok()

            with (patch.object(AnalysisDialog, "wait_visibility", lambda *_args: None),
                  patch.object(AnalysisDialog, "grab_set", lambda *_args: None)):
                root.after(20, lambda: check_and_enable(
                    next(w for w in root.winfo_children() if isinstance(w, AnalysisDialog))
                ))
                app.choose_analysis("Descriptive statistics")
            wait()

            run = app.runs[-1]
            self.assertEqual(run.options[GEOMETRIC_MEAN], True)
            before = run.result.tables["Summary"]
            numeric = ["Geometric mean", "Geometric 95% CI low", "Geometric 95% CI high"]
            self.assertTrue(before.loc["Values", numeric].isna().all())
            self.assertTrue(before.loc["Values", "Geometric note"].strip())

            # Exclude the leading zero (row 0, col 0) and verify automatic recalculation.
            app.show("data", "Synthetic")
            app.current_grid.select((0, 0))
            app.toggle_exclusion()
            wait()
            after = app.runs[-1].result.tables["Summary"]
            quantile = sqrt(2) * .95 / sqrt(1 - .95**2)
            expected = [2., 2.**(1 - quantile / sqrt(3)), 2.**(1 + quantile / sqrt(3))]
            for col, val in zip(numeric, expected, strict=True):
                self.assertTrue(isclose(after.loc["Values", col], val, rel_tol=1e-10))
            self.assertEqual(after.loc["Values", "Geometric note"], "")

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "synthetic-geometric.alab"
                app.path = path
                self.assertTrue(app.save())
                app.import_file(path)
                self.assertEqual(app.runs[0].options[GEOMETRIC_MEAN], True)
                app.open_sheet(("result", 0))
                wait()
                reopened = app.runs[0].result.tables["Summary"]
                pd.testing.assert_frame_equal(reopened, after)
        finally:
            app.worker.shutdown(wait=False)
            app = None
            gc.collect()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
