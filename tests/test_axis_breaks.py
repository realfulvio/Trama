"""Axis breaks: record rules, panel geometry, exact limits and ticks, symbols, SVG ids, restore and exports."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import warnings
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator

from analisi import axis_breaks as ab
from analisi.axis_breaks import (AxisBreakError, axis_breaks_reason, explicit_ticks, normalise_axis_breaks,
                                 plot_fraction_problem, segment_axes, segment_lengths, segment_ticks)
from analisi.data import Dataset, load_project, save_project
from analisi.figure_export import export_figure
from analisi.field_error import FieldError
from analisi.layout_svg import export_layout_svg
from analisi.presentation import apply_style, compose_layout, validate_graph_style, validated_style
from analisi.xy_errors import xy_errors
from analisi.xy_series import xy_series

FRAME = pd.DataFrame({
    "t": [0, 1, 2, 3, 4, 6, 7, 10, 11, 12, 18, 20, 22],
    "a": [1, 2, 2.7, 3.6, 4.5, 11, 15, 21, 22, 24, 27, 29, 31],
    "b": [2, 5, 8, np.nan, 9, 12, 14, 24, 27, 30, 25, 28, 34],
    "down": [.2, .2, .4, .2, .3, .4, .5, .2, .5, .2, .6, .8, 1.2],
    "up": [.6, .4, .7, .6, .8, .6, .3, .6, .7, .4, .9, .7, 1.6],
})
SERIES = {"X": "t", "Y columns": ["a", "b"], "Series style": {"a": "Line and points", "b": "Points"}}
ERRORS = {"X": "t", "Y": "a", "Y lower error": "down", "Y upper error": "up", "Y error values": "Distances"}
X_BREAKS = {"axis": "x", "gap": 0.04, "segments": [
    {"low": 0, "high": 4, "share": 35, "major_step": 2},
    {"low": 10, "high": 12, "share": 30, "major_step": 1},
    {"low": 18, "high": 22, "share": 35, "major_step": 2}]}
Y_BREAKS = {"axis": "y", "gap": 0.05, "segments": [
    {"low": 0, "high": 10, "share": 42, "major_step": 5},
    {"low": 20, "high": 36, "share": 58, "major_step": 4}]}


def _series(options=None):
    return xy_series(FRAME, options or SERIES).figure


def _draw(figure):
    FigureCanvasAgg(figure).draw()
    return figure


def _geometry(figure, axis):
    boxes = [panel.get_position() for panel in segment_axes(figure)]
    start, end, size = ("x0", "x1", "width") if axis == "x" else ("y0", "y1", "height")
    span = getattr(boxes[-1], end) - getattr(boxes[0], start)
    shares = [getattr(box, size) / span for box in boxes]
    gaps = [(getattr(right, start) - getattr(left, end)) / span for left, right in zip(boxes, boxes[1:])]
    return shares, gaps


class RecordTests(unittest.TestCase):
    def test_canonical_copy_and_off_state(self):
        self.assertEqual(normalise_axis_breaks(None), {})
        self.assertEqual(normalise_axis_breaks({}), {})
        record = deepcopy(X_BREAKS)
        del record["segments"][0]["major_step"]
        canonical = normalise_axis_breaks(record)
        self.assertIsNone(canonical["segments"][0]["major_step"])
        self.assertEqual(canonical["segments"][1], X_BREAKS["segments"][1])
        self.assertNotIn("major_step", record["segments"][0])

    def test_lengths_follow_the_formula(self):
        self.assertEqual(np.round(segment_lengths(X_BREAKS), 12).tolist(), [.322, .276, .322])
        self.assertAlmostEqual(sum(segment_lengths(Y_BREAKS)) + .05, 1)

    def test_every_invalid_record_names_its_row_and_field(self):
        def bad(change, field, row=None):
            record = deepcopy(X_BREAKS)
            change(record)
            with self.assertRaises(AxisBreakError) as caught:
                normalise_axis_breaks(record)
            self.assertEqual(caught.exception.field, field, caught.exception)
            self.assertEqual(caught.exception.row, row)
            self.assertIsInstance(caught.exception, FieldError)

        bad(lambda r: r["segments"][1].update(low=3), "segments.1.low", 1)
        bad(lambda r: r["segments"][1].update(low=4), "segments.1.low", 1)
        bad(lambda r: r["segments"][2].update(low=12, high=12), "segments.2.high", 2)
        bad(lambda r: r["segments"][0].update(high=-1), "segments.0.high", 0)
        bad(lambda r: r["segments"][0].update(low=float("nan")), "segments.0.low", 0)
        bad(lambda r: r["segments"][0].update(high=float("inf")), "segments.0.high", 0)
        bad(lambda r: r["segments"][0].update(low=True), "segments.0.low", 0)
        bad(lambda r: r["segments"][0].update(low="0"), "segments.0.low", 0)
        bad(lambda r: r["segments"][0].update(share=0), "segments.0.share", 0)
        bad(lambda r: r["segments"][2].update(share=float("nan")), "segments.2.share", 2)
        bad(lambda r: r["segments"][2].update(share=40), "segments.2.share", 2)
        bad(lambda r: r["segments"][1].update(major_step=0), "segments.1.major_step", 1)
        bad(lambda r: r["segments"][1].update(major_step=-1), "segments.1.major_step", 1)
        bad(lambda r: r["segments"][1].update(major_step=float("nan")), "segments.1.major_step", 1)
        bad(lambda r: r["segments"][1].update(major_step=2 / 250), "segments.1.major_step", 1)
        bad(lambda r: r["segments"][1].update(extra=1), "segments.1.low", 1)
        bad(lambda r: r["segments"][1].pop("share"), "segments.1.low", 1)
        bad(lambda r: r.update(gap=0.2), "gap")
        bad(lambda r: r.update(gap=0), "gap")
        bad(lambda r: r.update(gap="0.04"), "gap")
        bad(lambda r: r.update(axis="z"), "axis")
        bad(lambda r: r.update(segments=r["segments"][:1]), "segments")
        bad(lambda r: r.update(segments=r["segments"] * 2), "segments")
        bad(lambda r: r.update(unknown=1), "segments")
        with self.assertRaises(AxisBreakError):
            normalise_axis_breaks([])

    def test_limits_of_gap_and_ticks_are_accepted(self):
        for gap in (0.01, 0.10):
            normalise_axis_breaks({**X_BREAKS, "gap": gap})
        record = deepcopy(X_BREAKS)
        record["segments"][0]["major_step"] = 4 / 199
        normalise_axis_breaks(record)  # exactly 200 ticks
        shares = deepcopy(X_BREAKS)
        shares["segments"][0]["share"], shares["segments"][1]["share"] = 35.000000001, 29.999999999
        normalise_axis_breaks(shares)

    def test_explicit_ticks_start_at_low_and_include_high_on_the_grid(self):
        self.assertEqual(explicit_ticks(0, 4, 2), [0, 2, 4])
        self.assertEqual(explicit_ticks(10, 13, 2), [10, 12])
        self.assertEqual(explicit_ticks(0, 1, .1)[-1], 1)
        self.assertEqual(len(explicit_ticks(0, 1, .1)), 11)
        self.assertEqual(explicit_ticks(-2.5, 2.5, 2.5), [-2.5, 0, 2.5])

    def test_automatic_ticks_stay_inside_the_segment(self):
        for low, high in ((0, 4), (18, 22), (0.001, 0.0034), (-7, 130)):
            ticks = segment_ticks({"low": low, "high": high, "share": 35, "major_step": None})
            self.assertGreaterEqual(len(ticks), 2)
            self.assertTrue(all(low <= tick <= high for tick in ticks), ticks)

    def test_validated_style_accepts_the_section_without_rewriting_it(self):
        style = {"axis_breaks": deepcopy(X_BREAKS)}
        self.assertIs(validated_style(style), style)
        self.assertEqual(style["axis_breaks"], X_BREAKS)
        validated_style({"axis_breaks": {}})
        with self.assertRaises(FieldError):
            validated_style({"axis_breaks": {**X_BREAKS, "gap": 1}})

    def test_plot_fractions_cannot_share_a_graph_with_breaks(self):
        shape = {"id": "a0000000-0000-4000-8000-000000000001", "kind": "line", "units": "axes",
                 "points": [[.1, .1], [.2, .2]]}
        self.assertIn("plot fractions", plot_fraction_problem({"axis_breaks": X_BREAKS, "shapes": [shape]}))
        self.assertIsNone(plot_fraction_problem({"shapes": [shape]}))
        note = {"text": "n", "position": [.5, .5], "units": "axes", "align": "left", "size": 9, "color": "#000000"}
        self.assertIsNotNone(plot_fraction_problem({"axis_breaks": X_BREAKS, "annotations": [note]}))
        self.assertIsNone(plot_fraction_problem({"axis_breaks": X_BREAKS,
                                                 "annotations": [{**note, "units": "data"}]}))


class GeometryTests(unittest.TestCase):
    def test_three_x_panels_have_exact_limits_ticks_shares_and_gaps(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        panels = segment_axes(figure)
        self.assertEqual(figure.axes, panels)
        self.assertIs(panels[0], figure.axes[0])
        np.testing.assert_allclose([panel.get_xlim() for panel in panels], [[0, 4], [10, 12], [18, 22]], rtol=0, atol=1e-12)
        self.assertEqual([panel.get_xticks().tolist() for panel in panels], [[0, 2, 4], [10, 11, 12], [18, 20, 22]])
        for panel in panels[1:]:
            self.assertEqual(panel.get_ylim(), panels[0].get_ylim())
        shares, gaps = _geometry(figure, "x")
        np.testing.assert_allclose(shares, [.322, .276, .322], rtol=0, atol=1e-6)
        np.testing.assert_allclose(gaps, [.04, .04], rtol=0, atol=1e-6)

    def test_two_y_panels_run_bottom_to_top(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(Y_BREAKS)})
        _draw(figure)
        panels = segment_axes(figure)
        self.assertEqual(len(panels), 2)
        self.assertLess(panels[0].get_position().y0, panels[1].get_position().y0)
        np.testing.assert_allclose([panel.get_ylim() for panel in panels], [[0, 10], [20, 36]], rtol=0, atol=1e-12)
        self.assertEqual([panel.get_yticks().tolist() for panel in panels], [[0, 5, 10], [20, 24, 28, 32, 36]])
        self.assertEqual(panels[0].get_xlim(), panels[1].get_xlim())
        shares, gaps = _geometry(figure, "y")
        np.testing.assert_allclose(shares, [.399, .551], rtol=0, atol=1e-6)
        np.testing.assert_allclose(gaps, [.05], rtol=0, atol=1e-6)

    def test_shares_and_gaps_hold_at_every_figure_size(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        for size in ((4, 3), (8, 5), (12, 6), (3.2, 2.4)):
            figure.set_size_inches(*size)
            _draw(figure)
            shares, gaps = _geometry(figure, "x")
            np.testing.assert_allclose(shares, [.322, .276, .322], rtol=0, atol=1e-6, err_msg=str(size))
            np.testing.assert_allclose(gaps, [.04, .04], rtol=0, atol=1e-6, err_msg=str(size))

    def test_tick_labels_do_not_overlap_across_a_narrow_gap(self):
        for dimension, breaks in (("x", X_BREAKS), ("y", Y_BREAKS)):
            with self.subTest(dimension=dimension):
                figure = _series()
                figure.set_size_inches(3.2, 2.4)
                record = dict(deepcopy(breaks), gap=0.01)
                axis_name = dimension + "axis"
                bound = ("x1", "x0") if dimension == "x" else ("y1", "y0")
                _draw(figure)
                original_axis = getattr(figure.axes[0], axis_name)
                attribute = "get_ha" if dimension == "x" else "get_va"
                alignments = [getattr(tick.label1, attribute)() for tick in original_axis.get_major_ticks()]
                apply_style(figure, {"axis_breaks": record})
                _draw(figure)
                panels = segment_axes(figure)
                for lower, upper in zip(panels, panels[1:]):
                    last = getattr(lower, axis_name).get_major_ticks()[-1].label1.get_window_extent()
                    first = getattr(upper, axis_name).get_major_ticks()[0].label1.get_window_extent()
                    self.assertLessEqual(getattr(last, bound[0]), getattr(first, bound[1]))
                apply_style(figure, {})
                _draw(figure)
                self.assertEqual([getattr(tick.label1, attribute)() for tick in original_axis.get_major_ticks()],
                                 alignments)

    def test_the_layout_is_really_laid_out(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _draw(figure)
        first = segment_axes(figure)[0].get_position()
        self.assertGreater(first.x0, .04)  # room for the Y tick labels
        self.assertGreater(first.y0, .08)  # room for the X tick labels and the name

    def test_explicit_ticks_are_exact_and_automatic_ticks_stay_inside(self):
        figure = _series()
        record = deepcopy(X_BREAKS)
        record["segments"][1]["major_step"] = None
        apply_style(figure, {"axis_breaks": record})
        _draw(figure)
        for panel in segment_axes(figure):
            low, high = panel.get_xlim()
            self.assertTrue(all(low <= tick <= high for tick in panel.get_xticks()), panel.get_xticks())
        self.assertIsInstance(segment_axes(figure)[1].xaxis.get_major_locator(), FixedLocator)

    def test_other_axis_log_scale_is_kept_on_every_panel(self):
        figure = _series({**SERIES, "Y columns": ["a"], "Series style": {"a": "Points"}})
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "yscale": "log"})
        _draw(figure)
        self.assertIsNone(axis_breaks_reason(figure))
        self.assertEqual([panel.get_yscale() for panel in segment_axes(figure)], ["log"] * 3)

    def test_axis_names_and_title_sit_on_the_band(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "title": "Whole band", "xlabel": "Time"})
        _draw(figure)
        panels = segment_axes(figure)
        band = (panels[0].get_position().x0 + panels[-1].get_position().x1) / 2
        for text in (panels[0].xaxis.label, panels[0].title):
            extent = text.get_window_extent().transformed(figure.transFigure.inverted())
            self.assertAlmostEqual((extent.x0 + extent.x1) / 2, band, delta=.003)
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(Y_BREAKS), "title": "Top", "ylabel": "Level"})
        _draw(figure)
        panels = segment_axes(figure)
        self.assertFalse(panels[0].title.get_visible())
        self.assertEqual(panels[-1].title.get_text(), "Top")
        middle = (panels[0].get_position().y0 + panels[-1].get_position().y1) / 2
        extent = panels[0].yaxis.label.get_window_extent().transformed(figure.transFigure.inverted())
        self.assertAlmostEqual((extent.y0 + extent.y1) / 2, middle, delta=.003)

    def test_a_single_legend_stays_in_the_band(self):
        for record in (X_BREAKS, Y_BREAKS):
            figure = _series()
            apply_style(figure, {"axis_breaks": deepcopy(record)})
            _draw(figure)
            legends = [legend for legend in (*figure.legends, *(panel.get_legend() for panel in figure.axes))
                       if legend is not None and legend.get_visible()]
            self.assertEqual(len(legends), 1)
            self.assertEqual([text.get_text() for text in legends[0].get_texts()], ["a", "b"])
            band = ab._band(getattr(figure, ab.STATE_ATTR))
            box = legends[0].get_window_extent().transformed(figure.transFigure.inverted())
            self.assertGreaterEqual(box.x0, band.x0 - 1e-6)
            self.assertLessEqual(box.x1, band.x1 + 1e-6)
            self.assertGreaterEqual(box.y0, band.y0 - 1e-6)
            self.assertLessEqual(box.y1, band.y1 + 1e-6)

    def test_legend_choice_is_kept(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "legend": "lower right"})
        _draw(figure)
        box = figure.axes[0].get_legend().get_window_extent().transformed(figure.transFigure.inverted())
        band = ab._band(getattr(figure, ab.STATE_ATTR))
        self.assertGreater(box.x0, (band.x0 + band.x1) / 2)
        self.assertLess(box.y1, (band.y0 + band.y1) / 2)
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "legend": "hidden"})
        _draw(figure)
        self.assertIsNone(figure.axes[0].get_legend())


class DrawingTests(unittest.TestCase):
    def test_the_data_are_repeated_never_changed(self):
        figure = _series()
        before = [(line.get_xdata().copy(), line.get_ydata().copy()) for line in figure.axes[0].lines]
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        primary = figure.axes[0]
        for (x, y), line in zip(before, [line for line in primary.lines if line.get_gid() and line.get_gid().startswith("xy:1:")]):
            np.testing.assert_array_equal(line.get_xdata(), x)
            np.testing.assert_array_equal(line.get_ydata(), y)
        for panel in segment_axes(figure)[1:]:
            clones = [line for line in panel.lines if str(line.get_gid()).startswith(ab.GID_PREFIX + "line:")]
            self.assertEqual(len(clones), len(before))
            for (x, y), clone in zip(before, clones):
                np.testing.assert_array_equal(clone.get_xdata(), x)
                np.testing.assert_array_equal(clone.get_ydata(), y)  # NaN included: the gaps of the line stay

    def test_no_point_is_drawn_inside_a_gap(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        limits = [panel.get_xlim() for panel in segment_axes(figure)]
        for gap_x in (6, 7):  # the two points of the table that no segment contains
            self.assertFalse(any(low <= gap_x <= high for low, high in limits))

    def test_symbols_on_an_inclusive_limit_are_drawn_whole(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        seen = []
        for panel in segment_axes(figure):
            edge = [artist for artist in panel.lines if isinstance(artist, ab._EdgeMarkers)]
            self.assertTrue(edge)
            for artist in edge:
                self.assertFalse(artist.get_clip_on())
                self.assertEqual(artist.get_linestyle(), "None")
            seen.append(sorted({float(x) for artist in edge for x in artist.get_xdata()}))
        self.assertEqual(seen, [[0.0, 4.0], [10.0, 12.0], [18.0, 22.0]])
        for panel in segment_axes(figure):  # the lines stay clipped
            for line in panel.lines:
                if not isinstance(line, ab._EdgeMarkers) and not str(line.get_gid()).startswith(ab.MARKER_PREFIX):
                    self.assertTrue(line.get_clip_on())

    def test_a_line_that_crosses_a_gap_reaches_the_edge_but_does_not_fill_it(self):
        figure = _series({"X": "t", "Y columns": ["a"], "Series style": {"a": "Line"}})
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=100)
        buffer.seek(0)
        from matplotlib.image import imread

        pixels = imread(buffer)
        boxes = [panel.get_window_extent() for panel in segment_axes(figure)]
        width = pixels.shape[1]
        inked = pixels[:, :, :3].min(axis=2) < .9
        for left, right in zip(boxes, boxes[1:]):  # the white strip between two panels holds no data pixel
            middle = int((left.x1 + right.x0) / 2)
            rows = inked[int(pixels.shape[0] - boxes[0].y1) + 5: int(pixels.shape[0] - boxes[0].y0) - 25, middle]
            self.assertFalse(rows.any(), (middle, width))

    def test_error_bars_repeat_with_their_asymmetric_values(self):
        figure = xy_errors(FRAME, ERRORS).figure
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        last = segment_axes(figure)[-1]
        pieces = [piece for artist in last.collections for piece in artist.get_segments()]
        self.assertTrue(any(np.allclose(piece, [[18, 26.4], [18, 27.9]]) for piece in pieces))
        self.assertTrue(any(np.allclose(piece, [[22, 29.8], [22, 32.6]]) for piece in pieces))
        low, high = last.get_xlim()
        for panel in segment_axes(figure):  # the bars of the gap points are clipped away by every panel
            inside = [piece for artist in panel.collections for piece in artist.get_segments()
                      if panel.get_xlim()[0] <= piece[0][0] <= panel.get_xlim()[1]]
            self.assertFalse(any(piece[0][0] in (6, 7) for piece in inside))
        self.assertEqual((low, high), (18, 22))
        for panel in segment_axes(figure)[1:]:
            self.assertTrue(all(artist.get_clip_on() for artist in panel.collections))

    def test_error_bars_keep_their_legend_and_style(self):
        frame = FRAME.assign(group=["p", "q"] * 6 + ["p"])
        figure = xy_errors(frame, {**ERRORS, "Group": "group"}).figure
        apply_style(figure, {"axis_breaks": deepcopy(Y_BREAKS), "series": {}})
        _draw(figure)
        legends = [panel.get_legend() for panel in figure.axes if panel.get_legend() is not None]
        self.assertEqual(len(legends), 1)
        self.assertEqual({text.get_text() for text in legends[0].get_texts()}, {"p", "q"})

    def test_series_style_reaches_every_panel(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS),
                             "series": {"xy:1:a": {"color": "#cc0000", "line_style": "dashed", "width": 3}}})
        _draw(figure)
        for panel in segment_axes(figure):
            lines = [line for line in panel.lines if line.get_gid() and line.get_gid().startswith(ab.GID_PREFIX + "line:")
                     or line.get_gid() == "xy:1:a"]
            self.assertTrue(lines)
            for line in lines:
                if line.get_gid().endswith(":xy:1:a") or line.get_gid() == "xy:1:a":
                    self.assertEqual(line.get_color(), "#cc0000")
                    self.assertEqual(line.get_linestyle(), "--")
                    self.assertEqual(line.get_linewidth(), 3)

    def test_break_marks_are_stable_ids_in_the_vector_output(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        root = ET.fromstring(buffer.getvalue())
        ids = [node.get("id") for node in root.iter() if node.get("id", "").startswith(ab.MARKER_PREFIX)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), ["axis-break-marker-x1-after-bottom", "axis-break-marker-x1-before-bottom",
                                       "axis-break-marker-x2-after-bottom", "axis-break-marker-x2-before-bottom"])
        self.assertFalse([node for node in root.iter() if node.tag.endswith("}image")])
        self.assertGreaterEqual(len([node for node in root.iter() if node.tag.endswith("}clipPath")]), 3)
        all_ids = [node.get("id") for node in root.iter() if node.get("id")]
        self.assertEqual(len(all_ids), len(set(all_ids)), "duplicate SVG ids")

    def test_a_boxed_frame_marks_both_sides_of_every_gap(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(Y_BREAKS), "frame": "box"})
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        ids = sorted(node.get("id") for node in ET.fromstring(buffer.getvalue()).iter()
                     if node.get("id", "").startswith(ab.MARKER_PREFIX))
        self.assertEqual(ids, [f"axis-break-marker-y1-{side}-{edge}" for side in ("after", "before")
                               for edge in ("left", "right")])

    def test_exports_in_every_format_keep_the_breaks(self):
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        with TemporaryDirectory() as folder:
            for fmt in ("png", "svg", "pdf"):
                path = Path(folder) / f"graph.{fmt}"
                export_figure(figure, path, {"format": fmt, "width_mm": 120, "height_mm": 80, "dpi": 150})
                self.assertGreater(path.stat().st_size, 1000, fmt)
                if fmt == "svg":
                    text = path.read_text(encoding="utf-8")
                    self.assertEqual(text.count('id="axis-break-marker-x'), 4)
            self.assertEqual(len(segment_axes(figure)), 3)
            _draw(figure)
            shares, _ = _geometry(figure, "x")
            np.testing.assert_allclose(shares, [.322, .276, .322], rtol=0, atol=1e-6)

    def test_a_two_panel_layout_exports_with_the_breaks(self):
        first, second = _series(), _series()
        apply_style(first, {"axis_breaks": deepcopy(X_BREAKS)})
        apply_style(second, {"axis_breaks": deepcopy(Y_BREAKS)})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "layout.svg"
            export_layout_svg("Two graphs", 2, [first, second], path, {"transparent": False})
            text = path.read_text(encoding="utf-8")
            self.assertIn("axis-break-marker-x1-before-bottom", text)
            self.assertIn("axis-break-marker-y1-before-left", text)
        page = compose_layout("Two graphs", 2, [first, second])
        _draw(page)
        self.assertEqual(len(segment_axes(first)), 3)
        self.assertEqual(len(segment_axes(second)), 2)

    def test_10000_points_and_three_segments_stay_interactive(self):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame({"t": np.sort(rng.uniform(0, 22, 10_000)), "a": rng.normal(20, 5, 10_000)})
        figure = xy_series(frame, {"X": "t", "Y columns": ["a"], "Series style": {"a": "Line and points"}}).figure
        start = time.perf_counter()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(figure)
        elapsed = time.perf_counter() - start
        self.assertEqual(len(segment_axes(figure)), 3)
        self.assertLess(elapsed, 30)


class OverlayTests(unittest.TestCase):
    def test_references_guides_and_bands_appear_only_where_they_have_content(self):
        figure = _series()
        style = {"axis_breaks": deepcopy(X_BREAKS),
                 "reference_lines": [{"axis": "x", "value": 11, "label": "mid"}, {"axis": "y", "value": 15, "label": "level"}],
                 "axis_guides": [{"id": "a0000000-0000-4000-8000-000000000011", "axis": "x", "value": 20, "line": True,
                                  "tick": False, "label": "twenty", "color": "#aa0000", "style": "-", "width": 1.2}],
                 "axis_bands": [{"id": "a0000000-0000-4000-8000-000000000012", "axis": "x", "lower": 3, "upper": 11,
                                 "color": "#00aa00", "alpha": .2, "hatch": ""}]}
        apply_style(figure, style)
        _draw(figure)
        panels = segment_axes(figure)

        renderer = figure._get_renderer()

        def labels(panel):  # an annotation clipped to its point is not drawn where the point is out of range
            return [text.get_text() for text in panel.texts if text.get_visible() and text._check_xy(renderer)]

        self.assertEqual(labels(panels[0]), [])  # "level" belongs to the last panel, "mid" to the second
        self.assertEqual(sorted(labels(panels[1])), ["mid"])
        self.assertEqual(sorted(labels(panels[2])), ["level", "twenty"])
        vertical = [[line.get_xdata()[0] for line in panel.lines if line.get_linestyle() == "--" and len(line.get_xdata()) == 2
                     and line.get_xdata()[0] == line.get_xdata()[1]
                     and panel.get_xlim()[0] <= line.get_xdata()[0] <= panel.get_xlim()[1]] for panel in panels]  # the clip keeps the others out
        self.assertEqual(vertical, [[], [11], []])
        bands = [[patch for patch in panel.patches
                  if patch.get_xy()[0] <= panel.get_xlim()[1] and patch.get_xy()[0] + patch.get_width() >= panel.get_xlim()[0]]
                 for panel in panels]
        self.assertEqual([len(group) for group in bands], [1, 1, 0])  # [3, 11] crosses two segments
        self.assertEqual(len(figure.axes[0]._tramastat_references), 3)  # the Inspector keeps finding them

    def test_shapes_and_notes_in_data_units_are_clipped_to_their_panels(self):
        shape = {"id": "a0000000-0000-4000-8000-000000000021", "kind": "rectangle", "units": "data",
                 "points": [[2, 3], [11, 9]], "stroke": "#333333", "fill": None, "width": 1.0, "alpha": 1.0,
                 "line_style": "solid", "layer": "above"}
        note = {"text": "peak", "position": [11, 25], "units": "data", "align": "center", "size": 9, "color": "#000000"}
        figure = _series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "shapes": [shape], "annotations": [note]})
        _draw(figure)
        panels = segment_axes(figure)
        self.assertEqual([len(panel.patches) for panel in panels], [1, 1, 1])  # the rectangle crosses the gap: two parts
        self.assertEqual([[t.get_text() for t in panel.texts if panel.get_children()] for panel in panels][1], ["peak"])
        self.assertTrue(all(patch.get_clip_on() for panel in panels for patch in panel.patches))
        ids = [artist.get_gid() for panel in panels for artist in panel.patches]
        self.assertEqual(len(ids), len(set(ids)))

    def test_plot_fractions_are_refused_before_anything_changes(self):
        figure = _series()
        note = {"text": "n", "position": [.5, .5], "units": "axes", "align": "left", "size": 9, "color": "#000000"}
        limits = figure.axes[0].get_xlim()
        with self.assertRaises(ValueError):
            apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "annotations": [note]})
        self.assertEqual(len(figure.axes), 1)
        self.assertEqual(figure.axes[0].get_xlim(), limits)
        apply_style(figure, {"annotations": [note]})  # without the breaks it is fine


class LifecycleTests(unittest.TestCase):
    def test_apply_cancel_apply_never_accumulates_panels_or_artists(self):
        figure = _series()
        _draw(figure)
        reference = (len(figure.axes[0].get_children()), len(figure.axes[0].lines), figure.axes[0].get_xlim(),
                     figure.axes[0].get_ylim())
        counts = []
        for style in ({"axis_breaks": deepcopy(X_BREAKS)}, {"axis_breaks": deepcopy(Y_BREAKS)}, {},
                      {"axis_breaks": deepcopy(X_BREAKS), "grid": True}, {"axis_breaks": deepcopy(X_BREAKS), "grid": True},
                      {"axis_breaks": {}}, {"axis_breaks": deepcopy(Y_BREAKS)}, {"axis_breaks": deepcopy(Y_BREAKS)}):
            apply_style(figure, style)
            _draw(figure)
            counts.append((len(figure.axes), sum(len(panel.get_children()) for panel in figure.axes)))
        self.assertEqual([c[0] for c in counts], [3, 2, 1, 3, 3, 1, 2, 2])
        self.assertEqual(counts[3], counts[4])
        self.assertEqual(counts[6], counts[7])
        apply_style(figure, {})
        _draw(figure)
        self.assertEqual((len(figure.axes[0].get_children()), len(figure.axes[0].lines), figure.axes[0].get_xlim(),
                          figure.axes[0].get_ylim()), reference)

    def test_removing_the_breaks_restores_the_graph(self):
        for record in (X_BREAKS, Y_BREAKS):
            plain = _draw(_series())
            figure = _series()
            apply_style(figure, {"axis_breaks": deepcopy(record), "title": "t"})
            _draw(figure)
            apply_style(figure, {"title": plain.axes[0].get_title()})
            _draw(figure)
            self.assertEqual(segment_axes(figure), [])
            self.assertEqual(len(figure.axes), 1)
            axes, reference = figure.axes[0], plain.axes[0]
            self.assertEqual((axes.get_xlim(), axes.get_ylim()), (reference.get_xlim(), reference.get_ylim()))
            np.testing.assert_allclose(axes.get_position().bounds, reference.get_position().bounds, atol=1e-9)
            self.assertEqual(axes.get_xticks().tolist(), reference.get_xticks().tolist())
            self.assertEqual(axes.get_yticks().tolist(), reference.get_yticks().tolist())
            self.assertEqual([spine.get_visible() for spine in axes.spines.values()],
                             [spine.get_visible() for spine in reference.spines.values()])
            self.assertTrue(axes.title.get_visible())
            self.assertIsNone(axes.get_legend()._bbox_to_anchor)
            self.assertEqual(axes.get_legend()._loc, reference.get_legend()._loc)
            self.assertNotIsInstance(figure.get_layout_engine(), ab._BreakEngine)

    def test_a_figure_without_the_section_is_what_it_always_was(self):
        plain = _draw(_series())
        for style in ({}, {"axis_breaks": {}}, {"grid": True, "axis_breaks": {}}):
            figure = _series()
            apply_style(figure, style)
            _draw(figure)
            self.assertEqual(len(figure.axes), 1)
            self.assertEqual(segment_axes(figure), [])
            self.assertIsNone(axis_breaks_reason(figure))
            self.assertEqual(figure.axes[0].get_position().bounds if not style.get("grid") else plain.axes[0].get_position().bounds,
                             plain.axes[0].get_position().bounds)

    def test_an_invalid_section_changes_nothing(self):
        figure = _series()
        axes = figure.axes[0]
        snapshot = (axes.get_xlim(), axes.get_ylim(), len(axes.get_children()))
        bad = deepcopy(X_BREAKS)
        bad["segments"][1]["low"] = 2
        with self.assertRaises(FieldError) as caught:
            apply_style(figure, {"axis_breaks": bad})
        self.assertEqual(caught.exception.field, "segments.1.low")
        self.assertEqual(figure.axes, [axes])
        self.assertEqual((axes.get_xlim(), axes.get_ylim(), len(axes.get_children())), snapshot)
        with self.assertRaises(FieldError):  # validate_graph_style is the same transaction
            validate_graph_style(axes, {"axis_breaks": bad})
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        with self.assertRaises(FieldError):  # an invalid edit keeps the previous good panels
            apply_style(figure, {"axis_breaks": bad})
        self.assertEqual(len(segment_axes(figure)), 3)

    def test_the_project_keeps_the_section_and_redraws_it(self):
        style = {"axis_breaks": deepcopy(X_BREAKS), "title": "Saved"}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "breaks.alab"
            dataset = Dataset(FRAME, analyses=[("XY series", deepcopy(SERIES))], graph_styles={0: style})
            save_project(path, {"Signal": dataset})
            reopened = load_project(path)["Signal"]
        self.assertEqual(reopened.graph_styles[0], style)
        figure = xy_series(reopened.frame(), reopened.analyses[0][1]).figure
        apply_style(figure, reopened.graph_styles[0])
        self.assertEqual(len(segment_axes(figure)), 3)
        self.assertEqual(figure.axes[0].get_title(), "Saved")

    def test_a_recipe_without_the_section_loads_as_before(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "old.alab"
            dataset = Dataset(FRAME, analyses=[("XY series", deepcopy(SERIES))], graph_styles={0: {"grid": True}})
            save_project(path, {"Signal": dataset})
            reopened = load_project(path)["Signal"]
        self.assertEqual(reopened.graph_styles[0], {"grid": True})

    def test_the_worksheets_are_untouched_by_the_breaks(self):
        result = xy_series(FRAME, SERIES)
        before = {name: table.copy(deep=True) for name, table in result.tables.items()}
        apply_style(result.figure, {"axis_breaks": deepcopy(X_BREAKS)})
        _draw(result.figure)
        self.assertEqual(before.keys(), result.tables.keys())
        for name, table in before.items():
            pd.testing.assert_frame_equal(result.tables[name], table, check_exact=True)
        self.assertEqual(len(result.tables["Series values"]), 25)  # every plotted value, gap points included
        self.assertIn(6, result.tables["Series values"]["X"].tolist())


class CompatibilityTests(unittest.TestCase):
    """A saved record that a later edit makes impossible is kept, ignored, and explained."""

    def test_a_right_axis_is_refused_with_the_reason(self):
        figure = _series({**SERIES, "Series side": {"b": "Right"}})
        self.assertEqual(len(figure.axes), 2)
        for record in (X_BREAKS, Y_BREAKS):
            apply_style(figure, {"axis_breaks": deepcopy(record)})
            _draw(figure)
            self.assertEqual(len(figure.axes), 2)
            self.assertEqual(segment_axes(figure), [])
            self.assertIn("right Y axis", axis_breaks_reason(figure))

    def test_a_log_broken_axis_is_refused(self):
        frame = FRAME.assign(t=FRAME["t"] + 1)
        figure = xy_series(frame, {"X": "t", "Y columns": ["a"], "Series style": {"a": "Points"}}).figure
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "xscale": "log"})
        self.assertEqual(segment_axes(figure), [])
        self.assertIn("linear X axis", axis_breaks_reason(figure))
        self.assertEqual(figure.axes[0].get_xscale(), "log")
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})  # the reason goes when the cause goes
        self.assertEqual(len(segment_axes(figure)), 3)
        self.assertIsNone(axis_breaks_reason(figure))

    def test_other_graph_types_and_pictures_are_refused(self):
        record = normalise_axis_breaks(X_BREAKS)
        picture = Figure(layout="constrained").add_subplot()
        picture.imshow(np.zeros((3, 3)))
        picture._tramastat_non_native = True
        ab.mark_supported(picture)
        self.assertIn("native graph", ab.axis_breaks_problem(picture, record))
        other = Figure(layout="constrained").add_subplot()
        self.assertIn("XY series and XY error bars", ab.axis_breaks_problem(other, record))
        figure = Figure(layout="constrained")
        figure.add_subplot().plot([1, 2], [1, 2])
        self.assertIn("XY series and XY error bars", ab.axis_breaks_problem(figure.axes[0], record))

    def test_a_categorical_axis_is_refused(self):
        figure = Figure(layout="constrained")
        axes = figure.add_subplot()
        axes.plot(["a", "b", "c"], [1, 2, 3])
        ab.mark_supported(axes)
        self.assertIn("numeric X axis", ab.axis_breaks_problem(axes, normalise_axis_breaks(X_BREAKS)))

    def test_an_inverted_axis_is_refused(self):
        figure = _series()
        figure.axes[0].set_xlim(22, 0)
        self.assertIn("increases", ab.axis_breaks_problem(figure.axes[0], normalise_axis_breaks(X_BREAKS)))

    def test_drawing_elements_that_cannot_be_repeated_are_refused(self):
        figure = _series()
        figure.axes[0].bar([1], [1])
        self.assertIn("cannot repeat", ab.axis_breaks_problem(figure.axes[0], normalise_axis_breaks(X_BREAKS)))

    def test_an_exception_while_drawing_leaves_the_graph_whole(self):
        figure = _series()
        original = ab._repeat_data

        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        ab._repeat_data = broken
        try:
            apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS)})
        finally:
            ab._repeat_data = original
        _draw(figure)
        self.assertEqual(len(figure.axes), 1)
        self.assertEqual(segment_axes(figure), [])
        self.assertIn("could not be drawn", axis_breaks_reason(figure))
        self.assertNotIsInstance(figure.get_layout_engine(), ab._BreakEngine)


if __name__ == "__main__":
    unittest.main()
