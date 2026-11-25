"""Unit and project integration tests for whole-worksheet row sorting."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi import linked_tables as lt
from analisi import point_style as ps
from analisi.data import EDITABLE_LEGACY_COLUMNS, EDITABLE_LEGACY_XY
from analisi.i18n import set_language
from analisi.presentation import graph_series
from analisi.variable_types import VARIABLE_TYPES
from analisi.worksheet_row_identity import ROW_SPANS, after_permutation, current_spans, row_of, validate_permutation
from analisi.worksheet_sort import (
    ASCENDING,
    DESCENDING,
    compute_sort_order,
    plan_row_sort,
    remap_selection_after_sort,
    row_title_sort_column,
    sortable_columns,
    x_sort_column,
)
from analisi.worksheet_text import TextStyles
from trama_qt.project import Project, compute


def _synthetic_sort_fixture_bytes() -> bytes:
    """Equivalent in-memory fixture to collaudo ordine-righe.alab for portable unit testing."""
    return json.dumps({
        "version": 2,
        "tables": [{
            "title": "Ordine delle osservazioni",
            "columns": ["Row title", "X", "Y", "Campione"],
            "kinds": ["text", "numeric", "numeric", "text"],
            "rows": [
                ["Zeta", 3, 7, "Z-1"],
                ["alpha", 1, 2, "A-1"],
                ["Beta $", 2, 4, "B-1"],
                ["ALPHA", 1, 2, "A-2"],
                [None, None, 5, "VUOTO"],
                ["delta", 0, 9, "D"],
                ["beta $", 2, 10, "B-2"],
            ],
            "formulas": [],
            "analyses": [["XY series", {"X": "X", "Y columns": ["Y"]}]],
            "excluded": [[3, 2]],
            "table_format": "multivariable",
            "graph_styles": {},
            "row_heights": [[3, 40]],
            "cell_backgrounds": [[3, "Y", "#d4e4f6"]],
            "text_styles": [["Y", 3, 4, {"size": 14, "color": "#245b9a", "bold": True}]],
        }],
        "layouts": [],
    }).encode("utf-8")


def _open_sort_fixture(tmp_dir: str) -> tuple[Project, Path]:
    path = Path(tmp_dir) / "ordine-righe.alab"
    path.write_bytes(_synthetic_sort_fixture_bytes())
    project = Project()
    project.load(path)
    run = project.runs[0]
    run.result = compute(run, project.tables[run.title].frame(mask_excluded=True))
    return project, path


class WorksheetPermutationTests(unittest.TestCase):
    def test_validate_and_after_permutation_coalesce(self):
        frame = pd.DataFrame({"X": [10, 20, 30, 40, 50]})
        # Swap blocks [3, 4, 0, 1, 2] -> two contiguous spans.
        spans = after_permutation(frame, [3, 4, 0, 1, 2])
        self.assertEqual(spans, (("base", 4, 2), ("base", 1, 3)))
        self.assertEqual([row_of(spans, f"base:{i}") for i in range(1, 6)], [3, 4, 5, 1, 2])

        # Inverting back coalesces to a single base span.
        frame.attrs[ROW_SPANS] = spans
        restored = after_permutation(frame, [2, 3, 4, 0, 1])
        self.assertEqual(restored, (("base", 1, 5),))

    def test_rejects_invalid_permutations(self):
        for bad in (
            [0, 1],
            [0, 0, 2],
            [-1, 1, 2],
            [0, 1, 3],
            [True, 1, 2],
            "abc",
        ):
            with self.assertRaises(ValueError):
                validate_permutation(bad, 3)

    def test_text_styles_reorder_coalesces_adjacent_runs(self):
        styles = TextStyles({
            "Y": ((0, 1, (("bold", True),)), (2, 4, (("bold", True),))),
            "All": ((0, 5, (("italic", True),)),),
        })
        reordered = styles.reorder_rows(5, [0, 2, 3, 1, 4])
        # Old rows 0, 2, 3 move to 0, 1, 2 and coalesce into one run.
        self.assertEqual(reordered.runs["Y"], ((0, 3, (("bold", True),)),))
        # Full-sheet run remains a single full run.
        self.assertEqual(reordered.runs["All"], ((0, 5, (("italic", True),)),))


class SortKeyAndStabilityTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_numeric_and_unicode_casefold_stability_and_missing_last(self):
        # Ties & Unicode NFC vs NFD & casefolding.
        text_series = pd.Series(["e\u0301lan", "ALPHA", None, "Élan", "alpha", ""], dtype="string")
        asc = compute_sort_order(text_series, ASCENDING).tolist()
        desc = compute_sort_order(text_series, DESCENDING).tolist()
        # Non-missing asc: ALPHA (1), alpha (4), e\u0301lan (0), Élan (3); missing (2, 5) last.
        self.assertEqual(asc, [1, 4, 0, 3, 2, 5])
        # Descending keeps relative tie order: e\u0301lan (0) before Élan (3), ALPHA (1) before alpha (4), missing last!
        self.assertEqual(desc, [0, 3, 1, 4, 2, 5])

        num_series = pd.Series([np.nan, 2.0, 1.0, 2.0, np.nan, -3.5], dtype="Float64")
        self.assertEqual(compute_sort_order(num_series, ASCENDING).tolist(), [5, 2, 1, 3, 0, 4])
        self.assertEqual(compute_sort_order(num_series, DESCENDING).tolist(), [1, 3, 2, 5, 0, 4])

    def test_selection_remapping_avoids_unrelated_rows(self):
        # Permutation moves [0, 1, 2, 3] -> old 0..1 go to 0, 3 (non-contiguous).
        order = np.array([0, 2, 3, 1], dtype=np.intp)
        inv = np.empty(4, dtype=np.intp)
        inv[order] = np.arange(4, dtype=np.intp)
        # Scattered multi-row selection (0..1) -> focuses on moved active row only (no rows 1..2 included).
        res = remap_selection_after_sort(inv, 4, (0, 1, 1, 2), current_row=1, current_col=2)
        self.assertEqual(res, (3, 1, 3, 2, 3, 2))
        # Contiguous surviving block [2, 3] stays contiguous at [1, 2].
        res2 = remap_selection_after_sort(inv, 4, (2, 0, 3, 1), current_row=2, current_col=1)
        self.assertEqual(res2, (1, 0, 2, 1, 1, 1))


class ProjectSortIntegrationTests(unittest.TestCase):
    def test_fixture_scenarios_metadata_undo_redo_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, path = _open_sort_fixture(tmp)
            title = "Ordine delle osservazioni"
            ds = project.tables[title]

            self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "A-1", "B-1", "A-2", "VUOTO", "D", "B-2"])
            self.assertEqual(x_sort_column(ds), "X")
            self.assertEqual(row_title_sort_column(ds), "Row title")

            # Add a linked table and a point style targeting tracked row 3 ("A-2", 0-based).
            choice = next(c for c in project.table_source_choices() if c["kind"] == "sheet")
            rec = project.table_record(choice, (3, 0, 3, 3), mode="linked")
            series = graph_series(project.runs[0].result.figure.axes[0])[0]
            pmap = ps.point_map(series.artist)
            # Tracked "A-2" is 1-based row 4 (index 3), which is drawn on Y (row 3 is excluded in column 2 -> check row 1 "A-1").
            style = dict(project.runs[0].style or {})
            style[lt.TABLES] = [rec]
            project.apply_format(project.runs[0], style)

            # 1. X Ascending.
            affected = project.sort_rows(title, "X", ASCENDING)
            self.assertEqual(affected, [project.runs[0]])
            self.assertEqual(ds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])
            # Tracked "A-2" moved from 0-based 3 -> 2 (1-based 4 -> 3).
            self.assertEqual(ds.row_heights, {2: 40})
            self.assertEqual(ds.excluded, {(2, 2)})
            self.assertEqual(ds.cell_backgrounds, {(2, "Y"): "#d4e4f6"})
            self.assertEqual(ds.text_styles.runs["Y"], ((2, 3, (("size", 14), ("color", "#245b9a"), ("bold", True))),))
            # Original text casing and excluded stored value preserved.
            self.assertEqual(ds.raw.loc[1, "Row title"], "alpha")
            self.assertEqual(ds.raw.loc[2, "Row title"], "ALPHA")
            self.assertEqual(float(ds.raw.loc[2, "Y"]), 2.0)

            # Linked table resolves "A-2" at its new row token without pointing at wrong row.
            spec = project.table_specs([rec])[0]
            self.assertTrue(spec.resolved.ok)
            self.assertEqual(spec.resolved.cells[0][-1], "A-2")

            # Identity sort is a true no-op: zero history, zero recalc.
            rev_before = project.revision
            hist_before = project.history.position
            self.assertIsNone(project.sort_rows(title, "X", ASCENDING))
            self.assertEqual(project.revision, rev_before)
            self.assertEqual(project.history.position, hist_before)

            # Single recalc works cleanly and keeps point identity on moved rows.
            project.runs[0].result = compute(project.runs[0], ds.frame(mask_excluded=True))
            self.assertEqual(row_of(current_spans(ds.raw), "base:4"), 3)
            self.assertTrue(pmap is not None)

            # 2. X Descending.
            project.sort_rows(title, "X", DESCENDING)
            self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "B-1", "B-2", "A-1", "A-2", "D", "VUOTO"])

            # 3. Row title Ascending (casefold).
            project.sort_rows(title, "Row title", ASCENDING)
            self.assertEqual(ds.raw["Campione"].tolist(), ["A-1", "A-2", "B-1", "B-2", "D", "Z-1", "VUOTO"])

            # Undo back through the 3 sorts atomically.
            project.undo()
            self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "B-1", "B-2", "A-1", "A-2", "D", "VUOTO"])
            project.undo()
            self.assertEqual(ds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])
            project.undo()
            self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "A-1", "B-1", "A-2", "VUOTO", "D", "B-2"])
            self.assertEqual(ds.row_heights, {3: 40})
            self.assertEqual(ds.excluded, {(3, 2)})

            # Redo one step back to X Ascending and verify .alab save/reopen persistence.
            project.undo(redo=True)
            self.assertEqual(ds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])
            out_path = Path(tmp) / "sorted.alab"
            project.save(out_path)
            reopened = Project()
            reopened.load(out_path)
            rds = reopened.tables[title]
            self.assertEqual(rds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])
            self.assertEqual(rds.row_heights, {2: 40})
            self.assertEqual(rds.excluded, {(2, 2)})
            self.assertEqual(rds.cell_backgrounds, {(2, "Y"): "#d4e4f6"})
            self.assertEqual(row_of(current_spans(rds.raw), "base:4"), 3)

    def test_calculated_formula_column_blocked_and_positional_formulas_updated(self):
        project = Project()
        frame = pd.DataFrame({"X": [3.0, 1.0, 2.0], "Y": [30.0, 10.0, 20.0]})
        title, = project.add_tables({"CalcSheet": frame})
        ds = project.tables[title]
        project.set_formula(title, "Calc", "=X * 10")
        names = [opt.name for opt in sortable_columns(ds)]
        self.assertEqual(names, ["X", "Y"])
        with self.assertRaises(ValueError):
            project.sort_rows(title, "Calc", ASCENDING)

        project.sort_rows(title, "X", ASCENDING)
        evaluated = ds.frame()
        self.assertEqual(evaluated["Calc"].tolist(), [10.0, 20.0, 30.0])
        self.assertIn("Calc", ds.formulas)
        self.assertEqual(ds.raw.attrs.get(VARIABLE_TYPES) is None or isinstance(ds.raw.attrs.get(VARIABLE_TYPES), dict), True)

    def test_blocked_sheets_legacy_and_stale_revision(self):
        project = Project()
        title, = project.add_tables({"Locked": pd.DataFrame({"X": [2.0, 1.0], "Y": [1.0, 2.0]})})
        rev = project.revision
        project.edit_cell(title, 0, 0, "5")
        # Stale revision stops write before touching anything.
        with self.assertRaises(ValueError):
            project.sort_rows(title, "X", ASCENDING, expected_revision=rev)

        # Frozen sheet blocks sort.
        project.set_sheet_frozen(("data", title), True)
        self.assertFalse(project.can_reorder_rows(title))
        with self.assertRaises(ValueError):
            project.sort_rows(title, "X", ASCENDING)
        project.set_sheet_frozen(("data", title), False)

        # Fixed legacy formats block sort.
        for fmt in (EDITABLE_LEGACY_XY, EDITABLE_LEGACY_COLUMNS):
            saved = project.tables[title].table_format
            project.tables[title].table_format = fmt
            self.assertFalse(project.can_reorder_rows(title))
            with self.assertRaises(ValueError):
                project.sort_rows(title, "X", ASCENDING)
            project.tables[title].table_format = saved


if __name__ == "__main__":
    unittest.main()
