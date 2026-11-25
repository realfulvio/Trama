"""Paired comparison of two Deming lines in the Qt dialog and the engine.

The numbers are the eight paired rows of ``tests/data/deming-paired``. ``oracolo.py`` refits every omitted row
with an independent SVD; production uses ``leave_one_out_coefficients`` and must meet the same ``oracolo.json``.
"""
import importlib.util
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.analysis_chain import ChainCancelled
from analisi.data import load_project
from analisi.deming import PAIRED, PAIRED_COLUMNS, PAIRED_P_NOTE, PAIRED_SHEET, JACKKNIFE_LIMIT
from analisi.deming_plot import deming_result
from analisi.field_error import FieldError
from analisi.i18n import active_language, set_language
from analisi.workbench import analyse

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

ROOT = Path(__file__).resolve().parent / "data" / "deming-paired"
ORACLE = json.loads((ROOT / "oracolo.json").read_text(encoding="utf-8"))
TABLE = "Misure appaiate"
METHOD = "Deming regression"
FIRST, SECOND = "Controllo", "Trattamento $"
TOLERANCE = {"rtol": 0, "atol": 1e-12}


def _oracle_module():
    spec = importlib.util.spec_from_file_location("deming_paired_oracle", ROOT / "oracolo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project():
    return load_project(ROOT / "deming-appaiato.alab")


def _frame():
    return _project()[TABLE].frame(mask_excluded=True)


def _recipe(**extra):
    recipe = {"X": "X", "Y": FIRST, "Y series": [FIRST, SECOND], "Y / X error variance": 1.0,
              "Confidence level (%)": 95.0, "Parameter intervals": "None", PAIRED: True}
    recipe.update(extra)
    return recipe


def _run(frame=None, **extra):
    return analyse(METHOD, _frame() if frame is None else frame, _recipe(**extra))


def _sheet(result):
    return result.tables[PAIRED_SHEET]


def _close(testcase, values, expected):
    np.testing.assert_allclose(np.asarray(values, dtype=float), np.asarray(expected, dtype=float), **TOLERANCE)


class EngineTests(unittest.TestCase):
    def test_the_fixture_matches_the_svd_oracle_and_shows_both_sample_sizes(self):
        result = _run()
        sheet = _sheet(result)
        self.assertEqual(list(sheet.columns), list(PAIRED_COLUMNS))
        self.assertEqual(list(sheet["Coefficient"]), ["Slope", "Intercept"])
        self.assertEqual(list(sheet["First series"]), [FIRST, FIRST])
        self.assertEqual(list(sheet["Second series"]), [SECOND, SECOND])
        self.assertEqual(list(sheet["First N"]), [10, 10])
        self.assertEqual(list(sheet["Second N"]), [8, 8])
        self.assertEqual(list(sheet["Paired N"]), [8, 8])
        self.assertEqual(int(sheet["df"].iloc[0]), ORACLE["df"])
        _close(self, sheet["First"], ORACLE["first"])
        _close(self, sheet["Second"], ORACLE["second"])
        _close(self, sheet["Difference"], ORACLE["second_minus_first"])
        _close(self, sheet["SE"], ORACLE["se"])
        _close(self, sheet["Individual p"], ORACLE["p_two_sided"])
        _close(self, sheet["CI low"], ORACLE["lower"])
        _close(self, sheet["CI high"], ORACLE["upper"])
        self.assertTrue((sheet["Interval"] == "Approximate jackknife (t)").all())
        self.assertTrue((sheet["p note"] == PAIRED_P_NOTE).all())
        self.assertEqual(sheet["Status"].iloc[0], "")
        self.assertIn("X = 0", sheet["Status"].iloc[1])
        counts = dict(zip(result.tables["Deming regression"]["Series"], result.tables["Deming regression"]["N"]))
        self.assertEqual(counts, {FIRST: 10, SECOND: 8})
        paired = _frame()[["X", FIRST, SECOND]].apply(pd.to_numeric, errors="coerce").dropna().to_numpy(dtype=float)
        live = _oracle_module().contrast(paired, ratio=1.0, confidence=0.95)
        _close(self, sheet["Difference"], live["second_minus_first"])
        _close(self, sheet["SE"], live["se"])

    def test_known_sds_use_the_selected_ratio_and_ignore_the_variance_field(self):
        sheet = _sheet(_run(**{"Uncertainty input": "Known SDs", "X error SD": 2.0, "Y error SD": 2.0,
                               "Y / X error variance": 9.0}))
        _close(self, sheet["Difference"], ORACLE["second_minus_first"])
        self.assertTrue((sheet["Y / X measurement error variance"] == 1.0).all())

    def test_reversing_the_series_flips_the_estimate_and_the_interval_ends(self):
        forward = _sheet(_run())
        backward = _sheet(_run(**{"Y series": [SECOND, FIRST], "Y": SECOND}))
        _close(self, backward["Difference"], -forward["Difference"].to_numpy())
        _close(self, backward["SE"], forward["SE"])
        _close(self, backward["Individual p"], forward["Individual p"])
        _close(self, backward["CI low"], -forward["CI high"].to_numpy())
        _close(self, backward["CI high"], -forward["CI low"].to_numpy())
        _close(self, backward["First"], forward["Second"])
        _close(self, backward["Second"], forward["First"])

    def test_identical_paired_curves_keep_a_zero_difference_and_no_inference(self):
        frame = _frame()
        frame[SECOND] = frame[FIRST]
        sheet = _sheet(_run(frame))
        _close(self, sheet["Difference"], [0.0, 0.0])
        _close(self, sheet["SE"], [0.0, 0.0])
        self.assertTrue(sheet["Individual p"].isna().all())
        self.assertTrue(sheet["CI low"].isna().all())
        self.assertTrue(sheet["Status"].str.contains("zero").all())
        self.assertTrue((sheet["Interval"] == "Approximate jackknife (t)").all())

    def test_five_paired_rows_keep_the_separate_fits_and_name_the_count(self):
        frame = _frame()
        frame.iloc[0:3, frame.columns.get_loc(SECOND)] = np.nan
        result = _run(frame)
        sheet = _sheet(result)
        self.assertEqual(list(sheet["Paired N"]), [5, 5])
        self.assertEqual(list(sheet["First N"]), [10, 10])
        self.assertEqual(list(sheet["Second N"]), [5, 5])
        self.assertTrue(sheet["Difference"].isna().all())
        self.assertTrue(sheet["Status"].str.contains("5 are available").all())
        counts = dict(zip(result.tables["Deming regression"]["Series"], result.tables["Deming regression"]["N"]))
        self.assertEqual(counts[FIRST], 10)
        self.assertEqual(counts[SECOND], 5)
        self.assertTrue(np.isfinite(result.tables["Deming regression"]["Slope"]).all())

    def test_zero_paired_covariance_keeps_a_valid_series_report(self):
        frame = pd.DataFrame({
            "X": np.arange(1, 13, dtype=float),
            "A": [1, 2, 3, 4, 5, 6, 7, 8, np.nan, np.nan, np.nan, np.nan],
            "B": [4, 4, 4, 4, 4, 4, 4, 4, 1, 2, 3, 9],
        })
        result = _run(frame, **{"Y": "A", "Y series": ["A", "B"]})
        sheet = _sheet(result)
        self.assertEqual(int(sheet["Paired N"].iloc[0]), 8)
        self.assertIn('"B"', sheet["Status"].iloc[0])
        self.assertIn("nonzero covariance", sheet["Status"].iloc[0])
        self.assertTrue(sheet["First"].isna().all())
        report = result.tables["Deming regression"]
        self.assertEqual(list(report["Series"]), ["A", "B"])
        self.assertTrue(np.isfinite(report["Slope"]).all())

    def test_a_degenerate_omit_keeps_the_coefficients_and_blanks_the_inference(self):
        frame = pd.DataFrame({
            "X": [0, 0, 0, 0, 0, 1],
            "A": [1, 1.1, 0.9, 1.2, 0.8, 3],
            "B": [2, 2.2, 1.8, 2.1, 1.9, 4],
        })
        sheet = _sheet(_run(frame, **{"Y": "A", "Y series": ["A", "B"]}))
        self.assertTrue(np.isfinite(sheet["First"]).all())
        self.assertTrue(np.isfinite(sheet["Difference"]).all())
        self.assertTrue(sheet["SE"].isna().all())
        self.assertTrue(sheet["Individual p"].isna().all())
        self.assertTrue(sheet["Status"].str.contains("degenerate").all())

    def test_duplicate_x_values_still_fit_when_x_varies(self):
        x = np.array([1, 1, 2, 2, 3, 3, 4, 4, 5, 5], dtype=float)
        frame = pd.DataFrame({"X": x, "A": 2 * x + np.array([0.2, -0.2] * 5),
                              "B": x + np.array([0.1, -0.1] * 5)})
        sheet = _sheet(_run(frame, **{"Y": "A", "Y series": ["A", "B"]}))
        self.assertEqual(int(sheet["Paired N"].iloc[0]), 10)
        self.assertTrue(np.isfinite(sheet["Difference"]).all())
        self.assertTrue(np.isfinite(sheet["SE"]).all())

    def test_a_large_x_scale_matches_the_oracle_and_scales_the_slope(self):
        rng = np.random.default_rng(1)
        x = np.linspace(-2, 8, 40)
        frame = pd.DataFrame({"X": x, "A": 1.5 * x + rng.normal(scale=0.02, size=x.size),
                              "B": 0.4 * x + rng.normal(scale=0.02, size=x.size)})
        plain = _sheet(_run(frame, **{"Y": "A", "Y series": ["A", "B"]}))
        scaled = frame.copy()
        scaled["X"] = x * 1e8
        wide = _sheet(_run(scaled, **{"Y": "A", "Y series": ["A", "B"]}))
        live = _oracle_module().contrast(scaled[["X", "A", "B"]].to_numpy(dtype=float), 1.0, 0.95)
        _close(self, wide["Difference"], live["second_minus_first"])
        _close(self, wide["SE"], live["se"])
        # lambda stays 1 while X grows, so the intercept moves by a few hundred-thousandths.
        np.testing.assert_allclose(wide["Difference"].iloc[0], plain["Difference"].iloc[0] / 1e8, rtol=1e-4, atol=0)
        self.assertLess(abs(wide["Difference"].iloc[1] - plain["Difference"].iloc[1]), 1e-3)
        self.assertNotIn("X = 0", wide["Status"].iloc[1])

    def test_above_the_work_limit_keeps_the_coefficients_and_skips_the_jackknife(self):
        rng = np.random.default_rng(2)
        n = JACKKNIFE_LIMIT + 1
        x = np.linspace(0, 1, n)
        frame = pd.DataFrame({"X": x, "A": x + rng.normal(scale=0.01, size=n),
                              "B": 0.5 * x + rng.normal(scale=0.01, size=n)})
        with patch("analisi.deming.leave_one_out_coefficients", side_effect=AssertionError("jackknife ran")):
            sheet = _sheet(_run(frame, **{"Y": "A", "Y series": ["A", "B"]}))
        self.assertEqual(int(sheet["Paired N"].iloc[0]), n)
        self.assertTrue(np.isfinite(sheet["Difference"]).all())
        self.assertTrue(sheet["SE"].isna().all())
        self.assertTrue(sheet["Status"].str.contains(str(JACKKNIFE_LIMIT)).all())

    def test_the_option_off_or_absent_keeps_the_base_sheets(self):
        saved = _project()[TABLE].analyses[0][1]
        base = analyse(METHOD, _frame(), saved)
        off = analyse(METHOD, _frame(), {**saved, PAIRED: False})
        self.assertNotIn(PAIRED_SHEET, base.tables)
        self.assertNotIn(PAIRED_SHEET, off.tables)
        for name in base.tables:
            pd.testing.assert_frame_equal(base.tables[name], off.tables[name], check_exact=True)
        counts = dict(zip(base.tables["Deming regression"]["Series"], base.tables["Deming regression"]["N"]))
        self.assertEqual(counts, {FIRST: 10, SECOND: 8})

    def test_a_bad_flag_or_one_series_is_refused_before_a_fit(self):
        with self.assertRaises(FieldError) as caught:
            _run(**{PAIRED: "yes"})
        self.assertEqual(caught.exception.field, PAIRED)
        with self.assertRaises(FieldError) as caught:
            _run(**{"Y series": [FIRST]})
        self.assertEqual(caught.exception.field, PAIRED)

    def test_a_constant_series_still_stops_on_that_series(self):
        frame = pd.DataFrame({"X": np.arange(1, 9, dtype=float), "A": np.arange(2, 10, dtype=float), "B": np.ones(8)})
        with self.assertRaises(FieldError) as caught:
            _run(frame, **{"Y": "A", "Y series": ["A", "B"]})
        self.assertEqual(caught.exception.field, "Y series")
        self.assertIn('"B"', str(caught.exception))

    def test_cancellation_stops_before_the_paired_jackknife(self):
        event = threading.Event()
        event.set()
        for cancel in (lambda: True, event):
            with patch("analisi.deming.leave_one_out_coefficients", return_value=None) as jackknife:
                with self.assertRaises(ChainCancelled):
                    analyse(METHOD, _frame(), _recipe(), cancel=cancel)
            self.assertFalse(jackknife.called)
        self.assertIn(PAIRED_SHEET, analyse(METHOD, _frame(), _recipe(), cancel=threading.Event()).tables)

    def test_twenty_thousand_paired_rows_stay_on_the_vectorized_path(self):
        rng = np.random.default_rng(3)
        n = 20_000
        x = np.linspace(0, 10, n)
        frame = pd.DataFrame({"X": x, "A": 2 * x + rng.normal(scale=0.1, size=n),
                              "B": x + 0.5 + rng.normal(scale=0.1, size=n)})
        started = time.perf_counter()
        sheet = _sheet(_run(frame, **{"Y": "A", "Y series": ["A", "B"]}))
        elapsed = time.perf_counter() - started
        self.assertEqual(int(sheet["Paired N"].iloc[0]), n)
        self.assertTrue(np.isfinite(sheet["SE"]).all())
        self.assertLess(elapsed, 5.0)

    def test_the_figure_is_the_series_figure(self):
        saved = _project()[TABLE].analyses[0][1]
        frame = _frame()
        before = deming_result(frame, saved)
        after = deming_result(frame, {**saved, PAIRED: True})
        self.assertEqual(len(before.figure.axes[0].lines), len(after.figure.axes[0].lines))
        self.assertIn(PAIRED_SHEET, after.tables)
        before.figure.clf()
        after.figure.clf()


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _tick(dialog, names):
    box = dialog.controls["Y series"][1]
    for row in range(box.count()):
        item = box.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)


