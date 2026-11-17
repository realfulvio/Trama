"""Desktop smoke check for XY series formatting in Format Graph and the Inspector.

``tramastat.py --smoke`` calls :func:`check_xy_formatting` with its helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=xy-formatting python tramastat.py --smoke DIR``.
"""
from copy import deepcopy
from unittest.mock import patch

from matplotlib.colors import to_hex
import numpy as np
import pandas as pd

from .graph_dialog import GraphFormatDialog

SCREEN = (1024, 768)
TABLE = "XY formatting study"


def check_xy_formatting(root, app, directory, tools):
    """Drive Format Graph and the Inspector on an XY series graph across all three draw styles."""
    errors = tools.errors
    geometry = root.geometry()
    root.geometry(f"{SCREEN[0]}x{SCREEN[1]}+0+0")
    root.update()
    try:
        _run_xy_formatting_smoke(root, app, directory, tools, errors)
    finally:
        root.geometry(geometry)
        root.update()


def _run_xy_formatting_smoke(root, app, directory, tools, errors):
    source = pd.DataFrame({
        "Time": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Control": [10.0, 12.0, np.nan, 15.0, 18.0],
        "Treated": [9.0, 13.0, 17.0, 21.0, 26.0],
        "Pressure": [100.0, 104.0, 109.0, np.nan, 115.0],
    })
    alab = directory / "xy-series-formatting.alab"
    tools.save_project(alab, {TABLE: tools.Dataset(source)})
    app.import_file(alab)

    def choose_xy(dialog):
        tools.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("Time")
        tools.select_columns(dialog, "Y columns", ["Control", "Treated", "Pressure"])

    tools.drive_dialog(tools.AnalysisDialog, choose_xy)
    app.choose_analysis()
    tools.wait_for_calculation()
    run_index = len(app.runs) - 1
    app.show("graph", run_index)
    root.update()

    def find_dialog(parent):
        for child in parent.winfo_children():
            if isinstance(child, GraphFormatDialog):
                return child
            found = find_dialog(child)
            if found is not None:
                return found
        return None

    def open_format(action, *, accept):
        def enter():
            dialog = find_dialog(root)
            if dialog is None:
                errors.append("GraphFormatDialog did not open")
                return
            try:
                action(dialog)
                if dialog.winfo_exists():
                    dialog.ok() if accept else dialog.cancel()
                if dialog.winfo_exists():
                    errors.append("Format Graph remained open after ok/cancel")
            except Exception as error:
                errors.append(f"Format Graph: {error!r}")
                if dialog.winfo_exists():
                    dialog.cancel()

        before = len(errors)
        root.after(200, enter)
        app.format_graph()
        assert errors[before:] == [], errors[before:]

    def select_series(dialog, name):
        names = list(dialog.series_selector.cget("values"))
        assert name in names, (name, names)
        dialog.series_selector.current(names.index(name))
        dialog._select_series()

    def pick(combobox, label):
        values = list(combobox.cget("values"))
        assert label in values, (label, values)
        combobox.current(values.index(label))
        combobox.event_generate("<<ComboboxSelected>>")

    def check_dialog_fits(dialog):
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        assert width <= SCREEN[0] and height <= SCREEN[1], ("Format Graph exceeds 1024x768", width, height)

    # 1. Open Format Graph, configure Points / Line / Line and points across left and right axes,
    #    test validation error & recovery, and capture the dialog screenshot.
    def configure_all_series(dialog):
        dialog.notebook.select(2)
        dialog.update_idletasks()
        check_dialog_fits(dialog)

        # Series 1: Control -> Points on Left axis; first set line_style/width while in Line and points,
        # then switch back to Points so inactive properties stay saved while disabled.
        select_series(dialog, "Control")
        pick(dialog._draw_widget, "Line and points")
        pick(dialog._series_widgets["line_style"], "dotted")
        dialog.series_fields["width"].set("3.2")
        pick(dialog._draw_widget, "Points")
        assert str(dialog._series_widgets["line_style"].cget("state")) == "disabled"
        assert str(dialog._series_widgets["width"].cget("state")) == "disabled"
        assert str(dialog._series_widgets["marker"].cget("state")) == "readonly"
        dialog.series_fields["color"].set("#cc5500")
        pick(dialog._series_widgets["marker"], "Triangle up")
        dialog.series_fields["marker_size"].set("9.5")
        dialog.series_fields["marker_color"].set("#264653")
        dialog.series_fields["label"].set("Control pts")

        # Series 2: Treated -> Line on Left axis; set marker properties first, then switch to Line.
        select_series(dialog, "Treated")
        pick(dialog._draw_widget, "Points")
        pick(dialog._series_widgets["marker"], "Square")
        dialog.series_fields["marker_size"].set("8.0")
        dialog.series_fields["marker_color"].set("#e9c46a")
        pick(dialog._draw_widget, "Line")
        assert str(dialog._series_widgets["marker"].cget("state")) == "disabled"
        assert str(dialog._series_widgets["marker_size"].cget("state")) == "disabled"
        assert str(dialog._series_widgets["marker_color"].cget("state")) == "disabled"
        assert str(dialog._series_widgets["line_style"].cget("state")) == "readonly"
        dialog.series_fields["color"].set("#2a9d8f")
        pick(dialog._series_widgets["line_style"], "dashed")
        dialog.series_fields["width"].set("2.8")
        dialog.series_fields["label"].set("Treated line")

        # Series 3: Pressure -> Line and points on Right axis; trigger validation error then fix it.
        select_series(dialog, "Pressure")
        pick(dialog._draw_widget, "Line and points")
        pick(dialog._side_widget, "Right")
        dialog.series_fields["color"].set("#6a4c93")
        pick(dialog._series_widgets["line_style"], "dash-dot")
        dialog.series_fields["width"].set("99")  # invalid (> 72)
        pick(dialog._series_widgets["marker"], "Diamond")
        dialog.series_fields["marker_size"].set("7.5")
        dialog.series_fields["marker_color"].set("#f4a261")
        dialog.series_fields["label"].set("Pressure kPa")

        with patch.object(tools.messagebox, "showerror") as shown:
            assert dialog.validate() is False
            assert "0.1 and 72" in shown.call_args.args[1]
        assert dialog.winfo_exists()
        assert dialog.error_widget is dialog._series_widgets["width"]
        dialog.series_fields["width"].set("2.2")
        dialog.right_title.set("kPa")
        dialog.update_idletasks()
        tools.capture(dialog, "window-xy-series-format-dialog.png")

    open_format(configure_all_series, accept=True)

    run = app.runs[run_index]
    left_ax, right_ax = run.result.figure.axes
    ctrl_line, treat_line = left_ax.lines
    press_line, = right_ax.lines
    assert (ctrl_line.get_linestyle(), ctrl_line.get_marker()) == ("None", "^")
    assert (ctrl_line.get_markersize(), to_hex(ctrl_line.get_markerfacecolor())) == (9.5, "#264653")
    assert (treat_line.get_linestyle(), treat_line.get_marker()) == ("--", "None")
    assert treat_line.get_linewidth() == 2.8
    assert (press_line.get_linestyle(), press_line.get_marker()) == ("-.", "D")
    assert (press_line.get_linewidth(), press_line.get_markersize()) == (2.2, 7.5)
    assert [t.get_text() for t in left_ax.get_legend().get_texts()] == [
        "Control pts", "Treated line", "Pressure kPa"
    ]
    # Saved inactive properties are preserved in run.style
    assert run.style["series"]["xy:1:Control"]["line_style"] == "dotted"
    assert run.style["series"]["xy:1:Treated"]["marker"] == "s"

    # 2. Open GraphInspector: check 1024x768 layout, cancel a preview, apply an edit, test section reset.
    app.show("graph", run_index)
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None
    root.update()
    window_bottom = root.winfo_rooty() + root.winfo_height()
    for button in (inspector.apply_button, inspector.cancel_button):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= window_bottom + 1

    # Preview a change and cancel it -> confirmed style and figure revert
    inspector.select_group("xy:1:Control")
    assert "disabled" in inspector.fields["line_style"]["widget"].state()
    assert "disabled" not in inspector.fields["marker"]["widget"].state()
    inspector.vars["element:color"].set("#112233")
    inspector._now("element:color")
    assert to_hex(left_ax.lines[0].get_color()) == "#112233"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert to_hex(left_ax.lines[0].get_color()) == "#cc5500"

    # Reopen Inspector, test reset_section("data") in draft then discard, and apply a real change
    app.toggle_inspector()
    inspector = app.inspector
    inspector.reset_section("data")
    assert "series" not in inspector.draft
    assert (left_ax.lines[0].get_linestyle(), left_ax.lines[0].get_marker()) == ("None", "o")
    inspector.discard()
    assert (left_ax.lines[0].get_linestyle(), left_ax.lines[0].get_marker()) == ("None", "^")

    inspector.select_group("xy:1:Pressure")
    inspector.vars["element:label"].set("Arterial kPa")
    inspector._now("element:label")
    assert inspector.apply()
    inspector.cancel_button.invoke()
    root.update()
    assert run.style["series"]["xy:1:Pressure"]["label"] == "Arterial kPa"
    tools.capture(root, "window-xy-series-formatted-graph.png")

    # 3. Save .alab, reopen, and verify styles and options match
    expected_style = deepcopy(run.style)
    expected_options = deepcopy(run.options)
    app.path = alab
    assert app.save()
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    tools.wait_for_calculation()
    reopened_run = app.runs[0]
    assert reopened_run.style == expected_style
    assert reopened_run.options == expected_options

    # 4. Edit a cell and exclude another; verify recalculation updates points & Series values and keeps style
    app.show("data", TABLE)
    app.edit_cell(0, 1, "11.5")  # Control at Time=0.0 becomes 11.5
    tools.wait_for_calculation()
    app.current_grid.active_cell = (1, 2)  # Treated at Time=1.0 excluded
    app.toggle_exclusion()
    tools.wait_for_calculation()

    updated = app.runs[0]
    sheet = updated.result.tables["Series values"]
    assert float(sheet.loc[sheet["Y column"] == "Control", "Y"].iloc[0]) == 11.5
    assert sheet.loc[sheet["Y column"] == "Treated", "X"].tolist() == [0.0, 2.0, 3.0, 4.0]
    u_left, u_right = updated.result.figure.axes
    assert (u_left.lines[0].get_linestyle(), u_left.lines[0].get_marker()) == ("None", "^")
    assert (u_left.lines[1].get_linestyle(), u_left.lines[1].get_marker()) == ("--", "None")
    assert (u_right.lines[0].get_linestyle(), u_right.lines[0].get_marker()) == ("-.", "D")

    # 5. Use Result as Data on Series values and export SVG + PNG
    app.show("result", 0)
    root.update()
    before_tables = set(app.tables)
    app.use_result_as_data()
    new_tables = set(app.tables) - before_tables
    assert len(new_tables) == 1
    derived_name = next(iter(new_tables))
    assert list(app.tables[derived_name].frame().columns) == ["Source row", "X", "Y column", "Y"]

    app.show("graph", 0)
    svg_path = directory / "xy-formatted.svg"
    png_path = directory / "xy-formatted.png"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(svg_path)):
        app.export()
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(png_path)):
        app.export()
    assert svg_path.stat().st_size > 1000 and png_path.stat().st_size > 1000
    svg_text = svg_path.read_text(encoding="utf-8")
    assert "Control pts" in svg_text and "Arterial kPa" in svg_text
