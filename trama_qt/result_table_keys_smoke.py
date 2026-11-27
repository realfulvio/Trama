"""Use the numbered result shortcuts with the status and the narrow result selector."""
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.linear_diagnostics import RESIDUAL_DIAGNOSTICS

from .result_tabs import ResultTabs
from .shortcuts_dialog import ShortcutsDialog


def check_result_table_keys(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1., 2., 4., 8.], "Response": [2., 3., 7., 13.]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate("Linear regression", {"X": "X", "Y": "Response", RESIDUAL_DIAGNOSTICS: True})
    reference = "result", index
    window.open_sheet(reference)
    window.activateWindow()
    QTest.qWait(120)
    tabs = window.result_tabs
    assert tabs.count() >= 2
    navigation = window.page.findChild(ResultTabs)
    tabs.currentWidget().setFocus()
    QTest.keyClick(tabs.currentWidget(), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert tabs.currentIndex() == window.status_results.currentIndex() == navigation.choice.currentIndex() == 1
    assert window.actions["result_table_2"].isChecked()
    assert window.result_table_menu.menuAction().isEnabled()
    smoke.shot(window, "result-table-shortcut")

    def close_help():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, ShortcutsDialog)
            items = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
            keys = {item.child(j).text(1) for item in items for j in range(item.childCount())}
            assert "Ctrl+2" in keys
        except Exception as error:
            smoke.problem(f"result table shortcuts: {error!r}")
        finally:
            if isinstance(dialog, ShortcutsDialog):
                dialog.reject()
    QTimer.singleShot(100, close_help)
    QTest.keyClick(tabs.currentWidget(), Qt.Key.Key_F1)
    window.activateWindow()
    tabs.currentWidget().setFocus()
    QTest.qWait(100)
    QTest.keyClick(tabs.currentWidget(), Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert tabs.currentIndex() == 0 and window.actions["result_table_1"].isChecked()
    assert window.selected == reference
