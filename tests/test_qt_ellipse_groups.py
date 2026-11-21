import unittest

import pandas as pd

from tests.test_qt_shell import QApplication, _app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class EllipseGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        from analisi.ellipse_workbench import GROUP_STYLES

        frame = pd.DataFrame({"X": [0., 1., 2., 3.], "Y": [2., 4., 0., 1.], "batch": [1, "1", 1, "1"]})
        self.key = GROUP_STYLES
        self.styles = {"batch": {"str:1": {"Border width": 3.0, "Fill opacity (%)": 10.0}}}
        method = "Scatter / confidence ellipse"
        recipe = {"X": "X", "Y": "Y", "Group": "batch", "Ellipse": "Data ellipse", GROUP_STYLES: self.styles}
        self.dialog = AnalysisDialog(None, frame, current=(method, recipe), only=method)
        self.addCleanup(self.dialog.close)

    def test_accepting_a_saved_scatter_preserves_overrides(self):
        self.dialog.accept()
        self.assertEqual(self.dialog.result[1].get(self.key), self.styles)

    def test_editor_opens_from_analysis_and_keeps_only_confirmed_edits(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog
        from trama_qt.ellipse_groups import GroupDialog

        button = self.dialog.ellipse_groups
        self.assertNotIn(self.key, self.dialog.hidden)

        def drive(editor):
            groups = editor.groups
            self.assertNotEqual(groups.itemText(0), groups.itemText(1))
            self.assertEqual(groups.currentData(), "int:1")
            editor.fields["Border width"].setText("-2")
            groups.setCurrentIndex(1)
            self.assertEqual(groups.currentIndex(), 0)
            self.assertTrue(editor.error.text())
            editor.fields["Border width"].setText("2,5")
            groups.setCurrentIndex(1)
            self.assertEqual(groups.currentData(), "str:1")
            self.assertEqual(editor.fields["Border width"].text(), "3.0")
            editor.fields["Border width"].clear()
            editor.accept()
            return editor.result()

        with patch.object(GroupDialog, "exec", drive):
            button.click()
        expected = {"batch": {"int:1": {"Border width": 2.5}, "str:1": {"Fill opacity (%)": 10.0}}}
        self.assertEqual(self.dialog.options()[self.key], expected)
        self.assertEqual(self.styles["batch"]["str:1"]["Border width"], 3.0)

        def cancel(editor):
            editor.fields["Border width"].setText("7")
            editor.groups.setCurrentIndex(1)
            editor.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(GroupDialog, "exec", cancel):
            button.click()
        self.assertEqual(self.dialog.options()[self.key], expected)

    def test_changing_group_scope_hides_editor_and_retains_styles(self):
        from analisi.ellipse_workbench import ALL_POINTS, MATCH_POINTS
        box = self.dialog.controls["Ellipse grouping"][1]
        box.setCurrentIndex(box.findData(ALL_POINTS))
        self.assertIn(self.key, self.dialog.hidden)
        self.assertEqual(self.dialog.options()[self.key], self.styles)
        box.setCurrentIndex(box.findData(MATCH_POINTS))
        self.assertNotIn(self.key, self.dialog.hidden)

    def test_confirm_save_reopen_and_render(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from matplotlib.figure import Figure
        from analisi.data import Dataset, load_project, save_project
        from analisi.ellipse_workbench import draw_confidence_overlays

        self.dialog.accept()
        frame = pd.DataFrame({"X": [0, 1, 1, 0, 2, 3, 3, 2], "Y": [0, 0, 1, 1] * 2,
                              "batch": ["A"] * 4 + ["1"] * 4})
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ellipses.alab"
            save_project(path, {"Data": Dataset(frame, analyses=[self.dialog.result])})
            dataset = load_project(path)["Data"]
        _, recipe = dataset.analyses[0]
        self.assertEqual(recipe[self.key], self.styles)
        axes = Figure().add_subplot()
        draw_confidence_overlays(axes, dataset.raw, recipe, {"A": "blue", "1": "red"})
        self.assertEqual([line.get_linewidth() for line in axes.lines], [1.5, 3.0])

    def test_editor_uses_application_language_for_cancel(self):
        from PySide6.QtWidgets import QDialogButtonBox
        from analisi.i18n import active_language, set_language
        from trama_qt.ellipse_groups import GroupDialog

        self.addCleanup(set_language, active_language())
        set_language("it")
        button = self.dialog.ellipse_groups
        dialog = GroupDialog(button, self.dialog.data["batch"], button.choices(), button.styles)
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Cancel).text(), "Annulla")
        dialog.reject()
