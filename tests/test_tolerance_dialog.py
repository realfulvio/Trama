"""Tolerance intervals on the real dialog: tabs, captions, canonical choices, errors, focus and the two languages."""
import traceback
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n
from analisi.field_error import FieldError
from analisi.tolerance_intervals import (CONFIDENCE, COVERAGE, DISTRIBUTION, GROUP, SHOW_GRAPH, SIDES, TOLERANCE,
                                         VARIABLES, tolerance_intervals)
from tests.test_graph_i18n import TkCase, descendants


def table():
    rng = np.random.default_rng(93)
    return pd.DataFrame({"Signal": rng.normal(50, 4, 36), "Shifted": rng.normal(80, 9, 36),
                         "Lot": ["A", "B", "C"] * 12, "Note": ["x"] * 36})


class ToleranceDialog(TkCase):
    def drive(self, language, steps, data=None):
        """Open the real dialog, run ``steps(dialog, seen)`` once it holds the grab, then close it."""
        from analisi import ui_theme
        from tramastat import AnalysisDialog
        ui_theme.configure(self.root)
        original = i18n.active_language()
        self.addCleanup(i18n.set_language, original)
        i18n.set_language(language)
        seen = {}

        def enter():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            if dialog.grab_current() is not dialog:
                self.root.after(10, enter)
                return
            try:
                dialog.update()
                steps(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                dialog.result = None
                dialog.cancel()
        self.root.deiconify()
        self.root.after(80, enter)
        AnalysisDialog(self.root, table() if data is None else data, only=TOLERANCE)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def pick(dialog, names=("Signal",)):
        box = dialog.controls[VARIABLES][1]
        box.selection_clear(0, "end")
        for index, value in enumerate(box.get(0, "end")):
            if value in names:
                box.selection_set(index)
        dialog.update()

    @staticmethod
    def check(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        return ok, (report.call_args.args[1] if report.call_args else None)

    @staticmethod
    def texts(dialog):
        found = []
        for widget in descendants(dialog):
            try:
                found.append(str(widget.cget("text")))
            except Exception:
                pass
        return found

    def test_tabs_captions_and_the_explanation_in_both_languages(self):
        def steps(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["labels"] = {name: dialog.field_rows[name][0].cget("text")
                              for name in (VARIABLES, GROUP, DISTRIBUTION, SIDES, COVERAGE, CONFIDENCE, SHOW_GRAPH)}
            seen["texts"] = self.texts(dialog)
            seen["distribution"] = list(dialog.field_rows[DISTRIBUTION][1].cget("values"))
            seen["sides"] = list(dialog.field_rows[SIDES][1].cget("values"))
            seen["selected"] = list(dialog.controls[VARIABLES][1].curselection())
        english = self.drive("en", steps)
        self.assertEqual(english["tabs"], ["Data", "Interval"])
        self.assertEqual(english["labels"][COVERAGE], "Population coverage (%)")
        self.assertEqual(english["labels"][CONFIDENCE], "Confidence level (%)")
        self.assertEqual(english["distribution"], ["Normal", "Distribution-free"])
        self.assertEqual(english["sides"], ["Two-sided", "Lower", "Upper"])
        self.assertEqual(english["selected"], [], "nothing is preselected")
        explanation = [text for text in english["texts"] if "confidence interval of the mean" in text]
        self.assertTrue(explanation, "the dialog explains the two percentages")
        italian = self.drive("it", steps)
        self.assertNotEqual(italian["labels"][COVERAGE], english["labels"][COVERAGE])
        self.assertNotEqual(italian["labels"][CONFIDENCE], english["labels"][CONFIDENCE])
        self.assertNotEqual(italian["distribution"], english["distribution"])
        self.assertNotEqual(italian["sides"], english["sides"])
        self.assertTrue([text for text in italian["texts"] if "intervallo di confidenza della media" in text])
        self.assertFalse([text for text in italian["texts"] if "confidence interval of the mean" in text])

    def test_italian_choices_keep_canonical_values(self):
        def steps(dialog, seen):
            self.pick(dialog)
            seen["distribution"] = list(dialog.field_rows[DISTRIBUTION][1].cget("values"))
            seen["sides"] = list(dialog.field_rows[SIDES][1].cget("values"))
            dialog.field_rows[DISTRIBUTION][1].set(seen["distribution"][1])
            dialog.field_rows[SIDES][1].set(seen["sides"][2])
            dialog.update()
            seen["valid"] = self.check(dialog)[0]
            seen["options"] = dict(dialog.result[1])
        seen = self.drive("it", steps)
        self.assertEqual(len(seen["distribution"]), 2)
        self.assertEqual(len(seen["sides"]), 3)
        self.assertTrue(seen["valid"])
        self.assertEqual(seen["options"][DISTRIBUTION], "Distribution-free")
        self.assertEqual(seen["options"][SIDES], "Upper")
        self.assertEqual(seen["options"][VARIABLES], ["Signal"])

    def test_defaults_travel_to_the_options(self):
        def steps(dialog, seen):
            self.pick(dialog, ("Signal", "Shifted"))
            seen["valid"] = self.check(dialog)[0]
            seen["options"] = dict(dialog.result[1])
        seen = self.drive("en", steps)
        self.assertTrue(seen["valid"])
        options = seen["options"]
        self.assertEqual((options[DISTRIBUTION], options[SIDES]), ("Normal", "Two-sided"))
        self.assertEqual((options[COVERAGE], options[CONFIDENCE]), (90.0, 95.0))
        self.assertIs(options[SHOW_GRAPH], False)
        self.assertFalse(options.get(GROUP))

    def test_errors_name_the_field_and_move_the_focus(self):
        def steps(dialog, seen):
            seen["empty"] = self.check(dialog)
            seen["empty_focus"] = dialog.focus_get() is dialog.controls[VARIABLES][1]
            self.pick(dialog)
            dialog.controls[COVERAGE][1].set("100")
            seen["hundred"] = self.check(dialog)
            seen["hundred_focus"] = dialog.focus_get() is dialog.field_rows[COVERAGE][1]
            dialog.controls[COVERAGE][1].set("90")
            dialog.controls[CONFIDENCE][1].set("0")
            seen["zero"] = self.check(dialog)
            seen["zero_focus"] = dialog.focus_get() is dialog.field_rows[CONFIDENCE][1]
            dialog.controls[CONFIDENCE][1].set("97,5")
            seen["comma"] = self.check(dialog)[0]
            seen["level"] = dialog.result[1][CONFIDENCE]
            dialog.controls[GROUP][1].set("Signal")
            seen["group"] = self.check(dialog)
            dialog.controls[GROUP][1].set("")
            self.pick(dialog, ("Note",))
            seen["text"] = self.check(dialog)
        english = self.drive("en", steps)
        self.assertFalse(english["empty"][0])
        self.assertTrue(english["empty_focus"])
        self.assertFalse(english["hundred"][0])
        self.assertIn("Population coverage (%)", english["hundred"][1])
        self.assertTrue(english["hundred_focus"])
        self.assertFalse(english["zero"][0])
        self.assertIn("Confidence level (%)", english["zero"][1])
        self.assertTrue(english["zero_focus"])
        self.assertTrue(english["comma"])
        self.assertEqual(english["level"], 97.5)
        self.assertFalse(english["group"][0])
        self.assertFalse(english["text"][0])
        self.assertIn("Note", english["text"][1])
        italian = self.drive("it", steps)
        self.assertNotIn("Population coverage (%)", italian["hundred"][1])
        self.assertNotIn("Confidence level (%)", italian["zero"][1])
        self.assertTrue(italian["hundred_focus"] and italian["zero_focus"])
        self.assertNotIn("must be a finite number", italian["hundred"][1])
        self.assertIn("Note", italian["text"][1])

    def test_every_engine_message_has_an_italian_translation(self):
        from tramastat import translate_tolerance_error
        frame = table()
        wide = pd.DataFrame({f"c{i}": np.arange(10.0) for i in range(25)})
        many = pd.DataFrame({"x": np.arange(60.0), "g": np.arange(60)})
        pairs = pd.DataFrame({f"c{i}": np.arange(10.0) % 5 for i in range(24)}).assign(g=np.arange(10))
        big = pd.DataFrame({"x": np.zeros(100_001)})
        cases = [
            (frame, {VARIABLES: []}),
            (frame, {VARIABLES: ["Missing"]}),
            (frame, {VARIABLES: ["Signal", "Signal"]}),
            (wide, {VARIABLES: list(wide)}),
            (frame, {VARIABLES: ["Signal"], GROUP: "Missing"}),
            (frame, {VARIABLES: ["Signal"], GROUP: "Signal"}),
            (many, {VARIABLES: ["x"], GROUP: "g"}),
            (pairs, {VARIABLES: [name for name in pairs if name != "g"], GROUP: "g"}),
            (big, {VARIABLES: ["x"]}),
            (frame, {VARIABLES: ["Note"]}),
            (frame.assign(Signal=np.inf), {VARIABLES: ["Signal"]}),
            (frame, {VARIABLES: ["Signal"], COVERAGE: 100}),
            (frame, {VARIABLES: ["Signal"], CONFIDENCE: 0}),
            (frame, {VARIABLES: ["Signal"], DISTRIBUTION: "Gamma"}),
            (frame, {VARIABLES: ["Signal"], SIDES: "Both"}),
        ]
        original = i18n.active_language()
        self.addCleanup(i18n.set_language, original)
        i18n.set_language("it")
        for data, options in cases:
            with self.subTest(options=str(options)[:60]):
                with self.assertRaises(FieldError) as caught:
                    tolerance_intervals(data, options)
                text = translate_tolerance_error(caught.exception)
                self.assertNotEqual(text, str(caught.exception))
                for english in ("must be a finite number", "Select at least", "Choose up to", "must hold finite numbers"):
                    self.assertNotIn(english, text)

    def test_worksheet_names_in_messages_stay_literal(self):
        from tramastat import translate_tolerance_error
        original = i18n.active_language()
        self.addCleanup(i18n.set_language, original)
        i18n.set_language("it")
        with self.assertRaises(FieldError) as caught:
            tolerance_intervals(table(), {VARIABLES: ["Note"]})
        self.assertIn('"Note"', translate_tolerance_error(caught.exception))


if __name__ == "__main__":
    unittest.main()
