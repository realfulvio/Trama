"""Unit and integration tests for numeric series generation, validation, limits and project commits."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from analisi.data import EDITABLE_LEGACY_XY, MAX_CELLS
from analisi.i18n import set_language
from analisi.numeric_series import (ARITHMETIC, DEFAULT_SINGLE_CELL_COUNT, GEOMETRIC, format_preview,
                                    parse_series_number, plan_numeric_series, validate_series_target)
from trama_qt.project import Project, compute


def _fixture_project(tmp_dir):
    doc = {
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
    }
    path = Path(tmp_dir) / "esempio.alab"
    path.write_text(json.dumps(doc), encoding="utf-8")
    project = Project()
    project.load(path)
    return project


class NumericSeriesEngineTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_parse_decimal_comma_point_negative_and_fractions(self):
        self.assertEqual(float(parse_series_number("-0,25")[0]), -0.25)
        self.assertEqual(float(parse_series_number("-0.25")[0]), -0.25)
        self.assertEqual(float(parse_series_number("1/2")[0]), 0.5)
        self.assertEqual(float(parse_series_number("-3/4")[0]), -0.75)
        for bad in ("", "   ", "abc", "nan", "inf", "-inf", "1/0", "1/2/3", "1e500", True):
            with self.assertRaises(ValueError):
                parse_series_number(bad)

    def test_scenario_aritmetica_and_geometrica_and_fractional_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _fixture_project(tmp)
            title = "Serie XY"
            dataset = project.tables[title]

            # Scenario aritmetica: B2 (row=1, col=1), 5 values from 1, step -0,25 -> 4 of 5 occupied
            plan_arith = plan_numeric_series(dataset, 1, 1, mode=ARITHMETIC, start_text="1", count=5, step_text="-0,25")
            self.assertEqual(plan_arith.occupied_count, 4)
            self.assertEqual(plan_arith.range_label, "B2:B6")
            self.assertEqual(plan_arith.values.tolist(), [1.0, 0.75, 0.5, 0.25, 0.0])

            # Without confirm_replace=True it refuses and leaves history/data untouched
            with self.assertRaises(ValueError):
                project.create_numeric_series(title, plan_arith, confirm_replace=False)
            self.assertEqual(len(project.history.changes), 0)
            self.assertEqual(dataset.raw["X"].tolist(), [1, 2, 2, 4, 8])

            affected = project.create_numeric_series(title, plan_arith, confirm_replace=True)
            self.assertEqual(len(affected), 1)
            self.assertEqual(dataset.raw["X"].tolist(), [1.0, 1.0, 0.75, 0.5, 0.25, 0.0])
            # Other columns and metadata preserved
            self.assertEqual(dataset.raw["Row title"].tolist()[:5],
                             ["Campione A", "Campione B", "Campione B", "Campione C", "Campione D"])
            self.assertEqual(dataset.excluded, {(2, 3)})
            self.assertEqual(dataset.cell_backgrounds, {(2, "Segnale"): "#bee3da"})

            # Undo -> original 5 rows restored
            project.undo()
            self.assertEqual(dataset.raw["X"].tolist(), [1, 2, 2, 4, 8])
            project.undo(redo=True)
            self.assertEqual(dataset.raw["X"].tolist(), [1.0, 1.0, 0.75, 0.5, 0.25, 0.0])

            # Scenario geometrica: B6 (row=5, col=1), 4 values from 16, ratio 0,5
            plan_geo = plan_numeric_series(dataset, 5, 1, mode=GEOMETRIC, start_text="16", count=4, step_text="0,5")
            self.assertEqual(plan_geo.occupied_count, 1)  # row 5 currently holds 0.0
            affected = project.create_numeric_series(title, plan_geo, confirm_replace=True)
            self.assertEqual(len(affected), 1)
            self.assertEqual(dataset.raw["X"].tolist(), [1.0, 1.0, 0.75, 0.5, 0.25, 16.0, 8.0, 4.0, 2.0])

            # Recalculate XY recipe cleanly
            run = project.runs[0]
            result = compute(run, dataset.frame(mask_excluded=True))
            self.assertIsNotNone(result.figure)

            # Fractional ratio 1/2 in virtual column E (col=4)
            plan_virt = plan_numeric_series(dataset, 0, 4, mode=GEOMETRIC, start_text="8", count=4, step_text="1/2")
            self.assertTrue(plan_virt.is_virtual_column)
            self.assertEqual(plan_virt.occupied_count, 0)
            project.create_numeric_series(title, plan_virt)
            self.assertEqual(dataset.raw.columns[4], "Column 5")
            self.assertEqual(dataset.raw["Column 5"].dropna().tolist(), [8, 4, 2, 1])

    def test_scenario_limiti_leaves_data_and_history_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _fixture_project(tmp)
            title = "Serie XY"
            dataset = project.tables[title]
            project.set_formula(title, "Doppio", "=X * 2")
            hist_before = len(project.history.changes)
            raw_before = dataset.raw.copy()

            # Text column ("Row title", col 0)
            with self.assertRaises(ValueError):
                validate_series_target(dataset, (0, 0, 0, 0))
            # Calculated column (col 4 when formula is appended)
            formula_col = dataset.columns.index("Doppio")
            with self.assertRaises(ValueError):
                validate_series_target(dataset, (0, formula_col, 0, formula_col))
            # Multi-column selection
            with self.assertRaises(ValueError):
                validate_series_target(dataset, (0, 1, 2, 2))
            # Out-of-limit count (exceeds MAX_CELLS)
            with self.assertRaises(ValueError):
                plan_numeric_series(dataset, 0, 1, mode=ARITHMETIC, start_text="1",
                                    count=MAX_CELLS // len(dataset.raw.columns) + 1, step_text="1")
            # Overflow sequence
            with self.assertRaises(ValueError):
                plan_numeric_series(dataset, 0, 1, mode=GEOMETRIC, start_text="10", count=500, step_text="10")
            # Underflow to non-representable 0
            with self.assertRaises(ValueError):
                plan_numeric_series(dataset, 0, 1, mode=GEOMETRIC, start_text="1", count=2000, step_text="0.5")
            # Frozen sheet
            project.set_sheet_frozen(("data", title), True)
            with self.assertRaises(ValueError):
                project.create_numeric_series(title, 0, 1, mode=ARITHMETIC, start_text="1", count=3, step_text="1",
                                              confirm_replace=True)
            project.set_sheet_frozen(("data", title), False)

            self.assertEqual(len(project.history.changes), hist_before)
            pd.testing.assert_frame_equal(dataset.raw, raw_before)

    def test_target_proposals_and_locale_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = _fixture_project(tmp)
            dataset = project.tables["Serie XY"]
            self.assertEqual(validate_series_target(dataset, (1, 1, 1, 1)).proposed_count, DEFAULT_SINGLE_CELL_COUNT)
            self.assertEqual(validate_series_target(dataset, (1, 1, 3, 1)).proposed_count, 3)
            self.assertEqual(validate_series_target(dataset, (0, 4, 0, 4), full_column=True).proposed_count, 5)
            set_language("it")
            self.assertEqual(format_preview((1, 0.75, 0.5), (0.25, 0), 5), "1; 0,75; 0,5; 0,25; 0")
            set_language("en")
            self.assertEqual(format_preview((1, 0.75, 0.5), (0.25, 0), 5), "1, 0.75, 0.5, 0.25, 0")

    def test_fixed_legacy_xy_rejects_tail_growth(self):
        project = Project()
        frame = pd.DataFrame({"X": [1.0, 2.0], "Y": [3.0, 4.0]})
        frame.attrs["table_format"] = EDITABLE_LEGACY_XY
        project.add_tables({"Legacy": frame})
        with self.assertRaises(ValueError):
            plan_numeric_series(project.tables["Legacy"], 1, 0, mode=ARITHMETIC, start_text="1", count=3, step_text="1")


if __name__ == "__main__":
    unittest.main()
