"""Principal component regression on the real PCA dialog: tab, field states, errors, focus and languages."""
import traceback
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n, pca_regression
from analisi.field_error import FieldError
from analisi.workbench import analyse
from tests.test_graph_i18n import TkCase

METHOD = "Principal component analysis"
ENABLE, RESPONSE, CONFIDENCE, PLOT = (pca_regression.ENABLE, pca_regression.RESPONSE,
                                     pca_regression.CONFIDENCE, pca_regression.PLOT)


def table():
    rng = np.random.default_rng(87)
    base = rng.normal(size=14)
    frame = pd.DataFrame({
        "Conductivity": base + rng.normal(scale=.3, size=14),
        "Temperature": 2 * base + rng.normal(scale=.3, size=14),
        "Response": 3 + base + rng.normal(scale=.2, size=14)})
    frame.loc[3, "Response"] = np.nan
    return frame


class RegressionDialog(TkCase):
    def drive(self, language, steps, only=METHOD, data=None):
        """Open the real dialog, run `steps(dialog, seen)` once it holds the grab, then close it."""
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
        AnalysisDialog(self.root, table() if data is None else data, only=only)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def pick(dialog, names=("Conductivity", "Temperature")):
        box = dialog.controls["Variables"][1]
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

    def test_regression_tab_is_added_and_off_by_default(self):
        def steps(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["labels"] = {name: dialog.field_rows[name][0].cget("text")
                              for name in (ENABLE, RESPONSE, CONFIDENCE, PLOT)}
            seen["states"] = {name: str(dialog.field_rows[name][1].cget("state"))
                              for name in (RESPONSE, CONFIDENCE, PLOT)}
            self.pick(dialog)
            seen["valid"] = self.check(dialog)[0]
            seen["options"] = dict(dialog.result[1])
        english = self.drive("en", steps)
        self.assertIn("Regression", english["tabs"])
        self.assertEqual(english["labels"], {ENABLE: "Principal component regression", RESPONSE: "PCR response",
                                             CONFIDENCE: "PCR confidence (%)", PLOT: "PCR plot"})
        self.assertEqual(set(english["states"].values()), {"disabled"})
        self.assertTrue(english["valid"])
        self.assertIs(english["options"][ENABLE], False)
        italian = self.drive("it", steps)
        self.assertIn("Regressione", italian["tabs"])
        self.assertEqual(italian["labels"], {ENABLE: "Regressione sulle componenti principali",
                                             RESPONSE: "Risposta PCR", CONFIDENCE: "Confidenza PCR (%)",
                                             PLOT: "Grafico PCR"})
        self.assertIs(italian["options"][ENABLE], False)

    def test_italian_plot_labels_keep_canonical_values(self):
        def steps(dialog, seen):
            self.pick(dialog)
            dialog.controls[ENABLE][1].set(True)
            dialog.update()
            seen["states"] = {name: str(dialog.field_rows[name][1].cget("state"))
                              for name in (RESPONSE, CONFIDENCE, PLOT)}
            seen["choices"] = list(dialog.field_rows[PLOT][1].cget("values"))
            dialog.controls[RESPONSE][1].set("Response")
            dialog.field_rows[PLOT][1].set("Residui rispetto agli stimati")
            dialog.update()
            seen["valid"] = self.check(dialog)[0]
            seen["options"] = dict(dialog.result[1])
        seen = self.drive("it", steps)
        self.assertEqual(seen["states"], {RESPONSE: "readonly", CONFIDENCE: "normal", PLOT: "readonly"})
        self.assertEqual(seen["choices"], ["Mantieni grafico PCA", "Osservati rispetto agli stimati",
                                           "Residui rispetto agli stimati"])
        self.assertTrue(seen["valid"])
        self.assertEqual(seen["options"][PLOT], "Residuals vs fitted")
        self.assertEqual(seen["options"][RESPONSE], "Response")
        self.assertEqual(seen["options"][CONFIDENCE], 95.0)

    def test_errors_name_the_field_and_move_the_focus(self):
        def steps(dialog, seen):
            self.pick(dialog)
            dialog.controls[ENABLE][1].set(True)
            dialog.update()
            seen["empty"] = self.check(dialog)
            seen["empty_field"] = dialog.focus_get() is dialog.field_rows[RESPONSE][1]
            dialog.controls[RESPONSE][1].set("Response")
            dialog.controls[CONFIDENCE][1].set("100")
            seen["hundred"] = self.check(dialog)
            seen["hundred_field"] = dialog.focus_get() is dialog.field_rows[CONFIDENCE][1]
            dialog.controls[CONFIDENCE][1].set("90,5")
            seen["comma"] = self.check(dialog)[0]
            seen["level"] = dialog.result[1][CONFIDENCE]
            dialog.controls[RESPONSE][1].set("Temperature")
            seen["among"] = self.check(dialog)
        english = self.drive("en", steps)
        self.assertFalse(english["empty"][0])
        self.assertIn("PCR response", english["empty"][1])
        self.assertTrue(english["empty_field"])
        self.assertFalse(english["hundred"][0])
        self.assertIn("PCR confidence (%)", english["hundred"][1])
        self.assertTrue(english["hundred_field"])
        self.assertTrue(english["comma"])
        self.assertEqual(english["level"], 90.5)
        self.assertFalse(english["among"][0])
        self.assertIn("PCR response", english["among"][1])
        italian = self.drive("it", steps)
        self.assertIn("Risposta PCR", italian["empty"][1])
        self.assertIn("Confidenza PCR (%)", italian["hundred"][1])
        self.assertIn("Risposta PCR", italian["among"][1])
        self.assertNotIn("PCR response", italian["empty"][1] + italian["hundred"][1] + italian["among"][1])

    def test_a_stale_response_is_ignored_while_pcr_is_off(self):
        def steps(dialog, seen):
            self.pick(dialog)
            dialog.controls[RESPONSE][1].set("Temperature")
            dialog.controls[CONFIDENCE][1].set("250")
            seen["valid"] = self.check(dialog)[0]
            seen["options"] = dict(dialog.result[1])
        seen = self.drive("en", steps)
        self.assertTrue(seen["valid"])
        self.assertIs(seen["options"][ENABLE], False)

    def test_every_engine_message_has_an_italian_translation(self):
        from tramastat import format_pca_error
        frame = table()
        base = {"Variables": ["Conductivity", "Temperature"], "Standardize": True, "Selection": "All"}
        cases = [
            {ENABLE: True},
            {ENABLE: True, RESPONSE: "Missing"},
            {ENABLE: True, RESPONSE: "Temperature"},
            {ENABLE: True, RESPONSE: "Response", CONFIDENCE: 100.0},
            {ENABLE: True, RESPONSE: "Response", CONFIDENCE: 0.0},
            {ENABLE: True, RESPONSE: "Response", PLOT: "Bubble"},
            {ENABLE: True, RESPONSE: "Response", "Selection": "Eigenvalue threshold", "Eigenvalue threshold": 99.0},
        ]
        original = i18n.active_language()
        self.addCleanup(i18n.set_language, original)
        i18n.set_language("it")
        for extra in cases:
            with self.assertRaises(FieldError) as caught:
                analyse(METHOD, frame, {**base, **extra})
            text = format_pca_error(caught.exception)
            self.assertNotIn("PCR response", text)
            self.assertNotIn("PCR confidence", text)
            self.assertNotIn("PCR plot", text)
            self.assertNotEqual(text, str(caught.exception))


class RecoveryTargeting(unittest.TestCase):
    """Rank and degrees of freedom of the fit are known only on the worker: only a PCR recipe may reopen."""

    def test_only_a_pca_that_asked_for_pcr_carries_a_recovery_context(self):
        from tests.test_irls_recovery import fake_app
        from tramastat import AnalysisRecovery
        app = fake_app()
        self.assertIsInstance(app.weighting_recovery(METHOD, {ENABLE: True}, None), AnalysisRecovery)
        for options in ({}, {ENABLE: False}, {RESPONSE: "Response"}, {ENABLE: "yes"}):
            self.assertIsNone(app.weighting_recovery(METHOD, options, None), options)
        self.assertIsNone(app.weighting_recovery("Multiple regression", {ENABLE: True}, None))

    def test_the_failed_pcr_result_is_kept_and_the_field_error_reopens_the_dialog(self):
        from tramastat import App, Run
        app = App.__new__(App)
        app._chain_node_ids = ()
        for options in ({}, {ENABLE: False}):
            plain = Run(METHOD, "Data", options)
            self.assertFalse(app._keeps_failed_result(plain), options)
            self.assertFalse(app._reopens_field_error(plain), options)
        pcr = Run(METHOD, "Data", {ENABLE: True})
        self.assertTrue(app._keeps_failed_result(pcr))
        self.assertTrue(app._reopens_field_error(pcr))
