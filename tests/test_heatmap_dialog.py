"""0.72 heat-map dialogs on real Tk widgets: tabs, dynamic fields, errors on their field, category editor, Inspector."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import traceback
import unittest
from unittest.mock import patch

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from analisi import i18n
from analisi.graph_inspector import GraphInspector
from analisi.heatmap import (CATEGORY_COLORS, COLOR_MAPPING, HEAT_MAP, LEGEND_INTERVAL, LEGEND_START, MAX_COLOR,
                             MID_COLOR, MIN_COLOR, OPACITY, REVERSE_LEGEND, SHOW_LEGEND)
from analisi.heatmap_dialog import CategoryColorsDialog, CategoryColorsField
from analisi.workbench import analyse
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).parent / "data" / "heatmap_072"
CUSTOM = {"low": "#112233", "high": "#cc8844", "LOW": "#aa1177", "1": "#88bb22", "01": "#2255bb"}


class DialogCase(TkCase):
    def setUp(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog
        self.numeric = pd.read_csv(DATA / "numeric.csv")
        self.categories = pd.read_csv(DATA / "categories.csv", dtype=str)

    def drive(self, frame, current, action, *, initial_field=None):
        """Open the real dialog on ``frame`` with ``current`` options, run ``action(dialog)``, then close it."""
        seen, holder = {}, []

        def step():
            try:
                dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.AnalysisDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                holder.append(dialog)
                dialog.update_idletasks()
                action(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for dialog in holder:
                    dialog.result = None
                    dialog.cancel()

        self.root.deiconify()
        self.root.geometry("1024x768+0+0")
        self.root.after(80, step)
        self.AnalysisDialog(self.root, frame, current=(HEAT_MAP, current), only=HEAT_MAP, initial_field=initial_field)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    @staticmethod
    def rejected(dialog, field):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        return ok, report.call_args.args[1] if report.call_args else "", dialog.fields.select()


NUMERIC = {"Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row",
           "Color minimum (blank = automatic)": "0", "Color maximum (blank = automatic)": "4"}
CATEGORIES = {"Input format": "Long categories", "X categories": "X", "Y categories": "Y", "Values": "Class"}


class HeatMapDialogTests(DialogCase):
    def test_initial_color_field_takes_focus_from_the_parent_inspector(self):
        parent_control = ttk.Combobox(self.root, values=("Graph",))
        parent_control.pack()
        self.addCleanup(parent_control.destroy)
        self.root.deiconify()
        self.root.update()
        parent_control.focus_force()
        self.root.update()
        def action(dialog, seen):
            seen["focus"] = dialog.focus_get() is dialog.field_rows[COLOR_MAPPING][1]
            seen["tab"] = dialog.fields.select() == str(dialog.field_rows[COLOR_MAPPING][1].master)
        seen = self.drive(self.numeric, NUMERIC, action, initial_field=COLOR_MAPPING)
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["tab"])

    def test_tabs_and_fields_follow_the_mapping(self):
        def action(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["start"] = (self.placed(dialog, "Palette"), self.placed(dialog, MIN_COLOR), self.placed(dialog, LEGEND_START))
            dialog.controls[COLOR_MAPPING][1].set("Single gradient")
            dialog.update()
            seen["single"] = (self.placed(dialog, "Palette"), self.placed(dialog, MIN_COLOR),
                              self.placed(dialog, MID_COLOR), self.placed(dialog, MAX_COLOR))
            dialog.controls[COLOR_MAPPING][1].set("Double gradient")
            dialog.update()
            seen["double"] = (self.placed(dialog, MID_COLOR), self.placed(dialog, "Color midpoint (blank = automatic)"))
            seen["defaults"] = [dialog.controls[name][1].get() for name in (MIN_COLOR, MID_COLOR, MAX_COLOR)]
            dialog.controls[LEGEND_INTERVAL][1].set("0.5")
            dialog.update()
            seen["start_shown"] = self.placed(dialog, LEGEND_START)
            dialog.controls[SHOW_LEGEND][1].set(False)
            dialog.update()
            seen["hidden"] = [self.placed(dialog, n) for n in ("Color legend orientation", "Color legend title",
                                                              REVERSE_LEGEND, LEGEND_INTERVAL, LEGEND_START)]
            dialog.controls[SHOW_LEGEND][1].set(True)
            dialog.controls[COLOR_MAPPING][1].set("Single gradient")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1]) if dialog.result else None

        seen = self.drive(self.numeric, NUMERIC, action)
        # Layout sits next to Graph options while preserving the existing tabs and their relative order.
        self.assertEqual(seen["tabs"], ["Variables", "Graph options", "Layout", "Colors", "Categories", "Legend"])
        self.assertEqual(seen["start"], (True, False, False))
        self.assertEqual(seen["single"], (False, True, False, True))
        self.assertEqual(seen["double"], (True, True))
        self.assertEqual(seen["defaults"], ["#2166ac", "#f7f7f7", "#b2182b"])
        self.assertTrue(seen["start_shown"])
        self.assertEqual(seen["hidden"], [False] * 5)
        options = seen["options"]
        self.assertTrue(seen["ok"])
        self.assertEqual(options[COLOR_MAPPING], "Single gradient")
        self.assertNotIn("Palette", options)
        self.assertNotIn(MID_COLOR, options)
        self.assertEqual(options[OPACITY], 1.0)

    def test_each_error_names_its_field_and_tab_and_keeps_the_dialog(self):
        def action(dialog, seen):
            controls = dialog.controls
            controls[COLOR_MAPPING][1].set("Double gradient")
            for name, value, field, tab in ((MIN_COLOR, "nope", MIN_COLOR, "Colors"),
                                            (OPACITY, "7", OPACITY, "Colors"),
                                            (LEGEND_INTERVAL, "0", LEGEND_INTERVAL, "Legend")):
                controls[name][1].set(value)
                ok, message, selected = self.rejected(dialog, field)
                seen[name] = (ok, field in message or i18n.ui(field) in message,
                              dialog.fields.tab(selected, "text"), dialog.winfo_exists())
                controls[name][1].set({MIN_COLOR: "#112233", OPACITY: "1", LEGEND_INTERVAL: ""}[name])
            controls[LEGEND_INTERVAL][1].set("1")
            controls[LEGEND_START][1].set("9")
            ok, message, selected = self.rejected(dialog, LEGEND_START)
            seen["start"] = (ok, dialog.fields.tab(selected, "text"))
            controls[LEGEND_START][1].set("0,5")
            seen["fixed"] = dialog.validate()

        seen = self.drive(self.numeric, NUMERIC, action)
        for name, tab in ((MIN_COLOR, "Colors"), (OPACITY, "Colors"), (LEGEND_INTERVAL, "Legend")):
            self.assertEqual(seen[name], (False, True, tab, True), name)
        self.assertEqual(seen["start"], (False, "Legend"))
        self.assertTrue(seen["fixed"])

    def test_inactive_fields_never_block_a_valid_drawing(self):
        def action(dialog, seen):
            controls = dialog.controls
            controls[COLOR_MAPPING][1].set("Palette")
            controls[MIN_COLOR][1].set("nope")
            controls[MAX_COLOR][1].set("nope")
            controls[LEGEND_START][1].set("nonsense")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1]) if dialog.result else {}

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertTrue(seen["ok"])
        self.assertNotIn(MIN_COLOR, seen["options"])
        self.assertNotIn(LEGEND_START, seen["options"])

    def test_italian_shows_translated_text_and_saves_canonical_values(self):
        self.use("it")

        def action(dialog, seen):
            # Layout occupies tab index 2; Colors, Categories, Legend follow at 3..5.
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(3, 6)]
            seen["caption"] = dialog.field_rows[OPACITY][0].cget("text")
            combo = dialog.field_rows[COLOR_MAPPING][1]
            seen["values"] = list(combo.cget("values"))
            combo.set("Gradiente doppio")
            combo.event_generate("<<ComboboxSelected>>")
            dialog.update()
            seen["canonical"] = dialog.controls[COLOR_MAPPING][1].get()
            dialog.controls[OPACITY][1].set("3")
            ok, message, _ = self.rejected(dialog, OPACITY)
            seen["message"] = (ok, message)
            dialog.controls[OPACITY][1].set("0,5")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.numeric, NUMERIC, action)
        self.assertEqual(seen["tabs"], ["Colori", "Categorie", "Legenda"])
        self.assertEqual(seen["caption"], "Opacità dei colori")
        self.assertEqual(seen["values"], ["Tavolozza", "Gradiente singolo", "Gradiente doppio"])
        self.assertEqual(seen["canonical"], "Double gradient")
        self.assertFalse(seen["message"][0])
        self.assertIn("Opacità dei colori", seen["message"][1])
        self.assertIn("compreso tra 0 e 1", seen["message"][1])
        self.assertEqual(seen["options"][COLOR_MAPPING], "Double gradient")
        self.assertEqual(seen["options"][OPACITY], 0.5)

    def test_category_field_lists_levels_and_keeps_pairs_of_absent_levels(self):
        def action(dialog, seen):
            field = dialog.field_rows[CATEGORY_COLORS][1]
            seen["summary"] = field.summary.cget("text")
            seen["placed"] = (self.placed(dialog, CATEGORY_COLORS), self.placed(dialog, COLOR_MAPPING))
            dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(self.categories, {**CATEGORIES, CATEGORY_COLORS: {"low": "#112233", "gone": "#abcdef"}},
                          action)
        self.assertEqual(seen["summary"], "1 of 5 categories have a chosen color.")
        self.assertEqual(seen["placed"], (True, False))
        self.assertEqual(seen["options"][CATEGORY_COLORS], {"low": "#112233", "gone": "#abcdef"})
        self.assertNotIn(COLOR_MAPPING, seen["options"])
        self.assertNotIn("Color legend orientation", seen["options"])


class CategoryEditorTests(DialogCase):
    def test_twenty_categories_keep_buttons_visible_and_reveal_invalid_row(self):
        seen = {}

        def step():
            editor = next(w for w in self.root.winfo_children() if isinstance(w, CategoryColorsDialog))
            try:
                editor.update_idletasks()
                buttons = [w for frame in editor.winfo_children() for w in frame.winfo_children()
                           if isinstance(w, ttk.Button)]
                self.assertTrue(buttons)
                for button in buttons:
                    self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                         editor.winfo_rooty() + editor.winfo_height())
                # Simulate the small-screen viewport even when the test display is larger.
                editor.canvas.configure(height=200)
                editor.update_idletasks()
                editor.rows[-1][1].set("not a color")
                self.assertFalse(editor.validate())
                editor.update_idletasks()
                entry = editor.rows[-1][2]
                self.assertGreaterEqual(entry.winfo_rooty(), editor.canvas.winfo_rooty())
                self.assertLessEqual(entry.winfo_rooty() + entry.winfo_height(),
                                     editor.canvas.winfo_rooty() + editor.canvas.winfo_height())
                self.assertGreater(editor.canvas.yview()[0], 0)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                editor.cancel()

        self.root.deiconify()
        self.root.after(100, step)
        CategoryColorsDialog(self.root, [f"Level {i}" for i in range(20)], {})
        self.assertNotIn("error", seen, seen.get("error"))

    def open_editor(self, mapping, action):
        seen, holder = {}, []

        def step():
            try:
                editor = next(w for w in self.root.winfo_children() if isinstance(w, CategoryColorsDialog))
                holder.append(editor)
                editor.update_idletasks()
                action(editor, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for editor in holder:
                    editor.cancel() if seen.get("cancel") else editor.ok()

        self.root.deiconify()
        self.root.after(80, step)
        dialog = CategoryColorsDialog(self.root, ["low", "high", "LOW", "1", "01"], mapping)
        self.assertNotIn("error", seen, seen.get("error"))
        return dialog.result, seen

    def test_apply_keeps_unobserved_pairs_and_blank_clears(self):
        def action(editor, seen):
            self.assertEqual([row[0] for row in editor.rows], ["low", "high", "LOW", "1", "01"])
            editor.rows[0][1].set("")                    # clear "low"
            editor.rows[2][1].set("#aa1177")
            editor.rows[3][1].set(" red ")

        result, _ = self.open_editor({"low": "#112233", "gone": "#abcdef"}, action)
        self.assertEqual(result, {"gone": "#abcdef", "LOW": "#aa1177", "1": "red"})

    def test_cancel_returns_nothing(self):
        def action(editor, seen):
            editor.rows[0][1].set("#ff0000")
            seen["cancel"] = True

        result, _ = self.open_editor({}, action)
        self.assertIsNone(result)

    def test_invalid_color_stays_open_on_its_row(self):
        def action(editor, seen):
            editor.rows[1][1].set("not a color")
            seen["blocked"] = editor.validate()
            seen["message"] = editor.message.cget("text")
            seen["open"] = bool(editor.winfo_exists())
            editor.rows[1][1].set("#cc8844")
            seen["fixed"] = editor.validate()

        result, seen = self.open_editor({}, action)
        self.assertFalse(seen["blocked"])
        self.assertTrue(seen["open"] and seen["fixed"])
        self.assertIn("high", seen["message"])
        self.assertEqual(result, {"high": "#cc8844"})

    def test_field_summary_and_levels_error(self):
        from analisi.processing import FieldError

        def broken():
            raise FieldError("Values", "Choose a column for Values.")

        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        field = CategoryColorsField(holder, CUSTOM, broken)
        self.assertEqual(field.summary.cget("text"), "Choose the X, Y and value columns to list the categories.")
        self.assertEqual(field.values(), CUSTOM)
        self.assertIsNot(field.values(), field.mapping)
        ok = CategoryColorsField(holder, {"low": "#112233"}, lambda: ["low", "high"])
        self.assertEqual(ok.summary.cget("text"), "1 of 2 categories have a chosen color.")


class HeatMapInspectorTests(TkCase):
    def make(self, colors):
        frame = pd.read_csv(DATA / "numeric.csv")
        result = analyse(HEAT_MAP, frame, {**NUMERIC})
        run = SimpleNamespace(style=None, result=SimpleNamespace(style_warning=None), method=HEAT_MAP)
        holder = ttk.Frame(self.root)
        self.addCleanup(holder.destroy)
        canvas = FigureCanvasTkAgg(result.figure, master=holder)
        panel = GraphInspector(holder, run, canvas, None, confirmed=lambda: run.style,
                               commit=lambda style: setattr(run, "style", style), closed=lambda: None,
                               colors=colors)
        self.addCleanup(panel.dispose)
        return panel

    def test_heat_map_offers_its_editor_and_no_line_or_symbol_controls(self):
        calls = []
        panel = self.make(lambda: calls.append("open"))
        self.assertEqual(panel.elements, [])
        self.assertIn("colors", panel.widgets)
        for field in panel.fields.values():
            self.assertFalse(any(widget.winfo_manager() for widget in field["shown"]))
        panel.widgets["colors"].invoke()
        self.assertEqual(calls, ["open"])

    def test_other_graphs_keep_their_panel(self):
        panel = self.make(None)
        self.assertNotIn("colors", panel.widgets)


if __name__ == "__main__":
    unittest.main()
