"""The Qt dialog saves only the options of the selected clustering algorithm."""
import unittest

import pandas as pd

from analisi import kmeans_options as km
from analisi.i18n import active_language, set_language
from analisi.workbench import analyse

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtKmeansOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-kmeans-test", "-platform", "offscreen"])

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("it")
        self.frame = pd.DataFrame({"Signal": [0., 1., 2., 3., 4., 6.]})

    def dialog(self, method, options):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.frame, current=(method, options), only=method)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog

    def test_only_active_iterations_are_saved_and_drafts_survive_switches(self):
        dialog = self.dialog(km.SELECTION, {km.ALGORITHM: km.HARTIGAN, km.MAX_ITERATIONS: 31})
        algorithm = dialog.controls[km.ALGORITHM][1]
        hartigan = dialog.controls[km.MAX_ITERATIONS][1]
        macqueen = dialog.controls[km.MACQUEEN_ITERATIONS][1]
        hartigan.setText("draft")
        algorithm.setCurrentIndex(algorithm.findData(km.MACQUEEN))
        self.assertTrue(hartigan.isHidden())
        self.assertFalse(macqueen.isHidden())
        self.assertEqual(dialog.options()[km.MACQUEEN_ITERATIONS], km.DEFAULT_ITERATIONS)
        self.assertNotIn(km.MAX_ITERATIONS, dialog.options())
        self.assertNotIn(km.INITIAL_ROWS, dialog.options())
        algorithm.setCurrentIndex(algorithm.findData(km.HARTIGAN))
        self.assertEqual(hartigan.text(), "draft")
        algorithm.setCurrentIndex(algorithm.findData(km.LLOYD))
        self.assertTrue(hartigan.isHidden())
        self.assertTrue(macqueen.isHidden())
        self.assertNotIn(km.MACQUEEN_ITERATIONS, dialog.options())

    def test_invalid_initial_rows_focus_in_place_and_corrected_fit_is_canonical(self):
        dialog = self.dialog(km.CLUSTERING, {km.ALGORITHM: km.MACQUEEN, "Standardize": False,
                                           km.INITIAL_ROWS: "1, 1", km.MACQUEEN_ITERATIONS: 0})
        iterations = dialog.controls[km.MACQUEEN_ITERATIONS][1]
        initial = dialog.controls[km.INITIAL_ROWS][1]
        self.assertEqual(dialog.rows[km.MACQUEEN_ITERATIONS][0].text(), "Limite di iterazioni MacQueen")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), iterations)
        iterations.setText("10")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), initial)
        self.assertIn("virgole", dialog.banner.text())
        initial.setText("1, 2")
        dialog.accept()
        method, request = dialog.result
        self.assertEqual(request[km.ALGORITHM], "MacQueen")
        self.assertEqual(request[km.MACQUEEN_ITERATIONS], 10)
        self.assertEqual(analyse(method, self.frame, request).tables["Assignments"]["Cluster"].tolist(),
                         [1, 1, 1, 2, 2, 2])
