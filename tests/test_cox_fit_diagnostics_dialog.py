"""Cox regression dialog: the scaled Schoenfeld and Cox–Snell controls, their visibility, errors and recipe."""
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analisi import cox_fit_diagnostics as diagnostics, cox_outputs as cox, i18n
from analisi.processing import FieldError
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).parent / "data" / "cox-fit-diagnostics"
SCALED, SNELL, AXIS = diagnostics.SCALED, diagnostics.COX_SNELL, diagnostics.X_AXIS


class CoxDialogCase(TkCase):
    def setUp(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog
        self.frame = pd.read_csv(DATA / "followup.csv")
        self.addCleanup(i18n.set_language, i18n.active_language())

    def drive(self, action, *, current=None):
        seen = {}

        def step():
            try:
                dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.AnalysisDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                dialog.update()
                action(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for dialog in [w for w in self.root.winfo_children() if isinstance(w, self.AnalysisDialog)]:
                    dialog.result = None
                    dialog.cancel()

        self.root.deiconify()
        self.root.geometry("1024x768+0+0")
        self.root.after(80, step)
        self.AnalysisDialog(self.root, self.frame, current=(cox.METHOD, current) if current else None, only=cox.METHOD)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def configure(dialog):
        dialog.controls["Time"][1].set("Time")
        dialog.controls["Event"][1].set("Event")
        for label, names in (("Predictors", {"Dose", "Arm"}), ("Categorical predictors", {"Arm"})):
            box = dialog.controls[label][1]
            box.selection_clear(0, "end")
            for index, name in enumerate(box.get(0, "end")):
                if name in names:
                    box.selection_set(index)
            box.event_generate("<<ListboxSelect>>")
        dialog.update()

    @staticmethod
    def shown(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    @staticmethod
    def rejected(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        return ok, report.call_args.args[1] if report.call_args else ""


class FieldTests(CoxDialogCase):
    def test_the_new_controls_sit_on_the_diagnostics_tab_and_default_to_off(self):
        def action(dialog, seen):
            self.configure(dialog)
            tab = str(dialog.field_rows["Cox diagnostics"][1].master)
            seen["same_tab"] = [str(dialog.field_rows[name][1].master) == tab
                                for name in (SCALED, SNELL, cox.GRAPH, cox.GRAPH_TERM, AXIS)]
            seen["defaults"] = [dialog.controls[name][1].get() for name in (SCALED, SNELL)]
            seen["graphs"] = list(dialog.field_rows[cox.GRAPH][1].cget("values"))
            seen["axes"] = list(dialog.field_rows[AXIS][1].cget("values"))
            seen["axis_default"] = dialog.controls[AXIS][1].get()
            seen["hidden"] = [self.shown(dialog, name) for name in (cox.GRAPH_TERM, AXIS)]

        seen = self.drive(action)
        self.assertEqual(seen["same_tab"], [True] * 5)
        self.assertEqual(seen["defaults"], [False, False])
        self.assertEqual(seen["graphs"][-2:], [cox.SCALED_GRAPH, cox.SNELL_GRAPH])
        self.assertEqual(seen["axes"], ["Event time", "Source row"])
        self.assertEqual(seen["axis_default"], "Event time")
        self.assertEqual(seen["hidden"], [False, False])

    def test_the_term_and_the_axis_follow_the_view_that_is_drawn(self):
        def action(dialog, seen):
            self.configure(dialog)
            steps = []

            def record(label):
                dialog.update()
                steps.append((label, self.shown(dialog, cox.GRAPH_TERM), self.shown(dialog, AXIS)))

            dialog.controls[SNELL][1].set(True)
            record("snell automatic")
            dialog.controls[SCALED][1].set(True)
            record("snell+scaled automatic")
            dialog.controls[cox.SCHOENFELD][1].set(True)
            record("raw wins automatic")
            dialog.controls[cox.SCHOENFELD][1].set(False)
            dialog.controls[cox.GRAPH][1].set(cox.SNELL_GRAPH)
            record("snell explicit")
            dialog.controls[cox.GRAPH][1].set(cox.SCALED_GRAPH)
            record("scaled explicit")
            seen["steps"] = steps
            seen["terms"] = list(dialog.field_rows[cox.GRAPH_TERM][1].cget("values"))

        seen = self.drive(action)
        self.assertEqual(seen["steps"], [("snell automatic", False, False), ("snell+scaled automatic", True, True),
                                         ("raw wins automatic", True, False), ("snell explicit", False, False),
                                         ("scaled explicit", True, True)])
        self.assertEqual(seen["terms"], ["Dose", "Arm [B]"])

    def test_the_recipe_keeps_canonical_values_and_the_dummy_term_in_both_languages(self):
        for language in ("en", "it"):
            with self.subTest(language=language):
                i18n.set_language(language)

                def action(dialog, seen):
                    self.configure(dialog)
                    dialog.controls[SCALED][1].set(True)
                    dialog.controls[cox.GRAPH][1].set(cox.SCALED_GRAPH)
                    dialog.controls[cox.GRAPH_TERM][1].set("Arm [B]")
                    dialog.controls[AXIS][1].set("Source row")
                    dialog.update()
                    seen["labels"] = [dialog.field_rows[name][0].cget("text") for name in (SCALED, SNELL, AXIS)]
                    seen["graph_shown"] = dialog.field_rows[cox.GRAPH][1].get()
                    seen["axis_shown"] = dialog.field_rows[AXIS][1].get()
                    seen["ok"] = dialog.validate()
                    seen["recipe"] = dict(dialog.result[1]) if dialog.result else None
                    seen["figure"] = dialog.processing_result.figure.axes[0].get_title()
                    dialog.controls[AXIS][1].set("Event time")
                    dialog.validate()
                    seen["alternate"] = dialog.result[1][AXIS]

                seen = self.drive(action)
                self.assertTrue(seen["ok"])
                recipe = seen["recipe"]
                self.assertEqual((recipe[SCALED], recipe[SNELL], recipe[cox.GRAPH], recipe[cox.GRAPH_TERM], recipe[AXIS]),
                                 (True, False, cox.SCALED_GRAPH, "Arm [B]", "Source row"))
                self.assertEqual(seen["alternate"], "Event time")
                self.assertEqual(seen["figure"], "Scaled Schoenfeld residuals: Arm [B]")
                if language == "it":
                    self.assertEqual(seen["labels"], ["Residui di Schoenfeld scalati", "Diagnostica Cox–Snell",
                                                      "Asse X di Schoenfeld"])
                    self.assertEqual((seen["graph_shown"], seen["axis_shown"]), ("Schoenfeld scalati", "Riga di origine"))
                else:
                    self.assertEqual(seen["labels"], [SCALED, SNELL, AXIS])
                    self.assertEqual((seen["graph_shown"], seen["axis_shown"]), (cox.SCALED_GRAPH, "Source row"))

    def test_a_saved_recipe_reopens_with_its_view_term_and_axis(self):
        saved = {"Time": "Time", "Event": "Event", "Predictors": ["Dose", "Arm"], "Categorical predictors": ["Arm"],
                 "Ties": "Breslow", SCALED: True, SNELL: True, cox.GRAPH: cox.SCALED_GRAPH,
                 cox.GRAPH_TERM: "Arm [B]", AXIS: "Source row"}

        def action(dialog, seen):
            seen["values"] = [dialog.controls[name][1].get() for name in (SCALED, SNELL, cox.GRAPH, cox.GRAPH_TERM, AXIS)]
            seen["shown"] = [self.shown(dialog, cox.GRAPH_TERM), self.shown(dialog, AXIS)]

        seen = self.drive(action, current=saved)
        self.assertEqual(seen["values"], [True, True, cox.SCALED_GRAPH, "Arm [B]", "Source row"])
        self.assertEqual(seen["shown"], [True, True])


class ErrorTests(CoxDialogCase):
    def test_a_view_chosen_before_its_checkbox_names_graph_display_and_keeps_the_dialog_open(self):
        def action(dialog, seen):
            self.configure(dialog)
            dialog.controls[cox.GRAPH][1].set(cox.SCALED_GRAPH)
            seen["ok"], seen["message"] = self.rejected(dialog)
            seen["tab"] = dialog.fields.select() == str(dialog.field_rows[cox.GRAPH][1].master)
            seen["visible"] = dialog.field_rows[cox.GRAPH][1].winfo_viewable()
            dialog.controls[SCALED][1].set(True)
            seen["fixed"] = dialog.validate()

        seen = self.drive(action)
        self.assertFalse(seen["ok"])
        self.assertIn("Turn on Scaled Schoenfeld residuals to display scaled schoenfeld", seen["message"])
        self.assertTrue(seen["tab"] and seen["visible"])
        self.assertTrue(seen["fixed"])

    def test_the_italian_message_names_the_control_in_italian(self):
        i18n.set_language("it")

        def action(dialog, seen):
            self.configure(dialog)
            dialog.controls[cox.GRAPH][1].set(cox.SNELL_GRAPH)
            seen["ok"], seen["message"] = self.rejected(dialog)

        seen = self.drive(action)
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["message"], f"{i18n.ui(cox.GRAPH)}: Attiva Diagnostica Cox–Snell per mostrare "
                                          "grafico cox–snell.")
        self.assertNotEqual(i18n.ui(cox.GRAPH), cox.GRAPH)

    def test_an_error_on_a_field_of_a_view_not_yet_shown_shows_it_and_focuses_it(self):
        """Whatever field the engine names, the dialog reveals it and moves the keyboard there."""
        for field, view in ((cox.GRAPH_TERM, cox.SCALED_GRAPH), (AXIS, cox.SCALED_GRAPH), (SCALED, cox.AUTOMATIC),
                            (SNELL, cox.AUTOMATIC)):
            with self.subTest(field=field):
                def action(dialog, seen):
                    self.configure(dialog)
                    dialog.controls[SCALED][1].set(True)
                    dialog.controls[SNELL][1].set(True)
                    dialog.controls[cox.GRAPH][1].set(view)
                    dialog.update()
                    with patch("tramastat.analyse", side_effect=FieldError(field, "A problem with the data.")):
                        seen["ok"], seen["message"] = self.rejected(dialog)
                    dialog.update()
                    widget = dialog.field_rows[field][1]
                    seen["tab"] = dialog.fields.select() == str(widget.master)
                    seen["visible"] = bool(widget.winfo_viewable())

                seen = self.drive(action)
                self.assertFalse(seen["ok"])
                self.assertTrue(seen["message"].startswith(f"{field}: "), seen["message"])
                self.assertTrue(seen["tab"] and seen["visible"], seen)


if __name__ == "__main__":
    unittest.main()
