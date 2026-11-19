"""Global fit custom equation in the Qt window: the coefficient and series-constraint editors, offscreen.

Data in tests/data/qt_global_fit (synthetic): Y = A + 2 X with A = 1 for "Control $" and A = 4 for "Batch B",
plus residuals ±0.25, so the joint least-squares fit has A = 1 and 4, B = 2, RSS 0.5 and 5 residual df.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "qt_global_fit"
METHOD = "Global fit custom equation"
RECIPE = json.loads((DATA / "recipe.json").read_text(encoding="utf-8"))


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _estimates(result):
    rows = {}
    for row in result.tables["Parameters"].to_dict("records"):
        group = None if pd.isna(row["Group"]) else row["Group"]
        rows[(group, row["Parameter"])] = (row["Scope"], row["Estimate"])
    return rows, result.tables["Global fit"]["Value"]


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class GlobalFitEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)
        self.frame = pd.read_csv(DATA / "linear.csv")

    def dialog(self, recipe=None, frame=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.frame if frame is None else frame,
                                current=(METHOD, deepcopy(RECIPE) if recipe is None else recipe), only=METHOD)
        dialog.show()
        dialog.activateWindow()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def editors(self, dialog):
        return dialog.controls["Parameters"][1], dialog.controls["Series constraints"][1]

    def confirm(self, dialog):
        dialog.accept()
        self.app.processEvents()
        return dialog.result

    def analyse(self, options):
        from analisi.workbench import analyse
        return analyse(METHOD, self.frame, options)

    # -- editors and canonical values ------------------------------------------------------------------------
    def test_real_editors_keep_the_canonical_recipe_in_both_languages(self):
        from trama_qt.global_fit import GlobalCoefficientEditor, GlobalSeriesEditor
        for language in ("en", "it"):
            set_language(language)
            dialog = self.dialog()
            kind, coefficients = dialog.controls["Parameters"]
            self.assertEqual(kind, "Global coefficient list")
            self.assertIsInstance(coefficients, GlobalCoefficientEditor)
            kind, series = dialog.controls["Series constraints"]
            self.assertEqual(kind, "Global series constraints")
            self.assertIsInstance(series, GlobalSeriesEditor)
            self.assertEqual(series.labels(), ["Control $", "Batch B"])
            options = dialog.options()
            self.assertEqual(options["Parameters"], RECIPE["Parameters"])
            self.assertEqual(options["Series constraints"], RECIPE["Series constraints"])
            # Confirmed without a change, the recipe comes back identical (no default keys are added).
            self.assertEqual(self.confirm(dialog), (METHOD, RECIPE))
            dialog.reject()

    def test_new_analysis_starts_from_an_example_that_fits_the_equation(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.frame, current=(METHOD, {}), only=METHOD)
        self.addCleanup(dialog.deleteLater)
        options = dialog.options()
        self.assertEqual(options["Equation"], "A + B*X")
        self.assertEqual([(p["name"], p["shared"]) for p in options["Parameters"]], [("A", False), ("B", True)])
        self.assertEqual(options["Group"], "Series")
        self.assertEqual(options["Series constraints"], [])

    def test_fit_with_a_local_and_a_shared_coefficient_then_a_fixed_series_value(self):
        recipe = deepcopy(RECIPE)
        recipe["Series constraints"] = []
        dialog = self.dialog(recipe)
        coefficients, series = self.editors(dialog)
        method, options = self.confirm(dialog)
        rows, summary = _estimates(self.analyse(options))
        self.assertEqual(rows[("Control $", "A")][0], "Local")
        for key, value in ((("Control $", "A"), 1.0), (("Batch B", "A"), 4.0), ((None, "B"), 2.0)):
            self.assertTrue(math.isclose(rows[key][1], value, rel_tol=1e-7, abs_tol=1e-8), (key, rows[key]))
        self.assertEqual(summary["DF residual"], 5)
        self.assertTrue(math.isclose(summary["Residual SS"], .5, rel_tol=1e-7))

        dialog = self.dialog(options)
        coefficients, series = self.editors(dialog)
        series.set_override("Control $", "A", "fixed", "1")
        method, options = self.confirm(dialog)
        self.assertEqual(options["Series constraints"], RECIPE["Series constraints"])
        rows, summary = _estimates(self.analyse(options))
        self.assertEqual(rows[("Control $", "A")][0], "Fixed")
        self.assertTrue(math.isclose(rows[("Batch B", "A")][1], 4.0, rel_tol=1e-7))
        self.assertTrue(math.isclose(rows[(None, "B")][1], 2.0, rel_tol=1e-7))
        self.assertEqual(summary["DF residual"], 6)
        self.assertTrue(math.isclose(summary["Residual SS"], .5, rel_tol=1e-7))

    def test_scope_limits_and_decimal_comma(self):
        dialog = self.dialog()
        coefficients, _series = self.editors(dialog)
        coefficients.set_cell(0, coefficients.LOWER, "-2,5")
        coefficients.set_cell(0, coefficients.UPPER, "")
        coefficients.set_scope(1, "Fixed")
        coefficients.set_cell(1, coefficients.START, "2")
        values = dialog.options()["Parameters"]
        self.assertEqual(values[0], {"name": "A", "start": 1.0, "lower": -2.5, "upper": None,
                                     "fixed": False, "shared": False})
        self.assertEqual(values[1], {"name": "B", "start": 2.0, "lower": 0.0, "upper": 4.0,
                                     "fixed": True, "shared": False})
        method, options = self.confirm(dialog)
        rows, summary = _estimates(self.analyse(options))
        self.assertEqual(rows[(None, "B")][0], "Fixed")

    # -- errors keep the dialog open, with the cursor on the field --------------------------------------------
    def assert_open_with_error(self, dialog):
        self.assertIsNone(self.confirm(dialog))
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.banner.isVisible())
        self.assertTrue(dialog.banner.text())

    def test_reversed_limits_focus_the_lower_cell_and_keep_the_values(self):
        dialog = self.dialog()
        coefficients, _series = self.editors(dialog)
        coefficients.set_cell(1, coefficients.LOWER, "3")
        coefficients.set_cell(1, coefficients.UPPER, "1")
        self.assert_open_with_error(dialog)
        self.assertIn("lower limit", dialog.banner.text())
        self.assertIs(dialog.tabs.currentWidget().widget().layout(), dialog.rows["Parameters"][2])
        self.assertEqual((coefficients.table.currentRow(), coefficients.table.currentColumn()),
                         (1, coefficients.LOWER))
        self.assertTrue(coefficients.table.hasFocus())
        self.assertEqual(coefficients.cell(1, coefficients.LOWER), "3")
        self.assertEqual(coefficients.cell(1, coefficients.UPPER), "1")
        # Correct it and confirm.
        coefficients.set_cell(1, coefficients.LOWER, "0")
        coefficients.set_cell(1, coefficients.UPPER, "4")
        self.assertEqual(self.confirm(dialog), (METHOD, RECIPE))

    def test_number_that_is_not_finite_is_located(self):
        dialog = self.dialog()
        coefficients, _series = self.editors(dialog)
        coefficients.set_cell(0, coefficients.START, "inf")
        self.assert_open_with_error(dialog)
        self.assertEqual((coefficients.table.currentRow(), coefficients.table.currentColumn()),
                         (0, coefficients.START))

    def test_shared_coefficient_rejects_a_series_value_on_its_field(self):
        dialog = self.dialog()
        _coefficients, series = self.editors(dialog)
        self.assertFalse(series.fields[("B", "fixed")].isEnabled())  # Not offered for a shared coefficient.
        series.set_override("Control $", "B", "fixed", "2")
        series.select_series("Batch B")
        self.assert_open_with_error(dialog)
        self.assertIn("shared", dialog.banner.text())
        self.assertEqual(series.series, "Control $")
        field = series.fields[("B", "fixed")]
        self.assertTrue(field.hasFocus())
        self.assertEqual(field.text(), "2")
        # A limit on a shared coefficient is allowed and applies to every series.
        series.set_override("Control $", "B", "fixed", "")
        series.set_override("Control $", "B", "upper", "3")
        method, options = self.confirm(dialog)
        self.assertEqual(options["Series constraints"],
                         [{"series": "Control $", "parameters": {"A": {"fixed": 1.0}, "B": {"upper": 3.0}}}])

    def test_series_outside_the_data_is_shown_located_and_removed_on_request(self):
        dialog = self.dialog()
        _coefficients, series = self.editors(dialog)
        group = dialog.controls["Group"][1]
        group.setCurrentIndex(group.findData("SD"))
        self.app.processEvents()
        self.assertEqual(series.available, ["0.5", "1.0"])
        self.assertIn("Control $", series.labels())
        self.assertTrue(series.prune_button.isEnabled())
        self.assertIn("Control $", series.warning.text())
        series.select_series("0.5")
        self.assert_open_with_error(dialog)
        self.assertEqual(series.series, "Control $")
        self.assertTrue(series.fields[("A", "fixed")].hasFocus())
        # Back to Series: the constraint applies again; to SD again, then remove it explicitly.
        group.setCurrentIndex(group.findData("Series"))
        self.assertEqual(series.available, ["Control $", "Batch B"])
        group.setCurrentIndex(group.findData("SD"))
        self.assertEqual(series.prune(), 1)
        self.assertNotIn("Control $", series.labels())
        method, options = self.confirm(dialog)
        self.assertEqual(options["Group"], "SD")
        self.assertEqual(options["Series constraints"], [])

    def test_constraint_for_a_removed_coefficient_is_located(self):
        dialog = self.dialog()
        coefficients, series = self.editors(dialog)
        dialog.controls["Equation"][1].setPlainText("B*X")
        self.assertTrue(coefficients.read_equation())
        self.assertEqual(coefficients.names(), ["B"])
        self.assertIn("A", coefficients.status.text())
        self.assertIn("A", series.warning.text())
        self.assert_open_with_error(dialog)
        self.assertEqual(series.series, "Control $")
        self.assertTrue(series.fields[("A", "fixed")].hasFocus())

    # -- copies, Cancel and reopenings ------------------------------------------------------------------------
    def test_cancel_leaves_the_caller_values_and_reopening_starts_from_the_last_confirmed_recipe(self):
        caller = deepcopy(RECIPE)
        dialog = self.dialog(caller)
        coefficients, series = self.editors(dialog)
        coefficients.set_scope(0, "Shared")
        coefficients.set_cell(1, coefficients.START, "9")
        series.set_override("Batch B", "A", "initial", "3")
        dialog.reject()
        self.assertEqual(caller, RECIPE)

        confirmed = deepcopy(RECIPE)
        for _ in range(2):
            dialog = self.dialog(confirmed)
            coefficients, series = self.editors(dialog)
            self.assertEqual(coefficients.values(), confirmed["Parameters"])
            self.assertEqual(series.values(), confirmed["Series constraints"])
            series.set_override("Batch B", "A", "initial", "3,5")
            method, options = self.confirm(dialog)
            self.assertEqual(options["Series constraints"][-1],
                             {"series": "Batch B", "parameters": {"A": {"initial": 3.5}}})
            confirmed = options
        dialog = self.dialog(confirmed)
        self.assertEqual(self.editors(dialog)[1].values(), confirmed["Series constraints"])
        dialog.reject()

    # -- equations --------------------------------------------------------------------------------------------
    def test_read_from_equation_keeps_settings_in_order_and_reports_removed_names(self):
        from trama_qt.global_fit import equation_names
        self.assertEqual(equation_names("C*exp(-K*X) + A + C", "Arithmetic"), ["C", "K", "A"])
        dialog = self.dialog()
        coefficients, _series = self.editors(dialog)
        dialog.controls["Equation"][1].setPlainText("C + B*X + A*X^2")
        self.assertIn("C", coefficients.status.text())  # In the equation, not yet in the list.
        self.assertTrue(coefficients.read_equation())
        self.assertEqual([row["name"] for row in coefficients.rows()], ["C", "B", "A"])
        b = coefficients.rows()[1]
        self.assertEqual((b["lower"], b["upper"], b["scope"]), ("0", "4", "Shared"))
        dialog.controls["Equation"][1].setPlainText("B*X + C")
        self.assertIn("A", coefficients.status.text())  # Not used any more.
        coefficients.read_equation()
        self.assertEqual(coefficients.names(), ["B", "C"])
        self.assertIn("A", coefficients.status.text())
        # An equation that does not compile leaves the list as it was.
        dialog.controls["Equation"][1].setPlainText("B*X + (")
        self.assertFalse(coefficients.read_equation())
        self.assertEqual(coefficients.names(), ["B", "C"])

    def test_conditional_equation_with_a_fixed_threshold(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3, 4, 0, 1, 2, 3, 4],
                              "Y": [1.1, 2.9, 5.0, 5.1, 4.9, 2.0, 4.1, 6.0, 5.9, 6.1],
                              "Series": ["P"] * 5 + ["Q"] * 5})
        recipe = {"X": "X", "Y": "Y", "Group": "Series", "Equation syntax": "Conditional",
                  "Equation": "if(X < T, A + B*X, A + B*T)",
                  "Parameters": [], "Series constraints": [], "Weighting": "Unweighted"}
        dialog = self.dialog(recipe, frame)
        coefficients, _series = self.editors(dialog)
        self.assertTrue(coefficients.read_equation())
        self.assertEqual(coefficients.names(), ["T", "A", "B"])
        coefficients.set_scope(2, "Shared")
        # A threshold that is estimated is refused on the Parameters page.
        self.assert_open_with_error(dialog)
        self.assertIn("condition", dialog.banner.text())
        self.assertEqual((coefficients.table.currentRow(), coefficients.table.currentColumn()),
                         (0, coefficients.SCOPE))
        coefficients.set_scope(0, "Fixed")
        coefficients.set_cell(0, coefficients.START, "2")
        method, options = self.confirm(dialog)
        self.assertEqual(options["Parameters"][0], {"name": "T", "start": 2.0, "lower": None, "upper": None,
                                                    "fixed": True, "shared": False})
        from analisi.workbench import analyse
        result = analyse(METHOD, frame, options)
        expected = analyse(METHOD, frame, {**recipe, "Parameters": options["Parameters"]})
        pd.testing.assert_frame_equal(result.tables["Parameters"], expected.tables["Parameters"])
        rows = {(r["Group"], r["Parameter"]): r["Estimate"] for r in result.tables["Parameters"].to_dict("records")
                if r["Parameter"] == "B"}
        self.assertTrue(all(math.isclose(value, 2.0, abs_tol=0.1) for value in rows.values()))

    def test_errors_are_shown_in_italian(self):
        set_language("it")
        dialog = self.dialog()
        coefficients, _series = self.editors(dialog)
        coefficients.set_cell(1, coefficients.LOWER, "3")
        coefficients.set_cell(1, coefficients.UPPER, "1")
        self.assert_open_with_error(dialog)
        self.assertNotIn("lower limit", dialog.banner.text())
        self.assertIn("Coefficienti", dialog.banner.text())


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class GlobalFitWindowTests(unittest.TestCase):
    """The saved project in the window: identity, Cancel, edit and exclusion, recalculation and export."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def window(self):
        from trama_qt.window import MainWindow
        window = MainWindow()
        window.project.dirty = False
        window._ask_original = window._ask
        window.error = lambda error: self.fail(f"error shown: {error}")
        window.show()
        self.app.processEvents()

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(close)
        return window

    def wait(self, window, timeout=60):
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job, "calculation still running")

    def test_saved_project_round_trip_in_both_languages(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.window import export_graph, safe_csv
        for language in ("en", "it"):
            set_language(language)
            window = self.window()
            window.open_path(DATA / "demo.alab")
            self.app.processEvents()
            run = window.project.runs[0]
            self.assertEqual((run.method, run.options), (METHOD, RECIPE))
            window.open_sheet(("result", 0))
            self.wait(window)
            rows, summary = _estimates(window.project.runs[0].result)
            self.assertEqual(rows[("Control $", "A")][0], "Fixed")
            self.assertEqual(summary["DF residual"], 6)

            # Cancel before confirming: nothing changes and nothing is recalculated.
            def cancel(dialog):
                dialog.controls["Parameters"][1].set_scope(0, "Shared")
                return AnalysisDialog.DialogCode.Rejected
            with patch.object(AnalysisDialog, "exec", cancel):
                window.change_parameters()
            self.assertIsNone(window.job)
            self.assertEqual(window.project.runs[0].options, RECIPE)

            # Confirm without changes: the canonical recipe is identical.
            def accept(dialog):
                dialog.accept()
                return dialog.result and AnalysisDialog.DialogCode.Accepted
            with patch.object(AnalysisDialog, "exec", accept):
                window.change_parameters()
            self.wait(window)
            self.assertEqual(window.project.runs[0].options, RECIPE)

            # Edit one cell and exclude another: the linked fit is recalculated.
            window.open_sheet(("data", "Synthetic data"))
            self.app.processEvents()
            self.assertTrue(window.edit_cell("Synthetic data", 7, 1, "10,75"))
            self.wait(window)
            rows, summary = _estimates(window.project.runs[0].result)
            self.assertGreater(summary["Residual SS"], .5)
            window._apply_edit("Synthetic data",
                               lambda: window.project.toggle_exclusion("Synthetic data", [(7, 1)]))
            self.wait(window)
            rows, summary = _estimates(window.project.runs[0].result)
            self.assertEqual(summary["DF residual"], 5)

            # Save, reopen and export a table and the graph.
            saved = self.folder / f"global-{language}.alab"
            window.project.save(saved)
            window.open_path(saved)
            self.app.processEvents()
            self.assertEqual(window.project.runs[0].options, RECIPE)
            window.open_sheet(("result", 0))
            self.wait(window)
            result = window.project.runs[0].result
            safe_csv(self.folder / "parameters.csv", result.tables["Parameters"], index=False)
            self.assertIn("Control $", (self.folder / "parameters.csv").read_text(encoding="utf-8"))
            export_graph(result.figure, self.folder / "fit.svg")
            self.assertTrue((self.folder / "fit.svg").read_text(encoding="utf-8").lstrip().startswith("<?xml"))


if __name__ == "__main__":
    unittest.main()
