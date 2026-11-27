"""XY series with Step and Bars beside points and lines: geometry, validation, styles and vector export."""
from io import BytesIO
import math
import unittest
from xml.etree import ElementTree as ET

from matplotlib.colors import to_rgba
from matplotlib.container import BarContainer
import numpy as np
import pandas as pd

from analisi.field_error import FieldError
from analisi.graph_legend import collect_legend_entries
from analisi.grouped_bar_style import BAR_APPEARANCE
from analisi.presentation import (active_series_fields, apply_style, graph_series, validate_graph_style,
                                  xy_legend_handles)
from analisi.xy_series import BAR_WIDTH, SHEET, check_xy_options, parse_bar_width, prune_options, xy_series


def frame():
    # The package fixture (mixed-series.csv) with an extra row label so that source IDs are not positions.
    return pd.DataFrame({
        "Time": [0, 1, 2, 4, 5, 8],
        "Bars left": [2, np.nan, -3, 4, 0, 9],
        "Bars right": [1, 3, 2, np.nan, -2, 7],
        "Step dose": [0, 3, np.nan, 4, 6, 5],
        "Trend": [3, 4, 5, 6, 7, 8],
    })


def options(**update):
    return {
        "X": "Time", "Y columns": ["Bars left", "Bars right", "Step dose", "Trend"],
        "Series style": {"Bars left": "Bars", "Bars right": "Bars", "Step dose": "Step", "Trend": "Line"},
        "Series side": {"Bars right": "Right"},
        **update,
    }


def bars_of(axes):
    containers = [artist for artist in axes.containers if isinstance(artist, BarContainer)]
    return containers


def svg_ids(figure):
    output = BytesIO()
    figure.savefig(output, format="svg")
    return [element.get("id", "") for element in ET.fromstring(output.getvalue()).iter()]


