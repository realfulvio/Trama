import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi.category_graphs import BARS, category_graph
from analisi.i18n import active_language, set_language, tr
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedIntervalAppearanceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fields_accept_localized_values_and_apply_only_to_the_chosen_interval(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        frame = pd.DataFrame({"Visit": ["Before", "After"], "A [1]": [1., 3.], "A [2]": [3., 7.],
                              "B [1]": [4., 8.], "B [2]": [8., 10.]})
        options = {"Variables": list(frame.columns[1:]), "Row titles": "Visit", "Graph style": BARS, "Interval": "SEM"}
        graph = category_graph(frame, options, grouped=True)
        dialog = GraphFormatDialog(None, graph.figure.axes[0], {}, grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.selector.setCurrentIndex(1)
        for name, value in (("interval_color", "#992850"), ("interval_width", "2,5"), ("interval_caps", "0")):
            field = dialog.series_fields[name]
            self.assertTrue(field.isEnabled())
            self.assertEqual(field.accessibleName(), tr(f"graph.series.{name}"))
            field.setText(value)
        self.assertTrue(dialog.preview())
        dialog.accept()
        self.assertEqual(dialog.result["series"], {
            "grouped:1:B": {"interval_color": "#992850", "interval_width": 2.5, "interval_caps": 0.},
        })
