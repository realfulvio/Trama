"""Multifactor ANOVA in the Qt dialog: model terms, Type I factor order, errors, Cancel, save and reopen.

Offscreen; skipped when PySide6 (or the Qt platform libraries) are missing. The data are the synthetic
2×2 designs of the 0.95 acceptance: factor names with ``$`` and `` : `` must stay literal everywhere.
"""
from contextlib import contextmanager
from copy import deepcopy
from itertools import combinations
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi.anova_terms import FULL, MODEL_TERMS, SELECTED, TERM_SELECTION, label
from analisi.anova_ss import KEY as SUMS_OF_SQUARES, TYPE_I, TYPE_II
from analisi.i18n import active_language, set_language

METHOD = "Multifactor ANOVA"
A, B, C = "Treatment $", "Visit : phase", "Site & lab"
BALANCED = pd.DataFrame({
    "Response": [9, 11, 13, 15, 15, 17, 23, 25],
    A: ["Control"] * 4 + ["Drug"] * 4,
    B: ["Start", "Start", "End", "End"] * 2})
UNBALANCED = pd.concat([BALANCED, pd.DataFrame({"Response": [12, 22, 26], A: ["Control", "Drug", "Drug"],
                                                B: ["Start", "End", "End"]})], ignore_index=True)
RECIPE = {"Response": "Response", "Factors": [B, A], "Interaction order": 2, "Sums of squares": "Type I",
          "Term selection": "Selected terms", "Model terms": [[B], [A], [B, A]]}
LEGACY = {"Response": "Response", "Factors": [A, B], "Interaction order": 2}


def _rss(frame, terms):
    """Residual sum of squares of an intercept plus ±1-coded terms (two-level factors), by least squares."""
    columns = [np.ones(len(frame))]
    for term in terms:
        columns.append(np.prod([np.where(frame[name] == sorted(frame[name].unique())[0], 1.0, -1.0)
                                for name in term], axis=0))
    x = np.column_stack(columns)
    y = frame["Response"].to_numpy(float)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    return float(np.sum((y - x @ beta) ** 2))


def _sequential(frame, first, second):
    """Independent Type I sums of squares for the order ``first``, ``second``, then the interaction."""
    terms = [[first], [second], [first, second]]
    return [_rss(frame, terms[:i]) - _rss(frame, terms[:i + 1]) for i in range(3)], _rss(frame, terms)


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


