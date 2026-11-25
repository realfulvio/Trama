import unittest

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QAction
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from analisi.i18n import active_language, set_language


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class CommandSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["command-search", "-platform", "offscreen"])

    def make_window(self, language):
        from trama_qt.window import MainWindow

        self.addCleanup(set_language, active_language())
        set_language(language)
        window = MainWindow()
        window.show()
        self.addCleanup(self.close_window, window)
        self.app.processEvents()
        return window

    def close_window(self, window):
        for session in window.sessions:
            session.project.dirty = False
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def open(self, window, text):
        window.actions["search"].trigger()
        dialog = window.search_dialog
        dialog.query.setText(text)
        return dialog

    def test_filters_by_localized_menu_and_shortcut(self):
        dialog = self.open(self.make_window("it"), "modifica ctrl+c")
        self.assertEqual(dialog.results.topLevelItemCount(), 1)
        result = dialog.results.topLevelItem(0)
        self.assertEqual(result.data(0, Qt.ItemDataRole.UserRole), "copy")
        self.assertEqual(result.text(1), "Modifica")
        self.assertIn("Ctrl+C", result.text(2))
        dialog.query.setText("unmatched literal $")
        self.assertEqual(dialog.results.topLevelItemCount(), 0)
        self.assertFalse(dialog.run_button.isEnabled())

    def test_distinct_actions_with_the_same_caption_keep_their_identity(self):
        window = self.make_window("en")
        calls = []
        for key, menu in (("from_file", "File"), ("from_tools", "Tools")):
            action = QAction("Café && notes", window)
            action.triggered.connect(lambda _checked=False, key=key: calls.append(key))
            window.actions[key] = action
            window.command_menus[menu].addAction(action)
        window.actions["from_tools"].setEnabled(False)
        dialog = self.open(window, "cafe")
        self.assertEqual(dialog.results.topLevelItemCount(), 2)
        self.assertEqual(dialog.results.topLevelItem(0).text(0), "Café & notes")
        dialog.query.setText("tools cafe")
        self.assertFalse(dialog.run_button.isEnabled())
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        self.assertEqual(calls, [])
        self.assertTrue(dialog.isVisible())
        window.actions["from_tools"].setEnabled(True)
        self.app.processEvents()
        self.assertTrue(dialog.run_button.isEnabled())
        QTest.keyClick(dialog.query, Qt.Key.Key_Down)
        self.assertIs(self.app.focusWidget(), dialog.results)
        QTest.keyClick(dialog.results, Qt.Key.Key_Return)
        self.assertEqual(calls, ["from_tools"])
        self.assertFalse(dialog.isVisible())

    def test_exact_name_takes_priority_after_filter_changes(self):
        window = self.make_window("en")
        for key, title in (("longer", "Sample copy"), ("exact", "Sample")):
            window.actions[key] = QAction(title, window)
        dialog = self.open(window, "sample copy")
        self.assertEqual(dialog.results.currentItem().text(0), "Sample copy")
        dialog.query.setText("sample")
        self.assertEqual(dialog.results.currentItem().text(0), "Sample")
