"""Formatting of single points: engine, identity of a point, validation and exports (no Qt)."""
from io import BytesIO
import json
from pathlib import Path
import re
import unittest

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analisi import point_style as ps
from analisi.i18n import set_language, tr
from analisi.point_style_text import EN, IT
from analisi.presentation import (apply_style, capture_defaults, compose_layout, graph_series, validate_graph_style,
                                  validated_style)
from analisi.workbench import analyse
from analisi.xy_series import xy_series

CASES = json.loads((Path(__file__).resolve().parent / "data" / "point_style" / "casi.json").read_text("utf-8"))
SCATTER = "Scatter / confidence ellipse"
COLOR = CASES["stylesheet"]["color"]


def casi_frame(data=None):
    frame = pd.DataFrame(data if data is not None else CASES["data"])
    frame["Y"] = pd.to_numeric(frame["Y"])
    return frame


def scatter(frame=None, group="Group"):
    frame = casi_frame() if frame is None else frame
    options = {"X": "X", "Y": "Y", "Group": group}
    figure = analyse(SCATTER, frame, options).figure
    capture_defaults(figure)
    return figure


def series_of(figure, key):
    return {item.key: item for item in graph_series(figure.axes[0])}[key]


def record(figure, key, row, **fields):
    """The record that styles worksheet row ``row`` (1-based) of the series ``key``."""
    series = series_of(figure, key)
    pmap = ps.point_map(series.artist)
    index = int(np.flatnonzero(pmap.rows == row)[0])
    return {"series": key, "source": ps.source_record(pmap, index), **fields}


def png(figure, dpi=100):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi)
    return buffer.getvalue()


def pixels_of(data, color):
    image = plt.imread(BytesIO(data))
    target = np.array(matplotlib.colors.to_rgb(color))
    return int(np.sum(np.all(np.abs(image[..., :3] - target) < 0.02, axis=-1)))


def overlays(figure, key=None):
    """The marker lines that draw the styled points (optionally of one series)."""
    prefix = ps.GID_PREFIX + (key + ":" if key else "")
    return [child for child in figure.axes[0].get_children() if str(child.get_gid() or "").startswith(prefix)]


def hidden(artist):
    """The vertices a scatter collection leaves to the extra markers."""
    return list(np.flatnonzero(np.isnan(np.asarray(artist.get_offsets(), dtype=float)).any(axis=1)))


def legend_state(figure):
    legend = figure.axes[0].get_legend()
    handles = []
    for handle in legend.legend_handles:
        faces = handle.get_facecolor() if hasattr(handle, "get_facecolor") else None
        handles.append((type(handle).__name__, None if faces is None else np.round(np.asarray(faces), 6).tolist()))
    return [text.get_text() for text in legend.get_texts()], handles


