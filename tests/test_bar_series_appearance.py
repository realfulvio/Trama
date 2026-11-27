import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd

from analisi.category_graphs import BARS, GROUPED_GRAPH, STACKED, category_graph
from analisi.data import BAR_APPEARANCE_VERSION, Dataset, load_workspace, save_project
from analisi.grouped_bar_style import BAR_APPEARANCE, BAR_STYLES, bar_appearance, grouped_bars
from analisi.presentation import apply_style, graph_series, validated_style
from analisi.xy_series import xy_series


class BarSeriesAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.data = Dataset(pd.DataFrame({"Visit": [1., 2., 3.], "A": [2., 4., 7.], "B": [0., 8., 10.]}))
        self.grouped = {"Variables": ["A", "B"], "Row titles": "Visit", "Graph style": BARS}
        self.appearance = {"fill": "none", "border": "#309366", "pattern": "grid",
                           "pattern_color": "#b41d94", "width": 2.5}

    def test_fill_border_pattern_and_intervals_are_independent(self):
        frame = self.data.frame().rename(columns={"A": "A [1]"}).assign(**{"A [2]": [4., 7., 9.]})
        options = {**self.grouped, "Variables": ["A [1]", "A [2]", "B"], "Interval": "SD"}
        result = category_graph(frame, options, grouped=True)
        figure = result.figure
        series, other = graph_series(figure.axes[0])
        before = [bar_appearance(patch) for patch in series.artist.patches]
        other_before = [bar_appearance(patch) for patch in other.artist.patches]
        whiskers = series.artist._tramastat_grouped_series["errorbar"].lines[2][0]
        interval_color = whiskers.get_colors().copy()
        style = {"series": {series.key: {BAR_APPEARANCE: self.appearance}}}
        apply_style(figure, style)
        for patch in series.artist.patches:
            self.assertEqual(patch.get_facecolor(), to_rgba("none"))
            self.assertEqual(patch.get_edgecolor(), to_rgba("#309366"))
            self.assertEqual(patch.get_hatchcolor(), to_rgba("#b41d94"))
            self.assertEqual((patch.get_hatch(), patch.get_linewidth()), ("+", 2.5))
        self.assertEqual([bar_appearance(patch) for patch in other.artist.patches], other_before)
        np.testing.assert_array_equal(whiskers.get_colors(), interval_color)
        self.assertEqual(figure.axes[0].get_legend().legend_handles[0].get_hatch(), "+")
        apply_style(figure, {})
        self.assertEqual([bar_appearance(patch) for patch in series.artist.patches], before)

    def test_single_bar_inherits_the_series_pattern_color_then_can_override_it(self):
        result = category_graph(self.data.frame(), self.grouped, grouped=True)
        figure = result.figure
        series, _ = graph_series(figure.axes[0])
        first = next(bar for bar in grouped_bars(figure) if bar.series == series.name)
        style = {"series": {series.key: {BAR_APPEARANCE: self.appearance}}}
        outline = first.record({"border": "#203040", "pattern": "diagonal"})
        apply_style(figure, {**style, BAR_STYLES: [outline]})
        self.assertEqual(first.patch.get_hatchcolor(), to_rgba(self.appearance["pattern_color"]))
        record = first.record({"pattern_color": "#684422", "width": 7})
        apply_style(figure, {**style, BAR_STYLES: [record]})
        self.assertEqual(first.patch.get_hatchcolor(), to_rgba("#684422"))
        self.assertEqual(first.patch.get_linewidth(), 7)
        apply_style(figure, style)
        self.assertEqual(first.patch.get_hatchcolor(), to_rgba(self.appearance["pattern_color"]))
        self.assertEqual(first.patch.get_linewidth(), 2.5)

    def test_column_xy_and_stacked_grouped_bars_use_same_appearance(self):
        frame = self.data.frame()
        named_graphs = (
            ("column", category_graph(frame, self.grouped)),
            ("xy", xy_series(frame, {"X": "Visit", "Y columns": ["A", "B"], "Series style": {"A": BARS, "B": BARS}})),
            ("stacked", category_graph(frame, {**self.grouped, "Placement of groups": STACKED}, grouped=True)),
        )
        for name, result in named_graphs:
            with self.subTest(graph=name):
                chart = result.figure
                chosen = next(series for series in graph_series(chart.axes[0]) if series.artist.get_label() == "B")
                before = [patch.get_height() for patch in chosen.artist.patches]
                apply_style(chart, {"series": {chosen.key: {BAR_APPEARANCE: self.appearance}}})
                self.assertEqual([patch.get_height() for patch in chosen.artist.patches], before)
                self.assertTrue(all(patch.get_hatch() == "+" for patch in chosen.artist.patches))
                if name == "stacked":
                    self.assertEqual(chosen.artist.patches[0].get_linewidth(), 0.)

    def test_project_uses_new_schema_only_for_new_fields_and_patterns(self):
        chart = category_graph(self.data.frame(), self.grouped, grouped=True).figure
        first = grouped_bars(chart)[0]
        self.data.analyses = [(GROUPED_GRAPH, self.grouped)]
        cases = (
            ({BAR_STYLES: [first.record({"pattern": "diagonal"})]}, 27),
            ({BAR_STYLES: [first.record({"pattern": "horizontal"})]}, 28),
            ({BAR_STYLES: [first.record({"pattern_color": "#202020"})]}, 28),
            ({"series": {"grouped:1:A": {BAR_APPEARANCE: self.appearance}}}, 28),
        )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "Bars.alab"
            for style, version in cases:
                self.data.graph_styles = {0: style}
                save_project(path, {"Bars": self.data})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], version)
                restored, _ = load_workspace(path)
                self.assertEqual(restored["Bars"].graph_styles[0], style)
        self.assertEqual(BAR_APPEARANCE_VERSION, 28)
        for invalid in ({"pattern_color": "red"}, {"fill": True}, {"other": 1}, {"width": 73}):
            with self.assertRaisesRegex(ValueError, "Invalid bar appearance"):
                validated_style({"series": {"grouped:1:A": {BAR_APPEARANCE: invalid}}})