class MixedGeometryTests(unittest.TestCase):
    def assertClose(self, actual, expected):
        np.testing.assert_allclose(np.asarray(actual, dtype=float), np.asarray(expected, dtype=float),
                                   rtol=1e-12, atol=1e-12)

    def test_two_bar_series_on_both_axes_share_virtual_clusters(self):
        result = xy_series(frame(), options())
        left, right = result.figure.axes
        (left_bars,), (right_bars,) = bars_of(left), bars_of(right)
        self.assertClose([p.get_width() for p in left_bars.patches], [0.4] * 5)
        self.assertClose([p.get_x() + p.get_width() / 2 for p in left_bars.patches], [-0.2, 1.8, 3.8, 4.8, 7.8])
        self.assertClose([p.get_x() + p.get_width() / 2 for p in right_bars.patches], [0.2, 1.2, 2.2, 5.2, 8.2])
        self.assertClose([p.get_y() for p in left_bars.patches], [0] * 5)
        self.assertClose([p.get_height() for p in left_bars.patches], [2, -3, 4, 0, 9])
        self.assertClose([p.get_height() for p in right_bars.patches], [1, 3, 2, -2, 7])
        sheet = result.tables[SHEET]
        self.assertEqual(list(sheet.columns), ["Source row", "X", "Y column", "Y"])
        self.assertEqual(sheet["Y column"].tolist(),
                         ["Bars left"] * 5 + ["Bars right"] * 5 + ["Step dose"] * 5 + ["Trend"] * 6)
        # The sheet keeps the original X: the shifted centers are geometry only.
        self.assertClose(sheet.loc[sheet["Y column"] == "Bars right", "X"], [0, 1, 2, 5, 8])
        self.assertEqual(sheet.loc[sheet["Y column"] == "Bars left", "Source row"].tolist(), [0, 2, 3, 4, 5])
        self.assertEqual([t.get_text() for t in left.get_legend().get_texts()],
                         ["Bars left", "Bars right", "Step dose", "Trend"])
        self.assertIsNone(right.get_legend())

    def test_explicit_width_accepts_a_decimal_comma_and_single_position_uses_point_eight(self):
        result = xy_series(frame(), options(**{BAR_WIDTH: "1,2"}))
        patches = bars_of(result.figure.axes[0])[0].patches
        self.assertClose([p.get_width() for p in patches], [0.6] * 5)
        self.assertClose([p.get_x() + p.get_width() / 2 for p in patches], [-0.3, 1.7, 3.7, 4.7, 7.7])
        single = pd.DataFrame({"X": [3.0, 3.0], "A": [5.0, np.nan], "B": [np.nan, 2.0]})
        result = xy_series(single, {"X": "X", "Y columns": ["A"], "Series style": {"A": "Bars"}})
        (patch,) = bars_of(result.figure.axes[0])[0].patches
        self.assertAlmostEqual(patch.get_width(), 0.8)
        self.assertAlmostEqual(patch.get_x() + patch.get_width() / 2, 3.0)

    def test_three_slots_keep_their_place_when_a_value_is_missing(self):
        data = pd.DataFrame({"X": [0, 2], "A": [1, 1], "B": [np.nan, 2], "C": [3, 3]})
        result = xy_series(data, {"X": "X", "Y columns": ["A", "B", "C"],
                                  "Series style": dict.fromkeys("ABC", "Bars"), "Series side": {"B": "Right"}})
        left, right = result.figure.axes
        centers = {container.get_label(): [p.get_x() + p.get_width() / 2 for p in container.patches]
                   for axes in (left, right) for container in bars_of(axes)}
        width = 0.8 * 2
        self.assertClose(centers["A"], [0 - width / 3, 2 - width / 3])
        self.assertClose(centers["B"], [2.0])
        self.assertClose(centers["C"], [0 + width / 3, 2 + width / 3])

    def test_step_holds_values_and_breaks_on_missing_positions(self):
        figure = xy_series(frame(), options()).figure
        step = next(a for a in figure.axes[0].lines if a.get_gid() == "xy:1:Step dose")
        self.assertEqual(step.get_drawstyle(), "steps-post")
        self.assertEqual(step.get_marker(), "None")
        self.assertClose(step.get_xdata(), [0, 1, 2, 4, 5, 8])
        y = np.asarray(step.get_ydata(), dtype=float)
        self.assertTrue(math.isnan(y[2]))
        self.assertClose(np.delete(y, 2), [0, 3, 4, 6, 5])

    def test_legacy_styles_keep_their_artists(self):
        result = xy_series(frame(), {"X": "Time", "Y columns": ["Trend", "Step dose", "Bars left"],
                                     "Series style": {"Trend": "Line", "Step dose": "Line and points"}})
        trend, dose, left = result.figure.axes[0].lines
        self.assertEqual([a.get_gid() for a in (trend, dose, left)],
                         ["xy:1:Trend", "xy:1:Step dose", "xy:1:Bars left"])
        self.assertEqual([a.get_drawstyle() for a in (trend, dose, left)], ["default"] * 3)
        self.assertEqual((trend.get_marker(), trend.get_linestyle()), ("None", "-"))
        self.assertEqual((dose.get_marker(), dose.get_linestyle()), ("o", "-"))
        self.assertEqual((left.get_marker(), left.get_linestyle()), ("o", "None"))
        self.assertEqual(bars_of(result.figure.axes[0]), [])
        self.assertEqual(len(result.figure.axes), 1)
        self.assertTrue(result.figure.axes[0].patch.get_visible())


