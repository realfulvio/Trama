"""Repeated measures ANOVA dialog: the Sphericity correction choice, its note, field errors and Italian wording."""
import traceback
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import i18n, rm_sphericity
from analisi.field_error import FieldError
from tests.test_graph_i18n import LanguageMixin, TkCase
from tests.test_rm_sphericity import CONDITION, METHOD, VISIT, long, tables

LEGACY = "Geisser–Greenhouse (one-way)"
FIELD = rm_sphericity.FIELD


class DialogCase(TkCase):
    def setUp(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog

    def drive(self, action, *, frame=None, current=None, geometry="1024x768+0+0"):
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
        self.root.geometry(geometry)
        self.root.after(80, step)
        self.AnalysisDialog(self.root, long() if frame is None else frame,
                            current=(METHOD, current) if current is not None else None, only=METHOD)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def choose(dialog, factors=(VISIT, CONDITION), subject="Subject"):
        box = dialog.controls["Factors"][1]
        columns = list(box.get(0, "end"))
        box.selection_clear(0, "end")
        for name in factors:
            box.selection_set(columns.index(name))
        box.event_generate("<<ListboxSelect>>")
        dialog.controls["Response"][1].set("Response")
        dialog.controls["Subject"][1].set(subject)
        dialog.update()

    @staticmethod
    def rejected(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        return ok, report.call_args.args[1] if report.call_args else ""


class ChoiceTests(DialogCase):
    def test_new_dialog_offers_none_and_the_canonical_choice_and_starts_without_correction(self):
        def action(dialog, seen):
            binding = dialog.choice_bindings[FIELD]
            seen["values"] = binding.values
            seen["labels"] = binding.labels
            seen["start"] = dialog.controls[FIELD][1].get()
            seen["state"] = str(dialog.field_rows[FIELD][1].cget("state"))
            seen["note_none"] = dialog.sphericity_note.cget("text")
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            dialog.update()
            seen["note_gg"] = dialog.sphericity_note.cget("text")
            dialog.controls[FIELD][1].set(rm_sphericity.HF)
            dialog.update()
            seen["note_hf"] = dialog.sphericity_note.cget("text")
            dialog.controls[FIELD][1].set(rm_sphericity.LOWER)
            dialog.update()
            seen["note_lower"] = dialog.sphericity_note.cget("text")

        seen = self.drive(action)
        self.assertEqual(seen["values"], ("None", "Geisser–Greenhouse", "Huynh-Feldt", "Lower bound"))
        self.assertEqual(seen["labels"], ("None", "Geisser–Greenhouse", "Huynh-Feldt", "Lower bound"))
        self.assertEqual(seen["start"], "None")
        self.assertEqual(seen["state"], "readonly")
        self.assertIn("assume sphericity", seen["note_none"])
        for phrase in ("omnibus", "post-hoc", "Mauchly", "REML", "complete design"):
            self.assertIn(phrase, seen["note_gg"])
        for phrase in ("Huynh–Feldt estimates", "does not test sphericity", "Mauchly", "complete design"):
            self.assertIn(phrase, seen["note_hf"])
        for phrase in ("Lower bound", "1/d", "most conservative", "complete design"):
            self.assertIn(phrase, seen["note_lower"])

    def test_the_one_way_spelling_appears_only_for_a_recipe_that_uses_it(self):
        current = {"Response": "Response", "Factors": [VISIT], "Subject": "Subject", FIELD: LEGACY}

        def action(dialog, seen):
            binding = dialog.choice_bindings[FIELD]
            seen["values"] = binding.values
            seen["labels"] = binding.labels
            seen["shown"] = dialog.field_rows[FIELD][1].get()
            seen["note"] = dialog.sphericity_note.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1]) if dialog.result else None

        frame = long().drop(columns=CONDITION).groupby(["Subject", VISIT], as_index=False)["Response"].mean()
        seen = self.drive(action, frame=frame, current=current)
        self.assertEqual(seen["values"], ("None", "Geisser–Greenhouse", "Huynh-Feldt", "Lower bound", LEGACY))
        self.assertEqual(seen["labels"][4], "Geisser–Greenhouse (one-way, saved recipe)")
        self.assertEqual(seen["shown"], "Geisser–Greenhouse (one-way, saved recipe)")
        self.assertIn("Saved recipe", seen["note"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][FIELD], LEGACY)

    def test_italian_labels_note_and_recipe_stay_canonical(self):
        self.use("it")

        def action(dialog, seen):
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            dialog.update()
            seen["caption"] = dialog.field_rows[FIELD][0].cget("text")
            seen["none"] = dialog.choice_bindings[FIELD].labels[0]
            seen["note"] = dialog.sphericity_note.cget("text")
            dialog.controls[FIELD][1].set(rm_sphericity.HF)
            dialog.update()
            seen["note_hf"] = dialog.sphericity_note.cget("text")
            seen["labels"] = dialog.choice_bindings[FIELD].labels
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            dialog.update()
            self.choose(dialog)
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])

        seen = self.drive(action)
        self.assertEqual(seen["labels"], ("Nessuno", "Geisser–Greenhouse", "Huynh–Feldt", "Limite inferiore"))
        for phrase in ("Huynh–Feldt stima", "Mauchly", "disegno completo"):
            self.assertIn(phrase, seen["note_hf"])
        self.assertEqual(seen["caption"], "Correzione della sfericità")
        self.assertEqual(seen["none"], "Nessuno")
        for phrase in ("omnibus", "post-hoc", "Mauchly", "REML"):
            self.assertIn(phrase, seen["note"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][FIELD], "Geisser–Greenhouse")
        self.assertEqual(seen["options"]["Factors"], [VISIT, CONDITION])

    def test_the_choice_is_reachable_and_visible_on_a_small_screen(self):
        def action(dialog, seen):
            dialog.fields.select(dialog.field_rows[FIELD][1].master)
            dialog.update()
            field, note = dialog.field_rows[FIELD][1], dialog.sphericity_note
            seen["field_visible"] = field.winfo_viewable()
            seen["note_visible"] = note.winfo_viewable()
            seen["inside"] = (note.winfo_rooty() + note.winfo_height()
                              <= dialog.winfo_rooty() + dialog.winfo_height())
            dialog.field_rows[FIELD][1].focus_force()
            dialog.update()
            seen["focus"] = dialog.focus_get() is field

        seen = self.drive(action, geometry="1024x768+0+0")
        self.assertTrue(seen["field_visible"] and seen["note_visible"] and seen["inside"])


