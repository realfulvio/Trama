"""Verify grouped bar spacing through the Classic Qt formatting command."""

import json

import numpy as np
import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import (BAR_BASELINE, BAR_DIRECTION, BARS, DISTANCES, GROUPED_BAR_SPACING, GROUPED_GRAPH,
                                     HORIZONTAL_BARS, RIGHT_SIDE, SERIES_SIDE, SUMMARIES, grouped_graph_metadata)
from analisi.data import GROUPED_BAR_BASELINE_VERSION, GROUPED_BAR_SPACING_VERSION, GROUPED_RIGHT_AXIS_VERSION
from analisi.figure_export import export_figure
from analisi.presentation import Layout

from .graph_format import GraphFormatDialog
from .shortcuts_dialog import ShortcutsDialog


def check_grouped_bar_spacing(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"Visit": ["Before", "After"], "A": [2., np.nan],
                  "B": [3., 4.], "C": [7., 0.]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {"Variables": ["A", "B", "C"], "Row titles": "Visit", "Graph style": BARS})
    window.open_sheet(("graph", index))
    run = window.project.runs[index]
    original = run.result.tables["Graph data"].copy()
    initial_limits = run.result.figure.axes[0].get_xlim()
    spacing = {"adjacent": 25., "groups": 125., "empty": 50., "leading": 75., "trailing": 50.}

    def check_chart(figure):
        axes, = figure.axes
        bars = grouped_graph_metadata(axes)["handles"]
        np.testing.assert_allclose([patch.get_x() for patch in bars["B"].patches], [2., 6.5])
        assert all(patch.get_width() == 1 for patch in bars["B"].patches)
        assert bars["C"].patches[1].get_height() == 0
        np.testing.assert_allclose(axes.get_xlim(), [0., 9.25])

    def drive_dialog(cancel):
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            dialog.activateWindow()
            dialog.tabs.setCurrentIndex(dialog.spacing_tab)
            assert not dialog.spacing_controls["adjacent"].isEnabled()
            dialog.spacing_enabled.setChecked(True)
            for key, value in spacing.items():
                dialog.spacing_controls[key].setValue(value)
            field = dialog.spacing_controls["adjacent"]
            field.setFocus()
            QTest.keyClick(field, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.spacing_controls["groups"]
            assert dialog.preview()
            check_chart(dialog.preview_canvas.figure)
            smoke.app.processEvents()
            canvas = dialog.preview_canvas
            tab = dialog.tabs.currentWidget()
            bottom_right = canvas.mapTo(tab, QPoint(canvas.width() - 1, canvas.height() - 1))
            assert tab.rect().contains(bottom_right), "spacing preview was clipped"
            assert GROUPED_BAR_SPACING not in run.options
            if cancel:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                QTest.qWait(80)
                def close_shortcuts():
                    help_dialog = smoke.app.activeModalWidget()
                    smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open the shortcuts")
                    if isinstance(help_dialog, ShortcutsDialog):
                        help_dialog.reject()
                QTimer.singleShot(100, close_shortcuts)
                QTest.keyClick(dialog, Qt.Key.Key_F1)
                smoke.shot(dialog, "grouped-bar-spacing")
                field.setFocus()
                QTest.keyClick(field, Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"bar spacing: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                dialog.reject()

    position = window.project.history.position
    for cancel in (True, False):
        QTimer.singleShot(150, lambda: drive_dialog(cancel))
        window.actions["format_graph"].trigger()
        if cancel:
            assert GROUPED_BAR_SPACING not in run.options and window.project.history.position == position
    assert run.options[GROUPED_BAR_SPACING] == spacing
    assert window.project.history.position == position + 1
    check_chart(run.result.figure)
    pd.testing.assert_frame_equal(run.result.tables["Graph data"], original)
    window.actions["undo"].trigger()
    assert GROUPED_BAR_SPACING not in run.options and run.result.figure.axes[0].get_xlim() == initial_limits
    window.actions["redo"].trigger()
    check_chart(run.result.figure)

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    stem = smoke.folder / f"{smoke.language}-grouped-bar-spacing"
    saved = stem.with_suffix(".alab")
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == GROUPED_BAR_SPACING_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index]
    assert restored.options[GROUPED_BAR_SPACING] == spacing
    check_chart(restored.result.figure)
    svg = stem.with_suffix(".svg")
    export_figure(restored.result.figure, svg, {"format": "svg", "svg_text": "text"})
    layout = stem.with_name(stem.name + "-layout").with_suffix(".svg")
    window.project.export_layout(window.project.layouts[0], layout, {"format": "svg", "svg_text": "text"})
    assert all("<image" not in file.read_text(encoding="utf-8") for file in (svg, layout))
    smoke.shot(window, "grouped-bar-spacing-reopened")

    style = {"xlabel": "Visit", "ylabel": "Response", "axis": {"y": {"min": -1., "max": 9.}},
             "reference_lines": [{"axis": "y", "value": 2., "label": "Control limit"}]}
    window.project.apply_format(restored, style)
    window.show_sheet("graph", index)

    def horizontal_dialog():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            dialog.activateWindow()
            dialog.tabs.setCurrentIndex(dialog.spacing_tab)
            choice = dialog.bar_direction
            assert choice.isVisible() and choice.isEnabled()
            choice.set(HORIZONTAL_BARS)
            dialog.bar_baseline.setText("1,5")
            assert dialog.preview()
            assert dialog.preview_canvas.figure.axes[0].get_xlim() == (-1., 9.)
            assert BAR_DIRECTION not in restored.options
            choice.setFocus()
            QTest.keyClick(choice, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is not choice
            QTest.qWait(80)
            def close_shortcuts():
                help_dialog = smoke.app.activeModalWidget()
                smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open the shortcuts")
                if isinstance(help_dialog, ShortcutsDialog):
                    help_dialog.reject()
            QTimer.singleShot(120, close_shortcuts)
            QTest.keyClick(dialog, Qt.Key.Key_F1)
            QTest.qWait(140)
            smoke.shot(dialog, "grouped-bar-direction")
            field = dialog.spacing_controls["adjacent"]
            field.setFocus()
            QTest.keyClick(field, Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"bar direction: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                smoke.problem("Enter did not confirm the grouped graph format")
                dialog.reject()

    def check_horizontal():
        run = window.project.runs[index]
        assert run.options[BAR_DIRECTION] == HORIZONTAL_BARS
        assert run.options[BAR_BASELINE] == 1.5
        assert run.options[GROUPED_BAR_SPACING] == spacing
        axes, = run.result.figure.axes
        assert axes._tramastat_numeric_axes == ("x",) and axes.yaxis_inverted()
        assert axes.get_xlabel() == "Response" and axes.get_ylabel() == "Visit"
        assert axes.get_xlim() == (-1., 9.)
        assert run.style["reference_lines"][0]["axis"] == "x"
        bars = grouped_graph_metadata(axes)["handles"]["B"].patches
        np.testing.assert_allclose([patch.get_y() for patch in bars], [2., 6.5])
        np.testing.assert_allclose([patch.get_x() for patch in bars], [1.5, 1.5])
        np.testing.assert_allclose([patch.get_width() for patch in bars], [1.5, 2.5])
        pd.testing.assert_frame_equal(run.result.tables["Graph data"], original)
        return run

    position = window.project.history.position
    QTimer.singleShot(150, horizontal_dialog)
    window.actions["format_graph"].trigger()
    smoke.wait()
    check_horizontal()
    assert window.project.history.position == position + 1
    window.actions["undo"].trigger()
    smoke.wait()
    current = window.project.runs[index]
    assert current.options.get(BAR_DIRECTION) != HORIZONTAL_BARS
    assert BAR_BASELINE not in current.options
    assert current.result.figure.axes[0].get_ylabel() == "Response"
    window.actions["redo"].trigger()
    smoke.wait()
    check_horizontal()

    saved = stem.with_name(stem.name + "-horizontal").with_suffix(".alab")
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == GROUPED_BAR_BASELINE_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    reopened = check_horizontal()
    smoke.shot(window, "grouped-bar-horizontal")
    svg = saved.with_suffix(".svg")
    export_figure(reopened.result.figure, svg, {"format": "svg", "svg_text": "text"})
    assert "<image" not in svg.read_text(encoding="utf-8")
    layout = saved.with_name(saved.stem + "-layout").with_suffix(".svg")
    window.project.export_layout(window.project.layouts[0], layout, {"format": "svg", "svg_text": "text"})
    contents = layout.read_text(encoding="utf-8")
    assert "Response" in contents and "<image" not in contents

    window.close_project()
    partial = smoke.folder / "asymmetric"
    partial.mkdir(exist_ok=True)
    source = partial / "groups.csv"
    pd.DataFrame({
        "Visit": ["Lower", "Upper", "Both", "Neither"], "A [Mean]": [5., 8., 10., 11.],
        "A [Minus]": [3., np.nan, 2., np.nan], "A [Plus]": [np.nan, 3., 1., np.nan],
        "B [Mean]": [900., 1300., 1800., 2100.], "B [Minus]": [30., 50., 70., 80.], "B [Plus]": [60., 55., 75., 120.],
    }).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {
        "Variables": ["A [Mean]", "A [Minus]", "A [Plus]", "B [Mean]", "B [Minus]", "B [Plus]"], "Row titles": "Visit",
        "Input": SUMMARIES, "Graph style": BARS, "Summary error": DISTANCES,
    })
    window.open_sheet(("graph", index))
    run = window.project.runs[index]
    meta = grouped_graph_metadata(run.result.figure.axes[0])
    error = meta["handles"]["A"]._tramastat_grouped_series["errorbar"]
    np.testing.assert_array_equal([segment[:, 1] for segment in error.lines[2][0].get_segments()],
                                  [[2., 5.], [8., 11.], [8., 11.]])
    table = run.result.tables["Graph data"]
    a = table[table["Group"] == "A"]
    np.testing.assert_array_equal(a["Lower"], [2., np.nan, 8., np.nan])
    np.testing.assert_array_equal(a["Upper"], [np.nan, 11., 11., np.nan])
    smoke.shot(window, "grouped-partial-intervals")

    def assign_right():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            dialog.activateWindow()
            dialog.tabs.setCurrentIndex(2)
            dialog.selector.setCurrentIndex(1)
            side = dialog.grouped_side
            side.set(RIGHT_SIDE)
            assert dialog.preview()
            assert len(dialog.preview_canvas.figure.axes) == 2
            assert SERIES_SIDE not in run.options
            side.setFocus()
            QTest.keyClick(side, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.series_fields["label"]
            dialog.tabs.setCurrentIndex(1)
            dialog.right["title"].setText("Mass")
            dialog.right["min"].setText("0")
            field = dialog.right["max"]
            field.setText("2500")
            field.setFocus()
            QTest.keyClick(field, Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"right axis: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                dialog.reject()

    def check_right(run, limits):
        axes, right = run.result.figure.axes
        assert run.options[SERIES_SIDE] == {"B": RIGHT_SIDE}
        assert right.get_ylim() == limits and axes.get_ylim()[1] < 20
        assert right.get_ylabel() == "Mass"
        assert [label.get_text() for label in axes.get_legend().get_texts()] == ["A", "B"]
        pd.testing.assert_frame_equal(run.result.tables["Graph data"], table)
        return right

    QTimer.singleShot(150, assign_right)
    window.actions["format_graph"].trigger()
    right = check_right(run, (0., 2500.))
    assert window.actions["format_axis_right"].isEnabled()
    canvas = window.plot_tools.canvas
    canvas.draw()
    box = right.yaxis.label.get_window_extent(canvas.renderer)
    ratio = canvas.device_pixel_ratio
    click = QPoint(round((box.x0 + box.x1) / (2 * ratio)),
                   round(canvas.height() - (box.y0 + box.y1) / (2 * ratio)))

    def edit_right():
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            field = dialog.right["min"]
            assert dialog.tabs.currentIndex() == 1 and dialog.focusWidget() is field
            QTest.keyClick(field, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.right["max"]
            smoke.shot(dialog, "grouped-right-axis-options")
            dialog.right["max"].setText("2600")
            QTest.keyClick(dialog.right["max"], Qt.Key.Key_Return)
        except Exception as error:
            smoke.problem(f"right-axis double click: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, edit_right)
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=click)
    QTest.qWait(240)
    check_right(run, (0., 2600.))
    window.actions["undo"].trigger()
    check_right(run, (0., 2500.))
    window.actions["redo"].trigger()
    check_right(run, (0., 2600.))

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    saved = smoke.folder / f"{smoke.language}-grouped-right-axis.alab"
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == GROUPED_RIGHT_AXIS_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    check_right(window.project.runs[index], (0., 2600.))
    smoke.shot(window, "grouped-right-axis")
    svg = saved.with_suffix(".svg")
    window.project.export_layout(window.project.layouts[0], svg, {"format": "svg", "svg_text": "text"})
    contents = svg.read_text(encoding="utf-8")
    assert "Mass" in contents and "<image" not in contents
