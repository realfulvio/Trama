"""Desktop smoke check for the scaled Schoenfeld residuals and the Cox–Snell diagnostics of Cox regression.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=cox-fit-diagnostics``) calls :func:`check_cox_fit_diagnostics`.
Widgets are driven and events are generated. This is not a native pointer session. The check restores the
language, the window geometry and the export settings it found; it never writes the preferences file.
"""
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from tkinter import ttk

from . import cox_outputs as cox, ui_theme
from .cox_fit_diagnostics import (COX_SNELL, EVENT_TIME, SCALED, SCALED_SHEET, SNELL_COLUMN, SNELL_HAZARD_SHEET,
                                  SNELL_SHEET, SOURCE_ROW, X_AXIS)
from .data import Dataset, save_project
from . import figure_export_dialog
from .figure_export_dialog import FigureExportDialog
from .grid_data import paste_block
from .i18n import active_language, set_language, ui
from .presentation import Layout
from .workbench import analyse

METHOD = cox.METHOD
TITLE, RECOVERY = "Follow-up", "Recovery"
GRAPH, TERM = cox.GRAPH, cox.GRAPH_TERM
TERMS = ["Dose", "Arm [B]"]
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "data" / "cox-fit-diagnostics" / "followup.csv"
BASE = {"Time": "Time", "Event": "Event", "Predictors": ["Dose", "Arm"], "Categorical predictors": ["Arm"],
        "Ties": "Efron"}
EVENT_DOSE_ROW = 2   # zero-based worksheet row of source row 3: an event with Dose 3
RECOVERY_FIRST, RECOVERY_ROWS = 11, 17   # arm B is worksheet rows 11..16 of the Recovery sheet


def _frame():
    return pd.read_csv(FIXTURE)


def _recovery():
    """Arm B fills the last six rows (three events): one block edit renames the whole level."""
    frame = _frame().iloc[:17].copy()
    frame["Arm"] = ["B" if row >= RECOVERY_FIRST else "A" for row in range(len(frame))]
    return frame


def _button(dialog, text):
    pending = [dialog]
    while pending:
        widget = pending.pop()
        if isinstance(widget, ttk.Button) and widget.cget("text") == ui(text):
            return widget
        pending.extend(widget.winfo_children())
    raise AssertionError(text)


def _reachable(dialog, root, text):
    button = _button(dialog, text)
    dialog.update_idletasks()
    assert button.winfo_ismapped(), text
    bounds = root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()
    end = button.winfo_rootx() + button.winfo_width(), button.winfo_rooty() + button.winfo_height()
    assert end[0] <= bounds[0] + 1 and end[1] <= bounds[1] + 1, (text, end, bounds, dialog.geometry())
    return button


def check_cox_fit_diagnostics(root, app, directory, kit):
    directory = Path(directory)
    geometry, language = root.geometry(), active_language()
    export_session = dict(figure_export_dialog.SESSION)   # the export dialog remembers its last format
    try:
        root.geometry("1024x768+0+0")
        _check(root, app, directory, kit)
        set_language(language)
        wide = root.winfo_screenwidth() >= 1600 and root.winfo_screenheight() >= 1000
        if wide:
            root.geometry("1600x1000+0+0")
            _dialogs(root, app, directory, kit, "1600")
    finally:
        set_language(language)
        root.geometry(geometry)
        figure_export_dialog.SESSION.clear()
        figure_export_dialog.SESSION.update(export_session)


