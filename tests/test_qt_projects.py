"""Several independent projects in one Qt window: tabs, isolation, save and close decisions, busy windows.

Offscreen like ``test_qt_shell``; the pure session bookkeeping runs without Qt. The two fixtures use the same
sheet name and the same internal identifiers with different data, so a mix-up between tabs shows at once.
"""
from concurrent.futures import Future
from pathlib import Path
from shutil import copy2
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QTabBar
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from analisi.data import load_project
from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "qt_projects"


class _Project:
    """The few attributes sessions read: enough to test the bookkeeping without the engine."""

    def __init__(self, path=None, origin=None, dirty=False, number=1):
        self.path, self.origin, self.dirty, self.number = path, origin, dirty, number

    @property
    def title(self):
        path = self.path or self.origin
        return path.name if path else f"Untitled {self.number}"


class SessionBookkeepingTests(unittest.TestCase):
    def sessions(self, *projects):
        from trama_qt.sessions import Sessions
        sessions = Sessions(projects[0])
        for project in projects[1:]:
            sessions.add(project)
        return sessions

    def test_neighbour_step_and_limits(self):
        from trama_qt.sessions import MAX_PROJECT_TABS
        sessions = self.sessions(*[_Project(number=n) for n in range(1, 4)])
        first, second, third = sessions.items
        self.assertIs(sessions.neighbour(second), first)
        self.assertIs(sessions.neighbour(first), second)  # The first tab hands over to the next one.
        self.assertIs(sessions.step(-1), third)  # Wraps around.
        sessions.active = third
        self.assertIs(sessions.step(1), first)
        sessions.remove(first)
        self.assertEqual(len(sessions), 2)
        with self.assertRaises(ValueError):
            sessions.remove(sessions.active)
        while not sessions.full():
            sessions.add(_Project())
        self.assertEqual(len(sessions), MAX_PROJECT_TABS)
        with self.assertRaises(ValueError):
            sessions.add(_Project())
        single = self.sessions(_Project())
        self.assertIsNone(single.neighbour(single.active))

    def test_find_matches_the_saved_file_and_the_imported_source(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "dati.alab").write_text("x")
            (folder / "vista.prism").write_text("x")
            sessions = self.sessions(_Project(path=folder / "dati.alab"), _Project(origin=folder / "vista.prism"),
                                     _Project())
            self.assertIs(sessions.find(folder / "dati.alab"), sessions[0])
            self.assertIs(sessions.find(folder / "sub" / ".." / "dati.alab"), sessions[0])  # Same canonical path.
            self.assertIs(sessions.find(folder / "vista.prism"), sessions[1])
            self.assertIsNone(sessions.find(folder / "altro.alab"))
            self.assertIsNone(sessions.holding(folder / "dati.alab", besides=sessions[0]))
            self.assertIs(sessions.holding(folder / "dati.alab", besides=sessions[2]), sessions[0])
            link = folder / "link.alab"
            try:
                link.symlink_to(folder / "dati.alab")
            except OSError:  # Windows without the privilege.
                return
            self.assertIs(sessions.find(link), sessions[0])

    def test_labels_mark_dirty_and_tell_same_names_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name in ("lunedi", "martedi"):
                (folder / name).mkdir()
                (folder / name / "misure.alab").write_text("x")
            sessions = self.sessions(_Project(path=folder / "lunedi" / "misure.alab"),
                                     _Project(path=folder / "martedi" / "misure.alab", dirty=True),
                                     _Project(number=3))
            labels = sessions.labels()
            self.assertEqual(labels[0][0], "misure.alab · lunedi")
            self.assertEqual(labels[1][0], "• misure.alab · martedi")
            self.assertEqual(labels[2][0], "Untitled 3")
            self.assertIn(str(folder / "martedi"), labels[1][1])
            self.assertIn("Unsaved changes", labels[1][1])
            self.assertNotIn(str(folder), labels[2][0])  # Long folders are in the tooltip, not on the tab.

    def test_long_names_keep_both_ends(self):
        from trama_qt.sessions import LABEL_WIDTH, elide
        name = "esperimento-di-calibrazione-molto-lungo-2026-11.alab"
        short = elide(name)
        self.assertEqual(len(short), LABEL_WIDTH)
        self.assertTrue(short.startswith("esperimento") and short.endswith("11.alab") and "…" in short)
        self.assertEqual(elide("breve.alab"), "breve.alab")

    def test_reset_forgets_the_view_only(self):
        sessions = self.sessions(_Project())
        session = sessions.active
        session.selected, session.view, session.status = ("data", "x"), {"cell": (1, 1)}, "ok"
        fresh = _Project(number=2)
        session.reset(fresh)
        self.assertIs(session.project, fresh)
        self.assertEqual((session.selected, session.view, session.status), (None, {}, ""))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ProjectTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-projects", "-platform", "offscreen"])
        from trama_qt import theme
        theme.load_fonts()
        theme.apply(cls.app)

    def setUp(self):
        from trama_qt.window import MainWindow
        self.language = active_language()
        set_language("en")
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.a, self.b = self.folder / "sessione-a.alab", self.folder / "sessione-b.alab"
        copy2(DATA / "sessione-a.alab", self.a)
        copy2(DATA / "sessione-b.alab", self.b)
        self.window = MainWindow()
        self.window.resize(1024, 700)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()
        self.bar = self.window.findChild(QTabBar, "projectTabs")

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window._close_pending = False
        if self.window.job is not None:
            self.window.job = None
            self.window.timer.stop()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()  # An Inspector draft left by a test would ask here.
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    # -- helpers --------------------------------------------------------------------------------------
    def wait(self, timeout=30):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")
        self.assertEqual(self.errors, [])

    def open(self, path):
        self.window.open_path(path)
        self.wait()

    def type_cell(self, row, column, text, *, apply=True):
        """Type into a cell. The model applies it once the editor closes; ``apply`` lets that happen now."""
        model = self.window.sheet.model()
        self.assertTrue(model.setData(model.index(row, column), text))
        if apply:
            self.app.processEvents()
            self.wait()

    def answer(self, button):
        return mock.patch.object(QMessageBox, "question", return_value=button)

    def cell(self, project, row, column):
        return project.tables["Misure"].raw.iloc[row, column]

    def busy(self):
        """A calculation that has not finished: the window state of a running job, without the engine."""
        future = Future()
        done = []
        control = mock.Mock()
        control.cancel = mock.Mock()
        control.cancel.is_set.return_value = False
        control.progress.return_value = (0, 0)
        self.window._start(future, control, lambda f, cancelled: done.append(cancelled), "Calculating…")
        return future, control, done

    # -- opening --------------------------------------------------------------------------------------
    def test_new_and_open_make_tabs_and_the_empty_tab_is_reused(self):
        window = self.window
        self.assertEqual(self.bar.count(), 1)
        first = window.project
        self.open(self.a)  # The empty first tab takes the file.
        self.assertEqual(self.bar.count(), 1)
        self.assertIsNot(window.project, first)
        self.open(self.b)
        self.assertEqual(self.bar.count(), 2)
        window.new_project()
        self.assertEqual((self.bar.count(), self.bar.currentIndex()), (3, 2))
        self.assertTrue(window.project.is_empty())
        self.open(self.a)  # The empty new tab is reused too; A was open in the first tab, so it is shown instead.
        self.assertEqual(self.bar.count(), 3)
        self.assertIs(window.project, window.sessions[0].project)
        self.assertEqual(self.bar.currentIndex(), 0)

    def test_same_path_activates_the_existing_tab_without_losing_work(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("data", "Misure"))
        self.type_cell(0, 1, "42")
        self.app.processEvents()
        self.wait()
        original = window.project
        self.assertTrue(original.dirty)
        self.open(self.b)
        self.open(Path(self.folder / "." / "sessione-a.alab"))  # Another spelling of the same file.
        self.assertIs(window.project, original)
        self.assertEqual(self.bar.count(), 2)
        self.assertEqual(self.cell(original, 0, 1), 42)
        self.assertTrue(original.dirty)

    def test_tab_limit_is_reported_and_leaves_tabs_alone(self):
        from trama_qt.sessions import MAX_PROJECT_TABS
        window = self.window
        self.open(self.a)
        while len(window.sessions) < MAX_PROJECT_TABS:
            window.new_project()
        self.assertFalse(window.actions["new_project"].isEnabled())
        csv = self.folder / "pieno.csv"
        csv.write_text("P,Q\n1,2\n3,4\n", encoding="utf-8")
        window.open_path(csv)  # Data fills the empty tab, so it is no longer reused for a project.
        window.open_path(self.b)
        self.assertEqual(len(window.sessions), MAX_PROJECT_TABS)
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()

    def test_invalid_path_changes_nothing(self):
        window = self.window
        self.open(self.a)
        project = window.project
        broken = self.folder / "rotto.alab"
        broken.write_text("{ non è un progetto", encoding="utf-8")
        window.open_path(broken)
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()
        self.assertEqual(self.bar.count(), 1)
        self.assertIs(window.project, project)
        self.assertEqual(window.selected, ("data", "Misure"))
        window.open_path(self.folder / "manca.alab")  # A path that does not exist.
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()
        self.assertEqual(self.bar.count(), 1)
        self.assertEqual(window.sessions.find(broken), None)

    def test_csv_import_and_text_files_work_in_the_active_tab(self):
        import pandas as pd
        window = self.window
        self.open(self.a)
        self.open(self.b)
        csv = self.folder / "extra.csv"
        pd.DataFrame({"P": [1.0, 2.0], "Q": [3.0, 4.0]}).to_csv(csv, index=False)
        window.open_path(csv)
        self.assertEqual(self.bar.count(), 2)  # Data files do not open a tab.
        self.assertIn("extra", window.project.tables)
        self.assertNotIn("extra", window.sessions[0].project.tables)
        self.assertTrue(window.project.dirty)

    # -- isolation ------------------------------------------------------------------------------------
    def test_two_projects_with_the_same_ids_stay_apart(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 0))
        self.wait()
        one = window.project
        self.open(self.b)
        two = window.project
        self.assertIsNot(one, two)
        self.assertEqual(one.runs[0].uid, two.runs[0].uid)
        self.assertEqual(window.selected, ("data", "Misure"))
        self.assertEqual(self.cell(two, 0, 1), 103)
        self.assertEqual(two.tables["Misure"].excluded, {(2, 1)})
        self.assertEqual(one.tables["Misure"].excluded, set())
        self.type_cell(0, 1, "123")
        self.wait()
        self.assertEqual(self.cell(two, 0, 1), 123)
        self.assertEqual(self.cell(one, 0, 1), 3)
        window.switch_project(window.sessions[0])
        self.assertEqual(window.selected, ("graph", 0))
        self.assertTrue(window.page.canvases)
        self.assertFalse(one.dirty)
        self.assertTrue(two.dirty)
        self.assertEqual(self.bar.tabText(1)[:1], "•")
        self.assertNotEqual(self.bar.tabText(0)[:1], "•")

    def test_undo_history_belongs_to_each_tab(self):
        window = self.window
        self.open(self.a)
        self.type_cell(0, 1, "50")
        self.wait()
        self.assertTrue(window.actions["undo"].isEnabled())
        self.open(self.b)
        self.assertFalse(window.actions["undo"].isEnabled())  # B has nothing to undo; A's edit is not B's.
        window.undo()
        self.assertEqual(self.cell(window.project, 0, 1), 103)
        window.switch_project(window.sessions[0])
        self.assertTrue(window.actions["undo"].isEnabled())
        window.undo()
        self.wait()
        self.assertEqual(self.cell(window.project, 0, 1), 3)

    def test_tab_restores_sheet_cell_and_result_tab(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 1))
        self.wait()
        self.open(self.b)
        window.sheet.setCurrentIndex(window.sheet.model().index(3, 2))
        window.new_project()
        self.assertIsNone(window.selected)
        window.switch_project(window.sessions[1])
        self.assertEqual(window.selected, ("data", "Misure"))
        self.assertEqual((window.sheet.currentIndex().row(), window.sheet.currentIndex().column()), (3, 2))
        window.switch_project(window.sessions[0])
        self.assertEqual(window.selected, ("graph", 1))

    def test_result_tab_is_restored_and_a_home_tab_holds_no_stale_widgets(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        window = self.window
        self.open(self.a)
        window.open_sheet(("result", 0))
        self.wait()
        self.assertIsNotNone(window.result_tabs)
        last = window.result_tabs.count() - 1
        window.result_tabs.setCurrentIndex(last)
        window.new_project()
        self.assertIsNone(window.result_tabs)  # The empty tab keeps nothing of the previous page.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.switch_project(window.sessions[0])  # Leaving the empty tab must not touch a deleted widget.
        self.assertEqual(window.selected, ("result", 0))
        self.assertEqual(window.result_tabs.currentIndex(), last)
        window.switch_project(window.sessions[1])
        self.assertIsNone(window.result_tabs)

    def test_a_typed_cell_lands_in_its_own_project_when_the_tab_changes(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        window.switch_project(window.sessions[0])
        self.type_cell(1, 1, "77", apply=False)  # Typed, not yet applied (it waits for the editor to close).
        # Storing it recalculates the linked graphs: the switch waits for that, the edit stays in project A.
        self.assertFalse(window.switch_project(window.sessions[1]))
        self.assertIs(window.sessions.active, window.sessions[0])
        self.wait()
        self.assertIs(window.sessions.active, window.sessions[1])
        self.assertEqual(self.bar.currentIndex(), 1)
        self.assertEqual(self.cell(window.sessions[0].project, 1, 1), 77)
        self.assertEqual(self.cell(window.sessions[1].project, 1, 1), 107)
        self.assertTrue(window.sessions[0].project.dirty)
        self.assertFalse(window.sessions[1].project.dirty)
        self.assertEqual(self.errors, [])

    def test_save_while_a_cell_is_still_being_edited(self):
        from PySide6.QtWidgets import QLineEdit

        self.open(self.a)
        sheet = self.window.sheet
        index = sheet.model().index(1, 1)
        sheet.setCurrentIndex(index)
        sheet.edit(index)
        self.app.processEvents()
        editor = sheet.indexWidget(index)
        self.assertIsInstance(editor, QLineEdit)
        editor.selectAll()
        QTest.keyClicks(editor, "77")
        QTest.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        self.wait()
        self.assertEqual(load_project(self.a)["Misure"].raw.iat[1, 1], 77)
        self.assertFalse(self.window.project.dirty)

    def test_save_as_flushes_a_cell_waiting_for_the_next_event(self):
        self.open(self.a)
        self.type_cell(1, 1, "87", apply=False)
        target = self.a.with_name("saved-copy.alab")
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            self.window.actions["save_as"].trigger()
            self.wait()
        self.assertEqual(load_project(target)["Misure"].raw.iat[1, 1], 87)
        self.assertNotEqual(load_project(self.a)["Misure"].raw.iat[1, 1], 87)

    def test_a_late_edit_from_a_closed_tab_is_not_applied_elsewhere(self):
        window = self.window
        self.open(self.a)
        stale_project = window.project
        self.open(self.b)
        before = self.cell(window.project, 0, 1)
        self.assertFalse(window.edit_cell("Misure", 0, 1, "999", project=stale_project))
        self.assertEqual(self.cell(window.project, 0, 1), before)
        self.assertFalse(window.project.dirty)

    def test_style_commits_go_to_the_project_that_drew_the_graph(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 0))
        self.wait()
        one = window.project
        run = one.runs[0]
        self.open(self.b)
        two = window.project
        window.commit_style(run, {"title": "Solo A"}, project=one)
        self.assertTrue(one.dirty)
        self.assertFalse(two.dirty)
        self.assertNotIn("title", (two.runs[0].style or {}))

    def test_info_notes_typed_before_a_tab_change_stay_in_their_project(self):
        from analisi.info import InfoSheet
        window = self.window
        self.open(self.a)
        sheet = InfoSheet.new("Note A", None)
        window.project.update_info_sheets({sheet.uid: sheet})
        window.show_sheet("info", sheet.uid)
        window.project.dirty = False
        window.info_editor.notes.setPlainText("Nota di A")  # Typed; the editor stores it after a short pause.
        self.assertEqual(window.project.info_sheets[sheet.uid].notes, "")
        self.open(self.b)  # Leaving the tab stores the note first, in the project that owns the sheet.
        self.assertEqual(window.project.info_sheets, {})
        self.assertFalse(window.project.dirty)
        first = window.sessions[0].project
        self.assertEqual(first.info_sheets[sheet.uid].notes, "Nota di A")
        self.assertTrue(first.dirty)
        window.switch_project(window.sessions[0])
        self.assertEqual(window.selected, ("info", sheet.uid))
        self.assertEqual(window.info_editor.notes.toPlainText(), "Nota di A")

    # -- save, close ----------------------------------------------------------------------------------
    def test_close_asks_only_about_the_project_involved(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        self.type_cell(0, 1, "123")
        self.wait()
        two, one = window.project, window.sessions[0].project
        with self.answer(QMessageBox.StandardButton.Cancel) as asked:
            window.actions["close_project"].trigger()
            asked.assert_called_once()
            self.assertIn("sessione-b.alab", asked.call_args.args[2])
        self.assertIs(window.project, two)
        self.assertEqual(self.bar.count(), 2)
        self.assertTrue(two.dirty)
        self.assertEqual(self.cell(window.project, 0, 1), 123)
        self.assertEqual(load_project(self.b)["Misure"].raw.iloc[0, 1], 103)
        self.assertTrue(window.save())
        self.assertEqual(load_project(self.b)["Misure"].raw.iloc[0, 1], 123)
        self.assertEqual(load_project(self.a)["Misure"].raw.iloc[0, 1], 3)
        with mock.patch.object(QMessageBox, "question") as asked:  # Clean now: closes without asking.
            window.actions["close_project"].trigger()
            asked.assert_not_called()
        self.assertEqual(self.bar.count(), 1)
        self.assertIs(window.project, one)

    def test_close_a_tab_that_is_not_active_from_its_button(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        window.switch_project(window.sessions[0])
        self.type_cell(0, 1, "11")
        self.wait()
        two = window.sessions[1].project
        with self.answer(QMessageBox.StandardButton.Cancel):
            self.bar.tabCloseRequested.emit(0)  # The tab with changes: switches to it, asks, stays.
        self.assertIs(window.sessions.active, window.sessions[0])
        self.assertEqual(self.bar.count(), 2)
        with self.answer(QMessageBox.StandardButton.Discard):
            self.bar.tabCloseRequested.emit(0)
        self.assertEqual(self.bar.count(), 1)
        self.assertIs(window.project, two)
        self.assertEqual(load_project(self.a)["Misure"].raw.iloc[0, 1], 3)

    def test_failed_save_keeps_project_selection_and_changes(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 1))
        self.wait()
        window.project.dirty = True
        project, selected = window.project, window.selected
        with self.answer(QMessageBox.StandardButton.Save), \
                mock.patch("trama_qt.project.Project.save", side_effect=OSError("disco pieno")):
            self.assertFalse(window.close_project())
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()
        self.assertIs(window.project, project)
        self.assertEqual(window.selected, selected)
        self.assertTrue(project.dirty)
        self.assertEqual(self.bar.count(), 1)

    def test_last_close_leaves_an_empty_tab_and_a_new_project_number(self):
        window = self.window
        self.open(self.a)
        number = window.project.number
        self.assertTrue(window.close_project())
        self.assertEqual(self.bar.count(), 1)
        self.assertTrue(window.project.is_empty())
        self.assertEqual(window.project.number, number)
        self.assertIsNone(window.selected)
        self.assertTrue(window.actions["close_project"].isEnabled())
        self.assertIsNone(window.sessions.find(self.a))

    def test_save_as_never_overwrites_a_project_open_in_another_tab(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        before = self.b.read_bytes()
        window.switch_project(window.sessions[0])
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(self.b), "")):
            self.assertFalse(window.save(as_new=True))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("sessione-b.alab", self.errors[0])
        self.errors.clear()
        self.assertEqual(self.b.read_bytes(), before)
        self.assertEqual(window.project.path, self.a)
        other = self.folder / "copia.alab"
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(other), "")):
            self.assertTrue(window.save(as_new=True))
        self.assertEqual(window.project.path, other)
        self.assertEqual(self.bar.tabText(0), "copia.alab")

    def test_window_close_collects_every_decision_before_losing_tabs(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        window.switch_project(window.sessions[0])
        self.type_cell(0, 1, "1")
        window.switch_project(window.sessions[1])
        self.type_cell(0, 1, "2")
        # Save for the first, Cancel for the second: nothing is saved and nothing is closed.
        answers = [QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Cancel]
        before = (self.a.read_bytes(), self.b.read_bytes())
        with mock.patch.object(QMessageBox, "question", side_effect=answers) as asked:
            self.assertFalse(window.close())
            self.assertEqual(asked.call_count, 2)
        self.assertEqual((self.a.read_bytes(), self.b.read_bytes()), before)
        self.assertEqual(self.bar.count(), 2)
        self.assertTrue(all(session.project.dirty for session in window.sessions))
        self.assertEqual(self.cell(window.sessions[0].project, 0, 1), 1)
        self.assertEqual(self.cell(window.sessions[1].project, 0, 1), 2)
        self.assertEqual(self.bar.currentIndex(), window.sessions.index(window.sessions.active))
        self.assertTrue(window.isVisible())
        # Save for both: both files are written, then the window closes.
        with self.answer(QMessageBox.StandardButton.Save):
            self.assertTrue(window.close())
        self.assertEqual(load_project(self.a)["Misure"].raw.iloc[0, 1], 1)
        self.assertEqual(load_project(self.b)["Misure"].raw.iloc[0, 1], 2)

    def test_window_close_discard_leaves_files_alone(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        self.type_cell(0, 1, "9")
        before = self.b.read_bytes()
        with self.answer(QMessageBox.StandardButton.Discard):
            self.assertTrue(window.close())
        self.assertEqual(self.b.read_bytes(), before)

    def test_window_close_stops_when_one_save_fails(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        for session in window.sessions:
            session.project.dirty = True
        with self.answer(QMessageBox.StandardButton.Save), \
                mock.patch("trama_qt.project.Project.save", side_effect=OSError("sola lettura")):
            self.assertFalse(window.close())
        self.errors.clear()
        self.assertEqual(self.bar.count(), 2)
        self.assertTrue(window.isVisible())

    # -- Inspector draft ------------------------------------------------------------------------------
    def draft_in_a(self):
        """Tab A on its graph with an Inspector draft (a new title), B open behind it."""
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 0))
        self.wait()
        self.open(self.b)
        window.switch_project(window.sessions[0])
        window.toggle_inspector()
        inspector = window.inspector
        self.assertIsNotNone(inspector)
        inspector.widgets["title"].setText("Bozza di A")
        inspector._now("title")
        self.assertTrue(inspector.has_draft)
        return inspector, window.project.runs[0].result.figure.axes[0]

    def test_inspector_draft_keeps_the_original_tab_and_draft_when_cancelled(self):
        window = self.window
        inspector, axes = self.draft_in_a()
        with self.answer(QMessageBox.StandardButton.Cancel) as asked:
            self.assertFalse(window.switch_project(window.sessions[1]))
            asked.assert_called_once()
        self.assertIs(window.sessions.active, window.sessions[0])
        self.assertIs(window.inspector, inspector)
        self.assertTrue(inspector.has_draft)
        self.assertEqual(axes.get_title(), "Bozza di A")
        self.assertEqual(self.bar.currentIndex(), 0)
        self.assertTrue(window.inspector_wanted)
        self.assertFalse(window.sessions[1].project.dirty)

    def test_inspector_draft_applied_lands_in_its_own_project(self):
        window = self.window
        inspector, axes = self.draft_in_a()
        one, two = window.sessions[0].project, window.sessions[1].project
        with self.answer(QMessageBox.StandardButton.Apply):
            self.assertTrue(window.switch_project(window.sessions[1]))
        self.assertIs(window.sessions.active, window.sessions[1])
        self.assertEqual(one.runs[0].style["title"], "Bozza di A")
        self.assertTrue(one.dirty)
        self.assertIsNone((two.runs[0].style or {}).get("title"))
        self.assertFalse(two.dirty)

    def test_inspector_draft_discarded_restores_the_confirmed_style(self):
        window = self.window
        inspector, axes = self.draft_in_a()
        one = window.sessions[0].project
        with self.answer(QMessageBox.StandardButton.Discard):
            self.assertTrue(window.switch_project(window.sessions[1]))
        self.assertNotEqual(axes.get_title(), "Bozza di A")
        self.assertIsNone((one.runs[0].style or {}).get("title"))
        self.assertFalse(one.dirty)

    def test_closing_a_tab_with_an_inspector_draft_asks_first(self):
        window = self.window
        inspector, axes = self.draft_in_a()
        with self.answer(QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close_project())
        self.assertEqual(self.bar.count(), 2)
        self.assertIs(window.inspector, inspector)

    def test_inspector_wish_is_kept_per_tab(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 0))
        self.wait()
        window.toggle_inspector()
        self.assertTrue(window.inspector_wanted)
        self.open(self.b)
        self.assertFalse(window.inspector_wanted)
        self.assertIsNone(window.inspector)
        window.switch_project(window.sessions[0])
        self.assertTrue(window.inspector_wanted)
        self.assertIsNotNone(window.inspector)

    # -- calculations ---------------------------------------------------------------------------------
    def test_busy_window_blocks_switching_opening_and_closing_but_not_cancel(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        future, control, done = self.busy()
        try:
            self.assertFalse(self.bar.isEnabled())
            for key in ("new_project", "open", "close_project", "next_project", "previous_project"):
                self.assertFalse(window.actions[key].isEnabled(), key)
            self.assertFalse(window.switch_project(window.sessions[0]))
            self.assertIs(window.sessions.active, window.sessions[1])
            self.assertFalse(window.close_project())
            self.assertEqual(self.bar.count(), 2)
            self.assertTrue(window.cancel_button.isEnabled())
            window.cancel_button.click()
            control.cancel.set.assert_called()
        finally:
            future.set_result(None)
            self.wait()
        self.assertEqual(done, [False])
        self.assertTrue(self.bar.isEnabled())
        self.assertTrue(window.actions["close_project"].isEnabled())

    def test_files_that_arrive_while_busy_open_when_the_calculation_ends(self):
        window = self.window
        self.open(self.a)
        future, _, _ = self.busy()
        window.open_path(self.b)  # A drop or the command line during a calculation.
        window.open_path(self.b)
        self.assertEqual(self.bar.count(), 1)
        self.assertIsNone(window.sessions.find(self.b))
        future.set_result(None)
        self.wait()
        self.assertEqual(self.bar.count(), 2)  # Opened once, in a tab of its own.
        self.assertTrue(window.project.path == self.b)
        self.assertEqual(window._queued, [])

    def test_a_result_never_reaches_another_tab(self):
        window = self.window
        self.open(self.a)
        first = window.sessions.active
        future, _, done = self.busy()
        self.assertIs(window.job.session, first)
        window.sessions.items.append(window.sessions.items[0].__class__(window.project.__class__(9)))
        window._sync_tabs()
        try:
            window.sessions.active = window.sessions.items[1]  # Forced, as no UI path allows it.
            future.set_result("risultato")
            self.wait()
            self.assertIs(window.sessions.active, first)  # The job's own tab is back in front before it applies.
            self.assertEqual(done, [False])
        finally:
            window.sessions.items.pop()
            window._sync_tabs()

    def test_closing_the_window_during_a_calculation_cancels_then_closes(self):
        window = self.window
        self.open(self.a)
        future, control, _ = self.busy()
        window.close()
        control.cancel.set.assert_called()
        self.assertTrue(window.isVisible())
        self.assertTrue(window._close_pending)
        future.set_result(None)
        self.wait()
        QTest.qWait(50)
        self.app.processEvents()
        self.assertFalse(window.isVisible())

    def test_cancelling_a_real_recalculation_returns_to_the_same_tab(self):
        window = self.window
        self.open(self.a)
        window.open_sheet(("graph", 0))
        self.wait()
        self.open(self.b)
        window.switch_project(window.sessions[0])
        run = window.project.runs[0]
        window.refresh_runs([run])
        self.assertIsNotNone(window.job)
        self.assertIs(window.job.session, window.sessions[0])
        window.cancel_calculation()
        self.wait()
        self.assertIs(window.sessions.active, window.sessions[0])
        self.assertEqual(self.bar.count(), 2)
        self.assertEqual(self.cell(window.sessions[1].project, 0, 1), 103)

    # -- command line and drops ----------------------------------------------------------------------
    def test_command_line_project_opens_in_the_first_tab(self):
        from trama_qt import app as trama_app
        from trama_qt.window import MainWindow
        seen = {}

        def fake_exec(*args):
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, MainWindow) and widget is not self.window and widget.isVisible():
                    seen["window"] = widget
            return 0

        language = active_language()
        self.addCleanup(set_language, language)
        with mock.patch.object(QApplication, "exec", fake_exec), \
                mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.folder / "config"),
                                               "APPDATA": str(self.folder / "config")}):
            self.assertEqual(trama_app.main(["trama", "--flag", str(self.b)]), 0)
        window = seen["window"]
        self.addCleanup(window.close)
        self.assertEqual(len(window.sessions), 1)
        self.assertEqual(window.project.path, self.b)
        self.assertEqual(window.selected, ("data", "Misure"))
        window.sessions.active.project.dirty = False

    def test_dropped_files_open_tabs(self):
        from PySide6.QtCore import QMimeData, QPointF, QUrl
        from PySide6.QtGui import QDropEvent
        window = self.window

        def drop(path):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            window.dropEvent(QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                        Qt.KeyboardModifier.NoModifier))
            self.wait()

        drop(self.a)
        drop(self.b)
        self.assertEqual(self.bar.count(), 2)
        drop(self.a)  # Already open: its tab, no duplicate.
        self.assertEqual(self.bar.count(), 2)
        self.assertEqual(window.project.path, self.a)
        other = self.folder / "nota.docx"
        other.write_text("x")
        drop(other)  # Not a project or data file: ignored.
        self.assertEqual(self.bar.count(), 2)

    # -- keyboard -------------------------------------------------------------------------------------
    def test_keyboard_switches_and_closes_tabs(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        self.assertEqual(self.bar.currentIndex(), 1)
        for action, expected in (("next_project", 0), ("next_project", 1), ("previous_project", 0)):
            window.actions[action].trigger()
            self.assertEqual(self.bar.currentIndex(), expected)
        shortcuts = {action: {sequence.toString() for sequence in window.actions[action].shortcuts()}
                     for action in ("close_project", "next_project", "previous_project", "new_project", "new_table")}
        self.assertIn("Ctrl+W", shortcuts["close_project"])
        self.assertEqual(shortcuts["next_project"], {"Ctrl+Tab"})
        self.assertIn("Ctrl+Shift+Tab", shortcuts["previous_project"])
        self.assertEqual(shortcuts["new_project"], {"Ctrl+N", "Ctrl+Shift+N"})
        self.assertEqual(shortcuts["new_table"], {"Ctrl+T"})
        window.actions["close_project"].trigger()  # Clean tab: closes without asking.
        self.assertEqual(self.bar.count(), 1)
        window.actions["next_project"].trigger()  # One tab: nothing to switch to.
        self.assertFalse(window.actions["next_project"].isEnabled())

    def test_the_sheet_is_current_after_a_tab_change(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        window.switch_project(window.sessions[0])
        self.app.processEvents()
        self.assertIsNotNone(window.sheet)
        self.assertEqual(window.sheet.model().dataset, window.project.tables["Misure"])
        self.assertIs(window.sheet.model().dataset, window.sessions[0].project.tables["Misure"])

    # -- window title and languages -------------------------------------------------------------------
    def test_title_follows_the_active_tab_and_italian_labels(self):
        window = self.window
        self.open(self.a)
        self.open(self.b)
        self.type_cell(0, 1, "5")
        self.wait()
        self.assertTrue(window.windowTitle().startswith("• "))
        self.assertIn("sessione-b.alab", window.windowTitle())
        window.switch_project(window.sessions[0])
        self.assertFalse(window.windowTitle().startswith("• "))

    def test_italian_labels(self):
        from trama_qt.window import MainWindow
        self.open(self.a)
        self.type_cell(0, 1, "5")
        set_language("it")
        window = MainWindow()
        self.addCleanup(window.close)
        window.error = lambda error: self.errors.append(str(error))
        window.open_path(self.a)
        window.project.dirty = True
        window.new_project()
        window._sync_tabs()
        bar = window.findChild(QTabBar, "projectTabs")
        self.assertEqual(bar.accessibleName(), "Progetti aperti")
        self.assertEqual(window.actions["close_project"].text(), "Chiudi progetto")
        self.assertIn("Modifiche non salvate", bar.tabToolTip(0))
        self.assertEqual(bar.tabText(0), "• sessione-a.alab")
        self.assertIn("Senza titolo", bar.tabText(1))
        for session in window.sessions:
            session.project.dirty = False


if __name__ == "__main__":
    unittest.main()
