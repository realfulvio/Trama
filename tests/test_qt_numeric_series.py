"""Qt UI tests for Create numeric series dialog, menus, virtual headers, cancellation, undo/redo and XY recalc."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from analisi.i18n import set_language
from analisi.numeric_series import GEOMETRIC
from trama_qt.numeric_series_dialog import NumericSeriesDialog
from trama_qt.window import MainWindow


def _write_fixture(path):
    doc = {
        "version": 2,
        "tables": [{
            "title": "Serie XY",
            "columns": ["Row title", "X", "Segnale", "Controllo"],
            "kinds": ["text", "numeric", "numeric", "numeric"],
            "rows": [
                ["Campione A", 1, 3, 2],
                ["Campione B", 2, 6, 4],
                ["Campione B", 2, 6, 4],
                ["Campione C", 4, 12, 8],
                ["Campione D", 8, 24, 16],
            ],
            "formulas": [],
            "analyses": [["XY series", {"X": "X", "Y columns": ["Segnale", "Controllo"]}]],
            "excluded": [[2, 3]],
            "table_format": "xy",
            "graph_styles": {},
            "cell_backgrounds": [[2, "Segnale", "#bee3da"]],
        }],
        "layouts": [],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


class QtNumericSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-series"])

    def setUp(self):
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "esempio.alab"
        _write_fixture(self.path)
        self.window = MainWindow()
        self.addCleanup(self._cleanup)
        self.errors = []
        self.window.error = lambda err: self.errors.append(str(err))
        self.window.resize(1024, 768)
        self.window.show()
        self.window.open_path(self.path)
        self._wait()
        self.window.open_sheet(("data", "Serie XY"))
        self.app.processEvents()

    def _wait(self):
        for _ in range(200):
            self.app.processEvents()
            if self.window.job is None:
                return
            QTest.qWait(20)

    def _cleanup(self):
        set_language("en")
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_insert_menu_and_context_menu_and_cancel_leaves_data_intact(self):
        w = self.window
        self.assertIn(w.actions["create_numeric_series"], w.command_menus["Insert"].actions())

        # Single-cell B2 (row 1, col 1) -> proposes 10; set 5, first=1, step=-0.25 -> 4/5 occupied
        w.sheet.select_block(1, 1, 1, 1)
        self.app.processEvents()
        dataset = w.project.tables["Serie XY"]
        target = w.sheet.model().dataset
        from analisi.numeric_series import validate_series_target
        t_info = validate_series_target(target, (1, 1, 1, 1))
        dialog = NumericSeriesDialog(w, dataset, t_info)
        try:
            self.assertEqual(dialog.count.value(), 10)
            dialog.first.setText("1")
            dialog.count.setValue(5)
            dialog.step.setText("-0.25")
            self.assertEqual(dialog.range_label.text(), "B2:B6")
            self.assertFalse(dialog.ok_button.isEnabled())  # requires explicit confirmation
            self.assertIn("4 of 5", dialog.replace_warning.text())
            dialog.reject()
        finally:
            dialog.deleteLater()

        # Nothing changed after cancel
        self.assertEqual(dataset.raw["X"].tolist(), [1, 2, 2, 4, 8])
        self.assertEqual(len(w.project.history.changes), 0)

        # Context menu on numeric cell B2 exposes Create numeric series, on text cell A2 does not
        pos_b2 = w.sheet.visualRect(w.sheet.model().index(1, 1)).center()
        seen_num = []
        QTimer.singleShot(0, lambda: self._inspect_and_close(seen_num))
        w.sheet._context_menu(pos_b2)
        self.assertIn(w.actions["create_numeric_series"].text(), seen_num)

        pos_a2 = w.sheet.visualRect(w.sheet.model().index(1, 0)).center()
        seen_text = []
        QTimer.singleShot(0, lambda: self._inspect_and_close(seen_text))
        w.sheet._context_menu(pos_a2)
        self.assertNotIn(w.actions["create_numeric_series"].text(), seen_text)

    def _inspect_and_close(self, out_list):
        menu = self.app.activePopupWidget()
        if isinstance(menu, QMenu):
            out_list.extend(a.text() for a in menu.actions() if not a.isSeparator())
            menu.close()

    def test_italian_dialog_apply_undo_redo_and_recalculates_xy(self):
        set_language("it")
        w = MainWindow()
        w.error = lambda err: self.fail(str(err))
        w.resize(1024, 768)
        w.show()
        w.open_path(self.path)
        for _ in range(200):
            self.app.processEvents()
            if w.job is None:
                break
            QTest.qWait(20)
        try:
            w.open_sheet(("data", "Serie XY"))
            self.app.processEvents()
            w.sheet.select_block(1, 1, 1, 1)

            errors_drive = []

            def drive():
                dlg = next(widget for widget in w.findChildren(NumericSeriesDialog) if widget.isVisible())
                try:
                    dlg.first.setText("1")
                    dlg.count.setValue(5)
                    dlg.step.setText("-0,25")
                    self.assertIn("4 celle occupate su 5", dlg.replace_warning.text())
                    self.assertIn("0,75", dlg.preview_label.text())
                    self.assertFalse(dlg.ok_button.isEnabled())
                    dlg.confirm_replace.setChecked(True)
                    self.assertTrue(dlg.ok_button.isEnabled())
                    dlg.ok_button.click()
                except BaseException as exc:
                    errors_drive.append(exc)
                    dlg.reject()

            QTimer.singleShot(0, drive)
            w.create_numeric_series()
            if errors_drive:
                raise errors_drive[0]
            for _ in range(200):
                self.app.processEvents()
                if w.job is None:
                    break
                QTest.qWait(20)

            dataset = w.project.tables["Serie XY"]
            self.assertEqual(dataset.raw["X"].tolist(), [1.0, 1.0, 0.75, 0.5, 0.25, 0.0])
            self.assertIsNotNone(w.project.runs[0].result)
            self.assertIsNone(w.project.runs[0].calculation_error)

            # Virtual column heading E (col 4) -> geometric series with 1/2
            def drive_geo():
                dlg = next(widget for widget in w.findChildren(NumericSeriesDialog) if widget.isVisible())
                try:
                    self.assertEqual(dlg.count.value(), 6)  # proposes current table height
                    dlg.mode.setCurrentIndex(dlg.mode.findData(GEOMETRIC))
                    dlg.first.setText("16")
                    dlg.count.setValue(4)
                    dlg.step.setText("1/2")
                    self.assertTrue(dlg.ok_button.isEnabled())  # virtual column -> 0 occupied
                    dlg.ok_button.click()
                except BaseException as exc:
                    errors_drive.append(exc)
                    dlg.reject()

            QTimer.singleShot(0, drive_geo)
            w.create_numeric_series(column=4, start_row=0, full_column=True)
            if errors_drive:
                raise errors_drive[0]
            for _ in range(200):
                self.app.processEvents()
                if w.job is None:
                    break
                QTest.qWait(20)
            self.assertEqual(dataset.raw.iloc[:4, 4].tolist(), [16, 8, 4, 2])
        finally:
            w.project.dirty = False
            w.close()
            self.app.processEvents()

    def test_selection_proposes_length_and_invalid_target_shows_error_cleanly(self):
        w = self.window
        w.sheet.select_block(1, 1, 3, 1)  # 3 rows in X
        from analisi.numeric_series import validate_series_target
        t_info = validate_series_target(w.project.tables["Serie XY"], w.sheet.box())
        self.assertEqual(t_info.proposed_count, 3)

        # Multi-column selection via action shows error and leaves history empty
        w.sheet.select_block(0, 1, 2, 2)
        w.create_numeric_series()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(len(w.project.history.changes), 0)


if __name__ == "__main__":
    unittest.main()
