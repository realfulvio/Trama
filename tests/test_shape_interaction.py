"""The toolkit-free shape controller: DPI, log and inverted axes, overlapping lines, modifiers, twin axes."""
from copy import deepcopy
import unittest

import numpy as np
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from analisi.graph_shapes import validate_shapes
from analisi.presentation import apply_style
from analisi.shape_interaction import ShapeController, event_key
from tests.test_shape_options import BOX, LINE


class Harness(unittest.TestCase):
    dpi = 100

    def build(self, *, xscale="linear", yscale="linear", invert=False, limits=((0, 10), (0, 10))):
        self.figure = Figure(figsize=(4, 3), dpi=self.dpi)
        FigureCanvasAgg(self.figure)
        self.axes = self.figure.add_axes([.2, .2, .6, .6])
        self.axes.plot([1, 2, 3], [2, 4, 5])
        self.axes.set_xscale(xscale)
        self.axes.set_yscale(yscale)
        self.axes.set(xlim=limits[0], ylim=limits[1])
        if invert:
            self.axes.invert_xaxis()
            self.axes.invert_yaxis()
        self.records, self.commits = [], []
        self.figure.canvas.draw()
        self.editor = ShapeController(self.figure.canvas, self.axes, records=lambda: deepcopy(self.records),
                                      commit=self.commit, status=lambda text: None)
        self.addCleanup(self.editor.close)

    def commit(self, records):
        self.records = validate_shapes(records)
        self.commits.append(deepcopy(records))

    def show(self, records):
        self.records = validate_shapes(records)
        apply_style(self.figure, {"shapes": self.records})
        self.figure.canvas.draw()

    def event(self, name, point, *, data=False, **kwargs):
        pixel = (self.axes.transData if data else self.axes.transAxes).transform(point)
        event = MouseEvent(name, self.figure.canvas, *pixel, button=1, **kwargs)
        self.figure.canvas.callbacks.process(name, event)

    def drag(self, start, end, **kwargs):
        self.event("button_press_event", start, **kwargs)
        self.event("motion_notify_event", end, **kwargs)
        self.event("button_release_event", end, **kwargs)


class OverlapAndDpiTests(Harness):
    def test_the_topmost_of_two_overlapping_lines_is_picked_and_moves_alone(self):
        self.build()
        lower = {**LINE, "id": "00000000-0000-4000-8000-0000000000a1", "points": [[.2, .2], [.8, .8]]}
        upper = {**LINE, "id": "00000000-0000-4000-8000-0000000000a2", "points": [[.2, .2], [.8, .8]]}
        self.show([lower, upper])
        self.editor.set_mode("select")
        self.drag((.5, .5), (.5, .5))
        self.assertEqual(self.editor.selected, upper["id"])
        self.drag((.5, .5), (.5, .6))
        moved = {r["id"]: r for r in self.records}
        self.assertEqual(moved[lower["id"]]["points"], lower["points"])
        self.assertNotEqual(moved[upper["id"]]["points"], upper["points"])
        self.assertEqual(len(self.commits), 1)

    def test_a_line_layered_below_loses_to_one_above_at_the_same_place(self):
        self.build()
        below = {**LINE, "id": "00000000-0000-4000-8000-0000000000b1", "layer": "below",
                 "points": [[.2, .2], [.8, .8]]}
        above = {**LINE, "id": "00000000-0000-4000-8000-0000000000b2", "points": [[.2, .2], [.8, .8]]}
        self.show([above, below])
        self.editor.set_mode("select")
        self.drag((.5, .5), (.5, .5))
        self.assertEqual(self.editor.selected, above["id"])

    def test_the_hit_tolerance_is_five_points_at_any_dpi(self):
        for dpi in (72, 100, 200):
            with self.subTest(dpi=dpi):
                self.dpi = dpi
                self.build()
                self.show([deepcopy(LINE)])
                self.editor.set_mode("select")
                start, end = (self.axes.transAxes.transform(p) for p in LINE["points"])
                middle = (start + end) / 2
                normal = (end - start)[::-1] * [1, -1]
                normal = normal / np.linalg.norm(normal)
                for distance, expected in ((4, LINE["id"]), (9, None)):
                    self.editor.selected = None
                    point = middle + normal * distance * dpi / 72
                    event = MouseEvent("button_press_event", self.figure.canvas, *point, button=1)
                    self.figure.canvas.callbacks.process("button_press_event", event)
                    self.assertEqual(self.editor.selected, expected, (dpi, distance))
                    self.editor.cancel()
                self.editor.close()

    def test_handle_grab_distance_follows_the_dpi(self):
        self.dpi = 200
        self.build()
        self.show([deepcopy(BOX)])
        self.editor.set_mode("select")
        self.drag((.5, .5), (.5, .5))  # Filled box: the interior selects it.
        self.assertEqual(self.editor.selected, BOX["id"])
        corner = self.axes.transAxes.transform(BOX["points"][0])
        near = corner + [10 * self.dpi / 72, 0]  # 10 pt from the corner: beyond the 7 pt handle radius
        far_event = MouseEvent("button_press_event", self.figure.canvas, *near, button=1)
        self.editor.gesture = None
        self.figure.canvas.callbacks.process("button_press_event", far_event)
        self.assertEqual(self.editor.gesture["kind"], "move")
        self.editor.cancel()
        close = corner + [5 * self.dpi / 72, 0]
        event = MouseEvent("button_press_event", self.figure.canvas, *close, button=1)
        self.figure.canvas.callbacks.process("button_press_event", event)
        self.assertEqual(self.editor.gesture["kind"], "resize")


