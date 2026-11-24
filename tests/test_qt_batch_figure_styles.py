"""Change → Apply style to multiple graphs… on Qt (offscreen): homonyms, layout, static preview, undo/redo, errors, scale."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
import pandas as pd

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from matplotlib.colors import to_hex

PUBLICATION = {
    "version": 1,
    "name": "Pubblicazione",
    "style": {"accent": "#0B7A73", "font_family": "serif", "title_size": 17, "grid": True, "legend": "upper right"},
}
SHAPE_A = {
    "id": "0b7a7300-0000-4000-8000-000000000101",
    "kind": "rectangle",
    "units": "axes",
    "points": [[0.08, 0.55], [0.30, 0.80]],
    "stroke": "#AA4433",
    "width": 1.5,
    "line_style": "dashed",
    "fill": None,
    "alpha": 1.0,
    "layer": "above",
}
SHAPE_B = {
    "id": "0b7a7300-0000-4000-8000-000000000102",
    "kind": "ellipse",
    "units": "axes",
    "points": [[0.55, 0.15], [0.85, 0.40]],
    "stroke": "#225588",
    "width": 2.0,
    "line_style": "solid",
    "fill": None,
    "alpha": 0.9,
    "layer": "above",
}


def _app():
    app = QApplication.instance() or QApplication(["trama-batch-style-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class BatchFigureStylesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.graph_style_presets import PresetLibrary, library_path
        from trama_qt.window import MainWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.prefs = self.folder / "prefs"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.prefs), "APPDATA": str(self.prefs)})
        env.start()
        self.addCleanup(env.stop)
        self.library_file = library_path()
        self.assertTrue(str(self.library_file).startswith(str(self.prefs)))
        PresetLibrary(self.library_file).save(PUBLICATION)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        from PySide6.QtCore import QEvent

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

    def calculate(self, title, method, options, *, label=None):
        frame = self.window.project.tables[title].frame(mask_excluded=True)
        candidate = self.window.project.candidate(title, method, options)
        if label is not None:
            candidate.label = label
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNotNone(run.result)
        self.assertIsNone(run.calculation_error)
        return run

    def commit(self, run, style):
        from analisi.presentation import apply_style

        apply_style(run.result.figure, style)
        self.window.project.commit_style(run, deepcopy(style), record_shapes=False)

    def engine_counter(self):
        import trama_qt.project as project_module
        import trama_qt.window as window_module

        calls = []

        def counter(name):
            return lambda *args, **kwargs: calls.append(name)

        self._engine_patches = patches = [
            mock.patch.object(project_module, "compute", side_effect=counter("compute")),
            mock.patch.object(window_module, "compute", side_effect=counter("compute")),
            mock.patch.object(project_module, "xy_series", side_effect=counter("xy_series")),
            mock.patch.object(project_module, "analyse", side_effect=counter("analyse")),
        ]
        for patch in patches:
            patch.start()
        self.addCleanup(self.stop_engine_counter)
        return calls

    def stop_engine_counter(self):
        for patch in getattr(self, "_engine_patches", []):
            patch.stop()
        self._engine_patches = []

    def run_dialog(self, steps):
        from trama_qt.batch_figure_styles_dialog import BatchFigureStylesDialog

        seen = {}

        def drive(dialog):
            seen["dialog"] = dialog
            dialog.show()
            self.app.processEvents()
            seen["value"] = steps(dialog)
            self.app.processEvents()
            return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected

        with mock.patch.object(BatchFigureStylesDialog, "exec", lambda dialog: drive(dialog)):
            self.window.batch_figure_styles()
        return seen.get("value"), seen.get("dialog")

    def build_rich_project(self):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.legacy_restore import LEGACY_PREVIEW, LEGACY_TITLE, SAVED_BINARY_GRAPH
        from analisi.presentation import Layout

        project = self.window.project
        project.add_tables({
            "Foglio Alfa": pd.DataFrame({"Dose": [1.0, 2.0, 4.0, 8.0, 16.0], "Risposta": [2.1, 3.3, 5.8, 8.1, 9.4],
                                         "Controllo": [1.9, 2.8, 4.4, 6.2, 7.5]}),
            "Foglio Beta": pd.DataFrame({"Dose": [1.0, 2.0, 4.0, 8.0, 16.0], "Risposta": [1.7, 3.0, 5.1, 7.6, 8.9],
                                         "Controllo": [1.4, 2.2, 3.9, 5.5, 6.8]}),
            "Foglio Gamma": pd.DataFrame({"X": [1.0, 2.0, 3.0, 4.0, 5.0], "Y": [2.0, 4.1, 5.9, 8.2, 9.8]}),
        })
        # Two homonymous graphs on different source sheets
        hom1 = self.calculate("Foglio Alfa", "XY series",
                              {"X": "Dose", "Y columns": ["Risposta", "Controllo"], "Drawing": "Line and points"},
                              label="Curva dose")
        hom2 = self.calculate("Foglio Beta", "XY series",
                              {"X": "Dose", "Y columns": ["Risposta", "Controllo"], "Drawing": "Line and points"},
                              label="Curva dose")
        # Third eligible analysis graph (not selected in main batch test)
        unselected = self.calculate("Foglio Gamma", "Linear regression", {"X": "X", "Y": "Y"})
        # Figure-less result (excluded from dialog)
        self.calculate("Foglio Gamma", "Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"})
        # Pending graph (not calculated yet)
        pending = project.candidate("Foglio Gamma", "XY series", {"X": "X", "Y columns": ["Y"]})
        pending.label = "In attesa"
        project.tables["Foglio Gamma"].analyses.append((pending.method, pending.options))
        pending.slot = len(project.tables["Foglio Gamma"].analyses) - 1
        project.runs.append(pending)
        # Static imported preview (non-editable)
        static_opts = {LEGACY_TITLE: "Anteprima statica", LEGACY_PREVIEW: {"format": "emf", "data": ""}}
        project.tables["Foglio Gamma"].analyses.append((SAVED_BINARY_GRAPH, static_opts))
        static_run = project.runs_for("Foglio Gamma", project.tables["Foglio Gamma"])[-1]
        project.runs.append(static_run)

        from analisi.presentation import graph_series
        s1_key = graph_series(hom1.result.figure.axes[0])[1].key
        s2_key = graph_series(hom2.result.figure.axes[0])[1].key
        style1 = {
            "title": "Curva Alfa",
            "xlabel": "Dose (mg)",
            "ylabel": "Risposta A",
            "xscale": "log",
            "axis": {"y": {"min": 0.0, "max": 12.0}},
            "accent": "#AA4433",
            "grid": False,
            "series": {s1_key: {"color": "#224499"}},
            "shapes": [SHAPE_A],
        }
        style2 = {
            "title": "Curva Beta",
            "xlabel": "Dose (uM)",
            "ylabel": "Risposta B",
            "yscale": "log",
            "accent": "#993366",
            "grid": False,
            "series": {s2_key: {"color": "#336633"}},
            "shapes": [SHAPE_B],
        }
        style_unsel = {
            "title": "Regressione invariata",
            "accent": "#553311",
            "grid": False,
        }
        self.commit(hom1, style1)
        self.commit(hom2, style2)
        self.commit(unselected, style_unsel)

        layout = Layout("Layout confronto", 2, [hom1.reference, hom2.reference], AUTO_PAPER, WHITE)
        layout_idx = project.put_layout(layout)
        project.dirty = False
        self.window.refresh()
        return {
            "hom1": hom1,
            "hom2": hom2,
            "unselected": unselected,
            "pending": pending,
            "static": static_run,
            "layout_idx": layout_idx,
        }

    def test_homonyms_unselected_layout_static_preview_undo_redo_export_reopen(self):
        from trama_qt import graph_style_presets as gsp
        from trama_qt.gallery_catalog import describe as describe_card

        env = self.build_rich_project()
        hom1, hom2, unsel = env["hom1"], env["hom2"], env["unselected"]
        pending, static_run = env["pending"], env["static"]
        layout_idx = env["layout_idx"]
        window = self.window

        # Action must be in Change menu and enabled even on a data worksheet.
        self.assertIn(window.actions["batch_figure_styles"], window.command_menus["Change"].actions())
        window.open_sheet(("data", "Foglio Alfa"))
        self.assertTrue(window.actions["batch_figure_styles"].isEnabled())

        # Open hom1 with Inspector visible so Inspector refresh is also verified.
        hom1_idx = window.project.runs.index(hom1)
        window.open_sheet(("graph", hom1_idx))
        window.toggle_inspector()
        self.assertIsNotNone(window.inspector)

        before1, before2, before_unsel = deepcopy(hom1.style), deepcopy(hom2.style), deepcopy(unsel.style)
        layout_card_before = describe_card(window.project, ("layout", layout_idx))
        hom1_card_before = describe_card(window.project, ("graph", hom1_idx))

        calls = self.engine_counter()

        def apply_homonyms(dialog):
            # Layout and figure-less Transform are excluded; homonyms share name but have distinct UIDs.
            row_uids = [row.uid for row in dialog.rows]
            self.assertEqual(len(row_uids), len(set(row_uids)))
            self.assertIn(hom1.uid, row_uids)
            self.assertIn(hom2.uid, row_uids)
            self.assertIn(unsel.uid, row_uids)
            self.assertIn(pending.uid, row_uids)
            self.assertIn(static_run.uid, row_uids)
            self.assertEqual(len(dialog.rows), 5)

            # Active eligible graph is preselected.
            self.assertEqual(dialog.selected_uids(), [hom1.uid])
            # Non-applicable rows show an explicit reason and cannot be checked by Select all.
            by_uid = {row.uid: row for row in dialog.rows}
            self.assertFalse(by_uid[pending.uid].eligible)
            self.assertTrue(by_uid[pending.uid].reason)
            self.assertFalse(by_uid[static_run.uid].eligible)
            self.assertTrue(by_uid[static_run.uid].reason)
            dialog.select_all_button.click()
            self.assertEqual(dialog.selected_uids(), [hom1.uid, hom2.uid, unsel.uid])
            dialog.select_none_button.click()
            self.assertEqual(dialog.selected_uids(), [])
            self.assertFalse(dialog.apply_button.isEnabled())

            # Select both homonyms by stable UID.
            dialog.set_checked_uids([hom1.uid, hom2.uid])
            self.assertTrue(dialog.apply_button.isEnabled())
            self.assertFalse(dialog.preview_image.pixmap().isNull())
            self.assertIsNot(dialog._preview_figure, hom1.result.figure)
            dialog.accept()

        self.run_dialog(apply_homonyms)
        self.assertEqual(self.errors, [])
        self.assertEqual(calls, [])

        expected1 = gsp.apply_preset(before1, PUBLICATION)
        expected2 = gsp.apply_preset(before2, PUBLICATION)
        self.assertEqual(hom1.style, expected1)
        self.assertEqual(hom2.style, expected2)
        self.assertEqual(unsel.style, before_unsel)

        # Verify artists on both homonyms preserved title, axes, per-series colour, shapes and got preset look.
        ax1, ax2 = hom1.result.figure.axes[0], hom2.result.figure.axes[0]
        self.assertEqual(ax1.get_title(), "Curva Alfa")
        self.assertEqual(ax1.get_xscale(), "log")
        self.assertEqual(ax1.get_ylim(), (0.0, 12.0))
        self.assertEqual(to_hex(ax1.lines[0].get_color()), "#0b7a73")
        self.assertEqual(to_hex(ax1.lines[1].get_color()), "#224499")
        self.assertEqual(len(ax1._tramastat_shapes), 1)
        self.assertTrue(ax1.xaxis.get_gridlines()[0].get_visible())

        self.assertEqual(ax2.get_title(), "Curva Beta")
        self.assertEqual(ax2.get_yscale(), "log")
        self.assertEqual(to_hex(ax2.lines[0].get_color()), "#0b7a73")
        self.assertEqual(to_hex(ax2.lines[1].get_color()), "#336633")
        self.assertEqual(len(ax2._tramastat_shapes), 1)
        self.assertTrue(ax2.xaxis.get_gridlines()[0].get_visible())

        # Unselected graph was untouched.
        self.assertEqual(to_hex(unsel.result.figure.axes[0].lines[0].get_color()), "#553311")

        # Gallery signatures updated for both graph and layout (cache invalidation).
        self.assertNotEqual(describe_card(window.project, ("graph", hom1_idx)).sig, hom1_card_before.sig)
        self.assertNotEqual(describe_card(window.project, ("layout", layout_idx)).sig, layout_card_before.sig)

        # Inspector stayed open and refreshed to the confirmed style.
        self.assertIsNotNone(window.inspector)
        self.assertEqual(window.inspector.draft, expected1)
        self.assertTrue(window.inspector.widgets["grid"].isChecked())

        # Export layout reflects updated styles.
        layout_svg = self.folder / "layout-styled.svg"
        window.project.export_layout(window.project.layouts[layout_idx], layout_svg)
        self.assertIn("#0b7a73", layout_svg.read_text(encoding="utf-8").lower())

        # Save and reopen preserves styles.
        saved = self.folder / "batch-styled.alab"
        window.project.save(saved)

        # Single Undo reverts both homonyms at once (zero recalculations).
        self.assertTrue(window.actions["undo"].isEnabled())
        window.actions["undo"].trigger()
        self.assertEqual(calls, [])
        self.assertEqual(hom1.style, before1)
        self.assertEqual(hom2.style, before2)
        self.assertEqual(unsel.style, before_unsel)
        self.assertEqual(to_hex(hom1.result.figure.axes[0].lines[0].get_color()), "#aa4433")
        self.assertEqual(to_hex(hom2.result.figure.axes[0].lines[0].get_color()), "#993366")
        self.assertFalse(hom1.result.figure.axes[0].xaxis.get_gridlines()[0].get_visible())
        self.assertFalse(hom2.result.figure.axes[0].xaxis.get_gridlines()[0].get_visible())
        self.assertEqual(len(hom1.result.figure.axes[0]._tramastat_shapes), 1)
        self.assertEqual(len(hom2.result.figure.axes[0]._tramastat_shapes), 1)

        # Single Redo reapplies both homonyms at once (zero recalculations).
        self.assertTrue(window.actions["redo"].isEnabled())
        window.actions["redo"].trigger()
        self.assertEqual(calls, [])
        self.assertEqual(hom1.style, expected1)
        self.assertEqual(hom2.style, expected2)
        self.assertEqual(to_hex(hom1.result.figure.axes[0].lines[0].get_color()), "#0b7a73")
        self.assertEqual(to_hex(hom2.result.figure.axes[0].lines[0].get_color()), "#0b7a73")

        # Reopen the saved project and verify persisted styles match.
        self.stop_engine_counter()
        window.open_path(saved)
        for idx in (0, 1, 2):
            window.open_sheet(("graph", idx))
            self.wait()
        self.assertEqual(window.project.runs[0].style, expected1)
        self.assertEqual(window.project.runs[1].style, expected2)
        self.assertEqual(window.project.runs[2].style, before_unsel)

    def test_mini_preview_cancel_empty_selection_already_applied_and_second_target_failure(self):
        env = self.build_rich_project()
        hom1, hom2 = env["hom1"], env["hom2"]
        window = self.window
        window.open_sheet(("graph", 0))
        lib_bytes_before = self.library_file.read_bytes()
        before1, before2 = deepcopy(hom1.style), deepcopy(hom2.style)
        color1_before = to_hex(hom1.result.figure.axes[0].lines[0].get_color())
        color2_before = to_hex(hom2.result.figure.axes[0].lines[0].get_color())

        # 1. Mini preview + Esc clears preview and leaves project & library untouched.
        def preview_then_esc(dialog):
            self.assertFalse(dialog.preview_image.pixmap().isNull())
            self.assertIsNotNone(dialog._preview_figure)
            # Original figure was never altered by the preview copy.
            self.assertEqual(to_hex(hom1.result.figure.axes[0].lines[0].get_color()), color1_before)
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            self.assertTrue(dialog.preview_image.pixmap().isNull())
            self.assertIsNone(dialog._preview_figure)

        self.run_dialog(preview_then_esc)
        self.assertEqual(hom1.style, before1)
        self.assertFalse(window.project.dirty)
        self.assertFalse(window.project.history.can_apply())
        self.assertEqual(self.library_file.read_bytes(), lib_bytes_before)

        # 2. Empty selection cannot accept; Cancel leaves project untouched.
        def empty_then_cancel(dialog):
            dialog.select_none_button.click()
            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.accept()  # Must stay rejected with banner error
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.banner.objectName(), "errorBanner")
            dialog.reject()
            self.assertTrue(dialog.preview_image.pixmap().isNull())

        self.run_dialog(empty_then_cancel)
        self.assertFalse(window.project.dirty)
        self.assertFalse(window.project.history.can_apply())

        # 3. Simulated error on the second target rolls back the first figure completely.
        import trama_qt.project as project_module
        real_apply = project_module.apply_style
        apply_calls = {"n": 0}

        def fail_second(figure, style):
            apply_calls["n"] += 1
            if apply_calls["n"] == 2:
                raise ValueError("Simulated draw failure on second target")
            return real_apply(figure, style)

        def select_both(dialog):
            dialog.set_checked_uids([hom1.uid, hom2.uid])
            dialog.accept()

        with mock.patch.object(project_module, "apply_style", side_effect=fail_second):
            self.run_dialog(select_both)

        self.assertEqual(len(self.errors), 1)
        self.assertIn("Simulated draw failure", self.errors[0])
        self.assertEqual(hom1.style, before1)
        self.assertEqual(hom2.style, before2)
        self.assertEqual(to_hex(hom1.result.figure.axes[0].lines[0].get_color()), color1_before)
        self.assertEqual(to_hex(hom2.result.figure.axes[0].lines[0].get_color()), color2_before)
        self.assertFalse(window.project.dirty)
        self.assertFalse(window.project.history.can_apply())
        self.assertEqual(self.library_file.read_bytes(), lib_bytes_before)
        self.errors.clear()

        # 4. Already-applied style: zero mutations, no new undo step.
        self.run_dialog(select_both)
        self.assertEqual(self.errors, [])
        self.assertTrue(window.project.history.can_apply())
        hist_pos = window.project.history.position
        window.project.dirty = False

        self.run_dialog(select_both)
        self.assertEqual(self.errors, [])
        self.assertFalse(window.project.dirty)
        self.assertEqual(window.project.history.position, hist_pos)
        self.assertEqual(self.library_file.read_bytes(), lib_bytes_before)

    def test_inspector_draft_is_settled_before_opening_and_changed_run_is_rejected(self):
        env = self.build_rich_project()
        hom1, hom2 = env["hom1"], env["hom2"]
        window = self.window
        window.open_sheet(("graph", 0))
        window.toggle_inspector()
        window.inspector.widgets["title"].setText("Bozza non salvata")
        window.inspector._now("title")
        self.assertTrue(window.inspector.has_draft)

        # Cancel in draft prompt prevents opening the batch dialog.
        opened = []
        with mock.patch("trama_qt.window.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Cancel):
            self.run_dialog(lambda d: opened.append(d))
        self.assertEqual(opened, [])

        # Discard draft lets the dialog open; mutating a target while open aborts commit cleanly.
        before2 = deepcopy(hom2.style)

        def mutate_then_accept(dialog):
            dialog.set_checked_uids([hom1.uid, hom2.uid])
            hom2.style = {**hom2.style, "title": "Modificato altrove"}
            dialog.accept()

        with mock.patch("trama_qt.window.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Discard):
            self.run_dialog(mutate_then_accept)
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(hom2.style["title"], "Modificato altrove")
        self.assertNotEqual(hom1.style.get("accent"), PUBLICATION["style"]["accent"])
        self.assertEqual(before2["accent"], hom2.style["accent"])

    def test_scale_30_graphs_1000_points_zero_recalc(self):
        project = self.window.project
        x = np.linspace(1.0, 100.0, 1000)
        tables = {}
        for idx in range(30):
            tables[f"Serie {idx + 1:02d}"] = pd.DataFrame({"X": x, "Y": np.sin(x / (idx + 2)) + idx * 0.1})
        project.add_tables(tables)
        from trama_qt.project import compute
        for idx in range(30):
            title = f"Serie {idx + 1:02d}"
            run = project.candidate(title, "XY series", {"X": "X", "Y columns": ["Y"], "Drawing": "Line"})
            run.result = compute(run, project.tables[title].frame(mask_excluded=True))
            project.tables[title].analyses.append((run.method, run.options))
            run.slot = 0
            project.runs.append(run)
        project.dirty = False
        self.window.refresh()
        self.window.open_sheet(("graph", 0))

        calls = self.engine_counter()
        timings = {}

        from trama_qt.batch_figure_styles_dialog import BatchFigureStylesDialog
        from trama_qt.graph_style_presets import PresetLibrary

        t0 = time.perf_counter()
        rows = __import__("trama_qt.batch_figure_styles_dialog", fromlist=["batch_style_rows"]).batch_style_rows(project)
        dialog = BatchFigureStylesDialog(self.window, project, rows, PresetLibrary(), current_uid=project.runs[0].uid)
        dialog.show()
        self.app.processEvents()
        timings["open_s"] = time.perf_counter() - t0
        dialog.select_all_button.click()
        self.assertEqual(len(dialog.selected_uids()), 30)
        dialog.accept()
        selected_uids, preset = dialog.result
        dialog.deleteLater()

        t1 = time.perf_counter()
        outcome = project.commit_style_batch(selected_uids, preset)
        timings["commit_s"] = time.perf_counter() - t1
        self.window.update_actions()

        self.assertEqual(len(outcome.changed_uids), 30)
        self.assertEqual(calls, [])
        self.assertLess(timings["open_s"], 15.0)
        self.assertLess(timings["commit_s"], 30.0)
        # Single Undo reverts all 30 graphs with zero recalculations.
        self.window.actions["undo"].trigger()
        self.assertEqual(calls, [])
        self.assertTrue(all(run.style is None for run in project.runs))


if __name__ == "__main__":
    unittest.main()
