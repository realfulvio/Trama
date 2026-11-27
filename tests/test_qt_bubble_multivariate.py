"""Qt acceptance tests for multivariate Bubble plot controls, Inspector, style dialog, undo & zero recalculation."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analisi.bubble import (
    ATTR, BUBBLE, COLOR_COLUMN, COLOR_LIMITS, COLOR_MAX, COLOR_MID, COLOR_MIN, FILL_CONTINUOUS,
    FILL_BY_CATEGORY, FILL_FIXED, FILL_MODE, FIXED_AREA, MAX_AREA, MISSING_COLOR, PALETTE, REVERSE_PALETTE,
    SHAPE_BY_CATEGORY, SHAPE_COLUMN, SHAPE_MAP, SHAPE_MODE, SHEET, SIZE_BY_COLUMN, SIZE_FIXED,
    SIZE_MODE,
)
from analisi.i18n import set_language, tr
from analisi.bubble_style import apply_bubble_style
from trama_qt import theme
from trama_qt.analysis_dialog import AnalysisDialog
from trama_qt.bubble_style import BubbleStyleDialog, LevelSymbolDialog
from trama_qt.bubble_multivariate_smoke import check_legend_geometry
from trama_qt.graph_format import GraphFormatDialog
from trama_qt.project import Project, compute
from trama_qt.shortcuts_dialog import ShortcutsDialog
from trama_qt.window import MainWindow


MISURE_CSV = Path(__file__).resolve().parent / "data" / "bubble_multivariate" / "misure.csv"


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _load_misure():
    return pd.read_csv(MISURE_CSV, keep_default_na=True)


class QtBubbleMultivariateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self._old_prefs = os.environ.get("XDG_CONFIG_HOME")
        self._tmp = tempfile.mkdtemp(prefix="trama-qt-bubble-test-")
        os.environ["XDG_CONFIG_HOME"] = self._tmp
        set_language("en")
        theme.load_fonts()
        theme.install_qt_translations(self.app, "en")

    def tearDown(self):
        set_language("en")
        if self._old_prefs is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_prefs
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_analysis_dialog_modes_fixed_area_and_mixed_level_symbols(self):
        df = pd.DataFrame({
            "X": [1.0, 2.0, 3.0],
            "Y": [4.0, 5.0, 6.0],
            "Sig": [0.0, 25.0, 100.0],
            "Kind": pd.Series([1, "1", None], dtype=object),
        })
        dlg = AnalysisDialog(None, df, only=BUBBLE)
        self.addCleanup(dlg.deleteLater)

        # Default Size mode shows Size; switching to Fixed area hides Size and lets dialog accept with 2 numeric cols!
        dlg.controls[SIZE_MODE][1].setCurrentIndex(dlg.controls[SIZE_MODE][1].findData(SIZE_FIXED))
        self.assertIn("Size", dlg.hidden)
        self.assertNotIn(FIXED_AREA, dlg.hidden)

        dlg.controls[FILL_MODE][1].setCurrentIndex(dlg.controls[FILL_MODE][1].findData(FILL_CONTINUOUS))
        c_combo = dlg.controls[COLOR_COLUMN][1]
        c_combo.setCurrentIndex(c_combo.findData("Sig"))
        dlg.controls[SHAPE_MODE][1].setCurrentIndex(dlg.controls[SHAPE_MODE][1].findData(SHAPE_BY_CATEGORY))
        s_combo = dlg.controls[SHAPE_COLUMN][1]
        s_combo.setCurrentIndex(s_combo.findData("Kind"))
        self.app.processEvents()

        sym_dlg = LevelSymbolDialog(dlg, [("int:1", "1", "bubble.style.type.number"),
                                          ("str:1", "1", "bubble.style.type.text")], {})
        self.addCleanup(sym_dlg.deleteLater)
        self.assertEqual(sym_dlg.editor.table.rowCount(), 2)
        self.assertEqual(sym_dlg.editor.table.item(0, 1).text(), tr("bubble.style.type.number"))
        self.assertEqual(sym_dlg.editor.table.item(1, 1).text(), tr("bubble.style.type.text"))
        sym_dlg.editor._combos[0][1].set_value("D")
        sym_dlg.editor._combos[1][1].set_value("P")
        sym_dlg.accept()
        dlg.controls[SHAPE_MAP][1].set_mapping(sym_dlg.result)

        dlg.accept()
        self.assertIsNotNone(dlg.result)
        method, opts = dlg.result
        self.assertEqual(method, BUBBLE)
        self.assertEqual(opts[SIZE_MODE], SIZE_FIXED)
        self.assertEqual(opts[SHAPE_MAP], {"int:1": "D", "str:1": "P"})

    def test_narrow_window_keeps_bubble_guides_separate_and_scrollable(self):
        window = MainWindow()
        def close_window():
            window.project.dirty = False
            window.close()
        self.addCleanup(close_window)
        frame = _load_misure()
        title, = window.project.add_tables({"Measurements": frame})
        run = window.project.candidate(title, BUBBLE, {
            "X": "x", "Y": "y", "Size": "area", "Label": "etichetta", "Group": "id",
            FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
            SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "classe",
        })
        window.project.add_result(run, compute(run, frame))
        window.project.dirty = False
        window.resize(650, 470)
        window.show()
        window.open_sheet(("graph", 0))
        if window.inspector is None:
            window.toggle_inspector()
        self.app.processEvents()

        canvas = window.plot_tools.canvas
        viewport = window.page.figure_view
        self.assertTrue(window.nav_card.isVisible())
        self.assertTrue(window.inspector.isVisible())
        guide_width = check_legend_geometry(canvas)
        self.assertGreaterEqual(viewport.viewport().width() * canvas.device_pixel_ratio, guide_width)
        self.assertGreater(viewport.horizontalScrollBar().maximum(), 0)
        self.assertEqual(window.width(), 650)

        apply_bubble_style(canvas.figure, {"fill_mode": FILL_BY_CATEGORY})
        canvas.draw()
        self.app.processEvents()
        check_legend_geometry(canvas, ("bubble-group-legend", "bubble-shape-legend", "bubble-size-legend"))
        apply_bubble_style(canvas.figure, {})
        viewport.set_percent(70)
        self.app.processEvents()
        check_legend_geometry(canvas)
        window.resize(1380, 900)
        viewport.set_percent(100)
        self.app.processEvents()
        check_legend_geometry(canvas)
        self.assertEqual(viewport.horizontalScrollBar().maximum(), 0)

        window.open_sheet(("data", title))
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.open_sheet(("graph", 0))
        self.app.processEvents()
        replacement = window.plot_tools.canvas
        self.assertIsNot(replacement, canvas)
        self.assertIs(replacement.figure, run.result.figure)
        check_legend_geometry(replacement)

    def test_window_inspector_dialog_preview_apply_undo_zero_recalc_themes_and_exports(self):
        for lang, mode in (("it", "dark"), ("en", "light")):
            set_language(lang)
            theme.set_mode(mode, self.app, remember=False)
            theme.install_qt_translations(self.app, lang)
            win = MainWindow()
            def _close_clean(w=win):
                w.project.dirty = False
                if w.inspector is not None:
                    w.inspector.discard()
                    w.dispose_inspector()
                w.close()
            self.addCleanup(_close_clean)
            df = _load_misure()
            win.project.add_tables({"misure": df})
            run = win.project.candidate("misure", BUBBLE, {
                "X": "x", "Y": "y", "Size": "area", MAX_AREA: 400.0,
                FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
                SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "classe",
                "Label": "etichetta",
            })
            win.project.add_result(run, compute(run, df))
            win.refresh()
            win.open_sheet(("graph", 0))
            self.app.processEvents()

            # Contextual button & action & F1 shortcut list
            self.assertTrue(win.actions["bubble_style"].isEnabled())
            shortcuts = ShortcutsDialog(win)
            self.addCleanup(shortcuts.deleteLater)
            listed = [
                shortcuts.tree.topLevelItem(i).child(j).text(1)
                for i in range(shortcuts.tree.topLevelItemCount())
                for j in range(shortcuts.tree.topLevelItem(i).childCount())
            ]
            self.assertTrue(any("B" in s and "Shift" in s for s in listed))

            # Open Inspector -> live preview, Discard, Apply with zero recalculation!
            win.toggle_inspector()
            self.app.processEvents()
            self.assertIsNotNone(win.inspector)
            self.assertIsNotNone(win.inspector.bubble_section)

            with (
                mock.patch("trama_qt.project.compute", side_effect=AssertionError("Must not compute!")),
                mock.patch("analisi.bubble.bubble_plot", side_effect=AssertionError("Must not re-run bubble_plot!")),
            ):
                sec = win.inspector.bubble_section
                sec.reverse.setChecked(True)
                self.app.processEvents()
                self.assertTrue(getattr(run.result.figure, ATTR)["effective_encoding"]["reverse"])

                # Discard reverts preview
                win.inspector.discard()
                self.app.processEvents()
                self.assertFalse(getattr(run.result.figure, ATTR)["effective_encoding"]["reverse"])

                # Now edit & single Apply via Inspector -> commits + updates tables + creates 1 Undo step
                sec.palette.set_value("Blue–red")
                sec.limits_mode.setCurrentIndex(sec.limits_mode.findData("Manual"))
                sec.color_min.setText("0")
                sec.color_mid.setText("25")
                sec.color_max.setText("100")
                self.app.processEvents()
                self.assertTrue(win.inspector.apply())
                st = getattr(run.result.figure, ATTR)
                self.assertEqual(st["effective_encoding"]["palette"], "Blue–red")
                self.assertEqual(st["color_summary"]["midpoint"], 25.0)
                self.assertEqual(run.result.tables["Settings"].loc["Palette", "Value"], "Blue–red")
                self.assertAlmostEqual(float(run.result.tables[SHEET].loc[1, "Color position (u)"]), 0.5, places=6)

                # Undo reverts style and tables cleanly; Redo restores both!
                win.undo()
                self.app.processEvents()
                self.assertEqual(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"], "Viridis")
                self.assertEqual(run.result.tables["Settings"].loc["Palette", "Value"], "Viridis")
                win.undo(redo=True)
                self.app.processEvents()
                self.assertEqual(getattr(run.result.figure, ATTR)["effective_encoding"]["palette"], "Blue–red")

                # Open BubbleStyleDialog: Preview -> Esc cancel restores; then edit symbols + Apply
                dlg = BubbleStyleDialog(win, run.result.figure, run.style.get("bubble"), full_style=run.style)
                self.addCleanup(dlg.deleteLater)
                dlg.tabs.setCurrentIndex(2)
                dlg.level_symbols._combos[0][1].set_value("*")
                self.assertTrue(dlg.preview())
                self.assertEqual(getattr(run.result.figure, ATTR)["rendered_points"]["markers"][0], "*")
                dlg.reject()  # Cancel/Esc restores previous symbol mapping
                self.assertNotEqual(getattr(run.result.figure, ATTR)["rendered_points"]["markers"][0], "*")

                dlg2 = BubbleStyleDialog(win, run.result.figure, run.style.get("bubble"), full_style=run.style)
                self.addCleanup(dlg2.deleteLater)
                dlg2.level_symbols._combos[0][1].set_value("p")
                dlg2.accept()
                new_style = {**(run.style or {}), "bubble": dlg2.result}
                win.commit_style(run, new_style)
                self.assertEqual(getattr(run.result.figure, ATTR)["rendered_points"]["markers"][0], "p")

            # Export figure & save/reopen .alab with customized symbol map intact.
            alab = Path(self._tmp) / f"bubble-{lang}-{mode}.alab"
            win.project.save(alab)
            reopened = Project()
            reopened.load(alab)
            res_re = compute(reopened.runs[0], reopened.tables["misure"].raw)
            self.assertEqual(getattr(res_re.figure, ATTR)["rendered_points"]["markers"][0], "p")
            win.project.dirty = False
            if win.inspector is not None:
                win.inspector.discard()
                win.dispose_inspector()
            win.close()

    def test_format_dialog_keeps_an_inner_confirmation_pending(self):
        frame = _load_misure()
        project = Project()
        title, = project.add_tables({"Observations": frame})
        run = project.candidate(title, BUBBLE, {
            "X": "x", "Y": "y", "Size": "area", FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "segnale",
        })
        result = compute(run, frame)
        project.add_result(run, result)
        dialog = GraphFormatDialog(None, result.figure.axes[0], {})
        self.addCleanup(dialog.deleteLater)
        state = getattr(result.figure, ATTR)

        def edit(dialog):
            dialog.palette.set_value("Blue–red")
            dialog.accept()
            self.assertEqual(state["effective_encoding"]["palette"], "Blue–red")
            return QDialog.DialogCode.Accepted

        with mock.patch.object(BubbleStyleDialog, "exec", edit):
            dialog.edit_bubble()
        self.assertEqual(state["effective_encoding"]["palette"], "Viridis")
        self.assertEqual(dialog.style["bubble"]["palette"], "Blue–red")
        dialog.reject()
        self.assertFalse(run.style)
        self.assertEqual(state["effective_encoding"]["palette"], "Viridis")

    def test_italian_field_error_and_shape_warning_displayed(self):
        set_language("it")
        theme.install_qt_translations(self.app, "it")
        df = pd.DataFrame({
            "x": [1.0, 2.0], "y": [3.0, 4.0], "s": [1.0, 2.0], "sig": [10.0, 20.0],
        })
        dlg = AnalysisDialog(None, df, only=BUBBLE)
        self.addCleanup(dlg.deleteLater)
        dlg.controls[FILL_MODE][1].setCurrentIndex(dlg.controls[FILL_MODE][1].findData(FILL_CONTINUOUS))
        dlg.controls[COLOR_COLUMN][1].setCurrentIndex(dlg.controls[COLOR_COLUMN][1].findData("sig"))
        dlg.controls[COLOR_LIMITS][1].setCurrentIndex(dlg.controls[COLOR_LIMITS][1].findData("Manual"))
        dlg.controls[COLOR_MIN][1].setText("50")
        dlg.controls[COLOR_MAX][1].setText("10")
        dlg.accept()
        self.assertIsNone(dlg.result)
        self.assertEqual(dlg.error_field, COLOR_MIN)
        self.assertFalse(dlg.banner.isHidden())
        self.assertIn("minimo", dlg.banner.text().casefold())

        # Also verify >12 levels warning inside LevelSymbolDialog in Italian
        levels13 = [(f"str:L{i}", f"L{i}", "bubble.style.type.text") for i in range(13)]
        sym13 = LevelSymbolDialog(dlg, levels13, {})
        self.addCleanup(sym13.deleteLater)
        self.assertFalse(sym13.editor.warning.isHidden())
        self.assertIn("12", sym13.editor.warning.text())
