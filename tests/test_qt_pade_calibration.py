"""Qt dialog and full-window workflow tests for Padé (1,1) standard-curve calibration."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi import nonlinear_calibration as cal
from analisi import pade_calibration as pade
from analisi.i18n import set_language

METHOD = "Interpolate a standard curve"
MODEL = pade.MODEL


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _synthetic_frame():
    # Exact Padé (1,1) on [10, 30] with A0=2, A1=12, B1=2 plus mild noise and out-of-range queries.
    xs = [10.0, 12.5, 15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0]
    zs = [(x - 10.0) / 20.0 for x in xs]
    ys = [(2.0 + 12.0 * z) / (1.0 + 2.0 * z) for z in zs]
    return pd.DataFrame({
        "X": xs,
        "Y": ys,
        "X requests": [10.0, 17.5, 30.0, 5.0, 35.0, np.nan, np.nan, np.nan, np.nan],
        "Y requests": [2.0, 3.7142857142857144, 4.666666666666667, 1.0, 6.0, np.nan, np.nan, np.nan, np.nan],
    })


def _fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if hasattr(control, "findData"):
            position = control.findData(value)
            assert position >= 0, (name, value)
            control.setCurrentIndex(position)
        else:
            control.setText(str(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class PadeCalibrationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = _synthetic_frame() if frame is None else frame
        dialog = AnalysisDialog(None, frame, current=current or (METHOD, {}), **extra)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_existing_models_preserved_and_captions_localized_it_en(self):
        dialog = self._dialog()
        model_box = dialog.controls["Model"][1]
        model_ids = [model_box.itemData(i) for i in range(model_box.count())]
        self.assertEqual(tuple(model_ids), cal.INVERSE_MODELS)
        self.assertIn(MODEL, model_ids)
        self.assertIn("One-phase decay", model_ids)
        self.assertIn("Stimulation (variable slope)", model_ids)
        self.assertIn("Inhibition (variable slope, log10 X)", model_ids)

        # Model label updates with X unit in EN.
        _fill(dialog, Curve="Nonlinear", Model="Stimulation (variable slope)")
        self.assertEqual(dialog.rows["Model"][0].text(), "Model (concentration X)")
        _fill(dialog, Model="Inhibition (variable slope, log10 X)")
        self.assertEqual(dialog.rows["Model"][0].text(), "Model (log10 X)")
        _fill(dialog, Model=MODEL)
        self.assertEqual(dialog.rows["Model"][0].text(), "Model")
        dialog.tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertTrue(dialog.calibration.options_form.isRowVisible(dialog.calibration.note))
        self.assertTrue(dialog.calibration.note.isVisible())
        self.assertIn("A0", dialog.calibration.note.text())

        # Same check in Italian.
        set_language("it")
        dialog_it = self._dialog()
        self.assertEqual(dialog_it.heading.text(), "Interpola una curva di calibrazione")
        self.assertEqual(dialog_it.rows[cal.DIRECTION][0].text(), "Direzione")
        self.assertEqual(dialog_it.rows[cal.UNKNOWN_RESPONSES][0].text(), "Risposte incognite")
        self.assertEqual(dialog_it.rows[cal.UNKNOWN_X][0].text(), "X incognite")
        _fill(dialog_it, Curve="Nonlinear", Model="Stimulation (variable slope)")
        self.assertEqual(dialog_it.rows["Model"][0].text(), "Modello (concentrazione X)")
        _fill(dialog_it, Model="Inhibition (variable slope, log10 X)")
        self.assertEqual(dialog_it.rows["Model"][0].text(), "Modello (log10 X)")
        _fill(dialog_it, Model=MODEL)
        self.assertEqual(dialog_it.rows["Model"][0].text(), "Modello")
        self.assertIn("Solo stime puntuali", dialog_it.calibration.note.text())

    def test_switching_from_interval_model_to_pade_resets_uncertainty_to_none(self):
        dialog = self._dialog()
        _fill(dialog, **{
            "X": "X", "Y": "Y", cal.UNKNOWN_RESPONSES: "Y requests",
            cal.DIRECTION: "X from Y", "Curve": "Nonlinear",
            "Model": "One-phase decay", cal.UNCERTAINTY: "Prediction",
        })
        self.assertNotIn(cal.UNCERTAINTY, dialog.hidden)
        self.assertNotIn(cal.LEVEL, dialog.hidden)
        self.assertNotIn(cal.COUNT, dialog.hidden)

        # Switch to Padé (1,1): Uncertainty resets to None and interval controls hide cleanly.
        _fill(dialog, Model=MODEL)
        self.assertEqual(dialog.controls[cal.UNCERTAINTY][1].currentData(), "None")
        self.assertIn(cal.UNCERTAINTY, dialog.hidden)
        self.assertIn(cal.LEVEL, dialog.hidden)
        self.assertIn(cal.COUNT, dialog.hidden)
        self.assertNotIn(cal.MISSING_X_ONLY, dialog.hidden)
        dialog.controls[cal.MISSING_X_ONLY][1].setChecked(True)
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        _, options = dialog.result
        self.assertEqual(options["Model"], MODEL)
        self.assertTrue(options[cal.MISSING_X_ONLY])
        self.assertNotIn(cal.UNCERTAINTY, options)

        # Switching back to 5PL restores its own uncertainty settings.
        dialog2 = self._dialog()
        _fill(dialog2, **{
            cal.DIRECTION: "Y from X", cal.UNKNOWN_X: "X requests",
            "Curve": "Nonlinear", "Model": cal.CONCENTRATION_5PL, cal.UNCERTAINTY: "Mean response",
        })
        self.assertNotIn(cal.UNCERTAINTY, dialog2.hidden)
        _fill(dialog2, Model=MODEL)
        self.assertEqual(dialog2.controls[cal.UNCERTAINTY][1].currentData(), "None")
        self.assertIn(cal.UNCERTAINTY, dialog2.hidden)
        self.assertIn(cal.MISSING_X_ONLY, dialog2.hidden)
        _fill(dialog2, Model=cal.CONCENTRATION_5PL)
        self.assertNotIn(cal.UNCERTAINTY, dialog2.hidden)
        self.assertEqual(dialog2.controls[cal.UNCERTAINTY][1].currentData(), "None")
        self.assertEqual(dialog2.controls["Model"][1].currentData(), cal.CONCENTRATION_5PL)
        _fill(dialog2, **{cal.UNCERTAINTY: "Prediction"})
        self.assertNotIn(cal.LEVEL, dialog2.hidden)
        self.assertNotIn(cal.COUNT, dialog2.hidden)

    def test_reopened_invalid_interval_recipe_lets_user_return_to_none(self):
        set_language("it")
        bad_recipe = {
            "X": "X", "Y": "Y", cal.UNKNOWN_X: "X requests",
            cal.DIRECTION: "Y from X", "Curve": "Nonlinear", "Model": MODEL,
            cal.UNCERTAINTY: "Mean response", cal.LEVEL: 95.0,
        }
        dialog = self._dialog(current=(METHOD, bad_recipe))
        # Uncertainty stays visible so the user can see and fix it.
        self.assertNotIn(cal.UNCERTAINTY, dialog.hidden)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.error_field, cal.UNCERTAINTY)
        self.assertTrue(dialog.banner.isVisible())
        self.assertIn("Padé (1,1)", dialog.banner.text())
        self.assertIn("Nessuno", dialog.banner.text())

        # User selects None -> banner clears, dialog accepts cleanly.
        _fill(dialog, **{cal.UNCERTAINTY: "None"})
        self.assertIsNone(dialog.error_field)
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_dialog_validation_errors_localized_and_focused(self):
        set_language("it")
        # Constant Y
        const_y = pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [5., 5., 5., 5.], "Q": [5., np.nan, np.nan, np.nan]})
        dialog = self._dialog(const_y)
        _fill(dialog, **{"X": "X", "Y": "Y", cal.UNKNOWN_RESPONSES: "Q", "Curve": "Nonlinear", "Model": MODEL})
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.error_field, "Y")
        self.assertIn("variazione nulla", dialog.banner.text())

        # Too few distinct X
        few_x = pd.DataFrame({"X": [1., 1., 2., 2.], "Y": [2., 3., 4., 5.], "Q": [3., np.nan, np.nan, np.nan]})
        dialog2 = self._dialog(few_x)
        _fill(dialog2, **{"X": "X", "Y": "Y", cal.UNKNOWN_RESPONSES: "Q", "Curve": "Nonlinear", "Model": MODEL})
        dialog2.accept()
        self.assertIsNone(dialog2.result)
        self.assertEqual(dialog2.error_field, "X")
        self.assertIn("tre valori distinti", dialog2.banner.text())


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class PadeCalibrationWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = self._make_window(MainWindow)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))

    def tearDown(self):
        set_language("en")

    def _make_window(self, factory):
        window = factory()
        window.project.dirty = False
        window.show()
        self.app.processEvents()

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(close)
        return window

    def _wait(self, window=None, timeout=60):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job, "calculation still running")

    def _run_dialog(self, values):
        from trama_qt.analysis_dialog import AnalysisDialog

        def exec_(dialog):
            if dialog.method != METHOD:
                dialog.method = METHOD
                dialog.configure_fields()
            _fill(dialog, **values)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            self.window.analyze(METHOD)

    def test_both_directions_edit_recalculate_export_and_alab_roundtrip(self):
        from trama_qt.window import MainWindow
        csv_path = self.folder / "pade_standards.csv"
        _synthetic_frame().to_csv(csv_path, index=False)

        window = self.window
        window.open_path(csv_path)
        self._wait()
        title = window.selected[1]

        # 1. Run X from Y (inverse) with out-of-range queries.
        self._run_dialog({
            "X": "X", "Y": "Y", cal.DIRECTION: "X from Y", cal.UNKNOWN_RESPONSES: "Y requests",
            "Curve": "Nonlinear", "Model": MODEL,
        })
        self._wait()
        inv_run = window.project.runs[0]
        self.assertIsNone(inv_run.calculation_error)
        inv_table = inv_run.result.tables[cal.INTERPOLATED]
        self.assertEqual(inv_table["Status"].tolist(),
                         [cal.IN_RANGE, cal.IN_RANGE, cal.IN_RANGE, cal.OUT_OF_RANGE, cal.OUT_OF_RANGE])
        np.testing.assert_allclose(inv_table["Interpolated X"].iloc[:3], [10.0, 17.5, 30.0], atol=1e-6)
        self.assertTrue(inv_table["Interpolated X"].iloc[3:].isna().all())

        # 2. Run Y from X (forward) with out-of-range queries.
        window.show_sheet("data", title)
        self._run_dialog({
            "X": "X", "Y": "Y", cal.DIRECTION: "Y from X", cal.UNKNOWN_X: "X requests",
            "Curve": "Nonlinear", "Model": MODEL,
        })
        self._wait()
        fwd_run = window.project.runs[1]
        self.assertIsNone(fwd_run.calculation_error)
        fwd_table = fwd_run.result.tables[cal.PREDICTIONS]
        self.assertEqual(fwd_table["Status"].tolist(),
                         [cal.IN_RANGE, cal.IN_RANGE, cal.IN_RANGE, cal.OUTSIDE_CALIBRATION, cal.OUTSIDE_CALIBRATION])
        pred_before = float(fwd_table.at[1, "Predicted Y"])

        # 3. Edit a standard measurement and verify automatic recalculation of both runs.
        window.show_sheet("data", title)
        window.edit_cell(title, 4, 1, "4.35")  # Row 4: X=20.0, Y from 4.0 -> 4.35
        self._wait()
        inv_after = window.project.runs[0]
        fwd_after = window.project.runs[1]
        self.assertIsNone(inv_after.calculation_error)
        self.assertIsNone(fwd_after.calculation_error)
        pred_after = float(fwd_after.result.tables[cal.PREDICTIONS].at[1, "Predicted Y"])
        self.assertNotAlmostEqual(pred_before, pred_after, places=3)

        # 4. Export CSV from result sheet and vector SVG from graph sheet.
        window.show_sheet("result", 1)
        window.result_tabs.setCurrentIndex(list(fwd_after.result.tables).index(cal.PREDICTIONS))
        csv_out = self.folder / "pade_predictions.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv_out), "")):
            window.export()
        exported = pd.read_csv(csv_out)
        self.assertEqual(len(exported), 5)
        self.assertEqual(exported["Status"].tolist(),
                         [cal.IN_RANGE] * 3 + [cal.OUTSIDE_CALIBRATION] * 2)

        window.show_sheet("graph", 0)
        svg_out = self.folder / "pade_curve.svg"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(svg_out), "")):
            window.export()
        svg_text = svg_out.read_text(encoding="utf-8")
        self.assertIn("<svg", svg_text)
        self.assertIn("<path", svg_text)

        # 5. Save .alab, close and reopen in a new window (in Italian) and verify recalculation & equality.
        saved_tables_0 = {k: v.copy() for k, v in inv_after.result.tables.items()}
        saved_tables_1 = {k: v.copy() for k, v in fwd_after.result.tables.items()}
        project_path = self.folder / "pade_calibration.alab"
        window.project.save(project_path)
        with zipfile.ZipFile(project_path) if zipfile.is_zipfile(project_path) else open(project_path, "rb") as handle:
            raw = handle.read("project.json") if isinstance(handle, zipfile.ZipFile) else handle.read()
        analyses = json.loads(raw)["tables"][0]["analyses"]
        self.assertEqual(len(analyses), 2)
        self.assertEqual(analyses[0][1]["Model"], MODEL)
        self.assertEqual(analyses[1][1]["Model"], MODEL)

        set_language("it")
        reopened = self._make_window(MainWindow)
        reopened.error = lambda error: self.errors.append(str(error))
        reopened.open_path(project_path)
        self._wait(reopened)
        for idx, expected_tables in ((0, saved_tables_0), (1, saved_tables_1)):
            reopened.open_sheet(("graph", idx))
            self._wait(reopened)
            run = reopened.project.runs[idx]
            self.assertIsNone(run.calculation_error)
            for name, frame in expected_tables.items():
                pd.testing.assert_frame_equal(run.result.tables[name], frame, obj=f"{idx}:{name}")
        self.assertEqual(self.errors, [])

    def test_worker_error_reopens_dialog_with_translated_message_and_focus(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language("it")
        frame = _synthetic_frame().assign(**{"Empty Q": np.nan})
        csv_path = self.folder / "pade_empty_query.csv"
        frame.to_csv(csv_path, index=False)

        window = self.window
        window.open_path(csv_path)
        self._wait()

        reopened = []
        step = [0]

        def exec_(dialog):
            step[0] += 1
            if step[0] == 1:
                if dialog.method != METHOD:
                    dialog.method = METHOD
                    dialog.configure_fields()
                _fill(dialog, **{
                    "X": "X", "Y": "Y", cal.DIRECTION: "X from Y", cal.UNKNOWN_RESPONSES: "Empty Q",
                    "Curve": "Nonlinear", "Model": MODEL,
                })
                dialog.accept()
                return QDialog.DialogCode.Accepted
            dialog.show()
            self.app.processEvents()
            reopened.append((dialog.error_field, dialog.banner.text(), dialog.banner.isVisible()))
            return QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            window.analyze(METHOD)
            self._wait()

        self.assertEqual(len(reopened), 1)
        field, text, visible = reopened[0]
        self.assertEqual(field, cal.UNKNOWN_RESPONSES)
        self.assertTrue(visible)
        self.assertIn("valori di risposta incogniti", text)


if __name__ == "__main__":
    unittest.main()
