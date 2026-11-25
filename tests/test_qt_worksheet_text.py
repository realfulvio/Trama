"""The Text group in the Qt window: cells, results, state, undo, files, annotations and the toolbar."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language
from analisi.text_markup import SUBSCRIPT, SUPERSCRIPT

FIXTURE = pd.DataFrame({
    "Categoria": ["Controllo", "Prima", "Seconda", "Terza", "Quarta"],
    "Dose": [0.000125, 1.23456789012345, 12345.6789, 0.5, float("nan")],
    "Risposta": [2.125, -0.0004, -0.0, 1.2345e-14, 950.0],
    "Repliche": [4, 4, 12, 9999, 0],
})
TEXT_ACTIONS = ("text_font", "text_size", "text_bold", "text_italic", "text_underline", "text_color",
                "text_align_left", "text_align_center", "text_align_right", "text_restore")


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1180, 768)
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def select(self, view, top, left, bottom, right, current=None):
        model = view.model()
        view.setCurrentIndex(model.index(*(current or (top, left))))
        view.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.app.processEvents()

    def sheet(self, name="celle", frame=None):
        title, = self.window.project.add_tables({name: FIXTURE.copy() if frame is None else frame})
        self.window.show_sheet("data", title)
        self.app.processEvents()
        return title, self.window.sheet, self.window.sheet.model()

    def state(self, attribute):
        states = self.window.text_format.states()
        return (states[attribute].kind, states[attribute].value)

    # -- cells ---------------------------------------------------------------------------------------
    def test_bold_italic_underline_toggle_and_show_inherited_uniform_mixed(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 3, 2)
        self.assertEqual(self.state("bold"), ("inherited", None))
        self.assertFalse(window.actions["text_bold"].isChecked())
        window.actions["text_bold"].trigger()
        self.assertEqual(self.state("bold"), ("uniform", True))
        self.assertTrue(window.actions["text_bold"].isChecked())
        self.assertEqual(window.actions["text_bold"].property("textState"), "uniform")
        self.assertIn("on", window.actions["text_bold"].toolTip())
        self.assertTrue(model.data(model.index(1, 1), Qt.ItemDataRole.FontRole).bold())
        self.assertIsNone(model.data(model.index(4, 1), Qt.ItemDataRole.FontRole))
        self.assertIsNone(model.data(model.index(1, 3), Qt.ItemDataRole.FontRole))

        self.select(view, 0, 1, 4, 2)  # five rows, the last one not formatted: mixed
        self.assertEqual(self.state("bold")[0], "mixed")
        self.assertEqual(window.actions["text_bold"].property("textState"), "mixed")
        self.assertFalse(window.actions["text_bold"].isChecked())
        window.actions["text_bold"].trigger()  # mixed → on everywhere
        self.assertEqual(self.state("bold"), ("uniform", True))
        window.actions["text_bold"].trigger()  # uniform on → inherited again
        self.assertEqual(self.state("bold"), ("inherited", None))
        self.assertFalse(window.project.tables[title].text_styles)

        window.actions["text_italic"].trigger()
        window.actions["text_underline"].trigger()
        font = model.data(model.index(0, 1), Qt.ItemDataRole.FontRole)
        self.assertTrue(font.italic() and font.underline() and not font.bold())
        self.assertEqual(self.errors, [])

    def test_alignment_color_font_and_size_and_their_roles(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 1, 0, 2, 1)
        defaults = [model.data(model.index(1, column), Qt.ItemDataRole.TextAlignmentRole) for column in (0, 1)]
        window.actions["text_align_center"].trigger()
        self.assertTrue(window.actions["text_align_center"].isChecked())
        self.assertEqual(self.state("align"), ("uniform", "center"))
        for column in (0, 1):
            alignment = model.data(model.index(1, column), Qt.ItemDataRole.TextAlignmentRole)
            self.assertTrue(alignment & Qt.AlignmentFlag.AlignHCenter)
        window.actions["text_align_center"].trigger()  # again: back to the default alignment
        self.assertEqual([model.data(model.index(1, column), Qt.ItemDataRole.TextAlignmentRole)
                          for column in (0, 1)], defaults)
        window.actions["text_align_right"].trigger()
        self.assertTrue(model.data(model.index(1, 0), Qt.ItemDataRole.TextAlignmentRole) & Qt.AlignmentFlag.AlignRight)

        window.text_format.apply({"color": "#AA0000", "size": 14, "font": "DejaVu Sans"})
        brush = model.data(model.index(1, 1), Qt.ItemDataRole.ForegroundRole)
        self.assertEqual(brush.color().name(), "#aa0000")
        font = model.data(model.index(1, 1), Qt.ItemDataRole.FontRole)
        self.assertEqual((font.pointSizeF(), font.family()), (14.0, "DejaVu Sans"))
        self.assertGreaterEqual(view.verticalHeader().defaultSectionSize(), 14 * 96 / 72)
        self.assertEqual(self.state("size"), ("uniform", 14))
        self.assertIn("14 pt", window.actions["text_size"].toolTip())
        self.assertIn("DejaVu Sans", window.actions["text_font"].toolTip())

    def test_restore_text_removes_text_and_keeps_backgrounds_and_number_formats(self):
        window = self.window
        title, view, model = self.sheet()
        data = window.project.tables[title]
        self.select(view, 0, 1, 4, 2)
        window.project.set_table_background(title, (0, 1, 4, 2), "#ffd966")
        window.project.set_table_number_format(title, ["Dose"], {"mode": "fixed", "digits": 3})
        model.refresh_formats()
        window.text_format.apply({"bold": True, "color": "#112233", "size": 12})
        self.assertTrue(data.text_styles)
        window.actions["text_restore"].trigger()
        self.assertFalse(data.text_styles)
        self.assertEqual(data.cell_backgrounds[(0, "Dose")], "#ffd966")
        self.assertEqual(data.number_formats, {"Dose": {"mode": "fixed", "digits": 3}})
        self.assertEqual(model.data(model.index(0, 1)), "0.000")
        window.actions["text_restore"].trigger()  # nothing left to restore: no new undo step
        self.assertIn("already", window.message.text())

    def test_background_excluded_and_number_format_interact_with_text(self):
        window = self.window
        title, view, model = self.sheet()
        window.project.set_table_background(title, (0, 1, 0, 1), "#ffd966")
        view.model().refresh_backgrounds()
        self.select(view, 0, 1, 0, 1)
        window.text_format.apply({"color": "#aa0000"})
        brush = model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole)
        self.assertEqual(brush.color().name(), "#aa0000")  # the chosen colour wins over the automatic contrast
        self.assertEqual(model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole).color().name(), "#ffd966")
        window.text_format.apply({"color": None})
        self.assertNotEqual(model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole).color().name(), "#aa0000")
        window.project.set_table_number_format(title, ["Dose"], {"mode": "fixed", "digits": 2})
        model.refresh_formats()
        self.select(view, 1, 1, 1, 1)
        window.text_format.apply({"italic": True})
        self.assertEqual(model.data(model.index(1, 1)), "1.23")
        self.assertTrue(model.data(model.index(1, 1), Qt.ItemDataRole.FontRole).italic())

    def test_the_style_never_touches_values_clipboard_calculations_or_csv(self):
        window = self.window
        title, view, model = self.sheet()
        data = window.project.tables[title]
        before = data.frame().copy()
        editing = model.data(model.index(1, 1), Qt.ItemDataRole.EditRole)
        recalculated = []
        window.refresh_runs = lambda *args, **kwargs: recalculated.append(args)
        self.select(view, 0, 1, 4, 2)
        window.text_format.apply({"bold": True, "size": 20, "font": "Courier New", "align": "center"})
        pd.testing.assert_frame_equal(data.frame(), before)
        self.assertEqual(recalculated, [])
        self.assertEqual(model.data(model.index(1, 1), Qt.ItemDataRole.EditRole), editing)
        view.copy()
        text = QGuiApplication.clipboard().text()
        self.assertIn("1.23456789012345".replace(".", "," if "," in text.splitlines()[1] else "."), text)
        self.assertNotIn("bold", text.lower())
        csv = data.frame().to_csv(index=False)
        self.assertIn("1.23456789012345", csv)
        self.assertEqual(data.frame()["Dose"].dtype, float)

    def test_undo_and_redo_are_one_step_and_keep_the_grid_in_place(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 3, 2, current=(2, 2))
        window.text_format.apply({"bold": True})
        window.text_format.apply({"italic": True})
        data = window.project.tables[title]
        self.assertEqual(len(window.project.history.changes), 2)
        window.undo()
        self.assertEqual(self.state("italic")[0], "inherited")
        self.assertEqual(self.state("bold"), ("uniform", True))
        self.assertIs(window.sheet, view)
        self.assertEqual(view.currentIndex().row(), 2)
        window.undo()
        self.assertFalse(data.text_styles)
        self.assertIsNone(model.data(model.index(1, 1), Qt.ItemDataRole.FontRole))
        window.undo(redo=True)
        window.undo(redo=True)
        self.assertEqual(data.text_styles.style_at("Dose", 0), {"bold": True, "italic": True})
        self.assertTrue(model.data(model.index(0, 1), Qt.ItemDataRole.FontRole).bold())

    def test_row_and_column_edits_keep_the_style_with_its_cells(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 2, 1, 3, 1)
        window.text_format.apply({"bold": True})
        window.project.insert_rows(title, 0, 2)
        data = window.project.tables[title]
        self.assertEqual(data.text_styles.records(data.columns), [["Dose", 4, 6, {"bold": True}]])
        window.project.rename_column(title, 1, "Dose due")
        self.assertEqual(data.text_styles.records(data.columns)[0][0], "Dose due")
        window.project.delete_rows(title, [0, 1, 4])
        self.assertEqual(data.text_styles.records(data.columns), [["Dose due", 2, 3, {"bold": True}]])
        window.project.delete_columns(title, [1])
        self.assertFalse(data.text_styles)
        window.undo()
        self.assertTrue(window.project.tables[title].text_styles)

    def test_save_and_reopen_keeps_cell_and_result_styles(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 1, 1, 3, 2)
        window.text_format.apply({"color": "#336699", "underline": True, "font": "DejaVu Sans"})
        path = self.folder / "text.alab"
        window.project.save(path)
        self.assertTrue(window.close_project())
        window.open_path(path)
        self.app.processEvents()
        window.show_sheet("data", title)
        self.app.processEvents()
        data = window.project.tables[title]
        self.assertEqual(data.text_styles.style_at("Risposta", 2), {"font": "DejaVu Sans", "color": "#336699",
                                                                    "underline": True})
        model = window.sheet.model()
        self.assertEqual(model.data(model.index(2, 2), Qt.ItemDataRole.ForegroundRole).color().name(), "#336699")

    def test_locked_sheet_offers_no_text_command(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 1, 1)
        self.assertTrue(window.actions["text_bold"].isEnabled())
        window.project.set_sheet_frozen(("data", title), True)
        self.assertTrue(window.project.sheet_locked(("data", title)))
        window.show_sheet("data", title)
        self.app.processEvents()
        window.update_actions()
        for key in TEXT_ACTIONS:
            self.assertFalse(window.actions[key].isEnabled(), key)
        self.assertFalse(window.text_format.apply({"bold": True}))

    def test_no_selection_no_graph_no_command(self):
        window = self.window
        window.show_home()
        self.app.processEvents()
        window.update_actions()
        for key in TEXT_ACTIONS:
            self.assertFalse(window.actions[key].isEnabled(), key)
        self.assertFalse(window.actions["text_graph"].isEnabled())

    def test_font_dialog_changes_family_and_size_and_can_send_them_back(self):
        from PySide6.QtGui import QFontDatabase

        from trama_qt.text_format import TextFontDialog
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 1, 1)
        installed_family = QFontDatabase.families()[0]

        def confirm(family, size):
            def exec_(dialog):
                index = dialog.family.findData(family)
                self.assertGreaterEqual(index, 0)
                dialog.family.setCurrentIndex(index)
                if size in ("keep", "inherit"):
                    dialog.size.setCurrentIndex(0 if size == "keep" else 1)
                else:
                    dialog.size.setCurrentText(size)
                dialog.accept()
                return dialog.DialogCode.Accepted
            return exec_
        with patch.object(TextFontDialog, "exec", confirm(installed_family, "13,5")):
            window.actions["text_font"].trigger()
        self.assertEqual(window.project.tables[title].text_styles.style_at("Dose", 0),
                         {"font": installed_family, "size": 13.5})
        with patch.object(TextFontDialog, "exec", confirm("inherit", "inherit")):
            window.actions["text_font"].trigger()
        self.assertFalse(window.project.tables[title].text_styles)
        with patch.object(TextFontDialog, "exec", confirm("keep", "99")):
            window.actions["text_font"].trigger()  # the dialog refuses a size out of range and stays open
        self.assertFalse(window.project.tables[title].text_styles)

    def test_zoom_scales_explicit_sizes_and_row_heights(self):
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 0, 1)
        window.text_format.apply({"size": 12})
        small = model.data(model.index(0, 1), Qt.ItemDataRole.FontRole).pointSizeF()
        window.zoom_table(1)
        window.zoom_table(1)
        window.zoom_table(1)
        font = model.data(model.index(0, 1), Qt.ItemDataRole.FontRole)
        self.assertGreater(font.pointSizeF(), small)
        self.assertAlmostEqual(font.pointSizeF(), 12 * window.table_zoom / 100, places=1)
        self.assertGreater(view.verticalHeader().defaultSectionSize(), 26)

    def test_context_menu_and_change_menu_list_the_text_commands(self):
        window = self.window
        title, view, model = self.sheet()
        menu = window.command_menus["Change"]
        listed = {action.text() for action in menu.actions()}
        self.assertTrue({"Text font…", "Bold", "Italic", "Underline", "Restore text"} <= listed)
        set_language("it")
        self.assertEqual(window.actions["text_bold"].text(), "Bold")  # labels follow the language at start-up
        from analisi.i18n import tr
        self.assertEqual(tr("command.text_restore"), "Ripristina testo")
        self.assertEqual(tr("ribbon.text_group"), "Testo")

    # -- results --------------------------------------------------------------------------------------
    def test_result_tables_take_text_styles_read_only_values_and_survive_recalculation(self):
        from trama_qt.analysis_dialog import AnalysisDialog
        window = self.window
        frame = pd.DataFrame({"Dose": [0.5, 1, 2, 4, 8, 16, 32, 64],
                              "Response": [2.1, 3.9, 6.2, 8.1, 9.8, 12.3, 13.1, 13.5]})
        title, = window.project.add_tables({"Fit": frame})
        window.show_sheet("data", title)
        dialog = AnalysisDialog(window, frame, current=("Deming regression", {}))
        values = dialog.options()
        dialog.deleteLater()
        window.calculate_candidate(window.project.candidate(title, "Deming regression", values), frame, None)
        self.wait()
        window.open_sheet(("result", 0))
        self.app.processEvents()
        tabs = window.result_tabs
        names = [tabs.tabText(index) for index in range(tabs.count())]
        tabs.setCurrentIndex(names.index("Data"))
        view = tabs.currentWidget()
        self.assertEqual(view.model().flags(view.model().index(0, 1)) & Qt.ItemFlag.ItemIsEditable,
                         Qt.ItemFlag.NoItemFlags)
        shown = view.model().data(view.model().index(0, 1))
        self.select(view, 0, 1, 7, 2)
        self.assertTrue(window.actions["text_bold"].isEnabled())
        window.actions["text_bold"].trigger()
        window.text_format.apply({"color": "#aa0000", "align": "center"})
        run = window.project.runs[0]
        styles = window.project.tables[title].result_text_styles[run.slot]["Data"]
        self.assertEqual(styles.style_at(1, 0), {"color": "#aa0000", "bold": True, "align": "center"})
        self.assertTrue(view.model().data(view.model().index(0, 1), Qt.ItemDataRole.FontRole).bold())
        self.assertEqual(view.model().data(view.model().index(0, 1)), shown)  # text of the value unchanged
        self.assertEqual(self.state("bold"), ("uniform", True))
        # Another tab keeps its own look.
        other = next(index for index, name in enumerate(names) if name != "Data")
        tabs.setCurrentIndex(other)
        self.select(tabs.currentWidget(), 0, 0, 0, 0)
        self.assertEqual(self.state("bold"), ("inherited", None))
        tabs.setCurrentIndex(names.index("Data"))

        window.undo()  # the colour and alignment step only
        self.app.processEvents()
        self.assertEqual(window.project.tables[title].result_text_styles[run.slot]["Data"].style_at(1, 0),
                         {"bold": True})
        window.undo(redo=True)
        self.app.processEvents()

        window.show_sheet("data", title)
        model = window.sheet.model()
        model.setData(model.index(0, 1), "2.4")
        self.app.processEvents()
        self.wait()
        window.open_sheet(("result", 0))
        self.wait()
        view = window.result_tabs.widget(names.index("Data"))
        self.assertTrue(view.model().data(view.model().index(0, 1), Qt.ItemDataRole.FontRole).bold())

        saved = self.folder / "results.alab"
        window.project.save(saved)
        self.assertTrue(window.close_project())
        window.open_path(saved)
        self.app.processEvents()
        window.open_sheet(("result", 0))
        self.wait()
        run = window.project.runs[0]
        reopened = window.project.tables[title].result_text_styles[run.slot]["Data"]
        self.assertEqual(reopened.style_at(2, 7), {"color": "#aa0000", "bold": True, "align": "center"})

    # -- toolbar -------------------------------------------------------------------------------------
    def test_the_text_group_is_on_the_toolbar_and_in_the_overflow_menu_when_narrow(self):
        window = self.window
        title, view, model = self.sheet()
        toolbar = window.toolbar
        window.resize(1180, 768)
        self.app.processEvents()
        toolbar._fit()
        for key in TEXT_ACTIONS:
            button = toolbar.buttons[key]
            self.assertTrue(button.isVisibleTo(toolbar), key)
            self.assertLessEqual(button.mapTo(toolbar, button.rect().bottomRight()).x(), toolbar.width(), key)
        window.resize(560, 768)
        self.app.processEvents()
        toolbar._fit()
        self.assertTrue(toolbar.overflow.isVisible())
        names = [menu.title() for menu in toolbar.overflow.menu().findChildren(type(toolbar.overflow.menu()))]
        names += [action.text() for action in toolbar.overflow.menu().actions()]
        self.assertIn("Text", names)
        group = next(action.menu() for action in toolbar.overflow.menu().actions() if action.text() == "Text")
        self.assertEqual({action.text() for action in group.actions()} >= {"Bold", "Italic", "Underline"}, True)

    def test_the_toolbar_follows_150_percent_scale_and_both_themes(self):
        from trama_qt import theme
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 0, 1, 0, 1)
        window.text_format.apply({"bold": True})
        for mode in ("light", "dark"):
            theme.set_mode(mode)
            self.app.processEvents()
            image = window.toolbar.grab()
            self.assertFalse(image.isNull())
            for key in ("text_bold", "text_font"):
                icon = window.actions[key].icon()
                self.assertFalse(icon.pixmap(24, 24).isNull(), (mode, key))
        theme.set_mode("system")

    def test_graph_text_commands_open_the_existing_format_window(self):
        window = self.window
        title, view, model = self.sheet()
        window.show_sheet("data", title)
        calls = []
        window.format_graph = lambda: calls.append("format")
        window.text_format.graph_run = lambda: object()
        window.show_home()
        self.app.processEvents()
        self.assertIsNone(window.text_format.target())
        window.text_format.choose_font()
        window.text_format.choose_size()
        window.text_format.graph_text()
        self.assertEqual(calls, ["format", "format", "format"])

    # -- printing and rich output ----------------------------------------------------------------------
    def test_printed_tables_carry_the_text_formatting(self):
        from trama_qt.printing import table_sheet
        window = self.window
        title, view, model = self.sheet()
        self.select(view, 1, 1, 1, 1)
        window.text_format.apply({"bold": True, "italic": True, "underline": True, "size": 13,
                                  "color": "#aa0000", "font": "DejaVu Sans", "align": "center"})
        sheet = table_sheet(title, model, worksheet=True)
        html = next(iter(sheet.html_chunks(600))) if hasattr(sheet, "html_chunks") else ""
        if not html:
            self.skipTest("the print sheet exposes no HTML in this build")
        self.assertIn("font-weight:bold", html)
        self.assertIn("font-style:italic", html)
        self.assertIn("text-decoration:underline", html)
        self.assertIn("font-size:13pt", html)
        self.assertIn("color:#aa0000", html)
        self.assertIn("'DejaVu Sans'", html)
        self.assertIn('align="center"', html)

    # -- annotations -------------------------------------------------------------------------------------
    def test_annotation_editor_keeps_plain_text_and_stores_scripts(self):
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from trama_qt.annotations import AnnotationEditor
        axes = Figure().add_subplot()
        dialog = AnnotationEditor(self.window, axes)
        self.addCleanup(dialog.deleteLater)
        dialog.text.set_content("CO2 e 10-3")
        cursor = dialog.text.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(3, cursor.MoveMode.KeepAnchor)
        dialog.text.setTextCursor(cursor)
        self.assertEqual(dialog.text.script()[0], "inherited")
        dialog.subscript.click()
        self.assertTrue(dialog.subscript.isChecked())
        cursor.setPosition(8)
        cursor.setPosition(10, cursor.MoveMode.KeepAnchor)
        dialog.text.setTextCursor(cursor)
        dialog.superscript.click()
        dialog.flags["bold"].setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.problem.text(), "")
        record = dialog.result
        self.assertEqual(record["text"], "CO2 e 10-3")
        self.assertEqual(record["spans"], [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]])
        self.assertTrue(record["bold"])
        self.assertNotIn("italic", record)
        self.assertNotIn("font", record)
        # Explicit cleanup, then Restore text.
        again = AnnotationEditor(self.window, axes, record)
        self.addCleanup(again.deleteLater)
        self.assertEqual(again.text.content()[1], record["spans"])
        again.text.selectAll()
        self.assertEqual(again.text.script()[0], "mixed")
        again.text.clear_scripts()
        self.assertEqual(again.text.content()[1], [])
        again.restore()
        again.accept()
        self.assertEqual(again.result["text"], "CO2 e 10-3")
        self.assertEqual(set(again.result), {"text", "units", "position", "align", "size", "color"})

    def test_annotation_editor_counts_characters_beyond_the_basic_plane_correctly(self):
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from trama_qt.annotations import AnnotationEditor
        axes = Figure().add_subplot()
        record = {"text": "😀x2 É", "units": "axes", "position": [.1, .5], "size": 11, "color": "#174e78",
                  "align": "left", "spans": [[2, 3, SUBSCRIPT]]}
        dialog = AnnotationEditor(self.window, axes, record)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.text.content(), ("😀x2 É", [[2, 3, SUBSCRIPT]]))
        dialog.accept()
        self.assertEqual(dialog.result["spans"], [[2, 3, SUBSCRIPT]])

    def test_annotation_with_scripts_is_one_undo_step_and_exports(self):
        from analisi.figure_export import export_figure
        from trama_qt.annotations import GraphAnnotationsDialog
        window = self.window
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Risposta": [1, 3, 5, 7]})
        title, = window.project.add_tables({"Misure": frame})
        window.show_sheet("data", title)
        window.calculate_candidate(window.project.candidate(title, "Linear regression",
                                                            {"X": "X", "Y": "Risposta"}), frame, None)
        self.wait()
        window.open_sheet(("graph", 0))
        self.wait()
        record = {"text": "CO2 e 10-3", "units": "axes", "position": [.1, .8], "size": 12, "color": "#126c65",
                  "align": "left", "spans": [[2, 3, SUBSCRIPT], [8, 10, SUPERSCRIPT]], "bold": True}

        def confirm(dialog):
            dialog.result = [record]
            return dialog.DialogCode.Accepted
        with patch.object(GraphAnnotationsDialog, "exec", confirm):
            window.edit_annotations()
        self.app.processEvents()
        run = window.project.runs[0]
        self.assertEqual(run.style["annotations"], [record])
        texts = run.result.figure.axes[0].texts
        self.assertEqual(len(texts), 1)
        self.assertIn("_{", texts[0].get_text())
        self.assertEqual(record["text"], "CO2 e 10-3")  # what is stored, searched and copied stays plain
        for suffix in ("png", "pdf", "svg"):
            path = self.folder / f"annotation.{suffix}"
            export_figure(run.result.figure, path, {"format": suffix, "dpi": 150} if suffix == "png"
                          else {"format": suffix})
            self.assertGreater(path.stat().st_size, 500, suffix)
        window.undo()
        self.app.processEvents()
        self.assertNotIn("annotations", window.project.runs[0].style or {})
        self.assertEqual(len(window.project.runs[0].result.figure.axes[0].texts), 0)
        window.undo(redo=True)
        self.app.processEvents()
        self.assertEqual(window.project.runs[0].style["annotations"], [record])
        self.assertEqual(self.errors, [])

    def test_a_pasted_rich_text_keeps_only_its_words(self):
        from PySide6.QtCore import QMimeData
        from trama_qt.script_edit import ScriptEdit
        edit = ScriptEdit("")
        mime = QMimeData()
        mime.setHtml("<b>CO<sub>2</sub></b>")
        mime.setText("CO2")
        edit.insertFromMimeData(mime)
        self.assertEqual(edit.content(), ("CO2", []))


if __name__ == "__main__":
    unittest.main()
