"""Verify series appearance, individual overrides and vector export through Classica Qt."""
import json

from matplotlib.colors import to_rgba
import pandas as pd
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from analisi.category_graphs import BARS, GROUPED_GRAPH
from analisi.data import BAR_APPEARANCE_VERSION
from analisi.figure_export import export_figure
from analisi.grouped_bar_style import BAR_APPEARANCE, grouped_bars
from analisi.presentation import Layout

from .graph_format import GraphFormatDialog
from .shortcuts_dialog import ShortcutsDialog


def check_bar_series_appearance(smoke, window):
    source = smoke.folder / "groups.csv"
    pd.DataFrame({"Visit": ["1", "2", "3"], "Control": [3., 4., 7.], "Treated": [5., 8., 10.]}).to_csv(source, index=False)
    window.open_path(source)
    index = smoke.calculate(GROUPED_GRAPH, {"Variables": ["Control", "Treated"], "Row titles": "Visit", "Graph style": BARS})
    reference = "graph", index
    window.open_sheet(reference)
    original = window.project.runs[index].result.tables["Graph data"].copy()
    initial_depth = window.project.history.position
    appearance = {"fill": "none", "border": "#14804a", "width": 2.5, "pattern": "grid", "pattern_color": "#c05798"}
    key = "grouped:1:Treated"

    def check_chart(figure):
        treated = [bar.patch for bar in grouped_bars(figure) if bar.series == "Treated"]
        control = [bar.patch for bar in grouped_bars(figure) if bar.series == "Control"]
        assert len(treated) == len(control) == 3
        assert all(patch.get_facecolor() == to_rgba("none") and patch.get_edgecolor() == to_rgba(appearance["border"])
                   and patch.get_hatchcolor() == to_rgba(appearance["pattern_color"])
                   and patch.get_hatch() == "+" and patch.get_linewidth() == 2.5 for patch in treated)
        assert all(patch.get_hatch() is None for patch in control)
        assert figure.axes[0].get_legend().legend_handles[1].get_hatch() == "+"

    def edit_dialog(cancel):
        dialog = smoke.app.activeModalWidget()
        try:
            assert isinstance(dialog, GraphFormatDialog)
            dialog.activateWindow()
            dialog.tabs.setCurrentIndex(2)
            dialog.selector.setCurrentIndex(1)
            fields = dialog.series_bar_fields
            assert dialog.series_bar_group.isVisible()
            fields.transparent["fill"].setChecked(True)
            fields.colors["border"].setText(appearance["border"])
            fields.width.setText("2,5" if smoke.language == "it" else "2.5")
            fields.pattern.set("grid")
            fields.colors["pattern_color"].setText(appearance["pattern_color"])
            dialog.series_scroll.ensureWidgetVisible(fields.width)
            fields.width.setFocus()
            QTest.keyClick(fields.width, Qt.Key.Key_Tab)
            assert dialog.focusWidget() is fields.pattern
            assert dialog.preview()
            check_chart(dialog.preview_canvas.figure)
            assert not (window.project.runs[index].style or {}).get("series")
            if cancel:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
                return

            def close_shortcuts():
                help_dialog = smoke.app.activeModalWidget()
                smoke.expect(isinstance(help_dialog, ShortcutsDialog), "F1 did not open keyboard shortcuts")
                if isinstance(help_dialog, ShortcutsDialog):
                    help_dialog.reject()
            QTest.qWait(80)
            QTimer.singleShot(100, close_shortcuts)
            QTest.keyClick(fields.pattern, Qt.Key.Key_F1)
            smoke.shot(dialog, "bar-series-appearance")
            fields.width.setFocus()
            QTest.keyClick(fields.width, Qt.Key.Key_Return)
            assert not dialog.isVisible(), "Enter did not confirm the changes"
        except Exception as error:
            smoke.problem(f"bar series appearance: {error!r}")
        finally:
            if isinstance(dialog, GraphFormatDialog) and dialog.isVisible():
                dialog.reject()

    for cancel in (True, False):
        QTimer.singleShot(150, lambda: edit_dialog(cancel))
        window.actions["format_graph"].trigger()
        if cancel:
            assert window.project.history.position == initial_depth
    assert window.project.history.position == initial_depth + 1
    run = window.project.runs[index]
    assert run.style["series"][key][BAR_APPEARANCE] == appearance
    pd.testing.assert_frame_equal(run.result.tables["Graph data"], original)
    check_chart(run.result.figure)
    window.actions["undo"].trigger()
    assert all(bar.patch.get_hatch() is None for bar in grouped_bars(run.result.figure))
    window.actions["redo"].trigger()
    check_chart(run.result.figure)

    window.project.put_layout(Layout("Visits", 1, [run.reference]))
    saved = smoke.folder / f"{smoke.language}-bar-series.alab"
    window.project.save(saved)
    assert json.loads(saved.read_text(encoding="utf-8"))["version"] == BAR_APPEARANCE_VERSION
    window.close_project()
    window.open_path(saved)
    window.open_sheet(reference)
    smoke.wait()
    run = window.project.runs[index]
    check_chart(run.result.figure)
    smoke.shot(window, "bar-series-appearance-reopened")

    for suffix in (".pdf", ".svg"):
        graph = saved.with_suffix(suffix)
        panel = saved.with_name(saved.stem + "-layout").with_suffix(suffix)
        export_figure(run.result.figure, graph, {"format": suffix[1:]})
        window.project.export_layout(window.project.layouts[0], panel, {"format": suffix[1:]})
        for path in (graph, panel):
            payload = path.read_bytes()
            if suffix == ".svg":
                assert b"<pattern" in payload and b"<image" not in payload and b"#c05798" in payload
            else:
                assert payload.startswith(b"%PDF") and b"/Pattern" in payload and b"/Subtype /Image" not in payload
