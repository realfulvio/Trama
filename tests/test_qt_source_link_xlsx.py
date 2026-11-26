"""Worksheets linked to a sheet of an .xlsx workbook in the Qt window, offscreen: File → Import data… on a workbook
(sheet by name, header row or by position, key), File → Source link… showing the sheet, the package case (B edited
in the project and in the file, Keep the project / Use the file, Undo, Redo, save and reopen), Apply kept off by
duplicate keys and formulas without a stored result, the explicit choice of another sheet after a rename, a
workbook changed while the preview is open, Link to a file… on an existing worksheet, and Italian texts.
Skipped without PySide6."""
import csv
from pathlib import Path
import shutil
import unittest
from unittest import mock

from tests.test_qt_source_link import QApplication, SourceLinkWindowCase

DATA = Path(__file__).resolve().parent / "data" / "source_link_xlsx"


def expected(name):
    with (DATA / name).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return [[row[0], int(row[1]), int(row[2])] for row in rows[1:]]


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class WorkbookLinkWindowTests(SourceLinkWindowCase):
    def setUp(self):
        super().setUp()
        self.book = self.folder / "misure.xlsx"
        self.use("iniziale.xlsx")

    def use(self, fixture):
        shutil.copyfile(DATA / fixture, self.book)

    def import_book(self, sheet="Misure", key="ID", header=1, link=True, look=None):
        from trama_qt.workbook_link import WorkbookImportDialog
        seen = {}

        def choose(dialog):
            seen["sheets"] = [dialog.sheet_box.itemText(index) for index in range(dialog.sheet_box.count())]
            seen["default"] = dialog.import_button.isDefault()
            dialog.set_choice(sheet, header)
            dialog.link.setChecked(link)
            dialog.set_key(key)
            seen["names"] = [dialog.grid.horizontalHeaderItem(column).text()
                             for column in range(dialog.grid.columnCount())]
            seen["enabled"] = dialog.import_button.isEnabled()
            if look is not None:
                look(dialog, seen)
            return True

        with self.drive(WorkbookImportDialog, choose):
            self.window.open_path(self.book, import_data=True)
        self.wait()
        return self.window._active_table(), seen

    def rows(self, title, project=None):
        raw = (project or self.window.project).tables[title].raw
        return [[identity, int(dose), int(response)]
                for identity, dose, response in zip(raw["ID"], raw["Dose"], raw["Response"])]

    def regression(self, title):
        frame = self.window.project.tables[title].frame()
        candidate = self.window.project.candidate(title, "Linear regression", {"X": "Dose", "Y": "Response"})
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        self.window.show_sheet("data", title)
        self.app.processEvents()

    def edit_b(self, title, value="50"):
        self.window.project.edit_cell(title, self.ids(title).index("B"), 2, value)

    def link_dialog_rows(self, title):
        from trama_qt.source_link import SourceLinkDialog
        dialog = SourceLinkDialog(self.window, self.window.project, title)
        from PySide6.QtWidgets import QFormLayout
        layout = next(item for item in dialog.findChildren(QFormLayout))
        rows = {}
        for row in range(layout.rowCount()):
            label = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if label is not None and field is not None:
                rows[label.widget().text()] = field.widget().text()
        dialog.deleteLater()
        return rows

    # -- import and properties -----------------------------------------------------------------------------------
    def test_import_links_the_named_sheet_and_the_properties_show_it(self):
        title, seen = self.import_book()
        self.assertEqual(seen["sheets"], ["Riepilogo", "Misure"])
        self.assertEqual(seen["names"], ["ID", "Dose", "Response"])
        self.assertTrue(seen["default"])
        self.assertTrue(seen["enabled"])
        self.assertEqual(title, "Misure")
        link = self.window.project.tables[title].source_link
        self.assertEqual((link.kind, link.sheet, link.key), ("xlsx", "Misure", "ID"))
        self.assertEqual(self.ids(title), ["A", "B", "C", "D"])
        self.assertTrue(self.window.actions["refresh_source"].isEnabled())
        rows = self.link_dialog_rows(title)
        self.assertEqual(rows["Excel sheet"], "Misure")
        self.assertEqual(rows["Read as"], "Excel workbook · sheet Misure · header row 1")
        self.assertEqual(rows["Key column"], "ID")
        self.regression(title)
        self.assertAlmostEqual(self.slope(), 2.0, places=12)

    def test_import_without_link_and_by_position(self):
        title, seen = self.import_book(sheet="Riepilogo", header=None, link=False, key=None)
        self.assertEqual(seen["names"], ["Column 1", "Column 2", "Column 3"])
        self.assertIsNone(self.window.project.tables[title].source_link)
        self.assertEqual(self.window.project.tables[title].raw["Column 1"].tolist(), ["ID", "A", "B"])

    def test_import_dialog_keeps_import_off_for_a_linked_formula_without_result(self):
        self.use("formula-senza-cache.xlsx")

        def look(dialog, seen):
            seen["blocked"] = dialog.blocked.text()
            dialog.link.setChecked(False)
            seen["unlinked"] = dialog.import_button.isEnabled()
            seen["notes"] = dialog.notes.text()
            dialog.link.setChecked(True)

        _, seen = self.import_book(look=look)
        self.assertIn("C2", seen["blocked"])
        self.assertTrue(seen["unlinked"])  # Without a link it imports, the cell stays empty and the note says so.
        self.assertIn("C2", seen["notes"])
        self.assertEqual(list(self.window.project.tables), [])  # Linked: Import stayed off, nothing was added.

    # -- the package case ----------------------------------------------------------------------------------------
    def test_keep_the_project_undo_redo_save_and_reopen(self):
        title, _ = self.import_book()
        self.edit_b(title)
        self.use("aggiornato.xlsx")
        before = self.book.read_bytes()
        states = {}

        def decide(dialog):
            states["before"] = dialog.apply_button.isEnabled()
            states["heading"] = dialog.findChild(type(dialog.summary), "dialogTitle").text()
            dialog.conflicts.all_project.click()
            states["after"] = dialog.apply_button.isEnabled()
            return True

        seen = self.update(decide)
        self.assertEqual((states["before"], states["after"]), (False, True))
        self.assertEqual(states["heading"], "Update from file · misure.xlsx · Misure")
        self.assertIn("1 conflicts", seen["summary"])
        self.assertEqual(self.rows(title), expected("atteso-progetto.csv"))
        self.assertEqual(self.ids(title), ["C", "B", "E", "D"])
        self.assertEqual(self.book.read_bytes(), before)  # Only read.
        self.window.actions["undo"].trigger()
        self.wait()
        self.assertEqual(self.ids(title), ["A", "B", "C", "D"])
        self.window.actions["redo"].trigger()
        self.wait()
        self.assertEqual(self.rows(title), expected("atteso-progetto.csv"))
        target = self.folder / "studio.alab"
        self.window.project.save(target)
        from trama_qt.project import Project
        reopened = Project()
        reopened.load(target)
        self.assertEqual(self.rows(title, reopened), expected("atteso-progetto.csv"))
        self.assertEqual(reopened.tables[title].source_link.sheet, "Misure")

    def test_use_the_file(self):
        title, _ = self.import_book()
        self.edit_b(title)
        self.use("aggiornato.xlsx")
        self.update(lambda dialog: (dialog.conflicts.all_file.click(), True)[1])
        self.assertEqual(self.rows(title), expected("atteso-excel.csv"))

    def test_duplicate_and_formula_keep_apply_off(self):
        title, _ = self.import_book()
        raw = self.window.project.tables[title].raw
        for fixture, text in (("duplicato.xlsx", "The key column ID repeats B."), ("formula-senza-cache.xlsx", "C2")):
            with self.subTest(fixture=fixture):
                self.use(fixture)
                seen = self.update(lambda dialog: True)
                self.assertFalse(seen["enabled"])
                self.assertIn(text, seen["blocked"])
                self.assertIs(self.window.project.tables[title].raw, raw)

    def test_renamed_sheet_is_chosen_explicitly_and_kept_after_reopen(self):
        title, _ = self.import_book()
        self.use("rinominato.xlsx")
        from trama_qt.source_link import UpdatePreviewDialog
        seen = []

        def look(dialog):
            seen.append({"enabled": dialog.apply_button.isEnabled(), "blocked": dialog.blocked.text(),
                         "choice": None if dialog.sheet_choice is None else
                         [dialog.sheet_choice.itemText(index) for index in range(dialog.sheet_choice.count())],
                         "auto": None if dialog.sheet_choice is None else dialog.read_sheet.autoDefault()})
            if dialog.sheet_choice is not None:
                dialog.sheet_choice.setCurrentIndex(dialog.sheet_choice.findData("Misure 2027"))
                dialog.read_sheet.click()
                return False
            return True

        with self.drive(UpdatePreviewDialog, look):
            self.window.actions["refresh_source"].trigger()
            self.wait()
            self.wait()
        self.assertEqual(len(seen), 2)
        self.assertFalse(seen[0]["enabled"])
        self.assertIn("no longer has the sheet Misure", seen[0]["blocked"])
        self.assertEqual(seen[0]["choice"], ["Misure 2027", "Riepilogo"])
        self.assertFalse(seen[0]["auto"])  # Enter stays on Apply.
        self.assertTrue(seen[1]["enabled"])
        self.assertIsNone(seen[1]["choice"])
        self.assertEqual(self.window.project.tables[title].source_link.sheet, "Misure 2027")
        self.assertEqual(self.ids(title), ["C", "B", "E", "D"])
        target = self.folder / "studio.alab"
        self.window.project.save(target)
        from trama_qt.project import Project
        reopened = Project()
        reopened.load(target)
        self.assertEqual(reopened.tables[title].source_link.sheet, "Misure 2027")

    def test_workbook_changed_while_the_preview_is_open(self):
        title, _ = self.import_book()
        self.use("aggiornato.xlsx")
        raw = self.window.project.tables[title].raw

        def change(dialog):
            self.use("duplicato.xlsx")
            return True

        self.update(change)
        self.assertIs(self.window.project.tables[title].raw, raw)
        self.assertIn("Update cancelled: nothing changed.", self.messages)

    def test_link_an_existing_worksheet_to_a_sheet(self):
        import pandas as pd
        from trama_qt import source_link as qt_link
        from trama_qt.source_link import SourceLinkDialog, UpdatePreviewDialog
        from trama_qt.workbook_link import WorkbookImportDialog
        title = self.window.project.add_tables({"Prove": pd.DataFrame({"ID": ["A", "B", "C", "D"],
                                                                        "Dose": [1, 2, 3, 4],
                                                                        "Response": [3, 5, 7, 9]})})[0]
        self.window.show_sheet("data", title)
        self.app.processEvents()

        def choose(dialog):
            dialog.set_choice("Misure")
            dialog.set_key("ID")
            return True

        with mock.patch.object(SourceLinkDialog, "exec", lambda dialog: dialog._choose("change")), \
                mock.patch.object(qt_link, "choose_file", lambda *args, **kwargs: self.book), \
                self.drive(WorkbookImportDialog, choose), self.drive(UpdatePreviewDialog, lambda dialog: True):
            self.window.actions["source_link"].trigger()
            self.wait()
            self.wait()
        link = self.window.project.tables[title].source_link
        self.assertEqual((link.kind, link.sheet, link.key), ("xlsx", "Misure", "ID"))
        self.assertEqual(self.ids(title), ["A", "B", "C", "D"])

    def test_italian_texts(self):
        from analisi.i18n import set_language
        from trama_qt.workbook_link import WorkbookImportDialog
        set_language("it")
        dialog = WorkbookImportDialog(self.window, self.book)
        try:
            self.assertEqual(dialog.link.text(), "Collega al file sorgente")
            self.assertEqual(dialog.import_button.text(), "Importa")
            self.assertEqual(dialog.by_position.text(), "Senza intestazione: leggi le colonne per posizione")
        finally:
            dialog.deleteLater()
        set_language("en")
        title, _ = self.import_book()
        set_language("it")
        rows = self.link_dialog_rows(title)
        self.assertEqual(rows["Foglio Excel"], "Misure")
        self.assertEqual(rows["Letto come"], "Cartella Excel · foglio Misure · riga d'intestazione 1")
        self.use("rinominato.xlsx")
        seen = self.update(lambda dialog: False)
        self.assertIn("La cartella non ha più il foglio Misure", seen["blocked"])


if __name__ == "__main__":
    unittest.main()
