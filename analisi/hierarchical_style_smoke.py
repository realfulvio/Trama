"""Desktop smoke for the hierarchical presentation editor.

``tramastat.py --smoke`` calls :func:`check_hierarchical_style`.
Alone: ``TRAMASTAT_SMOKE_ONLY=hierarchical-style python tramastat.py --smoke DIR``.

Synthetic four-by-two markers only. Screenshots and exports go to ``DIR/hierarchical-style``.
A widget event is not a manual pointer test, and Xvfb scaling is not a system DPI.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import traceback
from tkinter import ttk
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .data import Dataset, save_project
from .graph_language_smoke import drive_mapped_dialog
from .hierarchical_style import describe_hierarchical_artists
from .hierarchical_style_dialog import HierarchicalStyleDialog
from .presentation import Layout


TABLE = "Markers"
METHOD = "Hierarchical clustering"


def _buttons(widget):
    found = []

    def walk(node):
        if isinstance(node, ttk.Button):
            try:
                found.append(str(node.cget("text")))
            except Exception:
                pass
        for child in node.winfo_children():
            walk(child)

    walk(widget)
    return found


def _png_stats(path):
    from PIL import Image, ImageStat

    image = Image.open(path)
    image.load()
    stat = ImageStat.Stat(image.convert("RGB"))
    return {"size": list(image.size), "stddev": [round(value, 2) for value in stat.stddev]}


def check_hierarchical_style(root, app, directory, tools):
    """EN and IT editor, both themes when the process was started in that theme, save/reopen, exports."""
    out = Path(directory) / "hierarchical-style"
    out.mkdir(exist_ok=True)
    log_path = out / "phases.log"
    phase_name = {"name": "start"}

    def phase(name):
        phase_name["name"] = name
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(name + "\n")
            stream.flush()

    def shot(window, name):
        tools.capture(window, name)
        source = Path(directory) / name
        if source.exists():
            source.replace(out / name)
        if os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"):
            assert (out / name).is_file() and (out / name).stat().st_size > 1000, name

    def operate(kind, action, *, confirm=False, timeout=12.0):
        def ready(dialog):
            try:
                dialog.update()
                action(dialog)
                if confirm:
                    dialog.ok()
                if dialog.winfo_exists():
                    if confirm:
                        tools.errors.append(f"{kind.__name__} stayed open: {getattr(dialog, 'problem', None)}")
                    dialog.cancel()
            except Exception as error:
                tools.errors.append(f"{kind.__name__}: {error!r}\n{traceback.format_exc()}")
                if dialog.winfo_exists():
                    dialog.cancel()

        drive_mapped_dialog(root, kind, ready, tools.errors, timeout=timeout)

    original = i18n.active_language()
    try:
        i18n.set_language("en")
        _run(root, app, directory, tools, out, phase, shot, operate)
        assert not tools.errors, tools.errors
    except Exception:
        phase("failed:" + phase_name["name"])
        try:
            tools.capture(root, "window-hierarchy-failure.png")
            source = Path(directory) / "window-hierarchy-failure.png"
            if source.exists():
                source.replace(out / "window-hierarchy-failure.png")
        except Exception:
            pass
        raise
    finally:
        i18n.set_language(original)


def _reachable(root, dialog):
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    for button in (dialog.preview_button, dialog.ok_button, dialog.cancel_button):
        assert button.winfo_ismapped() and button.winfo_viewable(), button
        assert button.winfo_rooty() >= dialog.winfo_rooty()
        assert button.winfo_rooty() + button.winfo_height() <= screen_h + 2, (
            button.winfo_rooty(), button.winfo_height(), screen_h)
        assert button.winfo_rootx() + button.winfo_width() <= screen_w + 2
    assert dialog.problem.winfo_ismapped()
    assert dialog.problem.winfo_parent() != str(dialog.scrolled.canvas)
    bottom = dialog.problem.winfo_rooty() + dialog.problem.winfo_height()
    assert dialog.winfo_rooty() <= dialog.problem.winfo_rooty() and bottom <= screen_h + 2, bottom


def _choose_next(dialog, field, expected):
    """Open the choice list from the keyboard and confirm the next canonical value."""
    section = field.split(".", 1)[0]
    dialog.notebook.select(dialog.tabs[section])
    dialog.update_idletasks()
    box = dialog.widgets[field]
    dialog.scrolled.reveal(box)
    box.focus_force()
    box.update()
    # Down posts the list. The popdown is a Tcl toplevel, so the following keys
    # go to its listbox path instead of a Tkinter child.
    box.event_generate("<Down>")
    # Windows delivers the focus change after the popdown has been mapped.
    box.update()
    listbox = f"{box._w}.popdown.f.l"
    assert str(box.tk.call("focus")) == listbox, "The choices did not receive keyboard focus."
    box.tk.call("event", "generate", listbox, "<Down>")
    box.tk.call("event", "generate", listbox, "<Return>")
    dialog.update()
    assert dialog.vars[field].get() == expected, (field, dialog.vars[field].get(), box.get())


def _width(figure, key="row"):
    return float(describe_hierarchical_artists(figure)[key]["branches"].get_linewidths()[0])


def _merges(run, name):
    return run.result.tables[name]["Distance"].to_numpy(dtype=float).copy()


def _run(root, app, directory, tools, out, phase, shot, operate):
    wait = tools.wait_for_calculation
    frame = pd.DataFrame({"A": [0.0, 0.0, 10.0, 10.0], "B": [0.0, 2.0, 10.0, 12.0]})
    source = out / "markers.alab"
    save_project(source, {TABLE: Dataset(frame)})
    phase("import")
    app.import_file(source)
    app.show("data", TABLE)
    root.update()

    def heat(dialog):
        tools.pick_method(dialog, METHOD)
        tools.select_columns(dialog, "Variables", {"A", "B"})
        dialog.controls["Direction"][1].set("Rows and columns")
        dialog.controls["Scale columns"][1].set("None")
        dialog.controls["Scale rows"][1].set("None")
        dialog.controls["Linkage"][1].set("average")
        dialog.controls["Distance"][1].set("euclidean")
        dialog.controls["Row cut"][1].set("Count")
        dialog.controls["Clusters"][1].set("2")
        dialog.controls["Column cut"][1].set("Count")
        dialog.controls["Column clusters"][1].set("2")
        dialog.controls["Graph output"][1].set("Heat map")
        dialog.controls["Label interval (0 = automatic)"][1].set("1")

    phase("fit-heat")
    operate(tools.AnalysisDialog, heat, confirm=True)
    app.choose_analysis(only=METHOD)
    wait()
    heat_index = next(i for i, run in enumerate(app.runs) if run.method == METHOD)
    app.show("data", TABLE)

    def tree(dialog):
        tools.pick_method(dialog, METHOD)
        tools.select_columns(dialog, "Variables", {"A", "B"})
        dialog.controls["Direction"][1].set("Rows")
        dialog.controls["Scale columns"][1].set("None")
        dialog.controls["Scale rows"][1].set("None")
        dialog.controls["Graph output"][1].set("Dendrogram")
        dialog.controls["Dendrogram orientation"][1].set("Vertical")
        dialog.controls["Label interval (0 = automatic)"][1].set("1")

    phase("fit-tree")
    operate(tools.AnalysisDialog, tree, confirm=True)
    app.choose_analysis(only=METHOD)
    wait()
    tree_index = next(i for i, run in enumerate(app.runs)
                      if run.method == METHOD and run.options.get("Graph output") == "Dendrogram")
    app.open_sheet(("graph", heat_index))
    wait()
    root.update()
    figure = app.runs[heat_index].result.figure
    row_distances = _merges(app.runs[heat_index], "Row Merges")
    column_distances = _merges(app.runs[heat_index], "Column Merges")
    assert np.allclose(np.sort(row_distances)[:2], [2.0, 2.0]), row_distances
    assert np.allclose(column_distances, [np.sqrt(8.0)]), column_distances
    baseline = _width(figure)
    assert "hierarchical" not in (app.runs[heat_index].style or {})
    assert i18n.tr("hierarchy.style.button") in _buttons(app.page), _buttons(app.page)
    shot(root, "window-hierarchy-graph-en.png")
    phase("save-legacy")
    legacy = out / "legacy-clusters.alab"
    app.path = legacy
    assert app.save(), "legacy project was not saved"

    phase("disabled-pages")
    app.open_sheet(("graph", tree_index))
    wait()

    def disabled(dialog):
        assert dialog.notebook.tab(dialog.tabs["column"], "state") == "disabled"
        assert dialog.notebook.tab(dialog.tabs["heatmap"], "state") == "disabled"
        assert dialog.notebook.tab(dialog.tabs["layout"], "state") == "disabled"
        assert dialog.notebook.tab(dialog.tabs["row"], "state") == "normal"
        _reachable(root, dialog)

    operate(HierarchicalStyleDialog, disabled)
    app.edit_hierarchical_style()
    assert not tools.errors, tools.errors

    phase("editor-en")
    app.open_sheet(("graph", heat_index))
    wait()
    before = _width(app.runs[heat_index].result.figure)

    def preview_and_error(dialog):
        _reachable(root, dialog)
        _choose_next(dialog, "row.color_mode", "single")
        assert dialog.widgets["row.color_mode"].get() == i18n.tr("hierarchy.style.choice.single")
        dialog.notebook.select(dialog.tabs["row"])
        dialog.vars["heatmap.minimum"].set("1")
        dialog.vars["heatmap.maximum"].set("")
        assert dialog.preview() is False
        assert dialog.focus_get() is dialog.widgets["heatmap.maximum"]
        assert dialog.notebook.select() == str(dialog.tabs["heatmap"])
        assert "both" in dialog.problem.cget("text").casefold()
        _reachable(root, dialog)
        shot(dialog, "window-hierarchy-dialog-en.png")
        assert _width(dialog.figure) == before
        dialog.vars["heatmap.minimum"].set("")
        dialog.vars["row.width"].set("3,5")
        assert dialog.preview() is True
        assert _width(dialog.figure) == 3.5

    operate(HierarchicalStyleDialog, preview_and_error)
    app.edit_hierarchical_style()
    assert not tools.errors, tools.errors
    assert app.runs[heat_index].style in (None, {}) or "hierarchical" not in (app.runs[heat_index].style or {})
    assert _width(app.runs[heat_index].result.figure) == before

    def apply_style(dialog):
        dialog.vars["row.width"].set("2.5")
        dialog.vars["row.color_mode"].set("cluster")
        dialog.vars["heatmap.title"].set("Signal $ literal")
        dialog.vars["heatmap.orientation"].set("horizontal")
        assert dialog.validate(), dialog.problem.cget("text")

    phase("apply")
    operate(HierarchicalStyleDialog, apply_style, confirm=True)
    app.edit_hierarchical_style()
    assert not tools.errors, tools.errors
    style = app.runs[heat_index].style
    assert style["hierarchical"]["row"]["width"] == 2.5
    assert style["hierarchical"]["row"]["color_mode"] == "cluster"
    assert style["hierarchical"]["heatmap"]["title"] == "Signal $ literal"
    assert style["hierarchical"]["heatmap"]["orientation"] == "horizontal"
    assert "color_mode" not in style["hierarchical"].get("column", {})
    assert np.allclose(_merges(app.runs[heat_index], "Row Merges"), row_distances)
    assert _width(app.runs[heat_index].result.figure) == 2.5
    described = describe_hierarchical_artists(app.runs[heat_index].result.figure)
    assert described["heatmap"]["colorbar"].orientation == "horizontal"
    assert len(app.runs[heat_index].result.figure.axes) == 4

    phase("format-graph")
    app.show("graph", heat_index)

    def format_graph(dialog):
        dialog.inputs["title"].set("Marker clusters")

    operate(tools.GraphFormatDialog, format_graph, confirm=True)
    app.format_graph()
    assert not tools.errors, tools.errors
    assert app.runs[heat_index].style["title"] == "Marker clusters"
    assert app.runs[heat_index].style["hierarchical"]["row"]["width"] == 2.5
    app.toggle_inspector()
    root.update()
    assert "hierarchical_style" in app.inspector.widgets
    app.toggle_inspector()
    shot(root, "window-hierarchy-styled-en.png")

    phase("italian")
    i18n.set_language("it")
    app.show("graph", heat_index)
    root.update()
    assert i18n.tr("hierarchy.style.button") in _buttons(app.page), _buttons(app.page)

    def italian(dialog):
        assert dialog.ok_button.cget("text") == i18n.tr("hierarchy.style.apply")
        assert dialog.widgets["row.color_mode"].get() == i18n.tr("hierarchy.style.choice.cluster")
        dialog.vars["heatmap.minimum"].set("4")
        assert dialog.preview() is False
        assert "automatici" in dialog.problem.cget("text")
        assert dialog.focus_get() is dialog.widgets["heatmap.maximum"]
        _reachable(root, dialog)
        shot(dialog, "window-hierarchy-dialog-it.png")

    operate(HierarchicalStyleDialog, italian)
    app.edit_hierarchical_style()
    assert not tools.errors, tools.errors
    assert app.runs[heat_index].style["hierarchical"]["row"]["width"] == 2.5
    i18n.set_language("en")

    if ui_theme.is_modern():
        phase("modern-copy")
        app.show("data", TABLE)
        root.update()
        workspace = app.modern_workspace
        assert workspace is not None and workspace.links
        heat_pos = next(i for i, (index, _run) in enumerate(workspace.links) if index == heat_index)
        workspace.choice.current(heat_pos)
        workspace._chosen()
        root.update()
        assert workspace.figure is not app.runs[heat_index].result.figure
        assert "heatmap" in describe_hierarchical_artists(workspace.figure)
        workspace.sidebar_wanted.set(True)
        workspace.toggle_sidebar()
        root.update()
        saved = app.runs[heat_index].result.figure

        def modern_apply(dialog):
            assert dialog.figure is not saved
            dialog.vars["column.width"].set("0.8")
            assert dialog.validate(), dialog.problem.cget("text")

        operate(HierarchicalStyleDialog, modern_apply, confirm=True)
        workspace.inspector.widgets["hierarchical_style"].invoke()
        assert not tools.errors, tools.errors
        assert app.runs[heat_index].style["hierarchical"]["column"]["width"] == 0.8
        assert _width(saved, "column") == 0.8
        assert _width(app.runs[heat_index].result.figure, "row") == 2.5
        shot(root, "window-hierarchy-modern.png")

    phase("save")
    styled = out / "styled-clusters.alab"
    app.path = styled
    assert app.save(), "styled project was not saved"
    saved_doc = json.loads(legacy.read_text(encoding="utf-8"))
    legacy_styles = saved_doc["tables"][0].get("graph_styles") or {}
    assert not any(isinstance(item, dict) and "hierarchical" in item for item in legacy_styles.values())
    phase("reopen-graph")
    app.import_file(styled)
    heat_index = next(i for i, run in enumerate(app.runs)
                      if run.method == METHOD and run.options.get("Graph output") == "Heat map")
    tree_index = next(i for i, run in enumerate(app.runs)
                      if run.method == METHOD and run.options.get("Graph output") == "Dendrogram")
    app.open_sheet(("graph", heat_index))
    wait()
    root.update()
    assert app.runs[heat_index].style["hierarchical"]["row"]["width"] == 2.5
    assert app.runs[heat_index].style["hierarchical"]["heatmap"]["title"] == "Signal $ literal"
    assert app.runs[heat_index].options["Linkage"] == "average"
    assert app.runs[heat_index].options["Distance"] == "euclidean"
    assert app.runs[heat_index].options["Scale columns"] == "None"
    assert _width(app.runs[heat_index].result.figure) == 2.5
    shot(root, "window-hierarchy-reopened.png")

    def parameters(dialog):
        assert dialog.controls["Linkage"][1].get() == "average"
        assert dialog.controls["Distance"][1].get() == "euclidean"
        assert dialog.controls["Scale columns"][1].get() == "None"
        assert dialog.controls["Graph output"][1].get() == "Heat map"
        assert dialog.controls["Direction"][1].get() == "Rows and columns"

    phase("parameters")
    operate(tools.AnalysisDialog, parameters)
    app.edit_analysis()
    assert not tools.errors, tools.errors

    phase("edit-cell")
    kept = deepcopy(app.runs[heat_index].style["hierarchical"])
    app.show("data", TABLE)
    root.update()
    app.edit_cell(0, 0, "3")
    wait()
    app.open_sheet(("graph", heat_index))
    wait()
    assert not np.allclose(_merges(app.runs[heat_index], "Row Merges"), row_distances)
    assert app.runs[heat_index].style["hierarchical"]["row"]["width"] == kept["row"]["width"]
    assert app.runs[heat_index].style["hierarchical"]["heatmap"]["title"] == kept["heatmap"]["title"]
    assert _width(app.runs[heat_index].result.figure) == 2.5

    phase("switch-graph")
    for graph_output in ("Elbow plot", "Heat map"):
        operate(tools.AnalysisDialog,
                lambda dialog: dialog.controls["Graph output"][1].set(graph_output), confirm=True)
        app.edit_analysis()
        wait()
        app.open_sheet(("graph", heat_index))
        wait()
        run = app.runs[heat_index]
        assert run.options["Graph output"] == graph_output
        assert run.result.style_warning is None and run.style["hierarchical"] == kept
        if graph_output == "Elbow plot":
            assert "Row Elbow data" in run.result.tables
            assert not describe_hierarchical_artists(run.result.figure)
        else:
            assert _width(run.result.figure) == 2.5

    phase("exclude")
    app.show("data", TABLE)
    root.update()
    app.current_grid.select((3, 1))
    app.toggle_exclusion()
    wait()
    app.open_sheet(("graph", heat_index))
    wait()
    assert len(app.runs[heat_index].result.tables["Row Merges"]) == 2
    assert app.runs[heat_index].style["hierarchical"] == kept
    assert _width(app.runs[heat_index].result.figure) == 2.5

    phase("export-figure")
    app.show("graph", heat_index)
    root.update()
    exported = {}
    for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"clusters.{ext}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:800] or (ext == "svg" and magic in content), ext
        assert len(content) > 1000
        exported[ext] = target
    svg = exported["svg"].read_text(encoding="utf-8")
    assert "Signal $ literal" in svg
    assert "selector" not in svg.casefold() and "rubber" not in svg.casefold()
    ET.parse(exported["svg"])
    png_info = _png_stats(exported["png"])
    assert max(png_info["stddev"]) > 1, png_info
    from pypdfium2 import PdfDocument

    with PdfDocument(exported["pdf"]) as document:
        assert len(document) == 1

    phase("csv-and-data")
    app.show("result", heat_index)
    root.update()
    titles = list(app.runs[heat_index].result.tables)
    app.result_tabs.select(titles.index("Row Merges"))
    csv_path = out / "row-merges.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Distance" in csv_text and "2" in csv_text
    before_tables = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert added, app.tables.keys()

    phase("layout")
    app.layouts.append(Layout("Cluster layout", 2, [
        app.runs[heat_index].reference, app.runs[tree_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-hierarchy-layout.png")
    for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"layout.{ext}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:800] or (ext == "svg" and magic in content), ext
        assert target.stat().st_size > 1000
    layout_svg = (out / "layout.svg").read_text(encoding="utf-8")
    assert "selector" not in layout_svg.casefold()
    ET.parse(out / "layout.svg")
    layout_png = _png_stats(out / "layout.png")
    assert max(layout_png["stddev"]) > 1

    phase("legacy")
    app.import_file(legacy)
    legacy_index = next(i for i, run in enumerate(app.runs)
                        if run.method == METHOD and run.options.get("Graph output") == "Heat map")
    app.open_sheet(("graph", legacy_index))
    wait()
    assert "hierarchical" not in (app.runs[legacy_index].style or {})
    assert app.runs[legacy_index].options["Linkage"] == "average"
    assert app.runs[legacy_index].options["Graph output"] == "Heat map"
    assert _width(app.runs[legacy_index].result.figure) == baseline
    assert np.allclose(_merges(app.runs[legacy_index], "Row Merges"), row_distances)
    assert len(app.runs[legacy_index].result.figure.axes) == 4
    shot(root, "window-hierarchy-legacy.png")

    screen = [root.winfo_screenwidth(), root.winfo_screenheight()]
    (out / "checks.json").write_text(json.dumps({
        "status": "PASS",
        "screen": screen,
        "theme": ui_theme._state.get("theme", "standard"),
        "tk_scaling": round(float(root.tk.call("tk", "scaling")), 4),
        "row_merges_before_edit": row_distances.tolist(),
        "column_merges": column_distances.tolist(),
        "figure_png": png_info,
        "layout_png": layout_png,
        "added_table": sorted(added),
    }, indent=2), encoding="utf-8")
    phase("done")
