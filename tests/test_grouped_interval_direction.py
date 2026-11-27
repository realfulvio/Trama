import unittest

import numpy as np
import pandas as pd

from analisi.category_graphs import (
    BARS, BOTH_INTERVALS, DISTANCES, INTERVAL_DIRECTION, LOWER_INTERVAL, SERIES_INTERVAL_DIRECTION,
    SERIES_PLACEMENT, STACK_PREVIOUS, STACKED, SUMMARIES, UPPER_INTERVAL,
    category_graph, grouped_graph_metadata,
)


class GroupedIntervalDirectionTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Visit": ["Before", "After"],
            "A [Mean]": [5., -2.], "A [Minus]": [2., 3.], "A [Plus]": [4., 2.],
            "B [Mean]": [3., 4.], "B [Minus]": [1., 2.], "B [Plus]": [3., 1.],
        })
        self.options = {"Input": SUMMARIES, "Variables": list(self.frame.columns[1:]), "Row titles": "Visit",
                        "Graph style": BARS, "Summary error": DISTANCES, SERIES_PLACEMENT: {"B": STACK_PREVIOUS}}

    def chart(self, **options):
        return category_graph(self.frame, {**self.options, **options}, grouped=True)

    def errorbar(self, figure, name):
        artist = grouped_graph_metadata(figure.axes[0])["handles"][name]
        return artist._tramastat_grouped_series["errorbar"]

    def endpoints(self, errorbar):
        return np.array([segment[:, 1] for segment in errorbar.lines[2][0].get_segments()])

    def test_directions_clip_asymmetric_intervals_at_each_stack_segment(self):
        original = self.chart()
        result = self.chart(**{INTERVAL_DIRECTION: UPPER_INTERVAL, SERIES_INTERVAL_DIRECTION: {"B": LOWER_INTERVAL}})
        a = self.errorbar(result.figure, "A")
        b = self.errorbar(result.figure, "B")
        np.testing.assert_array_equal(self.endpoints(a), [[5., 9.], [-2., 0.]])
        np.testing.assert_array_equal(self.endpoints(b), [[7., 8.], [2., 4.]])
        self.assertEqual([len(cap.get_ydata()) for cap in a.lines[1]], [0, 2])
        self.assertEqual([len(cap.get_ydata()) for cap in b.lines[1]], [2, 0])
        pd.testing.assert_frame_equal(original.tables["Graph data"], result.tables["Graph data"])

    def test_both_ends_can_override_the_plot_direction(self):
        result = self.chart(**{INTERVAL_DIRECTION: LOWER_INTERVAL, SERIES_INTERVAL_DIRECTION: {"B": BOTH_INTERVALS}})
        np.testing.assert_array_equal(self.endpoints(self.errorbar(result.figure, "A")), [[3., 5.], [-5., -2.]])
        np.testing.assert_array_equal(self.endpoints(self.errorbar(result.figure, "B")), [[7., 11.], [2., 5.]])

    def test_intervals_validate_the_choice_without_creating_errors_on_a_global_stack(self):
        for invalid in (["B"], {"B": "something else"}, {"": LOWER_INTERVAL}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "valid interval direction"):
                self.chart(**{SERIES_INTERVAL_DIRECTION: invalid})
        with self.assertRaisesRegex(ValueError, "Per-series interval direction"):
            self.chart(**{"Placement of groups": STACKED, "Summary error": "None", SERIES_PLACEMENT: {},
                         SERIES_INTERVAL_DIRECTION: {"B": LOWER_INTERVAL}})
