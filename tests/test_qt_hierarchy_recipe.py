"""Editing an existing hierarchy keeps its scale, variable order and actual fitted tree."""
import unittest

import numpy as np
import pandas as pd

from tests.test_qt_shell import QApplication, _app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SavedHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.frame = pd.DataFrame({
            "Label": list("ABCDE"), "Length": [0., 2., 8., 7., 4.],
            "Depth": [0., 20., 3., 12., 16.], "Width": [3., 5., 6., 2., 1.],
        })

    def edit(self, options):
        from trama_qt.analysis_dialog import AnalysisDialog
        method = "Hierarchical clustering"
        dialog = AnalysisDialog(None, self.frame, current=(method, options), only=method)
        self.addCleanup(dialog.close)
        return dialog

    def test_confirming_legacy_unscaled_recipe_preserves_the_fitted_distances(self):
        from analisi.workbench import analyse
        saved = {"Variables": ["Depth", "Length"], "Standardize": False, "Direction": "Rows",
                 "Observation labels": "Label", "Scaled data": True}
        method = "Hierarchical clustering"
        before = analyse(method, self.frame, saved)
        editor = self.edit(saved)
        editor.accept()
        _, options = editor.result
        after = analyse(method, self.frame, options)
        np.testing.assert_allclose(after.tables["Merges"]["Distance"], before.tables["Merges"]["Distance"])
        self.assertEqual(options["Scale columns"], "None")

    def test_saved_order_survives_adding_another_variable(self):
        from PySide6.QtCore import Qt
        saved = {"Variables": ["Width", "Length"], "Scale columns": "Center", "Standardize": False}
        dialog = self.edit(saved)
        columns = dialog.controls["Variables"][1]
        for i in range(columns.count()):
            if columns.item(i).text() == "Depth":
                columns.item(i).setCheckState(Qt.CheckState.Checked)
        dialog.accept()
        _, options = dialog.result
        self.assertEqual(options["Variables"], ["Width", "Length", "Depth"])
        self.assertEqual(options["Scale columns"], "Center")

    def test_legacy_implicit_raw_scale_and_new_recipe_default(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        editor = self.edit({"Variables": ["Depth", "Length"]})
        self.assertEqual(editor.controls["Scale columns"][1].currentData(), "None")
        fresh = AnalysisDialog(None, self.frame, only="Hierarchical clustering")
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.controls["Scale columns"][1].currentData(), "Standardize")
