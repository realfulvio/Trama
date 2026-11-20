"""The Qt dialog saves only the options of the selected clustering algorithm."""
import unittest

import pandas as pd

from analisi import kmeans_options as km, kmeans_reports
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

    def test_forgy_lloyd_preserves_its_iteration_limit_in_the_italian_dialog(self):
        dialog = self.dialog(km.SELECTION, {km.ALGORITHM: km.FORGY_LLOYD, km.LLOYD_ITERATIONS: 12})
        iterations = dialog.controls[km.LLOYD_ITERATIONS][1]
        self.assertFalse(iterations.isHidden())
        self.assertEqual(dialog.rows[km.LLOYD_ITERATIONS][0].text(), "Limite di iterazioni Lloyd")
        self.assertEqual(dialog.rows[km.ALGORITHM][0].text(), "Algoritmo k-means")
        self.assertEqual(dialog.rows[km.SCALE][0].text(), "Scala delle colonne")
        self.assertEqual(dialog.rows[km.GAP_REFERENCE][0].text(), "Geometria del riferimento Gap")
        iterations.setText("0")
        dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIs(dialog.focusWidget(), iterations)
        iterations.setText("12")
        dialog.accept()
        _, options = dialog.result
        self.assertEqual(options[km.ALGORITHM], km.FORGY_LLOYD)
        self.assertEqual(options[km.LLOYD_ITERATIONS], 12)
        self.assertNotIn(km.MAX_ITERATIONS, options)

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
        self.assertEqual(request[km.SCALE], km.UNSCALED)
        self.assertEqual(analyse(method, self.frame, request).tables["Assignments"]["Cluster"].tolist(),
                         [1, 1, 1, 2, 2, 2])

    def test_centering_control_restores_old_recipes_and_exposes_scaled_report(self):
        dialog = self.dialog(km.CLUSTERING, {"Standardize": False, kmeans_reports.SCALED: True})
        scale = dialog.controls[km.SCALE][1]
        scaled = dialog.controls[kmeans_reports.SCALED][1]
        self.assertEqual(scale.currentData(), km.UNSCALED)
        self.assertTrue(scaled.isHidden())
        self.assertNotIn(kmeans_reports.SCALED, dialog.options())
        scale.setCurrentIndex(scale.findData(km.CENTERED))
        self.assertEqual(scale.currentText(), "Centrati")
        self.assertFalse(scaled.isHidden())
        self.assertTrue(dialog.options()[kmeans_reports.SCALED])
        self.assertEqual(dialog.options()[km.SCALE], km.CENTERED)
