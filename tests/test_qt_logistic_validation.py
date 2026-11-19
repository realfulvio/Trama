"""Validate binary logistic model in the Qt dialog, offscreen: fields, checks before the worker, messages, catalog.

Skipped when PySide6 (or the Qt platform libraries) are not installed. The whole window path (import, run, export,
linked analysis, edit, save and reopen, 20,000-row run and cancel) is ``python -m trama_qt.logistic_validation_smoke``.
"""
import re
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi import logistic_validation as lv
from analisi.i18n import _EN, _IT, set_language
from analisi.logistic_validation_catalog import CAPTIONS, MESSAGES


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def frame(n=60):
    rng = np.random.default_rng(3)
    data = pd.DataFrame({"Outcome": np.tile([0, 0, 1, 1, 1, 0], n // 6), "Dose mg": rng.normal(size=n),
                         "Site #": rng.choice(["A", "B"], n), "Fold": np.tile([1, 2, 3], n // 3)})
    return data


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(value, list):
            for row in range(control.count()):
                item = control.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.text() in value else Qt.CheckState.Unchecked)
        elif hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        else:
            control.setText(str(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, data=None, current=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, frame() if data is None else data, current=current or (lv.METHOD, {}))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_fields_and_canonical_recipe(self):
        dialog = self.dialog()
        self.assertEqual(list(dialog.controls), list(lv.OPTIONS))
        fill(dialog, Response="Outcome", Predictors=["Dose mg", "Site #"], **{"Categorical predictors": ["Site #"]})
        fill(dialog, Threshold="0,25", Folds="3")
        dialog.accept()
        method, options = dialog.result
        self.assertEqual(method, lv.METHOD)
        self.assertEqual(options, {"Response": "Outcome", "Predictors": ["Dose mg", "Site #"],
                                   "Categorical predictors": ["Site #"], "Folds": 3, "Seed": 0,
                                   "Validation fold": None, "Threshold": .25, "Calibration bins": 10,
                                   "Graph view": "Calibration"})

    def test_errors_are_shown_on_their_field_before_any_fit(self):
        dialog = self.dialog()
        fill(dialog, Response="Outcome", Predictors=["Dose mg"], **{"Categorical predictors": []})
        fill(dialog, **{"Validation fold": "Fold", "Folds": "4"})
        with mock.patch.object(lv, "binomial_fit", side_effect=AssertionError("fit")), \
                mock.patch.object(lv, "separation_direction", side_effect=AssertionError("LP")):
            dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.banner.text(), "Fold 4 has no usable rows: use codes 1 to 4.")
        self.assertIs(self.app.focusWidget(), dialog.controls["Validation fold"][1])
        fill(dialog, Folds="3")
        dialog.accept()
        self.assertEqual(dialog.result[1]["Validation fold"], "Fold")

    def test_messages_in_italian(self):
        set_language("it")
        dialog = self.dialog()
        fill(dialog, Response="Outcome", Predictors=["Dose mg"], **{"Categorical predictors": []})
        fill(dialog, **{"Calibration bins": "30"})
        dialog.accept()
        self.assertEqual(dialog.banner.text(), "Classi di calibrazione: inserisci un numero intero da 3 a 20.")
        self.assertEqual(dialog.rows["Graph view"][0].text(), "Vista del grafico")
        self.assertEqual(dialog.heading.text(), "Valida il modello logistico binario")

    def test_engine_error_reopening_the_dialog_is_translated(self):
        set_language("it")
        from trama_qt.analysis_dialog import AnalysisDialog
        error = 'Fold 2: "Site #" has a single level in the training rows.'
        dialog = AnalysisDialog(None, frame(), current=(lv.METHOD, {}), error=error,
                                error_field="Categorical predictors")
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.banner.text(), 'Fold 2: "Site #" ha un solo livello nelle righe di addestramento.')

    def test_other_methods_are_untouched(self):
        dialog = self.dialog(current=("Multiple regression", {}))
        fill(dialog, Response="Outcome", Predictors=["Dose mg"])
        with mock.patch("trama_qt.logistic_validation.prepare", side_effect=AssertionError("called")):
            dialog.accept()
        self.assertEqual(dialog.result[0], "Multiple regression")


class CatalogTests(unittest.TestCase):
    def test_every_engine_message_has_a_translation(self):
        source = (lv.__file__ and open(lv.__file__, encoding="utf-8").read())
        patterns = [re.compile(re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.+?)", re.escape(english)) + r"\Z")
                    for english, _italian in MESSAGES.values()]
        texts = {
            "Threshold: enter a number from 0 to 1.", "Calibration bins: enter a whole number from 3 to 20.",
            'Column "x" contains text (source row 3).', "The usable rows need both outcomes, 0 and 1.",
            "Each outcome needs at least 5 usable rows, one per fold (outcome 1 has 3).",
            "Source row 9: fold code 7 is not a whole number from 1 to 5.",
            "Fold 2: the training rows are separated (complete or quasi-complete separation), so the logistic fit "
            "has no finite estimate. Change the predictors, the folds or the seed.",
            'Fold 1: every training row with level "Island" of "Clinic" has outcome 1 (quasi-complete separation). '
            "Merge rare levels, or change the folds or the seed.",
        }
        for text in texts:
            self.assertTrue(any(pattern.match(text) for pattern in patterns), text)
        self.assertGreaterEqual(source.count("FieldError("), len(MESSAGES) - 10)

    def test_placeholders_match_and_appear_once(self):
        for key, (english, italian) in MESSAGES.items():
            names = re.findall(r"\{(\w+)\}", english)
            self.assertEqual(len(names), len(set(names)), key)
            self.assertEqual(sorted(names), sorted(re.findall(r"\{(\w+)\}", italian)), key)
            self.assertEqual((_EN[key], _IT[key]), (english, italian))

    def test_captions_are_registered(self):
        for english, italian in CAPTIONS.items():
            self.assertEqual(_IT["interface." + english], italian)


if __name__ == "__main__":
    unittest.main()
