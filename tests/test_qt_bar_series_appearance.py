import os
import unittest

from matplotlib.colors import to_rgba
import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi.category_graphs import BARS, SYMBOLS, category_graph
from analisi.data import Dataset
from analisi.grouped_bar_style import BAR_APPEARANCE
from analisi.presentation import graph_series
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class QtBarSeriesAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_grouped_fields_follow_bar_mode_and_preview_is_independent(self):
        frame = Dataset(pd.DataFrame({"Label": ["V1", "V2"], "A": [4., 8.], "B": [5., 10.]})).frame()
        options = {"Variables": ["A", "B"], "Row titles": "Label", "Graph style": BARS}
        figure = category_graph(frame, options, grouped=True).figure
        dialog = GraphFormatDialog(None, figure.axes[0], {}, grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        fields = dialog.series_bar_fields
        fields.width.setText("2,5")
        fields.colors["border"].setText("#112233")
        fields.pattern.set("horizontal")
        self.assertTrue(dialog.preview())
        a = graph_series(dialog.preview_canvas.figure.axes[0])[0]
        self.assertEqual(a.artist.patches[0].get_linewidth(), 2.5)
        self.assertEqual(a.artist.patches[0].get_hatch(), "-")

        dialog.grouped_draw.set(SYMBOLS)
        self.assertTrue(dialog.series_bar_group.isHidden())
        self.assertTrue(dialog.preview())
        dialog.grouped_draw.set(BARS)
        self.assertFalse(dialog.series_bar_group.isHidden())
        self.assertEqual(fields.colors["border"].text(), "#112233")
        dialog.selector.setCurrentIndex(1)
        self.assertEqual(fields.colors["border"].text(), "")
        self.assertEqual(fields.pattern.value(), "")
        dialog.accept()
        appearance = dialog.result["series"]["grouped:1:A"][BAR_APPEARANCE]
        self.assertEqual(appearance, {"width": 2.5, "border": "#112233", "pattern": "horizontal"})
        self.assertNotEqual(graph_series(figure.axes[0])[0].artist.patches[0].get_edgecolor(), to_rgba("#112233"))
