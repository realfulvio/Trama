"""Normalize to references dialog: tabs, hidden fields, Italian captions, canonical recipes."""
import traceback
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi.field_error import FieldError
from analisi.i18n import placeholders
from analisi.reference_normalization import METHOD
from analisi.reference_normalization_dialog import translate_error
from tests.test_graph_i18n import LanguageMixin, TkCase, descendants

FRAME = pd.DataFrame({"y": [1.0, 2.0, 4.0], "x": [10.0, 20.0, 30.0]})


class ReferenceMessageTests(LanguageMixin, unittest.TestCase):
    def test_catalog_placeholders_match(self):
        keys = [key for key in i18n.CATALOGS["en"] if key.startswith("reference.")]
        self.assertGreater(len(keys), 20)
        for key in keys:
            english, italian = i18n.CATALOGS["en"][key], i18n.CATALOGS["it"][key]
            self.assertEqual(placeholders(english), placeholders(italian), key)
            self.assertNotEqual(english, italian, key)

    def test_column_names_stay_literal(self):
        self.use("it")
        name = "Misure {A} – città"
        missing = translate_error(FieldError("X", f'Column "{name}" is not in the table.'))
        self.assertIn(name, missing)
        self.assertNotIn("Column ", missing)
        used = translate_error(FieldError("Mean", '"y" is already used as X.'))
        self.assertIn('"y"', used)
        self.assertIn(" come X.", used)
        self.assertEqual(translate_error("Something new."), "Something new.")

    def test_english_messages_stay_english(self):
        self.use("en")
        self.assertEqual(translate_error("The zero and one references are equal."),
                         "The zero and one references are equal.")


