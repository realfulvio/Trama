"""Desktop smoke check for Cox regression with exact conditional ties, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_cox_exact_ties` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=cox-exact-ties python tramastat.py --smoke DIR``.

Synthetic data only. The expected coefficients are the frozen solution of the enumerated likelihood of the 11-row
table (every subset of every risk set listed, score root to 1e-12); no number below is computed by the module under
test, except where a step says it recalculates the same recipe through the dispatcher to prove that the dialog, the
worker and the saved recipe agree. The check runs the same scenario in English and in Italian and writes a report to
``DIR/cox-exact-ties``.
"""
import json
import threading
import time
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import cox_exact, i18n, models
from .data import Dataset
from .workbench import analyse

METHOD = "Cox regression"
EXACT = "Exact (conditional)"
TIED, SEPARATED, BUDGET, EFRON = "Tied times", "Separation", "Budget", "Efron predictions"
# Time 1 and time 3 carry two events each; row 3 is censored at time 1; Marker is empty in the last row.
TIED_FRAME = pd.DataFrame({
    "Time": [1, 1, 1, 2, 3, 3, 4, 4, 5, 6, 7],
    "Status": ["Event", "Event", "Censored", "Event", "Event", "Event", "Censored", "Event", "Event", "Censored",
               "Censored"],
    "Marker": [0, 1, 3, 2, 0, 3, 1, 2, 3, 0, None],
    "Group": list("ABAABAABBAB")})
BETA = [-0.030136728866362414, 0.51699868904825]
SE = [0.3418917793255356, 0.8571422430888186]
LOG_LIKELIHOOD, EVENTS, TIED_TIMES = -10.34738621201979, 7, 2
# Arm separates the events from the rest of every risk set; Other does not.
SEPARATED_FRAME = pd.DataFrame({"Time": [1, 1, 2, 2, 3, 4, 5, 6], "Status": ["Event"] * 4 + ["Censored"] * 4,
                                "Arm": [1, 1, 1, 1, 0, 0, 0, 0], "Other": [3, 1, 2, 1, 2, 3, 1, 2]})
PROFILES = [{"Label": "Low, A", "Values": {"Marker": 0, "Group": "A"}},
            {"Label": "High, B", "Values": {"Marker": 3, "Group": "B"}}]
MAIN = {"Time": "Time", "Event": "Status", "Predictors": ["Marker", "Group"], "Categorical predictors": ["Group"],
        "Event value": "Event", "Censor value": "Censored"}


def budget_frame():
    rows = np.arange(2001)
    return pd.DataFrame({"Time": rows // 2 + 1, "Status": np.where(rows % 3, "Event", "Censored"),
                         "Marker": rows % 7, "Group": np.where(rows % 2, "A", "B")})


