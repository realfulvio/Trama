import unittest

import pandas as pd

from analisi.data import MAX_COLUMNS
from analisi.presentation import apply_style, graph_series, validated_style
from analisi.axis_breaks import AXIS_BREAKS, segment_axes
from analisi.point_style import GID_PREFIX, POINTS, point_map, source_record
from analisi.series_layers import XY_SERIES_ORDER, xy_layer_groups, xy_order_record
from analisi.xy_series import X_ERROR_ARTISTS, xy_series


class XYSeriesLayersTests(unittest.TestCase):
    def test_single_point_style_and_broken_axis_follow_the_series_layer(self):
        frame = pd.DataFrame({"X": [1, 2, 4], "A": [2, 3, 4], "B": [2, 3, 4]})
        figure = xy_series(frame, {"X": "X", "Y columns": ["A", "B"]}).figure
        axes = figure.axes[0]
        a, b = graph_series(axes)
        order = {XY_SERIES_ORDER: [b.key, a.key]}
        source = source_record(point_map(b.artist), 0)
        apply_style(figure, {**order, POINTS: [{"series": b.key, "source": source, "color": "#ff0000"}]})
        overlay, = (line for line in axes.lines if str(line.get_gid()).startswith(GID_PREFIX))
        self.assertLess(b.artist.get_zorder(), overlay.get_zorder())
        self.assertLess(overlay.get_zorder(), a.artist.get_zorder())
        breaks = {"axis": "x", "gap": .04, "segments": [{"low": 0, "high": 2, "share": 50},
                                                       {"low": 3, "high": 5, "share": 50}]}
        apply_style(figure, {**order, AXIS_BREAKS: breaks})
        _, second = segment_axes(figure)
        clones = {line.get_gid().rsplit(":", 1)[-1]: line.get_zorder()
                  for line in second.lines if ":xy:1:" in str(line.get_gid())}
        self.assertLess(clones["B"], clones["A"])

    def test_orders_bars_points_and_errors_without_moving_bar_slots_or_legend(self):
        frame = pd.DataFrame({"X": [1, 2, 4], "DX": [.2, .2, .1],
                              "A": [2, 4, 6], "B": [2, 4, 6], "C": [2, 4, 6]})
        result = xy_series(frame, {"X": "X", "Y columns": ["A", "B", "C"], "X error distance": "DX",
                                  "Series style": {"B": "Bars", "C": "Bars"}})
        figure = result.figure
        axes = figure.axes[0]
        a, b, c = graph_series(axes)
        defaults = [a.artist.get_zorder(), b.artist.patches[0].get_zorder(), c.artist.patches[0].get_zorder()]
        centers = [patch.get_x() for item in (b, c) for patch in item.artist.patches]
        legend = [text.get_text() for text in axes.get_legend().get_texts()]
        values = {name: table.copy(deep=True) for name, table in result.tables.items()}
        order = [a.key, c.key, b.key]
        apply_style(figure, {XY_SERIES_ORDER: order})
        for _ in range(2):
            self.assertLess(a.artist.get_zorder(), c.artist.patches[0].get_zorder())
            self.assertLess(c.artist.patches[0].get_zorder(), b.artist.patches[0].get_zorder())
            for item in (b, c):
                self.assertTrue(all(error.get_zorder() == item.artist.patches[0].get_zorder()
                                    for error in getattr(item.artist, X_ERROR_ARTISTS)))
            self.assertEqual([patch.get_x() for item in (b, c) for patch in item.artist.patches], centers)
            self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], legend)
            apply_style(figure, {XY_SERIES_ORDER: order})
        apply_style(figure, {})
        self.assertEqual([a.artist.get_zorder(), b.artist.patches[0].get_zorder(),
                          c.artist.patches[0].get_zorder()], defaults)
        for name, table in result.tables.items():
            pd.testing.assert_frame_equal(table, values[name])

    def test_twin_axes_keep_their_own_stack_and_absent_keys_keep_their_place(self):
        frame = pd.DataFrame({"X": [1, 2], "A": [1, 2], "B": [1, 2], "C": [10, 20], "D": [10, 20]})
        figure = xy_series(frame, {"X": "X", "Y columns": ["A", "B", "C", "D"],
                                   "Series side": {"C": "Right", "D": "Right"}}).figure
        series = graph_series(figure.axes[0])
        a, b, c, d = (item.key for item in series)
        original_depth = [axes.get_zorder() for axes in figure.axes]
        record = xy_order_record(figure, series, [d, "xy:1:Missing", c, b, a], [a, b, d, c])
        self.assertEqual(record, [a, "xy:1:Missing", b, d, c])
        apply_style(figure, {XY_SERIES_ORDER: record})
        groups = xy_layer_groups(figure, series, record)
        self.assertEqual([[item.key for item in group] for _, group in groups], [[a, b], [d, c]])
        self.assertLess(series[3].artist.get_zorder(), series[2].artist.get_zorder())
        self.assertEqual([axes.get_zorder() for axes in figure.axes], original_depth)

    def test_rejects_duplicate_and_non_xy_entries(self):
        for order in (["xy:1:A", "xy:1:A"], ["bar:1:B"], "xy:1:A"):
            with self.subTest(order=order), self.assertRaisesRegex(ValueError, "Invalid XY series drawing order"):
                validated_style({XY_SERIES_ORDER: order})

    def test_order_supports_the_full_worksheet_column_budget(self):
        order = [f"xy:1:S{index}" for index in range(MAX_COLUMNS)]
        self.assertEqual(validated_style({XY_SERIES_ORDER: order})[XY_SERIES_ORDER], order)
        with self.assertRaisesRegex(ValueError, "Invalid XY series drawing order"):
            validated_style({XY_SERIES_ORDER: [*order, "xy:1:Extra"]})
