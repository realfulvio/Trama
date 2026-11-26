"""Native XY series: shared X, independent Y scales, source order."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from analisi.presentation import apply_style, graph_series, validated_style
from analisi.processing import FieldError
from analisi.workbench import analyse
from analisi.xy_series import (
    SHEET, X_DISTANCE, X_ERROR_ARTISTS, XY_METHOD, assign_colors, check_xy_options, prune_options, xy_series,
)


def x1_frame():
    return pd.DataFrame({
        "X": [0, 1, 2, 3, 4],
        "Temperatura": [18, 19, np.nan, 22, 21],
        "Pressione": [1000, 1020, 1050, np.nan, 1100],
    })


def x1_options():
    return {
        "X": "X",
        "Y columns": ["Temperatura", "Pressione"],
        "Series style": {"Temperatura": "Line and points", "Pressione": "Points"},
        "Series side": {"Temperatura": "Left", "Pressione": "Right"},
        "Y minimum": 15, "Y maximum": 25,
        "Right minimum": 900, "Right maximum": 1200,
        "Right title": "Pressione",
    }


class XYSeriesTests(unittest.TestCase):
    def test_horizontal_errors_keep_points_and_series_identity(self):
        frame = x1_frame()
        frame["Uncertainty"] = [0.2, pd.NA, 0.5, 0, 0.4]
        options = {**x1_options(), X_DISTANCE: "Uncertainty"}
        result = xy_series(frame, options)
        left, right = result.figure.axes
        self.assertEqual([series.key for series in graph_series(left)], ["xy:1:Temperatura", "xy:1:Pressione"])
        self.assertEqual(len(result.tables[SHEET]), 8)
        self.assertEqual(result.tables[SHEET][X_DISTANCE].isna().sum(), 2)
        np.testing.assert_allclose(left.containers[0].lines[2][0].get_segments(),
                                   [[(-0.2, 18), (0.2, 18)], [(3.6, 21), (4.4, 21)]])
        np.testing.assert_allclose(right.containers[0].lines[2][0].get_segments()[1], [(1.5, 1050), (2.5, 1050)])
        components = getattr(left.lines[0], X_ERROR_ARTISTS)
        apply_style(result.figure, {"series": {"xy:1:Temperatura": {"color": "#118833"}}})
        np.testing.assert_allclose(components[-1].get_colors()[0], [17 / 255, 136 / 255, 51 / 255, 1])
        apply_style(result.figure, {})
        np.testing.assert_allclose(components[-1].get_colors()[0], [31 / 255, 119 / 255, 180 / 255, 1])

    def test_rejects_bad_horizontal_error_values_and_columns(self):
        frame = x1_frame()
        options = {**x1_options(), X_DISTANCE: "Uncertainty"}
        for invalid in (-0.1, "bad", np.inf):
            with self.subTest(invalid=invalid):
                frame["Uncertainty"] = [0.1, invalid, np.nan, 0, 1.]
                with self.assertRaisesRegex(FieldError, "row 2"):
                    xy_series(frame, options)
        with self.assertRaisesRegex(FieldError, "distinct"):
            xy_series(frame, {**options, X_DISTANCE: "Temperatura"})
        frame["Uncertainty"] = [0.1, 0.2, np.nan, 0, 1.]
        frame["X"] = frame["X"].astype(float)
        frame.loc[0, ["X", "Uncertainty"]] = 1e308
        with self.assertRaisesRegex(FieldError, "row 1"):
            xy_series(frame, options)

    def test_x1_dual_axis_breaks_the_temperature_line(self):
        frame = x1_frame()
        result = xy_series(frame, x1_options())
        self.assertEqual(len(result.figure.axes), 2)
        left, right = result.figure.axes
        np.testing.assert_allclose(left.get_ylim(), (15, 25))
        np.testing.assert_allclose(right.get_ylim(), (900, 1200))
        self.assertEqual(left.get_xlabel(), "X")
        self.assertEqual(right.get_ylabel(), "Pressione")
        temperature = left.lines[0]
        pressure = right.lines[0]
        self.assertEqual(temperature.get_gid(), "xy:1:Temperatura")
        self.assertEqual(pressure.get_gid(), "xy:1:Pressione")
        self.assertEqual(temperature.get_linestyle(), "-")
        self.assertEqual(temperature.get_marker(), "o")
        self.assertEqual(pressure.get_linestyle(), "None")
        np.testing.assert_allclose(temperature.get_xdata()[np.isfinite(temperature.get_ydata())], [0, 1, 3, 4])
        self.assertTrue(np.isnan(temperature.get_ydata()[2]))
        np.testing.assert_allclose(pressure.get_xdata()[np.isfinite(pressure.get_ydata())], [0, 1, 2, 4])
        self.assertTrue(np.isnan(pressure.get_ydata()[3]))
        labels = [text.get_text() for text in left.get_legend().get_texts()]
        self.assertEqual(labels, ["Temperatura", "Pressione"])
        self.assertIsNone(right.get_legend())
        from analisi.presentation import apply_style
        apply_style(result.figure, {"series": {"xy:1:Temperatura": {"color": "#112233"}}})
        self.assertEqual(len(result.figure.axes), 2)
        np.testing.assert_allclose(result.figure.axes[1].get_ylim(), (900, 1200))
        self.assertEqual(result.figure.axes[1].get_ylabel(), "Pressione")
        self.assertEqual([text.get_text() for text in result.figure.axes[0].get_legend().get_texts()],
                         ["Temperatura", "Pressione"])
        self.assertEqual(result.figure.axes[0].lines[0].get_color(), "#112233")
        left.set_xlim(0.25, 3.5)
        np.testing.assert_allclose(right.get_xlim(), left.get_xlim())
        sheet = result.tables[SHEET]
        self.assertEqual(list(sheet.columns), ["Source row", "X", "Y column", "Y"])
        self.assertEqual(sheet["Y column"].tolist(), ["Temperatura"] * 4 + ["Pressione"] * 4)
        np.testing.assert_allclose(sheet.loc[sheet["Y column"] == "Temperatura", "X"], [0, 1, 3, 4])
        np.testing.assert_allclose(sheet.loc[sheet["Y column"] == "Pressione", "X"], [0, 1, 2, 4])
        self.assertFalse(right.xaxis.get_gridlines()[0].get_visible() if right.xaxis.get_gridlines() else False)

    def test_both_series_on_the_left_have_a_single_axes(self):
        options = x1_options()
        options["Series side"] = {"Temperatura": "Left", "Pressione": "Left"}
        options.pop("Right minimum")
        options.pop("Right maximum")
        result = xy_series(x1_frame(), options)
        self.assertEqual(len(result.figure.axes), 1)
        self.assertEqual([text.get_text() for text in result.figure.axes[0].get_legend().get_texts()],
                         ["Temperatura", "Pressione"])

    def test_x2_unicode_duplicate_exclusion_and_log_limits(self):
        frame = pd.DataFrame({
            "X": [1, 1, 2, 3],
            "Temperatura": [10, 12, 11, 13],
            "Pressione": [100, 110, 120, 130],
            "Δ Pressione": [1.5, 1.6, np.nan, 2.0],
        })
        stored = assign_colors(["Temperatura", "Pressione"], {})
        options = {
            "X": "X",
            "Y columns": ["Temperatura", "Pressione", "Δ Pressione"],
            "Series style": {"Temperatura": "Line", "Pressione": "Points", "Δ Pressione": "Line and points"},
            "Series side": {"Temperatura": "Left", "Pressione": "Right", "Δ Pressione": "Right"},
            "Series color": stored,
            "Right scale": "Log",
            "Right minimum": 1,
            "Right maximum": 1000,
        }
        colors = assign_colors(options["Y columns"], options["Series color"])
        self.assertEqual(colors["Temperatura"], stored["Temperatura"])
        self.assertEqual(colors["Pressione"], stored["Pressione"])
        self.assertNotEqual(colors["Δ Pressione"], colors["Temperatura"])
        before = deepcopy(options)
        result = xy_series(frame, options)
        self.assertEqual(options, before)
        sheet = result.tables[SHEET]
        self.assertEqual(sheet["Y column"].tolist()[:4], ["Temperatura"] * 4)
        temperatura = sheet.loc[sheet["Y column"] == "Temperatura"]
        np.testing.assert_allclose(temperatura["X"].iloc[:2], [1, 1])
        np.testing.assert_allclose(temperatura["Y"].iloc[:2], [10, 12])
        self.assertEqual(temperatura["X"].tolist(), [1, 1, 2, 3])
        self.assertNotIn(2, sheet.loc[sheet["Y column"] == "Δ Pressione", "X"].tolist())
        delta = result.figure.axes[1].lines[1]
        self.assertEqual(delta.get_gid(), "xy:1:Δ Pressione")
        self.assertTrue(np.isnan(delta.get_ydata()[2]))
        self.assertEqual(result.figure.axes[1].get_yscale(), "log")
        np.testing.assert_allclose(result.figure.axes[1].get_ylim(), (1, 1000))
        rejected = deepcopy(options)
        rejected["Right minimum"] = 0
        snapshot = deepcopy(rejected)
        with self.assertRaises(FieldError) as zero:
            check_xy_options(frame, rejected)
        self.assertEqual(zero.exception.field, "Right minimum")
        self.assertIn("positive", str(zero.exception))
        self.assertEqual(rejected, snapshot)
        blocked = deepcopy(options)
        blocked["Right scale"] = "Log"
        negative = frame.assign(Pressione=[-5, -4, -3, -2], **{"Δ Pressione": [-1, -1, -1, -1]})
        snapshot = deepcopy(blocked)
        with self.assertRaises(FieldError) as empty:
            check_xy_options(negative, blocked)
        self.assertEqual(empty.exception.field, "Right scale")
        self.assertEqual(blocked, snapshot)

    def test_identity_limits_and_old_styles_stay_compatible(self):
        frame = x1_frame()
        options = x1_options()
        options["Y columns"] = ["Pressione", "Temperatura"]
        options["Series side"] = {"Pressione": "Left", "Temperatura": "Right"}
        result = xy_series(frame, options)
        labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(labels, ["Pressione", "Temperatura"])
        self.assertEqual([line.get_gid() for line in (*result.figure.axes[0].lines, *result.figure.axes[1].lines)],
                         ["xy:1:Pressione", "xy:1:Temperatura"])
        pruned = prune_options({
            "Y columns": ["Pressione"],
            "Series color": {"Pressione": "#112233", "Temperatura": "#445566"},
            "Series style": {"Pressione": "Line", "Gone": "Points"},
            "Right title": "Keep",
        })
        self.assertEqual(pruned["Series color"], {"Pressione": "#112233"})
        self.assertEqual(pruned["Series style"], {"Pressione": "Line"})
        self.assertEqual(pruned["Right title"], "Keep")
        self.assertEqual(validated_style({"title": "Classic", "series": {"line:1:A": {"color": "#2866ae"}}})["title"],
                         "Classic")
        column = analyse("Column graph", frame.rename(columns={"Temperatura": "x", "Pressione": "z"}).assign(
            x=[1, 2, 3, 4, 5], z=[2, 3, 4, 5, 6]), {"Variables": ["x", "z"], "Graph style": "Individual points"})
        self.assertEqual(len(column.figure.axes), 1)
        from analisi.presentation import apply_style
        apply_style(column.figure, {"title": "Still one axes"})
        self.assertEqual(len(column.figure.axes), 1)
        self.assertEqual(column.figure.axes[0].get_title(), "Still one axes")

    def test_distinct_columns_and_a_flat_empty_series(self):
        frame = x1_frame()
        with self.assertRaises(FieldError) as same:
            check_xy_options(frame, {"X": "X", "Y columns": ["X"]})
        self.assertEqual(same.exception.field, "Y columns")
        self.assertIn("distinct", str(same.exception))
        empty = pd.DataFrame({"X": [1, 2], "Y": [np.nan, np.nan]})
        with self.assertRaisesRegex(ValueError, "at least one plotted point"):
            xy_series(empty, {"X": "X", "Y columns": ["Y"]})
        kept = x1_options()
        kept["Y columns"] = ["Temperatura", "Pressione", "Solo vuota"]
        frame = frame.assign(**{"Solo vuota": [np.nan] * 5})
        kept["Series side"]["Solo vuota"] = "Right"
        kept["Series style"]["Solo vuota"] = "Line"
        result = xy_series(frame, kept)
        self.assertEqual(result.figure.axes[1].lines[-1].get_gid(), "xy:1:Solo vuota")
        self.assertNotIn("Solo vuota", result.tables[SHEET]["Y column"].tolist())
        self.assertEqual([text.get_text() for text in result.figure.axes[0].get_legend().get_texts()],
                         ["Temperatura", "Pressione"])

    def test_catalog_default_is_one_axes(self):
        data = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6], "z": [7, 8, 9]})
        result = analyse(XY_METHOD, data, {"X": "x", "Y columns": ["y", "z"]})
        self.assertEqual(len(result.figure.axes), 1)
        self.assertFalse(result.tables[SHEET].empty)
        self.assertEqual(result.tables[SHEET]["Y column"].tolist(), ["y", "y", "y", "z", "z", "z"])

    def test_oracle_fixture_styles_reset_right_axis_and_immutable_values(self):
        from matplotlib.colors import to_rgba
        from analisi.presentation import apply_style, graph_series

        frame = pd.DataFrame({
            "X": [0, 1, 1, 2, 3, 4],
            "A": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0],
            "B": [10.0, 12.0, 13.0, np.nan, 17.0, 20.0],
        })
        options = {
            "X": "X",
            "Y columns": ["A", "B"],
            "Series style": {"A": "Line and points", "B": "Line and points"},
            "Series side": {"B": "Right"},
            "Right title": "Pressure",
        }
        style = {
            "series": {
                "xy:1:A": {
                    "color": "#cc0000",
                    "line_style": "dashed",
                    "width": 2.5,
                    "marker": "s",
                    "marker_size": 9,
                    "marker_color": "#00aa00",
                },
                "xy:1:B": {
                    "color": "#0066cc",
                    "line_style": "dotted",
                    "width": 1.5,
                    "marker": "^",
                    "marker_size": 7,
                    "label": "Pressure",
                },
            }
        }
        result = analyse(XY_METHOD, frame, options)
        before = result.tables[SHEET].copy(deep=True)
        axes = result.figure.axes[0]
        original = {
            s.key: (
                s.artist.get_color(),
                s.artist.get_linestyle(),
                s.artist.get_linewidth(),
                s.artist.get_marker(),
                s.artist.get_markersize(),
                to_rgba(s.artist.get_markerfacecolor()),
                to_rgba(s.artist.get_markeredgecolor()),
                s.artist.get_label(),
            )
            for s in graph_series(axes)
            if s.kind == "xy"
        }
        apply_style(result.figure, style)
        series = {s.key: s.artist for s in graph_series(axes) if s.kind == "xy"}
        artist_a = series["xy:1:A"]
        artist_b = series["xy:1:B"]
        self.assertIs(artist_a.axes, result.figure.axes[0])
        self.assertIs(artist_b.axes, result.figure.axes[1])
        self.assertEqual(artist_a.get_linestyle(), "--")
        self.assertEqual(artist_a.get_marker(), "s")
        np.testing.assert_allclose([artist_a.get_linewidth(), artist_a.get_markersize()], [2.5, 9.0])
        np.testing.assert_allclose(to_rgba(artist_a.get_color()), to_rgba("#cc0000"))
        np.testing.assert_allclose(to_rgba(artist_a.get_markerfacecolor()), to_rgba("#00aa00"))
        np.testing.assert_allclose(to_rgba(artist_a.get_markeredgecolor()), to_rgba("#00aa00"))
        self.assertEqual(artist_b.get_linestyle(), ":")
        self.assertEqual(artist_b.get_marker(), "^")
        np.testing.assert_allclose([artist_b.get_linewidth(), artist_b.get_markersize()], [1.5, 7.0])
        np.testing.assert_allclose(to_rgba(artist_b.get_color()), to_rgba("#0066cc"))
        np.testing.assert_allclose(to_rgba(artist_b.get_markerfacecolor()), to_rgba("#0066cc"))
        self.assertEqual(artist_b.get_label(), "Pressure")
        legend = axes.get_legend()
        self.assertEqual([t.get_text() for t in legend.get_texts()], ["A", "Pressure"])
        legend_lines = legend.get_lines()
        self.assertEqual(legend_lines[0].get_linestyle(), "--")
        self.assertEqual(legend_lines[0].get_marker(), "s")
        np.testing.assert_allclose(to_rgba(legend_lines[0].get_markerfacecolor()), to_rgba("#00aa00"))
        self.assertEqual(legend_lines[1].get_linestyle(), ":")
        self.assertEqual(legend_lines[1].get_marker(), "^")

        apply_style(result.figure, {})
        for key, artist in series.items():
            restored = (
                artist.get_color(),
                artist.get_linestyle(),
                artist.get_linewidth(),
                artist.get_marker(),
                artist.get_markersize(),
                to_rgba(artist.get_markerfacecolor()),
                to_rgba(artist.get_markeredgecolor()),
                artist.get_label(),
            )
            self.assertEqual(restored, original[key])
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()], ["A", "B"])
        pd.testing.assert_frame_equal(before, result.tables[SHEET])

    def test_structure_precedence_saved_inactive_properties_and_repeated_reset(self):
        from matplotlib.colors import to_rgba
        from analisi.presentation import active_series_fields, apply_style, graph_series

        frame = pd.DataFrame({"X": [0, 1, 2], "A": [1.0, 3.0, 2.0], "B": [4.0, 5.0, 6.0]})
        saved_style = {
            "series": {
                "xy:1:A": {
                    "color": "#cc0000",
                    "line_style": "dashed",
                    "width": 3.0,
                    "marker": "s",
                    "marker_size": 10.0,
                    "marker_color": "#00aa00",
                }
            }
        }
        # Points hides line even when line_style=dashed and width=3.0 are stored.
        points_res = xy_series(frame, {"X": "X", "Y columns": ["A", "B"], "Series style": {"A": "Points"}})
        apply_style(points_res.figure, saved_style)
        series_a = next(s for s in graph_series(points_res.figure.axes[0]) if s.key == "xy:1:A")
        self.assertEqual(active_series_fields(points_res.figure.axes[0], series_a),
                         {"color", "label", "marker", "marker_size", "marker_color"})
        self.assertEqual(series_a.artist.get_linestyle(), "None")
        self.assertEqual(series_a.artist.get_marker(), "s")
        self.assertEqual(series_a.artist.get_markersize(), 10.0)
        np.testing.assert_allclose(to_rgba(series_a.artist.get_markerfacecolor()), to_rgba("#00aa00"))
        self.assertEqual(points_res.figure.axes[0]._tramastat_style["series"]["xy:1:A"]["line_style"], "dashed")

        # Line hides marker even when marker=s and marker_color are stored.
        line_res = xy_series(frame, {"X": "X", "Y columns": ["A", "B"], "Series style": {"A": "Line"}})
        apply_style(line_res.figure, saved_style)
        series_a_line = next(s for s in graph_series(line_res.figure.axes[0]) if s.key == "xy:1:A")
        self.assertEqual(active_series_fields(line_res.figure.axes[0], series_a_line),
                         {"color", "label", "line_style", "width"})
        self.assertEqual(series_a_line.artist.get_linestyle(), "--")
        self.assertEqual(series_a_line.artist.get_linewidth(), 3.0)
        self.assertEqual(series_a_line.artist.get_marker(), "None")
        self.assertEqual(line_res.figure.axes[0]._tramastat_style["series"]["xy:1:A"]["marker"], "s")

        # Switching structure to Line and points and side to Right brings back both line and marker properties.
        both_res = xy_series(frame, {
            "X": "X",
            "Y columns": ["A", "B"],
            "Series style": {"A": "Line and points", "B": "Line and points"},
            "Series side": {"A": "Right"},
        })
        apply_style(both_res.figure, saved_style)
        series_a_both = next(s for s in graph_series(both_res.figure.axes[0]) if s.key == "xy:1:A")
        self.assertEqual(active_series_fields(both_res.figure.axes[0], series_a_both),
                         {"color", "label", "line_style", "width", "marker", "marker_size", "marker_color"})
        self.assertIs(series_a_both.artist.axes, both_res.figure.axes[1])
        self.assertEqual(series_a_both.artist.get_linestyle(), "--")
        self.assertEqual(series_a_both.artist.get_linewidth(), 3.0)
        self.assertEqual(series_a_both.artist.get_marker(), "s")
        self.assertEqual(series_a_both.artist.get_markersize(), 10.0)

        # No symbol (marker='none') and line_style='none' hide elements inside Line and points.
        apply_style(both_res.figure, {"series": {"xy:1:A": {"line_style": "none", "marker": "none"}}})
        self.assertEqual(series_a_both.artist.get_linestyle(), "None")
        self.assertEqual(series_a_both.artist.get_marker(), "none")

        # Repeated Apply (A then B) followed by Reset restores every default.
        apply_style(both_res.figure, {"series": {"xy:1:A": {"line_style": "dashed", "marker": "D", "width": 4.0}}})
        apply_style(both_res.figure, {
            "series": {
                "xy:1:A": {"line_style": "dashed", "marker": "D", "width": 4.0},
                "xy:1:B": {"line_style": "dash-dot", "marker": "v", "marker_size": 11.0, "color": "#228833"},
            }
        })
        apply_style(both_res.figure, {})
        for s in graph_series(both_res.figure.axes[0]):
            self.assertEqual(s.artist.get_linestyle(), "-")
            self.assertEqual(s.artist.get_marker(), "o")
            self.assertEqual(s.artist.get_linewidth(), 1.5)
            self.assertEqual(s.artist.get_markersize(), 6.0)

    def test_colons_in_column_names_reordered_y_empty_series_and_literal_dollar_titles(self):
        from analisi.presentation import apply_style, graph_series

        frame = pd.DataFrame({
            "X": [1.0, 2.0, 3.0],
            "Ratio:1:A": [2.0, 4.0, 6.0],
            "Dose:2:B": [10.0, 20.0, 30.0],
            "Empty:3": [np.nan, np.nan, np.nan],
        })
        # First Y column on Right axis, second on Left axis: legend and graph_series follow Y columns order.
        options = {
            "X": "X",
            "Y columns": ["Dose:2:B", "Ratio:1:A", "Empty:3"],
            "Series style": {"Dose:2:B": "Line and points", "Ratio:1:A": "Line and points", "Empty:3": "Line"},
            "Series side": {"Dose:2:B": "Right", "Ratio:1:A": "Left", "Empty:3": "Right"},
            "Right title": "Cost ($)",
        }
        result = xy_series(frame, options)
        axes = result.figure.axes[0]
        self.assertEqual([s.key for s in graph_series(axes)],
                         ["xy:1:Dose:2:B", "xy:1:Ratio:1:A", "xy:1:Empty:3"])
        style = {
            "title": "Budget $10 & $20 ($)",
            "xlabel": "Time ($t$)",
            "ylabel": "Rate ($)",
            "series": {
                "xy:1:Dose:2:B": {"color": "#aa0000", "marker": "*", "marker_size": 8.0, "label": "Dose $B"},
                "xy:1:Ratio:1:A": {"color": "#0055aa", "line_style": "dotted"},
            },
        }
        apply_style(result.figure, style)
        self.assertEqual(axes.get_title(), "Budget $10 & $20 ($)")
        self.assertEqual(axes.get_ylabel(), "Rate ($)")
        self.assertEqual(result.figure.axes[1].get_ylabel(), "Cost ($)")
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()], ["Dose $B", "Ratio:1:A"])
        self.assertEqual(result.tables[SHEET]["Y column"].tolist(), ["Dose:2:B"] * 3 + ["Ratio:1:A"] * 3)
