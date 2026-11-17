"""Desktop smoke check for Plot a function, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_plot_function` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=plot-function python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import plot_function as pf
from .data import Dataset, save_project

DOSES = "Function doses"


def check_plot_function(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert field in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            tools.capture(dialog, shot)
        return message

    def select(editor, *indices):
        editor.tree.selection_set([str(i) for i in indices])
        editor.show_selection()

    def set_value(editor, parameter, value, *indices):
        select(editor, *indices)
        editor.parameter.set(parameter)
        editor.value.set(value)
        editor.apply()

    # A new project has no table: Tools → Plot a function still opens and creates its own table.
    app.new_project()
    assert app.active_data is None and not app.tables

    def lines(dialog):
        assert dialog.method == pf.PLOT_FUNCTION
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Function", "Curves", "Output"]
        assert dialog.controls[pf.MODEL][1].get() == pf.DEFAULT_MODEL
        assert dialog.controls[pf.X_SOURCE][1].get() == pf.LINEAR
        assert placed(dialog, pf.SEGMENTS) and not placed(dialog, pf.X_COLUMN)
        dialog.controls[pf.X_SOURCE][1].set(pf.WORKSHEET)
        dialog.update()
        assert placed(dialog, pf.X_COLUMN) and not placed(dialog, pf.X_MIN) and not placed(dialog, pf.SEGMENTS)
        rejected(dialog, pf.X_COLUMN)
        dialog.controls[pf.X_SOURCE][1].set(pf.LINEAR)
        dialog.update()
        tools.capture(dialog, "window-function-options.png")
        editor = dialog.controls[pf.CURVES][1]
        assert [curve["name"] for curve in editor.values()] == ["A", "B"]
        # Duplicate A, rename the copy, then make a name clash and a bad value, each corrected in place.
        select(editor, 0)
        editor.duplicate()
        assert [curve["name"] for curve in editor.values()] == ["A", "B", "A copy"]
        assert editor.values()[2]["parameters"] == editor.values()[0]["parameters"]
        editor.name.set("b")
        editor.rename()
        dialog.fields.select(1)
        message = rejected(dialog, pf.CURVES, "window-function-name-error.png")
        assert "already used" in message, message
        editor.name.set("Twin")
        editor.rename()
        set_value(editor, "Slope", "abc", 2)
        assert "Slope" in rejected(dialog, pf.CURVES)
        set_value(editor, "Slope", "1,5", 1, 2)
        assert [curve["parameters"]["Slope"] for curve in editor.values()] == [1., 1.5, 1.5]
        set_value(editor, "Intercept", "2", 2)
        dialog.controls[pf.SEGMENTS][1].set("4.5")
        rejected(dialog, pf.SEGMENTS)
        dialog.controls[pf.SEGMENTS][1].set("20")
        dialog.controls[pf.X_MIN][1].set("-2")
        dialog.controls[pf.X_MAX][1].set("2")
        dialog.controls[pf.FIRST][1].set(True)
        dialog.controls[pf.INTEGRAL][1].set(True)
        select(editor, 0, 1, 2)
        dialog.fields.select(1)
        dialog.update()
        tools.capture(dialog, "window-function-curves.png")

    tools.drive_dialog(tools.AnalysisDialog, lines)
    app.plot_function()
    wait()
    host = app.active_data
    assert host == "Function plot", host
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.method == pf.PLOT_FUNCTION and run.title == host
    assert [curve["name"] for curve in run.options[pf.CURVES]] == ["A", "B", "Twin"]
    assert pf.X_COLUMN not in run.options
    values = run.result.tables[pf.VALUES]
    assert list(values.columns) == ["X", "A", "B", "Twin"] and len(values) == 21
    assert set(run.result.tables) == {pf.VALUES, pf.PARAMETERS, pf.SETTINGS, pf.FIRST, pf.INTEGRAL}
    np.testing.assert_allclose(run.result.tables[pf.FIRST]["Twin"], 1.5)
    app.show("graph", index)
    tools.capture(root, "window-function-graph.png")
    legend = [text.get_text() for text in run.result.figure.axes[0].get_legend().get_texts()]
    assert legend == ["A", "B", "Twin"], legend
    for suffix in ("png", "svg"):
        target = directory / f"function-lines.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "function-lines.svg").read_bytes()
    app.show("result", index)
    for sheet, name in ((pf.VALUES, "function-values.csv"), (pf.FIRST, "function-first-derivative.csv"),
                        (pf.INTEGRAL, "function-integral.csv")):
        app.result_tabs.select(list(run.result.tables).index(sheet))
        if sheet == pf.VALUES:
            tools.capture(root, "window-function-values.png")
        target = directory / name
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, encoding="utf-8-sig")
        # The export keeps the row index first, as for every result sheet.
        assert list(exported.columns)[-4:] == ["X", "A", "B", "Twin"], (name, list(exported.columns))
        assert len(exported) == 21, name

    # Use Result as Data copies Function values into an editable table.
    app.show("result", index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    copied = app.tables[app.active_data].frame()
    assert list(copied.columns) == ["X", "A", "B", "Twin"] and len(copied) == 21

    # Save and reopen; then change a parameter, save and reopen again with the same values each time.
    path = directory / "plot-function.alab"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(path)):
        assert app.save()

    def reopened():
        app.import_file(path)
        position = next(i for i, item in enumerate(app.runs) if item.method == pf.PLOT_FUNCTION)
        app.open_sheet(("result", position))
        wait()
        return position, app.runs[position]

    position, again = reopened()
    pd.testing.assert_frame_equal(again.result.tables[pf.VALUES], values)
    assert again.options == run.options

    def steeper(dialog):
        editor = dialog.controls[pf.CURVES][1]
        assert [curve["name"] for curve in editor.values()] == ["A", "B", "Twin"]
        set_value(editor, "Slope", "4", 0)

    app.show("result", position)
    tools.drive_dialog(tools.AnalysisDialog, steeper)
    app.edit_analysis()
    wait()
    changed = app.runs[position].result.tables[pf.VALUES]
    np.testing.assert_allclose(changed["A"], 4 * changed["X"])
    assert app.save()
    position, last = reopened()
    pd.testing.assert_frame_equal(last.result.tables[pf.VALUES], changed)
    assert last.options[pf.CURVES][0]["parameters"]["Slope"] == 4.

    # Worksheet X: values keep their order, blank cells drop, and an edit or an exclusion recalculates.
    source = directory / "function-doses.alab"
    save_project(source, {DOSES: Dataset(pd.DataFrame({"Dose": [-2., -.5, None, .25, 1.75, 5.],
                                                       "Note": ["a", "b", "blank", "c", "d", "e"]}))})
    app.import_file(source)
    app.show("data", DOSES)

    def worksheet(dialog):
        tools.pick_method(dialog, pf.PLOT_FUNCTION)
        dialog.controls[pf.X_SOURCE][1].set(pf.WORKSHEET)
        dialog.controls[pf.X_COLUMN][1].set("Dose")
        dialog.controls[pf.SECOND][1].set(True)
        dialog.controls[pf.MODEL][1].set("Polynomial (order 2)")
        dialog.update()
        editor = dialog.controls[pf.CURVES][1]
        assert all(not curve["parameters"] for curve in editor.values())
        assert "missing" in editor.note.cget("text")
        rejected(dialog, pf.CURVES)
        for key, value in (("B0", "1"), ("B1", "-2"), ("B2", "3")):
            set_value(editor, key, value, 0, 1)
        editor.tree.selection_set("1")
        editor.remove()
        dialog.fields.select(0)
        dialog.update()
        tools.capture(dialog, "window-function-worksheet.png")

    tools.drive_dialog(tools.AnalysisDialog, worksheet)
    app.choose_analysis()
    wait()
    sheet_index = len(app.runs) - 1
    table = app.runs[sheet_index].result.tables
    assert table[pf.VALUES]["X"].tolist() == [-2., -.5, .25, 1.75, 5.]
    np.testing.assert_allclose(table[pf.SECOND]["A"], 6., atol=1e-9)
    columns = list(app.tables[DOSES].raw.columns)
    app.edit_cell(5, columns.index("Dose"), "6")
    wait()
    assert app.runs[sheet_index].result.tables[pf.VALUES]["X"].tolist()[-1] == 6.
    app.show("data", DOSES)
    app.current_grid.select((1, columns.index("Dose")))
    app.toggle_exclusion()
    wait()
    assert app.runs[sheet_index].result.tables[pf.VALUES]["X"].tolist() == [-2., .25, 1.75, 6.]
    app.show("result", sheet_index)
    tools.capture(root, "window-function-recalculated.png")
    target = directory / "function-second-derivative.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.result_tabs.select(list(app.runs[sheet_index].result.tables).index(pf.SECOND))
        app.export()
    assert pd.read_csv(target, encoding="utf-8-sig")["X"].tolist() == [-2., .25, 1.75, 6.]
