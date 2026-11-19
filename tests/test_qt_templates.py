"""Analysis templates in the Qt window: Save as analysis template… and New project from template….

Offscreen like ``test_qt_projects``. The dialogs are driven through ``QDialog.exec`` with the real widgets: the
confirmation, the mapping assistant (errors with focus), Cancel, tabs, the worker and the first calculation.
"""
from contextlib import contextmanager
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
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "qt_templates"
SENTINEL = "SOLO_ORIGINALE_Ω"


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class TemplateWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-templates", "-platform", "offscreen"])
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
        for name in ("progetto-originale.alab", "nuova-calibrazione.csv", "nuovo-controllo.csv"):
            copy2(DATA / name, self.folder / name)
        copy2(DATA / "nuova-calibrazione.csv", self.folder / "Campioni nuovi.csv")
        copy2(DATA / "nuovo-controllo.csv", self.folder / "Controlli nuovi.csv")
        self.mapping = json.loads((DATA / "mappatura.json").read_text(encoding="utf-8"))
        self.original = self.folder / "progetto-originale.alab"
        self.window = MainWindow()
        self.window.resize(1024, 700)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        if self.window.job is not None:
            self.window.job.control.cancel.set()
            self.settle(expect_errors=None, timeout=10)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    # -- helpers --------------------------------------------------------------------------------------
    def settle(self, *, expect_errors=False, timeout=60):
        """Until no job runs and none is about to start (a read opens the assistant on the next turn)."""
        end, quiet = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            self.app.processEvents()
            quiet = quiet + 1 if self.window.job is None else 0
            if quiet >= 4:
                break
            time.sleep(0.02)
        self.assertIsNone(self.window.job, "calculation still running")
        if expect_errors is False:
            self.assertEqual(self.errors, [])

    @contextmanager
    def dialogs(self, *handlers):
        from trama_qt import templates
        queue = list(handlers)
        seen, failures = [], []

        def exec_(dialog):
            # The assistant opens from a Qt timer, where an exception would only be printed: keep it for the test.
            try:
                self.assertIsInstance(dialog, (templates.SaveTemplateDialog, templates.TemplateWizard))
                self.assertTrue(queue, f"unexpected {type(dialog).__name__}")
                dialog.show()
                self.app.processEvents()
                seen.append(dialog)
                if queue.pop(0)(dialog):
                    return QDialog.DialogCode.Accepted
            except BaseException as error:  # noqa: BLE001 - re-raised below, in the test.
                failures.append(error)
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with mock.patch.object(QDialog, "exec", exec_):
            yield seen
        if failures:
            raise failures[0]
        self.assertEqual(queue, [], "a dialog did not open")

    def open(self, path):
        self.window.open_path(path)
        self.settle()

    def save_template(self, target=None):
        target = target or self.folder / "procedura.tramatpl"

        def save(dialog):
            dialog.file.setText(str(target))
            dialog.accept()
            return dialog.path is not None

        with self.dialogs(save):
            self.window.save_template()
        self.settle()
        return target

    def sources_project(self):
        self.window.new_project()
        for name in ("Campioni nuovi", "Controlli nuovi"):
            self.window.open_path(self.folder / f"{name}.csv")
            self.settle()
        return self.window.project

    @staticmethod
    def assign(wizard, mapping):
        for table, (source, columns) in mapping.items():
            box = wizard.source_boxes[table]
            box.setCurrentIndex(box.findData(source))
            for column, chosen in columns.items():
                box = wizard.column_boxes[table, column]
                box.setCurrentIndex(box.findData(chosen))

    def apply(self, template, mapping=None):
        mapping = mapping or self.mapping

        def ok(wizard):
            self.assign(wizard, mapping)
            wizard.accept()
            return wizard.mapping is not None

        with self.dialogs(ok):
            self.window.new_from_template(template)
            self.settle(expect_errors=None)
        return self.window.project

    @staticmethod
    def slopes(project):
        return [round(float(run.result.tables["Regression"].loc["Slope", "Value"]), 9)
                for run in project.runs if run.method == "Linear regression" and run.result is not None]

    # -- save -----------------------------------------------------------------------------------------
    def test_save_writes_metadata_only_and_leaves_the_project_alone(self):
        self.open(self.original)
        self.window.open_sheet(("layout", 0))
        self.settle()
        project = self.window.project
        state = (project.dirty, project.path, project.history.can_apply(), self.original.read_bytes())
        target = self.save_template()
        self.assertEqual((project.dirty, project.path, project.history.can_apply(), self.original.read_bytes()),
                         state)
        text = target.read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, text)
        self.assertEqual(json.loads(text)["schema"], 1)
        self.assertIn("Template saved", self.window.message.text())

    def test_closing_the_confirmation_writes_nothing(self):
        self.open(self.original)
        target = self.folder / "procedura.tramatpl"
        seen = []

        def close(dialog):
            dialog.file.setText(str(target))
            seen.append(dialog.preview.toPlainText())
            return False

        with self.dialogs(close):
            self.window.save_template()
        self.settle()
        self.assertFalse(target.exists())
        self.assertIn("Curva corretta $", seen[0])
        self.assertIn("4 observation row(s)", seen[0])
        self.assertIn("1 excluded cell(s)", seen[0])

    def test_the_open_project_is_refused_as_target_even_through_a_link(self):
        self.open(self.original)
        alias = self.folder / "alias.tramatpl"
        try:
            alias.symlink_to(self.original)
        except OSError:
            self.skipTest("symbolic links are not available")
        before = self.original.read_bytes()

        def alias_then_cancel(dialog):
            dialog.file.setText(str(alias))
            dialog.accept()
            self.app.processEvents()
            self.assertTrue(dialog.problem.isVisible())
            self.assertIs(dialog.focusWidget(), dialog.file)
            self.assertEqual(dialog.file.accessibleDescription(), dialog.problem.text())
            dialog.file.setText(str(self.folder / "wrong.alab"))
            dialog.accept()
            self.assertIn(".tramatpl", dialog.problem.text())
            return False

        with self.dialogs(alias_then_cancel):
            self.window.save_template()
        self.assertEqual(self.original.read_bytes(), before)

    def test_an_info_reference_blocks_saving_and_says_where(self):
        from analisi.info import InfoSheet
        self.open(self.original)
        project = self.window.project
        sheet = InfoSheet("Costanti", (("k", "2"),), table="Analisi α")
        project.update_info_sheets({**project.info_sheets, sheet.uid: sheet})
        project.set_formula("Analisi α", "Scaled2", '=Y*INFO("k")')

        def blocked(dialog):
            self.assertFalse(dialog.save_button.isEnabled())
            self.assertIn("Formula Scaled2 of Analisi α", dialog.preview.toPlainText())
            dialog.accept()
            return dialog.path is not None

        with self.dialogs(blocked):
            self.window.save_template()
        self.assertEqual(list(self.folder.glob("*.tramatpl")), [])

    # -- new project from template --------------------------------------------------------------------
    def test_the_assistant_maps_new_data_into_a_new_tab(self):
        self.open(self.original)
        target = self.save_template()
        sources = self.sources_project()
        source_state = (sources.dirty, {title: table.raw.copy() for title, table in sources.tables.items()})
        tabs = len(self.window.sessions)

        def errors_then_cancel(wizard):
            self.assertEqual(wizard.source_boxes["Analisi α"].currentData(), None)  # Names differ: no proposal.
            self.assign(wizard, self.mapping)
            box = wizard.column_boxes["Analisi α", "Y"]
            box.setCurrentIndex(box.findData("Dose"))
            wizard.accept()
            self.app.processEvents()
            self.assertTrue(wizard.problem.isVisible())
            self.assertIn("Dose", wizard.problem.text())
            focused = wizard.focusWidget()
            self.assertIn(focused, (box, wizard.column_boxes["Analisi α", "X"]))
            self.assertEqual(focused.accessibleDescription(), wizard.problem.text())
            box.setCurrentIndex(box.findData("Segnale (mV)"))
            empty = wizard.column_boxes["Controllo", "Signal"]
            empty.setCurrentIndex(0)
            wizard.accept()
            self.assertIs(wizard.focusWidget(), empty)
            self.assertIn("Signal", wizard.problem.text())
            self.assertIn("Extra", wizard.summary.text())
            return False

        with self.dialogs(errors_then_cancel):
            self.window.new_from_template(target)
            self.settle()
        self.assertEqual(len(self.window.sessions), tabs)
        self.assertIs(self.window.project, sources)

        built = self.apply(target)
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.window.sessions), tabs + 1)
        self.assertIsNot(built, sources)
        self.assertEqual((built.path, built.origin, built.dirty, built.history.can_apply()), (None, None, True, False))
        self.assertEqual(self.slopes(built), [6.0, 3.0, 5.0])
        self.assertEqual(list(built.tables["Analisi α"].raw["Badge"]), ["0003", "0004", "0005", "0006"])
        self.assertEqual(sources.dirty, source_state[0])
        for title, frame in source_state[1].items():
            self.assertTrue(sources.tables[title].raw.equals(frame))
        self.assertIn("calculated on the new data", self.window.message.text())

        self.window.switch_project(self.window.sessions[tabs - 1])
        again = self.apply(target)
        self.assertFalse({run.uid for run in built.runs} & {run.uid for run in again.runs})

    def test_saved_reopened_and_edited_from_the_layout(self):
        self.open(self.original)
        target = self.save_template()
        self.sources_project()
        built = self.apply(target)
        saved = self.folder / "Istanza.alab"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(saved), "")):
            self.assertTrue(self.window.save(as_new=True))
        self.window.close_project()
        self.open(saved)
        self.window.open_sheet(("layout", 0))
        self.settle()
        reopened = self.window.project
        self.assertIsNot(reopened, built)
        self.assertEqual(self.slopes(reopened), [6.0, 5.0])  # The two panels of the layout.
        self.window.open_sheet(("data", "Controllo"))
        model = self.window.sheet.model()
        self.assertTrue(model.setData(model.index(3, 1), "26"))
        self.app.processEvents()
        self.settle()
        self.window.open_sheet(("layout", 0))
        self.settle()
        self.assertEqual(self.slopes(reopened)[-1], 6.5)

    def test_files_added_in_the_assistant_are_read_on_a_worker(self):
        self.open(self.original)
        target = self.save_template()
        self.window.new_project()
        reader = []
        from trama_qt.templates import _read_files as real

        def read(paths):
            reader.append(threading.current_thread().name)
            return real(paths)

        files = [str(self.folder / "nuova-calibrazione.csv"), str(self.folder / "nuovo-controllo.csv")]
        mapping = {"Analisi α": ["nuova-calibrazione", self.mapping["Analisi α"][1]],
                   "Controllo": ["nuovo-controllo", self.mapping["Controllo"][1]]}

        def add_then_create(wizard):
            with mock.patch.object(QFileDialog, "getOpenFileNames", return_value=(files, "")), \
                    mock.patch("trama_qt.templates._read_files", read):
                wizard.add_files()
                wizard.wait_files()
            self.assertEqual([wizard.source_boxes["Controllo"].itemText(i) for i in range(1, 3)],
                             ["nuova-calibrazione", "nuovo-controllo"])
            self.assign(wizard, mapping)
            wizard.accept()
            return wizard.mapping is not None

        empty = self.window.project
        with self.dialogs(add_then_create):
            self.window.new_from_template(target)
            self.settle()
        self.assertTrue(reader and reader[0] != threading.current_thread().name)
        self.assertIsNot(self.window.project, empty)
        self.assertNotIn(empty, [session.project for session in self.window.sessions])  # The empty tab was used.
        self.assertEqual(self.slopes(self.window.project), [6.0, 3.0, 5.0])

    def test_damaged_template_full_window_and_cancel_change_nothing(self):
        from trama_qt import templates
        self.open(self.original)
        target = self.save_template()
        sources = self.sources_project()
        bad = self.folder / "bad.tramatpl"
        bad.write_text(target.read_text(encoding="utf-8").replace('"schema": 1', '"schema": 999', 1),
                       encoding="utf-8")
        tabs = len(self.window.sessions)
        self.window.new_from_template(bad)
        self.settle(expect_errors=None)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("bad.tramatpl", self.errors[0])
        self.assertEqual(len(self.window.sessions), tabs)
        self.errors.clear()

        gate = threading.Event()
        real = templates.instantiate_template

        def slow(*args, **kwargs):
            while not kwargs["cancel"].is_set() and not gate.wait(0.02):
                pass
            return real(*args, **kwargs)

        def ok(wizard):
            self.assign(wizard, self.mapping)
            wizard.accept()
            return True

        with mock.patch.object(templates, "instantiate_template", slow), self.dialogs(ok):
            self.window.new_from_template(target)
            end = time.monotonic() + 20
            while not (self.window.job is not None and self.window.job.label.startswith("Building")) \
                    and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(0.02)
            self.assertIsNotNone(self.window.job)
            self.assertEqual(len(self.window.sessions), tabs)  # No tab while building.
            self.window.cancel_calculation()
            self.settle()
        gate.set()
        self.assertEqual(len(self.window.sessions), tabs)
        self.assertIs(self.window.project, sources)
        self.assertIn("not created", self.window.message.text())

        while not self.window.sessions.full():
            self.window.new_project()
            self.window.project.dirty = True
        with mock.patch.object(QFileDialog, "getOpenFileName", side_effect=AssertionError("asked for a file")):
            self.window.new_from_template()
        self.assertEqual(len(self.errors), 1)
        self.assertIn("6", self.errors[0])

    def test_a_failed_analysis_names_its_input_and_recovers_after_the_fix(self):
        self.open(self.original)
        target = self.save_template()
        sources = self.sources_project()
        flat = sources.tables["Campioni nuovi"]
        flat.raw["Dose"] = [1, 1, 1, 1]
        built = self.apply(target)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("could not be calculated", self.errors[0])
        self.assertIn("Curva corretta $", self.errors[0])
        self.assertIn("which reads Normalize of Transformed", self.errors[0])
        failed = [run for run in built.runs if run.calculation_error]
        self.assertTrue(failed and all(run.result is None for run in failed))  # Nothing old is shown.
        self.errors.clear()
        self.window.open_sheet(("data", "Analisi α"))
        model = self.window.sheet.model()
        for row, value in enumerate(("1", "2", "3", "4")):
            model.setData(model.index(row, 0), value)
            self.app.processEvents()
            self.settle()
        self.window.open_sheet(("layout", 0))
        self.settle()
        self.assertEqual(self.slopes(built)[0], 6.0)

    def test_commands_are_in_the_file_tab_and_translated(self):
        from trama_qt.templates import t
        window = self.window
        self.assertFalse(window.actions["save_template"].isEnabled())  # No data yet.
        self.assertTrue(window.actions["new_from_template"].isEnabled())
        self.open(self.original)
        self.assertTrue(window.actions["save_template"].isEnabled())
        self.assertEqual(window.actions["save_template"].text(), "Save as analysis template…")
        self.assertEqual(window.actions["new_from_template"].text(), "New project from template…")
        set_language("it")
        self.assertEqual(t("save_action"), "Salva come modello…")
        self.assertEqual(t("new_action"), "Nuovo progetto da modello…")


if __name__ == "__main__":
    unittest.main()
