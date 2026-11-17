"""Presentation overrides for native hierarchical clustering graphs.

These tests drive the public style API and the existing renderer. They do not
reimplement branch geometry, linkage or the package verifier.
"""
import copy
import json
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator, MultipleLocator

from analisi.data import Dataset, load_workspace, save_project
from analisi.hierarchical_style import (
    HierarchicalStyleError,
    apply_hierarchical_style,
    baseline_hierarchical_style,
    describe_hierarchical_artists,
    snapshot_hierarchical_style,
    validate_hierarchical_style,
)
from analisi.hierarchical_workbench import hierarchical_result
from analisi.presentation import apply_style, validated_style
from analisi.stats import hierarchical


def _frame(rows=4):
    base = np.array([[0.0, 0.0], [0.2, 0.1], [8.0, 9.0], [8.4, 8.7]], dtype=float)
    if rows == 4:
        values = base
    else:
        rng = np.random.default_rng(11)
        values = np.vstack([base, rng.normal(size=(rows - 4, 2))])
    return pd.DataFrame(values, columns=["A", "B"])


def _options(**extra):
    options = {
        "Variables": ["A", "B"],
        "Direction": "Rows and columns",
        "Scale columns": "None",
        "Scale rows": "None",
        "Linkage": "average",
        "Distance": "euclidean",
        "Row cut": "Count",
        "Clusters": 2,
        "Column cut": "Count",
        "Column clusters": 2,
        "Graph output": "Heat map",
        "Label interval (0 = automatic)": 1,
    }
    options.update(extra)
    return options


def _result(**extra):
    return hierarchical_result(_frame(), _options(**extra))


def _heat(**extra):
    return _result(**extra).figure


def _draw(figure):
    FigureCanvasAgg(figure).draw()
    return figure.canvas.get_renderer()


def _hexes(artist):
    return {to_hex(row[:3], keep_alpha=False) for row in np.atleast_2d(artist.get_colors())}


def _segments(figure):
    described = describe_hierarchical_artists(figure)
    return {key: np.array(described[key]["branches"].get_segments()) for key in ("row", "column") if key in described}


