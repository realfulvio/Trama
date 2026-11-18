"""The real Analyze dialog for Repeated-measures correlation: fields, notes, EN/IT banners, seed range and recovery."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import rmcorr
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, tr
from analisi.rmcorr_dialog import NOTE_BOOTSTRAP, NOTE_MODEL, caption, describe_error, number, translate_error
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "rmcorr"
METHOD = rmcorr.RMCORR
FRAME = pd.read_csv(DATA / "repeated.csv")
RECIPE = {"Subject": "Participant", "X": "Day", "Y": "Signal", "Confidence interval": "None",
          "Confidence level (%)": 95.0, "Bootstrap replicates": 2000, "Seed": 0, "Show graph": True}
BOOTSTRAP = {**RECIPE, "Confidence interval": "Subject bootstrap", "Bootstrap replicates": 200, "Seed": 2026}


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("rmcorr.")]
        self.assertGreaterEqual(len(keys), 30)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_english_stays_as_written_and_italian_groups_counts_with_dots(self):
        message = "At most 50,000 complete pairs are supported; 50,001 were found."
        self.assertEqual(translate_error(message), message)
        self.use("it")
        self.assertNotEqual(translate_error(message), message)
        self.assertIn("50.000", translate_error(message))
        self.assertIn("50.001", translate_error(message))
        self.assertEqual(number("2,000,000"), "2.000.000")

    def test_the_field_is_named_once_and_worksheet_text_stays_literal(self):
        error = FieldError("X", 'Column "{Giorno} $x$" does not vary within any subject with two or more complete pairs.')
        self.assertEqual(describe_error(error), f"X: {error}")
        self.use("it")
        shown = describe_error(error)
        self.assertIn('"{Giorno} $x$"', shown)
        self.assertNotIn("does not vary", shown)
        self.assertEqual(caption("Bootstrap replicates"), "Repliche bootstrap")
        self.assertEqual(caption("Unlisted"), "Unlisted")


class DialogCase(TkCase):
    frame = FRAME

    def open(self, action, recipe=None, frame=None, geometry="1024x768+0+0"):
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
        self.root.geometry(geometry)
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
    def notes(dialog):
        return [child.cget("text") for tab in dialog.fields.tabs() for child in dialog.nametowidget(tab).winfo_children()
                if child.winfo_class() == "TLabel" and child.cget("text") in (tr(NOTE_MODEL), tr(NOTE_BOOTSTRAP))]

    @staticmethod
    def states(dialog):
        return {name: str(dialog.field_rows[name][1].cget("state"))
                for name in ("Confidence level (%)", "Bootstrap replicates", "Seed")}


class EnglishDialogTests(DialogCase):
    def test_fields_defaults_notes_and_the_recipe(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            seen["notes"] = self.notes(dialog)
            seen["off"] = self.states(dialog)
            dialog.controls["Confidence interval"][1].set("Subject bootstrap")
            seen["on"] = self.states(dialog)
            dialog.controls["Confidence interval"][1].set("None")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variables", "Options"])
        self.assertEqual(seen["captions"], ["Subject", "X", "Y", "Confidence interval", "Confidence level (%)",
                                            "Bootstrap replicates", "Seed", "Show graph"])
        self.assertEqual(len(seen["notes"]), 2)
        self.assertIn("Pearson", seen["notes"][0])
        self.assertEqual(set(seen["off"].values()), {"disabled"})
        self.assertEqual(set(seen["on"].values()), {"normal"})
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"], RECIPE)

    def test_the_largest_seed_is_accepted_and_one_more_is_refused_with_focus(self):
        def act(dialog, seen):
            dialog.controls["Confidence interval"][1].set("Subject bootstrap")
            dialog.controls["Seed"][1].set(str(2**64 - 1))
            seen["largest"] = self.attempt(dialog)
            seen["kept"] = dialog.result[1]["Seed"] if dialog.result else None
            dialog.result = None
            dialog.controls["Seed"][1].set(str(2**64))
            seen["over"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Seed"][1]
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")

        seen = self.open(act)
        self.assertTrue(seen["largest"][0], seen["largest"][1])
        self.assertEqual(seen["kept"], 2**64 - 1)
        self.assertFalse(seen["over"][0])
        self.assertTrue(seen["over"][1].startswith("Seed"), seen["over"][1])
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["page"], "Options")

    def test_replicates_and_level_out_of_range_name_their_field(self):
        def act(dialog, seen):
            dialog.controls["Confidence interval"][1].set("Subject bootstrap")
            dialog.controls["Bootstrap replicates"][1].set("99")
            seen["few"] = self.attempt(dialog)
            seen["few_focus"] = dialog.initial_focus is dialog.field_rows["Bootstrap replicates"][1]
            dialog.controls["Bootstrap replicates"][1].set("2000")
            dialog.controls["Confidence level (%)"][1].set("100")
            seen["level"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertFalse(seen["few"][0])
        self.assertIn("Bootstrap replicates", seen["few"][1])
        self.assertIn("100", seen["few"][1])
        self.assertTrue(seen["few_focus"])
        self.assertFalse(seen["level"][0])
        self.assertIn("Confidence level (%)", seen["level"][1])

    def test_inactive_bootstrap_entries_never_block(self):
        def act(dialog, seen):
            dialog.controls["Seed"][1].set("abc")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertTrue(seen["ok"], seen["message"])

    def test_the_same_column_twice_and_a_value_without_subject_move_the_focus(self):
        frame = FRAME.copy()
        frame.loc[len(frame)] = [np.nan, 4, 7.5]

        def act(dialog, seen):
            dialog.controls["X"][1].set("Participant")
            seen["same"] = self.attempt(dialog)
            seen["same_focus"] = dialog.initial_focus is dialog.field_rows["X"][1]
            dialog.controls["X"][1].set("Day")
            seen["orphan"] = self.attempt(dialog)
            seen["orphan_focus"] = dialog.initial_focus is dialog.field_rows["Subject"][1]

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["same"], (False, "Choose three different columns for Subject, X and Y."))
        self.assertEqual(seen["orphan"], (False, f"Subject: Row {len(frame)} has an X or Y value but no subject."))
        self.assertTrue(seen["same_focus"] and seen["orphan_focus"])

    def test_a_saved_recipe_reappears_unchanged(self):
        recipe = {**BOOTSTRAP, "Confidence level (%)": 90.0, "Seed": 2**64 - 1, "Show graph": False}

        def act(dialog, seen):
            seen["on"] = self.states(dialog)
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe)
        self.assertEqual(set(seen["on"].values()), {"normal"})
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"], recipe)

    def test_the_notes_wrap_inside_a_wide_window(self):
        def act(dialog, seen):
            dialog.update()
            labels = [child for tab in dialog.fields.tabs() for child in dialog.nametowidget(tab).winfo_children()
                      if child.winfo_class() == "TLabel" and child.cget("text") == tr(NOTE_MODEL)]
            seen["fit"] = labels[0].winfo_reqwidth(), dialog.fields.winfo_width()

        for geometry in ("1024x768+0+0", "1600x1000+0+0"):
            seen = self.open(act, geometry=geometry)
            requested, room = seen["fit"]
            self.assertLessEqual(requested, room, geometry)


class ItalianDialogTests(DialogCase):
    def test_captions_choices_and_notes_are_italian_while_the_recipe_stays_canonical(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            interval = dialog.choice_bindings["Confidence interval"]
            seen["choices"] = interval.combobox.cget("values")
            interval.display.set("Bootstrap per soggetti")
            seen["canonical"] = dialog.controls["Confidence interval"][1].get()
            seen["notes"] = self.notes(dialog)
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variabili", "Opzioni"])
        self.assertEqual(seen["captions"][:4], ["Soggetto", "X", "Y", "Intervallo di confidenza"])
        self.assertEqual(seen["captions"][5], "Repliche bootstrap")
        self.assertEqual(seen["choices"], ("Nessuno", "Bootstrap per soggetti"))
        self.assertEqual(seen["canonical"], "Subject bootstrap")
        self.assertEqual(seen["notes"], [tr(NOTE_MODEL), tr(NOTE_BOOTSTRAP)])
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"]["Confidence interval"], "Subject bootstrap")

    def test_the_banner_is_italian_and_names_the_field(self):
        self.use("it")
        frame = FRAME.copy()
        frame.loc[len(frame)] = [np.nan, 4, 7.5]

        def act(dialog, seen):
            dialog.controls["Y"][1].set("Day")
            seen["same"] = self.attempt(dialog)
            dialog.controls["Y"][1].set("Signal")
            seen["orphan"] = self.attempt(dialog)

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["same"], (False, "Scegli tre colonne diverse per Soggetto, X e Y."))
        self.assertFalse(seen["orphan"][0])
        self.assertTrue(seen["orphan"][1].startswith("Soggetto: "), seen["orphan"][1])
        self.assertIn(str(len(frame)), seen["orphan"][1])
        self.assertNotIn("subject", seen["orphan"][1])


class RecoveryTests(TkCase):
    """A worksheet edit that cannot be calculated keeps the confirmed result; Cancel keeps the last result."""

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
        self.frame = FRAME.copy()
        self.app._add_tables({"Repeated": self.frame})
        self.run = tramastat.Run(METHOD, "Repeated", dict(BOOTSTRAP))
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
        deadline = time.monotonic() + 30

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
                seen.append((dialog.initial_focus, dialog.fields.tab(dialog.fields.select(), "text")))
                dialog.result = None
                dialog.cancel()
            elif time.monotonic() < deadline:
                self.root.after(15, close)

        self.root.after(15, close)
        return seen

    def test_only_a_bootstrap_run_offers_cancel(self):
        self.assertTrue(self.module.cancellable_run(METHOD, BOOTSTRAP))
        self.assertFalse(self.module.cancellable_run(METHOD, RECIPE))

    def test_a_value_without_subject_keeps_the_result_and_reopens_the_dialog(self):
        previous = self.run.result
        self.app.show("data", "Repeated")
        seen = self.cancel_reopened_dialog()
        subject = self.app.tables["Repeated"].raw.columns.get_loc("Participant")
        self.app.edit_cell(0, subject, "")
        self.wait()
        self.assertTrue(seen, "The real recovery dialog must reopen")
        self.assertEqual(seen[0][1], "Variables")
        self.assertIs(self.run.result, previous)
        self.assertIn("no subject", self.run.calculation_error)
        self.app.show("data", "Repeated")
        self.app.edit_cell(0, subject, "A")
        self.wait()
        self.assertIsNot(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)

    def test_an_edit_recalculates_the_same_bootstrap(self):
        before = self.run.result.tables["Repeated-measures correlation"].copy()
        self.app.show("data", "Repeated")
        day = self.app.tables["Repeated"].raw.columns.get_loc("Day")
        self.app.edit_cell(0, day, str(FRAME.iloc[0]["Day"]))
        self.wait()
        pd.testing.assert_frame_equal(self.run.result.tables["Repeated-measures correlation"], before)

    def test_cancel_stops_a_bootstrap_run_and_keeps_the_last_result(self):
        rng = np.random.default_rng(4)
        subjects = np.repeat(np.arange(200), 5)
        x = rng.normal(size=len(subjects))
        big = pd.DataFrame({"Participant": subjects, "Day": x, "Signal": x + rng.normal(size=len(subjects))})
        self.app._add_tables({"Big": big})
        run = self.module.Run(METHOD, "Big", {**BOOTSTRAP, "Bootstrap replicates": 10_000})
        self.app.add_result(run, self.app.compute(run, big))
        previous = run.result
        index = self.app.runs.index(run)
        self.app.recalculate(index)
        self.assertIsNotNone(self.app.calculation)
        self.app.calculation.cancel.set()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIs(self.app.runs[index].result, previous)
        self.assertEqual(self.app.status.get(), f"{METHOD} cancelled. The last completed results are kept.")


if __name__ == "__main__":
    unittest.main()
