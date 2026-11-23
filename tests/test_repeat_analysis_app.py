"""Repeat analysis on other sheets… in the classic Tk window: the menu entry, the assistant and the transaction."""
import gc
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from analisi import repeat_analysis_app
from analisi.data import project_bytes, save_project
from analisi.repeat_analysis_dialog import RepeatDialog
from analisi.repeat_analysis_smoke import MAPPINGS, fixture_tables
from analisi.repeat_analysis_text import t
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import TkCase


class RepeatAppCase(TkCase):
    def setUp(self):
        import tramastat
        gc.collect()  # Tk variables left by earlier tests are freed on this thread, not on a worker.
        self.tmp = tempfile.TemporaryDirectory()
        prefs = Path(self.tmp.name) / "prefs.json"
        save_theme(prefs, "standard")
        self.root.deiconify()
        with patch.object(tramastat, "config_path", return_value=prefs):
            self.app = tramastat.App(self.root)
        self.errors = []
        self.app.error = lambda error: self.errors.append(str(error))
        path = Path(self.tmp.name) / "project.alab"
        save_project(path, fixture_tables())
        self.app.import_file(path)
        self.root.update()
        self.source = next(i for i, run in enumerate(self.app.runs) if run.reference == ("Original", 0))
        self.app.open_sheet(("result", self.source))
        self.wait()

    def tearDown(self):
        self.wait()
        self.app._clear("")
        self.app.worker.shutdown(wait=True)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.withdraw()
        self.tmp.cleanup()
        del self.app
        gc.collect()  # The old App and assistants hold Tk variables: free them here, never on a later worker.

    def wait(self):
        until = time.monotonic() + 20
        while self.app.pending is not None and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        for _ in range(4):
            self.root.update()

    def assistant(self, *actions, during=None):
        """Open the command from the Analyze menu; each action drives one opening of the assistant."""
        queue, seen, failures = list(actions), [], []
        original = RepeatDialog.__init__

        def opened(dialog, *args, **kwargs):
            seen.append(dialog)
            action = queue.pop(0) if queue else None

            def drive():
                try:
                    if action is None:
                        raise AssertionError("unexpected assistant")
                    dialog.update()
                    if action(dialog):
                        dialog.ok()
                        return
                except BaseException as error:  # noqa: BLE001 - re-raised in the test.
                    failures.append(error)
                if dialog.winfo_exists():
                    dialog.cancel()

            self.root.after(50, drive)
            original(dialog, *args, **kwargs)

        with patch.object(RepeatDialog, "__init__", opened):
            popup, index = self.app.menu_entries["Analyze", "Repeat analysis on other sheets…"]
            popup.invoke(index)
            if during is not None and self.app.pending is not None:
                during()
            self.wait()
        if failures:
            raise failures[0]
        self.assertEqual(queue, [], "an assistant did not open")
        return len(seen)

    def choose(self, dialog, targets):
        dialog.next_button.invoke()
        for title in targets:
            dialog.toggle(title, True)
            for column, chosen in MAPPINGS[title].items():
                dialog.set_column(title, column, chosen)
        dialog.next_button.invoke()
        self.assertEqual(dialog.page, 2)
        return True


