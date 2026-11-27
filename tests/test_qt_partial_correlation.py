"""Partial correlation in the Classic Qt dialog. Offscreen."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import pandas as pd

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from analisi.i18n import set_language
from analisi.partial_correlation import COVARIATES, METHOD, SCATTER, VARIABLES
from trama_qt.classic_bar import MENUS


DATA = Path(__file__).resolve().parent / "data" / "correlazione-parziale" / "campione.csv"


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["trama-partial", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _check(widget, name, on=True):
    for row in range(widget.count()):
        item = widget.item(row)
        if item.text() == name:
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            return
    raise AssertionError(name)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class PartialDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.frame = pd.read_csv(DATA)

    def setUp(self):
        set_language("en")
        self.addCleanup(set_language, "en")

    def dialog(self, recipe=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        started = time.perf_counter()
        dialog = AnalysisDialog(None, self.frame, current=(METHOD, recipe or {}), only=METHOD)
        dialog.show()
        self.app.processEvents()
        dialog._open_seconds = time.perf_counter() - started
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_the_command_stays_in_the_analyze_menu(self):
        analyze = dict(MENUS)["Analyze"]
        self.assertIn("partial_correlation", analyze)
        self.assertLess(analyze.index("correlation_matrix"), analyze.index("partial_correlation"))

    def test_roles_note_and_enter(self):
        dialog = self.dialog()
        print(f"Partial correlation dialog: {dialog._open_seconds:.3f}s")
        variables = dialog.controls[VARIABLES][1]
        covariates = dialog.controls[COVARIATES][1]
        self.assertEqual([variables.item(row).text() for row in range(variables.count())],
                         ["ID", "X", "Y", "W", "Z1", "Z2"])
        self.assertEqual(dialog.partial_note.objectName(), "infoBanner")
        self.assertIn("approximate", dialog.partial_note.text())
        self.assertIn("exactly two", dialog.partial_note.text())
        self.assertTrue(dialog.partial_note.isVisible())
        _check(variables, "X")
        _check(covariates, "X")
        self.app.processEvents()
        self.assertEqual(variables.item(1).checkState(), Qt.CheckState.Unchecked)
        _check(variables, "X")
        _check(variables, "Y")
        _check(covariates, "Z1")
        variables.setFocus()
        QTest.keyClick(variables, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertIsNot(dialog.focusWidget(), variables)
        variables.setFocus()
        QTest.keyClick(variables, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(dialog.result)
        options = dialog.result[1]
        self.assertEqual(options[VARIABLES], ["X", "Y"])
        self.assertEqual(options[COVARIATES], ["Z1"])
        self.assertEqual(options["Method"], "Pearson")
        self.assertFalse(options[SCATTER])

    def test_three_variables_cannot_ask_for_the_residual_scatter(self):
        dialog = self.dialog()
        variables = dialog.controls[VARIABLES][1]
        covariates = dialog.controls[COVARIATES][1]
        for name in ("X", "Y", "W"):
            _check(variables, name)
        _check(covariates, "Z1")
        dialog.controls[SCATTER][1].setChecked(True)
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("exactly two", dialog.banner.text())
        self.assertIs(dialog.focusWidget(), dialog.controls[SCATTER][1])

    def test_italian_captions_and_the_overlap_message(self):
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.heading.text(), "Correlazione parziale")
        self.assertEqual(dialog.rows[COVARIATES][0].text(), "Covariate")
        self.assertEqual(dialog.rows[SCATTER][0].text(), "Grafico dei residui")
        self.assertIn("approssimato", dialog.partial_note.text())
        self.assertIn("Fisher", dialog.partial_note.text())
        variables = dialog.controls[VARIABLES][1]
        covariates = dialog.controls[COVARIATES][1]
        variables.blockSignals(True)
        covariates.blockSignals(True)
        _check(variables, "X")
        _check(variables, "Y")
        _check(covariates, "X")
        variables.blockSignals(False)
        covariates.blockSignals(False)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("covariata", dialog.banner.text())

    def test_the_example_reopens_with_the_same_roles(self):
        from analisi.data import load_project
        saved = load_project(DATA.parents[3] / "docs" / "examples" / "partial-correlation-campione.alab")
        dialog = self.dialog(saved["Campione"].analyses[0][1])
        options = dialog.options()
        self.assertEqual(options[VARIABLES], ["X", "Y", "W"])
        self.assertEqual(options[COVARIATES], ["Z1", "Z2"])
        self.assertEqual(options["Method"], "Pearson")
        self.assertTrue(options["Holm adjustment"])
        self.assertFalse(options[SCATTER])

    def test_light_and_dark_style_the_note(self):
        from trama_qt import theme
        dialog = self.dialog()
        theme.apply(self.app, dark=False)
        light = self.app.styleSheet()
        theme.apply(self.app, dark=True)
        dark = self.app.styleSheet()
        theme.apply(self.app, dark=False)
        self.assertIn("QLabel#infoBanner", light)
        self.assertIn("QLabel#infoBanner", dark)
        self.assertNotEqual(light, dark)
        self.assertTrue(dialog.partial_note.objectName() == "infoBanner")

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
app = QApplication(["trama-partial-scale"])
theme.load_fonts()
theme.apply(app)
frame = pd.read_csv("tests/data/correlazione-parziale/campione.csv")
dialog = AnalysisDialog(None, frame, current=("Partial correlation", {}), only="Partial correlation")
dialog.show()
app.processEvents()
screen = dialog.screen().availableGeometry()
button = dialog.run_button
assert button.width() + 4 >= button.sizeHint().width(), (button.width(), button.sizeHint().width())
print(screen.width(), screen.height(), dialog.width(), dialog.height(), button.width())
"""


if __name__ == "__main__":
    unittest.main()
