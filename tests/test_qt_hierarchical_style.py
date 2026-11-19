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

