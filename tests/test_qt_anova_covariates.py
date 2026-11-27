"""Covariates in the Classic Qt multifactor ANOVA dialog. Offscreen."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from analisi.anova_covariates import COVARIATES, REFERENCES
from analisi.anova_ss import KEY as SUMS, TYPE_I
from analisi.i18n import set_language


METHOD = "Multifactor ANOVA"
DATA = Path(__file__).resolve().parent / "data" / "covariate-anova" / "fattoriale.csv"


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["trama-covariates", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _tick(dialog, names):
    box = dialog.controls["Factors"][1]
    for row in range(box.count()):
        item = box.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)


def _column(dialog, field, name):
    combo = dialog.controls[field][1]
    index = combo.findData(name)
    assert index >= 0, (field, name, [combo.itemData(i) for i in range(combo.count())])
    combo.setCurrentIndex(index)


def _check(panel, name, on=True):
    for row in range(panel.columns.count()):
        item = panel.columns.item(row)
        if item.text() == name:
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            return
    raise AssertionError(name)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class CovariateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.frame = pd.read_csv(DATA)

    def setUp(self):
        set_language("en")
        self.addCleanup(set_language, "en")

    def dialog(self, recipe=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.frame, current=(METHOD, recipe or {}), only=METHOD)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def prepared(self, recipe=None):
        dialog = self.dialog(recipe)
        _column(dialog, "Response", "Y")
        _tick(dialog, ["Dose", "Metodo"])
        dialog.tabs.setCurrentIndex(1)
        self.app.processEvents()
        return dialog

    def test_the_panel_offers_numeric_columns_and_writes_explicit_references(self):
        dialog = self.prepared()
        panel = dialog.controls[COVARIATES][1]
        offered = [panel.columns.item(row).text() for row in range(panel.columns.count())]
        self.assertEqual(offered, ["X", "Z"])
        self.assertFalse(panel.note.isVisible())
        _check(panel, "X")
        _check(panel, "Z")
        self.app.processEvents()
        self.assertEqual(panel.note.objectName(), "infoBanner")
        self.assertTrue(panel.note.isVisible())
        self.assertIn("Type I", panel.note.text())
        self.assertIn("extrapolation", panel.note.text())
        self.assertIn("joint support", panel.note.text())
        panel.edits["X"].setText("6")
        panel.edits["Z"].setText("4")
        QTest.keyClick(panel.columns, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(dialog.result)
        options = dialog.result[1]
        self.assertEqual(options[COVARIATES], ["X", "Z"])
        self.assertEqual(options[REFERENCES], {"X": 6.0, "Z": 4.0})
        self.assertNotIn("Denominator method", options)

    def test_a_recipe_without_covariates_omits_the_keys(self):
        dialog = self.prepared({"Response": "Y", "Factors": ["Dose", "Metodo"], "Interaction order": 2})
        options = dialog.options()
        self.assertNotIn(COVARIATES, options)
        self.assertNotIn(REFERENCES, options)
        self.assertEqual(options["Interaction order"], 2)

    def test_type_i_with_a_covariate_stays_open_on_the_sums_of_squares(self):
        dialog = self.prepared()
        sums = dialog.controls[SUMS][1]
        sums.setCurrentIndex(sums.findData(TYPE_I))
        panel = dialog.controls[COVARIATES][1]
        _check(panel, "X")
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("Type III", dialog.banner.text())
        self.assertTrue(dialog.banner.isVisible())
        self.assertIs(dialog.focusWidget(), sums)

    def test_italian_captions_note_and_a_comma_reference(self):
        set_language("it")
        dialog = self.prepared()
        self.assertEqual(dialog.rows[COVARIATES][0].text(), "Covariate")
        panel = dialog.controls[COVARIATES][1]
        _check(panel, "X")
        self.app.processEvents()
        self.assertIn("estrapolazione", panel.note.text())
        self.assertIn("tipo I", panel.note.text())
        panel.edits["X"].setText("6,5")
        self.assertEqual(panel.values()[REFERENCES]["X"], 6.5)
        panel.edits["X"].setText("no")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("finito", dialog.banner.text())

    def test_light_and_dark_style_the_note(self):
        from trama_qt import theme
        dialog = self.prepared()
        _check(dialog.controls[COVARIATES][1], "X")
        theme.apply(self.app, dark=False)
        light = self.app.styleSheet()
        theme.apply(self.app, dark=True)
        dark = self.app.styleSheet()
        theme.apply(self.app, dark=False)
        self.assertIn("QLabel#infoBanner", light)
        self.assertIn("QLabel#infoBanner", dark)
        self.assertNotEqual(light, dark)

    def test_emulated_screens_keep_the_dialog_inside_the_display(self):
        cases = (("100", 1024, 768, 96), ("150", 1366, 768, 144))
        for name, width, height, dpi in cases:
            with self.subTest(scale=name):
                with tempfile.TemporaryDirectory() as directory:
                    config = Path(directory) / "schermo.json"
                    config.write_text(json.dumps({"screens": [{
                        "name": "s", "x": 0, "y": 0, "width": width, "height": height,
                        "logicalDpi": dpi, "logicalBaseDpi": 96, "dpr": 1.0}]}), encoding="utf-8")
                    env = os.environ.copy()
                    env["QT_QPA_PLATFORM"] = f"offscreen:configfile={config}"
                    env.pop("QT_SCALE_FACTOR", None)
                    probe = subprocess.run(
                        [sys.executable, "-c", PROBE], cwd=Path(__file__).resolve().parents[1],
                        env=env, check=False, capture_output=True, text=True)
                self.assertEqual(probe.returncode, 0, probe.stderr)
                print(probe.stdout.strip())
                screen_w, screen_h, dialog_w, dialog_h, button = (int(part) for part in probe.stdout.split())
                self.assertLessEqual(dialog_w, screen_w)
                self.assertLessEqual(dialog_h, screen_h)
                self.assertGreaterEqual(button, 1)


PROBE = r"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
from PySide6.QtWidgets import QApplication
import pandas as pd
from analisi.i18n import set_language
from trama_qt.analysis_dialog import AnalysisDialog
from trama_qt import theme

set_language("en")
app = QApplication(["trama-covariate-scale"])
theme.load_fonts()
theme.apply(app)
frame = pd.read_csv("tests/data/covariate-anova/fattoriale.csv")
dialog = AnalysisDialog(None, frame, current=("Multifactor ANOVA", {}), only="Multifactor ANOVA")
dialog.show()
app.processEvents()
screen = dialog.screen().availableGeometry()
button = dialog.run_button
assert button.width() + 4 >= button.sizeHint().width(), (button.width(), button.sizeHint().width())
print(screen.width(), screen.height(), dialog.width(), dialog.height(), button.width())
"""


if __name__ == "__main__":
    unittest.main()
