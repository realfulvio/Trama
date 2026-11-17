"""GUI smoke for Cox predicted survival and residuals, kept apart from the main smoke list.

``tramastat.smoke`` passes its helpers in ``ctx``; set TRAMASTAT_SMOKE_ONLY=cox to run this check alone.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .cox_outputs import (CENSOR_VALUE, DEVIANCE_GRAPH, DIAGNOSTICS, EVENT_VALUE, GRAPH, GRAPH_TERM, METHOD,
                          PREDICT, PROFILES, SCHOENFELD)

TIMES = [1, 2, 2, 3, 4, 4, 5, 6, 7, 8, 8, 9]
DIED = [1, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0]
ARMS = list("ABABAABABAAB")
EFRON_BETA = -0.580338684863295
EFRON_HAZARD = [0.10205598051370167, 0.21571115087954087, 0.5151515129205786, 0.757904278450546,
                1.0784769454472904, 1.4691463887398932]


def check_cox_outputs(ctx):
    app, root, directory = ctx.app, ctx.root, ctx.directory
    title = "Cox survival"
    data = pd.DataFrame({"Months": np.array(TIMES, dtype=float),
                         "Status": ["Died" if died else "Alive" for died in DIED], "Arm": ARMS})
    path = directory / "cox-outputs.alab"
    ctx.save_project(path, {title: ctx.Dataset(data)})
    app.import_file(path)

    def configure(dialog):
        ctx.pick_method(dialog, METHOD)
        dialog.controls["Time"][1].set("Months")
        dialog.controls["Event"][1].set("Status")
        ctx.select_columns(dialog, "Predictors", {"Arm"})
        ctx.select_columns(dialog, "Categorical predictors", {"Arm"})
        dialog.update_cox_terms()
        assert dialog.controls[EVENT_VALUE][1].get() == "1" and dialog.controls[CENSOR_VALUE][1].get() == "0"
        assert not dialog.field_rows[PROFILES][1].grid_info() and not dialog.field_rows[GRAPH_TERM][1].grid_info()
        # Numeric defaults on a text status column: the dialog stays open on the Event field.
        with patch.object(ctx.messagebox, "showerror") as shown:
            assert dialog.validate() is False
        message = shown.call_args.args[1]
        assert "'Died'" in message and "neither the event value nor the censor value" in message, message
        assert dialog.fields.select() == str(dialog.field_rows["Event"][1].master)
        ctx.capture(dialog, "window-cox-status-error.png")
        dialog.controls[EVENT_VALUE][1].set("Died")
        dialog.controls[CENSOR_VALUE][1].set("Alive")
        dialog.controls[PREDICT][1].set(True)
        assert dialog.field_rows[PROFILES][1].grid_info()
        editor = dialog.controls[PROFILES][1]
        # Predict survival without profiles names the editor.
        with patch.object(ctx.messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert "Profiles" in shown.call_args.args[1], shown.call_args
        for label, arm in (("Arm A", "A"), ("Arm B", "B")):
            editor.label.set(label)
            editor.inputs["Arm"].set(arm)
            assert editor.add()
        assert editor.values() == [{"Label": "Arm A", "Values": {"Arm": "A"}},
                                   {"Label": "Arm B", "Values": {"Arm": "B"}}]
        dialog.focus_field(PROFILES)
        ctx.capture(dialog, "window-cox-profiles.png")
        dialog.controls[DIAGNOSTICS][1].set(True)
        dialog.controls[SCHOENFELD][1].set(True)
        dialog.controls[GRAPH][1].set("Schoenfeld vs time")
        root.update()
        assert dialog.field_rows[GRAPH_TERM][1].grid_info()
        assert list(dialog.field_rows[GRAPH_TERM][1].cget("values")) == ["Arm [B]"]
        assert dialog.controls[GRAPH_TERM][1].get() == "Arm [B]"
        dialog.controls[GRAPH][1].set("Automatic")
        dialog.focus_field(DIAGNOSTICS)
        ctx.capture(dialog, "window-cox-diagnostics-options.png")
        assert dialog.validate() is True
        dialog.result = None

    ctx.drive_dialog(ctx.AnalysisDialog, configure)
    app.choose_analysis()
    ctx.wait()
    run = app.runs[0]
    assert run.options[EVENT_VALUE] == "Died" and run.options[PREDICT] is True
    tables = run.result.tables
    assert abs(tables["Coefficients"].loc["Arm [B]", "Estimate"] - EFRON_BETA) < 1e-7
    assert list(tables) == ["Coefficients", "Model", "Reference levels", "Baseline survival", "Predicted survival",
                            "Cox residuals", "Schoenfeld residuals"], list(tables)
    np.testing.assert_allclose(tables["Baseline survival"]["Baseline cumulative hazard"], EFRON_HAZARD, rtol=1e-8)
    predicted = tables["Predicted survival"]
    assert predicted["Profile"].tolist() == ["Arm A"] * 6 + ["Arm B"] * 6
    np.testing.assert_allclose(predicted["Survival"][6:], np.exp(-np.array(EFRON_HAZARD) * np.exp(EFRON_BETA)),
                               rtol=1e-8)
    axes = run.result.figure.axes[0]
    assert [line.get_label() for line in axes.lines] == ["Arm A", "Arm B"]

    app.show("result", 0)
    names = list(tables)
    app.result_tabs.select(names.index("Predicted survival"))
    ctx.capture(root, "window-cox-predicted.png")
    app.result_tabs.select(names.index("Cox residuals"))
    ctx.capture(root, "window-cox-residuals.png")
    target = directory / "cox-residuals.csv"
    with patch.object(ctx.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = pd.read_csv(target, index_col=0)
    assert exported["Source row"].tolist() == list(range(1, 13)), exported
    np.testing.assert_allclose(exported["Martingale residual"].sum(), 0, atol=1e-10)
    app.result_tabs.select(names.index("Schoenfeld residuals"))
    ctx.capture(root, "window-cox-schoenfeld.png")
    app.show("graph", 0)
    ctx.capture(root, "window-cox-curves.png")
    for suffix in ("png", "svg"):
        target = directory / f"cox-curves.{suffix}"
        with patch.object(ctx.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg " in (directory / "cox-curves.svg").read_bytes()

    # A status edit and an excluded time recalculate the baseline and keep the source rows.
    app.show("data", title)
    app.edit_cell(11, 1, "Died")
    ctx.wait()
    baseline = app.runs[0].result.tables["Baseline survival"]
    assert baseline["Time"].tolist() == [1, 2, 4, 6, 7, 8, 9], baseline["Time"].tolist()
    app.show("data", title)
    app.current_grid.select((6, 0))
    app.toggle_exclusion()
    ctx.wait()
    rows = app.runs[0].result.tables["Cox residuals"]
    assert rows["Source row"].tolist() == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12], rows["Source row"].tolist()
    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("result", 0))
    ctx.wait()
    reopened = app.runs[0]
    assert reopened.options[PROFILES] == [{"Label": "Arm A", "Values": {"Arm": "A"}},
                                          {"Label": "Arm B", "Values": {"Arm": "B"}}], reopened.options[PROFILES]
    pd.testing.assert_frame_equal(reopened.result.tables["Cox residuals"], rows)

    # The predicted curves become ordinary worksheet data.
    app.show("result", 0)
    app.result_tabs.select(list(reopened.result.tables).index("Predicted survival"))
    app.use_result_as_data()
    sheet = app.tables["Predicted survival"].raw
    assert sheet["Profile"].tolist()[:2] == ["Arm A", "Arm A"] and len(sheet) == 14, sheet

    # Changing the graph only changes the figure; changing the profiles only changes the curves.
    def deviance(dialog):
        assert dialog.controls[EVENT_VALUE][1].get() == "Died"
        assert len(dialog.controls[PROFILES][1].values()) == 2
        dialog.controls[GRAPH][1].set(DEVIANCE_GRAPH)
        editor = dialog.controls[PROFILES][1]
        editor.listbox.selection_set(1)
        editor.remove()

    before = app.runs[0].result.tables
    ctx.drive_dialog(ctx.AnalysisDialog, deviance)
    app.show("result", 0)
    app.edit_analysis()
    ctx.wait()
    after = app.runs[0].result
    assert after.figure.axes[0].get_ylabel() == "Deviance residual"
    assert after.tables["Predicted survival"]["Profile"].unique().tolist() == ["Arm A"]
    for name in ("Coefficients", "Baseline survival", "Cox residuals", "Schoenfeld residuals"):
        pd.testing.assert_frame_equal(after.tables[name], before[name])
    app.show("graph", 0)
    ctx.capture(root, "window-cox-deviance.png")

    # A recipe saved before the status codes keeps its three sheets and no graph.
    legacy = directory / "cox-legacy.alab"
    numeric = data.assign(Status=DIED)
    recipe = {"Time": "Months", "Event": "Status", "Predictors": ["Arm"], "Categorical predictors": ["Arm"],
              "Ties": "Efron"}
    ctx.save_project(legacy, {"Old Cox": ctx.Dataset(numeric, analyses=[(METHOD, recipe)])})
    app.import_file(legacy)
    app.open_sheet(("result", 0))
    ctx.wait()
    old = app.runs[0].result
    assert list(old.tables) == ["Coefficients", "Model", "Reference levels"] and old.figure is None, list(old.tables)
    assert abs(old.tables["Coefficients"].loc["Arm [B]", "Estimate"] - EFRON_BETA) < 1e-7
