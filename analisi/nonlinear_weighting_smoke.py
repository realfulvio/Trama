"""Desktop smoke check for the observed-Y weightings of Nonlinear regression (0.60).

``tramastat.py --smoke`` calls :func:`check_nonlinear_weighting` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=nonlinear-weighting python tramastat.py --smoke DIR``.

Synthetic data only. The expected numbers come from a closed-form weighted straight line computed here
with numpy, independent of the optimizer the application uses.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import fit_weights as fw
from . import i18n
from .data import Dataset, save_project
from .workbench import analyse

METHOD = "Nonlinear regression"
SHEET, OLD = "Weighted line", "Legacy fit"
Y = [1.2, 2.1, 2.9, 5.1, 5.9, 9.4, 10.1, 12.7, 16.0, 17.4]
FRAME = pd.DataFrame({
    "X": [*range(10), None, 11.],
    "Y": [*Y, 0., None],
    "Second": [*(3 * np.array(Y) + 2), 5., None],
    "Zero": [*Y[:4], 0., *Y[5:], 3., None],
    "Group": ["a"] * 5 + ["b"] * 5 + [None, None],
    "SD": [.5 + .1 * i for i in range(12)],
})
OLD_FRAME = pd.DataFrame({"X": [*range(10)], "Y": Y, "SD": [.5 + .1 * i for i in range(10)]})
BASE = {"X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line"}
OLD_RECIPES = [
    (METHOD, {"X": "X", "Y": "Y", "Model": "Straight line"}),  # saved before Weighting existed
    (METHOD, {**BASE, "Weighting": "Unweighted"}),
    (METHOD, {**BASE, "Weighting": "Inverse variance (column)", "SD column": "SD"}),
]
CHOICES = fw.NONLINEAR_WEIGHTINGS


def line(x, y, power):
    """Closed-form weighted straight line: coefficients, weighted SS and raw SS."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    scale = np.abs(y) ** power
    design = np.column_stack((np.ones(len(x)), x))
    beta = np.linalg.lstsq(design / scale[:, None], y / scale, rcond=None)[0]
    residual = y - design @ beta
    return beta, float(np.sum((residual / scale) ** 2)), float(residual @ residual)


