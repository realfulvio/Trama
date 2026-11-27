import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication, QDialog

from analisi.category_graphs import AS_GRAPH, BARS, LOWER_INTERVAL, SERIES_INTERVAL_DIRECTION, category_graph
from analisi.i18n import active_language, set_language
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedIntervalDirectionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, interval):
        frame = pd.DataFrame({"Visit": ["First", "Second"], "A [1]": [1., 2.], "A [2]": [2., 7.],
                              "B [1]": [3., 4.], "B [2]": [4., 6.]})
        options = {"Variables": list(frame.columns[1:]), "Row titles": "Visit", "Graph style": BARS, "Interval": interval}
        result = category_graph(frame, options, grouped=True)
        dialog = GraphFormatDialog(None, result.figure.axes[0], {}, grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog, options

    def test_editing_one_series_preserves_the_other_and_previews_without_commit(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        dialog, options = self.dialog("SEM")
        direction = dialog.grouped_interval
        dialog.selector.setCurrentIndex(1)
        self.assertTrue(direction.isEnabled())
        direction.set(LOWER_INTERVAL)
        self.assertEqual(direction.currentText(), "Solo inferiore")
        dialog.selector.setCurrentIndex(0)
        self.assertEqual(direction.value(), AS_GRAPH)
        self.assertTrue(dialog.preview())
        self.assertNotIn(SERIES_INTERVAL_DIRECTION, options)
        dialog.accept()
        self.assertEqual(QDialog.result(dialog), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.grouped_update[SERIES_INTERVAL_DIRECTION], {"B": LOWER_INTERVAL})

    def test_without_intervals_the_control_explains_how_to_enable_it(self):
        self.addCleanup(set_language, active_language())
        set_language("en")
        dialog, _ = self.dialog("None")
        self.assertFalse(dialog.grouped_interval.isEnabled())
        self.assertIn("Set the interval type", dialog.grouped_interval.toolTip())
