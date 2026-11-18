"""Desktop smoke check for Weibull AFT regression, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_weibull_aft` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=weibull-aft python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixture (tests/data/weibull_aft/follow-up.csv) and two small tables built here.
The expected numbers are the frozen profile-likelihood values of expected.json, never computed by the module under
test, except where a step recalculates the same recipe through the dispatcher to prove that the dialog, the worker and
the saved recipe agree. Every widget is driven through its real handler; the only generated events are
``<<ListboxSelect>>`` on the predictor lists, which is what a click delivers. No mouse or keyboard is used by hand.
"""
import json
import os
import sys
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from . import weibull_aft as engine
from . import weibull_aft_workbench as aft
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "weibull_aft"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = aft.WEIBULL_AFT
COX, KM = "Cox regression", "Kaplan–Meier survival"
FOLLOW_UP, ARMS, LEGACY = "Follow-up", "Arms", "Legacy survival"
PROFILE = "aft-profile-{number}"
# Screenshots on X11 show the real Tk message box of a refused field; elsewhere the message box is intercepted.
VISIBLE_ERRORS = sys.platform != "win32" and bool(os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"))


def arms():
    """Two arms; arm B has a single event, so censoring it leaves the arm coefficient without a finite maximum."""
    return pd.DataFrame({"Weeks": [2.0, 3.0, 5.0, 7.0, 4.0, 6.0, 8.0, 9.0], "Status": [1, 1, 1, 0, 0, 1, 0, 0],
                         "Arm": ["A", "A", "A", "A", "B", "B", "B", "B"]})


def legacy():
    frame = pd.read_csv(DATA / "follow-up.csv")
    return frame.assign(Status=(frame["Status"] == "event").astype(int), Arm=np.where(frame["Treatment"] > 0, "T", "C"))


def check_weibull_aft(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_weibull_aft(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_weibull_aft(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    large = screen[0] >= 1600 and screen[1] >= 1000
    root.geometry(("1600x1000" if large else "1024x768") + "+0+0")
    root.update()
    theme = "modern" if ui_theme.is_modern() else "standard"
    out = directory / "weibull-aft"
    out.mkdir(exist_ok=True)
    suffix = f"-{theme}-{screen[0]}x{screen[1]}"
    follow_up = pd.read_csv(DATA / "follow-up.csv")
    path = directory / "weibull-aft.alab"
    save_project(path, {FOLLOW_UP: Dataset(follow_up.copy()), ARMS: Dataset(arms()),
                        LEGACY: Dataset(legacy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "window": "1600x1000" if large else "1024x768", "theme": theme,
              "manual input": "none: every widget is driven through its handler", "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        stem, extension = name.rsplit(".", 1)
        name = stem + suffix + "." + extension
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def tab_text(dialog):
        return dialog.fields.tab(dialog.fields.select(), "text")

    def on_screen(dialog, name):
        """Validate with the real Tk message box: capture the screen while it is open, read it and press OK."""
        seen = {}

        def close(tries=0):
            boxes = [w for w in root.tk.call("winfo", "children", str(dialog)) if "__tk__messagebox" in str(w)]
            if not boxes:
                if tries < 400:
                    root.after(25, lambda: close(tries + 1))
                return
            box = str(boxes[0])
            root.update_idletasks()
            seen["text"] = str(root.tk.call(box + ".msg", "cget", "-text"))
            shot(root, name)
            root.tk.call(box + ".ok", "invoke")

        root.after(50, close)
        assert dialog.validate() is False, name
        assert "text" in seen, "the message box did not appear"
        return seen["text"]

    def rejected(dialog, field, contains, shot_name=None):
        if shot_name and VISIBLE_ERRORS:
            message = on_screen(dialog, shot_name)
        else:
            with patch.object(tools.messagebox, "showerror") as banner:
                assert dialog.validate() is False, field
            message = banner.call_args.args[1]
        assert dialog.winfo_exists()
        assert contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), (field, tab_text(dialog))
        target = dialog.initial_focus
        assert target is not None and target.winfo_exists(), "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        return message

    def button(dialog, text):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == i18n.ui(text):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog):
        """Run Analysis, Cancel and every page lie inside the screen at the current size."""
        dialog.update()
        for text in ("Run Analysis", "Cancel"):
            found = button(dialog, text)
            assert found is not None and found.winfo_viewable(), text
            assert found.winfo_rooty() + found.winfo_height() <= screen[1], (text, found.winfo_rooty(), screen)
            assert found.winfo_rootx() + found.winfo_width() <= screen[0], text
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def choose(dialog, label, names):
        tools.select_columns(dialog, label, set(names))
        dialog.controls[label][1].event_generate("<<ListboxSelect>>")
        dialog.update()

    def type_into(dialog, field, text):
        editor = dialog.controls[field][1]
        editor.text.delete("1.0", "end")
        editor.text.insert("1.0", text)
        dialog.update()

    def add_profile(dialog, name, values):
        editor = dialog.controls["Profiles"][1]
        editor.label.set(name)
        for predictor, value in values.items():
            editor.inputs[predictor].set(value)
        assert editor.add(), editor.note.cget("text")

    def table(index, name):
        return app.runs[index].result.tables[name]

    def lines(index):
        figure = app.runs[index].result.figure
        return {line.get_gid(): line for axes in figure.axes for line in axes.lines
                if str(line.get_gid()).startswith("aft-profile-")}

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title, app.runs[index].method
        assert not errors, errors
        return index

    def edit_with(index, action, initial_field=None):
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.show("result", index)
        app.edit_analysis(initial_field=initial_field)
        wait()

    # 1. English dialog: a column in the wrong role keeps its error on Time until it is corrected; then Estimated ML
    # with two profiles and the default curve from zero.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Data", "Model", "Predicted survival"]
        assert controls["Event value"][1].get() == "1" and controls["Censor value"][1].get() == "0"
        assert controls["Shape mode"][1].get() == "Estimated ML"
        assert not dialog.field_rows["Shape"][1].winfo_manager(), "Shape belongs to the Fixed mode"
        controls["Time"][1].set("Status")
        controls["Event"][1].set("Treatment")
        choose(dialog, "Predictors", [])
        first = rejected(dialog, "Time", 'Column "Status" contains non-numeric or infinite data',
                         "window-weibull-aft-error.png")
        assert first.startswith("Time: "), first
        controls["Confidence level (%)"][1].set("90")
        assert rejected(dialog, "Time", 'Column "Status"') == first, "the error stays until the role is corrected"
        controls["Confidence level (%)"][1].set("95")
        controls["Time"][1].set("Time")
        controls["Event"][1].set("Status")
        rejected(dialog, "Event", "neither the event value nor the censor value")
        controls["Event value"][1].set("event")
        controls["Censor value"][1].set("censored")
        choose(dialog, "Predictors", ["Treatment"])
        editor = controls["Profiles"][1]
        assert list(editor.inputs) == ["Treatment"], list(editor.inputs)
        controls["Show graph"][1].set(True)
        rejected(dialog, "Profiles", "Show graph needs at least one profile")
        add_profile(dialog, "Control", {"Treatment": "0"})
        add_profile(dialog, "Treated", {"Treatment": "1"})
        controls["Shape mode"][1].set("Fixed")
        dialog.update()
        assert dialog.field_rows["Shape"][1].winfo_manager(), "Fixed shows the Shape field"
        controls["Shape"][1].set("60")
        rejected(dialog, "Shape", "from 0.05 to 50")
        controls["Shape mode"][1].set("Estimated ML")
        dialog.update()
        reachable(dialog)
        for position, name in enumerate(("data", "model", "predicted")):
            dialog.fields.select(position)
            dialog.update()
            shot(dialog, f"window-weibull-aft-{name}.png")
        dialog.fields.select(0)

    main = analyse_with(english, FOLLOW_UP)
    options = app.runs[main].options
    assert options["Shape mode"] == "Estimated ML" and "Shape" not in options, options
    assert options["Profiles"] == [{"Name": "Control", "Values": {"Treatment": 0.0}},
                                   {"Name": "Treated", "Values": {"Treatment": 1.0}}], options["Profiles"]
    assert options["Times"] == [] and options["Show graph"] is True, options
    assert list(app.runs[main].result.tables) == ["Coefficients", "Model fit", "Fitted survival", "Survival curves"]
    done("english dialog: wrong role kept on Time until corrected, status codes, shape range, profiles")

    expected = EXPECTED["estimated"]
    fit = table(main, "Model fit").iloc[0]
    np.testing.assert_allclose(fit["Shape"], expected["shape"], rtol=1e-7)
    np.testing.assert_allclose(fit["Log likelihood"], expected["ll"], rtol=1e-9)
    np.testing.assert_allclose(fit["AIC"], expected["aic"], rtol=1e-9)
    assert (fit["N"], fit["Events"], fit["Censored"], fit["Parameters"]) == (16, 10, 6, 3), fit
    coefficients = table(main, "Coefficients")
    np.testing.assert_allclose(coefficients["Estimate"].to_numpy(), expected["beta"], rtol=1e-7)
    np.testing.assert_allclose(coefficients.loc["Treatment", "Time ratio"], 2.0, rtol=1e-9)
    curves = table(main, "Survival curves")
    assert len(curves) == 2 * 101 and list(curves["Profile"][:1]) == ["Control"]
    control = curves[curves["Profile"] == "Control"]
    assert control["Time"].iloc[0] == 0 and control["Survival"].iloc[0] == 1.0, "the curve starts at S(0) = 1"
    assert control["Time"].iloc[-1] == follow_up["Time"].max() and (curves["Extrapolated"] == "No").all()
    scale = np.exp(expected["beta"][0])
    np.testing.assert_allclose(control["Survival"], np.exp(-(control["Time"] / scale) ** expected["shape"]),
                               rtol=1e-7, atol=1e-12)
    done("Estimated ML equals the frozen profile likelihood (shape 1.49099085, time ratio 2), curve from zero")

    app.show("result", main)
    app.result_tabs.select(0)
    root.update()
    shot(root, "window-weibull-aft-results.png")
    app.show("graph", main)
    root.update()
    found = lines(main)
    assert sorted(found) == [PROFILE.format(number=1), PROFILE.format(number=2)], sorted(found)
    np.testing.assert_allclose(found["aft-profile-1"].get_ydata(), control["Survival"], rtol=1e-12)
    axes = app.runs[main].result.figure.axes[0]
    assert axes.get_ylim() == (0.0, 1.0) and axes.get_xlim()[0] == 0, (axes.get_ylim(), axes.get_xlim())
    assert getattr(axes, "_tramastat_numeric_axes", None) == ("x", "y")
    shot(root, "window-weibull-aft-graph.png")
    done("figure: one vector line per profile with the sheet coordinates, Y from 0 to 1")

    # 2. Reopen through Graph settings…: the profiles come back, explicit times reach beyond the follow-up.
    def reopen(dialog):
        assert tab_text(dialog) == "Predicted survival", tab_text(dialog)
        editor = dialog.controls["Profiles"][1]
        assert editor.values() == options["Profiles"], editor.values()
        assert dialog.controls["Times"][1].raw_lines() == [], dialog.controls["Times"][1].raw_lines()
        type_into(dialog, "Times", "0\n2\n4\n8\n20")
        dialog.update()
        shot(dialog, "window-weibull-aft-reopened-profiles.png")

    edit_with(main, reopen, "Show graph")
    assert app.runs[main].options["Times"] == [0.0, 2.0, 4.0, 8.0, 20.0], app.runs[main].options["Times"]
    curves = table(main, "Survival curves")
    assert list(curves["Time"]) == [0, 2, 4, 8, 20] * 2 and list(curves["Extrapolated"][:5]) == ["No"] * 4 + ["Yes"]
    figure = app.runs[main].result.figure
    assert [patch_.get_gid() for patch_ in figure.axes[0].patches] == ["aft-extrapolated"]
    assert lines(main)["aft-profile-2"].get_marker() == "o"
    done("reopen from Graph settings: profiles kept, times beyond the follow-up flagged as extrapolated")

    # 3. Edit a time and exclude a row: the worker recalculates the same recipe as the dispatcher.
    def recalculated(title, index):
        return analyse(METHOD, app.tables[title].frame(mask_excluded=True), dict(app.runs[index].options))

    app.show("data", FOLLOW_UP)
    time_column = app.tables[FOLLOW_UP].raw.columns.get_loc("Time")
    before = table(main, "Coefficients").copy()
    app.edit_cell(0, time_column, "1.3")
    wait()
    assert not table(main, "Coefficients").equals(before), "a time edit recalculates the fit"
    want = recalculated(FOLLOW_UP, main)
    for name in want.tables:
        pd.testing.assert_frame_equal(table(main, name), want.tables[name])
    app.show("data", FOLLOW_UP)
    app.current_grid.select((2, time_column))
    app.toggle_exclusion()
    wait()
    fit = table(main, "Model fit").iloc[0]
    assert (fit["N"], fit["Incomplete rows"]) == (15, 1), fit
    assert 3 not in set(table(main, "Fitted survival")["Source row"]), "the excluded row leaves the fitted sheet"
    assert list(table(main, "Fitted survival")["Source row"][:3]) == [1, 2, 4]
    pd.testing.assert_frame_equal(table(main, "Coefficients"), recalculated(FOLLOW_UP, main).tables["Coefficients"])
    done("cell edit and excluded row recalculate the fit; Source row stays physical")

    # 4. Italian dialog on a categorical arm, fixed shape: an error on its field, then the reference levels.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions["Shape mode"] == "Modalità della forma" and captions["Times"] == "Tempi", captions
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Dati", "Modello", "Sopravvivenza prevista"]
        mode = dialog.choice_bindings["Shape mode"]
        assert tuple(mode.combobox.cget("values")) == ("Stimata (massima verosimiglianza)", "Fissa")
        dialog.controls["Time"][1].set("Weeks")
        dialog.controls["Event"][1].set("Status")
        choose(dialog, "Predictors", ["Arm"])
        choose(dialog, "Categorical predictors", ["Arm"])
        dialog.controls["Censor value"][1].set("1")
        rejected(dialog, "Censor value", "Valore di censura: I valori di evento e di censura devono essere diversi",
                 "window-weibull-aft-it-error.png")
        dialog.controls["Censor value"][1].set("0")
        mode.display.set("Fissa")
        dialog.update()
        dialog.controls["Shape"][1].set("1")
        add_profile(dialog, "Braccio B", {"Arm": "B"})
        dialog.controls["Show graph"][1].set(True)
        reachable(dialog)
        for position, name in enumerate(("data", "model", "predicted")):
            dialog.fields.select(position)
            dialog.update()
            shot(dialog, f"window-weibull-aft-it-{name}.png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, ARMS)
        recipe = app.runs[italian_index].options
        assert recipe["Shape mode"] == "Fixed" and recipe["Shape"] == 1.0, "the recipe keeps the canonical token"
        assert table(italian_index, "Reference levels").loc["Arm", "Reference"] == "A"
        app.show("result", italian_index)
        app.result_tabs.select(0)
        root.update()
        shot(root, "window-weibull-aft-it-results.png")
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-weibull-aft-it-graph.png")
        assert app.runs[italian_index].result.figure.axes[0].get_ylabel() == "Survival probability"
    finally:
        i18n.set_language(original_language)
    done("italian dialog: equal codes refused on Censor value, canonical recipe, reference level A")

    # 5. A cell edit that leaves arm B without events: the last confirmed result stays and the dialog reopens on
    # Predictors with the reason; restoring the cell clears the stale note.
    app.show("result", italian_index)
    kept_tables = {name: frame.copy() for name, frame in app.runs[italian_index].result.tables.items()}
    kept_options = dict(app.runs[italian_index].options)
    state = {"done": False}

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found_ = find(child)
                if found_ is not None:
                    return found_
        return find(root)

    def recovered(tries=0):
        dialog = find_dialog()
        if dialog is None or not dialog.winfo_viewable():
            if tries > 1200:
                errors.append("the recovered AnalysisDialog did not open")
                state["done"] = True
                return
            root.after(25, lambda: recovered(tries + 1))
            return
        try:
            assert dialog.error_label is not None, "no banner"
            banner = dialog.error_label.cget("text")
            assert "cannot be estimated" in banner and "Arm [B]" in banner, banner
            assert dialog.initial_field == "Predictors", dialog.initial_field
            assert dialog.fields.select() == page_of(dialog, "Predictors")
            assert dialog.controls["Profiles"][1].values() == kept_options["Profiles"]
            assert dialog.controls["Shape mode"][1].get() == "Fixed"
            shot(dialog, "window-weibull-aft-recovered.png")
            dialog.cancel()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    app.show("data", ARMS)
    status_column = app.tables[ARMS].raw.columns.get_loc("Status")
    root.after(25, recovered)
    app.edit_cell(5, status_column, "0")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    assert app.runs[italian_index].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[italian_index].result.tables[name], frame)
    assert app.runs[italian_index].calculation_error and "Arm [B]" in app.runs[italian_index].calculation_error
    app.show("result", italian_index)
    assert app.stale_calculation_note() is not None, "the stale result must be flagged"
    app.show("data", ARMS)
    app.edit_cell(5, status_column, "1")
    wait()
    assert app.runs[italian_index].calculation_error is None
    assert app.stale_calculation_note(("result", italian_index)) is None
    done("a non-identifiable edit keeps the confirmed result, reopens Predictors and recovers")

    # 6. Format Graph with literal text; the style survives a recalculation.
    app.show("graph", main)
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Survival with $k$ and _text_"))
    app.format_graph()
    wait()
    assert app.runs[main].result.figure.axes[0].get_title() == "Survival with $k$ and _text_"
    app.recalculate(main)
    wait()
    assert app.runs[main].result.figure.axes[0].get_title() == "Survival with $k$ and _text_"
    done("Format Graph keeps literal text across a recalculation")

    # 7. Exports: CSV of each sheet, PNG, SVG and PDF of the figure, and a two-panel layout.
    app.show("result", main)
    sheets = list(app.runs[main].result.tables)
    for position, name in enumerate(sheets):
        app.result_tabs.select(position)
        target = out / f"weibull-aft-{position}{suffix}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Survival curves":
            assert list(exported.columns)[-3:] == engine.CURVE_COLUMNS[1:], list(exported.columns)
    app.show("graph", main)
    exports = out / f"exports{suffix}"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"weibull-aft.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "weibull-aft.svg").read_text(encoding="utf-8")
    assert 'id="aft-profile-1"' in svg and 'id="aft-profile-2"' in svg and 'id="aft-extrapolated"' in svg
    assert "<image" not in svg, "the figure must stay vector"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "weibull-aft.pdf")
    assert "Survival with" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Weibull AFT panels", 2, [app.runs[main].reference, app.runs[italian_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    for extension in ("pdf", "svg"):
        target = exports / f"layout.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, extension
    assert "<image" not in (exports / "layout.svg").read_text(encoding="utf-8")
    shot(root, "window-weibull-aft-layout.png")
    done("CSV of every sheet, PNG, SVG and PDF of the figure, a two-panel layout in vector formats")

    # Cox and Kaplan–Meier recipes written before this method existed keep their tables after a save and reopen.
    legacy_frame = app.tables[LEGACY].frame(mask_excluded=True)
    cox = tools.Run(COX, LEGACY, {"Time": "Time", "Event": "Status", "Event value": "1", "Censor value": "0",
                                  "Predictors": ["Arm"], "Categorical predictors": ["Arm"]})
    app.add_result(cox, app.compute(cox, legacy_frame))
    km = tools.Run(KM, LEGACY, {"Time": "Time", "Event columns": ["Status"], "Grouping variables": ["Arm"]})
    app.add_result(km, app.compute(km, legacy_frame))
    legacy_before = {run.method: {name: frame.copy() for name, frame in run.result.tables.items()} for run in (cox, km)}

    # 8. Save, reopen with the graph first: canonical recipes and the same tables.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, COX, KM)}
    assert len(expected_runs) >= 4, sorted(expected_runs)
    app.path = directory / f"weibull-aft-saved{suffix}.alab"
    assert app.save()
    (out / f"roundtrip{suffix}.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        app.open_sheet(("graph" if run.method == METHOD and run.result is not None and run.result.figure is not None
                        else "result", position))
        wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    for method, tables in legacy_before.items():
        run = next(run for run in app.runs if run.method == method and run.title == LEGACY)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], frame, rtol=1e-12)
    position = next(i for i, run in enumerate(app.runs) if run.method == METHOD and run.title == FOLLOW_UP)
    app.show("graph", position)
    root.update()
    assert sorted(lines(position)) == ["aft-profile-1", "aft-profile-2"]
    assert app.runs[position].result.figure.axes[0].get_title() == "Survival with $k$ and _text_"
    shot(root, "window-weibull-aft-reopened.png")
    done("save and reopen from the graph; Cox and Kaplan–Meier tables unchanged")

    # 9. Use Result as Data keeps the long curve table.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(list(app.runs[position].result.tables).index("Survival curves"))
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == engine.CURVE_COLUMNS and len(frame) == 10, list(frame.columns)
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data keeps Profile, Time, Survival and Extrapolated")
    (out / f"report{suffix}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
