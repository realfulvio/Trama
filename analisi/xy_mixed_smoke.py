"""Desktop smoke check for XY series that mix bars, steps, lines and points on one graph.

``tramastat.py --smoke`` calls :func:`check_xy_mixed` with its helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=xy-mixed python tramastat.py --smoke DIR``.

Synthetic data only: the six rows of the mixed-series fixture of the XY package. Every step drives the real
Analyze dialog, Format Graph, the Inspector, worksheet edits and exclusions, save and reopen, exports and a
two-panel layout, then checks the artists that were drawn and the vector IDs that were written.
"""
from copy import deepcopy
import json
import time
from unittest.mock import patch
from xml.etree import ElementTree as ET

from matplotlib.colors import to_hex, to_rgba
from matplotlib.container import BarContainer
import numpy as np
import pandas as pd

from . import i18n
from .graph_dialog import GraphFormatDialog
from .xy_series import BAR_WIDTH

TABLE = "Mixed series"
SMALL = (1024, 768)
LARGE = (1600, 1000)
COLUMNS = ["Bars left", "Bars right", "Step dose", "Trend"]


def source():
    return pd.DataFrame({
        "Time": [0.0, 1.0, 2.0, 4.0, 5.0, 8.0],
        "Bars left": [2.0, np.nan, -3.0, 4.0, 0.0, 9.0],
        "Bars right": [1.0, 3.0, 2.0, np.nan, -2.0, 7.0],
        "Step dose": [0.0, 3.0, np.nan, 4.0, 6.0, 5.0],
        "Trend": [3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    })


def bars(figure, side):
    return [c for c in figure.axes[side].containers if isinstance(c, BarContainer)]


def centers(container):
    return [round(p.get_x() + p.get_width() / 2, 9) for p in container.patches]


def svg_bar_ids(path):
    root = ET.parse(path).getroot()
    if any(element.tag.endswith("}image") for element in root.iter()):
        raise AssertionError(f"{path.name} embeds a raster image")
    return [element.get("id") for element in root.iter() if "xybar:" in (element.get("id") or "")]


def check_xy_mixed(root, app, directory, tools):
    """Run in English, then repeat the editors in Italian; ``tools`` carries the smoke helpers."""
    language = i18n.active_language()
    geometry = root.geometry()
    out = directory / "xy-mixed"
    out.mkdir(exist_ok=True)
    report = {"screen": f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}", "checks": [], "seconds": {}}
    started = time.monotonic()
    try:
        i18n.set_language("en")
        _check(root, app, directory, out, tools, report)
    finally:
        i18n.set_language(language)
        root.geometry(geometry)
        root.update()
        report["seconds"]["total"] = round(time.monotonic() - started, 2)
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _check(root, app, directory, out, tools, report):
    errors, wait = tools.errors, tools.wait_for_calculation
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{SMALL[0]}x{SMALL[1]}+0+0")
    root.update()

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def find(parent, kind):
        for child in parent.winfo_children():
            if isinstance(child, kind):
                return child
            found = find(child, kind)
            if found is not None:
                return found
        return None

    def format_graph(action, *, accept=True):
        def enter():
            dialog = find(root, GraphFormatDialog)
            if dialog is None:
                errors.append("Format Graph did not open")
                return
            try:
                dialog.update()
                action(dialog)
                if dialog.winfo_exists():
                    dialog.ok() if accept else dialog.cancel()
                if dialog.winfo_exists():
                    errors.append("Format Graph stayed open")
                    dialog.cancel()
            except Exception as error:
                errors.append(f"Format Graph: {error!r}")
                if dialog.winfo_exists():
                    dialog.cancel()

        before = len(errors)
        root.after(200, enter)
        app.format_graph()
        root.update()
        assert errors[before:] == [], errors[before:]

    def series(dialog, name):
        names = list(dialog.series_selector.cget("values"))
        dialog.series_selector.current(names.index(name))
        dialog._select_series()

    def pick(combobox, label):
        values = list(combobox.cget("values"))
        assert label in values, (label, values)
        combobox.current(values.index(label))
        combobox.event_generate("<<ComboboxSelected>>")

    def refused(dialog, contains, widget):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False
        message = banner.call_args.args[1]
        assert contains in message, message
        assert dialog.winfo_exists() and dialog.error_widget is widget, (dialog.error_widget, widget)
        dialog.update_idletasks()
        assert widget.winfo_ismapped(), "the field in error is reachable"
        return message

    def fits(dialog, size):
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        assert width <= size[0] and height <= size[1], ("Format Graph exceeds the screen", width, height, size)

    def width_shown(dialog):
        dialog.update_idletasks()
        return bool(dialog._bar_width_widget.grid_info())

    # 1. A synthetic project and an XY graph of the four columns, all points.
    alab = directory / "xy-mixed.alab"
    tools.save_project(alab, {TABLE: tools.Dataset(source())})
    app.import_file(alab)

    def choose(dialog):
        tools.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("Time")
        tools.select_columns(dialog, "Y columns", COLUMNS)

    tick = time.monotonic()
    tools.drive_dialog(tools.AnalysisDialog, choose)
    app.choose_analysis()
    wait()
    report["seconds"]["first graph"] = round(time.monotonic() - tick, 2)
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options["Y columns"] == COLUMNS, run.options
    app.show("graph", index)
    root.update()
    done("XY graph of four columns, default points")

    # 2. Format Graph: two bar series on opposite axes, a step, a line, colors and an invalid width corrected in place.
    def configure(dialog):
        dialog.notebook.select(2)
        fits(dialog, SMALL)
        assert not width_shown(dialog), "no bar series yet"
        series(dialog, "Bars left")
        pick(dialog._draw_widget, "Bars")
        assert width_shown(dialog)
        for key in ("line_style", "width", "marker", "marker_size", "marker_color"):
            assert str(dialog._series_widgets[key].cget("state")) == "disabled", key
        dialog.series_fields["color"].set("#ca5632")
        series(dialog, "Bars right")
        pick(dialog._draw_widget, "Bars")
        pick(dialog._side_widget, "Right")
        dialog.series_fields["color"].set("#317da6")
        series(dialog, "Step dose")
        pick(dialog._draw_widget, "Step")
        assert str(dialog._series_widgets["line_style"].cget("state")) == "readonly"
        assert str(dialog._series_widgets["marker"].cget("state")) == "disabled"
        series(dialog, "Trend")
        pick(dialog._draw_widget, "Line")
        dialog.bar_width.set("0")
        refused(dialog, "bar cluster width", dialog._bar_width_widget)
        series(dialog, "Bars left")
        dialog.bar_width.set("1.2")
        fits(dialog, SMALL)
        shot(dialog, "window-xy-mixed-format-bars.png")

    format_graph(configure)
    run = app.runs[index]
    figure = run.result.figure
    assert run.options["Series style"] == {"Bars left": "Bars", "Bars right": "Bars", "Step dose": "Step",
                                           "Trend": "Line"}, run.options["Series style"]
    assert run.options["Series side"]["Bars right"] == "Right" and run.options[BAR_WIDTH] == 1.2
    (left,), (right,) = bars(figure, 0), bars(figure, 1)
    assert centers(left) == [-0.3, 1.7, 3.7, 4.7, 7.7], centers(left)
    assert centers(right) == [0.3, 1.3, 2.3, 5.3, 8.3], centers(right)
    assert {round(p.get_width(), 9) for p in left.patches + right.patches} == {0.6}
    assert [p.get_height() for p in left.patches] == [2, -3, 4, 0, 9]
    assert left.patches[0].get_facecolor() == to_rgba("#ca5632")
    step = next(line for line in figure.axes[0].lines if line.get_gid() == "xy:1:Step dose")
    assert step.get_drawstyle() == "steps-post" and np.isnan(step.get_ydata()[2])
    assert [t.get_text() for t in figure.axes[0].get_legend().get_texts()] == COLUMNS
    app.show("graph", index)
    root.update()
    shot(root, "window-xy-mixed-graph.png")
    done("Format Graph: Bars on both axes, Step, Line, colors, invalid width refused then 1.2 applied")

    # 3. Scales: a log axis that carries bars is refused on its own control; Cancel leaves the graph as it was.
    def scales(dialog):
        dialog.notebook.select(1)
        dialog.right_scale.set("Log")
        refused(dialog, "linear right Y axis", dialog._right_widgets["Right scale"])
        shot(dialog, "window-xy-mixed-right-log-refused.png")
        dialog.right_scale.set("Linear")
        dialog.inputs["xscale"].set("log")
        refused(dialog, "linear X axis", dialog._axis_widgets["x"]["scale"])
        dialog.inputs["xscale"].set("linear")
        dialog.inputs["yscale"].set("log")
        refused(dialog, "linear left Y axis", dialog._axis_widgets["y"]["scale"])

    before = deepcopy((run.options, run.style))
    format_graph(scales, accept=False)
    assert (app.runs[index].options, app.runs[index].style) == before
    done("log scales refused on X, left Y and right Y while bars use them; Cancel keeps the recipe")

    # 4. Change type and axis: the right bars become a line on a log axis, then bars again on a linear axis.
    def to_line(dialog):
        series(dialog, "Bars right")
        pick(dialog._draw_widget, "Line")
        dialog.right_scale.set("Log")

    format_graph(to_line)
    figure = app.runs[index].result.figure
    assert bars(figure, 1) == [] and figure.axes[1].get_yscale() == "log"
    line = next(line for line in figure.axes[1].lines if line.get_gid() == "xy:1:Bars right")
    assert to_hex(line.get_color()) == "#317da6", "the series keeps its color through the change"
    assert len(bars(figure, 0)[0].patches) == 5 and round(bars(figure, 0)[0].patches[0].get_width(), 9) == 1.2

    def to_bars(dialog):
        series(dialog, "Bars right")
        pick(dialog._draw_widget, "Bars")
        dialog.right_scale.set("Linear")

    format_graph(to_bars)
    figure = app.runs[index].result.figure
    assert centers(bars(figure, 1)[0]) == [0.3, 1.3, 2.3, 5.3, 8.3]
    done("type and axis change: Bars → Line on a log right axis → Bars, color and key kept")

    # 5. Inspector: hide a bar series and cancel, then rename and recolor the left bars and apply.
    app.show("graph", index)
    app.toggle_inspector()
    inspector = app.inspector
    root.update()
    bottom = root.winfo_rooty() + root.winfo_height()
    for button in (inspector.apply_button, inspector.cancel_button):
        assert button.winfo_ismapped() and button.winfo_rooty() + button.winfo_height() <= bottom + 1
    figure = app.runs[index].result.figure
    inspector.select_group("xy:1:Bars right")
    assert "disabled" in inspector.fields["marker"]["widget"].state()
    assert "disabled" not in inspector.fields["visible"]["widget"].state()
    inspector.vars["element:visible"].set(False)
    inspector._now("element:visible")
    assert not any(p.get_visible() for p in bars(figure, 1)[0].patches)
    assert [t.get_text() for t in figure.axes[0].get_legend().get_texts()] == ["Bars left", "Step dose", "Trend"]
    assert centers(bars(figure, 0)[0]) == [-0.3, 1.7, 3.7, 4.7, 7.7], "a hidden series keeps its slot"
    shot(root, "window-xy-mixed-inspector-hidden.png")
    inspector.cancel_button.invoke()
    root.update()
    assert all(p.get_visible() for p in bars(figure, 1)[0].patches)
    app.toggle_inspector()
    inspector = app.inspector
    inspector.select_group("xy:1:Bars left")
    inspector.vars["element:label"].set("Observed $x$")
    inspector._now("element:label")
    inspector.vars["element:color"].set("#624b91")
    inspector._now("element:color")
    inspector.select_group("xy:1:Step dose")
    assert "disabled" not in inspector.fields["line_style"]["widget"].state()
    inspector.vars["element:line_style"].set("dashed")
    inspector._now("element:line_style")
    assert inspector.apply()
    inspector.cancel_button.invoke()
    root.update()
    run = app.runs[index]
    assert run.style["series"]["xy:1:Bars left"] == {"label": "Observed $x$", "color": "#624b91"}, run.style
    assert run.style["series"]["xy:1:Step dose"] == {"line_style": "dashed"}
    shot(root, "window-xy-mixed-inspector-applied.png")
    done("Inspector: hide, Cancel, label and color on bars, line pattern on the step, Apply")

    # 6. Worksheet: exclude a bar value, edit a step value, then repeat an X under the right bars and recover.
    app.show("data", TABLE)
    app.current_grid.active_cell = (3, 1)  # Bars left at Time 4
    app.toggle_exclusion()
    wait()
    app.edit_cell(2, 3, "2.5")  # Step dose at Time 2
    wait()
    run = app.runs[index]
    figure = run.result.figure
    assert centers(bars(figure, 0)[0]) == [-0.3, 1.7, 4.7, 7.7]
    sheet = run.result.tables["Series values"]
    assert sheet.loc[sheet["Y column"] == "Bars left", "X"].tolist() == [0.0, 2.0, 5.0, 8.0]
    step = next(line for line in figure.axes[0].lines if line.get_gid() == "xy:1:Step dose")
    assert float(step.get_ydata()[2]) == 2.5 and step.get_linestyle() == "--"
    assert figure.axes[0].get_legend().get_texts()[0].get_text() == "Observed $x$"
    app.edit_cell(1, 0, "0")  # Time 1 becomes 0: Bars right now repeats X = 0
    wait()
    status = app.status.get()
    assert app.runs[index].result is None, "the graph is not drawn from data it cannot represent"
    assert "repeats X = 0" in status and "Bars right" in status, status
    report["repeated_x_status"] = status
    app.show("graph", index)
    root.update()
    shot(root, "window-xy-mixed-repeated-x.png")
    app.show("data", TABLE)
    app.edit_cell(1, 0, "1")
    wait()
    assert app.runs[index].result is not None
    assert centers(bars(app.runs[index].result.figure, 1)[0]) == [0.3, 1.3, 2.3, 5.3, 8.3]
    done("exclusion and edit recalculate; a repeated X is reported in the status bar, then recovered")

    # 7. Save, reopen with the graph opened first, and compare recipe, style, artists and IDs.
    expected = deepcopy((app.runs[index].options, app.runs[index].style))
    app.path = alab
    assert app.save()
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    wait()
    reopened = app.runs[0]
    assert (reopened.options, reopened.style) == expected, (reopened.options, reopened.style)
    figure = reopened.result.figure
    assert centers(bars(figure, 0)[0]) == [-0.3, 1.7, 4.7, 7.7]
    assert bars(figure, 0)[0].patches[0].get_facecolor() == to_rgba("#624b91")
    index = 0
    done("save and reopen: recipe, style, bars, colors and exclusion survive")

    # 8. Exports: CSV of Series values, PNG, SVG and PDF of the graph.
    app.show("result", index)
    root.update()
    csv_path = out / "xy-mixed-series-values.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    values = pd.read_csv(csv_path, index_col=0)
    assert values.columns.tolist() == ["Source row", "X", "Y column", "Y"], values.columns
    assert values.loc[values["Y column"] == "Bars right", "X"].tolist() == [0.0, 1.0, 2.0, 5.0, 8.0]
    app.show("graph", index)
    root.update()
    paths = {fmt: out / f"xy-mixed.{fmt}" for fmt in ("png", "svg", "pdf")}
    for path in paths.values():
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(path)):
            app.export()
        assert path.stat().st_size > 1000, path
    ids = svg_bar_ids(paths["svg"])
    assert len(ids) == 9 and len(set(ids)) == 9, ids
    assert "xybar:Bars left:0" in ids and "xybar:Bars right:5" in ids, ids
    assert b"/Subtype /Image" not in paths["pdf"].read_bytes()
    report["svg_bar_ids"] = ids
    done("CSV, PNG, SVG and PDF exports; SVG has 9 unique xybar IDs and no image")

    # 9. A two-panel layout with a step-only graph: page preview, PNG and vector SVG.
    app.show("data", TABLE)

    def second(dialog):
        tools.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("Time")
        tools.select_columns(dialog, "Y columns", ["Trend"])

    tools.drive_dialog(tools.AnalysisDialog, second)
    app.choose_analysis()
    wait()
    other = len(app.runs) - 1

    def compose(dialog):
        dialog.name.set("Mixed XY layout")
        dialog.columns.set("2")
        dialog.list.selection_clear(0, "end")
        for position, candidate in enumerate(dialog.runs):
            if app.runs.index(candidate) in {index, other}:
                dialog.list.selection_set(position)
        dialog.add_selected()

    tools.drive_dialog(tools.LayoutDialog, compose)
    app.new_layout()
    root.update()
    layout = len(app.layouts) - 1
    assert len(app.layouts[layout].panels) == 2
    app.show("layout", layout)
    root.update()
    shot(root, "window-xy-mixed-layout.png")
    layout_svg, layout_png = out / "xy-mixed-layout.svg", out / "xy-mixed-layout.png"
    for path in (layout_svg, layout_png):
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(path)):
            app.export()
        assert path.stat().st_size > 1000, path
    layout_ids = [element.get("id") for element in ET.parse(layout_svg).getroot().iter()
                  if "xybar:" in (element.get("id") or "")]
    assert len(layout_ids) == 9 and len(set(layout_ids)) == 9, layout_ids
    done("two-panel layout: page, PNG and vector SVG with the 9 bar IDs")

    # 10. Italian: draw-style names, a decimal comma in the width, an invalid value corrected in the same dialog.
    try:
        i18n.set_language("it")
        app.show("graph", index)
        root.update()

        def italian(dialog):
            dialog.notebook.select(2)
            series(dialog, "Bars left")
            assert "Barre" in dialog._draw_widget.cget("values") and "Gradini" in dialog._draw_widget.cget("values")
            assert dialog.bar_width.get() == "1,2", dialog.bar_width.get()
            dialog.bar_width.set("abc")
            refused(dialog, "larghezza del gruppo di barre", dialog._bar_width_widget)
            dialog.bar_width.set("0,8")
            fits(dialog, SMALL)
            shot(dialog, "window-xy-mixed-format-it.png")

        format_graph(italian)
        assert app.runs[index].options[BAR_WIDTH] == 0.8
        assert centers(bars(app.runs[index].result.figure, 0)[0]) == [-0.2, 1.8, 4.8, 7.8]
        app.show("graph", index)
        root.update()
        shot(root, "window-xy-mixed-graph-it.png")
        app.toggle_inspector()
        app.inspector.select_group("xy:1:Bars right")
        root.update()
        shot(root, "window-xy-mixed-inspector-it.png")
        app.inspector.cancel_button.invoke()
        root.update()
    finally:
        i18n.set_language("en")
    done("Italian Format Graph: Barre/Gradini, '0,8' accepted after an invalid value, Inspector")

    # 11. A 1600 × 1000 window when the screen has room for it.
    if screen[0] >= 1680 and screen[1] >= 1050:
        root.geometry(f"{LARGE[0]}x{LARGE[1]}+0+0")
        root.update()
        for code in ("en", "it"):
            i18n.set_language(code)
            app.show("graph", index)
            root.update()
            shot(root, f"window-xy-mixed-graph-1600-{code}.png")

            def large(dialog, code=code):
                dialog.notebook.select(2)
                series(dialog, "Bars right")
                fits(dialog, LARGE)
                shot(dialog, f"window-xy-mixed-format-1600-{code}.png")

            format_graph(large, accept=False)
        i18n.set_language("en")
        done("1600 × 1000 window: graph and Format Graph in English and Italian")
    else:
        report["skipped"] = "1600 × 1000 window: the screen is smaller than 1680 × 1050"
