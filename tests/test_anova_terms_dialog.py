"""Multifactor ANOVA dialog: Term selection, the Model tab, the checkboxes and the recipe they produce."""
import traceback
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.anova_terms import FULL, MODEL_TERMS, SELECTED, TERM_SELECTION
from tests.test_graph_i18n import LanguageMixin, TkCase, descendants

METHOD = "Multifactor ANOVA"
FACTORS = ["A dose", "B group", "C lot"]
_RNG = np.random.default_rng(7)
FRAME = pd.DataFrame(
    [(10 + _RNG.normal(), a, b, c) for a in ("A0", "A1") for b in ("B0", "B1") for c in ("C0", "C1", "C2")
     for _ in range(3)],
    columns=["Response", *FACTORS])


class DialogCase(TkCase):
    def setUp(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog

    def drive(self, action, *, current=None, factors=FACTORS, geometry="1024x768+0+0"):
        seen, holder = {}, []

        def step():
            try:
                dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.AnalysisDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                holder.append(dialog)
                dialog.update_idletasks()
                if factors is not None:
                    self.choose_factors(dialog, factors)
                action(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for dialog in holder:
                    dialog.result = None
                    dialog.cancel()

        self.root.deiconify()
        self.root.geometry(geometry)
        self.root.after(80, step)
        self.AnalysisDialog(self.root, FRAME, current=(METHOD, current) if current is not None else None,
                            only=METHOD)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def choose_factors(dialog, names):
        box = dialog.controls["Factors"][1]
        columns = list(box.get(0, "end"))
        box.selection_clear(0, "end")
        for name in names:
            box.selection_set(columns.index(name))
        box.event_generate("<<ListboxSelect>>")
        dialog.controls["Response"][1].set("Response")
        dialog.update()

    @staticmethod
    def picker(dialog):
        return dialog.controls[MODEL_TERMS][1]

    @staticmethod
    def rejected(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        message = report.call_args.args[1] if report.call_args else ""
        return ok, message


class ModelTabTests(DialogCase):
    def test_model_tab_follows_variables_and_holds_the_term_fields(self):
        def action(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["mode"] = dialog.controls[TERM_SELECTION][1].get()
            seen["groups_shown"] = [bool(frame.winfo_manager()) for frame in self.picker(dialog).groups.values()]
            seen["order_placed"] = bool(dialog.field_rows["Interaction order"][1].winfo_manager())

        seen = self.drive(action)
        self.assertEqual(seen["tabs"][:3], ["Variables", "Model", "Options"])
        self.assertEqual(seen["mode"], FULL)
        self.assertEqual(seen["groups_shown"], [False, False, False])
        self.assertTrue(seen["order_placed"])

    def test_selected_terms_shows_the_groups_and_hides_the_interaction_order(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            seen["groups"] = {size: bool(frame.winfo_manager()) for size, frame in picker.groups.items()}
            seen["order_placed"] = bool(dialog.field_rows["Interaction order"][1].winfo_manager())
            seen["boxes"] = sorted(("+".join(term) for term in picker.boxes))
            seen["ticked"] = picker.values()

        seen = self.drive(action)
        self.assertEqual(seen["groups"], {1: True, 2: True, 3: True})
        self.assertFalse(seen["order_placed"])
        self.assertEqual(len(seen["boxes"]), 7)
        self.assertEqual(seen["ticked"], [["A dose"], ["B group"], ["C lot"]])

    def test_untouched_picker_follows_the_full_hierarchy_until_the_first_edit(self):
        def action(dialog, seen):
            picker = self.picker(dialog)
            dialog.controls["Interaction order"][1].set("2")
            dialog.update()
            seen["order2"] = len(picker.values())
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            seen["selected_start"] = [list(t) for t in picker.terms()]
            picker.vars[("A dose", "B group")].set(False)
            picker._toggle(("A dose", "B group"))
            dialog.controls["Interaction order"][1].set("3")
            dialog.update()
            seen["after_edit"] = len(picker.values())

        seen = self.drive(action)
        self.assertEqual(seen["order2"], 6)          # 3 mains + 3 two-way interactions
        self.assertEqual(len(seen["selected_start"]), 6)  # Selected terms starts from what Full would fit
        self.assertEqual(seen["after_edit"], 5)      # frozen: order 3 adds nothing silently

    def test_switching_modes_keeps_the_edited_terms_and_cancel_changes_nothing(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.boxes[("B group",)].invoke()
            seen["edited"] = picker.values()
            dialog.controls[TERM_SELECTION][1].set(FULL)
            dialog.update()
            seen["full_recipe_ok"] = dialog.validate()
            seen["full_options"] = dict(dialog.result[1])
            dialog.result = None
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            seen["back"] = picker.values()

        seen = self.drive(action)
        self.assertEqual(seen["edited"], [["A dose"], ["C lot"]])
        self.assertTrue(seen["full_recipe_ok"])
        self.assertNotIn(MODEL_TERMS, seen["full_options"])
        self.assertEqual(seen["back"], [["A dose"], ["C lot"]])

    def test_recipe_uses_the_literal_factor_names_in_model_order(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.clear()
            for term in (("C lot",), ("A dose",), ("A dose", "C lot")):
                picker.vars[term].set(True)
                picker._toggle(term)
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1] if dialog.result else None

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][TERM_SELECTION], SELECTED)
        self.assertEqual(seen["options"][MODEL_TERMS], [["A dose"], ["C lot"], ["A dose", "C lot"]])
        self.assertNotIn("Interaction order", seen["options"])  # hidden in Selected terms, so not saved

    def test_full_hierarchy_recipe_stays_free_of_the_new_keys(self):
        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertNotIn(TERM_SELECTION, seen["options"])
        self.assertNotIn(MODEL_TERMS, seen["options"])

    def test_saved_full_recipe_keeps_its_term_selection_key(self):
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 2, TERM_SELECTION: FULL}

        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action, current=current, factors=None)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][TERM_SELECTION], FULL)
        self.assertNotIn(MODEL_TERMS, seen["options"])

    def test_saved_terms_come_back_ticked_and_survive_a_deselected_factor(self):
        saved = [["A dose"], ["B group"], ["A dose", "B group"]]
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 1,
                   TERM_SELECTION: SELECTED, MODEL_TERMS: saved}

        def action(dialog, seen):
            picker = self.picker(dialog)
            seen["start"] = picker.values()
            self.choose_factors(dialog, ["A dose", "C lot"])
            seen["without_b"] = picker.values()
            self.choose_factors(dialog, FACTORS)
            seen["back"] = picker.values()

        seen = self.drive(action, current=current, factors=None)
        self.assertEqual(seen["start"], saved)
        self.assertEqual(seen["without_b"], [["A dose"]])
        self.assertEqual(seen["back"], saved)

    def test_missing_prerequisite_is_named_and_refused_then_added_on_request(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            for term in (("A dose",), ("A dose", "C lot")):
                picker.vars[term].set(term == ("A dose", "C lot"))
                picker._toggle(term)
            seen["problem"] = picker.problem.cget("text")
            seen["add_enabled"] = "disabled" not in picker.add_button.state()
            ok, message = self.rejected(dialog)
            seen["ok"], seen["message"] = ok, message
            seen["tab"] = dialog.fields.tab(dialog.fields.select(), "text")
            picker.add_required()
            dialog.update()
            seen["fixed"] = picker.values()
            seen["problem_after"] = picker.problem.cget("text")
            seen["ok_after"] = dialog.validate()

        seen = self.drive(action)
        self.assertIn("A dose:C lot", seen["problem"])
        self.assertIn("A dose", seen["problem"])
        self.assertTrue(seen["add_enabled"])
        self.assertFalse(seen["ok"])
        self.assertIn("strong hierarchy", seen["message"])
        self.assertEqual(seen["tab"], "Model")
        self.assertIn(["A dose"], seen["fixed"])
        self.assertIn(["A dose", "C lot"], seen["fixed"])
        self.assertEqual(seen["problem_after"], "")
        self.assertTrue(seen["ok_after"])

    def test_empty_selection_is_refused_with_the_model_terms_field(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            self.picker(dialog).clear()
            ok, message = self.rejected(dialog)
            seen["ok"], seen["message"] = ok, message
            seen["tab"] = dialog.fields.tab(dialog.fields.select(), "text")

        seen = self.drive(action)
        self.assertFalse(seen["ok"])
        self.assertTrue(seen["message"])
        self.assertEqual(seen["tab"], "Model")

    def test_idle_factors_are_named_and_the_summary_is_readable(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.clear()
            for term in (("A dose",), ("B group",), ("A dose", "B group")):
                picker.vars[term].set(True)
                picker._toggle(term)
            seen["summary"] = picker.summary.cget("text")
            seen["outside"] = picker.outside.cget("text")

        seen = self.drive(action)
        self.assertIn("Response = A dose + B group + A dose:B group", seen["summary"])
        self.assertIn("C lot", seen["outside"])

    def test_buttons_stay_reachable_at_1024x768_and_wheel_binding_is_not_duplicated(self):
        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            for _ in range(3):
                picker.refresh()
            dialog.update()
            seen["height"] = dialog.winfo_height()
            bottoms = []
            for caption in ("Run Analysis", "Cancel"):
                button = next(w for w in descendants(dialog)
                              if w.winfo_class() == "TButton" and w.cget("text") == caption)
                bottoms.append(button.winfo_ismapped() and button.winfo_rooty() + button.winfo_height()
                               <= dialog.winfo_rooty() + dialog.winfo_height())
            seen["buttons"] = bottoms
            group = picker.groups[1]
            seen["group_bindings"] = group.bind("<Button-4>").count("\n")
            box = next(iter(picker.boxes.values()))
            seen["box_bindings"] = box.bind("<Button-4>").count("\n")

        seen = self.drive(action)
        self.assertLessEqual(seen["height"], 768)
        self.assertEqual(seen["buttons"], [True, True])
        self.assertEqual((seen["group_bindings"], seen["box_bindings"]), (1, 1))  # one wheel handler each


class ModelTabItalianTests(DialogCase):
    def test_italian_captions_with_canonical_values_in_the_recipe(self):
        self.use("it")

        def action(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            combo = dialog.controls[TERM_SELECTION][1]
            combo.set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            seen["shown"] = [widget.cget("text") for widget in descendants(dialog)
                             if widget.winfo_class() in ("TLabel", "TButton", "TLabelframe")]
            seen["summary"] = picker.summary.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action)
        self.assertEqual(seen["tabs"][1], "Modello")
        for caption in ("Selezione dei termini", "Termini del modello", "Effetti principali",
                        "Interazioni a due fattori", "Interazioni a tre fattori", "Seleziona tutto",
                        "Deseleziona", "Aggiungi i termini richiesti"):
            self.assertIn(caption, seen["shown"])
        self.assertIn("Modello:", seen["summary"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][TERM_SELECTION], SELECTED)
        self.assertEqual(seen["options"][MODEL_TERMS], [["A dose"], ["B group"], ["C lot"]])

    def test_italian_hierarchy_message_names_the_terms_without_translating_them(self):
        self.use("it")

        def action(dialog, seen):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.vars[("A dose",)].set(False)
            picker._toggle(("A dose",))
            picker.vars[("A dose", "C lot")].set(True)
            picker._toggle(("A dose", "C lot"))
            seen["problem"] = picker.problem.cget("text")
            ok, message = self.rejected(dialog)
            seen["ok"], seen["message"] = ok, message

        seen = self.drive(action)
        self.assertIn("A dose:C lot richiede A dose", seen["problem"])
        self.assertFalse(seen["ok"])
        self.assertIn("gerarchia forte", seen["message"])
        self.assertIn("A dose:C lot", seen["message"])


class LanguageOnlyTests(LanguageMixin, unittest.TestCase):
    def test_module_imports_without_a_display(self):
        from analisi import anova_terms_dialog
        self.assertEqual(anova_terms_dialog.ANOVA_MODEL_TAB, "Model")
        self.assertEqual(anova_terms_dialog._clean([["a", "b"], ["a"], "x", [], [1]]),
                         {frozenset(("a", "b")), frozenset(("a",))})
        self.assertEqual(anova_terms_dialog._clean(None), set())


if __name__ == "__main__":
    unittest.main()
