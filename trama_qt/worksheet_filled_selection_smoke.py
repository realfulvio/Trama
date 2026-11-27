"""Use the sheet selection commands both on a worksheet and on a result table."""
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from analisi.reporting import Result

from .classic_bar import FILLED_SELECTION_COMMANDS
from .project import Run
from .sheet import selection_box
from .shortcuts_dialog import ShortcutsDialog


def check_filled_selection(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({
        "A": [2., 0., 4., None, 10.],
        "B": ["False", "Filled", "", "More", "Data"],
        "C": ["", "Note", "Value", "", "After gap"],
        "D": [6., 7., 8., 9., 10.],
    }).to_csv(source, index=False)
    window.open_path(source)
    control_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    worksheet = window.sheet
    worksheet.activateWindow()
    QTest.qWait(120)

    def locate(view, row, column):
        view.setCurrentIndex(view.model().index(row, column))
        view.setFocus()

    locate(worksheet, 0, 0)
    QTest.keyClick(worksheet, Qt.Key.Key_Right, control_shift)
    assert worksheet.box() == (0, 0, 0, 1)
    QTest.keyClick(worksheet, Qt.Key.Key_Down, control_shift)
    assert worksheet.box() == (0, 0, 2, 1)
    QTest.keyClick(worksheet, Qt.Key.Key_Down, control_shift)
    assert worksheet.box() == (0, 0, 2, 1)
    smoke.shot(window, "filled-selection-worksheet")

    locate(worksheet, 0, 1)
    QTest.keyClick(worksheet, Qt.Key.Key_F2)
    editor = worksheet.findChild(QLineEdit, "worksheetEditor")
    assert editor is not None
    editor.setText("two words")
    editor.setCursorPosition(0)
    QTest.keyClick(editor, Qt.Key.Key_Right, control_shift)
    assert editor.selectedText() and worksheet.box() == (0, 1, 0, 1)
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert worksheet.model().frame.iat[0, 1] == "False"

    def confirm_help():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, ShortcutsDialog)
            items = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
            captions = {item.child(j).text(0) for item in items for j in range(item.childCount())}
            assert all(window.actions[key].text() in captions for key in FILLED_SELECTION_COMMANDS)
            smoke.shot(dialog, "filled-selection-shortcuts")
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        except Exception as error:
            smoke.problem(f"sheet selection keyboard shortcuts: {error!r}")
        finally:
            if isinstance(dialog, ShortcutsDialog) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, confirm_help)
    QTest.keyClick(worksheet, Qt.Key.Key_F1)
    results = pd.DataFrame({"n": [2., 0., None, 10.], "Note": ["first", "second", "", "after"]},
                           index=["A", "B", "C", "D"])
    run = Run("Descriptive statistics", "groups", {}, Result({"Result": results}))
    window.project.runs.append(run)
    window.open_sheet(("result", len(window.project.runs) - 1))
    result_view = window.result_tabs.currentWidget()
    window.activateWindow()
    locate(result_view, 0, 1)
    QTest.qWait(120)
    QTest.keyClick(result_view, Qt.Key.Key_Down, control_shift)
    assert selection_box(result_view) == (0, 1, 1, 1), selection_box(result_view)
    QTest.keyClick(result_view, Qt.Key.Key_Left, control_shift)
    assert selection_box(result_view) == (0, 0, 1, 1)
    smoke.shot(window, "filled-selection-result")
