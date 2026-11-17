"""Tk dialog tests for heat-map color legend number format: EN/IT choices, visibility, errors and focus."""
from tkinter import ttk
import unittest

from analisi import i18n
from analisi.heatmap import SHOW_LEGEND
from analisi.heatmap_number_format import LEGEND_DECIMALS, NUMBER_FORMAT
from tests.test_heatmap_dialog import CATEGORIES, NUMERIC, DialogCase


class HeatMapLegendNumberFormatDialogTests(DialogCase):
    def test_visibility_canonical_selection_and_inactive_decimals(self):
        def action(dialog, seen):
            controls = dialog.controls
            seen["initial"] = (self.placed(dialog, NUMBER_FORMAT), self.placed(dialog, LEGEND_DECIMALS))
            controls[NUMBER_FORMAT][1].set("Scientific")
            dialog.update()
            seen["scientific"] = self.placed(dialog, LEGEND_DECIMALS)
            controls[LEGEND_DECIMALS][1].set("2,0")
            controls[NUMBER_FORMAT][1].set("Automatic")
            dialog.update()
            seen["auto_again"] = self.placed(dialog, LEGEND_DECIMALS)
            controls[LEGEND_DECIMALS][1].set("not-a-number")
            seen["auto_ok"] = dialog.validate()
            seen["auto_options"] = dict(dialog.result[1])

            controls[NUMBER_FORMAT][1].set("Fixed")
            dialog.update()
            controls[LEGEND_DECIMALS][1].set("3")
            controls[SHOW_LEGEND][1].set(False)
            dialog.update()
            seen["hidden_legend"] = (self.placed(dialog, NUMBER_FORMAT), self.placed(dialog, LEGEND_DECIMALS))
            controls[LEGEND_DECIMALS][1].set("99")
            seen["hidden_ok"] = dialog.validate()
            seen["hidden_options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["initial"], (True, False))
        self.assertTrue(seen["scientific"])
        self.assertFalse(seen["auto_again"])
        self.assertTrue(seen["auto_ok"])
        self.assertEqual(seen["auto_options"][NUMBER_FORMAT], "Automatic")
        self.assertNotIn(LEGEND_DECIMALS, seen["auto_options"])
        self.assertEqual(seen["hidden_legend"], (False, False))
        self.assertTrue(seen["hidden_ok"])
        self.assertNotIn(NUMBER_FORMAT, seen["hidden_options"])
        self.assertNotIn(LEGEND_DECIMALS, seen["hidden_options"])

    def test_categorical_map_hides_and_ignores_number_format_fields(self):
        def action(dialog, seen):
            seen["placed"] = (self.placed(dialog, NUMBER_FORMAT), self.placed(dialog, LEGEND_DECIMALS))
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.categories, {**CATEGORIES, NUMBER_FORMAT: "Fixed", LEGEND_DECIMALS: "bad"}, action)
        self.assertEqual(seen["placed"], (False, False))
        self.assertTrue(seen["ok"])
        self.assertNotIn(NUMBER_FORMAT, seen["options"])
        self.assertNotIn(LEGEND_DECIMALS, seen["options"])

    def test_error_selects_legend_tab_focuses_decimals_and_keeps_buttons_reachable(self):
        def action(dialog, seen):
            controls = dialog.controls
            controls[NUMBER_FORMAT][1].set("Fixed")
            dialog.update()
            controls[LEGEND_DECIMALS][1].set("2.5")
            ok, message, selected = self.rejected(dialog, LEGEND_DECIMALS)
            seen["rejected"] = (
                ok,
                LEGEND_DECIMALS in message,
                dialog.fields.tab(selected, "text"),
                dialog.focus_get() is dialog.field_rows[LEGEND_DECIMALS][1],
                dialog.winfo_exists(),
            )
            controls[LEGEND_DECIMALS][1].set("3")
            dialog.update()
            button = self._run_button(dialog)
            seen["reachable"] = (
                button is not None
                and button.winfo_rooty() + button.winfo_height() <= 768
                and dialog.winfo_rooty() + dialog.winfo_height() <= 768
            )
            seen["fixed_ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["rejected"], (False, True, "Legend", True, True))
        self.assertTrue(seen["reachable"])
        self.assertTrue(seen["fixed_ok"])
        self.assertEqual(seen["options"][NUMBER_FORMAT], "Fixed")
        self.assertEqual(seen["options"][LEGEND_DECIMALS], 3)

    def test_italian_labels_choices_errors_and_canonical_recipe_round_trip(self):
        self.use("it")

        def action(dialog, seen):
            seen["captions"] = (
                dialog.field_rows[NUMBER_FORMAT][0].cget("text"),
                dialog.field_rows[LEGEND_DECIMALS][0].cget("text"),
            )
            combo = dialog.field_rows[NUMBER_FORMAT][1]
            seen["values"] = list(combo.cget("values"))
            combo.set("Scientifico")
            combo.event_generate("<<ComboboxSelected>>")
            dialog.update()
            seen["canonical_mode"] = dialog.controls[NUMBER_FORMAT][1].get()
            dialog.controls[LEGEND_DECIMALS][1].set("2,5")
            ok, message, selected = self.rejected(dialog, LEGEND_DECIMALS)
            seen["rejected"] = (ok, message, dialog.fields.tab(selected, "text"))
            dialog.controls[LEGEND_DECIMALS][1].set("2,0")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["captions"], ("Formato numerico della legenda", "Decimali della legenda"))
        self.assertEqual(seen["values"], ["Automatico", "Decimali fissi", "Scientifico"])
        self.assertEqual(seen["canonical_mode"], "Scientific")
        self.assertFalse(seen["rejected"][0])
        self.assertIn("Decimali della legenda", seen["rejected"][1])
        self.assertIn("numero intero da 0 a 8", seen["rejected"][1])
        self.assertEqual(seen["rejected"][2], "Legenda")
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][NUMBER_FORMAT], "Scientific")
        self.assertEqual(seen["options"][LEGEND_DECIMALS], 2)
        self.assertIs(type(seen["options"][LEGEND_DECIMALS]), int)

    @staticmethod
    def _run_button(dialog):
        target = i18n.ui("Run Analysis")
        stack = [dialog]
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.Button) and widget.cget("text") == target:
                return widget
            stack.extend(widget.winfo_children())
        return None


if __name__ == "__main__":
    unittest.main()
