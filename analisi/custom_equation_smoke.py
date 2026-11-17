"""Desktop smoke check for Fit custom equation (0.61), driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_custom_equation` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=custom-equation python tramastat.py --smoke DIR``.

Synthetic data only. Expected values come from closed-form (weighted) least squares written here with
NumPy, independent of the optimizer the application uses.
"""
import time
from threading import Event
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import curve_models, custom_fit, i18n
from .custom_fit import CUSTOM_EQUATION
from .data import Dataset, save_project
from .field_error import FieldError
from .presentation import Layout
from .workbench import analyse

LINE, GROUPS, OTHER, OLD = "Line", "Groups", "Other", "Legacy"
X = np.array([-2., -1, 0, 1, 2, 3, 4, 5])
Y = np.array([1.2, 2.7, 4.4, 5.3, 7.2, 8.0, 10.2, 11.1])
SD = np.array([1., .5, 1.5, 1, .75, 2, 1.25, 1])
LINE_FRAME = pd.DataFrame({"X": X, "Y": Y, "SD": SD})
GROUP_FRAME = pd.concat([
    pd.DataFrame({"X": X, "Y": Y, "SD": SD, "Group": "Control"}),
    pd.DataFrame({"X": X, "Y": np.round(Y * 1.5 + 2, 6), "SD": SD, "Group": "Treated"})], ignore_index=True)
OTHER_FRAME = pd.DataFrame({"X": np.arange(6.), "Y": np.round(2 * np.exp(.3 * np.arange(6.)), 4)})
OLD_RECIPE = ("Nonlinear regression", {"X": "X", "Y columns": ["Y"], "Grouping variables": [],
                                       "Model": "Straight line", "Weighting": "Unweighted"})
OTHER_RECIPE = (CUSTOM_EQUATION, {
    "X": "X", "Y": "Y", "Group": None, "Equation": "A*exp(B*X)",
    "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                   {"name": "B", "start": .1, "lower": None, "upper": None, "fixed": False}],
    "Weighting": "Unweighted", "SD column": None, "Confidence level (%)": 95.0, "Curve points": 60})


def wls(x, y, sd=None, *, fixed_a=None):
    """Closed-form straight line Y = A + B*X; returns (A, B, standard errors or None for a fixed A, WSSE)."""
    sd = np.ones(len(x)) if sd is None else sd
    if fixed_a is not None:
        z = (x / sd)[:, None]
        beta = np.linalg.lstsq(z, (y - fixed_a) / sd, rcond=None)[0]
        resid = (y - fixed_a - x * beta[0]) / sd
        return fixed_a, beta[0], None, float(resid @ resid)
    design = np.column_stack([np.ones(len(x)), x]) / sd[:, None]
    beta = np.linalg.lstsq(design, y / sd, rcond=None)[0]
    resid = y / sd - design @ beta
    wsse = float(resid @ resid)
    covariance = np.linalg.inv(design.T @ design) * wsse / (len(x) - 2)
    return beta[0], beta[1], np.sqrt(np.diag(covariance)), wsse