def _tools(root, app, kit):
    """Helpers shared by the checks below."""
    suffix = "-modern" if ui_theme.is_modern() else ""
    capture, pick, select, wait, errors = kit.capture, kit.pick_method, kit.select_columns, kit.wait_for_calculation, kit.errors

    def shot(widget, name):
        capture(widget, name.replace(".png", suffix + ".png"))

    def find(parent=None):
        parent = root if parent is None else parent
        for child in parent.winfo_children():
            if isinstance(child, kit.AnalysisDialog):
                return child
            found = find(child)
            if found is not None:
                return found
        return None

    def drive(action, *, accept=True):
        """Run `action(dialog)` on the next analysis dialog, then confirm (or cancel) it."""
        holder = {"done": False}
        deadline = time.monotonic() + 30

        def enter():
            dialog = find()
            if dialog is None or not dialog.winfo_viewable():
                if time.monotonic() < deadline:
                    root.after(40, enter)
                    return
                holder["error"] = TimeoutError("The analysis dialog did not open.")
                holder["done"] = True
                return
            try:
                dialog.update()
                action(dialog)
                if accept:
                    dialog.ok()
                else:
                    dialog.result = None
                    dialog.cancel()
            except Exception as error:
                holder["error"] = error
                try:
                    dialog.result = None
                    dialog.cancel()
                except Exception:
                    pass
            holder["done"] = True

        root.after(200, enter)
        return holder

    def finish(holder):
        until = time.monotonic() + 30
        while not holder["done"] and time.monotonic() < until:
            root.update()
            time.sleep(.02)
        if "error" in holder:
            raise holder["error"]
        assert holder["done"], "The dialog driver did not finish."

    def run_dialog(action, *, accept=True):
        holder = drive(action, accept=accept)
        app.choose_analysis()
        finish(holder)
        wait()
        assert not errors, errors

    def edit_dialog(index, action):
        app.show("result", index)
        holder = drive(action)
        app.edit_analysis()
        finish(holder)
        wait()
        assert not errors, errors

    def reject(dialog, field, caption):
        """The dialog refuses, stays open, names the field, shows it and moves the focus to it."""
        with patch.object(kit.messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert caption in message, (caption, message)
        assert dialog.winfo_exists() and dialog.result is None
        widget = dialog.field_rows[field][1]
        assert widget.winfo_manager() == "grid" and widget.winfo_viewable(), field
        assert dialog.focus_get() is widget, (field, dialog.focus_get())
        assert str(dialog.fields.select()) == str(widget.master), field
        return message

    def configure(dialog):
        pick(dialog, METHOD)
        dialog.controls["Time"][1].set("Time")
        dialog.controls["Event"][1].set("Event")
        select(dialog, "Predictors", {"Dose", "Arm"})
        select(dialog, "Categorical predictors", {"Arm"})
        dialog.update_cox_terms()
        dialog.update_idletasks()

    def masked(title=TITLE):
        return app.tables[title].frame(mask_excluded=True)

    def same_as_engine(index, title=TITLE):
        """The worker reproduces a direct call of the engine on the same masked table, sheet by sheet."""
        run = app.runs[index]
        expected = analyse(METHOD, masked(title), run.options)
        assert list(run.result.tables) == list(expected.tables), (list(run.result.tables), list(expected.tables))
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], table, obj=name)
        return run.result.tables

    def column(title, name):
        return list(app.tables[title].raw.columns).index(name)

    def edit_block(title, name, first, values, *, settle=True):
        """One worksheet edit that replaces `values` down a column from row `first`, as a paste of a block does."""
        app.show("data", title)
        dataset = app.get_dataset()
        left = column(title, name)
        before = app.worksheet_state(dataset)
        paste_block(dataset, first, left, [[value] for value in values])
        app.finish_worksheet_edit(dataset, before, "Edit cells", (first, left, first + len(values) - 1, left))
        if settle:
            wait()

    return {"shot": shot, "drive": drive, "finish": finish, "run_dialog": run_dialog, "edit_dialog": edit_dialog,
            "reject": reject, "configure": configure, "same": same_as_engine, "masked": masked, "column": column,
            "wait": wait, "errors": errors, "edit_block": edit_block}


def _scatter(axes):
    return np.asarray(axes.collections[0].get_offsets(), dtype=float)


def _check_snell_figure(figure, tables):
    """Step coordinates are the table rows (from the origin) and the diagonal ends at the last residual."""
    axes = figure.axes[0]
    hazard = tables[SNELL_HAZARD_SHEET]
    step, diagonal = axes.lines
    assert step.get_drawstyle() == "steps-post", step.get_drawstyle()
    points = np.asarray(step.get_xydata(), dtype=float)
    expected = hazard[["Residual", "Cumulative hazard"]].to_numpy(dtype=float)
    if not (expected[0] == 0).all():
        expected = np.vstack([[0., 0.], expected])
    np.testing.assert_allclose(points, expected)
    last = float(hazard["Residual"].iat[-1])
    np.testing.assert_allclose(np.asarray(diagonal.get_xydata(), dtype=float), [[0., 0.], [last, last]])
    jumps = int((np.diff(points[:, 1]) > 0).sum())
    assert jumps == int((hazard["Events"] > 0).sum()), (jumps, hazard["Events"].tolist())
    assert (hazard["Events"].sum() + hazard["Censored"].sum()) == len(tables[SNELL_SHEET])
    assert axes.get_legend() is not None and axes.get_xscale() == axes.get_yscale() == "linear"


