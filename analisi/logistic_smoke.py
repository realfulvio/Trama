"""Desktop smoke check for logistic diagnostics and profile probabilities.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=logistic-profiles``) calls
:func:`check_logistic_profiles`.
"""
from unittest.mock import patch

import pandas as pd

from .data import Dataset, save_project
from .i18n import active_language, set_language
from .logistic_diagnostics import LOGISTIC_CI, LOGISTIC_CUTOFF, LOGISTIC_DIAGNOSTICS, LOGISTIC_PROFILES
from .ols_diagnostics import LINEAR_DIAGNOSTICS


def check_logistic_profiles(root, app, directory, kit):
    from tkinter import filedialog, messagebox

    capture, drive, pick, select = kit.capture, kit.drive_dialog, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _check(root, app, directory, capture, drive, pick, select, wait, messagebox, filedialog):
    path = directory / "logistic-profiles.alab"
    title = "Logistic outcomes"
    # The same balanced Group coding as the formula tests, plus one incomplete row.
    # A separated Group would make the exponentiated coefficient limits overflow.
    frame = pd.DataFrame({
        "X": [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0],
        "Group": ["A", "A", "A", "A", "B", "B", "B", "B", "A", "A", "A", "A", "B", "B", "B", "B", "A"],
        "Y": [1, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, None],
    })
    save_project(path, {title: Dataset(frame)})
    app.import_file(path)

    def italian(dialog):
        pick(dialog, "Multiple regression")
        dialog.controls["Family"][1].set("Logistic")
        heading = dialog.field_rows[LOGISTIC_DIAGNOSTICS][0]
        tab = heading.master
        assert heading.cget("text") == "Diagnostica logistica"
        assert dialog.fields.tab(tab, "text") == "Diagnostica e profili"
        assert dialog.field_rows[LOGISTIC_CUTOFF][0].cget("text") == "Soglia logistica"
        dialog.ok = dialog.cancel

    set_language("it")
    drive(italian)
    app.choose_analysis()
    set_language("en")

    def configure(dialog):
        pick(dialog, "Multiple regression")
        dialog.controls["Response"][1].set("Y")
        select(dialog, "Predictors", {"X", "Group"})
        select(dialog, "Categorical predictors", {"Group"})
        logistic_tab = dialog.field_rows[LOGISTIC_DIAGNOSTICS][0].master
        linear_tab = dialog.field_rows[LINEAR_DIAGNOSTICS][0].master
        dialog.controls["Family"][1].set("Poisson")
        assert dialog.fields.tab(logistic_tab, "state") == "disabled"
        assert dialog.field_rows["Exposure"][1].grid_info()
        dialog.controls["Family"][1].set("Linear")
        assert dialog.fields.tab(logistic_tab, "state") == "disabled"
        assert dialog.field_rows[LINEAR_DIAGNOSTICS][1].grid_info()
        dialog.controls["Family"][1].set("Logistic")
        assert dialog.fields.tab(logistic_tab, "state") == "normal"
        assert dialog.fields.tab(linear_tab, "state") == "disabled"
        assert dialog.field_rows[LOGISTIC_DIAGNOSTICS][1].grid_info()
        assert not dialog.field_rows[LOGISTIC_CUTOFF][1].grid_info()
        assert not dialog.field_rows[LOGISTIC_CI][1].grid_info()
        editor = dialog.controls[LOGISTIC_PROFILES][1]
        dialog.show_regression_fields()
        assert editor.predictors == ["X", "Group"]
        editor.profiles.append({"name": "Bad", "values": {"X": 0, "Group": "Z"}})
        editor.refresh()
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists()
        assert "Z" in shown.call_args.args[1] and "Bad" in shown.call_args.args[1], shown.call_args
        capture(dialog, "window-logistic-unknown-level.png")
        editor.profiles.clear()
        editor.refresh()
        dialog.show_regression_fields()
        assert not dialog.field_rows[LOGISTIC_CI][1].grid_info()
        editor.label.set("Centro")
        editor.inputs["X"].set("0")
        editor.inputs["Group"].set("A")
        assert editor.add() is True
        assert dialog.field_rows[LOGISTIC_CI][1].grid_info()
        editor.label.set("Alto")
        editor.inputs["X"].set("1")
        editor.inputs["Group"].set("B")
        assert editor.add() is True
        dialog.controls[LOGISTIC_DIAGNOSTICS][1].set(True)
        assert dialog.field_rows[LOGISTIC_CUTOFF][1].grid_info()
        dialog.controls[LOGISTIC_CUTOFF][1].set("1.5")
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists()
        assert "Logistic cutoff" in shown.call_args.args[1], shown.call_args
        dialog.controls[LOGISTIC_CUTOFF][1].set("0.5")
        dialog.controls[LOGISTIC_CI][1].set("95")
        dialog.fields.select(logistic_tab)
        dialog.update_idletasks()
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        assert dialog.field_rows[LOGISTIC_DIAGNOSTICS][0].cget("text") == "Logistic diagnostics"
        capture(dialog, "window-logistic-dialog.png")
        assert dialog.validate() is True
        dialog.result = None

    drive(configure)
    app.choose_analysis()
    wait()
    run = app.runs[0]
    assert run.options[LOGISTIC_DIAGNOSTICS] is True
    assert [profile["name"] for profile in run.options[LOGISTIC_PROFILES]] == ["Centro", "Alto"]
    tables = run.result.tables
    assert "Logistic diagnostics" in tables and "Logistic classification" in tables
    assert "Logistic fit metrics" in tables and "Logistic predictions" in tables
    assert tables["Logistic diagnostics"]["Source row"].tolist() == list(range(16))
    assert list(tables["Logistic classification"].columns) == ["Predicted 0", "Predicted 1"]
    assert tables["Logistic predictions"]["Profile"].tolist() == ["Centro", "Alto"]
    assert "conditional mean probability" in tables["Logistic predictions"]["Interval"].iloc[0]
    app.show("result", 0)
    app.result_tabs.select(list(tables).index("Logistic predictions"))
    capture(root, "window-logistic-predictions.png")
    confirmed = tables["Logistic predictions"].copy()

    def abort(dialog):
        dialog.controls[LOGISTIC_CUTOFF][1].set("2")
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists()
        assert "Logistic cutoff" in shown.call_args.args[1], shown.call_args
        dialog.result = None
        dialog.ok = dialog.cancel

    drive(abort)
    app.show("result", 0)
    app.edit_analysis()
    wait()
    assert app.runs[0].options[LOGISTIC_CUTOFF] == 0.5
    pd.testing.assert_frame_equal(app.runs[0].result.tables["Logistic predictions"], confirmed)

    app.show("data", title)
    app.edit_cell(0, 2, "0")
    wait()
    assert not app.runs[0].result.tables["Logistic predictions"]["Probability"].equals(confirmed["Probability"])
    app.show("data", title)
    app.current_grid.select((1, 0))
    app.toggle_exclusion()
    wait()
    source = app.runs[0].result.tables["Logistic diagnostics"]["Source row"].tolist()
    assert 0 in source and 1 not in source and 16 not in source
    saved = app.runs[0].result.tables["Logistic predictions"].copy()
    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("result", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.options[LOGISTIC_PROFILES][1]["name"] == "Alto"
    pd.testing.assert_frame_equal(reopened.result.tables["Logistic predictions"], saved)

    app.show("result", 0)
    app.result_tabs.select(list(reopened.result.tables).index("Logistic predictions"))
    app.use_result_as_data()
    sheet = app.tables["Logistic predictions"].raw
    assert sheet["Profile"].tolist() == ["Centro", "Alto"]
    csv_path = directory / "logistic-predictions.csv"
    app.show("result", 0)
    app.result_tabs.select(list(app.runs[0].result.tables).index("Logistic predictions"))
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    assert exported["Profile"].tolist() == ["Centro", "Alto"]