class ValidationTests(DialogCase):
    def test_a_good_design_runs_in_the_dialog_and_reuses_the_result(self):
        def action(dialog, seen):
            self.choose(dialog)
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])
            seen["tables"] = list(dialog.processing_result.tables)

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"], {"Response": "Response", "Factors": [VISIT, CONDITION],
                                           "Subject": "Subject", FIELD: "Geisser–Greenhouse"})
        self.assertEqual(seen["tables"], ["ANOVA", "Sphericity"])

    def test_without_a_correction_the_recipe_and_the_sheets_are_unchanged(self):
        def action(dialog, seen):
            self.choose(dialog)
            seen["ok"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])
            seen["tables"] = list(dialog.processing_result.tables)

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["options"][FIELD], "None")
        self.assertEqual(seen["tables"], ["ANOVA"])

    def test_an_incomplete_design_keeps_the_dialog_open_on_the_subject_field(self):
        def action(dialog, seen):
            self.choose(dialog)
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            seen["ok"], seen["message"] = self.rejected(dialog)
            seen["focus_page"] = dialog.fields.index(dialog.fields.select())
            seen["factors"] = [dialog.controls["Factors"][1].get(i) for i in dialog.controls["Factors"][1].curselection()]
            seen["choice"] = dialog.controls[FIELD][1].get()
            seen["result"] = dialog.result

        seen = self.drive(action, frame=long().drop(index=1))
        self.assertFalse(seen["ok"])
        self.assertIsNone(seen["result"])
        self.assertIn("Subject S1 has no measurement for Visit = Visit 1; Condition = Condition 2", seen["message"])
        self.assertIn("9 combinations of Visit × Condition", seen["message"])
        self.assertEqual(seen["focus_page"], 0)  # Subject sits on the Variables page
        self.assertEqual(seen["factors"], [VISIT, CONDITION])
        self.assertEqual(seen["choice"], "Geisser–Greenhouse")

    def test_the_same_dialog_runs_again_after_a_between_subject_column_is_replaced(self):
        frame = long().assign(Site=lambda f: f["Subject"].map({"S1": "North", "S2": "North", "S3": "South",
                                                               "S4": "South", "S5": "South"}))

        def action(dialog, seen):
            self.choose(dialog, factors=(VISIT, "Site"))
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            seen["first"], seen["message"] = self.rejected(dialog)
            self.choose(dialog, factors=(VISIT, CONDITION))
            seen["second"] = dialog.validate()
            seen["tables"] = list(dialog.processing_result.tables)

        seen = self.drive(action, frame=frame)
        self.assertFalse(seen["first"])
        self.assertIn("Subject S1 has 3 measurements for Visit = Visit 1; Site = North", seen["message"])
        self.assertTrue(seen["second"])
        self.assertEqual(seen["tables"], ["ANOVA", "Sphericity"])

    def test_italian_errors_name_the_field_and_keep_the_values_literal(self):
        self.use("it")

        def action(dialog, seen):
            self.choose(dialog)
            dialog.controls[FIELD][1].set(rm_sphericity.CANONICAL)
            seen["ok"], seen["message"] = self.rejected(dialog)

        seen = self.drive(action, frame=pd.concat([long(), long().iloc[:1]]))
        self.assertFalse(seen["ok"])
        self.assertTrue(seen["message"].startswith("Soggetto: "), seen["message"])
        self.assertIn("2 misure per Visit = Visit 1; Condition = Condition 1", seen["message"])

    def test_the_legacy_choice_with_two_factors_names_the_choice(self):
        current = {"Response": "Response", "Factors": [VISIT, CONDITION], "Subject": "Subject", FIELD: LEGACY}

        def action(dialog, seen):
            seen["ok"], seen["message"] = self.rejected(dialog)

        seen = self.drive(action, current=current)
        self.assertFalse(seen["ok"])
        self.assertIn("Geisser–Greenhouse to correct two Factors", seen["message"])


