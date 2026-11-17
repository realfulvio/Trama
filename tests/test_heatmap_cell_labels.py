"""Unit tests for heat-map cell label formatting, validation, rendering, and project round-trips."""
import math
from pathlib import Path
import tempfile
import unittest

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import QuadMesh
from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.heatmap import HEAT_MAP, visibility
from analisi.heatmap_cell_labels import (
    AUTO_CONTRAST,
    AUTO_FORMAT,
    CELL_LABEL_COLOR,
    CELL_LABEL_COLOR_MODE,
    CELL_LABEL_DECIMALS,
    CELL_LABEL_FONT_SIZE,
    CELL_LABEL_NUMBER_FORMAT,
    CELL_LABEL_PREFIX,
    CELL_LABEL_SUFFIX,
    CUSTOM_COLOR,
    FIXED_FORMAT,
    SCIENTIFIC_FORMAT,
    CellLabelSettings,
    format_cell_label,
    parse_cell_label_affix,
    parse_cell_label_color,
    parse_cell_label_decimals,
    parse_cell_label_font_size,
)
from analisi.processing import FieldError
from analisi.workbench import analyse

DATA_DIR = Path(__file__).resolve().parent / "data" / "heatmap_073"


def _mesh(figure):
    FigureCanvasAgg(figure).draw()
    return next(a for ax in figure.axes for a in ax.collections if isinstance(a, QuadMesh))


def _cell_texts(figure):
    return sorted((round(float(t.get_position()[0]), 8), round(float(t.get_position()[1]), 8), t.get_text())
                  for t in figure.axes[0].texts)


class CellLabelHelperTests(unittest.TestCase):
    def test_format_cell_label_rules_and_signed_zero(self):
        self.assertEqual(format_cell_label(-0.0, CellLabelSettings(number_format=AUTO_FORMAT)), "-0")
        self.assertEqual(format_cell_label(-0.0001, CellLabelSettings(number_format=AUTO_FORMAT)), "-0.0001")
        self.assertEqual(format_cell_label(-0.0, CellLabelSettings(number_format=FIXED_FORMAT, decimals=2)), "0.00")
        self.assertEqual(format_cell_label(-0.0001, CellLabelSettings(number_format=FIXED_FORMAT, decimals=2)), "0.00")
        self.assertEqual(format_cell_label(-0.0, CellLabelSettings(number_format=SCIENTIFIC_FORMAT, decimals=2)), "0.00e+00")
        self.assertEqual(format_cell_label(-0.0001, CellLabelSettings(number_format=SCIENTIFIC_FORMAT, decimals=3)), "-1.000e-04")
        self.assertEqual(format_cell_label(1e-12, CellLabelSettings(number_format=SCIENTIFIC_FORMAT, decimals=2)), "1.00e-12")
        self.assertEqual(format_cell_label(1e12, CellLabelSettings(number_format=FIXED_FORMAT, decimals=0)), "1000000000000")
        self.assertEqual(
            format_cell_label("1", CellLabelSettings(number_format=FIXED_FORMAT, decimals=2, prefix="(", suffix=" )"), categorical=True),
            "(1 )",
        )
        self.assertIsNone(format_cell_label(None, CellLabelSettings(), categorical=True))
        self.assertIsNone(format_cell_label(math.nan, CellLabelSettings()))

    def test_parse_decimals_font_size_color_and_affixes(self):
        for raw, expected in ((0, 0), (8, 8), (2.0, 2), ("2", 2), (" 3 ", 3), ("2.0", 2), ("2,0", 2), (np.int64(4), 4)):
            self.assertEqual(parse_cell_label_decimals(raw), expected)

        for bad in (-1, 9, 2.5, "2,5", "2.5", True, False, np.bool_(True), math.nan, math.inf, -math.inf,
                    "inf", "nan", "", "   ", "abc", "2_0", None):
            with self.assertRaises(FieldError) as caught:
                parse_cell_label_decimals(bad)
            self.assertEqual(caught.exception.field, CELL_LABEL_DECIMALS)

        for blank in (None, "", "   "):
            self.assertIsNone(parse_cell_label_font_size(blank))
        for raw, expected in ((6, 6.0), (36, 36.0), ("12,5", 12.5), (" 10.25 ", 10.25)):
            self.assertEqual(parse_cell_label_font_size(raw), expected)
        for bad in (True, False, np.bool_(True), "nan", "inf", math.nan, math.inf, -math.inf, 5, 5.99, 36.01, 37, "12_5", "abc"):
            with self.assertRaises(FieldError) as caught:
                parse_cell_label_font_size(bad)
            self.assertEqual(caught.exception.field, CELL_LABEL_FONT_SIZE)

        self.assertEqual(parse_cell_label_color(None), "#162633")
        self.assertEqual(parse_cell_label_color(" #ff3300 "), "#ff3300")
        for bad in ("nonsense", "", "   ", 123):
            with self.assertRaises(FieldError) as caught:
                parse_cell_label_color(bad)
            self.assertEqual(caught.exception.field, CELL_LABEL_COLOR)

        self.assertEqual(parse_cell_label_affix(" a ", CELL_LABEL_PREFIX), " a ")
        self.assertEqual(parse_cell_label_affix("x" * 80, CELL_LABEL_SUFFIX), "x" * 80)
        for bad in (123, "x" * 81):
            with self.assertRaises(FieldError) as caught:
                parse_cell_label_affix(bad, CELL_LABEL_PREFIX)
            self.assertEqual(caught.exception.field, CELL_LABEL_PREFIX)


