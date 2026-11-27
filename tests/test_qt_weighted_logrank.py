"""The weighted log-rank selector in the Classic Qt Kaplan–Meier dialog, offscreen."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language, tr
from analisi.weighted_logrank import (CUSTOM, DETAIL, DETAIL_SHEET, EARLY, GAMMA, GLOBAL, RHO, TARONE, WEIGHTING)

HERE = Path(__file__).resolve().parent / "data" / "weighted-logrank"
KM = "Kaplan–Meier survival"


def _app():
    app = QApplication.instance() or QApplication(["trama-weighted-logrank", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
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

    def cohort(self):
        return pd.read_csv(HERE / "coorti.csv")

    def dialog(self, language="en", saved=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        set_language(language)
        current = (KM, saved or {"Time": "tempo", "Event columns": ["evento"], "Grouping variables": ["gruppo"]})
        dialog = AnalysisDialog(self.window, self.cohort(), current=current, only=KM)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_exponents_appear_only_for_a_custom_weight_and_the_recipe_stays_canonical(self):
        dialog = self.dialog()
        self.assertLessEqual(dialog.width(), 1024)
        self.assertLessEqual(dialog.height(), 768)
        banner = next(label for label in dialog.findChildren(QLabel) if label.objectName() == "infoBanner")
        self.assertIn("Kaplan–Meier curves", banner.text())
        self.assertIn("early weight", banner.text())
        rho, gamma, detail = (dialog.controls[name][1] for name in (RHO, GAMMA, DETAIL))
        self.assertIn(RHO, dialog.hidden)
        self.assertIn(GAMMA, dialog.hidden)
        self.assertIn(DETAIL, dialog.hidden)
        weighting = dialog.controls[WEIGHTING][1]
        self.assertEqual(weighting.currentData(), "None")
        self.assertNotIn(WEIGHTING, dialog.options())

        weighting.setCurrentIndex(weighting.findData(TARONE))
        self.app.processEvents()
        self.assertIn(RHO, dialog.hidden)
        self.assertNotIn(DETAIL, dialog.hidden)
        self.assertFalse(detail.isChecked())
        saved = dialog.options()
        self.assertEqual(saved[WEIGHTING], TARONE)
        self.assertNotIn(RHO, saved)
        self.assertNotIn(DETAIL, saved)

        weighting.setCurrentIndex(weighting.findData(CUSTOM))
        self.app.processEvents()
        self.assertNotIn(RHO, dialog.hidden)
        self.assertNotIn(GAMMA, dialog.hidden)
        rho.setText("2")
        gamma.setText("0.5")
        detail.setChecked(True)
        saved = dialog.options()
        self.assertEqual(saved[RHO], 2.0)
        self.assertEqual(saved[GAMMA], 0.5)
        self.assertIs(saved[DETAIL], True)

        rho.setText("-1")
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("greater than or equal to zero", dialog.banner.text())
        self.assertEqual(dialog.error_field, RHO)

    def test_tab_enter_and_escape(self):
        dialog = self.dialog()
        weighting = dialog.controls[WEIGHTING][1]
        weighting.setFocus()
        self.app.processEvents()
        QTest.keyClick(weighting, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertIsNot(dialog.focusWidget(), weighting)
        self.assertNotEqual(dialog.focusWidget().focusPolicy(), Qt.FocusPolicy.NoFocus)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertIsNone(dialog.result)

        again = self.dialog()
        choice = again.controls[WEIGHTING][1]
        choice.setCurrentIndex(choice.findData(EARLY))
        again.controls[DETAIL][1].setChecked(True)
        QTest.keyClick(again, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIsNotNone(again.result)
        self.assertEqual(again.result[1][WEIGHTING], EARLY)
        self.assertNotIn(RHO, again.result[1])
        self.assertIs(again.result[1][DETAIL], True)

    def test_italian_labels_and_right_aligned_weight_column(self):
        from analisi.workbench import analyse
        from trama_qt.models import FrameModel
        from trama_qt.result_tabs import result_labels

        dialog = self.dialog("it")
        banner = next(label for label in dialog.findChildren(QLabel) if label.objectName() == "infoBanner")
        self.assertIn("curve di Kaplan–Meier", banner.text())
        weighting = dialog.controls[WEIGHTING][1]
        captions = [weighting.itemText(i) for i in range(weighting.count())]
        self.assertIn("Fleming–Harrington precoce (1, 0)", captions)
        self.assertIn("Fleming–Harrington tardivo (0, 1)", captions)
        self.assertEqual(tr("weight.sheet.detail"), "Dettaglio dei pesi")
        weighting.setCurrentIndex(weighting.findData(CUSTOM))
        dialog.controls[RHO][1].setText("-1")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("maggiore o uguale a zero", dialog.banner.text())

        set_language("en")
        result = analyse(KM, self.cohort(), {"Time": "tempo", "Event": "evento", "Group": "gruppo",
                                             WEIGHTING: TARONE, DETAIL: True, "Pairwise correction": "Holm"})
        set_language("it")
        title, headers = result_labels(KM, DETAIL_SHEET)
        self.assertEqual(title, "Dettaglio dei pesi")
        model = FrameModel(result.tables[DETAIL_SHEET], header_labels=headers)
        column = list(result.tables[DETAIL_SHEET].columns).index("Weight") + 1
        alignment = model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole)
        self.assertTrue(int(alignment) & int(Qt.AlignmentFlag.AlignRight))
        self.assertEqual(model.headerData(column, Qt.Orientation.Horizontal), "Peso")
        global_model = FrameModel(result.tables[GLOBAL])
        row = list(result.tables[GLOBAL].index).index("χ²")
        stored = result.tables[GLOBAL].at["χ²", "Value"]
        self.assertEqual(global_model.plain_text(row, 1), f"{stored:.10g}")

    def test_cancel_during_the_worker_leaves_the_project_unchanged(self):
        from analisi.weighted_logrank import WeightedComparisonCancelled
        path = Path(self.tmp.name) / "coorti.csv"
        self.cohort().to_csv(path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        title = self.window.selected[1]
        before = self.window.project.tables[title].raw.copy()
        runs = len(self.window.project.runs)

        def block(*_args, **_kwargs):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job = self.window.job
                if job is not None and job.control is not None and job.control.cancel.is_set():
                    raise WeightedComparisonCancelled("The weighted comparison was cancelled.")
                time.sleep(0.02)
            raise AssertionError("cancel was not observed")

        options = {"Time": "tempo", "Event columns": ["evento"], "Grouping variables": ["gruppo"],
                   WEIGHTING: TARONE, DETAIL: True}
        with patch("analisi.weighted_logrank.contribute", block):
            candidate = self.window.project.candidate(title, KM, options)
            frame = self.window.project.tables[title].frame(mask_excluded=True)
            self.window.calculate_candidate(candidate, frame, None)
            deadline = time.monotonic() + 5
            while self.window.job is None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(self.window.job)
            self.window.cancel_calculation()
            deadline = time.monotonic() + 5
            while self.window.job is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()
        self.assertIsNone(self.window.job)
        self.assertEqual(len(self.window.project.runs), runs)
        pd.testing.assert_frame_equal(self.window.project.tables[title].raw, before)


if __name__ == "__main__":
    unittest.main()