class Wording(LanguageMixin, unittest.TestCase):
    def test_every_sentence_has_both_languages_with_the_same_placeholders(self):
        for key, english in rm_sphericity.ERRORS.items():
            catalog = "rm.sphericity.error." + key
            self.assertEqual(i18n.CATALOGS["en"][catalog], english, key)
            self.assertTrue(i18n.CATALOGS["it"][catalog], key)
            self.assertEqual(i18n.placeholders(english), i18n.placeholders(i18n.CATALOGS["it"][catalog]), key)
        for key in ("choice.legacy", "note.none", "note.gg", "note.hf", "note.lower", "note.legacy"):
            self.assertTrue(i18n.CATALOGS["it"]["rm.sphericity." + key], key)

    def test_format_error_translates_with_literal_values_and_names_the_field(self):
        frame = long()
        with self.assertRaises(FieldError) as error:
            tables(frame.assign(Subject=frame["Subject"].replace("S1", "Ça {1}")).drop(index=1))
        self.use("it")
        shown = rm_sphericity.format_error(error.exception)
        self.assertTrue(shown.startswith("Soggetto: "), shown)
        self.assertIn("Ça {1}", shown)
        self.assertIn("non ha una misura", shown)
        self.use("en")
        # The English sentence already names the field, so no caption is prefixed.
        self.assertEqual(rm_sphericity.format_error(error.exception), str(error.exception))
        with self.assertRaises(FieldError) as other:
            tables(frame.assign(**{VISIT: "same"}))
        self.assertTrue(rm_sphericity.format_error(other.exception).startswith("Factors: "))

    def test_format_error_ignores_other_errors(self):
        self.assertIsNone(rm_sphericity.format_error(ValueError("Anything")))
        self.assertIsNone(rm_sphericity.format_error(FieldError("Response", "A sentence of another module.")))


if __name__ == "__main__":
    unittest.main()
