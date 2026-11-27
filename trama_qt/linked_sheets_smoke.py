"""Use the Family chooser from the status bar and from the keyboard."""
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.xy_series import XY_METHOD

from .family import FamilySheetsDialog
from .shortcuts_dialog import ShortcutsDialog
from .strings import qt


def check_linked_sheets(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1., 2., 4.], "Response": [2., 3., 7.]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(XY_METHOD, {"X": "X", "Y columns": ["Response"]})
    window.project.add_tables({"Unrelated": pd.DataFrame({"N": [1, 2]})})
    window.open_sheet(("data", "groups"))
    window.activateWindow()
    QTest.qWait(120)
    assert window.family_button.defaultAction() is window.actions["family_gallery"]
    assert qt("qt.family_linked_sheets_tip") in window.family_button.toolTip()

    def select_graph(confirm):
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, FamilySheetsDialog)
            dialog.activateWindow()
            search = dialog.search
            search.setFocus()
            QTest.qWait(60)
            QTest.keyClick(search, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.entries
            assert all("Unrelated" not in dialog.entries.item(i).text() for i in range(dialog.entries.count()))
            search.setFocus()
            search.setText("nothing to find")
            assert not dialog.open_button.isEnabled()
            QTest.keyClick(search, Qt.Key.Key_Return)
            assert dialog.isVisible()
            search.setText("grafici" if smoke.language == "it" else "graphs")
            assert len(dialog._shown()) == 1
            assert tuple(dialog.entries.currentItem().data(Qt.ItemDataRole.UserRole)) == ("graph", index)
            if not confirm:
                QTest.keyClick(search, Qt.Key.Key_Escape)
                return

            def close_shortcuts():
                help_dialog = smoke.app.activeModalWidget()
                smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open keyboard shortcuts")
                if isinstance(help_dialog, ShortcutsDialog):
                    help_dialog.reject()
            QTimer.singleShot(100, close_shortcuts)
            QTest.keyClick(search, Qt.Key.Key_F1)
            smoke.shot(dialog, "linked-sheet-filter")
            search.setFocus()
            QTest.keyClick(search, Qt.Key.Key_Return)
            assert not dialog.isVisible()
        except Exception as error:
            smoke.problem(f"linked sheets: {error!r}")
        finally:
            if isinstance(dialog, FamilySheetsDialog) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, lambda: select_graph(False))
    QTest.mouseClick(window.family_button, Qt.MouseButton.LeftButton)
    assert window.selected == ("data", "groups")
    window.activateWindow()
    window.sheet.setFocus()
    QTest.qWait(80)
    QTimer.singleShot(150, lambda: select_graph(True))
    QTest.keyClick(window.sheet, Qt.Key.Key_J,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert window.selected == ("graph", index)
    smoke.shot(window, "linked-sheet-opened")
