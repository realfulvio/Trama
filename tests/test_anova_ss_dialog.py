"""Multifactor ANOVA dialog: Sums of squares, its notes, the order of the factors for Type I and the recipe."""
import unittest

from analisi.anova_diagnostics import format_anova_error
from analisi.anova_ss import ERRORS, KEY
from analisi.anova_terms import MODEL_TERMS, SELECTED, TERM_SELECTION
from analisi.field_error import FieldError
from tests.test_anova_terms_dialog import FACTORS, DialogCase

A, B, C = FACTORS


def panel(dialog):
    return dialog.anova_order


def kind(dialog, value):
    dialog.controls[KEY][1].set(value)
    dialog.update()


def move(dialog, name, step):
    box = panel(dialog).listbox
    box.selection_clear(0, "end")
    box.selection_set(list(box.get(0, "end")).index(name))
    (panel(dialog).down if step > 0 else panel(dialog).up).invoke()
    dialog.update()


class SumsOfSquaresField(DialogCase):
    def test_the_selector_follows_the_interaction_order_on_the_model_page(self):
        def action(dialog, seen):
            rows = dialog.field_rows
            seen["page"] = rows[KEY][0].master is rows[TERM_SELECTION][0].master
            seen["rows"] = [int(rows[name][0].grid_info()["row"]) for name in (TERM_SELECTION, "Interaction order", KEY)]
            seen["panel_row"] = int(panel(dialog).grid_info()["row"])
            seen["picker_row"] = int(rows[MODEL_TERMS][0].grid_info()["row"])
            seen["value"] = dialog.controls[KEY][1].get()
            seen["choices"] = tuple(dialog.choice_bindings[KEY].combobox.cget("values"))

        seen = self.drive(action)
        self.assertTrue(seen["page"])
        self.assertEqual(seen["rows"], sorted(seen["rows"]))
        self.assertEqual(seen["panel_row"], seen["rows"][2] + 1)
        self.assertGreater(seen["picker_row"], seen["panel_row"])
        self.assertEqual(seen["value"], "Type III")
        self.assertEqual(seen["choices"], ("Type III", "Type I", "Type II"))

    def test_type_three_shows_nothing_extra_and_leaves_the_recipe_unchanged(self):
        def action(dialog, seen):
            dialog.update()
            seen["order"] = bool(panel(dialog).order.winfo_ismapped())
            seen["note"] = panel(dialog).note.cget("text")
            seen["preview"] = panel(dialog).preview.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action)
        self.assertFalse(seen["order"])
        self.assertEqual((seen["note"], seen["preview"]), ("", ""))
        self.assertTrue(seen["ok"])
        self.assertNotIn(KEY, seen["options"])

    def test_a_saved_type_three_keeps_its_key(self):
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 1, KEY: "Type III"}

        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action, current=current, factors=None)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][KEY], "Type III")

    def test_type_one_shows_the_note_the_factor_order_and_the_order_of_the_terms(self):
        def action(dialog, seen):
            dialog.controls["Interaction order"][1].set("2")
            kind(dialog, "Type I")
            current = panel(dialog)
            seen["order"] = bool(current.order.winfo_ismapped())
            seen["factors"] = list(current.listbox.get(0, "end"))
            seen["note"] = current.note.cget("text")
            seen["preview"] = current.preview.cget("text")
            kind(dialog, "Type II")
            seen["two_order"] = bool(current.order.winfo_ismapped())
            seen["two_note"] = current.note.cget("text")
            seen["two_preview"] = current.preview.cget("text")

        seen = self.drive(action)
        self.assertTrue(seen["order"])
        self.assertEqual(seen["factors"], FACTORS)
        self.assertIn("order", seen["note"].casefold())
        self.assertEqual(seen["preview"], f"Terms enter in this order: {A} → {B} → {C} → {A}:{B} → {A}:{C} → {B}:{C}")
        self.assertFalse(seen["two_order"])
        self.assertIn("interactions", seen["two_note"])
        self.assertEqual(seen["two_preview"], "")

    def test_the_type_two_note_waits_for_an_interaction(self):
        def action(dialog, seen):
            kind(dialog, "Type II")
            seen["main_only"] = panel(dialog).note.cget("text")
            dialog.controls["Interaction order"][1].set("2")
            dialog.update()
            seen["with_interactions"] = panel(dialog).note.cget("text")
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.clear()
            for term in ((A,), (B,)):
                picker.vars[term].set(True)
                picker._toggle(term)
            dialog.update()
            seen["selected_mains"] = panel(dialog).note.cget("text")
            picker.vars[(A, B)].set(True)
            picker._toggle((A, B))
            dialog.update()
            seen["selected_pair"] = panel(dialog).note.cget("text")

        seen = self.drive(action)
        self.assertEqual(seen["main_only"], "")
        self.assertNotEqual(seen["with_interactions"], "")
        self.assertEqual(seen["selected_mains"], "")
        self.assertEqual(seen["selected_pair"], seen["with_interactions"])

    def test_the_preview_follows_the_selected_terms(self):
        def action(dialog, seen):
            kind(dialog, "Type I")
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.clear()
            for term in ((C,), (A,), (A, C)):
                picker.vars[term].set(True)
                picker._toggle(term)
            dialog.update()
            seen["selected"] = panel(dialog).preview.cget("text")
            picker.boxes[(A, C)].invoke()
            dialog.update()
            seen["removed"] = panel(dialog).preview.cget("text")

        seen = self.drive(action)
        self.assertEqual(seen["selected"], f"Terms enter in this order: {A} → {C} → {A}:{C}")
        self.assertEqual(seen["removed"], f"Terms enter in this order: {A} → {C}")


