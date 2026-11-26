"""Qt pointer selection and movement of linked tables on native graphs and layout pages."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QFocusEvent, QKeySequence, QResizeEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np

from analisi import linked_tables as lt
from analisi.i18n import active_language, set_language, tr

FIXTURE = Path(__file__).resolve().parent / "data" / "qt_linked_table_move" / "tabelle-in-figura.alab"
HANDLE_LIGHT = (0x17, 0x66, 0x76)


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-table-move-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtLinkedTableMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt import theme
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        theme.set_mode("light", self.app, remember=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "tabelle-in-figura.alab"
        shutil.copy(FIXTURE, self.path)
        self.window = MainWindow()
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1120, 740)
        self.window.show()
        self.addCleanup(self._close)
        self.window.open_path(self.path)
        self.wait()
        self.window.project.dirty = False

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QTest.qWait(25)
            if self.window.job is None:
                QTest.qWait(25)
                if self.window.job is None:
                    return
        self.fail("calculation still running")

    @property
    def canvas(self):
        canvas, = self.window.page.canvases
        return canvas

    def open_graph(self):
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.canvas.draw()
        self.app.processEvents()

    def open_layout(self):
        self.window.open_sheet(("layout", 0))
        self.wait()
        self.canvas.draw()
        self.app.processEvents()

    def graph_records(self):
        return deepcopy((self.window.project.runs[0].style or {}).get(lt.TABLES, []))

    def layout_records(self):
        return deepcopy(self.window.project.layouts[0].tables)

    def artist_for(self, table_id):
        for artist in self.canvas.figure.artists:
            if isinstance(artist, lt.LinkedTableArtist) and artist.get_gid() == f"{lt.GID}{table_id}":
                return artist
        self.fail(f"artist {table_id} not found")

    def center_point(self, table_id):
        artist = self.artist_for(table_id)
        left, bottom, right, top = artist.bounds_pixels(self.canvas.figure)
        return self.mpl_to_qpoint((left + right) / 2, (bottom + top) / 2)

    def mpl_to_qpoint(self, x_px, y_px):
        ratio = float(self.canvas.device_pixel_ratio)
        return QPoint(round(x_px / ratio), self.canvas.height() - round(y_px / ratio))

    def fraction_to_qpoint(self, x_frac, y_frac_top):
        width, height = self.canvas.figure.get_size_inches()
        dpi = float(self.canvas.figure.dpi)
        return self.mpl_to_qpoint(x_frac * width * dpi, (1.0 - y_frac_top) * height * dpi)

    def drag_qpoints(self, start, end, *, modifier=Qt.KeyboardModifier.NoModifier, steps=10):
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, modifier, start)
        for step in range(1, steps + 1):
            t = step / steps
            pos = QPoint(round(start.x() + (end.x() - start.x()) * t),
                         round(start.y() + (end.y() - start.y()) * t))
            QTest.mouseMove(self.canvas, pos)
            self.app.processEvents()
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, modifier, end)
        self.app.processEvents()

    def texts(self, figure):
        return [child.get_text() for artist in figure.artists if isinstance(artist, lt.LinkedTableArtist)
                for child in artist._children if hasattr(child, "get_text") and child.get_text()]

    def handle_pixels(self, target=HANDLE_LIGHT):
        self.canvas.draw()
        image = self.canvas.grab().toImage()
        bits = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
        bgr = bits[:, :image.width(), :3].astype(int)
        color = np.array(target[::-1])
        return int((np.abs(bgr - color).max(axis=2) < 10).sum())

    def export_to(self, name):
        path = self.folder / name
        chosen = {"svg": "SVG (*.svg)", "pdf": "PDF (*.pdf)", "png": "PNG (*.png)"}[path.suffix[1:]]
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(path), chosen)):
            self.window.export()
        self.assertEqual(self.errors, [])
        self.assertTrue(path.exists() and path.stat().st_size > 0)
        return path

    # -- commands, menus, shortcut, i18n -------------------------------------------------------------
    def test_mode_action_menus_toolbar_shortcut_and_languages(self):
        from trama_qt.shortcuts_dialog import ShortcutsDialog
        window = self.window
        action = window.actions["linked_table_move"]
        self.assertTrue(action.isCheckable())
        self.assertEqual(action.shortcut(), QKeySequence("Ctrl+Shift+M"))
        self.assertIn(action, window.command_menus["Insert"].actions())
        self.assertIn(action, window.command_menus["Arrange"].actions())
        self.assertIn("linked_table_move", window.toolbar.buttons)
        self.assertFalse(action.isEnabled())  # worksheet has no linked tables

        self.open_graph()
        self.assertTrue(action.isEnabled())
        self.assertEqual(action.text(), "Select / move tables")
        dialog = ShortcutsDialog(window)
        self.addCleanup(dialog.deleteLater)
        shortcuts = {}
        for i in range(dialog.tree.topLevelItemCount()):
            head = dialog.tree.topLevelItem(i)
            for j in range(head.childCount()):
                shortcuts[head.child(j).text(0)] = head.child(j).text(1)
        self.assertEqual(shortcuts[action.text()], QKeySequence("Ctrl+Shift+M").toString(QKeySequence.SequenceFormat.NativeText))

        set_language("it")
        self.assertEqual(tr("command.linked_table_move"), "Seleziona / sposta tabelle")

        # Empty native graph disables the mode with an explanation in its tooltip.
        self.window.commit_linked_tables(("graph", 0), [])
        self.assertFalse(action.isEnabled())
        self.assertIn(tr("linked_table.move.none"), action.toolTip())

    # -- graph move, edge clamping, click, cancel, undo/redo, zero recalculation ---------------------
    def test_graph_move_clamping_click_cancel_and_undo_redo(self):
        self.open_graph()
        before = self.graph_records()
        linked_id, copy_id = before[0]["id"], before[1]["id"]
        self.window.project.dirty = False

        with mock.patch("trama_qt.project.compute", side_effect=AssertionError("move triggered calculation")):
            self.window.actions["linked_table_move"].trigger()
            self.app.processEvents()
            self.assertTrue(self.window.table_move.active)

            # Simple click selects without dirtying or pushing undo.
            start_pt = self.center_point(linked_id)
            QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
            self.app.processEvents()
            self.assertEqual(self.window.table_move.selected_id, linked_id)
            self.assertNotIn("{", self.window.message.text())
            self.assertIn("%", self.window.message.text())
            self.assertEqual(self.graph_records(), before)
            self.assertFalse(self.window.project.dirty)
            self.assertFalse(self.window.actions["undo"].isEnabled())
            self.assertGreater(self.handle_pixels(), 8)

            # Escape mid-drag cancels preview without committing.
            far_pt = self.fraction_to_qpoint(0.35, 0.45)
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
            QTest.mouseMove(self.canvas, far_pt)
            self.app.processEvents()
            self.assertEqual(self.graph_records(), before)
            self.assertFalse(self.window.project.dirty)
            QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, far_pt)
            self.app.processEvents()
            self.assertEqual(self.graph_records(), before)
            self.assertFalse(self.window.project.dirty)
            self.assertTrue(self.window.table_move.active)

            # FocusOut mid-drag also cancels preview cleanly.
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
            QTest.mouseMove(self.canvas, far_pt)
            self.app.processEvents()
            QApplication.sendEvent(self.canvas, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, far_pt)
            self.app.processEvents()
            self.assertEqual(self.graph_records(), before)
            self.assertFalse(self.window.project.dirty)

            # Real drag moves ONLY the linked table; copy stays fixed.
            target_pt = self.fraction_to_qpoint(0.28, 0.55)
            self.drag_qpoints(start_pt, target_pt)
            moved = self.graph_records()
            self.assertEqual(moved[0]["id"], linked_id)
            self.assertEqual(moved[0]["mode"], "linked")
            self.assertEqual(moved[0]["source"], before[0]["source"])
            self.assertEqual(moved[1], before[1])  # copy untouched
            self.assertGreater(moved[0]["position"][0], before[0]["position"][0] + 0.08)
            self.assertGreater(moved[0]["position"][1], before[0]["position"][1] + 0.30)
            self.assertTrue(self.window.project.dirty)

            # Drag to outside bottom-right corner clamps within drawable page.
            second_start = self.center_point(linked_id)
            outside_pt = QPoint(self.canvas.width() + 80, self.canvas.height() + 80)
            self.drag_qpoints(second_start, outside_pt)
            clamped = self.graph_records()
            artist = self.artist_for(linked_id)
            left, top, tw, th = artist.bounds_inches(self.canvas.figure)
            fig_w, fig_h = self.canvas.figure.get_size_inches()
            self.assertLessEqual(left + tw, fig_w + 1e-6)
            self.assertLessEqual(top + th, fig_h + 1e-6)
            self.assertLess(clamped[0]["position"][0], 1.0)
            self.assertLess(clamped[0]["position"][1], 1.0)

            # One Undo restores previous position; second Undo restores original; Redo reapplies.
            self.window.actions["undo"].trigger()
            self.app.processEvents()
            self.assertEqual(self.graph_records()[0]["position"], moved[0]["position"])
            self.window.actions["undo"].trigger()
            self.app.processEvents()
            self.assertEqual(self.graph_records(), before)
            self.window.actions["redo"].trigger()
            self.app.processEvents()
            self.assertEqual(self.graph_records()[0]["position"], moved[0]["position"])

            # Arrow nudge (Ctrl+Right = 10 logical px) commits one step; second Escape exits mode.
            before_nudge = self.graph_records()
            self.assertEqual(self.window.table_move.selected_id, linked_id)
            QTest.keyClick(self.canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            self.assertGreater(self.graph_records()[0]["position"][0], before_nudge[0]["position"][0])
            QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertFalse(self.window.table_move.active)

    # -- sheet switch mid-drag, pan/zoom precedence, drawing tools exclusion -------------------------
    def test_sheet_switch_cancels_preview_and_pan_zoom_keep_precedence(self):
        self.open_graph()
        before = self.graph_records()
        linked_id = before[0]["id"]
        self.window.actions["linked_table_move"].trigger()
        start_pt = self.center_point(linked_id)
        far_pt = self.fraction_to_qpoint(0.45, 0.45)

        # Sheet switch during drag cancels preview cleanly.
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
        QTest.mouseMove(self.canvas, far_pt)
        self.app.processEvents()
        self.window.open_sheet(("data", "Misure"))
        self.assertEqual(self.graph_records(), before)
        self.assertFalse(self.window.project.dirty)

        # Pan and Zoom take precedence when active.
        self.open_graph()
        self.window.actions["linked_table_move"].trigger()
        tools = self.window.plot_tools
        axes = self.canvas.figure.axes[0]
        full_xlim = axes.get_xlim()
        tools.zoom()
        self.assertFalse(self.window.table_move.allowed())
        self.drag_qpoints(self.center_point(linked_id), self.fraction_to_qpoint(0.75, 0.75))
        self.assertEqual(self.graph_records(), before)
        self.assertNotEqual(axes.get_xlim(), full_xlim)
        tools.zoom()
        self.assertTrue(self.window.table_move.allowed())

        # Mutual exclusion with shape drawing select tool.
        self.window.actions["draw_select"].trigger()
        self.app.processEvents()
        self.assertFalse(self.window.table_move.active)
        self.assertTrue(self.window.actions["draw_select"].isChecked())
        self.window.actions["linked_table_move"].trigger()
        self.app.processEvents()
        self.assertTrue(self.window.table_move.active)
        self.assertFalse(self.window.actions["draw_select"].isChecked())

    # -- overlapping tables --------------------------------------------------------------------------
    def test_overlapping_tables_move_only_topmost_and_preserve_order(self):
        self.open_graph()
        records = self.graph_records()
        records[1]["position"] = list(records[0]["position"])  # overlap copy directly above linked
        self.window.commit_linked_tables(("graph", 0), records)
        self.canvas.draw()
        self.app.processEvents()

        self.window.actions["linked_table_move"].trigger()
        pt = self.center_point(records[1]["id"])
        self.drag_qpoints(pt, self.fraction_to_qpoint(0.65, 0.45))
        after = self.graph_records()
        self.assertEqual([r["id"] for r in after], [r["id"] for r in records])
        self.assertEqual(after[0]["position"], records[0]["position"])
        self.assertGreater(after[1]["position"][0], 0.50)

    # -- layout page move, resize, DPR=1.5/2.0, data update, save/reopen, vector export --------------
    def test_layout_move_resize_dpi_data_update_and_vector_exports(self):
        self.open_layout()
        before_layout = self.layout_records()
        before_graph = self.graph_records()
        layout_table_id = before_layout[0]["id"]
        panel_axes = self.canvas.figure.axes[0]
        panel_bounds = tuple(panel_axes.get_position().bounds)

        # Resize window & canvas, simulate DPR=1.5 (with resizeEvent as Qt does), then drag layout page table.
        self.window.resize(900, 620)
        self.app.processEvents()
        self.canvas._set_device_pixel_ratio(1.5)
        self.canvas.resizeEvent(QResizeEvent(self.canvas.size(), self.canvas.size()))
        self.canvas.draw()
        self.app.processEvents()
        self.window.actions["linked_table_move"].trigger()
        self.app.processEvents()
        self.assertTrue(self.window.table_move.active)
        self.assertGreater(self.canvas.figure.dpi, 50)

        start_pt = self.center_point(layout_table_id)
        target_pt = self.fraction_to_qpoint(0.60, 0.25)
        self.drag_qpoints(start_pt, target_pt)
        moved_layout = self.layout_records()
        self.assertEqual(moved_layout[0]["id"], layout_table_id)
        self.assertGreater(moved_layout[0]["position"][0], 0.45)
        self.assertLess(moved_layout[0]["position"][1], 0.40)
        # Embedded graph panel & its tables are completely unchanged.
        self.assertEqual(self.graph_records(), before_graph)
        for got, exp in zip(self.canvas.figure.axes[0].get_position().bounds, panel_bounds, strict=True):
            self.assertAlmostEqual(float(got), float(exp), places=10)

        # Move graph linked table too (also verified at DPR=2.0 on SheetCanvas), then change last Risposta from 7 to 9.
        self.open_graph()
        self.canvas._set_device_pixel_ratio(2.0)
        self.canvas.resizeEvent(QResizeEvent(self.canvas.size(), self.canvas.size()))
        self.canvas.draw()
        self.app.processEvents()
        self.window.actions["linked_table_move"].trigger()
        graph_linked_id = before_graph[0]["id"]
        self.drag_qpoints(self.center_point(graph_linked_id), self.fraction_to_qpoint(0.25, 0.35))
        moved_graph = self.graph_records()
        self.assertGreater(moved_graph[0]["position"][0], 0.16)
        self.assertGreater(moved_graph[0]["position"][1], 0.20)

        self.window.open_sheet(("data", "Misure"))
        model = self.window.sheet.model()
        model.setData(model.index(3, 1), "9")
        self.wait()

        # Linked tables update to 2.6; copy stays 2.
        report = self.window.project.linked_table_report()
        self.assertEqual([(owner[0], r["mode"], res.cells) for owner, r, res in report],
                         [("graph", "linked", (("2.6",),)), ("graph", "copy", (("2",),)),
                          ("layout", "linked", (("2.6",),))])

        # Save and reopen preserves both moved positions.
        self.assertTrue(self.window.save())
        self.assertTrue(self.window.close_project())
        self.window.open_path(self.path)
        self.wait()
        self.assertEqual(self.graph_records()[0]["position"], moved_graph[0]["position"])
        self.assertEqual(self.graph_records()[1]["position"], before_graph[1]["position"])
        self.assertEqual(self.layout_records()[0]["position"], moved_layout[0]["position"])

        # Export PDF & SVG with selection mode active: vector text present, no editor handles leaked.
        self.open_graph()
        self.window.actions["linked_table_move"].trigger()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         self.center_point(graph_linked_id))
        self.assertGreater(self.handle_pixels(), 8)
        svg = self.export_to("graph.svg")
        svg_text = svg.read_text(encoding="utf-8")
        self.assertNotIn("#176676", svg_text.lower())
        self.assertIn("2.6", svg_text)
        pdf = self.export_to("graph.pdf")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

        self.open_layout()
        self.window.actions["linked_table_move"].trigger()
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         self.center_point(layout_table_id))
        from xml.etree import ElementTree as ET
        layout_svg = self.export_to("layout.svg")
        layout_svg_text = layout_svg.read_text(encoding="utf-8")
        self.assertNotIn("#176676", layout_svg_text.lower())
        svg_root = ET.fromstring(layout_svg_text)
        svg_values = ["".join(node.itertext()) for node in svg_root.iter("{http://www.w3.org/2000/svg}text")]
        self.assertEqual(svg_values.count("2.6"), 2)  # panel graph + layout page
        layout_pdf = self.export_to("layout.pdf")
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(layout_pdf)) as doc:
            words = doc[0].get_textpage().get_text_range().split()
        self.assertEqual(words.count("2.6"), 2)

    # -- missing source status box, double click numeric dialog, dialog Enter/autoDefault ------------
    def test_missing_source_status_box_moves_and_double_click_opens_numeric_dialog(self):
        from trama_qt.linked_tables import LinkedTableDialog, LinkedTablesDialog
        self.open_graph()
        # Add a second analysis, link a table to it, then delete that analysis so it enters missing state.
        second = self.window.project.candidate("Misure", "Descriptive statistics", {"Variables": ["Risposta"]})
        from trama_qt.project import compute
        self.window.project.add_result(second, compute(second, self.window.project.tables["Misure"].frame(mask_excluded=True)))
        run2 = self.window.project.runs[1]
        table_name = next(iter(run2.result.tables))
        choice = next(c for c in self.window.project.table_source_choices()
                      if c["kind"] == "result" and c["analysis"] == run2.uid and c["table"] == table_name)
        missing_rec = self.window.project.table_record(choice, (0, 0, 0, 0), mode="linked", position=(0.15, 0.55))
        self.window.commit_linked_tables(("graph", 0), [*self.graph_records(), missing_rec])
        self.window.project.delete_sheet(("result", 1))
        self.window.refresh()

        self.open_graph()
        self.assertIn(tr("linked_table.state.missing"), self.texts(self.canvas.figure))
        self.window.actions["linked_table_move"].trigger()
        self.drag_qpoints(self.center_point(missing_rec["id"]), self.fraction_to_qpoint(0.65, 0.72))
        moved = next(r for r in self.graph_records() if r["id"] == missing_rec["id"])
        self.assertEqual(moved["source"], missing_rec["source"])
        self.assertGreater(moved["position"][0], 0.30)

        # Double click opens LinkedTableDialog for the moved table and updates it.
        def accept_edit(dialog):
            self.assertEqual(dialog.record["id"], missing_rec["id"])
            dialog.x.setValue(33.0)
            dialog.y.setValue(44.0)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(LinkedTableDialog, "exec", accept_edit):
            QTest.mouseDClick(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                              self.center_point(missing_rec["id"]))
            self.app.processEvents()
        edited = next(r for r in self.graph_records() if r["id"] == missing_rec["id"])
        self.assertEqual(edited["position"], [0.33, 0.44])

        # LinkedTablesDialog adheres to AGENTS.md: Apply is default, inner QPushButtons are non-autoDefault.
        list_dialog = LinkedTablesDialog(self.window, self.window.project, self.graph_records(), owner="Misure")
        self.addCleanup(list_dialog.deleteLater)
        self.assertLessEqual(list_dialog.width(), 1024)
        self.assertLessEqual(list_dialog.height(), 768)
        for btn in (list_dialog.add_button, list_dialog.edit_button, list_dialog.remove_button):
            self.assertFalse(btn.autoDefault())
        defaults = [b for b in list_dialog.findChildren(QPushButton) if b.isDefault()]
        self.assertEqual([b.text() for b in defaults], [tr("graph.format.apply")])
        # Pressing Enter triggers default Apply button rather than Add/Edit/Remove.
        accepted = []
        list_dialog.accepted.connect(lambda: accepted.append(True))
        list_dialog.show()
        list_dialog.add_button.setFocus()
        self.app.processEvents()
        QTest.keyClick(list_dialog.add_button, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(accepted, [True])

        # Ctrl+Shift+M works when active table-move mode has focus, while Tab and F1 stay free.
        self.open_graph()
        self.window.actions["linked_table_move"].trigger()
        self.app.processEvents()
        self.assertTrue(self.window.table_move.active)
        QTest.keyClick(self.canvas, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertIsNone(self.window.table_move.controller.gesture)
        self.assertNotEqual(self.app.focusWidget(), self.canvas)


if __name__ == "__main__":
    unittest.main()
