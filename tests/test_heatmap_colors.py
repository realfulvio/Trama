"""0.72 heat-map colors and legends: gradients, opacity, category colors, color bar, validation, persistence."""
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import QuadMesh

from analisi.data import Dataset, load_project, save_project
from analisi.heatmap import (CATEGORY_COLORS, COLOR_MAPPING, HEAT_MAP, LEGEND_INTERVAL, LEGEND_START, MAX_TICKS,
                             OPACITY, REVERSE_LEGEND, SHOW_LEGEND, category_levels, visibility)
from analisi.processing import FieldError
from analisi.workbench import analyse
from tests.heatmap_color_oracle import color, rgba, ticks

DATA = Path(__file__).parent / "data" / "heatmap_072"
LOW, MID, HIGH = ("Color minimum (blank = automatic)", "Color midpoint (blank = automatic)",
                  "Color maximum (blank = automatic)")
OUTSIDE = "Out-of-range color (blank = clamp)"
CUSTOM = {"low": "#112233", "high": "#cc8844", "LOW": "#aa1177", "1": "#88bb22", "01": "#2255bb"}


def numeric_options(**changes):
    return {"Input format": "Matrix", "Variables": ["A", "B"], "Row labels": "Row", LOW: 0., HIGH: 4.,
            "Missing color": "#445566", **changes}


def category_options(**changes):
    return {"Input format": "Long categories", "X categories": "X", "Y categories": "Y", "Values": "Class",
            "Missing color": "#445566", **changes}


def mesh(result):
    result.figure.canvas = FigureCanvasAgg(result.figure)
    result.figure.canvas.draw()
    return next(c for ax in result.figure.axes for c in ax.collections if isinstance(c, QuadMesh))


