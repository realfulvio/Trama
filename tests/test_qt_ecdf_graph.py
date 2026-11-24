"""Qt integration tests for Empirical cumulative distribution (ECDF), offscreen."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:
    QApplication = None

import numpy as np
import pandas as pd

from analisi import ecdf_graph as ecdf
from analisi.i18n import set_language


FIXTURE = Path(__file__).resolve().parent / "data" / "ecdf_graph" / "synthetic.csv"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-ecdf-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _tick_variables(dialog, *names):
    _kind, box = dialog.controls[ecdf.VARIABLES]
    for i in range(box.count()):
        box.item(i).setCheckState(Qt.CheckState.Unchecked)
    for name in names:
        for i in range(box.count()):
            if box.item(i).text() == name:
                box.item(i).setCheckState(Qt.CheckState.Checked)


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
class EcdfQtDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        if frame is None:
            frame = pd.read_csv(FIXTURE)
        dialog = AnalysisDialog(None, frame, current=current or (ecdf.METHOD, {}), **extra)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_search_translations_and_dynamic_visibility(self):
        dialog = self._dialog()
        dialog.query.setText("cumulative")
        self.assertIn(ecdf.METHOD, [
            dialog.methods.topLevelItem(g).child(r).data(0, Qt.ItemDataRole.UserRole)
            for g in range(dialog.methods.topLevelItemCount())
            for r in range(dialog.methods.topLevelItem(g).childCount())
        ])
        self.assertNotIn(ecdf.RESPONSE, dialog.hidden)
        self.assertNotIn(ecdf.GROUP, dialog.hidden)
        self.assertIn(ecdf.VARIABLES, dialog.hidden)

        _set_combo(dialog, ecdf.INPUT, ecdf.SEPARATE)
        self.assertIn(ecdf.RESPONSE, dialog.hidden)
        self.assertIn(ecdf.GROUP, dialog.hidden)
        self.assertNotIn(ecdf.VARIABLES, dialog.hidden)

        set_language("it")
        it_dialog = self._dialog()
        self.assertEqual(it_dialog.heading.text(), "Distribuzione cumulativa empirica")
        it_dialog.query.setText("cumulativa")
        found = [
            it_dialog.methods.topLevelItem(g).child(r).data(0, Qt.ItemDataRole.UserRole)
            for g in range(it_dialog.methods.topLevelItemCount())
            for r in range(it_dialog.methods.topLevelItem(g).childCount())
        ]
        self.assertIn(ecdf.METHOD, found)

    def test_selection_order_preserved_on_reopen_and_empty_group_shows_translated_error(self):
        set_language("it")
        dialog = self._dialog()
        _set_combo(dialog, ecdf.INPUT, ecdf.SEPARATE)
        _tick_variables(dialog, "Constant", "Series B", "Series A")
        _set_combo(dialog, ecdf.Y_AXIS, ecdf.PERCENT)
        opts = dialog.options()
        self.assertEqual(opts, {
            ecdf.INPUT: ecdf.SEPARATE,
            ecdf.VARIABLES: ["Constant", "Series B", "Series A"],
            ecdf.Y_AXIS: ecdf.PERCENT,
        })

        reopened = self._dialog(current=(ecdf.METHOD, opts))
        self.assertEqual(reopened.options(), opts)

        # Selecting an empty column triggers an explicit Italian banner error without closing.
        _tick_variables(reopened, "Series A", "Empty")
        reopened.accept()
        self.assertIsNone(reopened.result)
        self.assertTrue(reopened.banner.isVisible())
        self.assertIn("Empty", reopened.banner.text())
        self.assertIn("osservazioni numeriche valide", reopened.banner.text())


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class EcdfQtWindowWorkflowTests(unittest.TestCase):
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

    def test_end_to_end_edit_recalc_format_export_and_alab_roundtrip(self):
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.window import MainWindow, export_graph

        window = self._make_window(MainWindow)
        window.resize(1024, 768)
        window.show()
        self.app.processEvents()

        raw = pd.DataFrame({
            "Series A": [-1.5, 0.0, 0.0, 2.0, 99.0],
            "Series B": [0.0, 1.0, 1.0, 3.0, np.nan],
            "Constant": [4.0, 4.0, 4.0, np.nan, np.nan],
        })
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_in = tmp / "input.csv"
            raw.to_csv(csv_in, index=False)
            window.open_path(csv_in)
            _wait(self.app, window)
            title = window.selected[1]
            # Exclude cell (row 4, col 0) = 99.0 in Series A
            window.project.tables[title].excluded.add((4, 0))
            frame = window.project.tables[title].frame(mask_excluded=True)

            # Run in Proportion mode
            recipe_prop = {
                ecdf.INPUT: ecdf.SEPARATE,
                ecdf.VARIABLES: ["Series B", "Series A", "Constant"],
                ecdf.Y_AXIS: ecdf.PROPORTION,
            }
            candidate_prop = window.project.candidate(title, ecdf.METHOD, recipe_prop)
            window.calculate_candidate(candidate_prop, frame, None)
            _wait(self.app, window)
            self.assertEqual(window.selected[0], "graph")
            idx = window.selected[1]
            run = window.project.runs[idx]
            self.assertEqual(run.method, ecdf.METHOD)
            self.assertEqual(run.result.tables[ecdf.SUMMARY_SHEET]["Group"].tolist(),
                             ["Series B", "Series A", "Constant"])
            self.assertEqual(run.result.tables[ecdf.SUMMARY_SHEET]["Excluded"].tolist(), [1, 1, 2])

            csv_prop = tmp / "points_prop.csv"
            run.result.tables[ecdf.POINTS_SHEET].to_csv(csv_prop, index=False)

            # Switch to Percent mode and confirm identical exported CSV
            recipe_pct = {**recipe_prop, ecdf.Y_AXIS: ecdf.PERCENT}
            candidate_pct = window.project.candidate(title, ecdf.METHOD, recipe_pct, index=idx)
            window.calculate_candidate(candidate_pct, frame, idx)
            _wait(self.app, window)
            run = window.project.runs[idx]
            self.assertEqual(run.result.figure.axes[0].get_ylabel(), "Cumulative probability (%)")
            csv_pct = tmp / "points_pct.csv"
            run.result.tables[ecdf.POINTS_SHEET].to_csv(csv_pct, index=False)
            self.assertEqual(csv_prop.read_bytes(), csv_pct.read_bytes())

            # Format Graph dialog applies custom title and grid cleanly
            axes = run.result.figure.axes[0]
            fmt_dlg = GraphFormatDialog(window, axes, run.style or {})
            fmt_dlg.texts["title"].setText("Formatted ECDF")
            fmt_dlg.grid.setChecked(True)
            fmt_dlg.accept()
            self.assertIsNotNone(fmt_dlg.result)
            window.project.apply_format(run, fmt_dlg.result)
            window.show_sheet(*window.selected)
            fmt_dlg.deleteLater()
            self.assertEqual(window.project.runs[idx].result.figure.axes[0].get_title(), "Formatted ECDF")

            # Export PNG, SVG and PDF
            for ext in ("png", "svg", "pdf"):
                out = tmp / f"graph.{ext}"
                export_graph(window.project.runs[idx].result.figure, out)
                self.assertTrue(out.exists() and out.stat().st_size > 200, ext)

            # Save .alab, reopen in fresh window, edit a cell, recalculate
            alab = tmp / "ecdf-project.alab"
            window.project.save(alab)

            reopened = self._make_window(MainWindow)
            reopened.open_path(alab)
            _wait(self.app, reopened)
            reopened.open_sheet(("graph", 0))
            _wait(self.app, reopened)
            run2 = reopened.project.runs[0]
            self.assertEqual(run2.options, recipe_pct)
            self.assertEqual(run2.result.figure.axes[0].get_title(), "Formatted ECDF")

            # Modify Series A row 0 from -1.5 to -4.0 and recalculate
            t2 = run2.title
            reopened.project.tables[t2].raw.iat[0, 0] = -4.0
            reopened.refresh_runs([run2])
            _wait(self.app, reopened)
            pts_after = reopened.project.runs[0].result.tables[ecdf.POINTS_SHEET]
            a_pts = pts_after[pts_after["Group"] == "Series A"]
            self.assertEqual(a_pts["X"].iloc[0], -4.0)
            self.assertEqual(reopened.project.runs[0].result.figure.axes[0].lines[1].get_xdata()[1], -4.0)


if __name__ == "__main__":
    unittest.main()
