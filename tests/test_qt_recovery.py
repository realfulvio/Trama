"""Recovery copies in the Qt window: when copies are taken, what they hold, how saves and closes clear them, and
File → Recover projects… after a window that did not close normally.

Offscreen like ``test_qt_projects``. The clock is injected (``tick`` is called by the test, never by a timer) and
the profile is a temporary folder, so nothing touches the user's preferences. A crashed window is simulated by
dropping its lease; the real crash of a separate process is in ``trama_qt/recovery_drill.py``.
"""
from dataclasses import replace
import json
from pathlib import Path
from shutil import copy2
import tempfile
import threading
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "qt_recovery"
TABLE = "Calibrazione $ <β>"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RecoveryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-recovery", "-platform", "offscreen"])
        from trama_qt import theme
        theme.load_fonts()
        theme.apply(cls.app)

    def setUp(self):
        self.language = active_language()
        set_language("en")
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.root = self.folder / "profile" / "recovery"
        self.saved = self.folder / "misure-salvate.alab"
        copy2(DATA / "misure-salvate.alab", self.saved)
        self.original = self.saved.read_bytes()
        self.clock = Clock()
        self.windows = []
        self.window = self.new_window()

    def controller(self, **options):
        from trama_qt.recovery import RecoveryController
        options.setdefault("interval", 30)
        return RecoveryController(self.root, clock=self.clock, tick_ms=3_600_000, heartbeat_ms=3_600_000, **options)

    def new_window(self, controller=None):
        from trama_qt.window import MainWindow
        window = MainWindow(recovery=controller or self.controller())
        window.resize(1024, 700)
        window.errors = []
        window.error = lambda error, window=window: window.errors.append(str(error))
        window.show()
        self.windows.append(window)
        self.addCleanup(self._close, window)
        self.app.processEvents()
        return window

    def _close(self, window):
        if window.recovery is not None and window.recovery.closed:
            return
        for session in window.sessions:
            session.project.dirty = False
        window.job = None
        window.timer.stop()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    # -- helpers ---------------------------------------------------------------------------------------------
    def wait_job(self, window=None, timeout=30):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job)

    def settle(self, window=None):
        """Let the background writes finish and their outcome reach the window."""
        window = window or self.window
        window.recovery.wait()
        self.app.processEvents()

    def advance(self, seconds, window=None):
        window = window or self.window
        window.recovery.tick()
        self.clock.now += seconds
        window.recovery.tick()
        self.settle(window)

    def open(self, path, window=None):
        window = window or self.window
        window.open_path(path)
        self.wait_job(window)

    def edit_cell(self, row, column, text, window=None):
        window = window or self.window
        title = next(iter(window.project.tables))
        window.edit_cell(title, row, column, text)
        self.wait_job(window)

    def store(self):
        from trama_qt.recovery_store import RecoveryStore
        return RecoveryStore(self.root)

    def copy_of(self, project):
        """The project a recovery copy holds, read back with the ordinary .alab reader."""
        from trama_qt.project import Project
        path = self.folder / f"read-{project.recovery_key}.alab"
        path.write_bytes(self.store().read_snapshot(project.recovery_key))
        loaded = Project()
        loaded.load(path)
        return loaded

    def crash(self, window):
        """What a killed process leaves: copies on disk, a lease nobody renews (here: removed)."""
        controller = window.recovery
        controller.wait()
        controller.closed = True
        controller.timer.stop()
        controller.heartbeat.stop()
        controller.queue.shutdown(wait=True)
        controller.leases.release(controller.owner)
        for session in window.sessions:
            session.project.dirty = False
        window.recovery = None
        window.close()

    # -- what is copied, and when ----------------------------------------------------------------------------
    def test_confirmed_changes_are_copied_after_the_interval_and_read_back(self):
        from analisi.presentation import Layout
        window = self.window
        self.open(self.saved)
        project = window.project
        self.edit_cell(4, 1, "15")
        window.project.toggle_exclusion(TABLE, {(1, 1)})
        sheet = next(iter(project.info_sheets.values()))
        project.change_info(replace(sheet, notes="Nota confermata prima dell’interruzione."))
        window.open_sheet(("graph", 0))
        self.wait_job()
        run = project.runs[0]
        project.put_layout(Layout("Pannello", 1, [run.reference]))
        window.recovery.tick()
        self.clock.now += 29
        window.recovery.tick()
        self.settle()
        self.assertEqual(self.store().list_snapshots(), [])  # Changes are grouped until the interval ends.
        self.clock.now += 1
        window.recovery.tick()
        self.settle()
        copy = self.copy_of(project)
        raw = copy.tables[TABLE].raw
        self.assertEqual(float(raw.iloc[4, 1]), 15.0)
        self.assertIn((1, 1), copy.tables[TABLE].excluded)
        self.assertEqual(next(iter(copy.info_sheets.values())).notes, "Nota confermata prima dell’interruzione.")
        self.assertEqual(len(copy.layouts), 1)
        self.assertEqual(copy.tables[TABLE].analyses, project.tables[TABLE].analyses)
        self.assertEqual(self.saved.read_bytes(), self.original)  # The original is never written.
        self.assertEqual(project.path, self.saved)  # A copy does not change the project's file or state.
        self.assertTrue(project.dirty)
        self.assertIn("Last recovery copy", window.recovery.label.text())

    def test_no_rewrite_without_new_changes_and_one_copy_per_interval(self):
        self.open(self.saved)
        self.edit_cell(0, 1, "2")
        writes = []
        store = self.window.recovery.store
        original = store.write_snapshot

        def counting(*args, **options):
            writes.append(args[1])
            return original(*args, **options)

        with mock.patch.object(store, "write_snapshot", side_effect=counting):
            self.advance(30)
            self.edit_cell(0, 1, "3")
            self.advance(10)
            self.edit_cell(0, 1, "4")
            self.advance(10)
            self.assertEqual(writes, [1])  # The second burst waits for its own interval.
            self.advance(30)
            self.assertEqual(writes, [1, 2])
            for _ in range(3):
                self.advance(30)  # The data stays still for several intervals: nothing is rewritten.
            self.assertEqual(writes, [1, 2])
        self.assertEqual(float(self.copy_of(self.window.project).tables[TABLE].raw.iloc[0, 1]), 4.0)

    def test_inactive_tab_is_copied_and_same_titles_keep_their_identity(self):
        other_folder = self.folder / "altra"
        other_folder.mkdir()
        twin = other_folder / self.saved.name
        copy2(self.saved, twin)
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "7")
        self.open(twin)
        self.edit_cell(0, 1, "8")
        first, second = (session.project for session in window.sessions)
        self.assertEqual(first.title, second.title)
        self.assertIs(window.project, second)
        self.advance(30)
        snapshots = self.store().list_snapshots()
        self.assertEqual({item["session_key"] for item in snapshots}, {first.recovery_key, second.recovery_key})
        self.assertEqual(float(self.copy_of(first).tables[TABLE].raw.iloc[0, 1]), 7.0)
        self.assertEqual(float(self.copy_of(second).tables[TABLE].raw.iloc[0, 1]), 8.0)
        sources = {item["source"] for item in snapshots}
        self.assertEqual(sources, {str(self.saved), str(twin)})

    def test_copy_does_not_wait_for_a_running_recalculation(self):
        window = self.window
        self.open(self.saved)
        self.edit_cell(4, 1, "21")
        window.job = mock.Mock()  # A recalculation that has not finished.
        try:
            self.advance(30)
        finally:
            window.job = None
        copy = self.copy_of(window.project)
        self.assertEqual(float(copy.tables[TABLE].raw.iloc[4, 1]), 21.0)
        self.assertEqual(copy.tables[TABLE].analyses, window.project.tables[TABLE].analyses)

    def test_untitled_project_is_copied(self):
        window = self.window
        window.new_table()
        self.edit_cell(0, 0, "42")
        self.advance(30)
        [record] = self.store().list_snapshots()
        self.assertIsNone(record["source"])
        self.assertEqual(record["title"], window.project.title)

    def test_inspector_draft_is_not_copied(self):
        window = self.window
        self.open(self.saved)
        window.open_sheet(("graph", 0))
        self.wait_job()
        window.project.dirty = True  # A change, so the project is copied at all.
        window.toggle_inspector()
        inspector = window.inspector
        self.assertIsNotNone(inspector)
        inspector.widgets["title"].setText("Bozza")
        inspector._now("title")
        self.assertTrue(inspector.has_draft)
        self.advance(30)
        copy = self.copy_of(window.project)
        self.assertNotEqual((copy.tables[TABLE].graph_styles.get(0) or {}).get("title"), "Bozza")
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Apply):
            self.assertTrue(window.settle_graph_draft())
        self.advance(30)
        copy = self.copy_of(window.project)
        self.assertEqual(copy.tables[TABLE].graph_styles[0]["title"], "Bozza")  # Confirmed: now it is copied.

    # -- saves, closes and late writers ----------------------------------------------------------------------
    def test_save_clears_covered_copies_and_new_changes_get_new_ones(self):
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        self.advance(30)
        project = window.project
        self.assertEqual(len(self.store().list_snapshots()), 1)
        self.assertTrue(window.save())
        self.settle()
        self.assertEqual(self.store().list_snapshots(), [])
        self.advance(60)
        self.assertEqual(self.store().list_snapshots(), [])  # Saved: nothing to protect.
        self.edit_cell(0, 1, "6")
        self.advance(30)
        [record] = self.store().list_snapshots()
        self.assertEqual(record["generation"], project.recovery_generation)

    def test_close_discard_removes_only_that_tab_and_cancel_keeps_all(self):
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        window.new_project()
        window.new_table()
        self.edit_cell(0, 0, "1")
        first, second = (session.project for session in window.sessions)
        self.advance(30)
        self.assertEqual(len(self.store().list_snapshots()), 2)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close_project(window.sessions[0]))
        self.settle()
        self.assertEqual(len(self.store().list_snapshots()), 2)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(window.close_project(window.sessions[0]))
        self.settle()
        self.assertEqual([item["session_key"] for item in self.store().list_snapshots()], [second.recovery_key])
        self.assertNotEqual(first.recovery_key, second.recovery_key)

    def test_late_serialisation_cannot_bring_back_a_saved_or_discarded_copy(self):
        from trama_qt.recovery_store import durable_write
        gate, entered = threading.Event(), threading.Event()

        def slow(path, data):
            entered.set()
            gate.wait(10)
            durable_write(path, data)

        window = self.new_window(self.controller(write_bytes=slow))
        self.open(self.saved, window)
        self.edit_cell(0, 1, "5", window)
        window.recovery.tick()
        self.clock.now += 30
        window.recovery.tick()  # The copy is being written (slowly) in the background...
        self.assertTrue(entered.wait(5))
        window.recovery.capture(window.project)  # ...and one more is queued behind it.
        project = window.project
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(window.close_project())  # Discard while the write is still on the disk.
        gate.set()
        window.recovery.wait()
        self.app.processEvents()
        with self.assertRaises(FileNotFoundError):
            self.store().read_snapshot(project.recovery_key)
        self.assertEqual([p.name for p in self.root.iterdir() if p.is_file()], [])

    def test_save_while_writing_keeps_nothing_older(self):
        from trama_qt.recovery_store import durable_write
        gate, entered = threading.Event(), threading.Event()

        def slow(path, data):
            if not entered.is_set():
                entered.set()
                gate.wait(10)
            durable_write(path, data)

        window = self.new_window(self.controller(write_bytes=slow))
        self.open(self.saved, window)
        self.edit_cell(0, 1, "5", window)
        window.recovery.capture(window.project)
        self.assertTrue(entered.wait(5))
        window.recovery.capture(window.project)
        self.assertTrue(window.save())
        gate.set()
        self.settle(window)
        self.assertEqual(self.store().list_snapshots(), [])

    def test_preference_off_writes_nothing(self):
        window = self.window
        window.recovery.configure(False, 30)
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        self.advance(120)
        self.assertEqual(self.store().list_snapshots(), [])
        self.assertIn("off", window.recovery.label.text())
        window.recovery.configure(True, 15)
        self.advance(15)
        self.assertEqual(len(self.store().list_snapshots()), 1)

    def test_settings_dialog_saves_preference(self):
        from trama_qt.recovery import RecoverySettingsDialog
        from trama_qt.recovery_store import load_settings
        controller = self.window.recovery
        controller.settings_path = self.folder / "profile" / "preferences.json"
        dialog = RecoverySettingsDialog(controller, self.window)
        dialog.enabled.setChecked(False)
        dialog.interval.setCurrentIndex(dialog.interval.findData(60))
        dialog.accept()
        self.assertEqual(load_settings(controller.settings_path), (False, 60))
        self.assertEqual((controller.enabled, controller.interval), (False, 60))
        dialog.deleteLater()

    def test_write_failure_keeps_last_copy_and_reports_once(self):
        import errno
        failing = [False]
        from trama_qt.recovery_store import durable_write

        def disk(path, data):
            if failing[0]:
                raise OSError(errno.ENOSPC, "No space left on device")
            durable_write(path, data)

        window = self.new_window(self.controller(write_bytes=disk))
        self.open(self.saved, window)
        self.edit_cell(0, 1, "5", window)
        self.advance(30, window)
        before = self.store().read_snapshot(window.project.recovery_key)
        last = window.recovery.label.text()
        self.assertIn("Last recovery copy", last)
        failing[0] = True
        messages = []
        window.status = lambda text: messages.append(str(text))
        for value in ("6", "7", "8"):
            self.edit_cell(0, 1, value, window)
            self.advance(30, window)
        self.assertEqual(self.store().read_snapshot(window.project.recovery_key), before)
        label = window.recovery.label.text()
        self.assertIn("failed", label)
        self.assertIn(last.split()[-1], label)  # The time of the last good copy stays visible.
        self.assertEqual(sum("could not be written" in message for message in messages), 1)
        failing[0] = False
        self.advance(30, window)
        self.assertIn("Last recovery copy", window.recovery.label.text())
        self.assertEqual(float(self.copy_of(window.project).tables[TABLE].raw.iloc[0, 1]), 8.0)

    def test_limit_pauses_copies_without_deleting(self):
        from trama_qt import recovery_store
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        with mock.patch.object(recovery_store, "MAX_SNAPSHOT_BYTES", 10):
            self.advance(30)
        self.assertEqual(self.store().list_snapshots(), [])
        self.assertIn("paused", window.recovery.label.text())
        self.advance(30)  # Retried at the next interval once the limit allows it.
        self.assertEqual(len(self.store().list_snapshots()), 1)
        self.assertNotIn("paused", window.recovery.label.text())

    # -- recovering --------------------------------------------------------------------------------------------
    def crashed_with_two_copies(self):
        """Window 1 had the saved project changed and an untitled project, then stopped without closing."""
        window = self.window
        self.open(self.saved)
        self.edit_cell(4, 1, "15")
        window.new_project()
        window.new_table()
        self.edit_cell(0, 0, "99")
        self.advance(30)
        keys = [session.project.recovery_key for session in window.sessions]
        self.assertEqual(len(self.store().list_snapshots()), 2)
        self.crash(window)
        return keys

    def test_recovered_project_can_still_offer_the_moved_source_file(self):
        from analisi.source_link import locate
        from tests.test_source_link import DATA as SOURCE_DATA, link_file

        original = self.folder / "Original"
        original.mkdir()
        source = original / "data.csv"
        copy2(SOURCE_DATA / "iniziale.csv", source)
        project, title = link_file(source)
        project.save(original / "study.alab")
        moved = original.rename(self.folder / "Moved")
        self.open(moved / "study.alab")
        self.edit_cell(0, 2, "99")
        self.advance(30)
        self.crash(self.window)
        fresh = self.new_window()
        recovery = fresh.recovery
        [record] = recovery.store.list_snapshots()
        restored = recovery.load(record, 1)
        self.assertEqual(restored.tables[title].raw.iat[0, 2], 99)
        self.assertEqual(locate(restored.tables[title].source_link, restored.path),
                         ((moved / "data.csv").resolve(), True))

    def test_recover_one_defer_other_then_reopen_from_file(self):
        from trama_qt.recovery import RecoveryDialog
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        self.settle(window)
        self.assertIsNotNone(window.recovery.notice)  # The start-up notice.
        self.assertIn("2 recovery copies", window.recovery.notice.findChild(QLabel).text())
        dialog = RecoveryDialog(window.recovery, window)
        self.assertEqual(dialog.list.topLevelItemCount(), 2)
        states = {dialog.list.topLevelItem(i).text(2) for i in range(2)}
        self.assertEqual(states, {"Unchanged", "Never saved"})
        saved_record = next(record for record in dialog.records if record["source"])
        window.recovery.recover([saved_record])
        dialog.deleteLater()
        project = window.project
        self.assertEqual(project.recovery_key, keys[0])
        self.assertTrue(project.dirty)
        self.assertIsNone(project.path)
        self.assertIn("(recovered)", project.title)
        self.assertEqual(float(project.tables[TABLE].raw.iloc[4, 1]), 15.0)
        self.assertEqual(self.saved.read_bytes(), self.original)
        self.assertEqual(window.errors, [])
        # The original opens in its own tab beside the copy.
        self.open(self.saved, window)
        self.assertEqual(len(window.sessions), 2)
        self.assertEqual(float(window.project.tables[TABLE].raw.iloc[4, 1]), 9.0)
        # The deferred copy is still offered (and the recovered one, open in a tab, is not).
        offered, problems, others = window.recovery.offered()
        self.assertEqual([record["session_key"] for record in offered], [keys[1]])
        def choose_all(dialog):
            dialog.list.selectAll()
            dialog.accept()
            return RecoveryDialog.DialogCode.Accepted

        with mock.patch.object(RecoveryDialog, "exec", choose_all):
            window.recover_projects()
        self.assertEqual(len(window.sessions), 3)
        self.assertEqual(window.project.recovery_key, keys[1])
        self.assertEqual(float(next(iter(window.project.tables.values())).raw.iloc[0, 0]), 99.0)

    def test_save_as_cancel_keeps_copy_then_save_clears_it(self):
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        offered = window.recovery.offered()[0]
        window.recovery.recover([record for record in offered if record["session_key"] == keys[0]])
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")) as asked:
            self.assertFalse(window.save())
        suggested = asked.call_args[0][2]
        self.assertEqual(Path(suggested).name, "misure-salvate (recovered).alab")
        self.assertEqual(Path(suggested).parent, self.saved.parent)
        self.settle(window)
        self.assertEqual(self.store().record(keys[0])["owner"], window.recovery.owner)
        target = self.folder / "nuovo.alab"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            self.assertTrue(window.save())
        self.settle(window)
        with self.assertRaises(FileNotFoundError):
            self.store().read_snapshot(keys[0])
        self.assertEqual(self.store().read_snapshot(keys[1]) is not None, True)  # The other copy is untouched.
        self.assertEqual(self.saved.read_bytes(), self.original)
        self.assertEqual(window.project.title, "nuovo.alab")

    def test_recovered_project_interrupted_again_keeps_newest_generation(self):
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        record = next(record for record in window.recovery.offered()[0] if record["session_key"] == keys[0])
        window.recovery.recover([record])
        self.advance(60, window)
        self.assertEqual(self.store().record(keys[0])["generation"], record["generation"])  # Nothing new yet.
        self.edit_cell(3, 1, "33", window)
        self.advance(30, window)
        self.assertEqual(self.store().record(keys[0])["generation"], record["generation"] + 1)
        self.crash(window)
        third = self.new_window()
        offered = {item["session_key"]: item for item in third.recovery.offered()[0]}
        self.assertEqual(set(offered), set(keys))
        third.recovery.recover([offered[keys[0]]])
        self.assertEqual(float(third.project.tables[TABLE].raw.iloc[3, 1]), 33.0)
        self.assertEqual(third.project.title.count("(recovered)"), 1)

    def test_discard_of_recovered_copy_removes_it(self):
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        record = next(record for record in window.recovery.offered()[0] if record["session_key"] == keys[0])
        window.recovery.recover([record])
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close_project())
        self.settle(window)
        self.assertIsNotNone(self.store().record(keys[0]))
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(window.close_project())
        self.settle(window)
        with self.assertRaises(FileNotFoundError):
            self.store().record(keys[0])

    def test_changed_original_and_damaged_copy_in_the_dialog(self):
        from trama_qt.recovery import RecoveryDialog
        keys = self.crashed_with_two_copies()
        self.saved.write_bytes(self.original.replace(b"SINT-01", b"SINT-02"))  # Changed outside Trama.
        reference = self.root / f"{keys[1]}.json"
        reference.write_text(reference.read_text(encoding="utf-8")[:-20], encoding="utf-8")  # Damaged index.
        window = self.new_window()
        dialog = RecoveryDialog(window.recovery, window)
        self.assertEqual(dialog.list.topLevelItemCount(), 1)
        self.assertEqual(dialog.list.topLevelItem(0).text(2), "Changed on disk")
        self.assertEqual([entry["session_key"] for entry in dialog.selected_records()], [keys[0]])
        self.assertTrue(dialog.recover_button.isEnabled())
        self.assertTrue(dialog.warning.isVisibleTo(dialog))
        self.assertIn("changed on disk", dialog.warning.text())
        self.assertTrue(dialog.damaged.isVisibleTo(dialog))
        self.assertIn("(1)", dialog.damaged.text())
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.delete_damaged()
        self.assertTrue(reference.exists())
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.delete_damaged()
        self.assertFalse(reference.exists())
        dialog.accept()
        window.recovery.recover(dialog.chosen)
        self.assertEqual(window.project.recovery_key, keys[0])
        self.assertEqual(self.saved.read_bytes(), self.original.replace(b"SINT-01", b"SINT-02"))
        dialog.deleteLater()

    def test_delete_copy_needs_explicit_choice(self):
        from trama_qt.recovery import RecoveryDialog
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        dialog = RecoveryDialog(window.recovery, window)
        dialog.list.selectAll()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.delete_selected()
        self.assertEqual(len(self.store().list_snapshots()), 2)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.delete_selected()
        self.assertEqual(self.store().list_snapshots(), [])
        self.assertTrue(keys)
        dialog.deleteLater()

    def test_tab_limit_does_not_consume_copies(self):
        from trama_qt.sessions import MAX_PROJECT_TABS
        keys = self.crashed_with_two_copies()
        window = self.new_window()
        messages = []
        window.status = lambda text: messages.append(str(text))
        for _ in range(MAX_PROJECT_TABS - 1):
            window.new_table()
            window.new_project()
        window.new_table()
        self.assertTrue(window.sessions.full())
        offered = window.recovery.offered()[0]
        self.assertEqual(window.recovery.recover(offered), 0)
        self.assertTrue(any("Close a project" in message for message in messages))
        self.assertEqual({record["session_key"] for record in self.store().list_snapshots()}, set(keys))
        # One tab freed: one copy opens, the other stays for later.
        for session in window.sessions:
            session.project.dirty = False
        window.close_project(window.sessions[0])
        self.assertEqual(window.recovery.recover(window.recovery.offered()[0]), 1)
        self.assertEqual(len(window.recovery.offered()[0]), 1)

    def test_second_window_neither_offers_nor_deletes_live_copies(self):
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        self.advance(30)
        other = self.new_window()
        offered, problems, others = other.recovery.offered()
        self.assertEqual((offered, problems, others), ([], [], 1))
        self.assertIsNone(other.recovery.notice)
        other.recovery.store.sweep(alive=other.recovery.leases.alive)
        self.assertEqual(len(self.store().list_snapshots()), 1)
        self.assertNotEqual(other.recovery.owner, window.recovery.owner)

    def test_normal_close_leaves_no_copies(self):
        window = self.window
        self.open(self.saved)
        self.edit_cell(0, 1, "5")
        self.advance(30)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(window.close())
        self.assertEqual([p.name for p in self.root.iterdir() if p.is_file()], [])
        self.assertEqual(list((self.root / "leases").iterdir()), [])

    def test_italian_texts(self):
        from trama_qt.recovery import RecoveryDialog, r
        keys = self.crashed_with_two_copies()
        set_language("it")
        window = self.new_window()
        self.assertEqual(window.actions["recover"].text(), "Recupera progetti…")
        dialog = RecoveryDialog(window.recovery, window)
        self.assertEqual(dialog.windowTitle(), "Recupera progetti")
        self.assertEqual({dialog.list.topLevelItem(i).text(2) for i in range(2)}, {"Immutato", "Mai salvato"})
        window.recovery.recover([record for record in dialog.records if record["session_key"] == keys[0]])
        self.assertIn("(recuperato)", window.project.title)
        self.assertTrue(r("notice", count=2).startswith("Trama ha trovato 2"))
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