class HierarchicalStyleValidationTests(unittest.TestCase):
    def test_canonical_copy_does_not_mutate_the_input(self):
        original = {"row": {"color": "blue", "palette": ["red", "#00FF00"], "width": 2}}
        snapshot = copy.deepcopy(original)
        canonical = validate_hierarchical_style(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(canonical["row"]["color"], "#0000ff")
        self.assertEqual(canonical["row"]["palette"], ["#ff0000", "#00ff00"])
        canonical["row"]["width"] = 9
        self.assertEqual(original["row"]["width"], 2)

    def test_empty_section_is_empty(self):
        self.assertEqual(validate_hierarchical_style({}), {})

    def test_rejected_values_name_the_field(self):
        cases = [
            ({"unknown": 1}, "unknown"),
            ({"row": {"width": True}}, "row.width"),
            ({"row": {"width": "2.5"}}, "row.width"),
            ({"row": {"width": 0}}, "row.width"),
            ({"row": {"width": 12.01}}, "row.width"),
            ({"row": {"alpha": float("nan")}}, "row.alpha"),
            ({"row": {"alpha": float("inf")}}, "row.alpha"),
            ({"column": {"palette": []}}, "column.palette"),
            ({"column": {"palette": ["#112233"] * 25}}, "column.palette"),
            ({"row": {"labels": {"rotation": 91}}}, "row.labels.rotation"),
            ({"row": {"labels": {"rotation": -90.1}}}, "row.labels.rotation"),
            ({"row": {"labels": {"size": 3}}}, "row.labels.size"),
            ({"row": {"labels": {"first": True}}}, "row.labels.first"),
            ({"row": {"labels": {"first": 0}}}, "row.labels.first"),
            ({"row": {"labels": {"interval": -1}}}, "row.labels.interval"),
            ({"row": {"labels": {"interval": 1.5}}}, "row.labels.interval"),
            ({"row": {"labels": {"extra": 1}}}, "row.labels.extra"),
            ({"row": {"color": "none"}}, "row.color"),
            ({"row": {"color": "#ff000080"}}, "row.color"),
            ({"row": {"distance": {"minimum": 4, "maximum": 4}}}, "row.distance.maximum"),
            ({"row": {"distance": {"step": 0}}}, "row.distance.step"),
            ({"heatmap": {"minimum": 1}}, "heatmap.maximum"),
            ({"heatmap": {"maximum": 2}}, "heatmap.minimum"),
            ({"heatmap": {"minimum": 2, "maximum": 2}}, "heatmap.maximum"),
            ({"heatmap": {"minimum": None, "maximum": 1}}, "heatmap.minimum"),
            ({"heatmap": {"cmap": "jet"}}, "heatmap.cmap"),
            ({"heatmap": {"title": "a\nb"}}, "heatmap.title"),
            ({"heatmap": {"title": "x" * 161}}, "heatmap.title"),
            ({"heatmap": {"title": "bad\u0001"}}, "heatmap.title"),
            ({"layout": {"row_tree_ratio": 0}}, "layout.row_tree_ratio"),
            ({"layout": {"column_tree_ratio": 1.01}}, "layout.column_tree_ratio"),
            ("row", "hierarchical"),
        ]
        for record, field in cases:
            with self.subTest(field=field):
                with self.assertRaises(HierarchicalStyleError) as caught:
                    validate_hierarchical_style(record)
                self.assertEqual(caught.exception.field, field)

    def test_literal_title_and_boundary_values_are_kept(self):
        title = "Signal $ literal (group)"
        canonical = validate_hierarchical_style({
            "heatmap": {"title": title, "minimum": None, "maximum": None, "orientation": "horizontal"},
            "layout": {"row_tree_ratio": 0.05, "column_tree_ratio": 1},
            "row": {"labels": {"rotation": -90, "size": 40, "interval": 0, "first": 1}, "alpha": 0, "width": 12},
        })
        self.assertEqual(canonical["heatmap"]["title"], title)
        self.assertIsNone(canonical["heatmap"]["minimum"])
        self.assertEqual(canonical["layout"]["column_tree_ratio"], 1)
        self.assertEqual(canonical["row"]["labels"]["rotation"], -90)

    def test_invalid_apply_does_not_mutate_artists(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        before = np.array(described["row"]["branches"].get_colors())
        widths = np.array(described["row"]["branches"].get_linewidths())
        axes = [id(ax) for ax in figure.axes]
        with self.assertRaises(HierarchicalStyleError) as caught:
            apply_hierarchical_style(figure, {"row": {"width": 2}, "heatmap": {"minimum": 1}})
        self.assertEqual(caught.exception.field, "heatmap.maximum")
        np.testing.assert_allclose(described["row"]["branches"].get_colors(), before)
        np.testing.assert_allclose(described["row"]["branches"].get_linewidths(), widths)
        self.assertEqual([id(ax) for ax in figure.axes], axes)

    def test_non_hierarchical_and_raster_figures_are_refused(self):
        plain = Figure()
        plain.add_subplot().plot([0, 1], [2, 3])
        raster = Figure()
        raster.add_subplot().imshow([[0, 1], [2, 3]])
        for figure in (plain, raster):
            before = len(figure.axes)
            with self.assertRaises(HierarchicalStyleError) as caught:
                apply_hierarchical_style(figure, {"row": {"width": 2}})
            self.assertEqual(caught.exception.field, "figure")
            self.assertEqual(len(figure.axes), before)

    def test_distance_overrides_are_checked_before_changing_artists(self):
        figure = _heat()
        row = describe_hierarchical_artists(figure)["row"]["branches"]
        before = np.array(row.get_linewidths())
        for distance, field in [
            ({"minimum": 1000}, "column.distance.minimum"),
            ({"step": 0.001}, "column.distance.step"),
        ]:
            with self.subTest(distance=distance), self.assertRaises(HierarchicalStyleError) as caught:
                apply_hierarchical_style(figure, {"row": {"width": 5}, "column": {"distance": distance}})
            self.assertEqual(caught.exception.field, field)
            np.testing.assert_allclose(row.get_linewidths(), before)


class HierarchicalStyleGeometryTests(unittest.TestCase):
    def test_empty_override_matches_the_renderer(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        colors = np.array(described["row"]["branches"].get_colors())
        segments = _segments(figure)
        image = np.array(described["heatmap"]["image"].get_array())
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        apply_hierarchical_style(figure, {})
        self.assertEqual(snapshot_hierarchical_style(figure), {})
        np.testing.assert_allclose(described["row"]["branches"].get_colors(), colors)
        for key, before in segments.items():
            np.testing.assert_allclose(described[key]["branches"].get_segments(), before)
        np.testing.assert_allclose(described["heatmap"]["image"].get_array(), image)
        self.assertEqual(len(figure.axes), 4)

    def test_fixture_style_colors_labels_and_scalar_width(self):
        figure = _heat()
        style = {
            "row": {
                "color_mode": "cluster",
                "palette": ["blue", "red"],
                "mixed_color": "#222222",
                "width": 2.5,
                "alpha": 0.6,
                "line_style": "dashed",
                "labels": {"rotation": 30, "size": 9, "color": "black", "interval": 1},
                "distance": {"visible": True, "minimum": 0, "maximum": 20, "step": 5, "reversed": True},
            },
            "column": {
                "color_mode": "single",
                "color": "#663399",
                "width": 0.8,
                "labels": {"rotation": -45, "size": 13, "color": "#103050", "interval": 1},
            },
            "heatmap": {
                "cmap": "plasma", "reverse": True, "minimum": -2, "maximum": 12,
                "colorbar": True, "orientation": "horizontal", "title": "Signal $ literal",
                "cell_aspect": "auto",
            },
            "layout": {"row_tree_ratio": 0.4, "column_tree_ratio": 0.15},
        }
        before = _segments(figure)
        apply_hierarchical_style(figure, style)
        described = describe_hierarchical_artists(figure)
        row = described["row"]["branches"]
        self.assertEqual(_hexes(row), {"#0000ff", "#ff0000", "#222222"})
        np.testing.assert_allclose(row.get_linewidths(), [2.5])
        self.assertAlmostEqual(row.get_alpha(), 0.6)
        self.assertEqual(_hexes(described["column"]["branches"]), {"#663399"})
        heat = described["heatmap"]["axes"]
        self.assertTrue(all(tick.get_rotation() == 30 for tick in heat.get_yticklabels()))
        self.assertTrue(all(tick.get_rotation() % 360 == 315 for tick in heat.get_xticklabels()))
        self.assertTrue(all(tick.get_parse_math() is False for tick in heat.get_xticklabels()))
        np.testing.assert_allclose(described["heatmap"]["image"].get_clim(), [-2, 12])
        import matplotlib
        np.testing.assert_allclose(
            described["heatmap"]["image"].get_cmap()(0.25), matplotlib.colormaps["plasma"](0.75))
        colorbar = described["heatmap"]["colorbar"]
        self.assertEqual(colorbar.orientation, "horizontal")
        self.assertEqual(colorbar.ax.get_xlabel(), "Signal $ literal")
        self.assertFalse(colorbar.ax.xaxis.label.get_parse_math())
        self.assertEqual(heat.get_aspect(), "auto")
        for key, segments in before.items():
            np.testing.assert_allclose(described[key]["branches"].get_segments(), segments)
        self.assertEqual(described["row"]["distance_dimension"], "x")
        self.assertEqual(described["column"]["distance_dimension"], "y")

    def test_second_partial_preview_inherits_the_renderer_baseline(self):
        figure = _heat()
        apply_hierarchical_style(figure, {"row": {"width": 4, "color_mode": "single", "color": "green"}})
        apply_hierarchical_style(figure, {"row": {"color_mode": "single", "color": "red"}})
        row = describe_hierarchical_artists(figure)["row"]["branches"]
        np.testing.assert_allclose(row.get_linewidths(), [1.4])
        self.assertEqual(_hexes(row), {"#ff0000"})
        self.assertAlmostEqual(row.get_alpha(), 1.0)

    def test_same_style_is_idempotent_and_the_snapshot_is_independent(self):
        figure = _heat()
        style = {"row": {"width": 2.5, "alpha": 0.6, "color_mode": "single", "color": "blue"}}
        described = describe_hierarchical_artists(figure)
        colors = np.array(described["row"]["branches"].get_colors())
        axis_ids = [id(ax) for ax in figure.axes]
        counts = [(len(ax.lines), len(ax.collections), len(ax.images)) for ax in figure.axes]
        for _ in range(3):
            apply_hierarchical_style(figure, style)
            _draw(figure)
        self.assertEqual([id(ax) for ax in figure.axes], axis_ids)
        self.assertEqual([(len(ax.lines), len(ax.collections), len(ax.images)) for ax in figure.axes], counts)
        taken = snapshot_hierarchical_style(figure)
        taken["row"]["width"] = 7
        self.assertEqual(snapshot_hierarchical_style(figure)["row"]["width"], 2.5)
        apply_hierarchical_style(figure, {})
        np.testing.assert_allclose(described["row"]["branches"].get_colors(), colors)
        self.assertEqual([id(ax) for ax in figure.axes], axis_ids)
        self.assertEqual([(len(ax.lines), len(ax.collections), len(ax.images)) for ax in figure.axes], counts)

    def test_style_on_a_copied_figure_does_not_touch_the_original(self):
        figure = _heat()
        original = describe_hierarchical_artists(figure)
        before = np.array(original["row"]["branches"].get_linewidths())
        clone = copy.deepcopy(figure)
        cloned = describe_hierarchical_artists(clone)
        self.assertIs(cloned["row"]["axes"].figure, clone)
        self.assertIsNot(cloned["row"]["branches"], original["row"]["branches"])
        self.assertIs(cloned["heatmap"]["image"].axes.figure, clone)
        apply_hierarchical_style(clone, {"row": {"width": 9}})
        np.testing.assert_allclose(cloned["row"]["branches"].get_linewidths(), [9])
        apply_hierarchical_style(clone, {"heatmap": {"orientation": "horizontal", "title": "Copy only"}})
        np.testing.assert_allclose(original["row"]["branches"].get_linewidths(), before)
        self.assertEqual(original["heatmap"]["colorbar"].orientation, "vertical")
        self.assertEqual(original["heatmap"]["colorbar"].ax.get_xlabel(), "")
        copied = describe_hierarchical_artists(clone)
        self.assertEqual(copied["heatmap"]["colorbar"].orientation, "horizontal")
        self.assertEqual(copied["heatmap"]["colorbar"].ax.get_xlabel(), "Copy only")
        self.assertIsNot(copied["heatmap"]["colorbar"], original["heatmap"]["colorbar"])
        self.assertEqual(len(figure.axes), 4)
        self.assertEqual(len(clone.axes), 4)

    def test_applying_a_style_does_not_refit(self):
        figure = _heat()

        def fail(*args, **kwargs):
            raise AssertionError("clustering was invoked")

        with patch("analisi.stats.hierarchical", fail), patch("analisi.hierarchical_workbench.hierarchical", fail):
            apply_hierarchical_style(figure, {"row": {"width": 3}, "heatmap": {"cmap": "magma"}})
        np.testing.assert_allclose(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths(), [3])

    def test_cluster_colors_follow_current_ids_and_a_missing_cut_is_mixed(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        self.assertEqual(described["row"]["cluster_ids"], (1, 1, 2, 2))
        apply_hierarchical_style(figure, {
            "row": {"color_mode": "cluster", "palette": ["#010101", "#020202"], "mixed_color": "#333333"},
        })
        self.assertEqual(_hexes(described["row"]["branches"]), {"#010101", "#020202", "#333333"})
        bare = _heat(**{"Row cut": "No cut", "Column cut": "No cut"})
        bare_desc = describe_hierarchical_artists(bare)
        self.assertIsNone(bare_desc["row"]["cluster_ids"])
        apply_hierarchical_style(bare, {"row": {"color_mode": "cluster", "mixed_color": "#abcdef"}})
        self.assertEqual(_hexes(bare_desc["row"]["branches"]), {"#abcdef"})

    def test_palette_lengths_cycle_without_inventing_groups(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        apply_hierarchical_style(figure, {
            "row": {"color_mode": "cluster", "palette": ["#aa0000"], "mixed_color": "#111111"},
        })
        self.assertEqual(_hexes(described["row"]["branches"]), {"#aa0000", "#111111"})
        palette = [f"#{index:06x}" for index in range(1, 25)]
        apply_hierarchical_style(figure, {
            "row": {"color_mode": "cluster", "palette": palette, "mixed_color": "#111111"},
        })
        self.assertEqual(_hexes(described["row"]["branches"]), {"#000001", "#000002", "#111111"})

    def test_omitted_label_color_keeps_per_leaf_colors_on_a_standalone_tree(self):
        figure = _result(**{"Graph output": "Dendrogram", "Direction": "Rows",
                            "Dendrogram orientation": "Horizontal"}).figure
        described = describe_hierarchical_artists(figure)
        self.assertNotIn("heatmap", described)
        before = [to_hex(tick.get_color(), keep_alpha=False) for tick in described["row"]["axes"].get_yticklabels()]
        self.assertGreater(len(set(before)), 1)
        apply_hierarchical_style(figure, {"row": {"labels": {"size": 12}}})
        after = [to_hex(tick.get_color(), keep_alpha=False) for tick in described["row"]["axes"].get_yticklabels()]
        self.assertEqual(after, before)
        apply_hierarchical_style(figure, {"row": {"labels": {"color": "#103050"}}})
        painted = {to_hex(tick.get_color(), keep_alpha=False) for tick in described["row"]["axes"].get_yticklabels()}
        self.assertEqual(painted, {"#103050"})

    def test_equal_literal_labels_stay_equal_and_unparsed(self):
        frame = _frame()
        frame["Name"] = ["Same $", "Same $", "Same $", "Same $"]
        result = hierarchical_result(frame, _options(**{"Observation labels": "Name", "Direction": "Rows"}))
        figure = result.figure
        apply_hierarchical_style(figure, {"row": {"labels": {"interval": 1, "rotation": 15}}})
        labels = describe_hierarchical_artists(figure)["heatmap"]["axes"].get_yticklabels()
        self.assertEqual([tick.get_text() for tick in labels], ["Same $"] * 4)
        self.assertTrue(all(tick.get_parse_math() is False for tick in labels))

    def test_automatic_interval_uses_the_renderer_rule_and_can_show_every_leaf(self):
        frame = pd.DataFrame({"A": np.linspace(0, 10, 60), "B": np.linspace(1, 4, 60)})
        result = hierarchical_result(frame, _options(**{
            "Direction": "Rows", "Label interval (0 = automatic)": 0, "Clusters": 2}))
        figure = result.figure
        apply_hierarchical_style(figure, {"row": {"labels": {"interval": 0, "first": 1}}})
        shown = [tick.get_text() for tick in describe_hierarchical_artists(figure)["heatmap"]["axes"].get_yticklabels()]
        self.assertEqual(len(shown), 30)
        apply_hierarchical_style(figure, {"row": {"labels": {"interval": 1}}})
        shown = [tick.get_text() for tick in describe_hierarchical_artists(figure)["heatmap"]["axes"].get_yticklabels()]
        self.assertEqual(len(shown), 60)
        apply_hierarchical_style(figure, {"row": {"labels": {"visible": False}}})
        self.assertEqual(describe_hierarchical_artists(figure)["heatmap"]["axes"].get_yticklabels(), [])

    def test_distance_limits_change_only_the_distance_view(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        segments = np.array(described["row"]["branches"].get_segments())
        leaf_ylim = described["row"]["axes"].get_ylim()
        apply_hierarchical_style(figure, {"row": {"distance": {
            "visible": True, "minimum": 0, "maximum": 20, "step": 5, "reversed": True}}})
        axes = described["row"]["axes"]
        self.assertEqual(axes.get_xlim(), (20, 0))
        self.assertEqual(axes.get_ylim(), leaf_ylim)
        self.assertIsInstance(axes.xaxis.get_major_locator(), MultipleLocator)
        self.assertTrue(axes.axison)
        self.assertFalse(axes.yaxis.get_tick_params()["labelleft"])
        self.assertTrue(described["heatmap"]["axes"].get_yticklabels())
        np.testing.assert_allclose(described["row"]["branches"].get_segments(), segments)
        apply_hierarchical_style(figure, {"row": {"distance": {"step": None, "reversed": False}}})
        self.assertIsInstance(axes.xaxis.get_major_locator(), AutoLocator)
        self.assertLess(axes.get_xlim()[0], axes.get_xlim()[1])

    def test_hiding_a_tree_keeps_its_gridspec_space(self):
        figure = _heat()
        gridspec = describe_hierarchical_artists(figure)["row"]["axes"].get_subplotspec().get_gridspec()
        before = list(gridspec.get_width_ratios())
        apply_hierarchical_style(figure, {"row": {"visible": False}})
        row = describe_hierarchical_artists(figure)["row"]
        self.assertFalse(row["branches"].get_visible())
        self.assertEqual(list(gridspec.get_width_ratios()), before)
        apply_hierarchical_style(figure, {"row": {"visible": True}})
        self.assertTrue(row["branches"].get_visible())

    def test_colorbar_orientation_reuses_the_axis_and_horizontal_clears_labels(self):
        figure = _heat()
        described = describe_hierarchical_artists(figure)
        slot = described["heatmap"]["colorbar"].ax
        image = described["heatmap"]["image"]
        apply_hierarchical_style(figure, {"heatmap": {
            "orientation": "horizontal", "title": "Signal $ literal", "colorbar": True,
        }, "column": {"labels": {"rotation": -45, "size": 13, "interval": 1}}})
        for _ in range(2):
            apply_hierarchical_style(figure, {"heatmap": {"orientation": "horizontal", "colorbar": True}})
        self.assertIs(described["heatmap"]["colorbar"].ax, slot)
        self.assertEqual(len(figure.axes), 4)
        renderer = _draw(figure)
        bar = slot.get_window_extent(renderer)
        for tick in described["heatmap"]["axes"].get_xticklabels():
            self.assertFalse(tick.get_window_extent(renderer).overlaps(bar))
        title = slot.xaxis.label.get_window_extent(renderer)
        self.assertFalse(title.overlaps(bar))
        self.assertGreaterEqual(title.y0, 0)
        heat_box = described["heatmap"]["axes"].get_window_extent(renderer)
        self.assertGreater(heat_box.height, bar.height * 4)
        self.assertEqual(len(image.callbacks.callbacks.get("changed", {})), 1)
        apply_hierarchical_style(figure, {"heatmap": {"colorbar": False}})
        self.assertFalse(slot.get_visible())
        self.assertEqual(len(figure.axes), 4)
        apply_hierarchical_style(figure, {"heatmap": {"colorbar": True, "orientation": "vertical"}})
        self.assertTrue(slot.get_visible())
        self.assertEqual(described["heatmap"]["colorbar"].orientation, "vertical")
        self.assertEqual(len(figure.axes), 4)
        self.assertEqual(len(image.callbacks.callbacks.get("changed", {})), 1)

    def test_absent_layout_keys_restore_the_captured_ratios(self):
        figure = _heat()
        gridspec = describe_hierarchical_artists(figure)["row"]["axes"].get_subplotspec().get_gridspec()
        captured = (list(gridspec.get_width_ratios()), list(gridspec.get_height_ratios()))
        apply_hierarchical_style(figure, {"layout": {"row_tree_ratio": 0.4, "column_tree_ratio": 0.15}})
        self.assertAlmostEqual(gridspec.get_width_ratios()[0] / gridspec.get_width_ratios()[1], 0.4)
        self.assertAlmostEqual(gridspec.get_height_ratios()[0] / gridspec.get_height_ratios()[1], 0.15)
        apply_hierarchical_style(figure, {"row": {"width": 2}})
        self.assertEqual(list(gridspec.get_width_ratios()), captured[0])
        self.assertEqual(list(gridspec.get_height_ratios()), captured[1])

    def test_one_direction_and_standalone_orientations(self):
        rows = _heat(**{"Direction": "Rows"})
        described = describe_hierarchical_artists(rows)
        self.assertIn("row", described)
        self.assertNotIn("column", described)
        self.assertIn("heatmap", described)
        apply_hierarchical_style(rows, {"column": {"width": 4}, "row": {"width": 2}})
        np.testing.assert_allclose(described["row"]["branches"].get_linewidths(), [2])
        columns = _heat(**{"Direction": "Columns"})
        column_desc = describe_hierarchical_artists(columns)
        self.assertIn("column", column_desc)
        self.assertNotIn("row", column_desc)
        horizontal = _result(**{"Graph output": "Dendrogram", "Direction": "Rows",
                                "Dendrogram orientation": "Horizontal"}).figure
        vertical = _result(**{"Graph output": "Dendrogram", "Direction": "Columns",
                              "Dendrogram orientation": "Vertical"}).figure
        self.assertEqual(describe_hierarchical_artists(horizontal)["row"]["distance_dimension"], "x")
        self.assertEqual(describe_hierarchical_artists(vertical)["column"]["distance_dimension"], "y")
        self.assertNotIn("heatmap", describe_hierarchical_artists(horizontal))
        apply_hierarchical_style(horizontal, {"row": {"color_mode": "single", "color": "red", "width": 3}})
        self.assertEqual(_hexes(describe_hierarchical_artists(horizontal)["row"]["branches"]), {"#ff0000"})

    def test_letters_follow_the_fit_order(self):
        figure = _result(**{"Graph output": "Dendrogram", "Direction": "Rows",
                            "Label type": "Letters", "Label interval (0 = automatic)": 1}).figure
        apply_hierarchical_style(figure, {"row": {"labels": {"interval": 1}}})
        texts = [tick.get_text() for tick in describe_hierarchical_artists(figure)["row"]["axes"].get_xticklabels()]
        self.assertEqual(texts, ["A", "B", "C", "D"])

    def test_large_matrix_does_not_add_an_artist_per_cell(self):
        rng = np.random.default_rng(5)
        frame = pd.DataFrame(rng.normal(size=(80, 120)), columns=[f"V{i}" for i in range(120)])
        options = _options(**{"Variables": list(frame.columns), "Direction": "Rows and columns", "Clusters": 3,
                              "Column clusters": 3})
        result = hierarchical_result(frame, options)
        figure = result.figure
        before = [(len(ax.lines), len(ax.collections), len(ax.images)) for ax in figure.axes]
        tracemalloc.start()
        started = time.perf_counter()
        apply_hierarchical_style(figure, {
            "row": {"width": 1.2, "color_mode": "single", "color": "#225588"},
            "column": {"width": 1.1},
            "heatmap": {"cmap": "cividis", "minimum": -2, "maximum": 2, "orientation": "horizontal"},
            "layout": {"row_tree_ratio": 0.3, "column_tree_ratio": 0.2},
        })
        _draw(figure)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        after = [(len(ax.lines), len(ax.collections), len(ax.images)) for ax in figure.axes]
        self.assertEqual(after, before)
        self.assertEqual(sum(images for _, _, images in after), 1)
        print(f"hierarchical style 80x120 apply+draw {elapsed:.3f}s tracemalloc peak {peak / 1e6:.2f} MB")

    def test_changed_fit_keeps_the_stored_style(self):
        frame = _frame()
        dataset = Dataset(frame.copy())
        options = _options(**{"Direction": "Rows"})
        dataset.analyses.append(("Hierarchical clustering", options))
        dataset.graph_styles[0] = {"title": "Kept", "hierarchical": {"row": {"width": 3.5, "color": "navy"}}}
        full = hierarchical_result(dataset.frame(), options)
        dataset.excluded.add((0, 0))
        masked = hierarchical_result(dataset.frame(mask_excluded=True), options)
        self.assertNotEqual(full.tables["Merges"]["Distance"].tolist(), masked.tables["Merges"]["Distance"].tolist())
        with self.subTest("project"):
            with self._temporary_project(dataset) as reopened:
                stored = reopened.graph_styles[0]
        self.assertEqual(stored["title"], "Kept")
        self.assertEqual(stored["hierarchical"]["row"]["color"], "#000080")
        self.assertEqual(stored["hierarchical"]["row"]["width"], 3.5)
        self.assertNotIn("xlabel", stored)
        apply_hierarchical_style(masked.figure, stored["hierarchical"])
        np.testing.assert_allclose(
            describe_hierarchical_artists(masked.figure)["row"]["branches"].get_linewidths(), [3.5])

    def _temporary_project(self, dataset):
        import tempfile
        return _Project(dataset, tempfile.TemporaryDirectory())


class _Project:
    def __init__(self, dataset, directory):
        self.dataset = dataset
        self.directory = directory

    def __enter__(self):
        path = Path(self.directory.__enter__()) / "project.alab"
        save_project(path, {"Data": self.dataset})
        tables, _layouts = load_workspace(path)
        return tables["Data"]

    def __exit__(self, *args):
        return self.directory.__exit__(*args)


class HierarchicalStyleIntegrationTests(unittest.TestCase):
    def test_saved_dendrogram_style_is_inactive_on_an_elbow_plot(self):
        style = {"xlabel": "Cluster count", "hierarchical": {"row": {"width": 3.0}}}
        elbow = _result(**{"Graph output": "Elbow plot"})
        before = elbow.tables["Row Elbow data"].copy()
        artists = tuple(elbow.figure.axes[0].lines)

        apply_style(elbow.figure, style)

        self.assertEqual(tuple(elbow.figure.axes[0].lines), artists)
        self.assertEqual(elbow.figure.axes[0].get_xlabel(), "Cluster count")
        pd.testing.assert_frame_equal(elbow.tables["Row Elbow data"], before)
        self.assertEqual(style["hierarchical"], {"row": {"width": 3.0}})

        heatmap = _heat()
        apply_style(heatmap, style)
        row = describe_hierarchical_artists(heatmap)["row"]["branches"]
        np.testing.assert_allclose(row.get_linewidths(), [3.0])

    def test_presentation_keeps_generic_fields_and_legend_options(self):
        style = {
            "title": "Keep literal",
            "tick_size": 11,
            "legend_options": {"title": "Kept legend", "frame": False},
            "hierarchical": {"row": {"width": 4, "color": "green"}},
        }
        validated_style(style)
        self.assertEqual(style["legend_options"], {"title": "Kept legend", "frame": False})
        self.assertEqual(style["hierarchical"]["row"]["color"], "#008000")
        self.assertEqual(style["title"], "Keep literal")
        figure = _heat()
        apply_style(figure, {"tick_size": 15})
        labels = describe_hierarchical_artists(figure)["heatmap"]["axes"].get_yticklabels()
        self.assertTrue(labels)
        self.assertTrue(all(tick.get_fontsize() == 15 for tick in labels))
        apply_style(figure, {"title": "Keep literal", "hierarchical": {"row": {"width": 4, "color_mode": "single",
                                                                               "color": "green"}}})
        self.assertEqual(figure.axes[0].get_title(), "Keep literal")
        np.testing.assert_allclose(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths(), [4])

    def test_resetting_the_section_does_not_drop_the_generic_style(self):
        figure = _heat()
        apply_style(figure, {"title": "Stay", "hierarchical": {"row": {"width": 5}}})
        apply_style(figure, {"title": "Stay"})
        self.assertEqual(figure.axes[0].get_title(), "Stay")
        np.testing.assert_allclose(
            describe_hierarchical_artists(figure)["row"]["branches"].get_linewidths(), [1.4])
        self.assertEqual(snapshot_hierarchical_style(figure), {})

    def test_baseline_is_the_renderer_capture(self):
        figure = _heat()
        baseline = baseline_hierarchical_style(figure)
        self.assertEqual(baseline["row"]["color_mode"], "analysis")
        self.assertEqual(baseline["heatmap"]["cmap"], "viridis")
        self.assertAlmostEqual(baseline["layout"]["row_tree_ratio"], 1.35 / 5)
        json.dumps(baseline)

    def test_merge_distances_match_the_known_fixture(self):
        path = Path(__file__).parent / "data" / "hierarchical_style" / "matrix.csv"
        frame = pd.read_csv(path)
        result = hierarchical_result(frame, _options())
        expected = json.loads((path.parent / "expected.json").read_text())
        np.testing.assert_allclose(result.tables["Row Merges"]["Distance"], expected["row_merge_distances"])
        np.testing.assert_allclose(result.tables["Column Merges"]["Distance"], expected["column_merge_distances"])
        segments = _segments(result.figure)
        apply_hierarchical_style(result.figure, json.loads((path.parent / "style.json").read_text()))
        for key, before in segments.items():
            np.testing.assert_allclose(
                describe_hierarchical_artists(result.figure)[key]["branches"].get_segments(), before)
        # The reference fit is still the one this process computed before styling.
        self.assertEqual(hierarchical(frame, ["A", "B"], 2).tree.shape[0], 3)


if __name__ == "__main__":
    unittest.main()