class CasesTests(unittest.TestCase):
    """The acceptance cases of the specification: rows 1 and 2 are identical, only the second is formatted."""

    def setUp(self):
        self.figure = scatter()
        self.key = "scatter:1:C"
        self.before = {"limits": (self.figure.axes[0].get_xlim(), self.figure.axes[0].get_ylim()),
                       "legend": legend_state(self.figure),
                       "offsets": [np.array(item.artist.get_offsets()) for item in graph_series(self.figure.axes[0])],
                       "png": png(self.figure)}
        self.record = record(self.figure, self.key, CASES["stylesheet"]["source_row_1_based"],
                             color=COLOR, marker="s", marker_size=CASES["stylesheet"]["size_pt"])

    def test_four_observations_and_original_legend(self):
        counts = [len(ps.drawn_vertices(item.artist)) for item in graph_series(self.figure.axes[0])]
        self.assertEqual(sum(counts), CASES["expected"]["observations"])
        self.assertEqual(self.before["legend"][0], CASES["expected"]["original_legend"])

    def test_only_the_second_identical_row_changes(self):
        apply_style(self.figure, {ps.POINTS: [self.record]})
        status = ps.point_statuses(self.figure)
        self.assertEqual([(item.state, item.index, item.row) for item in status], [("ok", 1, 2)])
        artist = series_of(self.figure, self.key).artist
        self.assertEqual((len(artist.get_facecolor()), len(artist.get_sizes()), len(artist.get_paths())), (1, 1, 1))
        self.assertEqual(hidden(artist), [1])  # the series draws rows 1 and 3; the extra marker draws row 2
        offsets = np.array(artist.get_offsets())
        self.assertTrue(np.array_equal(offsets[[0, 2]], self.before["offsets"][0][[0, 2]]))
        pmap = ps.point_map(artist)  # the data and its order are intact
        self.assertEqual((list(pmap.rows), list(pmap.x), list(pmap.y)), ([1, 2, 3], [1.0, 1.0, 2.0], [2.0, 2.0, 4.0]))
        (extra,) = overlays(self.figure, self.key)
        self.assertEqual((extra.get_marker(), extra.get_markersize()), ("s", 9.0))
        self.assertEqual(matplotlib.colors.to_hex(extra.get_markerfacecolor()), COLOR)
        self.assertEqual((list(extra.get_xdata()), list(extra.get_ydata())), ([1.0], [2.0]))
        self.assertEqual(ps.describe_point(pmap, 0), "Row 1 · X = 1 · Y = 2")

    def test_blank_fields_follow_the_series_whatever_it_looks_like(self):
        series_style = {self.key: {"color": "#112233", "marker": "^", "marker_size": 12}}
        only_color = dict(self.record)
        only_color.pop("marker"), only_color.pop("marker_size")
        apply_style(self.figure, {"series": series_style, ps.POINTS: [only_color]})
        (extra,) = overlays(self.figure, self.key)
        self.assertEqual((extra.get_marker(), extra.get_markersize()), ("^", 12.0))
        self.assertEqual(matplotlib.colors.to_hex(extra.get_markerfacecolor()), COLOR)
        only_marker = {key: value for key, value in self.record.items() if key not in {"color", "marker_size"}}
        apply_style(self.figure, {"series": series_style, ps.POINTS: [only_marker]})
        (extra,) = overlays(self.figure, self.key)
        self.assertEqual((extra.get_marker(), extra.get_markersize()), ("s", 12.0))
        self.assertEqual(matplotlib.colors.to_hex(extra.get_markerfacecolor()), "#112233")
        only_size = {key: value for key, value in self.record.items() if key not in {"color", "marker"}}
        apply_style(self.figure, {ps.POINTS: [only_size]})
        (extra,) = overlays(self.figure, self.key)
        self.assertEqual((extra.get_marker(), extra.get_markersize()), ("o", 9.0))
        self.assertEqual(matplotlib.colors.to_hex(extra.get_markerfacecolor()), "#1f77b4")

    def test_every_symbol_draws_and_a_tight_export_still_works(self):
        for code in ps.MARKER_CODES:
            with self.subTest(marker=code):
                apply_style(self.figure, {ps.POINTS: [dict(self.record, marker=code)]})
                (extra,) = overlays(self.figure, self.key)
                self.assertEqual(extra.get_marker(), code)
                buffer = BytesIO()
                self.figure.savefig(buffer, format="png", dpi=80, bbox_inches="tight")
                self.assertGreater(len(buffer.getvalue()), 1000)
        apply_style(self.figure, {ps.POINTS: [self.record]})
        self.assertEqual(hidden(series_of(self.figure, self.key).artist), [1])  # NaN offsets did not break the export

    def test_legend_and_limits_do_not_change(self):
        apply_style(self.figure, {ps.POINTS: [self.record], "legend": "lower right"})
        texts, handles = legend_state(self.figure)
        self.assertEqual(texts, ["C", "T"])
        apply_style(self.figure, {"legend": "lower right"})
        self.assertEqual(legend_state(self.figure), (texts, handles))  # same handles as without any point style
        apply_style(self.figure, {ps.POINTS: [self.record]})
        axes = self.figure.axes[0]
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), self.before["limits"])
        self.assertEqual(legend_state(self.figure), self.before["legend"])

    def test_adverse_insertion_of_an_identical_row_suspends_the_style(self):
        apply_style(self.figure, {ps.POINTS: [self.record]})
        rows = list(CASES["data"])
        position = CASES["after_ambiguous_insertion"]["insert_at_1_based"] - 1
        rows.insert(position, dict(CASES["after_ambiguous_insertion"]["data"]))
        changed = scatter(casi_frame(rows))
        apply_style(changed, {ps.POINTS: [self.record]})
        (status,) = ps.point_statuses(changed)
        self.assertEqual((status.state, status.reason), ("suspended", "ambiguous"))
        self.assertEqual(overlays(changed), [])  # no point took the style
        self.assertEqual(hidden(series_of(changed, self.key).artist), [])
        self.assertEqual(png(changed), png(scatter(casi_frame(rows))))  # drawn exactly as without the style
        self.assertIn("not given to another row", ps.reason_text(status, self.record))
        self.assertIn("Dopo la modifica", self._italian(ps.reason_text, status, self.record))

    @staticmethod
    def _italian(function, *args):
        set_language("it")
        try:
            return function(*args)
        finally:
            set_language("en")

    def test_insertion_of_another_row_keeps_the_style_on_the_same_row(self):
        rows = list(CASES["data"])
        rows.insert(0, {"X": 9, "Y": 9, "Group": "T"})
        changed = scatter(casi_frame(rows))
        apply_style(changed, {ps.POINTS: [self.record]})
        (status,) = ps.point_statuses(changed)
        self.assertEqual(status.state, "ok")
        artist = series_of(changed, self.key).artist
        pmap = ps.point_map(artist)
        self.assertEqual(int(pmap.rows[status.index]), 3)  # the old row 2 is row 3 now
        self.assertEqual(hidden(artist), [status.index])
        (extra,) = overlays(changed, self.key)
        self.assertEqual(matplotlib.colors.to_hex(extra.get_markerfacecolor()), COLOR)

    def test_exclusion_waits_and_the_style_comes_back(self):
        masked = casi_frame()
        masked.loc[1, "Y"] = np.nan  # what Dataset.frame(mask_excluded=True) gives for an excluded cell
        changed = scatter(masked)
        apply_style(changed, {ps.POINTS: [self.record]})
        (status,) = ps.point_statuses(changed)
        self.assertEqual((status.state, status.reason), ("hidden", "not_drawn"))
        self.assertIsNone(ps.point_styles_status(changed, [self.record]))  # waiting is not a warning
        back = scatter()
        apply_style(back, {ps.POINTS: [self.record]})
        self.assertEqual(ps.point_statuses(back)[0].state, "ok")

    def test_edit_follows_the_row(self):
        rows = [dict(row) for row in CASES["data"]]
        rows[1]["Y"] = 3  # row 2 edited: the style stays on row 2
        changed = scatter(casi_frame(rows))
        apply_style(changed, {ps.POINTS: [self.record]})
        (status,) = ps.point_statuses(changed)
        self.assertEqual((status.state, status.row, status.index), ("ok", 2, 1))

    def test_other_rows_deleted_or_moved(self):
        rows = [dict(row) for row in CASES["data"]]
        del rows[2]  # an unrelated row goes: still unique
        changed = scatter(casi_frame(rows))
        apply_style(changed, {ps.POINTS: [self.record]})
        self.assertEqual(ps.point_statuses(changed)[0].state, "ok")
        rows = [dict(row) for row in CASES["data"]]
        del rows[0]  # one of the two identical rows goes: which copy is left is unknown
        changed = scatter(casi_frame(rows))
        apply_style(changed, {ps.POINTS: [self.record]})
        self.assertEqual(ps.point_statuses(changed)[0].state, "suspended")

    def test_recipe_change_suspends(self):
        changed = scatter(group=None)
        apply_style(changed, {ps.POINTS: [self.record]})
        (status,) = ps.point_statuses(changed)
        self.assertEqual((status.state, status.reason), ("suspended", "no_series"))
        self.assertEqual(len(graph_series(changed.axes[0])), 1)
        ungrouped_key = graph_series(changed.axes[0])[0].key
        moved = dict(self.record, series=ungrouped_key)
        apply_style(changed, {ps.POINTS: [moved]})
        self.assertEqual(ps.point_statuses(changed)[0].reason, "recipe")

    def test_style_never_reaches_the_other_series(self):
        apply_style(self.figure, {ps.POINTS: [self.record]})
        other = series_of(self.figure, "scatter:1:T").artist
        self.assertEqual((hidden(other), len(other.get_facecolor()), len(other.get_paths())), ([], 1, 1))
        self.assertEqual(overlays(self.figure, "scatter:1:T"), [])
        self.assertEqual(len(overlays(self.figure, self.key)), 1)

    def test_reset_returns_the_exact_original_rendering(self):
        apply_style(self.figure, {ps.POINTS: [self.record]})
        self.assertNotEqual(png(self.figure), self.before["png"])
        apply_style(self.figure, {})
        self.assertEqual(png(self.figure), self.before["png"])
        self.assertEqual(ps.point_statuses(self.figure), [])

    def test_exports_show_the_chosen_color_without_the_indicator(self):
        series = series_of(self.figure, self.key)
        apply_style(self.figure, {ps.POINTS: [self.record]})
        plain = png(self.figure)
        self.assertGreater(pixels_of(plain, COLOR), 20)
        self.assertEqual(pixels_of(self.before["png"], COLOR), 0)
        ps.show_indicator(series, 1)
        self.assertEqual(png(self.figure), plain)  # the ring is on screen only
        buffer = BytesIO()
        self.figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().decode("utf-8")
        self.assertIn(COLOR, svg)
        self.assertNotIn(ps.INDICATOR_COLOR, svg)
        with matplotlib.rc_context({"pdf.compression": 0}):
            buffer = BytesIO()
            self.figure.savefig(buffer, format="pdf")
        wanted = np.array(matplotlib.colors.to_rgb(COLOR))
        fills = re.findall(rb"([0-9.]+) ([0-9.]+) ([0-9.]+) rg", buffer.getvalue())
        self.assertTrue(any(np.allclose(np.array(fill, dtype=float), wanted, atol=1e-3) for fill in fills))
        ps.clear_indicator(self.figure)

    def test_layout_shows_the_style_and_not_the_ring(self):
        series = series_of(self.figure, self.key)
        apply_style(self.figure, {ps.POINTS: [self.record]})
        ps.show_indicator(series, 1)
        layout = compose_layout("Layout", 1, [self.figure])
        self.assertGreater(pixels_of(png(layout, 150), COLOR), 5)
        self.assertEqual(pixels_of(png(layout, 150), ps.INDICATOR_COLOR), 0)
        ps.clear_indicator(self.figure)

    def test_the_ring_and_the_extra_marker_sit_on_the_point(self):
        series = series_of(self.figure, self.key)
        apply_style(self.figure, {ps.POINTS: [self.record]})
        axes = self.figure.axes[0]
        ring = ps.show_indicator(series, 1)
        (extra,) = overlays(self.figure, self.key)
        expected = axes.transData.transform((1.0, 2.0))
        for line in (ring, extra):
            placed = line.get_transform().transform(np.column_stack([line.get_xdata(), line.get_ydata()]))
            self.assertTrue(np.allclose(placed[0], expected), line.get_gid())
        ps.clear_indicator(self.figure)

    def test_indicator_stays_out_of_series_and_limits(self):
        series = series_of(self.figure, self.key)
        before = (self.figure.axes[0].get_xlim(), self.figure.axes[0].get_ylim())
        ps.show_indicator(series, 1)
        axes = self.figure.axes[0]
        axes.relim()
        axes.autoscale_view()
        self.assertEqual([item.key for item in graph_series(axes)], ["scatter:1:C", "scatter:1:T"])
        self.assertEqual(len(axes.get_legend().get_texts()), 2)
        self.assertEqual((axes.get_xlim(), axes.get_ylim()), before)
        apply_style(self.figure, {ps.POINTS: [self.record], "xlabel": "Dose"})
        ps.clear_indicator(self.figure)
        self.assertEqual([artist.get_gid() for artist in axes.get_children() if artist.get_gid() == ps.INDICATOR_GID], [])


