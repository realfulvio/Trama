"""Qt extraction recipes expose and validate only the chosen worksheet format."""
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import extract_rearrange as extraction
from analisi.i18n import active_language, set_language

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ExtractRearrangeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["extract-test", "-platform", "offscreen"])

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        self.frame = pd.DataFrame({"Y": [2, 8], "X": [1, 2], "Età $": ["M", "S"], "Cura à": ["B", "A"]})

    def dialog(self, recipe):
        from trama_qt.analysis_dialog import AnalysisDialog

        method = extraction.EXTRACT_REARRANGE
        dialog = AnalysisDialog(None, self.frame, only=method, current=(method, recipe))
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_each_format_serializes_only_active_fields_and_restores_the_draft(self):
        e = extraction
        recipe = {e.OUTPUT: "Grouped", e.RESPONSE: "Y", e.ROW_FACTOR: "Età $", e.COLUMN_FACTOR: "Cura à",
                  e.COMPLETE: False, e.PREFIX: True}
        dialog = self.dialog(recipe)
        kind = dialog.controls[e.OUTPUT][1]
        self.assertEqual(kind.currentData(), "Grouped")
        self.assertNotEqual(kind.currentText(), "Grouped")
        self.assertEqual(dialog.controls[e.ROW_FACTOR][1].currentText(), "Età $")
        self.assertFalse(dialog.controls[e.X][1].isVisible())
        self.assertTrue(dialog.controls[e.ROW_FACTOR][1].isVisible())
        self.assertIs(dialog.rows[e.OUTPUT][2], dialog.rows[e.RESPONSE][2])

        for output, fields in e.EXTRACT_FIELDS.items():
            with self.subTest(output=output):
                kind.setCurrentIndex(kind.findData(output))
                options = dialog.options()
                expected = {e.OUTPUT, e.PREFIX, *fields}
                if output != "Contingency":
                    expected.add(e.COMPLETE)
                self.assertEqual(set(options), expected)
                self.assertEqual(options[e.OUTPUT], output)

        kind.setCurrentIndex(kind.findData("Grouped"))
        expected = {**recipe, e.SUBJECT: None}
        self.assertEqual(dialog.options(), expected)
        with patch.object(e, "_numbers", side_effect=AssertionError("The GUI evaluated observations")):
            dialog.accept()
        self.assertEqual(dialog.result, (e.EXTRACT_REARRANGE, expected))

    def test_missing_saved_column_focuses_the_active_field_without_running(self):
        e = extraction
        recipe = {e.OUTPUT: "Grouped", e.RESPONSE: "removed column",
                  e.ROW_FACTOR: "Età $", e.COLUMN_FACTOR: "Cura à", e.COMPLETE: False}
        dialog = self.dialog(recipe)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("Scegli", dialog.banner.text())
        field = dialog.controls[e.RESPONSE][1]
        self.assertIs(dialog.focusWidget(), field)
        field.setCurrentIndex(field.findData("Y"))
        self.assertTrue(dialog.banner.isHidden())
        dialog.accept()
        self.assertEqual(dialog.result[1][e.RESPONSE], "Y")
        self.assertEqual(recipe[e.RESPONSE], "removed column")
