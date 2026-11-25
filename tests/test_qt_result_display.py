"""Verify analysis-output formatting against the real metric and value layouts."""

import unittest

import numpy as np
import pandas as pd

from analisi import result_display as output
from analisi.i18n import active_language, set_language
from analisi.workbench import analyse
from tests.test_survival_comparisons import BASE as SURVIVAL_OPTIONS, fixture as survival_frame
from tests.test_ttest_inputs import COLUMNS, WIDE

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


SURVIVAL = "Kaplan–Meier survival"
NONLINEAR = "Nonlinear regression"
TEST_OPTIONS = {**COLUMNS, "Design": "Paired", "Show paired t-test details": True}
DISPLAY = {output.DIGITS: 4, output.P_STYLE: output.VALUE_AND_STARS}


def nonlinear_frame():
    time = np.repeat(np.arange(6, dtype=float), 2)
    return pd.DataFrame({"X": time, "Y": 1 + 8*np.exp(-.4*time) + np.tile([-.17, .13], 6)})


NONLINEAR_OPTIONS = {"X": "X", "Y columns": ["Y"], "Model": "One-phase decay", "Replicate lack of fit": True}


@unittest.skipIf(QApplication is None, "PySide6 is not importable")
class ReportDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-report-display", "-platform", "offscreen"])

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("en")

    def test_p_value_row_is_formatted_in_both_short_and_multiresponse_reports(self):
        from trama_qt.models import FrameModel

        paired = analyse("t-test", WIDE, TEST_OPTIONS).tables["t-test"]
        paired_model = FrameModel(paired, result_display=output.renderer("t-test", DISPLAY))
        for label in ("p", "Pairing p (positive association)"):
            index = paired.index.get_loc(label)
            self.assertIn("(", paired_model.index(index, 1).data())
            self.assertEqual(paired_model.plain_text(index, 1), f'{paired.at[label, "Value"]:.10g}')
        self.assertNotIn("(", paired_model.index(paired.index.get_loc("Mean first"), 1).data())

        frame = survival_frame()
        frame["Event copy"] = frame[SURVIVAL_OPTIONS["Event"]]
        options = dict(SURVIVAL_OPTIONS)
        options["Event columns"] = [options.pop("Event"), "Event copy"]
        options["Grouping variables"] = [options.pop("Group")]
        table = analyse(SURVIVAL, frame, options).tables["Log-rank test"]
        p_rows = np.flatnonzero(table["Metric"].eq("p").to_numpy())
        self.assertEqual(len(p_rows), 2)
        model = FrameModel(table, result_display=output.renderer(SURVIVAL, DISPLAY))
        value_column = table.columns.get_loc("Value") + 1
        for row in p_rows:
            self.assertIn("(", model.index(int(row), value_column).data())
            self.assertEqual(model.plain_text(int(row), value_column), f'{table.at[row, "Value"]:.10g}')

    def test_nonlinear_parameters_and_diagnostics_use_independent_formats(self):
        from trama_qt.models import FrameModel

        frame = nonlinear_frame()
        original = analyse(NONLINEAR, frame, NONLINEAR_OPTIONS)
        styled = analyse(NONLINEAR, frame, {**NONLINEAR_OPTIONS, **DISPLAY})
        self.assertEqual(list(original.tables), list(styled.tables))
        render = output.renderer(NONLINEAR, DISPLAY)
        for title, table in styled.tables.items():
            pd.testing.assert_frame_equal(table, original.tables[title], check_exact=True)
        parameters = next(table for title, table in styled.tables.items() if title.startswith("Parameters:"))
        estimate = parameters.columns.get_loc("Estimate") + 1
        model = FrameModel(parameters, result_display=render)
        self.assertEqual(model.index(0, estimate).data(), f'{parameters["Estimate"].iloc[0]:.4g}')
        diagnosis = next(table for title, table in styled.tables.items() if title.startswith("Replicate lack of fit"))
        model = FrameModel(diagnosis, result_display=render)
        self.assertIn("(", model.index(diagnosis.index.get_loc("p"), 1).data())
        self.assertIsNone(render("At risk", np.int64(12857)))

    def test_output_controls_restore_and_default_keys_are_omitted(self):
        from trama_qt.analysis_dialog import AnalysisDialog

        examples = (("t-test", WIDE, TEST_OPTIONS), (NONLINEAR, nonlinear_frame(), NONLINEAR_OPTIONS),
                    (SURVIVAL, survival_frame(), SURVIVAL_OPTIONS))
        for method, frame, options in examples:
            with self.subTest(method=method):
                dialog = AnalysisDialog(None, frame, current=(method, {**options, **DISPLAY}), only=method)
                self.addCleanup(dialog.deleteLater)
                values = dialog.options()
                self.assertEqual({key: values[key] for key in DISPLAY}, DISPLAY)
                dialog.controls[output.DIGITS][1].setText("0")
                style = dialog.controls[output.P_STYLE][1]
                style.setCurrentIndex(style.findData(output.AUTO))
                self.assertFalse(output.OPTIONS.keys() & dialog.options().keys())