def check_nonlinear_weighting(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "nonlinear-weighting"
    out.mkdir(exist_ok=True)
    path = directory / "nonlinear-weighting.alab"

    old = Dataset(OLD_FRAME.copy())
    old.analyses.extend((method, dict(options)) for method, options in OLD_RECIPES)
    save_project(path, {SHEET: Dataset(FRAME.copy()), OLD: old})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot_name=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        assert field in report.call_args.args[1], report.call_args
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            shot(dialog, shot_name)

    def drive(action, *, accept):
        """Like tools.drive_dialog, but the dialog can also be cancelled."""
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found

        def enter():
            dialog = find(root)
            if dialog is None:
                errors.append("AnalysisDialog did not open")
                return
            try:
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(str(error))
                dialog.cancel()

        root.after(200, enter)

    def fit(index, name, table):
        return app.runs[index].result.tables[f"{table}: {name}"]

    def estimates(index):
        return fit(index, "All", "Parameters")["Estimate"].to_numpy(float)

    # 1. Recipes saved by 0.60.0 and earlier keep their tables and open with the right fields.
    positions = [i for i, run in enumerate(app.runs) if run.title == OLD]
    assert len(positions) == 3, positions
    for position, (method, options) in zip(positions, OLD_RECIPES):
        app.open_sheet(("result", position))
        wait()
        assert app.runs[position].options == options, app.runs[position].options
        expected = analyse(method, OLD_FRAME, options)
        assert list(app.runs[position].result.tables) == list(expected.tables)
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(app.runs[position].result.tables[name], table)
    assert "Weighted R²" not in fit(positions[0], "All", "Fit").index
    assert "Weighted R²" in fit(positions[2], "All", "Fit").index

    def inverse_recipe(dialog):
        assert dialog.controls["Weighting"][1].get() == "Inverse variance (column)"
        assert tuple(dialog.field_rows["Weighting"][1].cget("values")) == CHOICES
        assert placed(dialog, "SD column") and dialog.controls["SD column"][1].get() == "SD"
        dialog.controls["Weighting"][1].set("1/Y²")
        dialog.update()
        assert not placed(dialog, "SD column")
        assert "Y²" in dialog.weighting_note.cget("text")

    app.show("result", positions[2])
    drive(inverse_recipe, accept=False)  # cancelling keeps the stored recipe
    app.edit_analysis()
    root.update()
    assert app.runs[positions[2]].options == OLD_RECIPES[2][1]

    def unweighted_recipe(dialog):
        assert dialog.controls["Weighting"][1].get() == "Unweighted" and not placed(dialog, "SD column")

    app.show("result", positions[0])
    drive(unweighted_recipe, accept=False)
    app.edit_analysis()
    root.update()

    # 2. New analysis: observed 1/Y² on a response with a zero. The error stays on Weighting; changing
    #    the response corrects it.
    app.show("data", SHEET)

    def new_fit(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        tools.select_columns(dialog, "Y columns", {"Zero"})
        dialog.controls["Model"][1].set("Straight line")
        assert dialog.controls["Weighting"][1].get() == "Unweighted"
        assert tuple(dialog.field_rows["Weighting"][1].cget("values")) == CHOICES
        assert not placed(dialog, "SD column")
        assert "equally" in dialog.weighting_note.cget("text")
        dialog.controls["Weighting"][1].set("Inverse variance (column)")
        dialog.update()
        assert placed(dialog, "SD column")
        dialog.controls["Weighting"][1].set("1/Y²")
        dialog.update()
        assert not placed(dialog, "SD column")
        assert "relative distances" in dialog.weighting_note.cget("text")
        rejected(dialog, "Weighting", "window-weighting-zero-error.png")
        dialog.controls["Weighting"][1].set("1/abs(Y)")
        rejected(dialog, "Weighting")
        tools.select_columns(dialog, "Y columns", {"Y"})
        dialog.controls["Weighting"][1].set("1/Y²")
        dialog.update()
        dialog.fields.select(dialog.field_rows["Weighting"][1].master)
        shot(dialog, "window-weighting-dialog.png")

    tools.drive_dialog(tools.AnalysisDialog, new_fit)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.options["Weighting"] == "1/Y²" and "SD column" not in run.options, run.options
    beta, weighted_ss, raw_ss = line(range(10), Y, 1)
    # The two incomplete rows (X missing, and Y missing) leave the ten complete points.
    assert fit(index, "All", "Fit").loc["N", "Value"] == 10
    assert np.allclose(estimates(index), beta, rtol=2e-6), (estimates(index), beta)
    table = fit(index, "All", "Fit")["Value"]
    assert table["Weighting"] == "1/Y²"
    assert abs(table["Weighted residual SS"] - weighted_ss) < 2e-6 * weighted_ss
    assert abs(table["Residual SS"] - raw_ss) < 2e-6 * raw_ss
    assert "Weighted R²" in table.index
    residuals = fit(index, "All", "Residuals")
    assert np.allclose(residuals["Weighted residual"], residuals["Residual"] / residuals["Observed"].abs())
    assert list(app.tables[SHEET].raw.columns) == list(FRAME.columns), "weights must not add worksheet columns"
    # The graph draws the tabulated estimates.
    curve = app.runs[index].result.figure.axes[0].lines[0].get_xydata()
    assert np.allclose(curve[:, 1], beta[0] + beta[1] * curve[:, 0], rtol=2e-6, atol=1e-6)
    app.show("result", index)
    app.result_tabs.select(1)
    shot(root, "window-weighting-result.png")
    app.show("graph", index)
    shot(root, "window-weighting-graph.png")
    for suffix in ("png", "svg"):
        target = out / f"weighted-fit.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (out / "weighted-fit.svg").read_bytes()
    app.show("result", index)
    app.result_tabs.select(1)
    csv = out / "weighted-fit.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = csv.read_text(encoding="utf-8-sig")
    assert "Weighted residual SS" in exported and "1/Y²" in exported, exported[:200]
    before = set(app.tables)
    app.show("result", index)
    app.result_tabs.select(1)
    app.use_result_as_data()
    added = set(app.tables) - before
    assert len(added) == 1, added
    assert "Weighted residual SS" in app.tables[added.pop()].raw.iloc[:, 0].astype(str).tolist()

    # 3. Edit the analysis: a cancelled change keeps it, an accepted one recalculates with 1/abs(Y).
    def change(dialog):
        dialog.controls["Weighting"][1].set("Unweighted")

    app.show("result", index)
    drive(change, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[index].options["Weighting"] == "1/Y²" and np.allclose(estimates(index), beta, rtol=2e-6)

    def to_absolute(dialog):
        assert dialog.controls["Weighting"][1].get() == "1/Y²" and not placed(dialog, "SD column")
        dialog.controls["Weighting"][1].set("1/abs(Y)")

    drive(to_absolute, accept=True)
    app.edit_analysis()
    wait()
    beta_abs, weighted_abs, _ = line(range(10), Y, .5)
    assert app.runs[index].options["Weighting"] == "1/abs(Y)"
    assert np.allclose(estimates(index), beta_abs, rtol=2e-6), (estimates(index), beta_abs)
    assert abs(fit(index, "All", "Fit").loc["Weighted residual SS", "Value"] - weighted_abs) < 2e-6 * weighted_abs

    # 4. A cell edited to zero stops the recalculation with the weighting message; excluding it recovers.
    columns = list(app.tables[SHEET].raw.columns)
    app.show("data", SHEET)
    app.edit_cell(3, columns.index("Y"), "0")
    wait()
    status = app.status.get()
    assert "need attention" in status and "zero" in status, status
    assert app.runs[index].result is None, "the linked result waits for a valid recalculation"
    app.show("data", SHEET)
    app.current_grid.select((3, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    kept = [i for i in range(10) if i != 3]
    beta_kept = line(kept, [Y[i] for i in kept], .5)[0]
    assert fit(index, "All", "Fit").loc["N", "Value"] == 9
    assert np.allclose(estimates(index), beta_kept, rtol=2e-6), (estimates(index), beta_kept)
    app.show("data", SHEET)
    app.edit_cell(9, columns.index("Y"), "18.5")
    wait()
    changed = [Y[i] if i != 9 else 18.5 for i in kept]
    assert np.allclose(estimates(index), line(kept, changed, .5)[0], rtol=2e-6)
    app.show("result", index)
    app.result_tabs.select(1)
    shot(root, "window-weighting-recalculated.png")

    # 5. Two responses and two groups, each series weighted by its own Y.
    app.show("data", SHEET)

    def grouped(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("X")
        tools.select_columns(dialog, "Y columns", {"Y", "Second"})
        tools.select_columns(dialog, "Grouping variables", {"Group"})
        dialog.controls["Model"][1].set("Straight line")
        dialog.controls["Weighting"][1].set("1/abs(Y)")

    tools.drive_dialog(tools.AnalysisDialog, grouped)
    app.choose_analysis()
    wait()
    second = len(app.runs) - 1
    parameters = app.runs[second].result.tables["Parameters"].set_index(["Response variable", "Group"])
    kept_y = FRAME["Y"].copy()
    kept_y.iloc[3] = np.nan  # the excluded cell
    kept_y.iloc[9] = 18.5  # the edited cell
    kept_second = FRAME["Second"]
    checks = [("Y", "1 · Group='a'", range(5), kept_y), ("Y", "2 · Group='b'", range(5, 10), kept_y),
              ("Second", "1 · Group='a'", range(5), kept_second), ("Second", "2 · Group='b'", range(5, 10), kept_second)]
    for response, label, rows, source in checks:
        rows = [i for i in rows if np.isfinite(source.iloc[i])]
        expected = line(FRAME["X"].iloc[rows], source.iloc[rows], .5)[0]
        found = parameters.loc[(response, label), "Estimate"].to_numpy(float)
        assert np.allclose(found, expected, rtol=2e-6), (response, label, found, expected)
    assert len(app.runs[second].result.figure.axes) == 2

    # 6. Save and reopen: the choice and the results survive.
    saved = {(r.title, r.slot): (dict(r.options), {k: v.copy() for k, v in r.result.tables.items()})
             for r in app.runs if r.method == METHOD and r.title == SHEET}
    slot = app.runs[index].slot
    app.path = directory / "nonlinear-weighting-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position in range(len(app.runs)):
        app.open_sheet(("result", position))
        wait()
    reopened = {(r.title, r.slot): r for r in app.runs}
    for key, (options, tables) in saved.items():
        assert reopened[key].options == options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame)
    index = next(i for i, r in enumerate(app.runs) if (r.title, r.slot) == (SHEET, slot))
    assert app.runs[index].options["Weighting"] == "1/abs(Y)"

    # 7. The explanation under Weighting follows the interface language.
    def italian(dialog):
        dialog.controls["Weighting"][1].set("1/Y²")
        dialog.update()
        assert "distanze relative" in dialog.weighting_note.cget("text")
        shot(dialog, "window-weighting-dialog-it.png")

    i18n.set_language("it")
    try:
        app.show("result", index)
        drive(italian, accept=False)
        app.edit_analysis()
        root.update()
    finally:
        i18n.set_language("en")
    assert fw.NOTE_KEYS["1/Y²"] in i18n.CATALOGS["it"]
    assert not errors, errors
