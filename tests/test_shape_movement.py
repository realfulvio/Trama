"""Screen-space constrained movement and keyboard navigation, independent of data units."""
from copy import deepcopy
import unittest

import numpy as np
import tests.test_shape_canvas as fixtures
from analisi.presentation import apply_style


class ConstrainedDrawingMovement(unittest.TestCase):
    setUp = fixtures.ShapeCanvasTests.setUp
    commit = fixtures.ShapeCanvasTests.commit
    event = fixtures.ShapeCanvasTests.event
    drag = fixtures.ShapeCanvasTests.drag

    def load_box(self):
        self.records = [deepcopy(fixtures.BOX)]
        self.commits.clear()
        apply_style(self.figure, {'shapes': self.records})
        self.figure.canvas.draw()
        self.editor.set_mode('select')

    def test_ctrl_horizontal_and_shift_vertical_keep_size_identity_and_style(self):
        for key, offset in [('control', [.05, 0]), ('ctrl', [.05, 0]), ('shift', [0, .06])]:
            with self.subTest(key=key):
                self.load_box()
                before = deepcopy(self.records[0])
                self.drag((.5, .5), (.55, .56), key=key)
                self.assertEqual(len(self.commits), 1)

                after = self.records[0]
                np.testing.assert_allclose(np.array(after['points']) - before['points'],
                                           [offset, offset], atol=.006)
                self.assertEqual({k: v for k, v in after.items() if k != 'points'},
                                 {k: v for k, v in before.items() if k != 'points'})

    def test_ignored_component_outside_axes_does_not_reject_a_valid_horizontal_move(self):
        self.load_box()
        before = deepcopy(self.records)
        self.drag((.5, .5), (.55, 1.5), key='control')
        self.assertEqual(len(self.commits), 1)
        np.testing.assert_allclose(np.array(self.records[0]['points'])[:, 1],
                                   np.array(before[0]['points'])[:, 1], atol=1e-12)

    def test_orthogonal_pointer_motion_is_an_exact_no_op(self):
        self.load_box()
        before = deepcopy(self.records)
        self.drag((.5, .5), (.5, .7), key='control')
        self.assertEqual(self.records, before)
        self.assertEqual(self.commits, [])

    def test_both_modifiers_leave_movement_unconstrained(self):
        self.load_box()
        before = deepcopy(self.records)
        self.drag((.5, .5), (.55, .56), key='ctrl+shift')
        np.testing.assert_allclose(np.array(self.records[0]['points']) - before[0]['points'],
                                   [[.05, .06], [.05, .06]], atol=.006)

    def test_reversed_log_data_axes_constrain_in_display_coordinates(self):
        self.axes.set(xscale='log', xlim=(100, 1), ylim=(10, 0))
        self.records = [{**fixtures.LINE, 'units': 'data', 'points': [[2., 3.], [20., 7.]]}]
        apply_style(self.figure, {'shapes': self.records})
        self.figure.canvas.draw()
        self.editor.set_mode('select')
        pixels = self.axes.transData.transform(self.records[0]['points'])
        start = self.axes.transAxes.inverted().transform(pixels.mean(axis=0))
        self.drag(start, start + [.05, .08], key='control')
        after = self.axes.transData.transform(self.records[0]['points'])
        np.testing.assert_allclose(after[:, 1], pixels[:, 1], atol=1e-10)
        np.testing.assert_allclose(after[:, 0] - pixels[:, 0], [.05 * self.axes.bbox.width] * 2, atol=1.)

    def test_ctrl_arrows_nudge_ten_pixels_and_shift_alias_keeps_working(self):
        for key, delta in [('ctrl+right', [10, 0]), ('control+up', [0, 10]), ('shift+left', [-10, 0])]:
            with self.subTest(key=key):
                self.load_box()
                self.editor.selected = self.records[0]['id']
                before = self.axes.transAxes.transform(self.records[0]['points'])
                self.editor.key(key)
                after = self.axes.transAxes.transform(self.records[0]['points'])
                np.testing.assert_allclose(after - before, [delta, delta], atol=1e-10)
                self.assertEqual(len(self.commits), 1)

class ConstrainedMovementTk(unittest.TestCase):
    def test_real_control_arrow_binding_does_not_bubble_and_restores_previous_handler(self):
        import tkinter as tk
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from analisi.shape_canvas import ShapeCanvas
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        figure = Figure(figsize=(4, 3), dpi=100)
        axes = figure.add_subplot()
        canvas = FigureCanvasTkAgg(figure, master=root)
        widget = canvas.get_tk_widget()
        widget.pack()
        records = [deepcopy(fixtures.BOX)]
        prior, bubbled = [], []
        widget.bind('<Control-Right>', lambda event: prior.append(True))
        root.bind('<Control-Right>', lambda event: bubbled.append(True))
        controller = ShapeCanvas(canvas, axes, records=lambda: deepcopy(records),
                                 commit=lambda new: records.__setitem__(slice(None), new), status=lambda text: None)
        self.addCleanup(controller.close)
        apply_style(figure, {'shapes': records})
        root.update()
        canvas.draw()
        controller.set_mode('select')
        controller.selected = records[0]['id']
        widget.focus_force()
        root.update()
        before = axes.transAxes.transform(records[0]['points'])
        widget.event_generate('<Control-Right>')
        root.update()
        np.testing.assert_allclose(axes.transAxes.transform(records[0]['points']) - before,
                                   [[10, 0], [10, 0]], atol=1e-10)
        self.assertEqual((prior, bubbled), ([], []))
        controller.set_mode(None)
        widget.event_generate('<Control-Right>')
        root.update()
        self.assertEqual((prior, bubbled), ([True], [True]))