class MixedValidationTests(unittest.TestCase):
    def field(self, data, update, left_scale="linear"):
        with self.assertRaises(FieldError) as raised:
            xy_series(data, options(**update), left_scale=left_scale)
        return raised.exception

    def test_repeated_x_is_rejected_only_among_valid_points_of_a_bar_series(self):
        data = pd.concat([frame(), frame().iloc[[0]]], ignore_index=True)
        error = self.field(data, {})
        self.assertEqual((error.field, error.column), ("Y columns", "Bars left"))
        self.assertIn("repeats X = 0", str(error))
        # A missing Y at the repeated X draws no rectangle, so it is not a duplicate.
        data.loc[6, ["Bars left", "Bars right"]] = np.nan
        xy_series(data, options())
        # Lines and points keep duplicate X values in sheet order, as before.
        xy_series(pd.concat([frame(), frame().iloc[[0]]]), {"X": "Time", "Y columns": ["Trend"]})

    def test_invalid_explicit_widths_name_the_width_field(self):
        for value in (0, -1, "abc", "1,2,3", math.inf, math.nan, True, "1e400", [1]):
            with self.subTest(value=value):
                self.assertEqual(self.field(frame(), {BAR_WIDTH: value}).field, BAR_WIDTH)
        for value in (None, "", "  "):
            self.assertIsNone(parse_bar_width(value))
        self.assertEqual(parse_bar_width("0.25"), 0.25)
        self.assertEqual(parse_bar_width(2), 2.0)

    def test_collapsed_or_overflowing_rectangles_name_the_width_field(self):
        far = pd.DataFrame({"X": [1e17, 1e17 + 16], "A": [1.0, 2.0]})
        bars = {"X": "X", "Y columns": ["A"], "Series style": {"A": "Bars"}}
        with self.assertRaises(FieldError) as raised:
            xy_series(far, {**bars, BAR_WIDTH: 1e-3})
        self.assertEqual(raised.exception.field, BAR_WIDTH)
        with self.assertRaises(FieldError) as raised:
            xy_series(pd.DataFrame({"X": [1.7e308], "A": [1.0]}), {**bars, BAR_WIDTH: 1e308})
        self.assertEqual(raised.exception.field, BAR_WIDTH)
        # Automatic widths collapse too when valid X values are adjacent floating-point numbers.
        tight = pd.DataFrame({"X": [1.0, np.nextafter(1.0, 2.0)], "A": [1.0, 2.0]})
        with self.assertRaises(FieldError) as raised:
            xy_series(tight, bars)
        self.assertEqual(raised.exception.field, BAR_WIDTH)

    def test_bars_need_a_linear_value_axis_but_the_other_side_may_be_logarithmic(self):
        self.assertEqual(self.field(frame(), {"Right scale": "Log"}).field, "Right scale")
        self.assertEqual(self.field(frame(), {}, left_scale="log").field, "Y scale")
        # Bars on the left, a positive line on a logarithmic right axis.
        data = frame()
        mixed = options(**{"Series side": {"Trend": "Right"}, "Right scale": "Log"})
        mixed["Series style"]["Bars right"] = "Points"
        result = xy_series(data, mixed)
        self.assertEqual(result.figure.axes[1].get_yscale(), "log")
        self.assertEqual(len(bars_of(result.figure.axes[0])), 1)

    def test_change_parameters_check_sees_the_saved_draw_styles(self):
        data = pd.concat([frame(), frame().iloc[[0]]], ignore_index=True)
        saved = options()
        edited = {"X": "Time", "Y columns": ["Bars left", "Trend"]}
        merged = prune_options({**saved, **edited})
        with self.assertRaises(FieldError) as raised:
            check_xy_options(data, merged)
        self.assertEqual(raised.exception.field, "Y columns")
        check_xy_options(data, prune_options({**saved, "Y columns": ["Trend", "Step dose"]}))


