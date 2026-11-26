"""Exercise mixed placement of grouped series on the Classic Qt desktop."""

import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import BARS, GROUPED_GRAPH, INTERLEAVED, SERIES_PLACEMENT, STACK_PREVIOUS
from analisi.figure_export import export_figure
from analisi.presentation import Layout, graph_series

from .graph_format import GraphFormatDialog
from .shortcuts_dialog import ShortcutsDialog


def check_grouped_placement(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({
        "Visit": ["V1", "V2", "V3", "V4"],
        "A [1]": [1, -3, 4, 1], "A [2]": [3, -1, 6, 3],
        "B [1]": [2, -7, None, -4], "B [2]": [4, -5, None, -2],
        "C [1]": [6, 3, 7, 2], "C [2]": [8, 5, 9, 4],
    }).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {
        "Variables": ["A [1]", "A [2]", "B [1]", "B [2]", "C [1]", "C [2]"],
        "Row titles": "Visit", "Graph style": BARS, "Placement of groups": INTERLEAVED, "Interval": "SEM",
    })
    window.open_sheet(("graph", index))
    run = window.project.runs[index]
    baseline = run.result.tables["Graph data"].copy()
    expected = {"B": STACK_PREVIOUS}

    def check_chart(figure):
        a, b, c = [series.artist for series in graph_series(figure.axes[0])]
        np.testing.assert_allclose([patch.get_y() for patch in b.patches], [2, -2, 0])
        np.testing.assert_allclose([patch.get_height() for patch in b.patches], [3, -6, -3])
        _, _, whiskers = b._tramastat_grouped_series["errorbar"].lines
        np.testing.assert_allclose([segment[:, 1] for segment in whiskers[0].get_segments()],
                                   [[4, 6], [-9, -7], [-4, -2]])

        def center(patch):
            return patch.get_x() + patch.get_width() / 2

        np.testing.assert_allclose([center(patch) for patch in b.patches],
                                   [center(a.patches[i]) for i in (0, 1, 3)])
        assert np.isclose(center(c.patches[0]) - center(a.patches[0]), .38)
        assert [item.get_text() for item in figure.axes[0].get_legend().get_texts()] == ["A", "B", "C"]

    def drive_dialog(cancel):
        dialog = smoke.app.activeModalWidget()
        if not isinstance(dialog, GraphFormatDialog):
            smoke.problem("the grouped placement dialog did not open")
            return
        try:
            dialog.activateWindow()
            QTest.qWait(40)
            dialog.tabs.setCurrentIndex(2)
            smoke.expect(not dialog.grouped_place.isEnabled(), "the first series should have no preceding reference")
            dialog.selector.setCurrentIndex(1)
            placement = dialog.grouped_place
            smoke.expect(placement.isEnabled() and "A" in placement.toolTip(), "the preceding series was not identified")
            placement.setFocus()
            QTest.keyClick(placement, Qt.Key.Key_Tab)
            smoke.expect(dialog.focusWidget() is dialog.series_fields["label"], "Tab did not reach the legend label")
            if not cancel:
                def close_shortcuts():
                    help_dialog = smoke.app.activeModalWidget()
                    smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open the shortcuts")
                    if isinstance(help_dialog, ShortcutsDialog):
                        help_dialog.reject()
                QTimer.singleShot(100, close_shortcuts)
                QTest.keyClick(dialog, Qt.Key.Key_F1)
            placement.set(STACK_PREVIOUS)
            if not dialog.preview():
                smoke.problem("the mixed placement preview failed")
                return
            check_chart(dialog.preview_canvas.figure)
            smoke.expect(SERIES_PLACEMENT not in run.options, "preview changed the confirmed recipe")
            if cancel:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                smoke.shot(dialog, "grouped-placement")
                dialog.series_fields["color"].setFocus()
                QTest.keyClick(dialog.series_fields["color"], Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(str(error))
        finally:
            if dialog.isVisible():
                dialog.reject()

    position = window.project.history.position
    for cancel in (True, False):
        QTimer.singleShot(150, lambda: drive_dialog(cancel))
        window.actions["format_graph"].trigger()
        if cancel:
            smoke.expect(SERIES_PLACEMENT not in run.options and window.project.history.position == position,
                         "Cancel changed the recipe or its history")
    smoke.expect(run.options.get(SERIES_PLACEMENT) == expected
                 and window.project.history.position == position + 1, "Enter did not record one placement change")
    smoke.expect(run.result.tables["Graph data"].equals(baseline), "placement changed the numeric table")
    window.actions["undo"].trigger()
    smoke.expect(SERIES_PLACEMENT not in run.options, "Undo did not restore the series positions")
    window.actions["redo"].trigger()
    smoke.expect(run.options.get(SERIES_PLACEMENT) == expected, "Redo did not restore the stack")

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    stem = smoke.folder / f"{smoke.language}-grouped-placement"
    saved = stem.with_suffix(".alab")
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index]
    assert restored.options.get(SERIES_PLACEMENT) == expected
    check_chart(restored.result.figure)
    svg = stem.with_suffix(".svg")
    export_figure(restored.result.figure, svg, {"format": "svg", "svg_text": "text"})
    layout = stem.with_name(stem.name + "-layout").with_suffix(".svg")
    window.project.export_layout(window.project.layouts[0], layout, {"format": "svg", "svg_text": "text"})
    assert all("<image" not in file.read_text(encoding="utf-8") for file in (svg, layout))
    smoke.shot(window, "grouped-placement-reopened")
