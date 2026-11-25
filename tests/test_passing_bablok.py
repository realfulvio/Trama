"""Passing–Bablok regression beside Deming, tangent metric.

The two published samples are the fractions in ``tests/data/passing-bablok/casi.json``.
``_tangent`` repeats that ranking with fractions and does not call the engine.
"""
from fractions import Fraction
from itertools import combinations
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.analysis_chain import ChainCancelled
from analisi.field_error import FieldError
from analisi.i18n import active_language, set_language
from analisi.passing_bablok import (CALCULATION, IDENTITY, LEVEL, METHOD, NOTES, PAIRS, SHEET, SLOPE_LIMIT,
                                   listed_in_classic)
from analisi.workbench import GROUPS, GRAPH_METHODS, analyse

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

ROOT = Path(__file__).resolve().parent / "data" / "passing-bablok"
CASES = json.loads((ROOT / "casi.json").read_text(encoding="utf-8"))


def _tangent(x_values, y_values):
    """mcr's tangent median on exact fractions, without vertical pairs."""
    slopes = []
    for (x1, y1), (x2, y2) in combinations(list(zip(x_values, y_values)), 2):
        if x1 != x2:
            slopes.append(Fraction(y2 - y1, x2 - x1))
    below = sum(slope < -1 for slope in slopes)
    equal = sum(slope == -1 for slope in slopes)
    slopes.sort()
    shifted = len(slopes) + 2 * below + equal
    half = (shifted + 1) // 2
    slope = slopes[half - 1] if shifted % 2 else (slopes[half - 1] + slopes[half]) / 2
    residuals = sorted(Fraction(y) - slope * Fraction(x) for x, y in zip(x_values, y_values))
    count = len(residuals)
    half = (count + 1) // 2
    intercept = residuals[half - 1] if count % 2 else (residuals[half - 1] + residuals[half]) / 2
    return slope, intercept


def _frame(x_values, y_values, x_name="Reference", y_name="Method"):
    return pd.DataFrame({x_name: x_values, y_name: y_values})


def _run(x_values, y_values, **extra):
    options = {"X": "Reference", "Y": "Method", LEVEL: 95.0, IDENTITY: False}
    options.update(extra)
    return analyse(METHOD, _frame(x_values, y_values), options)


def _estimate(result, parameter):
    sheet = result.tables[SHEET].set_index("Parameter")
    return float(sheet.loc[parameter, "Estimate"])


