"""Verify direct legend editing and reordering through the Classica Qt window."""

import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from analisi.figure_export import export_figure
from analisi.graph_legend import collect_legend_entries

from .legend import LegendEditor
from .shortcuts_dialog import ShortcutsDialog


def check_direct_legend(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1, 2, 4], "First": [2, 4, 6], "Second": [8, 6, 4]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate("XY series", {"X": "X", "Y columns": ["First", "Second"]})
    run = window.project.runs[index]
    figure = run.result.figure
    before = dict(run.options)
    first, second = collect_legend_entries(figure)
    edit, reverse = (window.actions[key] for key in ("format_legend", "reverse_legend"))
    smoke.expect(any(edit in menu.actions() and reverse in menu.actions()
                     for action in window.menuBar().actions() if (menu := action.menu()) is not None),
                 "the legend commands are missing from the menu")

    def texts(plot):
        return [label.get_text() for label in plot.axes[0].get_legend().get_texts()]

    reverse.trigger()
    smoke.app.processEvents()
    smoke.expect(texts(figure) == ["Second", "First"], "menu command did not reverse the legend")
    canvas = window.plot_tools.canvas
    canvas.draw()
    box = figure.axes[0].get_legend().get_texts()[0].get_window_extent(canvas.renderer)
    ratio = canvas.device_pixel_ratio
    point = QPoint(round((box.x0 + box.x1) / (2 * ratio)),
                   round(canvas.height() - (box.y0 + box.y1) / (2 * ratio)))
    changed = "Second $ · 2"

    def verify():
        dialog = smoke.app.activeModalWidget()
        if not isinstance(dialog, LegendEditor):
            smoke.problem("double click did not open the legend editor")
            return
        try:
            field = dialog.labels[second.key]
            smoke.expect(dialog.focusWidget() is field and not dialog.labels[first.key].text(),
                         "the editor focused a different entry")
            smoke.shot(dialog, "legend-entry")
            QTest.keyClick(field, Qt.Key.Key_Tab)
            smoke.expect(dialog.focusWidget() is not field, "Tab did not move focus")

            def close_help():
                help_dialog = smoke.app.activeModalWidget()
                smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open shortcuts")
                if isinstance(help_dialog, ShortcutsDialog):
                    help_dialog.reject()
            QTimer.singleShot(100, close_help)
            QTest.keyClick(dialog, Qt.Key.Key_F1)
            field.setFocus()
            field.setText(changed)
            QTest.keyClick(field, Qt.Key.Key_Return)
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, verify)
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    QTest.qWait(240)
    smoke.expect(texts(figure) == [changed, "First"], "Enter did not save the selected legend entry")
    window.actions["undo"].trigger()
    smoke.expect(texts(figure) == ["Second", "First"], "undo did not restore the original label")
    window.actions["redo"].trigger()
    smoke.expect(texts(figure) == [changed, "First"], "redo did not restore the new label")
    smoke.expect(run.options == before, "the legend commands changed the analysis settings")
    stem = smoke.folder / f"{smoke.language}-legend"
    saved = stem.with_suffix(".alab")
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index].result.figure
    smoke.expect(texts(restored) == [changed, "First"], "legend order or label changed after reopening")
    export = stem.with_suffix(".svg")
    export_figure(restored, export, {"format": "svg", "svg_text": "text"})
    smoke.expect(changed in export.read_text(encoding="utf-8"), "new legend label is missing from the export")
    smoke.shot(window, "legend-reopened")
