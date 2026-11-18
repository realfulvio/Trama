"""The real Analyze dialog for Meta-analysis: pages, captions, the ratio unit, hidden fields, EN/IT and recovery."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import meta_analysis as meta
from analisi.field_error import FieldError
from analisi.meta_analysis_dialog import describe_error, translate_error
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).resolve().parent / "data" / "meta_analysis"
METHOD = meta.META_ANALYSIS
RATIOS = pd.read_csv(DATA / "ratios.csv")
RECIPE = {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE", "Measure": "Ratio",
          "Pooling model": meta.RANDOM, "Random interval": meta.MODIFIED_KH, "Confidence level (%)": 95.0,
          "Prediction interval": True, "Leave one out": True, "Show graph": True}


class MessageTests(TkCase):
    def test_italian_banners_name_the_field_and_keep_worksheet_text(self):
        self.use("it")
        error = FieldError("Standard error", "Standard error: source row 4 must be greater than zero (0).")
        self.assertEqual(describe_error(error), "Errore standard: la riga di origine 4 deve essere maggiore di zero (0).")
        error = FieldError("Standard error", "Standard error: choose a column different from Estimate.")
        self.assertEqual(describe_error(error), "Errore standard: scegli una colonna diversa da Stima.")
        error = FieldError("Estimate", 'Choose an existing column for Estimate: "Dose $x$" is not in the worksheet.')
        self.assertEqual(translate_error(error),
                         "Scegli una colonna esistente per Stima: «Dose $x$» non è nel foglio dati.")
        self.assertEqual(describe_error(FieldError("Confidence level (%)", "Confidence level (%) must be a number.")),
                         "Il livello di confidenza (%) deve essere un numero.")

    def test_english_messages_stay_as_written_and_the_field_is_named_once(self):
        self.use("en")
        error = FieldError("Pooling model", "Pooling model: the Paule–Mandel estimate of tau² did not converge.")
        self.assertEqual(describe_error(error), str(error))
        self.assertEqual(describe_error(FieldError("Leave one out", "Leave one out: choose on or off.")),
                         "Leave one out: choose on or off.")
        self.assertEqual(describe_error(FieldError("Show graph", "Choose on or off.")), "Show graph: Choose on or off.")


class DialogCase(TkCase):
    def open(self, action, recipe=None, frame=None):
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
        self.root.geometry("1024x768+0+0")
        self.root.after(80, drive)
        AnalysisDialog(self.root, (RATIOS if frame is None else frame).copy(),
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
    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    @staticmethod
    def focused(dialog):
        """The field whose control holds the keyboard focus after a failed Run Analysis."""
        return next((name for name, (_, widget) in dialog.field_rows.items() if widget is dialog.initial_focus), None)


class EnglishDialogTests(DialogCase):
    def setUp(self):
        self.use("en")

    def test_pages_captions_and_the_common_effect_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in controls}
            seen["hidden"] = [name for name in controls if not self.placed(dialog, name)]
            seen["pages"] = {name: dialog.fields.tab(dialog.field_rows[name][1].master, "text") for name in controls}
            for name, column in (("Study", "Study"), ("Estimate", "Estimate"), ("Standard error", "SE")):
                controls[name][1].set(column)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Studies", "Model and output"])
        self.assertEqual(list(seen["captions"].values()),
                         ["Study", "Estimate", "Standard error", "Measure", "Pooling model", "Random interval",
                          "Confidence level (%)", "Prediction interval", "Leave one out", "Show graph"])
        self.assertEqual(seen["hidden"], ["Random interval", "Prediction interval"])
        self.assertEqual({name for name, page in seen["pages"].items() if page == "Studies"},
                         {"Study", "Estimate", "Standard error", "Measure"})
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE",
                                          "Measure": "Difference", "Pooling model": meta.COMMON,
                                          "Confidence level (%)": 95.0, "Leave one out": False, "Show graph": True})

    def test_ratio_relabels_the_standard_error_and_highlights_the_log_unit(self):
        def act(dialog, seen):
            heading = dialog.field_rows["Standard error"][0]
            seen["before"] = heading.cget("text"), dialog.meta_unit_note.cget("text")
            dialog.controls["Measure"][1].set("Ratio")
            dialog.update()
            seen["after"] = heading.cget("text"), dialog.meta_unit_note.cget("text")
            dialog.controls["Pooling model"][1].set(meta.RANDOM)
            dialog.update()
            seen["random"] = [self.placed(dialog, name) for name in ("Random interval", "Prediction interval")]
            seen["choices"] = list(dialog.field_rows["Random interval"][1].cget("values"))

        seen = self.open(act)
        self.assertEqual(seen["before"][0], "Standard error")
        self.assertEqual(seen["after"][0], "SE of ln(ratio)")
        self.assertIn("NATURAL LOGARITHM", seen["after"][1])
        self.assertNotIn("NATURAL LOGARITHM", seen["before"][1])
        self.assertEqual(seen["random"], [True, True])
        self.assertEqual(seen["choices"], ["Modified Knapp–Hartung", "Normal"])

    def test_a_field_error_keeps_the_dialog_on_its_page_with_the_focus(self):
        def act(dialog, seen):
            controls = dialog.controls
            controls["Estimate"][1].set("Estimate")
            controls["Standard error"][1].set("Estimate")
            seen["same"] = self.attempt(dialog), self.focused(dialog)
            controls["Standard error"][1].set("SE")
            controls["Confidence level (%)"][1].set("100")
            seen["level"] = self.attempt(dialog), self.focused(dialog), dialog.fields.tab(dialog.fields.select(),
                                                                                         "text")
            controls["Confidence level (%)"][1].set("95")
            seen["ok"] = dialog.validate()

        seen = self.open(act)
        (ok, banner), field = seen["same"]
        self.assertFalse(ok)
        self.assertEqual(field, "Standard error")
        self.assertEqual(banner, "Standard error: choose a column different from Estimate.")
        (ok, banner), field, page = seen["level"]
        self.assertFalse(ok)
        self.assertEqual((field, page), ("Confidence level (%)", "Model and output"))
        self.assertIn("strictly between 0 and 100", banner)
        self.assertTrue(seen["ok"])

    def test_an_invalid_cell_names_the_field_and_the_row_before_any_calculation(self):
        frame = RATIOS.copy()
        frame.loc[3, "SE"] = 0.0

        def act(dialog, seen):
            for name, column in (("Estimate", "Estimate"), ("Standard error", "SE")):
                dialog.controls[name][1].set(column)
            seen["attempt"] = self.attempt(dialog), self.focused(dialog)

        (ok, banner), field = self.open(act, frame=frame)["attempt"]
        self.assertFalse(ok)
        self.assertEqual(field, "Standard error")
        self.assertEqual(banner, "Standard error: source row 4 must be greater than zero (0).")

    def test_a_saved_random_effects_recipe_reappears_unchanged(self):
        def act(dialog, seen):
            seen["values"] = {name: dialog.controls[name][1].get() for name in dialog.controls}
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, dict(RECIPE))
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], RECIPE)
        self.assertEqual(seen["values"]["Measure"], "Ratio")


class ItalianDialogTests(DialogCase):
    def setUp(self):
        self.use("it")

    def test_captions_choices_and_notes_are_italian_while_the_recipe_stays_canonical(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            seen["models"] = list(dialog.field_rows["Pooling model"][1].cget("values"))
            seen["measures"] = list(dialog.field_rows["Measure"][1].cget("values"))
            dialog.field_rows["Measure"][1].set("Rapporto")
            dialog.update()
            seen["note"] = dialog.meta_unit_note.cget("text")
            seen["se"] = dialog.field_rows["Standard error"][0].cget("text")
            dialog.controls["Standard error"][1].set("Estimate")
            seen["banner"] = self.attempt(dialog)[1]
            dialog.controls["Standard error"][1].set("SE")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE"})
        self.assertEqual(seen["tabs"], ["Studi", "Modello e risultati"])
        self.assertEqual(seen["captions"]["Pooling model"], "Modello di sintesi")
        self.assertEqual(seen["captions"]["Leave one out"], "Omissione di uno studio alla volta")
        self.assertEqual(seen["models"], ["Effetto comune", "Effetti casuali (Paule–Mandel)"])
        self.assertEqual(seen["measures"], ["Differenza", "Rapporto"])
        self.assertEqual(seen["se"], "ES di ln(rapporto)")
        self.assertIn("LOGARITMO NATURALE", seen["note"])
        self.assertEqual(seen["banner"], "Errore standard: scegli una colonna diversa da Stima.")
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"]["Measure"], "Ratio")
        self.assertEqual(seen["recipe"]["Pooling model"], meta.COMMON)


class AppTests(TkCase):
    """A worksheet edit or Cancel keeps the confirmed result; the Graphs entry follows Show graph."""

    def setUp(self):
        import tramastat
        self.use("en")
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
        self.frame = RATIOS.copy()
        self.app._add_tables({"Ratios": self.frame})
        self.run = tramastat.Run(METHOD, "Ratios", dict(RECIPE))
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
                seen.append((dialog.initial_field, dialog.fields.tab(dialog.fields.select(), "text"),
                             dialog.error_label.cget("text") if dialog.error_label is not None else ""))
                dialog.result = None
                dialog.cancel()
            elif time.monotonic() < deadline:
                self.root.after(15, close)

        self.root.after(15, close)
        return seen

    def test_an_invalid_edit_reopens_the_field_and_keeps_the_result(self):
        previous = self.run.result
        self.app.show("data", "Ratios")
        seen = self.cancel_reopened_dialog()
        column = self.app.tables["Ratios"].raw.columns.get_loc("SE")
        self.app.edit_cell(1, column, "0")
        self.wait()
        self.assertTrue(seen, "the real recovery dialog must reopen")
        field, page, banner = seen[0]
        self.assertEqual((field, page), ("Standard error", "Studies"))
        self.assertIn("source row 2 must be greater than zero", banner)
        self.assertIs(self.run.result, previous)
        self.assertIn("source row 2", self.run.calculation_error)
        self.app.show("result", 0)
        self.assertIn("source row 2", self.app.stale_calculation_note())
        self.app.show("data", "Ratios")
        self.app.edit_cell(1, column, "0.27")
        self.wait()
        self.assertIsNot(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)

    def test_an_excluded_cell_is_omitted_and_counted(self):
        self.app.show("data", "Ratios")
        column = self.app.tables["Ratios"].raw.columns.get_loc("Estimate")
        self.app.current_grid.select((2, column))
        self.app.toggle_exclusion()
        self.wait()
        row = self.run.result.tables["Pooled"].iloc[0]
        self.assertEqual((row["Studies"], row["Omitted studies"]), (4, 1))
        self.assertEqual(list(self.run.result.tables["Studies"]["Source row"]), [1, 2, 4, 5])

    def test_only_leave_one_out_offers_cancel_and_cancel_keeps_the_last_result(self):
        self.assertTrue(self.module.cancellable_run(METHOD, RECIPE))
        self.assertFalse(self.module.cancellable_run(METHOD, {**RECIPE, "Leave one out": False}))
        previous = self.run.result
        self.app.recalculate(0)
        self.assertIsNotNone(self.app.calculation)
        self.app.calculation.cancel.set()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIs(self.app.runs[0].result, previous)
        self.assertEqual(self.app.status.get(), f"{METHOD} cancelled. The last completed results are kept.")

    def test_cancel_after_an_edit_asks_to_open_the_analysis_again(self):
        self.app.show("data", "Ratios")
        self.app.edit_cell(0, self.app.tables["Ratios"].raw.columns.get_loc("Estimate"), "0.8")
        self.assertIsNotNone(self.app.calculation)
        self.app.calculation.cancel.set()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.run.result)
        self.assertEqual(self.app.status.get(),
                         f"{METHOD} recalculation cancelled. Open the analysis to calculate again.")

    def test_the_graphs_entry_follows_show_graph(self):
        graphs = dict((name, entries) for name, entries, *_ in self.app.sheet_sections())["Graphs"]
        self.assertEqual(len(graphs), 1)
        self.run.result = None
        self.assertEqual(len(dict((name, entries) for name, entries, *_ in self.app.sheet_sections())["Graphs"]), 1)
        self.run.options["Show graph"] = False
        self.assertEqual(dict((name, entries) for name, entries, *_ in self.app.sheet_sections())["Graphs"], [])


if __name__ == "__main__":
    unittest.main()