class HeatMapColorTests(unittest.TestCase):
    def setUp(self):
        self.numeric = pd.read_csv(DATA / "numeric.csv")
        self.categories = pd.read_csv(DATA / "categories.csv", dtype=str)

    def run_numeric(self, **changes):
        return analyse(HEAT_MAP, self.numeric, numeric_options(**changes))

    def error_field(self, frame, options):
        with self.assertRaises(FieldError) as caught:
            analyse(HEAT_MAP, frame, options)
        return caught.exception.field

    # ----- legacy -----------------------------------------------------------------------------------------------
    def test_frozen_legacy_recipes_are_unchanged(self):
        frozen = json.loads((DATA / "legacy-072.json").read_text(encoding="utf-8"))
        cases = {"matrix": (self.numeric, numeric_options()),
                 "diverging": (self.numeric, numeric_options(Palette="Blue–red", **{"Color scale": "Diverging", MID: 1.})),
                 "categorical": (self.categories, category_options())}
        for name, (frame, options) in cases.items():
            with self.subTest(name):
                result = analyse(HEAT_MAP, frame, options)
                np.testing.assert_allclose(mesh(result).get_facecolors(), frozen[name]["rgba"], rtol=1e-12, atol=1e-12)
                table = result.tables["Heat map data"]
                self.assertEqual(list(result.tables), frozen[name]["sheets"])
                self.assertEqual(list(table.index), frozen[name]["index"])
                legend = result.figure.axes[0].get_legend()
                self.assertEqual([t.get_text() for t in legend.get_texts()] if legend else [], frozen[name]["legend"])

    def test_saved_legacy_project_opens_without_new_options(self):
        loaded = load_project(DATA / "legacy-072.alab")
        for dataset in loaded.values():
            for method, options in dataset.analyses:
                self.assertEqual(method, HEAT_MAP)
                self.assertFalse({COLOR_MAPPING, OPACITY, CATEGORY_COLORS, SHOW_LEGEND} & set(options))

    # ----- numeric colors ---------------------------------------------------------------------------------------
    def expected(self, mapping, opacity=1., outside=None):
        return [color(v, low=0., high=4., minimum="#000000", maximum="#ffffff", opacity=opacity, midpoint=1.,
                      middle="#00ff00" if mapping == "Double gradient" else None, outside=outside)
                for v in self.numeric[["A", "B"]].to_numpy().flat]

    def gradient(self, mapping, opacity=1., outside=None):
        options = {COLOR_MAPPING: mapping, "Minimum color": "#000000", "Midpoint color": "#00ff00",
                   "Maximum color": "#ffffff", OPACITY: opacity, MID: 1.}
        if outside:
            options[OUTSIDE] = outside
        result = self.run_numeric(**options)
        actual = mesh(result).get_facecolors()
        expected = np.array(self.expected(mapping, opacity, outside))
        np.testing.assert_allclose(actual, expected, rtol=0, atol=2 / 255)
        np.testing.assert_allclose(actual[:, 3], expected[:, 3], atol=1e-12)
        np.testing.assert_allclose(result.tables["Heat map data"].to_numpy(), self.numeric[["A", "B"]].to_numpy(),
                                   equal_nan=True)
        return actual

    def test_single_and_double_gradient_follow_the_oracle(self):
        for mapping in ("Single gradient", "Double gradient"):
            for opacity in (1., .25, 0.):
                for outside in (None, "#ff0000"):
                    with self.subTest(mapping=mapping, opacity=opacity, outside=outside):
                        self.gradient(mapping, opacity, outside)

    def test_gradient_anchors_are_exact_and_midpoint_is_asymmetric(self):
        values = pd.DataFrame({"Row": ["a", "b", "c", "d"], "V": [0., 1., 4., .5]})
        options = {"Input format": "Matrix", "Variables": ["V"], "Row labels": "Row", LOW: 0., HIGH: 4.,
                   COLOR_MAPPING: "Double gradient", "Minimum color": "#ff0000", "Midpoint color": "#00ff00",
                   "Maximum color": "#0000ff", MID: 1.}
        faces = mesh(analyse(HEAT_MAP, values, options)).get_facecolors()
        np.testing.assert_allclose(faces[0], rgba("#ff0000"), atol=1e-12)
        np.testing.assert_allclose(faces[2], rgba("#0000ff"), atol=1e-12)
        np.testing.assert_allclose(faces[1], rgba("#00ff00"), atol=1 / 1000)
        np.testing.assert_allclose(faces[3], [.5, .5, 0, 1], atol=1 / 1000)

    def test_source_alpha_is_interpolated_and_multiplied_by_opacity(self):
        values = pd.DataFrame({"Row": ["a", "b", "c"], "V": [0., 2., 4.]})
        options = {"Input format": "Matrix", "Variables": ["V"], "Row labels": "Row", LOW: 0., HIGH: 4.,
                   COLOR_MAPPING: "Single gradient", "Minimum color": "#00000040", "Maximum color": "#ffffffc0",
                   OPACITY: .5}
        faces = mesh(analyse(HEAT_MAP, values, options)).get_facecolors()
        low, high = 0x40 / 255, 0xc0 / 255
        np.testing.assert_allclose(faces[:, 3], [low * .5, (low + high) / 4, high * .5], atol=2e-4)

    def test_opacity_leaves_the_missing_color_alone_and_applies_to_palettes(self):
        faces = mesh(self.run_numeric(**{OPACITY: .3})).get_facecolors()
        np.testing.assert_allclose(faces[:, 3][:9], .3, atol=1e-12)
        np.testing.assert_allclose(faces[-1], rgba("#445566"), atol=1e-12)
        zero = mesh(self.run_numeric(**{OPACITY: 0.})).get_facecolors()
        self.assertEqual(float(zero[:, 3][:9].max()), 0.)
        self.assertEqual(float(zero[-1][3]), 1.)

    def test_inactive_palette_and_scale_do_not_affect_or_block_a_gradient(self):
        plain = mesh(self.run_numeric(**{COLOR_MAPPING: "Single gradient"})).get_facecolors()
        other = mesh(self.run_numeric(**{COLOR_MAPPING: "Single gradient", "Palette": "Magma",
                                         "Color scale": "Diverging"})).get_facecolors()
        np.testing.assert_array_equal(plain, other)
        broken = mesh(self.run_numeric(**{COLOR_MAPPING: "Single gradient", "Palette": "nope",
                                          "Color scale": "nope", MID: "x", "Midpoint color": "bad"})).get_facecolors()
        np.testing.assert_array_equal(plain, broken)
        self.assertEqual(self.error_field(self.numeric, numeric_options(Palette="nope")), "Palette")

    def test_inactive_gradient_colors_do_not_block_a_palette(self):
        mesh(self.run_numeric(**{"Minimum color": "bad", "Maximum color": 3}))

    def test_double_gradient_needs_ordered_limits(self):
        self.assertEqual(self.error_field(self.numeric, numeric_options(**{COLOR_MAPPING: "Double gradient", MID: 9.})),
                         MID)
        self.assertEqual(self.error_field(self.numeric, numeric_options(**{COLOR_MAPPING: "Triple"})), COLOR_MAPPING)

    def test_constant_matrix_keeps_the_automatic_limits_with_a_gradient(self):
        flat = pd.DataFrame({"Row": ["a", "b"], "V": [3., 3.]})
        result = analyse(HEAT_MAP, flat, {"Input format": "Matrix", "Variables": ["V"], "Row labels": "Row",
                                          COLOR_MAPPING: "Single gradient"})
        self.assertEqual(len(mesh(result).get_facecolors()), 2)

    def test_single_row_and_column_and_wide_units(self):
        small = pd.DataFrame({"Row": ["a"], "V": [1e-12]})
        mesh(analyse(HEAT_MAP, small, {"Input format": "Matrix", "Variables": ["V"], "Row labels": "Row",
                                       COLOR_MAPPING: "Double gradient", OPACITY: .5}))

    def test_horizontal_colorbar_tracks_the_map_width_after_resize(self):
        for shape in ((10, 2), (2, 10), (4, 4)):
            for cell_shape in ("Square", "Stretch"):
                frame = pd.DataFrame({f"C{i}": range(shape[0]) for i in range(shape[1])})
                result = analyse(HEAT_MAP, frame, {"Variables": list(frame.columns), "Cell shape": cell_shape,
                                                   "Color legend orientation": "Horizontal",
                                                   "Color legend title": "Signal"})
                for size in ((8, 5), (5, 7)):
                    with self.subTest(shape=shape, cell_shape=cell_shape, size=size):
                        result.figure.set_size_inches(*size)
                        mesh(result)
                        axes, bar = result.figure.axes
                        np.testing.assert_allclose([axes.get_position().x0, axes.get_position().x1],
                                                   [bar.get_position().x0, bar.get_position().x1], atol=1e-9)
                        bounds = bar.get_tightbbox(result.figure.canvas.get_renderer())
                        self.assertGreaterEqual(bounds.y0, 0)
                        self.assertLessEqual(bounds.y1, result.figure.bbox.height)

    # ----- categories -------------------------------------------------------------------------------------------
    def test_category_colors_follow_the_level_text(self):
        result = analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM}))
        expected = [rgba(CUSTOM.get(v, "#445566")) for v in ["low", "high", "LOW", "1", "01", None]]
        np.testing.assert_allclose(mesh(result).get_facecolors(), expected, atol=1e-12)
        self.assertEqual([t.get_text() for t in result.figure.axes[0].get_legend().get_texts()], list(CUSTOM))

    def test_transpose_and_reverse_do_not_reassign_colors(self):
        base = mesh(analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM}))).get_facecolors()
        by_cell = {}
        for options in ({}, {"Transpose": True}, {"Reverse rows": True}, {"Reverse columns": True, "Transpose": True}):
            result = analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM}, **options))
            table = result.tables["Heat map data"]
            faces = mesh(result).get_facecolors().reshape(*table.shape, 4)
            for (row, col), value in np.ndenumerate(table.to_numpy()):
                if value is not None and not pd.isna(value):
                    np.testing.assert_allclose(faces[row, col], rgba(CUSTOM[value]), atol=1e-12)
        self.assertEqual(len(base), 6)

    def test_unmapped_levels_keep_the_legacy_palette_and_extra_pairs_wait(self):
        partial = {"low": "#112233", "never seen": "#abcdef"}
        legacy = mesh(analyse(HEAT_MAP, self.categories, category_options())).get_facecolors()
        result = mesh(analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: partial})))
        faces = result.get_facecolors()
        np.testing.assert_allclose(faces[0], rgba("#112233"), atol=1e-12)
        np.testing.assert_allclose(faces[1:5], legacy[1:5], atol=1e-12)

    def test_category_levels_keep_case_and_leading_zero_and_first_occurrence(self):
        self.assertEqual(category_levels(self.categories, category_options()), ["low", "high", "LOW", "1", "01"])

    def test_returning_level_regains_its_color(self):
        shown = self.categories.copy()
        gone = shown[shown["Class"] != "high"]
        options = category_options(**{CATEGORY_COLORS: CUSTOM})
        self.assertNotIn("high", analyse(HEAT_MAP, gone, options).figure.axes[0].get_legend().get_texts()[1].get_text())
        again = mesh(analyse(HEAT_MAP, shown, options)).get_facecolors()
        np.testing.assert_allclose(again[1], rgba("#cc8844"), atol=1e-12)

    def test_category_color_mapping_is_validated(self):
        for bad in ([], "x", {"a": "nope"}, {"": "#112233"}, {1: "#112233"}, {"a": 3}, {"a": None},
                    {str(i): "#112233" for i in range(501)}):
            with self.subTest(bad=bad):
                self.assertEqual(self.error_field(self.categories, category_options(**{CATEGORY_COLORS: bad})),
                                 CATEGORY_COLORS)

    def test_category_opacity_and_reverse_legend_only_change_what_they_name(self):
        plain = mesh(analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM}))).get_facecolors()
        faded = mesh(analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM, OPACITY: .4})))
        np.testing.assert_allclose(faded.get_facecolors()[:5, :3], plain[:5, :3], atol=1e-12)
        np.testing.assert_allclose(faded.get_facecolors()[:5, 3], .4, atol=1e-12)
        np.testing.assert_allclose(faded.get_facecolors()[5], rgba("#445566"), atol=1e-12)
        reverse = analyse(HEAT_MAP, self.categories, category_options(**{CATEGORY_COLORS: CUSTOM, REVERSE_LEGEND: True}))
        np.testing.assert_allclose(mesh(reverse).get_facecolors(), plain, atol=1e-12)
        self.assertEqual([t.get_text() for t in reverse.figure.axes[0].get_legend().get_texts()], list(CUSTOM)[::-1])

    def test_missing_cells_are_not_a_legend_entry_and_hidden_legend_is_absent(self):
        result = analyse(HEAT_MAP, self.categories, category_options(**{SHOW_LEGEND: False}))
        self.assertIsNone(result.figure.axes[0].get_legend())
        self.assertEqual(len(result.figure.axes), 1)

    def test_category_title_is_literal(self):
        result = analyse(HEAT_MAP, self.categories, category_options(**{"Color legend title": "$a$ b"}))
        title = result.figure.axes[0].get_legend().get_title()
        self.assertEqual(title.get_text(), "$a$ b")
        self.assertFalse(title.get_parse_math())

    # ----- numeric legend ---------------------------------------------------------------------------------------
    def test_orientation_reverse_title_and_ticks(self):
        bar = mesh(self.run_numeric(**{"Color legend orientation": "Horizontal", REVERSE_LEGEND: True,
                                       "Color legend title": "$x$ (a.u.)", LEGEND_INTERVAL: 1., LEGEND_START: .5})).colorbar
        self.assertEqual(bar.orientation, "horizontal")
        self.assertTrue(bar.ax.xaxis_inverted())
        self.assertEqual(bar.ax.get_xlabel(), "$x$ (a.u.)")
        self.assertFalse(bar.ax.xaxis.label.get_parse_math())
        np.testing.assert_allclose(bar.get_ticks(), ticks(0, 4, 1, .5), atol=1e-12)

    def test_reverse_changes_only_the_bar(self):
        a = mesh(self.run_numeric()).get_facecolors()
        b = mesh(self.run_numeric(**{REVERSE_LEGEND: True}))
        np.testing.assert_allclose(a, b.get_facecolors())
        self.assertTrue(b.colorbar.ax.yaxis_inverted())

    def test_decimal_text_and_italian_comma_are_accepted(self):
        bar = mesh(self.run_numeric(**{LEGEND_INTERVAL: "0,5", LEGEND_START: "1,25"})).colorbar
        np.testing.assert_allclose(bar.get_ticks(), ticks(0, 4, .5, 1.25), atol=1e-12)

    def test_ticks_never_exceed_the_range_and_automatic_start_is_inactive(self):
        bar = mesh(self.run_numeric(**{LEGEND_INTERVAL: 1.5})).colorbar
        np.testing.assert_allclose(bar.get_ticks(), [0, 1.5, 3])
        mesh(self.run_numeric(**{LEGEND_START: "not a number"}))

    def test_tick_budget_is_checked_before_anything_is_built(self):
        self.assertEqual(self.error_field(self.numeric, numeric_options(**{LEGEND_INTERVAL: 4 / MAX_TICKS})),
                         LEGEND_INTERVAL)
        self.assertEqual(self.error_field(self.numeric, numeric_options(**{LEGEND_INTERVAL: 1e-300})), LEGEND_INTERVAL)
        mesh(self.run_numeric(**{LEGEND_INTERVAL: 4 / (MAX_TICKS - 1) + 1e-9}))

    def test_legend_field_errors_name_their_field(self):
        cases = [({LEGEND_INTERVAL: 0.}, LEGEND_INTERVAL), ({LEGEND_INTERVAL: -1.}, LEGEND_INTERVAL),
                 ({LEGEND_INTERVAL: math.inf}, LEGEND_INTERVAL), ({LEGEND_INTERVAL: True}, LEGEND_INTERVAL),
                 ({LEGEND_INTERVAL: "x"}, LEGEND_INTERVAL),
                 ({LEGEND_INTERVAL: 1., LEGEND_START: 8.}, LEGEND_START),
                 ({LEGEND_INTERVAL: 1., LEGEND_START: -.1}, LEGEND_START),
                 ({LEGEND_INTERVAL: 1., LEGEND_START: math.nan}, LEGEND_START),
                 ({OPACITY: True}, OPACITY), ({OPACITY: "x"}, OPACITY), ({OPACITY: math.nan}, OPACITY),
                 ({REVERSE_LEGEND: "yes"}, REVERSE_LEGEND), ({SHOW_LEGEND: 1}, SHOW_LEGEND),
                 ({"Color legend orientation": "Diagonal"}, "Color legend orientation"),
                 ({"Color legend title": 3}, "Color legend title")]
        for changes, field in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.error_field(self.numeric, numeric_options(**changes)), field)

    def test_start_on_the_limits_is_valid(self):
        for start in (0., 4.):
            bar = mesh(self.run_numeric(**{LEGEND_INTERVAL: 2., LEGEND_START: start})).colorbar
            self.assertEqual(float(bar.get_ticks()[0]), start if start == 0 else 4.)

    def test_hidden_legend_has_no_axis_and_ignores_legend_fields(self):
        result = self.run_numeric(**{SHOW_LEGEND: False, LEGEND_INTERVAL: 0., "Color legend orientation": "Horizontal"})
        self.assertIsNone(mesh(result).colorbar)
        self.assertEqual(len(result.figure.axes), 1)
        np.testing.assert_allclose(mesh(result).get_facecolors(), mesh(self.run_numeric()).get_facecolors())

    def test_color_bar_shares_norm_colormap_and_extremes(self):
        result = self.run_numeric(**{COLOR_MAPPING: "Double gradient", MID: 1., OPACITY: .5, OUTSIDE: "#ff0000"})
        plot = mesh(result)
        self.assertIs(plot.colorbar.mappable.norm, plot.norm)
        self.assertIs(plot.colorbar.mappable.cmap, plot.cmap)
        self.assertEqual(plot.colorbar.extend, "both")
        np.testing.assert_allclose(plot.cmap.get_under(), (1, 0, 0, .5))
        self.assertIs(result.figure.axes[0].collections[0], plot)  # the map is the first axes, not the bar

    def test_legend_choices_do_not_change_results_or_data(self):
        base = self.run_numeric()
        other = self.run_numeric(**{"Color legend orientation": "Horizontal", REVERSE_LEGEND: True,
                                    "Color legend title": "T", LEGEND_INTERVAL: 1.})
        pd.testing.assert_frame_equal(base.tables["Heat map data"], other.tables["Heat map data"])
        self.assertEqual(list(base.tables), list(other.tables))

    def test_frame_is_not_modified(self):
        before = self.numeric.copy(deep=True)
        self.run_numeric(**{COLOR_MAPPING: "Double gradient", OPACITY: .5})
        pd.testing.assert_frame_equal(self.numeric, before)

    # ----- visibility and persistence ---------------------------------------------------------------------------
    def test_visibility_follows_the_choices(self):
        shown = visibility("Matrix", "Linear", "Palette", "")
        self.assertTrue(shown["Palette"] and not shown["Minimum color"] and not shown["Color legend start"])
        single = visibility("Matrix", "Diverging", "Single gradient", "0.5")
        self.assertTrue(single["Minimum color"] and single["Maximum color"] and not single["Midpoint color"])
        self.assertFalse(single["Palette"] or single["Color scale"] or single["Color midpoint (blank = automatic)"])
        self.assertTrue(single["Color legend start"])
        double = visibility("Matrix", "Linear", "Double gradient", None)
        self.assertTrue(double["Midpoint color"] and double["Color midpoint (blank = automatic)"])
        categories = visibility("Long categories", "Linear", "Palette", "")
        self.assertTrue(categories[CATEGORY_COLORS])
        self.assertFalse(categories["Color legend orientation"] or categories[COLOR_MAPPING])
        hidden = visibility("Matrix", "Linear", "Palette", "1", show_legend=False)
        self.assertFalse(any(hidden[name] for name in (REVERSE_LEGEND, "Color legend title", "Color legend orientation",
                                                       LEGEND_INTERVAL, LEGEND_START)))

    def test_options_survive_a_project_round_trip(self):
        options = category_options(**{CATEGORY_COLORS: CUSTOM, OPACITY: .5, REVERSE_LEGEND: True,
                                      "Color legend title": "$x$"})
        numeric = numeric_options(**{COLOR_MAPPING: "Double gradient", "Minimum color": "#112233",
                                     LEGEND_INTERVAL: "0,5", LEGEND_START: "0,5", MID: 1.})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "heat.alab"
            save_project(path, {"Numeric": Dataset(self.numeric.copy(), analyses=[(HEAT_MAP, numeric)]),
                                "Categories": Dataset(self.categories.copy(), analyses=[(HEAT_MAP, options)])})
            loaded = load_project(path)
        self.assertEqual(loaded["Categories"].analyses[0][1], options)
        self.assertEqual(loaded["Numeric"].analyses[0][1], numeric)
        first = analyse(HEAT_MAP, loaded["Categories"].frame(), loaded["Categories"].analyses[0][1])
        np.testing.assert_allclose(mesh(first).get_facecolors()[0], rgba(CUSTOM["low"], .5), atol=1e-12)

    def test_exports_keep_the_gradient_and_the_bar(self):
        result = self.run_numeric(**{COLOR_MAPPING: "Double gradient", MID: 1., "Color legend orientation": "Horizontal"})
        with tempfile.TemporaryDirectory() as folder:
            for extension in ("png", "svg", "pdf"):
                path = Path(folder) / f"heat.{extension}"
                result.figure.savefig(path)
                self.assertGreater(path.stat().st_size, 1000, extension)


if __name__ == "__main__":
    unittest.main()