class HeatMapCellLabelsEngineTests(unittest.TestCase):
    def setUp(self):
        self.matrix = pd.read_csv(DATA_DIR / "matrix.csv")
        self.categories = pd.read_csv(DATA_DIR / "categories.csv", dtype=str)
        self.base_matrix = {"Input format": "Matrix", "Variables": ["A", "B", "C"], "Row labels": "Row",
                            "Show cell values": True}
        self.base_cat = {"Input format": "Long categories", "X categories": "Col", "Y categories": "Row",
                         "Values": "Value", "Show cell values": True}

    def test_quadmesh_rgba_ticks_colorbar_and_data_table_invariant(self):
        legacy = analyse(HEAT_MAP, self.matrix, self.base_matrix)
        styled = analyse(HEAT_MAP, self.matrix, {
            **self.base_matrix,
            CELL_LABEL_NUMBER_FORMAT: SCIENTIFIC_FORMAT,
            CELL_LABEL_DECIMALS: 3,
            CELL_LABEL_FONT_SIZE: "14,5",
            CELL_LABEL_COLOR_MODE: CUSTOM_COLOR,
            CELL_LABEL_COLOR: "#ff3300",
            CELL_LABEL_PREFIX: "$x$_",
            CELL_LABEL_SUFFIX: " %",
        })
        legacy_mesh = _mesh(legacy.figure)
        styled_mesh = _mesh(styled.figure)
        np.testing.assert_array_equal(legacy_mesh.get_facecolors(), styled_mesh.get_facecolors())
        np.testing.assert_array_equal(legacy_mesh.colorbar.get_ticks(), styled_mesh.colorbar.get_ticks())
        self.assertEqual(
            [t.get_text() for t in legacy_mesh.colorbar.ax.yaxis.get_ticklabels()],
            [t.get_text() for t in styled_mesh.colorbar.ax.yaxis.get_ticklabels()],
        )
        pd.testing.assert_frame_equal(legacy.tables["Heat map data"], styled.tables["Heat map data"])

    def test_negative_zero_extreme_values_and_legacy_font(self):
        frame = pd.DataFrame({"Row": ["r1", "r2"], "A": [-0.0, 1e-10], "B": [1e10, -0.0004]})
        base = {"Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row", "Show cell values": True}
        legacy = analyse(HEAT_MAP, frame, base)
        auto = analyse(HEAT_MAP, frame, {**base, CELL_LABEL_NUMBER_FORMAT: AUTO_FORMAT})
        self.assertEqual(_cell_texts(legacy.figure), _cell_texts(auto.figure))
        self.assertEqual([t.get_fontsize() for t in auto.figure.axes[0].texts],
                         [t.get_fontsize() for t in legacy.figure.axes[0].texts])

        fixed = analyse(HEAT_MAP, frame, {**base, CELL_LABEL_NUMBER_FORMAT: FIXED_FORMAT, CELL_LABEL_DECIMALS: 2})
        self.assertEqual(
            _cell_texts(fixed.figure),
            [(0.5, 0.5, "0.00"), (0.5, 1.5, "0.00"), (1.5, 0.5, "10000000000.00"), (1.5, 1.5, "0.00")],
        )

    def test_long_numeric_and_transpose_reverse_positions(self):
        long_df = pd.DataFrame({
            "X": ["c1", "c1", "c2", "c2"],
            "Y": ["r1", "r1", "r1", "r2"],
            "Val": [1.0, 3.0, -0.0001, 5.5],
        })
        result = analyse(HEAT_MAP, long_df, {
            "Input format": "Long numeric", "X categories": "X", "Y categories": "Y", "Values": "Val",
            "Cell value": "Mean", "Transpose": True, "Reverse rows": True, "Reverse columns": True,
            "Show cell values": True, "Mark missing cells": True,
            CELL_LABEL_NUMBER_FORMAT: FIXED_FORMAT, CELL_LABEL_DECIMALS: 2,
            CELL_LABEL_PREFIX: "~", CELL_LABEL_SUFFIX: " u",
        })
        texts = result.figure.axes[0].texts
        missing_artist = next(t for t in texts if t.get_text() == "×")
        self.assertEqual((round(missing_artist.get_position()[0], 8), round(missing_artist.get_position()[1], 8)), (0.5, 1.5))
        self.assertTrue(np.allclose(to_rgba(missing_artist.get_color()), to_rgba("#36485a")))
        annotated = sorted((round(t.get_position()[0], 8), round(t.get_position()[1], 8), t.get_text())
                           for t in texts if t.get_text() != "×")
        self.assertEqual(annotated, [(0.5, 0.5, "~5.50 u"), (1.5, 0.5, "~0.00 u"), (1.5, 1.5, "~2.00 u")])

    def test_long_categories_literal_and_missing_unaffixed(self):
        legacy = analyse(HEAT_MAP, self.categories, self.base_cat)
        result = analyse(HEAT_MAP, self.categories, {
            **self.base_cat,
            "Mark missing cells": True,
            CELL_LABEL_NUMBER_FORMAT: "bad-ignored",
            CELL_LABEL_DECIMALS: -5,
            CELL_LABEL_FONT_SIZE: "11,5",
            CELL_LABEL_COLOR_MODE: CUSTOM_COLOR,
            CELL_LABEL_COLOR: "navy",
            CELL_LABEL_PREFIX: "[",
            CELL_LABEL_SUFFIX: "]",
        })
        np.testing.assert_array_equal(_mesh(legacy.figure).get_facecolors(), _mesh(result.figure).get_facecolors())
        texts = result.figure.axes[0].texts
        self.assertEqual(
            sorted((round(t.get_position()[0], 8), round(t.get_position()[1], 8), t.get_text()) for t in texts),
            [(0.5, 0.5, "[$p$_A]"), (0.5, 1.5, "[alpha]"), (1.5, 0.5, "[1]"), (1.5, 1.5, "×")],
        )
        for t in texts:
            if t.get_text() == "×":
                self.assertTrue(np.allclose(to_rgba(t.get_color()), to_rgba("#36485a")))
                self.assertNotEqual(t.get_fontsize(), 11.5)
            else:
                self.assertFalse(t.get_parse_math())
                self.assertEqual(t.get_fontsize(), 11.5)
                self.assertTrue(np.allclose(to_rgba(t.get_color()), to_rgba("navy")))

    def test_visibility_flags(self):
        hidden = visibility("Matrix", "Linear", show_cell_values=False,
                            cell_label_number_format="Fixed", cell_label_color_mode="Custom")
        for key in (CELL_LABEL_NUMBER_FORMAT, CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE,
                    CELL_LABEL_COLOR_MODE, CELL_LABEL_COLOR, CELL_LABEL_PREFIX, CELL_LABEL_SUFFIX):
            self.assertFalse(hidden[key])

        cat = visibility("Long categories", "Linear", show_cell_values=True,
                         cell_label_number_format="Fixed", cell_label_color_mode="Custom")
        self.assertFalse(cat[CELL_LABEL_NUMBER_FORMAT])
        self.assertFalse(cat[CELL_LABEL_DECIMALS])
        self.assertTrue(cat[CELL_LABEL_FONT_SIZE])
        self.assertTrue(cat[CELL_LABEL_COLOR_MODE])
        self.assertTrue(cat[CELL_LABEL_COLOR])
        self.assertTrue(cat[CELL_LABEL_PREFIX])
        self.assertTrue(cat[CELL_LABEL_SUFFIX])

        num = visibility("Matrix", "Linear", show_cell_values=True,
                         cell_label_number_format="Scientific", cell_label_color_mode="Auto contrast")
        self.assertTrue(num[CELL_LABEL_NUMBER_FORMAT])
        self.assertTrue(num[CELL_LABEL_DECIMALS])
        self.assertFalse(num[CELL_LABEL_COLOR])

    def test_project_round_trip_and_exports(self):
        opts = {
            **self.base_matrix,
            CELL_LABEL_NUMBER_FORMAT: FIXED_FORMAT,
            CELL_LABEL_DECIMALS: 1,
            CELL_LABEL_FONT_SIZE: 10.5,
            CELL_LABEL_COLOR_MODE: CUSTOM_COLOR,
            CELL_LABEL_COLOR: "#224466",
            CELL_LABEL_PREFIX: "$x$_",
            CELL_LABEL_SUFFIX: " %",
        }
        result = analyse(HEAT_MAP, self.matrix, opts)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alab = root / "labels.alab"
            save_project(alab, {"Matrix": Dataset(self.matrix, analyses=[(HEAT_MAP, opts)])})
            loaded = load_project(alab)
            saved_opts = loaded["Matrix"].analyses[0][1]
            self.assertEqual(saved_opts, opts)
            reopened = analyse(HEAT_MAP, loaded["Matrix"].raw, saved_opts)
            self.assertEqual(_cell_texts(result.figure), _cell_texts(reopened.figure))
            for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
                out = root / f"out.{ext}"
                reopened.figure.savefig(out, format=ext)
                raw = out.read_bytes()
                self.assertIn(magic, raw[:400] if ext != "svg" else raw)
            self.assertIn("$x$_1.2 %", (root / "out.svg").read_text(encoding="utf-8"))
            csv_path = root / "table.csv"
            reopened.tables["Heat map data"].to_csv(csv_path)
            self.assertTrue(csv_path.stat().st_size > 10)


if __name__ == "__main__":
    unittest.main()
