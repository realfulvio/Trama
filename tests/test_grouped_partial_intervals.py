import unittest

import numpy as np
import pandas as pd

from analisi.category_graphs import (
    BAR_DIRECTION, BARS, DISTANCES, HORIZONTAL_BARS, INTERVAL_DIRECTION, LIMITS,
    LOWER_INTERVAL, SERIES_PLACEMENT, STACK_PREVIOUS, SUMMARIES, UPPER_INTERVAL,
    category_graph, grouped_graph_metadata,
)
from analisi.field_error import FieldError


class GroupedPartialIntervalTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Visit": ["Lower", "Upper", "Both", "Neither"], "A [Mean]": [5., 8., 10., 11.],
            "A [Minus]": [3., np.nan, 2., np.nan], "A [Plus]": [np.nan, 3., 1., np.nan],
        })

    def graph(self, **choices):
        settings = {"Input": SUMMARIES, "Variables": list(self.frame.columns[1:]), "Row titles": "Visit",
                    "Graph style": BARS, "Summary error": DISTANCES}
        return category_graph(self.frame, {**settings, **choices}, grouped=True)

    def errorbar(self, result, series="A"):
        primary = grouped_graph_metadata(result.figure.axes[0])["handles"][series]
        return primary._tramastat_grouped_series["errorbar"]

    def test_partial_endpoints_follow_their_rows_in_both_orientations(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                settings = {BAR_DIRECTION: HORIZONTAL_BARS} if horizontal else {}
                result = self.graph(**settings)
                error = self.errorbar(result)
                values = 0 if horizontal else 1
                np.testing.assert_array_equal([segment[:, values] for segment in error.lines[2][0].get_segments()],
                                              [[2., 5.], [8., 11.], [8., 11.]])
                caps = [getattr(cap, "get_xdata" if horizontal else "get_ydata")() for cap in error.lines[1]]
                np.testing.assert_array_equal(caps[0], [2., 8.])
                np.testing.assert_array_equal(caps[1], [11., 11.])
                table = result.tables["Graph data"]
                np.testing.assert_array_equal(table["Lower"], [2., np.nan, 8., np.nan])
                np.testing.assert_array_equal(table["Upper"], [np.nan, 11., 11., np.nan])

    def test_display_direction_uses_only_available_endpoints(self):
        for direction, segments in ((LOWER_INTERVAL, [[2., 5.], [8., 10.]]),
                                    (UPPER_INTERVAL, [[8., 11.], [10., 11.]])):
            with self.subTest(direction=direction):
                error = self.errorbar(self.graph(**{INTERVAL_DIRECTION: direction}))
                np.testing.assert_array_equal([segment[:, 1] for segment in error.lines[2][0].get_segments()], segments)

    def test_partial_lower_limit_from_a_stacked_summary_is_translated_with_its_segment(self):
        self.frame["B [Mean]"] = [5., 7., 8., 9.]
        self.frame["B [Minus]"] = [1., np.nan, np.nan, np.nan]
        self.frame["B [Plus]"] = [np.nan] * 4
        error = self.errorbar(self.graph(**{SERIES_PLACEMENT: {"B": STACK_PREVIOUS}}), "B")
        np.testing.assert_array_equal(error.lines[2][0].get_segments()[0][:, 1], [9., 10.])
        self.assertEqual(len(error.lines[1][1].get_ydata()), 0)

    def test_entered_limits_on_the_wrong_side_report_the_column(self):
        self.frame = self.frame.rename(columns={"A [Minus]": "A [Lower]", "A [Plus]": "A [Upper]"})
        self.frame["A [Lower]"] = [2., np.nan, 8., np.nan]
        self.frame["A [Upper]"] = [np.nan, 11., 11., np.nan]
        self.assertEqual(len(self.errorbar(self.graph(**{"Summary error": LIMITS})).lines[2][0].get_segments()), 3)
        self.frame.loc[0, "A [Lower]"] = 6.
        with self.assertRaisesRegex(FieldError, "wrong side") as error:
            self.graph(**{"Summary error": LIMITS})
        self.assertEqual(error.exception.column, "A [Lower]")