@unittest.skipIf(QApplication is None, "PySide6 is not importable")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)

    def _dialog(self, saved=None, language="en"):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language(language)
        dialog = AnalysisDialog(None, _frame(), current=(METHOD, saved or {}), only=METHOD)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.reject)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_note_states_the_row_pairing_and_the_option_starts_off(self):
        dialog = self._dialog()
        self.assertFalse(dialog.controls[PAIRED][1].isChecked())
        self.assertIn("same unit", dialog.deming_paired_note.text())
        self.assertEqual(dialog.rows[PAIRED][0].text(), "Compare paired series")
        dialog.accept()
        self.assertNotIn(PAIRED, dialog.result[1])

    def test_one_series_stays_in_the_dialog_and_two_series_save_the_key(self):
        dialog = self._dialog()
        _tick(dialog, [FIRST])
        dialog.controls[PAIRED][1].setChecked(True)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("exactly two Y series", dialog.banner.text())
        _tick(dialog, [FIRST, SECOND])
        dialog.banner.hide()
        dialog.accept()
        self.assertTrue(dialog.result[1][PAIRED])

    def test_italian_captions_and_a_non_finite_ratio_stay_in_the_dialog(self):
        dialog = self._dialog(language="it")
        self.assertEqual(dialog.rows[PAIRED][0].text(), "Confronta le serie appaiate")
        self.assertIn("stessa unità", dialog.deming_paired_note.text())
        dialog.controls[PAIRED][1].setChecked(True)
        dialog.accept()
        self.assertIn("esattamente due serie Y", dialog.banner.text())
        _tick(dialog, [FIRST, SECOND])
        dialog.controls["Y / X error variance"][1].setText("inf")
        dialog.banner.hide()
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.text())

    def test_an_explicit_off_from_an_older_recipe_is_kept(self):
        dialog = self._dialog({**_project()[TABLE].analyses[0][1], PAIRED: False})
        dialog.accept()
        self.assertIs(dialog.result[1][PAIRED], False)
