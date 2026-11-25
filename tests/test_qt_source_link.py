"""File → Update from file… and File → Source link… in the Qt window, offscreen: import with "Link to the source
file", the regression of the package case (slope 2 → 2.2, Undo 2, Redo 2.2), the preview and its decisions, a file
that is missing, moved or changed while the preview is open, Cancel while reading, unlinking, Italian texts and the
Excel export of the last confirmed version. Skipped without PySide6."""
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

DATA = Path(__file__).resolve().parent / "data" / "source_link"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SourceLinkWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.window import MainWindow
        previous = active_language()
        set_language("en")
        self.addCleanup(set_language, previous)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.messages = []
        original = self.window.status
        self.window.status = lambda text, *args, **kwargs: (self.messages.append(text),
                                                            original(text, *args, **kwargs))[1]
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
            time.sleep(0.01)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "the worker did not finish")

    # -- helpers ---------------------------------------------------------------------------------------------------
    def drive(self, cls, configure):
        """Replace ``cls.exec``: ``configure(dialog)`` acts like a person and returns True to confirm."""
        def run(dialog):
            dialog.show()
            self.app.processEvents()
            if configure(dialog):
                dialog.accept()
                return dialog.DialogCode.Accepted if dialog.isHidden() else dialog.DialogCode.Rejected
            dialog.reject()
            return dialog.DialogCode.Rejected
        return mock.patch.object(cls, "exec", run)

    def import_linked(self, path, key="ID", configure=None):
        from trama_qt.text_import import TextImportDialog
        seen = {}

        def choose(dialog):
            seen["link"] = dialog.link.text()
            dialog.link.setChecked(True)
            dialog.key.setCurrentIndex(dialog.key.findData(key) if key else 0)
            if configure is not None:
                configure(dialog)
            return True

        with self.drive(TextImportDialog, choose):
            self.window.open_path(path, import_data=True)
        self.wait()
        title = self.window._active_table()
        self.assertIsNotNone(self.window.project.tables[title].source_link)
        return title, seen

    def regression(self, title):
        frame = self.window.project.tables[title].frame()
        candidate = self.window.project.candidate(title, "Linear regression", {"X": "X", "Y": "Y"})
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        self.window.show_sheet("data", title)
        self.app.processEvents()

    def slope(self):
        return float(self.window.project.runs[0].result.tables["Regression"].loc["Slope"].iloc[0])

    def update(self, configure):
        from trama_qt.source_link import UpdatePreviewDialog
        seen = {}

        def look(dialog):
            seen["summary"] = dialog.summary.text()
            seen["blocked"] = dialog.blocked.text() if dialog.blocked.isVisibleTo(dialog) else ""
            seen["notices"] = dialog.notices.text() if dialog.notices.isVisibleTo(dialog) else ""
            seen["enabled"] = dialog.apply_button.isEnabled()
            seen["default"] = dialog.apply_button.isDefault()
            seen["banner"] = dialog.blocked.objectName()
            seen["cells"] = [[dialog.table.item(row, column).text() for column in range(dialog.table.columnCount())]
                             for row in range(dialog.table.rowCount())]
            return configure(dialog)

        with self.drive(UpdatePreviewDialog, look):
            self.window.actions["refresh_source"].trigger()
            self.wait()
        self.wait()
        return seen

    def ids(self, title):
        return self.window.project.tables[title].raw["ID"].tolist()

    def copy(self, fixture, target):
        shutil.copyfile(DATA / fixture, target)

    # -- the package case ------------------------------------------------------------------------------------------
    def test_update_from_file_applies_one_undoable_step_and_recalculates(self):
        from trama_qt.classic_bar import MENUS
        file_menu = dict(MENUS)["File"]
        self.assertIn("refresh_source", file_menu)
        self.assertIn("source_link", file_menu)
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        self.assertFalse(self.window.actions["refresh_source"].isEnabled())
        title, seen = self.import_linked(path)
        self.assertEqual(seen["link"], "Link to the source file")
        self.assertTrue(self.window.actions["refresh_source"].isEnabled())
        self.assertEqual(self.window.actions["refresh_source"].shortcut().toString(), "Ctrl+Shift+U")
        self.regression(title)
        self.assertAlmostEqual(self.slope(), 2.0, places=12)
        self.copy("aggiornato.csv", path)
        before = path.read_bytes()
        seen = self.update(lambda dialog: True)
        self.assertEqual(seen["summary"],
                         "4 rows in the file · 1 added · 1 modified · 0 removed · 1 moved · 2 unchanged")
        self.assertTrue(seen["enabled"])
        self.assertEqual(seen["cells"], [["Modified", "2 → 3", "B", "2", "5 → 9"], ["Added", "4", "D", "4", "11"],
                                         ["Moved", "3 → 1", "C", "3", "7"]])
        self.assertIn("The rows take the order of the file.", seen["notices"])
        self.assertTrue(seen["default"])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])
        self.assertAlmostEqual(self.slope(), 2.2, places=12)
        self.assertTrue(any(text.startswith("Updated from dati.csv") for text in self.messages))
        self.assertEqual(path.read_bytes(), before)  # Only read.
        self.window.actions["undo"].trigger()
        self.wait()
        self.assertEqual(self.ids(title), ["A", "B", "C"])
        self.assertEqual(self.window.project.tables[title].raw["Y"].tolist(), [3, 5, 7])
        self.assertAlmostEqual(self.slope(), 2.0, places=12)
        self.window.actions["redo"].trigger()
        self.wait()
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])
        self.assertAlmostEqual(self.slope(), 2.2, places=12)
        # The export reads the last confirmed version.
        from trama_qt.excel_workbook import ExcelExportDialog
        from openpyxl import load_workbook

        def choose(dialog):
            dialog.set_checked(("data", title))
            return True

        workbook = self.folder / "uscita.xlsx"
        with self.drive(ExcelExportDialog, choose):
            self.window.export_excel_workbook(workbook)
        self.wait()
        self.assertEqual(self.errors, [])
        sheet = load_workbook(workbook)[title]
        self.assertEqual([row[0] for row in sheet.iter_rows(min_row=2, values_only=True)][:4], ["C", "A", "B", "D"])

    def test_duplicate_keys_keep_apply_off_and_change_nothing(self):
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        raw = self.window.project.tables[title].raw
        self.copy("duplicato.csv", path)
        seen = self.update(lambda dialog: True)  # Even pressing Enter on a blocked preview applies nothing.
        self.assertFalse(seen["enabled"])
        self.assertIn("Apply is not available:", seen["blocked"])
        self.assertIn("The key column ID repeats B.", seen["blocked"])
        self.assertEqual(seen["banner"], "infoBanner")
        self.assertIs(self.window.project.tables[title].raw, raw)
        self.assertIn("Update cancelled: nothing changed.", self.messages)

    def test_conflict_needs_a_choice_before_apply(self):
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        self.window.project.edit_cell(title, 1, 2, "6")
        self.copy("aggiornato.csv", path)
        states = {}

        def decide(dialog):
            states["before"] = dialog.apply_button.isEnabled()
            states["cells"] = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
            buttons = dialog.choices.buttons()
            self.assertFalse(any(button.isChecked() for button in buttons))
            next(button for button in buttons if button.property("choice") == "file").setChecked(True)
            states["after"] = dialog.apply_button.isEnabled()
            return True

        seen = self.update(decide)
        self.assertIn("1 conflicts", seen["summary"])
        self.assertFalse(states["before"])
        self.assertTrue(states["after"])
        self.assertEqual(states["cells"][0], "Conflict")
        values = dict(zip(self.ids(title), self.window.project.tables[title].raw["Y"].tolist()))
        self.assertEqual(values["B"], 9)

    def test_cancel_in_the_preview_keeps_everything(self):
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        link = self.window.project.tables[title].source_link
        self.copy("aggiornato.csv", path)
        self.update(lambda dialog: False)
        self.assertEqual(self.ids(title), ["A", "B", "C"])
        self.assertIs(self.window.project.tables[title].source_link, link)
        self.assertIn("Update cancelled: nothing changed.", self.messages)

    def test_file_changed_while_the_preview_is_open(self):
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        self.copy("aggiornato.csv", path)
        texts = {}

        def change_file(dialog):
            path.write_text("ID,X,Y\nA,1,3\nB,2,50\nC,3,7\nE,5,13\n", encoding="utf-8")
            dialog.accept()  # Apply: refused, the preview stays open and says why.
            texts["visible"] = dialog.isVisible()
            texts["blocked"] = dialog.blocked.text()
            texts["enabled"] = dialog.apply_button.isEnabled()
            return False

        self.update(change_file)
        self.assertTrue(texts["visible"])
        self.assertFalse(texts["enabled"])
        self.assertIn("The file changed while this preview was open.", texts["blocked"])
        self.assertEqual(self.ids(title), ["A", "B", "C"])

    def test_missing_file_asks_to_locate_and_never_searches(self):
        from trama_qt import source_link as commands
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        elsewhere = self.folder / "nuova cartella"
        elsewhere.mkdir()
        self.copy("aggiornato.csv", elsewhere / "dati.csv")
        path.unlink()
        asked = {}

        def press(text):
            def run(box):
                asked["text"] = box.text()
                next(button for button in box.buttons() if button.text() == text).click()
                return 0
            return run

        with mock.patch.object(QMessageBox, "exec", press("Locate…")), \
                mock.patch.object(commands, "choose_file", return_value=elsewhere / "dati.csv"):
            seen = self.update(lambda dialog: True)
        self.assertIn("The linked file was not found", asked["text"])
        self.assertIn("File chosen by you", seen["notices"])
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])
        self.assertEqual(Path(self.window.project.tables[title].source_link.path), elsewhere / "dati.csv")
        # Cancel at the question: nothing changes.
        (elsewhere / "dati.csv").unlink()
        with mock.patch.object(QMessageBox, "exec", press("Cancel")):
            self.window.actions["refresh_source"].trigger()
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])
        self.assertEqual(self.messages[-1], "Update cancelled: nothing changed.")

    def test_project_moved_with_its_file_asks_to_confirm_the_relative_path(self):
        folder = self.folder / "Studio"
        folder.mkdir()
        path = folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        self.window.project.save(folder / "studio.alab")
        moved = self.folder / "Studio copiato"
        shutil.copytree(folder, moved)
        shutil.rmtree(folder)
        self.copy("aggiornato.csv", moved / "dati.csv")
        self.window.project.path = moved / "studio rinominato.alab"
        states = {}

        def confirm(dialog):
            states["before"] = dialog.apply_button.isEnabled()
            dialog.use_file.setChecked(True)
            states["after"] = dialog.apply_button.isEnabled()
            return True

        self.update(confirm)
        self.assertEqual((states["before"], states["after"]), (False, True))
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])

    def test_cancel_while_reading(self):
        path = self.folder / "grande.csv"
        path.write_text("ID,X\n" + "".join(f"K{row},{row}\n" for row in range(60000)), encoding="utf-8")
        title, _ = self.import_linked(path)
        raw = self.window.project.tables[title].raw
        from analisi import source_link as engine
        original = engine.read_file

        def slow(path_, *, cancel=None, progress=None):
            end = time.monotonic() + 10
            while self.window.job is None and time.monotonic() < end:
                time.sleep(0.005)
            self.window.job.control.cancel.set()  # Cancel pressed while the file is read.
            return original(path_, cancel=cancel, progress=progress)

        with mock.patch.object(engine, "read_file", slow):
            self.window.actions["refresh_source"].trigger()
            self.wait()
        self.assertIs(self.window.project.tables[title].raw, raw)
        self.assertEqual(self.messages[-1], "Update cancelled: nothing changed.")

    def test_source_link_dialog_unlink_and_undo(self):
        from trama_qt.source_link import SourceLinkDialog
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, _ = self.import_linked(path)
        link = self.window.project.tables[title].source_link
        seen = {}

        def look(dialog):
            from PySide6.QtWidgets import QLabel, QPushButton
            seen["texts"] = [label.text() for label in dialog.findChildren(QLabel)]
            buttons = {button.objectName(): button for button in dialog.findChildren(QPushButton)}
            seen["auto"] = [buttons[name].autoDefault() for name in ("sourceLink_update", "sourceLink_change",
                                                                       "sourceLink_unlink")]
            buttons["sourceLink_unlink"].click()
            return False

        with self.drive(SourceLinkDialog, look), \
                mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.actions["source_link"].trigger()
        self.assertIn(str(path), seen["texts"])
        self.assertIn("ID", seen["texts"])
        self.assertEqual(seen["auto"], [False, False, False])
        self.assertIsNone(self.window.project.tables[title].source_link)
        self.assertFalse(self.window.actions["refresh_source"].isEnabled())
        self.assertEqual(self.ids(title), ["A", "B", "C"])
        self.window.actions["undo"].trigger()
        self.wait()
        self.assertIs(self.window.project.tables[title].source_link, link)
        self.assertTrue(self.window.actions["refresh_source"].isEnabled())

    def test_link_an_existing_worksheet_with_change_source(self):
        import pandas as pd
        from trama_qt import source_link as commands
        from trama_qt.text_import import TextImportDialog
        title = self.window.project.add_tables({"Misure": pd.DataFrame({"ID": ["A", "B"], "X": [1, 2],
                                                                        "Y": [3, 5]})})[0]
        self.window.refresh()
        self.window.show_sheet("data", title)
        self.app.processEvents()
        path = self.folder / "misure.csv"
        self.copy("aggiornato.csv", path)

        def choose(dialog):
            dialog.link.setChecked(True)
            dialog.key.setCurrentIndex(dialog.key.findData("ID"))
            return True

        with mock.patch.object(commands, "choose_file", return_value=path), \
                self.drive(TextImportDialog, choose):
            seen = self.update_with(lambda: commands.change_source(self.window, title), lambda dialog: True)
        self.assertIn("2 added", seen["summary"])
        self.assertIn("1 modified", seen["summary"])
        self.assertEqual(self.ids(title), ["C", "A", "B", "D"])
        self.assertEqual(self.window.project.tables[title].source_link.key, "ID")

    def update_with(self, start, configure):
        from trama_qt.source_link import UpdatePreviewDialog
        seen = {}

        def look(dialog):
            seen["summary"] = dialog.summary.text()
            return configure(dialog)

        with self.drive(UpdatePreviewDialog, look):
            start()
            self.wait()
        self.wait()
        return seen

    def test_italian_texts(self):
        from analisi.i18n import set_language
        from trama_qt.source_link import summary, t, translate
        from analisi.source_link import message
        set_language("it")
        self.assertEqual(t("Update from file…"), "Aggiorna da file…")
        self.assertEqual(t("Source link…"), "Collegamento sorgente…")
        self.assertEqual(translate(message("The key column {name} repeats {keys}.", name="ID", keys="B")),
                         "La colonna chiave ID ripete B.")
        path = self.folder / "dati.csv"
        self.copy("iniziale.csv", path)
        title, seen = self.import_linked(path)
        self.assertEqual(seen["link"], "Collega al file sorgente")
        self.copy("aggiornato.csv", path)
        seen = self.update(lambda dialog: True)
        self.assertEqual(seen["summary"],
                         "4 righe nel file · 1 aggiunte · 1 modificate · 0 rimosse · 1 spostate · 2 invariate")
        self.assertEqual([row[0] for row in seen["cells"]], ["Modificata", "Aggiunta", "Spostata"])
        self.assertIn("Le righe prendono l'ordine del file.", seen["notices"])
        self.assertTrue(summary)


if __name__ == "__main__":
    unittest.main()