class MixedStyleTests(unittest.TestCase):
    def test_series_keep_their_key_when_draw_style_or_axis_changes(self):
        for style in ("Points", "Line", "Line and points", "Step", "Bars"):
            for side in ("Left", "Right"):
                with self.subTest(style=style, side=side):
                    result = xy_series(frame(), {"X": "Time", "Y columns": ["Trend", "Bars left"],
                                                 "Series style": {"Bars left": style},
                                                 "Series side": {"Bars left": side}})
                    series = graph_series(result.figure.axes[0])
                    self.assertEqual([item.key for item in series], ["xy:1:Trend", "xy:1:Bars left"])
                    self.assertEqual({item.kind for item in series}, {"xy"})

    def test_bars_take_color_label_and_visibility_and_keep_saved_line_settings(self):
        result = xy_series(frame(), options())
        figure, axes = result.figure, result.figure.axes[0]
        bars = next(item for item in graph_series(axes) if item.key == "xy:1:Bars left")
        self.assertEqual(active_series_fields(axes, bars), {"color", "label", "visible", BAR_APPEARANCE})
        geometry = [(p.get_x(), p.get_width()) for p in bars.artist.patches]
        style = {"series": {"xy:1:Bars left": {"color": "#624b91", "label": "Observed $x$", "marker": "s",
                                               "line_style": "dashed", "width": 3.0},
                            "xy:1:Bars right": {"visible": False}}}
        validate_graph_style(axes, style)
        apply_style(figure, style)
        self.assertTrue(all(p.get_facecolor() == to_rgba("#624b91") for p in bars.artist.patches))
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()],
                         ["Observed $x$", "Step dose", "Trend"])
        right = bars_of(figure.axes[1])[0]
        self.assertFalse(any(p.get_visible() for p in right.patches))
        # A hidden series keeps its slot: the other series does not move.
        self.assertEqual([(p.get_x(), p.get_width()) for p in bars.artist.patches], geometry)
        ids = svg_ids(figure)
        self.assertEqual(len([i for i in ids if i.startswith("xybar:Bars left:")]), 5)
        self.assertEqual([i for i in ids if i.startswith("xybar:Bars right:")], [])
        # Back to points: the saved symbol returns, visibility is inactive and stays saved.
        points = xy_series(frame(), options(**{"Series style": {"Bars left": "Points"}}))
        apply_style(points.figure, style)
        line = points.figure.axes[0].lines[0]
        self.assertEqual((line.get_gid(), line.get_marker(), line.get_linestyle()), ("xy:1:Bars left", "s", "None"))
        apply_style(figure, {})
        self.assertTrue(all(p.get_visible() for p in right.patches))
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()],
                         ["Bars left", "Bars right", "Step dose", "Trend"])

    def test_step_takes_line_controls_and_visibility(self):
        result = xy_series(frame(), options())
        axes = result.figure.axes[0]
        step = next(item for item in graph_series(axes) if item.key == "xy:1:Step dose")
        self.assertEqual(active_series_fields(axes, step), {"color", "label", "line_style", "width", "visible"})
        self.assertEqual(active_series_fields(axes, step, "Line"), {"color", "label", "line_style", "width"})
        self.assertEqual(active_series_fields(axes, step, "Bars"), {"color", "label", "visible", BAR_APPEARANCE})
        apply_style(result.figure, {"series": {"xy:1:Step dose": {"line_style": "dotted", "width": 2.5,
                                                                  "marker": "D", "visible": False}}})
        self.assertEqual((step.artist.get_linestyle(), step.artist.get_linewidth()), (":", 2.5))
        self.assertEqual(step.artist.get_marker(), "None")
        self.assertFalse(step.artist.get_visible())
        self.assertNotIn(step.artist, xy_legend_handles(axes))
        # The same saved style on a plain line leaves the line visible: visibility is a Step and Bars control.
        line = xy_series(frame(), options(**{"Series style": {"Step dose": "Line"}}))
        apply_style(line.figure, {"series": {"xy:1:Step dose": {"visible": False}}})
        self.assertTrue(next(a for a in line.figure.axes[0].lines if a.get_gid() == "xy:1:Step dose").get_visible())
        with self.assertRaises(ValueError):
            apply_style(result.figure, {"series": {"xy:1:Step dose": {"visible": "no"}}})

    def test_bars_reject_a_non_linear_x_or_left_y_axis_on_the_formatted_graph(self):
        result = xy_series(frame(), options())
        axes = result.figure.axes[0]
        for style, field in (({"xscale": "log"}, "X scale"), ({"yscale": "log"}, "Y scale"),
                             ({"xscale": "probability"}, "X scale")):
            with self.subTest(style=style):
                with self.assertRaises(FieldError) as raised:
                    apply_style(result.figure, style)
                self.assertEqual(raised.exception.field, field)
        # Bars only on the right: the left axis may still become logarithmic in the style check.
        right_only = xy_series(frame(), options(**{"Series style": {"Bars right": "Bars", "Trend": "Line"},
                                                   "Y columns": ["Bars right", "Trend"]}))
        validate_graph_style(right_only.figure.axes[0], {"yscale": "log"})

    def test_right_bars_are_drawn_below_left_lines_and_the_legend(self):
        result = xy_series(frame(), options(**{"Y columns": ["Bars right", "Trend"]}))
        left, right = result.figure.axes
        self.assertLess(right.get_zorder(), left.get_zorder())
        self.assertTrue(right.patch.get_visible())
        self.assertFalse(left.patch.get_visible())
        both = xy_series(frame(), options()).figure.axes
        self.assertGreaterEqual(both[1].get_zorder(), both[0].get_zorder())

    def test_vector_export_keeps_one_unique_id_per_rectangle(self):
        data = frame()
        data.index = ["r1", "r2", "r3", "r4", "r5", "r6"]
        result = xy_series(data, options())
        ids = [i for i in svg_ids(result.figure) if i.startswith("xybar:")]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertIn("xybar:Bars left:r3", ids)
        self.assertIn("xybar:Bars right:r6", ids)
        output = BytesIO()
        result.figure.savefig(output, format="svg")
        self.assertNotIn(b"<image", output.getvalue())
        pdf = BytesIO()
        result.figure.savefig(pdf, format="pdf")
        self.assertNotIn(b"/Subtype /Image", pdf.getvalue())
        repeated = frame()
        repeated.index = [0, 0, 1, 2, 3, 4]
        ids = [i for i in svg_ids(xy_series(repeated, options()).figure) if i.startswith("xybar:")]
        self.assertEqual(len(set(ids)), 10)

    def test_legend_editor_maps_bar_entries_to_their_series_keys(self):
        result = xy_series(frame(), options())
        entries = collect_legend_entries(result.figure)
        keys = [entry.key for entry in entries]
        self.assertEqual(keys[:4], ["xy:1:Bars left", "xy:1:Bars right", "xy:1:Step dose", "xy:1:Trend"])


if __name__ == "__main__":
    unittest.main()
