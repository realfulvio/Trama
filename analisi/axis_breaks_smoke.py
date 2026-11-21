"""Desktop smoke check for axis breaks on XY series and XY error bars.

``tramastat.py --smoke`` calls :func:`check_axis_breaks` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=axis-breaks python tramastat.py --smoke DIR``.

It drives the real widgets of the application: Format Graph and the Inspector open the editor, the editor
previews on the live graph, and the confirmed style is saved, reopened, recalculated and exported. The window
takes the size of the screen (at most 1600×1000), so the same check runs at 1024×768, 1600×1000 and 1920×1080.

Synthetic data only. Artifacts and the project stay in ``DIR/axis-breaks``; screenshots in ``DIR``.
"""
from copy import deepcopy
from io import BytesIO
import platform
import re
import sys
import time
import traceback
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from PIL import Image

from . import i18n, ui_theme
from .axis_breaks import (AXIS_BREAKS, MARKER_PREFIX, axis_breaks_reason, panel_scope, segment_axes)
from .axis_breaks_dialog import AxisBreaksDialog
from .axis_guides import AXIS_GUIDES
from .axis_guides_dialog import AxisGuidesDialog, GuideEditorDialog
from .axis_guides_smoke import _fits, _pdf_objects
from .data import Dataset, save_project
from .figure_export_dialog import FigureExportDialog
from .graph_dialog import GraphFormatDialog
from .graph_language_smoke import drive_mapped_dialog

TITLE = "Dose response"
OLD = "Old project"
FLAT = "Two axes"
LOGGED = "Log axis"
COLUMNS = "Columns"
BIG = "Ten thousand"
FRAME = pd.DataFrame({
    "Time": [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 7.0, 10.0, 11.0, 12.0, 18.0, 20.0, 22.0],
    "Control": [1.0, 2.0, 2.7, 3.6, 4.5, 11.0, 15.0, 21.0, 22.0, 24.0, 27.0, 29.0, 31.0],
    "Treated": [2.0, 5.0, 8.0, np.nan, 9.0, 12.0, 14.0, 24.0, 27.0, 30.0, 25.0, 28.0, 34.0],
    "Lower": [.2, .2, .4, .2, .3, .4, .5, .2, .5, .2, .6, .8, 1.2],
    "Upper": [.6, .4, .7, .6, .8, .6, .3, .6, .7, .4, .9, .7, 1.6],
})
SERIES = ("XY series", {"X": "Time", "Y columns": ["Control", "Treated"],
                        "Series style": {"Control": "Line and points", "Treated": "Points"}})
ERRORS = ("XY error bars", {"X": "Time", "Y": "Control", "Y lower error": "Lower", "Y upper error": "Upper",
                            "Y error values": "Distances"})
X_BREAKS = {"axis": "x", "gap": 0.04, "segments": [
    {"low": 0.0, "high": 4.0, "share": 35.0, "major_step": 2.0},
    {"low": 10.0, "high": 12.0, "share": 30.0, "major_step": 1.0},
    {"low": 18.0, "high": 22.0, "share": 35.0, "major_step": 2.0}]}
Y_BREAKS = {"axis": "y", "gap": 0.05, "segments": [
    {"low": 0.0, "high": 10.0, "share": 42.0, "major_step": 5.0},
    {"low": 20.0, "high": 36.0, "share": 58.0, "major_step": 4.0}]}


def check_axis_breaks(kit):
    """Run the end-to-end axis breaks smoke inside the real Trama application."""
    original_lang = i18n.active_language()
    geometry = kit.root.geometry()
    try:
        _run(kit)
    finally:
        i18n.set_language(original_lang)
        kit.root.geometry(geometry)
        kit.root.update()


def _panels(figure):
    return segment_axes(figure)


def _legends(figure):
    return [item for item in (*figure.legends, *(axes.get_legend() for axes in figure.axes))
            if item is not None and item.get_visible()]


def _scopes(figure):
    return [panel_scope(panel)[:3] for panel in _panels(figure)]


