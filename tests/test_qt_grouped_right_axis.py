import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi.category_graphs import BARS, RIGHT_SIDE, SERIES_SIDE, category_graph
from analisi.i18n import active_language, set_language, tr
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedRightAxisDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, style=None):
        frame = pd.DataFrame({"Visit": ["V1", "V2"], "A": [2., 3.], "B": [100., 200.]})
        options = {"Variables": ["A", "B"], "Row titles": "Visit", "Graph style": BARS}
        result = category_graph(frame, options, grouped=True)
        dialog = GraphFormatDialog(None, result.figure.axes[0], style or {},
                                   grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog, options

    def test_right_axis_settings_enable_for_the_selected_series(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        dialog, options = self.dialog()
        self.assertFalse(dialog.right["title"].isEnabled())
        dialog.selector.setCurrentIndex(1)
        self.assertEqual(dialog.grouped_side.accessibleName(), tr("grouped.series.axis"))
        dialog.grouped_side.set(RIGHT_SIDE)
        self.assertEqual(dialog.grouped_side.currentText(), "Destra")
        self.assertTrue(dialog.right["title"].isEnabled())
        dialog.right["min"].setText("0")
        self.assertFalse(dialog.preview())
        self.assertEqual(dialog.tabs.currentIndex(), 1)
        dialog.right["max"].setText("220,5")
        dialog.right["title"].setText("Mass")
        self.assertTrue(dialog.preview())
        self.assertNotIn(SERIES_SIDE, options)
        self.assertEqual(dialog.preview_canvas.figure.axes[1].get_ylim(), (0., 220.5))
        dialog.accept()
        self.assertEqual(dialog.grouped_update[SERIES_SIDE], {"B": RIGHT_SIDE})
        self.assertEqual(dialog.grouped_update["Right title"], "Mass")

    def test_an_existing_linked_right_axis_blocks_an_independent_right_axis(self):
        dialog, _ = self.dialog({"linked_axes": {"y": {"multiplier": 2., "offset": 0., "label": "Converted"}}})
        dialog.selector.setCurrentIndex(1)
        dialog.grouped_side.set(RIGHT_SIDE)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("independent right Y axis", dialog.banner.text())
