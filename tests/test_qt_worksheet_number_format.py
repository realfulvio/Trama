"""Change → Number format… in the Qt window: data sheets, two result tabs of one fit, copy, undo, save."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.grid_data import clipboard_decimal_mark
from analisi.i18n import active_language, set_language

FIXTURE = pd.DataFrame({
    "Categoria": ["Controllo", "Prima", "Seconda", "Terza", "Quarta"],
    "Dose": [0.000125, 1.23456789012345, 12345.6789, 0.5, float("nan")],
    "Risposta": [2.125, -0.0004, -0.0, 1.2345e-14, 950.0],
    "Repliche": [4, 4, 12, 9999, 0],
})


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def choose(spec=None, *, reset=False, seen=None):
    """A stand-in for the dialog's exec: record what it shows, then confirm ``spec`` (or Reset)."""
    def exec_(dialog):
        if seen is not None:
            seen.append((dialog.target, dialog.shown.text(), dialog.reset.isEnabled()))
        if reset:
            dialog.restore()
        else:
            dialog.set_mode(spec["mode"])
            if "digits" in spec:
                dialog.digits.setValue(spec["digits"])
            dialog.confirm()
        return dialog.DialogCode.Accepted
    return exec_


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtNumberFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1024, 768)
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

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def select(self, view, top, left, bottom, right, current=None):
        model = view.model()
        view.setCurrentIndex(model.index(*(current or (top, left))))
        view.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def format(self, spec=None, **kwargs):
        from trama_qt.worksheet_number_format import NumberFormatDialog
        with patch.object(NumberFormatDialog, "exec", choose(spec, **kwargs)):
            self.window.change_number_format()
        self.app.processEvents()

    def column(self, model, column, role=Qt.ItemDataRole.DisplayRole):
        return [model.data(model.index(row, column), role) for row in range(5)]

    def test_data_sheet_shows_the_format_keeps_numbers_and_undoes_in_place(self):
        window = self.window
        title, = window.project.add_tables({"celle": FIXTURE.copy()})
        window.show_sheet("data", title)
        window.project.set_table_background(title, (1, 1, 1, 1), "#ffd966")
        sheet, model = window.sheet, window.sheet.model()
        model.refresh_backgrounds()
        self.select(sheet, 0, 0, 4, 2, current=(1, 1))
        seen = []
        self.format({"mode": "fixed", "digits": 3}, seen=seen)
        target, shown, reset = seen[0]
        self.assertEqual(target.changing_text(), "Columns that change: Dose, Risposta")
        self.assertIn("Categoria", target.unchanged_text())
        self.assertEqual((target.value, target.sample, reset), (1.23456789012345, False, False))
        self.assertEqual(shown, "1.23456789")
        data = window.project.tables[title]
        self.assertEqual(data.number_formats, {"Dose": {"mode": "fixed", "digits": 3},
                                               "Risposta": {"mode": "fixed", "digits": 3}})
        self.assertEqual(self.column(model, 1), ["0.000", "1.235", "12345.679", "0.500", ""])
        self.assertEqual(self.column(model, 2), ["2.125", "0.000", "0.000", "0.000", "950.000"])
        self.assertEqual(self.column(model, 3), ["4", "4", "12", "9999", "0"])
        self.assertEqual(model.data(model.index(1, 1), Qt.ItemDataRole.EditRole), "1.23456789012345")
        self.assertEqual(model.data(model.index(1, 1), Qt.ItemDataRole.BackgroundRole).color().name(), "#ffd966")
        self.assertEqual(data.raw.iat[1, 1], 1.23456789012345)
        self.assertTrue(window.project.dirty)

        set_language("it")
        model.refresh_formats()
        self.assertEqual(self.column(model, 1)[:2], ["0,000", "1,235"])
        set_language("en")
        model.refresh_formats()

        self.select(sheet, 1, 1, 1, 1)
        sheet.copy()
        self.assertEqual(QGuiApplication.clipboard().text().strip(), "1" + clipboard_decimal_mark() + "23456789012345")

        for mode, digits, expected in (("significant", 2, "1.2"), ("scientific", 1, "1.2e+00")):
            self.format({"mode": mode, "digits": digits})
            self.assertEqual(model.data(model.index(1, 1)), expected)
        self.format({"mode": "automatic"})
        self.assertEqual(model.data(model.index(1, 1)), "1.23456789")
        self.assertNotIn("Dose", data.number_formats)

        self.select(sheet, 0, 2, 4, 2, current=(3, 2))
        seen = []
        self.format(reset=True, seen=seen)
        self.assertTrue(seen[0][2], "Reset is offered when a format exists")
        self.assertEqual(data.number_formats, {})
        window.undo()
        self.app.processEvents()
        self.assertIs(window.sheet, sheet, "undo of a format keeps the sheet, its selection and scroll")
        self.assertEqual(sheet.currentIndex().row(), 3)
        self.assertEqual(model.data(model.index(0, 2)), "2.125")
        self.assertEqual(data.number_formats["Risposta"], {"mode": "fixed", "digits": 3})
        window.undo(redo=True)
        self.app.processEvents()
        self.assertEqual(data.number_formats, {})
        self.assertEqual(model.data(model.index(1, 2)), "-0.0004")

    def test_text_only_selection_and_calculated_columns(self):
        window = self.window
        title, = window.project.add_tables({"celle": FIXTURE.copy()})
        window.project.tables[title].set_formula("Doppia", "=2*Risposta")
        window.show_sheet("data", title)
        sheet = window.sheet
        self.select(sheet, 0, 0, 4, 0)
        self.format({"mode": "fixed", "digits": 1})
        self.assertEqual(len(self.errors), 1)
        self.assertIn("numeric", self.errors[0])
        self.select(sheet, 0, 4, 4, 4)
        self.format({"mode": "fixed", "digits": 1})
        self.assertEqual(sheet.model().data(sheet.model().index(0, 4)), "4.2")  # 4.25: half to even.
        self.assertEqual(window.project.tables[title].number_formats, {"Doppia": {"mode": "fixed", "digits": 1}})

    def test_two_result_tabs_of_one_fit_keep_their_own_formats(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        window = self.window
        frame = pd.DataFrame({"Dose": [0.5, 1, 2, 4, 8, 16, 32, 64],
                              "Response": [2.1, 3.9, 6.2, 8.1, 9.8, 12.3, 13.1, 13.5]})
        title, = window.project.add_tables({"Fit": frame})
        window.show_sheet("data", title)
        dialog = AnalysisDialog(window, frame, current=("Deming regression", {}))
        values = dialog.options()
        dialog.deleteLater()
        window.calculate_candidate(window.project.candidate(title, "Deming regression", values), frame, None)
        self.wait()
        window.open_sheet(("result", 0))
        self.app.processEvents()
        self.assertEqual(window.selected[0], "result")
        tabs = window.result_tabs
        names = [tabs.tabText(index) for index in range(tabs.count())]
        data_tab, pairs_tab = names.index("Data"), names.index("Pairs")

        tabs.setCurrentIndex(data_tab)
        view = tabs.currentWidget()
        self.select(view, 0, 1, 7, 1)
        self.format({"mode": "fixed", "digits": 1})
        tabs.setCurrentIndex(pairs_tab)
        pairs = tabs.currentWidget()
        self.select(pairs, 0, 2, 7, 2)
        self.format({"mode": "scientific", "digits": 2})

        run = window.project.runs[0]
        formats = window.project.tables[title].result_number_formats[run.slot]
        self.assertEqual(formats, {"Data": {1: {"mode": "fixed", "digits": 1}},
                                   "Pairs": {2: {"mode": "scientific", "digits": 2}}})
        view = tabs.widget(data_tab)
        self.assertEqual(view.model().data(view.model().index(0, 1)), "0.5")
        self.assertNotEqual(view.model().data(view.model().index(0, 2)), "2.1e+00")
        value = run.result.tables["Pairs"].iat[0, 1]
        self.assertEqual(pairs.model().data(pairs.model().index(0, 2)), f"{value:.2e}")
        self.select(pairs, 0, 2, 0, 2)
        pairs.copy()
        self.assertEqual(QGuiApplication.clipboard().text().strip(), pairs.model().plain_text(0, 2))
        self.assertNotEqual(pairs.model().plain_text(0, 2), f"{value:.2e}")

        window.undo()
        self.app.processEvents()
        self.assertEqual(window.project.tables[title].result_number_formats[run.slot],
                         {"Data": {1: {"mode": "fixed", "digits": 1}}})
        window.undo(redo=True)
        self.app.processEvents()

        # Editing the source recalculates the fit; the formats stay on their tabs.
        window.show_sheet("data", title)
        model = window.sheet.model()
        model.setData(model.index(0, 1), "2.4")
        self.app.processEvents()
        self.wait()
        window.open_sheet(("result", 0))
        self.wait()
        tabs = window.result_tabs
        view = tabs.widget(data_tab)
        self.assertEqual(view.model().data(view.model().index(0, 2)), "2.4")
        self.assertEqual(view.model().data(view.model().index(0, 1)), "0.5")

        saved = self.folder / "formats.alab"
        window.project.save(saved)
        self.assertTrue(window.close_project())
        window.open_path(saved)
        self.app.processEvents()
        window.open_sheet(("result", 0))
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(window.project.tables[title].result_number_formats[run.slot],
                         {"Data": {1: {"mode": "fixed", "digits": 1}},
                          "Pairs": {2: {"mode": "scientific", "digits": 2}}})
        tabs = window.result_tabs
        pairs = tabs.widget(pairs_tab)
        value = run.result.tables["Pairs"].iat[0, 1]
        self.assertEqual(pairs.model().data(pairs.model().index(0, 2)), f"{value:.2e}")

    def test_real_dialog_limits_digits_and_cancel_leaves_the_sheet(self):
        from analisi.worksheet_number_format import format_target, worksheet_columns
        from trama_qt.worksheet_number_format import NumberFormatDialog
        title, = self.window.project.add_tables({"celle": FIXTURE.copy()})
        data = self.window.project.tables[title]
        frame = data.frame()
        target = format_target(worksheet_columns(data, frame), (0, 1, 4, 1), {}, active=(0, 1),
                               value_at=lambda row, column: frame.iat[row, column], rows=len(frame))
        set_language("it")
        dialog = NumberFormatDialog(self.window, target)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.windowTitle(), "Formato numerico")
        self.assertFalse(dialog.reset.isEnabled())
        self.assertFalse(dialog.digits.isEnabled())
        dialog.mode_buttons["significant"].click()
        self.assertEqual((dialog.digits.minimum(), dialog.digits.maximum()), (1, 15))
        dialog.digits.setValue(2)
        self.assertEqual(dialog.shown.text(), "0,00013")
        dialog.mode_buttons["fixed"].click()
        self.assertEqual((dialog.digits.minimum(), dialog.digits.maximum()), (0, 12))
        dialog.show()
        self.app.processEvents()
        self.assertLessEqual(dialog.sizeHint().height(), 768)
        dialog.reject()
        self.assertIsNone(dialog.choice)
        self.assertEqual(data.number_formats, {})


if __name__ == "__main__":
    unittest.main()