def _drive(owner, kind, ready, errors):
    """Run ``ready(dialog)`` once ``kind`` is open; a failure is recorded and closes the dialog, never hangs it."""
    def guarded(dialog):
        try:
            ready(dialog)
        except Exception:
            errors.append(f"{kind.__name__}: {traceback.format_exc()}")
            if dialog.winfo_exists():
                dialog.cancel()

    drive_mapped_dialog(owner, kind, guarded, errors)


def _edit_breaks(owner, button, errors, mutate):
    """Open the editor with ``button`` and run ``mutate(editor)``; the editor stays open until it returns."""
    _drive(owner, AxisBreaksDialog, mutate, errors)
    button.invoke()
    assert not errors, errors


def _fill(editor, record):
    editor.axis.set(record["axis"])
    editor.count.set(str(len(record["segments"])))
    for row, segment in enumerate(record["segments"]):
        for name in ("low", "high", "share"):
            editor.vars[(row, name)].set(f"{segment[name]:g}")
        editor.vars[(row, "major_step")].set("" if segment["major_step"] is None else f"{segment['major_step']:g}")
    editor.gap.set(f"{record['gap']:g}")


def run_index(app, title, slot=0):
    return next(position for position, item in enumerate(app.runs) if item.title == title and item.slot == slot)


def _rows(frame):
    """The points of a Series values sheet that fall inside X_BREAKS (limits belong to their segment)."""
    inside = np.zeros(len(frame), dtype=bool)
    for segment in X_BREAKS["segments"]:
        inside |= (frame["X"] >= segment["low"]) & (frame["X"] <= segment["high"])
    return int(inside.sum())


