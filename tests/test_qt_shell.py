"""The Qt window end to end, offscreen: open, edit, analyse, graph, save, reopen, export.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
from pathlib import Path
import tempfile
import time
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import tr

ROOT = Path(__file__).resolve().parent.parent


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
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

    def reopen(self, path):
        """Read a saved project back from disk. Opening a file that is already open only shows its tab, so the
        project closes first (it was just saved) and opens again in the tab left empty."""
        self.assertTrue(self.window.close_project())
        self.assertTrue(self.window.project.is_empty())
        self.window.open_path(path)
        self.app.processEvents()
        self.assertEqual(Path(self.window.project.path), Path(path))

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
        self.reopen(saved)
        self.app.processEvents()
        self.assertIn("groups", window.project.tables)
        self.assertEqual(window.project.tables["groups"].raw.iat[1, 0], 9.0)
        self.assertGreaterEqual(len(window.project.runs), 1)
        # Opened results are recalculated on first view.
        window.open_sheet(("result", 0))
        self.wait()
        self.assertIsNotNone(window.project.runs[0].result)

        from trama_qt.window import export_graph, safe_csv
        table = next(iter(window.project.runs[0].result.tables.values()))
        safe_csv(self.folder / "table.csv", table, index=True)
        self.assertTrue((self.folder / "table.csv").stat().st_size > 0)
        if graph is not None:
            index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
            window.open_sheet(("graph", index))
            self.wait()
            figure = window.project.runs[index].result.figure
            canvas = figure.canvas
            export_graph(figure, self.folder / "graph.svg")
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
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        reopened = window.project.runs[index]
        self.assertEqual(reopened.style["title"], "Formatted")
        self.assertEqual(reopened.result.figure.axes[0].get_title(), "Formatted")

    def test_inspector_preview_apply_and_cancel(self):
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.toggle_inspector()
        inspector = window.inspector
        self.assertIs(graph.result.figure.canvas, inspector.canvas)
        self.assertIsNotNone(inspector)
        axes = graph.result.figure.axes[0]
        inspector.widgets["title"].setText("Anteprima")
        inspector._now("title")
        self.assertEqual(axes.get_title(), "Anteprima")  # Previewed on the live figure...
        self.assertNotEqual((graph.style or {}).get("title"), "Anteprima")  # ...not yet confirmed.
        inspector.widgets["ymin"].setText("1")
        inspector._now("yrange")
        self.assertIn("yrange", inspector.errors)  # Both limits are needed.
        inspector.widgets["ymax"].setText("9")
        inspector._now("yrange")
        self.assertNotIn("yrange", inspector.errors)
        self.assertEqual(axes.get_ylim(), (1.0, 9.0))
        self.assertTrue(inspector.apply())
        self.assertEqual(graph.style["title"], "Anteprima")
        self.assertEqual(window.project.tables["groups"].graph_styles[graph.slot]["title"], "Anteprima")

        inspector.widgets["title"].setText("Bozza")
        inspector._now("title")
        self.assertTrue(inspector.has_draft)
        inspector.cancel()  # Closing restores the confirmed style.
        self.assertIsNone(window.inspector)
        self.assertEqual(axes.get_title(), "Anteprima")

        # Leaving the graph with a draft also restores the confirmed style; the panel comes back on the graph.
        window.toggle_inspector()
        window.inspector.widgets["title"].setText("Bozza")
        window.inspector._now("title")
        window.show_sheet("data", "groups")
        self.assertEqual(axes.get_title(), "Anteprima")
        window.inspector_wanted = True
        window.show_sheet("graph", window.project.runs.index(graph))
        self.assertIsNotNone(window.inspector)

    def test_annotations(self):
        from trama_qt.annotations import AnnotationEditor, GraphAnnotationsDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        axes = graph.result.figure.axes[0]
        editor = AnnotationEditor(window, axes)
        editor.accept()
        self.assertIsNone(editor.result)  # Empty text.
        editor.text.setPlainText("p < 0,05")
        editor.arrow.setChecked(True)
        editor.target[0].setText("0,5")
        editor.accept()
        self.assertEqual(editor.result["target"], [0.5, 0.5])
        dialog = GraphAnnotationsDialog(window, axes, [])
        dialog.records.append(editor.result)
        dialog.fill(0)
        dialog.accept()
        style = dict(graph.style or {}, annotations=dialog.result)
        window.project.apply_format(graph, style)
        self.assertIn("p < 0,05", [text.get_text() for text in axes.texts])
        saved = self.folder / "notes.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        self.assertEqual(window.project.runs[index].style["annotations"][0]["text"], "p < 0,05")

    def test_axis_guides_and_bands(self):
        from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
        from trama_qt.axis_guides import AxisBandsDialog, AxisGuidesDialog, BandEditor, GuideEditor
        from trama_qt.graph_format import GraphFormatDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        axes = graph.result.figure.axes[0]
        guide = GuideEditor(window, axes)
        self.assertEqual(guide.fields["axis"].value(), "y")  # X is categorical.
        guide.fields["value"].setText("abc")
        guide.accept()
        self.assertIsNone(guide.result)
        self.assertTrue(guide.problem.text())
        guide.fields["value"].setText("2,5")
        guide.fields["label"].setText("soglia")
        guide.accept()
        self.assertEqual(guide.result["value"], 2.5)
        band = BandEditor(window, axes)
        band.fields["lower"].setText("4")
        band.fields["upper"].setText("1")
        band.accept()
        self.assertIsNone(band.result)  # Lower above upper.
        band.fields["upper"].setText("6")
        band.accept()
        self.assertEqual((band.result["lower"], band.result["upper"]), (4.0, 6.0))

        current, xy = window.project.format_inputs(graph)
        dialog = GraphFormatDialog(window, axes, current, xy=xy)
        guides = AxisGuidesDialog(dialog, axes, [], {"y": "linear"})
        guides.records.append(guide.result)
        guides.fill(0)
        guides.duplicate()
        self.assertEqual(len(guides.records), 2)
        guides.remove()
        guides.accept()
        bands = AxisBandsDialog(dialog, axes, [band.result])
        bands.accept()
        dialog.guide_records[AXIS_GUIDES], dialog.guide_records[AXIS_BANDS] = guides.result, bands.result
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
        window.project.apply_format(graph, dialog.result)
        saved = self.folder / "guides.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        style = window.project.runs[index].style
        self.assertEqual(style[AXIS_GUIDES][0]["label"], "soglia")
        self.assertEqual(style[AXIS_BANDS][0]["upper"], 6.0)

    def test_shapes(self):
        from analisi.graph_shapes import SHAPES
        from trama_qt.shapes import GraphShapesDialog, ShapeEditor
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        self.assertTrue(window.actions["shapes"].isEnabled())
        axes = graph.result.figure.axes[0]
        editor = ShapeEditor(window, axes)
        self.assertFalse(editor.fields["fill"].isEnabled())  # A line has no interior.
        editor.fields["x2"].setText("0,2")
        editor.fields["y2"].setText("0,3")
        editor.accept()
        self.assertIsNone(editor.result)  # Zero-length line.
        self.assertTrue(editor.problem.text())
        editor.fields["kind"].set("rectangle")
        self.assertTrue(editor.fields["fill"].isEnabled())
        editor.fields["x2"].setText("0,6")
        editor.fields["y2"].setText("0,8")
        editor.fields["fill"].setText("#ffeeaa")
        editor.fields["hatch"].set("diagonal")
        editor.accept()
        rectangle = editor.result
        self.assertEqual(rectangle["points"], [[0.2, 0.3], [0.6, 0.8]])
        dialog = GraphShapesDialog(window, axes, [rectangle])
        dialog.duplicate()
        dialog.move(-1)
        self.assertEqual(len(dialog.records), 2)
        dialog.remove()
        dialog.accept()
        window.project.apply_format(graph, dict(graph.style or {}, shapes=dialog.result))
        saved = self.folder / "shapes.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "Column graph")
        window.open_sheet(("graph", index))
        self.wait()
        self.assertEqual(window.project.runs[index].style[SHAPES][0]["hatch"], "diagonal")

    def test_pairwise_comparisons_and_letters(self):
        from unittest import mock
        from analisi import pairwise_graph as pg
        from trama_qt.pairwise import PairwiseDialog
        window = self.window
        self.open_example()
        self.run_method("Paired t-test (columns)", {"First": "Control", "Second": "Treated"})
        window.open_sheet(("data", "groups"))
        self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        index = len(window.project.runs) - 1
        window.open_sheet(("graph", index))
        self.wait()
        self.assertTrue(window.actions["pairwise"].isEnabled())
        seen = {}

        def run_dialog(dialog):
            seen["rows"] = len(dialog.rows)
            dialog.cutoff.setText("2")
            dialog.filter.set(pg.AT_OR_BELOW)
            dialog.accept()
            seen["problem"] = dialog.problem.text()
            dialog.cutoff.setText("0,05")
            dialog.filter.set(pg.NO_FILTER)
            dialog.label.set(pg.P_VALUE)
            dialog.accept()
            return PairwiseDialog.DialogCode.Accepted

        with mock.patch.object(PairwiseDialog, "exec", run_dialog):
            window.pairwise_comparisons()
            self.wait()
        self.assertEqual(seen["rows"], 1)
        self.assertTrue(seen["problem"])  # Cutoff above 1.
        run = window.project.runs[index]
        self.assertEqual(run.options[pg.SECTION]["Label"], pg.P_VALUE)
        self.assertTrue(pg.drawn_brackets(run.result.figure))

        def letters(dialog):
            self.assertEqual(dialog.display.value(), pg.LETTERS)
            dialog.accept()
            return PairwiseDialog.DialogCode.Accepted

        window.open_sheet(("graph", index))
        with mock.patch.object(PairwiseDialog, "exec", letters):
            window.pairwise_comparisons(letters=True)
            self.wait()
        run = window.project.runs[index]
        self.assertEqual(run.options[pg.SECTION]["Display"], pg.LETTERS)
        self.assertTrue(pg.drawn_letters(run.result.figure))

    def test_duplicate_and_save_family(self):
        from unittest import mock
        from trama_qt.family import FamilyDialog
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("data", "groups"))
        self.assertTrue(window.actions["duplicate_family"].isEnabled())
        seen = {}

        def duplicate(dialog):
            seen["preview"] = dialog.preview.toPlainText()
            dialog.name.setText("groups")
            dialog.accept()
            seen["problem"] = dialog.problem.text()  # The name is taken.
            dialog.name.setText("Repeat")
            dialog.accept()
            return FamilyDialog.DialogCode.Accepted

        with mock.patch.object(FamilyDialog, "exec", duplicate):
            window.duplicate_family()
            self.wait()
        self.assertIn("Column graph", seen["preview"])
        self.assertTrue(seen["problem"])
        self.assertIn("Repeat", window.project.tables)
        self.assertEqual([run.method for run in window.project.runs if run.title == "Repeat"], ["Column graph"])
        self.assertEqual(window.selected, ("data", "Repeat"))
        self.assertTrue(window.project.dirty)

        target = self.folder / "family.alab"
        window.open_sheet(("graph", window.project.runs.index(graph)))
        self.wait()
        with mock.patch.object(FamilyDialog, "exec", lambda dialog: dialog.accept() or FamilyDialog.DialogCode.Accepted), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window.save_family_as()
            self.wait()
        self.assertTrue(target.exists())
        from analisi.data import load_workspace
        tables, _, _ = load_workspace(target, include_info=True)
        self.assertEqual(list(tables), ["groups"])

    def test_info_sheet_editing(self):
        from unittest import mock
        from analisi.info import NOTE_BOLD
        from trama_qt.info_editor import InfoDetails
        window = self.window
        self.open_example()

        def details(dialog):
            dialog.title.setText("Esperimento")
            dialog.scope.setCurrentIndex(1)  # The groups table.
            dialog.accept()
            return InfoDetails.DialogCode.Accepted

        with mock.patch.object(InfoDetails, "exec", details):
            window.new_info()
        self.assertEqual(window.selected[0], "info")
        uid = window.selected[1]
        editor = window.info_editor
        editor.add_row()
        row = len(editor.sheet.fields) - 1
        editor.table.item(row, 0).setText("Dose")
        editor.table.item(row, 1).setText("10")
        self.assertEqual(window.project.tables["groups"].info.get("dose"), "10")
        editor.notes.setPlainText("Nota importante")
        cursor = editor.notes.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(15, cursor.MoveMode.KeepAnchor)
        editor.notes.setTextCursor(cursor)
        editor.toggle_style(NOTE_BOLD)
        window.open_sheet(("data", "groups"))  # Leaving the sheet stores the notes.
        sheet = window.project.info_sheets[uid]
        self.assertEqual((sheet.notes, sheet.note_styles), ("Nota importante", ((5, 15, NOTE_BOLD),)))
        saved = self.folder / "info.alab"
        window.project.save(saved)
        self.reopen(saved)
        sheet = next(iter(window.project.info_sheets.values()))
        self.assertEqual((sheet.title, sheet.table), ("Esperimento", "groups"))
        self.assertIn(("Dose", "10"), sheet.fields)
        self.assertEqual(sheet.note_styles, ((5, 15, NOTE_BOLD),))
        window.open_sheet(("info", sheet.uid))
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            window.remove_info()
        self.assertFalse(window.project.info_sheets)

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

    def test_axis_breaks_on_xy_graph(self):
        from analisi.axis_breaks import AXIS_BREAKS
        from trama_qt.axis_breaks import AxisBreaksDialog
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})
        axes = graph.result.figure.axes[0]
        dialog = AxisBreaksDialog(window, axes, {})
        self.assertFalse(dialog.gap.isEnabled())
        dialog.axis.set("y")
        dialog.count.set("2")
        for (row, name), text in {(0, "low"): "5,5", (0, "high"): "6", (0, "share"): "50",
                                  (1, "low"): "6,2", (1, "high"): "6,8", (1, "share"): "40"}.items():
            dialog.cells[(row, name)].setText(text)
        dialog.accept()
        self.assertIsNone(dialog.result)  # Shares add up to 90.
        self.assertTrue(dialog.problem.text())
        dialog.cells[(1, "share")].setText("50")
        dialog.accept()
        record = dialog.result
        self.assertEqual(record["axis"], "y")

        def change(format_dialog):
            self.assertIsNotNone(format_dialog.breaks_summary)
            format_dialog.axis_breaks = record
            format_dialog._break_states()
            self.assertFalse(format_dialog.axis_fields["y"]["min"].isEnabled())

        style = self.format_with(graph, change)
        self.assertEqual(style[AXIS_BREAKS]["segments"][1]["low"], 6.2)
        saved = self.folder / "breaks.alab"
        window.project.save(saved)
        self.reopen(saved)
        index = next(i for i, r in enumerate(window.project.runs) if r.method == "XY series")
        window.open_sheet(("graph", index))
        self.wait()
        self.assertEqual(window.project.runs[index].style[AXIS_BREAKS]["axis"], "y")

    def test_legend_formatting(self):
        from analisi.graph_legend import LEGEND_OPTIONS_KEY
        from trama_qt.legend import LegendEditor
        window = self.window
        self.open_example()
        graph = self.run_method("XY series", {"X": "Control", "Y columns": ["Treated"]})
        figure = graph.result.figure
        editor = LegendEditor(window, figure, {})
        self.assertFalse(editor.non_native)
        editor.title.setText("Gruppi")
        editor.columns.setText("abc")
        editor.accept()
        self.assertIsNone(editor.result)
        self.assertTrue(editor.problem.text())
        editor.columns.setText("1")
        editor.frame.set("hidden")
        editor.accept()
        options = editor.result
        self.assertEqual(options["title"], "Gruppi")
        self.assertIs(options["frame"], False)

        def change(dialog):
            dialog.legend_options = options

        style = self.format_with(graph, change)
        self.assertEqual(style[LEGEND_OPTIONS_KEY]["title"], "Gruppi")
        legend = graph.result.figure.axes[0].get_legend() or graph.result.figure.legends[0]
        self.assertEqual(legend.get_title().get_text(), "Gruppi")

    def test_export_with_options(self):
        from unittest import mock
        from PIL import Image
        from trama_qt import export_options
        from trama_qt.export_options import ExportOptionsDialog
        self.addCleanup(lambda: (export_options.SESSION.clear(),
                                 export_options.SESSION.update(preset="Screen", **export_options.fe.PRESETS["Screen"])))
        window = self.window
        self.open_example()
        graph = self.run_method("Column graph", {"Variables": ["Control", "Treated"]})
        window.open_sheet(("graph", window.project.runs.index(graph)))
        self.wait()
        self.assertTrue(window.actions["export_options"].isEnabled())
        seen = {}

        def png(dialog):
            dialog.format.setCurrentText("PNG")
            dialog.width.setText("abc")
            dialog.accept()
            seen["problem"] = dialog.summary.text()
            dialog.width.setText("85")
            dialog.dpi.setText("200")
            seen["preset"] = dialog.preset.currentData()
            seen["summary"] = dialog.summary.text()
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        target = self.folder / "graph"
        with mock.patch.object(ExportOptionsDialog, "exec", png), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window.export_with_options()
        self.assertTrue(seen["problem"])
        self.assertEqual(seen["preset"], "Custom")
        self.assertIn("669", seen["summary"])
        with Image.open(self.folder / "graph.png") as image:
            self.assertEqual(image.size[0], 669)
        self.assertEqual(export_options.SESSION["width_mm"], 85)

        # The next dialog starts from the session's choices; SVG text as paths.
        def svg(dialog):
            seen["width"] = dialog.width.text()
            dialog.format.setCurrentText("SVG")
            dialog.svg_text.setCurrentIndex(1)
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        with mock.patch.object(ExportOptionsDialog, "exec", svg), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName",
                           return_value=(str(self.folder / "graph.svg"), "")):
            window.export_with_options()
        self.assertEqual(seen["width"], "85")
        text = (self.folder / "graph.svg").read_text(encoding="utf-8")
        self.assertIn("<path", text)
        self.assertNotIn("<text", text)
        self.assertEqual(export_options.SESSION["svg_text"], "paths")  # The next dialog starts from Paths.
        dialog = ExportOptionsDialog(window, (4, 3))
        self.assertEqual(dialog.svg_text.currentData(), "paths")
        dialog.deleteLater()

        # A layout: vector PDF at a chosen width.
        window.show_sheet("data", "groups")
        self.run_method("Box / violin plot", {"Variables": ["Control", "Treated"]})
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        key = window.project.put_layout(Layout("Figura", 2, [run.reference for run in window.project.runs],
                                               AUTO_PAPER, WHITE))
        window.open_sheet(("layout", key))
        self.wait()

        def pdf(dialog):
            seen["layout_note"] = dialog.note.text()
            dialog.format.setCurrentText("PDF")
            dialog.width.setText("180")
            dialog.accept()
            return ExportOptionsDialog.DialogCode.Accepted

        with mock.patch.object(ExportOptionsDialog, "exec", pdf), \
                mock.patch("trama_qt.window.QFileDialog.getSaveFileName",
                           return_value=(str(self.folder / "layout.pdf"), "")):
            window.export_with_options()
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(str(self.folder / "layout.pdf"))[0]
        self.assertAlmostEqual(page.get_width() / 72 * 25.4, 180, delta=0.5)

    def test_analysis_chains(self):
        from unittest import mock
        from analisi.analysis_chain import ResultSource
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.analysis_source import AnalysisSourceDialog
        window = self.window
        ask = type(window)._ask.__get__(window)  # The dialog opens; a failed calculation still fails the test.
        window._ask = lambda *args, error=None, **kwargs: (self.fail(f"calculation failed: {error}") if error
                                                          else ask(*args, **kwargs))
        path = self.folder / "chain.csv"
        pd.DataFrame({"X": [0.0, 1.0, 2.0, 3.0], "Y": [1.0, 3.0, 5.0, 7.0]}).to_csv(path, index=False)
        window.open_path(path)
        self.app.processEvents()
        self.run_method("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"})
        window.open_sheet(("result", 0))
        self.assertTrue(window.actions["analyze_result"].isEnabled())
        self.assertFalse(window.actions["source_analysis"].isEnabled())

        def pick(method, values):
            def run(dialog):
                if dialog.method != method:
                    dialog.method = method
                    dialog.configure_fields()
                for name, value in values.items():
                    kind, control = dialog.controls[name]
                    if isinstance(value, list):
                        for row in range(control.count()):
                            item = control.item(row)
                            item.setCheckState(Qt.CheckState.Checked if item.text() in value
                                               else Qt.CheckState.Unchecked)
                    else:
                        position = control.findData(value)
                        control.setCurrentIndex(position if position >= 0 else control.findText(value))
                dialog.accept()
                return AnalysisDialog.DialogCode.Accepted if dialog.result else AnalysisDialog.DialogCode.Rejected
            return mock.patch.object(AnalysisDialog, "exec", run)

        with pick("Normalize", {"Variables": ["X", "Y"], "Method": "Subtract first value"}):
            window.analyze_result_table()
            self.wait()
        runs = window.project.runs
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[1].source, ResultSource(runs[0].uid, "Transformed"))
        window.open_sheet(("result", 1))
        self.assertTrue(window.actions["source_analysis"].isEnabled())
        with pick("Linear regression", {"X": "X", "Y": "Y"}):
            window.analyze_result_table()
            self.wait()
        self.assertEqual(runs[2].source, ResultSource(runs[1].uid, "Normalized"))
        self.assertAlmostEqual(runs[2].result.tables["Regression"].loc["Slope", "Value"], 2.0)

        # The navigator nests each linked result under its source.
        def item_for(ref):
            found = []

            def walk(item):
                if item.data(0, Qt.ItemDataRole.UserRole) == ref:
                    found.append(item)
                for child in range(item.childCount()):
                    walk(item.child(child))
            for top in range(window.navigator.topLevelItemCount()):
                walk(window.navigator.topLevelItem(top))
            return found[0]
        self.assertEqual(item_for(("result", 1)).parent().data(0, Qt.ItemDataRole.UserRole), ("result", 0))

        window.open_sheet(("result", 2))
        window.source_analysis()
        self.assertEqual(window.selected, ("result", 1))
        self.assertEqual(window.result_tabs.tabText(window.result_tabs.currentIndex()), "Normalized")

        # Change input result: a cycle is refused in the dialog; the Transform table is accepted.
        window.open_sheet(("result", 0))
        seen = {}

        def cycle(dialog):
            dialog.source.setCurrentIndex(next(i for i, other in enumerate(dialog.parents)
                                               if other is not None and other.uid == runs[2].uid))
            dialog.accept()
            seen["cycle"] = dialog.problem.text()
            return AnalysisSourceDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisSourceDialog, "exec", cycle):
            window.change_input_result()
        self.assertIn(tr("chain.error.cycle"), seen["cycle"])
        self.assertIsNone(runs[0].source)

        def transform(dialog):
            dialog.source.setCurrentIndex(next(i for i, other in enumerate(dialog.parents)
                                               if other is not None and other.uid == runs[0].uid))
            dialog.accept()
            return AnalysisSourceDialog.DialogCode.Accepted

        window.open_sheet(("result", 2))
        with mock.patch.object(AnalysisSourceDialog, "exec", transform), pick("Linear regression", {}):
            window.change_input_result()
            self.wait()
        runs = window.project.runs
        self.assertEqual(runs[2].source, ResultSource(runs[0].uid, "Transformed"))
        self.assertAlmostEqual(runs[2].result.tables["Regression"].loc["Slope", "Value"], 2.0)

        saved = self.folder / "chain.alab"
        window.project.save(saved)
        self.reopen(saved)
        runs = window.project.runs
        self.assertEqual(runs[1].source, ResultSource(runs[0].uid, "Transformed"))
        self.assertEqual(runs[2].source, ResultSource(runs[0].uid, "Transformed"))

    def test_text_import_wizard(self):
        from unittest import mock
        from trama_qt.text_import import TextImportDialog
        window = self.window
        path = self.folder / "misure.txt"
        path.write_text("ID;Dose;Risposta;Note\n1;0,5;10,2;a\n2;1,0;-99;b\n3;1,5;12,9*;c\n4;2,0;14,1;d\n"
                        "5;2,5;15,0;e\n", encoding="utf-8")
        seen = {}

        def choose(dialog):
            seen["first"] = dialog.summary.text()
            dialog.bounds["first_column"].setText("x")
            dialog.refresh_preview()
            seen["problem"] = dialog.summary.text()
            dialog.accept()
            seen["refused"] = dialog.result is None
            dialog.bounds["first_column"].setText("2")
            dialog.bounds["last_column"].setText("3")
            dialog.bounds["last_row"].setText("4")
            dialog.missing.setText("-99")
            dialog.mark_excluded.setChecked(True)
            dialog.refresh_preview()
            seen["preview"] = [dialog.table.horizontalHeaderItem(column).text()
                               for column in range(dialog.table.columnCount())]
            seen["marked"] = dialog.table.item(2, 1).text()
            dialog.accept()
            return TextImportDialog.DialogCode.Accepted

        with mock.patch.object(TextImportDialog, "exec", choose):
            window.open_path(path, import_data=True)
        self.assertIn("5", seen["first"])
        self.assertTrue(seen["problem"])
        self.assertTrue(seen["refused"])
        self.assertEqual(seen["preview"], ["Dose", "Risposta"])
        self.assertEqual(seen["marked"], "* 12.9")
        self.assertEqual(window.selected, ("data", "misure"))
        dataset = window.project.tables["misure"]
        frame = dataset.frame()
        self.assertEqual(list(frame.columns), ["Dose", "Risposta"])
        self.assertEqual(len(frame), 4)
        self.assertAlmostEqual(frame["Dose"].iloc[1], 1.0)
        self.assertTrue(pd.isna(frame["Risposta"].iloc[1]))
        self.assertTrue(pd.isna(dataset.frame(mask_excluded=True)["Risposta"].iloc[2]))

        # Cancel adds nothing.
        with mock.patch.object(TextImportDialog, "exec", lambda dialog: TextImportDialog.DialogCode.Rejected):
            window.open_path(path, import_data=True)
        self.assertEqual(list(window.project.tables), ["misure"])

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
        self.reopen(saved)
        self.assertEqual([item.name for item in window.project.layouts], ["Figura 1"])
        window.open_sheet(("layout", 0))
        self.wait()
        self.assertIsNotNone(window.project.layout_figure(window.project.layouts[0]))

        # Layout export (vector PDF/SVG, raster PNG) and the multi-page PDF of graphs and layouts.
        layout = window.project.layouts[0]
        for name in ("layout.pdf", "layout.svg", "layout.png"):
            window.project.export_layout(layout, self.folder / name)
            self.assertGreater((self.folder / name).stat().st_size, 1000, name)
        from trama_qt.pdf_bundle import PdfBundleDialog, bundle_sheets
        for index in range(len(window.project.runs)):
            window.open_sheet(("graph", index))
            self.wait()
        entries, notes = bundle_sheets(window.project, range(len(window.project.runs)), ())
        self.assertEqual([entry.kind for entry in entries], ["Graph", "Graph", "Layout"])
        dialog = PdfBundleDialog(window, entries, notes)
        dialog.width.setText("abc")
        dialog.accept()
        self.assertIsNone(dialog.result)
        dialog.width.setText("120")
        dialog.list.item(0).setSelected(False)
        dialog.accept()
        self.assertEqual(dialog.result["refs"], [entries[1].ref, entries[2].ref])
        pages = window.project.export_pdf_pages(dialog.result["refs"], self.folder / "bundle.pdf",
                                                dialog.result["settings"], ["a", "b"])
        self.assertEqual(pages, 2)
        import pypdfium2 as pdfium
        self.assertEqual(len(pdfium.PdfDocument(str(self.folder / "bundle.pdf"))), 2)

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

    def test_formula_columns_and_cell_editing(self):
        from unittest import mock
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication as _App
        from trama_qt.formula import FormulaDialog
        window = self.window
        self.open_example()
        self.assertTrue(window.actions["formula"].isEnabled())

        def new_column(dialog):
            dialog.name.setText("Double")
            dialog.expression.setPlainText("=Control *")
            dialog.accept()
            seen["problem"] = dialog.problem.text()
            dialog.expression.setPlainText("=Control * 2")
            dialog.accept()
            return FormulaDialog.DialogCode.Accepted

        seen = {}
        with mock.patch.object(FormulaDialog, "exec", new_column):
            window.edit_formula()
        self.assertTrue(seen["problem"])
        dataset = window.project.tables["groups"]
        self.assertEqual(dataset.formulas, {"Double": "=Control * 2"})
        self.assertAlmostEqual(dataset.frame()["Double"].iloc[0], 8.2)

        # A double click on the calculated column's header opens its formula to change.
        def change(dialog):
            seen["loaded"] = (dialog.name.text(), dialog.expression.toPlainText())
            dialog.expression.setPlainText("=Control * 3")
            dialog.accept()
            return FormulaDialog.DialogCode.Accepted

        with mock.patch.object(FormulaDialog, "exec", change):
            window.rename_column(2)
        self.assertEqual(seen["loaded"], ("Double", "=Control * 2"))
        self.assertAlmostEqual(window.project.tables["groups"].frame()["Double"].iloc[0], 12.3)
        window.undo()
        self.assertEqual(window.project.tables["groups"].formulas["Double"], "=Control * 2")

        # F2, a value and Enter write the cell and move down one row.
        sheet = window.sheet
        sheet.setFocus()
        sheet.setCurrentIndex(sheet.model().index(0, 0))
        QTest.keyClick(sheet, Qt.Key.Key_F2)
        editor = _App.focusWidget()
        editor.setText("9")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.wait()
        self.assertAlmostEqual(window.project.tables["groups"].raw.iloc[0, 0], 9.0)
        self.assertEqual(window.sheet.currentIndex().row(), 1)

    def test_desktop_smoke(self):
        """python -m trama_qt --smoke, in English on the test screen: every dialog fits and nothing is clipped."""
        from trama_qt.smoke import run
        folder = self.folder / "smoke"
        status = run(folder, languages=("en",))
        self.assertEqual(status, "PASS", (folder / "report.txt").read_text(encoding="utf-8"))
        self.assertGreater(len(list(folder.glob("en-*.png"))), 25)

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

    def test_compact_ribbon_keeps_classic_command_reachable(self):
        from PySide6.QtWidgets import QToolButton

        window = self.window
        window.resize(600, 480)
        window.ribbon_tabs.setCurrentIndex(0)
        self.app.processEvents()
        self.assertLessEqual(window.width(), 600)
        toolbar = window.ribbon.currentWidget()
        classic = window.actions["classic"]
        if not toolbar.widgetForAction(classic).isVisible():
            overflow = toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
            self.assertTrue(overflow.isVisible())
            self.assertIn(classic, overflow.menu().actions())


if __name__ == "__main__":
    unittest.main()
