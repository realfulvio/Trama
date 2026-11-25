"""Small behaviour fixes in the Classica Qt window: status messages that expire, status bar dividers,
right-aligned numbers in mixed result columns and Apply as the default button of Format graph."""
import os
import unittest

os.environ.setdefault("MPLBACKEND", "Agg")

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QFrame, QPushButton
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi.i18n import active_language, set_language


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class StatusBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window.resize(1180, 768)
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

    def test_a_status_message_is_highlighted_then_returns_to_ready(self):
        window = self.window
        window.status("Saved to results.alab")
        self.assertEqual(window.message.text(), "Saved to results.alab")
        self.assertTrue(window.message.property("fresh"))
        self.assertTrue(window._message_timer.isActive())
        self.assertEqual(window._message_timer.interval(), 6000)
        window._message_timer.stop()
        window._message_expired()
        self.assertEqual(window.message.text(), "Ready")
        self.assertFalse(window.message.property("fresh"))

    def test_a_running_calculation_keeps_its_message(self):
        window = self.window
        window.status("Calculating…")
        window.job = object()
        try:
            window._message_expired()
            self.assertEqual(window.message.text(), "Calculating…")
            self.assertTrue(window._message_timer.isActive())
        finally:
            window.job = None
            window._message_timer.stop()

    def test_status_bar_groups_are_separated(self):
        dividers = self.window.statusBar().findChildren(QFrame, "statusDivider")
        self.assertEqual(len(dividers), 3)
        self.assertTrue(all(divider.frameShape() == QFrame.Shape.VLine for divider in dividers))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ResultAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_mixed_result_column_is_right_aligned_like_numbers(self):
        from trama_qt.models import FrameModel
        frame = pd.DataFrame({"Statistic": ["Mean", "SD", "N", "Test"],
                              "Value": [1.25, 0.5, 12, "Welch"],
                              "Note": ["a", "b", 3.0, "c"]}, dtype=object)
        model = FrameModel(frame)
        right = int(Qt.AlignmentFlag.AlignRight)
        alignment = lambda column: int(model.data(model.index(0, column), Qt.ItemDataRole.TextAlignmentRole)) & right
        header = lambda column: int(model.headerData(column, Qt.Orientation.Horizontal,
                                                     Qt.ItemDataRole.TextAlignmentRole)) & right
        self.assertEqual(model.numeric, [False, True, False])
        self.assertTrue(alignment(2))
        self.assertTrue(header(2))
        self.assertFalse(alignment(1))
        self.assertFalse(header(1))
        self.assertFalse(header(3))
        self.assertFalse(header(0))

    def test_booleans_do_not_count_as_numbers(self):
        from trama_qt.models import FrameModel
        model = FrameModel(pd.DataFrame({"Flag": [True, False, True]}, dtype=object))
        self.assertEqual(model.numeric, [False])


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class GraphFormatDefaultButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_enter_applies_instead_of_opening_the_legend(self):
        import matplotlib.pyplot as plt
        from analisi.i18n import tr
        from trama_qt.graph_format import GraphFormatDialog
        figure, axes = plt.subplots()
        self.addCleanup(plt.close, figure)
        axes.plot([1, 2, 3], [2, 4, 3], label="Serie")
        axes.legend()
        dialog = GraphFormatDialog(None, axes, {})
        self.addCleanup(dialog.deleteLater)
        defaults = [button for button in dialog.findChildren(QPushButton) if button.isDefault()]
        self.assertEqual([button.text() for button in defaults], [tr("graph.format.apply")])
        others = [button for button in dialog.findChildren(QPushButton) if button not in defaults]
        self.assertTrue(others)
        self.assertFalse(any(button.autoDefault() for button in others))


if __name__ == "__main__":
    unittest.main()