def _choose(dialog, field, value):
    combo = dialog.controls[field][1]
    index = combo.findData(value)
    assert index >= 0, (field, value)
    combo.setCurrentIndex(index)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtAnovaDialogTests(unittest.TestCase):
    """The dialog alone: editors, recipe, draft, errors and focus."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.language = active_language()
        self.addCleanup(set_language, self.language)

    def dialog(self, frame, recipe=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, frame, current=(METHOD, recipe if recipe is not None else {}), only=METHOD)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_saved_recipe_is_kept_in_both_languages(self):
        for language in ("en", "it"):
            set_language(language)
            saved = deepcopy(RECIPE)
            dialog = self.dialog(UNBALANCED, saved)
            kind, editor = dialog.controls[MODEL_TERMS]
            self.assertNotEqual(kind, "kept")
            self.assertIs(type(editor).__name__, "TermEditor")
            self.assertEqual(dialog.options(), {**dialog.options(), **RECIPE}, language)
            self.assertEqual(saved, RECIPE)  # the dialog works on copies
            # The check boxes and the summary show the literal names, in the saved factor order.
            self.assertEqual([box.text() for box in editor.boxes.values()],
                             [label((B,)), label((A,)), label((B, A))])
            self.assertIn(label((B, A)), editor.summary.text())
            self.assertFalse(dialog.anova.order.box.isHidden())
            self.assertEqual([dialog.anova.order.list.item(i).text() for i in range(2)], [B, A])
            # Interaction order is out of sight under Selected terms, and its saved value is kept.
            self.assertTrue(dialog.rows["Interaction order"][1].isHidden())
            self.assertEqual(dialog.options()["Interaction order"], 2)
        set_language("it")
        dialog = self.dialog(UNBALANCED, deepcopy(RECIPE))
        self.assertEqual(dialog.rows[MODEL_TERMS][0].text(), "Termini del modello")
        self.assertEqual(dialog.controls[SUMS_OF_SQUARES][1].currentText(), "Tipo I")

    def test_legacy_recipe_stays_implicit(self):
        dialog = self.dialog(BALANCED, deepcopy(LEGACY))
        options = dialog.options()
        for key in (TERM_SELECTION, SUMS_OF_SQUARES, MODEL_TERMS):
            self.assertNotIn(key, options)
        self.assertEqual(options["Factors"], [A, B])
        self.assertEqual(options["Interaction order"], 2)
        self.assertTrue(dialog.anova.order.box.isHidden())  # Type III: no factor order to set
        editor = dialog.controls[MODEL_TERMS][1]
        self.assertTrue(editor.tools.isHidden())
        self.assertIn(label((A, B)), editor.summary.text())  # Full hierarchy of order 2

    def test_hierarchy_error_focus_and_correction(self):
        dialog = self.dialog(UNBALANCED)
        _tick(dialog, [A, B])
        _choose(dialog, TERM_SELECTION, SELECTED)
        editor = dialog.controls[MODEL_TERMS][1]
        self.assertEqual(editor.values(), [[A], [B]])  # starts from the Full hierarchy of Interaction order 1
        editor.boxes[(A, B)].setChecked(True)
        editor.boxes[(A,)].setChecked(False)
        editor.boxes[(B,)].setChecked(False)
        self.assertEqual(editor.values(), [[A, B]])
        self.assertTrue(editor.add_button.isEnabled())
        self.assertIn(label((A,)), editor.problem.text())
        dialog.tabs.setCurrentIndex(0)
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertIn("strong hierarchy", dialog.banner.text())
        self.assertEqual(dialog.tabs.currentIndex(), 1)
        self.assertIs(dialog.focusWidget(), editor.add_button)
        QTest.keyClick(editor.add_button, Qt.Key.Key_Space)
        self.assertEqual(editor.values(), [[A], [B], [A, B]])
        self.assertFalse(editor.add_button.isEnabled())
        dialog.accept()
        self.assertEqual(dialog.result[1][MODEL_TERMS], [[A], [B], [A, B]])

    def test_italian_error_is_translated(self):
        set_language("it")
        dialog = self.dialog(UNBALANCED)
        _tick(dialog, [A, B])
        _choose(dialog, TERM_SELECTION, SELECTED)
        editor = dialog.controls[MODEL_TERMS][1]
        editor.boxes[(A, B)].setChecked(True)
        editor.boxes[(A,)].setChecked(False)
        dialog.accept()
        self.assertIn("gerarchia forte", dialog.banner.text())
        self.assertTrue(dialog.banner.text().startswith("Termini del modello"))

    def test_draft_survives_mode_switch_and_factor_changes(self):
        frame = UNBALANCED.assign(**{C: ["North", "South"] * 5 + ["North"]})
        dialog = self.dialog(frame)
        _tick(dialog, [A, B, C])
        _choose(dialog, TERM_SELECTION, SELECTED)
        editor = dialog.controls[MODEL_TERMS][1]
        self.assertEqual(len(editor.boxes), 3 + 3 + 1)
        self.assertIn(label((A, C)).replace("&", "&&"), [box.text() for box in editor.boxes.values()])
        editor.clear()
        for term in ((A,), (B,), (C,), (A, C)):
            editor.boxes[term].setChecked(True)
        # Full hierarchy and back keeps the draft.
        _choose(dialog, TERM_SELECTION, FULL)
        self.assertTrue(editor.tools.isHidden())
        self.assertFalse(dialog.rows["Interaction order"][1].isHidden())
        _choose(dialog, TERM_SELECTION, SELECTED)
        self.assertEqual(editor.values(), [[A], [B], [C], [A, C]])
        # Unticking C sets A:C aside, shown and kept, never dropped silently.
        _tick(dialog, [A, B])
        self.assertEqual(editor.values(), [[A], [B], [C], [A, C]][:2] + [[C], [A, C]])
        self.assertIn(label((A, C)), editor.unavailable_note.text())
        self.assertFalse(editor.remove_button.isHidden())
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), editor.remove_button)
        # Ticking C again brings the terms back; then remove them explicitly after unticking.
        _tick(dialog, [A, B, C])
        self.assertEqual(editor.values(), [[A], [B], [C], [A, C]])
        self.assertTrue(editor.remove_button.isHidden())
        _tick(dialog, [A, B])
        editor.remove_button.click()
        self.assertEqual(editor.values(), [[A], [B]])
        dialog.accept()
        self.assertEqual(dialog.result[1][MODEL_TERMS], [[A], [B]])

    def test_factor_order_keeps_places_and_keyboard(self):
        frame = UNBALANCED.assign(**{C: ["North", "South"] * 5 + ["North"]})
        dialog = self.dialog(frame)
        _tick(dialog, [A, B])
        _choose(dialog, SUMS_OF_SQUARES, TYPE_I)
        order = dialog.anova.order
        self.assertFalse(order.box.isHidden())
        self.assertIn("→", order.preview.text())
        order.list.setFocus()
        order.list.setCurrentRow(0)
        QTest.keyClick(order.list, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(order.ordered(), [B, A])
        self.assertEqual(dialog.options()["Factors"], [B, A])
        # A deselected factor keeps its place; one ticked for the first time goes last.
        _tick(dialog, [A])
        _tick(dialog, [A, B])
        self.assertEqual(dialog.options()["Factors"], [B, A])
        _tick(dialog, [A, B, C])
        self.assertEqual(dialog.options()["Factors"], [B, A, C])
        dialog.controls["Interaction order"][1].setText("2")
        order.list.setCurrentRow(2)
        order.up.click()
        self.assertEqual(dialog.options()["Factors"], [B, C, A])
        self.assertEqual(order.preview.text().count("→"), 5)  # three main effects and three two-way terms
        _choose(dialog, SUMS_OF_SQUARES, TYPE_II)
        self.assertTrue(order.box.isHidden())
        self.assertIn("Type II", order.note.text())

    def test_orphan_term_of_a_saved_recipe(self):
        saved = {**deepcopy(RECIPE), "Model terms": [[B], [A], [B, A], ["Ghost"]]}
        dialog = self.dialog(UNBALANCED, saved)
        editor = dialog.controls[MODEL_TERMS][1]
        self.assertIn("Ghost", editor.unavailable_note.text())
        self.assertEqual(dialog.options()[MODEL_TERMS][-1], ["Ghost"])
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("Ghost", dialog.banner.text())
        editor.remove_button.click()
        dialog.accept()
        self.assertEqual(dialog.result[1][MODEL_TERMS], RECIPE["Model terms"])

    def test_engine_limits(self):
        frame = pd.DataFrame({"Response": np.arange(20.0), **{f"F{i}": ["a", "b"] * 10 for i in range(9)}})
        dialog = self.dialog(frame)
        _tick(dialog, [f"F{i}" for i in range(9)])
        _choose(dialog, TERM_SELECTION, SELECTED)
        editor = dialog.controls[MODEL_TERMS][1]
        self.assertEqual(editor.boxes, {})
        self.assertIn("eight", editor.summary.text())
        _tick(dialog, [f"F{i}" for i in range(4)])
        self.assertEqual(len(editor.boxes), 4 + 6 + 4)  # no four-way term: interactions go up to order 3
        self.assertEqual(max(len(term) for term in editor.boxes), 3)

    def test_error_reopened_from_the_worker_is_focused(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language("it")
        dialog = AnalysisDialog(None, UNBALANCED, current=(METHOD, deepcopy(RECIPE)), only=METHOD,
                                error="The selected model cannot be identified. Check empty cells and redundant terms.",
                                error_field=MODEL_TERMS)
        self.addCleanup(dialog.deleteLater)
        self.assertIn("non è identificabile", dialog.banner.text())
        self.assertEqual(dialog.tabs.currentIndex(), 1)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtAnovaWindowTests(unittest.TestCase):
    """The whole flow in the window: dialog, worker, results, Cancel, save, reopen and recalculation."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
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
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def open_frame(self, frame, name):
        path = self.folder / f"{name}.csv"
        frame.to_csv(path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        self.assertEqual(self.window.selected, ("data", name))

    @contextmanager
    def drive(self, *steps):
        """Each dialog the window opens runs the next step instead of waiting for a click."""
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

    def test_balanced_full_hierarchy_then_main_effects(self):
        self.open_frame(BALANCED, "balanced")

        def full(dialog):
            _tick(dialog, [A, B])
            dialog.controls["Interaction order"][1].setText("2")
            dialog.accept()
            return True

        with self.drive(full):
            self.window.analyze(method=METHOD)
        self.wait()
        run = self.window.project.runs[-1]
        table = run.result.tables["ANOVA (type III)"]
        np.testing.assert_allclose(table["F"].drop("Residual").to_numpy(float), [64, 36, 4])
        self.assertEqual(run.options["Factors"], [A, B])
        for key in (TERM_SELECTION, SUMS_OF_SQUARES, MODEL_TERMS):
            self.assertNotIn(key, run.options)

        def main_effects(dialog):
            _choose(dialog, TERM_SELECTION, SELECTED)
            dialog.controls[MODEL_TERMS][1].boxes[(A, B)].setChecked(False)
            dialog.accept()
            return True

        with self.drive(main_effects):
            self.window.change_parameters()
        self.wait()
        run = self.window.project.runs[-1]
        table = run.result.tables["ANOVA (type III)"]
        self.assertAlmostEqual(table.loc[label((A,)), "F"], 40)
        self.assertAlmostEqual(table.loc[label((B,)), "F"], 22.5)
        self.assertEqual(list(run.result.tables["Model terms"].index), [label((A,)), label((B,))])
        self.assertEqual(run.options[MODEL_TERMS], [[A], [B]])
        self.assertEqual(run.options["Interaction order"], 2)  # kept from the recipe for Full hierarchy

    def test_unbalanced_type_one_order(self):
        self.open_frame(UNBALANCED, "unbalanced")
        runs = []

        def type_one(move, kind=TYPE_I):
            def step(dialog):
                _tick(dialog, [A, B])
                dialog.controls["Interaction order"][1].setText("2")
                _choose(dialog, SUMS_OF_SQUARES, TYPE_I)  # the order is set under Type I and kept after
                if move:
                    dialog.anova.order.list.setCurrentRow(0)
                    dialog.anova.order.down.click()
                _choose(dialog, SUMS_OF_SQUARES, kind)
                dialog.accept()
                return True
            return step

        for move, kind in ((False, TYPE_I), (True, TYPE_I), (False, TYPE_II), (True, TYPE_II)):
            self.window.open_sheet(("data", "unbalanced"))
            with self.drive(type_one(move, kind)):
                self.window.analyze(method=METHOD)
            self.wait()
            runs.append(self.window.project.runs[-1])
        self.assertEqual(runs[0].options["Factors"], [A, B])
        self.assertEqual(runs[1].options["Factors"], [B, A])
        self.assertEqual(runs[3].options["Factors"], [B, A])
        first, second = (run.result.tables["ANOVA (type I)"] for run in runs[:2])
        (ss_a, ss_b, ss_ab), rss = _sequential(UNBALANCED, A, B)
        (ss_b2, ss_a2, ss_ab2), rss2 = _sequential(UNBALANCED, B, A)
        np.testing.assert_allclose(first["SS"].to_numpy(float), [ss_a, ss_b, ss_ab, rss], rtol=1e-10)
        np.testing.assert_allclose(second["SS"].to_numpy(float), [ss_b2, ss_a2, ss_ab2, rss2], rtol=1e-10)
        self.assertGreater(abs(ss_a - ss_a2), 1)  # the order changes the Type I SS of the factor
        self.assertAlmostEqual(first.loc["Residual", "SS"], second.loc["Residual", "SS"], places=10)
        two, two_moved = (run.result.tables["ANOVA (type II)"]["SS"].to_numpy(float) for run in runs[2:])
        np.testing.assert_allclose(two, two_moved[[1, 0, 2, 3]], rtol=1e-10)  # A, B, A:B, Residual

    def test_interaction_only_error_then_cancelled_reorder(self):
        self.open_frame(UNBALANCED, "unbalanced")
        seen = {}

        def interaction_only(dialog):
            _tick(dialog, [A, B])
            _choose(dialog, TERM_SELECTION, SELECTED)
            editor = dialog.controls[MODEL_TERMS][1]
            editor.boxes[(A, B)].setChecked(True)
            editor.boxes[(A,)].setChecked(False)
            editor.boxes[(B,)].setChecked(False)
            dialog.accept()
            seen["error"], seen["focus"] = dialog.banner.text(), dialog.focusWidget()
            self.assertIs(seen["focus"], editor.add_button)
            editor.add_button.click()
            dialog.accept()
            return True

        with self.drive(interaction_only):
            self.window.analyze(method=METHOD)
        self.wait()
        self.assertIn(label((A, B)), seen["error"])
        run = self.window.project.runs[-1]
        self.assertEqual(list(run.result.tables["Model terms"].index), [label((A,)), label((B,)), label((A, B))])
        confirmed, result = deepcopy(run.options), run.result

        def reorder_then_cancel(dialog):
            _choose(dialog, SUMS_OF_SQUARES, TYPE_I)
            dialog.anova.order.list.setCurrentRow(0)
            dialog.anova.order.down.click()
            dialog.controls[MODEL_TERMS][1].boxes[(B, A)].setChecked(False)  # terms follow the new order
            self.assertEqual(dialog.options()["Factors"], [B, A])
            dialog.reject()
            return False

        with self.drive(reorder_then_cancel):
            self.window.change_parameters()
        self.wait()
        self.assertEqual(run.options, confirmed)
        self.assertIs(self.window.project.runs[-1].result, result)

        def reopen(dialog):  # the next opening starts again from the confirmed recipe
            self.assertEqual(dialog.options()["Factors"], [A, B])
            self.assertEqual(dialog.options()[MODEL_TERMS], confirmed[MODEL_TERMS])
            dialog.reject()
            return False

        with self.drive(reopen):
            self.window.change_parameters()

    def test_legacy_and_selected_recipes_edit_exclude_save_reopen(self):
        from analisi.data import Dataset, save_project
        from trama_qt.window import safe_csv
        path = self.folder / "demo.alab"
        save_project(path, {"Synthetic data": Dataset(UNBALANCED, analyses=[(METHOD, deepcopy(LEGACY)),
                                                                            (METHOD, deepcopy(RECIPE))])})
        window = self.window
        window.open_path(path)
        self.app.processEvents()
        for index in (0, 1):
            window.open_sheet(("result", index))
            self.wait()
            self.assertIsNotNone(window.project.runs[index].result)
        legacy, selected = window.project.runs[:2]
        self.assertEqual(legacy.options, LEGACY)
        self.assertEqual(selected.options, RECIPE)
        self.assertIn("ANOVA (type I)", selected.result.tables)
        # Reopening the legacy analysis and confirming it unchanged adds none of the new keys.
        window.open_sheet(("result", 0))

        def unchanged(dialog):
            dialog.accept()
            return True

        with self.drive(unchanged):
            window.change_parameters()
        self.wait()
        legacy = window.project.runs[0]
        for key in (TERM_SELECTION, SUMS_OF_SQUARES, MODEL_TERMS):
            self.assertNotIn(key, legacy.options)
        before = legacy.result.tables["ANOVA (type III)"]["SS"].copy()
        # A cell edit and an excluded cell recalculate both analyses.
        window.open_sheet(("data", "Synthetic data"))
        model = window.sheet.model()
        self.assertTrue(model.setData(model.index(8, 0), "14"))
        self.app.processEvents()
        self.wait()
        window.sheet.setCurrentIndex(model.index(9, 0))
        window.toggle_exclusion()
        self.app.processEvents()
        self.wait()
        for run in window.project.runs[:2]:
            self.assertIsNone(run.calculation_error)
        self.assertEqual(window.project.runs[1].result.tables["Model terms"].shape[0], 3)
        self.assertFalse(np.allclose(window.project.runs[0].result.tables["ANOVA (type III)"]["SS"], before))
        n_selected = window.project.runs[1].result.tables["ANOVA (type I)"].loc["Residual", "df"]
        self.assertEqual(n_selected, len(UNBALANCED) - 1 - 3 - 1)
        # Save, reopen: the factor orders and the literal term names come back.
        saved = self.folder / "reopened.alab"
        window.project.save(saved)
        table_csv, data_csv = self.folder / "type-one.csv", self.folder / "data.csv"
        safe_csv(table_csv, window.project.runs[1].result.tables["ANOVA (type I)"], index=True)
        safe_csv(data_csv, window.project.tables["Synthetic data"].frame(mask_excluded=True))
        window.open_path(saved)
        self.app.processEvents()
        self.assertEqual([run.options["Factors"] for run in window.project.runs[:2]], [[A, B], [B, A]])
        self.assertEqual(window.project.runs[1].options[MODEL_TERMS], RECIPE["Model terms"])
        self.assertIn((9, 0), window.project.tables["Synthetic data"].excluded)
        window.open_sheet(("result", 1))
        self.wait()
        self.assertEqual(list(pd.read_csv(table_csv, index_col=0).index),
                         [label((B,)), label((A,)), label((B, A)), "Residual"])
        window.open_path(data_csv)
        self.app.processEvents()
        self.assertEqual(list(window.project.tables["data"].frame().columns), ["Response", A, B])


class OracleTests(unittest.TestCase):
    """The independent reference of these tests reproduces the published F values of the fixtures."""

    def test_reference(self):
        terms = [[A], [B], [A, B]]
        error = _rss(BALANCED, terms)
        f = [(_rss(BALANCED, terms[:i]) - _rss(BALANCED, terms[:i + 1])) / (error / 4) for i in range(3)]
        np.testing.assert_allclose(f, [64, 36, 4])
        error = _rss(BALANCED, terms[:2])
        f = [(_rss(BALANCED, terms[:i]) - _rss(BALANCED, terms[:i + 1])) / (error / 5) for i in range(2)]
        np.testing.assert_allclose(f, [40, 22.5])
        self.assertTrue(all(len(term) <= 3 for size in (1, 2) for term in combinations([A, B], size)))


if __name__ == "__main__":
    unittest.main()
