"""Planned contrasts of the Multifactor ANOVA in the Qt window (0.96).

Offscreen; skipped when PySide6 (or the Qt platform libraries) are missing. The data are the synthetic 2 × 3
fixture of the 0.96 package (``tests/data/planned_contrasts``): levels with ``$`` and ``|`` stay literal.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from analisi import anova_planned_contrasts as planned
from analisi.i18n import active_language, set_language

METHOD = "Multifactor ANOVA"
DATA = Path(__file__).parent / "data" / "planned_contrasts"
FRAME = pd.read_csv(DATA / "contrasti-pianificati.csv")
FIXTURE = json.loads((DATA / "designs.json").read_text(encoding="utf-8"))
BASE = {"Response": "Score", "Factors": ["Treatment", "Visit"], "Interaction order": 2}
RECIPE = {**BASE, planned.FACTORS: ["Treatment", "Visit"], planned.CONTRASTS: FIXTURE["contrasts"],
          planned.CORRECTION: "Holm", planned.ALPHA: 0.05}


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


@contextmanager
def editors(test, *steps):
    """Each Planned contrasts… editor that opens runs the next step instead of waiting for a click."""
    from trama_qt.planned_contrasts import ContrastEditor
    queue = list(steps)

    def run(editor):
        test.assertTrue(queue, "unexpected contrast editor")
        editor.show()
        QApplication.instance().processEvents()
        accepted = queue.pop(0)(editor)
        if accepted:
            editor.accept()
            return QDialog.DialogCode.Accepted if editor.result_state is not None else QDialog.DialogCode.Rejected
        editor.reject()
        return QDialog.DialogCode.Rejected

    with mock.patch.object(ContrastEditor, "exec", run):
        yield
    test.assertEqual(queue, [], "an editor step did not run")


def build_two_contrasts(test, editor, *, language="en"):
    """Two contrasts in one draft, an error on a weight and its fix, a duplicate and a reorder."""
    app = QApplication.instance()
    test.assertEqual(editor.factors(), ["Treatment", "Visit"])
    editor.add_contrast()
    first = editor.contrast()
    test.assertEqual([w["levels"] for w in first["weights"]],
                     [{"Treatment": "Control $", "Visit": "A"}, {"Treatment": "Control $", "Visit": "B |"}])
    editor.name.setText("Control: B | − A")
    editor._renamed("Control: B | − A")
    editor.set_coefficient(0, "-1")
    editor.set_coefficient(1, "1")
    editor.add_contrast()
    editor._renamed("Treated vs Control $")
    for row, cell in enumerate([("Treated", "A"), ("Control $", "A")]):
        editor.set_level(row, "Treatment", cell[0])
        editor.set_level(row, "Visit", cell[1])
    editor.set_coefficient(0, "1,5" if language == "it" else "1.5")
    editor.set_coefficient(1, "0")  # a zero weight: refused, with the cursor on its row
    app.processEvents()
    test.assertFalse(editor.validate(show=True))
    test.assertTrue(editor.weights_error.isVisible())
    test.assertIn("“Treated vs Control $”", editor.weights_error.text())
    test.assertEqual(editor.table.currentRow(), 1)
    editor.set_coefficient(1, "-3/2")
    test.assertTrue(editor.validate(show=True), editor.weights_error.text())
    test.assertFalse(editor.weights_error.isVisible())
    editor.duplicate()
    test.assertEqual(editor.current, 2)
    test.assertEqual(editor.contrast()["name"],
                     "Treated vs Control $ (copia)" if language == "it" else "Treated vs Control $ (copy)")
    test.assertEqual(editor.items[2]["weights"], editor.items[1]["weights"])
    editor.move(-1)
    editor.move(-1)
    test.assertEqual([item["name"] for item in editor.items][0], editor.contrast()["name"])
    return True


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtContrastDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)

    def dialog(self, frame, recipe):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, frame, current=(METHOD, deepcopy(recipe)), only=METHOD)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_legacy_recipe_gets_none_of_the_keys(self):
        dialog = self.dialog(FRAME, BASE)
        options = dialog.options()
        for key in planned.KEYS:
            self.assertNotIn(key, options)
        panel = dialog.controls[planned.CONTRASTS][1]
        self.assertIn("No planned contrasts", panel.summary.text())
        for key in (planned.CORRECTION, planned.ALPHA, planned.FACTORS):
            self.assertNotIn(key, dialog.controls)  # only the editor shows them

    def test_saved_recipe_round_trips_in_both_languages(self):
        for language in ("en", "it"):
            set_language(language)
            saved = deepcopy(RECIPE)
            dialog = self.dialog(FRAME, saved)
            self.assertEqual({key: dialog.options()[key] for key in planned.KEYS},
                             {key: RECIPE[key] for key in planned.KEYS})
            self.assertEqual(saved, RECIPE)
            panel = dialog.controls[planned.CONTRASTS][1]
            self.assertIn("3", panel.summary.text())
            self.assertIn("Treatment × Visit", panel.summary.text())
            with editors(self, lambda editor: True):
                panel.open_editor()
            self.assertEqual(panel.values(), {key: RECIPE[key] for key in planned.KEYS}, language)

    def test_two_contrasts_error_duplicate_reorder_in_italian(self):
        set_language("it")
        dialog = self.dialog(FRAME, BASE)
        panel = dialog.controls[planned.CONTRASTS][1]
        with editors(self, lambda editor: build_two_contrasts(self, editor, language="it")):
            panel.open_editor()
        options = dialog.options()
        names = [record["name"] for record in options[planned.CONTRASTS]]
        self.assertEqual(names, ["Treated vs Control $ (copia)", "Control: B | − A", "Treated vs Control $"])
        self.assertEqual(options[planned.CONTRASTS][0]["weights"], options[planned.CONTRASTS][2]["weights"])
        self.assertEqual(options[planned.CONTRASTS][2]["weights"],
                         [{"levels": ["Treated", "A"], "coefficient": 1.5},
                          {"levels": ["Control $", "A"], "coefficient": -1.5}])
        self.assertEqual(options[planned.FACTORS], ["Treatment", "Visit"])
        self.assertEqual(options[planned.CORRECTION], "Holm")
        self.assertIn("Contrasti pianificati", dialog.rows[planned.CONTRASTS][0].text())
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_cancelled_editor_keeps_the_draft(self):
        dialog = self.dialog(FRAME, RECIPE)
        panel = dialog.controls[planned.CONTRASTS][1]

        def change_then_cancel(editor):
            editor.remove()
            editor.correction.setCurrentIndex(editor.correction.findData("None"))
            return False

        with editors(self, change_then_cancel):
            panel.open_editor()
        self.assertEqual(dialog.options()[planned.CONTRASTS], RECIPE[planned.CONTRASTS])

    def test_removed_level_stays_readable_until_corrected(self):
        frame = FRAME[FRAME.Visit != "C"].reset_index(drop=True)  # the level C is gone from the data
        dialog = self.dialog(frame, {**RECIPE, planned.CONTRASTS: FIXTURE["contrasts"][2:]})
        panel = dialog.controls[planned.CONTRASTS][1]
        self.assertFalse(panel.notice.isHidden())
        dialog.accept()  # the engine check refuses the level, on the planned contrasts
        self.assertIsNone(dialog.result)
        self.assertIn("“C”", dialog.banner.text())
        self.assertIs(dialog.focusWidget(), panel.button)

        def correct(editor):
            texts = [editor.table.cellWidget(2, 1).itemText(i) for i in range(editor.table.cellWidget(2, 1).count())]
            self.assertIn("C (not in the data)", texts)
            self.assertTrue(editor.level_note.isVisible())
            self.assertTrue(editor.weights_error.isVisible())  # reopened on the problem row
            self.assertEqual(editor.table.currentRow(), 2)
            editor.remove_weight()
            editor.set_coefficient(0, "-1")
            editor.set_coefficient(1, "1")
            return True

        with editors(self, correct):
            panel.open_editor()
        self.assertTrue(panel.notice.isHidden())
        dialog.accept()
        self.assertEqual(dialog.result[1][planned.CONTRASTS][0]["weights"],
                         [{"levels": ["Control $", "A"], "coefficient": -1},
                          {"levels": ["Control $", "B |"], "coefficient": 1}])

    def test_alpha_and_name_errors_show_beside_their_field(self):
        dialog = self.dialog(FRAME, RECIPE)
        panel = dialog.controls[planned.CONTRASTS][1]

        def errors(editor):
            editor.alpha.setText("1,5")
            self.assertFalse(editor.validate())
            self.assertTrue(editor.alpha_error.isVisible())
            self.assertIs(editor.focusWidget(), editor.alpha)
            editor.alpha.setText("0,1")
            editor.select(1)
            editor._renamed(RECIPE[planned.CONTRASTS][0]["name"])
            self.assertFalse(editor.validate())
            self.assertTrue(editor.name_error.isVisible())
            self.assertEqual(editor.current, 1)
            editor._renamed("Distinct")
            return True

        with editors(self, errors):
            panel.open_editor()
        options = dialog.options()
        self.assertEqual(options[planned.ALPHA], 0.1)
        self.assertEqual(options[planned.CONTRASTS][1]["name"], "Distinct")

    def test_engine_error_reopens_on_the_panel_in_italian(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language("it")
        message = "“Difference of differences”: the coefficients add up to 0.5. They must add up to 0."
        dialog = AnalysisDialog(None, FRAME, current=(METHOD, deepcopy(RECIPE)), only=METHOD,
                                error=message, error_field=planned.CONTRASTS)
        self.addCleanup(dialog.deleteLater)
        self.assertIn("devono sommare a 0", dialog.banner.text().lower())
        self.assertIn("0,5", dialog.banner.text())
        self.assertEqual(dialog.tabs.currentIndex(), 1)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtContrastWindowTests(unittest.TestCase):
    """The whole flow from the fixture .alab: Analyze → Multifactor ANOVA, worker, sheets, CSV, Cancel, save,
    reopen in Italian, cell edit and exclusion, legacy recipe with diagnostics, post hoc and figure."""

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
        self.assertEqual(queue, [], "a step did not run")

    def open_fixture(self):
        path = self.folder / "contrasti-pianificati.alab"
        shutil.copy(DATA / "contrasti-pianificati.alab", path)
        self.window.open_path(path)
        self.app.processEvents()
        title = next(iter(self.window.project.tables))
        self.assertEqual(title, "Campioni $ 2 × 3")
        self.window.open_sheet(("data", title))
        return title

    def test_fixture_flow(self):
        from trama_qt.window import safe_csv
        title = self.open_fixture()

        def new_analysis(dialog):
            _tick(dialog, ["Treatment", "Visit"])
            dialog.controls["Interaction order"][1].setText("2")
            panel = dialog.controls[planned.CONTRASTS][1]
            with editors(self, lambda editor: build_two_contrasts(self, editor)):
                panel.open_editor()
            dialog.accept()
            return True

        with self.drive(new_analysis):
            self.window.analyze(method=METHOD)
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        sheet = run.result.tables[planned.SHEET]
        self.assertEqual(sheet["Contrast"].tolist(),
                         ["Treated vs Control $ (copy)", "Control: B | − A", "Treated vs Control $"])
        means = FRAME.groupby(["Treatment", "Visit"])["Score"].mean()
        np.testing.assert_allclose(sheet["Estimate"],
                                   [1.5 * (means["Treated", "A"] - means["Control $", "A"]),
                                    means["Control $", "B |"] - means["Control $", "A"],
                                    1.5 * (means["Treated", "A"] - means["Control $", "A"])])
        self.assertEqual(sheet["Status"].tolist(), ["OK"] * 3)
        self.assertEqual(run.result.tables[planned.WEIGHTS_SHEET].columns.tolist(),
                         ["Contrast", "Treatment", "Visit", "Coefficient"])
        # Both sheets go to CSV with the literal text.
        for name in (planned.SHEET, planned.WEIGHTS_SHEET):
            path = self.folder / f"{name}.csv"
            safe_csv(path, run.result.tables[name])
            assert_frame_equal(pd.read_csv(path), run.result.tables[name].reset_index(drop=True),
                               check_dtype=False)
        confirmed, result = deepcopy(run.options), run.result

        # A change in the editor, then Cancel on the analysis dialog: the confirmed recipe stays.
        def change_then_cancel(dialog):
            panel = dialog.controls[planned.CONTRASTS][1]

            def remove_all(editor):
                while editor.items:
                    editor.remove()
                return True

            with editors(self, remove_all):
                panel.open_editor()
            self.assertNotIn(planned.CONTRASTS, dialog.options())
            dialog.reject()
            return False

        with self.drive(change_then_cancel):
            self.window.change_parameters()
        self.wait()
        self.assertEqual(run.options, confirmed)
        self.assertIs(self.window.project.runs[-1].result, result)

        # Save, reopen in Italian: the same recipe and the same sheets.
        saved = self.folder / "salvato.alab"
        self.window.project.save(saved)
        set_language("it")
        self.window.open_path(saved)
        self.app.processEvents()
        index = next(i for i, item in enumerate(self.window.project.runs) if item.method == METHOD)
        self.window.open_sheet(("result", index))
        self.wait()
        reopened = self.window.project.runs[index]
        self.assertEqual(reopened.options, confirmed)
        for name in (planned.SHEET, planned.WEIGHTS_SHEET):
            assert_frame_equal(reopened.result.tables[name], result.tables[name])

        # A cell edit and an excluded observation recalculate the contrasts.
        title = next(iter(self.window.project.tables))
        self.window.open_sheet(("data", title))
        model = self.window.sheet.model()
        self.assertTrue(model.setData(model.index(9, 2), "5"))  # Treated, A: 2 → 5
        self.app.processEvents()
        self.wait()
        self.window.sheet.setCurrentIndex(model.index(0, 2))  # Control $, A: exclude the 1
        self.window.toggle_exclusion()
        self.app.processEvents()
        self.wait()
        after = self.window.project.runs[index]
        self.assertIsNone(after.calculation_error)
        new = after.result.tables[planned.SHEET]
        control_a, treated_a = np.mean([2, 3]), np.mean([5, 3, 4])
        self.assertAlmostEqual(new["Estimate"].iloc[2], 1.5 * (treated_a - control_a))
        self.assertEqual(int(new["df"].iloc[0]), 18 - 1 - 6)

    def test_legacy_recipe_with_diagnostics_post_hoc_and_figure(self):
        from analisi.data import Dataset, save_project
        legacy = {**BASE, "Compare marginal means by": "Visit", "Correction": "Tukey",
                  "ANOVA residual diagnostics": True, "ANOVA diagnostic graph": "Residuals vs fitted"}
        path = self.folder / "legacy.alab"
        save_project(path, {"Campioni": Dataset(FRAME, analyses=[(METHOD, deepcopy(legacy))])})
        self.window.open_path(path)
        self.app.processEvents()
        self.window.open_sheet(("result", 0))
        self.wait()
        run = self.window.project.runs[0]
        before = run.result

        def unchanged(dialog):
            dialog.accept()
            return True

        with self.drive(unchanged):
            self.window.change_parameters()
        self.wait()
        run = self.window.project.runs[0]
        self.assertEqual({key: run.options[key] for key in legacy}, legacy)
        for key in planned.KEYS:
            self.assertNotIn(key, run.options)
        self.assertEqual(list(run.result.tables), list(before.tables))
        for name in before.tables:
            assert_frame_equal(run.result.tables[name], before.tables[name])
        self.assertIsNotNone(run.result.figure)

        def add_contrasts(dialog):
            panel = dialog.controls[planned.CONTRASTS][1]

            def fixture(editor):
                editor.items = [{"name": c["name"], "weights": [
                    {"levels": dict(zip(["Treatment", "Visit"], w["levels"])), "coefficient": str(w["coefficient"])}
                    for w in c["weights"]]} for c in FIXTURE["contrasts"]]
                editor.fill_list(select=0)
                return True

            with editors(self, fixture):
                panel.open_editor()
            dialog.accept()
            return True

        with self.drive(add_contrasts):
            self.window.change_parameters()
        self.wait()
        run = self.window.project.runs[0]
        self.assertEqual([name for name in run.result.tables if name not in (planned.SHEET, planned.WEIGHTS_SHEET)],
                         list(before.tables))
        self.assertIn("Multiple comparisons", run.result.tables)
        self.assertIn(planned.SHEET, run.result.tables)
        self.assertIsNotNone(run.result.figure)
        np.testing.assert_allclose(run.result.tables[planned.SHEET]["Estimate"], [3, 4, 0], atol=1e-12)
        # The same fixture under Type I, II and III: the contrasts do not change.
        from analisi.workbench import analyse
        sheets = [analyse(METHOD, FRAME, {**run.options, "Sums of squares": kind}).tables[planned.SHEET]
                  for kind in ("Type I", "Type II", "Type III")]
        for other in sheets[1:]:
            assert_frame_equal(other, sheets[0])


if __name__ == "__main__":
    unittest.main()
