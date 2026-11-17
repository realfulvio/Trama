"""Desktop smoke check for inverse intervals, 4PL Y from X and replicate counts (0.53).

``tramastat.py --smoke`` calls :func:`check_calibration_intervals` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=calibration-intervals python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import nonlinear_calibration as cal
from .data import Dataset, save_project
from .workbench import analyse

METHOD = "Interpolate a standard curve"
LINEAR = "Inverse standards"
SPLIT = "Disconnected standards"
STIM = "4PL standards"
DECAY = "Decay standards"
LINEAR_FRAME = pd.DataFrame({
    "X": [0., 1, 2, 3, 4, 5, 6, 7], "Y": [3.6, 4.7, 7.4, 8.2, 11.3, 13.1, 14.55, 17.35],
    "Query Y": [9., 9., 3.5, 16.9, 40., None, None, None], "K": [1, 4, 1, 1, 2, None, None, None],
    # 1.5 sits on a used query row, so choosing this column must keep the dialog open.
    "Bad K": [1., 1.5, 1., 1., 1., None, None, None]})
SPLIT_FRAME = pd.DataFrame({
    "X": [-12., -5, -3, -2, 1, 9, 11, 13], "Y": [-2., -3, 6, 1, 8, -1, 7, 6],
    "Query Y": [5.72, None, None, None, None, None, None, None]})
STIM_FRAME = pd.DataFrame({
    "Row title": [f"Sample {i}" for i in range(1, 12)],
    "X": [0.0, 0.002, 0.005565118804414252, 0.015485273653622542, 0.04308869380063767, 0.1198968500637882,
          0.33362010744001186, 0.9283177667225556, 2.5830993300297656, 7.187627327609253, 20.0],
    "Y": [1.66, 1.488825253191901, 1.7143188253726587, 1.7623083596162068, 2.003765813676237, 3.378195740236635,
          5.574583093878689, 8.365784152280451, 9.493488554010991, 10.020018004424037, 10.001035945257762],
    "Query X": [0.4, 0.4, 0.0, 20.0, -1.0, None, None, None, None, None, None],
    "K": [1, 4, 1, 1, 2, None, None, None, None, None, None]})
DECAY_FRAME = pd.DataFrame({
    "X": [0., .4, .8, 1.3, 2., 3., 4.5, 6., 8.],
    "Y": [12.12, 9.520515858035663, 8.085205479701944, 6.335573582107391, 4.515317930340125,
          3.5227407158651354, 2.416646919127301, 2.3524191144580437, 1.9951656442076078],
    "Query X": [2.5, 2.5, 0., -1., None, None, None, None, None], "K": [1, 4, 2, 1, None, None, None, None, None]})
# Recipes as 0.53.0 saved them: no replicate count field, Uncertainty only for Y from X.
LEGACY = {
    LINEAR: {"X": "X", "Y": "Y", "Unknown responses": "Query Y", "Curve": "Linear"},
    STIM: {"X": "X", "Y": "Y", "Direction": "X from Y", "Unknown responses": "Query Y", "Curve": "Nonlinear",
           "Model": "Stimulation (variable slope)"},
    DECAY: {"X": "X", "Y": "Y", "Direction": "Y from X", "Unknown X": "Query X", "Curve": "Nonlinear",
            "Model": "One-phase decay", "Uncertainty": "Mean response", "Confidence level (%)": 90.0},
}
INTERVAL_FIELDS = ["Response", "Interpolated X", "Outside calibration", "X lower", "X upper", cal.INTERVAL_STATUS,
                   cal.REPLICATES]


def check_calibration_intervals(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "calibration-intervals.alab"
    frames = {LINEAR: LINEAR_FRAME, SPLIT: SPLIT_FRAME, DECAY: DECAY_FRAME,
              STIM: STIM_FRAME.assign(**{"Query Y": [2.5, 5., 9., 12.] + [None] * 7})}
    datasets = {}
    for title, frame in frames.items():
        datasets[title] = Dataset(frame.copy())
        if title in LEGACY:
            datasets[title].analyses.append((METHOD, dict(LEGACY[title])))
    save_project(path, datasets)
    app.import_file(path)
    positions = {run.title: position for position, run in enumerate(app.runs)}
    assert set(positions) == set(LEGACY), positions
    # 0.53.0 recipes: same options and the tables that the engine gives for them.
    for title, options in LEGACY.items():
        app.open_sheet(("result", positions[title]))
        wait()
        run = app.runs[positions[title]]
        assert run.options == options, (run.options, options)
        expected = analyse(METHOD, datasets[title].frame(mask_excluded=True), options)
        assert list(run.result.tables) == list(expected.tables), list(run.result.tables)
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], table)
        assert cal.REPLICATES not in run.result.tables[next(iter(expected.tables))].columns

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            tools.capture(dialog, shot)

    def fields(dialog, values):
        for name, value in values:
            dialog.controls[name][1].set(value)
            dialog.update()

    # X from Y on the line, with the visibility of every interval field in both directions.
    app.show("data", LINEAR)

    def inverse(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), ("Unknown responses", "Query Y"), ("Curve", "Linear")))
        assert dialog.controls[cal.DIRECTION][1].get() == "X from Y"
        assert placed(dialog, cal.UNCERTAINTY) and not placed(dialog, cal.LEVEL) and not placed(dialog, cal.COUNT)
        fields(dialog, ((cal.UNCERTAINTY, "Mean response"),))
        assert placed(dialog, cal.LEVEL) and not placed(dialog, cal.COUNT)
        fields(dialog, ((cal.UNCERTAINTY, "Prediction"),))
        assert placed(dialog, cal.LEVEL) and placed(dialog, cal.COUNT)
        fields(dialog, (("Curve", "Nonlinear"),))
        # The default model is One-phase decay, so Mean response and Prediction stay available.
        assert dialog.controls["Model"][1].get() == "One-phase decay"
        assert placed(dialog, cal.UNCERTAINTY) and placed(dialog, cal.LEVEL) and placed(dialog, cal.COUNT)
        assert dialog.inverse_note.winfo_manager()
        fields(dialog, (("Model", "One-phase association"),))
        assert not placed(dialog, cal.UNCERTAINTY) and not placed(dialog, cal.LEVEL) and not placed(dialog, cal.COUNT)
        assert not dialog.inverse_note.winfo_manager()
        fields(dialog, (("Model", "One-phase decay"),))
        assert placed(dialog, cal.UNCERTAINTY) and dialog.inverse_note.winfo_manager()
        fields(dialog, ((cal.DIRECTION, "Y from X"),))
        assert not dialog.inverse_note.winfo_manager()
        assert placed(dialog, cal.UNCERTAINTY) and placed(dialog, cal.COUNT) and placed(dialog, cal.UNKNOWN_X)
        fields(dialog, ((cal.DIRECTION, "X from Y"), ("Curve", "Linear")))
        assert placed(dialog, cal.COUNT) and not placed(dialog, cal.UNKNOWN_X)
        dialog.controls[cal.LEVEL][1].set("150")
        rejected(dialog, cal.LEVEL)
        dialog.controls[cal.LEVEL][1].set("95")
        dialog.controls[cal.COUNT][1].set("Bad K")
        rejected(dialog, cal.COUNT, "window-calibration-count-error.png")
        dialog.controls[cal.COUNT][1].set("K")
        dialog.update()
        dialog.fields.select(dialog.field_rows[cal.COUNT][1].master)
        tools.capture(dialog, "window-calibration-inverse-options.png")

    tools.drive_dialog(tools.AnalysisDialog, inverse)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options[cal.UNCERTAINTY] == "Prediction" and run.options[cal.COUNT] == "K", run.options
    assert cal.UNKNOWN_X not in run.options
    table = run.result.tables[cal.INTERPOLATED]
    assert list(table.columns) == INTERVAL_FIELDS, list(table.columns)
    assert table[cal.INTERVAL_STATUS].tolist() == ["Complete", "Complete", "Clipped low", "Clipped high",
                                                   "Outside calibration"], table[cal.INTERVAL_STATUS].tolist()
    assert table[cal.REPLICATES].tolist() == [1, 4, 1, 1, 2]
    np.testing.assert_allclose(table[["X lower", "X upper"]].iloc[0].astype(float),
                               [2.282134411373394, 3.6681359551697676], rtol=1e-6)
    np.testing.assert_allclose(table[["X lower", "X upper"]].iloc[1].astype(float),
                               [2.572741404364653, 3.3775289621785083], rtol=1e-6)
    app.show("result", index)
    app.result_tabs.select(0)
    tools.capture(root, "window-calibration-inverse-intervals.png")

    # Edit a standard and a count, then exclude a query: its row and its count leave the calculation.
    columns = list(app.tables[LINEAR].raw.columns)
    first = float(table.at[0, "X lower"])
    app.show("data", LINEAR)
    app.edit_cell(3, columns.index("Y"), "9.2")
    wait()
    moved = app.runs[index].result.tables[cal.INTERPOLATED]
    assert abs(float(moved.at[0, "X lower"]) - first) > 1e-4
    width = float(moved.at[1, "X upper"] - moved.at[1, "X lower"])
    app.show("data", LINEAR)
    app.edit_cell(1, columns.index("K"), "9")
    wait()
    narrowed = app.runs[index].result.tables[cal.INTERPOLATED]
    assert narrowed.at[1, cal.REPLICATES] == 9
    assert float(narrowed.at[1, "X upper"] - narrowed.at[1, "X lower"]) < width
    app.show("data", LINEAR)
    app.current_grid.select((0, columns.index("Query Y")))
    app.toggle_exclusion()
    wait()
    app.show("data", LINEAR)
    app.edit_cell(0, columns.index("K"), "")
    wait()
    excluded = app.runs[index].result.tables[cal.INTERPOLATED]
    assert list(excluded.index) == [1, 2, 3, 4], list(excluded.index)
    assert excluded[cal.REPLICATES].tolist() == [9, 1, 1, 2]

    # Two components on the disconnected fixture, then Use Result as Data on that sheet.
    app.show("data", SPLIT)

    def split(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), ("Unknown responses", "Query Y"), ("Curve", "Linear"),
                        (cal.UNCERTAINTY, "Mean response"), (cal.LEVEL, "95")))
        assert not placed(dialog, cal.COUNT)

    tools.drive_dialog(tools.AnalysisDialog, split)
    app.choose_analysis()
    wait()
    split_index = len(app.runs) - 1
    tables = app.runs[split_index].result.tables
    assert tables[cal.INTERPOLATED][cal.INTERVAL_STATUS].tolist() == [cal.DISCONNECTED]
    components = tables[cal.COMPONENTS]
    assert list(components.columns) == ["Source row", "Component", "X lower", "X upper"]
    np.testing.assert_allclose(components[["X lower", "X upper"]].to_numpy(dtype=float),
                               [[-12.0, -7.4218207984856726], [-2.14977339324102, 13.0]], rtol=1e-8)
    app.show("result", split_index)
    app.result_tabs.select(list(tables).index(cal.COMPONENTS))
    root.update()
    tools.capture(root, "window-calibration-inverse-components.png")
    before = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1, added
    copied = app.tables[added.pop()].raw
    assert list(copied.columns) == ["Source row", "Component", "X lower", "X upper"], list(copied.columns)
    csv = directory / "inverse-components.csv"
    app.show("result", split_index)
    app.result_tabs.select(list(tables).index(cal.COMPONENTS))
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    assert "Component" in csv.read_text(encoding="utf-8-sig")

    # Y from X on a concentration 4PL with replicate counts.
    app.show("data", STIM)

    def four_pl(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), (cal.DIRECTION, "Y from X"), (cal.UNKNOWN_X, "Query X"),
                        ("Curve", "Nonlinear")))
        values = tuple(dialog.field_rows["Model"][1]["values"])
        assert all(model in values for model in cal.FORWARD_MODELS), values
        fields(dialog, (("Model", "Inhibition (variable slope)"), (cal.UNCERTAINTY, "Prediction")))
        fields(dialog, (("Model", "Stimulation (variable slope)"), (cal.LEVEL, "90"), (cal.COUNT, "K")))
        assert dialog.field_rows["Model"][0].cget("text") == "Model (concentration X)"

    tools.drive_dialog(tools.AnalysisDialog, four_pl)
    app.choose_analysis()
    wait()
    stim_index = len(app.runs) - 1
    result = app.runs[stim_index].result
    predictions = result.tables[cal.PREDICTIONS]
    assert predictions.columns[-1] == cal.REPLICATES
    assert predictions["Status"].tolist() == ["In range"] * 4 + [cal.OUTSIDE_CALIBRATION]
    assert predictions["Row title"].tolist() == [f"Sample {i}" for i in range(1, 6)]
    np.testing.assert_allclose(predictions[["Predicted Y", "Y lower", "Y upper"]].iloc[2].astype(float),
                               [1.6076549958278028, 1.3680293522994649, 1.8472806393561407], rtol=1e-4)
    bands = result.tables[cal.BANDS]
    assert (bands["X"].iloc[0], bands["X"].iloc[-1]) == (0.0, 20.0)
    axis = result.figure.axes[0]
    labels = [text.get_text() for text in axis.get_legend().get_texts()]
    assert "90% prediction band (k = 1)" in labels and "Stimulation (variable slope)" in labels, labels
    assert axis.get_xscale() == "linear" and axis.get_xlim()[0] <= 0.0
    app.show("graph", stim_index)
    tools.capture(root, "window-calibration-4pl-graph.png")
    for suffix in ("png", "svg"):
        target = directory / f"calibration-4pl.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", stim_index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "calibration-4pl.svg").read_bytes()
    app.show("result", stim_index)
    app.result_tabs.select(0)
    tools.capture(root, "window-calibration-4pl-predictions.png")
    csv = directory / "calibration-4pl-predictions.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = csv.read_text(encoding="utf-8-sig")
    assert "Replicate count" in exported and "Outside calibration" in exported, exported[:200]
    before = set(app.tables)
    app.show("result", stim_index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1 and "Replicate count" in app.tables[added.pop()].raw.columns

    # Y from X on the decay with k, then without: the 0.53.0 columns and legend come back.
    app.show("data", DECAY)

    def decay(dialog):
        tools.pick_method(dialog, METHOD)
        fields(dialog, (("X", "X"), ("Y", "Y"), (cal.DIRECTION, "Y from X"), (cal.UNKNOWN_X, "Query X"),
                        ("Curve", "Nonlinear"), ("Model", "One-phase decay"), (cal.UNCERTAINTY, "Prediction"),
                        (cal.LEVEL, "90"), (cal.COUNT, "K")))

    tools.drive_dialog(tools.AnalysisDialog, decay)
    app.choose_analysis()
    wait()
    decay_index = len(app.runs) - 1
    assert app.runs[decay_index].result.tables[cal.PREDICTIONS].columns[-1] == cal.REPLICATES

    def drop_count(dialog):
        assert dialog.controls[cal.COUNT][1].get() == "K"
        dialog.controls[cal.COUNT][1].set("")
        dialog.update()

    app.show("result", decay_index)
    tools.drive_dialog(tools.AnalysisDialog, drop_count)
    app.edit_analysis()
    wait()
    plain = app.runs[decay_index].result
    assert plain.tables[cal.PREDICTIONS].columns.tolist() == ["Source row", "X", "Predicted Y", "Status", "Y lower",
                                                            "Y upper"]
    labels = [text.get_text() for text in plain.figure.axes[0].get_legend().get_texts()]
    assert "90% prediction band" in labels, labels

    # Save and reopen: every recipe keeps its options and tables. Runs come back grouped by data table.
    def recipes():
        found = {}
        for position, item in enumerate(app.runs):
            if item.method == METHOD:
                found.setdefault(item.title, []).append(position)
        return found

    saved = {title: [(dict(app.runs[position].options),
                      {name: table.copy() for name, table in app.runs[position].result.tables.items()})
                     for position in positions]
             for title, positions in recipes().items()}
    app.path = path
    assert app.save()
    app.import_file(path)
    reopened = recipes()
    assert {title: len(items) for title, items in reopened.items()} == {
        title: len(items) for title, items in saved.items()}, reopened
    for title, positions in reopened.items():
        for position, (options, tables) in zip(positions, saved[title], strict=True):
            app.open_sheet(("result", position))
            wait()
            assert app.runs[position].options == options, (title, app.runs[position].options, options)
            assert list(app.runs[position].result.tables) == list(tables)
            for name, table in tables.items():
                pd.testing.assert_frame_equal(app.runs[position].result.tables[name], table)