def _check(root, app, directory, kit):
    tools = _tools(root, app, kit)
    shot, run_dialog, edit_dialog, reject = tools["shot"], tools["run_dialog"], tools["edit_dialog"], tools["reject"]
    configure, same, masked, column, wait, errors = (
        tools["configure"], tools["same"], tools["masked"], tools["column"], tools["wait"], tools["errors"])
    drive, finish, edit_block = tools["drive"], tools["finish"], tools["edit_block"]
    set_language("en")
    path = directory / "cox-fit-diagnostics.alab"
    save_project(path, {TITLE: Dataset(_frame()), RECOVERY: Dataset(_recovery())})
    app.import_file(path)
    app.show("data", TITLE)
    root.update()

    # 1. A view chosen before its checkbox refuses on Graph display; the term and the axis follow the view.
    def scaled_dialog(dialog):
        configure(dialog)
        assert [dialog.controls[name][1].get() for name in (SCALED, COX_SNELL)] == [False, False]
        assert [dialog.field_rows[name][1].winfo_manager() for name in (TERM, X_AXIS)] == ["", ""]
        dialog.controls[GRAPH][1].set(cox.SCALED_GRAPH)
        message = reject(dialog, GRAPH, "Turn on Scaled Schoenfeld residuals")
        assert "scaled schoenfeld" in message, message
        shot(dialog, "window-cox-fit-error-graph.png")
        dialog.controls[SCALED][1].set(True)
        dialog.update()
        assert [dialog.field_rows[name][1].winfo_manager() for name in (TERM, X_AXIS)] == ["grid", "grid"]
        assert list(dialog.field_rows[TERM][1].cget("values")) == TERMS
        assert dialog.controls[TERM][1].get() == "Dose" and dialog.controls[X_AXIS][1].get() == EVENT_TIME
        assert list(dialog.field_rows[X_AXIS][1].cget("values")) == [EVENT_TIME, SOURCE_ROW]
        dialog.controls[TERM][1].set("Arm [B]")           # a dummy term of the categorical predictor
        dialog.controls[X_AXIS][1].set(SOURCE_ROW)
        dialog.fields.select(dialog.field_rows[SCALED][0].master)
        dialog.update_idletasks()
        _reachable(dialog, root, "Run Analysis")
        _reachable(dialog, root, "Cancel")
        shot(dialog, "window-cox-fit-dialog.png")
        assert dialog.validate() is True
        recipe = dialog.result[1]
        assert (recipe[SCALED], recipe[COX_SNELL], recipe[GRAPH], recipe[TERM], recipe[X_AXIS]) == (
            True, False, cox.SCALED_GRAPH, "Arm [B]", SOURCE_ROW), recipe
        dialog.result = None

    run_dialog(scaled_dialog)
    scaled = len(app.runs) - 1
    tables = same(scaled)
    assert list(tables) == ["Coefficients", "Model", "Reference levels", SCALED_SHEET], list(tables)
    sheet = tables[SCALED_SHEET]
    assert sheet["Source row"].tolist() == [2, 3, 6, 7, 9, 11, 12, 15, 17], sheet["Source row"].tolist()
    app.show("graph", scaled)
    root.update()
    axes = app.runs[scaled].result.figure.axes[0]
    np.testing.assert_allclose(_scatter(axes), sheet[["Source row", "Arm [B]"]].to_numpy(dtype=float))
    assert axes.get_xlabel() == "Source row" and len(axes.lines) == 1 and not np.asarray(axes.lines[0].get_ydata(), dtype=float).any()
    shot(root, "window-cox-fit-scaled-row.png")
    app.show("result", scaled)
    app.result_tabs.select(list(tables).index(SCALED_SHEET))
    root.update()
    shot(root, "window-cox-fit-scaled-sheet.png")

    # 2. Alternate the axis and the term through the edit dialog; the raw residuals coexist.
    def alternate(dialog):
        assert dialog.controls[SCALED][1].get() is True and dialog.controls[X_AXIS][1].get() == SOURCE_ROW
        assert dialog.controls[TERM][1].get() == "Arm [B]"
        dialog.controls[X_AXIS][1].set(EVENT_TIME)
        dialog.controls[TERM][1].set("Dose")
        dialog.controls[cox.SCHOENFELD][1].set(True)
        dialog.update_idletasks()
        _reachable(dialog, root, "Run Analysis")

    edit_dialog(scaled, alternate)
    tables = same(scaled)
    assert list(tables)[-2:] == ["Schoenfeld residuals", SCALED_SHEET], list(tables)
    sheet = tables[SCALED_SHEET]
    app.show("graph", scaled)
    root.update()
    axes = app.runs[scaled].result.figure.axes[0]
    np.testing.assert_allclose(_scatter(axes), sheet[["Time", "Dose"]].to_numpy(dtype=float))
    assert axes.get_xlabel() == "Time" and axes.get_title() == "Scaled Schoenfeld residuals: Dose"
    shot(root, "window-cox-fit-scaled-time.png")
    assert app.runs[scaled].options[X_AXIS] == EVENT_TIME

    # 3. The Cox–Snell view: jumps and diagonal coordinates agree with the tables.
    def snell_dialog(dialog):
        configure(dialog)
        dialog.controls[COX_SNELL][1].set(True)
        dialog.controls[GRAPH][1].set(cox.SNELL_GRAPH)
        dialog.update()
        assert [dialog.field_rows[name][1].winfo_manager() for name in (TERM, X_AXIS)] == ["", ""]
        dialog.fields.select(dialog.field_rows[COX_SNELL][0].master)
        dialog.update_idletasks()
        shot(dialog, "window-cox-fit-snell-dialog.png")

    run_dialog(snell_dialog)
    snell = len(app.runs) - 1
    tables = same(snell)
    assert list(tables)[3:] == [SNELL_SHEET, SNELL_HAZARD_SHEET], list(tables)
    assert 8 not in tables[SNELL_SHEET]["Source row"].tolist()      # the row with an empty Dose
    assert (tables[SNELL_SHEET][SNELL_COLUMN] >= 0).all() and tables[SNELL_SHEET]["Event"].sum() == 9
    app.show("graph", snell)
    root.update()
    _check_snell_figure(app.runs[snell].result.figure, tables)
    shot(root, "window-cox-fit-snell-graph.png")
    for name in (SNELL_SHEET, SNELL_HAZARD_SHEET):
        app.show("result", snell)
        app.result_tabs.select(list(tables).index(name))
        root.update()
        shot(root, "window-cox-fit-snell-" + ("residuals" if name == SNELL_SHEET else "hazard") + ".png")

    # 4. One more analysis with every output: the earlier sheets keep their order; Automatic keeps the old priority.
    def everything(dialog):
        configure(dialog)
        dialog.controls[cox.PREDICT][1].set(True)
        editor = dialog.controls[cox.PROFILES][1]
        editor.label.set("Reference")
        editor.inputs["Dose"].set("1")
        editor.inputs["Arm"].set("A")
        assert editor.add()
        for name in (cox.DIAGNOSTICS, cox.SCHOENFELD, SCALED, COX_SNELL):
            dialog.controls[name][1].set(True)
        dialog.update()
        assert dialog.controls[GRAPH][1].get() == cox.AUTOMATIC

    run_dialog(everything)
    full = len(app.runs) - 1
    tables = same(full)
    assert list(tables) == ["Coefficients", "Model", "Reference levels", "Baseline survival", "Predicted survival",
                            "Cox residuals", "Schoenfeld residuals", SCALED_SHEET, SNELL_SHEET,
                            SNELL_HAZARD_SHEET], list(tables)
    assert app.runs[full].result.figure.axes[0].get_title() == "Predicted survival (Cox)"
    np.testing.assert_array_equal(tables[SNELL_SHEET][SNELL_COLUMN].to_numpy(), tables["Cox residuals"]["Expected events"])

    # 5. An excluded predictor cell of an event and an edited time recalculate every sheet and graph.
    before = app.runs[scaled].result.tables[SCALED_SHEET]["Source row"].tolist()
    app.show("data", TITLE)
    app.current_grid.active_cell = (EVENT_DOSE_ROW, column(TITLE, "Dose"))
    app.toggle_exclusion()
    wait()
    for index in (scaled, snell, full):
        after = same(index)
    rows = app.runs[scaled].result.tables[SCALED_SHEET]["Source row"].tolist()
    assert 3 in before and 3 not in rows and len(rows) == len(before) - 1, (before, rows)
    assert 3 not in app.runs[snell].result.tables[SNELL_SHEET]["Source row"].tolist()
    _check_snell_figure(app.runs[snell].result.figure, app.runs[snell].result.tables)
    app.show("data", TITLE)
    time_before = app.runs[snell].result.tables[SNELL_HAZARD_SHEET].copy()
    app.edit_cell(4, column(TITLE, "Time"), "11.5")      # source row 5: a censoring at 3 moves to 11.5
    wait()
    for index in (scaled, snell, full):
        same(index)
    assert not np.array_equal(app.runs[snell].result.tables[SNELL_HAZARD_SHEET]["Residual"].to_numpy(),
                              time_before["Residual"].to_numpy())
    _check_snell_figure(app.runs[snell].result.figure, app.runs[snell].result.tables)
    app.show("graph", snell)
    root.update()
    shot(root, "window-cox-fit-snell-edited.png")

    # 6. Worker errors. A failure that names a control reopens the dialog on it and keeps the last good result;
    #    a refit that fails without naming one leaves no result, as every Cox recalculation did before.
    def recovery_dialog(dialog):
        configure(dialog)
        dialog.controls[SCALED][1].set(True)
        dialog.controls[GRAPH][1].set(cox.SCALED_GRAPH)
        dialog.controls[TERM][1].set("Arm [B]")

    app.show("data", RECOVERY)
    run_dialog(recovery_dialog)
    rec = len(app.runs) - 1
    assert app.runs[rec].options[TERM] == "Arm [B]"
    same(rec, RECOVERY)
    block = RECOVERY_ROWS - RECOVERY_FIRST
    seen = {}

    def reopened(dialog, fixed_term, *, accept):
        seen["focus"] = dialog.focus_get() is dialog.field_rows[TERM][1]
        seen["shown"] = dialog.field_rows[TERM][1].winfo_manager() == "grid"
        seen["banner"] = dialog.error
        seen["terms"] = list(dialog.field_rows[TERM][1].cget("values"))
        seen["kept"] = (dialog.controls[SCALED][1].get(), dialog.controls[GRAPH][1].get(),
                        dialog.controls[X_AXIS][1].get())
        shot(dialog, "window-cox-fit-recovery.png")
        if accept:
            dialog.controls[TERM][1].set(fixed_term)

    # 6a. The whole level B is renamed in one edit: the Schoenfeld term of the recipe is gone.
    kept = app.runs[rec].result
    holder = drive(lambda dialog: reopened(dialog, "Arm [C]", accept=True))
    edit_block(RECOVERY, "Arm", RECOVERY_FIRST, ["C"] * block, settle=False)
    wait()
    finish(holder)
    wait()
    assert seen["focus"] and seen["shown"], seen
    assert "Schoenfeld term" in seen["banner"] and "Arm [C]" in seen["banner"], seen
    assert seen["terms"] == ["Dose", "Arm [C]"] and seen["kept"] == (True, cox.SCALED_GRAPH, EVENT_TIME), seen
    fixed = app.runs[rec]
    assert fixed.options[TERM] == "Arm [C]" and fixed.options[SCALED] is True and fixed.calculation_error is None
    assert fixed.result is not kept and list(fixed.result.tables[SCALED_SHEET].columns)[2:] == ["Dose", "Arm [C]"]
    same(rec, RECOVERY)

    # 6b. The level comes back and the dialog is cancelled: the last good result stays, marked as stale.
    good = app.runs[rec].result
    holder = drive(lambda dialog: reopened(dialog, "Arm [B]", accept=False), accept=False)
    edit_block(RECOVERY, "Arm", RECOVERY_FIRST, ["B"] * block, settle=False)
    wait()
    finish(holder)
    wait()
    stale = app.runs[rec]
    assert stale.result is good and stale.calculation_error and stale.options[TERM] == "Arm [C]", stale.calculation_error
    assert "Choose one of the model terms" in stale.calculation_error, stale.calculation_error
    app.show("result", rec)
    note = app.stale_calculation_note()
    assert note and "Arm [B]" in note, note
    shot(root, "window-cox-fit-stale.png")
    edit_dialog(rec, lambda dialog: dialog.controls[TERM][1].set("Arm [B]"))
    assert app.runs[rec].calculation_error is None and app.runs[rec].options[TERM] == "Arm [B]"
    same(rec, RECOVERY)

    # 6c. A refit that cannot be done and names no control (one level left in Arm): no partial result at all.
    edit_block(RECOVERY, "Arm", 0, ["A"] * RECOVERY_ROWS, settle=False)
    wait()
    assert app.runs[rec].result is None, "a failed refit must not leave a partial result"
    assert "need attention" in app.status.get() and "must have 2 to 100 levels" in app.status.get(), app.status.get()
    edit_block(RECOVERY, "Arm", RECOVERY_FIRST, ["B"] * block)
    assert app.runs[rec].result is not None and app.runs[rec].calculation_error is None
    same(rec, RECOVERY)

    # 7. Inspector: Apply keeps the analysis recipe as it was and the figure editable; Discard restores the style.
    app.show("graph", snell)
    root.update()
    keys = ("Time", "Event", "Predictors", "Categorical predictors", "Ties", SCALED, COX_SNELL, GRAPH, TERM, X_AXIS)
    recipe = {key: app.runs[snell].options.get(key) for key in keys}
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector is not None
    inspector.vars["title"].set("Cox–Snell check")
    inspector._now("title")
    inspector.vars["legend"].set("lower right")
    inspector._now("legend")
    assert inspector.apply() is True, inspector.status.cget("text")
    axes = app.runs[snell].result.figure.axes[0]
    assert axes.get_title() == "Cox–Snell check", axes.get_title()
    assert axes.get_legend()._get_loc() == 4, axes.get_legend()._get_loc()
    inspector.vars["title"].set("Discarded title")
    inspector._now("title")
    assert app.runs[snell].result.figure.axes[0].get_title() == "Discarded title"
    inspector.discard()
    assert app.runs[snell].result.figure.axes[0].get_title() == "Cox–Snell check"
    root.update()
    shot(root, "window-cox-fit-inspector.png")
    app.toggle_inspector()
    assert {key: app.runs[snell].options.get(key) for key in keys} == recipe, "the Inspector changed the recipe"

    # 8. Use Result as Data on both diagnostic tables.
    app.show("result", snell)
    for name in (SNELL_SHEET, SNELL_HAZARD_SHEET):
        app.show("result", snell)
        app.result_tabs.select(list(app.runs[snell].result.tables).index(name))
        known = set(app.tables)
        app.use_result_as_data()
        created = set(app.tables) - known
        assert len(created) == 1, created
        copied = app.tables[created.pop()].raw
        pd.testing.assert_frame_equal(copied.reset_index(drop=True), app.runs[snell].result.tables[name].reset_index(drop=True),
                                      check_dtype=False)

    # 9. A layout with the scaled and the Cox–Snell graphs exports as a two-panel PDF.
    app.layouts.append(Layout("Cox checks", 2, [app.runs[scaled].reference, app.runs[snell].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-cox-fit-layout.png")
    target = directory / "cox-fit-layout.pdf"
    problems = []

    def pdf(dialog):
        try:
            dialog.format.set("PDF")
            dialog.update()
        except Exception as error:
            problems.append(error)

    kit.drive_dialog(FigureExportDialog, pdf)
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)), patch.object(app, "error") as error:
        app.export_with_options()
    assert not problems and not error.called, (problems, error.call_args)
    from .pdf_bundle_smoke import read_pdf

    [(size, text, images)] = read_pdf(target)
    assert "Cox checks" in text and images == 0, (text, images)
    assert "Scaled Schoenfeld residuals: Dose" in text and "Cumulative hazard of the residuals" in text, text
    assert "y = x" in text and "Estimated cumulative hazard of the residuals" in text, text

    # 10. Save, then reopen with the graph first: the recipes stay canonical and the figures are rebuilt.
    app.show("data", TITLE)
    assert app.save()
    app.import_file(app.path)
    assert app.runs[snell].result is None
    app.open_sheet(("graph", snell))
    wait()
    reopened_run = app.runs[snell]
    assert reopened_run.options[COX_SNELL] is True and reopened_run.options[GRAPH] == cox.SNELL_GRAPH
    assert reopened_run.options.get(X_AXIS) is None
    same(snell)
    _check_snell_figure(reopened_run.result.figure, reopened_run.result.tables)
    root.update()
    shot(root, "window-cox-fit-reopen.png")
    app.open_sheet(("graph", scaled))
    wait()
    assert app.runs[scaled].options[X_AXIS] == EVENT_TIME and app.runs[scaled].options[TERM] == "Dose"
    same(scaled)

    # 11. Recipes saved before the new keys keep their sheets, order and graph.
    legacy = {**BASE, cox.PREDICT: True, cox.PROFILES: [{"Label": "A", "Values": {"Dose": 1, "Arm": "A"}}],
              cox.DIAGNOSTICS: True, cox.SCHOENFELD: True}
    old = directory / "cox-fit-legacy.alab"
    save_project(old, {"Old Cox": Dataset(_frame(), analyses=[(METHOD, legacy)])})
    app.import_file(old)
    app.open_sheet(("result", 0))
    wait()
    result = app.runs[0].result
    assert list(result.tables) == ["Coefficients", "Model", "Reference levels", "Baseline survival",
                                   "Predicted survival", "Cox residuals", "Schoenfeld residuals"], list(result.tables)
    assert result.figure.axes[0].get_title() == "Predicted survival (Cox)"
    assert SCALED not in app.runs[0].options and COX_SNELL not in app.runs[0].options

    # 12. The Italian dialog: translated captions and choices, canonical recipe, translated messages.
    app.import_file(path)
    _dialogs(root, app, directory, kit, "1024")
    assert not errors, errors


def _dialogs(root, app, directory, kit, size):
    """Open the real dialog in Italian and in English at the current size and check what the user sees."""
    tools = _tools(root, app, kit)
    shot, reject, configure = tools["shot"], tools["reject"], tools["configure"]
    drive, finish, errors = tools["drive"], tools["finish"], tools["errors"]
    if TITLE not in app.tables:
        app.import_file(directory / "cox-fit-diagnostics.alab")
    app.show("data", TITLE)
    root.update()
    for language in ("it", "en"):
        set_language(language)
        seen = {}

        def action(dialog):
            configure(dialog)
            labels = [dialog.field_rows[name][0].cget("text") for name in (SCALED, COX_SNELL, X_AXIS)]
            dialog.controls[GRAPH][1].set(cox.SNELL_GRAPH)
            caption = ui(COX_SNELL)
            message = reject(dialog, GRAPH, caption)
            seen["message"], seen["labels"] = message, labels
            dialog.controls[SCALED][1].set(True)
            dialog.controls[GRAPH][1].set(cox.SCALED_GRAPH)
            dialog.controls[X_AXIS][1].set(SOURCE_ROW)
            dialog.controls[TERM][1].set("Arm [B]")
            dialog.fields.select(dialog.field_rows[SCALED][0].master)
            dialog.update()
            seen["graph"] = dialog.field_rows[GRAPH][1].get()
            seen["axis"] = dialog.field_rows[X_AXIS][1].get()
            _reachable(dialog, root, "Run Analysis")
            shot(dialog, f"window-cox-fit-dialog-{language}-{size}.png")
            assert dialog.validate() is True
            seen["recipe"] = dict(dialog.result[1])
            dialog.result = None

        holder = drive(action, accept=False)
        app.choose_analysis()
        finish(holder)
        assert not errors, errors
        recipe = seen["recipe"]
        # The recipe holds canonical English values whatever the language on screen.
        assert (recipe[GRAPH], recipe[X_AXIS], recipe[TERM], recipe[SCALED]) == (cox.SCALED_GRAPH, SOURCE_ROW,
                                                                                  "Arm [B]", True), recipe
        if language == "it":
            assert seen["labels"] == ["Residui di Schoenfeld scalati", "Diagnostica Cox–Snell", "Asse X di Schoenfeld"], seen
            assert (seen["graph"], seen["axis"]) == ("Schoenfeld scalati", "Riga di origine"), seen
            assert "Attiva Diagnostica Cox–Snell" in seen["message"], seen["message"]
        else:
            assert seen["labels"] == [SCALED, COX_SNELL, X_AXIS] and seen["graph"] == cox.SCALED_GRAPH, seen
            assert "Turn on Cox-Snell diagnostics" in seen["message"], seen["message"]
    set_language("en")
