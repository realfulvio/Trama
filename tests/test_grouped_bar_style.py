from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
import pandas as pd

from analisi.category_graphs import (BAR_DIRECTION, BARS, DISTANCES, GROUPED_GRAPH, HORIZONTAL_BARS,
                                     PERCENT_STACKED, RIGHT_SIDE, SERIES_SIDE, SERIES_STYLE,
                                     STACKED, SUMMARIES, SYMBOLS, category_graph)
from analisi.data import Dataset, GROUPED_SINGLE_BAR_VERSION, load_workspace, save_project
from analisi.grouped_bar_style import BAR_STYLES, bars_at, grouped_bars, unavailable_bar_styles
from analisi.presentation import apply_style, validated_style
from analisi.repeat_analysis import fit_style
from analisi.worksheet_column_identity import COLUMN_IDS, after_insertion as new_column
from analisi.worksheet_row_identity import ROW_SPANS, after_deletion, after_insertion, after_move


class GroupedBarStyleTests(unittest.TestCase):
    def setUp(self):
        self.data = Dataset(pd.DataFrame({"Visit": ["Same", "Same", "Last"],
                                          "A [1]": [2., 2., 4.], "A [2]": [4., 4., 6.],
                                          "B": [10., 10., 80.]}))
        self.options = {"Variables": ["A [1]", "A [2]", "B"], "Row titles": "Visit", "Graph style": BARS}
        self.color = "#fa7300"

    def plot(self, data=None, **options):
        return category_graph((data or self.data).frame(), {**self.options, **options}, grouped=True)

    @staticmethod
    def bar(figure, row, series):
        return next(bar for bar in grouped_bars(figure) if bar.row == row and bar.series == series)

    def test_only_the_selected_bar_is_formatted_and_legend_keeps_its_series_color(self):
        result = self.plot()
        figure = result.figure
        bar = self.bar(figure, 0, "A")
        other = self.bar(figure, 1, "A")
        colors = [handle.get_facecolor() for handle in figure.axes[0].get_legend().legend_handles]
        baseline = other.patch.get_facecolor()
        record = bar.record({"fill": self.color, "border": "#443322", "width": 2.5, "pattern": "cross"})
        style = {BAR_STYLES: [record]}
        apply_style(figure, style)
        self.assertEqual(bar.patch.get_facecolor(), to_rgba(self.color))
        self.assertEqual(bar.patch.get_edgecolor(), to_rgba("#443322"))
        self.assertEqual((bar.patch.get_hatch(), bar.patch.get_linewidth()), ("xx", 2.5))
        self.assertEqual(other.patch.get_facecolor(), baseline)
        self.assertEqual([handle.get_facecolor() for handle in figure.axes[0].get_legend().legend_handles], colors)
        pd.testing.assert_frame_equal(result.tables["Graph data"], self.plot().tables["Graph data"])

        group = {"series": {"grouped:1:A": {"color": "#245888"}}}
        apply_style(figure, {**group, **style})
        apply_style(figure, group)
        self.assertEqual(bar.patch.get_facecolor(), other.patch.get_facecolor())
        self.assertEqual(bar.patch.get_hatch(), other.patch.get_hatch())
        self.assertEqual(bar.patch.get_linewidth(), other.patch.get_linewidth())

    def test_missing_values_do_not_shift_bars_and_identity_follows_row_changes(self):
        target = self.bar(self.plot().figure, 1, "A")
        style = {BAR_STYLES: [target.record({"fill": self.color})]}
        raw = self.data.raw
        moved = raw.iloc[[1, 0, 2]].reset_index(drop=True)
        moved.attrs[ROW_SPANS] = after_move(raw, 1, 2, 0)
        result = self.plot(Dataset(moved))
        self.assertEqual(self.bar(result.figure, 0, "A").key, target.key)
        apply_style(result.figure, style)
        self.assertEqual(self.bar(result.figure, 0, "A").patch.get_facecolor(), to_rgba(self.color))
        self.assertNotEqual(self.bar(result.figure, 1, "A").patch.get_facecolor(), to_rgba(self.color))

        grown = raw.iloc[[0, 0, 1, 2]].reset_index(drop=True)
        grown.attrs[ROW_SPANS] = after_insertion(raw, 0, 1)
        grown.loc[0, ["A [1]", "A [2]"]] = None
        result = self.plot(Dataset(grown))
        self.assertEqual(self.bar(result.figure, 2, "A").key, target.key)
        apply_style(result.figure, style)
        self.assertEqual(self.bar(result.figure, 2, "A").patch.get_facecolor(), to_rgba(self.color))

        deleted = raw.iloc[[0, 2]].reset_index(drop=True)
        deleted.attrs[ROW_SPANS] = after_deletion(raw, [1])
        result = self.plot(Dataset(deleted))
        apply_style(result.figure, style)
        self.assertEqual(unavailable_bar_styles(result.figure, style[BAR_STYLES]), 1)
        self.assertFalse(any(bar.patch.get_facecolor() == to_rgba(self.color) for bar in grouped_bars(result.figure)))

    def test_new_replicate_with_the_same_name_does_not_inherit_removed_bar_style(self):
        target = self.bar(self.plot().figure, 1, "A")
        style = {BAR_STYLES: [target.record({"fill": self.color})]}
        old = self.data.raw
        frame = old.drop(columns="A [2]")
        frame.attrs[COLUMN_IDS] = {"Visit": "base:1", "A [1]": "base:2", "B": "base:4"}
        inserted = frame.assign(**{"A [2]": old["A [2]"]})
        inserted.attrs[COLUMN_IDS] = new_column(frame, "A [2]")
        figure = self.plot(Dataset(inserted)).figure
        apply_style(figure, style)
        self.assertEqual(unavailable_bar_styles(figure, style[BAR_STYLES]), 1)

    def test_layout_and_axis_changes_keep_the_bar_identity(self):
        target = self.bar(self.plot().figure, 0, "B")
        style = {BAR_STYLES: [target.record({"fill": self.color})]}
        for choices in ({BAR_DIRECTION: HORIZONTAL_BARS}, {"Placement of groups": STACKED},
                        {"Placement of groups": PERCENT_STACKED}, {SERIES_SIDE: {"B": RIGHT_SIDE}},
                        {SERIES_SIDE: {"B": RIGHT_SIDE}, "Right scale": "Log"},
                        {SERIES_STYLE: {"A": SYMBOLS}}):
            with self.subTest(choices=choices):
                result = self.plot(**choices)
                apply_style(result.figure, style)
                bar = self.bar(result.figure, 0, "B")
                self.assertEqual(bar.key, target.key)
                self.assertEqual(bar.patch.get_facecolor(), to_rgba(self.color))
                canvas = FigureCanvasAgg(result.figure)
                canvas.draw()
                x, y = bar.patch.get_transform().transform((.5, .5))
                matches = bars_at(MouseEvent("button_press_event", canvas, x, y, button=3))
                self.assertIn(bar, matches)

    def test_summary_bar_identity_uses_its_estimate_column(self):
        data = Dataset(pd.DataFrame({"Visit": ["1", "2"], "A [Mean]": [4., 8.], "A [Minus]": [1., 2.],
                                     "A [Plus]": [2., 3.]}))
        source = {"Input": SUMMARIES, "Variables": list(data.raw.columns[1:])}
        old = self.bar(self.plot(data, **source, **{"Summary error": DISTANCES}).figure, 0, "A")
        new = self.bar(self.plot(data, **source, **{"Summary error": "None"}).figure, 0, "A")
        self.assertEqual(old.key, new.key)
        self.assertEqual(new.columns, ("base:2",))

    def test_styles_round_trip_vector_export_and_stay_with_the_source_worksheet(self):
        chart = self.plot()
        records = [self.bar(chart.figure, 1, "B").record({"fill": self.color, "pattern": "diagonal"})]
        style = {BAR_STYLES: records, "title": "Visits"}
        self.data.analyses = [(GROUPED_GRAPH, self.options)]
        self.data.graph_styles = {0: style}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "Visit.alab"
            save_project(path, {"Visits": self.data})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], GROUPED_SINGLE_BAR_VERSION)
            restored, _ = load_workspace(path)
        restored = restored["Visits"]
        self.assertEqual(restored.graph_styles[0], style)
        chart = self.plot(restored)
        apply_style(chart.figure, restored.graph_styles[0])
        output = BytesIO()
        chart.figure.savefig(output, format="svg")
        self.assertIn(self.color.encode(), output.getvalue())
        self.assertIn(b"<pattern", output.getvalue())
        self.assertNotIn(b"<image", output.getvalue())
        self.assertEqual(fit_style(chart.figure, style), ({"title": "Visits"}, True))

    def test_style_validation_rejects_duplicate_targets_and_invalid_values(self):
        record = self.bar(self.plot().figure, 0, "A").record({"fill": "none"})
        broken = ([record, record], [{**record, "row_token": "row:0"}], [{**record, "columns": ["name:A"]}],
                  [{**record, "columns": ["base:4", "base:2"]}])
        for records in broken:
            with self.subTest(records=records), self.assertRaises(ValueError):
                validated_style({BAR_STYLES: records})
        for style in ({"fill": "#ab1"}, {"width": float("inf")}, {"width": True},
                      {"pattern": []}, {"extra": "red"}, {}):
            with self.subTest(style=style), self.assertRaises(ValueError):
                validated_style({BAR_STYLES: [{**deepcopy(record), "style": style}]})
