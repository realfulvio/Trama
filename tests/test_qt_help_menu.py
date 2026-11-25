"""Help menu, F1 and the Keyboard shortcuts window of the Classica Qt window (EN and IT)."""
import unittest
from types import SimpleNamespace

try:
    from PySide6.QtCore import QEvent, QRect
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

from analisi.i18n import active_language, set_language


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def _plain(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class HelpMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def make_window(self, language="en"):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language(language)
        window = MainWindow()
        window.project.dirty = False
        window.show()
        self.addCleanup(self._close, window)
        self.app.processEvents()
        return window

    def _close(self, window):
        for session in window.sessions:
            session.project.dirty = False
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def menus(self, window):
        return {_plain(action.text()): action.menu() for action in window.menuBar().actions() if action.menu()}

    def test_help_menu_is_last_and_holds_shortcuts_search_and_about(self):
        from trama_qt.strings import qt
        window = self.make_window()
        menus = self.menus(window)
        titles = list(menus)
        self.assertEqual(titles[-1], qt("qt.toolbar_help"))
        help_menu = menus[titles[-1]]
        actions = [action for action in help_menu.actions() if not action.isSeparator()]
        self.assertEqual(actions, [window.actions["help_shortcuts"], window.actions["search"], window.actions["about"]])
        file_menu = menus[titles[0]]
        self.assertNotIn(window.actions["about"], file_menu.actions())

    def test_f1_opens_keyboard_shortcuts_and_search_has_a_plain_name(self):
        window = self.make_window()
        self.assertEqual(window.actions["help_shortcuts"].shortcut(), QKeySequence("F1"))
        self.assertEqual(window.actions["search"].text(), "Search commands")
        opened = []
        from trama_qt import shortcuts_dialog
        original = shortcuts_dialog.ShortcutsDialog.exec
        shortcuts_dialog.ShortcutsDialog.exec = lambda dialog: opened.append(dialog) or 0
        self.addCleanup(setattr, shortcuts_dialog.ShortcutsDialog, "exec", original)
        window.actions["help_shortcuts"].trigger()
        self.assertEqual(len(opened), 1)

    def rows(self, dialog):
        rows = {}
        for i in range(dialog.tree.topLevelItemCount()):
            head = dialog.tree.topLevelItem(i)
            for j in range(head.childCount()):
                if not head.child(j).isHidden():
                    rows[head.child(j).text(0)] = head.child(j).text(1)
        return rows

    def test_shortcuts_window_lists_real_shortcuts_and_filters(self):
        from trama_qt.shortcuts_dialog import ShortcutsDialog
        window = self.make_window()
        dialog = ShortcutsDialog(window)
        self.addCleanup(dialog.deleteLater)
        rows = self.rows(dialog)
        native = lambda text: QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)
        self.assertEqual(rows["Search commands"], native("Ctrl+K"))
        self.assertEqual(rows[_plain(window.actions["help_shortcuts"].text())], "F1")
        self.assertEqual(rows[_plain(window.actions["copy"].text())], native("Ctrl+C"))
        self.assertEqual(rows[_plain(window.actions["undo"].text())], native("Ctrl+Z"))
        self.assertEqual(len(rows), len(set(rows)))
        dialog.filter.setText("ctrl+k")
        self.assertEqual(list(self.rows(dialog)), ["Search commands"])
        dialog.filter.setText("")
        self.assertEqual(self.rows(dialog), rows)

    def test_italian_labels(self):
        from trama_qt.shortcuts_dialog import ShortcutsDialog
        window = self.make_window("it")
        self.assertEqual(list(self.menus(window))[-1], "Aiuto")
        self.assertEqual(window.actions["help_shortcuts"].text(), "Scorciatoie da tastiera")
        dialog = ShortcutsDialog(window)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.windowTitle(), "Scorciatoie da tastiera")
        self.assertEqual(dialog.tree.headerItem().text(0), "Comando")

    def test_shortcuts_window_fits_small_available_screen(self):
        from trama_qt.shortcuts_dialog import ShortcutsDialog

        class ShortcutsOnSmallScreen(ShortcutsDialog):
            def screen(self):
                return SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 680, 480))

        dialog = ShortcutsOnSmallScreen(self.make_window())
        self.addCleanup(dialog.deleteLater)
        self.assertLessEqual(dialog.height(), 432)


if __name__ == "__main__":
    unittest.main()
