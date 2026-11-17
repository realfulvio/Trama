"""Unit tests for pure heat-map layout geometry, axis label planning, and validation."""
import unittest

import numpy as np
import pandas as pd

from analisi.field_error import FieldError
from analisi.heatmap_layout import (
    COLUMN_GAP_MODE,
    COLUMN_GAP_SIZE,
    COLUMN_GAPS_AFTER,
    COLUMN_LABEL_EVERY,
    COLUMN_LABEL_FONT_SIZE,
    COLUMN_LABEL_FREQUENCY,
    COLUMN_LABEL_ROTATION,
    COLUMN_LABEL_SIDE,
    ROW_GAP_MODE,
    ROW_GAP_SIZE,
    ROW_GAPS_AFTER,
    ROW_LABEL_EVERY,
    ROW_LABEL_FONT_SIZE,
    ROW_LABEL_FREQUENCY,
    ROW_LABEL_SIDE,
    SHOW_COLUMN_LABELS,
    SHOW_ROW_LABELS,
    build_layout_table,
    is_legacy_layout,
    label_plan,
    layout_geometry,
    parse_gap_boundaries,
    parse_gap_size,
    parse_label_every,
    parse_label_font_size,
)


class HeatMapLayoutGeometryTests(unittest.TestCase):
    def test_defaults_produce_unit_grid_with_no_gaps(self):
        geom = layout_geometry(3, 4, {})
        self.assertEqual(geom["x0"], [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(geom["x1"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(geom["y0"], [0.0, 1.0, 2.0])
        self.assertEqual(geom["y1"], [1.0, 2.0, 3.0])
        self.assertEqual(geom["xcenters"], [0.5, 1.5, 2.5, 3.5])
        self.assertEqual(geom["ycenters"], [0.5, 1.5, 2.5])
        self.assertEqual(geom["width"], 4.0)
        self.assertEqual(geom["height"], 3.0)
        self.assertEqual(geom["row_boundaries"], [])
        self.assertEqual(geom["column_boundaries"], [])

    def test_selected_boundaries_and_sorted_canonical_order(self):
        geom = layout_geometry(
            4,
            4,
            {
                ROW_GAP_MODE: "Selected boundaries",
                ROW_GAPS_AFTER: " 3 , 1 ",
                ROW_GAP_SIZE: "0,25",
                COLUMN_GAP_MODE: "Selected boundaries",
                COLUMN_GAPS_AFTER: "2",
                COLUMN_GAP_SIZE: 0.5,
            },
        )
        self.assertEqual(geom["row_boundaries"], [1, 3])
        self.assertEqual(geom["column_boundaries"], [2])
        self.assertEqual(geom["x0"], [0.0, 1.0, 2.5, 3.5])
        self.assertEqual(geom["x1"], [1.0, 2.0, 3.5, 4.5])
        self.assertEqual(geom["xcenters"], [0.5, 1.5, 3.0, 4.0])
        self.assertEqual(geom["y0"], [0.0, 1.25, 2.25, 3.5])
        self.assertEqual(geom["y1"], [1.0, 2.25, 3.25, 4.5])
        self.assertEqual(geom["width"], 4.5)
        self.assertEqual(geom["height"], 4.5)

    def test_single_item_axis_allows_every_boundary_without_gaps_and_rejects_selected(self):
        geom = layout_geometry(
            1,
            2,
            {
                ROW_GAP_MODE: "Every boundary",
                ROW_GAP_SIZE: 2.0,
                COLUMN_GAP_MODE: "Every boundary",
                COLUMN_GAP_SIZE: 0.5,
            },
        )
        self.assertEqual(geom["row_boundaries"], [])
        self.assertEqual(geom["height"], 1.0)
        self.assertEqual(geom["column_boundaries"], [1])
        self.assertEqual(geom["width"], 2.5)

        with self.assertRaises(FieldError) as ctx:
            layout_geometry(1, 2, {ROW_GAP_MODE: "Selected boundaries", ROW_GAPS_AFTER: "1"})
        self.assertEqual(ctx.exception.field, ROW_GAPS_AFTER)

    def test_zero_gap_size_keeps_bounds_and_records_selected_boundaries(self):
        geom = layout_geometry(
            3,
            2,
            {ROW_GAP_MODE: "Selected boundaries", ROW_GAPS_AFTER: "2,1", ROW_GAP_SIZE: 0},
        )
        self.assertEqual(geom["row_boundaries"], [1, 2])
        self.assertEqual(geom["y0"], [0.0, 1.0, 2.0])
        self.assertEqual(geom["height"], 3.0)

    def test_none_and_every_ignore_disabled_fields_even_when_invalid(self):
        geom = layout_geometry(
            3,
            3,
            {
                ROW_GAP_MODE: "None",
                ROW_GAP_SIZE: "bad",
                ROW_GAPS_AFTER: "0,0",
                COLUMN_GAP_MODE: "Every boundary",
                COLUMN_GAP_SIZE: "0,5",
                COLUMN_GAPS_AFTER: "[1,2]",
            },
        )
        self.assertEqual(geom["row_boundaries"], [])
        self.assertEqual(geom["column_boundaries"], [1, 2])
        self.assertEqual(geom["width"], 4.0)

    def test_invalid_gap_sizes_and_boundaries_name_exact_field(self):
        for bad_size in (-0.01, 2.01, float("inf"), float("-inf"), float("nan"), "abc", "", None, True, np.bool_(True), "1_0", 10**400):
            with self.subTest(bad_size=repr(bad_size)):
                with self.assertRaises(FieldError) as ctx:
                    parse_gap_size(bad_size, ROW_GAP_SIZE)
                self.assertEqual(ctx.exception.field, ROW_GAP_SIZE)

        for bad_list in ("", "   ", "0", "4", "2,2", "1.5", "1,5", "1,", ",1", "True", True, "[1]", "1,inf", "-1", "²"):
            with self.subTest(bad_list=repr(bad_list)):
                with self.assertRaises(FieldError) as ctx:
                    parse_gap_boundaries(bad_list, 4, COLUMN_GAPS_AFTER)
                self.assertEqual(ctx.exception.field, COLUMN_GAPS_AFTER)

        with self.assertRaises(FieldError) as ctx:
            layout_geometry(3, 3, {ROW_GAP_MODE: "Bogus"})
        self.assertEqual(ctx.exception.field, ROW_GAP_MODE)


class HeatMapLabelPlanTests(unittest.TestCase):
    def test_automatic_matches_legacy_step_and_literal_names(self):
        names = [f"${i}$" if i == 0 else f"r\\{i}" for i in range(80)]
        plan = label_plan(names, "column", {})
        self.assertTrue(plan["visible"])
        self.assertEqual(plan["rotation"], 40)
        self.assertEqual(plan["side"], "Bottom")
        self.assertIsNone(plan["font_size"])
        self.assertEqual(plan["indices"], list(range(0, 80, 4)))
        self.assertEqual(plan["labels"][0], "$0$")
        self.assertEqual(plan["labels"][1], "r\\4")

    def test_every_nth_does_not_force_final_label(self):
        plan = label_plan(["a", "b", "c", "d", "e"], "row", {ROW_LABEL_FREQUENCY: "Every Nth", ROW_LABEL_EVERY: 3})
        self.assertEqual(plan["indices"], [0, 3])
        self.assertEqual(plan["labels"], ["a", "d"])
        self.assertEqual(plan["rotation"], 0)

    def test_hidden_axis_ignores_invalid_fields_and_returns_canonical_defaults(self):
        plan = label_plan(
            ["a", "b"],
            "column",
            {
                SHOW_COLUMN_LABELS: False,
                COLUMN_LABEL_FREQUENCY: "Bad",
                COLUMN_LABEL_EVERY: "inf",
                COLUMN_LABEL_ROTATION: "Bad",
                COLUMN_LABEL_SIDE: "Bad",
                COLUMN_LABEL_FONT_SIZE: "100",
            },
        )
        self.assertEqual(
            plan,
            {"indices": [], "labels": [], "rotation": 0, "font_size": None, "side": "Bottom", "visible": False},
        )

    def test_invalid_label_options_raise_field_error(self):
        for bad_every in (0, -1, 10001, 1.5, "1,5", "1_0", True, np.bool_(False), "abc", 10**400):
            with self.subTest(bad_every=repr(bad_every)):
                with self.assertRaises(FieldError) as ctx:
                    parse_label_every(bad_every, ROW_LABEL_EVERY)
                self.assertEqual(ctx.exception.field, ROW_LABEL_EVERY)

        for bad_font in (5.99, 36.01, float("inf"), float("nan"), "abc", "1_2", True, np.bool_(True), 10**400):
            with self.subTest(bad_font=repr(bad_font)):
                with self.assertRaises(FieldError) as ctx:
                    parse_label_font_size(bad_font, COLUMN_LABEL_FONT_SIZE)
                self.assertEqual(ctx.exception.field, COLUMN_LABEL_FONT_SIZE)

        self.assertEqual(parse_label_font_size(" 11,5 ", COLUMN_LABEL_FONT_SIZE), 11.5)
        self.assertIsNone(parse_label_font_size("   ", COLUMN_LABEL_FONT_SIZE))

        with self.assertRaises(FieldError) as ctx:
            label_plan(["a"], "row", {SHOW_ROW_LABELS: "yes"})
        self.assertEqual(ctx.exception.field, SHOW_ROW_LABELS)
        with self.assertRaises(FieldError) as ctx:
            label_plan(["a"], "row", {ROW_LABEL_SIDE: "Top"})
        self.assertEqual(ctx.exception.field, ROW_LABEL_SIDE)
        with self.assertRaises(FieldError) as ctx:
            label_plan(["a"], "column", {COLUMN_LABEL_ROTATION: "45"})
        self.assertEqual(ctx.exception.field, COLUMN_LABEL_ROTATION)

    def test_legacy_detection_and_layout_table(self):
        self.assertTrue(is_legacy_layout({}))
        self.assertTrue(is_legacy_layout({ROW_GAP_MODE: "None", ROW_GAP_SIZE: "bad", ROW_LABEL_EVERY: "bad"}))
        self.assertFalse(is_legacy_layout({ROW_GAP_MODE: "Every boundary", ROW_GAP_SIZE: 0}))
        self.assertFalse(is_legacy_layout({SHOW_COLUMN_LABELS: False}))
        self.assertFalse(is_legacy_layout({COLUMN_LABEL_ROTATION: "Vertical"}))
        self.assertFalse(is_legacy_layout({ROW_LABEL_FONT_SIZE: "10"}))

        geom = layout_geometry(2, 2, {ROW_GAP_MODE: "Every boundary", ROW_GAP_SIZE: 0.5})
        table = build_layout_table(["r1", "r1"], ["$ATP$", "B"], geom)
        self.assertEqual(
            list(table.columns),
            ["Display row", "Display column", "Row label", "Column label", "X left", "X right", "Y top", "Y bottom"],
        )
        self.assertEqual(len(table), 4)
        self.assertEqual(table["Display row"].tolist(), [1, 1, 2, 2])
        self.assertEqual(table["Display column"].tolist(), [1, 2, 1, 2])
        self.assertEqual(table["Row label"].tolist(), ["r1", "r1", "r1", "r1"])
        self.assertEqual(table["Column label"].tolist(), ["$ATP$", "B", "$ATP$", "B"])
        pd.testing.assert_series_equal(table["Y top"], pd.Series([0.0, 0.0, 1.5, 1.5], name="Y top"))


if __name__ == "__main__":
    unittest.main()
