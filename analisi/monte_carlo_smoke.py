"""Desktop smoke check for Monte Carlo study, kept apart from tramastat.py so other dialogs can change freely.

``tramastat.py --smoke`` calls :func:`check_monte_carlo_study` with its own helpers.
"""
from concurrent.futures import Future
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import monte_carlo as mc
from .data import Dataset, save_project

TITLE = "Monte Carlo inputs"
FIXTURE = {"X": [2., -1., None, 4., 2., 0.], "Label": ["first", "second", "blank", "fourth", "duplicate", "last"]}
WELCH_VALUES = {mc.REPLICATES: "2000", mc.SEED: "42", mc.ALPHA: "0,05", mc.LEVEL: "95", mc.N_A: "10", mc.N_B: "10",
                mc.MEAN_A: "0", mc.MEAN_B: "0", mc.SD_A: "1", mc.SD_B: "1", mc.NULL: "0"}


def check_monte_carlo_study(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "monte-carlo.alab"
    save_project(path, {TITLE: Dataset(pd.DataFrame(FIXTURE))})
    app.import_file(path)

    def fill(dialog, values):
        for name, value in values.items():
            dialog.controls[name][1].set(value)
        dialog.update()

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert field in report.call_args.args[1], report.call_args
        if shot:
            tools.capture(dialog, shot)
        return report.call_args.args[1]

    def shown(dialog):
        return {name for name, visible in dialog.monte_carlo_fields().items() if visible}

    # Welch study under H0: the dialog shows only the fields of the chosen design and rejects bad values on their field.
    def welch(dialog):
        tools.pick_method(dialog, mc.MONTE_CARLO)
        assert dialog.fields.tab(0, "text") == "Study" and dialog.fields.tab(1, "text") == "Design"
        assert dialog.controls[mc.STUDY][1].get() == mc.WELCH
        assert shown(dialog) == set(mc.DESIGN_FIELDS[mc.WELCH])
        assert not dialog.field_rows[mc.P_A][1].winfo_manager()
        dialog.controls[mc.STUDY][1].set(mc.PEARSON)
        dialog.update()
        assert shown(dialog) == set(mc.DESIGN_FIELDS[mc.PEARSON])
        dialog.fields.select(1)
        tools.capture(dialog, "window-monte-carlo-pearson-design.png")
        dialog.controls[mc.STUDY][1].set(mc.OLS)
        dialog.update()
        assert shown(dialog) == set(mc.DESIGN_FIELDS[mc.OLS]) - {mc.X_COLUMN}
        dialog.controls[mc.X_SOURCE][1].set(mc.WORKSHEET)
        dialog.update()
        assert shown(dialog) == set(mc.DESIGN_FIELDS[mc.OLS]) - {mc.N, mc.X_MIN, mc.X_MAX}
        tools.capture(dialog, "window-monte-carlo-ols-worksheet.png")
        dialog.controls[mc.STUDY][1].set(mc.WELCH)
        dialog.update()
        dialog.fields.select(0)
        fill(dialog, {**WELCH_VALUES, mc.REPLICATES: "10000", mc.N_A: "150", mc.N_B: "100"})
        message = rejected(dialog, mc.REPLICATES, "window-monte-carlo-budget-error.png")
        assert "2,000,000" in message, message
        fill(dialog, WELCH_VALUES)
        for field, value in ((mc.SEED, "-1"), (mc.SEED, "18446744073709551616"), (mc.LEVEL, "100"),
                             (mc.ALPHA, "1"), (mc.N_A, "1"), (mc.SD_B, "-2"), (mc.REPLICATES, "12.5")):
            dialog.controls[field][1].set(value)
            rejected(dialog, field)
            fill(dialog, WELCH_VALUES)
        dialog.controls[mc.SEED][1].set(str(2**64 - 1))
        assert dialog.validate() is True
        assert dialog.result[1][mc.SEED] == 2**64 - 1
        dialog.controls[mc.SEED][1].set("42")
        dialog.controls[mc.GRAPH][1].set(mc.GRAPH_ESTIMATES)
        dialog.update()
        tools.capture(dialog, "window-monte-carlo-study.png")

    tools.drive_dialog(tools.AnalysisDialog, welch)
    app.show("data", TITLE)
    app.choose_analysis()
    wait()
    index = next(i for i, run in enumerate(app.runs) if run.method == mc.MONTE_CARLO)
    run = app.runs[index]
    assert run.options[mc.STUDY] == mc.WELCH and run.options[mc.SEED] == 42 and mc.P_A not in run.options
    assert set(run.options) == set(mc.COMMON) | set(mc.DESIGN_FIELDS[mc.WELCH]), run.options
    replicates = run.result.tables[mc.REPLICATE_SHEET]
    summary = run.result.tables[mc.SUMMARY_SHEET].iloc[0]
    assert len(replicates) == 2000 and summary["Valid"] == 2000
    assert .025 <= summary["Rejection rate"] <= .075, summary["Rejection rate"]
    first = replicates.copy()
    app.show("result", index)
    tools.capture(root, "window-monte-carlo-replicates.png")
    app.result_tabs.select(1)
    tools.capture(root, "window-monte-carlo-summary.png")
    app.result_tabs.select(2)
    tools.capture(root, "window-monte-carlo-settings.png")
    target = directory / "monte-carlo-summary.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.result_tabs.select(1)
        app.export()
    exported = pd.read_csv(target)
    assert exported["Requested"].tolist() == [2000] and "Coverage Wilson high" in exported
    assert ("graph", index) in [ref for _, refs, *_ in app.sheet_sections() for _, ref in refs]
    app.open_graph_view(index)
    tools.capture(root, "window-monte-carlo-estimates.png")
    assert app.graph_format_problem(app.runs[index]) is None
    for suffix in (".svg", ".png"):
        image = directory / f"monte-carlo-estimates{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(image)):
            app.export()
        assert image.stat().st_size > 1000, image

    # A second study with the same seed and generation settings sees the same random draws.
    def same_seed(dialog):
        tools.pick_method(dialog, mc.MONTE_CARLO)
        fill(dialog, {**WELCH_VALUES, mc.NULL: "0,5"})
        dialog.controls[mc.GRAPH][1].set(mc.GRAPH_P)

    tools.drive_dialog(tools.AnalysisDialog, same_seed)
    app.show("data", TITLE)
    app.choose_analysis()
    wait()
    twin = len(app.runs) - 1
    assert app.runs[twin].options[mc.NULL] == .5
    other = app.runs[twin].result.tables[mc.REPLICATE_SHEET]
    np.testing.assert_array_equal(other["Estimate"].to_numpy(float), first["Estimate"].to_numpy(float))
    assert not np.array_equal(other["p"].to_numpy(float), first["p"].to_numpy(float))
    app.open_graph_view(twin)
    tools.capture(root, "window-monte-carlo-p-values.png")

    # Change Parameters with more replicates and the same seed repeats the study and extends the identical prefix.
    def extend(dialog):
        assert dialog.controls[mc.SEED][1].get() == "42"
        dialog.controls[mc.REPLICATES][1].set("2500")

    app.show("result", index)
    tools.drive_dialog(tools.AnalysisDialog, extend)
    app.edit_analysis()
    wait()
    longer = app.runs[index].result.tables[mc.REPLICATE_SHEET]
    assert len(longer) == 2500
    pd.testing.assert_frame_equal(longer.iloc[:2000], first)

    # Rendezvous after actual worker progress. Spawned workers do not inherit a
    # monkeypatch of simulate_block and can otherwise finish before the first Tk poll.
    report_progress = tools.CalculationControl.report

    def pause_after_progress(control, done, total):
        report_progress(control, done, total)
        if 0 < done < total and not control.cancel.wait(timeout=30):
            raise AssertionError("The GUI did not cancel after the worker reported progress.")

    def wait_for_progress():
        deadline = time.monotonic() + 20
        while not (app.calculation and app.calculation.progress()[0] > 0 and "replicates" in app.status.get()):
            assert time.monotonic() < deadline, "no progress"
            root.update()
            time.sleep(.02)
        root.update()

    def large(dialog):
        dialog.controls[mc.REPLICATES][1].set("10000")
        dialog.controls[mc.N_A][1].set("100")
        dialog.controls[mc.N_B][1].set("100")

    count = len(app.runs)
    with patch.object(tools.CalculationControl, "report", pause_after_progress):
        # Recalculating an existing study: the last completed tables, graph and parameters stay.
        app.show("result", index)
        tools.drive_dialog(tools.AnalysisDialog, large)
        app.edit_analysis()
        wait_for_progress()
        assert app.cancel_button.winfo_manager(), "Cancel calculation is not shown"
        assert "of 10,000 replicates" in app.status.get(), app.status.get()
        tools.capture(root, "window-monte-carlo-progress.png")
        app.cancel_calculation()
        wait()
        assert not app.cancel_button.winfo_manager()
        assert "cancelled" in app.status.get() and "kept" in app.status.get(), app.status.get()
        tools.capture(root, "window-monte-carlo-cancelled.png")
        kept = app.runs[index]
        assert kept.options[mc.REPLICATES] == 2500 and kept.options[mc.N_A] == 10
        assert kept.result.tables[mc.REPLICATE_SHEET] is longer
        assert len(app.runs) == count

        # A new study that is cancelled adds no recipe.
        def new_large(dialog):
            tools.pick_method(dialog, mc.MONTE_CARLO)
            fill(dialog, WELCH_VALUES)
            large(dialog)

        tools.drive_dialog(tools.AnalysisDialog, new_large)
        app.show("data", TITLE)
        app.choose_analysis()
        wait_for_progress()
        app.cancel_calculation()
        wait()
        assert len(app.runs) == count and len(app.tables[TITLE].analyses) == count
        assert "No study was added" in app.status.get(), app.status.get()

    # The next calculation is unaffected by the cancelled one.
    app.recalculate(index)
    wait()
    pd.testing.assert_frame_equal(app.runs[index].result.tables[mc.REPLICATE_SHEET], longer)

    # The worker can finish while its result is still waiting for Tk's polling callback.
    def completed(function, *args):
        future = Future()
        future.set_result(function(*args))
        return future

    kept = app.runs[index].result
    with patch.object(app.worker, "submit", completed):
        app.recalculate(index)
    app.cancel_calculation()
    wait()
    assert app.runs[index].result is kept and "cancelled" in app.status.get(), app.status.get()

    # OLS with worksheet X: blank X is ignored; editing and excluding an X recalculate the linked study.
    def ols(dialog):
        tools.pick_method(dialog, mc.MONTE_CARLO)
        dialog.controls[mc.STUDY][1].set(mc.OLS)
        dialog.update()
        dialog.controls[mc.X_SOURCE][1].set(mc.WORKSHEET)
        dialog.update()
        fill(dialog, {mc.X_COLUMN: "Label", mc.REPLICATES: "9", mc.SEED: str(2**64 - 1), mc.INTERCEPT: "2",
                      mc.SLOPE: "-1,1", mc.SD: "2", mc.NULL: "-0,3", mc.LEVEL: "80"})
        rejected(dialog, mc.X_COLUMN, "window-monte-carlo-x-text-error.png")
        dialog.controls[mc.X_COLUMN][1].set("X")

    tools.drive_dialog(tools.AnalysisDialog, ols)
    app.show("data", TITLE)
    app.choose_analysis()
    wait()
    ols_index = len(app.runs) - 1
    ols_run = app.runs[ols_index]
    assert mc.N not in ols_run.options and ols_run.options[mc.X_COLUMN] == "X"
    settings = dict(ols_run.result.tables[mc.SETTINGS_SHEET].itertuples(index=False, name=None))
    assert settings["Effective N"] == 5 and settings["X values ignored"] == 1, settings
    ols_first = ols_run.result.tables[mc.REPLICATE_SHEET]
    app.show("result", ols_index)
    app.result_tabs.select(2)
    tools.capture(root, "window-monte-carlo-ols-settings.png")
    app.show("data", TITLE)
    with patch.object(app.worker, "submit", completed):
        app.edit_cell(0, 0, "3")
    app.cancel_calculation()
    wait()
    assert app.runs[ols_index].result is None and "cancelled" in app.status.get(), app.status.get()
    app.recalculate(ols_index)
    wait()
    edited = app.runs[ols_index].result.tables[mc.REPLICATE_SHEET]
    assert not np.allclose(edited["Estimate"].to_numpy(float), ols_first["Estimate"].to_numpy(float))
    app.show("data", TITLE)
    app.current_grid.select((3, 0))
    app.toggle_exclusion()
    wait()
    settings = dict(app.runs[ols_index].result.tables[mc.SETTINGS_SHEET].itertuples(index=False, name=None))
    assert settings["Effective N"] == 4 and settings["X values ignored"] == 2, settings
    app.show("data", TITLE)
    app.current_grid.select((3, 0))
    app.toggle_exclusion()
    wait()
    app.show("data", TITLE)
    app.edit_cell(0, 0, "2")
    wait()
    pd.testing.assert_frame_equal(app.runs[ols_index].result.tables[mc.REPLICATE_SHEET], ols_first)

    # Pearson 2x2 with zero margins: Undefined rows keep their place and the graph explains missing values.
    def pearson(dialog):
        tools.pick_method(dialog, mc.MONTE_CARLO)
        dialog.controls[mc.STUDY][1].set(mc.PEARSON)
        dialog.update()
        fill(dialog, {mc.REPLICATES: "4", mc.SEED: "1", mc.N_A: "3", mc.N_B: "5", mc.P_A: "0", mc.P_B: "0"})
        dialog.controls[mc.GRAPH][1].set(mc.GRAPH_P)

    tools.drive_dialog(tools.AnalysisDialog, pearson)
    app.show("data", TITLE)
    app.choose_analysis()
    wait()
    undefined = len(app.runs) - 1
    table = app.runs[undefined].result.tables[mc.REPLICATE_SHEET]
    assert (table["Status"] == mc.UNDEFINED).all() and table["Reason"].str.len().gt(0).all()
    app.show("result", undefined)
    tools.capture(root, "window-monte-carlo-undefined.png")
    app.open_graph_view(undefined)
    tools.capture(root, "window-monte-carlo-undefined-graph.png")

    # Save and reopen: recipes come back and recalculate the same replicates.
    assert app.save()
    app.import_file(app.path)
    reopened = [i for i, run in enumerate(app.runs) if run.method == mc.MONTE_CARLO]
    assert len(reopened) == 4, reopened
    app.open_sheet(("result", reopened[0]))
    wait()
    pd.testing.assert_frame_equal(app.runs[reopened[0]].result.tables[mc.REPLICATE_SHEET], longer)
    app.open_sheet(("result", reopened[2]))
    wait()
    assert app.runs[reopened[2]].options[mc.SEED] == 2**64 - 1
    pd.testing.assert_frame_equal(app.runs[reopened[2]].result.tables[mc.REPLICATE_SHEET], ols_first)

    # Use Result as Data turns the replicates into an ordinary worksheet.
    app.show("result", reopened[0])
    app.result_tabs.select(0)
    app.use_result_as_data()
    sheet = app.tables[mc.REPLICATE_SHEET].raw
    assert len(sheet) == 2500 and list(sheet.columns) == mc.ROW_COLUMNS

    # Simulate data keeps its 0.49 recipe and its tables.
    simulate = directory / "simulate-legacy.alab"
    options = {"Distribution": "Normal", "N": 5, "Seed": 42, "Mean": 0., "SD": 1., "X minimum": 0., "X maximum": 1.,
               "Intercept": 0., "Slope": 1., "Success probability A": .5, "Success probability B": .5}
    save_project(simulate, {"Old": Dataset(pd.DataFrame({"x": [1.]}), analyses=[("Simulate data", options)])})
    app.import_file(simulate)
    app.open_sheet(("result", 0))
    wait()
    values = app.runs[0].result.tables["Simulated data"]["Value"].to_numpy(float)
    np.testing.assert_allclose(values, np.random.default_rng(42).normal(0, 1, 5))
