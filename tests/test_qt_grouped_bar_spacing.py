import os
import unittest

import pandas as pd
from PySide6.QtWidgets import QApplication, QDialog

from analisi.category_graphs import BARS, GROUPED_BAR_SPACING, category_graph
from analisi.i18n import active_language, set_language, tr
from trama_qt.graph_format import GraphFormatDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GroupedBarSpacingDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, spacing=None):
        frame = pd.DataFrame({"Visit": ["First", "Second"], "A": [1., 2.], "B": [3., 4.]})
        options = {"Variables": ["A", "B"], "Row titles": "Visit", "Graph style": BARS}
        if spacing:
            options[GROUPED_BAR_SPACING] = spacing
        result = category_graph(frame, options, grouped=True)
        dialog = GraphFormatDialog(None, result.figure.axes[0], {}, grouped={"frame": frame, "options": options})
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog, options

    def test_localized_controls_and_shared_preview(self):
        current = active_language()
        self.addCleanup(set_language, current)
        for language, caption in (("en", "Bar spacing"), ("it", "Spaziatura barre")):
            with self.subTest(language=language):
                set_language(language)
                dialog, options = self.dialog()
                dialog.tabs.setCurrentIndex(dialog.spacing_tab)
                self.assertEqual(dialog.tabs.tabText(dialog.spacing_tab), caption)
                field = dialog.spacing_controls["adjacent"]
                self.assertEqual(field.accessibleName(), tr("grouped.spacing.adjacent"))
                self.assertFalse(field.isEnabled())
                spacing_tab = dialog.tabs.currentWidget()
                self.assertTrue(spacing_tab.isAncestorOf(dialog.preview_canvas))
                dialog.spacing_enabled.setChecked(True)
                self.assertTrue(field.isEnabled())
                field.setValue(200.)
                self.assertTrue(dialog.preview())
                self.assertNotIn(GROUPED_BAR_SPACING, options)
                limits = dialog.preview_canvas.figure.axes[0].get_xlim()
                self.assertAlmostEqual(limits[1], 11.45)
                dialog.tabs.setCurrentIndex(2)
                self.assertTrue(dialog.tabs.currentWidget().isAncestorOf(dialog.preview_canvas))
                dialog.accept()
                self.assertEqual(QDialog.result(dialog), QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.grouped_update[GROUPED_BAR_SPACING]["adjacent"], 200.)

    def test_disabling_custom_spacing_restores_automatic_geometry(self):
        dialog, options = self.dialog({"adjacent": 0., "groups": 0., "empty": 0., "leading": 0., "trailing": 0.})
        dialog.spacing_enabled.setChecked(False)
        dialog.accept()
        self.assertNotIn(GROUPED_BAR_SPACING, dialog.grouped_update)
        self.assertIn(GROUPED_BAR_SPACING, options)