class XYTests(unittest.TestCase):
    def setUp(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4, 5, 6], "A": [2, 4, 3, 6, 5, 7.0], "B": [1, 2, 2, 3, 4, np.nan]})
        options = {"X": "X", "Y columns": ["A", "B"], "Series style": {"A": "Line and points", "B": "Points"}}
        self.figure = xy_series(frame, options).figure
        capture_defaults(self.figure)
        self.line = series_of(self.figure, "xy:1:A")
        self.dots = series_of(self.figure, "xy:1:B")

    def test_line_keeps_its_stroke_and_the_point_is_drawn_once(self):
        before = (self.line.artist.get_xdata().copy(), self.line.artist.get_ydata().copy(),
                  self.line.artist.get_linewidth(), self.line.artist.get_color())
        apply_style(self.figure, {ps.POINTS: [record(self.figure, "xy:1:A", 3, color="#00aa00", marker="D",
                                                     marker_size=12)]})
        artist = self.line.artist
        self.assertTrue(np.array_equal(artist.get_xdata(), before[0]))
        self.assertTrue(np.array_equal(artist.get_ydata(), before[1]))
        self.assertEqual((artist.get_linewidth(), artist.get_color()), before[2:])
        mask = artist.get_markevery()
        self.assertEqual(list(np.flatnonzero(~np.asarray(mask))), [2])  # the plain marker of row 3 is off
        overlays = [child for child in self.figure.axes[0].get_children()
                    if str(child.get_gid() or "").startswith(ps.GID_PREFIX)]
        self.assertEqual(len(overlays), 1)
        self.assertEqual((overlays[0].get_marker(), overlays[0].get_markersize()), ("D", 12.0))
        self.assertEqual([text.get_text() for text in self.figure.axes[0].get_legend().get_texts()], ["A", "B"])
        apply_style(self.figure, {})
        self.assertIsNone(artist.get_markevery())
        self.assertFalse([child for child in self.figure.axes[0].get_children()
                          if str(child.get_gid() or "").startswith(ps.GID_PREFIX)])

    def test_missing_value_has_no_point_and_the_style_waits(self):
        pmap = ps.point_map(self.dots.artist)
        self.assertFalse(pmap.drawn[5])
        self.assertEqual(len(ps.drawn_vertices(self.dots.artist)), 5)
        source = ps.source_record(ps.point_map(self.line.artist), 0)
        source["recipe"] = list(pmap.recipe)
        lost = {"series": "xy:1:B", "source": dict(source, row=6, x=6.0, y=7.0, copy=1, copies=1), "color": "#00aa00"}
        apply_style(self.figure, {ps.POINTS: [lost]})
        self.assertEqual(ps.point_statuses(self.figure)[0].state, "hidden")

    def test_series_without_symbols_says_why(self):
        figure = xy_series(pd.DataFrame({"X": [1, 2, 3], "A": [1, 2, 3.0]}),
                           {"X": "X", "Y columns": ["A"], "Series style": {"A": "Line"}}).figure
        capture_defaults(figure)
        series = graph_series(figure.axes[0])[0]
        self.assertEqual(ps.support_reason(series), "no_symbols")
        self.assertIn("without symbols", ps.reason_text(ps.PointStatus("suspended", None, "no_symbols")))

    def test_unsupported_graphs_have_no_point_map(self):
        figure = analyse("Histogram", pd.DataFrame({"Y": [1, 2, 3, 4, 5.0]}), {"Response": "Y", "Bins": 3}).figure
        capture_defaults(figure)
        for item in graph_series(figure.axes[0]):
            self.assertNotIn(item.kind, {"scatter", "xy"})
            self.assertIsNone(ps.point_map(item.artist))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.figure = scatter()
        self.good = record(self.figure, "scatter:1:C", 2, color="#ac4320", marker="s", marker_size=9)

    def test_a_valid_record_is_kept_in_the_shared_style_model(self):
        style = validated_style({ps.POINTS: [self.good]})
        self.assertEqual(style[ps.POINTS], [self.good])
        validate_graph_style(self.figure.axes[0], {ps.POINTS: [self.good]})

    def test_rejected_records(self):
        bad = [
            dict(self.good, color="not a color"),
            dict(self.good, marker="none"),
            dict(self.good, marker_size=0),
            dict(self.good, marker_size=500),
            dict(self.good, marker_size=float("nan")),
            dict(self.good, extra=1),
            {key: value for key, value in self.good.items() if key not in {"color", "marker", "marker_size"}},
            dict(self.good, series="line:1:A"),
            dict(self.good, source=dict(self.good["source"], row=0)),
            dict(self.good, source=dict(self.good["source"], copy=5)),
            dict(self.good, source={**self.good["source"], "unknown": 1}),
            dict(self.good, source=dict(self.good["source"], recipe=["X"])),
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validated_style({ps.POINTS: [item]})
        with self.assertRaises(ValueError):
            validated_style({ps.POINTS: [self.good, dict(self.good)]})  # the same point twice
        with self.assertRaises(ValueError):
            validated_style({ps.POINTS: "red"})

    def test_at_most_256_points(self):
        many = []
        for row in range(1, 258):
            source = dict(self.good["source"], row=row, rows=300, x=float(row), y=1.0, copy=1, copies=1)
            many.append(dict(self.good, source=source))
        validated_style({ps.POINTS: many[:256]})
        with self.assertRaises(ValueError):
            validated_style({ps.POINTS: many})

    def test_old_styles_open_with_the_previous_look(self):
        apply_style(self.figure, {"title": "Old file", "series": {"scatter:1:C": {"color": "#112233"}}})
        self.assertEqual(ps.point_statuses(self.figure), [])
        self.assertEqual(overlays(self.figure), [])
        self.assertEqual(ps.points_of_style({"title": "x"}), [])

    def test_with_point_edits_in_place_and_removes_empty_records(self):
        apply_style(self.figure, {ps.POINTS: [self.good]})
        series = series_of(self.figure, "scatter:1:C")
        statuses = ps.point_statuses(self.figure)
        pmap = ps.point_map(series.artist)
        records = ps.with_point([self.good], statuses, series.key, pmap, 1, color="#00aa00")
        self.assertEqual((len(records), records[0]["color"], records[0]["marker"]), (1, "#00aa00", "s"))
        records = ps.with_point(records, statuses, series.key, pmap, 1, color=None, marker=None, marker_size=None)
        self.assertEqual(records, [])
        added = ps.with_point([], [], series.key, pmap, 0, color="#00aa00")
        self.assertEqual(added[0]["source"]["row"], 1)
        self.assertEqual(ps.strip_points({ps.POINTS: added, "title": "x"}), {"title": "x"})


class TextTests(unittest.TestCase):
    def test_english_and_italian_have_the_same_keys(self):
        self.assertEqual(EN.keys(), IT.keys())
        for key, text in IT.items():
            with self.subTest(key=key):
                self.assertTrue(text)

    def test_engine_messages_are_translated(self):
        self.addCleanup(set_language, "en")
        set_language("it")
        self.assertEqual(ps.translate_point_error(ValueError("A point is formatted twice.")),
                         "Un punto è formattato due volte.")
        self.assertEqual(tr("point.section"), "Punto singolo")
        set_language("en")
        self.assertEqual(tr("point.section"), "Single point")


if __name__ == "__main__":
    unittest.main()
