"""Edit native and saved Select and Transform recipes on Qt."""
from copy import deepcopy
import unittest

import pandas as pd

from analisi.i18n import active_language, set_language
from analisi.select_transform import CALCULATED, FILTERS, SELECT_TRANSFORM

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SelectTransformDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["select-transform-test", "-platform", "offscreen"])

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        self.frame = pd.DataFrame({"Group $": ["A", "B", "A"], "Value": [1., 2., 4.], "Limit": [2., 2., 2.]})

    def dialog(self, saved=None, **error):
        from trama_qt.analysis_dialog import AnalysisDialog

        dialog = AnalysisDialog(None, self.frame, current=(SELECT_TRANSFORM, saved or {}),
                                only=SELECT_TRANSFORM, **error)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_edit_restore_and_cancel_preserve_literal_columns_and_rule_order(self):
        recipe = {
            "Variables": ["Limit", "Group $"],
            "First row": "2",
            "Last row": "",
            FILTERS: [{"column": "Value", "operator": ">=", "target": "Number", "value": "2"}],
            CALCULATED: [{"name": "AA $", "expression": "Value + 1"},
                         {"name": "BB", "expression": '2 * COL("AA $")'}],
        }
        original = deepcopy(recipe)
        dialog = self.dialog(recipe)
        self.assertEqual(dialog.options(), recipe)
        self.assertIn("Filtri delle righe", [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())])
        columns = dialog.controls["Variables"][1]
        columns.list.setCurrentRow(1)
        columns.move(-1)
        self.assertEqual(dialog.options()["Variables"], ["Group $", "Limit"])
        conditions = dialog.controls[FILTERS][1]
        conditions.value.setText("3,5")
        self.assertEqual(dialog.options()[FILTERS][0]["value"], "3,5")
        formulas = dialog.controls[CALCULATED][1]
        formulas.list.setCurrentRow(1)
        formulas.up.click()
        self.assertEqual([rule["name"] for rule in dialog.options()[CALCULATED]], ["BB", "AA $"])
        formulas.remove_button.click()
        self.assertEqual(dialog.options()[CALCULATED], recipe[CALCULATED][:1])
        dialog.reject()
        self.assertEqual(recipe, original)

    def test_new_recipe_validation_focus_and_correction(self):
        dialog = self.dialog()
        conditions = dialog.controls[FILTERS][1]
        formulas = dialog.controls[CALCULATED][1]
        conditions.add_button.click()
        conditions.column.setCurrentIndex(conditions.column.findData("Value"))
        conditions.value.setText("wrong")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("numero finito", dialog.banner.text())
        self.assertIs(dialog.focusWidget(), conditions.value)
        conditions.value.setText("1,5")
        self.assertTrue(dialog.banner.isHidden())
        formulas.add_button.click()
        formulas.name.setText("Ricalcolo")
        formulas.expression.setPlainText('COL("missing")')
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), formulas.expression)
        formulas.expression.setPlainText("WITH_SEED(1, GAUSS(Value, 0))")
        dialog.accept()
        method, options = dialog.result
        self.assertEqual(method, SELECT_TRANSFORM)
        self.assertEqual(options[FILTERS], [{"column": "Value", "operator": "=", "target": "Number", "value": "1,5"}])
        self.assertEqual(options[CALCULATED], [{"name": "Ricalcolo", "expression": "WITH_SEED(1, GAUSS(Value, 0))"}])

    def test_filter_target_controls_and_worker_error_restore(self):
        recipe = {FILTERS: [{"column": "Group $", "operator": "Is not missing", "target": "Text", "value": "old"}]}
        dialog = self.dialog(recipe, error="Condition 1: choose an existing variable.", error_field=FILTERS)
        conditions = dialog.controls[FILTERS][1]
        self.assertIs(dialog.focusWidget(), conditions.column)
        self.assertFalse(conditions.target.isEnabled())
        conditions.operator.setCurrentIndex(conditions.operator.findData("="))
        conditions.target.setCurrentIndex(conditions.target.findData("Column"))
        self.assertTrue(conditions.target.isEnabled())
        conditions.other_column.setCurrentIndex(conditions.other_column.findData("Group $"))
        value, = dialog.options()[FILTERS]
        self.assertEqual(value["value"], "Group $")
        self.assertEqual(value["target"], "Column")
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_recipe_validation_does_not_evaluate_statistics_on_a_fake_empty_table(self):
        recipe = {CALCULATED: [{"name": "Weight", "expression": "1 / COUNT(Value)"}]}
        dialog = self.dialog(recipe)
        dialog.accept()
        self.assertIsNotNone(dialog.result, dialog.banner.text())
