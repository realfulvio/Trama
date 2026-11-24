"""Qt integration tests for Raincloud plot, offscreen."""
from pathlib import Path
import tempfile
import time
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

import numpy as np
import pandas as pd

from analisi import raincloud_plot as rc
from analisi.category_order import set_order
from analisi.i18n import set_language


FIXTURE = Path(__file__).resolve().parent / "data" / "raincloud_plot" / "raincloud.csv"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-raincloud-tests", "-platform", "offscreen"])
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
class RaincloudQtDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        if frame is None:
            frame = pd.read_csv(FIXTURE, keep_default_na=False)
        dialog = AnalysisDialog(None, frame, current=current or (rc.METHOD, {}), **extra)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_reopening_with_a_worker_error_keeps_the_dialog_available(self):
        set_language("it")
        generic = self._dialog(current=("Transform", {}), only="Transform", error="Calculation stopped.")
        self.assertIn("Calculation stopped.", generic.banner.text())
        raincloud = self._dialog(only=rc.METHOD, error="Choose an existing column for Group.",
                                 error_field=rc.GROUP)
        self.assertEqual(raincloud.banner.text(), "Scegli una colonna esistente per Gruppo.")
        self.assertIs(raincloud.focusWidget(), raincloud.controls[rc.GROUP][1])

    def test_en_it_dialog_conditional_bandwidth_and_focus_on_error(self):
        dlg = self._dialog()
        self.assertEqual(dlg.heading.text(), "Raincloud plot")
        self.assertEqual(dlg.controls[rc.RESPONSE][1].currentData(), "Misura")
        self.assertEqual(dlg.controls[rc.GROUP][1].currentData(), "")
        self.assertNotIn(rc.BANDWIDTH_MULTIPLIER, dlg.hidden)

        # Unchecking Show density hides Bandwidth multiplier and skips numeric check on it.
        dlg.controls[rc.BANDWIDTH_MULTIPLIER][1].setText("-2")
        dlg.controls[rc.SHOW_DENSITY][1].setChecked(False)
        self.app.processEvents()
        self.assertIn(rc.BANDWIDTH_MULTIPLIER, dlg.hidden)
        dlg.accept()
        self.assertIsNotNone(dlg.result)
        self.assertFalse(dlg.result[1][rc.SHOW_DENSITY])

        # Italian UI: turning all components off triggers translated error and focuses Show density.
        set_language("it")
        it_dlg = self._dialog()
        self.assertEqual(it_dlg.heading.text(), "Grafico raincloud")
        it_dlg.controls[rc.SHOW_DENSITY][1].setChecked(False)
        it_dlg.controls[rc.SHOW_BOX][1].setChecked(False)
        it_dlg.controls[rc.SHOW_POINTS][1].setChecked(False)
        it_dlg.accept()
        self.assertIsNone(it_dlg.result)
        self.assertTrue(it_dlg.banner.isVisible())
        self.assertIn("almeno un componente", it_dlg.banner.text())
        self.assertEqual(it_dlg.error_field, rc.SHOW_DENSITY)
        self.assertIs(it_dlg.focusWidget(), it_dlg.controls[rc.SHOW_DENSITY][1])

        # Bad bandwidth focuses Bandwidth multiplier.
        it_dlg.controls[rc.SHOW_DENSITY][1].setChecked(True)
        it_dlg.controls[rc.BANDWIDTH_MULTIPLIER][1].setText("0")
        it_dlg.accept()
        self.assertIsNone(it_dlg.result)
        self.assertEqual(it_dlg.error_field, rc.BANDWIDTH_MULTIPLIER)
        self.assertIs(it_dlg.focusWidget(), it_dlg.controls[rc.BANDWIDTH_MULTIPLIER][1])

        # Fix bandwidth and select Group + Horizontal orientation.
        it_dlg.controls[rc.BANDWIDTH_MULTIPLIER][1].setText("1,5")
        _set_combo(it_dlg, rc.GROUP, "Gruppo")
        _set_combo(it_dlg, rc.ORIENTATION, rc.HORIZONTAL)
        it_dlg.accept()
        self.assertIsNotNone(it_dlg.result)
        self.assertEqual(it_dlg.result[1][rc.ORIENTATION], rc.HORIZONTAL)
        self.assertAlmostEqual(it_dlg.result[1][rc.BANDWIDTH_MULTIPLIER], 1.5)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RaincloudQtWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def _make_window(self):
        from trama_qt.window import MainWindow
        window = MainWindow()
        window.project.dirty = False

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()

        self.addCleanup(close)
        return window

    def test_inspector_no_recalc_exclusion_reorder_format_layout_export_alab(self):
        from trama_qt.graph_format import GraphFormatDialog
        from trama_qt.inspector import GraphInspector
        from trama_qt.window import export_graph
        from analisi.presentation import compose_layout, graph_groups

        window = self._make_window()
        window.resize(1200, 800)
        window.show()
        self.app.processEvents()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_in = tmp / "raincloud.csv"
            csv_in.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            window.open_path(csv_in)
            _wait(self.app, window)
            title = window.selected[1]
            dataset = window.project.tables[title]
            frame = dataset.frame(mask_excluded=True)

            recipe = {
                rc.RESPONSE: "Misura",
                rc.GROUP: "Gruppo",
                rc.ORIENTATION: rc.VERTICAL,
                rc.SHOW_DENSITY: True,
                rc.SHOW_BOX: True,
                rc.SHOW_POINTS: True,
                rc.BANDWIDTH_MULTIPLIER: 1.0,
            }
            cand = window.project.candidate(title, rc.METHOD, recipe)
            window.calculate_candidate(cand, frame, None)
            _wait(self.app, window)
            self.assertEqual(window.selected[0], "graph")
            idx = window.selected[1]
            run = window.project.runs[idx]
            result_before = run.result

            # Change Control $ color via Inspector WITHOUT recalculating.
            canvas = window._figure_canvas(run.result.figure)
            inspector = GraphInspector(
                run, canvas,
                confirmed=lambda: run.style or {},
                commit=lambda style: window.commit_style(run, style, project=window.project),
                closed=lambda: None,
                parent=window,
            )
            inspector.select_group("raincloud:str:Control $")
            inspector.fields["color"].setText("#cc3311")
            inspector.fields["color"].editingFinished.emit()
            inspector.apply()
            inspector.deleteLater()

            self.assertIs(run.result, result_before)
            self.assertIsNone(window.job)
            ctrl = next(g for g in graph_groups(run.result.figure.axes[0]) if g.key == "raincloud:str:Control $")
            scatter = next(a for a, role in ctrl.artists if role == "point")
            self.assertAlmostEqual(float(scatter.get_facecolor()[0][0]), 0xCC / 255.0, places=2)

            # Format Graph changes title & grid while keeping group color.
            fmt = GraphFormatDialog(window, run.result.figure.axes[0], run.style or {})
            fmt.texts["title"].setText("Raincloud · Test $1")
            fmt.grid.setChecked(True)
            fmt.accept()
            self.assertIsNotNone(fmt.result)
            window.project.apply_format(run, fmt.result)
            window.show_sheet(*window.selected)
            fmt.deleteLater()
            self.assertIn("raincloud:str:Control $", run.style.get("groups", {}))

            # Export PNG, SVG, PDF and 2-panel layout.
            for ext in ("png", "svg", "pdf"):
                out = tmp / f"raincloud.{ext}"
                export_graph(run.result.figure, out)
                self.assertTrue(out.exists() and out.stat().st_size > 200, ext)

            cand2 = window.project.candidate(title, rc.METHOD, {**recipe, rc.ORIENTATION: rc.HORIZONTAL})
            window.calculate_candidate(cand2, frame, None)
            _wait(self.app, window)
            layout_fig = compose_layout(
                "Raincloud comparison", 2,
                [window.project.runs[0].result.figure, window.project.runs[1].result.figure],
            )
            self.assertGreaterEqual(len(layout_fig.axes), 2)

            # Exclude row 4 (Control $, 7) and reorder categories so Control $ moves from 1st to 3rd.
            dataset.excluded.add((4, 1))
            set_order(dataset, "Gruppo", ["str:Trattamento", "str:Costante", "str:Control $", "str:Singolo"])
            window.refresh_runs([window.project.runs[0]])
            _wait(self.app, window)

            summary = window.project.runs[0].result.tables[rc.SUMMARY_SHEET]
            self.assertEqual(list(summary["Group"]), ["Trattamento", "Costante", "Control $", "Singolo"])
            ctrl_row = summary.loc[summary["Group"] == "Control $"].iloc[0]
            self.assertEqual(int(ctrl_row["N"]), 4)
            self.assertAlmostEqual(float(ctrl_row["Maximum"]), 3.0)

            ctrl_after = next(g for g in graph_groups(window.project.runs[0].result.figure.axes[0])
                              if g.key == "raincloud:str:Control $")
            scatter_after = next(a for a, role in ctrl_after.artists if role == "point")
            self.assertAlmostEqual(float(scatter_after.get_facecolor()[0][0]), 0xCC / 255.0, places=2)

            # Save .alab and reopen in fresh window: style of Control $ still follows group.
            alab = tmp / "raincloud-project.alab"
            window.project.save(alab)
            reopened = self._make_window()
            reopened.open_path(alab)
            _wait(self.app, reopened)
            reopened.open_sheet(("graph", 0))
            _wait(self.app, reopened)
            run_re = reopened.project.runs[0]
            self.assertEqual(run_re.options, recipe)
            ctrl_re = next(g for g in graph_groups(run_re.result.figure.axes[0])
                           if g.key == "raincloud:str:Control $")
            scatter_re = next(a for a, role in ctrl_re.artists if role == "point")
            self.assertAlmostEqual(float(scatter_re.get_facecolor()[0][0]), 0xCC / 255.0, places=2)


if __name__ == "__main__":
    unittest.main()
