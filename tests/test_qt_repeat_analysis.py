"""Analysis → Repeat analysis on other sheets… in the Qt window.

Offscreen like ``test_qt_templates``. The assistant is driven through ``RepeatDialog.exec`` with its real widgets:
the recipe, the sheets (refusals, choices by hand, a duplicate), the preview, the worker, Cancel, a failed copy
that reopens the same assistant, and the copies added with their links.
"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from analisi.i18n import active_language, set_language

MAPPINGS = {"Lot B": {"X": "Tempo", "Y": "Segnale"}, "Lot C": {"X": "Concentrazione", "Y": "Risposta"},
            "Short": {"X": "A", "Y": "B"}}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RepeatWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-repeat", "-platform", "offscreen"])
        from trama_qt import theme
        theme.load_fonts()
        theme.apply(cls.app)

    def setUp(self):
        from trama_qt.repeat_smoke import fixture
        from trama_qt.window import MainWindow
        self.language = active_language()
        set_language("en")
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.window = MainWindow()
        self.window.resize(1024, 700)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.window.open_path(fixture(Path(self.tmp.name)))
        self.settle()
        self.project = self.window.project
        self.source = next(index for index, run in enumerate(self.project.runs) if run.reference == ("Original", 0))

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        if self.window.job is not None:
            self.window.job.control.cancel.set()
            self.settle(timeout=10)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def settle(self, timeout=60):
        end, quiet = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            self.app.processEvents()
            quiet = quiet + 1 if self.window.job is None else 0
            if quiet >= 4:
                break
            time.sleep(0.02)
        self.assertIsNone(self.window.job, "calculation still running")

    def run_assistant(self, *handlers, during=None):
        """Open the command on the source; each handler drives one opening of the assistant."""
        from trama_qt import repeat_analysis
        queue, seen, failures = list(handlers), [], []

        def exec_(dialog):
            try:
                self.assertTrue(queue, "unexpected assistant")
                dialog.show()
                self.app.processEvents()
                seen.append(dialog)
                if queue.pop(0)(dialog):
                    return QDialog.DialogCode.Accepted
            except BaseException as error:  # noqa: BLE001 - re-raised in the test.
                failures.append(error)
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with mock.patch.object(repeat_analysis.RepeatDialog, "exec", exec_):
            self.window.open_sheet(("result", self.source))
            self.settle()
            self.window.actions["repeat_analysis"].trigger()
            if during is not None and self.window.job is not None:
                during()
            self.settle()
        if failures:
            raise failures[0]
        self.assertEqual(queue, [], "an assistant did not open")
        return seen

    def choose(self, dialog, targets):
        dialog.next.click()
        items = {dialog.sheet_list.item(row).data(Qt.ItemDataRole.UserRole): dialog.sheet_list.item(row)
                 for row in range(dialog.sheet_list.count())}
        for title in targets:
            items[title].setCheckState(Qt.CheckState.Checked)
            for row in range(dialog.table.rowCount()):
                box = dialog.table.cellWidget(row, 1)
                box.setCurrentIndex(box.findData(MAPPINGS[title][dialog.table.item(row, 0).text()]))
        dialog.next.click()
        self.assertEqual(dialog.pages.currentIndex(), 2)
        return True

    def test_menu_and_action_state(self):
        from trama_qt.classic_bar import MENUS
        analyze = next(entries for title, entries in MENUS if "change_input" in entries)
        self.assertEqual(analyze[analyze.index("change_input") + 1], "repeat_analysis")
        self.window.show_sheet("data", "Lot B")
        self.window.update_actions()
        self.assertFalse(self.window.actions["repeat_analysis"].isEnabled())
        self.window.open_sheet(("result", self.source))
        self.settle()
        self.assertTrue(self.window.actions["repeat_analysis"].isEnabled())

    def test_steps_refusals_and_duplicate(self):
        def drive(dialog):
            self.assertTrue(dialog.follow.isChecked())
            self.assertIn("Linear regression", dialog.summary.toPlainText())
            dialog.only.setChecked(True)
            self.assertNotIn("Linear regression of", dialog.summary.toPlainText())
            dialog.follow.setChecked(True)
            dialog.next.click()
            items = {dialog.sheet_list.item(row).data(Qt.ItemDataRole.UserRole): dialog.sheet_list.item(row)
                     for row in range(dialog.sheet_list.count())}
            self.assertFalse(items["Original"].flags() & Qt.ItemFlag.ItemIsEnabled)
            self.assertIn("already runs on this sheet", items["Original"].text())
            self.assertFalse(dialog.next.isEnabled())
            items["Lot B"].setCheckState(Qt.CheckState.Checked)
            self.assertFalse(dialog.next.isEnabled())
            boxes = [dialog.table.cellWidget(row, 1) for row in range(dialog.table.rowCount())]
            for box in boxes:  # Not proposed: the names differ.
                self.assertEqual(box.currentData(), "")
                box.setCurrentIndex(box.findData("Tempo"))
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for row, box in enumerate(boxes):
                self.assertIs(dialog.table.cellWidget(row, 1), box)
            self.assertFalse(dialog.next.isEnabled())
            self.assertIn("chosen twice", dialog.sheet_status.text())
            boxes[1].setCurrentIndex(boxes[1].findData("Segnale"))
            self.assertTrue(dialog.next.isEnabled())
            dialog.next.click()
            self.assertIn("Tempo", dialog.preview.toPlainText())
            dialog.back.click()
            self.assertEqual(dialog.assistant.columns["Lot B"], {"X": "Tempo", "Y": "Segnale"})
            return False

        before = len(self.project.runs)
        self.run_assistant(drive)
        self.assertEqual(len(self.project.runs), before)
        self.assertFalse(self.project.tables["Lot B"].analyses)

    def test_copies_are_added_linked_and_calculated(self):
        self.run_assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]))
        self.assertEqual(self.errors, [])
        runs = self.project.runs
        for title, slope in (("Lot B", 2.), ("Lot C", 5.)):
            parent = next(run for run in runs if run.reference == (title, 0))
            child = next(run for run in runs if run.reference == (title, 1))
            self.assertEqual(child.source.analysis_id, parent.uid)
            self.assertAlmostEqual(child.result.tables["Regression"].at["Slope", "Value"], slope)
        self.assertTrue(self.project.dirty)
        self.assertEqual(self.window.selected[0], "result")
        self.assertEqual(runs[self.window.selected[1]].reference, ("Lot B", 0))

    def test_cancel_and_failure_leave_the_project_unchanged(self):
        from analisi.data import project_bytes
        before, count = project_bytes(self.project.tables), len(self.project.runs)
        self.run_assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]),
                           during=self.window.cancel_calculation)
        self.assertEqual((project_bytes(self.project.tables), len(self.project.runs)), (before, count))
        notices = []

        def reopened(dialog):
            notices.append(dialog.banner.text())
            self.assertEqual(dialog.pages.currentIndex(), 1)
            self.assertEqual(dialog.assistant.selected, ["Lot B", "Short"])
            return False

        self.run_assistant(lambda dialog: self.choose(dialog, ["Lot B", "Short"]), reopened)
        self.assertIn("Short", notices[0])
        self.assertIn("Linear regression", notices[0])
        self.assertEqual((project_bytes(self.project.tables), len(self.project.runs)), (before, count))
        self.assertEqual(self.errors, [])

    def test_changed_project_is_refused(self):
        def change():
            self.project.tables["Lot C"].raw.iat[0, 1] = 4.5
            self.project.dirty = True

        count = len(self.project.runs)
        self.run_assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]), during=change)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("changed during the calculation", self.errors[0])
        self.assertEqual(len(self.project.runs), count)
        self.assertFalse(self.project.tables["Lot B"].analyses)

    def test_preparation_failure_reopens_with_the_same_choices(self):
        from trama_qt import repeat_analysis

        def reopened(dialog):
            self.assertEqual(dialog.pages.currentIndex(), 1)
            self.assertEqual(dialog.assistant.columns["Lot B"], MAPPINGS["Lot B"])
            self.assertIn("Fixture preparation error", dialog.banner.text())
            return False

        with mock.patch.object(repeat_analysis, "prepare_job", side_effect=ValueError("Fixture preparation error")):
            self.run_assistant(lambda dialog: self.choose(dialog, ["Lot B"]), reopened)
        self.assertFalse(self.project.tables["Lot B"].analyses)

    def test_italian_texts(self):
        set_language("it")
        from analisi.repeat_analysis_text import t
        self.assertEqual(t("command"), "Ripeti analisi su altri fogli…")

        def drive(dialog):
            self.assertEqual(dialog.windowTitle(), "Ripeti analisi su altri fogli")
            self.assertEqual(dialog.step.text(), "Passo 1 di 3")
            self.assertIn("Origine: Original", dialog.source.text())
            return False

        self.run_assistant(drive)


if __name__ == "__main__":
    unittest.main()