class FactorOrder(DialogCase):
    def test_up_and_down_reorder_the_factors_the_preview_and_the_recipe(self):
        def action(dialog, seen):
            dialog.controls["Interaction order"][1].set("2")
            kind(dialog, "Type I")
            move(dialog, B, -1)
            seen["list"] = list(panel(dialog).listbox.get(0, "end"))
            seen["selection"] = panel(dialog).listbox.curselection()
            seen["preview"] = panel(dialog).preview.cget("text")
            seen["factors"] = dialog.anova_factors()
            picker = self.picker(dialog)
            seen["pairs"] = [term for term in picker.available() if len(term) == 2]
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])
            dialog.result = None
            move(dialog, B, 1)
            seen["back"] = list(panel(dialog).listbox.get(0, "end"))
            move(dialog, A, 1)
            move(dialog, A, 1)
            seen["last"] = list(panel(dialog).listbox.get(0, "end"))

        seen = self.drive(action)
        self.assertEqual(seen["list"], [B, A, C])
        self.assertEqual(seen["selection"], (0,))
        self.assertTrue(seen["preview"].endswith(f"{B} → {A} → {C} → {B}:{A} → {B}:{C} → {A}:{C}"), seen["preview"])
        self.assertEqual(seen["factors"], [B, A, C])
        self.assertEqual(seen["pairs"], [(B, A), (B, C), (A, C)])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"]["Factors"], [B, A, C])
        self.assertEqual(seen["options"][KEY], "Type I")
        self.assertEqual(seen["back"], FACTORS)
        self.assertEqual(seen["last"], [B, C, A])  # moving past the end changes nothing

    def test_the_ticked_selected_terms_survive_a_reorder(self):
        def action(dialog, seen):
            kind(dialog, "Type I")
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker = self.picker(dialog)
            picker.clear()
            for term in ((A,), (B,), (A, B)):
                picker.vars[term].set(True)
                picker._toggle(term)
            dialog.update()
            move(dialog, B, -1)
            seen["values"] = picker.values()
            seen["preview"] = panel(dialog).preview.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action)
        self.assertEqual(seen["values"], [[B], [A], [B, A]])
        self.assertTrue(seen["preview"].endswith(f"{B} → {A} → {B}:{A}"), seen["preview"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][MODEL_TERMS], [[B], [A], [B, A]])
        self.assertEqual(seen["options"]["Factors"], [B, A, C])

    def test_a_saved_order_comes_back_and_a_deselected_factor_keeps_its_place(self):
        current = {"Response": "Response", "Factors": [C, A, B], "Interaction order": 1, KEY: "Type I"}

        def action(dialog, seen):
            seen["start"] = list(panel(dialog).listbox.get(0, "end"))
            seen["factors"] = dialog.anova_factors()
            self.choose_factors(dialog, [A, B])
            seen["without_c"] = list(panel(dialog).listbox.get(0, "end"))
            self.choose_factors(dialog, [A, B, C])
            seen["with_c"] = list(panel(dialog).listbox.get(0, "end"))
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action, current=current, factors=None)
        self.assertEqual(seen["start"], [C, A, B])
        self.assertEqual(seen["factors"], [C, A, B])
        self.assertEqual(seen["without_c"], [A, B])
        self.assertEqual(seen["with_c"], [C, A, B])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"]["Factors"], [C, A, B])

    def test_a_newly_ticked_factor_goes_last(self):
        def action(dialog, seen):
            kind(dialog, "Type I")
            self.choose_factors(dialog, [B, C])
            move(dialog, C, -1)
            self.choose_factors(dialog, [A, B, C])
            seen["list"] = list(panel(dialog).listbox.get(0, "end"))
            seen["factors"] = dialog.anova_factors()

        seen = self.drive(action, factors=[B, C])
        self.assertEqual(seen["list"], [C, B, A])
        self.assertEqual(seen["factors"], [C, B, A])

    def test_a_saved_order_is_kept_for_type_three_too(self):
        current = {"Response": "Response", "Factors": [B, A], "Interaction order": 2}

        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action, current=current, factors=None)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"]["Factors"], [B, A])
        self.assertNotIn(KEY, seen["options"])

    def test_one_factor_leaves_the_buttons_unused(self):
        def action(dialog, seen):
            kind(dialog, "Type I")
            current = panel(dialog)
            seen["up"] = "disabled" in current.up.state()
            seen["preview"] = current.preview.cget("text")

        seen = self.drive(action, factors=[A])
        self.assertTrue(seen["up"])
        self.assertEqual(seen["preview"], f"Terms enter in this order: {A}")


