"""Exercise the axes shortcuts through the Qt canvas and its real modal editor."""

import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest

from analisi.axis_breaks import AXIS_BREAKS, segment_axes

from .graph_format import GraphFormatDialog
from .shortcuts_dialog import ShortcutsDialog


def check_axis_clicks(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"X": [1, 2, 4, 8], "Left": [2, 3, 5, 6], "Right": [100, 200, 400, 800]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate("XY series", {"X": "X", "Y columns": ["Left", "Right"]})
    run = window.project.runs[index]
    style, xy = window.project.format_inputs(run)
    dialog = GraphFormatDialog(window, run.result.figure.axes[0], style, xy=xy)
    dialog.xy_side["Right"] = "Right"
    dialog.accept()
    if dialog.result is None:
        raise RuntimeError(dialog.banner.text())
    window.project.apply_format(run, dialog.result, xy_update=dialog.xy_update, xy_result=dialog.xy_result)
    dialog.deleteLater()
    window.show_sheet("graph", index)
    smoke.app.processEvents()

    def open_from(artist, target, name, *, apply=False):
        canvas = window.plot_tools.canvas
        canvas.draw()
        box = artist.get_window_extent(canvas.renderer)
        ratio = canvas.device_pixel_ratio
        point = QPoint(round((box.x0 + box.x1) / (2 * ratio)),
                       round(canvas.height() - (box.y0 + box.y1) / (2 * ratio)))
        opened = []

        def verify():
            dialog = smoke.app.activeModalWidget()
            if not isinstance(dialog, GraphFormatDialog):
                smoke.problem(f"{name}: double click did not open Format Graph")
                return
            opened.append(True)
            try:
                field = target(dialog)
                smoke.expect(dialog.tabs.currentIndex() == 1 and dialog.focusWidget() is field,
                             f"{name}: focus is on a different axis")
                smoke.shot(dialog, name)
                QTest.keyClick(field, Qt.Key.Key_Tab)
                smoke.expect(dialog.focusWidget() is not field, f"{name}: Tab did not move focus")
                if apply:
                    def check_help():
                        help_dialog = smoke.app.activeModalWidget()
                        smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open shortcuts")
                        if isinstance(help_dialog, ShortcutsDialog):
                            help_dialog.reject()
                    QTimer.singleShot(100, check_help)
                    QTest.keyClick(dialog, Qt.Key.Key_F1)
                    dialog.right["min"].setText("0")
                    dialog.right["max"].setText("900")
                    QTest.keyClick(dialog.right["max"], Qt.Key.Key_Return)
            finally:
                if dialog.isVisible():
                    dialog.reject()

        QTimer.singleShot(150, verify)
        QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(240)
        smoke.expect(bool(opened), f"{name}: axis editor did not appear")

    axes, right = run.result.figure.axes
    open_from(axes.xaxis.label, lambda dialog: dialog.axis_fields["x"]["min"], "format-x")
    open_from(axes.yaxis.label, lambda dialog: dialog.axis_fields["y"]["min"], "format-y")
    open_from(right.yaxis.label, lambda dialog: dialog.right["min"], "format-right", apply=True)
    smoke.expect(run.options.get("Right maximum") == 900.0, "Enter did not apply the right-axis limit")

    broken = smoke.calculate("XY series", {"X": "X", "Y columns": ["Left"]})
    run = window.project.runs[broken]
    record = {"axis": "x", "gap": .04, "segments": [{"low": 0, "high": 4, "share": 50},
                                                     {"low": 5, "high": 9, "share": 50}]}
    window.project.apply_format(run, {AXIS_BREAKS: record})
    window.show_sheet("graph", broken)
    smoke.app.processEvents()
    smoke.expect(not window.actions["format_axis_right"].isEnabled(), "the second segment enabled the right Y axis")
    _, second = segment_axes(run.result.figure)
    open_from(second.spines["bottom"], lambda dialog: dialog.breaks_button, "format-segment")
    saved = smoke.folder / f"{smoke.language}-axis-format.alab"
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    window.open_sheet(("graph", index))
    smoke.wait()
    restored = window.project.runs[index]
    smoke.expect(restored.result.figure.axes[1].get_ylim() == (0.0, 900.0),
                 "the right-axis limit was not restored")
    smoke.shot(window, "axis-format-reopened")
