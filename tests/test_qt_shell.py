"""The Qt window end to end, offscreen: open, edit, analyse, graph, save, reopen, export.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "QtAgg")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def _app():
    app = QApplication.instance() or QApplication([])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtShellTests(unittest.TestCase):
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
        # A failed calculation reopens the dialog; in a test it must fail instead of waiting for a click.
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def run_method(self, method, options):
        title = self.window.selected[1] if self.window.selected[0] == "data" else self.window.project.runs[
            self.window.selected[1]].title
        frame = self.window.project.tables[title].frame(mask_excluded=True)
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(self.window, frame, current=(method, {}))
        for name, value in options.items():  # Tick the columns a user would tick.
            kind, control = dialog.controls[name]
            if isinstance(value, list) and hasattr(control, "item"):
                for row in range(control.count()):
                    item = control.item(row)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        values = dialog.options()  # The dialog defaults, as a user pressing Run would send them.
        dialog.deleteLater()
        values.update(options)
        candidate = self.window.project.candidate(title, method, values)
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        return self.window.project.runs[-1]

    def open_example(self):
        path = self.folder / "groups.csv"
        pd.DataFrame({"Control": [4.1, 5.0, 4.7, 5.3, 4.9], "Treated": [5.9, 6.3, 6.1, 5.7, 6.6]}).to_csv(
            path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        self.assertEqual(self.window.selected, ("data", "groups"))

    def test_edit_analyse_graph_save_reopen_export(self):
        window = self.window
        self.open_example()
        model = window.sheet.model()
        self.assertTrue(model.setData(model.index(0, 0), "4.4"))
        self.app.processEvents()
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.4)
        window.undo()
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.1)
        window.undo(redo=True)
        self.assertEqual(window.project.tables["groups"].raw.iat[0, 0], 4.4)

        run = self.run_method("Descriptive statistics", {"Variables": ["Control", "Treated"]})
        self.assertIsNotNone(run.result)
        self.assertEqual(window.selected[0], "result")
        self.assertIsNotNone(window.result_tabs)
        self.assertGreater(window.result_tabs.count(), 0)

        # Editing the source recalculates the linked result.
        window.show_sheet("data", "groups")
        model = window.sheet.model()
        model.setData(model.index(1, 0), "9")
        self.app.processEvents()
        self.wait()
        self.assertIsNone(window.project.runs[0].calculation_error)

        window.show_sheet("data", "groups")
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertIsNotNone(graph.result.figure)
        self.assertEqual(window.selected[0], "graph")
        self.assertTrue(window.page.canvases)

        saved = self.folder / "project.alab"
        window.project.save(saved)
        window.refresh()
        self.assertFalse(window.project.dirty)
        window.open_path(saved)
        self.app.processEvents()
        self.assertIn("groups", window.project.tables)
        self.assertEqual(window.project.tables["groups"].raw.iat[1, 0], 9.0)
        self.assertGreaterEqual(len(window.project.runs), 1)
        # Opened results are recalculated on first view.
        window.open_sheet(("result", 0))
        self.wait()
        self.assertIsNotNone(window.project.runs[0].result)

        from trama_qt.window import safe_csv, save_figure
        table = next(iter(window.project.runs[0].result.tables.values()))
        safe_csv(self.folder / "table.csv", table, index=True)
        self.assertTrue((self.folder / "table.csv").stat().st_size > 0)
        if graph is not None:
            index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
            window.open_sheet(("graph", index))
            self.wait()
            figure = window.project.runs[index].result.figure
            canvas = figure.canvas
            save_figure(figure, self.folder / "graph.svg", dpi=300)
            self.assertIs(figure.canvas, canvas)
            self.assertTrue((self.folder / "graph.svg").read_text(encoding="utf-8").lstrip().startswith("<?xml"))

    def format_with(self, run, change):
        from trama_qt.graph_format import GraphFormatDialog
        style, xy = self.window.project.format_inputs(run)
        dialog = GraphFormatDialog(self.window, run.result.figure.axes[0], style, xy=xy)
        change(dialog)
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        self.window.project.apply_format(run, dialog.result, xy_update=dialog.xy_update, xy_result=dialog.xy_result)
        dialog.deleteLater()
        return dialog.result

    def test_format_graph_round_trip(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertTrue(window.actions["format_graph"].isEnabled())

        def change(dialog):
            dialog.texts["title"].setText("Formatted")
            dialog.fonts["title_size"].setText("15")
            dialog.axis_fields["y"]["min"].setText("0")
            dialog.axis_fields["y"]["max"].setText("10")
            dialog.references.setPlainText("Y, 5, limit")

        style = self.format_with(graph, change)
        self.assertEqual(style["title"], "Formatted")
        axes = graph.result.figure.axes[0]
        self.assertEqual(axes.get_title(), "Formatted")
        self.assertEqual(axes.get_ylim(), (0.0, 10.0))
        self.assertTrue(window.project.dirty)

        # A bad value stays in the dialog with a message instead of reaching the graph.
        from trama_qt.graph_format import GraphFormatDialog
        current, xy = window.project.format_inputs(graph)
        dialog = GraphFormatDialog(window, axes, current, xy=xy)
        dialog.axis_fields["y"]["min"].setText("abc")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.text())
        dialog.deleteLater()

        saved = self.folder / "styled.alab"
        window.project.save(saved)
        window.open_path(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        reopened = window.project.runs[index]
        self.assertEqual(reopened.style["title"], "Formatted")
        self.assertEqual(reopened.result.figure.axes[0].get_title(), "Formatted")

    def test_format_xy_graph_recipe(self):
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})

        def change(dialog):
            dialog.selector.setCurrentIndex(0)
            dialog.draw.set("Line and points")
            dialog.right["title"].setText("Right")

        self.format_with(graph, change)
        self.assertEqual(graph.options["Series style"], {"Treated": "Line and points"})
        self.assertEqual(window.project.tables["groups"].analyses[graph.slot][1]["Series style"],
                         {"Treated": "Line and points"})

    def test_layout_compose_edit_reopen(self):
        from trama_qt.layout_dialog import LayoutDialog
        window = self.window
        self.open_example()
        self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.show_sheet("data", "groups")
        self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        candidates = window.project.layout_candidates()
        self.assertEqual(len(candidates), 2)
        dialog = LayoutDialog(window, candidates)
        dialog.accept()
        self.assertIsNone(dialog.result)  # No panels yet.
        self.assertTrue(dialog.problem.text())
        dialog.available.selectAll()
        dialog.add_selected()
        dialog.panels.setCurrentRow(1)
        dialog.move_selected(-1)
        dialog.name.setText("Figura 1")
        dialog.accept()
        layout = dialog.result
        self.assertEqual(layout.panels, [candidates[1].reference, candidates[0].reference])
        key = window.project.put_layout(layout)
        window.open_sheet(("layout", key))
        self.wait()
        self.assertEqual(window.selected, ("layout", key))
        self.assertTrue(window.page.canvases)
        self.assertTrue(window.actions["edit_layout"].isEnabled())

        saved = self.folder / "layout.alab"
        window.project.save(saved)
        window.open_path(saved)
        self.assertEqual([item.name for item in window.project.layouts], ["Figura 1"])
        window.open_sheet(("layout", 0))
        self.wait()
        self.assertIsNotNone(window.project.layout_figure(window.project.layouts[0]))

    def test_insert_delete_rename_and_exclude(self):
        window = self.window
        self.open_example()
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.insert_row()
        self.assertEqual(len(window.project.tables["groups"].raw), 6)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.delete_rows()
        self.assertEqual(len(window.project.tables["groups"].raw), 5)
        window.sheet.setCurrentIndex(window.sheet.model().index(2, 1))
        window.toggle_exclusion()
        self.assertIn((2, 1), window.project.tables["groups"].excluded)
        window.project.rename_column("groups", 1, "Drug")
        self.assertEqual(list(window.project.tables["groups"].raw.columns), ["Control", "Drug"])

    def test_every_dialog_builds_and_reads_its_defaults(self):
        from analisi.workbench import METHODS
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.DataFrame({"X": [1.0, 2, 3, 4, 5, 6], "Y": [2.0, 4, 5, 4, 6, 8],
                              "Group": ["a", "a", "b", "b", "c", "c"], "Time": [1.0, 2, 3, 4, 5, 6],
                              "Event": [1, 0, 1, 1, 0, 1]})
        failures = []
        for method in METHODS:
            try:
                dialog = AnalysisDialog(None, frame, current=(method, {}))
                self.assertEqual(dialog.method, method)
                try:
                    dialog.options()
                except ValueError:
                    pass  # A missing required column is reported to the user, not a crash.
                dialog.deleteLater()
            except Exception as error:  # noqa: BLE001
                failures.append(f"{method}: {type(error).__name__}: {error}")
        self.app.processEvents()
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
