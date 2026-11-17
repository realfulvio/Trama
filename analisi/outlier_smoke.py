"""Desktop smoke check for Identify outliers, kept apart from tramastat.py so other dialogs can change freely.

``tramastat.py --smoke`` calls :func:`check_outlier_screening` with its own helpers.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .data import Dataset, save_project
from .outlier_screening import ALPHA, ITERATIVE, METHOD, OUTLIERS, Q, ROUT

LEGACY = "Outlier test (Grubbs)"
FIXTURE = {
    "Clean": [-5, -4, -3, -2, -1, 0, 0, 1, 2, 3, 4, 5],
    "Spikes": [-60, -4, -3, -2, -1, 0, 0, 1, 2, 3, 4, 60],
    "Grubbs chain": [1, 1.1, .8, 1.2, .9, 1.05, .95, 25, 200, None, None, None],
    "Constant": [5] * 12,
    "Sparse": [1, 2] + [None] * 10,
}


def check_outlier_screening(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "outliers.alab"
    title = "Outlier screening"
    data = pd.DataFrame(FIXTURE)
    save_project(path, {title: Dataset(data)})
    app.import_file(path)

    def choose(dialog):
        tools.pick_method(dialog, OUTLIERS)
        assert dialog.controls[METHOD][1].get() == ROUT
        assert dialog.outlier_fields() == {Q: True, ALPHA: False}
        assert dialog.field_rows[Q][1].winfo_manager() and not dialog.field_rows[ALPHA][1].winfo_manager()
        assert dialog.controls[Q][1].get() == "1.0"
        tools.select_columns(dialog, "Variables", set(FIXTURE))
        # A bad Q keeps the dialog open on its field.
        for text in ("0", "100", "-1", "abc", "nan"):
            dialog.controls[Q][1].set(text)
            with patch.object(tools.messagebox, "showerror") as report:
                assert dialog.validate() is False, text
            assert "Q (%)" in report.call_args.args[1], report.call_args
            if text == "100":
                tools.capture(dialog, "window-outliers-q-error.png")
        # Switching to Grubbs shows Alpha in place of Q, and a bad Alpha is reported on its field.
        dialog.controls[METHOD][1].set(ITERATIVE)
        dialog.update()
        assert dialog.outlier_fields() == {Q: False, ALPHA: True}
        assert dialog.field_rows[ALPHA][1].winfo_manager() and not dialog.field_rows[Q][1].winfo_manager()
        dialog.controls[ALPHA][1].set("1,5")
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False
        assert "Alpha" in report.call_args.args[1], report.call_args
        tools.capture(dialog, "window-outliers-alpha.png")
        dialog.controls[METHOD][1].set(ROUT)
        dialog.update()
        dialog.controls[Q][1].set("1")
        tools.capture(dialog, "window-outliers-options.png")

    tools.drive_dialog(tools.AnalysisDialog, choose)
    app.choose_analysis()
    wait()
    index = next(i for i, run in enumerate(app.runs) if run.method == OUTLIERS)
    run = app.runs[index]
    assert run.options[METHOD] == ROUT and run.options[Q] == 1.0 and ALPHA not in run.options
    flags = run.result.tables["Outliers"]
    spikes = flags[flags["Variable"] == "Spikes"]
    assert spikes["Source row"].tolist() == [1, 12] and spikes["Value"].tolist() == [-60, 60]
    summary = run.result.tables["Summary"].set_index("Variable")
    assert summary.loc["Constant", "Status"] == "Constant"
    assert summary.loc["Sparse", "Status"] == "Insufficient observations"
    assert abs(summary.loc["Spikes", "RSDR"] - 3.8287636363636364) < 1e-9
    app.show("result", index)
    tools.capture(root, "window-outliers-results.png")
    app.result_tabs.select(1)
    tools.capture(root, "window-outliers-summary.png")

    # CSV export of the Outliers sheet.
    target = directory / "outliers.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.result_tabs.select(0)
        app.export()
    exported = pd.read_csv(target)
    assert exported[exported["Variable"] == "Spikes"]["Source row"].tolist() == [1, 12]

    # Excluding a spike in the source recalculates and the excluded value is not flagged again.
    app.show("data", title)
    app.current_grid.select((0, 1))
    app.toggle_exclusion()
    wait()
    run = app.runs[index]
    rows = run.result.tables["Outliers"]
    assert 1 not in rows[rows["Variable"] == "Spikes"]["Source row"].tolist()
    assert run.result.tables["Summary"].set_index("Variable").loc["Spikes", "N"] == 11
    assert app.tables[title].excluded == {(0, 1)}
    app.show("data", title)
    app.current_grid.select((0, 1))
    app.toggle_exclusion()
    wait()

    # Edit the analysis: iterative Grubbs on the chain flags rows 9 and 8 in this order.
    def iterative(dialog):
        dialog.controls[METHOD][1].set(ITERATIVE)
        dialog.update()
        tools.select_columns(dialog, "Variables", {"Grubbs chain"})
        dialog.controls[ALPHA][1].set("0,05")

    app.show("result", index)
    tools.drive_dialog(tools.AnalysisDialog, iterative)
    app.edit_analysis()
    wait()
    run = app.runs[index]
    assert run.options[METHOD] == ITERATIVE and run.options[ALPHA] == .05 and Q not in run.options
    chain = run.result.tables["Outliers"]
    assert chain["Source row"].tolist() == [9, 8] and chain["Step"].tolist() == [1, 2], chain
    tools.capture(root, "window-outliers-iterative.png")

    # A changed value in the source recalculates the linked result.
    app.show("data", title)
    app.edit_cell(7, 2, "1.15")
    wait()
    assert app.runs[index].result.tables["Outliers"]["Source row"].tolist() == [9]
    app.show("data", title)
    app.edit_cell(7, 2, "25")
    wait()

    # Save and reopen keep the recipe and the results.
    assert app.save()
    app.import_file(app.path)
    reopened = next(i for i, run in enumerate(app.runs) if run.method == OUTLIERS)
    app.open_sheet(("result", reopened))
    wait()
    again = app.runs[reopened]
    assert again.options[METHOD] == ITERATIVE
    assert again.result.tables["Outliers"]["Source row"].tolist() == [9, 8]

    # Processed data becomes an ordinary worksheet with the flagged cells blank.
    app.show("result", reopened)
    app.result_tabs.select(2)
    app.use_result_as_data()
    processed = app.tables["Processed data"].raw
    assert len(processed) == 12 and processed["Grubbs chain"].isna().sum() == 5
    assert processed["Spikes"].tolist() == FIXTURE["Spikes"]

    # The Grubbs recipe saved by 0.48.0 still opens on its own sheet.
    legacy = directory / "outliers-legacy.alab"
    save_project(legacy, {"Old": Dataset(data, analyses=[(LEGACY, {"Response": "Grubbs chain", "Alpha": .05})])})
    app.import_file(legacy)
    app.open_sheet(("result", 0))
    wait()
    old = app.runs[0].result
    assert app.runs[0].method == LEGACY and list(old.tables) == ["Grubbs' test"]
    report = old.tables["Grubbs' test"]["Value"]
    assert report["Candidate row"] == "8" and bool(report["Flagged"]) and report["N"] == 9
    assert np.isclose(report["G"], 2.647199, atol=1e-6)
