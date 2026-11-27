import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication

from analisi.category_graphs import BARS, category_graph
from analisi.data import Dataset
from analisi.grouped_bar_style import grouped_bars
from analisi.i18n import active_language, set_language, tr
from trama_qt.grouped_bar_editor import GroupedBarEditor

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedBarEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        frame = Dataset(pd.DataFrame({"Visit": ["A", "A"], "Values": [3., 3.]})).frame()
        figure = category_graph(frame, {"Variables": ["Values"], "Row titles": "Visit",
                                        "Graph style": BARS}, grouped=True).figure
        self.bars = grouped_bars(figure)
        self.appearances = []

    def editor(self, previous=None, **options):
        dialog = GroupedBarEditor(None, self.bars, previous or [], self.appearances.append, **options)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_select_individual_bar_validates_fields_and_applies_one_record(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        bar = self.bars[1]
        dialog = self.editor(target=bar.key)
        self.assertIn("Riga 2", dialog.target.currentText())
        dialog.width.setText("NaN")
        dialog.target.setCurrentIndex(0)
        self.assertEqual(dialog.target.currentIndex(), 1)
        self.assertEqual(dialog.problem.text(), tr("grouped_bar.error"))
        dialog.width.setText("2,5")
        dialog.transparent["fill"].setChecked(True)
        self.assertFalse(dialog.colors["fill"].isEnabled())
        dialog.pattern.set("cross")
        wanted = [bar.record({"fill": "none", "pattern": "cross", "width": 2.5})]
        dialog._preview()
        self.assertEqual(self.appearances, [wanted])
        self.assertIsNone(dialog.result)
        dialog.accept()
        self.assertEqual(dialog.result, wanted)

    def test_reset_restores_only_selected_bar_and_cancel_leaves_records_unchanged(self):
        first, second = (bar.record({"border": "#abcd12"}) for bar in self.bars)
        dialog = self.editor([first, second])
        dialog.reset_fields()
        dialog.target.setCurrentIndex(1)
        self.assertEqual(dialog.colors["border"].text(), second["style"]["border"])
        dialog._preview()
        self.assertEqual(self.appearances, [[second]])
        dialog.reject()
        self.assertIsNone(dialog.result)
        self.assertEqual(first["style"]["border"], "#abcd12")
