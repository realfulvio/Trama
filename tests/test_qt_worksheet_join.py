"""Join worksheets by key in the Qt window: dialog, recalculation, persistence, families and relinking.

Offscreen; skipped when PySide6 (or the Qt platform libraries) are missing. The project is the synthetic
``tests/data/worksheet_join/unione-campioni.alab``: "Misure $" on the left, "Anagrafica | visite" on the right.
"""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi import worksheet_join as wj
from analisi.analysis_chain import ResultSource
from analisi.i18n import active_language, set_language

FIXTURE = Path(__file__).parent / "data" / "worksheet_join" / "unione-campioni.alab"
LEFT, RIGHT = "Misure $", "Anagrafica | visite"
FULL_ROWS = [[1, "A", 10, "L1", 100, "A1"], [1, "A", 10, "L1", 101, "A2"], [1, "B", 20, "L2", None, None],
             ["1", "A", 30, "L3", 102, "A3"], [None, "A", 40, "L4", None, None], [2, "C", 50, "L5", None, None],
             [None, "A", None, None, 200, "A4"], [3, "D", None, None, 300, "A5"]]
FULL_LEFT = FULL_ROWS[:6]
COLUMNS = ["Sample", "Visit", "Signal", "Signal [right]", "Signal [right 2]", "Batch $"]


def rows(table):
    return [[None if pd.isna(value) else value for value in row] for row in table.itertuples(index=False, name=None)]


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def choose(box, value):
    position = box.findData(value)
    assert position >= 0, (box.objectName(), value)
    box.setCurrentIndex(position)


