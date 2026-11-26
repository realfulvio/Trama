"""Linked coefficients in the two Classica Qt dialogs (Fit custom equation and Global fit custom equation), offscreen.

Data: tests/data/coefficient_links/curve.csv, Y = B + A*X + C*X^2 with C = 2*A + 1 (A = 1.5, C = 4).
"""
from copy import deepcopy
from pathlib import Path
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "coefficient_links"
LINK = {"source": "A", "factor": 2.0, "offset": 1.0}
SINGLE = {"X": "x", "Y": "y", "Equation": "B + A*X + C*X^2",
          "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                         {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                         {"name": "C", "start": 3.0, "lower": None, "upper": None, "fixed": False, "link": LINK}]}
GLOBAL = {"X": "x", "Y": "y", "Group": "serie", "Equation": "B + A*X + C*X^2", "Series constraints": [],
          "Parameters": [{**SINGLE["Parameters"][0], "shared": True}, {**SINGLE["Parameters"][1], "shared": False},
                         {**SINGLE["Parameters"][2], "shared": True}]}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class LinkEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)
        self.frame = pd.read_csv(DATA / "curve.csv")

    def dialog(self, method, recipe):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.frame, current=(method, deepcopy(recipe)), only=method)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_single_dialog_shows_the_resolved_formula_and_keeps_the_recipe(self):
        dialog = self.dialog("Fit custom equation", SINGLE)
        editor = dialog.controls["Parameters"][1]
        summary, problem = editor.preview.texts()
        self.assertIn("C = 2*A + 1", summary)
        self.assertIn("Order: A → C.", summary)
        self.assertEqual(problem, "")
        # The linked start is read-only and shows the value from the link: 2 * 1 + 1.
        self.assertEqual(editor.cell(2, editor.START), "3")
        self.assertFalse(editor.table.item(2, editor.START).flags() & Qt.ItemFlag.ItemIsEditable)
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        self.assertEqual(dialog.result[1]["Parameters"], SINGLE["Parameters"])

    def test_single_rename_delete_and_conflicts(self):
        dialog = self.dialog("Fit custom equation", SINGLE)
        editor = dialog.controls["Parameters"][1]
        editor.table.item(0, editor.NAME).setText("K")
        self.assertEqual(editor.cell(2, editor.SOURCE), "K")
        self.assertIn("Links now follow K (was A).", editor.preview.texts()[1])
        dialog.controls["Equation"][1].setPlainText("B + K*X + C*X^2")
        # Fixed and Linked exclude each other: ticking Fixed removes the link.
        editor.table.item(2, editor.FIXED).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(editor.cell(2, editor.SOURCE), "")
        editor.table.item(2, editor.FIXED).setCheckState(Qt.CheckState.Unchecked)
        editor.set_link(2, "K", "-2", "1")
        # Removing the source frees the dependent, with the start it had through the link (−2·1 + 1).
        editor.remove_row(0)
        self.assertEqual(editor.cell(1, editor.SOURCE), "")
        self.assertEqual(editor.cell(1, editor.START), "-1")
        self.assertTrue(editor.table.item(1, editor.START).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertIn("free again", editor.preview.texts()[1])
        records = editor.values()
        self.assertNotIn("link", records[-1])
        self.assertEqual(records[-1]["start"], -1.0)

    def test_single_cycle_is_shown_before_run_and_focused(self):
        recipe = deepcopy(SINGLE)
        recipe["Parameters"][0]["link"] = {"source": "C", "factor": 0.5, "offset": -0.5}
        dialog = self.dialog("Fit custom equation", recipe)
        editor = dialog.controls["Parameters"][1]
        self.assertIn("The links form a cycle: A → C → A.", editor.preview.texts()[1])
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertEqual(editor.table.currentColumn(), editor.SOURCE)
        editor.table.item(0, editor.SOURCE).setText("")
        self.assertFalse(dialog.banner.isVisible())
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_italian_labels_and_messages(self):
        set_language("it")
        recipe = deepcopy(SINGLE)
        recipe["Parameters"][2]["lower"], recipe["Parameters"][2]["upper"] = 10.0, 20.0
        recipe["Parameters"][0].update(lower=-1.0, upper=1.0, start=0.0)
        dialog = self.dialog("Fit custom equation", recipe)
        editor = dialog.controls["Parameters"][1]
        headers = [editor.table.horizontalHeaderItem(i).text() for i in range(editor.table.columnCount())]
        self.assertEqual(headers[-3:], ["Collegato a", "Fattore", "Scostamento"])
        problem = editor.preview.texts()[1]
        self.assertTrue(problem.startswith("Legami: C: i suoi limiti (da 10 a 20)"), problem)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("non lasciano valori ammessi per A", dialog.banner.text())

    def test_global_dialog_linked_scopes_series_and_reopen(self):
        for language in ("en", "it"):
            set_language(language)
            dialog = self.dialog("Global fit custom equation", GLOBAL)
            coefficients = dialog.controls["Parameters"][1]
            self.assertEqual(coefficients.rows()[2]["scope"], "Linked shared")
            self.assertIn("C = 2*A + 1", coefficients.preview.texts()[0])
            series = dialog.controls["Series constraints"][1]
            series.select_series("Uno")
            self.assertFalse(series.fields[("C", "fixed")].isEnabled())
            self.assertFalse(series.fields[("C", "initial")].isEnabled())
            self.assertTrue(series.fields[("C", "upper")].isEnabled())
            dialog.accept()
            self.assertEqual(dialog.result[1]["Parameters"], GLOBAL["Parameters"], language)

    def test_global_preview_accepts_effective_starts_of_local_coefficients(self):
        set_language("en")
        recipe = deepcopy(GLOBAL)
        recipe["Parameters"][0].update(start=0.0, shared=False)
        recipe["Parameters"][2].update(lower=1.5, shared=False)
        recipe["Series constraints"] = [
            {"series": label, "parameters": {"A": {"initial": 3.0}}} for label in ("Uno", "Due")
        ]
        dialog = self.dialog("Global fit custom equation", recipe)
        summary, problem = dialog.controls["Parameters"][1].preview.texts()
        self.assertEqual(problem, "")
        self.assertIn("Default starting value C", summary)
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        self.assertEqual(dialog.result[1]["Series constraints"], recipe["Series constraints"])

    def test_global_source_choice_sets_the_scope_and_errors_name_the_series(self):
        recipe = deepcopy(GLOBAL)
        del recipe["Parameters"][2]["link"]
        dialog = self.dialog("Global fit custom equation", recipe)
        coefficients = dialog.controls["Parameters"][1]
        coefficients.set_cell(2, coefficients.SOURCE, "A")
        self.assertEqual(coefficients.rows()[2]["scope"], "Linked shared")
        self.assertEqual((coefficients.cell(2, coefficients.FACTOR), coefficients.cell(2, coefficients.OFFSET)),
                         ("1", "0"))
        coefficients.set_cell(2, coefficients.FACTOR, "2")
        coefficients.set_cell(2, coefficients.OFFSET, "1")
        self.assertEqual(coefficients.values()[2]["link"], LINK)
        # A shared link to a local source: the banner names the coefficient, the cursor goes to its scope row.
        coefficients.set_cell(2, coefficients.SOURCE, "B")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("estimated separately in series 'Uno'", dialog.banner.text())
        coefficients.set_cell(2, coefficients.SOURCE, "A")
        self.assertFalse(dialog.banner.isVisible())
        series = dialog.controls["Series constraints"][1]
        series.set_override("Due", "C", "lower", "10")
        series.set_override("Due", "C", "upper", "20")
        coefficients.set_cell(0, coefficients.LOWER, "0")
        coefficients.set_cell(0, coefficients.UPPER, "2")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.text().startswith("Series constraints: Series 'Due', C: its limits")
                        or "Series 'Due', C: its limits" in dialog.banner.text(), dialog.banner.text())
        series.clear_all()
        self.assertFalse(dialog.banner.isVisible())
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_keyboard_enter_and_escape(self):
        dialog = self.dialog("Fit custom equation", SINGLE)
        editor = dialog.controls["Parameters"][1]
        # Tab walks the cells of the table (the smoke checks it on a real window); the buttons never take Enter.
        self.assertTrue(editor.table.tabKeyNavigation())
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertIsNone(dialog.result)


if __name__ == "__main__":
    unittest.main()


class CatalogTests(unittest.TestCase):
    def test_every_link_text_has_both_languages_and_the_same_placeholders(self):
        from analisi.i18n import _LINKS_EN, _LINKS_IT, placeholders
        self.assertEqual(set(_LINKS_EN), set(_LINKS_IT))
        for key, text in _LINKS_EN.items():
            self.assertEqual(placeholders(text), placeholders(_LINKS_IT[key]), key)

    def test_engine_messages_match_the_catalog(self):
        from analisi.field_error import FieldError
        from analisi.global_custom_fit import global_custom_fit
        from trama_qt.coefficient_links import translate
        frame = pd.read_csv(DATA / "curve.csv")
        bad = deepcopy(GLOBAL)
        bad["Parameters"][2]["link"] = {"source": "B", "factor": 2.0, "offset": 1.0}
        with self.assertRaises(FieldError) as raised:
            global_custom_fit(frame, bad)
        set_language("it")
        self.addCleanup(set_language, "en")
        self.assertIn("stimato a parte nella serie 'Uno'", translate(raised.exception))
