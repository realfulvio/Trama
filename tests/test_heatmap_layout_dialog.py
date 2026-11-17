"""Tk dialog tests for heat-map Layout tab: scrolling, visibility, errors, focus, and EN/IT round-trip."""
from tkinter import ttk
import unittest

from analisi import i18n
from analisi.heatmap_layout import (
    COLUMN_GAP_MODE,
    COLUMN_GAP_SIZE,
    COLUMN_GAPS_AFTER,
    COLUMN_LABEL_EVERY,
    COLUMN_LABEL_FONT_SIZE,
    COLUMN_LABEL_FREQUENCY,
    COLUMN_LABEL_ROTATION,
    COLUMN_LABEL_SIDE,
    ROW_GAP_MODE,
    ROW_GAP_SIZE,
    ROW_GAPS_AFTER,
    ROW_LABEL_EVERY,
    ROW_LABEL_FONT_SIZE,
    ROW_LABEL_FREQUENCY,
    ROW_LABEL_SIDE,
    SHOW_COLUMN_LABELS,
    SHOW_ROW_LABELS,
)
from tests.test_heatmap_dialog import NUMERIC, DialogCase


class HeatMapLayoutDialogTests(DialogCase):
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

    @staticmethod
    def _scroll_canvas(dialog):
        return dialog.field_rows[ROW_GAP_MODE][1].master._scroll_canvas

    def test_visibility_and_inactive_layout_fields_do_not_block_or_save(self):
        def action(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["initial_hidden"] = [
                self.placed(dialog, name)
                for name in (
                    ROW_GAP_SIZE,
                    ROW_GAPS_AFTER,
                    COLUMN_GAP_SIZE,
                    COLUMN_GAPS_AFTER,
                    ROW_LABEL_EVERY,
                    COLUMN_LABEL_EVERY,
                )
            ]
            controls[ROW_GAP_SIZE][1].set("-5")
            controls[ROW_GAPS_AFTER][1].set("0,0")
            controls[ROW_LABEL_EVERY][1].set("bad")
            controls[SHOW_ROW_LABELS][1].set(False)
            controls[ROW_LABEL_FONT_SIZE][1].set("inf")
            controls[ROW_LABEL_SIDE][1].set("bad")
            dialog.update()
            seen["row_labels_hidden"] = [
                self.placed(dialog, name)
                for name in (ROW_LABEL_FREQUENCY, ROW_LABEL_EVERY, ROW_LABEL_SIDE, ROW_LABEL_FONT_SIZE)
            ]
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["tabs"], ["Variables", "Graph options", "Layout", "Colors", "Categories", "Legend"])
        self.assertEqual(seen["initial_hidden"], [False] * 6)
        self.assertEqual(seen["row_labels_hidden"], [False] * 4)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][SHOW_ROW_LABELS], False)
        for hidden_key in (ROW_GAP_SIZE, ROW_GAPS_AFTER, ROW_LABEL_FREQUENCY, ROW_LABEL_EVERY, ROW_LABEL_SIDE, ROW_LABEL_FONT_SIZE):
            self.assertNotIn(hidden_key, seen["options"])

    def test_errors_select_layout_tab_scroll_to_field_focus_and_keep_buttons_reachable(self):
        def action(dialog, seen):
            controls = dialog.controls
            controls[ROW_GAP_MODE][1].set("Selected boundaries")
            controls[COLUMN_GAP_MODE][1].set("Selected boundaries")
            controls[ROW_LABEL_FREQUENCY][1].set("Every Nth")
            controls[COLUMN_LABEL_FREQUENCY][1].set("Every Nth")
            dialog.update_idletasks()
            canvas = self._scroll_canvas(dialog)
            layout_page = dialog.fields.tabs()[2]

            checks = [
                (ROW_GAP_SIZE, "-0.5", "0.25"),
                (ROW_GAPS_AFTER, "2,2", "2"),
                (COLUMN_GAPS_AFTER, "0", "1"),
                (ROW_LABEL_EVERY, "1.5", "2"),
                (COLUMN_LABEL_FONT_SIZE, str(10**400), "11,5"),
            ]
            for field, bad_val, good_val in checks:
                dialog.fields.select(0)
                controls[field][1].set(bad_val)
                ok, message, selected = self.rejected(dialog, field)
                dialog.update_idletasks()
                entry = dialog.field_rows[field][1]
                inside_canvas = (
                    entry.winfo_rooty() >= canvas.winfo_rooty()
                    and entry.winfo_rooty() + entry.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
                )
                seen[field] = (
                    ok,
                    field in message,
                    selected == layout_page,
                    dialog.focus_get() is entry,
                    inside_canvas,
                    dialog.winfo_exists(),
                )
                controls[field][1].set(good_val)

            controls[ROW_GAP_SIZE][1].set("0,25")
            button = self._run_button(dialog)
            seen["reachable"] = (
                button is not None
                and button.winfo_viewable()
                and button.winfo_rooty() + button.winfo_height() <= 768
                and dialog.winfo_rooty() + dialog.winfo_height() <= 768
            )
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        for field in (ROW_GAP_SIZE, ROW_GAPS_AFTER, COLUMN_GAPS_AFTER, ROW_LABEL_EVERY, COLUMN_LABEL_FONT_SIZE):
            self.assertEqual(seen[field], (False, True, True, True, True, True), field)
        self.assertTrue(seen["reachable"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][ROW_GAP_SIZE], 0.25)
        self.assertEqual(seen["options"][COLUMN_LABEL_FONT_SIZE], 11.5)
        self.assertEqual(seen["options"][ROW_GAPS_AFTER], "2")

    def test_italian_stringvar_canonical_and_translated_choices_save_canonical(self):
        self.use("it")

        def action(dialog, seen):
            controls = dialog.controls
            seen["row_mode_caption"] = dialog.field_rows[ROW_GAP_MODE][0].cget("text")
            seen["row_mode_values"] = list(dialog.field_rows[ROW_GAP_MODE][1].cget("values"))
            seen["rot_values"] = list(dialog.field_rows[COLUMN_LABEL_ROTATION][1].cget("values"))

            # Canonical value set via variable StringVar updates translated combobox display.
            controls[ROW_GAP_MODE][1].set("Selected boundaries")
            dialog.update()
            seen["display_from_canonical"] = dialog.field_rows[ROW_GAP_MODE][1].get()

            # Translated value set via ChoiceBinding display StringVar resolves to canonical variable.
            dialog.choice_bindings[COLUMN_LABEL_ROTATION].display.set("Verticale")
            dialog.choice_bindings[COLUMN_LABEL_SIDE].display.set("Sopra")
            dialog.choice_bindings[ROW_LABEL_SIDE].display.set("Destra")
            dialog.update()
            seen["canonical_from_display"] = (
                controls[COLUMN_LABEL_ROTATION][1].get(),
                controls[COLUMN_LABEL_SIDE][1].get(),
                controls[ROW_LABEL_SIDE][1].get(),
            )

            controls[ROW_GAPS_AFTER][1].set("99")
            ok, message, _ = self.rejected(dialog, ROW_GAPS_AFTER)
            seen["it_err"] = (ok, message)
            controls[ROW_GAPS_AFTER][1].set("2")
            controls[ROW_GAP_SIZE][1].set("0,3")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["row_mode_caption"], "Modalità separazione righe")
        self.assertEqual(seen["row_mode_values"], ["Nessuno", "Ogni separazione", "Selezionate"])
        self.assertEqual(seen["rot_values"], ["Predefinita (40°)", "Orizzontale", "Diagonale", "Verticale"])
        self.assertEqual(seen["display_from_canonical"], "Selezionate")
        self.assertEqual(seen["canonical_from_display"], ("Vertical", "Top", "Right"))
        self.assertFalse(seen["it_err"][0])
        self.assertIn("Separazioni righe dopo", seen["it_err"][1])
        self.assertIn("da 1 a", seen["it_err"][1])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][ROW_GAP_MODE], "Selected boundaries")
        self.assertEqual(seen["options"][ROW_GAP_SIZE], 0.3)
        self.assertEqual(seen["options"][COLUMN_LABEL_ROTATION], "Vertical")
        self.assertEqual(seen["options"][COLUMN_LABEL_SIDE], "Top")
        self.assertEqual(seen["options"][ROW_LABEL_SIDE], "Right")


if __name__ == "__main__":
    unittest.main()
