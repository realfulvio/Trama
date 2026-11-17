"""Desktop smoke check for Y from X on a standard curve, kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_calibration_prediction` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=calibration-prediction python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import nonlinear_calibration as cal
from .data import Dataset, save_project

METHOD = "Interpolate a standard curve"
LINEAR = "Linear standards"
DECAY = "Decay standards"
LEGACY = {"X": "X", "Y": "Y", "Unknown responses": "Unknown", "Curve": "Linear"}
LINEAR_FRAME = pd.DataFrame({
    "Row title": [f"Sample {i}" for i in range(1, 9)],
    "X": [0., 1, 2, 3, 4, 5, 6, 7], "Y": [3.6, 4.7, 7.4, 8.2, 11.3, 13.1, 14.55, 17.35],
    "Query X": [3., 3., 0., -1., None, None, None, None],
    "Unknown": [5., 9., 20., None, None, None, None, None]})
DECAY_FRAME = pd.DataFrame({
    "X": [0., .4, .8, 1.3, 2., 3., 4.5, 6., 8.],
    "Y": [12.12, 9.520515858035663, 8.085205479701944, 6.335573582107391, 4.515317930340125,
          3.5227407158651354, 2.416646919127301, 2.3524191144580437, 1.9951656442076078],
    "Query X": [2.5, 2.5, 0., -1., None, None, None, None, None]})
FIELDS = ["Source row", "Row title", "X", "Predicted Y", "Status", "Y lower", "Y upper"]


def check_calibration_prediction(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "calibration-prediction.alab"
    legacy = Dataset(LINEAR_FRAME.copy())
    legacy.analyses.append((METHOD, dict(LEGACY)))
    save_project(path, {LINEAR: legacy, DECAY: Dataset(DECAY_FRAME.copy())})
    app.import_file(path)
    base = len(app.runs) - 1
    # A 0.52.0 inverse recipe keeps its sheets and options.
    app.open_sheet(("result", base))
    wait()
    old = app.runs[base]
    assert old.method == METHOD and cal.DIRECTION not in old.options
    assert list(old.result.tables) == ["Interpolated values", "Linear calibration"], list(old.result.tables)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        if shot:
            tools.capture(dialog, shot)

    app.show("data", LINEAR)

    def linear(dialog):
        tools.pick_method(dialog, METHOD)
        assert dialog.controls[cal.DIRECTION][1].get() == "X from Y"
        assert placed(dialog, "Unknown responses") and not placed(dialog, cal.UNKNOWN_X)
        # Since 0.53 the inverse line offers intervals too; with None the level stays hidden.
        assert dialog.controls[cal.UNCERTAINTY][1].get() == "None"
        assert placed(dialog, cal.UNCERTAINTY) == (dialog.controls["Curve"][1].get() == "Linear")
        assert not placed(dialog, cal.LEVEL) and not placed(dialog, cal.COUNT)
        for name, value in (("X", "X"), ("Y", "Y"), (cal.DIRECTION, "Y from X"), ("Curve", "Linear")):
            dialog.controls[name][1].set(value)
        dialog.update()
        assert placed(dialog, cal.UNKNOWN_X) and not placed(dialog, "Unknown responses")
        assert placed(dialog, cal.UNCERTAINTY) and not placed(dialog, cal.LEVEL)
        dialog.controls[cal.UNKNOWN_X][1].set("Query X")
        dialog.controls[cal.UNCERTAINTY][1].set("Prediction")
        dialog.update()
        assert placed(dialog, cal.LEVEL)
        for bad in ("150", "0", "abc"):
            dialog.controls[cal.LEVEL][1].set(bad)
            rejected(dialog, cal.LEVEL, "window-calibration-level-error.png" if bad == "150" else None)
            assert dialog.fields.select() == str(dialog.field_rows[cal.LEVEL][1].master)
        dialog.controls[cal.LEVEL][1].set("95")
        dialog.controls["Curve"][1].set("Nonlinear")
        # Since 0.53 the variable-slope 4PL models predict too; One-phase association still does not.
        dialog.controls["Model"][1].set("One-phase association")
        rejected(dialog, "Model")
        dialog.controls["Curve"][1].set("Linear")
        dialog.update()
        dialog.fields.select(dialog.field_rows[cal.LEVEL][1].master)
        tools.capture(dialog, "window-calibration-prediction-options.png")

    tools.drive_dialog(tools.AnalysisDialog, linear)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options[cal.DIRECTION] == "Y from X" and "Unknown responses" not in run.options
    table = run.result.tables[cal.PREDICTIONS]
    assert list(table.columns) == FIELDS, list(table.columns)
    assert table["Status"].tolist() == ["In range"] * 3 + ["Outside calibration"]
    assert table["Row title"].tolist() == ["Sample 1", "Sample 2", "Sample 3", "Sample 4"]
    assert np.allclose(table[["Predicted Y", "Y lower", "Y upper"]].iloc[0].astype(float),
                       [9.038690476190474, 7.678844691470537, 10.398536260910411], rtol=1e-6)
    bands = run.result.tables[cal.BANDS]
    assert (bands["X"].iloc[0], bands["X"].iloc[-1]) == (0.0, 7.0)
    labels = [text.get_text() for text in run.result.figure.axes[0].get_legend().get_texts()]
    assert "95% prediction band" in labels and "Predictions" in labels, labels
    app.show("graph", index)
    tools.capture(root, "window-calibration-prediction-graph.png")
    for suffix in ("png", "svg"):
        target = directory / f"calibration-prediction.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "calibration-prediction.svg").read_bytes()
    app.show("result", index)
    app.result_tabs.select(0)
    tools.capture(root, "window-calibration-predictions.png")
    csv = directory / "calibrated-predictions.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = csv.read_text(encoding="utf-8-sig")
    assert "Outside calibration" in exported and "Predicted Y" in exported, exported[:200]

    # Exclude the X = 7 standard: the domain and the bands shrink, then a Y edit recalculates.
    app.show("data", LINEAR)
    columns = list(app.tables[LINEAR].raw.columns)
    app.current_grid.select((7, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    assert app.runs[index].result.tables[cal.BANDS]["X"].iloc[-1] == 6.0
    before = float(app.runs[index].result.tables[cal.PREDICTIONS].at[0, "Predicted Y"])
    app.show("data", LINEAR)
    app.edit_cell(3, columns.index("Y"), "9.2")
    wait()
    after = app.runs[index].result.tables[cal.PREDICTIONS]
    assert abs(float(after.at[0, "Predicted Y"]) - before) > 1e-3
    app.show("result", index)
    tools.capture(root, "window-calibration-recalculated.png")

    # One-phase decay with a 90% mean response band.
    app.show("data", DECAY)

    def decay(dialog):
        tools.pick_method(dialog, METHOD)
        for name, value in (("X", "X"), ("Y", "Y"), (cal.DIRECTION, "Y from X"), (cal.UNKNOWN_X, "Query X"),
                            ("Curve", "Nonlinear"), ("Model", "One-phase decay"), (cal.UNCERTAINTY, "Mean response"),
                            (cal.LEVEL, "90")):
            dialog.controls[name][1].set(value)
        dialog.update()

    tools.drive_dialog(tools.AnalysisDialog, decay)
    app.choose_analysis()
    wait()
    decay_index = len(app.runs) - 1
    decay_run = app.runs[decay_index].result
    found = decay_run.tables[cal.PREDICTIONS]
    assert np.allclose(found[["Predicted Y", "Y lower", "Y upper"]].iloc[0].astype(float),
                       [3.936126072269264, 3.7834006427542186, 4.08885150178431], rtol=1e-5)
    assert {"Calibration parameters", "Fit diagnostics", cal.BANDS} <= set(decay_run.tables)

    saved = {position: (dict(item.options), item.result.tables[cal.PREDICTIONS].copy())
             for position, item in enumerate(app.runs) if item.options.get(cal.DIRECTION) == "Y from X"}
    assert app.save()
    app.import_file(app.path)
    for position in range(len(app.runs)):
        app.open_sheet(("result", position))
        wait()
    assert cal.DIRECTION not in app.runs[base].options
    assert "Interpolated values" in app.runs[base].result.tables
    for position, (options, predictions) in saved.items():
        assert app.runs[position].options == options
        pd.testing.assert_frame_equal(app.runs[position].result.tables[cal.PREDICTIONS], predictions)
