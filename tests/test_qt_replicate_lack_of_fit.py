"""The replicate lack-of-fit checkbox in the Classica Qt dialog, offscreen."""
from pathlib import Path
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

import pandas as pd

from analisi.i18n import set_language
from analisi.ols_diagnostics import LACK_OF_FIT_SHEET, REPLICATE_LACK_OF_FIT, show_component, show_note
from analisi.processing import FieldError
from analisi.workbench import analyse


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def frame():
    return pd.read_csv(Path(__file__).resolve().parents[1] / "tests" / "data" / "replicate-lack-of-fit" / "repliche.csv")


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        elif hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        elif hasattr(control, "setChecked"):
            control.setChecked(bool(value))
        else:
            control.setText(str(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, current=None, language="en"):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language(language)
        dialog = AnalysisDialog(None, frame(), current=current or ("Multiple regression", {}))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_new_analysis_stores_the_checkbox_off_and_enter_confirms(self):
        dialog = self.dialog()
        index = dialog.tabs.indexOf(dialog._lof_scroll)
        self.assertGreaterEqual(index, 0)
        self.assertEqual(dialog.tabs.tabText(index), "Diagnostics and predictions")
        self.assertTrue(dialog.tabs.isTabVisible(index))
        box = dialog.controls[REPLICATE_LACK_OF_FIT][1]
        self.assertFalse(box.isChecked())
        self.assertTrue(box.isEnabled())
        self.assertFalse(dialog._lof_note.isVisibleTo(dialog))
        self.assertLessEqual(dialog.width(), 1024)
        self.assertLessEqual(dialog.height(), 768)
        self.assertTrue(dialog.run_button.isDefault())
        fill(dialog, Response="Y", Predictors=["X1", "X2"])
        QTest.keyClick(dialog.run_button, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(dialog.result)
        self.assertIs(dialog.result[1][REPLICATE_LACK_OF_FIT], False)

    def test_tab_reaches_the_checkbox_and_a_saved_check_survives(self):
        saved = {"Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
                 "Family": "Linear", REPLICATE_LACK_OF_FIT: True}
        dialog = self.dialog(current=("Multiple regression", saved))
        box = dialog.controls[REPLICATE_LACK_OF_FIT][1]
        self.assertTrue(box.isChecked())
        dialog.tabs.setCurrentWidget(dialog._lof_scroll)
        dialog._lof_scroll.setFocus()
        self.app.processEvents()
        reached = False
        for _ in range(15):
            QTest.keyClick(dialog.focusWidget() or dialog, Qt.Key.Key_Tab)
            self.app.processEvents()
            if dialog.focusWidget() is box:
                reached = True
                break
        self.assertTrue(reached, "Tab did not reach the replicate lack-of-fit checkbox")
        dialog.accept()
        self.assertIs(dialog.result[1][REPLICATE_LACK_OF_FIT], True)

    def test_other_families_hide_the_tab_and_omit_the_key(self):
        dialog = self.dialog()
        fill(dialog, Family="Poisson", Response="Y", Predictors=["X1"])
        self.app.processEvents()
        index = dialog.tabs.indexOf(dialog._lof_scroll)
        self.assertFalse(dialog.tabs.isTabVisible(index))
        self.assertIn(REPLICATE_LACK_OF_FIT, dialog.hidden)
        dialog.accept()
        self.assertNotIn(REPLICATE_LACK_OF_FIT, dialog.result[1])

    def test_weights_disable_the_checkbox_and_explain_it_in_italian(self):
        dialog = self.dialog(language="it")
        fill(dialog, Response="Y", Predictors=["X1", "X2"], **{"Gaussian weighting": "1/abs(Y)"})
        dialog.tabs.setCurrentWidget(dialog._lof_scroll)
        self.app.processEvents()
        box = dialog.controls[REPLICATE_LACK_OF_FIT][1]
        self.assertFalse(box.isEnabled())
        self.assertEqual(dialog._lof_note.objectName(), "infoBanner")
        self.assertTrue(dialog._lof_note.isVisibleTo(dialog))
        self.assertIn("senza pesi", dialog._lof_note.text())
        self.assertEqual(dialog.tabs.tabText(dialog.tabs.indexOf(dialog._lof_scroll)), "Diagnostica e previsioni")
        box.setChecked(True)
        dialog.accept()
        self.assertIs(dialog.result[1][REPLICATE_LACK_OF_FIT], True)
        message = dialog._message(FieldError(REPLICATE_LACK_OF_FIT, f"{REPLICATE_LACK_OF_FIT} must be yes or no."))
        self.assertIn("sì o no", message)
        self.assertIn("Test di mancato adattamento sulle repliche", message)

    def test_the_result_sheet_translates_components_and_the_note(self):
        from trama_qt.models import FrameModel
        from trama_qt.result_tabs import result_labels
        result = analyse("Multiple regression", frame(), {
            "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
            "Family": "Linear", REPLICATE_LACK_OF_FIT: True})
        table = result.tables[LACK_OF_FIT_SHEET]
        set_language("it")
        caption, headers = result_labels("Multiple regression", LACK_OF_FIT_SHEET)
        model = FrameModel(table, {"Component": show_component, "Note": show_note}, header_labels=headers)
        self.assertEqual(caption, "Mancato adattamento sulle repliche")
        self.assertEqual(model.headerData(0, Qt.Orientation.Horizontal), "Componente")
        self.assertEqual(model.headerData(2, Qt.Orientation.Horizontal), "gdl")
        self.assertEqual(model.plain_text(0, 0), "Residuo")
        self.assertEqual(model.plain_text(2, 0), "Mancato adattamento")
        note_column = list(table.columns).index("Note") + 1
        self.assertIn("tutti i predittori", model.plain_text(2, note_column))
        self.assertEqual(model.plain_text(2, 1), "32")
        self.assertEqual(model.plain_text(2, list(table.columns).index("F") + 1), "16")


if __name__ == "__main__":
    unittest.main()