class Italian(DialogCase):
    def test_captions_translate_and_the_recipe_stays_canonical(self):
        def action(dialog, seen):
            dialog.controls["Interaction order"][1].set("2")
            kind(dialog, "Type I")
            current = panel(dialog)
            seen["caption"] = dialog.field_rows[KEY][0].cget("text")
            seen["shown"] = dialog.choice_bindings[KEY].combobox.get()
            seen["value"] = dialog.controls[KEY][1].get()
            seen["order"] = current.caption.cget("text")
            seen["buttons"] = (current.up.cget("text"), current.down.cget("text"))
            seen["note"] = current.note.cget("text")
            seen["preview"] = current.preview.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])
            dialog.result = None
            kind(dialog, "Type II")
            seen["shown_two"] = dialog.choice_bindings[KEY].combobox.get()
            seen["note_two"] = current.note.cget("text")

        self.use("it")
        seen = self.drive(action)
        self.assertEqual(seen["caption"], "Somme dei quadrati")
        self.assertEqual((seen["shown"], seen["value"]), ("Tipo I", "Type I"))
        self.assertEqual(seen["order"], "Ordine dei fattori")
        self.assertEqual(seen["buttons"], ("Su", "Giù"))
        self.assertTrue(seen["note"].startswith("Il tipo I"))
        self.assertTrue(seen["preview"].startswith("I termini entrano in quest’ordine: "))
        self.assertEqual(seen["options"][KEY], "Type I")
        self.assertEqual(seen["shown_two"], "Tipo II")
        self.assertTrue(seen["note_two"].startswith("Il tipo II"))


class FieldErrors(DialogCase):
    def test_the_error_is_worded_in_the_active_language_with_its_caption(self):
        error = FieldError(KEY, ERRORS["numeric"])
        self.assertTrue(format_anova_error(error).startswith("Sums of squares: The sums of squares could not"))
        self.use("it")
        self.assertTrue(format_anova_error(error).startswith("Somme dei quadrati: Le somme dei quadrati non"))

    def test_the_dialog_focuses_the_field_of_an_error(self):
        def action(dialog, seen):
            dialog.fields.select(0)
            dialog.update()
            dialog.focus_field(KEY)
            dialog.update()
            seen["tab"] = dialog.fields.tab(dialog.fields.select(), "text")
            seen["focus"] = dialog.focus_get() is dialog.field_rows[KEY][1]

        seen = self.drive(action)
        self.assertEqual(seen["tab"], "Model")
        self.assertTrue(seen["focus"])


if __name__ == "__main__":
    unittest.main()
