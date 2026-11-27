"""Verify focus moves through the worksheet, notes and graph controls on the live desktop."""
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.xy_series import XY_METHOD

from .shortcuts_dialog import ShortcutsDialog


def check_workspace_panes(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1., 2., 4.], "Response": [2., 4., 8.]}).to_csv(source, index=False)
    window.open_path(source)
    window.activateWindow()
    QTest.qWait(120)

    def move(source, target, step=1):
        modifier = Qt.KeyboardModifier.NoModifier if step > 0 else Qt.KeyboardModifier.ShiftModifier
        QTest.keyClick(source, Qt.Key.Key_F6, modifier)
        QTest.qWait(100)
        focus = smoke.app.focusWidget()
        assert focus is target, (focus, target)

    worksheet = window.sheet
    worksheet.setCurrentIndex(worksheet.model().index(1, 1))
    window.navigator.setFocus()
    move(window.navigator, worksheet)
    assert worksheet.currentIndex() == worksheet.model().index(1, 1)
    window.actions["sheet_notes"].trigger()
    notes = window.worksheet_notes
    assert notes is not None
    notes.add_note()
    note = notes.editor.notes
    note.setPlainText("An observation to review before export.")
    QTest.qWait(100)
    move(note, window.navigator)
    move(window.navigator, note, -1)
    smoke.shot(notes, "workspace-focus-note")
    window.nav_card.hide()
    move(note, worksheet)
    assert worksheet.currentIndex() == worksheet.model().index(1, 1)
    window.close_worksheet_notes()
    assert any("observation" in item.notes for item in window.project.info_sheets.values())
    window.nav_card.show()

    index = smoke.calculate(XY_METHOD, {"X": "X", "Y columns": ["Response"]})
    reference = "graph", index
    window.open_sheet(reference)
    if window.inspector is None:
        window.actions["inspector"].trigger()
    assert window.inspector is not None
    canvas = window.plot_tools.canvas
    window.activateWindow()
    window.navigator.setFocus()
    QTest.qWait(120)
    move(window.navigator, canvas)
    smoke.shot(window, "workspace-focus-canvas")
    move(canvas, window.inspector.selector)
    QTest.keyClick(window.inspector.selector, Qt.Key.Key_Tab)
    assert window.inspector.isAncestorOf(smoke.app.focusWidget())
    move(smoke.app.focusWidget(), canvas, -1)

    def then_close_help():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, ShortcutsDialog)
            items = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
            captions = {item.child(j).text(0) for item in items for j in range(item.childCount())}
            assert all(window.actions[key].text() in captions
                       for key in ("focus_next_pane", "focus_previous_pane"))
        except Exception as error:
            smoke.problem(f"workspace focus help: {error!r}")
        finally:
            if isinstance(dialog, ShortcutsDialog):
                dialog.reject()

    QTimer.singleShot(100, then_close_help)
    QTest.keyClick(canvas, Qt.Key.Key_F1)
    assert window.selected == reference
