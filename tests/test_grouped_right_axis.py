import unittest

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba

from analisi.category_graphs import (
    BAR_BASELINE, BAR_DIRECTION, BARS, HORIZONTAL_BARS, LIMITS, RIGHT_SIDE, SERIES_INTERVAL_DIRECTION,
    SERIES_PLACEMENT, SERIES_SIDE, STACK_PREVIOUS, SUMMARIES, UPPER_INTERVAL, category_graph, grouped_graph_metadata,
)
from analisi.presentation import apply_style


class GroupedRightAxisTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Visit": ["Before", "After"], "A": [2., 4.], "B": [1000., 2000.], "C": [500., 700.],
        })
        self.options = {"Variables": ["A", "B", "C"], "Row titles": "Visit", "Graph style": BARS}

    def chart(self, **choices):
        return category_graph(self.frame, {**self.options, **choices}, grouped=True)

    def test_right_axis_draws_only_its_series_with_an_independent_range(self):
        before = self.chart()
        result = self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE, "C": RIGHT_SIDE},
                               "Right title": "Mass (mg)", "Right minimum": 0, "Right maximum": 2500})
        left, right = result.figure.axes
        handles = grouped_graph_metadata(left)["handles"]
        self.assertIs(handles["A"].patches[0].axes, left)
        self.assertIs(handles["B"].patches[0].axes, right)
        self.assertIs(handles["C"].patches[0].axes, right)
        self.assertEqual(right.get_ylim(), (0., 2500.))
        self.assertLess(left.get_ylim()[1], 10)
        self.assertEqual(right.get_ylabel(), "Mass (mg)")
        self.assertTrue(left.get_shared_x_axes().joined(left, right))
        self.assertEqual([entry.get_text() for entry in left.get_legend().get_texts()], ["A", "B", "C"])
        pd.testing.assert_frame_equal(before.tables["Graph data"], result.tables["Graph data"])

        apply_style(result.figure, {"series": {"grouped:1:B": {"color": "#9154af"}}})
        self.assertEqual(handles["B"].patches[0].get_edgecolor(), to_rgba("#9154af"))

    def test_bars_on_the_same_axis_stack_in_that_axis_units(self):
        result = self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE, "C": RIGHT_SIDE},
                               SERIES_PLACEMENT: {"C": STACK_PREVIOUS}})
        left, right = result.figure.axes
        handles = grouped_graph_metadata(left)["handles"]
        self.assertEqual([patch.get_y() for patch in handles["C"].patches], [1000., 2000.])
        self.assertNotIn("y", getattr(left, "_tramastat_zero_baseline", ()))
        self.assertIn("y", right._tramastat_zero_baseline)
        with self.assertRaisesRegex(ValueError, "same value axis"):
            self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE}, SERIES_PLACEMENT: {"C": STACK_PREVIOUS}})

    def test_all_series_on_right_and_error_cases(self):
        result = self.chart(**{SERIES_SIDE: dict.fromkeys(("A", "B", "C"), RIGHT_SIDE)})
        left, right = result.figure.axes
        self.assertFalse(left.yaxis.get_visible())
        self.assertTrue(right.yaxis.get_visible())

        for choices, message in (({BAR_DIRECTION: HORIZONTAL_BARS}, "vertical grouped"),
                                 ({"Right scale": "Other"}, "linear or logarithmic"),
                                 ({"Right minimum": 3}, "both axis limits")):
            with self.subTest(choices=choices), self.assertRaisesRegex(ValueError, message):
                self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE}, **choices})

    def test_logarithmic_bars_start_at_one_and_keep_the_exact_lower_limit(self):
        frame = pd.DataFrame({
            "Visit": ["A", "B"], "A [Mean]": [-2., 4.], "A [Lower]": [np.nan, np.nan],
            "A [Upper]": [np.nan, np.nan], "B [Mean]": [1e-22, 10.],
            "B [Lower]": [np.nan, 1e-20], "B [Upper]": [np.nan, 12.],
        })
        options = {
            "Variables": list(frame.columns[1:]), "Row titles": "Visit", "Graph style": BARS,
            "Input": SUMMARIES, "Summary error": LIMITS, SERIES_SIDE: {"B": RIGHT_SIDE},
        }
        linear = category_graph(frame, options, grouped=True)
        logarithmic = category_graph(frame, {**options, "Right scale": "Log"}, grouped=True)
        left, right = logarithmic.figure.axes
        self.assertEqual((left.get_yscale(), right.get_yscale()), ("linear", "log"))
        handles = grouped_graph_metadata(left)["handles"]
        bars = handles["B"].patches
        self.assertEqual(bars[0].get_y(), 1e-22)
        self.assertEqual(bars[1].get_y(), 1.)
        self.assertEqual(bars[1].get_height(), 9.)
        error = handles["B"]._tramastat_grouped_series["errorbar"]
        np.testing.assert_array_equal(error.lines[2][0].get_segments()[0][:, 1], [1e-20, 12.])
        self.assertLessEqual(right.get_ylim()[0], 1e-22)
        pd.testing.assert_frame_equal(linear.tables["Graph data"], logarithmic.tables["Graph data"])

    def test_visible_endpoints_and_baseline_must_suit_the_logarithmic_axis(self):
        frame = pd.DataFrame({
            "Visit": ["A", "B"], "B [Mean]": [2., 10.],
            "B [Lower]": [0., 8.], "B [Upper]": [4., 12.],
        })
        options = {
            "Variables": list(frame.columns[1:]), "Row titles": "Visit", "Graph style": BARS,
            "Input": SUMMARIES, "Summary error": LIMITS, SERIES_SIDE: {"B": RIGHT_SIDE}, "Right scale": "Log",
        }
        with self.assertRaisesRegex(ValueError, "must be positive"):
            category_graph(frame, options, grouped=True)
        upper = {**options, SERIES_INTERVAL_DIRECTION: {"B": UPPER_INTERVAL}, BAR_BASELINE: .5}
        result = category_graph(frame, upper, grouped=True)
        handle = grouped_graph_metadata(result.figure.axes[0])["handles"]["B"]
        self.assertEqual(handle.patches[0].get_y(), .5)
        with self.assertRaisesRegex(ValueError, "baseline.* must be positive"):
            category_graph(frame, {**upper, BAR_BASELINE: -1.}, grouped=True)
        with self.assertRaisesRegex(ValueError, "stack on the right needs a linear"):
            self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE, "C": RIGHT_SIDE}, "Right scale": "Log",
                           SERIES_PLACEMENT: {"C": STACK_PREVIOUS}})
