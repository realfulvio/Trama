"""The real Analyze dialog for Competing risks: pages, editors, hidden fields, EN/IT messages and recovery."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import competing_risks as engine
from analisi import competing_risks_workbench as cr
from analisi import i18n
from analisi.competing_risks_dialog import (CodeListEditor, TimeListEditor, caption, describe_error, number,
                                            read_time, show_time, translate_error)
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate_message
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "competing_risks"
METHOD = cr.COMPETING_RISKS
COHORTS = pd.read_csv(DATA / "cohorts.csv")
RECIPE = {"Time": "Time", "Status": "Status", "Group": "Group", "Censor code": "0", "Event codes": ["1", "2"],
          "Times": [], "Confidence level (%)": 95.0, "Gray tests": "Off", "Graph": "Selected cause",
          "Graph cause": "", "Display": "Fraction", "Show confidence bands": False}

SAMPLES = {"field": "Event codes", "role": "Time", "first": "Status", "name": "Day", "text": "'x'", "value": "3",
           "row": "4", "limit": "100,000", "count": "100,001", "rows": "250,000", "work": "31,000,000",
           "position": "2", "shown": "abc", "cause": "'9'"}
CAPTIONS_IT = {"field": "Codici dell’evento", "role": "Tempo", "first": "Stato"}
GROUPED_IT = {"limit": "100.000", "count": "100.001", "rows": "250.000", "work": "31.000.000"}


def base_frame():
    return pd.DataFrame({"t": [1., 2, 3, 4, 5, 6], "s": [1, 2, 0, 1, 2, 0], "g": list("AABBAB")})


def options(**changes):
    return {"Time": "t", "Status": "s", "Group": "g", "Censor code": "0", "Event codes": ["1", "2"], **changes}


def triggers():
    """(call, field) for every message the engine and the workbench can raise before any curve is calculated."""
    base, rng = base_frame(), np.random.default_rng(3)
    big = 100_000
    wide = pd.DataFrame({"t": rng.random(big), "s": rng.integers(0, 4, big), "g": rng.integers(0, 12, big)})
    pairs = wide.assign(s=rng.integers(0, 3, big))
    long = pd.DataFrame({"t": rng.random(50_000), "s": rng.integers(0, 6, 50_000), "g": rng.integers(0, 5, 50_000)})
    duplicated = base.copy()
    duplicated.columns = ["t", "t", "g"]

    def check(frame, **changes):
        return lambda: cr.check_options(frame, options(**changes))

    def check_changes(frame, changes):
        return lambda: cr.check_options(frame, options(**changes))

    def budget(frame, events, pairwise):
        return lambda: engine.check_gray_budget(engine.prepare(frame, "t", "s", "g", "0", events), pairwise)

    yield check(base, Time=None), "Time"
    yield check(base, Time="nope"), "Time"
    yield check(duplicated), "Time"
    yield check_changes(base, {"Event codes": [1, 2]}), "Event codes"
    yield check_changes(base, {"Event codes": ["", "2"]}), "Event codes"
    yield check_changes(base, {"Event codes": ["1.5"]}), "Event codes"
    yield check_changes(base, {"Event codes": ["99999999999999999999"]}), "Event codes"
    yield check(base.assign(s=[True, False] * 3)), "Status"
    yield check(base.assign(s=pd.Series([(1, 2)] * 6, dtype=object))), "Status"
    yield check(base.assign(s=[1, "a", 1, "a", 1, "a"])), "Status"
    yield check(pd.DataFrame({"t": np.zeros(big + 1), "s": np.zeros(big + 1, dtype=int)}), Group=None), "Time"
    yield check(base, Status="t"), "Status"
    yield check_changes(base, {"Event codes": []}), "Event codes"
    yield check_changes(base, {"Censor code": None}), "Censor code"
    yield check(base.assign(t=np.nan)), "Time"
    yield check(base.assign(t=[True, False] * 3)), "Time"
    yield check(base.assign(t=[-1., 2, 3, 4, 5, 6])), "Time"
    yield check(base.assign(t=[2**53 + 1, 2, 3, 4, 5, 6])), "Time"
    yield check_changes(base, {"Event codes": ["0"]}), "Censor code"
    yield check_changes(base, {"Event codes": ["1", "1"]}), "Event codes"
    yield check(base.assign(s=[9, 1, 2, 0, 1, 2])), "Status"
    yield check(base.assign(g=pd.Series([1, "1", 1, "1", 1, "1"], dtype=object))), "Group"
    yield check(pd.DataFrame({"t": np.arange(13.), "s": [0, 1] * 6 + [1], "g": np.arange(13)})), "Group"
    yield check_changes(base, {"Show confidence bands": "yes"}), "Show confidence bands"
    yield check_changes(base, {"Confidence level (%)": 100}), "Confidence level (%)"
    yield check_changes(base, {"Gray tests": "Maybe"}), "Gray tests"
    yield check(base, Times="5"), "Times"
    yield check(base, Times=list(range(201))), "Times"
    yield check(base, Times=[1, -2]), "Times"
    yield check_changes(base, {"Graph cause": "9"}), "Graph cause"
    yield check_changes(long, {"Event codes": list("12345")}), "Time"
    # The Gray budget is reached through check_options only after the curve budget, which is always tighter for a
    # worksheet of the allowed size; the engine check is called directly.
    yield budget(wide, ["1", "2", "3"], False), "Group"
    yield budget(pairs, ["1", "2"], True), "Gray tests"


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("cr.")]
        self.assertGreaterEqual(len(keys), 60)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key, english in CATALOGS["en"].items():
            if not key.startswith("cr.error."):
                continue
            message = english
            expected = CATALOGS["it"][key]
            for name in placeholders(english):
                message = message.replace("{%s}" % name, SAMPLES[name])
                expected = expected.replace("{%s}" % name, (CAPTIONS_IT | GROUPED_IT).get(name, SAMPLES[name]))
            self.assertEqual(translate_error(message), expected, key)

    def test_english_messages_stay_as_written(self):
        for key, english in CATALOGS["en"].items():
            if key.startswith("cr.error."):
                message = english.format(**SAMPLES) if "{" in english else english
                self.assertEqual(translate_error(message), message, key)

    def test_a_message_of_the_engine_names_a_template_and_changes_in_italian(self):
        self.use("it")
        seen = set()
        for call, field in triggers():
            with self.assertRaises(FieldError) as raised:
                call()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            self.assertNotEqual(translate_error(error), str(error), str(error))
            keys = [key for key, pattern in i18n._message_patterns("cr.error.") if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            seen.add(keys[0])
        # Only the defensive messages that no worksheet can reach are left out of the triggers.
        unreachable = {"cr.error.status_not_allowed", "cr.error.gray_causes", "cr.error.gray_times"}
        every = {key for key in CATALOGS["en"] if key.startswith("cr.error.")}
        self.assertEqual(every - seen, unreachable)

    def test_italian_counts_use_dots_and_worksheet_text_stays_literal(self):
        self.use("it")
        self.assertEqual(number("100,000"), "100.000")
        self.assertEqual(number("7"), "7")
        self.assertEqual(translate_error('Choose an existing column for Time: "{Misura} & $x$" is not in the worksheet.'),
                         'Scegli una colonna esistente per Tempo: "{Misura} & $x$" non è nel foglio.')

    def test_the_shared_level_messages_come_from_the_common_catalog(self):
        self.use("it")
        self.assertEqual(translate_error("Confidence level (%) must be a number."),
                         "Il livello di confidenza (%) deve essere un numero.")
        self.assertEqual(describe_error(ValueError("Confidence level (%) must be a number."), "Confidence level (%)"),
                         "Il livello di confidenza (%) deve essere un numero.")

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.assertEqual(describe_error(FieldError("Time", 'Column "x" must be numeric.')),
                         'Time: Column "x" must be numeric.')
        self.assertEqual(describe_error(FieldError("Event codes", "Event codes: a code cannot be empty.")),
                         "Event codes: a code cannot be empty.")
        self.use("it")
        self.assertEqual(describe_error(FieldError("Event codes", "Event codes: a code cannot be empty.")),
                         "Codici dell’evento: un codice non può essere vuoto.")
        self.assertEqual(caption("Gray tests"), "Test di Gray")
        self.assertEqual(caption("Unlisted"), "Unlisted")

    def test_time_text_round_trips_without_losing_digits(self):
        self.assertEqual([show_time(value) for value in (1.0, 2.5, 1e20, 0.1 + 0.2, "x", None, True)],
                         ["1", "2.5", repr(1e20), repr(0.1 + 0.2), "x", "", "True"])
        self.assertEqual([read_time(text) for text in ("3", " 2,5 ", "1e3", "abc", "")], [3.0, 2.5, 1000.0, "abc", ""])


class DialogCase(TkCase):
    frame = COHORTS

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
        AnalysisDialog(self.root, (self.frame if frame is None else frame).copy(),
                       current=(METHOD, recipe) if recipe else None, only=METHOD)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def type_into(editor, text):
        editor.text.delete("1.0", "end")
        editor.text.insert("1.0", text)

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None


class EnglishDialogTests(DialogCase):
    def test_pages_defaults_and_the_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in controls}
            self.assertEqual((controls["Time"][1].get(), controls["Status"][1].get(), controls["Group"][1].get()),
                             ("Time", "Status", ""))
            self.assertIsInstance(controls["Event codes"][1], CodeListEditor)
            self.assertIsInstance(controls["Times"][1], TimeListEditor)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Data", "Estimates", "Graph"])
        self.assertEqual(list(seen["captions"].values()),
                         ["Time", "Status", "Group", "Censor code", "Event codes", "Times", "Confidence level (%)",
                          "Gray tests", "Graph", "Graph cause", "Display", "Show confidence bands"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {**RECIPE, "Group": None})

    def test_the_codes_and_the_times_keep_what_is_typed(self):
        def act(dialog, seen):
            self.type_into(dialog.controls["Event codes"][1], " 1 \n\n2 ")
            self.type_into(dialog.controls["Times"][1], "1,5\n\n  2\nabc\n")
            dialog.controls["Censor code"][1].set(" 0")
            seen["parsed"] = dialog.controls["Event codes"][1].values(), dialog.controls["Times"][1].values()
            seen["ok"], seen["message"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertEqual(seen["parsed"], ([" 1 ", "", "2 "], [1.5, 2.0, "abc"]))
        self.assertFalse(seen["ok"])
        self.assertIn("Times", seen["message"])
        self.assertIn("abc", seen["message"])

    def test_a_blank_line_between_codes_is_an_empty_code_that_names_its_field(self):
        def act(dialog, seen):
            self.type_into(dialog.controls["Event codes"][1], "1\n\n2")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")
            seen["focus"] = dialog.initial_focus is dialog.controls["Event codes"][1].focus_target()

        seen = self.open(act)
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["message"], "Event codes: a code cannot be empty.")
        self.assertEqual(seen["page"], "Data")
        self.assertTrue(seen["focus"])

    def test_a_repeated_code_and_a_censor_code_that_is_also_an_event_move_the_focus(self):
        def act(dialog, seen):
            self.type_into(dialog.controls["Event codes"][1], "1\n1")
            seen["first"] = self.attempt(dialog)
            seen["first_focus"] = dialog.initial_focus is dialog.controls["Event codes"][1].focus_target()
            self.type_into(dialog.controls["Event codes"][1], "1\n0")
            seen["second"] = self.attempt(dialog)
            seen["second_focus"] = dialog.initial_focus is dialog.field_rows["Censor code"][1]

        seen = self.open(act)
        self.assertEqual(seen["first"], (False, "Event codes: '1' repeats an earlier code "
                                                 "(the same status written twice)."))
        self.assertEqual(seen["second"], (False, "Censor code and event code '0' are the same status. "
                                                  "Use different codes."))
        self.assertTrue(seen["first_focus"] and seen["second_focus"])

    def test_a_bad_time_selects_the_estimates_page(self):
        def act(dialog, seen):
            self.type_into(dialog.controls["Times"][1], "-3")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")
            dialog.controls["Times"][1].set_lines([])
            dialog.controls["Confidence level (%)"][1].set("101")
            seen["level"] = self.attempt(dialog)
            dialog.controls["Confidence level (%)"][1].set("9,5e1")
            seen["comma"] = dialog.validate()
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["message"], "Times: value 1 (-3) must be a finite number of 0 or more.")
        self.assertEqual(seen["page"], "Estimates")
        self.assertEqual(seen["level"], (False, "Confidence level (%) must be a number greater than 0 and less than 100."))
        self.assertTrue(seen["comma"])
        self.assertEqual(seen["recipe"]["Confidence level (%)"], 95.0)

    def test_the_drawn_cause_follows_the_typed_codes_and_never_rewrites_a_saved_value(self):
        frame = pd.DataFrame({"Time": [1., 2, 3, 4, 5, 6], "Status": [0, 7, 9, 7, 9, 0], "Group": list("ABABAB")})

        def act(dialog, seen):
            editor, binding = dialog.controls["Event codes"][1], dialog.choice_bindings["Graph cause"]
            seen["initial"] = binding.combobox.cget("values")
            self.type_into(editor, "7\n\n8 \n7\n9")
            dialog.update()
            seen["typed"] = binding.combobox.cget("values")
            dialog.controls["Graph cause"][1].set("8 ")
            self.type_into(editor, "7\n9")
            dialog.update()
            seen["kept"] = dialog.controls["Graph cause"][1].get(), binding.combobox.get()
            seen["ok"], seen["message"] = self.attempt(dialog)

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["initial"], ("First cause", "1", "2"))
        self.assertEqual(seen["typed"], ("First cause", "7", "8 ", "9"))
        self.assertEqual(seen["kept"], ("8 ", "8 "))
        self.assertEqual((seen["ok"], seen["message"]), (False, "Graph cause: '8 ' is not one of the event codes."))

    def test_all_causes_hides_the_drawn_cause_and_it_is_neither_checked_nor_saved(self):
        def act(dialog, seen):
            dialog.controls["Graph cause"][1].set("nonsense")
            dialog.controls["Graph"][1].set("All causes")
            dialog.update()
            seen["hidden"] = not dialog.field_rows["Graph cause"][1].winfo_manager()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]
            dialog.controls["Graph"][1].set("Selected cause")
            dialog.update()
            seen["shown"] = bool(dialog.field_rows["Graph cause"][1].winfo_manager())

        seen = self.open(act)
        self.assertTrue(seen["hidden"] and seen["shown"] and seen["ok"])
        self.assertNotIn("Graph cause", seen["recipe"])
        self.assertEqual(seen["recipe"]["Graph"], "All causes")

    def test_a_saved_recipe_reappears_unchanged(self):
        recipe = {**RECIPE, "Event codes": ["2", "1"], "Times": [1.0, 2.5, 3.0], "Confidence level (%)": 90.0,
                  "Gray tests": "Omnibus and pairwise", "Graph cause": "1", "Display": "Percent",
                  "Show confidence bands": True, "Censor code": " 0"}
        frame = pd.DataFrame({"Time": [1., 2, 3, 4, 5, 6], "Status": [" 0", "1", "2", " 0", "1", "2"],
                              "Group": list("ABABAB")})

        def act(dialog, seen):
            seen["lines"] = (dialog.controls["Event codes"][1].raw_lines(), dialog.controls["Times"][1].raw_lines())
            seen["censor"] = dialog.controls["Censor code"][1].get()
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe, frame)
        self.assertEqual(seen["lines"], (["2", "1"], ["1", "2.5", "3"]))
        self.assertEqual(seen["censor"], " 0")
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"], recipe)


class ItalianDialogTests(DialogCase):
    def test_captions_choices_and_hints_are_italian_while_the_recipe_stays_canonical(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            gray = dialog.choice_bindings["Gray tests"]
            seen["gray"] = gray.combobox.cget("values"), gray.combobox.get()
            gray.display.set("Globale e a coppie")
            seen["canonical"] = dialog.controls["Gray tests"][1].get()
            seen["cause"] = dialog.choice_bindings["Graph cause"].combobox.cget("values")
            seen["hints"] = [child.cget("text") for name in ("Event codes", "Times")
                             for child in dialog.field_rows[name][1].winfo_children()
                             if child.winfo_class() == "TLabel"]
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Dati", "Stime", "Grafico"])
        self.assertEqual(seen["captions"], ["Tempo", "Stato", "Gruppo", "Codice di censura", "Codici dell’evento",
                                            "Tempi richiesti", "Livello di confidenza (%)", "Test di Gray", "Grafico",
                                            "Causa nel grafico", "Visualizzazione", "Mostra le bande di confidenza"])
        self.assertEqual(seen["gray"], (("Disattivati", "Globale (omnibus)", "Globale e a coppie"), "Disattivati"))
        self.assertEqual(seen["canonical"], "Omnibus and pairwise")
        self.assertEqual(seen["cause"], ("Prima causa", "1", "2"))
        self.assertTrue(all(text.startswith(("Un codice", "Facoltativo")) for text in seen["hints"]))
        self.assertEqual(len(seen["hints"]), 2)
        self.assertEqual(seen["recipe"]["Gray tests"], "Omnibus and pairwise")
        self.assertEqual(seen["recipe"]["Graph"], "Selected cause")
        self.assertEqual(seen["recipe"]["Graph cause"], "")

    def test_the_hints_wrap_inside_the_room_the_longer_italian_captions_leave(self):
        self.use("it")

        def act(dialog, seen):
            seen["fit"] = {}
            for tab, name in ((0, "Event codes"), (1, "Times")):
                dialog.fields.select(tab)
                dialog.update()
                editor = dialog.field_rows[name][1]
                seen["fit"][name] = (editor.hint.winfo_width(), editor.winfo_width(), editor.hint.winfo_reqwidth())

        seen = self.open(act)
        for name, (hint, editor, requested) in seen["fit"].items():
            self.assertGreater(editor, 100, name)
            self.assertLessEqual(hint, editor, name)
            self.assertLessEqual(requested, editor + 6, name)

    def test_the_banner_is_italian_names_the_field_and_keeps_worksheet_text_literal(self):
        self.use("it")

        def act(dialog, seen):
            self.type_into(dialog.controls["Event codes"][1], "1\n1")
            seen["repeat"] = self.attempt(dialog)
            self.type_into(dialog.controls["Event codes"][1], "1\n2")
            dialog.controls["Time"][1].set("Group")
            seen["numeric"] = self.attempt(dialog)
            dialog.controls["Time"][1].set("Time")
            dialog.controls["Status"][1].set("Time")
            seen["different"] = self.attempt(dialog)
            dialog.controls["Status"][1].set("Status")
            dialog.controls["Confidence level (%)"][1].set("abc")
            seen["level"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertEqual(seen["repeat"], (False, "Codici dell’evento: '1' ripete un codice precedente "
                                                 "(lo stesso stato scritto due volte)."))
        self.assertEqual(seen["numeric"], (False, 'Tempo: La colonna "Group" deve essere numerica.'))
        self.assertEqual(seen["different"], (False, "Scegli colonne diverse per Tempo e Stato."))
        self.assertEqual(seen["level"], (False, "Il livello di confidenza (%) deve essere un numero."))

    def test_italian_reopens_a_recipe_written_in_english(self):
        self.use("it")
        recipe = {**RECIPE, "Gray tests": "Omnibus", "Display": "Percent"}

        def act(dialog, seen):
            seen["shown"] = (dialog.choice_bindings["Gray tests"].combobox.get(),
                             dialog.choice_bindings["Display"].combobox.get())
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe)
        self.assertEqual(seen["shown"], ("Globale (omnibus)", "Percentuale"))
        self.assertEqual(seen["recipe"], recipe)


class RecoveryTests(TkCase):
    """A worksheet edit or a candidate that fails keeps the confirmed result, flags it stale and reopens the field."""

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
                seen.append((dialog.initial_focus, dialog.fields.tab(dialog.fields.select(), "text"),
                             dialog.controls["Event codes"][1].focus_target()))
                dialog.result = None
                dialog.cancel()
            elif time.monotonic() < deadline:
                self.root.after(15, close)

        self.root.after(15, close)
        return seen

    def test_an_unknown_status_is_flagged_and_recoverable(self):
        previous = self.run.result
        self.assertEqual(self.run.options["Event codes"], ["1", "2"])
        self.app.show("data", "Cohorts")
        seen = self.cancel_reopened_dialog()
        status = self.app.tables["Cohorts"].raw.columns.get_loc("Status")
        self.app.edit_cell(0, status, "7")
        self.wait()
        self.assertTrue(seen, "The real recovery dialog must reopen")
        focus, page, editor = seen[0]
        self.assertEqual(page, "Data")
        self.assertIsNotNone(focus)
        self.assertIs(self.run.result, previous)
        self.assertIn("neither the censor code nor one of the event codes", self.run.calculation_error)
        self.app.show("result", 0)
        self.assertIn("neither", self.app.stale_calculation_note())
        self.app.show("data", "Cohorts")
        self.app.edit_cell(0, status, "2")
        self.wait()
        self.assertIsNot(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)
        self.assertIsNone(self.app.stale_calculation_note(("result", 0)))

    def test_the_stale_note_is_translated_with_the_active_language(self):
        self.use("it")
        self.run.calculation_error = "Source row 5: status 7 is neither the censor code nor one of the event codes."
        self.app.show("result", 0)
        note = self.app.stale_calculation_note()
        self.assertIn("Riga origine 5: lo stato 7 non è né il codice di censura", note)

    def test_a_failing_candidate_does_not_mark_the_confirmed_result_stale(self):
        previous = self.run.result
        candidate = self.module.Run(METHOD, "Cohorts", {**RECIPE, "Event codes": ["1", "1"]})
        seen = self.cancel_reopened_dialog()
        recovery = self.app.weighting_recovery(METHOD, candidate.options, 0)
        self.assertIsNotNone(recovery)
        self.app.start_analysis(candidate, self.frame, 0, recovery=recovery)
        self.wait()
        self.assertTrue(seen)
        self.assertIs(self.app.runs[0], self.run)
        self.assertIs(self.run.result, previous)
        self.assertIsNone(self.run.calculation_error)
        self.assertEqual(seen[0][1], "Data")
        self.assertEqual(self.app.status.get(), "Change discarded. The confirmed analysis is kept.")

    def test_only_a_gray_run_offers_cancel(self):
        self.assertFalse(self.module.cancellable_run(METHOD, RECIPE))
        for choice in ("Omnibus", "Omnibus and pairwise"):
            self.assertTrue(self.module.cancellable_run(METHOD, {**RECIPE, "Gray tests": choice}))
        self.assertFalse(self.module.cancellable_run("Kaplan–Meier survival", {"Gray tests": "Omnibus"}))

    def test_cancel_stops_a_gray_run_and_keeps_the_last_result(self):
        self.run.options["Gray tests"] = "Omnibus"
        previous = self.run.result
        self.app.recalculate(0)
        self.assertIsNotNone(self.app.calculation)
        self.app.calculation.cancel.set()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIs(self.app.runs[0].result, previous)
        self.assertEqual(self.app.status.get(), f"{METHOD} cancelled. The last completed results are kept.")

    def test_cancel_during_a_recalculation_after_an_edit_asks_to_open_the_analysis_again(self):
        self.run.options["Gray tests"] = "Omnibus"
        self.app.show("data", "Cohorts")
        self.app.edit_cell(0, self.app.tables["Cohorts"].raw.columns.get_loc("Time"), "9")
        self.assertIsNotNone(self.app.calculation)
        self.app.calculation.cancel.set()
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.run.result)
        self.assertEqual(self.app.status.get(),
                         f"{METHOD} recalculation cancelled. Open the analysis to calculate again.")


if __name__ == "__main__":
    unittest.main()
