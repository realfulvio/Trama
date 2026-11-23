"""File → Export analysis report… on Qt: candidates, dialog, freezing and the real path, offscreen.

The fixture ``tests/data/qt_report/calibrazione-report.alab`` is synthetic (package Report riproducibili).
Every archive is read back with ``zipfile`` and ``json`` here, not only with ``verify_bundle``.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np

from analisi.report_bundle import verify_bundle

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "data" / "qt_report" / "calibrazione-report.alab"
TITLE = "Control $ <A> & β"
NOTE = "Confronto <script>test</script> tra curve"
PRIVATE = ("Nota privata sintetica", "SINT-01", "Note calibrazione")


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-report-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def calculated_project(*, second=True, layout=True):
    """The fixture with its regression calculated, a second run with the same label and a layout."""
    from analisi.presentation import Layout
    from trama_qt.project import Project, compute
    project = Project()
    project.load(FIXTURE)
    run = project.runs[0]
    frame = project.tables[run.title].frame(mask_excluded=True)
    run.result = compute(run, frame)
    if second:
        candidate = project.candidate(run.title, run.method, {**deepcopy(run.options), "Y": "Dose", "X": "Risposta"})
        candidate.label = run.name  # Same label as the first one: the recipes must still stay apart.
        project.add_result(candidate, compute(candidate, frame))
    if layout:
        project.put_layout(Layout("Pannello β", 2, [r.reference for r in project.runs]))
    project.dirty = False
    return project


def members(path):
    with zipfile.ZipFile(path) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ReportCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_tables_graphs_and_layouts_in_navigator_order(self):
        from trama_qt.report_catalog import candidates
        project = calculated_project()
        items = candidates(project)
        self.assertEqual([item.ref for item in items],
                         [("table", 0, "Regression"), ("graph", 0), ("table", 1, "Regression"), ("graph", 1),
                          ("layout", 0)])
        self.assertTrue(all(item.available for item in items))
        self.assertEqual(items[0].options, {"X": "Dose", "Y": "Risposta"})
        self.assertEqual(items[2].options, {"X": "Risposta", "Y": "Dose"})
        self.assertEqual(items[0].label, items[2].label)
        self.assertEqual(items[4].method, "Layout")
        self.assertEqual(items[4].options["columns"], 2)
        self.assertFalse(project.dirty)

    def test_not_calculated_and_failed_items_carry_a_reason(self):
        from trama_qt.report_catalog import candidates
        project = calculated_project()
        project.runs[1].calculation_error = "Division by zero in the fit"
        fresh = calculated_project(second=False, layout=False)
        fresh.runs[0].result = None
        items = {item.ref: item for item in candidates(project)}
        self.assertIn("Division by zero", items[("table", 1, "Regression")].reason)
        self.assertIn("Division by zero", items[("graph", 1)].reason)
        self.assertTrue(items[("layout", 0)].reason)
        pending = candidates(fresh)
        self.assertEqual(len(pending), 1)
        self.assertFalse(pending[0].available)
        self.assertEqual(fresh.runs[0].result, None)  # Listing never calculates.

    def test_recipe_is_json_without_paths_caches_or_imported_drawings(self):
        from trama_qt.report_catalog import recipe
        cleaned = recipe({"X": "Dose", "Level": np.float64(0.95), "Count": np.int64(3), "Pair": ("a", "b"),
                          "Missing": float("nan"), "Legacy graph preview": b"\x00", "Source": "/home/luca/x.csv",
                          "Windows": "C:\\Users\\luca\\x.csv", "Blob": b"x", "Nested": {"Legacy notes": "x", "k": 1}})
        self.assertEqual(cleaned, {"X": "Dose", "Level": 0.95, "Count": 3, "Pair": ["a", "b"], "Missing": None,
                                   "Nested": {"k": 1}})
        json.dumps(cleaned, allow_nan=False)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ReportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def dialog(self, project=None):
        from trama_qt.report_catalog import candidates
        from trama_qt.report_dialog import ReportDialog
        project = project or calculated_project()
        dialog = ReportDialog(None, candidates(project), "Calibrazione")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_report_buttons_remain_reachable_on_a_short_screen(self):
        from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

        dialog = self.dialog()
        dialog.resize(680, 420)
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.height(), 420)
        scroll = dialog.findChild(QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(scroll.isAncestorOf(dialog.box))
        for choice in (QDialogButtonBox.StandardButton.Ok, QDialogButtonBox.StandardButton.Cancel):
            button = dialog.box.button(choice)
            self.assertTrue(button.isVisible())
            self.assertLessEqual(button.mapTo(dialog, button.rect().bottomRight()).y(), dialog.height())

    def test_empty_selection_and_empty_names_are_field_errors(self):
        dialog = self.dialog()
        dialog.check_all(False)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.summary.objectName(), "errorBanner")
        self.assertIn("Select at least one", dialog.summary.text())
        dialog.check_all(True)
        dialog.list.item(0).setText("   ")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("Section 1", dialog.summary.text())
        dialog.list.item(0).setText("Tabella A")
        dialog.title.setText("")
        dialog.accept()
        self.assertIsNone(dialog.result)

    def test_order_names_and_contents_preview(self):
        dialog = self.dialog()
        self.assertFalse(dialog.project.isChecked())  # The project copy starts off.
        dialog.list.setCurrentRow(4)
        dialog.move(-1)
        dialog.move(-1)
        dialog.list.item(0).setText("Tabella <prima>")
        dialog.list.item(1).setCheckState(Qt.CheckState.Unchecked)
        lines = dialog.contents()
        self.assertEqual(lines[:3], ["index.html", "manifest.json", "tables/001.csv — Tabella <prima>"])
        self.assertEqual(lines[3].split(" — ")[0], "figures/002.svg")
        self.assertIn("Pannello β", lines[3])
        dialog.project.setChecked(True)
        self.assertEqual(dialog.contents()[-1], "project.alab")
        dialog.accept()
        self.assertEqual([item.ref for item, _ in dialog.result["items"]],
                         [("table", 0, "Regression"), ("layout", 0), ("table", 1, "Regression"), ("graph", 1)])
        self.assertTrue(dialog.result["include_project"])

    def test_unavailable_rows_show_the_reason_and_cannot_be_ticked(self):
        project = calculated_project()
        project.runs[1].calculation_error = "Fit did not converge"
        dialog = self.dialog(project)
        rows = dialog.rows()
        failed = [row for row in rows if "Fit did not converge" in row.text()]
        self.assertEqual(len(failed), 3)  # Its table, its graph and the layout that uses it.
        for row in failed:
            self.assertFalse(row.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            self.assertFalse(row.flags() & Qt.ItemFlag.ItemIsEnabled)
        dialog.accept()
        self.assertEqual(len(dialog.result["items"]), 2)

    def test_italian_texts(self):
        from analisi.i18n import active_language, set_language
        language = active_language()
        set_language("it")
        self.addCleanup(set_language, language)
        dialog = self.dialog()
        self.assertEqual(dialog.windowTitle(), "Esporta report di analisi")
        self.assertEqual(dialog.language.currentData(), "it")
        dialog.check_all(False)
        self.assertIn("Seleziona almeno", dialog.summary.text())


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ReportWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.window import MainWindow
        self.language = active_language()
        set_language("en")
        self.addCleanup(set_language, self.language)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / "calibrazione-report.alab"
        self.source.write_bytes(FIXTURE.read_bytes())
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1100, 760)
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
        self.assertIsNone(self.window.job, "job still running")

    def prepare(self):
        """Open the fixture, calculate the regression, add a second run with the same label and a layout."""
        from analisi.presentation import Layout
        from trama_qt.project import compute
        self.window.open_path(self.source)
        self.wait()
        project = self.window.project
        self.window.refresh_runs(list(project.runs))
        self.wait()
        run = project.runs[0]
        frame = project.tables[run.title].frame(mask_excluded=True)
        candidate = project.candidate(run.title, run.method, {**deepcopy(run.options), "Y": "Dose", "X": "Risposta"})
        candidate.label = run.name
        project.add_result(candidate, compute(candidate, frame))
        project.put_layout(Layout("Pannello β", 2, [r.reference for r in project.runs]))
        self.window.refresh()
        self.window.show_sheet("graph", 0)
        self.app.processEvents()
        project.dirty = False
        return project

    def export(self, target, *, setup=None, include_project=False, replace=None, cancel_dialog=False):
        """Run File → Export analysis report… with the real dialog, driven by ``setup(dialog)``."""
        from trama_qt import report_dialog

        def run_dialog(dialog):
            dialog.show()
            self.app.processEvents()
            if cancel_dialog:
                dialog.reject()
                return QDialog.DialogCode.Rejected
            dialog.title.setText(TITLE)
            dialog.note.setPlainText(NOTE)
            dialog.project.setChecked(include_project)
            if setup is not None:
                setup(dialog)
            dialog.accept()
            return dialog.result is not None and QDialog.DialogCode.Accepted or QDialog.DialogCode.Rejected

        answers = []

        def question(*args, **kwargs):
            answers.append(args[2])
            return QMessageBox.StandardButton.Yes if replace else QMessageBox.StandardButton.No

        with mock.patch.object(report_dialog.ReportDialog, "exec", run_dialog), \
                mock.patch.object(report_dialog.QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                mock.patch.object(report_dialog.QMessageBox, "question", side_effect=question):
            self.window.actions["export_report"].trigger()
            self.wait()
        return answers

    def test_action_is_in_the_file_menu(self):
        from trama_qt.report_dialog import text
        self.assertEqual(self.window.actions["export_report"].text(), text("command"))
        self.assertIn(self.window.actions["export_report"], self.window.command_menus["File"].actions())
        self.assertFalse(self.window.actions["export_report"].isEnabled())  # Nothing to report yet.
        self.prepare()
        self.assertTrue(self.window.actions["export_report"].isEnabled())

    def test_real_path_order_names_recipes_and_privacy(self):
        project = self.prepare()
        selected, original = self.window.selected, self.source.read_bytes()
        target = self.folder / "report.zip"

        def setup(dialog):
            dialog.list.setCurrentRow(4)  # Layout first, then the first table renamed.
            for _ in range(4):
                dialog.move(-1)
            dialog.list.item(1).setText("Tabella $ <B>")
        self.export(target, setup=setup)
        self.assertEqual(self.errors, [])
        manifest = verify_bundle(target)
        files = members(target)
        self.assertEqual(sorted(files), ["figures/001.svg", "figures/003.svg", "figures/005.svg", "index.html",
                                         "manifest.json", "tables/002.csv", "tables/004.csv"])
        sections = manifest["sections"]
        self.assertEqual([s["label"] for s in sections],
                         ["Pannello β", "Tabella $ <B>", project.runs[0].name, project.runs[1].name,
                          project.runs[1].name])
        self.assertEqual([s["method"] for s in sections], ["Layout"] + ["Linear regression"] * 4)
        self.assertEqual(sections[1]["options"], {"X": "Dose", "Y": "Risposta"})
        self.assertEqual(sections[3]["options"], {"X": "Risposta", "Y": "Dose"})
        self.assertEqual(manifest["project_title"], TITLE)
        self.assertEqual(manifest["metadata"]["language"], "en")
        self.assertRegex(manifest["metadata"]["created_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        csv_text = files["tables/002.csv"].decode("utf-8-sig")
        self.assertIn("Slope", csv_text)
        self.assertIn("2.1", csv_text)
        self.assertIn(b"<svg", files["figures/003.svg"])
        index = files["index.html"].decode("utf-8")
        self.assertIn("Control $ &lt;A&gt; &amp; β", index)
        self.assertIn("Confronto &lt;script&gt;test&lt;/script&gt; tra curve", index)
        blob = b"".join(files.values()).decode("utf-8", "replace")
        for private in PRIVATE + (str(self.folder),):
            self.assertNotIn(private, blob)
        self.assertFalse(project.dirty)
        self.assertEqual(self.window.selected, selected)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIn("5 sections", self.window.message.text())
        self.assertIn(str(target), self.window.message.text())

    def test_project_copy_reopens_and_recalculates(self):
        from trama_qt.project import Project, compute
        project = self.prepare()
        target = self.folder / "with-project.zip"
        self.export(target, include_project=True)
        self.assertEqual(self.errors, [])
        files = members(target)
        self.assertIn("project.alab", files)
        self.assertIn("project.alab", [f["path"] for f in verify_bundle(target)["files"]])
        copy = self.folder / "copy.alab"
        copy.write_bytes(files["project.alab"])
        reopened = Project()
        reopened.load(copy)
        self.assertEqual([(r.method, r.options) for r in reopened.runs], [(r.method, r.options) for r in project.runs])
        self.assertEqual(len(reopened.info_sheets), 1)
        self.assertEqual([layout.name for layout in reopened.layouts], ["Pannello β"])
        for run in reopened.runs:
            run.result = compute(run, reopened.tables[run.title].frame(mask_excluded=True))
        reopened.save(self.folder / "copy-saved.alab")
        self.assertFalse(project.dirty)
        self.assertEqual(project.path, self.source)

    def test_existing_report_asks_before_replacing(self):
        self.prepare()
        target = self.folder / "report.zip"
        target.write_bytes(b"previous")
        answers = self.export(target, replace=False)
        self.assertEqual(len(answers), 1)
        self.assertIn("report.zip", answers[0])
        self.assertEqual(target.read_bytes(), b"previous")
        self.export(target, replace=True)
        verify_bundle(target)

    def test_cancel_in_the_dialog_writes_nothing(self):
        self.prepare()
        target = self.folder / "report.zip"
        self.export(target, cancel_dialog=True)
        self.assertFalse(target.exists())
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["calibrazione-report.alab"])

    def test_change_between_preview_and_confirmation_stops_the_export(self):
        project = self.prepare()
        target = self.folder / "report.zip"

        def setup(dialog):
            project.runs[0].calculation_error = "Recalculation pending"
        self.export(target, setup=setup)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("changed after the preview", self.errors[0])
        self.assertFalse(target.exists())

    def test_cancel_while_writing_keeps_the_previous_file(self):
        from analisi import report_bundle
        from trama_qt import report_dialog
        self.prepare()
        target = self.folder / "report.zip"
        target.write_bytes(b"previous")
        started = threading.Event()

        def slow(*args, cancel, **kwargs):
            started.set()
            end = time.monotonic() + 20
            while not cancel() and time.monotonic() < end:
                time.sleep(0.01)
            return report_bundle.export_bundle(*args, cancel=cancel, **kwargs)

        def run_dialog(dialog):
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with mock.patch.object(report_dialog, "export_bundle", slow), \
                mock.patch.object(report_dialog.ReportDialog, "exec", run_dialog), \
                mock.patch.object(report_dialog.QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                mock.patch.object(report_dialog.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.actions["export_report"].trigger()
            self.assertIsNotNone(self.window.job)
            self.assertFalse(self.window.actions["export_report"].isEnabled())
            self.assertTrue(started.wait(10))
            self.window.cancel_calculation()
            self.wait()
        self.assertEqual(target.read_bytes(), b"previous")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["calibrazione-report.alab", "report.zip"])
        self.assertIn("cancelled", self.window.message.text())

    def test_cancel_while_freezing_writes_nothing(self):
        from trama_qt import report_dialog
        self.prepare()
        target = self.folder / "report.zip"
        with mock.patch.object(report_dialog.QProgressDialog, "wasCanceled", return_value=True):
            self.export(target)
        self.assertFalse(target.exists())
        self.assertIsNone(self.window.job)
        self.assertIn("cancelled", self.window.message.text())

    def test_busy_window_and_kept_inspector_draft_do_nothing(self):
        from trama_qt import report_dialog
        self.prepare()
        with mock.patch.object(report_dialog.ReportDialog, "exec", side_effect=AssertionError("opened")):
            with mock.patch.object(self.window, "settle_graph_draft", return_value=False):
                self.window.export_report()
            self.window.job = object()
            try:
                self.window.export_report()
            finally:
                self.window.job = None

    def test_inspector_draft_is_settled_before_the_snapshot(self):
        self.prepare()
        calls = []
        original = self.window.settle_graph_draft

        def settle():
            calls.append(1)
            return original()
        with mock.patch.object(self.window, "settle_graph_draft", settle):
            self.export(self.folder / "report.zip")
        self.assertEqual(calls, [1])

    def test_only_the_active_tab_is_reported(self):
        self.prepare()
        self.window.new_project()
        self.app.processEvents()
        self.assertFalse(self.window.actions["export_report"].isEnabled())
        self.window.switch_project(self.window.sessions.items[0])
        self.app.processEvents()
        target = self.folder / "report.zip"
        self.export(target)
        self.assertEqual(len(verify_bundle(target)["sections"]), 5)

    def test_same_project_gives_the_same_members_except_the_time(self):
        self.prepare()
        first, second = self.folder / "a.zip", self.folder / "b.zip"
        self.export(first)
        self.export(second)
        a, b = members(first), members(second)
        self.assertEqual(sorted(a), sorted(b))
        for name in a:
            if name not in {"index.html", "manifest.json"}:
                self.assertEqual(a[name], b[name], name)


if __name__ == "__main__":
    unittest.main()
