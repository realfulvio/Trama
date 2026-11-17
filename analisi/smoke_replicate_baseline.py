"""GUI smoke for Remove baseline with replicate subcolumns (package 05).

Kept out of tramastat.py so dialog rewrites in parallel branches do not collide.
`kit` carries the smoke helpers: app, root, directory, errors, pick_method,
select_columns, drive_dialog, capture and wait_for_calculation.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .data import Dataset, save_project

METHOD = "Remove baseline and column math"
REF, SIGNAL, WIDE = ["Ref [1]", "Ref [2]"], ["Signal [1]", "Signal [2]"], ["Wide [1]", "Wide [2]", "Wide [3]"]


def check_replicate_baseline(kit):
    from tkinter import filedialog, messagebox

    app, directory = kit.app, kit.directory
    path = directory / "replicate-baseline.alab"
    title = "Replicates"
    data = pd.DataFrame({"X": [0., 1, 2, 3], "Ref [1]": [2., 4, None, 8], "Ref [2]": [4., 6, None, 10],
                         "Signal [1]": [10., 12, 15, 20], "Signal [2]": [14., 16, 19, 22],
                         "Wide [1]": [1., 2, 3, 4], "Wide [2]": [2., 3, 4, 5], "Wide [3]": [3., 4, 5, 6]})
    data.attrs.update(table_format="XY with replicates",
                      worksheet_roles={"x": ["X"], "y": [REF, SIGNAL, WIDE]})
    save_project(path, {title: Dataset(data)})
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
        kit.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert controls["Replicate handling"][1].get() == "Independent columns"
        visible = dialog.processing_visibility()
        assert visible["Baseline column"] and not visible["Baseline subcolumns"]
        controls["X"][1].set("X")
        controls["Replicate handling"][1].set("Matched subcolumns")
        dialog.update()
        visible = dialog.processing_visibility()
        assert visible["Baseline subcolumns"] and not visible["Baseline column"]
        kit.select_columns(dialog, "Baseline subcolumns", set(REF))
        # An incomplete replicate group and groups that cannot be paired keep the dialog open.
        kit.select_columns(dialog, "Data columns", {"Signal [1]"})
        rejected(dialog, "Data columns", "incomplete")
        kit.select_columns(dialog, "Data columns", set(WIDE))
        rejected(dialog, "Baseline subcolumns", "same number of replicates", "window-replicate-baseline-error.png")
        controls["Baseline"][1].set("Linear fit of baseline column vs X")
        rejected(dialog, "Replicate handling", "linear baseline")
        controls["Baseline"][1].set("Baseline column, same row")
        kit.select_columns(dialog, "Data columns", set(SIGNAL))
        dialog.focus_field("Replicate handling")
        kit.capture(dialog, "window-replicate-baseline-options.png")

    kit.drive_dialog(configure)
    app.choose_analysis()
    kit.wait_for_calculation()
    index = len(app.runs) - 1
    run = app.runs[index]
    processed = run.result.tables["Processed data"]
    assert list(processed.columns) == ["X", *SIGNAL]
    np.testing.assert_allclose(processed[SIGNAL], [[8, 10], [8, 10], [np.nan, np.nan], [12, 12]], equal_nan=True)
    app.show("result", index)
    kit.capture(kit.root, "window-replicate-baseline-matched.png")

    # Editing a baseline replicate recalculates; excluding one leaves only its partner blank.
    app.show("data", title)
    app.edit_cell(0, 1, "6")
    kit.wait_for_calculation()
    assert app.runs[index].result.tables["Processed data"]["Signal [1]"].iloc[0] == 4
    app.show("data", title)
    app.current_grid.select((1, 2))
    app.toggle_exclusion()
    kit.wait_for_calculation()
    changed = app.runs[index].result.tables["Processed data"]
    np.testing.assert_allclose(changed.iloc[1, 1:], [8, np.nan], equal_nan=True)

    app.show("result", index)
    target = directory / "replicate-baseline.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = target.read_text(encoding="utf-8-sig")
    assert "Signal [1]" in exported and "Signal [2]" in exported, exported

    assert app.save()
    app.import_file(path)
    index = next(i for i, item in enumerate(app.runs) if item.method == METHOD and item.title == title)
    app.open_sheet(("result", index))
    kit.wait_for_calculation()
    reopened = app.runs[index]
    assert reopened.options["Replicate handling"] == "Matched subcolumns"
    assert reopened.options["Baseline subcolumns"] == REF
    pd.testing.assert_frame_equal(reopened.result.tables["Processed data"], changed)

    app.show("result", index)
    app.use_result_as_data()
    used = app.selected[1]
    assert app.tables[used].raw.attrs["worksheet_roles"] == {"x": ["X"], "y": [SIGNAL]}
    assert app.tables[used].table_format == "XY with replicates"
    kit.capture(kit.root, "window-replicate-baseline-data.png")
    assert app.save()
    app.import_file(path)
    assert app.tables[used].raw.attrs["worksheet_roles"] == {"x": ["X"], "y": [SIGNAL]}

    # The produced table feeds a second replicate analysis: one mean per dataset.
    def means(dialog):
        kit.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        dialog.controls["Replicate handling"][1].set("Mean vs baseline mean")
        dialog.controls["Baseline"][1].set("Mean of first K rows")
        kit.select_columns(dialog, "Data columns", set(SIGNAL))

    app.show("data", used)
    kit.drive_dialog(means)
    app.choose_analysis()
    kit.wait_for_calculation()
    summary = app.runs[-1].result.tables["Processed data"]
    assert list(summary.columns) == ["X", "Signal"], summary.columns
    np.testing.assert_allclose(summary["Signal"], [0, 1, np.nan, 5], equal_nan=True)