class RepeatAppTests(RepeatAppCase):
    def test_menu_label_and_refusal_without_a_result(self):
        popup, index = self.app.menu_entries["Analyze", "Repeat analysis on other sheets…"]
        self.assertEqual(popup.entrycget(index, "label"), t("command"))
        self.app.open_sheet(("data", "Lot B"))
        self.root.update()
        self.app.repeat_analysis()
        self.assertEqual(self.errors, [t("select")])

    def test_steps_refusals_and_duplicate(self):
        def drive(dialog):
            self.assertTrue(dialog.follow_var.get())
            self.assertIn("Linear regression", dialog.summary.get("1.0", "end"))
            dialog.follow_var.set(False)
            dialog._follow_changed()
            self.assertNotIn("Linear regression of", dialog.summary.get("1.0", "end"))
            dialog.follow_var.set(True)
            dialog._follow_changed()
            dialog.next_button.invoke()
            self.assertIn("Original", dialog.refused)
            dialog.toggle("Original")
            self.assertEqual(dialog.assistant.selected, [])
            self.assertTrue(dialog.next_button.instate(["disabled"]))
            dialog.toggle("Lot B", True)
            self.assertEqual(dialog.boxes["X"].get(), t("choose"))  # Different names are never proposed.
            dialog.set_column("Lot B", "X", "Tempo")
            dialog.set_column("Lot B", "Y", "Tempo")
            self.assertTrue(dialog.next_button.instate(["disabled"]))
            self.assertIn("chosen twice", dialog.status_var.get())
            dialog.next_button.invoke()  # Blocked: still on the sheets.
            self.assertEqual(dialog.page, 1)
            dialog.set_column("Lot B", "Y", "Segnale")
            self.assertEqual(dialog.status_var.get(), t("ready"))
            dialog.next_button.invoke()
            self.assertIn("Tempo", dialog.preview.get("1.0", "end"))
            dialog.back_button.invoke()
            self.assertEqual(dialog.assistant.columns["Lot B"], {"X": "Tempo", "Y": "Segnale"})
            return False

        count = len(self.app.runs)
        self.assistant(drive)
        self.assertEqual(len(self.app.runs), count)
        self.assertEqual(self.errors, [])

    def test_copies_are_added_linked_and_calculated(self):
        self.assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]))
        self.assertEqual(self.errors, [])
        for title, slope in (("Lot B", 2.), ("Lot C", 5.)):
            parent = next(run for run in self.app.runs if run.reference == (title, 0))
            child = next(run for run in self.app.runs if run.reference == (title, 1))
            self.assertEqual(child.source.analysis_id, parent.uid)
            self.assertAlmostEqual(child.result.tables["Regression"].loc["Slope", "Value"], slope)
        self.assertTrue(self.app.dirty)
        self.assertEqual(self.app.runs[self.app.selected[1]].reference, ("Lot B", 0))

    def test_cancel_failure_and_change_leave_the_project_unchanged(self):
        before, count = project_bytes(self.app.tables), len(self.app.runs)
        self.assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]), during=self.app.cancel_calculation)
        self.assertEqual((project_bytes(self.app.tables), len(self.app.runs)), (before, count))
        self.assertEqual(self.app.status.get(), t("cancelled"))
        notices = []

        def reopened(dialog):
            notices.append(dialog.banner_var.get())
            self.assertEqual(dialog.page, 1)
            self.assertEqual(dialog.assistant.selected, ["Lot B", "Short"])
            return False

        self.assistant(lambda dialog: self.choose(dialog, ["Lot B", "Short"]), reopened)
        self.assertIn("Short", notices[0])
        self.assertEqual((project_bytes(self.app.tables), len(self.app.runs)), (before, count))

        def change():
            self.app.tables["Lot C"].raw.iat[0, 1] = 4.5

        self.assistant(lambda dialog: self.choose(dialog, ["Lot B", "Lot C"]), during=change)
        self.assertEqual(self.errors, [t("changed")])
        self.assertEqual(len(self.app.runs), count)
        self.assertFalse(self.app.tables["Lot B"].analyses)

    def test_closed_project_receives_nothing(self):
        count = len(self.app.runs)
        projects = []

        def switch():
            projects.append(self.app.active_project)
            self.app.active_project = object()  # Another project is shown when the copies are ready.

        with patch.object(repeat_analysis_app, "apply_repeat") as apply:
            try:
                self.assistant(lambda dialog: self.choose(dialog, ["Lot B"]), during=switch)
            finally:
                self.app.active_project = projects[0]
        apply.assert_not_called()
        self.assertEqual(len(self.app.runs), count)

    def test_preparation_failure_reopens_with_the_same_choices(self):
        def reopened(dialog):
            self.assertEqual(dialog.page, 1)
            self.assertEqual(dialog.assistant.columns["Lot B"], MAPPINGS["Lot B"])
            self.assertIn("Fixture preparation error", dialog.banner_var.get())
            return False

        with patch.object(repeat_analysis_app, "prepare_job", side_effect=ValueError("Fixture preparation error")):
            self.assistant(lambda dialog: self.choose(dialog, ["Lot B"]), reopened)
        self.assertFalse(self.app.tables["Lot B"].analyses)
