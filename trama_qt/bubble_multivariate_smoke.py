"""Desktop acceptance for the multivariate bubble chart and its presentation history."""
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from analisi.bubble import (ATTR, BUBBLE, COLOR_COLUMN, FILL_CONTINUOUS, FILL_MODE, SHAPE_BY_CATEGORY,
                            SHAPE_COLUMN, SHAPE_MODE, SHEET)
from analisi.figure_export import export_figure
from analisi.graph_legend import visible_legends
from analisi.presentation import compose_layout

from .bubble_style import BubbleStyleDialog
from .shortcuts_dialog import ShortcutsDialog


def check_bubble_multivariate(smoke, window):
    source = smoke.folder / "groups.csv"
    source.write_text(
        "X,Y,Size,Signal,Class,Name\n1,6,1,0,A,First\n1,6,4,25,B,Overlap\n"
        "2,1,9,50,A,Center\n3,7,16,100,B,Maximum\n4,3,0,1000,C,Zero\n"
        "5,4,4,,A,Missing signal\n,4,9,200,C,Missing X\n2,5,1,25,,Missing class\n",
        encoding="utf-8",
    )
    window.open_path(source)
    smoke.wait()
    assert not window.actions["bubble_style"].isEnabled()
    index = smoke.calculate(BUBBLE, {
        "X": "X", "Y": "Y", "Size": "Size", "Label": "Name",
        FILL_MODE: FILL_CONTINUOUS, COLOR_COLUMN: "Signal",
        SHAPE_MODE: SHAPE_BY_CATEGORY, SHAPE_COLUMN: "Class",
    })
    reference = "graph", index
    window.open_sheet(reference)
    window.activateWindow()
    QTest.qWait(120)
    run = window.project.runs[index]
    result = run.result
    figure = result.figure
    state = getattr(figure, ATTR)
    assert list(result.tables[SHEET]["Source row"]) == [1, 2, 3, 4, 6, 8]
    assert list(result.tables[SHEET]["Marker area (pt²)"]) == [25., 100., 225., 400., 100., 25.]
    assert state["color_summary"]["limits"] == (0., 100.)
    assert window.actions["bubble_style"].isEnabled()
    if window.inspector is None:
        window.toggle_inspector()
    assert window.inspector.bubble_section is not None
    smoke.shot(window, "bubble-multivariate-graph")

    def close_help():
        help_dialog = smoke.app.activeModalWidget()
        if not isinstance(help_dialog, ShortcutsDialog):
            smoke.problem("F1 did not open keyboard shortcuts")
            return
        try:
            sections = [help_dialog.tree.topLevelItem(i) for i in range(help_dialog.tree.topLevelItemCount())]
            assert any(section.child(j).text(1) == "Ctrl+Shift+B"
                       for section in sections for j in range(section.childCount()))
        except AssertionError:
            smoke.problem("F1 did not list the bubble encoding shortcut")
        finally:
            help_dialog.reject()

    def edit(confirm):
        dialog = smoke.app.activeModalWidget()
        if not isinstance(dialog, BubbleStyleDialog):
            smoke.problem("The bubble encoding dialog did not open")
            return
        try:
            dialog.tabs.setCurrentIndex(1)
            dialog.palette.set_value("Blue–red")
            dialog.limits_mode.setCurrentIndex(dialog.limits_mode.findData("Manual"))
            dialog.color_min.setText("0")
            dialog.color_mid.setText("25")
            dialog.color_max.setText("100")
            assert dialog.preview()
            assert state["effective_encoding"]["palette"] == "Blue–red"
            if not confirm:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
                return
            dialog.color_mid.setFocus()
            QTest.keyClick(dialog.color_mid, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is dialog.color_max
            QTimer.singleShot(100, close_help)
            QTest.keyClick(dialog.color_max, Qt.Key.Key_F1)
            assert dialog.apply_button.isDefault()
            smoke.shot(dialog, "bubble-multivariate-dialog")
            QTest.keyClick(dialog.color_max, Qt.Key.Key_Return)
            assert not dialog.isVisible()
            assert QDialog.result(dialog) == QDialog.DialogCode.Accepted, "Return did not accept the encoding"
        except Exception as error:
            smoke.problem(f"Bubble editor: {error!r}")
        finally:
            if dialog.isVisible():
                dialog.reject()

    def open_editor(confirm):
        canvas = window.plot_tools.canvas
        window.activateWindow()
        canvas.setFocus()
        QTest.qWait(120)
        QTimer.singleShot(150, lambda: edit(confirm))
        keys = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        QTest.keyClick(canvas, Qt.Key.Key_B, keys)

    undo_before = len(window.project.history.changes)
    open_editor(False)
    assert state["effective_encoding"]["palette"] == "Viridis"
    assert len(window.project.history.changes) == undo_before
    open_editor(True)
    assert state["effective_encoding"]["palette"] == "Blue–red", (run.style, smoke.problems)
    assert len(window.project.history.changes) == undo_before + 1
    assert result.tables[SHEET].loc[1, "Color position (u)"] == 0.5
    window.undo()
    assert state["effective_encoding"]["palette"] == "Viridis"
    window.undo(redo=True)
    assert state["effective_encoding"]["palette"] == "Blue–red"
    assert run.result is result and window.job is None

    stem = smoke.folder / f"{smoke.language}-bubble-multivariate"
    window.project.save(stem.with_suffix(".alab"))
    for extension in ("svg", "pdf"):
        export_figure(figure, stem.with_suffix("." + extension), {"format": extension})
    layout = compose_layout("Bubble charts", 2, [figure, figure])
    export_figure(layout, stem.with_name(stem.name + "-layout").with_suffix(".svg"), {"format": "svg"})
    saved = window.project
    assert window.close_project()
    window.open_path(stem.with_suffix(".alab"))
    smoke.wait()
    assert window.project is not saved and window.project.path == stem.with_suffix(".alab")
    window.open_sheet(reference)
    smoke.wait()
    assert window.project.runs[index].result.tables[SHEET].loc[1, "Color position (u)"] == 0.5
    reopened = getattr(window.project.runs[index].result.figure, ATTR)
    assert reopened["effective_encoding"]["palette"] == "Blue–red"
    smoke.shot(window, "bubble-multivariate-reopened")
    _check_compact_tools(smoke, window)


def _check_compact_tools(smoke, window):
    original_size = window.size()
    if window.inspector is None:
        window.toggle_inspector()
    window.resize(650, 470)
    QTest.qWait(120)
    page = window.page
    tools = page.graph_tools
    menu = tools.menu()
    assert tools.isVisible(), (window.size(), page.size())
    assert menu.actions() == [
        window.actions[key] for key in ("annotations", "draw", "linked_table", "linked_table_move", "bubble_style")
    ]
    assert not page.actions_row.parentWidget().isVisible()
    smoke.shot(window, "compact-graph-actions")
    viewport = page.figure_view
    assert viewport.horizontalScrollBar().maximum() > 0
    canvas = window.plot_tools.canvas
    guide_width = check_legend_geometry(canvas)
    assert viewport.viewport().width() * canvas.device_pixel_ratio >= guide_width
    viewport.horizontalScrollBar().setValue(viewport.horizontalScrollBar().maximum())
    smoke.shot(window, "compact-bubble-legends")
    viewport.horizontalScrollBar().setValue(0)

    def navigate_menu():
        try:
            assert menu.isVisible()
            menu.setActiveAction(window.actions["bubble_style"])
            QTest.keyClick(menu, Qt.Key.Key_Escape)
        except Exception as error:
            smoke.problem(f"Compact graph tools: {error!r}")
            menu.close()

    tools.setFocus()
    QTimer.singleShot(150, navigate_menu)
    QTest.keyClick(tools, Qt.Key.Key_Space)
    assert window.selected[0] == "graph"
    window.resize(original_size)
    QTest.qWait(120)
    assert page.actions_row.parentWidget().isVisible()
    assert not tools.isVisible()


def check_legend_geometry(
    canvas, expected=("bubble-shape-legend", "bubble-missing-legend", "bubble-size-legend", "color scale"),
):
    """Verify every guide stays outside the plotting area and apart from the other guides."""
    canvas.draw()
    figure = canvas.figure
    renderer = canvas.get_renderer()
    axes = figure.axes[0]
    guides = {legend.get_gid(): legend.get_window_extent(renderer) for legend in visible_legends(figure)}
    if colorbar := getattr(axes, "_tramastat_bubble_colorbar", None):
        guides["color scale"] = colorbar.ax.get_tightbbox(renderer)
    assert set(guides) >= set(expected), tuple(guides)
    for label, box in guides.items():
        assert figure.bbox.contains(*box.p0) and figure.bbox.contains(*box.p1), (label, box, figure.bbox)
        assert not axes.bbox.overlaps(box), label
    for index, (first, box) in enumerate(guides.items()):
        for second, other in list(guides.items())[index + 1:]:
            assert not box.overlaps(other), (first, second)
    return max(box.width for box in guides.values())


def main(argv=None):
    """Run this check from a checkout using a separate preferences directory."""
    from argparse import ArgumentParser
    from tempfile import TemporaryDirectory
    import os

    from PySide6.QtWidgets import QApplication

    from analisi.i18n import set_language

    from . import theme
    from .smoke import Smoke
    from .window import MainWindow

    parser = ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("it", "en"), default="it")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    with TemporaryDirectory(prefix="trama-bubble-prefs-") as prefs:
        os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = prefs
        set_language(args.lang)
        app = QApplication([])
        theme.load_fonts()
        theme.set_mode(args.theme, app, remember=False)
        theme.install_qt_translations(app, args.lang)
        window = MainWindow()
        window.resize(980, 620 if app.devicePixelRatio() > 1 else 700)
        window.show()
        theme.keep_on_screen(window)
        smoke = Smoke(args.out)
        smoke.language, smoke.window = args.lang, window
        window.error = smoke.problem
        try:
            check_bubble_multivariate(smoke, window)
        finally:
            window.project.dirty = False
            window.close()
        return int(smoke.report() != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
