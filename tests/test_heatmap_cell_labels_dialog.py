"""Tk dialog tests for heat-map cell label options: visibility, swatch/picker, EN/IT, errors and focus."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from analisi import i18n
from analisi.heatmap_cell_labels import (
    CELL_LABEL_COLOR,
    CELL_LABEL_COLOR_MODE,
    CELL_LABEL_DECIMALS,
    CELL_LABEL_FONT_SIZE,
    CELL_LABEL_NUMBER_FORMAT,
    CELL_LABEL_PREFIX,
    CELL_LABEL_SUFFIX,
)
from tests.test_heatmap_dialog import CATEGORIES, NUMERIC, DialogCase


class HeatMapCellLabelsDialogTests(DialogCase):
    def test_visibility_swatch_picker_and_inactive_fields_not_copied(self):
        def action(dialog, seen):
            controls = dialog.controls
            seen["initially_hidden"] = [
                self.placed(dialog, name)
                for name in (
                    CELL_LABEL_NUMBER_FORMAT,
                    CELL_LABEL_DECIMALS,
                    CELL_LABEL_FONT_SIZE,
                    CELL_LABEL_COLOR_MODE,
                    CELL_LABEL_COLOR,
                    CELL_LABEL_PREFIX,
                    CELL_LABEL_SUFFIX,
                )
            ]
            seen["default_color"] = controls[CELL_LABEL_COLOR][1].get()
            controls[CELL_LABEL_FONT_SIZE][1].set("nan")
            controls[CELL_LABEL_DECIMALS][1].set("-9")
            controls[CELL_LABEL_COLOR_MODE][1].set("Custom")
            controls[CELL_LABEL_COLOR][1].set("nonsense")
            seen["hidden_valid"] = dialog.validate()
            seen["hidden_options"] = dict(dialog.result[1])

            controls["Show cell values"][1].set(True)
            dialog.update()
            seen["shown_auto"] = (
                self.placed(dialog, CELL_LABEL_NUMBER_FORMAT),
                self.placed(dialog, CELL_LABEL_DECIMALS),
                self.placed(dialog, CELL_LABEL_FONT_SIZE),
                self.placed(dialog, CELL_LABEL_COLOR_MODE),
                self.placed(dialog, CELL_LABEL_COLOR),
                self.placed(dialog, CELL_LABEL_PREFIX),
                self.placed(dialog, CELL_LABEL_SUFFIX),
            )
            controls[CELL_LABEL_NUMBER_FORMAT][1].set("Fixed")
            controls[CELL_LABEL_COLOR_MODE][1].set("Custom")
            dialog.update()
            seen["shown_custom"] = (
                self.placed(dialog, CELL_LABEL_DECIMALS),
                self.placed(dialog, CELL_LABEL_COLOR),
                seen["default_color"],
            )
            color_frame = dialog.field_rows[CELL_LABEL_COLOR][1]
            swatch = next(w for w in color_frame.winfo_children() if isinstance(w, tk.Label))
            pick_btn = next(w for w in color_frame.winfo_children() if isinstance(w, ttk.Button))
            with patch("analisi.graph_dialog.colorchooser.askcolor", return_value=((255, 51, 0), "#ff3300")):
                pick_btn.invoke()
            dialog.update()
            seen["picked"] = (controls[CELL_LABEL_COLOR][1].get(), swatch.cget("background"))

            controls[CELL_LABEL_COLOR_MODE][1].set("Auto contrast")
            controls[CELL_LABEL_NUMBER_FORMAT][1].set("Automatic")
            controls[CELL_LABEL_FONT_SIZE][1].set("   ")
            dialog.update()
            seen["final_ok"] = dialog.validate()
            seen["final_options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["initially_hidden"], [False] * 7)
        self.assertTrue(seen["hidden_valid"])
        for key in (CELL_LABEL_NUMBER_FORMAT, CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE,
                    CELL_LABEL_COLOR_MODE, CELL_LABEL_COLOR, CELL_LABEL_PREFIX, CELL_LABEL_SUFFIX):
            self.assertNotIn(key, seen["hidden_options"])
        self.assertEqual(seen["shown_auto"], (True, False, True, True, True, True, True))
        self.assertEqual(seen["shown_custom"], (True, True, "#162633"))
        self.assertEqual(seen["picked"], ("#ff3300", "#ff3300"))
        self.assertTrue(seen["final_ok"])
        self.assertNotIn(CELL_LABEL_DECIMALS, seen["final_options"])
        self.assertNotIn(CELL_LABEL_COLOR, seen["final_options"])
        self.assertEqual(seen["final_options"][CELL_LABEL_FONT_SIZE], "")

    def test_categorical_map_hides_numeric_cell_label_controls(self):
        def action(dialog, seen):
            dialog.controls["Show cell values"][1].set(True)
            dialog.update()
            seen["placed"] = (
                self.placed(dialog, CELL_LABEL_NUMBER_FORMAT),
                self.placed(dialog, CELL_LABEL_DECIMALS),
                self.placed(dialog, CELL_LABEL_FONT_SIZE),
                self.placed(dialog, CELL_LABEL_COLOR_MODE),
                self.placed(dialog, CELL_LABEL_PREFIX),
                self.placed(dialog, CELL_LABEL_SUFFIX),
            )
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(
            self.categories,
            {**CATEGORIES, CELL_LABEL_NUMBER_FORMAT: "Fixed", CELL_LABEL_DECIMALS: "bad"},
            action,
        )
        self.assertEqual(seen["placed"], (False, False, True, True, True, True))
        self.assertTrue(seen["ok"])
        self.assertNotIn(CELL_LABEL_NUMBER_FORMAT, seen["options"])
        self.assertNotIn(CELL_LABEL_DECIMALS, seen["options"])

    def test_errors_focus_responsible_entry_and_keep_run_reachable_at_1024_and_1600(self):
        def action(dialog, seen):
            controls = dialog.controls
            controls["Show cell values"][1].set(True)
            controls[CELL_LABEL_NUMBER_FORMAT][1].set("Fixed")
            controls[CELL_LABEL_COLOR_MODE][1].set("Custom")
            dialog.update()

            controls[CELL_LABEL_DECIMALS][1].set("2.5")
            ok, message, selected = self.rejected(dialog, CELL_LABEL_DECIMALS)
            seen["decimals_err"] = (
                ok,
                CELL_LABEL_DECIMALS in message,
                dialog.fields.tab(selected, "text"),
                dialog.focus_get() is dialog.field_rows[CELL_LABEL_DECIMALS][1],
            )
            controls[CELL_LABEL_DECIMALS][1].set("2")

            controls[CELL_LABEL_FONT_SIZE][1].set("37")
            ok, message, _ = self.rejected(dialog, CELL_LABEL_FONT_SIZE)
            seen["font_err"] = (
                ok,
                CELL_LABEL_FONT_SIZE in message,
                dialog.focus_get() is dialog.field_rows[CELL_LABEL_FONT_SIZE][1],
            )
            controls[CELL_LABEL_FONT_SIZE][1].set("12,5")

            controls[CELL_LABEL_COLOR][1].set("nonsense")
            ok, message, _ = self.rejected(dialog, CELL_LABEL_COLOR)
            color_entry = next(w for w in dialog.field_rows[CELL_LABEL_COLOR][1].winfo_children() if isinstance(w, ttk.Entry))
            seen["color_err"] = (ok, CELL_LABEL_COLOR in message, dialog.focus_get() is color_entry)
            controls[CELL_LABEL_COLOR][1].set("#ff3300")

            controls[CELL_LABEL_PREFIX][1].set("a" * 81)
            ok, message, _ = self.rejected(dialog, CELL_LABEL_PREFIX)
            seen["prefix_err"] = (ok, CELL_LABEL_PREFIX in message, dialog.focus_get() is dialog.field_rows[CELL_LABEL_PREFIX][1])
            controls[CELL_LABEL_PREFIX][1].set("$x$_")
            controls[CELL_LABEL_SUFFIX][1].set(" %")
            dialog.update()

            button = self._run_button(dialog)
            seen["reachable_1024"] = (
                button is not None
                and button.winfo_viewable()
                and button.winfo_rooty() + button.winfo_height() <= 768
                and dialog.winfo_rooty() + dialog.winfo_height() <= 768
            )
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["decimals_err"], (False, True, "Graph options", True))
        self.assertEqual(seen["font_err"], (False, True, True))
        self.assertEqual(seen["color_err"], (False, True, True))
        self.assertEqual(seen["prefix_err"], (False, True, True))
        self.assertTrue(seen["reachable_1024"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][CELL_LABEL_FONT_SIZE], 12.5)
        self.assertEqual(seen["options"][CELL_LABEL_PREFIX], "$x$_")
        self.assertEqual(seen["options"][CELL_LABEL_SUFFIX], " %")

    def test_italian_ui_choices_errors_and_canonical_recipe(self):
        self.use("it")

        def action(dialog, seen):
            dialog.controls["Show cell values"][1].set(True)
            dialog.update()
            fmt_combo = dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][1]
            mode_combo = dialog.field_rows[CELL_LABEL_COLOR_MODE][1]
            seen["captions"] = tuple(
                dialog.field_rows[k][0].cget("text")
                for k in (
                    CELL_LABEL_NUMBER_FORMAT,
                    CELL_LABEL_DECIMALS,
                    CELL_LABEL_FONT_SIZE,
                    CELL_LABEL_COLOR_MODE,
                    CELL_LABEL_COLOR,
                    CELL_LABEL_PREFIX,
                    CELL_LABEL_SUFFIX,
                )
            )
            seen["fmt_values"] = list(fmt_combo.cget("values"))
            seen["mode_values"] = list(mode_combo.cget("values"))
            fmt_combo.set("Scientifico")
            fmt_combo.event_generate("<<ComboboxSelected>>")
            mode_combo.set("Personalizzato")
            mode_combo.event_generate("<<ComboboxSelected>>")
            dialog.update()
            dialog.controls[CELL_LABEL_DECIMALS][1].set("2,5")
            ok, msg, _ = self.rejected(dialog, CELL_LABEL_DECIMALS)
            seen["rejected"] = (ok, msg)
            dialog.controls[CELL_LABEL_DECIMALS][1].set("3,0")
            dialog.controls[CELL_LABEL_FONT_SIZE][1].set("11,5")
            dialog.controls[CELL_LABEL_PREFIX][1].set(" ~")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(
            seen["captions"],
            (
                "Formato numerico etichette",
                "Decimali etichette",
                "Dimensione font etichette",
                "Modalità colore etichette",
                "Colore etichette",
                "Prefisso etichette",
                "Suffisso etichette",
            ),
        )
        self.assertEqual(seen["fmt_values"], ["Automatico", "Decimali fissi", "Scientifico"])
        self.assertEqual(seen["mode_values"], ["Contrasto automatico", "Personalizzato"])
        self.assertFalse(seen["rejected"][0])
        self.assertIn("Decimali etichette", seen["rejected"][1])
        self.assertIn("numero intero da 0 a 8", seen["rejected"][1])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][CELL_LABEL_NUMBER_FORMAT], "Scientific")
        self.assertEqual(seen["options"][CELL_LABEL_DECIMALS], 3)
        self.assertIs(type(seen["options"][CELL_LABEL_DECIMALS]), int)
        self.assertEqual(seen["options"][CELL_LABEL_FONT_SIZE], 11.5)
        self.assertEqual(seen["options"][CELL_LABEL_COLOR_MODE], "Custom")
        self.assertEqual(seen["options"][CELL_LABEL_PREFIX], " ~")

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
