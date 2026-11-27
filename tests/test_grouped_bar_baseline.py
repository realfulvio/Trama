import unittest

import numpy as np
import pandas as pd

from analisi.category_graphs import (
    BAR_BASELINE, BAR_DIRECTION, BARS, HORIZONTAL_BARS, SERIES_PLACEMENT, STACK_PREVIOUS,
    STACKED, category_graph, grouped_graph_metadata,
)


class GroupedBarBaselineTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Visit": ["Before", "After"], "A [1]": [1., 5.], "A [2]": [3., 7.],
                                   "B": [9., -2.]})
        self.options = {"Variables": list(self.frame.columns[1:]), "Row titles": "Visit",
                        "Graph style": BARS, "Interval": "SEM"}

    def chart(self, **options):
        return category_graph(self.frame, {**self.options, **options}, grouped=True)

    def test_baseline_changes_the_bar_start_without_shifting_its_estimate_or_interval(self):
        original = self.chart()
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                settings = {BAR_BASELINE: 4.5}
                if horizontal:
                    settings[BAR_DIRECTION] = HORIZONTAL_BARS
                result = self.chart(**settings)
                bars = grouped_graph_metadata(result.figure.axes[0])["handles"]["A"]
                starts = [bar.get_x() if horizontal else bar.get_y() for bar in bars.patches]
                lengths = [bar.get_width() if horizontal else bar.get_height() for bar in bars.patches]
                self.assertEqual(starts, [4.5, 4.5])
                self.assertEqual(lengths, [-2.5, 1.5])
                error = bars._tramastat_grouped_series["errorbar"]
                endpoints = [sample[:, int(not horizontal)] for sample in error.lines[2][0].get_segments()]
                np.testing.assert_array_equal(endpoints, [[1., 3.], [5., 7.]])
                pd.testing.assert_frame_equal(original.tables["Graph data"], result.tables["Graph data"])

    def test_custom_baseline_rejects_stacked_bars(self):
        for mode in ({"Placement of groups": STACKED, "Interval": "None"},
                     {SERIES_PLACEMENT: {"B": STACK_PREVIOUS}}):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "without stacks"):
                self.chart(**{**mode, BAR_BASELINE: -2.})

    def test_invalid_or_unrepresentable_baseline_shows_an_error(self):
        for invalid in (False, float("inf"), float("nan"), 10 ** 400, "1.5"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "finite starting value"):
                self.chart(**{BAR_BASELINE: invalid})
        self.frame.loc[0, "B"] = -1.e308
        with self.assertRaisesRegex(ValueError, "exceeds the numeric range"):
            self.chart(**{BAR_BASELINE: 1.e308, "Interval": "None"})
