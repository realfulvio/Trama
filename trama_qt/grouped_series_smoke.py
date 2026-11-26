"""Exercise the grouped series drawing controls from the Classic Qt window."""

import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import BARS, GROUPED_GRAPH, INTERLEAVED, LINE_SYMBOLS, SERIES_STYLE
from analisi.figure_export import export_figure
from analisi.presentation import Layout, graph_series

from .graph_format import GraphFormatDialog
from .shortcuts_dialog import ShortcutsDialog


def check_grouped_series(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({
        "Visit": ["V1", "V2", "V3", "V4"],
        "Control [1]": [1, 2, 3, 4], "Control [2]": [3, 4, 5, 6],
        "Treatment [1]": [3, 7, None, 9], "Treatment [2]": [5, 9, None, 11],
    }).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {
        "Variables": ["Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"],
        "Row titles": "Visit", "Graph style": BARS, "Placement of groups": INTERLEAVED, "Interval": "SEM",
    })
    window.open_sheet(("graph", index))
    run = window.project.runs[index]
    baseline = run.result.tables["Graph data"].copy()
    expected = {"Treatment": LINE_SYMBOLS}

    def drive_dialog(cancel):
        dialog = smoke.app.activeModalWidget()
        if not isinstance(dialog, GraphFormatDialog):
            smoke.problem("the grouped graph format dialog did not open")
            return
        try:
            dialog.activateWindow()
            QTest.qWait(40)
            dialog.tabs.setCurrentIndex(2)
            dialog.selector.setCurrentIndex(1)
            draw = dialog.grouped_draw
            draw.setFocus()
            QTest.keyClick(draw, Qt.Key.Key_Tab)
            focus = dialog.focusWidget()
            smoke.expect(focus is not None and focus is not draw and dialog.isAncestorOf(focus),
                         "Tab did not advance to the next control")

            if not cancel:
                def close_shortcuts():
                    help_dialog = smoke.app.activeModalWidget()
                    smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open the shortcuts")
                    if isinstance(help_dialog, ShortcutsDialog):
                        help_dialog.reject()
                QTimer.singleShot(100, close_shortcuts)
                QTest.keyClick(dialog, Qt.Key.Key_F1)

            dialog.grouped_draw.set(LINE_SYMBOLS)
            color = dialog.series_fields["color"]
            color.setText("#cc3311")
            if not dialog.preview():
                smoke.problem("the grouped preview failed")
                return
            canvas = dialog.preview_canvas
            canvas.draw()
            smoke.expect(abs(canvas.figure.bbox.width - canvas.width() * canvas.device_pixel_ratio) < 1,
                         "the grouped preview was drawn at the wrong display scale")
            smoke.expect([item.kind for item in graph_series(canvas.figure.axes[0])] == ["bar", "line"],
                         "the preview did not mix bars and line")
            smoke.expect(SERIES_STYLE not in run.options, "preview changed the confirmed recipe")
            if cancel:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                smoke.shot(dialog, "grouped-format")
                color.setFocus()
                QTest.keyClick(color, Qt.Key.Key_Return)
        finally:
            if dialog.isVisible():
                dialog.reject()

    position = window.project.history.position
    for cancel in (True, False):
        QTimer.singleShot(150, lambda: drive_dialog(cancel))
        window.actions["format_graph"].trigger()
        if cancel:
            smoke.expect(SERIES_STYLE not in run.options and window.project.history.position == position,
                         "Cancel changed the chart or its history")
    smoke.expect(run.options.get(SERIES_STYLE) == expected and window.project.history.position == position + 1,
                 "Enter did not record the new drawing in one step")
    smoke.expect(run.result.tables["Graph data"].equals(baseline), "drawing changes altered the numeric table")
    window.actions["undo"].trigger()
    smoke.expect(SERIES_STYLE not in run.options, "Undo did not restore the bars")
    window.actions["redo"].trigger()
    smoke.expect(run.options.get(SERIES_STYLE) == expected, "Redo did not restore the line")

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    stem = smoke.folder / f"{smoke.language}-grouped-series"
    saved = stem.with_suffix(".alab")
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index]
    axes = restored.result.figure.axes[0]
    smoke.expect(restored.options.get(SERIES_STYLE) == expected, "the drawing was lost on reopening")
    smoke.expect([item.kind for item in graph_series(axes)] == ["bar", "line"], "the reopened graph is wrong")
    smoke.expect([item.get_text() for item in axes.get_legend().get_texts()] == ["Control", "Treatment"],
                 "the reopened legend is wrong")
    graph = stem.with_suffix(".svg")
    layout = stem.with_name(stem.name + "-layout").with_suffix(".svg")
    export_figure(restored.result.figure, graph, {"format": "svg", "svg_text": "text"})
    window.project.export_layout(window.project.layouts[0], layout, {"format": "svg", "svg_text": "text"})
    for path in (graph, layout):
        svg = path.read_text(encoding="utf-8")
        smoke.expect("Control" in svg and "Treatment" in svg and "<image" not in svg,
                     f"the series were lost in vector export {path.name}")
    smoke.shot(window, "grouped-reopened")
