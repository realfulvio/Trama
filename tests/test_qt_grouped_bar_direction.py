import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi.category_graphs import BAR_BASELINE, BAR_DIRECTION, BARS, HORIZONTAL_BARS, POINTS, category_graph
from analisi.i18n import active_language, set_language
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedBarDirectionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, style):
        frame = pd.DataFrame({"Visit": ["First", "Second"], "A [1]": [1., 2.], "A [2]": [2., 4.]})
        options = {"Variables": list(frame.columns[1:]), "Row titles": "Visit", "Graph style": style}
        result = category_graph(frame, options, grouped=True)
        dialog = GraphFormatDialog(None, result.figure.axes[0], {}, grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog, options

    def test_orientation_is_localized_and_previews_without_mutating_the_parameters(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        dialog, options = self.dialog(BARS)
        direction = dialog.bar_direction
        dialog.tabs.setCurrentIndex(dialog.spacing_tab)
        direction.set(HORIZONTAL_BARS)
        self.assertEqual(direction.currentText(), "Orizzontale")
        self.assertTrue(dialog.preview())
        self.assertEqual(dialog.preview_canvas.figure.axes[0]._tramastat_numeric_axes, ("x",))
        self.assertNotIn(BAR_DIRECTION, options)
        dialog.accept()
        self.assertEqual(dialog.grouped_update[BAR_DIRECTION], HORIZONTAL_BARS)

    def test_no_bar_direction_selector_without_bars(self):
        dialog, _ = self.dialog(POINTS)
        self.assertIsNone(dialog.bar_direction)

    def test_baseline_accepts_a_decimal_comma_and_validates_the_field(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        dialog, options = self.dialog(BARS)
        dialog.bar_baseline.setText("nan")
        self.assertFalse(dialog.preview())
        self.assertEqual(dialog.tabs.currentIndex(), dialog.spacing_tab)
        self.assertIn("iniziale finito", dialog.banner.text())
        dialog.bar_baseline.setText("1,5")
        self.assertTrue(dialog.preview())
        self.assertNotIn(BAR_BASELINE, options)
        dialog.accept()
        self.assertEqual(dialog.grouped_update[BAR_BASELINE], 1.5)
