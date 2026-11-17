"""Dispatcher, vector rendering, export, and project integration tests for heat-map layout."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PolyCollection, QuadMesh
import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.heatmap import (
    CATEGORY_COLORS,
    HEAT_MAP,
    LEGEND_DECIMALS,
    NUMBER_FORMAT,
    ORIENTATION,
    REVERSE_LEGEND,
    visibility,
)
from analisi.heatmap_cell_labels import CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE, CELL_LABEL_NUMBER_FORMAT
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
)
from analisi.presentation import apply_style
from analisi.workbench import analyse


class HeatMapLayoutDispatchTests(unittest.TestCase):
    def setUp(self):
        self.matrix = pd.DataFrame({
            "Row": ["r1", "dup", "dup", "$ATP$"],
            "A": [1.234, 0.0, 0.00001234, 7.0],
            "B": [-0.0001, 1000.0, 2.5, 8.0],
            "C": [np.nan, -12.3456, 3.0, 9.0],
            "D": [4.0, 5.0, 6.0, 10.0],
        })
        self.long_numeric = pd.DataFrame({
            "Row": ["r1", "r1", "r1", "r2", "r2", "r3", "r3"],
            "Column": ["A", "A", "B", "A", "B", "A", "B"],
            "Value": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0, np.nan],
        })
        self.categories = pd.DataFrame({
            "Row": ["r1", "r1", "r2", "r2", "r3", "r3"],
            "Column": ["A", "B", "A", "B", "A", "B"],
            "Value": ["$ATP$", "low", "high", None, "low", "high"],
        })

    def test_zero_gap_active_mode_matches_legacy_bounds_and_rgba_and_adds_layout_table(self):
        base_opts = {"Input format": "Matrix", "Variables": ["A", "B", "C", "D"], "Row labels": "Row"}
        legacy = analyse(HEAT_MAP, self.matrix, base_opts)
        zero = analyse(
            HEAT_MAP,
            self.matrix,
            {**base_opts, ROW_GAP_MODE: "Every boundary", ROW_GAP_SIZE: 0, COLUMN_GAP_MODE: "Selected boundaries",
             COLUMN_GAPS_AFTER: "2", COLUMN_GAP_SIZE: 0},
        )
        self.assertEqual(list(legacy.tables), ["Heat map data"])
        self.assertEqual(list(zero.tables), ["Heat map data", "Heat map layout"])
        self.assertIsInstance(legacy.figure.axes[0].collections[0], QuadMesh)
        self.assertIsInstance(zero.figure.axes[0].collections[0], PolyCollection)
        ax_leg, ax_zero = legacy.figure.axes[0], zero.figure.axes[0]
        self.assertEqual(ax_leg.get_xlim(), ax_zero.get_xlim())
        self.assertEqual(ax_leg.get_ylim(), ax_zero.get_ylim())
        leg_mesh = ax_leg.collections[0]
        zero_poly = ax_zero.collections[0]
        leg_mesh.update_scalarmappable()
        zero_poly.update_scalarmappable()
        np.testing.assert_allclose(zero_poly.get_facecolors(), leg_mesh.get_facecolors(), rtol=0, atol=1e-12)

    def test_visibility_gates_layout_controls_cleanly(self):
        hidden = visibility("Matrix", "Linear", row_gap_mode="None", column_gap_mode="None",
                            show_row_labels=False, row_label_frequency="Every Nth",
                            show_column_labels=False, column_label_frequency="Every Nth")
        for key in (ROW_GAP_SIZE, ROW_GAPS_AFTER, COLUMN_GAP_SIZE, COLUMN_GAPS_AFTER,
                    ROW_LABEL_FREQUENCY, ROW_LABEL_EVERY, ROW_LABEL_SIDE, ROW_LABEL_FONT_SIZE,
                    COLUMN_LABEL_FREQUENCY, COLUMN_LABEL_EVERY, COLUMN_LABEL_ROTATION,
                    COLUMN_LABEL_SIDE, COLUMN_LABEL_FONT_SIZE):
            self.assertFalse(hidden[key], key)

        selected = visibility("Matrix", "Linear", row_gap_mode="Selected boundaries",
                              column_gap_mode="Every boundary", show_row_labels=True,
                              row_label_frequency="Every Nth", show_column_labels=True,
                              column_label_frequency="Automatic")
        self.assertTrue(selected[ROW_GAP_SIZE])
        self.assertTrue(selected[ROW_GAPS_AFTER])
        self.assertTrue(selected[COLUMN_GAP_SIZE])
        self.assertFalse(selected[COLUMN_GAPS_AFTER])
        self.assertTrue(selected[ROW_LABEL_EVERY])
        self.assertFalse(selected[COLUMN_LABEL_EVERY])

    def test_long_numeric_aggregation_with_gaps_and_hidden_labels_and_vector_svg_pdf(self):
        opts = {
            "Input format": "Long numeric",
            "X categories": "Column",
            "Y categories": "Row",
            "Values": "Value",
            "Cell value": "Mean",
            "Show cell values": True,
            "Mark missing cells": True,
            CELL_LABEL_NUMBER_FORMAT: "Fixed",
            CELL_LABEL_DECIMALS: 1,
            CELL_LABEL_FONT_SIZE: 10.5,
            ORIENTATION: "Horizontal",
            REVERSE_LEGEND: True,
            NUMBER_FORMAT: "Fixed",
            LEGEND_DECIMALS: 1,
            ROW_GAP_MODE: "Every boundary",
            ROW_GAP_SIZE: 0.25,
            COLUMN_GAP_MODE: "Selected boundaries",
            COLUMN_GAPS_AFTER: "1",
            COLUMN_GAP_SIZE: 0.5,
            SHOW_ROW_LABELS: False,
            ROW_LABEL_EVERY: "bad",
            SHOW_COLUMN_LABELS: True,
            COLUMN_LABEL_SIDE: "Top",
            COLUMN_LABEL_ROTATION: "Vertical",
            COLUMN_LABEL_FONT_SIZE: "11,5",
        }
        result = analyse(HEAT_MAP, self.long_numeric, opts)
        data_tbl = result.tables["Heat map data"]
        layout_tbl = result.tables["Heat map layout"]
        self.assertAlmostEqual(data_tbl.loc["r1", "A"], 2.0)
        self.assertTrue(pd.isna(data_tbl.loc["r3", "B"]))
        self.assertEqual(len(layout_tbl), 6)

        ax = result.figure.axes[0]
        self.assertEqual(ax.get_xlim(), (0.0, 2.5))
        self.assertEqual(ax.get_ylim(), (3.5, 0.0))
        self.assertEqual([t for t in ax.get_yticklabels() if t.get_visible()], [])
        xt = [t for t in ax.get_xticklabels() if t.get_visible()]
        self.assertEqual([t.get_text() for t in xt], ["A", "B"])
        self.assertEqual([t.get_rotation() for t in xt], [90.0, 90.0])
        self.assertTrue(all(abs(t.get_fontsize() - 11.5) < 1e-9 for t in xt))
        texts = {(round(float(t.get_position()[0]), 6), round(float(t.get_position()[1]), 6)): t.get_text()
                 for t in ax.texts}
        self.assertEqual(texts[(0.5, 0.5)], "2.0")
        self.assertEqual(texts[(2.0, 3.0)], "×")

        svg_buf = BytesIO()
        result.figure.savefig(svg_buf, format="svg")
        svg_text = svg_buf.getvalue().decode("utf-8")
        ET.fromstring(svg_text)
        self.assertIn('id="PolyCollection_1"', svg_text)
        self.assertIn("2.0", svg_text)

        # Without a numeric colorbar gradient strip, the entire SVG is purely vector.
        no_bar = analyse(HEAT_MAP, self.long_numeric, {**opts, "Show color legend": False})
        no_bar_svg = BytesIO()
        no_bar.figure.savefig(no_bar_svg, format="svg")
        no_bar_text = no_bar_svg.getvalue().decode("utf-8")
        self.assertNotIn("<image", no_bar_text)
        self.assertIn('id="PolyCollection_1"', no_bar_text)

        pdf_buf = BytesIO()
        result.figure.savefig(pdf_buf, format="pdf")
        self.assertTrue(pdf_buf.getvalue().startswith(b"%PDF"))

    def test_categorical_right_labels_place_legend_without_overlap_and_preserve_custom_colors(self):
        opts = {
            "Input format": "Long categories",
            "X categories": "Column",
            "Y categories": "Row",
            "Values": "Value",
            "Show cell values": True,
            "Mark missing cells": True,
            CATEGORY_COLORS: {"$ATP$": "#cc3311", "high": "#114477"},
            ROW_GAP_MODE: "Every boundary",
            ROW_GAP_SIZE: 0.3,
            ROW_LABEL_SIDE: "Right",
            COLUMN_LABEL_ROTATION: "Diagonal",
        }
        result = analyse(HEAT_MAP, self.categories, opts)
        ax = result.figure.axes[0]
        FigureCanvasAgg(result.figure)
        result.figure.canvas.draw()
        renderer = result.figure.canvas.get_renderer()
        legend = ax.get_legend()
        self.assertIsNotNone(legend)
        leg_box = legend.get_window_extent(renderer)
        for tick in ax.get_yticklabels():
            if tick.get_visible():
                tick_box = tick.get_window_extent(renderer)
                self.assertFalse(leg_box.overlaps(tick_box), (leg_box.bounds, tick_box.bounds))
        # Apply Format Graph / Inspector style and ensure PolyCollection & gaps remain intact.
        apply_style(result.figure, {"title": "Formatted Map"})
        self.assertEqual(ax.get_title(), "Formatted Map")
        self.assertEqual(ax.get_ylim(), (3.6, 0.0))
        self.assertIsInstance(ax.collections[0], PolyCollection)

    def test_stress_80x120_uses_single_aggregated_collection(self):
        rng = np.random.default_rng(7)
        cols = [f"C{j:03d}" for j in range(120)]
        data = {"Row": [f"R{i:02d}" for i in range(80)]}
        for j, name in enumerate(cols):
            data[name] = rng.normal(loc=j * 0.1, size=80)
        frame = pd.DataFrame(data)
        opts = {
            "Input format": "Matrix",
            "Variables": cols,
            "Row labels": "Row",
            ROW_GAP_MODE: "Every boundary",
            ROW_GAP_SIZE: 0.15,
            COLUMN_GAP_MODE: "Every boundary",
            COLUMN_GAP_SIZE: 0.15,
        }
        result = analyse(HEAT_MAP, frame, opts)
        ax = result.figure.axes[0]
        self.assertEqual(len(ax.collections), 1)
        self.assertIsInstance(ax.collections[0], PolyCollection)
        self.assertEqual(len(ax.patches), 0)
        self.assertEqual(len(result.tables["Heat map layout"]), 80 * 120)

    def test_project_save_load_preserves_canonical_layout_options(self):
        opts = {
            "Input format": "Matrix",
            "Variables": ["A", "B", "C", "D"],
            "Row labels": "Row",
            ROW_GAP_MODE: "Selected boundaries",
            ROW_GAP_SIZE: 0.25,
            ROW_GAPS_AFTER: "2",
            COLUMN_LABEL_ROTATION: "Vertical",
            COLUMN_LABEL_SIDE: "Top",
            ROW_LABEL_FONT_SIZE: 10.5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout-roundtrip.alab"
            save_project(path, {"M": Dataset(self.matrix, analyses=[(HEAT_MAP, opts)])})
            loaded = load_project(path)
            saved_method, saved_opts = loaded["M"].analyses[0]
            self.assertEqual(saved_method, HEAT_MAP)
            self.assertEqual(saved_opts, opts)


if __name__ == "__main__":
    unittest.main()