def _environment(root, out, editor_size, inspector_size):
    import tkinter

    lines = [
        f"system: {platform.platform()}", f"python: {sys.version.split()[0]}",
        f"tk: {root.tk.call('info', 'patchlevel')} (tkinter {tkinter.TkVersion})",
        f"screen: {root.winfo_screenwidth()}x{root.winfo_screenheight()}",
        f"window: {root.winfo_width()}x{root.winfo_height()}",
        f"tk scaling: {float(root.tk.call('tk', 'scaling')):.3f}", f"editor: {editor_size[0]}x{editor_size[1]}",
        f"inspector width: {inspector_size}",
    ]
    (out / "environment.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(kit):
    app, root, wait, capture = kit.app, kit.root, kit.wait_for_calculation, kit.capture
    errors = kit.errors
    out = kit.directory / "axis-breaks"
    out.mkdir(exist_ok=True)
    alab = out / "axis-breaks.alab"
    screen = (min(root.winfo_screenwidth(), 1600), min(root.winfo_screenheight(), 1000))
    root.geometry(f"{screen[0]}x{screen[1]}+0+0")
    root.update()

    dataset = Dataset(FRAME.copy())
    dataset.analyses.extend([SERIES, ERRORS])
    legacy = Dataset(FRAME.copy())
    legacy.analyses.append(SERIES)
    flat = Dataset(FRAME.copy())
    flat.analyses.append(("XY series", {**SERIES[1], "Series side": {"Control": "Left", "Treated": "Right"}}))
    flat.graph_styles[0] = {"axis_breaks": deepcopy(Y_BREAKS)}
    logged = Dataset(FRAME.copy())
    logged.analyses.append(SERIES)
    logged.graph_styles[0] = {"yscale": "log", "axis_breaks": deepcopy(Y_BREAKS)}
    columns = Dataset(FRAME[["Control", "Treated"]].copy())
    columns.analyses.append(("Column graph", {"Variables": ["Control", "Treated"]}))
    columns.graph_styles[0] = {"axis_breaks": deepcopy(Y_BREAKS)}
    save_project(alab, {TITLE: dataset, OLD: legacy, FLAT: flat, LOGGED: logged, COLUMNS: columns})

    # --- 1. English, Format Graph: three X segments on the series graph ---------------------
    i18n.set_language("en")
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]
    original_limits = run.result.figure.axes[0].get_xlim()
    assert not _panels(run.result.figure) and AXIS_BREAKS not in (run.style or {})
    sizes = {}

    def drive_format(dlg):
        dlg.notebook.select(1)
        _fits(dlg, (dlg.breaks_button,), root)
        assert dlg.breaks_summary.cget("text") == i18n.tr("axis_breaks.summary_none")

        def drive_editor(editor):
            _fits(editor, (editor.preview_button, editor.ok_button, editor.cancel_button, editor.suggest_button), root)
            sizes["editor"] = (editor.winfo_width(), editor.winfo_height())
            editor.axis.set("x")
            assert editor.vars[(0, "low")].get(), "choosing the axis suggests the segments"
            _fill(editor, X_BREAKS)
            assert editor.preview()
            figure = run.result.figure
            assert _scopes(figure) == [("x", 0.0, 4.0), ("x", 10.0, 12.0), ("x", 18.0, 22.0)], _scopes(figure)
            valid = _scopes(figure)

            def refuses(change, widget):
                """An invalid draft keeps the last valid preview and sends the focus to its field."""
                before = {key: variable.get() for key, variable in editor.vars.items()}
                change()
                assert not editor.preview(), widget
                assert editor.problem.cget("text"), widget
                assert editor.error_widget is editor.widgets[widget], (editor.error_widget, widget)
                assert _scopes(run.result.figure) == valid
                assert editor.winfo_exists()
                for key, value in before.items():
                    editor.vars[key].set(value)

            refuses(lambda: (editor.vars[(1, "low")].set("13"), editor.vars[(1, "high")].set("12")),
                    "segments.1.high")
            refuses(lambda: editor.vars[(1, "low")].set("3"), "segments.1.low")
            refuses(lambda: editor.vars[(2, "share")].set("40"), "segments.2.share")
            refuses(lambda: editor.vars[(0, "high")].set("abc"), "segments.0.high")
            refuses(lambda: editor.vars[(0, "major_step")].set("0.001"), "segments.0.major_step")
            refuses(lambda: editor.gap.set("0.5"), "gap")
            # Changing the axis asks for new segments of that axis; the old ones are not reused.
            editor.axis.set("y")
            assert float(editor.vars[(0, "high")].get()) > 12, "the Y segments follow the Y data"
            editor.axis.set("x")
            _fill(editor, X_BREAKS)
            assert editor.preview()
            capture(editor, "window-axis-breaks-dialog-en.png")
            editor.ok()

        _edit_breaks(dlg, dlg.breaks_button, errors, drive_editor)
        assert dlg.breaks_summary.cget("text") == i18n.tr("axis_breaks.summary", axis="X", count=3)
        assert str(dlg._axis_widgets["x"]["min"].cget("state")) == "disabled"
        assert str(dlg._axis_widgets["y"]["min"].cget("state")) != "disabled"
        capture(dlg, "window-axis-breaks-format-en.png")
        dlg.ok()

    _drive(root, GraphFormatDialog, drive_format, errors)
    app.format_graph()
    assert not errors, errors
    run = app.runs[0]
    figure = run.result.figure
    assert run.style[AXIS_BREAKS]["axis"] == "x" and len(run.style[AXIS_BREAKS]["segments"]) == 3
    assert app.tables[TITLE].graph_styles[0][AXIS_BREAKS] == run.style[AXIS_BREAKS]
    assert _scopes(figure) == [("x", 0.0, 4.0), ("x", 10.0, 12.0), ("x", 18.0, 22.0)]
    assert len(_legends(figure)) == 1, "one legend for the three panels"
    assert all(panel.get_ylim() == figure.axes[0].get_ylim() for panel in _panels(figure)), "Y stays in sync"
    assert any(str(item.get_gid()).startswith(MARKER_PREFIX) for panel in _panels(figure) for item in panel.get_children())
    root.update()
    capture(root, "window-axis-breaks-x3-en.png")

    # Format Graph Cancel puts the confirmed graph back after a preview of other breaks.
    def drive_cancel(dlg):
        dlg.notebook.select(1)

        def drive_editor(editor):
            editor.axis.set("y")
            assert editor.preview()
            assert _scopes(run.result.figure)[0][0] == "y"
            editor.ok()

        _edit_breaks(dlg, dlg.breaks_button, errors, drive_editor)
        dlg.cancel()

    _drive(root, GraphFormatDialog, drive_cancel, errors)
    app.format_graph()
    assert not errors, errors
    assert _scopes(app.runs[0].result.figure)[0][0] == "x" and app.runs[0].style[AXIS_BREAKS]["axis"] == "x"

    # --- 2. Inspector: two Y segments on the error bars graph, guides and series style ---------------------
    app.open_sheet(("graph", 1))
    wait()
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None and hasattr(inspector, "axis_breaks_button")
    root.update()
    sizes["inspector"] = inspector.winfo_width()
    figure = app.runs[1].result.figure
    assert not _panels(figure)

    def drive_y(editor):
        editor.axis.set("y")
        editor.count.set("2")
        _fill(editor, Y_BREAKS)
        assert editor.preview() and len(_panels(figure)) == 2
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_y)
    assert inspector.draft[AXIS_BREAKS]["axis"] == "y" and inspector.has_draft
    assert "disabled" in inspector.widgets["ymin"].state() and "disabled" in inspector.widgets["yscale"].state()
    assert "disabled" not in inspector.widgets["xmin"].state()
    # A guide on the broken axis reaches the panel that has its value, and its label shows once.
    def drive_guide(guides):
        def drive_add(editor):
            editor.fields["axis"].set("y")
            editor.fields["value"].set("25")
            editor.fields["tick"].set(True)
            editor.fields["line"].set(True)
            editor.fields["label"].set("Limit")
            editor.ok()

        _drive(guides, GuideEditorDialog, drive_add, errors)
        guides.add()
        assert not errors, errors
        guides.ok()

    _drive(inspector, AxisGuidesDialog, drive_guide, errors)
    inspector.axis_guides_button.invoke()
    assert not errors, errors
    assert inspector.draft[AXIS_GUIDES][0]["label"] == "Limit"
    labels = [text.get_text() for panel in _panels(figure) for text in panel.get_yticklabels()]
    assert labels.count("Limit") == 1, labels
    inspector.vars["element:color"].set("#aa3355")
    inspector._now("element:color")
    colors = {panel_scope(panel)[3]: [str(line.get_color()) for line in panel.lines if line.get_marker() == "o"]
              for panel in _panels(figure)}
    assert all("#aa3355" in values for values in colors.values()), colors
    assert inspector.apply() and inspector.apply(), "Apply twice"
    assert len(_panels(figure)) == 2 and len(_legends(figure)) <= 1, (len(_panels(figure)), len(_legends(figure)))
    assert app.runs[1].style[AXIS_BREAKS] == inspector.draft[AXIS_BREAKS]
    asymmetric = [segment for panel in _panels(figure) for collection in panel.collections
                  if isinstance(collection, LineCollection) for segment in collection.get_segments()]
    assert asymmetric, "error bars are drawn on the panels"
    root.update()
    capture(root, "window-axis-breaks-y2-en.png")
    _environment(root, out, sizes["editor"], sizes["inspector"])
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None

    # --- 3. Italian and the Modern theme: decimal commas, translated problems, both entry points ------------
    i18n.set_language("it")
    app.open_sheet(("graph", 1))
    wait()
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None
    figure = app.runs[1].result.figure
    assert len(_panels(figure)) == 2

    def drive_italian(editor):
        _fits(editor, (editor.preview_button, editor.ok_button, editor.cancel_button), root)
        assert editor.title() == "Interruzioni asse"
        editor.vars[(0, "share")].set("42,5")
        editor.vars[(1, "share")].set("50")
        assert not editor.preview()
        assert editor.problem.cget("text") == i18n.tr("axis_breaks.error.m_total", total="92.5")
        assert editor.error_widget is editor.widgets["segments.1.share"]
        editor.vars[(1, "share")].set("57,5")
        editor.vars[(0, "major_step")].set("2,5")
        assert editor.preview()
        capture(editor, "window-axis-breaks-dialog-it.png")
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_italian)
    assert inspector.apply()
    record = app.runs[1].style[AXIS_BREAKS]
    assert [segment["share"] for segment in record["segments"]] == [42.5, 57.5]
    assert record["segments"][0]["major_step"] == 2.5
    root.update()
    capture(root, "window-axis-breaks-it.png")
    inspector.cancel_button.invoke()
    root.update()

    # The Modern workspace is created only when the app starts in that theme.
    if ui_theme.is_modern():
        app.show("data", TITLE)
        root.update()
        workspace = app.modern_workspace
        assert workspace is not None and workspace.inspector is not None
        workspace.choice.current(0)
        workspace._chosen()
        if not workspace.sidebar_wanted.get():
            workspace.show_format()
        root.update()
        assert hasattr(workspace.inspector, "axis_breaks_button")
        assert "disabled" not in workspace.inspector.axis_breaks_button.state()
        capture(root, "window-axis-breaks-modern.png")
    i18n.set_language("en")
    root.update()

    # --- 4. Save, reopen the graph first, old projects, and styles that cannot be drawn ------------------------
    app.path = alab
    assert app.save()
    app.import_file(alab)

    def graph_of(title, slot=0):
        index = next(position for position, item in enumerate(app.runs) if item.title == title and item.slot == slot)
        app.open_sheet(("graph", index))
        wait()
        return app.runs[index]

    reopened = graph_of(TITLE)
    assert reopened.style[AXIS_BREAKS] == X_BREAKS | {"segments": reopened.style[AXIS_BREAKS]["segments"]}
    assert _scopes(reopened.result.figure) == [("x", 0.0, 4.0), ("x", 10.0, 12.0), ("x", 18.0, 22.0)]
    assert reopened.result.style_warning is None
    old = graph_of(OLD)
    assert AXIS_BREAKS not in (old.style or {}) and not _panels(old.result.figure)
    assert old.result.style_warning is None and axis_breaks_reason(old.result.figure) is None
    declared = {
        FLAT: "right Y axis", LOGGED: "linear Y axis", COLUMNS: "XY series, XY error bars and global nonlinear fits"}
    for title, fragment in declared.items():
        item = graph_of(title)
        figure = item.result.figure
        assert not _panels(figure), title
        assert item.style[AXIS_BREAKS] == Y_BREAKS, "a saved setting that cannot be drawn is kept"
        assert fragment in (axis_breaks_reason(figure) or ""), (title, axis_breaks_reason(figure))
        assert fragment in (item.result.style_warning or ""), (title, item.result.style_warning)
        assert "need review" in app.status.get() and fragment in app.status.get(), app.status.get()
        assert len(figure.axes) == (2 if title == FLAT else 1), "the graph is whole, not half drawn"
    flat_run = graph_of(FLAT)
    app.toggle_inspector()
    assert "saved but not drawn" in app.inspector.axis_breaks_label.cget("text")
    app.close_inspector()

    # --- 5. Editing data: a point in the gap stays in the sheet, one on the limit appears ------------------
    app.show("data", TITLE)
    app.edit_cell(5, 1, "12.5")
    wait()
    run = graph_of(TITLE)
    sheet = run.result.tables["Series values"]
    assert ((sheet["X"] == 6.0) & (sheet["Y column"] == "Control") & (sheet["Y"] == 12.5)).any(), "the gap point is listed"
    visible = _rows(sheet)
    assert len(_panels(run.result.figure)) == 3
    app.show("data", TITLE)
    app.edit_cell(5, 0, "4")
    wait()
    run = graph_of(TITLE)
    assert _rows(run.result.tables["Series values"]) == visible + 2, "points on a limit belong to the segment"
    assert len(_panels(run.result.figure)) == 3
    app.show("data", TITLE)
    app.apply_worksheet_history()
    wait()
    run = graph_of(TITLE)
    assert _rows(run.result.tables["Series values"]) == visible
    app.show("data", TITLE)
    app.apply_worksheet_history()
    wait()
    run = graph_of(TITLE)
    assert (run.result.tables["Series values"]["Y"] == 12.5).sum() == 0, "undo returns the original value"
    assert _scopes(run.result.figure) == [("x", 0.0, 4.0), ("x", 10.0, 12.0), ("x", 18.0, 22.0)]

    # --- 6. Three segments, two, none; Apply twice, Esc and the reset of the Axes section -------------------
    app.toggle_inspector()
    inspector = app.inspector
    figure = run.result.figure
    two = {"axis": "x", "gap": 0.04, "segments": [
        {"low": 0.0, "high": 4.0, "share": 40.0, "major_step": 2.0},
        {"low": 18.0, "high": 22.0, "share": 60.0, "major_step": 2.0}]}

    def drive_two(editor):
        _fill(editor, two)
        assert editor.preview()
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_two)
    assert len(_panels(figure)) == 2 and inspector.apply() and inspector.apply()
    assert len(_panels(figure)) == 2 and len(figure.axes) == 2 and app.runs[run_index(app, TITLE)].style[AXIS_BREAKS]["segments"][1]["share"] == 60.0

    def drive_none(editor):
        editor.axis.set("")
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_none)
    assert not _panels(figure) and AXIS_BREAKS not in inspector.draft and len(figure.axes) == 1
    assert figure.axes[0].get_xlim() == original_limits, (figure.axes[0].get_xlim(), original_limits)
    assert type(figure.get_layout_engine()).__name__ == "ConstrainedLayoutEngine"
    assert figure.axes[0].get_legend() is not None
    assert inspector.apply()
    assert AXIS_BREAKS not in app.runs[run_index(app, TITLE)].style
    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_two)
    assert len(_panels(figure)) == 2
    inspector.reset_section("axes")
    assert not _panels(figure) and AXIS_BREAKS not in inspector.draft
    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_two)
    assert len(_panels(figure)) == 2
    inspector._escape(None)
    root.update()
    assert app.inspector is None and not _panels(figure), "Esc discards the draft and shows the confirmed graph"
    assert AXIS_BREAKS not in app.runs[run_index(app, TITLE)].style

    # --- 7. Exports: figure, old figure, two axes, and a two-panel layout in PNG, SVG and PDF ---------------
    graph_of(TITLE)
    app.toggle_inspector()
    inspector = app.inspector
    figure = app.runs[run_index(app, TITLE)].result.figure

    def drive_x(editor):
        _fill(editor, X_BREAKS)
        assert editor.preview()
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_x)
    assert inspector.apply() and len(_panels(figure)) == 3
    app.close_inspector()

    def export_with_options(target, fmt, svg_text=None):
        def drive_export(dialog):
            dialog.format.set(fmt)
            if svg_text:
                dialog.svg_text.set(svg_text)

        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            kit.drive_dialog(FigureExportDialog, drive_export)
            app.export_with_options()
        assert not errors, errors
        assert target.exists() and target.stat().st_size > 0, target

    def check_svg(path, *, markers, label=None):
        text = path.read_text(encoding="utf-8")
        assert "<image" not in text, "vector export holds no bitmap"
        ids = [element.get("id") for element in ET.fromstring(text).iter() if element.get("id")]
        assert len(ids) == len(set(ids)), "SVG ids are unique"
        found = [item for item in ids if MARKER_PREFIX in item]
        assert bool(found) == markers, (path.name, len(found))
        if label:
            assert label in text
        return found

    graph_of(TITLE, 1)
    results = {}
    for fmt, extension, extra in (("PNG", "png", {}), ("SVG", "svg", {"svg_text": "Text"}), ("PDF", "pdf", {})):
        target = out / f"y-breaks.{extension}"
        export_with_options(target, fmt, **extra)
        results[extension] = target
    flat = Image.open(results["png"]).convert("L")
    marked = sum(1 for value in flat.getdata() if value < 200)
    assert flat.size[0] > 200 and marked > 0.002 * flat.size[0] * flat.size[1], ("the PNG is blank", flat.size, marked)
    assert check_svg(results["svg"], markers=True, label="Limit")
    pdf_text, pdf_paths, pdf_images = _pdf_objects(results["pdf"])
    assert "Limit" in pdf_text and pdf_paths > 0 and pdf_images == 0

    graph_of(OLD)
    export_with_options(out / "old.svg", "SVG", svg_text="Text")
    check_svg(out / "old.svg", markers=False)
    graph_of(FLAT)
    export_with_options(out / "two-axes.svg", "SVG", svg_text="Text")
    check_svg(out / "two-axes.svg", markers=False)
    export_with_options(out / "two-axes.png", "PNG")

    graph_of(TITLE, 1)

    def choose_layout(dialog):
        dialog.name.set("Layout axis breaks")
        dialog.list.selection_set(0, 1)
        dialog.add_selected()

    kit.drive_dialog(kit.LayoutDialog, choose_layout)
    app.new_layout()
    layout_svg, layout_pdf = out / "layout-breaks.svg", out / "layout-breaks.pdf"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(layout_pdf)):
        app.export()
    panels = {item.split("-", 1)[0] for item in check_svg(layout_svg, markers=True)}
    assert len(panels) >= 2, ("both graphs keep their break marks in the layout", panels)
    _, layout_paths, layout_images = _pdf_objects(layout_pdf)
    assert layout_paths > 0 and layout_images == 0
    export_with_options(out / "layout-breaks.png", "PNG")

    # --- 8. Time: 10,000 points and three segments ---------------------------------------------------------
    rng = np.random.default_rng(7)
    seconds = np.concatenate([rng.uniform(0, 4, 3000), rng.uniform(10, 12, 3000), rng.uniform(18, 22, 4000)])
    big = Dataset(pd.DataFrame({"Time": seconds, "Control": 1.4 * seconds + rng.normal(0, 1.5, len(seconds))}))
    big.analyses.append(("XY series", {"X": "Time", "Y columns": ["Control"], "Series style": {"Control": "Points"}}))
    big_path = out / "ten-thousand.alab"
    save_project(big_path, {BIG: big})
    app.import_file(big_path)
    graph_of(BIG)
    app.toggle_inspector()
    inspector = app.inspector
    figure = app.runs[run_index(app, BIG)].result.figure
    timings = {}
    start = time.perf_counter()
    app.graph_canvas.draw()
    timings["draw without breaks"] = time.perf_counter() - start

    def drive_big(editor):
        _fill(editor, X_BREAKS)
        start = time.perf_counter()
        assert editor.preview()
        app.graph_canvas.draw()
        timings["preview with three segments (apply and draw)"] = time.perf_counter() - start
        editor.ok()

    _edit_breaks(inspector, inspector.axis_breaks_button, errors, drive_big)
    assert inspector.apply() and len(_panels(figure)) == 3
    app.close_inspector()
    for fmt, extension, extra in (("PNG", "png", {}), ("SVG", "svg", {"svg_text": "Text"}), ("PDF", "pdf", {})):
        start = time.perf_counter()
        export_with_options(out / f"ten-thousand.{extension}", fmt, **extra)
        timings[f"first {fmt} export (end to end, dialog included)"] = time.perf_counter() - start
    lines = [f"{name}: {value:.2f} s" for name, value in timings.items()]
    (out / "timings.txt").write_text("10,000 points, X axis, three segments\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("axis breaks timings:", "; ".join(lines))
    assert timings["preview with three segments (apply and draw)"] < 20, timings
    assert max(value for name, value in timings.items() if name.startswith("first")) < 60, timings
    widget = app.graph_canvas.get_tk_widget()
    with (out / "environment.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"graph widget: {widget.winfo_width()}x{widget.winfo_height()}"
                     f" (pixel ratio {app.graph_canvas.device_pixel_ratio})\n")
