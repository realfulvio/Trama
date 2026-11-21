"""Exercise the same style transaction from both Qt graph editors."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np

from analisi.hierarchical_style import describe_hierarchical_artists, snapshot_hierarchical_style
from analisi.i18n import active_language, set_language, tr
from test_hierarchical_style import _frame, _options, _result

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
except ImportError:
    QApplication = None
else:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from trama_qt.graph_format import GraphFormatDialog
    from trama_qt.hierarchical_style import HierarchicalStyleDialog
    from trama_qt.inspector import GraphInspector
    from trama_qt.project import Project, compute


@unittest.skipUnless(QApplication is not None, "PySide6 unavailable")
class QtHierarchicalStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        language = active_language()
        set_language("it")
        self.addCleanup(set_language, language)

    def track(self, widget):
        def close():
            widget.close()
            widget.deleteLater()
            self.app.processEvents()
        self.addCleanup(close)
        return widget

    def field(self, dialog, field):
        return dialog.fields[field][2]

    def through_editor(self, parent, action):
        """Click the real button and drive its modal child."""
        errors = []

        def drive():
            modal = self.app.activeModalWidget()
            try:
                self.assertIsInstance(modal, HierarchicalStyleDialog)
                action(modal)
            except Exception as error:
                errors.append(error)
                if modal is not None:
                    modal.reject()

        QTimer.singleShot(0, drive)
        control = next(button for button in parent.findChildren(QPushButton)
                       if button.text() == tr("hierarchy.style.button"))
        control.click()
        if errors:
            raise errors[0]

    def test_cluster_legend_updates_with_preview_and_respects_general_legend_formatting(self):
        from copy import deepcopy
        from matplotlib.colors import to_hex
        from analisi.presentation import apply_style

        figure = _result(Direction="Rows", **{"Graph output": "Dendrogram"}).figure
        self.track(FigureCanvasQTAgg(figure))
        section = {"row": {"legend_visible": True, "legend_title": "Saved groups", "color_mode": "cluster",
                           "palette": ["#555555", "#aaaaaa"]}}
        style = {"hierarchical": section, "legend_options": {"title": "User title", "reverse": True}}
        apply_style(figure, style)
        legend, = figure.legends
        self.assertEqual(legend.get_title().get_text(), "User title")
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Cluster 2", "Cluster 1"])
        dialog = self.track(HierarchicalStyleDialog(None, figure, section))
        self.field(dialog, "row.palette").setText("#001122, #ddeeff")
        dialog.preview()
        legend, = figure.legends
        self.assertEqual([to_hex(handle.get_color()) for handle in legend.legend_handles], ["#ddeeff", "#001122"])
        self.assertEqual(legend.get_title().get_text(), "User title")
        self.field(dialog, "row.legend_visible").setChecked(False)
        dialog.preview()
        self.assertFalse(figure.legends)
        dialog.reject()
        legend, = figure.legends
        self.assertEqual([to_hex(handle.get_color()) for handle in legend.legend_handles], ["#aaaaaa", "#555555"])
        apply_style(figure, {**style, "legend": "hidden"})
        self.assertFalse(figure.legends)
        apply_style(figure, style)
        cloned = deepcopy(figure)
        apply_style(cloned, {**style, "legend": "hidden"})
        self.assertFalse(cloned.legends)
        self.assertEqual(len(figure.legends), 1)

    def test_column_distance_preview_keeps_ticks_and_spaces_labels_in_a_short_margin(self):
        from io import BytesIO
        from xml.etree import ElementTree
        from matplotlib import rc_context
        from analisi.hierarchical_style import apply_hierarchical_style

        figure = _result().figure
        canvas = self.track(FigureCanvasQTAgg(figure))
        apply_hierarchical_style(figure, {"column": {"distance": {
            "visible": True, "minimum": 0, "maximum": 20, "step": 5, "title_visible": False}}})
        axis = describe_hierarchical_artists(figure)["column"]["axes"].yaxis
        figure.set_layout_engine(None)
        for height, wanted in ((.04, 2), (.45, 5)):
            axis.axes.set_position([.2, .7 - height, .5, height])
            canvas.draw()
            ticks = [tick for tick in axis.get_major_ticks() if 0 <= tick.get_loc() <= 20]
            self.assertEqual([tick.get_loc() for tick in ticks], [0, 5, 10, 15, 20])
            labels = [tick.label1 for tick in ticks if tick.label1.get_text()]
            self.assertEqual(len(labels), wanted)
            boxes = sorted((label.get_window_extent().y0, label.get_window_extent().y1) for label in labels)
            self.assertTrue(all(a[1] < b[0] for a, b in zip(boxes, boxes[1:])))

        axis.axes.set_position([.2, .65, .5, .05])
        with rc_context({"svg.fonttype": "none"}):
            output = BytesIO()
            figure.savefig(output, format="svg")
        ns = "{http://www.w3.org/2000/svg}"
        labels = {el.text for el in ElementTree.fromstring(output.getvalue()).iter(ns + "text")}
        self.assertTrue({"0", "5", "10", "15", "20"}.issubset(labels))

    def test_colorbar_preview_reverses_scale_and_cancel_restores_values_and_title(self):
        from analisi.hierarchical_style import apply_hierarchical_style

        figure = _result().figure
        self.track(FigureCanvasQTAgg(figure))
        initial = {"heatmap": {"title": "Table values", "title_position": "above"}}
        apply_hierarchical_style(figure, initial)
        bar = describe_hierarchical_artists(figure)["heatmap"]["colorbar"]
        dialog = self.track(HierarchicalStyleDialog(None, figure, initial))
        self.field(dialog, "heatmap.title_position").set("hidden")
        self.field(dialog, "heatmap.scale_labels").setChecked(False)
        self.field(dialog, "heatmap.scale_reverse").setChecked(True)
        dialog.preview()
        self.assertFalse(bar.ax.get_title())
        self.assertFalse(bar.ax.get_yticklabels())
        self.assertTrue(bar.ax.yaxis.get_inverted())
        dialog.reject()
        self.assertEqual(bar.ax.get_title(), "Table values")
        self.assertTrue(bar.ax.get_yticklabels())
        self.assertFalse(bar.ax.yaxis.get_inverted())
        self.assertEqual(snapshot_hierarchical_style(figure), initial)

    def test_dense_matrix_keeps_fixed_print_interval_while_preview_fits_window_and_zoom(self):
        from io import BytesIO
        from xml.etree import ElementTree
        import matplotlib
        from matplotlib.figure import Figure
        from analisi.hierarchical_style import set_leaf_ticks

        figure = Figure(figsize=(4, 2))
        canvas = self.track(FigureCanvasQTAgg(figure))
        ax = figure.subplots()
        positions = np.arange(43) + .5
        labels = [f"City {number}" for number in range(43)]
        set_leaf_ticks(ax, "y", positions, labels, fit_preview=True)
        ax.set_ylim(43, 0)
        canvas.draw()
        visible = [t for t in ax.get_yticklabels() if t.get_text()]
        self.assertTrue(1 < len(visible) < len(labels))
        boxes = sorted((t.get_window_extent().y0, t.get_window_extent().y1) for t in visible)
        self.assertTrue(all(b[0] >= a[1] for a, b in zip(boxes, boxes[1:])))
        self.assertEqual(len(ax.get_yticks()), len(labels))
        out = BytesIO()
        with matplotlib.rc_context({"svg.fonttype": "none"}):
            figure.savefig(out, format="svg")
        ns = "{http://www.w3.org/2000/svg}"
        exported = [el.text for el in ElementTree.fromstring(out.getvalue()).iter(ns + "text")]
        self.assertTrue(set(labels).issubset(exported))
        ax.set_ylim(24, 19)
        canvas.draw()
        for i in range(19, 24):
            self.assertEqual(ax.yaxis.get_major_ticks()[i].label1.get_text(), labels[i])

    def test_unclustered_columns_preview_and_cancel_without_adding_a_tree(self):
        figure = _result(Direction="Rows").figure
        self.track(FigureCanvasQTAgg(figure))
        matrix = describe_hierarchical_artists(figure)["heatmap"]["axes"]
        dialog = self.track(HierarchicalStyleDialog(None, figure, {}))
        self.assertNotIn("column.width", dialog.fields)
        label = matrix.get_xticklabels()[0]
        initial = label.get_rotation(), label.get_fontweight()
        self.field(dialog, "column.labels.rotation").setText("90")
        self.field(dialog, "column.labels.bold").setChecked(True)
        dialog.preview()
        self.assertEqual((label.get_rotation(), label.get_fontweight()), (90, "bold"))
        dialog.reject()
        self.assertEqual((label.get_rotation(), label.get_fontweight()), initial)

    def test_preview_hides_only_the_distance_title_and_cancel_restores_it(self):
        figure = _result(**{"Direction": "Rows", "Graph output": "Dendrogram",
                            "Dendrogram orientation": "Vertical"}).figure
        self.track(FigureCanvasQTAgg(figure))
        axis = describe_hierarchical_artists(figure)["row"]["axes"].yaxis
        dialog = self.track(HierarchicalStyleDialog(None, figure, {}))
        title = self.field(dialog, "row.distance.title_visible")
        self.assertTrue(title.isChecked())
        self.assertTrue(axis.label.get_text())
        title.setChecked(False)
        dialog.preview()
        self.assertFalse(axis.label.get_visible())
        self.assertTrue(axis.get_ticklabels())
        dialog.reject()
        self.assertTrue(axis.label.get_visible())
        self.assertEqual(snapshot_hierarchical_style(figure), {})

    def test_preview_rollback_and_focus_color_limit(self):
        figure = _result().figure
        self.track(FigureCanvasQTAgg(figure))
        dialog = self.track(HierarchicalStyleDialog(None, figure, {}))
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog._section(), {})
        self.field(dialog, "row.width").setText("2,5")
        self.field(dialog, "heatmap.minimum").setText("1")
        dialog.preview()
        self.assertTrue(dialog.banner.isVisible())
        self.assertIn(tr("hierarchy.style.error.both_limits"), dialog.banner.text())
        self.assertEqual(dialog.tabs.currentWidget(), dialog.fields["heatmap.maximum"][3])
        self.assertEqual(self.app.focusWidget(), self.field(dialog, "heatmap.maximum"))
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        self.field(dialog, "heatmap.maximum").setText("8")
        dialog.preview()
        self.assertEqual(snapshot_hierarchical_style(figure)["row"]["width"], 2.5)
        dialog.reject()
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        self.assertIsNone(dialog.result)

    def test_format_cancel_and_apply_stays_with_the_graph_and_roundtrips(self):
        project = Project()
        frame = _frame()
        project.add_tables({"Misure": frame})
        run = project.candidate("Misure", "Hierarchical clustering", _options())
        original = compute(run, frame)
        project.add_result(run, original)
        figure = original.figure
        canvas = self.track(FigureCanvasQTAgg(figure))
        source_style = {"title": "Distanze $"}
        section = {"heatmap": {"orientation": "horizontal"}, "row": {"width": 2.5}}

        def choose(dialog):
            self.field(dialog, "heatmap.orientation").set("horizontal")
            self.field(dialog, "row.width").setText("2.5")
            dialog.preview()
            self.assertEqual(snapshot_hierarchical_style(figure), section)
            dialog.accept()

        first = self.track(GraphFormatDialog(None, figure.axes[0], source_style))
        self.through_editor(first, choose)
        first.reject()
        self.assertEqual(source_style, {"title": "Distanze $"})
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        self.assertIsNone(run.style)

        second = self.track(GraphFormatDialog(None, figure.axes[0], source_style))
        segments = describe_hierarchical_artists(figure)["row"]["branches"].get_segments()
        self.through_editor(second, choose)
        second.accept()
        self.assertIsNotNone(second.result)
        project.apply_format(run, second.result)
        self.assertIs(run.result, original)
        self.assertIs(figure.canvas, canvas)
        artists = describe_hierarchical_artists(figure)
        np.testing.assert_array_equal(artists["row"]["branches"].get_segments(), segments)
        self.assertEqual(artists["heatmap"]["colorbar"].orientation, "horizontal")
        self.assertEqual(run.style["hierarchical"], section)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "cluster.alab"
            project.save(path)
            reopened = Project()
            reopened.load(path)
            job = reopened.plan_refresh(reopened.runs)
            self.assertFalse(reopened.apply_refresh(job, reopened.run_refresh(job)))
            result = reopened.runs[0].result
            self.assertEqual(snapshot_hierarchical_style(result.figure), section)
            for name, table in original.tables.items():
                self.assertTrue(table.equals(result.tables[name]), name)

    def test_inspector_cancel_restores_and_apply_commits_only_once(self):
        figure = _result().figure
        canvas = self.track(FigureCanvasQTAgg(figure))
        run = SimpleNamespace(method="Hierarchical clustering", result=None)
        confirmations = []
        panel = self.track(GraphInspector(run, canvas, confirmed=lambda: confirmations[-1] if confirmations else {},
                                          commit=confirmations.append, closed=lambda: None))
        self.addCleanup(panel.dispose)

        def choose(dialog):
            self.field(dialog, "column.visible").setChecked(False)
            dialog.accept()

        self.through_editor(panel, choose)
        self.assertTrue(panel.has_draft)
        self.assertEqual(snapshot_hierarchical_style(figure), {"column": {"visible": False}})
        self.assertEqual(confirmations, [])
        panel.discard()
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        self.through_editor(panel, choose)
        self.assertTrue(panel.apply())
        self.assertEqual(confirmations, [{"hierarchical": {"column": {"visible": False}}}])
        self.assertFalse(panel.has_draft)