class DialogCase(TkCase):
    def setUp(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog

    def drive(self, action, *, current=None, initial_field=None):
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
        self.AnalysisDialog(self.root, FRAME, current=(METHOD, current or {}), only=METHOD,
                            initial_field=initial_field)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    @staticmethod
    def rejected(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        message = report.call_args.args[1] if report.call_args else ""
        return ok, message, dialog.fields.select()


class ReferenceDialogTests(DialogCase):
    def test_equal_references_keep_the_dialog_on_one_reference(self):
        def action(dialog, seen):
            dialog.controls["Zero reference"][1].set("Constant")
            dialog.controls["One reference"][1].set("Constant")
            dialog.update()
            dialog.controls["Zero value"][1].set("2")
            dialog.controls["One value"][1].set("2")
            ok, message, selected = self.rejected(dialog)
            seen["ok"] = ok
            seen["message"] = message
            seen["tab"] = dialog.fields.tab(selected, "text")
            seen["exists"] = dialog.winfo_exists()
            seen["focus"] = dialog.focus_get() is dialog.field_rows["One reference"][1]

        seen = self.drive(action)
        self.assertFalse(seen["ok"])
        self.assertIn("equal", seen["message"])
        self.assertIn("One reference", seen["message"])
        self.assertEqual(seen["tab"], "References")
        self.assertTrue(seen["exists"])
        self.assertTrue(seen["focus"])

    def test_hidden_error_field_selects_the_output_tab(self):
        def action(dialog, seen):
            seen["tab"] = dialog.fields.tab(dialog.fields.select(), "text")
            seen["placed"] = self.placed(dialog, "Error lower")
            seen["input"] = dialog.controls["Input"][1].get()

        seen = self.drive(action, current={"Input": "Raw values"}, initial_field="Error lower")
        self.assertEqual(seen["input"], "Raw values")
        self.assertEqual(seen["tab"], "Output")
        self.assertFalse(seen["placed"])

    def test_buttons_fit_on_a_1024x768_screen(self):
        def action(dialog, seen):
            dialog.update()
            seen["height"] = dialog.winfo_height()
            bottoms = []
            for caption in ("Run Analysis", "Cancel"):
                button = next(w for w in descendants(dialog)
                              if w.winfo_class() == "TButton" and w.cget("text") == caption)
                bottoms.append(button.winfo_ismapped()
                               and button.winfo_rooty() + button.winfo_height()
                               <= dialog.winfo_rooty() + dialog.winfo_height())
            seen["buttons"] = bottoms

        seen = self.drive(action)
        self.assertLessEqual(seen["height"], 768)
        self.assertEqual(seen["buttons"], [True, True])

    def test_constant_text_survives_the_input_switch(self):
        def action(dialog, seen):
            dialog.controls["Zero reference"][1].set("Constant")
            dialog.update()
            dialog.controls["Zero value"][1].set("1,5")
            dialog.fields.select(dialog.field_rows["Replicates"][1].master)
            dialog.update()
            seen["hidden"] = dialog.reference_replicate_note.winfo_ismapped()
            dialog.controls["Replicates"][1].set("Normalize row means")
            dialog.update()
            seen["means"] = (dialog.reference_replicate_note.winfo_ismapped(),
                             dialog.reference_replicate_note.cget("text"))
            dialog.controls["Replicates"][1].set("Each replicate, common references")
            dialog.update()
            seen["each"] = dialog.reference_replicate_note.cget("text")
            dialog.controls["Input"][1].set("Summary values")
            dialog.update()
            seen["summary"] = (dialog.controls["Zero value"][1].get(),
                               dialog.reference_replicate_note.winfo_ismapped())
            dialog.controls["Input"][1].set("Raw values")
            dialog.update()
            seen["back"] = dialog.controls["Zero value"][1].get()
            dialog.controls["Error lower"][1].set("nope")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1]) if dialog.result else {}
            seen["still"] = dialog.controls["Zero value"][1].get()

        seen = self.drive(action)
        self.assertFalse(seen["hidden"])
        self.assertTrue(seen["means"][0])
        self.assertIn("row mean", seen["means"][1])
        self.assertIn("every replicate", seen["each"])
        self.assertNotEqual(seen["means"][1], seen["each"])
        self.assertEqual(seen["summary"], ("1,5", False))
        self.assertEqual(seen["back"], "1,5")
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"]["Zero value"], 1.5)
        self.assertNotIn("Error lower", seen["options"])
        self.assertEqual(seen["still"], "1,5")

    def test_italian_tabs_keep_the_english_recipe(self):
        def collect(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["displays"] = {name: dialog.field_rows[name][1].get()
                                for name in ("Input", "Replicates", "Units", "Zero reference")}
            seen["canonical"] = {name: dialog.controls[name][1].get()
                                 for name in ("Input", "Replicates", "Units", "Zero reference")}
            seen["rows"] = dialog.field_rows["Zero rows"][0].cget("text")
            dialog.controls["Zero reference"][1].set("Constant")
            dialog.controls["One reference"][1].set("Constant")
            dialog.update()
            dialog.controls["Zero value"][1].set("2")
            dialog.controls["One value"][1].set("2")
            ok, message, selected = self.rejected(dialog)
            seen["equal"] = (ok, message, dialog.fields.tab(selected, "text"), dialog.winfo_exists())
            dialog.controls["One reference"][1].set("Maximum")
            dialog.controls["Zero value"][1].set("1,5")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1]) if dialog.result else None
            seen["typed"] = dialog.controls["Zero value"][1].get()

        english = self.drive(collect)
        self.use("it")
        italian = self.drive(collect)
        self.assertEqual(english["tabs"], ["Input", "References", "Output"])
        self.assertEqual(italian["tabs"], ["Dati in ingresso", "Riferimenti", "Risultati"])
        self.assertEqual(italian["displays"]["Input"], "Valori grezzi")
        self.assertEqual(italian["displays"]["Replicates"], "Colonne indipendenti")
        self.assertEqual(italian["displays"]["Units"], "Percentuali")
        self.assertEqual(italian["canonical"], english["canonical"])
        self.assertEqual(italian["rows"], "Righe dello zero, numerate da 1")
        self.assertEqual(italian["equal"][0], False)
        self.assertIn("uguali", italian["equal"][1])
        self.assertIn("Riferimento uno", italian["equal"][1])
        self.assertEqual(italian["equal"][2], "Riferimenti")
        self.assertTrue(italian["equal"][3])
        self.assertTrue(italian["ok"])
        self.assertTrue(english["ok"])
        self.assertEqual(italian["options"], english["options"])
        self.assertEqual(italian["options"]["Input"], "Raw values")
        self.assertEqual(italian["options"]["Units"], "Percentages")
        self.assertEqual(italian["options"]["Zero reference"], "Constant")
        self.assertEqual(italian["options"]["Zero value"], 1.5)
        self.assertEqual(italian["typed"], "1,5")
        self.assertNotIn("One value", italian["options"])


if __name__ == "__main__":
    unittest.main()
