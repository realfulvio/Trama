import unittest

import numpy as np
import pandas as pd

from analisi.category_graphs import (
    BARS, GAP_BEFORE, GROUPED_BAR_SPACING, GROUPED_SERIES_ORDER, POINTS, SERIES_PLACEMENT,
    STACKED, STACK_PREVIOUS, SUMMARIES, SUPERIMPOSED, category_graph, grouped_graph_metadata,
)


class GroupedBarSpacingTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Visit": ["Before", "After"], "A": [2., np.nan],
                                   "B": [3., 4.], "C": [7., 0.]})
        self.options = {"Variables": ["A", "B", "C"], "Row titles": "Visit", "Graph style": BARS}
        self.spacing = {"adjacent": 25., "groups": 125., "empty": 50., "leading": 75., "trailing": 50.}

    def chart(self, **options):
        return category_graph(self.frame, {**self.options, **options}, grouped=True)

    def left_edges(self, axes):
        bars = grouped_graph_metadata(axes)["handles"]
        return {key: [patch.get_x() for patch in bar.patches] for key, bar in bars.items()}

    def test_partial_missing_slot_and_real_zero_have_distinct_widths(self):
        expected = self.chart()
        result = self.chart(**{GROUPED_BAR_SPACING: self.spacing})
        axes, = result.figure.axes
        self.assertEqual(self.left_edges(axes), {"A": [.75], "B": [2., 6.5], "C": [3.25, 7.75]})
        self.assertEqual(axes.get_xlim(), (0., 9.25))
        np.testing.assert_array_equal(axes.get_xticks(), [2.5, 7.25])
        self.assertEqual([text.get_text() for text in axes.get_xticklabels()], ["Before", "After"])
        pd.testing.assert_frame_equal(result.tables["Graph data"], expected.tables["Graph data"])

    def test_zero_spacing_can_remove_a_missing_slot_without_removing_a_zero(self):
        setting = dict.fromkeys(self.spacing, 0)
        result = self.chart(**{GROUPED_BAR_SPACING: setting})
        axes, = result.figure.axes
        self.assertEqual(self.left_edges(axes), {"A": [0.], "B": [1., 3.], "C": [2., 4.]})
        self.assertEqual(axes.get_xlim(), (0., 5.))
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["A", "B", "C"])

    def test_stacks_and_overlays_share_a_slot_and_distancing_adds_the_extra_gap(self):
        placement = {"B": STACK_PREVIOUS, "C": GAP_BEFORE}
        result = self.chart(**{GROUPED_BAR_SPACING: self.spacing, SERIES_PLACEMENT: placement})
        axes, = result.figure.axes
        self.assertEqual(self.left_edges(axes), {"A": [.75], "B": [.75, 5.75], "C": [3.25, 8.25]})
        self.assertEqual(grouped_graph_metadata(axes)["handles"]["B"].patches[0].get_y(), 2.)
        overlay = self.chart(**{GROUPED_BAR_SPACING: self.spacing, "Placement of groups": SUPERIMPOSED})
        self.assertEqual(self.left_edges(overlay.figure.axes[0]), {"A": [.75], "B": [.75, 3.25], "C": [.75, 3.25]})

    def test_omitting_an_empty_stacked_row_keeps_it_in_the_sheet(self):
        self.frame.loc[1, ["A", "B", "C"]] = np.nan
        result = self.chart(**{GROUPED_BAR_SPACING: {**self.spacing, "empty": 0.},
                               "Placement of groups": STACKED})
        axes, = result.figure.axes
        self.assertEqual([text.get_text() for text in axes.get_xticklabels()], ["Before"])
        self.assertEqual(axes.get_xlim(), (0., 2.25))
        self.assertEqual(len(result.tables["Graph data"]), 6)

    def test_summary_bars_with_one_row_label_the_reordered_nonempty_series(self):
        self.frame = pd.DataFrame({"Visit": ["Before"], "A [Mean]": [2.], "B [Mean]": [np.nan], "C [Mean]": [0.]})
        self.options.update({"Input": SUMMARIES, "Variables": list(self.frame.columns[1:])})
        result = self.chart(**{GROUPED_BAR_SPACING: {**self.spacing, "empty": 0.},
                               GROUPED_SERIES_ORDER: ["C", "B", "A"]})
        axes, = result.figure.axes
        self.assertEqual([text.get_text() for text in axes.get_xticklabels()], ["C", "A"])
        self.assertEqual(axes.get_xlim(), (0., 3.5))
        self.assertEqual(len(result.tables["Graph data"]), 3)

    def test_invalid_settings_are_rejected(self):
        for value in (None, {}, {**self.spacing, "empty": 101}, {**self.spacing, "groups": np.nan},
                      {**self.spacing, "leading": False}, {**self.spacing, "adjacent": -1}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "valid percentages"):
                self.chart(**{GROUPED_BAR_SPACING: value})
        with self.assertRaisesRegex(ValueError, "available for grouped bar"):
            self.chart(**{GROUPED_BAR_SPACING: self.spacing, "Graph style": POINTS})
