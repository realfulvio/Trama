import unittest

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from analisi.category_graphs import BAR_DIRECTION, BARS, HORIZONTAL_BARS, category_graph, grouped_graph_metadata
from analisi.presentation import apply_style


class GroupedIntervalAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Visit": ["Before", "After"], "A [1]": [1., 3.], "A [2]": [3., 7.],
                                   "B [1]": [4., 7.], "B [2]": [7., 8.]})
        self.options = {"Variables": list(self.frame.columns[1:]), "Row titles": "Visit",
                        "Graph style": BARS, "Interval": "SEM"}

    def test_intervals_keep_their_own_style_in_both_orientations(self):
        for direction in ({}, {BAR_DIRECTION: HORIZONTAL_BARS}):
            with self.subTest(direction=direction):
                result = category_graph(self.frame, {**self.options, **direction}, grouped=True)
                bars = grouped_graph_metadata(result.figure.axes[0])["handles"]
                initial = bars["A"].patches[0].get_facecolor()
                _, caps, whiskers = bars["A"]._tramastat_grouped_series["errorbar"].lines
                original_color = whiskers[0].get_colors().copy()
                original_widths = whiskers[0].get_linewidths().copy()
                original_lengths = [cap.get_markersize() for cap in caps]
                other = bars["B"]._tramastat_grouped_series["errorbar"].lines[2][0]
                other_colors = other.get_colors().copy()
                apply_style(result.figure, {"series": {"grouped:1:A": {
                    "interval_color": "#cc315d", "interval_width": 2.5, "interval_caps": 0.,
                }}})
                np.testing.assert_array_equal(whiskers[0].get_colors()[0], to_rgba("#cc315d"))
                self.assertEqual(list(whiskers[0].get_linewidths()), [2.5])
                self.assertTrue(all(not cap.get_visible() for cap in caps))
                self.assertEqual(bars["A"].patches[0].get_facecolor(), initial)
                np.testing.assert_array_equal(other.get_colors(), other_colors)
                apply_style(result.figure, {"series": {"grouped:1:A": {"interval_caps": 6.}}})
                self.assertEqual([cap.get_markersize() for cap in caps], [6., 6.])
                self.assertTrue(all(cap.get_visible() for cap in caps))
                apply_style(result.figure, {})
                np.testing.assert_array_equal(whiskers[0].get_colors(), original_color)
                np.testing.assert_array_equal(whiskers[0].get_linewidths(), original_widths)
                self.assertEqual([cap.get_markersize() for cap in caps], original_lengths)

    def test_interval_style_rejects_nonfinite_thickness_and_invalid_caps(self):
        chart = category_graph(self.frame, self.options, grouped=True).figure
        for changes in ({"interval_caps": -1}, {"interval_caps": 73}, {"interval_width": 0},
                        {"interval_width": float("inf")}, {"interval_color": "bad color"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_style(chart, {"series": {"grouped:1:A": changes}})
