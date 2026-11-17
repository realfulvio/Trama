"""Desktop smoke check for multiple linear diagnostics and profile predictions.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=ols-diagnostics``) calls
:func:`check_ols_diagnostics`.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from .data import Dataset, save_project
from .ols_diagnostics import LINEAR_CI, LINEAR_DIAGNOSTICS, LINEAR_PROFILES, LINEAR_RESIDUAL_PLOT


def check_ols_diagnostics(root, app, directory, kit):
    from tkinter import filedialog, messagebox

    capture, drive, pick, select = kit.capture, kit.drive_dialog, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    path = directory / "ols-diagnostics.alab"
    title = "Orthogonal regression"
    frame = pd.DataFrame({
        "X": [-1, 1, -1, 1, -1, 1, -1, 1, 1],
        "Group": ["A", "A", "A", "A", "B", "B", "B", "B", "B"],
        "Y": [9, 13, 7, 11, 13, 17, 9, 13, None],
    })
    save_project(path, {title: Dataset(frame)})
    app.import_file(path)

    def configure(dialog):
        pick(dialog, "Multiple regression")
        dialog.controls["Response"][1].set("Y")
        select(dialog, "Predictors", {"X", "Group"})
        select(dialog, "Categorical predictors", {"Group"})
        dialog.show_regression_fields()
        assert dialog.field_rows[LINEAR_DIAGNOSTICS][1].grid_info()
        dialog.controls["Family"][1].set("Poisson")
        assert not dialog.field_rows[LINEAR_DIAGNOSTICS][1].grid_info()
        assert not dialog.field_rows[LINEAR_PROFILES][1].grid_info()
        assert dialog.fields.tab(dialog.field_rows[LINEAR_DIAGNOSTICS][0].master, "state") == "disabled"
        assert dialog.field_rows["Exposure"][1].grid_info()
        dialog.controls["Family"][1].set("Linear")
        assert dialog.field_rows[LINEAR_RESIDUAL_PLOT][1].grid_info()
        editor = dialog.controls[LINEAR_PROFILES][1]
        editor.profiles.append({"name": "Bad", "values": {"X": 0, "Group": "Z"}})
        editor.refresh()
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert "Z" in shown.call_args.args[1] and "Bad" in shown.call_args.args[1], shown.call_args
        assert dialog.winfo_exists()
        capture(dialog, "window-ols-unknown-level.png")
        editor.profiles[:] = [
            {"name": "Alfa", "values": {"X": 0, "Group": "A"}},
            {"name": "Beta", "values": {"X": 2, "Group": "B"}},
        ]
        editor.refresh()
        dialog.controls[LINEAR_DIAGNOSTICS][1].set(True)
        dialog.controls[LINEAR_RESIDUAL_PLOT][1].set("Residuals vs fitted")
        dialog.controls[LINEAR_CI][1].set("95")
        capture(dialog, "window-ols-options.png")
        assert dialog.validate() is True
        dialog.result = None

    drive(configure)
    app.choose_analysis()
    wait()
    run = app.runs[0]
    assert run.options[LINEAR_DIAGNOSTICS] is True
    assert np.allclose(run.result.tables["Coefficients"]["Estimate"], [10, 2, 3], atol=1e-8)
    diagnostics = run.result.tables["Linear diagnostics"]
    assert diagnostics["Source row"].tolist() == list(range(8))
    assert abs(run.result.tables["Linear model diagnostics"].loc["PRESS", "Value"] - 51.2) < 1e-8
    predictions = run.result.tables["Linear predictions"]
    assert predictions["Profile"].tolist() == ["Alfa", "Beta"]
    assert np.allclose(predictions["Prediction"], [10, 17])
    app.show("result", 0)
    app.result_tabs.select(list(run.result.tables).index("Linear predictions"))
    capture(root, "window-ols-predictions.png")
    app.show("graph", 0)
    capture(root, "window-ols-residuals.png")

    app.show("data", title)
    app.edit_cell(0, 2, "10")
    wait()
    assert not np.allclose(app.runs[0].result.tables["Linear predictions"]["Prediction"], [10, 17])
    app.show("data", title)
    app.current_grid.select((1, 0))
    app.toggle_exclusion()
    wait()
    assert app.runs[0].result.tables["Linear diagnostics"]["Source row"].tolist() == [0, 2, 3, 4, 5, 6, 7]
    saved_predictions = app.runs[0].result.tables["Linear predictions"].copy()
    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("result", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.options[LINEAR_PROFILES][0]["name"] == "Alfa"
    pd.testing.assert_frame_equal(reopened.result.tables["Linear predictions"], saved_predictions)

    app.show("result", 0)
    app.result_tabs.select(list(reopened.result.tables).index("Linear predictions"))
    app.use_result_as_data()
    sheet = app.tables["Linear predictions"].raw
    assert sheet["Profile"].tolist() == reopened.result.tables["Linear predictions"]["Profile"].tolist()
    csv_path = directory / "ols-predictions.csv"
    app.show("result", 0)
    app.result_tabs.select(list(app.runs[0].result.tables).index("Linear predictions"))
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    assert exported["Profile"].tolist() == ["Alfa", "Beta"]
    app.show("graph", 0)
    svg_path = directory / "ols-residuals.svg"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(svg_path)):
        app.export()
    assert b"<svg" in svg_path.read_bytes()
