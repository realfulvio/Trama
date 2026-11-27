import unittest

import numpy as np
import pandas as pd

from analisi.category_graphs import (
    BAR_DIRECTION, BARS, GROUPED_BAR_SPACING, HORIZONTAL_BARS, LINE_SYMBOLS, LOWER_INTERVAL,
    PERCENT_STACKED, POINTS, SERIES_INTERVAL_DIRECTION, SERIES_PLACEMENT, SERIES_STYLE, STACK_PREVIOUS,
    category_graph, grouped_graph_metadata, transpose_grouped_bar_style,
)
from analisi.presentation import apply_style


class GroupedBarDirectionTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Visit": ["Before", "After"], "A [1]": [1., -3.], "A [2]": [3., -1.],
            "B [1]": [2., -7.], "B [2]": [4., -5.], "C": [8., 7.],
        })
        self.options = {"Variables": list(self.frame.columns[1:]), "Row titles": "Visit", "Graph style": BARS}

    def chart(self, **options):
        return category_graph(self.frame, {**self.options, **options}, grouped=True)

    def test_horizontal_stack_and_asymmetric_intervals_use_the_value_axis(self):
        common = {"Interval": "SEM", SERIES_PLACEMENT: {"B": STACK_PREVIOUS},
                  SERIES_INTERVAL_DIRECTION: {"B": LOWER_INTERVAL}, SERIES_STYLE: {"C": LINE_SYMBOLS},
                  GROUPED_BAR_SPACING: {"adjacent": 25., "groups": 75., "empty": 100., "leading": 50., "trailing": 50.}}
        original = self.chart(**common)
        result = self.chart(**{**common, BAR_DIRECTION: HORIZONTAL_BARS})
        axes, = result.figure.axes
        meta = grouped_graph_metadata(axes)
        bars = meta["handles"]["B"]
        self.assertEqual(axes._tramastat_numeric_axes, ("x",))
        self.assertEqual(axes._tramastat_categorical_axes, ("y",))
        self.assertEqual(axes._tramastat_zero_baseline, ("x",))
        self.assertTrue(axes.yaxis_inverted())
        self.assertEqual([tick.get_text() for tick in axes.get_yticklabels()], ["Before", "After"])
        self.assertEqual(axes.get_xlabel(), "Value")
        self.assertEqual([bar.get_x() for bar in bars.patches], [2., -2.])
        self.assertEqual([bar.get_width() for bar in bars.patches], [3., -6.])
        self.assertTrue(all(bar.get_height() == 1 for bar in bars.patches))
        err = bars._tramastat_grouped_series["errorbar"]
        self.assertTrue(err.has_xerr and not err.has_yerr)
        np.testing.assert_array_equal([segment[:, 0] for segment in err.lines[2][0].get_segments()],
                                      [[4., 5.], [-9., -8.]])
        np.testing.assert_array_equal(meta["handles"]["C"].get_xdata(), [8., 7.])
        pd.testing.assert_frame_equal(original.tables["Graph data"], result.tables["Graph data"])

    def test_percent_stack_has_a_horizontal_zero_to_one_hundred_scale(self):
        self.frame.iloc[:, 1:] = abs(self.frame.iloc[:, 1:])
        result = self.chart(**{BAR_DIRECTION: HORIZONTAL_BARS, "Placement of groups": PERCENT_STACKED})
        axes, = result.figure.axes
        self.assertEqual(axes.get_xlim(), (0., 100.))
        self.assertEqual([label.get_text() for label in axes.get_legend().get_texts()], ["A", "B", "C"])
        self.assertTrue(axes.yaxis_inverted())

    def test_transposition_preserves_numeric_limits_labels_and_data_anchors(self):
        before = {
            "xlabel": "Visits", "ylabel": "Response", "axis": {"y": {"min": -12., "max": 12.}},
            "linked_axes": {"y": {"multiplier": 2., "offset": 1., "label": "Converted units"}},
            "reference_lines": [{"axis": "y", "value": 2., "label": "Limit"}],
            "axis_breaks": {},
            "annotations": [
                {"units": "data", "position": [0., 4.], "target": [1., 5.],
                 "align": "left", "size": 12., "text": "Data anchor", "color": "#315570"},
                {"units": "axes", "position": [.8, .2], "align": "left", "size": 12.,
                 "text": "Corner note", "color": "#315570"},
            ],
        }
        changed = transpose_grouped_bar_style(before)
        self.assertEqual(changed["annotations"][0]["position"], [4., 0.])
        self.assertEqual(changed["annotations"][0]["target"], [5., 1.])
        self.assertEqual(changed["annotations"][1], before["annotations"][1])
        self.assertEqual(changed["reference_lines"][0]["axis"], "x")
        self.assertEqual(transpose_grouped_bar_style(changed), before)
        result = self.chart(**{BAR_DIRECTION: HORIZONTAL_BARS})
        apply_style(result.figure, changed)
        axes, = result.figure.axes
        self.assertEqual(axes.get_xlabel(), "Response")
        self.assertEqual(axes.get_ylabel(), "Visits")
        self.assertEqual(axes.get_xlim(), (-12., 12.))

    def test_orientation_is_rejected_if_the_grouped_chart_has_no_bars(self):
        with self.assertRaisesRegex(ValueError, "available for grouped bar"):
            self.chart(**{BAR_DIRECTION: HORIZONTAL_BARS, "Graph style": POINTS})
