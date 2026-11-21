"""File → Import/Export Excel workbook on the Qt window, offscreen: the real dialogs, the worker, Cancel, errors
that change nothing, the overwrite question and a reopen of the exported file. Skipped without PySide6."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd
from openpyxl import load_workbook

DATA = Path(__file__).resolve().parent / "data" / "xlsx_exchange"
FIXTURE = DATA / "quaderno-multifoglio.xlsx"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ExcelWorkbookTests(unittest.TestCase):
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
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
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

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "still running")

    def drive(self, configure):
        """Replace QDialog.exec: ``configure(dialog)`` sets the dialog like a person, then returns the code
        (accept() is called for Accepted)."""
        original = QDialog.exec

        def run(dialog):
            dialog.show()
            self.app.processEvents()
            accepted = configure(dialog)
            if accepted:
                dialog.accept()
                return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected
            dialog.reject()
            return QDialog.DialogCode.Rejected
        return mock.patch.object(QDialog, "exec", run), original

    def import_fixture(self, configure, path=FIXTURE):
        patch, _ = self.drive(configure)
        with patch:
            self.window.import_excel_workbook(path)
        self.wait()

    # -- import ------------------------------------------------------------------------------------
    def test_dialog_lists_sheets_and_previews_header_rows(self):
        seen = {}

        def configure(dialog):
            states = [dialog.list.item(row, 1).text() for row in range(dialog.list.rowCount())]
            seen["states"] = states
            seen["checked"] = dialog.checked()
            seen["vuoto_flags"] = dialog.list.item(3, 0).flags()
            dialog.set_header("Controlli", 2)
            seen["names"] = dialog.names.text()
            seen["letters"] = [dialog.grid.horizontalHeaderItem(index).text() for index in range(dialog.grid.columnCount())]
            seen["rows"] = [dialog.grid.verticalHeaderItem(index).text() for index in range(dialog.grid.rowCount())]
            dialog.set_header("Controlli", 9)
            seen["error"] = dialog.notes.text()
            seen["enabled_on_error"] = dialog.import_button.isEnabled()
            dialog.set_header("Controlli", None)
            seen["no_header"] = dialog.names.text()
            dialog.set_header("Controlli", 2)
            dialog.select("Campioni α")
            seen["value"] = dialog.grid.item(1, 0).text()
            seen["warning"] = dialog.notes.text()
            return False

        self.import_fixture(configure)
        self.assertEqual(seen["states"], ["visible", "visible", "hidden", "visible · empty"])
        self.assertEqual(seen["checked"], ["Campioni α", "Controlli"])  # Visible readable sheets only.
        self.assertFalse(seen["vuoto_flags"] & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertEqual(seen["names"], "Names in Trama: ID esterno, Risposta")
        self.assertEqual(seen["letters"], ["A", "B"])
        self.assertEqual(seen["rows"][:2], ["1", "2"])
        self.assertIn("past the last row", seen["error"])
        self.assertFalse(seen["enabled_on_error"])
        self.assertEqual(seen["no_header"], "Names in Trama: Column 1, Column 2")
        self.assertEqual(seen["value"], "0007")
        self.assertIn("G3", seen["warning"])
        self.assertFalse(self.window.project.tables)  # Cancel adds nothing.

    def test_import_two_sheets_with_header_rows(self):
        notices = []

        def configure(dialog):
            dialog.set_checked("Appunti", False)
            dialog.set_header("Controlli", 2)
            return True

        with mock.patch("trama_qt.excel_workbook.inform", lambda parent, title, text: notices.append(text)):
            self.import_fixture(configure)
        self.assertEqual(self.errors, [])
        tables = self.window.project.tables
        self.assertEqual(list(tables), ["Campioni α", "Controlli"])
        sample = tables["Campioni α"].raw
        self.assertEqual(sample.loc[0, "ID"], "0007")
        self.assertEqual(sample.loc[0, "Data"], "2026-04-06T12:30:00")
        self.assertEqual(sample.loc[0, "Nota"], "=letterale")
        self.assertEqual(sample.loc[0, "Calcolo"], 5)
        self.assertTrue(pd.isna(sample.loc[1, "Calcolo"]))
        self.assertTrue(sample.iloc[2].isna().all())
        self.assertEqual(tables["Controlli"].raw.to_dict("list"), {"ID esterno": ["001", "002"], "Risposta": [0, 13.5]})
        self.assertEqual(self.window.selected, ("data", "Campioni α"))
        self.assertTrue(notices and "G3" in notices[0])
        # Same names again: the project names them as it names any other import.
        with mock.patch("trama_qt.excel_workbook.inform", lambda *args: None):
            self.import_fixture(configure)
        self.assertEqual(list(self.window.project.tables)[2:], ["Campioni α (2)", "Controlli (2)"])

    def test_failures_add_nothing(self):
        self.window.project.add_tables({"Esistente": pd.DataFrame({"A": [1, 2]})})
        before = list(self.window.project.tables)
        self.window.import_excel_workbook(DATA / "rotto.xlsx")
        self.assertEqual(len(self.errors), 1)
        self.assertIn("rotto.xlsx", self.errors[0])
        self.assertTrue(self.window.project.dirty)  # The modified project stays as it was.

        def broken(dialog):  # A sheet whose header row no longer fits by the time it is read.
            dialog.set_header("Controlli", 2)
            dialog.headers["Controlli"] = 99
            dialog.errors.clear()
            return True

        self.import_fixture(broken)
        self.assertEqual(list(self.window.project.tables), before)
        self.assertIn("99", self.errors[-1])

        def cancel_during_read(dialog):
            return True

        original_read = __import__("analisi.xlsx_exchange", fromlist=["WorkbookReader"]).WorkbookReader.read

        def slow_read(reader, selections, **options):
            options["cancel"].set()
            return original_read(reader, selections, **options)

        with mock.patch("analisi.xlsx_exchange.WorkbookReader.read", slow_read):
            self.import_fixture(cancel_during_read)
        self.assertEqual(list(self.window.project.tables), before)
        self.assertIn("cancelled", self.window.message.text())

        def empty(dialog):
            for name in dialog.checked():
                dialog.set_checked(name, False)
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIn("at least one", dialog.notes.text())
            return False

        self.import_fixture(empty)
        self.assertEqual(list(self.window.project.tables), before)

    def test_table_limit(self):
        from trama_qt.excel_workbook import MAX_TABLES
        self.window.project.add_tables({f"T{index}": pd.DataFrame({"A": [1]}) for index in range(MAX_TABLES - 1)})

        def configure(dialog):
            self.assertFalse(dialog.import_button.isEnabled())  # Two visible sheets, room for one.
            dialog.set_checked("Controlli", False)
            return True

        with mock.patch("trama_qt.excel_workbook.inform", lambda *args: None):
            self.import_fixture(configure)
        self.assertEqual(len(self.window.project.tables), MAX_TABLES)

    # -- export ------------------------------------------------------------------------------------
    def analysed_project(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        with mock.patch("trama_qt.excel_workbook.inform", lambda *args: None):
            self.import_fixture(lambda dialog: dialog.set_header("Controlli", 2) or True)
        frame = pd.DataFrame({"Group": ["a", "a", "a", "b", "b", "b", "c", "c", "c"],
                              "Y": [1, 2, 3, 4, 5, 6, 7, 8, 9.5]})
        frame.index = range(len(frame))
        titles = self.window.project.add_tables({"Gruppi": frame})
        self.window.show_sheet("data", titles[0])
        dialog = AnalysisDialog(self.window, frame, current=("One-way ANOVA", {}))
        values = dialog.options()
        dialog.deleteLater()
        values.update({"Response": "Y", "Group": "Group", "Post-hoc": "Tukey", "Brown–Forsythe variance test": True})
        candidate = self.window.project.candidate(titles[0], "One-way ANOVA", values)
        self.window.calculate_candidate(candidate, self.window.project.tables[titles[0]].frame(), None)
        self.wait()
        run = self.window.project.runs.index(self.window.project.runs[-1])
        self.assertGreaterEqual(len(self.window.project.runs[run].result.tables), 2)
        return run

    def test_export_order_names_and_reopen(self):
        run = self.analysed_project()
        self.window.open_sheet(("result", run))
        self.app.processEvents()
        result = self.window.project.runs[run]
        names = list(result.result.tables)
        seen = {}

        def configure(dialog):
            seen["default"] = dialog.chosen()
            dialog.set_checked(("data", "Campioni α"))
            dialog.set_checked(("data", "Controlli"))
            dialog.set_checked(("result", run, names[1]))
            dialog.move_key(("data", "Controlli"), 0)
            dialog.move_key(("data", "Campioni α"), 1)
            seen["excel"] = dialog.excel_names()
            seen["order"] = dialog.chosen()
            return True

        path = self.folder / "uscita.xlsx"
        patch, _ = self.drive(configure)
        with patch:
            self.window.export_excel_workbook(path)
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertEqual(seen["default"], [("result", run, names[0])])  # The table on screen.
        self.assertEqual(seen["order"][:2], [("data", "Controlli"), ("data", "Campioni α")])
        book = load_workbook(path)
        self.assertEqual(book.sheetnames, list(seen["excel"].values()))
        self.assertEqual(len(book.sheetnames), 4)
        self.assertTrue(all(len(name) <= 31 for name in book.sheetnames))
        self.assertFalse(any(cell.data_type == "f" for sheet in book for row in sheet.iter_rows() for cell in row))
        sample = book[book.sheetnames[1]]
        self.assertEqual((sample["A2"].value, sample["A2"].data_type), ("0007", "s"))
        self.assertEqual((sample["H2"].value, sample["H2"].data_type), ("=letterale", "s"))
        anova = book[book.sheetnames[2]]
        self.assertEqual(anova["A1"].value, result.result.tables[names[0]].index.name)  # "Term", kept.
        book.close()
        before = path.read_bytes()

        # Reopen in Trama through the import.
        with mock.patch("trama_qt.excel_workbook.inform", lambda *args: None):
            self.import_fixture(lambda dialog: True, path=path)
        reopened = self.window.project.tables[list(self.window.project.tables)[-1]].raw
        expected = result.result.tables[names[1]]
        self.assertEqual(list(reopened.columns)[0], expected.index.name or "Row")
        self.assertEqual(len(reopened), len(expected))

        # An existing file: No keeps it, Yes replaces it after the new workbook was verified.
        patch, _ = self.drive(lambda dialog: True)
        with patch, mock.patch("trama_qt.excel_workbook.confirm", return_value=False) as asked:
            self.window.export_excel_workbook(path)
        self.wait()
        asked.assert_called_once()
        self.assertEqual(path.read_bytes(), before)
        patch, _ = self.drive(lambda dialog: True)
        with patch, mock.patch("trama_qt.excel_workbook.confirm", return_value=True):
            self.window.export_excel_workbook(path)
        self.wait()
        self.assertNotEqual(path.read_bytes(), before)
        self.assertEqual(sorted(item.name for item in self.folder.iterdir()), ["uscita.xlsx"])

    def test_export_errors_and_cancel_keep_the_old_file(self):
        frame = pd.DataFrame({"A": [1.0, float("inf")]})
        self.window.project.add_tables({"Infinito": frame, "Buono": pd.DataFrame({"B": [1]})})
        self.window.show_sheet("data", "Infinito")
        path = self.folder / "vecchio.xlsx"
        path.write_bytes(b"old")
        patch, _ = self.drive(lambda dialog: True)
        with patch, mock.patch("trama_qt.excel_workbook.confirm", return_value=True):
            self.window.export_excel_workbook(path)
        self.wait()
        self.assertEqual(path.read_bytes(), b"old")
        self.assertIn('"Infinito"', self.errors[-1])
        self.assertIn("row 3", self.errors[-1])

        self.window.show_sheet("data", "Buono")
        original = __import__("analisi.xlsx_exchange", fromlist=["prepare_workbook"]).prepare_workbook

        def cancelled(path_, entries, **options):
            options["cancel"].set()
            return original(path_, entries, **options)

        patch, _ = self.drive(lambda dialog: True)
        with patch, mock.patch("trama_qt.excel_workbook.confirm", return_value=True), \
                mock.patch("trama_qt.excel_workbook.prepare_workbook", cancelled):
            self.window.export_excel_workbook(path)
            self.wait()  # Inside: the worker must see the patched function.
        self.assertEqual(path.read_bytes(), b"old")
        self.assertIn("cancelled", self.window.message.text())
        self.assertEqual(sorted(item.name for item in self.folder.iterdir()), ["vecchio.xlsx"])

    def test_unavailable_results_are_listed_with_a_reason(self):
        from trama_qt.excel_workbook import ExcelExportDialog, export_items
        run = self.analysed_project()
        self.window.project.runs[run].calculation_error = "the data changed"
        items = export_items(self.window.project)
        stale = [item for item in items if item.kind == "result"]
        self.assertTrue(stale and all(item.reason and "the data changed" in item.reason for item in stale))
        dialog = ExcelExportDialog(self.window, items, chosen=[stale[0].key])
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.chosen(), [])
        row = next(index for index, item in enumerate(dialog.order) if item.key == stale[0].key)
        self.assertFalse(dialog.table.item(row, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(dialog.export_button.isEnabled())

    def test_actions_in_the_file_group(self):
        self.assertTrue(self.window.actions["import_excel"].isEnabled())
        self.assertFalse(self.window.actions["export_excel"].isEnabled())
        self.window.project.add_tables({"A": pd.DataFrame({"x": [1]})})
        self.window.refresh()
        self.assertTrue(self.window.actions["export_excel"].isEnabled())
        self.assertEqual(self.window.actions["import_excel"].text(), "Import Excel workbook…")

    def test_italian_texts(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.excel_workbook import t, translate
        previous = active_language()
        set_language("it")
        try:
            self.assertEqual(t("Import Excel workbook…"), "Importa cartella Excel…")
            self.assertEqual(t("Export Excel workbook…"), "Esporta cartella Excel…")
            self.assertIn("oltre l'ultima riga", translate(
                'Worksheet "Controlli": the header row 9 is past the last row with values (4).'))
            self.assertIn("riga 3", translate('Sheet "A" (Excel "A"), row 3, column "x": infinite values cannot be '
                                              'stored in Excel. Correct the data and export again.'))
        finally:
            set_language(previous)


if __name__ == "__main__":
    unittest.main()
