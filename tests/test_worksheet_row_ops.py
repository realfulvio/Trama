"""Unit and integration tests for row reordering, row heights, stable identity and metadata remapping."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from analisi import point_style as ps
from analisi.data import EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_XY, Dataset, load_project, project_document, save_project
from analisi.presentation import graph_series
from analisi.worksheet_appearance import MAX_ROW_HEIGHT, MIN_ROW_HEIGHT, read_row_heights
from analisi.worksheet_row_identity import ROW_SPANS, after_move, move_row_index, moved_row_bounds, row_of
from trama_qt.project import Project, compute


def _fixture_bytes():
    return json.dumps({
        "version": 2,
        "tables": [{
            "title": "Serie XY",
            "columns": ["Row title", "X", "Segnale", "Controllo"],
            "kinds": ["text", "numeric", "numeric", "numeric"],
            "rows": [
                ["Campione A", 1, 3, 2],
                ["Campione B", 2, 6, 4],
                ["Campione B", 2, 6, 4],
                ["Campione C", 4, 12, 8],
                ["Campione D", 8, 24, 16],
            ],
            "formulas": [],
            "analyses": [["XY series", {"X": "X", "Y columns": ["Segnale", "Controllo"]}]],
            "excluded": [[2, 3]],
            "table_format": "xy",
            "graph_styles": {},
            "cell_backgrounds": [[2, "Segnale", "#bee3da"]],
        }],
        "layouts": [],
    }).encode("utf-8")


def _open_fixture(tmp_dir):
    path = Path(tmp_dir) / "esempio.alab"
    path.write_bytes(_fixture_bytes())
    project = Project()
    project.load(path)
    run = project.runs[0]
    run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))
    return project, path


class RowIdentityMoveTests(unittest.TestCase):
    def test_after_move_and_coalesce(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4, 5]})
        spans = after_move(frame, 2, 3, 0)
        self.assertEqual(spans, (("base", 3, 1), ("base", 1, 2), ("base", 4, 2)))
        self.assertEqual([row_of(spans, f"base:{i}") for i in range(1, 6)], [2, 3, 1, 4, 5])
        frame.attrs[ROW_SPANS] = spans
        # Move back to original position coalesces spans back to one span.
        restored = after_move(frame, 0, 1, 3)
        self.assertEqual(restored, (("base", 1, 5),))
        self.assertEqual(moved_row_bounds(1, 3, 5), (3, 5))
        self.assertEqual([move_row_index(i, 1, 3, 5) for i in range(5)], [0, 3, 4, 1, 2])

    def test_rejects_invalid_move_bounds(self):
        frame = pd.DataFrame({"X": [1, 2, 3]})
        for bad in ((-1, 1, 0), (1, 1, 0), (0, 4, 1), (0, 1, 4), (True, 2, 0)):
            with self.assertRaises(ValueError):
                after_move(frame, *bad)


class RowHeightPersistenceTests(unittest.TestCase):
    def test_malformed_row_heights_rejected(self):
        for bad in (
            "nope",
            [[0, 20], [1, 20], [2, 20]],
            [[0]],
            [[True, 24]],
            [[0, True]],
            [[0, 24.5]],
            [[-1, 24]],
            [[2, 24]],
            [[0, MIN_ROW_HEIGHT - 1]],
            [[0, MAX_ROW_HEIGHT + 1]],
            [[0, 24], [0, 30]],
        ):
            with self.assertRaises(ValueError):
                read_row_heights(bad, 2)

    def test_save_reopen_preserves_custom_heights_and_existing_alab_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, path = _open_fixture(tmp)
            self.assertEqual(project.tables["Serie XY"].row_heights, {})
            self.assertFalse(project.set_row_heights("Serie XY", [2], None))
            self.assertTrue(project.set_row_heights("Serie XY", [2], 42))
            saved = Path(tmp) / "saved.alab"
            project.save(saved)
            reopened = Project()
            reopened.load(saved)
            self.assertEqual(reopened.tables["Serie XY"].row_heights, {2: 42})


class ProjectRowOperationsTests(unittest.TestCase):
    def test_move_carries_text_runs_with_duplicate_rows_and_persists_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = _open_fixture(tmp)
            title = "Serie XY"
            dataset = project.tables[title]
            project.set_table_text_style(title, (1, 2, 3, 2), {"bold": True})
            project.set_table_text_style(title, (2, 2, 2, 2), {"color": "#126c65"})
            project.set_row_heights(title, [2], 42)
            original = dataset.text_styles

            project.move_rows(title, 2, 3, 0)
            styles = dataset.text_styles
            self.assertEqual(styles.style_at("Segnale", 0), {"color": "#126c65", "bold": True})
            self.assertEqual(styles.style_at("Segnale", 1), {})
            self.assertEqual(styles.style_at("Segnale", 2), {"bold": True})
            self.assertEqual(styles.style_at("Segnale", 3), {"bold": True})
            self.assertEqual(styles.run_count(), 2)
            self.assertEqual(dataset.row_heights, {0: 42})

            project.undo()
            self.assertEqual(dataset.text_styles, original)
            self.assertEqual(dataset.row_heights, {2: 42})
            project.undo(redo=True)
            self.assertEqual(dataset.text_styles, styles)
            saved = Path(tmp) / "styled-rows.alab"
            project.save(saved)
            reopened = Project()
            reopened.load(saved)
            self.assertEqual(reopened.tables[title].text_styles, styles)
            self.assertEqual(reopened.tables[title].row_heights, {0: 42})

    def test_scenario_identita_riga_with_point_style_undo_redo_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = _open_fixture(tmp)
            title = "Serie XY"
            run = project.runs[0]
            series = next(s for s in graph_series(run.result.figure.axes[0]) if s.key == "xy:1:Segnale")
            pmap = ps.point_map(series.artist)
            idx = int(next(i for i, r in enumerate(pmap.rows) if r == 3))
            rec = {"series": series.key, "source": ps.source_record(pmap, idx), "color": "#ac4320", "marker": "s"}
            token_before = rec["source"]["row_token"]
            project.commit_style(run, {ps.POINTS: [rec]})

            # Move row 3 (index 2) before row 1 (destination 0)
            affected = project.move_rows(title, 2, 3, 0)
            self.assertEqual(len(affected), 1)
            run.result = compute(run, project.tables[title].frame(mask_excluded=True))
            dataset = project.tables[title]
            self.assertEqual(dataset.raw["Row title"].tolist(),
                             ["Campione B", "Campione A", "Campione B", "Campione C", "Campione D"])
            self.assertEqual(dataset.excluded, {(0, 3)})
            self.assertEqual(dataset.cell_backgrounds, {(0, "Segnale"): "#bee3da"})
            (status,) = ps.point_statuses(run.result.figure)
            self.assertEqual((status.state, status.index), ("ok", 0))
            new_pmap = ps.point_map(next(s for s in graph_series(run.result.figure.axes[0]) if s.key == "xy:1:Segnale").artist)
            self.assertEqual(int(new_pmap.rows[status.index]), 1)
            self.assertEqual(run.style[ps.POINTS][0]["source"]["row_token"], token_before)

            # Undo -> original order, D3, C3, point style back on row 3
            _, undo_runs = project.undo()
            self.assertEqual(len(undo_runs), 1)
            run.result = compute(run, project.tables[title].frame(mask_excluded=True))
            self.assertEqual(dataset.excluded, {(2, 3)})
            self.assertEqual(dataset.cell_backgrounds, {(2, "Segnale"): "#bee3da"})
            (status_undo,) = ps.point_statuses(run.result.figure)
            self.assertEqual((status_undo.state, status_undo.index), ("ok", 2))

            # Redo -> moved again, save & reopen
            _, redo_runs = project.undo(redo=True)
            self.assertEqual(len(redo_runs), 1)
            out = Path(tmp) / "reopened.alab"
            project.save(out)
            reopened = Project()
            reopened.load(out)
            reopened_run = reopened.runs[0]
            reopened_run.result = compute(reopened_run, reopened.tables[title].frame(mask_excluded=True))
            self.assertEqual(reopened.tables[title].excluded, {(0, 3)})
            self.assertEqual(reopened.tables[title].cell_backgrounds, {(0, "Segnale"): "#bee3da"})
            (status_reopen,) = ps.point_statuses(reopened_run.result.figure)
            self.assertEqual((status_reopen.state, status_reopen.index), ("ok", 0))
            self.assertEqual(reopened_run.style[ps.POINTS][0]["source"]["row_token"], token_before)

    def test_scenario_blocco_and_single_recalc_and_formula_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = _open_fixture(tmp)
            title = "Serie XY"
            project.set_formula(title, "Doppio", "=X * 2")
            affected = project.move_rows(title, 1, 3, 5)
            self.assertEqual(len(affected), 1)
            dataset = project.tables[title]
            self.assertEqual(dataset.raw["Row title"].tolist(),
                             ["Campione A", "Campione C", "Campione D", "Campione B", "Campione B"])
            self.assertEqual(dataset.frame()["Doppio"].tolist(), [2, 8, 16, 4, 4])
            # Exclusion on old row 3 (index 2) moved to row 5 (index 4)
            self.assertEqual(dataset.excluded, {(4, 3)})
            self.assertEqual(dataset.cell_backgrounds, {(4, "Segnale"): "#bee3da"})

    def test_scenario_altezza_zero_recalc_follows_row_and_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = _open_fixture(tmp)
            title = "Serie XY"
            self.assertTrue(project.set_row_heights(title, [2], 56))
            # Presentation only: undo returns [] affected runs (0 recalcs)
            self.assertEqual(project.tables[title].row_heights, {2: 56})
            project.move_rows(title, 2, 3, 0)
            self.assertEqual(project.tables[title].row_heights, {0: 56})
            # Insert before row 0 shifts height to row 1; delete removes/shifts
            project.insert_rows(title, 0, 1)
            self.assertEqual(project.tables[title].row_heights, {1: 56})
            project.delete_rows(title, [0])
            self.assertEqual(project.tables[title].row_heights, {0: 56})
            # Reset height -> 0 recalcs
            self.assertTrue(project.set_row_heights(title, [0], None))
            self.assertEqual(project.tables[title].row_heights, {})
            _, runs = project.undo()
            self.assertEqual(runs, [])
            self.assertEqual(project.tables[title].row_heights, {0: 56})

    def test_locks_and_non_reorderable_views_block_moves_and_virtual_rows(self):
        project = Project()
        project.add_tables({"Data": pd.DataFrame({"A": [1.0, 2.0, 3.0]})})
        with self.assertRaises(ValueError):
            project.move_rows("Data", 2, 4, 0)  # includes virtual row 3
        with self.assertRaises(ValueError):
            project.set_row_heights("Data", [3], 40)  # virtual row
        project.set_sheet_frozen(("data", "Data"), True)
        with self.assertRaises(ValueError):
            project.move_rows("Data", 0, 1, 2)
        with self.assertRaises(ValueError):
            project.set_row_heights("Data", [0], 40)
        project.set_sheet_frozen(("data", "Data"), False)

        # Fixed legacy view refuses row reordering
        fixed = pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]})
        fixed.attrs["table_format"] = EDITABLE_LEGACY_XY
        project.add_tables({"LegacyXY": fixed})
        self.assertFalse(project.can_reorder_rows("LegacyXY"))
        with self.assertRaises(ValueError):
            project.move_rows("LegacyXY", 0, 1, 2)

        cols = pd.DataFrame({"Group": ["A", "B"], "Value": [1.0, 2.0]})
        cols.attrs["table_format"] = EDITABLE_LEGACY_COLUMNS
        project.add_tables({"LegacyCols": cols})
        self.assertFalse(project.can_reorder_rows("LegacyCols"))
        with self.assertRaises(ValueError):
            project.move_rows("LegacyCols", 0, 1, 2)


if __name__ == "__main__":
    unittest.main()
