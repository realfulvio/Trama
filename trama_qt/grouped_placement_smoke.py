"""Exercise mixed placement of grouped series on the Classic Qt desktop."""

import json

from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import (
    BARS, GROUPED_GRAPH, GROUPED_SERIES_ORDER, INTERLEAVED, LOWER_INTERVAL,
    SERIES_INTERVAL_DIRECTION, SERIES_PLACEMENT, STACK_PREVIOUS, grouped_graph_metadata,
)
from analisi.figure_export import export_figure
from analisi.data import GROUPED_INTERVAL_APPEARANCE_VERSION
from analisi.presentation import Layout, graph_series

from .graph_format import GraphFormatDialog
from .series_order import SeriesOrderDialog
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
            smoke.expect(dialog.focusWidget() is dialog.grouped_interval, "Tab did not reach the interval direction")
            QTest.keyClick(dialog.grouped_interval, Qt.Key.Key_Tab)
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
            canvas = dialog.preview_canvas
            check_chart(canvas.figure)
            smoke.app.processEvents()
            tab = dialog.tabs.currentWidget()
            bottom_right = canvas.mapTo(tab, QPoint(canvas.width() - 1, canvas.height() - 1))
            smoke.expect(tab.rect().contains(bottom_right), "the preview was clipped by the fields")
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

    def reorder():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, SeriesOrderDialog)
            assert [dialog.list.item(row).text() for row in range(dialog.list.count())] == ["A", "B", "C"]
            dialog.list.setCurrentRow(2)
            dialog.move(-1)
            dialog.move(-1)
            smoke.shot(dialog, "grouped-series-order")
            dialog.list.setFocus()
            QTest.keyClick(dialog.list, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is not dialog.list
            QTest.keyClick(dialog, Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"series order: {error!r}")
        finally:
            if isinstance(dialog, SeriesOrderDialog) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, reorder)
    window.actions["series_drawing_order"].trigger()
    current = restored.result.figure.axes[0]
    assert restored.options[GROUPED_SERIES_ORDER] == ["C", "A", "B"]
    assert [item.get_text() for item in current.get_legend().get_texts()] == ["A", "B", "C"]
    bars = grouped_graph_metadata(current)["handles"]
    assert bars["C"].patches[0].get_x() < bars["A"].patches[0].get_x() == bars["B"].patches[0].get_x()
    window.actions["undo"].trigger()
    assert GROUPED_SERIES_ORDER not in restored.options
    check_chart(restored.result.figure)

    def check_one_sided(figure):
        bars = grouped_graph_metadata(figure.axes[0])["handles"]
        err_a = bars["A"]._tramastat_grouped_series["errorbar"]
        err_b = bars["B"]._tramastat_grouped_series["errorbar"]
        assert all(len(cap.get_ydata()) == 4 for cap in err_a.lines[1])
        assert [len(cap.get_ydata()) for cap in err_b.lines[1]] == [3, 0]
        np.testing.assert_allclose([segment[:, 1] for segment in err_b.lines[2][0].get_segments()],
                                   [[4, 5], [-9, -8], [-4, -3]])
        assert all(not cap.get_visible() for cap in err_b.lines[1])
        whisker, = err_b.lines[2]
        np.testing.assert_allclose(whisker.get_colors()[0], to_rgba("#943454"))
        np.testing.assert_allclose(whisker.get_linewidths(), [2.5])

    def lower_interval():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            dialog.activateWindow()
            dialog.tabs.setCurrentIndex(2)
            dialog.selector.setCurrentIndex(1)
            choice = dialog.grouped_interval
            assert choice.isEnabled()
            choice.set(LOWER_INTERVAL)
            for name, value in (("interval_color", "#943454"), ("interval_width", "2,5"), ("interval_caps", "0")):
                field = dialog.series_fields[name]
                assert field.isEnabled()
                field.setText(value)
            assert dialog.preview()
            check_one_sided(dialog.preview_canvas.figure)
            assert SERIES_INTERVAL_DIRECTION not in restored.options
            choice.setFocus()
            QTest.keyClick(choice, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.series_fields["label"]
            caps = dialog.series_fields["interval_caps"]
            dialog.series_scroll.ensureWidgetVisible(caps)
            caps.setFocus()
            smoke.shot(dialog, "grouped-interval-direction")
            QTest.keyClick(caps, Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"interval direction: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, lower_interval)
    window.actions["format_graph"].trigger()
    assert restored.options[SERIES_INTERVAL_DIRECTION] == {"B": LOWER_INTERVAL}
    pd.testing.assert_frame_equal(restored.result.tables["Graph data"], baseline)
    check_one_sided(restored.result.figure)
    window.actions["undo"].trigger()
    assert SERIES_INTERVAL_DIRECTION not in restored.options
    check_chart(restored.result.figure)
    window.actions["redo"].trigger()
    check_one_sided(restored.result.figure)

    saved = stem.with_name(stem.name + "-interval").with_suffix(".alab")
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == GROUPED_INTERVAL_APPEARANCE_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    reopened = window.project.runs[index]
    assert reopened.options[SERIES_INTERVAL_DIRECTION] == {"B": LOWER_INTERVAL}
    check_one_sided(reopened.result.figure)
    assert reopened.style["series"]["grouped:1:B"]["interval_width"] == 2.5
    svg = saved.with_suffix(".svg")
    export_figure(reopened.result.figure, svg, {"format": "svg", "svg_text": "text"})
    assert "<image" not in svg.read_text(encoding="utf-8")
    smoke.shot(window, "grouped-interval-reopened")
