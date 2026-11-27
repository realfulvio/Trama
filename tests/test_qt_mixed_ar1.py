"""Covariance structure and visit order in the Classic Qt mixed-model dialog."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:
    QApplication = None

import pandas as pd

from analisi.ar1 import AR1, COVARIANCE, SUBJECT_EFFECTS, VISIT_ORDER
from analisi.i18n import active_language, set_language

HERE = Path(__file__).resolve().parent / "data" / "reml-ar1"
METHOD = "Mixed-effects model (REML)"
RECIPE = {
    "Input format": "Long table",
    "Y": "Response",
    "Subject": "Subject",
    "Within factors": ["Visit"],
    "Between factors": ["Group"],
    COVARIANCE: AR1,
    VISIT_ORDER: ["V1", "V2", "V3", "V4"],
    "Post-hoc": "Unadjusted",
    "Comparison factor": "Group",
    "Condition on factors": ["Visit"],
    "Comparison families": "Separate",
}


def _app():
    app = QApplication.instance() or QApplication(["trama-mixed-ar1", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def visits():
    frame = pd.read_csv(HERE / "visite.csv")
    frame["Response"] = pd.to_numeric(frame["Response"], errors="coerce")
    return frame


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class MixedCovarianceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("en")

    def dialog(self, saved, language="en"):
        from trama_qt.analysis_dialog import AnalysisDialog

        set_language(language)
        dialog = AnalysisDialog(None, visits(), current=(METHOD, dict(saved)), only=METHOD)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def show_field(self, dialog, name):
        _caption, widget, form = dialog.rows[name]
        for index in range(dialog.tabs.count()):
            scroll = dialog.tabs.widget(index)
            if scroll.widget().layout() is form:
                dialog.tabs.setCurrentIndex(index)
                scroll.ensureWidgetVisible(widget)
                break
        self.app.processEvents()
        return widget

    def test_ar1_confirms_the_order_and_hides_the_denominator_method(self):
        dialog = self.dialog(RECIPE)
        self.assertLessEqual(dialog.width(), 1024)
        self.assertLessEqual(dialog.height(), 768)
        self.assertTrue(dialog.run_button.isVisible())
        self.assertFalse(any(shortcut.key() == QKeySequence("F1") for shortcut in dialog.findChildren(QShortcut)))
        covariance = self.show_field(dialog, COVARIANCE)
        editor = dialog.controls[VISIT_ORDER][1]
        self.assertEqual(covariance.currentData(), AR1)
        self.assertEqual(editor.values(), ["V1", "V2", "V3", "V4"])
        self.assertNotIn(VISIT_ORDER, dialog.hidden)
        self.assertIn("Denominator method", dialog.hidden)
        self.assertIn("approximate", editor.note.text())
        self.assertIn("6", editor.note.text())
        self.assertIn("3", editor.note.text())
        self.assertEqual(editor.note.objectName(), "infoBanner")
        editor.list.setCurrentRow(0)
        editor.move(1)
        self.assertEqual(editor.values(), ["V2", "V1", "V3", "V4"])
        editor.move(-1)
        self.assertEqual(editor.values(), ["V1", "V2", "V3", "V4"])
        covariance.setFocus()
        QTest.keyClick(covariance, Qt.Key.Key_Tab)
        self.app.processEvents()
        focus = self.app.focusWidget()
        self.assertIsNot(focus, covariance)
        self.assertTrue(editor.isAncestorOf(focus) or focus is editor)
        QTest.keyClick(focus, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(dialog.result)
        method, options = dialog.result
        self.assertEqual(method, METHOD)
        self.assertEqual(options[COVARIANCE], AR1)
        self.assertEqual(options[VISIT_ORDER], ["V1", "V2", "V3", "V4"])
        self.assertNotIn("Denominator method", options)

    def test_subject_effects_keep_the_denominator_and_drop_the_visit_order(self):
        saved = {**RECIPE, COVARIANCE: SUBJECT_EFFECTS, "Denominator method": "Kenward–Roger"}
        dialog = self.dialog(saved)
        self.assertEqual(dialog.controls[COVARIANCE][1].currentData(), SUBJECT_EFFECTS)
        self.assertIn(VISIT_ORDER, dialog.hidden)
        self.assertNotIn("Denominator method", dialog.hidden)
        self.assertFalse(dialog.controls[VISIT_ORDER][1].isVisible())
        dialog.controls[COVARIANCE][1].setCurrentIndex(dialog.controls[COVARIANCE][1].findData(AR1))
        self.app.processEvents()
        self.assertNotIn(VISIT_ORDER, dialog.hidden)
        order = dialog.controls[VISIT_ORDER][1].values()
        dialog.controls[COVARIANCE][1].setCurrentIndex(dialog.controls[COVARIANCE][1].findData(SUBJECT_EFFECTS))
        self.app.processEvents()
        self.assertEqual(dialog.controls[VISIT_ORDER][1].values(), order)
        self.assertEqual(dialog.controls["Denominator method"][1].currentData(), "Kenward–Roger")
        options = dialog.options()
        self.assertEqual(options[COVARIANCE], SUBJECT_EFFECTS)
        self.assertNotIn(VISIT_ORDER, options)
        self.assertEqual(options["Denominator method"], "Kenward–Roger")

    def test_italian_note_and_a_rejected_order_name_the_field(self):
        dialog = self.dialog(RECIPE, "it")
        covariance = dialog.controls[COVARIANCE][1]
        self.assertEqual(covariance.currentText(), "AR(1) per visite ordinate")
        editor = dialog.controls[VISIT_ORDER][1]
        self.assertIn("approssimati", editor.note.text())
        self.assertEqual(editor.up.toolTip(), "Sposta la visita in alto")
        self.assertEqual(editor.down.toolTip(), "Sposta la visita in basso")
        editor.levels = ["V1", "V2"]
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("visite", dialog.banner.text().casefold())
        self.assertEqual(dialog.error_field, VISIT_ORDER)

    def test_light_and_dark_keep_the_coverage_note(self):
        from trama_qt import theme

        dialog = self.dialog(RECIPE)
        note = dialog.controls[VISIT_ORDER][1].note
        self.show_field(dialog, VISIT_ORDER)
        theme.apply(self.app, dark=False)
        self.app.processEvents()
        light = self.app.styleSheet()
        self.assertTrue(note.isVisible())
        theme.apply(self.app, dark=True)
        self.app.processEvents()
        dark = self.app.styleSheet()
        self.assertNotEqual(light, dark)
        self.assertIn("QLabel#infoBanner", dark)
        self.assertTrue(note.isVisible())
        theme.apply(self.app, dark=False)

    def _emulated_screen(self, width, height, dpi):
        """Offscreen screen. 96 dpi is 100%; 144 dpi is the documented 150% emulation."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Path(folder.name) / "screen.json"
        config.write_text(json.dumps({"screens": [{
            "name": "s", "x": 0, "y": 0, "width": width, "height": height,
            "logicalDpi": dpi, "logicalBaseDpi": 96, "dpr": 1.0,
        }]}), encoding="utf-8")
        script = (
            "import pandas as pd\n"
            "from PySide6.QtWidgets import QApplication\n"
            "app = QApplication(['scale'])\n"
            "from trama_qt.analysis_dialog import AnalysisDialog\n"
            f"frame = pd.read_csv({str(HERE / 'visite.csv')!r})\n"
            "frame['Response'] = pd.to_numeric(frame['Response'], errors='coerce')\n"
            f"saved = {RECIPE!r}\n"
            "dialog = AnalysisDialog(None, frame, current=('Mixed-effects model (REML)', saved),"
            " only='Mixed-effects model (REML)')\n"
            "dialog.show()\n"
            "app.processEvents()\n"
            "editor = dialog.controls['Visit order'][1]\n"
            "assert editor.values() == ['V1', 'V2', 'V3', 'V4'], editor.values()\n"
            "assert dialog.run_button.isVisible()\n"
            "assert dialog.run_button.width() >= dialog.run_button.sizeHint().width() - 4\n"
            "assert editor.up.width() >= editor.up.sizeHint().width() - 4\n"
            "screen = dialog.screen().availableGeometry()\n"
            "assert dialog.width() <= screen.width() and dialog.height() <= screen.height()\n"
            "print(f'scale-dialog {dialog.width()}x{dialog.height()} screen {screen.width()}x{screen.height()}')\n"
        )
        env = os.environ.copy()
        env.pop("QT_SCALE_FACTOR", None)
        # Qt separates platform arguments at colons, including a Windows drive separator.
        env["QT_QPA_PLATFORM"] = f"offscreen:configfile={config.name}"
        project = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (project, env.get("PYTHONPATH"))))
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=config.parent,
            env=env, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        print(completed.stdout.strip())
        return completed.stdout

    def test_compact_and_emulated_one_and_a_half_scale_keep_the_controls(self):
        self._emulated_screen(1024, 768, 96)
        self._emulated_screen(1366, 768, 144)
