import unittest

import pandas as pd

from analisi.category_graphs import (
    BARS, GROUPED_SERIES_ORDER, INTERLEAVED, SERIES_PLACEMENT, STACKED, STACK_PREVIOUS,
    category_graph, grouped_graph_metadata,
)
from analisi.graph_legend import LEGEND_OPTIONS_KEY
from analisi.presentation import apply_style


class GroupedSeriesOrderTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Visit": ["Before", "After"], "A": [2, 3], "B": [4, 5], "C": [6, 7]})
        self.options = {"Variables": ["A", "B", "C"], "Row titles": "Visit", "Graph style": BARS}

    def chart(self, **options):
        return category_graph(self.frame, {**self.options, **options}, grouped=True)

    def legend(self, axes):
        return [label.get_text() for label in axes.get_legend().get_texts()]

    def test_interleaving_reassigns_positions_and_leaves_colors_and_legend_in_place(self):
        baseline = self.chart(**{"Placement of groups": INTERLEAVED})
        changed = self.chart(**{"Placement of groups": INTERLEAVED, GROUPED_SERIES_ORDER: ["C", "A", "B"]})
        axes, = changed.figure.axes
        meta = grouped_graph_metadata(axes)
        handles = meta["handles"]
        self.assertEqual(list(handles), ["C", "A", "B"])
        self.assertLess(handles["C"].patches[0].get_x(), handles["A"].patches[0].get_x())
        self.assertLess(handles["A"].patches[0].get_x(), handles["B"].patches[0].get_x())
        original = grouped_graph_metadata(baseline.figure.axes[0])["handles"]
        for name in handles:
            self.assertEqual(handles[name].patches[0].get_facecolor(), original[name].patches[0].get_facecolor())
        self.assertTrue(baseline.tables["Graph data"].equals(changed.tables["Graph data"]))
        self.assertEqual(self.legend(axes), ["A", "B", "C"])
        apply_style(changed.figure, {LEGEND_OPTIONS_KEY: {"reverse": True}})
        self.assertEqual(self.legend(axes), ["C", "B", "A"])

    def test_stack_uses_the_drawing_order_and_retains_original_legend_order(self):
        for value in (STACKED, INTERLEAVED):
            with self.subTest(layout=value):
                settings = {"Placement of groups": value, GROUPED_SERIES_ORDER: ["C", "A", "B"]}
                if value == INTERLEAVED:
                    settings[SERIES_PLACEMENT] = {"B": STACK_PREVIOUS, "A": STACK_PREVIOUS}
                result = self.chart(**settings)
                axes, = result.figure.axes
                bars = grouped_graph_metadata(axes)["handles"]
                self.assertEqual([bars[name].patches[0].get_y() for name in ("C", "A", "B")], [0., 6., 8.])
                apply_style(result.figure, {"legend": "upper left"})
                self.assertEqual(self.legend(axes), ["A", "B", "C"])

    def test_absent_entries_and_duplicate_order(self):
        result = self.chart(**{GROUPED_SERIES_ORDER: ["C", "Absent"]})
        self.assertEqual(grouped_graph_metadata(result.figure.axes[0])["series_order"], ["C", "A", "B"])
        with self.assertRaisesRegex(ValueError, "valid order"):
            self.chart(**{GROUPED_SERIES_ORDER: ["C", "C"]})