def check_cox_exact_ties(root, app, directory, tools):
    """Run the scenario in English, then the essential part of it in Italian."""
    language = i18n.active_language()
    try:
        report = {"checks": [], "messages": {}}
        for locale in ("en", "it"):
            i18n.set_language(locale)
            _check(root, app, directory, tools, locale, report)
        out = directory / "cox-exact-ties"
        (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        i18n.set_language(language)


def _check(root, app, directory, tools, locale, report):
    italian = locale == "it"
    errors, wait = tools.errors, tools.wait_for_calculation
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "cox-exact-ties"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{locale}" + (f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else "")
    names = {title: f"{title} {locale}" for title in (TIED, SEPARATED, BUDGET, EFRON)}
    tools.save_project(directory / f"cox-exact-ties-{locale}.alab", {
        names[TIED]: Dataset(TIED_FRAME.copy()), names[SEPARATED]: Dataset(SEPARATED_FRAME.copy()),
        names[BUDGET]: Dataset(budget_frame()), names[EFRON]: Dataset(TIED_FRAME.copy())})
    app.import_file(directory / f"cox-exact-ties-{locale}.alab")

    def done(name):
        report["checks"].append(f"{locale}: {name}")

    def shot(window, name):
        stem, extension = name.rsplit(".", 1)
        tools.capture(window, f"{stem}{suffix}.{extension}")
        if (directory / f"{stem}{suffix}.{extension}").exists():
            (directory / f"{stem}{suffix}.{extension}").replace(out / f"{stem}{suffix}.{extension}")

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def note_shown(dialog, key):
        return [note for note in dialog.cox_notes if note.cget("text") == i18n.tr(key) and note.winfo_manager()]

    def run_button(dialog):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == i18n.ui("Run Analysis"):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog):
        """Run Analysis and every tab lie inside the screen at the current size."""
        dialog.update()
        button = run_button(dialog)
        assert button is not None and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= screen[1], (button.winfo_rooty(), screen)
        assert button.winfo_rootx() + button.winfo_width() <= screen[0]
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def fill(dialog, **extra):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Time"][1].set("Time")
        dialog.controls["Event"][1].set("Status")
        tools.select_columns(dialog, "Predictors", {"Marker", "Group"})
        tools.select_columns(dialog, "Categorical predictors", {"Group"})
        dialog.update_cox_terms()
        dialog.controls["Event value"][1].set("Event")
        dialog.controls["Censor value"][1].set("Censored")
        for name, value in extra.items():
            dialog.controls[name.replace("_", " ")][1].set(value)

    def add_profiles(dialog):
        editor = dialog.controls["Profiles"][1]
        for profile in PROFILES:
            editor.label.set(profile["Label"])
            for name, value in profile["Values"].items():
                editor.inputs[name].set(str(value))
            assert editor.add()
        return editor

    def drive(action):
        """Drive the next AnalysisDialog, which the worker reopens on a field error; ``settle`` waits for its run."""
        state = {"done": False}

        def wrapped(dialog):
            try:
                action(dialog)
            finally:
                state["done"] = True

        tools.drive_dialog(tools.AnalysisDialog, wrapped)
        return state

    def settle(state):
        deadline = time.monotonic() + 40
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, ("the analysis did not finish", state, app.pending, errors)
            root.update()
            time.sleep(.02)
        assert not errors, errors

    def analyse_with(title, first, recovered=None):
        """New analysis on ``title``; ``first`` drives the dialog, ``recovered`` the dialog reopened on a field error."""
        app.show("data", names[title])
        before = len(app.runs)
        drive(first)
        app.choose_analysis()
        if recovered is not None:
            settle(drive(recovered))
        else:
            wait()
        return before

    def results(index):
        return app.runs[index].result.tables

    def expect_exact_tables(tables):
        coefficients, model = tables["Coefficients"], tables["Model"]["Value"]
        assert list(tables) == ["Coefficients", "Model", "Reference levels"], list(tables)
        assert list(coefficients.index) == ["Marker", "Group [B]"]
        np.testing.assert_allclose(coefficients["Estimate"], BETA, rtol=2e-6)
        np.testing.assert_allclose(coefficients["SE"], SE, rtol=2e-6)
        np.testing.assert_allclose(model["Log likelihood"], LOG_LIKELIHOOD, rtol=1e-8)
        np.testing.assert_allclose(model["AIC"], -2 * LOG_LIKELIHOOD + 4, rtol=1e-8)
        assert (model["N"], model["Incomplete rows"], model["Ties"]) == (10, 1, EXACT), model
        assert (model["Events"], model["Tied event times"]) == (EVENTS, TIED_TIMES), model

    # 1. The dialog. Ties offers Exact after the two historical choices; the notes appear with it and name what it
    # refuses. Predict survival (with two profiles) and Cox diagnostics are refused by Run Analysis on their own control,
    # the dialog stays open with nothing lost, and turning them off lets the fit through.
    def first_dialog(dialog):
        fill(dialog)
        ties = dialog.field_rows["Ties"][1]
        shown = list(ties.cget("values"))
        assert shown == ["Efron", "Breslow", i18n.tr("cox.exact.choice")], shown
        assert dialog.controls["Ties"][1].get() == "Efron" and not dialog.cox_notes[0].winfo_manager()
        dialog.controls["Ties"][1].set(EXACT)
        dialog.update()
        assert dialog.controls["Ties"][1].get() == EXACT, "the variable keeps the canonical value"
        assert ties.get() == i18n.tr("cox.exact.choice")
        assert note_shown(dialog, "cox.exact.hint"), "the note on the Ties page"
        dialog.controls["Predict survival"][1].set(True)
        dialog.update()
        assert placed(dialog, "Profiles")
        editor = add_profiles(dialog)
        assert len(editor.values()) == 2
        dialog.fields.select(page_of(dialog, "Predict survival"))
        dialog.update()
        assert len(note_shown(dialog, "cox.exact.unavailable")) >= 1
        shot(dialog, "window-cox-exact-unavailable.png")
        with patch.object(tools.messagebox, "showerror") as shown:
            assert dialog.validate() is False
        message = shown.call_args.args[1]
        assert i18n.ui("Predict survival") in message, message
        assert dialog.fields.select() == page_of(dialog, "Predict survival"), "the tab of the refused control"
        assert dialog.controls["Ties"][1].get() == EXACT, "no other estimator was substituted"
        assert [p["Label"] for p in editor.values()] == [p["Label"] for p in PROFILES], "the profiles are kept"
        report["messages"][f"{locale}-predict"] = message
        dialog.controls["Predict survival"][1].set(False)
        dialog.controls["Cox diagnostics"][1].set(True)
        with patch.object(tools.messagebox, "showerror") as shown:
            assert dialog.validate() is False
        message = shown.call_args.args[1]
        assert i18n.ui("Cox diagnostics") in message, message
        assert dialog.fields.select() == page_of(dialog, "Cox diagnostics")
        report["messages"][f"{locale}-diagnostics"] = message
        shot(dialog, "window-cox-exact-refused.png")
        dialog.controls["Cox diagnostics"][1].set(False)
        assert [p["Label"] for p in editor.values()] == [p["Label"] for p in PROFILES], "the profiles are kept"
        dialog.fields.select(page_of(dialog, "Ties"))
        dialog.update()
        shot(dialog, "window-cox-exact-dialog.png")
        reachable(dialog)
        with patch.object(tools.messagebox, "showerror") as shown:
            assert dialog.validate() is True, shown.call_args
        dialog.result = None

    before = len(app.runs)
    app.show("data", names[TIED])
    tools.drive_dialog(tools.AnalysisDialog, first_dialog)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    assert len(app.runs) == before + 1 and app.runs[index].method == METHOD
    options = app.runs[index].options
    assert options["Ties"] == EXACT and not options["Predict survival"] and not options["Cox diagnostics"], options
    assert [p["Label"] for p in options.get("Profiles", [])] in ([], [p["Label"] for p in PROFILES]), options
    expect_exact_tables(results(index))
    assert app.runs[index].result.figure is None, "Exact draws nothing"
    done("Exact in the dialog: notes, refusal of Predict survival and Cox diagnostics on their own tab, then the fit")

    app.show("result", index)
    shot(app.root, "window-cox-exact-coefficients.png")
    app.result_tabs.select(1)
    shot(app.root, "window-cox-exact-model.png")
    done("Coefficients and Model sheets on screen")

    # 2. CSV of each sheet, Use Result as Data and the saved project.
    for position, name in enumerate(results(index)):
        app.result_tabs.select(position)
        target = out / f"cox-exact-{locale}-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Coefficients":
            np.testing.assert_allclose(exported["Estimate"], BETA, rtol=2e-6)
            assert list(exported.columns) == list(results(index)["Coefficients"].columns)
        if name == "Model":
            assert exported.loc["Ties", "Value"] == EXACT and int(float(exported.loc["Events", "Value"])) == EVENTS
    done("CSV of every sheet")
    created_before = set(app.tables)
    app.show("result", index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    wait()
    created = set(app.tables) - created_before
    assert len(created) == 1, created
    sheet = app.tables[next(iter(created))].raw
    assert {"Estimate", "SE"} <= set(sheet.columns), list(sheet.columns)
    np.testing.assert_allclose(sheet["Estimate"].astype(float), BETA, rtol=2e-6)
    done("Use Result as Data on the Coefficients sheet")

    # 3. Cancel a new fit, then a recalculation that has a result to keep. The fit waits on a gate inside the worker,
    # so Cancel is requested while it runs; the engine then looks at the token before computing anything.
    def gated():
        gate, real = threading.Event(), cox_exact.fit_exact

        def slow(*args, **kwargs):
            gate.wait(20)
            return real(*args, **kwargs)

        return gate, patch.object(cox_exact, "fit_exact", slow)

    gate, patcher = gated()
    runs_before = len(app.runs)
    with patcher:
        app.show("data", names[EFRON])
        tools.drive_dialog(tools.AnalysisDialog, lambda dialog: (fill(dialog, Ties=EXACT)))
        app.choose_analysis()
        assert app.calculation is not None, "an exact fit offers Cancel"
        app.cancel_calculation()
        gate.set()
        wait()
    assert len(app.runs) == runs_before, "a cancelled new fit adds nothing"
    assert app.status.get() == i18n.tr("cox.exact.cancelled.new"), app.status.get()
    done("Cancel of a new exact fit adds nothing")

    keep = index
    kept = results(keep)
    kept_copy = {name: frame.copy() for name, frame in kept.items()}
    gate, patcher = gated()
    with patcher:
        app.show("result", keep)
        tools.drive_dialog(tools.AnalysisDialog, lambda dialog: dialog.controls["Predictors"][1].selection_clear(0, "end")
                           or tools.select_columns(dialog, "Predictors", {"Marker"})
                           or tools.select_columns(dialog, "Categorical predictors", set()))
        app.edit_analysis()
        assert app.calculation is not None
        app.cancel_calculation()
        gate.set()
        wait()
    assert app.runs[keep].result.tables is kept and app.runs[keep].options["Predictors"] == ["Marker", "Group"]
    assert app.status.get() == i18n.tr("cox.exact.cancelled.kept"), app.status.get()
    done("Cancel of an edit keeps the last completed results and the confirmed recipe")

    column = app.tables[names[TIED]].raw.columns.get_loc("Marker")
    gate, patcher = gated()
    with patcher:
        app.show("data", names[TIED])
        app.edit_cell(0, column, "2")
        assert app.calculation is not None, "a recalculation offers Cancel too"
        app.cancel_calculation()
        gate.set()
        wait()
    assert app.runs[keep].result is not None
    for name, frame in kept_copy.items():
        pd.testing.assert_frame_equal(app.runs[keep].result.tables[name], frame)
    note = app.stale_calculation_note(("result", keep))
    assert note and cox_exact.translate_error("The exact Cox recalculation was cancelled.") in note, note
    assert app.status.get() == i18n.tr("cox.exact.cancelled.recalculation"), app.status.get()
    app.show("result", keep)
    shot(app.root, "window-cox-exact-stale.png")
    app.recalculate(keep)
    wait()
    assert app.stale_calculation_note(("result", keep)) is None and app.runs[keep].calculation_error is None
    assert results(keep)["Coefficients"]["Estimate"].tolist() != BETA, "the edited Marker value changes the fit"
    app.show("data", names[TIED])
    app.edit_cell(0, column, "0")
    wait()
    expect_exact_tables(results(keep))
    done("Cancel of a recalculation keeps the result marked stale; Recalculate completes it")

    # 4. An excluded cell recalculates against the dispatcher; the saved project reopens to the same tables.
    app.show("data", names[TIED])
    app.current_grid.select((5, column))
    app.toggle_exclusion()
    wait()
    want = analyse(METHOD, app.tables[names[TIED]].frame(mask_excluded=True), dict(app.runs[keep].options))
    for name, frame in want.tables.items():
        pd.testing.assert_frame_equal(results(keep)[name], frame)
    assert results(keep)["Model"]["Value"]["Incomplete rows"] == 2
    app.current_grid.select((5, column))
    app.toggle_exclusion()
    wait()
    expect_exact_tables(results(keep))
    app.path = directory / f"cox-exact-saved-{locale}.alab"
    assert app.save()
    (out / f"roundtrip-{locale}.alab").write_bytes(app.path.read_bytes())
    saved = {(r.title, r.slot): (dict(r.options), {k: v.copy() for k, v in r.result.tables.items()})
             for r in app.runs if r.result is not None and r.method == METHOD}
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("result", position))
            wait()
    for run in app.runs:
        if run.method == METHOD and (run.title, run.slot) in saved:
            options_before, tables_before = saved[(run.title, run.slot)]
            assert run.options == options_before and run.options["Ties"] == EXACT
            for name, frame in tables_before.items():
                pd.testing.assert_frame_equal(run.result.tables[name], frame)
    done("excluded cell recalculates like the dispatcher; the project reopens to the same recipe and tables")

    # 5. An Efron recipe with predictions is not touched. Switching it to Exact keeps the profiles in the dialog.
    def efron(dialog):
        fill(dialog)
        dialog.controls["Predict survival"][1].set(True)
        add_profiles(dialog)
        dialog.controls["Cox diagnostics"][1].set(True)

    app.show("data", names[EFRON])
    before = len(app.runs)
    tools.drive_dialog(tools.AnalysisDialog, efron)
    app.choose_analysis()
    wait()
    efron_index = len(app.runs) - 1
    assert len(app.runs) == before + 1 and app.runs[efron_index].options["Ties"] == "Efron"
    efron_tables = {name: frame.copy() for name, frame in results(efron_index).items()}
    assert {"Baseline survival", "Predicted survival", "Cox residuals"} <= set(efron_tables), list(efron_tables)
    assert app.runs[efron_index].result.figure is not None
    legacy = models.cox_regression(app.tables[names[EFRON]].frame(mask_excluded=True).assign(
        Status=lambda frame: frame["Status"].eq("Event").astype(float)), "Time", "Status", ["Marker", "Group"],
        ["Group"], "efron")
    for name in ("Coefficients", "Model"):
        pd.testing.assert_frame_equal(efron_tables[name], legacy[name])
    done("an Efron recipe with predictions keeps its sheets, figure and the legacy coefficients")

    def to_exact(dialog):
        assert [p["Label"] for p in dialog.controls["Profiles"][1].values()] == [p["Label"] for p in PROFILES]
        dialog.controls["Ties"][1].set(EXACT)
        dialog.update()
        assert note_shown(dialog, "cox.exact.unavailable")
        with patch.object(tools.messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert i18n.ui("Predict survival") in shown.call_args.args[1], shown.call_args
        assert dialog.fields.select() == page_of(dialog, "Predict survival")
        assert dialog.controls["Predict survival"][1].get() is True, "the preference is not discarded"
        assert [p["Label"] for p in dialog.controls["Profiles"][1].values()] == [p["Label"] for p in PROFILES]
        dialog.controls["Ties"][1].set("Efron")
        assert not any(note.winfo_manager() for note in dialog.cox_notes)

    app.show("result", efron_index)
    tools.drive_dialog(tools.AnalysisDialog, to_exact)
    app.edit_analysis()
    wait()
    assert app.runs[efron_index].options["Ties"] == "Efron"
    for name, frame in efron_tables.items():
        pd.testing.assert_frame_equal(results(efron_index)[name], frame)
    done("an older Efron recipe with predictions is refused when switched to Exact and returns unchanged")

    # 6. Limits and separation: an error on the field, then the correction. No estimator is substituted.
    def over_budget(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Time"][1].set("Time")
        dialog.controls["Event"][1].set("Status")
        tools.select_columns(dialog, "Predictors", {"Marker", "Group"})
        tools.select_columns(dialog, "Categorical predictors", {"Group"})
        dialog.update_cox_terms()
        dialog.controls["Event value"][1].set("Event")
        dialog.controls["Censor value"][1].set("Censored")
        dialog.controls["Ties"][1].set(EXACT)

    def budget_banner(dialog):
        banner = dialog.error_label.cget("text")
        assert dialog.initial_field == "Ties" and "2000" in banner and "2001" in banner, banner
        assert dialog.fields.select() == page_of(dialog, "Ties")
        shot(dialog, "window-cox-exact-budget.png")
        dialog.controls["Ties"][1].set("Efron")

    runs = len(app.runs)
    analyse_with(BUDGET, over_budget, budget_banner)
    assert len(app.runs) == runs + 1 and app.runs[-1].options["Ties"] == "Efron" and app.runs[-1].result is not None
    done("2001 rows: error on Ties, no automatic fallback, the user chooses Efron")

    def separated(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Time"][1].set("Time")
        dialog.controls["Event"][1].set("Status")
        tools.select_columns(dialog, "Predictors", {"Arm"})
        dialog.update_cox_terms()
        dialog.controls["Event value"][1].set("Event")
        dialog.controls["Censor value"][1].set("Censored")
        dialog.controls["Ties"][1].set(EXACT)

    def separation_banner(dialog):
        banner = dialog.error_label.cget("text")
        assert dialog.initial_field == "Predictors" and banner, banner
        assert dialog.fields.select() == page_of(dialog, "Predictors")
        shot(dialog, "window-cox-exact-separation.png")
        tools.select_columns(dialog, "Predictors", {"Other"})
        dialog.update_cox_terms()

    runs = len(app.runs)
    analyse_with(SEPARATED, separated, separation_banner)
    assert len(app.runs) == runs + 1 and app.runs[-1].options["Predictors"] == ["Other"]
    assert np.isfinite(results(len(app.runs) - 1)["Coefficients"]["SE"]).all()
    done("separation: error on Predictors, then the correction")
    assert not errors, errors
