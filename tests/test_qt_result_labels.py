import unittest

import pandas as pd

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from analisi.distribution_graphs import BOX_VIOLIN, SEPARATE, VIOLIN
from analisi.i18n import active_language, set_language


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ResultLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["result-labels", "-platform", "offscreen"])

    def test_italian_distribution_labels_preserve_frame_and_copy_headers(self):
        from trama_qt.project import compute
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language("it")
        window = MainWindow()
        self.addCleanup(self.close_window, window)
        title, = window.project.add_tables({"Dati": pd.DataFrame({"Group": [1, 2, 3, 5], "Value": [5, 6, 8, 9]})})
        recipe = window.project.candidate(title, BOX_VIOLIN, {
            "Input": SEPARATE, "Variables": ["Group", "Value"], "Style": VIOLIN, "Overlay observations": True,
        })
        result = compute(recipe, window.project.input_frame(recipe))
        window.project.add_result(recipe, result)
        window.show_sheet("result", 0)
        tabs = window.result_tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],
                         ["Riepilogo dei gruppi", "Osservazioni nel grafico", "Densità del violino", "Impostazioni"])
        view = tabs.widget(0)
        model = view.model()
        self.assertIs(model.frame, result.tables["Group summary"])
        self.assertEqual(model.headerData(1, Qt.Orientation.Horizontal), "Gruppo")
        self.assertEqual(model.data(model.index(0, 1)), "Group")
        view.selectAll()
        view.copy()
        self.assertIn("Row\tGroup\tN\tMedian", self.app.clipboard().text())

    def test_other_methods_and_unknown_result_names_stay_literal(self):
        from trama_qt.result_tabs import result_labels

        self.addCleanup(set_language, active_language())
        set_language("it")
        self.assertEqual(result_labels("Imported table", "Group summary"), ("Group summary", {}))
        self.assertEqual(result_labels("Descriptive statistics", "Summary"), ("Riepilogo", {}))
        self.assertEqual(result_labels("Linear regression", "Residuals"), ("Residui", {}))
        set_language("en")
        self.assertEqual(result_labels("Linear regression", "Residuals"), ("Residuals", {}))

    def close_window(self, window):
        for session in window.sessions:
            session.project.dirty = False
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
