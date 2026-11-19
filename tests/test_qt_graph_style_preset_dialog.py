"""Graph → Figure styles… on Qt, offscreen: save, preview, cancel, apply, reopen, second project, errors.

Uses a temporary preferences folder and the synthetic two-graph session of the Stili-Figura package.
Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from matplotlib.colors import to_hex

SESSION = {"version": 2, "layouts": [], "tables": [
    {"title": title, "columns": ["Dose", "Response"], "kinds": ["numeric", "numeric"],
     "rows": [[1, a], [2, b], [4, c], [8, d], [16, e]], "formulas": [],
     "analyses": [["XY series", {"X": "Dose", "Y columns": ["Response"], "Drawing": "Line and points"}]],
     "excluded": [], "table_format": "xy", "graph_styles": {}}
    for title, (a, b, c, d, e) in (("Calibrazione $ A", (2.1, 3.2, 5.9, 8.2, 9.3)),
                                    ("Calibrazione B", (1.8, 3.1, 5.2, 7.7, 8.8)))]}
PUBLICATION = {"accent": "#0B7A73", "font_family": "serif", "title_size": 18, "grid": True, "legend": "upper right"}
SHAPE = {"id": "0b7a7300-0000-4000-8000-000000000002", "kind": "rectangle", "units": "axes",
         "points": [[0.1, 0.6], [0.35, 0.85]], "stroke": "#AA4433", "width": 1.5, "line_style": "dashed",
         "fill": None, "alpha": 1.0, "layer": "above"}
SECOND = {"title": "Calibrazione B", "xlabel": "Tempo", "accent": "#AA4433", "grid": False, "xscale": "log",
          "shapes": [SHAPE]}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class GraphStylePresetDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        prefs = self.folder / "prefs"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(prefs), "APPDATA": str(prefs)})
        env.start()
        self.addCleanup(env.stop)
        from trama_qt.graph_style_presets import library_path
        self.library_file = library_path()
        self.assertTrue(str(self.library_file).startswith(str(prefs)))
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        from PySide6.QtCore import QEvent

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
        self.assertIsNone(self.window.job, "calculation still running")

    def open_session(self, name="sessione.alab", session=SESSION):
        path = self.folder / name
        path.write_text(json.dumps(session), encoding="utf-8")
        self.window.open_path(path)
        self.app.processEvents()
        for index in range(len(self.window.project.runs)):
            self.window.open_sheet(("graph", index))
            self.wait()
        self.assertEqual(len(self.window.project.runs), 2)
        return path

    def commit(self, index, style):
        from analisi.presentation import apply_style
        run = self.window.project.runs[index]
        self.window.open_sheet(("graph", index))
        self.wait()
        apply_style(run.result.figure, style)
        self.window.commit_style(run, deepcopy(style))
        self.window.show_sheet("graph", index)
        return run

    def dialog(self, steps):
        """Run Figure styles… with ``steps(dialog)`` in place of the user; returns what steps returned."""
        from trama_qt.graph_style_preset_dialog import GraphStylePresetDialog
        seen = {}

        def run(dialog):
            seen["dialog"] = dialog
            seen["value"] = steps(dialog)
            accepted = dialog.result is not None
            return dialog.DialogCode.Accepted if accepted else dialog.DialogCode.Rejected

        with mock.patch.object(GraphStylePresetDialog, "exec", lambda dialog: run(dialog)):
            self.window.graph_style_presets()
        return seen.get("value"), seen.get("dialog")

    @staticmethod
    def choose(dialog, name):
        items = dialog.list.findItems(name, Qt.MatchFlag.MatchExactly)
        assert items, name
        dialog.list.setCurrentItem(items[0])

    def engine_counter(self):
        """Counts every calculation the engine could start (none is expected for styles)."""
        import trama_qt.project as project
        import trama_qt.window as window
        calls = []
        def counter(name):
            return lambda *args, **kwargs: calls.append(name)

        self._engine_patches = patches = [
            mock.patch.object(project, "compute", side_effect=counter("compute")),
            mock.patch.object(window, "compute", side_effect=counter("compute")),
            mock.patch.object(project, "xy_series", side_effect=counter("xy")),
            mock.patch.object(project, "analyse", side_effect=counter("analyse"))]
        for patch in patches:
            patch.start()
        self.addCleanup(self.stop_engine_counter)
        return calls

    def stop_engine_counter(self):
        for patch in getattr(self, "_engine_patches", []):
            patch.stop()
        self._engine_patches = []

    # -- the acceptance flow of the package ------------------------------------------------------
    def test_publication_style_preview_cancel_apply_reopen_second_project(self):
        from trama_qt import graph_style_presets as gsp
        from trama_qt.window import export_graph
        window = self.window
        self.open_session()
        first = self.commit(0, PUBLICATION)
        second = self.commit(1, SECOND)
        before_second = deepcopy(second.style)
        self.assertTrue(window.actions["graph_style_presets"].isEnabled())
        self.assertIn(window.actions["graph_style_presets"],
                      window.ribbon.widget(3).actions())  # Graph tab, next to Format Graph.

        # Save «Pubblicazione» from the first graph; Enter in the name field saves without closing.
        window.open_sheet(("graph", 0))

        def save(dialog):
            dialog.show()
            QTest.keyClicks(dialog.name, " Pubblicazione ")
            dialog.name.setFocus()
            QTest.keyClick(dialog.name, Qt.Key.Key_Return)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.list.currentItem().text(), "Pubblicazione")
            dialog.reject()

        self.dialog(save)
        stored = json.loads(self.library_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["presets"], [{"version": 1, "name": "Pubblicazione", "style": PUBLICATION}])
        self.assertEqual(first.style, PUBLICATION)

        # Preview on the second graph, then cancel: the confirmed figure comes back, nothing is stored.
        calls = self.engine_counter()
        window.open_sheet(("graph", 1))
        axes = second.result.figure.axes[0]
        line = axes.lines[0]
        confirmed_color = to_hex(line.get_color())

        def cancel(dialog):
            self.choose(dialog, "Pubblicazione")
            self.assertEqual(to_hex(line.get_color()), "#0b7a73")
            self.assertTrue(axes.xaxis.get_gridlines()[0].get_visible())
            self.assertIn("serif", axes.title.get_fontfamily())
            self.assertEqual(axes.title.get_fontsize(), 18)
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            self.assertFalse(dialog.isVisible())

        self.dialog(cancel)
        self.assertEqual(to_hex(line.get_color()), confirmed_color)
        self.assertFalse(axes.xaxis.get_gridlines()[0].get_visible())
        self.assertEqual(second.style, before_second)

        # Again, and Apply: one commit of the complete style.
        commits = []
        original = window.commit_style
        window.commit_style = lambda run, style: (commits.append((run, deepcopy(style))), original(run, style))

        def apply(dialog):
            self.choose(dialog, "Pubblicazione")
            dialog.accept()

        self.dialog(apply)
        window.commit_style = original
        self.assertEqual(len(commits), 1)
        self.assertIs(commits[0][0], second)
        expected = gsp.apply_preset(before_second, gsp.read_preset_file(self._export_fixture()))
        self.assertEqual(second.style, expected)
        self.assertEqual(second.style["title"], "Calibrazione B")
        self.assertEqual(second.style["xscale"], "log")
        self.assertEqual(second.style["shapes"], [SHAPE])
        axes = second.result.figure.axes[0]
        self.assertEqual(axes.get_title(), "Calibrazione B")
        self.assertEqual(axes.get_xscale(), "log")
        self.assertEqual(to_hex(axes.lines[0].get_color()), "#0b7a73")
        self.assertEqual(len(axes._tramastat_shapes), 1)
        self.assertEqual(calls, [])  # Preview and Apply never recalculate.
        self.assertTrue(window.project.dirty)
        self.assertEqual(self.errors, [])

        # Save, reopen: the graph keeps the style even after the preset is deleted from the library.
        saved = self.folder / "styled.alab"
        window.project.save(saved)
        recipe = deepcopy(second.style)
        gsp.PresetLibrary().load().delete("Pubblicazione")
        self.stop_engine_counter()
        window.open_path(saved)
        window.open_sheet(("graph", 1))
        self.wait()
        reopened = window.project.runs[1]
        self.assertEqual(reopened.style, recipe)
        self.assertEqual(to_hex(reopened.result.figure.axes[0].lines[0].get_color()), "#0b7a73")
        self.assertEqual(reopened.result.figure.axes[0].get_xscale(), "log")

        # A second project receives the style from the library (imported again); SVG and PDF show it.
        self.open_session("secondo.alab")
        self.commit(0, {"title": "Calibrazione $ A", "xscale": "log"})  # A lone $ is not math text.

        def import_and_apply(dialog):
            self.assertIsNotNone(dialog.import_path(self._export_fixture()))
            self.choose(dialog, "Pubblicazione")
            dialog.accept()

        self.dialog(import_and_apply)
        other = window.project.runs[0]
        self.assertEqual(other.style, {"title": "Calibrazione $ A", "xscale": "log", **PUBLICATION})
        figure = other.result.figure
        export_graph(figure, self.folder / "secondo.svg")
        export_graph(figure, self.folder / "secondo.pdf")
        svg = (self.folder / "secondo.svg").read_text(encoding="utf-8").lower()
        self.assertIn("#0b7a73", svg)
        self.assertTrue((self.folder / "secondo.pdf").read_bytes().startswith(b"%PDF"))
        self.assertIn(b"Serif", (self.folder / "secondo.pdf").read_bytes())
        self.assertEqual(figure.axes[0].get_title(), "Calibrazione $ A")
        self.assertEqual(figure.axes[0].get_xscale(), "log")
        self.assertIn("Calibrazione $ A", (self.folder / "secondo.svg").read_text(encoding="utf-8"))

    def _export_fixture(self):
        path = self.folder / "pubblicazione.json"
        path.write_text(json.dumps({"version": 1, "name": "Pubblicazione", "style": PUBLICATION}), encoding="utf-8")
        return path

    # -- library actions and errors --------------------------------------------------------------
    def test_import_homonym_truncated_write_error_and_damaged_library(self):
        from trama_qt import graph_style_presets as gsp
        self.open_session()
        self.commit(0, PUBLICATION)
        fixture = self._export_fixture()
        shouting = self.folder / "maiuscole.json"
        shouting.write_text(json.dumps({"version": 1, "name": "PUBBLICAZIONE", "style": {"grid": False}}),
                            encoding="utf-8")
        truncated = self.folder / "troncato.json"
        truncated.write_text(fixture.read_text(encoding="utf-8")[:-9], encoding="utf-8")
        answers = []
        question = mock.patch("trama_qt.graph_style_preset_dialog.QMessageBox.question",
                              side_effect=lambda *a, **k: answers.pop(0))
        question.start()
        self.addCleanup(question.stop)

        def steps(dialog):
            self.assertIsNotNone(dialog.import_path(fixture))
            answers.append(QMessageBox.StandardButton.No)
            self.assertIsNone(dialog.import_path(shouting))  # Same name ignoring case, not replaced.
            self.assertEqual(gsp.PresetLibrary().load().get("pubblicazione")["style"], PUBLICATION)
            answers.append(QMessageBox.StandardButton.Yes)
            self.assertIsNotNone(dialog.import_path(shouting))
            self.assertEqual(gsp.PresetLibrary().load().names(), ["PUBBLICAZIONE"])
            before = self.library_file.read_bytes()
            self.assertIsNone(dialog.import_path(truncated))
            self.assertEqual(dialog.banner.objectName(), "errorBanner")
            self.assertIn("JSON", dialog.banner.text())
            with mock.patch("trama_qt.graph_style_presets.os.replace", side_effect=PermissionError(13, "Denied")):
                dialog.name.setText("Nuovo")
                dialog.save_preset()
            self.assertIn("Denied", dialog.banner.text())
            self.assertEqual(self.library_file.read_bytes(), before)
            self.assertEqual(dialog.list.count(), 1)
            # A wrong name stays in the field with its message.
            dialog.name.setText("   ")
            dialog.save_preset()
            self.assertFalse(dialog.name_error.isHidden())
            self.assertEqual(self.library_file.read_bytes(), before)
            # Rename and delete ask for confirmation of their own.
            self.choose(dialog, "PUBBLICAZIONE")
            self.assertTrue(dialog.rename_to("Rivista"))
            answers.append(QMessageBox.StandardButton.Yes)
            self.assertTrue(dialog.delete_preset())
            self.assertEqual(gsp.PresetLibrary().load().presets, [])
            dialog.reject()

        self.dialog(steps)
        self.assertEqual(answers, [])

        # A damaged library: the reason and path are shown, nothing is written until it is set aside.
        self.library_file.write_text('{"version": 1, "presets": [', encoding="utf-8")

        def damaged(dialog):
            self.assertEqual(dialog.banner.objectName(), "errorBanner")
            self.assertIn(str(self.library_file), dialog.banner.text())
            self.assertFalse(dialog.buttons["save"].isEnabled())
            self.assertFalse(dialog.set_aside_button.isHidden())
            dialog.name.setText("Prova")
            dialog.save_preset()
            self.assertEqual(self.library_file.read_text(encoding="utf-8"), '{"version": 1, "presets": [')
            answers.append(QMessageBox.StandardButton.Yes)
            dialog.set_aside()
            self.assertTrue(dialog.buttons["save"].isEnabled())
            dialog.reject()

        self.dialog(damaged)
        kept = [path for path in self.library_file.parent.iterdir() if ".damaged-" in path.name]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_text(encoding="utf-8"), '{"version": 1, "presets": [')

    def test_inspector_draft_is_kept_and_defaults_cannot_be_saved(self):
        window = self.window
        self.open_session()
        window.open_sheet(("graph", 0))
        window.toggle_inspector()
        inspector = window.inspector
        inspector.widgets["title"].setText("Bozza")
        inspector._now("title")
        self.assertTrue(inspector.has_draft)
        opened = []
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.dialog(lambda dialog: opened.append(dialog))
        self.assertEqual(opened, [])  # Back to the graph: the draft stays.
        self.assertTrue(window.inspector.has_draft)
        self.assertEqual(window.project.runs[0].result.figure.axes[0].get_title(), "Bozza")
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            def defaults(dialog):
                dialog.name.setText("Vuoto")
                dialog.save_preset()
                self.assertFalse(dialog.name_error.isHidden())
                self.assertFalse(dialog.apply_button.isEnabled())
                dialog.reject()
            self.dialog(defaults)
        self.assertFalse(self.library_file.exists())

    def test_italian_captions_and_canonical_values(self):
        from analisi.i18n import active_language, set_language
        previous = active_language()
        set_language("it")
        self.addCleanup(set_language, previous)
        from trama_qt.graph_style_preset_dialog import GraphStylePresetDialog
        from trama_qt.graph_style_presets import PresetLibrary
        self.open_session()
        run = self.commit(0, PUBLICATION)
        library = PresetLibrary()
        library.save({"version": 1, "name": "Pubblicazione", "style": PUBLICATION})
        dialog = GraphStylePresetDialog(self.window, run.result.figure, None, run.style, library)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.windowTitle(), "Stili di figura")
        self.assertEqual(dialog.apply_button.text(), "Applica")
        self.choose(dialog, "Pubblicazione")
        shown = [dialog.details.itemAt(row, dialog.details.ItemRole.FieldRole).widget()
                 for row in range(dialog.details.rowCount())]
        texts = " ".join(widget.text() if hasattr(widget, "text") else
                         " ".join(child.text() for child in widget.findChildren(type(dialog.banner)))
                         for widget in shown)
        self.assertIn("Con grazie", texts)
        self.assertIn("in alto a destra", texts)
        dialog.reject()
        self.assertEqual(json.loads(self.library_file.read_text(encoding="utf-8"))["presets"][0]["style"]["legend"],
                         "upper right")


if __name__ == "__main__":
    unittest.main()
