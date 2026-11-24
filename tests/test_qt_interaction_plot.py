"""Qt integration tests for the two-factor interaction plot, offscreen."""
from pathlib import Path
import tempfile
import time
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

import numpy as np
import pandas as pd

from analisi import interaction_plot as ip
from analisi.i18n import set_language


FIXTURE = Path(__file__).resolve().parent / "data" / "interaction_plot" / "interaction.csv"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-interaction-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _set_combo(dialog, field, value):
    _kind, combo = dialog.controls[field]
    idx = combo.findData(value)
    assert idx >= 0, (field, value)
    combo.setCurrentIndex(idx)


def _wait(app, window, timeout=30.0):
    end = time.monotonic() + timeout
    while window.job is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert window.job is None, "background job did not finish"


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class InteractionPlotQtDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        if frame is None:
            frame = pd.read_csv(FIXTURE, keep_default_na=False)
        dialog = AnalysisDialog(None, frame, current=current or (ip.METHOD, {}), **extra)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_en_it_captions_defaults_visibility_and_error_focus(self):
        dialog = self._dialog()
        self.assertEqual(dialog.heading.text(), "Interaction plot")
        self.assertEqual(dialog.controls[ip.RESPONSE][1].currentData(), "Response")
        self.assertEqual(dialog.controls[ip.X_FACTOR][1].currentData(), "Dose")
        self.assertEqual(dialog.controls[ip.SERIES_FACTOR][1].currentData(), "Group")
        self.assertEqual(dialog.controls[ip.ERROR_BARS][1].currentData(), ip.CI)
        self.assertNotIn(ip.CONFIDENCE_LEVEL, dialog.hidden)
        dialog.tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertTrue(dialog.interaction.help_note.isVisible())

        # Toggling error bars hides/shows Confidence level cleanly.
        _set_combo(dialog, ip.ERROR_BARS, ip.SD)
        self.assertIn(ip.CONFIDENCE_LEVEL, dialog.hidden)
        _set_combo(dialog, ip.ERROR_BARS, ip.CI)
        self.assertNotIn(ip.CONFIDENCE_LEVEL, dialog.hidden)

        # Italian UI, role error preserves selections and focuses the offending control.
        set_language("it")
        it_dialog = self._dialog()
        self.assertEqual(it_dialog.heading.text(), "Grafico d'interazione")
        _set_combo(it_dialog, ip.SERIES_FACTOR, "Dose")
        it_dialog.controls[ip.CONFIDENCE_LEVEL][1].setText("90")
        it_dialog.accept()
        self.assertIsNone(it_dialog.result)
        self.assertTrue(it_dialog.banner.isVisible())
        self.assertIn("diversa da Risposta e Fattore X", it_dialog.banner.text())
        self.assertEqual(it_dialog.error_field, ip.SERIES_FACTOR)
        self.assertEqual(it_dialog.controls[ip.CONFIDENCE_LEVEL][1].text(), "90")
        self.assertIs(it_dialog.focusWidget(), it_dialog.controls[ip.SERIES_FACTOR][1])

        # Fix the error and accept.
        _set_combo(it_dialog, ip.SERIES_FACTOR, "Group")
        it_dialog.accept()
        self.assertIsNotNone(it_dialog.result)
        self.assertEqual(it_dialog.result[1][ip.CONFIDENCE_LEVEL], 90.0)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class InteractionPlotQtWindowWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _make_window(self, factory):
        window = factory()
        window.project.dirty = False

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()

        self.addCleanup(close)
        return window

    def test_end_to_end_edit_exclude_style_alab_export_and_layout(self):
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.window import MainWindow, export_graph
        from analisi.grid_data import edit_cell_value
        from analisi.presentation import compose_layout, graph_series

        window = self._make_window(MainWindow)
        window.resize(1200, 800)
        window.show()
        self.app.processEvents()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_in = tmp / "interaction.csv"
            csv_in.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            window.open_path(csv_in)
            _wait(self.app, window)
            title = window.selected[1]
            frame = window.project.tables[title].frame(mask_excluded=True)

            recipe = {
                ip.RESPONSE: "Response",
                ip.X_FACTOR: "Dose",
                ip.SERIES_FACTOR: "Group",
                ip.ERROR_BARS: ip.CI,
                ip.CONFIDENCE_LEVEL: 95.0,
            }
            cand = window.project.candidate(title, ip.METHOD, recipe)
            window.calculate_candidate(cand, frame, None)
            _wait(self.app, window)
            self.assertEqual(window.selected[0], "graph")
            idx = window.selected[1]
            run = window.project.runs[idx]
            cells = run.result.tables[ip.CELLS_SHEET]
            self.assertAlmostEqual(cells.iloc[0]["Mean"], 4.0)
            self.assertEqual(cells.iloc[0]["N"], 3)

            # Style Control $ via Format Graph, verify literal legend and persisted style.
            axes = run.result.figure.axes[0]
            fmt = GraphFormatDialog(window, axes, run.style or {})
            fmt.texts["title"].setText("Interaction · Synthetic")
            fmt.grid.setChecked(True)
            fmt.accept()
            self.assertIsNotNone(fmt.result)
            style = dict(fmt.result)
            style.setdefault("series", {})["errorbar:1:Control $"] = {"color": "#cc3311", "marker": "D"}
            window.project.apply_format(run, style)
            window.show_sheet(*window.selected)
            fmt.deleteLater()

            # Export CSV, PNG, SVG, PDF.
            cells.to_csv(tmp / "cells.csv", index=False)
            for ext in ("png", "svg", "pdf"):
                out = tmp / f"interaction.{ext}"
                export_graph(window.project.runs[idx].result.figure, out)
                self.assertTrue(out.exists() and out.stat().st_size > 200, ext)

            # Edit first '2' -> '8': first mean changes from 4 to 6; series style stays.
            edit_cell_value(window.project.tables[title], 0, 2, "8")
            window.refresh_runs([window.project.runs[idx]])
            _wait(self.app, window)
            cells_edited = window.project.runs[idx].result.tables[ip.CELLS_SHEET]
            self.assertAlmostEqual(cells_edited.iloc[0]["Mean"], 6.0)
            ctrl_s = next(s for s in graph_series(window.project.runs[idx].result.figure.axes[0])
                          if s.key == "errorbar:1:Control $")
            self.assertEqual(ctrl_s.artist.lines[0].get_color(), "#cc3311")

            # Exclude that cell: first mean becomes 5.0 and N becomes 2; series style stays.
            window.project.tables[title].excluded.add((0, 2))
            window.refresh_runs([window.project.runs[idx]])
            _wait(self.app, window)
            cells_excl = window.project.runs[idx].result.tables[ip.CELLS_SHEET]
            self.assertAlmostEqual(cells_excl.iloc[0]["Mean"], 5.0)
            self.assertEqual(cells_excl.iloc[0]["N"], 2)

            # Second graph (None error bars) + 2-panel layout.
            cand2 = window.project.candidate(title, ip.METHOD, {**recipe, ip.ERROR_BARS: ip.NONE})
            window.calculate_candidate(cand2, window.project.tables[title].frame(mask_excluded=True), None)
            _wait(self.app, window)
            layout_fig = compose_layout(
                "Layout", 2, [window.project.runs[0].result.figure, window.project.runs[1].result.figure]
            )
            self.assertGreaterEqual(len(layout_fig.axes), 2)

            # Save .alab and reopen in fresh window.
            alab = tmp / "interaction-project.alab"
            window.project.save(alab)
            reopened = self._make_window(MainWindow)
            reopened.open_path(alab)
            _wait(self.app, reopened)
            reopened.open_sheet(("graph", 0))
            _wait(self.app, reopened)
            run_re = reopened.project.runs[0]
            self.assertEqual(run_re.options, recipe)
            self.assertAlmostEqual(run_re.result.tables[ip.CELLS_SHEET].iloc[0]["Mean"], 5.0)
            self.assertEqual(run_re.result.tables[ip.CELLS_SHEET].iloc[0]["N"], 2)


if __name__ == "__main__":
    unittest.main()