class AxisTests(Harness):
    def test_creating_on_a_log_axis_with_inverted_limits_keeps_the_screen_rectangle(self):
        self.build(xscale="log", yscale="log", invert=True, limits=((.1, 1000), (.1, 1000)))
        self.editor.set_mode("rectangle")
        self.drag((.2, .3), (.7, .8))
        (x1, y1), (x2, y2) = self.records[0]["points"]
        self.assertEqual(self.records[0]["units"], "axes")
        np.testing.assert_allclose([x1, y1, x2, y2], [.2, .3, .7, .8], atol=.01)

    def test_moving_a_data_record_on_log_and_inverted_axes_is_a_screen_translation(self):
        self.build(xscale="log", yscale="log", invert=True, limits=((.1, 1000), (.1, 1000)))
        record = {**BOX, "units": "data", "points": [[1., 1.], [100., 100.]]}
        self.show([record])
        self.editor.set_mode("select")
        before = self.axes.transData.transform(record["points"])
        self.drag((10., 10.), (10., 10.), data=True)
        self.assertEqual(self.editor.selected, BOX["id"])
        self.drag((10., 10.), (30., 30.), data=True)
        after = self.axes.transData.transform(self.records[0]["points"])
        delta = after - before
        np.testing.assert_allclose(delta[0], delta[1], atol=1e-6)
        self.assertTrue(np.all(self.records[0]["points"][0] != record["points"][0]))

    def test_a_data_shape_cannot_be_dragged_off_a_log_domain(self):
        self.build(xscale="log", yscale="log", limits=((.1, 1000), (.1, 1000)))
        record = {**BOX, "units": "data", "points": [[1., 1.], [100., 100.]]}
        self.show([record])
        self.editor.set_mode("select")
        self.drag((10., 10.), (10., 10.), data=True)
        self.event("button_press_event", (10., 10.), data=True)
        self.event("motion_notify_event", (-5., 10.), data=True)
        self.event("button_release_event", (-5., 10.), data=True)
        self.assertEqual(self.commits, [])
        self.assertEqual(self.records, validate_shapes([record]))


