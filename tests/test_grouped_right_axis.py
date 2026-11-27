import unittest

import pandas as pd
from matplotlib.colors import to_rgba

from analisi.category_graphs import (
    BAR_DIRECTION, BARS, HORIZONTAL_BARS, RIGHT_SIDE, SERIES_PLACEMENT, SERIES_SIDE,
    STACK_PREVIOUS, category_graph, grouped_graph_metadata,
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
                                 ({"Right scale": "Log"}, "linear scale"),
                                 ({"Right minimum": 3}, "both axis limits")):
            with self.subTest(choices=choices), self.assertRaisesRegex(ValueError, message):
                self.chart(**{SERIES_SIDE: {"B": RIGHT_SIDE}, **choices})
