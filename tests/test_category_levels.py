"""Tests for category level renaming, merging, recipe blocking, joins, and Qt dialog."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton

from analisi.category_levels import (
    LevelEditDraft,
    LevelEditError,
    apply_level_plan,
    can_rename_levels,
    find_blocking_recipes,
    scan_column_levels,
)
from analisi.category_order import WORKSHEET_ORDERS, set_order
from analisi.data import Dataset, load_workspace, save_project
from analisi.i18n import set_language, tr
from analisi.variable_types import VARIABLE_TYPES
from analisi import worksheet_join
from trama_qt.category_order import CategoryOrderDialog
from trama_qt.project import Project
from trama_qt.window import MainWindow


CASI_JSON = {
    "input": ["A", "B", "A", None, "Controllo $", "Procès"],
    "stored_order": ["Controllo $", "B", "A", "Procès"],
    "swap": {
        "mapping": {"A": "B", "B": "A"},
        "values": ["B", "A", "B", None, "Controllo $", "Procès"],
        "order": ["Controllo $", "A", "B", "Procès"],
    },
    "merge": {
        "mapping": {"A": "Risposta", "B": "Risposta"},
        "confirmation": True,
        "values": ["Risposta", "Risposta", "Risposta", None, "Controllo $", "Procès"],
        "order": ["Controllo $", "Risposta", "Procès"],
    },
    "cancel": {"changes": False},
    "invalid": {"mapping": {"A": ""}, "changes": False},
}


def _load_casi():
    pack_casi = (
        Path(__file__).resolve().parents[2]
        / "trama-gestione-livelli-categorie-pack"
        / "casi.json"
    )
    if pack_casi.is_file():
        return json.loads(pack_casi.read_text(encoding="utf-8"))
    return CASI_JSON


def _casi_dataset(casi):
    ds = Dataset(pd.DataFrame({
        "Gruppo": pd.Series(casi["input"], dtype="string"),
        "Valore": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    }))
    set_order(ds, "Gruppo", [f"str:{v}" for v in casi["stored_order"]])
    return ds


def _series_as_json_values(series):
    out = []
    for v in series.tolist():
        if pd.isna(v):
            out.append(None)
        else:
            out.append(v)
    return out


class CategoryLevelsCoreTests(unittest.TestCase):
    def setUp(self):
        set_language("it")
        self.casi = _load_casi()

    def tearDown(self):
        set_language("en")

    def test_casi_json_swap_merge_cancel_invalid(self):
        casi = self.casi

        # 1. Swap
        ds_swap = _casi_dataset(casi)
        draft = LevelEditDraft(ds_swap, "Gruppo")
        self.assertEqual([e.raw_label for e in draft.levels], casi["stored_order"])
        self.assertEqual([e.count for e in draft.levels], [1, 1, 2, 1])
        draft.apply_mapping(casi["swap"]["mapping"])
        plan = draft.validate()
        self.assertEqual(plan.merges, ())
        apply_level_plan(ds_swap, plan)
        self.assertEqual(_series_as_json_values(ds_swap.raw["Gruppo"]), casi["swap"]["values"])
        self.assertEqual(
            ds_swap.raw.attrs[WORKSHEET_ORDERS]["Gruppo"],
            [f"str:{v}" for v in casi["swap"]["order"]],
        )

        # 2. Merge (first position preserved in order, confirmation required)
        ds_merge = _casi_dataset(casi)
        draft_merge = LevelEditDraft(ds_merge, "Gruppo")
        draft_merge.apply_mapping(casi["merge"]["mapping"])
        plan_merge = draft_merge.validate()
        self.assertEqual(len(plan_merge.merges), 1)
        self.assertEqual(plan_merge.merges[0].target_label, "Risposta")
        self.assertEqual(plan_merge.merges[0].total_count, 3)
        self.assertEqual([s.raw_label for s in plan_merge.merges[0].sources], ["B", "A"])
        self.assertEqual([s.count for s in plan_merge.merges[0].sources], [1, 2])
        apply_level_plan(ds_merge, plan_merge)
        self.assertEqual(_series_as_json_values(ds_merge.raw["Gruppo"]), casi["merge"]["values"])
        self.assertEqual(
            ds_merge.raw.attrs[WORKSHEET_ORDERS]["Gruppo"],
            [f"str:{v}" for v in casi["merge"]["order"]],
        )

        # 3. Cancel / no-op
        ds_cancel = _casi_dataset(casi)
        before_raw = ds_cancel.raw
        draft_cancel = LevelEditDraft(ds_cancel, "Gruppo")
        plan_cancel = draft_cancel.validate()
        self.assertFalse(plan_cancel.has_changes)
        apply_level_plan(ds_cancel, plan_cancel)
        self.assertIs(ds_cancel.raw, before_raw)

        # 4. Invalid empty name
        ds_inv = _casi_dataset(casi)
        draft_inv = LevelEditDraft(ds_inv, "Gruppo")
        draft_inv.apply_mapping(casi["invalid"]["mapping"])
        with self.assertRaises(LevelEditError) as ctx:
            draft_inv.validate()
        self.assertEqual(ctx.exception.token, "str:A")
        self.assertEqual(ctx.exception.code, "empty")
        self.assertEqual(_series_as_json_values(ds_inv.raw["Gruppo"]), casi["input"])

    def test_collision_with_existing_level_requires_confirmation_and_keeps_first_slot(self):
        ds = Dataset(pd.DataFrame({"G": pd.Series(["First", "Middle", "Last", "First"], dtype="string")}))
        set_order(ds, "G", ["str:Last", "str:Middle", "str:First"])
        draft = LevelEditDraft(ds, "G")
        draft.set_target("str:Middle", "First")
        plan = draft.validate()
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual(plan.merges[0].target_label, "First")
        self.assertEqual([s.raw_label for s in plan.merges[0].sources], ["Middle", "First"])
        self.assertEqual(plan.merges[0].total_count, 3)
        apply_level_plan(ds, plan)
        self.assertEqual(ds.raw["G"].tolist(), ["First", "First", "Last", "First"])
        # Middle was before First in stored order -> merged "First" keeps Middle's first slot (index 1).
        self.assertEqual(ds.raw.attrs[WORKSHEET_ORDERS]["G"], ["str:Last", "str:First"])

    def test_ambiguous_mixed_types_and_significant_whitespace_literal(self):
        raw = pd.DataFrame({
            "Mix": pd.Series([1, 1.0, "1", "1.0", True, " A ", "A", None], dtype=object),
        })
        ds = Dataset(raw)
        entries = scan_column_levels(ds.raw, "Mix")
        by_token = {e.token: e for e in entries}
        self.assertEqual(len(entries), 7)
        self.assertTrue(by_token["int:1"].ambiguous)
        self.assertTrue(by_token["float:1.0"].ambiguous)
        self.assertTrue(by_token["str:1"].ambiguous)
        self.assertTrue(by_token["str:1.0"].ambiguous)
        self.assertTrue(by_token["str: A "].ambiguous)
        self.assertTrue(by_token["str:A"].ambiguous)
        # All display labels must be pairwise distinct.
        displays = [e.display_label for e in entries]
        self.assertEqual(len(displays), len(set(displays)))
        self.assertEqual(by_token["str: A "].display_label, "' A '")

        # Rename only int:1 -> "Uno" and preserve leading/trailing spaces on "  B  "
        draft = LevelEditDraft(ds, "Mix")
        draft.set_target("int:1", "Uno")
        draft.set_target("str: A ", "  B  ")
        plan = draft.validate()
        apply_level_plan(ds, plan)
        self.assertEqual(
            [None if pd.isna(v) else v for v in ds.raw["Mix"].tolist()],
            ["Uno", 1.0, "1", "1.0", True, "  B  ", "A", None],
        )

    def test_eligibility_checks(self):
        ds = Dataset(pd.DataFrame({
            "Num": [1.0, 2.0, 3.0],
            "Txt": pd.Series(["A", "B", "A"], dtype="string"),
            "NumAsText": pd.Series(["1", "2", "1"], dtype="string"),
        }))
        ds.raw.attrs[VARIABLE_TYPES] = {"NumAsText": "categorical"}
        ds.set_formula("Calc", "Num * 2")
        self.assertFalse(can_rename_levels(ds, "Num"))
        self.assertTrue(can_rename_levels(ds, "Txt"))
        self.assertTrue(can_rename_levels(ds, "NumAsText"))
        self.assertFalse(can_rename_levels(ds, "Calc"))

        ds_xy = Dataset(pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]}), table_format="xy")
        self.assertFalse(can_rename_levels(ds_xy, "X"))


class CategoryLevelsProjectAndJoinTests(unittest.TestCase):
    def setUp(self):
        set_language("it")

    def tearDown(self):
        set_language("en")

    def test_single_history_step_undo_redo_metadata_and_single_recalc(self):
        project = Project()
        other_df = pd.DataFrame({"K": ["X", "Y"], "V": [1.0, 2.0]})
        main_df = pd.DataFrame({
            "Gruppo": pd.Series(["A", "B", "A", None, "Controllo $", "Procès"], dtype="string"),
            "Valore": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })
        t_main, t_other = project.add_tables({"Studio": main_df, "Altro": other_df})
        ds = project.tables[t_main]
        ds.raw.attrs[VARIABLE_TYPES] = {"Gruppo": "categorical"}
        set_order(ds, "Gruppo", ["str:Controllo $", "str:B", "str:A", "str:Procès"])
        ds.excluded.add((2, 1))
        ds.number_formats["Valore"] = {"mode": "fixed", "digits": 2}
        ds.cell_backgrounds[(0, "Gruppo")] = "#FFEEAA"

        run = project.candidate(t_main, "Descriptive statistics", {"Variables": ["Valore"]})
        project.runs.append(run)
        ds.analyses.append((run.method, run.options))

        draft = LevelEditDraft(ds, "Gruppo")
        draft.apply_mapping({"A": "Risposta", "B": "Risposta"})
        plan = draft.validate()

        with patch.object(project, "table_runs", wraps=project.table_runs) as spy_runs:
            affected = project.apply_category_levels(t_main, plan)
            self.assertEqual(spy_runs.call_count, 1)

        self.assertEqual(len(affected), 1)
        self.assertEqual(len(project.history.changes), 1)
        self.assertEqual(_series_as_json_values(ds.raw["Gruppo"]), ["Risposta", "Risposta", "Risposta", None, "Controllo $", "Procès"])
        self.assertEqual(ds.raw.attrs[WORKSHEET_ORDERS]["Gruppo"], ["str:Controllo $", "str:Risposta", "str:Procès"])
        self.assertEqual(ds.raw.attrs[VARIABLE_TYPES], {"Gruppo": "categorical"})
        self.assertEqual(ds.excluded, {(2, 1)})
        self.assertEqual(ds.number_formats, {"Valore": {"mode": "fixed", "digits": 2}})
        self.assertEqual(ds.cell_backgrounds, {(0, "Gruppo"): "#FFEEAA"})
        self.assertEqual(project.tables[t_other].raw["K"].tolist(), ["X", "Y"])

        # Undo restores both values and order in one step
        title, undo_affected = project.undo()
        self.assertEqual(title, t_main)
        self.assertEqual(len(undo_affected), 1)
        self.assertEqual(_series_as_json_values(ds.raw["Gruppo"]), ["A", "B", "A", None, "Controllo $", "Procès"])
        self.assertEqual(ds.raw.attrs[WORKSHEET_ORDERS]["Gruppo"], ["str:Controllo $", "str:B", "str:A", "str:Procès"])

        # Redo reapplies both
        title, redo_affected = project.undo(redo=True)
        self.assertEqual(title, t_main)
        self.assertEqual(len(redo_affected), 1)
        self.assertEqual(_series_as_json_values(ds.raw["Gruppo"]), ["Risposta", "Risposta", "Risposta", None, "Controllo $", "Procès"])
        self.assertEqual(ds.raw.attrs[WORKSHEET_ORDERS]["Gruppo"], ["str:Controllo $", "str:Risposta", "str:Procès"])

        # Save .alab and reopen
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.alab"
            save_project(path, project.tables)
            tables, _ = load_workspace(path)
            reopened = tables[t_main]
            self.assertEqual(_series_as_json_values(reopened.raw["Gruppo"]), ["Risposta", "Risposta", "Risposta", None, "Controllo $", "Procès"])
            self.assertEqual(reopened.raw.attrs[WORKSHEET_ORDERS]["Gruppo"], ["str:Controllo $", "str:Risposta", "str:Procès"])
            self.assertEqual(reopened.raw.attrs[VARIABLE_TYPES], {"Gruppo": "categorical"})
            self.assertEqual(reopened.excluded, {(2, 1)})
            self.assertEqual(reopened.number_formats, {"Valore": {"mode": "fixed", "digits": 2}})

    def test_blocking_recipes_direct_and_left_right_join(self):
        project = Project()
        left_df = pd.DataFrame({
            "ID": ["1", "2", "3", "4", "5", "6"],
            "Arm": pd.Series(["Ctrl", "Ctrl", "DrugA", "DrugA", "DrugB", "DrugB"], dtype="string"),
            "Y": [1.0, 1.2, 2.5, 2.8, 3.1, 3.4],
        })
        right_df = pd.DataFrame({
            "ID": ["1", "2", "3", "4", "5", "6"],
            "Arm": pd.Series(["R_Ctrl", "R_Ctrl", "R_A", "R_A", "R_B", "R_B"], dtype="string"),
            "Cohort": pd.Series(["North", "North", "South", "South", "East", "East"], dtype="string"),
        })
        t_left, t_right = project.add_tables({"Left": left_df, "Right": right_df})

        # 1. Direct Dunnett on Left.Arm
        r_dunnett = project.candidate(t_left, "One-way ANOVA", {
            "Response": "Y", "Group": "Arm", "Method": "Ordinary",
            "Post-hoc": "Dunnett", "Control group": "Ctrl",
        })
        project.runs.append(r_dunnett)

        # 2. Direct Multifactor ANOVA planned contrast on Left.Arm
        r_mf = project.candidate(t_left, "Multifactor ANOVA", {
            "Response": "Y", "Factors": ["Arm"],
            "Planned contrast factors": ["Arm"],
            "Planned contrasts": [{
                "name": "Ctrl vs A",
                "weights": [{"levels": ["Ctrl"], "coefficient": -1.0}, {"levels": ["DrugA"], "coefficient": 1.0}],
            }],
        })
        project.runs.append(r_mf)

        # 3. Join Left + Right on ID -> produces Arm, Arm [right], Cohort
        r_join = project.candidate(t_left, worksheet_join.METHOD, {
            worksheet_join.RIGHT_SHEET: t_right,
            worksheet_join.LEFT_KEYS: ["ID"],
            worksheet_join.RIGHT_KEYS: ["ID"],
            worksheet_join.JOIN_TYPE: worksheet_join.LEFT,
            worksheet_join.CARDINALITY: worksheet_join.ONE_TO_ONE,
        })
        project.runs.append(r_join)

        # 4. Derived ANCOVA reading Left's Arm via Joined data
        from analisi.analysis_chain import ResultSource
        r_ancova_left = project.candidate(
            t_left, "Kruskal–Wallis",
            {"Response": "Y", "Group": "Arm", "Dunn comparisons": "Versus control", "Control group": "DrugA"},
            source=ResultSource(r_join.uid, worksheet_join.JOINED),
        )
        project.runs.append(r_ancova_left)

        # 5. Derived One-way ANOVA reading Right's Arm [right] via Joined data
        r_rmst_right = project.candidate(
            t_left, "One-way ANOVA",
            {"Response": "Y", "Group": "Arm [right]", "Method": "Ordinary", "Post-hoc": "Dunnett", "Control group": "R_Ctrl"},
            source=ResultSource(r_join.uid, worksheet_join.JOINED),
        )
        project.runs.append(r_rmst_right)

        # Merging Ctrl -> Placebo removes "Ctrl": blocks Dunnett, Multifactor contrast
        draft_left = LevelEditDraft(project.tables[t_left], "Arm")
        draft_left.apply_mapping({"Ctrl": "Placebo"})
        plan_left = draft_left.validate()
        blockers_left = find_blocking_recipes(project, t_left, plan_left)
        self.assertGreaterEqual(len(blockers_left), 2)
        with self.assertRaises(LevelEditError) as ctx:
            project.apply_category_levels(t_left, plan_left)
        self.assertEqual(ctx.exception.code, "recipe_blocked")
        self.assertIn("Ctrl", str(ctx.exception))

        # Merging DrugA -> Active removes "DrugA": blocks Multifactor contrast AND join-derived Kruskal-Wallis!
        draft_left2 = LevelEditDraft(project.tables[t_left], "Arm")
        draft_left2.apply_mapping({"DrugA": "Active"})
        plan_left2 = draft_left2.validate()
        blockers_left2 = find_blocking_recipes(project, t_left, plan_left2)
        recipes_names = {b.recipe_name for b in blockers_left2}
        self.assertTrue(any("Kruskal" in name for name in recipes_names), blockers_left2)

        # Right table rename of R_Ctrl -> Base: blocks join-derived Dunnett on "Arm [right]"
        draft_right = LevelEditDraft(project.tables[t_right], "Arm")
        draft_right.apply_mapping({"R_Ctrl": "Base"})
        plan_right = draft_right.validate()
        blockers_right = find_blocking_recipes(project, t_right, plan_right)
        self.assertEqual(len(blockers_right), 1)
        self.assertEqual(blockers_right[0].levels, ("R_Ctrl",))

        # Renaming Cohort (unused by explicit controls) succeeds and refreshes join + downstream
        draft_cohort = LevelEditDraft(project.tables[t_right], "Cohort")
        draft_cohort.apply_mapping({"East": "West"})
        affected_right = project.apply_category_levels(t_right, draft_cohort.validate())
        self.assertIn(r_join, affected_right)

        # Renaming DrugB -> High (unused by controls/contrasts) succeeds and returns join + direct runs
        draft_ok = LevelEditDraft(project.tables[t_left], "Arm")
        draft_ok.apply_mapping({"DrugB": "High"})
        affected_left = project.apply_category_levels(t_left, draft_ok.validate())
        self.assertIn(r_join, affected_left)

    def test_blocking_recipes_ancova_rmst_and_kaplan_meier(self):
        project = Project()
        df = pd.DataFrame({
            "Time": [5.0, 8.0, 10.0, 4.0, 6.0, 9.0],
            "Status": [1, 0, 1, 1, 1, 0],
            "Arm": pd.Series(["Ctrl", "Ctrl", "Ctrl", "Treated", "Treated", "Treated"], dtype="string"),
            "Cov": [1.0, 2.0, 3.0, 1.5, 2.5, 3.5],
        })
        title, = project.add_tables({"Survival": df})
        project.runs.append(project.candidate(title, "ANCOVA", {
            "Response": "Time", "Covariate": "Cov", "Group": "Arm",
            "Comparisons": "Against control", "Control group": "Ctrl",
        }))
        project.runs.append(project.candidate(title, "Restricted mean survival time", {
            "Time": "Time", "Status": "Status", "Group": "Arm", "Reference group": "Ctrl",
        }))
        project.runs.append(project.candidate(title, "Kaplan–Meier survival", {
            "Time": "Time", "Event columns": ["Status"], "Grouping variables": ["Arm"],
            "Pairwise correction": "Holm–Šídák", "Pairwise comparison family": "Versus control",
            "Pairwise control group": "Ctrl",
        }))
        draft = LevelEditDraft(project.tables[title], "Arm")
        draft.apply_mapping({"Ctrl": "Placebo"})
        blockers = find_blocking_recipes(project, title, draft.validate())
        names = {b.recipe_name for b in blockers}
        self.assertEqual(len(blockers), 3)
        self.assertTrue(any("ANCOVA" in n for n in names), names)
        self.assertTrue(any("RMST" in n or "mean survival" in n.lower() or "ristretta" in n.lower() for n in names), names)
        self.assertTrue(any("Kaplan" in n for n in names), names)

    def test_benchmark_50k_rows_50_levels(self):
        rng = np.random.default_rng(42)
        levels = [f"Level_{i:02d}" for i in range(50)]
        col = pd.Series(rng.choice(levels, size=50_000), dtype="string")
        ds = Dataset(pd.DataFrame({"Category": col, "Measure": rng.normal(size=50_000)}))

        t0 = time.perf_counter()
        draft = LevelEditDraft(ds, "Category")
        t_scan = time.perf_counter() - t0

        self.assertEqual(len(draft.levels), 50)
        self.assertEqual(sum(e.count for e in draft.levels), 50_000)

        draft.apply_mapping({"Level_00": "Merged_00_01", "Level_01": "Merged_00_01", "Level_02": "Renamed_02"})
        t1 = time.perf_counter()
        plan = draft.validate()
        apply_level_plan(ds, plan)
        t_apply = time.perf_counter() - t1

        self.assertEqual(len(ds.raw), 50_000)
        self.assertNotIn("Level_00", set(ds.raw["Category"].dropna()))
        self.assertNotIn("Level_01", set(ds.raw["Category"].dropna()))
        self.assertIn("Merged_00_01", set(ds.raw["Category"].dropna()))
        self.assertLess(t_scan + t_apply, 2.0)


class CategoryOrderDialogQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language("it")
        self.casi = _load_casi()

    def tearDown(self):
        set_language("en")

    def test_filter_preserves_proposals_and_validation_focuses_invalid_field(self):
        ds = _casi_dataset(self.casi)
        draft = LevelEditDraft(ds, "Gruppo")
        dialog = CategoryOrderDialog(None, "Gruppo", draft)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Verify initial displayed order matches stored_order
        displayed = [dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount())]
        self.assertEqual(displayed, self.casi["stored_order"])

        # Edit "A" -> "" (invalid), then filter on "Procès" so "A" is hidden, edit "Procès" -> "Procès 2"
        row_a = displayed.index("A")
        dialog.table.item(row_a, 2).setText("")
        dialog.search.setText("Procès")
        self.app.processEvents()
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).text(), "Procès")
        self.assertFalse(dialog.up.isEnabled())
        self.assertFalse(dialog.down.isEnabled())
        dialog.table.item(0, 2).setText("Procès 2")

        # Clear filter and verify both proposals are preserved
        dialog.search.clear()
        self.app.processEvents()
        self.assertEqual(dialog.table.rowCount(), 4)
        self.assertEqual(dialog.table.item(row_a, 2).text(), "")
        self.assertEqual(dialog.table.item(displayed.index("Procès"), 2).text(), "Procès 2")

        # Filter back to hide "A" and press Apply -> validation must clear filter, show error, and select (row_a, 2)
        dialog.search.setText("Procès")
        self.app.processEvents()
        dialog.accept()
        self.app.processEvents()
        self.assertEqual(dialog.result(), 0)  # Dialog stayed open (not accepted)
        self.assertTrue(dialog.problem.isVisible())
        self.assertEqual(dialog.search.text(), "")
        self.assertEqual(dialog.table.currentRow(), row_a)
        self.assertEqual(dialog.table.currentColumn(), 2)
        # Close active inline editor if opened
        editor = dialog.table.focusWidget()
        if isinstance(editor, QLineEdit):
            self.assertEqual(editor.text(), "")

    def test_merge_confirmation_cancel_and_recipe_check_before_confirmation(self):
        project = Project()
        df = pd.DataFrame({
            "Gruppo": pd.Series(self.casi["input"], dtype="string"),
            "Y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })
        title, = project.add_tables({"Studio": df})
        set_order(project.tables[title], "Gruppo", [f"str:{v}" for v in self.casi["stored_order"]])
        run = project.candidate(title, "One-way ANOVA", {
            "Response": "Y", "Group": "Gruppo", "Method": "Ordinary",
            "Post-hoc": "Dunnett", "Control group": "A",
        })
        project.runs.append(run)

        # 1. Blocking recipe must prevent confirmation prompt from even running
        draft_blocked = LevelEditDraft(project.tables[title], "Gruppo")
        confirm_calls = []
        dlg_blocked = CategoryOrderDialog(
            None, "Gruppo", draft_blocked,
            check_recipes=lambda plan: project.category_level_blockers(title, plan),
            confirm_merge=lambda merges: confirm_calls.append(merges) or True,
        )
        self.addCleanup(dlg_blocked.deleteLater)
        dlg_blocked.show()
        self.app.processEvents()
        dlg_blocked.table.item(1, 2).setText("Risposta")  # B -> Risposta
        dlg_blocked.table.item(2, 2).setText("Risposta")  # A -> Risposta (removes A!)
        dlg_blocked.accept()
        self.app.processEvents()
        self.assertEqual(confirm_calls, [])
        self.assertTrue(dlg_blocked.problem.isVisible())
        self.assertIn("A", dlg_blocked.problem.text())

        # 2. Without blocking recipe, declining confirmation keeps dialog open and data intact
        project.runs.clear()
        draft_merge = LevelEditDraft(project.tables[title], "Gruppo")
        dlg_merge = CategoryOrderDialog(
            None, "Gruppo", draft_merge,
            check_recipes=lambda plan: project.category_level_blockers(title, plan),
            confirm_merge=lambda merges: False,
        )
        self.addCleanup(dlg_merge.deleteLater)
        dlg_merge.table.item(1, 2).setText("Risposta")
        dlg_merge.table.item(2, 2).setText("Risposta")
        dlg_merge.accept()
        self.assertIsNone(dlg_merge.plan)
        self.assertEqual(_series_as_json_values(project.tables[title].raw["Gruppo"]), self.casi["input"])

        # 3. Confirming applies cleanly; Esc / Cancel does not
        dlg_merge.confirm_merge = lambda merges: True
        dlg_merge.accept()
        self.assertIsNotNone(dlg_merge.plan)

    def test_large_merge_confirmation_fits_scrolls_and_can_be_retried_after_cancel(self):
        values = [f"Category {i:03d}" for i in range(256)]
        literal = "Merged 127 <b>literal</b> &"
        ds = Dataset(pd.DataFrame({"Group": values}))
        draft = LevelEditDraft(ds, "Group")
        draft.apply_mapping({value: literal if i >= 254 else f"Merged {i // 2:03d}"
                             for i, value in enumerate(values)})
        dialog = CategoryOrderDialog(None, "Group", draft)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        observed = {}

        def inspect_and_click(button_key):
            popup = self.app.activeModalWidget()
            try:
                buttons = {button.text(): button for button in popup.findChildren(QPushButton)}
                cancel = buttons[tr("setup.cancel")]
                confirm = buttons[tr("category_levels.merge.confirm")]
                bounds = popup.screen().availableGeometry()
                observed["buttons_visible"] = all(bounds.contains(button.mapToGlobal(button.rect().center()))
                                                  for button in (cancel, confirm))
                preview = popup.findChild(QPlainTextEdit)
                if preview is not None:
                    scroll = preview.verticalScrollBar()
                    scroll.setValue(scroll.maximum())
                    observed["can_scroll"] = scroll.value() > 0
                    observed["literal_at_end"] = literal in preview.toPlainText()
                QTest.mouseClick(buttons[tr(button_key)], Qt.MouseButton.LeftButton)
            finally:
                if popup.isVisible():
                    popup.reject()

        QTimer.singleShot(80, lambda: inspect_and_click("setup.cancel"))
        dialog.accept()
        self.assertTrue(observed["buttons_visible"])
        self.assertTrue(observed["can_scroll"])
        self.assertTrue(observed["literal_at_end"])
        self.assertTrue(dialog.isVisible())
        self.assertIsNone(dialog.plan)
        self.assertEqual(ds.raw["Group"].tolist(), values)

        QTimer.singleShot(80, lambda: inspect_and_click("category_levels.merge.confirm"))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(len(dialog.plan.merges), 128)
        apply_level_plan(ds, dialog.plan)
        self.assertEqual(ds.raw["Group"].iloc[254:].tolist(), [literal, literal])

    def test_window_escape_and_apply_with_mainwindow(self):
        window = MainWindow()
        self.addCleanup(window.close)
        title, = window.project.add_tables({
            "Studio": pd.DataFrame({
                "Gruppo": pd.Series(self.casi["input"], dtype="string"),
                "Y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            })
        })
        set_order(window.project.tables[title], "Gruppo", [f"str:{v}" for v in self.casi["stored_order"]])
        window.open_sheet(("data", title))
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.project.dirty = False

        def cancel_edit(dialog):
            dialog.table.item(1, 2).setText("Modificato")
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(CategoryOrderDialog, "exec", cancel_edit):
            window.actions["category_order"].trigger()

        self.assertFalse(window.project.dirty)
        self.assertEqual(_series_as_json_values(window.project.tables[title].raw["Gruppo"]), self.casi["input"])


if __name__ == "__main__":
    unittest.main()
