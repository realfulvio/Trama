"""Catalog global fits keep their full recipe when edited in Qt."""
from copy import deepcopy
import unittest

import pandas as pd

from analisi.i18n import active_language, set_language
from tests.test_qt_global_fit import QApplication, _app


METHOD = "Global nonlinear regression"
RECIPE = {
    "Input format": "Wide XY", "X": "Time", "Y columns": ["Control $", "Treatment"],
    "Merge numbered replicates": False, "Model": "Straight line",
    "Shared parameters": ["Slope"], "Fixed parameters": {},
    "Parameter bounds": {"Slope": [0, 10]}, "Initial values": {"Slope": 1.5},
    "Compare local parameters": ["Intercept"],
    "Series constraints": [{"series": "Control $", "parameters": {"Intercept": {"lower": 0}}}],
}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class CatalogGlobalFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def dialog(self, recipe, frame=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = frame if frame is not None else pd.DataFrame({"Time": [0, 1, 2, 3], "Control $": [1.1, 2.9, 4.9, 7.1],
                              "Treatment": [4.1, 5.9, 7.9, 10.1]})
        dialog = AnalysisDialog(None, frame, current=(METHOD, recipe), only=METHOD)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_confirm_keeps_saved_scopes_starts_bounds_and_series(self):
        from analisi.workbench import analyse

        dialog = self.dialog(deepcopy(RECIPE))
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        method, options = dialog.result
        for key in ("Shared parameters", "Fixed parameters", "Parameter bounds", "Initial values",
                    "Compare local parameters", "Series constraints"):
            self.assertEqual(options[key], RECIPE[key])
        result = analyse(method, dialog.data, options)
        slope = result.tables["Parameters"].query("Parameter == 'Slope'").iloc[0]
        self.assertEqual(slope["Scope"], "Shared")
        self.assertAlmostEqual(slope["Estimate"], 2)

    def test_model_switch_restores_drafts_and_errors_focus_the_coefficient(self):
        from PySide6.QtCore import Qt
        self.addCleanup(set_language, active_language())
        set_language("it")
        recipe = deepcopy(RECIPE)
        dialog = self.dialog(recipe)
        parameters = dialog.controls["Parameters"][1]
        series = dialog.controls["Series constraints"][1]
        model = dialog.controls["Model"][1]
        self.assertEqual(series.labels(), ["Control $", "Treatment"])

        slope = next(row for row in range(parameters.rowCount())
                     if parameters.item(row, 0).text() == "Slope")
        parameters.item(slope, parameters.START).setText("1,75")
        series.set_override("Treatment", "Intercept", "initial", "3,5")
        model.setCurrentIndex(model.findData("One-phase decay"))
        self.assertEqual(series.values(), [])
        model.setCurrentIndex(model.findData("Straight line"))
        self.assertEqual(parameters.item(slope, parameters.START).text(), "1,75")
        self.assertEqual(series.values()[-1], {"series": "Treatment", "parameters": {"Intercept": {"initial": 3.5}}})

        parameters.item(slope, parameters.LOWER).setText("11")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.error_field, "Parameters")
        self.assertEqual(parameters.currentRow(), slope)
        self.assertEqual(parameters.currentColumn(), parameters.LOWER)
        self.assertEqual(recipe, RECIPE)
        parameters.item(slope, parameters.LOWER).setText("0")
        parameters.item(slope, parameters.SCOPE).setData(Qt.ItemDataRole.UserRole, "Fixed")
        parameters.item(slope, parameters.FIXED).setText("2")
        dialog.accept()
        self.assertEqual(dialog.result[1]["Fixed parameters"], {"Slope": 2})
        self.assertEqual(dialog.result[1]["Shared parameters"], [])

    def test_numeric_and_text_series_keep_distinct_overrides(self):
        frame = pd.DataFrame({"Time": [0, 1, 0, 1], "Response": [1, 3, 5, 7],
                              "Group": pd.Series([1, 1, "1", "1"], dtype=object)})
        recipe = {**RECIPE, "Input format": "Long table", "Y": "Response", "Series": "Group",
                  "Series constraints": [{"series": 1, "parameters": {"Intercept": {"lower": 0}}}]}
        dialog = self.dialog(recipe, frame)
        series = dialog.controls["Series constraints"][1]
        self.assertEqual(series.labels(), [1, "1"])
        series.set_override("1", "Intercept", "initial", "5")
        dialog.accept()
        self.assertEqual(dialog.result[1]["Series constraints"], [
            {"series": 1, "parameters": {"Intercept": {"lower": 0}}},
            {"series": "1", "parameters": {"Intercept": {"initial": 5}}},
        ])