class ModifierAndLifecycleTests(Harness):
    def test_qt_style_events_report_modifiers_not_a_key(self):
        class Event:
            key = None
            modifiers = frozenset({"ctrl", "shift"})
        self.assertEqual(event_key(Event()), "ctrl+shift")
        Event.key, Event.modifiers = "control", frozenset()
        self.assertEqual(event_key(Event()), "ctrl")
        Event.key = None
        self.assertEqual(event_key(Event()), "")

    def test_ctrl_modifier_from_the_event_makes_a_square(self):
        self.build()
        self.editor.set_mode("rectangle")
        pixel_a = self.axes.transAxes.transform((.2, .2))
        pixel_b = self.axes.transAxes.transform((.5, .8))
        for name, pixel in (("button_press_event", pixel_a), ("motion_notify_event", pixel_b),
                            ("button_release_event", pixel_b)):
            event = MouseEvent(name, self.figure.canvas, *pixel, button=1, modifiers=["ctrl"])
            self.figure.canvas.callbacks.process(name, event)
        points = self.axes.transAxes.transform(self.records[0]["points"])
        self.assertAlmostEqual(abs(points[1, 0] - points[0, 0]), abs(points[1, 1] - points[0, 1]), places=3)

    def test_ctrl_and_shift_constrain_a_move_through_event_modifiers(self):
        self.build()
        self.show([deepcopy(BOX)])
        self.editor.set_mode("select")
        self.drag((.5, .5), (.5, .5))
        start = self.axes.transAxes.transform((.5, .5))
        end = self.axes.transAxes.transform((.6, .6))
        before = np.asarray(self.records[0]["points"])
        for name, pixel in (("button_press_event", start), ("motion_notify_event", end),
                            ("button_release_event", end)):
            event = MouseEvent(name, self.figure.canvas, *pixel, button=1, modifiers=["ctrl"])
            self.figure.canvas.callbacks.process(name, event)
        after = np.asarray(self.records[0]["points"])
        self.assertTrue(np.allclose(after[:, 1], before[:, 1]))
        self.assertFalse(np.allclose(after[:, 0], before[:, 0]))

    def test_a_twin_axis_over_the_plot_does_not_hide_it_from_the_pointer(self):
        self.build()
        twin = self.axes.twinx()
        twin.plot([1, 2, 3], [10, 20, 30])
        self.figure.canvas.draw()
        self.editor.set_mode("rectangle")
        for name, point in (("button_press_event", (.2, .2)), ("motion_notify_event", (.7, .8)),
                            ("button_release_event", (.7, .8))):
            pixel = self.axes.transAxes.transform(point)
            event = MouseEvent(name, self.figure.canvas, *pixel, button=1)
            self.assertIs(event.inaxes, twin)  # The topmost axes, not the one the shapes belong to.
            self.figure.canvas.callbacks.process(name, event)
        self.assertEqual(len(self.records), 1)

    def test_a_press_outside_the_plot_starts_nothing(self):
        self.build()
        self.editor.set_mode("rectangle")
        event = MouseEvent("button_press_event", self.figure.canvas, 5, 5, button=1)
        self.figure.canvas.callbacks.process("button_press_event", event)
        self.assertIsNone(self.editor.gesture)

    def test_a_commit_that_closes_the_controller_does_not_touch_it_again(self):
        self.build()
        self.editor.commit = lambda records: (self.commit(records), self.editor.close())
        self.editor.set_mode("rectangle")
        self.drag((.2, .2), (.6, .6))
        self.assertEqual(len(self.records), 1)
        self.assertIsNone(self.editor.mode)

    def test_a_lost_pointer_event_after_close_is_ignored(self):
        self.build()
        self.editor.set_mode("line")
        self.event("button_press_event", (.2, .2))
        self.editor.close()
        self.event("motion_notify_event", (.6, .6))
        self.event("button_release_event", (.6, .6))
        self.assertEqual(self.commits, [])
        self.assertFalse(getattr(self.axes, "_tramastat_shapes", []))

    def test_escape_cancels_a_drag_without_leaving_a_preview(self):
        self.build()
        self.editor.set_mode("ellipse")
        self.event("button_press_event", (.2, .2))
        self.event("motion_notify_event", (.6, .6))
        self.assertEqual(len(self.axes._tramastat_shapes), 1)
        self.editor.key("escape")
        self.assertEqual(self.editor.mode, "select")
        self.assertFalse(self.axes._tramastat_shapes)
        self.assertEqual(self.commits, [])


if __name__ == "__main__":
    unittest.main()
