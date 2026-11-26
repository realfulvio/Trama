"""File → Update from file… with conflicts decided row by row in the Qt window, offscreen: the package case through
the conflict list (and its inverse), a command for all then single rows changed, Apply waiting for every decision,
the keyboard (Tab into the list, Alt+N, Alt+P, Alt+F, Enter), Undo/Redo, a file changed while decisions are open,
a conflict past the rows the table of changes draws, and the Italian texts. Skipped without PySide6."""
from pathlib import Path
import unittest

import pandas as pd

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from tests.test_qt_source_link import SourceLinkWindowCase

DATA = Path(__file__).resolve().parent / "data" / "source_link" / "per_riga"


def expected(name):
    return pd.read_csv(DATA / name).values.tolist()


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RowByRowConflictWindowTests(SourceLinkWindowCase):
    def setUp(self):
        super().setUp()
        self.path = self.folder / "dati.csv"

    def edited(self):
        """The package case: iniziale linked by ID, B 21, C 31, D 41, E deleted, then aggiornato on disk."""
        self.path.write_text((DATA / "iniziale.csv").read_text(encoding="utf-8"), encoding="utf-8")
        title, _ = self.import_linked(self.path)
        project = self.window.project
        ids = self.ids(title)
        for key, value in (("B", "21"), ("C", "31"), ("D", "41")):
            project.edit_cell(title, ids.index(key), 1, value)
        project.delete_rows(title, [ids.index("E")])
        self.path.write_text((DATA / "aggiornato.csv").read_text(encoding="utf-8"), encoding="utf-8")
        return title

    def rows(self, title):
        return self.window.project.tables[title].raw[["ID", "Y"]].values.tolist()

    @staticmethod
    def lines(panel, *keys):
        return [line for line in range(panel.table.rowCount()) if panel.table.item(line, 0).text() in keys]

    def select(self, panel, keys):
        model = panel.table.selectionModel()
        panel.table.clearSelection()
        for line in self.lines(panel, *keys):
            model.select(panel.table.model().index(line, 0), model.SelectionFlag.Select | model.SelectionFlag.Rows)
        self.app.processEvents()
        self.assertEqual(len(panel.selected_lines()), len(keys))

    def test_package_case_row_by_row_and_its_inverse(self):
        for project_keys, file_keys, name in ((("B", "D"), ("C", "E"), "atteso.csv"),
                                              (("C", "E"), ("B", "D"), "atteso-inverso.csv")):
            with self.subTest(expected=name):
                title = self.edited()
                seen = {}

                def decide(dialog):
                    panel = dialog.conflicts
                    seen["title"] = panel.title()
                    seen["kinds"] = {panel.table.item(line, 0).text(): panel.table.item(line, 1).text()
                                     for line in range(panel.table.rowCount())}
                    seen["differences"] = {panel.table.item(line, 0).text(): panel.table.item(line, 2).text()
                                           for line in range(panel.table.rowCount())}
                    seen["open"] = [panel.state.text(), dialog.apply_button.isEnabled(), panel.keep.isEnabled()]
                    self.select(panel, project_keys)
                    panel.keep.click()
                    seen["half"] = [panel.state.text(), dialog.apply_button.isEnabled()]
                    self.select(panel, file_keys)
                    panel.take.click()
                    seen["decided"] = {panel.table.item(line, 0).text(): panel.table.item(line, 3).text()
                                       for line in range(panel.table.rowCount())}
                    seen["done"] = [panel.state.text(), dialog.apply_button.isEnabled(),
                                    panel.next_open.isEnabled()]
                    seen["states"] = sorted(dialog.table.item(line, 0).text()
                                            for line in range(dialog.table.rowCount())
                                            if ":" in dialog.table.item(line, 0).text())
                    return True

                self.update(decide)
                self.assertEqual(seen["title"], "Changed in the project and in the file (4)")
                self.assertEqual(seen["kinds"], {"E": "Deleted in the project, changed in the file",
                                                 "C": "Changed in both", "B": "Changed in both",
                                                 "D": "Edited in the project, removed from the file"})
                self.assertEqual(seen["differences"]["B"], "Y: 21 → 24")
                self.assertEqual(seen["differences"]["E"], "deleted here · file: Y 55")
                self.assertEqual(seen["differences"]["D"], "worksheet: Y 41 · not in the file")
                self.assertEqual(seen["open"], ["4 of 4 still to decide", False, False])
                self.assertEqual(seen["half"], ["2 of 4 still to decide", False])
                self.assertEqual(seen["done"], ["All 4 decided.", True, False])
                if name == "atteso.csv":
                    self.assertEqual(seen["decided"], {
                        "E": "File: Restores the row", "C": "File: Takes the file values",
                        "B": "Project: Keeps the worksheet values",
                        "D": "Project: Stays at the bottom as a project row"})
                    self.assertIn("Conflict: keep the project", seen["states"])
                    self.assertIn("Edited in the project, removed from the file: keep the project", seen["states"])
                else:
                    self.assertEqual(seen["decided"]["E"], "Project: The row stays deleted")
                    self.assertEqual(seen["decided"]["D"], "File: Removes the row")
                self.assertEqual(self.errors, [])
                self.assertEqual(self.rows(title), expected(name))

    def test_a_command_for_all_then_single_rows_undo_and_redo(self):
        title = self.edited()
        before = self.rows(title)

        def decide(dialog):
            panel = dialog.conflicts
            panel.all_project.click()
            self.assertTrue(dialog.apply_button.isEnabled())
            self.select(panel, ("C", "E"))  # The command for all only filled the lines: they stay editable.
            panel.take.click()
            return True

        self.update(decide)
        self.assertEqual(self.rows(title), expected("atteso.csv"))
        self.window.actions["undo"].trigger()
        self.wait()
        self.assertEqual(self.rows(title), before)
        self.window.actions["redo"].trigger()
        self.wait()
        self.assertEqual(self.rows(title), expected("atteso.csv"))

    def test_enter_with_a_decision_missing_applies_nothing(self):
        title = self.edited()
        before = self.window.project.tables[title].raw

        def decide(dialog):
            panel = dialog.conflicts
            self.select(panel, ("B", "C", "D"))
            panel.keep.click()
            self.assertEqual(panel.state.text(), "1 of 4 still to decide")
            self.assertIn("1 conflict(s) still need a decision", dialog.blocked.text())
            dialog.accept()  # Enter on a preview with an open conflict.
            self.assertTrue(dialog.isVisible())
            return False

        self.update(decide)
        self.assertIs(self.window.project.tables[title].raw, before)
        self.assertIn("Update cancelled: nothing changed.", self.messages)

    def test_keyboard_tab_into_the_list_alt_n_alt_p_alt_f_and_enter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        title = self.edited()
        reached = []

        def keys(dialog):
            panel = dialog.conflicts
            dialog.activateWindow()
            dialog.table.setFocus()
            self.app.processEvents()
            for _ in range(30):  # Tab from the table of changes reaches the conflict list.
                focus = self.app.focusWidget()
                if focus is panel.table:
                    reached.append("list")
                    break
                QTest.keyClick(focus, Qt.Key.Key_Tab)
            by_key = {"B": Qt.Key.Key_P, "D": Qt.Key.Key_P, "C": Qt.Key.Key_F, "E": Qt.Key.Key_F}
            for _ in range(4):
                QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_N, Qt.KeyboardModifier.AltModifier)
                QTest.qWait(250)  # A mnemonic animates the click before it fires.
                line = panel.selected_lines()[0]
                key = panel.table.item(line, 0).text()
                QTest.keyClick(self.app.focusWidget(), by_key[key], Qt.KeyboardModifier.AltModifier)
                QTest.qWait(250)
            reached.append(panel.state.text())
            reached.append(dialog.apply_button.isDefault())
            QTest.keyClick(self.app.focusWidget(), Qt.Key.Key_Return)  # Enter = Apply.
            self.app.processEvents()
            reached.append(dialog.isHidden())
            return dialog.isHidden()

        self.update(keys)
        self.assertEqual(reached, ["list", "All 4 decided.", True, True])
        self.assertEqual(self.rows(title), expected("atteso.csv"))

    def test_file_changed_while_decisions_are_open(self):
        title = self.edited()
        before = self.rows(title)
        texts = {}

        def change(dialog):
            dialog.conflicts.all_file.click()
            self.path.write_text("ID,Y\nE,56\nC,32\nA,10\nB,24\nF,60\nG,75\n", encoding="utf-8")
            dialog.accept()
            texts["visible"] = dialog.isVisible()
            texts["enabled"] = dialog.apply_button.isEnabled()
            texts["blocked"] = dialog.blocked.text()
            return False

        self.update(change)
        self.assertTrue(texts["visible"])
        self.assertFalse(texts["enabled"])
        self.assertIn("The file changed while this preview was open.", texts["blocked"])
        self.assertEqual(self.rows(title), before)
        # A new preview reads the new file and its decisions start again from nothing.
        seen = {}

        def look(dialog):
            seen["state"] = dialog.conflicts.state.text()
            seen["E"] = dialog.conflicts.table.item(self.lines(dialog.conflicts, "E")[0], 2).text()
            return False

        self.update(look)
        self.assertEqual(seen, {"state": "4 of 4 still to decide", "E": "deleted here · file: Y 56"})

    def test_a_conflict_past_the_rows_the_table_of_changes_draws(self):
        count = 1_200
        self.path.write_text("\n".join(["ID,Y"] + [f"K{row:04d},{row}" for row in range(count)]) + "\n",
                             encoding="utf-8")
        title, _ = self.import_linked(self.path)
        project = self.window.project
        raw = project.tables[title].raw.copy()
        raw["Y"] = raw["Y"] + 1000
        project.edit(title, "Edit", lambda dataset: setattr(dataset, "raw", raw))
        self.path.write_text("\n".join(["ID,Y"] + [f"K{row:04d},{row + 5}" for row in range(count)]) + "\n",
                             encoding="utf-8")
        seen = {}

        def decide(dialog):
            panel = dialog.conflicts
            seen["drawn"] = dialog.table.rowCount()
            seen["listed"] = panel.table.rowCount()
            panel.table.selectAll()
            panel.table.selectionModel().select(
                panel.table.model().index(count - 1, 0),
                panel.table.selectionModel().SelectionFlag.Deselect | panel.table.selectionModel().SelectionFlag.Rows)
            panel.keep.click()
            seen["state"] = panel.state.text()
            panel.next_open.click()
            seen["next"] = [panel.table.item(line, 0).text() for line in panel.selected_lines()]
            panel.take.click()
            seen["done"] = [panel.state.text(), dialog.apply_button.isEnabled()]
            return True

        self.update(decide)
        self.assertEqual(seen["drawn"], 1_000)
        self.assertEqual(seen["listed"], count)
        self.assertEqual(seen["state"], "1 of 1,200 still to decide")
        self.assertEqual(seen["next"], ["K1199"])
        self.assertEqual(seen["done"], ["All 1,200 decided.", True])
        values = project.tables[title].raw["Y"].tolist()
        self.assertEqual(values[-1], count - 1 + 5)
        self.assertEqual(values[0], 1000)

    def test_italian_texts_of_the_conflict_list(self):
        from analisi.i18n import set_language
        set_language("it")
        title = self.edited()
        seen = {}

        def look(dialog):
            panel = dialog.conflicts
            seen["title"] = panel.title()
            seen["buttons"] = [button.text() for button in (panel.all_project, panel.all_file, panel.keep, panel.take,
                                                            panel.next_open)]
            seen["header"] = [panel.table.horizontalHeaderItem(column).text() for column in range(4)]
            seen["open"] = [panel.state.text(), panel.table.item(0, 3).text()]
            panel.all_file.click()
            seen["done"] = panel.state.text()
            seen["E"] = panel.table.item(self.lines(panel, "E")[0], 3).text()
            return False

        self.update(look)
        self.assertEqual(seen["title"], "Cambiate nel progetto e nel file (4)")
        self.assertEqual(seen["buttons"], ["Mantieni il progetto per tutte", "Usa il file per tutte",
                                           "Mantieni il &progetto", "Usa il &file", "&Successiva da decidere"])
        letters = [text[text.index("&") + 1].lower() for text in seen["buttons"] if "&" in text]
        self.assertEqual(len(letters), len(set(letters)), letters)  # Every Alt shortcut reaches one button.
        self.assertEqual(seen["header"], ["Chiave", "Conflitto", "Differenze (foglio → file)", "Decisione"])
        self.assertEqual(seen["open"], ["4 di 4 ancora da decidere", "Da decidere"])
        self.assertEqual(seen["done"], "Tutte le 4 decise.")
        self.assertEqual(seen["E"], "File: ripristina la riga")
        self.assertEqual(self.rows(title)[0], ["A", 10])  # Cancel: nothing changed.


if __name__ == "__main__":
    unittest.main()
