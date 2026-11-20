"""Leaf ordering of hierarchical clustering in the Qt window, offscreen: dialog, recalculation, cancel, projects.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi import leaf_order
from analisi.hierarchical_style import describe_hierarchical_artists
from analisi.i18n import set_language

METHOD = "Hierarchical clustering"
TITLE = "Profili sintetici"
VARIABLES = ["Cold", "Warm", "Salt", "Oxygen", "Light"]
PROFILES = pd.DataFrame({
    "Label": [f"Sample {i}" for i in range(1, 8)],
    "Cold": [17, 20, -21, 21, -16, 5, -22], "Warm": [28, 1, -22, -30, 20, 27, 26],
    "Salt": [-14, -21, -5, -5, -26, 15, 21], "Oxygen": [-18, 20, 12, 1, -10, 25, -22],
    "Light": [18, 1, -6, 28, 15, 20, 29]})
RECIPE = {"Variables": VARIABLES, "Observation labels": "Label", "Direction": "Rows and columns",
          "Scale columns": "None", "Scale rows": "None", "Linkage": "average", "Distance": "cityblock",
          "Graph output": "Heat map", "Leaf ordering": "Optimal"}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def choose(dialog, name, value):
    control = dialog.controls[name][1]
    control.setCurrentIndex(control.findData(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class LeafOrderDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None, **kwargs):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, PROFILES if frame is None else frame, current=current or (METHOD, {}),
                                **kwargs)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_the_field_defaults_to_default_and_a_recipe_stores_the_choice(self):
        dialog = self.dialog()
        control = dialog.controls["Leaf ordering"][1]
        self.assertEqual([control.itemData(i) for i in range(control.count())], ["Default", "Optimal"])
        self.assertEqual(dialog.options()["Leaf ordering"], "Default")
        choose(dialog, "Leaf ordering", "Optimal")
        dialog.accept()
        self.assertEqual(dialog.result[1]["Leaf ordering"], "Optimal")

    def test_saved_recipes_reopen_and_old_recipes_mean_default(self):
        reopened = self.dialog(current=(METHOD, RECIPE))
        self.assertEqual(reopened.options()["Leaf ordering"], "Optimal")
        legacy = {key: value for key, value in RECIPE.items() if key != "Leaf ordering"}
        self.assertEqual(self.dialog(current=(METHOD, legacy)).options()["Leaf ordering"], "Default")

    def test_italian_captions_and_choices(self):
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.rows["Leaf ordering"][0].text(), "Ordine delle foglie")
        control = dialog.controls["Leaf ordering"][1]
        self.assertEqual([control.itemText(i) for i in range(control.count())], ["Predefinito", "Ottimale"])
        self.assertEqual(dialog.heading.text(), "Raggruppamento gerarchico")

    def test_the_keyboard_reaches_and_changes_the_choice(self):
        dialog = self.dialog()
        control = dialog.controls["Leaf ordering"][1]
        control.setFocus()
        QTest.keyClick(control, Qt.Key.Key_Down)
        self.assertEqual(control.currentData(), "Optimal")
        QTest.keyClick(control, Qt.Key.Key_Up)
        self.assertEqual(control.currentData(), "Default")
        # The control sits in the tab chain right after Distance.
        chain, widget = [], dialog.controls["Distance"][1]
        for _ in range(4):
            widget = widget.nextInFocusChain()
            chain.append(widget)
        self.assertIn(control, chain)

    def test_too_many_leaves_are_refused_on_the_field_before_any_worker(self):
        rows = pd.DataFrame(np.random.default_rng(4).normal(size=(2100, 2)), columns=["A", "B"])
        dialog = self.dialog(rows, current=(METHOD, {"Variables": ["A", "B"], "Direction": "Rows"}))
        choose(dialog, "Leaf ordering", "Optimal")
        with mock.patch.object(leaf_order, "optimal_order", side_effect=AssertionError("ordering in the dialog")):
            dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("limited to 2000 leaves", dialog.banner.text())
        self.assertIs(self.app.focusWidget(), dialog.controls["Leaf ordering"][1])
        choose(dialog, "Leaf ordering", "Default")
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        set_language("it")
        italian = self.dialog(rows, current=(METHOD, {"Variables": ["A", "B"], "Direction": "Rows"}))
        choose(italian, "Leaf ordering", "Optimal")
        italian.accept()
        self.assertTrue(italian.banner.text().startswith("L’ordine ottimale delle foglie è limitato a 2000"),
                        italian.banner.text())

    def test_columns_below_the_limit_are_accepted(self):
        rows = pd.DataFrame(np.random.default_rng(4).normal(size=(2100, 3)), columns=["A", "B", "C"])
        dialog = self.dialog(rows, current=(METHOD, {"Variables": ["A", "B", "C"], "Direction": "Columns"}))
        choose(dialog, "Leaf ordering", "Optimal")
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_an_engine_error_reopens_on_the_field_in_the_active_language(self):
        message = ("Optimal leaf ordering is limited to 2000 leaves per axis. "
                   "Use fewer observations or variables, or choose Default.")
        dialog = self.dialog(error=message, error_field="Leaf ordering")
        self.assertEqual(dialog.banner.text(), message)
        self.assertIs(self.app.focusWidget(), dialog.controls["Leaf ordering"][1])
        set_language("it")
        shown = self.dialog(error=message, error_field="Leaf ordering")
        self.assertTrue(shown.banner.text().startswith("L’ordine ottimale delle foglie è limitato a 2000"))

    def test_dialog_fits_1024_by_768_in_light_and_dark(self):
        from trama_qt import theme
        try:
            for dark in (False, True):
                theme.apply(self.app, dark=dark)
                for language in ("en", "it"):
                    set_language(language)
                    dialog = self.dialog()
                    hint = dialog.minimumSizeHint()
                    self.assertLessEqual(hint.width(), 1024, (dark, language))
                    self.assertLessEqual(hint.height(), 768, (dark, language))
                    dialog.resize(1024, 700)
                    self.app.processEvents()
                    self.assertTrue(dialog.run_button.isVisible())
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class LeafOrderWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        set_language("en")

    def wait(self, timeout=120):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def open_table(self, frame=PROFILES):
        path = self.folder / f"{TITLE}.csv"
        frame.to_csv(path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        return TITLE

    def calculate(self, options, title=TITLE):
        project = self.window.project
        frame = project.tables[title].frame(mask_excluded=True)
        candidate = project.candidate(title, METHOD, options)
        from trama_qt.analysis_dialog import AnalysisDialog
        reopened = []  # a failed calculation reopens the dialog: never let a test wait on it
        refuse = lambda dialog: reopened.append(True) or QDialog.DialogCode.Rejected  # noqa: E731
        with mock.patch.object(AnalysisDialog, "exec", refuse):
            self.window.calculate_candidate(candidate, frame, None)
            self.wait()
        self.assertEqual(reopened, [], "the calculation failed and reopened the dialog")
        return len(project.runs) - 1

    def through_dialog(self, command, values):
        from trama_qt.analysis_dialog import AnalysisDialog

        def exec_(dialog):
            for name, value in values.items():
                choose(dialog, name, value)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()

    def order_of(self, run, key):
        meta = describe_hierarchical_artists(run.result.figure)
        return [index + 1 for index in meta[key]["leaf_order"]]

    def test_run_edit_recalculate_export_save_and_reopen(self):
        window = self.window
        title = self.open_table()
        index = self.calculate(RECIPE)
        run = window.project.runs[index]
        self.assertIsNone(run.calculation_error)
        self.assertEqual(self.order_of(run, "row"), run.result.tables["Row leaf order"]["Input index"].tolist())
        self.assertEqual(self.order_of(run, "column"), run.result.tables["Column leaf order"]["Input index"].tolist())
        costs = run.result.tables["Leaf order costs"].set_index("Axis")
        self.assertEqual(costs.loc["Row", "Final cost"], 520.0)
        self.assertEqual(costs.loc["Column", "Final cost"], 492.0)
        self.assertEqual(window.project.tables[title].analyses[-1], (METHOD, RECIPE))

        # An edited cell recalculates every sheet, the figure and the order.
        window.open_sheet(("data", title))
        column = list(window.project.tables[title].raw.columns).index("Cold")
        window.edit_cell(title, 0, column, "-40")
        self.wait()
        run = window.project.runs[index]
        edited = PROFILES.copy()
        edited.loc[0, "Cold"] = -40
        fresh = leaf_order_tables(edited)
        for name in ("Row leaf order", "Column leaf order", "Leaf order costs"):
            pd.testing.assert_frame_equal(run.result.tables[name], fresh[name], obj=name)
        self.assertEqual(self.order_of(run, "row"), fresh["Row leaf order"]["Input index"].tolist())

        # Exports keep the order and stay vector.
        window.open_sheet(("graph", index))
        self.wait()
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"leaf.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        svg = (self.folder / "leaf.svg").read_text(encoding="utf-8")
        self.assertGreater(svg.count("<path"), 10)
        self.assertEqual(svg.count("<image"), 2)  # the heat map cells and the colour bar; the dendrograms are paths

        # Save, reopen in another language: the recipe and the tables come back, the order is recomputed.
        before = {name: frame.copy() for name, frame in run.result.tables.items()}
        saved = self.folder / "foglie.alab"
        window.project.save(saved)
        set_language("it")
        self.assertTrue(window.close_project())
        window.open_path(saved)
        self.app.processEvents()
        window.open_sheet(("graph", 0))
        self.wait()
        reopened = window.project.runs[0]
        self.assertEqual(reopened.options, RECIPE)
        for name in ("Row leaf order", "Column leaf order", "Leaf order costs"):
            pd.testing.assert_frame_equal(reopened.result.tables[name], before[name], obj=name)
        self.assertEqual(self.errors, [])

    def test_the_dialog_switches_a_calculated_analysis_between_default_and_optimal(self):
        window = self.window
        self.open_table()
        index = self.calculate({**RECIPE, "Leaf ordering": "Default"})
        run = window.project.runs[index]
        self.assertNotIn("Row leaf order", run.result.tables)
        window.open_sheet(("graph", index))
        self.through_dialog(window.change_parameters, {"Leaf ordering": "Optimal"})
        self.wait()
        run = window.project.runs[index]
        self.assertEqual(run.options["Leaf ordering"], "Optimal")
        self.assertIn("Row leaf order", run.result.tables)
        self.through_dialog(window.change_parameters, {"Leaf ordering": "Default"})
        self.wait()
        self.assertNotIn("Row leaf order", window.project.runs[index].result.tables)

    def test_cancel_keeps_the_recipe_and_the_previous_result(self):
        window = self.window
        rows = pd.DataFrame(np.random.default_rng(8).normal(size=(500, 6)), columns=list("ABCDEF"))
        rows.insert(0, "Label", [f"Row {i}" for i in range(500)])
        self.open_table(rows)
        recipe = {"Variables": list("ABCDEF"), "Observation labels": "Label", "Direction": "Rows",
                  "Scale columns": "Standardize", "Leaf ordering": "Default", "Graph output": "Dendrogram"}
        index = self.calculate(recipe)
        run = window.project.runs[index]
        options, result = dict(run.options), run.result
        real = leaf_order._minplus

        def slow(left, right, cancel):
            time.sleep(0.01)
            return real(left, right, cancel)

        window.open_sheet(("graph", index))
        with mock.patch.object(leaf_order, "_minplus", slow):
            self.through_dialog(window.change_parameters, {"Leaf ordering": "Optimal"})
            self.assertIsNotNone(window.job)
            end = time.monotonic() + .3
            while time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIsNotNone(window.job, "the ordering ended before it could be cancelled")
            started = time.monotonic()
            window.cancel_calculation()
            self.wait()
            latency = time.monotonic() - started
        self.assertLess(latency, 2)
        run = window.project.runs[index]
        self.assertEqual(run.options, options)
        self.assertIs(run.result, result)
        self.assertEqual(self.errors, [])


def leaf_order_tables(frame):
    from analisi.workbench import analyse
    return analyse(METHOD, frame, RECIPE).tables


if __name__ == "__main__":
    unittest.main()
