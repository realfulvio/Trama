"""Unit tests for heat-map color legend number formatting and validation."""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import QuadMesh

from analisi.data import Dataset, load_project, save_project
from analisi.heatmap import (HEAT_MAP, LEGEND_INTERVAL, LEGEND_START, REVERSE_LEGEND, SHOW_LEGEND, visibility)
from analisi.processing import FieldError
from analisi.workbench import analyse

NUMBER_FORMAT = "Color legend number format"
LEGEND_DECIMALS = "Color legend decimals"

FORMAT_CASES = [
    (0.1, "Fixed", 2, "0.10"),
    (1.234, "Fixed", 2, "1.23"),
    (-0.0001, "Fixed", 2, "0.00"),
    (-12.3456, "Fixed", 3, "-12.346"),
    (0, "Fixed", 0, "0"),
    (0.0001234, "Scientific", 2, "1.23e-04"),
    (-0.0, "Scientific", 2, "0.00e+00"),
    (1234000, "Scientific", 3, "1.234e+06"),
    (-0.0001234, "Scientific", 1, "-1.2e-04"),
    (1e-09, "Fixed", 8, "0.00000000"),
    (123, "Automatic", 2, None),
]


def _mesh(result):
    result.figure.canvas = FigureCanvasAgg(result.figure)
    result.figure.canvas.draw()
    return next(c for ax in result.figure.axes for c in ax.collections if isinstance(c, QuadMesh))


class FormatLegendHelperTests(unittest.TestCase):
    def test_format_cases_match_specification(self):
        from analisi.heatmap_number_format import format_legend_value

        for value, mode, decimals, expected in FORMAT_CASES:
            with self.subTest(value=value, mode=mode, decimals=decimals):
                self.assertEqual(format_legend_value(value, mode, decimals), expected)

    def test_non_finite_or_boolean_values_raise_value_error(self):
        from analisi.heatmap_number_format import format_legend_value

        for bad_value in (math.nan, math.inf, -math.inf, True, False, "1.5", None):
            with self.subTest(value=bad_value):
                with self.assertRaises(ValueError):
                    format_legend_value(bad_value, "Fixed", 2)

    def test_invalid_mode_and_decimals_raise_value_error(self):
        from analisi.heatmap_number_format import format_legend_value

        with self.assertRaises(ValueError):
            format_legend_value(1.0, "Engineering", 2)
        for bad_decimals in (-1, 9, True, False, 2.5, 2.0, "2", math.nan, math.inf, None):
            with self.subTest(decimals=bad_decimals):
                with self.assertRaises(ValueError):
                    format_legend_value(1.0, "Fixed", bad_decimals)

    def test_parse_decimals_accepts_integral_numbers_and_decimal_comma_strings(self):
        from analisi.heatmap_number_format import parse_legend_decimals

        for raw, expected in ((0, 0), (8, 8), (2.0, 2), ("2", 2), (" 3 ", 3), ("2.0", 2), ("2,0", 2), (np.int64(4), 4)):
            with self.subTest(raw=raw):
                self.assertEqual(parse_legend_decimals(raw), expected)

    def test_parse_decimals_rejects_booleans_fractions_range_and_non_finite(self):
        from analisi.heatmap_number_format import parse_legend_decimals

        for bad in (-1, 9, 2.5, "2,5", "2.5", True, False, np.bool_(True), math.nan, math.inf, -math.inf,
                    "inf", "-inf", "nan", "", "   ", "abc", "2_0", None):
            with self.subTest(bad=bad):
                with self.assertRaises(FieldError) as caught:
                    parse_legend_decimals(bad)
                self.assertEqual(caught.exception.field, LEGEND_DECIMALS)


class HeatMapLegendNumberFormatTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Row": ["r1", "r2"], "A": [0.0, 0.25], "B": [0.5, 1.0]})
        self.base = {
            "Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row",
            "Color minimum (blank = automatic)": 0, "Color maximum (blank = automatic)": 1,
            LEGEND_INTERVAL: 0.25, LEGEND_START: 0,
        }

    def test_automatic_preserves_legacy_ticks_labels_and_ignores_invalid_decimals(self):
        legacy = analyse(HEAT_MAP, self.frame, self.base)
        auto = analyse(HEAT_MAP, self.frame, {**self.base, NUMBER_FORMAT: "Automatic", LEGEND_DECIMALS: "bad-old"})
        legacy_mesh = _mesh(legacy)
        auto_mesh = _mesh(auto)
        np.testing.assert_array_equal(legacy_mesh.colorbar.get_ticks(), auto_mesh.colorbar.get_ticks())
        self.assertEqual(
            [t.get_text() for t in legacy_mesh.colorbar.ax.yaxis.get_ticklabels()],
            [t.get_text() for t in auto_mesh.colorbar.ax.yaxis.get_ticklabels()],
        )
        np.testing.assert_allclose(legacy_mesh.get_facecolors(), auto_mesh.get_facecolors(), rtol=0, atol=0)
        pd.testing.assert_frame_equal(legacy.tables["Heat map data"], auto.tables["Heat map data"])

    def test_fixed_and_scientific_modes_across_orientations_and_reversals(self):
        from analisi.heatmap_number_format import format_legend_value

        for mode in ("Fixed", "Scientific"):
            for decimals in (0, 2, 3):
                for orientation in ("Vertical", "Horizontal"):
                    for reverse in (False, True):
                        with self.subTest(mode=mode, decimals=decimals, orientation=orientation, reverse=reverse):
                            opts = {
                                **self.base,
                                NUMBER_FORMAT: mode,
                                LEGEND_DECIMALS: decimals,
                                "Color legend orientation": orientation,
                                REVERSE_LEGEND: reverse,
                                "Color legend title": "$x$ (a.u.)",
                            }
                            result = analyse(HEAT_MAP, self.frame, opts)
                            plot = _mesh(result)
                            bar = plot.colorbar
                            axis = bar.ax.xaxis if orientation == "Horizontal" else bar.ax.yaxis
                            ticks = bar.get_ticks()
                            labels = [t.get_text() for t in axis.get_ticklabels()]
                            self.assertEqual(labels, [format_legend_value(float(v), mode, decimals) for v in ticks])
                            self.assertEqual(axis.get_offset_text().get_text(), "")
                            self.assertFalse(axis.label.get_parse_math())

                            control = analyse(HEAT_MAP, self.frame, {
                                **self.base,
                                "Color legend orientation": orientation,
                                REVERSE_LEGEND: reverse,
                                "Color legend title": "$x$ (a.u.)",
                            })
                            ctrl_plot = _mesh(control)
                            np.testing.assert_array_equal(ticks, ctrl_plot.colorbar.get_ticks())
                            np.testing.assert_allclose(plot.get_facecolors(), ctrl_plot.get_facecolors(), rtol=0, atol=0)
                            pd.testing.assert_frame_equal(result.tables["Heat map data"], control.tables["Heat map data"])

                            result.figure.set_size_inches(6, 4)
                            result.figure.canvas.draw()
                            self.assertEqual([t.get_text() for t in axis.get_ticklabels()], labels)

    def test_automatic_ticks_without_explicit_interval_and_extreme_values_have_no_offset(self):
        small = pd.DataFrame({"Row": ["r1", "r2"], "A": [1e-5, 2e-5], "B": [3e-5, 4e-5]})
        result = analyse(HEAT_MAP, small, {
            "Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row",
            NUMBER_FORMAT: "Scientific", LEGEND_DECIMALS: 2,
        })
        plot = _mesh(result)
        axis = plot.colorbar.ax.yaxis
        self.assertEqual(axis.get_offset_text().get_text(), "")
        labels = [t.get_text() for t in axis.get_ticklabels()]
        self.assertTrue(all("e-" in label for label in labels), labels)

    def test_duplicate_rounded_labels_keep_all_ticks_and_positions(self):
        opts = {
            "Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row",
            "Color minimum (blank = automatic)": 0, "Color maximum (blank = automatic)": 1,
            LEGEND_INTERVAL: 0.25, LEGEND_START: 0,
            NUMBER_FORMAT: "Fixed", LEGEND_DECIMALS: 0,
        }
        result = analyse(HEAT_MAP, self.frame, opts)
        bar = _mesh(result).colorbar
        np.testing.assert_allclose(bar.get_ticks(), [0.0, 0.25, 0.5, 0.75, 1.0])
        self.assertEqual([t.get_text() for t in bar.ax.yaxis.get_ticklabels()], ["0", "0", "0", "1", "1"])

    def test_validation_errors_target_canonical_fields(self):
        with self.assertRaises(FieldError) as caught:
            analyse(HEAT_MAP, self.frame, {**self.base, NUMBER_FORMAT: "invalid"})
        self.assertEqual(caught.exception.field, NUMBER_FORMAT)

        for bad in (-1, 9, 2.5, True, "inf", "2,5", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(FieldError) as caught:
                    analyse(HEAT_MAP, self.frame, {**self.base, NUMBER_FORMAT: "Fixed", LEGEND_DECIMALS: bad})
                self.assertEqual(caught.exception.field, LEGEND_DECIMALS)

    def test_hidden_legend_and_categorical_ignore_format_fields(self):
        hidden = analyse(HEAT_MAP, self.frame, {
            **self.base, SHOW_LEGEND: False, NUMBER_FORMAT: "invalid", LEGEND_DECIMALS: "invalid",
        })
        self.assertEqual(len(hidden.figure.axes), 1)

        cats = pd.DataFrame({"X": ["x1", "x2"], "Y": ["y1", "y1"], "Class": ["1.234", "01"]})
        cat_result = analyse(HEAT_MAP, cats, {
            "Input format": "Long categories", "X categories": "X", "Y categories": "Y", "Values": "Class",
            NUMBER_FORMAT: "Fixed", LEGEND_DECIMALS: 1,
        })
        FigureCanvasAgg(cat_result.figure).draw()
        self.assertEqual({t.get_text() for t in cat_result.figure.axes[0].get_legend().get_texts()}, {"1.234", "01"})

    def test_visibility_and_project_round_trip_and_exports(self):
        auto_vis = visibility("Matrix", "Linear", number_format="Automatic")
        self.assertTrue(auto_vis[NUMBER_FORMAT])
        self.assertFalse(auto_vis[LEGEND_DECIMALS])

        fixed_vis = visibility("Matrix", "Linear", number_format="Fixed")
        self.assertTrue(fixed_vis[NUMBER_FORMAT] and fixed_vis[LEGEND_DECIMALS])

        sci_vis = visibility("Matrix", "Linear", number_format="Scientific")
        self.assertTrue(sci_vis[NUMBER_FORMAT] and sci_vis[LEGEND_DECIMALS])

        hidden_vis = visibility("Matrix", "Linear", show_legend=False, number_format="Scientific")
        self.assertFalse(hidden_vis[NUMBER_FORMAT] or hidden_vis[LEGEND_DECIMALS])

        cat_vis = visibility("Long categories", "Linear", number_format="Scientific")
        self.assertFalse(cat_vis[NUMBER_FORMAT] or cat_vis[LEGEND_DECIMALS])

        opts = {**self.base, NUMBER_FORMAT: "Scientific", LEGEND_DECIMALS: "3,0"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fmt.alab"
            save_project(path, {"Numeric": Dataset(self.frame.copy(), analyses=[(HEAT_MAP, opts)])})
            loaded = load_project(path)
            result = analyse(HEAT_MAP, loaded["Numeric"].frame(), loaded["Numeric"].analyses[0][1])
            bar = _mesh(result).colorbar
            self.assertEqual([t.get_text() for t in bar.ax.yaxis.get_ticklabels()],
                             ["0.000e+00", "2.500e-01", "5.000e-01", "7.500e-01", "1.000e+00"])
            for ext in ("png", "svg", "pdf"):
                out = Path(folder) / f"heat.{ext}"
                result.figure.savefig(out)
                self.assertGreater(out.stat().st_size, 1000, ext)


if __name__ == "__main__":
    unittest.main()