def check_custom_equation(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "custom-equation"
    out.mkdir(exist_ok=True)
    root.geometry("1024x768+0+0")
    first_path, second_path = directory / "custom-equation.alab", directory / "custom-equation-other.alab"
    old = Dataset(LINE_FRAME.copy())
    old.analyses.append((OLD_RECIPE[0], dict(OLD_RECIPE[1])))
    save_project(first_path, {LINE: Dataset(LINE_FRAME.copy()), GROUPS: Dataset(GROUP_FRAME.copy()), OLD: old})
    other = Dataset(OTHER_FRAME.copy())
    other.analyses.append((OTHER_RECIPE[0], dict(OTHER_RECIPE[1])))
    save_project(second_path, {OTHER: other})
    catalog = dict(curve_models.MODELS)
    app.import_file(first_path)
    first_project = app.active_project

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def find_dialog(parent=None):
        for child in (parent or root).winfo_children():
            if isinstance(child, tools.AnalysisDialog):
                return child
            found = find_dialog(child)
            if found is not None:
                return found

    def drive(action, *, accept):
        """Like tools.drive_dialog, but the dialog can also be cancelled."""
        def enter(tries=0):
            dialog = find_dialog()
            if dialog is None or not dialog.winfo_viewable():
                if tries < 200:
                    root.after(40, lambda: enter(tries + 1))
                    return
                errors.append("AnalysisDialog did not open")
                return
            try:
                dialog.update_idletasks()
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(repr(error))
                dialog.cancel()

        root.after(100, enter)

    def when_open(action, *, accept):
        """Drive the dialog that the application reopens by itself once the worker reported an error."""
        state = {"done": False}

        def enter(tries=0):
            dialog = find_dialog()
            if dialog is None:
                if tries > 1200:
                    errors.append("the recovered AnalysisDialog did not open")
                    state["done"] = True
                    return
                root.after(25, lambda: enter(tries + 1))
                return
            try:
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(repr(error))
                dialog.cancel()
            state["done"] = True

        root.after(25, enter)
        return state

    def settle(state):
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(.02)
        assert not errors, errors

    def menu_entry(menu_label, entry_label):
        bar = root.nametowidget(root.cget("menu"))
        for position in range(bar.index("end") + 1):
            if bar.type(position) == "cascade" and bar.entrycget(position, "label") == i18n.ui(menu_label):
                popup = root.nametowidget(bar.entrycget(position, "menu"))
                for item in range(popup.index("end") + 1):
                    if popup.type(item) == "command" and popup.entrycget(item, "label") == i18n.ui(entry_label):
                        return popup, item
        raise AssertionError(f"menu entry {menu_label} / {entry_label} not found")

    def rejected(dialog, field, shot_name=None, contains=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (contains or field) in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            shot(dialog, shot_name)
        return message

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def set_equation(dialog, text):
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", text)

    def select_row(dialog, index):
        table = dialog.controls["Parameters"][1]
        table.tree.selection_set(str(index))
        table.load_selection()
        return table

    def table_of(run, name):
        return run.result.tables[name]

    def check_line(run, x, y, sd=None, *, fixed_a=None, name="All"):
        a, b, errors_, wsse = wls(np.asarray(x, float), np.asarray(y, float), sd, fixed_a=fixed_a)
        parameters = table_of(run, f"Parameters: {name}")
        np.testing.assert_allclose(parameters["Estimate"], [a, b], rtol=2e-6)
        fit = table_of(run, f"Fit: {name}")["Value"]
        assert abs(float(fit["Weighted residual SS"]) - wsse) < 1e-6 * max(1., wsse), (fit["Weighted residual SS"], wsse)
        if errors_ is not None:
            np.testing.assert_allclose(parameters["SE"], errors_, rtol=5e-5)
        return fit

    # 1. New analysis through the real Analyze menu, with the editors at 1024×768.
    app.show("data", LINE)
    root.update()

    def first_fit(dialog):
        tools.pick_method(dialog, CUSTOM_EQUATION)
        assert [dialog.fields.tab(i, "text") for i in range(4)] == ["Variables", "Equation", "Parameters", "Output"]
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        assert dialog.controls["Equation"][1].values() == "A + B*X"
        parameters = dialog.controls["Parameters"][1]
        assert [row["name"] for row in parameters.values()] == ["A", "B"]
        assert not placed(dialog, "SD column"), "the SD column belongs to Inverse variance only"
        dialog.update()
        assert dialog.winfo_width() <= 1024 and dialog.winfo_height() <= 768, (dialog.winfo_width(), dialog.winfo_height())
        for position in range(4):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= 768, "the dialog must fit the screen"
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-custom-equation.png")
        # An unsafe expression keeps the dialog open on Equation and adds no analysis.
        set_equation(dialog, "X.__class__")
        dialog.controls["Equation"][1].check()
        assert "Unexpected" in dialog.controls["Equation"][1].message.cget("text")
        rejected(dialog, "Equation", "window-custom-equation-error.png", contains="Unexpected")
        set_equation(dialog, "A + B*log(X)")
        message = rejected(dialog, "Equation", contains="not defined")
        assert "source row 0" in message, message
        set_equation(dialog, "A + B*X")
        dialog.controls["Equation"][1].check()
        assert "valid" in dialog.controls["Equation"][1].message.cget("text")
        # lower > upper names Parameters; correcting the row lets the dialog close.
        table = select_row(dialog, 1)
        table.variables["lower"].set("3")
        table.variables["upper"].set("1")
        rejected(dialog, "Parameters", contains="lower limit")
        table.variables["lower"].set("")
        table.variables["upper"].set("")
        assert dialog.validate() is True
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-custom-parameters.png")
        # A curve-point count that is not a finite whole number keeps the dialog open on that field,
        # with the typed value and a readable message, and adds no analysis.
        points = dialog.controls["Curve points"][1]
        runs_before = len(app.runs)
        for typed in ("nan", "inf", "-inf", "1e999", "50.5", "abc"):
            points.set(typed)
            message = rejected(dialog, "Curve points", contains="Curve points")
            assert "whole number" in message, message
            assert points.get() == typed, (typed, points.get())
        assert len(app.runs) == runs_before, "a rejected Curve points value must not add a result"
        points.set("60")
        # Adding a coefficient that the equation does not use is a Parameters error as well.
        table.add()
        rejected(dialog, "Parameters", contains="does not use")
        table.remove()

    before = len(app.runs)
    drive(first_fit, accept=True)
    popup, item = menu_entry("Analyze", "Analyze data…")
    popup.invoke(item)
    wait()
    assert len(app.runs) == before + 1 and not errors, errors
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.method == CUSTOM_EQUATION and run.options["Equation"] == "A + B*X"
    assert [(p["name"], p["fixed"]) for p in run.options["Parameters"]] == [("A", False), ("B", False)]
    assert set(run.options) == {"X", "Y", "Group", "Equation", "Parameters", "Weighting", "Confidence level (%)",
                                "Curve points"}, sorted(run.options)
    check_line(run, X, Y)
    slope, intercept = np.polyfit(X, Y, 1)
    np.testing.assert_allclose(table_of(run, "Parameters: All")["Estimate"], [intercept, slope], rtol=2e-6)

    # 2. Graph, Inspector colour, exports.
    app.show("graph", index)
    root.update()
    shot(root, "window-custom-graph.png")
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the data series"
    panel.select_group(panel.elements[0]["key"])
    widget = panel.fields["color"]["widget"]
    panel.vars["element:color"].set("#9b4174")
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert run.style and "#9b4174" in str(run.style), run.style
    app.toggle_inspector()
    for suffix in ("svg", "png"):
        target = out / f"custom-line.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (out / "custom-line.svg").read_bytes()
    app.show("result", index)
    app.result_tabs.select(0)
    csv = out / "custom-parameters.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = pd.read_csv(csv, encoding="utf-8-sig")
    assert {"Estimate", "SE", "CI lower", "CI upper", "Status"} <= set(exported.columns), exported.columns
    shot(root, "window-custom-parameters-table.png")

    # 3. A previous recipe (saved before this method existed) keeps its tables.
    legacy = next(i for i, r in enumerate(app.runs) if r.title == OLD)
    app.open_sheet(("result", legacy))
    wait()
    expected_legacy = analyse(*OLD_RECIPE[:1], LINE_FRAME, OLD_RECIPE[1])
    for name, frame in expected_legacy.tables.items():
        pd.testing.assert_frame_equal(app.runs[legacy].result.tables[name], frame)

    # 4. Edit one Y, then exclude one: estimates, residuals and curve are recalculated, Source row stays original.
    app.show("data", LINE)
    columns = list(app.tables[LINE].raw.columns)
    app.edit_cell(2, columns.index("Y"), "5.5")
    wait()
    changed = Y.copy()
    changed[2] = 5.5
    check_line(app.runs[index], X, changed)
    app.show("data", LINE)
    app.current_grid.select((3, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    keep = [i for i in range(8) if i != 3]
    fit = check_line(app.runs[index], X[keep], changed[keep])
    assert fit["N"] == 7 and fit["Skipped rows"] == 1
    assert table_of(app.runs[index], "Residuals: All").index.tolist() == keep
    a, b = table_of(app.runs[index], "Parameters: All")["Estimate"]
    curve = table_of(app.runs[index], "Curve: All")
    np.testing.assert_allclose(curve["Predicted"], a + b * curve["X"], rtol=1e-9)
    confirmed = app.runs[index]
    confirmed_tables = {name: frame.copy() for name, frame in confirmed.result.tables.items()}
    confirmed_options, confirmed_figure, confirmed_style = dict(confirmed.options), confirmed.result.figure, confirmed.style

    # 5. Change parameters: fix A = 1. Cancel keeps the confirmed analysis; Apply changes the degrees of freedom.
    def fix_intercept(dialog):
        assert dialog.method == CUSTOM_EQUATION and dialog.controls["Equation"][1].values() == "A + B*X"
        table = select_row(dialog, 0)
        table.variables["start"].set("1")
        table.fixed.set(True)
        table.store()
        dialog.update()

    app.show("result", index)
    drive(fix_intercept, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[index] is confirmed and confirmed.options == confirmed_options
    for name, frame in confirmed_tables.items():
        pd.testing.assert_frame_equal(confirmed.result.tables[name], frame)
    drive(fix_intercept, accept=True)
    app.edit_analysis()
    wait()
    fixed_run = app.runs[index]
    assert fixed_run.options["Parameters"][0]["fixed"] is True and fixed_run.options["Parameters"][0]["start"] == 1.0
    fit = check_line(fixed_run, X[keep], changed[keep], fixed_a=1.0)
    assert fit["Free parameters"] == 1 and fit["df"] == 6, fit
    assert table_of(fixed_run, "Parameters: All")["Status"].tolist() == ["Fixed", "Free"]
    assert len(table_of(fixed_run, "Parameters: All")) == 2

    # 6. A worker error after validation reopens the candidate with Parameters focused; Cancel keeps everything.
    app.layouts.append(Layout("Custom recovery layout", 1, [fixed_run.reference]))
    panels = [list(layout.panels) for layout in app.layouts]
    kept_tables = {name: frame.copy() for name, frame in fixed_run.result.tables.items()}
    kept_options, kept_figure, kept_style = dict(fixed_run.options), fixed_run.result.figure, fixed_run.style
    candidate = {}

    def widen(dialog):
        set_equation(dialog, "A + B*X + C*X^2")
        table = dialog.controls["Parameters"][1]
        table.add()
        table.variables["name"].set("C")
        table.variables["start"].set("0.1")
        candidate["rows"] = [row["name"] for row in table.values()]

    def recovered(dialog):
        assert dialog.error_label is not None and "Injected" in dialog.error_label.cget("text"), dialog.error
        assert dialog.initial_field == "Parameters" and dialog.fields.select() == str(
            dialog.field_rows["Parameters"][1].master)
        assert dialog.controls["Equation"][1].values() == "A + B*X + C*X^2"
        assert [row["name"] for row in dialog.controls["Parameters"][1].values()] == candidate["rows"] == ["A", "B", "C"]
        shot(dialog, "window-custom-recovered.png")

    failure = FieldError("Parameters", "Injected worker failure")
    for attempt in range(2):
        app.show("result", index)
        drive(widen, accept=True)
        with patch.object(custom_fit, "_fit_group", side_effect=failure):
            app.edit_analysis()
            assert app.pending is not None or find_dialog() is not None
            wait_state = when_open(recovered, accept=False) if attempt == 0 else when_open(
                lambda dialog: (recovered(dialog), dialog.controls["Equation"][1].values()), accept=False)
            settle(wait_state)
        assert app.runs[index] is fixed_run and fixed_run.options == kept_options
        assert fixed_run.result.figure is kept_figure and fixed_run.style == kept_style
        for name, frame in kept_tables.items():
            pd.testing.assert_frame_equal(fixed_run.result.tables[name], frame)
        assert [list(layout.panels) for layout in app.layouts] == panels and fixed_run.reference in app.layouts[-1].panels
        assert "discarded" in app.status.get(), app.status.get()
    # Corrected: the same candidate now fits (three coefficients, N = 7).
    app.show("result", index)
    drive(widen, accept=True)
    app.edit_analysis()
    wait()
    assert app.runs[index].options["Equation"] == "A + B*X + C*X^2"
    assert table_of(app.runs[index], "Fit: All")["Value"]["df"] == 5, table_of(app.runs[index], "Fit: All")
    assert table_of(app.runs[index], "Parameters: All").index.tolist() == ["A", "B", "C"]
    # Back to the straight line with both free: no stale coefficient rows remain.
    def narrow(dialog):
        set_equation(dialog, "A + B*X")
        table = select_row(dialog, 2)
        table.remove()
        table = select_row(dialog, 0)
        table.fixed.set(False)
        table.store()

    app.show("result", index)
    drive(narrow, accept=True)
    app.edit_analysis()
    wait()
    check_line(app.runs[index], X[keep], changed[keep])
    assert table_of(app.runs[index], "Parameters: All").index.tolist() == ["A", "B"]
    assert len(app.runs[index].result.figure.axes[0].lines) == 1

    # 7. Groups with inverse-variance weights.
    app.show("data", GROUPS)

    def grouped(dialog):
        tools.pick_method(dialog, CUSTOM_EQUATION)
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Weighting"][1].set("Inverse variance (column)")
        dialog.update()
        assert placed(dialog, "SD column")
        rejected(dialog, "SD column") if dialog.controls["SD column"][1].get() == "" else None
        dialog.controls["SD column"][1].set("SD")
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-custom-groups-dialog.png")

    tools.drive_dialog(tools.AnalysisDialog, grouped)
    app.choose_analysis()
    wait()
    group_index = len(app.runs) - 1
    group_run = app.runs[group_index]
    assert group_run.options["SD column"] == "SD" and group_run.options["Group"] == "Group"
    treated = GROUP_FRAME[GROUP_FRAME.Group == "Treated"]
    check_line(group_run, X, Y, SD, name="Control")
    check_line(group_run, treated.X, treated.Y, treated.SD.to_numpy(), name="Treated")
    app.show("graph", group_index)
    root.update()
    axes = group_run.result.figure.axes[0]
    assert [t.get_text() for t in axes.get_legend().get_texts()] == ["Control", "Treated"]
    shot(root, "window-custom-groups-graph.png")
    before_tables = set(app.tables)
    for sheet in ("Curve: Treated", "Residuals: Control"):
        app.show("result", group_index)
        app.result_tabs.select(list(group_run.result.tables).index(sheet))
        app.use_result_as_data()
    created = set(app.tables) - before_tables
    assert len(created) == 2, created
    frames = {name: app.tables[name].raw for name in created}
    assert any(list(f.columns) == ["X", "Predicted"] and len(f) == 201 for f in frames.values())
    assert any(list(f.columns)[:2] == ["Source row", "X"] for f in frames.values()), {k: list(f.columns) for k, f in frames.items()}

    # 8. Save, reopen, open the graph before the worksheet and wait for the recalculation.
    expected = {(r.title, r.slot): (dict(r.options), {k: v.copy() for k, v in r.result.tables.items()})
                for r in app.runs if r.method == CUSTOM_EQUATION and r.result is not None}
    assert len(expected) == 2, sorted(expected)
    app.path = directory / "custom-equation-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run_ in enumerate(app.runs):
        if run_.method == CUSTOM_EQUATION:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(r.title, r.slot): r for r in app.runs}
    for key, (options, tables) in expected.items():
        assert reopened[key].options == options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    key = next(k for k in expected if k[0] == LINE)
    reopened_index = next(i for i, r in enumerate(app.runs) if (r.title, r.slot) == key)
    app.show("result", reopened_index)
    app.result_tabs.select(0)
    shot(root, "window-custom-reopened.png")

    # 9. A second project with the same coefficient names and another formula does not contaminate the first.
    app.add_project()
    second_project = app.active_project
    app.import_file(second_path)
    other_index = next(i for i, r in enumerate(app.runs) if r.title == OTHER)
    app.open_sheet(("graph", other_index))
    wait()
    expected_other = analyse(*OTHER_RECIPE[:1], OTHER_FRAME, OTHER_RECIPE[1])
    pd.testing.assert_frame_equal(app.runs[other_index].result.tables["Parameters: All"],
                                  expected_other.tables["Parameters: All"])
    np.testing.assert_allclose(app.runs[other_index].result.tables["Parameters: All"]["Estimate"], [2., .3], rtol=1e-3)
    app.switch_project(first_project)
    root.update()
    reopened_index = next(i for i, r in enumerate(app.runs) if (r.title, r.slot) == key)
    app.open_sheet(("graph", reopened_index))
    wait()
    pd.testing.assert_frame_equal(app.runs[reopened_index].result.tables["Parameters: All"],
                                  expected[key][1]["Parameters: All"], rtol=1e-9)
    assert catalog == curve_models.MODELS and "A*exp(B*X)" not in curve_models.MODELS
    assert app.projects[second_project] is not None

    # 10. Italian and English: labels change, the recipe and the values do not.
    app.show("result", reopened_index)
    recipe = dict(app.runs[reopened_index].options)

    def english(dialog):
        dialog.fields.select(1)
        assert [dialog.fields.tab(i, "text") for i in range(4)] == ["Variables", "Equation", "Parameters", "Output"]
        assert dialog.controls["Equation"][1].values() == recipe["Equation"]

    def italian(dialog):
        assert [dialog.fields.tab(i, "text") for i in range(4)] == ["Variabili", "Equazione", "Coefficienti",
                                                                    "Risultati"], [
            dialog.fields.tab(i, "text") for i in range(4)]
        dialog.fields.select(1)
        editor = dialog.controls["Equation"][1]
        assert editor.values() == recipe["Equation"]
        set_equation(dialog, "A + B*X.__class__")
        editor.check()
        assert "inatteso" in editor.message.cget("text"), editor.message.cget("text")
        message = rejected(dialog, "Equation", "window-custom-equation-it.png", contains="inatteso")
        assert "Equazione" in message, message
        set_equation(dialog, recipe["Equation"])
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-custom-parameters-it.png")
        assert dialog.validate() is True
        assert dialog.result[1]["Equation"] == recipe["Equation"]
        assert dialog.result[1]["Parameters"] == recipe["Parameters"], dialog.result[1]["Parameters"]
        assert dialog.result[1]["Weighting"] == "Unweighted"

    drive(english, accept=False)
    app.edit_analysis()
    root.update()
    i18n.set_language("it")
    try:
        drive(italian, accept=False)
        app.edit_analysis()
        root.update()
    finally:
        i18n.set_language("en")
    assert app.runs[reopened_index].options == recipe
    # Leave the application idle for the checks that follow in the general smoke.
    wait()
    assert app.pending is None and not errors, errors
