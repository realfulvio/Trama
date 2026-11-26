"""Verify the drawing order of overlapping XY series from the Qt window."""

import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.figure_export import export_figure
from analisi.presentation import Layout, graph_series
from analisi.series_layers import XY_SERIES_ORDER

from .series_order import SeriesOrderDialog
from .shortcuts_dialog import ShortcutsDialog


def check_xy_series_layers(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1, 2, 4], "A": [2, 4, 6], "B": [2, 4, 6], "C": [2, 4, 6]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate("XY series", {"X": "X", "Y columns": ["A", "B", "C"]})
    run = window.project.runs[index]
    figure = run.result.figure
    before = dict(run.options)
    a, b, c = graph_series(figure.axes[0])
    keys = [b.key, c.key, a.key]
    action = window.actions["series_drawing_order"]
    reverse = window.actions["reverse_series_drawing_order"]
    smoke.expect(any(action in menu.actions() and reverse in menu.actions()
                     for entry in window.menuBar().actions() if (menu := entry.menu()) is not None),
                 "the drawing order commands are missing from the menu")

    def drive_dialog():
        dialog = smoke.app.activeModalWidget()
        if not isinstance(dialog, SeriesOrderDialog):
            smoke.problem("the drawing order dialog did not open")
            return
        try:
            smoke.expect(dialog.focusWidget() is dialog.list, "the series list does not have focus")
            QTest.keyClick(dialog.list, Qt.Key.Key_Tab)
            smoke.expect(dialog.focusWidget() is dialog.front, "Tab did not reach Move forward")

            def close_help():
                help_dialog = smoke.app.activeModalWidget()
                smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open shortcuts")
                if isinstance(help_dialog, ShortcutsDialog):
                    help_dialog.reject()
            QTimer.singleShot(100, close_help)
            QTest.keyClick(dialog, Qt.Key.Key_F1)
            dialog.front.click()
            dialog.front.click()
            smoke.shot(dialog, "series-order-dialog")
            dialog.list.setFocus()
            QTest.keyClick(dialog.list, Qt.Key.Key_Return)
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, drive_dialog)
    action.trigger()
    smoke.expect((run.style or {}).get(XY_SERIES_ORDER) == keys, "Enter did not save the requested order")
    smoke.expect(b.artist.get_zorder() < c.artist.get_zorder() < a.artist.get_zorder(), "the graph did not reorder")
    reverse.trigger()
    smoke.expect((run.style or {}).get(XY_SERIES_ORDER) == keys[::-1], "the menu did not reverse the series order")
    window.actions["undo"].trigger()
    smoke.expect((run.style or {}).get(XY_SERIES_ORDER) == keys, "undo did not restore the series order")
    window.actions["redo"].trigger()
    smoke.expect((run.style or {}).get(XY_SERIES_ORDER) == keys[::-1], "redo did not restore the reverse order")
    window.actions["undo"].trigger()
    smoke.expect(run.options == before, "the series order changed the graph recipe")
    layout = Layout("Overlapping series", 1, [run.reference])
    window.project.put_layout(layout)
    stem = smoke.folder / f"{smoke.language}-series-order"
    saved = stem.with_suffix(".alab")
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index].result.figure
    legend = restored.axes[0].get_legend()
    smoke.expect([label.get_text() for label in legend.get_texts()] == ["A", "B", "C"], "the legend was reordered")
    output = stem.with_suffix(".svg")
    export_figure(restored, output, {"format": "svg"})
    layout_output = stem.with_name(stem.name + "-layout").with_suffix(".svg")
    window.project.export_layout(window.project.layouts[0], layout_output)
    for path in (output, layout_output):
        svg = path.read_text(encoding="utf-8")
        positions = [svg.find(key + '"') for key in keys]
        smoke.expect(0 <= positions[0] < positions[1] < positions[2], f"series order was lost in {path.name}")
    smoke.shot(window, "series-order-reopened")
