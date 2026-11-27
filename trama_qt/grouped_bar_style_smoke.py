"""Verify individual grouped bars through the Qt dialog and canvas context menu."""
import json

from matplotlib.colors import to_rgba
import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from analisi.category_graphs import BARS, GROUPED_GRAPH
from analisi.data import GROUPED_SINGLE_BAR_VERSION
from analisi.figure_export import export_figure
from analisi.grouped_bar_style import BAR_STYLES, grouped_bars
from analisi.presentation import Layout

from .grouped_bar_editor import GroupedBarEditor
from .shortcuts_dialog import ShortcutsDialog


def check_grouped_bar_style(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"Visit": ["A", "A", "C"], "Control": [3., 3., 5.], "Treated": [6., 6., 8.]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {"Variables": ["Control", "Treated"], "Row titles": "Visit", "Graph style": BARS})
    reference = "graph", index
    window.open_sheet(reference)
    run = window.project.runs[index]
    original = run.result.tables["Graph data"].copy()
    initial_depth = window.project.history.position
    target = next(bar for bar in grouped_bars(run.result.figure) if bar.row == 1 and bar.series == "Control")
    key = target.key
    fill = "#fca35f"
    rgba = to_rgba(fill)

    def selected_bar(run):
        return next(bar for bar in grouped_bars(run.result.figure) if bar.key == key)

    def check_chart(run, *, styled):
        bar = selected_bar(run)
        assert (bar.patch.get_facecolor() == rgba) == styled
        assert (bar.patch.get_hatch() == "/") == styled
        if styled:
            assert bar.patch.get_edgecolor() == to_rgba("#873d19")
            assert bar.patch.get_linewidth() == 2.5
        others = [bar for bar in grouped_bars(run.result.figure) if bar.key != key]
        assert all(bar.patch.get_facecolor() != rgba for bar in others)
        pd.testing.assert_frame_equal(run.result.tables["Graph data"], original)

    def edit_dialog(cancel):
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GroupedBarEditor), "the format command did not open its dialog"
            dialog.activateWindow()
            if cancel:
                dialog.target.setCurrentIndex(next(i for i, bar in enumerate(dialog.bars) if bar.key == key))
            assert dialog.bars[dialog.target.currentIndex()].key == key
            field = dialog.colors["fill"]
            field.setFocus()
            QTest.keyClick(field, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is not field
            field.setText(fill)
            dialog.colors["border"].setText("#873d19")
            dialog.width.setText("2,5" if smoke.language == "it" else "2.5")
            dialog.pattern.set("diagonal")
            dialog._preview()
            assert BAR_STYLES not in (run.style or {}) and window.project.history.position == initial_depth
            check_chart(run, styled=True)
            if cancel:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                def close_shortcuts():
                    help_dialog = smoke.app.activeModalWidget()
                    smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open keyboard shortcuts")
                    if isinstance(help_dialog, ShortcutsDialog):
                        help_dialog.reject()
                QTimer.singleShot(100, close_shortcuts)
                QTest.keyClick(dialog, Qt.Key.Key_F1)
                smoke.shot(dialog, "grouped-bar-style")
                field.setFocus()
                QTest.keyClick(field, Qt.Key.Key_Return)
                assert not dialog.isVisible(), "Enter did not confirm the changes"
        except Exception as error:
            smoke.problem(f"individual bar style: {error!r}")
        finally:
            if isinstance(dialog, GroupedBarEditor) and dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(150, lambda: edit_dialog(True))
    window.actions["format_grouped_bar"].trigger()
    assert BAR_STYLES not in (run.style or {}) and window.project.history.position == initial_depth
    check_chart(run, styled=False)

    canvas = window.plot_tools.canvas
    canvas.draw()
    x, y = target.patch.get_transform().transform((.5, .5))
    ratio = canvas.device_pixel_ratio
    position = QPoint(round(x / ratio), round(canvas.height() - y / ratio))

    def choose_command():
        menu = smoke.app.activePopupWidget()
        if not isinstance(menu, QMenu) or len(menu.actions()) != 1:
            smoke.problem("right-clicking the bar did not open its context menu")
            if menu is not None:
                menu.close()
            return
        action, = menu.actions()
        QTimer.singleShot(150, lambda: edit_dialog(False))
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(150, choose_command)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=position)
    QTest.qWait(550)
    assert window.project.history.position == initial_depth + 1
    check_chart(run, styled=True)
    window.actions["undo"].trigger()
    check_chart(run, styled=False)
    window.actions["redo"].trigger()
    check_chart(run, styled=True)

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    saved = smoke.folder / f"{smoke.language}-individual-bars.alab"
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == GROUPED_SINGLE_BAR_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(reference)
    smoke.wait()
    run = window.project.runs[index]
    check_chart(run, styled=True)
    smoke.shot(window, "grouped-bar-style-reopened")

    svg = saved.with_suffix(".svg")
    layout = saved.with_name(saved.stem + "-layout").with_suffix(".svg")
    export_figure(run.result.figure, svg, {"format": "svg", "svg_text": "text"})
    window.project.export_layout(window.project.layouts[0], layout, {"format": "svg", "svg_text": "text"})
    for path in (svg, layout):
        document = path.read_text(encoding="utf-8")
        assert fill in document and "<pattern" in document and "<image" not in document

    affected = window.project.move_rows(run.title, 1, 2, 0)
    window.refresh_runs(affected)
    smoke.wait()
    assert selected_bar(run).row == 0 and selected_bar(run).patch.get_facecolor() == rgba
    affected = window.project.delete_rows(run.title, [0])
    window.refresh_runs(affected)
    smoke.wait()
    assert run.result.style_warning
    assert all(bar.patch.get_facecolor() != rgba for bar in grouped_bars(run.result.figure))
    window.actions["undo"].trigger()
    smoke.wait()
    assert selected_bar(run).row == 0 and selected_bar(run).patch.get_facecolor() == rgba
