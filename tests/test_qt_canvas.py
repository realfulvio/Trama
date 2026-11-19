"""Pointer drawing on the Qt graph canvas, driven with real mouse and key events (offscreen).

A rectangle already stored in the fixture must survive untouched; new shapes, moves, resizes, the clipboard,
Undo/Redo of one graph, sheet changes, export and reopening all go through the widgets a person would use.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np

from analisi.graph_shapes import SHAPES
from analisi.i18n import tr
from analisi.shape_clipboard import dump_shape

FIXTURE = Path(__file__).resolve().parent / "data" / "qt_canvas" / "grafico.alab"
HANDLE = (0x17, 0x66, 0x76)  # Selection handle edge colour of the shared controller.


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-canvas-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from analisi.i18n import set_language
        from trama_qt.window import MainWindow
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "grafico.alab"
        shutil.copy(FIXTURE, self.path)
        self.window = MainWindow()
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1000, 700)
        self.window.show()
        self.addCleanup(self._close)
        self.window.open_path(self.path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.window.project.dirty = False

    def _close(self):
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def wait(self, timeout=60):
        """Until no calculation runs, also after the events a finished one queues (a refresh can follow an edit)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QTest.qWait(30)
            if self.window.job is None:
                QTest.qWait(30)
                if self.window.job is None:
                    return
        self.fail("calculation still running")

    # -- helpers ---------------------------------------------------------------------------------------
    @property
    def graph(self):
        return self.window.project.runs[0]

    @property
    def canvas(self):
        canvas, = self.window.page.canvases
        return canvas

    @property
    def shapes(self):
        return deepcopy((self.graph.style or {}).get(SHAPES, []))

    def point(self, fraction):
        x, y = self.graph.result.figure.axes[0].transAxes.transform(fraction)
        ratio = self.canvas.device_pixel_ratio
        return QPoint(round(x / ratio), self.canvas.height() - round(y / ratio))

    def tool(self, name):
        self.window.actions[f"draw_{name}"].trigger()
        self.app.processEvents()

    def drag(self, start, end, *, modifier=Qt.KeyboardModifier.NoModifier, steps=40):
        canvas = self.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifier, self.point(start))
        QTest.mouseMove(canvas, self.point(end), steps)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifier, self.point(end))
        self.app.processEvents()

    def press_move(self, start, end):
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point(start))
        QTest.mouseMove(self.canvas, self.point(end), 40)
        self.app.processEvents()

    def draw_rectangle(self, start=(.55, .52), end=(.83, .79)):
        self.tool("rectangle")
        self.drag(start, end)
        return self.shapes[-1]

    def click(self, fraction):
        self.drag(fraction, fraction, steps=-1)

    def drawn_ids(self):
        axes = self.graph.result.figure.axes[0]
        return [str(a.get_gid()).removeprefix("tramastat-shape-") for a in getattr(axes, "_tramastat_shapes", ())]

    def svg_ids(self, path):
        return re.findall(r'id="tramastat-shape-([0-9a-f-]+)"', Path(path).read_text(encoding="utf-8"))

    def export_to(self, name):
        path = self.folder / name
        chosen = {"svg": "SVG (*.svg)", "pdf": "PDF (*.pdf)", "png": "PNG (*.png)"}[path.suffix[1:]]
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(path), chosen)):
            self.window.export()
        self.assertEqual(self.errors, [])
        self.assertTrue(path.exists() and path.stat().st_size > 0)
        return path

    # -- creation ------------------------------------------------------------------------------------
    def test_drawing_a_rectangle_adds_one_shape_and_keeps_the_stored_one(self):
        original, = self.shapes
        new = self.draw_rectangle()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.shapes), 2)
        self.assertEqual(self.shapes[0], original)
        self.assertNotEqual(new["id"], original["id"])
        self.assertEqual((new["kind"], new["units"]), ("rectangle", "axes"))
        for pair, wanted in zip(new["points"], ((.55, .52), (.83, .79)), strict=True):
            self.assertTrue(np.allclose(pair, wanted, atol=.035), pair)
        self.assertTrue(self.window.project.dirty)
        self.assertEqual(self.window.project.tables["Misure"].graph_styles[0][SHAPES], self.shapes)
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, [original])
        self.assertEqual(self.drawn_ids(), [original["id"]])
        self.assertFalse(self.window.project.runs[1].style)

    def test_every_tool_draws_its_kind(self):
        for name, kind in (("line", "line"), ("arrow", "line"), ("rectangle", "rectangle"), ("ellipse", "ellipse")):
            with self.subTest(tool=name):
                self.tool(name)
                self.drag((.2, .6), (.5, .9))
                self.assertEqual(self.shapes[-1]["kind"], kind)
                if name == "arrow":
                    self.assertEqual(self.shapes[-1]["arrow_heads"], "end")
        self.assertEqual(len(self.shapes), 5)
        self.assertEqual(len(set(s["id"] for s in self.shapes)), 5)

    def test_a_tool_returns_to_select_after_one_shape_but_shift_keeps_it(self):
        self.tool("rectangle")
        self.drag((.5, .5), (.7, .7))
        self.assertTrue(self.window.actions["draw_select"].isChecked())
        self.tool("line")
        self.drag((.5, .5), (.7, .7), modifier=Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(self.window.actions["draw_line"].isChecked())

    def test_a_click_without_a_drag_and_a_drag_outside_commit_nothing(self):
        before = self.shapes
        self.tool("rectangle")
        self.click((.5, .5))
        self.drag((.5, .5), (1.4, .7))
        self.assertEqual(self.shapes, before)
        self.assertFalse(self.window.project.dirty)
        self.assertFalse(self.window.project.runs[0].shape_history.changes)
        self.assertEqual(self.drawn_ids(), [before[0]["id"]])

    def test_ctrl_makes_a_square_from_the_real_modifier(self):
        self.tool("rectangle")
        self.drag((.5, .3), (.7, .9), modifier=Qt.KeyboardModifier.ControlModifier)
        axes = self.graph.result.figure.axes[0]
        pixels = axes.transAxes.transform(self.shapes[-1]["points"])
        self.assertAlmostEqual(abs(pixels[1, 0] - pixels[0, 0]), abs(pixels[1, 1] - pixels[0, 1]), delta=1.5)

    # -- select, move, resize --------------------------------------------------------------------------
    def test_moving_keeps_identity_unit_and_style(self):
        original, = self.shapes
        self.tool("select")
        self.drag((.27, .23), (.47, .43))
        moved, = self.shapes
        self.assertEqual(moved["id"], original["id"])
        for key in ("kind", "units", "stroke", "width", "fill", "alpha", "layer", "hatch", "hatch_color"):
            self.assertEqual(moved[key], original[key], key)
        self.assertTrue(np.allclose(np.array(moved["points"]) - original["points"], .2, atol=.04))
        self.assertEqual(len(self.window.project.runs[0].shape_history.changes), 1)

    def test_resizing_from_a_corner_moves_only_that_corner(self):
        original, = self.shapes
        self.tool("select")
        self.click((.27, .23))
        self.assertEqual(self.errors, [])
        self.drag((.40, .32), (.55, .50))
        resized, = self.shapes
        self.assertEqual(resized["points"][0], original["points"][0])
        self.assertTrue(np.allclose(resized["points"][1], (.55, .50), atol=.035))
        self.assertEqual(resized["id"], original["id"])

    def test_each_drag_is_one_undo_step_in_order(self):
        original, = self.shapes
        self.tool("select")
        self.drag((.27, .23), (.37, .33))
        first = self.shapes
        self.drag((.37, .33), (.47, .43))
        second = self.shapes
        self.assertNotEqual(first, second)
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, first)
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, [original])
        self.assertFalse(self.window.actions["undo"].isEnabled())
        self.window.actions["redo"].trigger()
        self.window.actions["redo"].trigger()
        self.assertEqual(self.shapes, second)
        self.assertEqual(self.drawn_ids(), [original["id"]])

    def test_the_arrow_keys_nudge_one_pixel_and_ctrl_ten_in_one_step_each(self):
        self.tool("select")
        self.click((.27, .23))
        before = self.shapes[0]
        QTest.keyClick(self.canvas, Qt.Key.Key_Right)
        QTest.keyClick(self.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        axes = self.graph.result.figure.axes[0]
        moved = axes.transAxes.transform(self.shapes[0]["points"]) - axes.transAxes.transform(before["points"])
        self.assertTrue(np.allclose(moved[:, 0], 11 * self.canvas.device_pixel_ratio, atol=.6), moved)
        self.assertEqual(len(self.graph.shape_history.changes), 2)

    def test_delete_removes_the_selection_and_undo_brings_it_back(self):
        original, = self.shapes
        self.tool("select")
        self.click((.27, .23))
        QTest.keyClick(self.canvas, Qt.Key.Key_Delete)
        self.assertEqual(self.shapes, [])
        self.assertNotIn(SHAPES, self.graph.style or {})
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, [original])

    def test_delete_does_nothing_with_no_tool_on(self):
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_Delete)
        self.assertEqual(len(self.shapes), 1)

    def test_escape_cancels_a_drag_and_a_second_escape_leaves_the_tools(self):
        original, = self.shapes
        self.tool("rectangle")
        self.press_move((.5, .5), (.7, .7))
        self.assertEqual(len(self.drawn_ids()), 2)  # The preview.
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point((.7, .7)))
        self.assertEqual(self.shapes, [original])
        self.assertEqual(self.drawn_ids(), [original["id"]])
        self.assertTrue(self.window.actions["draw_select"].isChecked())
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.drawing.controller.mode)
        self.assertFalse(self.window.actions["draw_select"].isChecked())

    def test_losing_focus_during_a_drag_cancels_the_preview(self):
        original, = self.shapes
        self.tool("ellipse")
        self.press_move((.5, .5), (.7, .7))
        self.assertEqual(len(self.drawn_ids()), 2)
        QApplication.sendEvent(self.canvas, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
        self.assertEqual(self.drawn_ids(), [original["id"]])
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.point((.7, .7)))
        self.assertEqual(self.shapes, [original])

    def test_a_double_click_opens_the_numeric_editor_and_ok_commits_one_step(self):
        from trama_qt.shapes import ShapeEditor
        original, = self.shapes
        self.tool("select")
        opened = []

        def accept(dialog):
            opened.append(dialog.record["id"])
            dialog.result = {**dialog.record, "width": 3.0}
            return ShapeEditor.DialogCode.Accepted

        with mock.patch.object(ShapeEditor, "exec", accept):
            QTest.mouseDClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                              self.point((.27, .23)))
            self.app.processEvents()
        self.assertEqual(opened, [original["id"]])
        self.assertEqual(self.shapes[0]["width"], 3.0)
        self.assertEqual(len(self.graph.shape_history.changes), 1)
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, [original])

    # -- undo is separate from the grid and from other graphs -----------------------------------------
    def test_undo_on_a_graph_leaves_the_worksheet_history_alone(self):
        self.window.open_sheet(("data", "Misure"))
        model = self.window.sheet.model()
        self.assertTrue(model.setData(model.index(0, 1), "4"))
        self.wait()
        position = self.window.project.history.position
        self.assertTrue(self.window.project.history.can_apply())
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.window.project.dirty = False
        self.draw_rectangle()
        self.assertEqual(len(self.shapes), 2)
        self.window.actions["undo"].trigger()
        self.assertEqual(len(self.shapes), 1)
        self.assertEqual(self.window.project.history.position, position)
        self.assertEqual(self.window.project.tables["Misure"].raw.iat[0, 1], 4)
        self.window.open_sheet(("data", "Misure"))
        self.wait()
        self.window.actions["undo"].trigger()
        self.wait()
        self.assertEqual(self.window.project.tables["Misure"].raw.iat[0, 1], 3)
        self.assertEqual(len(self.shapes), 1)

    def test_the_shape_history_is_not_carried_to_another_graph_or_the_grid(self):
        self.draw_rectangle()
        self.assertTrue(self.window.actions["undo"].isEnabled())
        self.window.open_sheet(("graph", 1))
        self.wait()
        self.assertFalse(self.window.actions["undo"].isEnabled())
        self.assertIsNone(self.window.drawing.history_run())
        self.window.open_sheet(("data", "Misure"))
        self.assertFalse(self.window.actions["undo"].isEnabled())
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertTrue(self.window.actions["undo"].isEnabled())
        self.assertEqual(len(self.window.project.runs[0].shape_history.changes), 1)

    def test_ctrl_z_and_ctrl_y_keys_on_the_canvas_reach_the_graph_history(self):
        self.draw_rectangle()
        self.window.activateWindow()
        self.canvas.setFocus()
        QTest.keyClick(self.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.shapes), 1)
        QTest.keyClick(self.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.shapes), 2)

    def test_a_recalculation_keeps_the_graph_history(self):
        self.draw_rectangle()
        history = self.graph.shape_history
        candidate = self.window.project.candidate("Misure", self.graph.method, dict(self.graph.options), index=0)
        self.window.project.add_result(candidate, self.graph.result, 0)
        self.assertIs(self.window.project.runs[0].shape_history, history)
        self.assertEqual(len(history.changes), 1)

    # -- clipboard -------------------------------------------------------------------------------------
    def test_copy_then_paste_adds_a_new_identity_in_one_step(self):
        original, = self.shapes
        self.tool("select")
        self.click((.27, .23))
        self.window.actions["shape_copy"].trigger()
        self.assertEqual(self.errors, [])
        copied = json.loads(QApplication.clipboard().text())
        self.assertEqual((copied["format"], copied["shape"]["id"]), ("TramaStat/native-drawing", original["id"]))
        self.window.actions["shape_paste"].trigger()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.shapes), 2)
        self.assertNotEqual(self.shapes[1]["id"], original["id"])
        self.assertEqual(self.shapes[0], original)
        self.assertEqual(self.window.drawing.controller.selected, self.shapes[1]["id"])
        self.assertEqual(len(self.graph.shape_history.changes), 1)
        self.window.actions["undo"].trigger()
        self.assertEqual(self.shapes, [original])

    def test_cut_removes_and_the_keys_copy_and_paste_work_on_the_canvas(self):
        original, = self.shapes
        self.tool("select")
        self.click((.27, .23))
        QTest.keyClick(self.canvas, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.shapes, [])
        QTest.keyClick(self.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.shapes), 1)
        self.assertNotEqual(self.shapes[0]["id"], original["id"])
        self.assertEqual({k: v for k, v in self.shapes[0].items() if k != "id"},
                         {k: v for k, v in original.items() if k != "id"})

    def test_an_invalid_clipboard_changes_nothing(self):
        before = self.shapes
        self.tool("select")
        for text in ("", "hello", '{"kind": "rectangle"}', "[1, 2]", '{"version": 99}'):
            self.errors.clear()
            QApplication.clipboard().setText(text)
            self.window.actions["shape_paste"].trigger()
            self.assertEqual(len(self.errors), 1, text)
            self.assertEqual(self.shapes, before)
        self.assertFalse(self.graph.shape_history.changes)
        self.assertEqual(self.drawn_ids(), [before[0]["id"]])

    def test_a_shape_outside_the_axis_domain_is_not_pasted(self):
        self.tool("select")
        self.graph.result.figure.axes[0].set_xscale("log")
        record = {**self.shapes[0], "units": "data", "points": [[-5., 2.], [3., 4.]]}
        QApplication.clipboard().setText(dump_shape(record))
        before = self.shapes
        self.window.actions["shape_paste"].trigger()
        self.assertEqual(self.errors, [tr("shape.error.axis_domain")])
        self.assertEqual(self.shapes, before)
        self.assertFalse(self.graph.shape_history.changes)

    def test_a_shape_outside_the_plot_fractions_is_not_pasted(self):
        self.tool("select")
        text = json.dumps({"format": "TramaStat/native-drawing", "version": 1,
                           "shape": {**self.shapes[0], "points": [[-.5, .2], [.5, .5]]}})
        QApplication.clipboard().setText(text)
        before = self.shapes
        self.window.actions["shape_paste"].trigger()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.shapes, before)

    def test_a_failed_clipboard_write_leaves_the_drawings_intact(self):
        before = self.shapes
        self.tool("select")
        self.click((.27, .23))

        class Broken:
            def setText(self, text):
                pass

            def text(self):
                return "something else"

        with mock.patch("trama_qt.shape_canvas.QApplication.clipboard", return_value=Broken()):
            self.window.actions["shape_cut"].trigger()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.shapes, before)
        self.assertFalse(self.graph.shape_history.changes)

    def test_copy_without_a_selection_says_what_to_do(self):
        self.tool("select")
        self.window.actions["shape_copy"].trigger()
        self.assertEqual(self.errors, [tr("shape.clipboard.select")])

    # -- context menu ----------------------------------------------------------------------------------
    def test_the_context_menu_edits_one_property_and_duplicates(self):
        original, = self.shapes
        self.tool("select")
        drawing = self.window.drawing
        self.assertTrue(drawing.change(original["id"], "width", 4.0))
        self.assertEqual(self.shapes[0]["width"], 4.0)
        self.assertTrue(drawing.change(original["id"], "duplicate"))
        self.assertEqual(len(self.shapes), 2)
        self.assertNotEqual(self.shapes[1]["id"], original["id"])
        self.assertTrue(drawing.change(original["id"], "back"))
        self.assertEqual(self.shapes[0]["layer"], "below")
        self.assertEqual(len(self.graph.shape_history.changes), 3)
        menu = drawing.context_menu(original["id"])
        self.addCleanup(menu.deleteLater)
        titles = [action.text() for action in menu.actions() if action.text()]
        self.assertIn(tr("shape.context.format"), titles)
        self.assertIn(tr("shape.clipboard.copy"), titles)
        self.assertIn(tr("shape.context.remove"), titles)

    def test_a_right_click_selects_without_changing_the_model(self):
        shown = []
        self.window.drawing.popup = lambda menu, position: (shown.append([a.text() for a in menu.actions()]),
                                                           menu.deleteLater())
        before = self.shapes
        QTest.mouseClick(self.canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                         self.point((.27, .23)))
        self.assertEqual(self.shapes, before)
        self.assertEqual(self.window.drawing.controller.selected, before[0]["id"])
        self.assertEqual(len(shown), 1)
        self.assertFalse(self.graph.shape_history.changes)

    # -- sheets, pages and scopes ---------------------------------------------------------------------
    def test_changing_sheet_during_a_drag_closes_the_preview(self):
        original, = self.shapes
        figure = self.graph.result.figure
        self.tool("rectangle")
        self.press_move((.5, .5), (.7, .7))
        self.assertEqual(len(self.drawn_ids()), 2)
        controller = self.window.drawing.controller
        self.window.open_sheet(("data", "Misure"))
        self.assertIsNone(self.window.drawing.controller)
        self.assertEqual(controller.mode, None)
        self.assertEqual([str(a.get_gid()).removeprefix("tramastat-shape-")
                          for a in figure.axes[0]._tramastat_shapes], [original["id"]])
        self.assertEqual(self.shapes, [original])
        self.assertFalse(self.window.project.dirty)

    def test_leaving_to_the_grid_and_coming_back_starts_with_the_tools_off(self):
        self.tool("select")
        self.window.open_sheet(("data", "Misure"))
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertFalse(self.window.actions["draw_select"].isChecked())
        self.assertIsNone(self.window.drawing.controller.mode)
        self.assertTrue(self.window.actions["draw_select"].isEnabled())

    def test_the_tools_are_off_on_data_and_layout_pages(self):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        self.window.open_sheet(("data", "Misure"))
        for name in ("select", "line", "arrow", "rectangle", "ellipse"):
            self.assertFalse(self.window.actions[f"draw_{name}"].isEnabled(), name)
        runs = self.window.project.runs
        key = self.window.project.put_layout(Layout("Figure 1", 2, [runs[0].reference, runs[1].reference],
                                                    AUTO_PAPER, WHITE))
        self.window.open_sheet(("layout", key))
        self.wait()
        self.assertIsNone(self.window.drawing.controller)
        self.assertFalse(self.window.actions["draw_rectangle"].isEnabled())
        self.assertEqual(len(self.window.page.canvases), 1)  # The page still shows its figure.

    def test_an_axis_break_names_the_reason_and_disables_the_tools(self):
        from analisi.axis_breaks import AXIS_BREAKS, segment_axes
        style = deepcopy(self.graph.style)
        style.pop(SHAPES)  # Shapes in plot fractions cannot be combined with axis breaks.
        style[AXIS_BREAKS] = {"axis": "y", "gap": .03, "segments": [
            {"low": 2, "high": 8, "share": 50}, {"low": 10, "high": 14, "share": 50}]}
        self.window.project.apply_format(self.graph, style)
        self.window.show_sheet("graph", 0)
        self.assertTrue(segment_axes(self.graph.result.figure))
        self.assertIsNone(self.window.drawing.controller)
        self.assertFalse(self.window.actions["draw_rectangle"].isEnabled())
        self.assertIn(tr("axis_breaks.canvas_note"), self.window.actions["draw_rectangle"].toolTip())
        self.window.actions["draw_rectangle"].setEnabled(True)  # A forced trigger still refuses, with the reason.
        self.window.drawing.start("rectangle")
        self.assertEqual(self.errors, [tr("axis_breaks.canvas_note")])
        self.assertNotIn(SHAPES, self.graph.style)
        self.assertTrue(self.window.actions["shapes"].isEnabled())  # The numeric editor stays reachable.

    def test_an_imported_graph_is_out_of_scope(self):
        from analisi.prism_restore import SAVED_XY
        self.graph.method = SAVED_XY
        self.addCleanup(setattr, self.graph, "method", "XY series")
        self.window.update_actions()
        self.assertFalse(self.window.actions["draw_rectangle"].isEnabled())
        self.assertEqual(self.window.drawing.problem(), tr("shape.native"))

    def test_a_twin_axis_graph_is_out_of_scope_with_a_reason(self):
        axes = self.graph.result.figure.axes[0]
        axes.twinx()
        self.window.drawing.attach(self.window.page, self.canvas, None, self.graph)
        self.assertIsNone(self.window.drawing.controller)
        self.assertIn("single-panel", self.window.drawing.problem())

    def test_a_pending_calculation_blocks_the_tools_and_a_preview_is_closed(self):
        original, = self.shapes
        self.tool("rectangle")
        self.press_move((.5, .5), (.7, .7))
        self.window.recalculate()
        self.assertEqual(self.errors, [])
        self.wait()
        self.assertEqual(self.shapes, [original])
        self.assertEqual(self.drawn_ids(), [original["id"]])
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           self.point((.7, .7)))
        self.assertEqual(self.shapes, [original])

    def test_the_inspector_draft_blocks_a_new_gesture(self):
        self.window.toggle_inspector()
        self.app.processEvents()
        inspector = self.window.inspector
        self.assertIsNotNone(inspector)
        with mock.patch.object(type(inspector), "has_draft", new_callable=mock.PropertyMock, return_value=True):
            self.assertFalse(self.window.drawing.allowed())

    # -- handles never leave the screen ---------------------------------------------------------------
    def handle_pixels(self):
        self.canvas.draw()
        image = self.canvas.grab().toImage()
        count = 0
        for x in range(image.width()):
            for y in range(image.height()):
                colour = image.pixelColor(x, y)
                if abs(colour.red() - HANDLE[0]) < 8 and abs(colour.green() - HANDLE[1]) < 8 \
                        and abs(colour.blue() - HANDLE[2]) < 8:
                    count += 1
        return count

    def test_the_handles_show_on_screen_but_in_no_export_or_saved_file(self):
        self.draw_rectangle()
        selected = self.window.drawing.controller.selected
        self.assertEqual(selected, self.shapes[-1]["id"])
        self.assertGreater(self.handle_pixels(), 8)  # Two square handles at least.
        svg = self.export_to("canvas.svg")
        self.assertNotIn("#176676", svg.read_text(encoding="utf-8").lower())
        self.assertEqual(sorted(self.svg_ids(svg)), sorted(s["id"] for s in self.shapes))
        png = self.export_to("canvas.png")
        pdf = self.export_to("canvas.pdf")
        from PIL import Image
        with Image.open(png) as image:
            pixels = np.asarray(image.convert("RGB")).astype(int)
        near = (np.abs(pixels - HANDLE).max(axis=2) < 6)
        self.assertEqual(int(near.sum()), 0, "selection handles leaked into the PNG")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertGreater(self.handle_pixels(), 8)  # Exporting leaves the on-screen handles in place.
        self.assertTrue(self.window.save())
        saved = self.path.read_text(encoding="utf-8")
        self.assertNotIn("176676", saved.lower())
        stored = json.loads(saved)["tables"][0]["graph_styles"]["0"]["shapes"]
        self.assertEqual(stored, self.shapes)

    def test_an_export_during_a_drag_leaves_the_preview_out(self):
        original, = self.shapes
        self.tool("rectangle")
        self.press_move((.5, .5), (.7, .7))
        svg = self.export_to("during.svg")
        self.assertEqual(self.svg_ids(svg), [original["id"]])
        self.assertEqual(self.shapes, [original])

    # -- persistence -----------------------------------------------------------------------------------
    def test_save_reopen_and_recalculate_preserve_every_shape_in_order(self):
        self.draw_rectangle()
        self.tool("arrow")
        self.drag((.2, .7), (.6, .9))
        expected = self.shapes
        self.assertEqual(len(expected), 3)
        self.assertTrue(self.window.save())
        self.window.project.dirty = False
        self.window.open_path(self.path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertEqual(self.shapes, expected)
        self.assertEqual(self.drawn_ids(), [s["id"] for s in expected])
        self.window.recalculate()
        self.wait()
        self.assertEqual(self.shapes, expected)
        self.assertEqual(self.drawn_ids(), [s["id"] for s in expected])
        self.assertEqual(self.shapes[0]["hatch"], "diagonal")
        self.assertEqual(self.shapes[0]["alpha"], 0.8)
        self.assertEqual(self.shapes[2]["arrow_heads"], "end")

    def test_the_stored_recipe_is_read_without_migration(self):
        stored = json.loads(FIXTURE.read_text(encoding="utf-8"))["tables"][0]["graph_styles"]["0"]["shapes"]
        self.assertEqual(self.shapes, stored)

    def test_shapes_stay_editable_from_the_numeric_editor_after_drawing(self):
        from trama_qt.shapes import GraphShapesDialog
        new = self.draw_rectangle()
        seen = []

        def capture(dialog):
            seen.append([r["id"] for r in dialog.records])
            dialog.reject()
            return GraphShapesDialog.DialogCode.Rejected

        with mock.patch.object(GraphShapesDialog, "exec", capture):
            self.window.actions["shapes"].trigger()
        self.assertEqual(seen, [[s["id"] for s in self.shapes]])
        self.assertEqual(seen[0][-1], new["id"])

    # -- actions ---------------------------------------------------------------------------------------
    def test_the_tool_actions_are_exclusive_and_toggle_off(self):
        self.tool("line")
        self.assertTrue(self.window.actions["draw_line"].isChecked())
        self.tool("ellipse")
        self.assertTrue(self.window.actions["draw_ellipse"].isChecked())
        self.assertFalse(self.window.actions["draw_line"].isChecked())
        self.assertEqual(self.window.drawing.controller.mode, "ellipse")
        self.window.actions["draw_ellipse"].trigger()
        self.assertIsNone(self.window.drawing.controller.mode)
        self.assertFalse(any(self.window.actions[f"draw_{n}"].isChecked()
                             for n in ("select", "line", "arrow", "rectangle", "ellipse")))

    def test_the_graph_toolbar_and_ribbon_offer_the_tools(self):
        page = self.window.page
        from PySide6.QtWidgets import QToolBar
        bars = page.findChildren(QToolBar)
        offered = {a for bar in bars for a in bar.actions()}
        self.assertTrue({self.window.actions[f"draw_{n}"] for n in ("select", "rectangle")} <= offered)
        ribbon = [a for bar in self.window.findChildren(QToolBar, "commandTools") for a in bar.actions()]
        self.assertIn(self.window.actions["draw"], ribbon)

    def test_zoom_or_pan_and_the_tools_do_not_run_together(self):
        tools = self.window.drawing.toolbar
        self.tool("select")
        tools.zoom()
        self.assertFalse(self.window.drawing.allowed())
        before = self.shapes
        self.drag((.27, .23), (.47, .43))
        self.assertEqual(self.shapes, before)
        tools.zoom()
        self.assertTrue(self.window.drawing.allowed())

    def test_starting_a_tool_turns_off_an_active_pan(self):
        tools = self.window.drawing.toolbar
        tools.pan()
        self.assertTrue(tools.mode)
        self.tool("select")
        self.assertFalse(tools.mode)
        self.assertTrue(self.window.actions["draw_select"].isChecked())

    # -- high DPI --------------------------------------------------------------------------------------
    def test_drawing_works_at_a_device_pixel_ratio_of_two(self):
        self.canvas._set_device_pixel_ratio(2)
        self.canvas.draw()
        self.app.processEvents()
        self.assertEqual(self.canvas.device_pixel_ratio, 2)
        new = self.draw_rectangle()
        for pair, wanted in zip(new["points"], ((.55, .52), (.83, .79)), strict=True):
            self.assertTrue(np.allclose(pair, wanted, atol=.035), pair)
        self.assertTrue(self.window.actions["draw_select"].isChecked())
        original = self.shapes[0]
        self.drag((.27, .23), (.47, .43))
        self.assertTrue(np.allclose(np.array(self.shapes[0]["points"]) - original["points"], .2, atol=.04))


if __name__ == "__main__":
    unittest.main()
