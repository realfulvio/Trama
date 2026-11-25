"""Qt Classic desktop tests for Mann–Whitney and Wilcoxon rank/difference graphs."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTreeWidgetItemIterator

from analisi.data import Dataset, save_project
from analisi.i18n import set_language
from analisi.rank_graphs import LEGACY_P_METHOD, RANK_PLOT, WILCOXON_DIFFERENCES
from analisi.rank_tests import (
    ALTERNATIVE,
    CONTINUITY,
    EXACT,
    MANN_WHITNEY,
    PRATT,
    P_VALUE,
    WILCOXON,
    ZERO_DIFFERENCES,
)
from trama_qt import theme
from trama_qt.analysis_dialog import AnalysisDialog
from trama_qt.gallery_catalog import catalog
from trama_qt.window import MainWindow


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        theme.load_fonts()
        theme.apply(app)
    return app


def _wait_window(window, timeout=15.0):
    app = _app()
    end = time.monotonic() + timeout
    while window.job is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _navigator_refs(window):
    refs = set()
    items = QTreeWidgetItemIterator(window.navigator)
    while (item := items.value()) is not None:
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref:
            refs.add(tuple(ref))
        items += 1
    return refs


class RankGraphDialogAndWindowTests(unittest.TestCase):
    def setUp(self):
        self._old_home = os.environ.get("HOME")
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        self._old_appdata = os.environ.get("APPDATA")
        self._tmp = tempfile.TemporaryDirectory()
        cfg = os.path.join(self._tmp.name, "cfg")
        os.makedirs(cfg, exist_ok=True)
        os.environ["HOME"] = self._tmp.name
        os.environ["XDG_CONFIG_HOME"] = cfg
        os.environ["APPDATA"] = cfg
        set_language("en")
        _app()

    def tearDown(self):
        set_language("en")
        for key, value in (("HOME", self._old_home), ("XDG_CONFIG_HOME", self._old_xdg), ("APPDATA", self._old_appdata)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_dialog_defaults_are_off_and_i18n_captions_are_clean(self):
        frame = pd.DataFrame({"Response": [3.0, 7.0, 3.0, 5.0, 8.0], "Group": ["Dose $", "Dose $", "B", "B", "B"]})
        dialog = AnalysisDialog(
            None,
            frame,
            current=(MANN_WHITNEY, {"Response": "Response", "Group": "Group", P_VALUE: "Automatic"}),
        )
        try:
            self.assertFalse(dialog.controls[RANK_PLOT][1].isChecked())
            self.assertEqual(dialog.rows[RANK_PLOT][0].text(), "Plot ranks")
            self.assertNotIn(RANK_PLOT, dialog.options())
        finally:
            dialog.close()

        set_language("it")
        wx_frame = pd.DataFrame({"Prima": [5.0, 1.0, 2.0, 8.0], "Seconda": [1.0, 5.0, 2.0, 1.0]})
        dialog_it = AnalysisDialog(None, wx_frame, only=WILCOXON)
        try:
            self.assertFalse(dialog_it.controls[RANK_PLOT][1].isChecked())
            self.assertFalse(dialog_it.controls[WILCOXON_DIFFERENCES][1].isChecked())
            self.assertEqual(dialog_it.rows[RANK_PLOT][0].text(), "Grafico dei ranghi")
            self.assertEqual(dialog_it.rows[WILCOXON_DIFFERENCES][0].text(), "Grafico delle differenze appaiate")
            self.assertIsNotNone(dialog_it.controls[RANK_PLOT][1].nextInFocusChain())
        finally:
            dialog_it.close()

    def test_legacy_dialog_preserves_by_default_and_asks_before_migrating(self):
        frame = pd.DataFrame({"Response": [3.0, 7.0, 3.0, 5.0, 8.0], "Group": ["Dose $", "Dose $", "B", "B", "B"]})
        legacy_opts = {"Response": "Response", "Group": "Group"}
        dialog = AnalysisDialog(None, frame, current=(MANN_WHITNEY, legacy_opts))
        try:
            p_combo = dialog.controls[P_VALUE][1]
            self.assertEqual(p_combo.currentData(), LEGACY_P_METHOD)
            self.assertEqual(p_combo.currentText(), "Legacy (original test)")
            self.assertFalse(dialog.controls[ALTERNATIVE][1].isEnabled())
            self.assertFalse(dialog.controls[CONTINUITY][1].isEnabled())
            self.assertTrue(dialog.controls[RANK_PLOT][1].isEnabled())

            # Enabling Plot ranks under Legacy preserves the legacy recipe without asking to migrate.
            dialog.controls[RANK_PLOT][1].setChecked(True)
            with mock.patch.object(QMessageBox, "question") as asked:
                dialog.accept()
            asked.assert_not_called()
            self.assertEqual(dialog.result, (MANN_WHITNEY, {"Response": "Response", "Group": "Group", RANK_PLOT: True}))
        finally:
            dialog.close()

        # Switching away from Legacy unlocks modern controls and confirms before migrating.
        dialog2 = AnalysisDialog(None, frame, current=(MANN_WHITNEY, legacy_opts))
        try:
            p_combo = dialog2.controls[P_VALUE][1]
            p_combo.setCurrentIndex(p_combo.findData(EXACT))
            self.assertTrue(dialog2.controls[ALTERNATIVE][1].isEnabled())
            self.assertFalse(dialog2.controls[CONTINUITY][1].isEnabled())  # disabled on Exact conditional

            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as declined:
                dialog2.accept()
            declined.assert_called_once()
            self.assertIsNone(dialog2.result)

            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                dialog2.accept()
            self.assertEqual(dialog2.result[1][P_VALUE], EXACT)
        finally:
            dialog2.close()

    def test_pending_graph_in_navigator_and_gallery_after_reopen_and_recalc_on_cell_edit(self):
        mw_ds = Dataset(
            pd.DataFrame({
                "Value": [3.0, 7.0, 3.0, 5.0, 8.0],
                "Group": ["Dose $", "Dose $", "B", "B", "B"],
            }),
            analyses=[(MANN_WHITNEY, {"Response": "Value", "Group": "Group", P_VALUE: "Automatic", RANK_PLOT: True})],
        )
        wx_ds = Dataset(
            pd.DataFrame({
                "First": [5.0, 1.0, 2.0, 8.0, np.nan],
                "Second": [1.0, 5.0, 2.0, 1.0, 9.0],
            }),
            analyses=[(
                WILCOXON,
                {
                    "First": "First",
                    "Second": "Second",
                    P_VALUE: "Automatic",
                    ZERO_DIFFERENCES: PRATT,
                    RANK_PLOT: True,
                    WILCOXON_DIFFERENCES: True,
                },
            )],
        )
        project_path = Path(self._tmp.name) / "pending.alab"
        save_project(project_path, {"MW Data": mw_ds, "WX Data": wx_ds})

        window = MainWindow()
        try:
            window.resize(1024, 768)
            window.open_path(project_path)
            _app().processEvents()

            mw_index = 0
            wx_index = 1
            self.assertIsNone(window.project.runs[mw_index].result)
            self.assertIsNone(window.project.runs[wx_index].result)

            # Pending runs must still appear in navigator Graphs and Gallery.
            nav_refs = _navigator_refs(window)
            self.assertIn(("graph", mw_index), nav_refs)
            self.assertIn(("graph", wx_index), nav_refs)

            gallery_refs = {entry.ref for entry in catalog(window.project)}
            self.assertIn(("graph", mw_index), gallery_refs)
            self.assertIn(("graph", wx_index), gallery_refs)

            # Opening a pending graph triggers background calculation and draws both panels.
            window.open_sheet(("graph", wx_index))
            _wait_window(window)
            self.assertIsNotNone(window.project.runs[wx_index].result)
            self.assertEqual(len(window.project.runs[wx_index].result.figure.axes), 2)

            # Navigating to result sheet and back preserves both views.
            window.open_sheet(("result", wx_index))
            _app().processEvents()
            self.assertEqual(window.selected, ("result", wx_index))
            window.open_sheet(("graph", wx_index))
            _app().processEvents()
            self.assertEqual(window.selected, ("graph", wx_index))

            # Modify a data cell on WX Data and recalculate -> rank graph & table update cleanly.
            affected = window.project.paste("WX Data", 0, 0, [["10"]], "Edit cell")
            window.refresh_runs(affected)
            _wait_window(window)
            updated_diffs = window.project.runs[wx_index].result.tables["Ranks"]["Difference"].tolist()
            self.assertEqual(updated_diffs, [9.0, -4.0, 0.0, 7.0])
        finally:
            window.project.dirty = False
            window.close()


if __name__ == "__main__":
    unittest.main()
