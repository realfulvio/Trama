"""Fit the rendered graph or paper and change a graph recipe through the Classica commands."""
from os import environ
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtGraphCommandsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from trama_qt import theme

        cls.app = QApplication.instance() or QApplication(
            ["trama-qt-graph-commands", "-platform", environ.get("QT_QPA_PLATFORM", "offscreen")])
        theme.load_fonts()
        theme.apply(cls.app)

    def setUp(self):
        from trama_qt.window import MainWindow

        self.window = MainWindow()
        self.window.error = lambda error: self.fail(f"Unexpected dialog: {error}")
        self.addCleanup(self.close_window)
        self.window.resize(1120, 670)
        self.window.show()
        self.project = self.window.project
        self.title, = self.project.add_tables({"Observations": pd.DataFrame({
            "Untreated": [2, 4, 6, 8], "Treated": [3, 5, 8, 11], "Other": [7, 9, 10, 12],
        })})
        self.window.show_sheet("data", self.title)
        self.app.processEvents()

    def close_window(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self):
        deadline = time.monotonic() + 15
        while self.window.job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        self.assertIsNone(self.window.job)

    def add_run(self, method, options, *, source=None):
        from trama_qt.project import compute

        run = self.project.candidate(self.title, method, options, source=source)
        self.project.add_result(run, compute(run, self.project.input_frame(run)))
        return run

    def zoom_axes(self):
        toolbar = self.window.plot_tools
        canvas = toolbar.canvas
        canvas.draw()
        axes = canvas.figure.axes[0]
        bounds = axes.bbox
        ratio = canvas.device_pixel_ratio

        def point(fraction):
            return QPoint(round((bounds.x0 + fraction * bounds.width) / ratio),
                          canvas.height() - round((bounds.y0 + fraction * bounds.height) / ratio))

        toolbar._actions["zoom"].trigger()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point(.2))
        QTest.mouseMove(canvas, point(.75))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point(.75))
        self.app.processEvents()
        toolbar._actions["zoom"].trigger()

    def test_graph_and_native_layout_view_commands_restore_the_full_view(self):
        from analisi.presentation import Layout
        from trama_qt.strings import qt

        window = self.window
        fit_graph = window.actions["fit_graph"]
        fit_page = window.actions["fit_layout_page"]
        self.assertIn(fit_graph, window.command_menus["View"].actions())
        self.assertIn(fit_page, window.command_menus["View"].actions())
        self.assertFalse(fit_graph.isEnabled())
        self.assertFalse(fit_page.isEnabled())
        graph = self.add_run("Histogram", {"Response": "Treated", "Bins": 4})
        window.show_sheet("graph", 0)
        self.app.processEvents()
        axes = graph.result.figure.axes[0]
        full = axes.get_xlim(), axes.get_ylim()
        self.assertTrue(fit_graph.isEnabled())
        self.assertFalse(fit_page.isEnabled())
        self.assertEqual(window.plot_tools.fit_action.text(), qt("qt.fit_graph"))
        self.zoom_axes()
        zoomed = axes.get_xlim(), axes.get_ylim()
        self.assertNotEqual(zoomed, full)
        self.project.dirty = False
        fit_graph.trigger()
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), full)
        self.assertFalse(self.project.dirty)
        window.plot_tools._actions["back"].trigger()
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), zoomed)
        window.show_sheet("data", self.title)
        window.show_sheet("graph", 0)
        self.app.processEvents()
        fit_graph.trigger()
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), full)

        key = self.project.put_layout(Layout("Figure", 1, [graph.reference], "A4 portrait"))
        window.show_sheet("layout", key)
        self.app.processEvents()
        canvas = window.plot_tools.canvas
        axes = canvas.figure.axes[0]
        full = axes.get_xlim(), axes.get_ylim()
        paper = tuple(canvas.figure.get_size_inches())
        self.assertFalse(fit_graph.isEnabled())
        self.assertTrue(fit_page.isEnabled())
        self.assertFalse(fit_page.isCheckable())
        self.zoom_axes()
        self.assertNotEqual((axes.get_xlim(), axes.get_ylim()), full)
        fit_page.trigger()
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), full)
        self.assertEqual(tuple(canvas.figure.get_size_inches()), paper)
        self.assertLessEqual(canvas.height(), canvas.parentWidget().height())

    def test_saved_layout_fit_menu_and_toolbar_share_the_scroll_mode(self):
        from matplotlib.figure import Figure
        from analisi.legacy_restore import SAVED_BINARY_LAYOUT
        from analisi.legacy_zip_layout import ZIP_LAYOUT
        from analisi.workbench import Result
        from trama_qt.project import Run
        from trama_qt.window import ImportedPaperPreview

        window = self.window
        paper = (8.5, 14)
        figure = Figure(figsize=paper)
        figure.add_subplot().plot([0, 1], [1, 2])
        run = Run(SAVED_BINARY_LAYOUT, self.title, {ZIP_LAYOUT: {"paper": paper}})
        self.project.add_result(run, Result({}, figure))
        window.show_sheet("saved-layout", 0)
        self.app.processEvents()
        preview = window.page.findChild(ImportedPaperPreview)
        scroll = preview.verticalScrollBar()
        fit = window.actions["fit_layout_page"]
        toolbar_fit = window.plot_tools.fit_action
        self.assertTrue(fit.isEnabled())
        self.assertTrue(fit.isCheckable())
        self.assertFalse(fit.isChecked())
        self.assertGreater(scroll.maximum(), 0)
        fit.trigger()
        self.app.processEvents()
        self.assertTrue(toolbar_fit.isChecked())
        self.assertEqual(scroll.maximum(), 0)
        self.assertEqual(tuple(figure.get_size_inches()), paper)
        toolbar_fit.trigger()
        self.app.processEvents()
        self.assertFalse(fit.isChecked())
        self.assertGreater(scroll.maximum(), 0)
        window.show_sheet("data", self.title)
        self.assertFalse(fit.isEnabled())
        self.assertFalse(fit.isChecked())
        self.assertFalse(fit.isCheckable())

    def select_graph_type(self, dialog, method):
        from trama_qt.project import GRAPH_TYPE_METHODS
        from trama_qt.strings import qt

        self.assertEqual(dialog.windowTitle(), qt("qt.graph_type_title"))
        methods = {}
        for row in range(dialog.methods.topLevelItemCount()):
            group = dialog.methods.topLevelItem(row)
            for index in range(group.childCount()):
                item = group.child(index)
                methods[item.data(0, Qt.ItemDataRole.UserRole)] = item
        self.assertEqual(set(methods), set(GRAPH_TYPE_METHODS))
        dialog.methods.setCurrentItem(methods[method])

    def test_in_place_conversion_keeps_links_and_reloads_the_layout(self):
        from analisi.analysis_chain import ResultSource
        from analisi.category_graphs import COLUMN_GRAPH, GROUPED_GRAPH
        from analisi.presentation import Layout
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.strings import qt

        window = self.window
        source = self.add_run("Transform", {"Variables": ["Untreated", "Treated", "Other"],
                                            "Operation": "Absolute value"})
        input_ref = ResultSource(source.uid, "Transformed")
        graph = self.add_run(COLUMN_GRAPH, {"Variables": ["Treated", "Untreated"]}, source=input_ref)
        graph.label = "Study"
        style = {"title": "Observations", "grid": True, "axis": {"y": {"min": 0, "max": 30}}}
        self.project.apply_format(graph, style)
        child_link = ResultSource(graph.uid, "Graph data")
        child = self.add_run("Descriptive statistics", {"Variables": ["N"]}, source=child_link)
        old_summary = child.result
        layout = self.project.put_layout(Layout("Figure", 1, [graph.reference]))
        window.show_sheet("graph", 1)
        change = window.actions["change_graph_type"]
        self.assertIn(change, window.command_menus["Change"].actions())
        self.assertTrue(change.isEnabled())

        def choose(dialog):
            self.select_graph_type(dialog, GROUPED_GRAPH)
            columns = dialog.controls["Variables"][1]
            checked = [columns.item(row).text() for row in range(columns.count())
                       if columns.item(row).checkState() == Qt.CheckState.Checked]
            self.assertEqual(checked, ["Treated", "Untreated"])
            self.assertEqual(dialog.run_button.text(), qt("qt.apply_graph_type"))
            dialog.accept()
            self.assertIsNotNone(dialog.result)
            return AnalysisDialog.DialogCode.Accepted

        with patch.object(AnalysisDialog, "exec", choose):
            change.trigger()
            self.wait()

        converted = self.project.runs[1]
        self.assertEqual(converted.method, GROUPED_GRAPH)
        self.assertEqual((converted.uid, converted.reference, converted.source, converted.label),
                         (graph.uid, graph.reference, input_ref, "Study"))
        self.assertEqual(converted.style, {"title": "Observations", "grid": True})
        self.assertEqual(self.project.tables[self.title].graph_styles[graph.slot], converted.style)
        self.assertEqual(self.project.layouts[layout].panels, [converted.reference])
        self.assertEqual(child.source, child_link)
        self.assertIsNot(child.result, old_summary)
        self.assertIsNone(child.calculation_error)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "converted.alab"
            self.project.save(path)
            self.assertTrue(window.close_project())
            window.open_path(path)
            window.open_sheet(("layout", layout))
            self.wait()
            restored = window.project.runs[1]
            self.assertEqual((restored.uid, restored.reference, restored.source, restored.method, restored.style),
                             (graph.uid, graph.reference, input_ref, GROUPED_GRAPH, converted.style))
            self.assertEqual(window.project.runs[2].source, child_link)
            self.assertTrue(window.actions["fit_layout_page"].isEnabled())

    def test_incompatible_link_leaves_recipe_and_figure_intact(self):
        from analisi.analysis_chain import ResultSource
        from analisi.category_graphs import COLUMN_GRAPH
        from analisi.presentation import Layout
        from trama_qt.analysis_dialog import AnalysisDialog
        from trama_qt.strings import qt

        graph = self.add_run(COLUMN_GRAPH, {"Variables": ["Treated", "Untreated"]})
        child_link = ResultSource(graph.uid, "Graph data")
        self.add_run("Descriptive statistics", {"Variables": ["N"]}, source=child_link)
        layout = self.project.put_layout(Layout("Figure", 1, [graph.reference]))
        self.project.dirty = False
        self.window.show_sheet("graph", 0)
        shown = self.project.runs[0].result.figure

        def choose(dialog):
            self.select_graph_type(dialog, "Histogram")
            dialog.accept()
            self.assertIsNotNone(dialog.result)
            return AnalysisDialog.DialogCode.Accepted

        errors = []
        self.window.error = errors.append
        with patch.object(AnalysisDialog, "exec", choose):
            self.window.actions["change_graph_type"].trigger()
            self.wait()
        self.assertEqual([str(error) for error in errors], [qt("qt.graph_type_linked_result", name="Graph data")])
        self.assertIs(self.project.runs[0], graph)
        self.assertIs(graph.result.figure, shown)
        self.assertEqual(self.project.runs[1].source, child_link)
        self.assertEqual(self.project.layouts[layout].panels, [graph.reference])
        self.assertFalse(self.project.dirty)

    def test_saved_drawing_and_analysis_graph_keep_their_recipe(self):
        from matplotlib.figure import Figure
        from analisi.legacy_restore import SAVED_BINARY_GRAPH
        from analisi.workbench import Result
        from trama_qt.project import Run

        window = self.window
        self.add_run("Linear regression", {"X": "Untreated", "Y": "Treated"})
        stored = Run(SAVED_BINARY_GRAPH, self.title, {})
        figure = Figure()
        figure.add_subplot().plot([0, 1], [0, 1])
        self.project.add_result(stored, Result({}, figure))
        for index in range(2):
            window.show_sheet("graph", index)
            self.app.processEvents()
            self.assertFalse(window.actions["change_graph_type"].isEnabled())
            self.assertTrue(window.actions["fit_graph"].isEnabled())
