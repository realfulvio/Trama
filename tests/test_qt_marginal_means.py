"""Estimated marginal means in the Classic Qt Multifactor ANOVA dialog.

Offscreen. The numbers are the unbalanced oracle in ``tests/data/marginal_means/oracolo.json``: the dialog
keeps an old recipe unchanged, refuses a confidence of 0, then saves 95% as 0.95. Reopening, a cell edit
and an exclusion recalculate the sheet, and the CSV matches it.
"""
from contextlib import contextmanager
from copy import deepcopy
import tempfile
import time
from pathlib import Path
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
except ImportError:
    QApplication = None

import pandas as pd
from pandas.testing import assert_frame_equal

from analisi import anova_marginal_means as means
from analisi.i18n import active_language, set_language
from tests.test_anova_marginal_means import ORACLE, assert_close, combination, oracle_frame, overall

METHOD = "Multifactor ANOVA"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _tick(dialog, names):
    box = dialog.controls["Factors"][1]
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

    def _dialog(self, frame, saved=None, language="en"):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language(language)
        dialog = AnalysisDialog(None, frame, current=(METHOD, saved or {}), only=METHOD)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.reject)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_off_omits_the_keys_and_italian_captions(self):
        dialog = self._dialog(oracle_frame(), language="it")
        _tick(dialog, ["A", "B"])
        panel = dialog.controls[means.ENABLED][1]
        self.assertFalse(panel.enabled.isChecked())
        self.assertFalse(panel.factor_list.isEnabled())
        self.assertEqual(panel.title.text(), "Medie marginali stimate")
        self.assertIn("Confidenza", panel.confidence_label.text())
        _tick(dialog, ["A", "B"])
        self.assertFalse(set(means.KEYS) & set(dialog.options()))
        panel.enabled.setChecked(True)
        self.assertTrue(panel.factor_list.isEnabled())
        self.assertEqual(panel.confidence.text(), "95")
        panel.enabled.setChecked(False)
        self.assertFalse(set(means.KEYS) & set(dialog.options()))

    def test_a_zero_percent_is_refused_and_95_is_stored_as_a_proportion(self):
        dialog = self._dialog(oracle_frame())
        _tick(dialog, ["A", "B"])
        panel = dialog.controls[means.ENABLED][1]
        self.assertEqual([panel.factor_list.item(row).data(Qt.ItemDataRole.UserRole)
                          for row in range(panel.factor_list.count())], ["A", "B"])
        panel.enabled.setChecked(True)
        panel.factor_list.item(1).setCheckState(Qt.CheckState.Checked)  # B first
        panel.factor_list.item(0).setCheckState(Qt.CheckState.Checked)  # then A
        panel.confidence.setText("0")
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("less than 100", dialog.banner.text())
        self.assertIn("Marginal mean confidence", dialog.banner.text())
        self.assertEqual(panel.confidence.selectedText(), "0")
        panel.confidence.setText("95")
        panel.overall.setChecked(True)
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        options = dialog.result[1]
        self.assertEqual(options[means.FACTORS], ["B", "A"])
        self.assertTrue(options[means.OVERALL])
        self.assertEqual(options[means.CONFIDENCE], 0.95)

    def test_italian_comma_and_a_saved_order_round_trip(self):
        saved = {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 2,
                 means.ENABLED: True, means.FACTORS: ["B", "A"], means.OVERALL: True, means.CONFIDENCE: 0.975}
        dialog = self._dialog(oracle_frame(), saved, language="it")
        panel = dialog.controls[means.ENABLED][1]
        self.assertEqual(panel.factors(), ["B", "A"])
        self.assertEqual(panel.confidence.text(), "97,5")
        self.assertEqual(panel.title.text(), "Medie marginali stimate")
        dialog.accept()
        options = dialog.result[1]
        self.assertEqual(options[means.FACTORS], ["B", "A"])
        self.assertEqual(options[means.CONFIDENCE], 0.975)
        self.assertTrue(options[means.ENABLED])

    def test_special_characters_stay_in_the_recipe(self):
        frame = pd.DataFrame({"A & B": ['µ "x"', 'µ "x"', "B |", "B |"], "Y": [1.0, 2.0, 3.0, 4.0]})
        dialog = self._dialog(frame)
        _tick(dialog, ["A & B"])
        panel = dialog.controls[means.ENABLED][1]
        panel.enabled.setChecked(True)
        self.assertEqual(panel.factor_list.item(0).text(), "A & B")
        panel.factor_list.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(dialog.options()[means.FACTORS], ["A & B"])

    def test_a_factor_that_left_the_model_stays_visible(self):
        frame = oracle_frame()
        frame["C"] = ["c0", "c1"] * (len(frame) // 2) + ["c0"] * (len(frame) % 2)
        saved = {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 2,
                 means.ENABLED: True, means.FACTORS: ["C"], means.OVERALL: False, means.CONFIDENCE: 0.95}
        dialog = self._dialog(frame, saved)
        panel = dialog.controls[means.ENABLED][1]
        for index in range(dialog.tabs.count()):
            if dialog.tabs.widget(index).findChild(QWidget, "marginalMeansPanel") is not None:
                dialog.tabs.setCurrentIndex(index)
        self.app.processEvents()
        names = [panel.factor_list.item(row).data(Qt.ItemDataRole.UserRole)
                 for row in range(panel.factor_list.count())]
        self.assertEqual(dialog.anova.model_factors(), ["A", "B"])
        self.assertIn("C", names)
        self.assertFalse(panel.note.isHidden())
        self.assertIn("C", panel.note.text())
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("“C”", dialog.banner.text())

    def test_a_narrow_dialog_keeps_the_controls(self):
        dialog = self._dialog(oracle_frame(), language="it")
        panel = dialog.controls[means.ENABLED][1]
        for index in range(dialog.tabs.count()):
            if dialog.tabs.widget(index).findChild(QWidget, "marginalMeansPanel") is not None:
                dialog.tabs.setCurrentIndex(index)
        dialog.resize(480, 640)
        self.app.processEvents()
        panel = dialog.controls[means.ENABLED][1]
        panel.enabled.setChecked(True)
        self.app.processEvents()
        self.assertGreater(panel.width(), 200)
        self.assertGreater(panel.factor_list.width(), 80)
        self.assertGreaterEqual(panel.confidence.width(), 40)
        self.assertTrue(panel.title.wordWrap())
        for child in panel.findChildren(QWidget):
            if child.isVisibleTo(panel):
                self.assertGreater(child.width(), 0, child.objectName() or type(child).__name__)


@unittest.skipIf(QApplication is None, "PySide6 is not importable")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.language = active_language()
        self.addCleanup(set_language, self.language)
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    @contextmanager
    def drive(self, *steps):
        from trama_qt.analysis_dialog import AnalysisDialog
        queue = list(steps)

        def run(dialog):
            self.assertTrue(queue, f"unexpected dialog: {dialog.banner.text()}")
            dialog.show()
            self.app.processEvents()
            accepted = queue.pop(0)(dialog)
            return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", run):
            yield
        self.assertEqual(queue, [])

    def test_oracle_save_edit_and_a_legacy_recipe(self):
        from analisi.data import Dataset, save_project
        from analisi.workbench import analyse
        from trama_qt.window import safe_csv
        path = self.folder / "oracle.alab"
        save_project(path, { "Oracle": Dataset(oracle_frame()) })
        self.window.open_path(path)
        self.app.processEvents()
        self.window.open_sheet(("data", "Oracle"))

        def build(dialog):
            _tick(dialog, ["A", "B"])
            dialog.controls["Interaction order"][1].setText("2")
            combo = dialog.controls["Compare marginal means by"][1]
            combo.setCurrentIndex(max(combo.findData(""), 0))
            panel = dialog.controls[means.ENABLED][1]
            panel.enabled.setChecked(True)
            for row in range(panel.factor_list.count()):
                item = panel.factor_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) in ("A", "B"):
                    item.setCheckState(Qt.CheckState.Checked)
            panel.overall.setChecked(True)
            panel.confidence.setText("95")
            dialog.accept()
            return True

        with self.drive(build):
            self.window.analyze(method=METHOD)
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        sheet = run.result.tables[means.SHEET]
        assert_close(combination(sheet, A="A0", B="B0"), ORACLE["expected"]["A0 B0"])
        assert_close(overall(sheet), ORACLE["expected"]["Globale"])
        self.assertNotIn("Multiple comparisons", run.result.tables)
        csv_path = self.folder / "means.csv"
        safe_csv(csv_path, sheet)
        # Blank cells and an empty Reason are both empty in the CSV; read_csv turns both into NaN.
        exported = sheet.reset_index(drop=True).astype(object)
        exported = exported.mask(exported.map(lambda value: value == ""), float("nan"))
        assert_frame_equal(pd.read_csv(csv_path), exported, check_dtype=False)
        confirmed, result = deepcopy(run.options), run.result

        def cancel(dialog):
            dialog.controls[means.ENABLED][1].enabled.setChecked(False)
            self.assertFalse(set(means.KEYS) & set(dialog.options()))
            dialog.reject()
            return False

        with self.drive(cancel):
            self.window.change_parameters()
        self.wait()
        self.assertEqual(run.options, confirmed)

        saved = self.folder / "saved.alab"
        self.window.project.save(saved)
        set_language("it")
        self.window.open_path(saved)
        self.app.processEvents()
        index = next(i for i, item in enumerate(self.window.project.runs) if item.method == METHOD)
        self.window.open_sheet(("result", index))
        self.wait()
        reopened = self.window.project.runs[index]
        self.assertEqual(reopened.options, confirmed)
        assert_frame_equal(reopened.result.tables[means.SHEET], result.tables[means.SHEET])
        self.assertEqual(means.SHEET, "Estimated marginal means")

        self.window.open_sheet(("data", "Oracle"))
        model = self.window.sheet.model()
        self.assertTrue(model.setData(model.index(0, 2), "2"))
        self.app.processEvents()
        self.wait()
        self.window.sheet.setCurrentIndex(model.index(2, 2))
        self.window.toggle_exclusion()
        self.app.processEvents()
        self.wait()
        after = self.window.project.runs[index]
        self.assertIsNone(after.calculation_error)
        fresh = analyse(METHOD, self.window.project.tables["Oracle"].frame(mask_excluded=True), after.options)
        assert_frame_equal(after.result.tables[means.SHEET], fresh.tables[means.SHEET])
        self.assertNotAlmostEqual(float(after.result.tables[means.SHEET]["Estimate"].iloc[0]),
                                  float(sheet["Estimate"].iloc[0]), delta=1e-8)

        legacy_path = self.folder / "legacy.alab"
        legacy = {"Response": "Y", "Factors": ["A", "B"], "Interaction order": 2}
        save_project(legacy_path, {"Oracle": Dataset(oracle_frame(), analyses=[(METHOD, deepcopy(legacy))])})
        set_language("en")
        self.window.open_path(legacy_path)
        self.app.processEvents()
        self.window.open_sheet(("result", 0))
        self.wait()
        before = self.window.project.runs[0].result
        self.assertNotIn(means.SHEET, before.tables)

        def unchanged(dialog):
            self.assertFalse(dialog.controls[means.ENABLED][1].enabled.isChecked())
            dialog.accept()
            return True

        with self.drive(unchanged):
            self.window.change_parameters()
        self.wait()
        kept = self.window.project.runs[0]
        for key in means.KEYS:
            self.assertNotIn(key, kept.options)
        self.assertEqual(list(kept.result.tables), list(before.tables))
        for name in before.tables:
            assert_frame_equal(kept.result.tables[name], before.tables[name])
