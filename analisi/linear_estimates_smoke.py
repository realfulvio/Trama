"""Real-dialog and project-lifecycle acceptance for linear point intervals."""
import json
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .linear_estimates import FORWARD, INVERSE, X_VALUE, Y_VALUE, LEVEL, SHEET, LABEL_KEYS


def check_linear_estimates(root, app, directory, kit):
    wait, capture = kit.wait_for_calculation, kit.capture
    frame = pd.DataFrame({"X": [0., 1., 2., 3., 4.], "Y": [1., 3., 2., 5., 7.]})
    # Exercise exponent-safe arithmetic from the actual frozen Windows build.
    from .workbench import analyse
    from scipy import stats
    extreme = analyse("Linear regression", frame.assign(X=frame.X*1e-150, Y=frame.Y*1e-100),
                      {"X": "X", "Y": "Y", FORWARD: True, X_VALUE: 1e170}).tables[SHEET].iloc[0]
    half = stats.t.isf(.025, 3)*np.sqrt(.12)*1e220
    np.testing.assert_allclose([extreme.Estimate, extreme.Lower, extreme.Upper],
                               [1.4e220, 1.4e220-half, 1.4e220+half], rtol=3e-12)
    horizontal = pd.DataFrame({"X": [-2., -1., 0., 1., 2.], "Y": [-1., 0., 2., 0., -1.]})
    legacy = Dataset(frame.copy(), analyses=[("Linear regression", {"X": "X", "Y": "Y"})])
    path = directory / "linear-point-estimates.alab"
    title = "Linear points"
    save_project(path, {title: legacy, "Horizontal": Dataset(horizontal)})
    app.import_file(path)
    app.open_sheet(("result", 0))
    wait()
    previous = app.runs[0].result.tables["Regression"].copy()
    assert list(app.runs[0].result.tables) == ["Regression"]
    app.show("data", title)

    def configure(dialog):
        kit.pick_method(dialog, "Linear regression")
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        assert not dialog.linear_visibility()[LEVEL]
        assert not dialog.linear_visibility()[X_VALUE]
        assert not dialog.linear_visibility()[Y_VALUE]
        dialog.controls[FORWARD][1].set(True)
        assert dialog.linear_visibility()[LEVEL] and dialog.linear_visibility()[X_VALUE]
        for name, value in [(X_VALUE, "inf"), (X_VALUE, "abc"), (LEVEL, "100")]:
            dialog.controls[X_VALUE][1].set("2,0")
            dialog.controls[LEVEL][1].set("95")
            dialog.controls[name][1].set(value)
            with patch.object(kit.messagebox, "showerror") as shown:
                assert not dialog.validate()
            assert shown.called and dialog.winfo_exists()
            dialog.update()
            assert dialog.focus_get() == dialog.field_rows[name][1]
        dialog.controls[X_VALUE][1].set("2,0")
        dialog.controls[LEVEL][1].set("95")
        dialog.controls[INVERSE][1].set(True)
        dialog.controls[Y_VALUE][1].set("0")
        for label, key in LABEL_KEYS.items():
            assert dialog.field_rows[label][0].cget("text") == i18n.tr(key)
        dialog.update()
        assert dialog.winfo_width() <= min(1024, root.winfo_screenwidth())
        assert dialog.winfo_height() <= min(768, root.winfo_screenheight())
        from . import ui_theme
        (directory / "linear-ui.json").write_text(json.dumps({
            "platform": sys.platform, "font_family": ui_theme.family(), "ui_scale": ui_theme.scale(),
            "dialog_width": dialog.winfo_width(), "dialog_height": dialog.winfo_height(),
            "tcl": root.tk.call("info", "patchlevel"), "tk": root.tk.call("package", "provide", "Tk"),
            "field_errors_corrected_in_same_dialog": True,
        }, indent=2), encoding="utf-8")
        capture(dialog, "window-linear-estimates-options-it.png")

    try:
        i18n.set_language("it")
        kit.drive_dialog(kit.AnalysisDialog, configure)
        app.choose_analysis()
        wait()
    finally:
        i18n.set_language("en")
    index = next(i for i, run in enumerate(app.runs) if run.options.get(INVERSE))
    run = app.runs[index]
    table = run.result.tables[SHEET]
    assert run.options[X_VALUE] == 2.0 and run.options[Y_VALUE] == 0.0
    assert table.Direction.tolist() == ["Y from X", "X from Y"]
    np.testing.assert_allclose(table[["Estimate", "Lower", "Upper"]].iloc[0],
                               [3.6, 2.0409260847, 5.1590739153], rtol=1e-9)
    np.testing.assert_allclose(table[["Estimate", "Lower", "Upper"]].iloc[1],
                               [-4/7, -10.3959697653527, 0.8593046505487123], rtol=1e-10)
    app.open_sheet(("result", 0))
    wait()
    pd.testing.assert_frame_equal(app.runs[0].result.tables["Regression"], previous)
    app.show("result", index)
    app.result_tabs.select(list(run.result.tables).index(SHEET))
    capture(root, "window-linear-estimates-results.png")

    def narrower(dialog):
        assert dialog.controls[FORWARD][1].get() and dialog.controls[INVERSE][1].get()
        dialog.controls[LEVEL][1].set("90")
    kit.drive_dialog(kit.AnalysisDialog, narrower)
    app.edit_analysis()
    wait()
    changed = app.runs[index].result.tables[SHEET]
    assert changed.Upper.iloc[0]-changed.Lower.iloc[0] < table.Upper.iloc[0]-table.Lower.iloc[0]

    app.show("data", title)
    app.edit_cell(0, 1, "2.0")
    app.open_sheet(("result", index))
    wait()
    assert not np.allclose(app.runs[index].result.tables[SHEET].Estimate, changed.Estimate)
    app.show("data", title)
    app.current_grid.select((1, 1))
    app.toggle_exclusion()
    app.open_sheet(("result", index))
    wait()
    assert app.runs[index].result.tables["Regression"].loc["N", "Value"] == 4
    expected = app.runs[index].result.tables[SHEET].copy()
    assert app.save()
    app.import_file(path)
    app.open_sheet(("graph", index))  # Restore the linked source before opening its result.
    wait()
    pd.testing.assert_frame_equal(app.runs[index].result.tables[SHEET], expected)
    assert app.runs[index].options[LEVEL] == 90.0

    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index(SHEET))
    csv = directory / "linear-estimates.csv"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = pd.read_csv(csv, index_col=0)  # The application's CSV contract includes the result row index.
    pd.testing.assert_frame_equal(exported, expected, check_dtype=False)
    app.use_result_as_data()
    assert SHEET in app.tables
    pd.testing.assert_frame_equal(app.tables[SHEET].raw, expected, check_dtype=False)
    for suffix, signature in [("svg", b"<svg"), ("png", b"\x89PNG"), ("pdf", b"%PDF")]:
        app.show("graph", index)
        output = directory / ("linear-estimates."+suffix)
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(output)):
            app.export()
        assert signature in output.read_bytes()[:1200]

    app.show("result", index)
    def disable(dialog):
        dialog.controls[FORWARD][1].set(False)
        dialog.controls[INVERSE][1].set(False)
        dialog.controls[X_VALUE][1].set("nan")
        assert not dialog.linear_visibility()[LEVEL]
    kit.drive_dialog(kit.AnalysisDialog, disable)
    app.edit_analysis()
    wait()
    assert list(app.runs[index].result.tables) == ["Regression"]
    assert LEVEL not in app.runs[index].options

    app.show("data", "Horizontal")
    def unbounded(dialog):
        kit.pick_method(dialog, "Linear regression")
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls[INVERSE][1].set(True)
        dialog.controls[Y_VALUE][1].set("5")
    kit.drive_dialog(kit.AnalysisDialog, unbounded)
    app.choose_analysis()
    wait()
    index = next(i for i, run in enumerate(app.runs) if run.title == "Horizontal")
    table = app.runs[index].result.tables[SHEET].copy()
    assert table["Confidence set"].tolist() == ["Two unbounded intervals"]*2
    assert table.Estimate.isna().all()
    assert np.isneginf(table.Lower.iloc[0]) and np.isposinf(table.Upper.iloc[1])
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index(SHEET))
    capture(root, "window-linear-estimates-unbounded.png")
    assert app.save()
    app.import_file(path)
    app.open_sheet(("result", index))
    wait()
    pd.testing.assert_frame_equal(app.runs[index].result.tables[SHEET], table)
    assert not kit.errors, kit.errors
