"""Desktop smoke check for Transpose X and Y, kept apart from tramastat.py so other dialogs can change freely.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=transpose``) calls :func:`check_transpose_xy` with a kit that
carries app, root, directory, capture, pick_method, select_columns, drive_dialog(action) and wait_for_calculation.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .data import Dataset, save_project
from .transpose_xy import (ASCENDING, ORDER, PLOT, REPLICATES, ROW_TITLE, SUMMARY_MEAN, TRANSPOSE_XY, X_TRANSFORM,
                           Y_SETS)

LEGACY = "Transform"
REP, MEAN = ["A [1]", "A [2]"], ["B [Mean]", "B [SD]"]


def _source():
    data = pd.DataFrame({
        "Dose": [10., 20, 30, None, 40, 50, 60],
        "Title": ["first", "second", "first", "blank X", "fourth", "last", "neg"],
        "A [1]": [6., 8, None, 9, 7, None, -5], "A [2]": [8., None, 12, 9, 7, None, -3],
        "B [Mean]": [25., 16, None, 36, 9, 4, 1], "B [SD]": [2., 5, 4, 6, 3, 1, 1]})
    data.attrs.update(table_format="XY with replicates", worksheet_roles={"x": ["Dose"], "y": [REP, MEAN]})
    return data


def check_transpose_xy(kit):
    from tkinter import filedialog, messagebox

    app, directory, wait = kit.app, kit.directory, kit.wait_for_calculation
    path = directory / "transpose-xy.alab"
    title = "Dose response"
    save_project(path, {title: Dataset(_source())})
    app.import_file(path)

    def rejected(dialog, field, text, shot=None):
        with patch.object(messagebox, "showerror") as report:
            assert dialog.validate() is False
        message = report.call_args.args[1]
        assert field in message and text in message, message
        assert dialog.winfo_exists()
        if shot:
            kit.capture(dialog, shot)

    def configure(dialog):
        kit.pick_method(dialog, TRANSPOSE_XY)
        controls = dialog.controls
        assert controls["X"][1].get() == "Dose"
        editor = controls[Y_SETS][1]
        # The XY roles of the table are proposed: replicates A and the mean of B.
        assert editor.values() == [{"name": "A", "mode": REPLICATES, "columns": REP},
                                   {"name": "B", "mode": SUMMARY_MEAN, "columns": ["B [Mean]"]}], editor.values()
        dialog.focus_field(Y_SETS)
        kit.capture(dialog, "window-transpose-sets.png")
        # A set that reuses a column, and a name that collides with the result's X column, stay in the dialog.
        editor.add()
        editor.variables["name"].set("Extra")
        editor.choose_columns(["A [1]"])
        rejected(dialog, "Y sets", "more than one Y set", "window-transpose-error.png")
        editor.variables["name"].set("X")
        editor.choose_columns(["B [SD]"])
        rejected(dialog, "Y sets", "collides")
        editor.remove()
        assert [item["name"] for item in editor.values()] == ["A", "B"]
        controls[ROW_TITLE][1].set("Title")
        # Log10 after the swap fails on the negative mean of A and says so on the transform field.
        controls[X_TRANSFORM][1].set("Log10")
        rejected(dialog, X_TRANSFORM, "strictly positive", "window-transpose-log-error.png")
        controls[X_TRANSFORM][1].set("None")
        controls[ORDER][1].set(ASCENDING)
        controls[PLOT][1].set(True)
        dialog.focus_field(ORDER)
        kit.capture(dialog, "window-transpose-options.png")

    kit.drive_dialog(configure)
    app.choose_analysis()
    wait()
    index = next(i for i, run in enumerate(app.runs) if run.method == TRANSPOSE_XY)
    run = app.runs[index]
    assert run.options[ROW_TITLE] == "Title" and run.options[ORDER] == ASCENDING and run.options[PLOT] is True
    table = run.result.tables["Transposed XY"]
    assert list(table.columns) == ["X", "Row title", "A", "B"]
    np.testing.assert_allclose(table["X"], [-4, 7, 7, 8, 12, 1, 4, 9, 16, 25])
    assert table["Row title"].tolist() == ["neg", "first", "fourth", "second", "first", "neg", "last", "fourth",
                                           "second", "first"]
    assert table["A"].iloc[:5].tolist() == [60, 10, 40, 20, 30] and table["A"].iloc[5:].isna().all()
    sources = run.result.tables["Source rows"]
    assert sources["Source row"].tolist() == [7, 1, 5, 2, 3, 7, 6, 5, 2, 1]
    assert sources["N present"].tolist() == [2, 2, 2, 1, 1, 1, 1, 1, 1, 1]
    assert run.result.figure is not None and len(run.result.figure.axes[0].lines) == 2
    app.show("result", index)
    kit.capture(kit.root, "window-transpose-result.png")
    app.result_tabs.select(1)
    kit.capture(kit.root, "window-transpose-sources.png")
    app.show("graph", index)
    kit.capture(kit.root, "window-transpose-graph.png")

    # Excluding a replicate of the first row leaves the other one: the mean becomes 8 with one value present.
    app.show("data", title)
    app.current_grid.select((0, 2))
    app.toggle_exclusion()
    wait()
    changed = app.runs[index].result
    first = changed.tables["Source rows"].query("Series == 'A' and `Source row` == 1")
    assert first["N present"].tolist() == [1]
    assert 8.0 in changed.tables["Transposed XY"]["X"].tolist()
    # Editing the source recalculates the linked result.
    app.show("data", title)
    app.edit_cell(1, 0, "25")
    wait()
    assert 25.0 in app.runs[index].result.tables["Transposed XY"]["A"].tolist()

    app.show("result", index)
    app.result_tabs.select(0)
    target = directory / "transposed-xy.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
    assert list(exported.columns) == ["X", "Row title", "A", "B"] and len(exported) == 10

    # Save and reopen keep the recipe and the results.
    before = app.runs[index].result.tables["Transposed XY"].copy()
    assert app.save()
    app.import_file(path)
    reopened = next(i for i, item in enumerate(app.runs) if item.method == TRANSPOSE_XY)
    app.open_sheet(("result", reopened))
    wait()
    again = app.runs[reopened]
    assert again.options[Y_SETS][0]["columns"] == REP and again.options[ORDER] == ASCENDING
    pd.testing.assert_frame_equal(again.result.tables["Transposed XY"], before)

    # Use Result as Data gives a usable XY table with the roles of the result.
    app.show("result", reopened)
    app.result_tabs.select(0)
    app.use_result_as_data()
    used = app.selected[1]
    raw = app.tables[used].raw
    assert raw.attrs["worksheet_roles"] == {"x": ["X"], "y": [["A"], ["B"]]}
    assert app.tables[used].table_format.casefold() == "xy"
    assert raw["Row title"].iloc[0] == "neg"
    kit.capture(kit.root, "window-transpose-data.png")
    assert app.save()
    app.import_file(path)
    assert app.tables[used].raw.attrs["worksheet_roles"] == {"x": ["X"], "y": [["A"], ["B"]]}

    # A native XY graph from the transposed table.
    def graph(dialog):
        kit.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("X")
        kit.select_columns(dialog, "Y columns", {"A", "B"})

    app.show("data", used)
    kit.drive_dialog(graph)
    app.choose_analysis()
    wait()
    xy = next(run for run in app.runs if run.method == "XY series" and run.title == used)
    assert len(xy.result.figure.axes[0].lines) == 2
    app.show("graph", app.runs.index(xy))
    kit.capture(kit.root, "window-transpose-xy-graph.png")

    # A recipe of the legacy Transform analysis still opens.
    legacy = directory / "transpose-legacy.alab"
    save_project(legacy, {"Old": Dataset(pd.DataFrame({"Dose": [1., 2, 3]}),
                                         analyses=[(LEGACY, {"Variables": ["Dose"], "Operation": "Square"})])})
    app.import_file(legacy)
    app.open_sheet(("result", 0))
    wait()
    assert app.runs[0].method == LEGACY and app.runs[0].result.tables
