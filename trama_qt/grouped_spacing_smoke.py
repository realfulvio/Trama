"""Verify grouped bar spacing through the Classic Qt formatting command."""

import json

import numpy as np
import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import BARS, GROUPED_BAR_SPACING, GROUPED_GRAPH, grouped_graph_metadata
from analisi.data import GROUPED_BAR_SPACING_VERSION
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