class EngineTests(unittest.TestCase):
    def test_the_published_samples_match_the_fraction_ranking(self):
        for example in CASES["cases"]:
            with self.subTest(slope=example["slope"]):
                result = _run(example["x"], example["y"])
                slope, intercept = _tangent(example["x"], example["y"])
                self.assertEqual(slope, Fraction(str(example["slope"])))
                self.assertEqual(intercept, Fraction(str(example["intercept"])))
                self.assertAlmostEqual(_estimate(result, "Slope"), float(slope), places=12)
                self.assertAlmostEqual(_estimate(result, "Intercept"), float(intercept), places=12)
                details = result.tables[CALCULATION].set_index("Item")["Value"]
                self.assertEqual(int(details["Valid pairs"]), 4)
                self.assertEqual(int(details["Slopes used"]), 6)
                self.assertIn("not estimable", " ".join(result.tables[NOTES]["Note"]))
                self.assertIn("Tangent metric", result.tables[NOTES]["Note"].iloc[0])

    def test_a_slope_between_minus_one_and_zero_stays_in_the_ranking(self):
        x_values, y_values = [1, 3, 4, 6], [5, 4, 6, 8]
        result = _run(x_values, y_values)
        slope, intercept = _tangent(x_values, y_values)
        negative = [Fraction(y2 - y1, x2 - x1)
                    for (x1, y1), (x2, y2) in combinations(list(zip(x_values, y_values)), 2)
                    if Fraction(y2 - y1, x2 - x1) < 0]
        self.assertTrue(negative)
        self.assertTrue(all(Fraction(-1) < value < 0 for value in negative))
        self.assertAlmostEqual(_estimate(result, "Slope"), float(slope), places=12)
        self.assertAlmostEqual(_estimate(result, "Intercept"), float(intercept), places=12)
        details = result.tables[CALCULATION].set_index("Item")["Value"]
        self.assertGreater(int(details["Slopes in (−1, 0)"]), 0)

    def test_a_slope_of_minus_one_is_kept_and_matches_the_fraction_ranking(self):
        x_values, y_values = [1, 2, 3, 5], [2, 1, 4, 5]
        result = _run(x_values, y_values)
        slope, intercept = _tangent(x_values, y_values)
        self.assertAlmostEqual(_estimate(result, "Slope"), float(slope), places=12)
        self.assertAlmostEqual(_estimate(result, "Intercept"), float(intercept), places=12)
        details = result.tables[CALCULATION].set_index("Item")["Value"]
        self.assertEqual(int(details["Slopes equal to −1"]), 1)
        self.assertIn("equal to −1 kept", " ".join(result.tables[NOTES]["Note"]))

    def test_duplicate_x_is_a_vertical_slope_and_the_line_still_fits(self):
        result = _run([1, 1, 2, 3, 4], [2, 5, 4, 6, 8])
        details = result.tables[CALCULATION].set_index("Item")["Value"]
        self.assertGreaterEqual(int(details["Vertical slopes"]), 1)
        self.assertIn("vertical slopes", " ".join(result.tables[NOTES]["Note"]))
        self.assertTrue(np.isfinite(_estimate(result, "Slope")))
        self.assertEqual(len(result.tables[PAIRS]), 5)

    def test_a_near_tie_in_x_is_treated_as_repeated(self):
        result = _run([1.0, 1.0 + 1e-16, 2.0, 3.0], [1.0, 4.0, 2.0, 3.0])
        details = result.tables[CALCULATION].set_index("Item")["Value"]
        self.assertGreaterEqual(int(details["Vertical slopes"]), 1)

    def test_missing_and_excluded_rows_are_counted_and_left_out_of_the_fit(self):
        frame = _frame([1, 2, 3, 4, 5], [4, 2, 5, 7, None])
        frame.iloc[0, 1] = np.nan  # excluded cells arrive as missing values
        kept = _run([2, 3, 4], [2, 5, 7])
        result = analyse(METHOD, frame, {"X": "Reference", "Y": "Method", LEVEL: 95.0})
        self.assertEqual(_estimate(result, "Slope"), _estimate(kept, "Slope"))
        details = result.tables[CALCULATION].set_index("Item")["Value"]
        self.assertEqual(int(details["Incomplete rows"]), 2)
        self.assertEqual(int(details["Valid pairs"]), 3)
        self.assertIn("missing or excluded: 2", " ".join(result.tables[NOTES]["Note"]))

    def test_swapping_the_columns_is_the_saved_direction_and_changes_the_line(self):
        frame = _frame([1, 2, 3, 4], [4, 2, 5, 7])
        forward = analyse(METHOD, frame, {"X": "Reference", "Y": "Method", LEVEL: 95.0})
        backward = analyse(METHOD, frame, {"X": "Method", "Y": "Reference", LEVEL: 95.0})
        self.assertNotAlmostEqual(_estimate(forward, "Slope"), _estimate(backward, "Slope"), places=6)
        self.assertEqual(backward.tables[PAIRS].columns.tolist(), ["Method", "Reference"])

    def test_interior_intervals_match_the_recorded_mcr_run(self):
        # R 4.5.3, mcr 1.3.3.1: mcreg(..., method.reg="PaBa", method.ci="analytical",
        # slope.measure="tangent", alpha=0.05). Finite ends only; four pairs are blank here.
        recorded = {
            11: {"Slope": (3.0, 2.888888888888889, 3.111111111111111),
                 "Intercept": (-1.0, -1.111111111111111, 0.2222222222222214)},
            16: {"Slope": (1.666666666666667, 1.533333333333333, 1.75),
                 "Intercept": (0.8333333333333321, -0.5000000000000022, 2.566666666666666)},
        }
        odd = list(range(1, 12))
        samples = {
            11: (odd, [3 * x + ((-1) ** x) for x in odd]),
            16: ([1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 13, 15, 16, 18, 20, 22],
                 [4, 3, 8, 7, 11, 10, 15, 14, 18, 20, 22, 26, 27, 31, 34, 38]),
        }
        for count, (x_values, y_values) in samples.items():
            sheet = _run(x_values, y_values).tables[SHEET].set_index("Parameter")
            for parameter, (estimate, low, high) in recorded[count].items():
                self.assertAlmostEqual(float(sheet.loc[parameter, "Estimate"]), estimate, places=9)
                self.assertAlmostEqual(float(sheet.loc[parameter, "CI low"]), low, places=9)
                self.assertAlmostEqual(float(sheet.loc[parameter, "CI high"]), high, places=9)
        falling = _run([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [20, 18, 17, 14, 12, 11, 9, 7, 5, 2])
        sheet = falling.tables[SHEET].set_index("Parameter")
        self.assertAlmostEqual(float(sheet.loc["Slope", "Estimate"]), -2.0, places=9)
        self.assertAlmostEqual(float(sheet.loc["Slope", "CI low"]), -2.0, places=9)
        self.assertAlmostEqual(float(sheet.loc["Slope", "CI high"]), -1.8, places=9)
        self.assertAlmostEqual(float(sheet.loc["Intercept", "Estimate"]), 22.5, places=9)
        self.assertAlmostEqual(float(sheet.loc["Intercept", "CI low"]), 21.5, places=9)
        self.assertAlmostEqual(float(sheet.loc["Intercept", "CI high"]), 22.5, places=9)
        self.assertEqual(falling.tables[CALCULATION].set_index("Item").loc["Positive correlation", "Value"], "No")

    def test_even_and_odd_samples_with_an_interior_interval(self):
        odd = list(range(1, 12))
        odd_y = [3 * x + ((-1) ** x) for x in odd]
        even_x = [1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 13, 15, 16, 18, 20, 22]
        even_y = [4, 3, 8, 7, 11, 10, 15, 14, 18, 20, 22, 26, 27, 31, 34, 38]
        for x_values, y_values in ((odd, odd_y), (even_x, even_y)):
            result = _run(x_values, y_values)
            sheet = result.tables[SHEET].set_index("Parameter")
            slope, intercept = _tangent(x_values, y_values)
            self.assertAlmostEqual(_estimate(result, "Slope"), float(slope), places=12)
            self.assertAlmostEqual(_estimate(result, "Intercept"), float(intercept), places=12)
            for parameter in ("Slope", "Intercept"):
                estimate = float(sheet.loc[parameter, "Estimate"])
                low = float(sheet.loc[parameter, "CI low"])
                high = float(sheet.loc[parameter, "CI high"])
                self.assertTrue(np.isfinite([low, estimate, high]).all())
                self.assertLess(low, estimate)
                self.assertGreater(high, estimate)
            self.assertEqual(result.tables[CALCULATION].set_index("Item").loc["Interval", "Value"],
                             "Passing–Bablok analytical (tangent)")

    def test_a_negative_pair_is_fitted_and_the_note_names_the_mcr_difference(self):
        result = _run([1, 2, 3, 4], [-4, -2, -5, -7])
        self.assertTrue(np.isfinite(_estimate(result, "Slope")))
        self.assertIn("mcr 1.3.3.1 stops", " ".join(result.tables[NOTES]["Note"]))

    def test_a_constant_axis_keeps_the_points_and_names_the_cause(self):
        result = _run([1, 1, 1, 1], [1, 2, 3, 4])
        self.assertTrue(np.isnan(_estimate(result, "Slope")))
        self.assertIn("do not both vary", " ".join(result.tables[NOTES]["Note"]))
        self.assertEqual(len(result.figure.axes[0].collections), 1)
        self.assertEqual(len(result.figure.axes[0].lines), 0)

    def test_three_pairs_are_required_and_the_limit_is_checked_before_allocation(self):
        with self.assertRaises(FieldError) as few:
            _run([1, 2], [1, 2])
        self.assertEqual(few.exception.field, "X")
        self.assertIn("at least 3", str(few.exception))
        count = 2001
        with patch("analisi.passing_bablok.np.triu_indices", side_effect=AssertionError("allocated")):
            with self.assertRaises(FieldError) as limited:
                _run(list(range(count)), list(range(count)))
        self.assertIn(str(SLOPE_LIMIT), str(limited.exception))
        self.assertIn("before allocating", str(limited.exception))

    def test_cancellation_stops_before_the_pairwise_slopes(self):
        event = threading.Event()
        event.set()
        for cancel in (lambda: True, event):
            with patch("analisi.passing_bablok.np.triu_indices", side_effect=AssertionError("allocated")):
                with self.assertRaises(ChainCancelled):
                    analyse(METHOD, _frame([1, 2, 3, 4], [4, 2, 5, 7]),
                            {"X": "Reference", "Y": "Method"}, cancel=cancel)
        result = analyse(METHOD, _frame([1, 2, 3, 4], [4, 2, 5, 7]),
                         {"X": "Reference", "Y": "Method"}, cancel=threading.Event())
        self.assertIn(SHEET, result.tables)

    def test_the_figure_exports_and_the_identity_line_is_optional(self):
        plain = _run([1, 2, 3, 4], [4, 2, 5, 7])
        marked = _run([1, 2, 3, 4], [4, 2, 5, 7], **{IDENTITY: True})
        self.assertEqual(len(plain.figure.axes[0].lines), 1)
        self.assertEqual(len(marked.figure.axes[0].lines), 2)
        self.assertEqual(marked.figure.axes[0].get_lines()[1].get_label(), "Identity")
        for suffix in ("png", "svg", "pdf"):
            from io import BytesIO
            buffer = BytesIO()
            marked.figure.savefig(buffer, format=suffix)
            self.assertGreater(buffer.tell(), 100)

    def test_deming_recipes_and_existing_command_positions_stay(self):
        names = GROUPS["Regression and Curves"]
        deming = names.index("Deming regression")
        self.assertEqual(names[deming + 1], METHOD)
        self.assertEqual(names[deming - 1], "Compare regression lines")
        self.assertEqual(names[deming + 2], "Multiple regression")
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertFalse(listed_in_classic(METHOD, "Linear regression"))
        self.assertTrue(listed_in_classic(METHOD, METHOD))
        self.assertTrue(listed_in_classic("Deming regression", "Linear regression"))
        from trama_qt.classic_bar import GROUPS as toolbar
        analysis = next(group for group in toolbar if group[0] == "Analysis")
        self.assertEqual(analysis[1][:3], ("analyze", "linear", "nonlinear"))
        frame = _frame([1, 2, 3, 4, 5], [2, 4, 5, 8, 9], "x", "y")
        deming_result = analyse("Deming regression", frame, {"X": "x", "Y": "y", "Y / X error variance": 1.0})
        self.assertEqual(list(deming_result.tables), ["Deming regression", "Data", "Pairs"])
        self.assertNotIn(SHEET, deming_result.tables)

    def test_the_example_project_keeps_the_acceptance_line_and_the_direction(self):
        from analisi.data import load_project
        data = load_project(ROOT / "passing-bablok.alab")["Metodi"]
        method, options = data.analyses[0]
        self.assertEqual((method, options["X"], options["Y"], options[IDENTITY]),
                         (METHOD, "Riferimento", "Metodo", True))
        result = analyse(method, data.frame(mask_excluded=True), options)
        self.assertAlmostEqual(_estimate(result, "Slope"), 2.25, places=12)
        self.assertAlmostEqual(_estimate(result, "Intercept"), -1.875, places=12)
        notes = " ".join(result.tables[NOTES]["Note"])
        self.assertIn("missing or excluded: 2", notes)
        self.assertIn("not estimable", notes)
        self.assertEqual(len(result.figure.axes[0].lines), 2)

    def test_two_thousand_pairs_stay_inside_the_limit(self):
        import time
        count = 2000
        x_values = np.linspace(1.0, 10.0, count)
        y_values = 2.0 * x_values + 1.0
        started = time.perf_counter()
        result = _run(x_values, y_values)
        elapsed = time.perf_counter() - started
        self.assertEqual(int(result.tables[CALCULATION].set_index("Item").loc["Valid pairs", "Value"]), count)
        self.assertLess(elapsed, 5.0)


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not importable")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)

    def _dialog(self, language="en"):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language(language)
        frame = _frame([1, 2, 3, 4], [4, 2, 5, 7])
        dialog = AnalysisDialog(None, frame, current=(METHOD, {}))
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.reject)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _order(self, dialog):
        tree = dialog.methods
        for index in range(tree.topLevelItemCount()):
            folder = tree.topLevelItem(index)
            labels = [folder.child(child).data(0, Qt.ItemDataRole.UserRole) for child in range(folder.childCount())]
            if METHOD in labels:
                return labels
        self.fail("Passing–Bablok is not in the Qt method list")

    def test_the_qt_list_places_it_immediately_after_deming(self):
        labels = self._order(self._dialog())
        self.assertEqual(labels[labels.index("Deming regression") + 1], METHOD)
        self.assertEqual(labels[labels.index(METHOD) + 1], "Multiple regression")
        dialog = self._dialog()
        self.assertFalse(dialog.controls[IDENTITY][1].isChecked())
        dialog.accept()
        self.assertIs(dialog.result[1][IDENTITY], False)
        self.assertEqual(dialog.result[1]["X"], "Reference")
        self.assertEqual(dialog.result[1]["Y"], "Method")

    def test_italian_name_and_a_non_finite_level_stay_in_the_dialog(self):
        dialog = self._dialog("it")
        labels = self._order(dialog)
        folder = next(dialog.methods.topLevelItem(index) for index in range(dialog.methods.topLevelItemCount())
                      if METHOD in [dialog.methods.topLevelItem(index).child(child).data(0, Qt.ItemDataRole.UserRole)
                                    for child in range(dialog.methods.topLevelItem(index).childCount())])
        child = folder.child(labels.index(METHOD))
        self.assertEqual(child.text(0), "Regressione di Passing–Bablok")
        dialog.controls[LEVEL][1].setText("inf")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.text())

    def test_a_short_sample_is_translated(self):
        from analisi.passing_bablok import format_error
        set_language("it")
        with self.assertRaises(FieldError) as error:
            _run([1, 2], [1, 2])
        self.assertIn("almeno 3", format_error(error.exception))