def fill(dialog, *, sheet=RIGHT, pairs=(("Sample", "ID"), ("Visit", "Time")), kind="Full", rule="One-to-many"):
    """What a user does in the dialog: the right sheet, one row per key pair, the join type and cardinality."""
    editor = dialog.join
    if sheet is not None:
        choose(editor.sheet, sheet)
    if pairs is not None:
        while len(editor.pairs.pairs) < len(pairs):
            editor.pairs.add_button.click()
        while len(editor.pairs.pairs) > len(pairs):
            editor.pairs.pairs[-1][3].click()
        for (_, left_box, right_box, _), (left, right) in zip(editor.pairs.pairs, pairs):
            choose(left_box, left)
            choose(right_box, right)
    if kind is not None:
        choose(editor.kind, kind)
    if rule is not None:
        choose(editor.rule, rule)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtJoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.language = active_language()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()
        self.window.open_path(FIXTURE)
        self.app.processEvents()

    def _close(self):
        set_language(self.language)
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    @contextmanager
    def dialogs(self, *steps):
        """Answer the analysis dialogs that open, in order: each step fills a dialog and returns True to
        press Run, False to cancel. Errors reopen the dialog, so a step sees the banner of the last one."""
        from trama_qt.analysis_dialog import AnalysisDialog
        pending = list(steps)
        seen = []

        def run(dialog):
            self.assertTrue(pending, f"unexpected dialog: {dialog.banner.text()}")
            seen.append(dialog)
            step = pending.pop(0)
            if not step(dialog):
                return AnalysisDialog.DialogCode.Rejected
            dialog.accept()
            return AnalysisDialog.DialogCode.Accepted if dialog.result else AnalysisDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", run):
            yield seen
        self.assertFalse(pending, "a dialog did not open")

    def create_join(self, **choices):
        window = self.window
        window.show_sheet("data", LEFT)

        def step(dialog):
            self.assertEqual(dialog.method, wj.METHOD)
            self.assertEqual(list(dialog.join.sources), [RIGHT])
            fill(dialog, **choices)
            return True

        with self.dialogs(step):
            window.analyze(wj.METHOD)
            self.wait()
        return window.project.runs[-1]

    # -- dialog and first calculation -----------------------------------------------------------------
    def test_full_one_to_many_matches_the_oracle(self):
        run = self.create_join()
        self.assertEqual(run.method, wj.METHOD)
        self.assertIsNone(run.calculation_error)
        joined = run.result.tables[wj.JOINED]
        self.assertEqual(joined.columns.tolist(), COLUMNS)
        self.assertEqual(rows(joined), FULL_ROWS)
        self.assertEqual(rows(run.result.tables[wj.PROVENANCE])[-2:], [[None, 4, "Right only"],
                                                                         [None, 5, "Right only"]])
        self.assertEqual(run.options, {wj.RIGHT_SHEET: RIGHT, wj.LEFT_KEYS: ["Sample", "Visit"],
                                       wj.RIGHT_KEYS: ["ID", "Time"], wj.JOIN_TYPE: "Full",
                                       wj.CARDINALITY: "One-to-many"})
        self.assertEqual(self.window.selected, ("result", 0))
        self.assertEqual([self.window.result_tabs.tabText(i) for i in range(3)], [wj.JOINED, wj.PROVENANCE,
                                                                                    wj.DIAGNOSTICS])

    def test_dialog_defaults_columns_after_source_change_and_pair_rows(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        project = self.window.project
        project.new_table("Other sheet")
        frame = project.tables[LEFT].frame(mask_excluded=True)
        dialog = AnalysisDialog(self.window, frame, current=(wj.METHOD, {}),
                                join_sources=project.join_sources(LEFT), join_left=LEFT)
        self.addCleanup(dialog.deleteLater)
        editor = dialog.join
        self.assertEqual(list(editor.sources), [RIGHT, "Other sheet"])
        self.assertEqual(editor.kind.currentData(), "Left")
        self.assertEqual(editor.rule.currentData(), "One-to-one")
        self.assertEqual(len(editor.pairs.pairs), 1)
        choose(editor.sheet, RIGHT)
        right_box = editor.pairs.pairs[0][2]
        self.assertEqual([right_box.itemData(i) for i in range(right_box.count())], ["ID", "Time", "Signal",
                                                                                        "Batch $"])
        choose(right_box, "Batch $")
        choose(editor.sheet, "Other sheet")
        self.assertEqual([right_box.itemData(i) for i in range(right_box.count())],
                         ["Column 1", "Column 2", "Column 3"])
        for _ in range(5):
            editor.pairs.add_button.click()
        self.assertEqual(len(editor.pairs.pairs), wj.MAX_KEYS)
        self.assertFalse(editor.pairs.add_button.isEnabled())
        # Each pair is one row of the grid: caption, left column, right column, remove.
        grid = editor.pairs.grid
        for row, (caption, left_box, right_box, remove) in enumerate(editor.pairs.pairs, 1):
            self.assertEqual({grid.getItemPosition(grid.indexOf(widget))[0]
                              for widget in (caption, left_box, right_box, remove)}, {row})
        editor.pairs.pairs[1][3].click()
        self.assertEqual(len(editor.pairs.pairs), 3)
        self.assertEqual(editor.pairs.pairs[1][0].text(), "Pair 2")

    def test_dialog_checks_and_focuses_the_wrong_pair(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        project = self.window.project
        frame = project.tables[LEFT].frame(mask_excluded=True)
        dialog = AnalysisDialog(self.window, frame, current=(wj.METHOD, {}),
                                join_sources=project.join_sources(LEFT), join_left=LEFT)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        fill(dialog, pairs=(("Sample", "ID"), ("Sample", "Time")))
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertIn("Pair 2", dialog.banner.text())
        self.app.processEvents()
        self.assertIs(dialog.focusWidget(), dialog.join.pairs.pairs[1][1])
        choose(dialog.join.pairs.pairs[1][1], "Visit")
        dialog.accept()
        self.assertEqual(dialog.result[1][wj.LEFT_KEYS], ["Sample", "Visit"])

    def test_one_to_one_error_is_corrected_in_the_same_dialog(self):
        def first(dialog):
            fill(dialog, kind="Full", rule="One-to-one")
            return True

        def second(dialog):
            self.assertIn("The right worksheet repeats a key in rows 1 and 2.", dialog.banner.text())
            self.assertEqual(dialog.tabs.currentIndex(), 1)  # Options, where Join cardinality is
            self.assertEqual(dialog.join.rule.currentData(), "One-to-one")
            self.assertEqual(dialog.join.sheet.currentData(), RIGHT)
            choose(dialog.join.rule, "One-to-many")
            return True

        self.window.show_sheet("data", LEFT)
        with self.dialogs(first, second):
            self.window.analyze(wj.METHOD)
            self.wait()
            self.wait()
        self.assertEqual(len(self.window.project.runs), 1)
        self.assertEqual(rows(self.window.project.runs[0].result.tables[wj.JOINED]), FULL_ROWS)

    def test_change_parameters_inner_left_and_cancel(self):
        run = self.create_join()
        window = self.window
        counts = {}
        for kind in ("Inner", "Left"):
            with self.dialogs(lambda dialog, kind=kind: (fill(dialog, sheet=None, pairs=None, kind=kind, rule=None),
                                                         True)[1]):
                window.change_parameters()
                self.wait()
            counts[kind] = len(window.project.runs[0].result.tables[wj.JOINED])
        self.assertEqual(counts, {"Inner": 3, "Left": 6})
        recipe = dict(window.project.runs[0].options)
        uid = window.project.runs[0].uid

        def cancel(dialog):
            self.assertEqual(dialog.join.kind.currentData(), "Left")
            self.assertEqual(dialog.join.pairs.values(), (["Sample", "Visit"], ["ID", "Time"]))
            fill(dialog, kind="Full", rule="Many-to-many", pairs=(("Sample", "ID"),))
            return False

        with self.dialogs(cancel):
            window.change_parameters()
        self.assertEqual(window.project.runs[0].options, recipe)
        self.assertEqual(window.project.runs[0].uid, uid)
        self.assertIs(run.method, wj.METHOD)

    # -- recalculation ---------------------------------------------------------------------------------
    def edit_cell(self, title, row, column, value):
        window = self.window
        window.show_sheet("data", title)
        model = window.sheet.model()
        self.assertTrue(model.setData(model.index(row, column), value))
        self.app.processEvents()
        self.wait()

    def test_edits_of_either_sheet_recalculate_the_join_and_its_dependents(self):
        window = self.window
        self.create_join(kind="Left")
        join = window.project.runs[0]
        # A dependent analysis that reads the joined table through a link.
        with self.dialogs(lambda dialog: True):
            window._ask(LEFT, join.result.tables[wj.JOINED].copy(), current=("Descriptive statistics",
                                                                            {"Variables": ["Signal"]}),
                        source=ResultSource(join.uid, wj.JOINED))
            self.wait()
        child = window.project.runs[1]
        self.assertEqual(child.source, ResultSource(join.uid, wj.JOINED))
        child_result = child.result

        # Opening the result again does not recalculate anything when nothing changed.
        window.open_sheet(("result", 1))
        self.assertIsNone(window.job)
        self.assertIs(child.result, child_result)

        # Right: change a key (row 5 becomes "1", "A" as typed text, so it now matches left row 3) and a value.
        self.edit_cell(RIGHT, 4, 0, "1")
        self.assertEqual(window.project.tables[RIGHT].raw.iat[4, 0], "1")  # typed into a mixed column: text
        self.edit_cell(RIGHT, 4, 1, "A")
        self.edit_cell(RIGHT, 0, 2, "999")
        joined = window.project.runs[0].result.tables[wj.JOINED]
        self.assertEqual(rows(joined)[0], [1, "A", 10, "L1", 999, "A1"])
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.PROVENANCE])[3:5],
                         [[3, 3, "Matched"], [3, 5, "Matched"]])
        self.assertIsNot(window.project.runs[1].result, child_result)
        after_right = rows(window.project.runs[0].result.tables[wj.JOINED])

        # Left: change a value, then exclude the Visit cell of row 1 (its key becomes incomplete).
        self.edit_cell(LEFT, 0, 2, "11")
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.JOINED])[0][2], 11)
        window.show_sheet("data", LEFT)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.toggle_exclusion()
        self.wait()
        joined = window.project.runs[0].result.tables[wj.JOINED]
        self.assertEqual(rows(joined)[0], [1, None, 11, "L1", None, None])
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.PROVENANCE])[0], [1, None, "Left only"])
        after_left = rows(joined)

        # Undo and Redo go through the join as well: back to the state after the right edits, then forward.
        for _ in range(2):
            window.undo()
            self.wait()
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.JOINED]), after_right)
        for _ in range(3):
            window.undo()
            self.wait()
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.JOINED]), FULL_LEFT)
        for _ in range(5):
            window.undo(redo=True)
            self.wait()
        self.assertEqual(rows(window.project.runs[0].result.tables[wj.JOINED]), after_left)
        self.assertFalse(self.errors)

    def test_refresh_job_carries_both_sources_and_skips_precompute(self):
        self.create_join()
        project = self.window.project
        job = project.plan_refresh(project.table_runs(RIGHT))
        identifier = project.runs[0].uid
        self.assertEqual(job.selected, [identifier])
        self.assertIn(identifier, job.join_data)
        self.assertEqual(job.join_data[identifier].columns.tolist(), ["ID", "Time", "Signal", "Batch $"])
        with mock.patch("trama_qt.project.precompute_analyses", return_value={}) as precompute:
            outcomes = project.run_refresh(job)
        self.assertEqual(precompute.call_args.args[0], [])
        self.assertIsNone(outcomes[identifier].error)

    # -- persistence, sources and copies -------------------------------------------------------------
    def save_and_reopen(self, name="join.alab"):
        window = self.window
        path = self.folder / name
        window.project.save(path)
        self.assertTrue(window.close_project())
        window.open_path(path)
        self.app.processEvents()
        return path

    def test_save_reopen_in_italian_open_result_before_right_sheet(self):
        self.create_join()
        path = self.save_and_reopen()
        set_language("it")
        project = self.window.project
        self.assertEqual(project.runs[0].options[wj.RIGHT_SHEET], RIGHT)
        self.assertIsNone(project.runs[0].result)
        self.window.open_sheet(("result", 0))  # the right sheet was never opened
        self.wait()
        self.assertEqual(rows(project.runs[0].result.tables[wj.JOINED]), FULL_ROWS)
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = project.tables[LEFT].frame(mask_excluded=True)
        dialog = AnalysisDialog(self.window, frame, current=(wj.METHOD, project.runs[0].options),
                                join_sources=project.join_sources(LEFT), join_left=LEFT)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.heading.text(), "Unisci fogli per chiave")
        self.assertEqual(dialog.join.kind.currentText(), "Completa")
        self.assertEqual(dialog.join.rule.currentText(), "Uno a molti")
        self.assertEqual(dialog.join.options(), project.runs[0].options)
        self.assertEqual(Path(project.path), path)

    def test_csv_export_and_use_result_as_data(self):
        from trama_qt.window import safe_csv
        run = self.create_join()
        path = self.folder / "joined.csv"
        safe_csv(path, run.result.tables[wj.JOINED])
        back = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
        self.assertEqual(back.columns.tolist(), COLUMNS)
        self.assertEqual(len(back), len(FULL_ROWS))
        window = self.window
        window.open_sheet(("result", 0))
        window.result_tabs.setCurrentIndex(0)
        window.use_result_as_data()
        title = window.selected[1]
        self.assertEqual(title, wj.JOINED)
        frame = window.project.tables[title].frame(mask_excluded=True)
        self.assertEqual(frame.columns.tolist(), COLUMNS)
        self.assertEqual(rows(frame), FULL_ROWS)
        # The new sheet is an ordinary data sheet: it can be joined again, also with its source sheets.
        self.assertIn(title, window.project.join_sources(LEFT))

    def test_missing_source_is_reported_and_relinked(self):
        self.create_join()
        project = self.window.project
        project.runs[0].options[wj.RIGHT_SHEET] = "Gone $ sheet"
        project.tables[LEFT].analyses[0] = (wj.METHOD, project.runs[0].options)
        self.window.refresh_runs([project.runs[0]])
        self.wait()
        self.assertIn('"Gone $ sheet" is not in this project', project.runs[0].calculation_error)

        def relink(dialog):
            editor = dialog.join
            self.assertEqual(editor.sheet.currentData(), "Gone $ sheet")
            self.assertEqual(editor.sheet.currentText(), "Gone $ sheet (missing)")
            dialog.accept()  # never relinked on its own: Run refuses the missing sheet
            self.assertIsNone(dialog.result)
            self.assertIn('"Gone $ sheet"', dialog.banner.text())
            choose(editor.sheet, RIGHT)
            return True

        self.window.open_sheet(("result", 0))
        with self.dialogs(relink):
            self.window.change_parameters()
            self.wait()
        self.assertIsNone(project.runs[0].calculation_error)
        self.assertEqual(project.runs[0].options[wj.RIGHT_SHEET], RIGHT)

    def test_engine_error_on_reopen_names_the_sheet(self):
        """A recipe whose right sheet disappeared fails with the error on Join right sheet, before the worker."""
        project = self.window.project
        run = project.candidate(LEFT, wj.METHOD, {wj.RIGHT_SHEET: "Nope", wj.LEFT_KEYS: ["Sample"],
                                                  wj.RIGHT_KEYS: ["ID"]})
        data = project.join_data(run)
        self.assertIsInstance(data, wj.FieldError)
        self.assertEqual(data.field, wj.RIGHT_SHEET)
        run.options[wj.RIGHT_SHEET] = LEFT
        self.assertIn("already on the left", str(project.join_data(run)))

    def test_second_tab_with_a_colliding_title_keeps_its_own_sheet(self):
        window = self.window
        self.create_join(kind="Inner")
        first = window.project
        window.new_project()
        self.app.processEvents()
        other = window.project
        self.assertIsNot(other, first)
        other.add_tables({LEFT: pd.DataFrame({"Sample": [1], "Visit": ["A"]}),
                          RIGHT: pd.DataFrame({"ID": [1], "Time": ["A"], "Signal": [-1], "Batch $": ["other"]})})
        window.switch_project(0)
        self.app.processEvents()
        joined = first.runs[0].result.tables[wj.JOINED]
        self.assertNotIn("other", joined["Batch $"].tolist())
        self.assertEqual(first.join_data(first.runs[0])["Batch $"].tolist(), ["A1", "A2", "A3", "A4", "A5"])

    def test_family_copy_and_export_keep_the_right_sheet(self):
        from analisi.family_workflow import duplicate_family, save_family
        from analisi.data import load_workspace
        self.create_join()
        project = self.window.project
        project.sync_links(persist=True)
        infos = tuple(project.info_sheets.values())
        # Duplicate only the left family: the copy keeps reading the original right sheet of this project.
        bundle = duplicate_family(project.tables, project.layouts, infos, ("data", LEFT), name="Copy $")
        copy_recipe = bundle.tables["Copy $"].analyses[0][1]
        self.assertEqual(copy_recipe[wj.RIGHT_SHEET], RIGHT)
        project.apply_family(bundle)
        copy_run = next(run for run in project.runs if run.title == "Copy $")
        self.window.refresh_runs([copy_run])
        self.wait()
        self.assertEqual(rows(copy_run.result.tables[wj.JOINED]), FULL_ROWS)
        # Save family as: the right sheet travels with the export and the join opens on its own.
        path = self.folder / "family.alab"
        save_family(path, project.tables, project.layouts, infos, ("data", LEFT))
        tables, _, _ = load_workspace(path, include_info=True)
        self.assertEqual(set(tables), {LEFT, RIGHT})
        self.assertEqual(tables[RIGHT].analyses, [])
        self.assertEqual(tables[LEFT].analyses[0][1][wj.RIGHT_SHEET], RIGHT)
        # Both sheets copied together: the copy reads the copied right sheet.
        from analisi.family_workflow import _remap_options
        remapped = _remap_options(copy_recipe, {}, 0, 0, {}, {RIGHT: "Copy of right", LEFT: "Copy $"})
        self.assertEqual(remapped[wj.RIGHT_SHEET], "Copy of right")

    def test_classic_window_keeps_the_recipe(self):
        import importlib.util
        if importlib.util.find_spec("tkinter") is None:
            self.skipTest("Tk is not available")
        import tramastat
        run = self.create_join()
        with self.assertRaises(ValueError) as caught:
            tramastat.App.compute(run, self.window.project.tables[LEFT].frame(mask_excluded=True))
        self.assertIn("standard window", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
