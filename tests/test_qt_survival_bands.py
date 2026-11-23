"""Kaplan–Meier simultaneous bands in the Qt window, offscreen: the dialog choice in English and Italian, a run
with one and with two responses, recalculation after an edit or an exclusion, exports and a project round trip.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import set_language
from tests.test_survival_bands import CHOICE, COLUMNS, SHEET, oracle

KM = "Kaplan–Meier survival"
DATA = Path(__file__).resolve().parent / "data" / "survival_bands"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def worksheet():
    frame = pd.read_csv(DATA / "fixture.csv")
    frame["Relapse"] = 1 - frame["Event"]
    return frame


def tick(control, names):
    for row in range(control.count()):
        item = control.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(value, list):
            tick(control, value)
        elif hasattr(control, "findData"):
            position = control.findData(value)
            assert position >= 0, (name, value)
            control.setCurrentIndex(position)
        else:
            control.setText(str(value))


def rows(frame=None):
    frame = worksheet() if frame is None else frame
    return [{key: str(value) for key, value in row.items()} for row in frame.to_dict("records")]


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, worksheet(), current=(KM, {}))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_the_choice_is_last_and_the_default_stays_none(self):
        dialog = self.dialog()
        _kind, combo = dialog.controls["Uncertainty"]
        self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                         ["None", "Standard error bars", "Pointwise confidence band", "Pointwise confidence bars",
                          CHOICE])
        self.assertEqual(combo.currentData(), "None")
        self.assertEqual(combo.itemText(4), "Hall–Wellner simultaneous band")
        fill(dialog, **{"Event columns": ["Event"]})
        self.assertEqual(dialog.options()["Uncertainty"], "None")

    def test_the_italian_caption_is_the_conservative_band_and_the_recipe_stays_canonical(self):
        set_language("it")
        dialog = self.dialog()
        _kind, combo = dialog.controls["Uncertainty"]
        self.assertEqual(combo.itemText(4), "Banda simultanea Hall–Wellner (conservativa)")
        fill(dialog, Uncertainty=CHOICE, **{"Event columns": ["Event"], "Grouping variables": ["Group"]})
        options = dialog.options()
        self.assertEqual(options["Uncertainty"], CHOICE)
        self.assertEqual(options["Confidence level (%)"], 95.0)

    def test_dialog_fits_1024_by_768_with_the_choice_selected(self):
        from trama_qt import theme
        try:
            for dark in (False, True):
                theme.apply(self.app, dark=dark)
                for language in ("en", "it"):
                    set_language(language)
                    dialog = self.dialog()
                    fill(dialog, Uncertainty=CHOICE)
                    hint = dialog.minimumSizeHint()
                    self.assertLessEqual(hint.width(), 1024, (dark, language))
                    self.assertLessEqual(hint.height(), 768, (dark, language))
                    _kind, combo = dialog.controls["Uncertainty"]
                    self.assertGreaterEqual(combo.width(), combo.minimumSizeHint().width())
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.csv = self.folder / "sopravvivenza.csv"
        worksheet().to_csv(self.csv, index=False)
        self.window = self.make_window(MainWindow)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))

    def tearDown(self):
        set_language("en")

    def make_window(self, factory):
        window = factory()
        window.project.dirty = False
        window.show()
        self.app.processEvents()

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(close)
        return window

    def wait(self, window=None, timeout=120):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job, "calculation still running")

    def through_dialog(self, command, values):
        from trama_qt.analysis_dialog import AnalysisDialog

        def exec_(dialog):
            if dialog.method != KM:
                dialog.method = KM
                dialog.configure_fields()
            fill(dialog, **values)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()

    def first_run(self, **values):
        self.window.open_path(self.csv)
        self.wait()
        self.title = self.window.selected[1]
        base = {"Time": "Time", "Event columns": ["Event"], "Grouping variables": ["Group"], "Uncertainty": CHOICE}
        self.through_dialog(lambda: self.window.analyze(KM), {**base, **values})
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return run

    def test_run_edit_exclude_and_undo_recalculate_the_sheet(self):
        window = self.window
        run = self.first_run()
        self.assertEqual(window.selected, ("graph", 0))
        self.assertEqual(run.options["Uncertainty"], CHOICE)
        sheet = run.result.tables[SHEET]
        self.assertEqual(list(sheet.columns), COLUMNS)
        oracle.compare(sheet, oracle.oracle(rows(), 95))
        # Turning the terminal censored subject of "Censored" (row 17) into an event changes its band.
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 16, 1, "1")
        self.wait()
        edited = worksheet()
        edited.loc[16, "Event"] = 1
        sheet = window.project.runs[0].result.tables[SHEET]
        oracle.compare(sheet, oracle.oracle(rows(edited), 95))
        self.assertTrue((sheet[sheet["Group"] == "Censored"]["Status"] == "Available").any())
        # Excluding a cell of the Control group leaves the whole row out of the curves and the sheet.
        window.show_sheet("data", self.title)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.toggle_exclusion()
        self.wait()
        left_out = edited.drop(index=0)
        oracle.compare(window.project.runs[0].result.tables[SHEET], oracle.oracle(rows(left_out), 95))
        window.undo()
        self.wait()
        oracle.compare(window.project.runs[0].result.tables[SHEET], oracle.oracle(rows(edited), 95))
        self.assertEqual(self.errors, [])

    def test_cumulative_percent_and_levels_through_the_dialog(self):
        window = self.window
        self.first_run(**{"Confidence level (%)": "90"})
        oracle.compare(window.project.runs[0].result.tables[SHEET], oracle.oracle(rows(), 90))
        window.show_sheet("graph", 0)

        def change(**values):
            def exec_(dialog):
                fill(dialog, **values)
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected
            from trama_qt.analysis_dialog import AnalysisDialog
            with mock.patch.object(AnalysisDialog, "exec", exec_):
                window.change_parameters()
            self.wait()

        change(**{"Confidence level (%)": "99", "Curve": "Cumulative events", "Display units": "Percent"})
        run = window.project.runs[0]
        self.assertIsNone(run.calculation_error)
        oracle.compare(run.result.tables[SHEET], oracle.oracle(rows(), 99))
        axes = run.result.figure.axes[0]
        self.assertEqual(axes.get_ylabel(), "Cumulative event probability (%)")
        self.assertTrue(axes.get_legend_handles_labels()[1][-1].startswith("99% simultaneous band"))
        change(Uncertainty="None")
        self.assertNotIn(SHEET, window.project.runs[0].result.tables)
        self.assertEqual(self.errors, [])

    def test_two_responses_exports_and_round_trip_in_italian(self):
        from trama_qt.window import MainWindow
        window = self.window
        run = self.first_run(**{"Event columns": ["Event", "Relapse"]})
        tables = {name: frame.copy() for name, frame in run.result.tables.items()}
        sheet = tables[SHEET]
        self.assertEqual(list(sheet.columns), ["Response variable", *COLUMNS])
        self.assertEqual(set(sheet["Response variable"]), {"Event", "Relapse"})
        window.show_sheet("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"curva.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        svg = (self.folder / "curva.svg").read_text(encoding="utf-8")
        self.assertIn("<path", svg)
        self.assertNotIn("<image", svg)
        self.assertIn("simultaneous band", svg)
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index(SHEET))
        target = self.folder / "bande.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            window.export()
        # The window writes the row index of every result table: the first column has no name.
        exported = pd.read_csv(target, keep_default_na=False, index_col=0)
        self.assertEqual(list(exported.columns), list(sheet.columns))
        self.assertEqual(len(exported), len(sheet))

        project = self.folder / "bande simultanee.alab"
        window.project.save(project)
        raw = zipfile.ZipFile(project).read("project.json") if zipfile.is_zipfile(project) else project.read_bytes()
        method, options = json.loads(raw)["tables"][0]["analyses"][0]
        self.assertEqual(method, KM)
        self.assertEqual(options["Uncertainty"], CHOICE)
        self.assertEqual(options["Event columns"], ["Event", "Relapse"])

        set_language("it")
        other = self.make_window(MainWindow)
        other.error = lambda error: self.errors.append(str(error))
        other.open_path(project)
        self.wait(other)
        other.open_sheet(("graph", 0))
        self.wait(other)
        reopened = other.project.runs[0]
        self.assertIsNotNone(reopened.result)
        self.assertEqual(reopened.options, run.options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened.result.tables[name], frame, obj=name)
        self.assertEqual(self.errors, [])

    def test_a_recipe_saved_before_the_choice_keeps_its_default_and_outputs(self):
        window = self.window
        window.open_path(self.csv)
        self.wait()
        values = {"Time": "Time", "Event columns": ["Event"], "Grouping variables": ["Group"]}
        self.through_dialog(lambda: window.analyze(KM), values)
        self.wait()
        run = window.project.runs[-1]
        self.assertEqual(run.options["Uncertainty"], "None")
        self.assertNotIn(SHEET, run.result.tables)
        from analisi.workbench import analyse
        legacy = {key: value for key, value in run.options.items() if key != "Uncertainty"}
        for name, table in analyse(KM, worksheet(), legacy).tables.items():
            pd.testing.assert_frame_equal(table, run.result.tables[name], obj=name)


if __name__ == "__main__":
    unittest.main()
