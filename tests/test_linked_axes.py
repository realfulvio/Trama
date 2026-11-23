"""Linked secondary axes: the record, conversion, drawing on every supported graph, the cases that must not draw,
extreme limits, pickling, exports and the IT/EN catalog. Every fixture is synthetic."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import unittest
import warnings
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg

from analisi import linked_axes as la
from analisi.i18n import active_language, set_language, tr, translate_message
from analisi.figure_export import export_figure
from analisi.layout_svg import export_layout_svg
from analisi.linked_axes import (AffineMap, GID_PREFIX, LinkedAxesError, apply_linked_axes, clear_linked_axes,
                                 convert, linked_axes_conflicts, linked_axes_reasons, linked_axes_status,
                                 linked_children, normalise_linked_axes, range_problem, reverse,
                                 style_without_linked_y, supported_dimensions)
from analisi.linked_axes_text import EN, IT
from analisi.presentation import apply_style, compose_layout, validate_graph_style, validated_style
from analisi.survival_plot import style_after_parameter_change
from analisi.workbench import analyse
from analisi.xy_series import xy_series

FRAME = pd.DataFrame({
    "t": [0.5, 1, 2, 3, 4, 6, 7, 10, 11, 12, 18, 20, 22],
    "a": [1, 2, 2.7, 3.6, 4.5, 11, 15, 21, 22, 24, 27, 29, 31],
    "b": [2, 5, 8, np.nan, 9, 12, 14, 24, 27, 30, 25, 28, 34],
    "lo": .3, "hi": .4,
    "event": [1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1],
    "arm": ["A", "B"] * 6 + ["A"],
})
COLUMNS = pd.DataFrame({"A": [4.1, 5.0, 4.7, 5.3, 4.9], "B": [5.9, 6.3, 6.1, 5.7, 6.6], "C": [7.2, 6.8, 7.7, 7.1, 7.4]})
SERIES = {"X": "t", "Y columns": ["a"], "Series style": {"a": "Line and points"}}
BOTH = {"x": {"multiplier": 2.0, "offset": 1.0, "label": "Twice plus one"},
        "y": {"multiplier": 0.5, "offset": -2.0, "label": "Half minus two"}}
X_BREAKS = {"axis": "x", "gap": 0.04, "segments": [
    {"low": 0, "high": 4, "share": 35, "major_step": 2},
    {"low": 10, "high": 12, "share": 30, "major_step": 1},
    {"low": 18, "high": 22, "share": 35, "major_step": 2}]}


def series(options=None):
    return xy_series(FRAME, options or SERIES).figure


def draw(figure):
    FigureCanvasAgg(figure).draw()
    return figure


def item(multiplier=1.0, offset=0.0, label=""):
    return {"multiplier": multiplier, "offset": offset, "label": label}


def drawn(figure):
    return sorted(linked_children(figure.axes[0]))


class RecordTests(unittest.TestCase):
    def test_off_state_and_canonical_copy(self):
        self.assertEqual(normalise_linked_axes(None), {})
        self.assertEqual(normalise_linked_axes({}), {})
        record = {"y": {"multiplier": 2, "offset": 0, "label": "µm/s"}}
        canonical = normalise_linked_axes(record)
        self.assertEqual(canonical, {"y": {"multiplier": 2.0, "offset": 0.0, "label": "µm/s"}})
        self.assertIs(type(canonical["y"]["multiplier"]), float)
        self.assertIs(type(record["y"]["multiplier"]), int)  # the input is never rewritten

    def test_every_invalid_record_names_its_field(self):
        good = item(2.0, 1.0, "ok")
        cases = [
            ("whole", ["x"], None, "x", la.M_TYPE),
            ("whole", {"z": good}, None, "x", la.M_TYPE),
            ("record", {"x": "no"}, "x", "multiplier", la.M_TYPE),
            ("keys", {"x": {"multiplier": 1.0, "offset": 0.0}}, "x", "multiplier", la.M_TYPE),
            ("extra", {"x": {**good, "unit": "m"}}, "x", "multiplier", la.M_TYPE),
        ]
        for value in (0, -1.0, float("nan"), float("inf"), True, "2", None, 1e400):
            cases.append((f"multiplier {value!r}", {"y": {**good, "multiplier": value}}, "y", "multiplier",
                          la.M_MULTIPLIER.format(axis="Y")))
        for value in (float("nan"), float("-inf"), "1", None, False, 1e308 * 10):
            cases.append((f"offset {value!r}", {"x": {**good, "offset": value}}, "x", "offset",
                          la.M_OFFSET.format(axis="X")))
        for value in ("a" * 161, "two\nlines", "tab\t", "bell\x07", 5, None):
            cases.append((f"label {value!r}", {"y": {**good, "label": value}}, "y", "label",
                          la.M_LABEL.format(axis="Y")))
        for name, record, dimension, field, message in cases:
            with self.subTest(name):
                with self.assertRaises(LinkedAxesError) as caught:
                    normalise_linked_axes(record)
                self.assertEqual(caught.exception.dimension, dimension)
                self.assertEqual(caught.exception.name, field)
                self.assertIsInstance(caught.exception, ValueError)
                self.assertEqual(str(caught.exception), message)

    def test_boundary_labels_and_unicode_are_accepted(self):
        for label in ("", "a" * 160, "Temperatura (°F)", "µg/mL", r"$\mu$m", "日本語"):
            self.assertEqual(normalise_linked_axes({"x": item(1.0, 0.0, label)})["x"]["label"], label)

    def test_validated_style_keeps_the_record_and_refuses_a_bad_one(self):
        style = validated_style({"linked_axes": deepcopy(BOTH)})
        self.assertEqual(style["linked_axes"], BOTH)
        with self.assertRaises(ValueError):
            validated_style({"linked_axes": {"x": item(0.0)}})
        self.assertNotIn("linked_axes", validated_style({}))

    def test_a_style_cannot_ask_for_an_offset_on_a_logarithmic_axis_or_an_overflowing_range(self):
        figure = series()
        axes = figure.axes[0]
        validate_graph_style(axes, {"xscale": "log", "linked_axes": {"x": item(25.4, 0.0, "mm")}})
        with self.assertRaises(ValueError) as caught:
            validate_graph_style(axes, {"xscale": "log", "linked_axes": {"x": item(25.4, 3.0, "mm")}})
        self.assertEqual(str(caught.exception), la.M_LOG_OFFSET.format(axis="X"))
        explicit = {"axis": {"y": {"min": 0, "max": 1e300}}, "linked_axes": {"y": item(1e10)}}
        with self.assertRaises(ValueError) as caught:
            validate_graph_style(axes, explicit)
        self.assertEqual(str(caught.exception), la.M_RANGE.format(axis="Y"))

    def test_a_label_with_broken_math_text_is_refused_where_it_is_typed(self):
        with self.assertRaises(ValueError):
            validate_graph_style(series().axes[0], {"linked_axes": {"x": item(1.0, 0.0, r"$\frac{1$")}})


class ConversionTests(unittest.TestCase):
    def test_convert_and_reverse_are_exact_inverses(self):
        record = item(1.8, 32.0)
        values = np.array([-40.0, 0.0, 37.5, 100.0])
        np.testing.assert_allclose(convert(record, values), [-40.0, 32.0, 99.5, 212.0])
        np.testing.assert_allclose(reverse(record, convert(record, values)), values)

    def test_range_problem_flags_overflow_and_collapse_only(self):
        self.assertIsNone(range_problem("x", item(2.0, 1.0), (-5, 5)))
        self.assertIsNone(range_problem("x", item(1e-15), (0, 1)))
        self.assertIsNone(range_problem("x", item(1e-200), (0, 1)))
        for record, limits in ((item(1e300 * 10), (0, 1)), (item(1.0, 1e300), (0, 1)), (item(1e-300), (0, 1)),
                               (item(1e10), (0, 1e300))):
            with self.subTest(record=record, limits=limits):
                self.assertEqual(range_problem("x", normalise_or_raw(record), limits), la.M_RANGE.format(axis="X"))
        self.assertIsNone(range_problem("x", item(2.0), (float("nan"), 1)))  # nothing to judge yet

    def test_the_matplotlib_map_stays_finite_and_picklable(self):
        forward = AffineMap(item(1e10, 5.0))
        values = forward(np.array([-1e300, 0.0, np.nan, 1e300]))
        self.assertTrue(np.isfinite(values).all())
        again = pickle.loads(pickle.dumps(forward))
        np.testing.assert_array_equal(again(np.array([1.0, 2.0])), forward(np.array([1.0, 2.0])))
        inverse = AffineMap(item(2.0, 4.0), inverse=True)
        np.testing.assert_allclose(inverse(np.array([4.0, 10.0])), [0.0, 3.0])


def normalise_or_raw(record):
    """The overflow records cannot pass ``normalise_linked_axes`` (that is the point); the range check takes them raw."""
    return record


class DrawingTests(unittest.TestCase):
    def test_both_axes_are_real_children_with_stable_ids(self):
        figure = series()
        figure.axes[0].set_title("Kept")
        before = [line.get_data() for line in figure.axes[0].lines]
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        axes = figure.axes[0]
        self.assertEqual(len(figure.axes), 1)  # a child axis does not join ``figure.axes``
        self.assertEqual(sorted(child.get_gid() for child in axes.child_axes), [GID_PREFIX + "x", GID_PREFIX + "y"])
        found = linked_children(axes)
        self.assertEqual(found["x"].xaxis.label.get_text(), "Twice plus one")
        self.assertEqual(found["y"].yaxis.label.get_text(), "Half minus two")
        self.assertEqual(axes.get_title(), "Kept")
        for line, (x, y) in zip(axes.lines, before, strict=True):
            np.testing.assert_array_equal(line.get_xdata(), x)
            np.testing.assert_array_equal(line.get_ydata(), y)
        self.assertEqual(linked_axes_reasons(figure), {})

    def test_the_limits_follow_pan_zoom_inversion_and_reset(self):
        figure = series()
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        axes = figure.axes[0]
        found = linked_children(axes)

        def check():
            draw(figure)
            low, high = axes.get_xlim()
            np.testing.assert_allclose(found["x"].get_xlim(), [2 * low + 1, 2 * high + 1])
            low, high = axes.get_ylim()
            np.testing.assert_allclose(found["y"].get_ylim(), [.5 * low - 2, .5 * high - 2])

        check()
        axes.set_xlim(3, 8)  # zoom
        check()
        axes.set_xlim(-2, 3)  # pan
        check()
        axes.set_ylim(*axes.get_ylim()[::-1])  # inversion: the secondary axis is inverted with it
        check()
        axes.set_xlim(*axes.get_xlim()[::-1])
        check()
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})  # reset: formatting again
        self.assertEqual(drawn(figure), ["x", "y"])
        check()

    def test_zooming_far_beyond_the_validated_range_never_raises(self):
        figure = series()
        apply_style(figure, {"linked_axes": {"x": item(1e10, 5.0, "huge")}})
        axes = figure.axes[0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # matplotlib widens a collapsed range; it must not raise
            for limits in ((1e300, 1e301), (-1e305, 1e305), (0, 1e-300), (1e-300, 2e-300)):
                axes.set_xlim(*limits)
                draw(figure)

    def test_formatting_again_never_stacks_axes(self):
        figure = series()
        for _ in range(3):
            apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        self.assertEqual(len(figure.axes[0].child_axes), 2)
        for index in range(20):
            record = deepcopy(BOTH)
            record["x"]["label"] = f"round {index}"
            apply_style(figure, {"linked_axes": record})
        draw(figure)
        self.assertLessEqual(len(figure.axes[0].child_axes), 2)
        self.assertEqual(linked_children(figure.axes[0])["x"].xaxis.label.get_text(), "round 19")
        apply_style(figure, {})
        self.assertEqual(len(figure.axes[0].child_axes), 0)
        self.assertEqual(linked_axes_reasons(figure), {})

    def test_the_secondary_axis_follows_the_fonts_of_the_graph(self):
        figure = series()
        apply_style(figure, {"label_size": 13, "linked_axes": {"x": item(2.0, 0.0, "Twice")}})
        child = linked_children(figure.axes[0])["x"]
        self.assertEqual(child.xaxis.label.get_fontsize(), 13)
        self.assertEqual(child.xaxis.label.get_color(), figure.axes[0].xaxis.label.get_color())
        self.assertFalse(child.xaxis.get_gridlines()[0].get_visible())  # the grid stays on the primary axis

    def test_xy_error_bars_and_regressions_take_linked_axes(self):
        cases = {
            "XY error bars": {"X": "t", "Y": "a", "Y lower error": "lo", "Y upper error": "hi",
                              "Y error values": "Distances"},
            "Linear regression": {"X": "t", "Y": "a"},
            "Deming regression": {"X": "t", "Y": "a", "Y / X error variance": 1.0},
            "Nonlinear regression": {"X": "t", "Y columns": ["a"], "Model": "One-phase decay"},
        }
        for method, options in cases.items():
            with self.subTest(method):
                figure = analyse(method, FRAME, options).figure
                self.assertEqual(supported_dimensions(figure.axes[0]), ("x", "y"))
                apply_style(figure, {"linked_axes": deepcopy(BOTH)})
                draw(figure)
                self.assertEqual(drawn(figure), ["x", "y"])
                self.assertEqual(linked_axes_reasons(figure), {})

    def test_survival_curves_with_a_risk_table_take_both_axes_and_a_unit_change_drops_the_y_record(self):
        options = {"Time": "t", "Event columns": ["event"], "Grouping variables": ["arm"],
                   "Show risk table below graph": True}
        figure = analyse("Kaplan–Meier survival", FRAME, options).figure
        self.assertEqual(len(figure.axes), 2)
        percent = {"x": item(1 / 12, 0.0, "Years"), "y": item(100.0, 0.0, "Survival (%)")}
        apply_style(figure, {"linked_axes": percent})
        draw(figure)
        self.assertEqual(drawn(figure), ["x", "y"])
        self.assertEqual(len(figure.axes), 2)
        kept = style_after_parameter_change({"linked_axes": percent}, {"Curve": "Survival"},
                                            {"Curve": "Cumulative events"})
        self.assertEqual(kept["linked_axes"], {"x": percent["x"]})  # the Y quantity changed: its unit no longer holds
        self.assertEqual(percent["y"]["label"], "Survival (%)")  # the original is not edited
        unchanged = style_after_parameter_change({"linked_axes": percent}, {"Curve": "Survival"},
                                                 {"Curve": "Survival"})
        self.assertEqual(unchanged["linked_axes"], percent)  # nothing about the Y quantity changed
        self.assertEqual(style_without_linked_y({"title": "t"}), {"title": "t"})
        self.assertNotIn("linked_axes", style_without_linked_y({"linked_axes": {"y": percent["y"]}}))

    def test_column_and_grouped_graphs_take_the_value_axis_only(self):
        figure = analyse("Column graph", COLUMNS, {"Variables": ["A", "B", "C"]}).figure
        self.assertEqual(supported_dimensions(figure.axes[0]), ("y",))
        apply_style(figure, {"linked_axes": {"y": item(1000.0, 0.0, "mg"), "x": item(2.0, 0.0, "no")}})
        draw(figure)
        self.assertEqual(drawn(figure), ["y"])
        self.assertEqual(linked_axes_reasons(figure), {"x": la.P_CATEGORICAL.format(axis="X")})
        grouped = analyse("Grouped graph", COLUMNS, {"Variables": ["A", "B", "C"]}).figure
        self.assertEqual(supported_dimensions(grouped.axes[0]), ("y",))
        apply_style(grouped, {"linked_axes": {"y": item(1000.0, 0.0, "mg")}})
        self.assertEqual(drawn(grouped), ["y"])

    def test_graphs_without_support_say_so(self):
        figure = analyse("Correlation", FRAME, {"X": "t", "Y": "a", "Method": "Pearson"}).figure
        self.assertEqual(supported_dimensions(figure.axes[0]), ())
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        self.assertEqual(drawn(figure), [])
        self.assertEqual(linked_axes_reasons(figure), {"x": la.P_SUPPORT, "y": la.P_SUPPORT})
        self.assertIn(tr("linked_axes.error.support"), linked_axes_status(figure, {"linked_axes": BOTH}))


class ConflictTests(unittest.TestCase):
    def test_a_logarithmic_primary_axis_takes_a_unit_change_only(self):
        figure = series()
        apply_style(figure, {"xscale": "log"})
        axes = figure.axes[0]
        self.assertEqual(linked_axes_conflicts(axes), {})
        apply_style(figure, {"xscale": "log", "linked_axes": {"x": item(25.4, 0.0, "mm")}})
        draw(figure)
        self.assertEqual(drawn(figure), ["x"])
        child = linked_children(figure.axes[0])["x"]
        self.assertEqual(child.xaxis.get_scale(), "functionlog")
        np.testing.assert_allclose(child.get_xlim(), [25.4 * value for value in figure.axes[0].get_xlim()], rtol=1e-9)
        # The same record with an offset leaves the axis out and keeps the record in the style.
        # The same record with an offset is refused when the style itself chooses the logarithmic scale...
        with self.assertRaises(ValueError) as caught:
            apply_style(figure, {"xscale": "log", "linked_axes": {"x": item(25.4, 3.0, "mm")}})
        self.assertEqual(str(caught.exception), la.M_LOG_OFFSET.format(axis="X"))
        self.assertEqual(drawn(figure), ["x"])  # ...and the graph is left as it was

    def test_a_default_log_scale_with_an_offset_is_a_reason_not_an_error(self):
        figure = series()
        figure.axes[0].set_yscale("log")  # a graph whose own scale is logarithmic
        apply_style(figure, {"linked_axes": {"y": item(2.0, 5.0, "shifted")}})
        self.assertEqual(drawn(figure), [])
        self.assertIn("y", linked_axes_reasons(figure))

    def test_an_independent_right_axis_blocks_the_right_axis_only(self):
        figure = series({"X": "t", "Y columns": ["a", "b"], "Series side": {"a": "Left", "b": "Right"}})
        self.assertEqual(len(figure.axes), 2)
        conflicts = linked_axes_conflicts(figure.axes[0])
        self.assertEqual(conflicts, {"y": la.P_RIGHT})
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        draw(figure)
        self.assertEqual(drawn(figure), ["x"])
        self.assertEqual(linked_axes_reasons(figure), {"y": la.P_RIGHT})
        self.assertEqual(linked_axes_conflicts(figure.axes[0], right=False), {})  # the choice the dialog is making
        self.assertEqual(len(figure.axes), 2)

    def test_axis_breaks_win_and_the_record_stays(self):
        figure = series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "linked_axes": deepcopy(BOTH)})
        draw(figure)
        self.assertEqual(linked_children(figure.axes[0]), {})
        self.assertEqual(set(linked_axes_reasons(figure)), {"x", "y"})
        self.assertTrue(all(reason == la.P_BREAKS for reason in linked_axes_reasons(figure).values()))
        status = linked_axes_status(figure, {"linked_axes": BOTH})
        self.assertIn(tr("linked_axes.error.breaks"), status)
        # Without the breaks the same style draws both axes again.
        apply_style(figure, {"linked_axes": deepcopy(BOTH)})
        self.assertEqual(drawn(figure), ["x", "y"])
        self.assertIsNone(linked_axes_status(figure, {"linked_axes": BOTH}))

    def test_two_plot_panels_and_non_native_graphs_are_refused(self):
        figure = series()
        figure.add_subplot(2, 2, 4)
        self.assertEqual(set(linked_axes_conflicts(figure.axes[0])), {"x", "y"})
        self.assertTrue(all(value == la.P_PANELS for value in linked_axes_conflicts(figure.axes[0]).values()))
        picture = series()
        picture.axes[0]._tramastat_non_native = True
        self.assertEqual(set(linked_axes_conflicts(picture.axes[0]).values()), {la.P_NATIVE})

    def test_extreme_limits_are_left_out_with_a_reason(self):
        figure = series()
        figure.axes[0].set_xlim(0, 1e300)
        apply_style(figure, {"linked_axes": {"x": item(1e10, 0.0, "huge")}})
        draw(figure)
        self.assertEqual(drawn(figure), [])
        self.assertEqual(linked_axes_reasons(figure), {"x": la.P_RANGE.format(axis="X")})

    def test_clearing_is_safe_when_nothing_is_linked(self):
        figure = series()
        clear_linked_axes(figure.axes[0])
        self.assertEqual(apply_linked_axes(figure, {}), {})
        self.assertEqual(linked_axes_reasons(figure), {})
        self.assertIsNone(linked_axes_status(figure, {}))


class CoexistenceTests(unittest.TestCase):
    def test_grid_references_guides_bands_notes_and_shapes_keep_working(self):
        shape = {"id": "a0000000-0000-4000-8000-000000000021", "kind": "rectangle", "units": "data",
                 "points": [[2, 3], [11, 9]], "stroke": "#333333", "fill": None, "width": 1.0, "alpha": 1.0,
                 "line_style": "solid", "layer": "above"}
        note = {"text": "peak", "position": [11, 25], "units": "data", "align": "center", "size": 9,
                "color": "#000000"}
        style = {"grid": True, "legend": "best", "shapes": [shape], "annotations": [note],
                 "reference_lines": [{"axis": "x", "value": 11, "label": "mid"}],
                 "axis_guides": [{"id": "a0000000-0000-4000-8000-000000000011", "axis": "x", "value": 20,
                                  "line": True, "tick": False, "label": "twenty", "color": "#aa0000", "style": "-",
                                  "width": 1.2}],
                 "axis_bands": [{"id": "a0000000-0000-4000-8000-000000000012", "axis": "x", "lower": 3, "upper": 11,
                                 "color": "#00aa00", "alpha": .2, "hatch": ""}]}
        plain, linked = series(), series()
        apply_style(plain, deepcopy(style))
        apply_style(linked, {**deepcopy(style), "linked_axes": deepcopy(BOTH)})
        draw(plain)
        draw(linked)
        self.assertEqual(drawn(linked), ["x", "y"])
        a, b = plain.axes[0], linked.axes[0]
        self.assertEqual(len(a.lines), len(b.lines))
        self.assertEqual(len(a.patches), len(b.patches))
        self.assertEqual([t.get_text() for t in a.texts], [t.get_text() for t in b.texts])
        self.assertEqual(a.get_legend() is None, b.get_legend() is None)
        self.assertEqual(a.get_xlim(), b.get_xlim())
        self.assertEqual(a.get_ylim(), b.get_ylim())
        self.assertTrue(b.xaxis.get_gridlines()[0].get_visible())


class ExportTests(unittest.TestCase):
    def linked(self):
        figure = series()
        apply_style(figure, {"title": "Exported", "linked_axes": deepcopy(BOTH)})
        return figure

    def test_figures_with_linked_axes_pickle_and_draw_again(self):
        figure = self.linked()
        draw(figure)
        restored = pickle.loads(pickle.dumps(figure))
        draw(restored)
        self.assertEqual(sorted(child.get_gid() for child in restored.axes[0].child_axes),
                         [GID_PREFIX + "x", GID_PREFIX + "y"])

    def test_vector_exports_carry_the_ids_and_no_raster(self):
        figure = self.linked()
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        root = ET.fromstring(buffer.getvalue())
        ids = {node.get("id") for node in root.iter() if node.get("id")}
        self.assertIn(GID_PREFIX + "x", ids)
        self.assertIn(GID_PREFIX + "y", ids)
        self.assertFalse([node for node in root.iter() if node.tag.endswith("}image")])
        text = buffer.getvalue().decode("utf-8")
        self.assertIn("Twice plus one", text)  # kept as text, not outlines, with the default font handling
        pdf = BytesIO()
        figure.savefig(pdf, format="pdf")
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))
        self.assertNotIn(b"/Subtype /Image", pdf.getvalue())

    def test_the_labels_stay_inside_the_figure_and_below_the_title(self):
        figure = self.linked()
        draw(figure)
        renderer = figure._get_renderer()
        page = figure.bbox
        children = linked_children(figure.axes[0])
        top = children["x"].get_tightbbox(renderer)
        right = children["y"].get_tightbbox(renderer)
        for box in (top, right):
            self.assertGreaterEqual(box.x0, page.x0 - 1)
            self.assertLessEqual(box.x1, page.x1 + 1)
            self.assertGreaterEqual(box.y0, page.y0 - 1)
            self.assertLessEqual(box.y1, page.y1 + 1)
        title = figure.axes[0].title.get_window_extent(renderer)
        self.assertGreaterEqual(title.y0, top.y0 + 1)  # the title sits above the top axis label

    def test_every_export_format_and_the_layout_page_work(self):
        figure = self.linked()
        with TemporaryDirectory() as folder:
            for fmt in ("png", "svg", "pdf"):
                path = Path(folder) / f"graph.{fmt}"
                export_figure(figure, path, {"format": fmt, "width_mm": 120, "height_mm": 80, "dpi": 150})
                self.assertGreater(path.stat().st_size, 1000, fmt)
                if fmt == "svg":
                    self.assertIn(GID_PREFIX + "x", path.read_text(encoding="utf-8"))
            self.assertEqual(drawn(figure), ["x", "y"])  # exporting leaves the live graph as it was
            other = self.linked()
            layout = Path(folder) / "layout.svg"
            export_layout_svg("Two graphs", 2, [figure, other], layout, {"transparent": False})
            self.assertIn(GID_PREFIX + "x", layout.read_text(encoding="utf-8"))
        draw(compose_layout("Two graphs", 2, [figure, other]))


class CatalogTests(unittest.TestCase):
    def test_english_and_italian_carry_the_same_keys(self):
        self.assertEqual(set(EN), set(IT))
        for key in EN:
            self.assertTrue(IT[key].strip(), key)
        placeholders = lambda text: sorted(part.split("}")[0] for part in text.split("{")[1:])  # noqa: E731
        for key in EN:
            self.assertEqual(placeholders(EN[key]), placeholders(IT[key]), key)

    def test_every_engine_message_has_an_italian_translation(self):
        self.addCleanup(set_language, active_language())
        messages = [la.M_TYPE, la.M_MULTIPLIER.format(axis="X"), la.M_OFFSET.format(axis="Y"),
                    la.M_LABEL.format(axis="X"), la.M_LOG_OFFSET.format(axis="Y"), la.M_RANGE.format(axis="X"),
                    la.P_SUPPORT, la.P_NATIVE, la.P_CATEGORICAL.format(axis="X"), la.P_SCALE.format(axis="Y"),
                    la.P_BREAKS, la.P_RIGHT, la.P_PANELS, la.P_LOG_OFFSET.format(axis="Y"),
                    la.P_RANGE.format(axis="X"), la.P_FAILED.format(kind="ValueError", message="boom")]
        for key in ("error.type", "error.multiplier", "error.offset", "error.label", "error.log_offset",
                    "error.range", "error.support", "error.native", "error.categorical", "error.scale",
                    "error.breaks", "error.right", "error.panels", "error.p_log_offset", "error.p_range",
                    "error.failed"):
            self.assertIn("linked_axes." + key, EN)
        set_language("it")
        for message in messages:
            with self.subTest(message):
                translated = translate_message(message, "linked_axes.error.")
                self.assertNotEqual(translated, message)
        self.assertEqual(translate_message(la.M_OFFSET.format(axis="Y"), "linked_axes.error."),
                         "Asse Y collegato: inserisci uno scostamento finito.")
        set_language("en")
        self.assertEqual(translate_message(la.M_OFFSET.format(axis="Y"), "linked_axes.error."),
                         la.M_OFFSET.format(axis="Y"))

    def test_the_status_line_is_translated(self):
        self.addCleanup(set_language, active_language())
        figure = series()
        apply_style(figure, {"axis_breaks": deepcopy(X_BREAKS), "linked_axes": deepcopy(BOTH)})
        set_language("it")
        status = linked_axes_status(figure, {"linked_axes": BOTH})
        self.assertTrue(status.startswith("Gli assi secondari sono salvati ma non disegnati: "), status)
        self.assertIn("interruzioni dell’asse", status)


if __name__ == "__main__":
    unittest.main()
