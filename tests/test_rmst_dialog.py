"""The real Analyze dialog for Restricted mean survival time: pages, reference group, typed numbers, EN/IT, recovery."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi import rmst_workbench as workbench
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate_message
from analisi.rmst_dialog import amount, caption, describe_error, read_number, shown_number, translate_error
from analisi.rmst_text import ERROR_PREFIX, MESSAGES
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "rmst" / "fixtures"
METHOD = workbench.RMST
COHORTS = pd.read_csv(DATA / "cohorts.csv")
RECIPE = {"Time": "Time", "Status": "Event", "Group": "Group", "Reference group": "Reference", "Horizon": 6.5,
          "Event code": "1", "Censor code": "0", "Confidence level (%)": 95.0, "Show graph": True}
SAMPLES = {"field": "Horizon", "role": "Time", "first": "Status", "name": "Series $B", "limit": "50,000",
           "count": "50,001", "row": "4", "shown": "'x'", "value": "8.5", "first_group": "A_1",
           "second_group": "$B"}


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("rmst.")]
        self.assertGreater(len(keys), 40)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        self.assertEqual(CATALOGS["it"]["interface.Restricted mean survival time"], "Sopravvivenza media ristretta")

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key, english in MESSAGES.items():
            with self.subTest(key=key):
                values = {name: SAMPLES[name] for name in placeholders(english)}
                message = english.format(**values)
                shown = translate_message(message, ERROR_PREFIX)
                self.assertNotEqual(shown, message)
                self.assertEqual(shown, CATALOGS["it"][ERROR_PREFIX + key].format(**values))

    def test_english_messages_stay_as_written(self):
        self.use("en")
        error = FieldError("Horizon", MESSAGES["horizon_beyond"].format(field="Horizon", value="8.5", name="$B",
                                                                         limit="8"))
        self.assertEqual(translate_error(error), str(error))
        self.assertEqual(describe_error(error), str(error))

    def test_italian_numbers_use_the_decimal_comma_and_group_names_stay_literal(self):
        self.use("it")
        error = FieldError("Horizon", MESSAGES["horizon_beyond"].format(field="Horizon", value="8.5",
                                                                         name="Series $B", limit="8.25"))
        self.assertEqual(describe_error(error), "Orizzonte 8,5 supera il follow-up. Il gruppo Series $B è osservato "
                                                "fino a 8,25: usa un orizzonte maggiore di 0 e non oltre questo "
                                                "valore.")
        rows = FieldError("Time", MESSAGES["rows"].format(limit="50,000", count="50,001"))
        self.assertIn("50.000", translate_error(rows))
        self.assertIn("50.001", translate_error(rows))
        self.assertEqual(amount("6.5"), "6,5")
        self.assertEqual(shown_number(6.5), "6,5")
        self.assertEqual(shown_number(8.0), "8")

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.use("it")
        error = FieldError("Reference group", MESSAGES["reference_empty"].format(first_group="A", second_group="B"))
        self.assertEqual(describe_error(error), "Scegli il gruppo di riferimento: A o B.")
        error = FieldError("Censor code", MESSAGES["same_codes"])
        self.assertTrue(describe_error(error).startswith("Il codice evento e il codice censura"))
        error = FieldError("Status", MESSAGES["status_mixed"].format(name="Event"))
        self.assertEqual(describe_error(error), 'La colonna "Event" mescola numeri e testo. Usa un solo tipo di codice '
                                                "di stato.")
        error = FieldError("Time", MESSAGES["time_type"].format(name="Days"))
        self.assertTrue(describe_error(error).startswith('Tempo: La colonna "Days"'))
        self.assertEqual(caption("Horizon"), "Orizzonte")

    def test_generic_dialog_messages_are_translated(self):
        self.use("it")
        self.assertEqual(translate_error(ValueError("Choose a column for Time.")), "Scegli una colonna per Tempo.")

    def test_typed_numbers(self):
        self.assertEqual(read_number(" 6,5 "), 6.5)
        self.assertEqual(read_number("1e2"), 100.0)
        self.assertEqual(read_number(""), "")
        self.assertEqual(read_number("soon"), "soon")


class DialogCase(TkCase):
    frame = COHORTS

    def open(self, action, recipe=None, frame=None, size="1024x768"):
        from tramastat import AnalysisDialog

        seen = {}

        def drive():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            try:
                dialog.update_idletasks()
                action(dialog, seen)
            except Exception:
                import traceback
                seen["error"] = traceback.format_exc()
            finally:
                dialog.result = seen.get("keep")
                dialog.cancel() if dialog.result is None else dialog.destroy()

        self.root.deiconify()
        self.root.geometry(f"{size}+0+0")
        self.root.after(80, drive)
        AnalysisDialog(self.root, (self.frame if frame is None else frame).copy(),
                       current=(METHOD, recipe) if recipe else None, only=METHOD)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def page(dialog):
        return dialog.fields.tab(dialog.fields.select(), "text")

    @staticmethod
    def focused(dialog, name):
        widget = dialog.field_rows[name][1]
        return dialog.initial_focus is widget


class EnglishDialogTests(DialogCase):
    def test_pages_captions_defaults_and_the_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in controls]
            seen["defaults"] = {name: controls[name][1].get() for name in controls}
            seen["reference shown"] = dialog.field_rows["Reference group"][1].winfo_ismapped()
            seen["empty horizon"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = self.focused(dialog, "Horizon")
            controls["Horizon"][1].set("5")
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Data", "Codes and estimate"])
        self.assertEqual(seen["captions"], ["Time", "Status", "Group", "Reference group", "Horizon", "Event code",
                                            "Censor code", "Confidence level (%)", "Show graph"])
        self.assertEqual(seen["defaults"], {"Time": "Time", "Status": "Event", "Group": "", "Reference group": "",
                                            "Horizon": "", "Event code": "1", "Censor code": "0",
                                            "Confidence level (%)": "95.0", "Show graph": True})
        self.assertFalse(seen["reference shown"])
        self.assertEqual(seen["empty horizon"], (False, "Enter the horizon: a time greater than 0, in the units of "
                                                        "the Time column."))
        self.assertEqual(seen["page"], "Data")
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {"Time": "Time", "Status": "Event", "Group": None, "Horizon": 5.0,
                                          "Event code": "1", "Censor code": "0", "Confidence level (%)": 95.0,
                                          "Show graph": True})

    def test_group_offers_the_reference_and_the_horizon_limit(self):
        def act(dialog, seen):
            dialog.controls["Group"][1].set("Group")
            dialog.update()
            seen["shown"] = dialog.field_rows["Reference group"][1].winfo_ismapped()
            seen["values"] = list(dialog.field_rows["Reference group"][1].cget("values"))
            seen["reference"] = dialog.controls["Reference group"][1].get()
            seen["limit"] = dialog.rmst_limit.cget("text")
            dialog.controls["Horizon"][1].set("8.5")
            seen["beyond"] = self.attempt(dialog)
            seen["focus"] = self.focused(dialog, "Horizon")
            dialog.controls["Horizon"][1].set("6,5")
            dialog.controls["Reference group"][1].set("Series $B")
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]
            dialog.controls["Group"][1].set("")
            dialog.update()
            seen["hidden"] = not dialog.field_rows["Reference group"][1].winfo_ismapped()
            seen["single"] = dialog.validate() and dialog.result[1]

        seen = self.open(act)
        self.assertTrue(seen["shown"])
        self.assertEqual(seen["values"], ["Reference", "Series $B"])
        self.assertEqual(seen["reference"], "Reference")
        self.assertEqual(seen["limit"], "Largest usable horizon: 8.")
        self.assertEqual(seen["beyond"], (False, "Horizon 8.5 is beyond the follow-up. Group Reference is observed "
                                                 "up to 8: use a horizon greater than 0 and no larger than that."))
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {**RECIPE, "Reference group": "Series $B"})
        self.assertTrue(seen["hidden"])
        self.assertNotIn("Reference group", seen["single"])
        self.assertIsNone(seen["single"]["Group"])

    def test_a_reference_change_is_dropped_by_cancel(self):
        def change(dialog, seen):
            dialog.controls["Reference group"][1].set("Series $B")

        def look(dialog, seen):
            seen["reference"] = dialog.controls["Reference group"][1].get()
            seen["horizon"] = dialog.controls["Horizon"][1].get()
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]

        self.open(change, RECIPE)  # closed with Cancel: nothing is kept
        seen = self.open(look, RECIPE)
        self.assertEqual((seen["reference"], seen["horizon"]), ("Reference", "6.5"))
        self.assertEqual(seen["recipe"], RECIPE)

    def test_a_saved_reference_that_is_no_longer_a_group_stays_until_corrected(self):
        frame = COHORTS.replace({"Group": {"Reference": "Control"}})

        def act(dialog, seen):
            seen["reference"] = dialog.controls["Reference group"][1].get()
            seen["values"] = list(dialog.field_rows["Reference group"][1].cget("values"))
            seen["stale"] = self.attempt(dialog)
            seen["focus"] = self.focused(dialog, "Reference group")
            dialog.controls["Reference group"][1].set("Control")
            seen["ok"] = dialog.validate()

        seen = self.open(act, RECIPE, frame)
        self.assertEqual(seen["reference"], "Reference")
        self.assertEqual(seen["values"], ["Control", "Series $B"])
        self.assertEqual(seen["stale"], (False, 'Reference group: "Reference" is not a group of the complete rows. '
                                                "Choose Control or Series $B."))
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["ok"])

    def test_text_codes_level_and_a_typed_number_that_is_not_a_number(self):
        frame = pd.read_csv(DATA / "text-status.csv")
        recipe = {"Time": "Time", "Status": "Status", "Group": "Cohort", "Reference group": "Ref", "Horizon": 4.0,
                  "Event code": "event", "Censor code": "lost", "Confidence level (%)": 90.0, "Show graph": False}

        def act(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]
            dialog.controls["Censor code"][1].set("event")
            seen["same"] = self.attempt(dialog)
            seen["same page"] = self.page(dialog)
            seen["same focus"] = self.focused(dialog, "Censor code")
            dialog.controls["Censor code"][1].set("lost")
            dialog.controls["Confidence level (%)"][1].set("ninety")
            seen["level"] = self.attempt(dialog)
            dialog.controls["Confidence level (%)"][1].set("97,5")
            dialog.controls["Horizon"][1].set("soon")
            seen["horizon"] = self.attempt(dialog)
            dialog.controls["Horizon"][1].set("3,25")
            seen["fixed"] = dialog.validate()
            seen["fixed recipe"] = dialog.result[1]

        seen = self.open(act, recipe, frame)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], recipe)
        self.assertEqual(seen["same"], (False, "The event code and the censor code are the same status. Use "
                                               "different codes."))
        self.assertEqual(seen["same page"], "Codes and estimate")
        self.assertTrue(seen["same focus"])
        self.assertEqual(seen["level"], (False, "Confidence level (%) must be a number greater than 0 and less "
                                                "than 100."))
        self.assertEqual(seen["horizon"], (False, "Horizon must be a finite number greater than 0."))
        self.assertTrue(seen["fixed"])
        self.assertEqual(seen["fixed recipe"], {**recipe, "Horizon": 3.25, "Confidence level (%)": 97.5})

    def test_three_groups_name_the_group_field(self):
        frame = COHORTS.assign(Group=["C"] + COHORTS["Group"].tolist()[1:])

        def act(dialog, seen):
            seen["values"] = list(dialog.field_rows["Reference group"][1].cget("values"))
            seen["limit"] = dialog.rmst_limit.cget("text")
            seen["banner"] = self.attempt(dialog)
            seen["focus"] = self.focused(dialog, "Group")

        seen = self.open(act, RECIPE, frame)
        self.assertEqual(seen["values"], ["C", "Series $B", "Reference"])
        self.assertEqual(seen["limit"], "")
        self.assertIn('Column "Group" has 3 groups', seen["banner"][1])
        self.assertTrue(seen["focus"])

    def test_buttons_stay_on_a_1024_by_768_screen(self):
        def act(dialog, seen):
            dialog.update()
            buttons = [w for w in dialog.winfo_children() if w.winfo_class() == "TFrame"][-1]
            seen["bottom"] = dialog.winfo_rooty() + dialog.winfo_height()
            seen["right"] = dialog.winfo_rootx() + dialog.winfo_width()
            seen["screen"] = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
            seen["buttons"] = buttons.winfo_rooty() + buttons.winfo_height()

        for language in ("en", "it"):
            with self.subTest(language=language):
                self.use(language)
                seen = self.open(act, RECIPE)
                width, height = seen["screen"]
                limit = min(height, 768)
                self.assertLessEqual(seen["buttons"], limit)
                self.assertLessEqual(seen["bottom"], limit)
                self.assertLessEqual(seen["right"], min(width, 1024))


class ItalianDialogTests(DialogCase):
    def test_captions_hints_and_banner_are_italian_while_the_recipe_stays_canonical(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            seen["horizon"] = dialog.controls["Horizon"][1].get()
            seen["limit"] = dialog.rmst_limit.cget("text")
            dialog.controls["Horizon"][1].set("8,5")
            seen["beyond"] = self.attempt(dialog)
            dialog.controls["Horizon"][1].set("6,5")
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, {**RECIPE, "Horizon": 6.5})
        self.assertEqual(seen["tabs"], ["Dati", "Codici e stima"])
        self.assertEqual(seen["captions"], ["Tempo", "Stato", "Gruppo", "Gruppo di riferimento", "Orizzonte",
                                            "Codice evento", "Codice censura", "Livello di confidenza (%)",
                                            "Mostra grafico"])
        self.assertEqual(seen["horizon"], "6,5")
        self.assertEqual(seen["limit"], "Orizzonte massimo utilizzabile: 8.")
        self.assertEqual(seen["beyond"], (False, "Orizzonte 8,5 supera il follow-up. Il gruppo Reference è "
                                                 "osservato fino a 8: usa un orizzonte maggiore di 0 e non oltre "
                                                 "questo valore."))
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], RECIPE)

    def test_the_menu_caption_is_italian(self):
        self.use("it")
        self.assertEqual(i18n.ui("Restricted mean survival time"), "Sopravvivenza media ristretta")


class RecoveryTests(TkCase):
    """Edits and exclusions recalculate with the saved recipe; a horizon beyond the new support flags a stale result."""

    def setUp(self):
        import tramastat
        self.module = tramastat
        self.tmp = tempfile.TemporaryDirectory()
        preferences = Path(self.tmp.name) / "preferences.json"
        save_theme(preferences, "standard")
        self.root.deiconify()
        with patch.object(tramastat, "config_path", return_value=preferences):
            self.app = tramastat.App(self.root)
        self.root.geometry("1000x700+0+0")
        self.errors = []
        self.app.error = lambda message: self.errors.append(str(message))
        self.frame = COHORTS.copy()
        self.app._add_tables({"Cohorts": self.frame})
        self.run = tramastat.Run(METHOD, "Cohorts", dict(RECIPE))
        self.app.add_result(self.run, self.app.compute(self.run, self.frame))
        self.root.update()

    def tearDown(self):
        self.wait()
        self.app._clear("")
        self.app.worker.shutdown(wait=True)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.withdraw()
        self.tmp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 12

        def poll():
            if self.app.pending is None or time.monotonic() >= deadline:
                self.root.quit()
            else:
                self.root.after(10, poll)

        self.root.after(0, poll)
        self.root.mainloop()
        self.root.update()
        self.assertIsNone(self.app.pending)

    def cancel_reopened_dialog(self):
        seen = []
        deadline = time.monotonic() + 8

        def close():
            dialogs = [w for w in self.root.winfo_children() if isinstance(w, self.module.AnalysisDialog)]
            if dialogs and dialogs[0].grab_current() is dialogs[0]:
                dialog = dialogs[0]
                seen.append((dialog.initial_focus is dialog.field_rows["Horizon"][1],
                             dialog.fields.tab(dialog.fields.select(), "text")))
                dialog.result = None
                dialog.cancel()
            elif time.monotonic() < deadline:
                self.root.after(15, close)

        self.root.after(15, close)
        return seen

    def rmst(self, label):
        return float(self.run.result.tables["RMST"].set_index("Group").loc[label, "RMST"])

    def test_an_edit_recalculates_with_the_saved_options(self):
        before = self.rmst("Reference")
        self.app.show("data", "Cohorts")
        time_column = self.app.tables["Cohorts"].raw.columns.get_loc("Time")
        self.app.edit_cell(2, time_column, "1.5")  # Reference: the event at 1 moves to 1.5
        self.wait()
        self.assertIsNone(self.run.calculation_error)
        self.assertAlmostEqual(self.rmst("Reference") - before, 0.5 * (1 - 5 / 6), places=12)
        self.assertEqual(self.run.options, RECIPE)

    def test_shrinking_the_support_below_the_horizon_keeps_the_result_and_reopens_horizon(self):
        previous = self.run.result
        self.app.show("data", "Cohorts")
        seen = self.cancel_reopened_dialog()
        time_column = self.app.tables["Cohorts"].raw.columns.get_loc("Time")
        self.app.edit_cell(10, time_column, "5")  # the last Reference observation, 8, becomes 5 < 6.5
        self.wait()
        self.assertTrue(seen, "The real recovery dialog must reopen")
        self.assertEqual(seen[0], (True, "Data"))
        self.assertIs(self.run.result, previous)
        self.assertIn("beyond the follow-up", self.run.calculation_error)
        self.app.show("result", 0)
        self.assertIn("observed up to 6", self.app.stale_calculation_note())
        self.app.show("data", "Cohorts")
        self.app.edit_cell(10, time_column, "8")
        self.wait()
        self.assertIsNot(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)

    def test_the_stale_note_is_translated_with_the_active_language(self):
        self.use("it")
        self.run.calculation_error = MESSAGES["horizon_beyond"].format(field="Horizon", value="6.5", name="Reference",
                                                                       limit="6")
        self.app.show("result", 0)
        self.assertIn("Orizzonte 6,5 supera il follow-up", self.app.stale_calculation_note())


if __name__ == "__main__":
    unittest.main()
