"""Desktop smoke check for Ordinal logistic regression, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_ordinal_logit` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=ordinal-logit python tramastat.py --smoke DIR``.

Synthetic data only: the packaged ``stages.csv`` (tests/data/ordinal_logit, the frozen analytic values of expected.json)
and a seeded simulated trial. The numbers of the trial are never compared with frozen values: each step compares the
dialog, the worker and the saved recipe with the same recipe run through the dispatcher.
Every widget is driven through its real handler; no event is injected except ``<<ListboxSelect>>`` (a programmatic
selection does not send it) and ``event_generate`` on the Inspector entry.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ordinal_logit as ol
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "ordinal_logit"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = ol.ORDINAL_LOGIT
STAGES, TRIAL = "Stages", "Trial"
BAR = "ordinal-logit-profile-{profile}-category-{category}"


def trial_frame():
    """A seeded proportional-odds trial: four grades, two continuous predictors and a three-site factor."""
    rng = np.random.default_rng(20261118)
    rows = 300
    frame = pd.DataFrame({"Dose": rng.normal(size=rows).round(3), "Age": rng.uniform(20, 70, size=rows).round(1),
                          "Site": rng.choice(["north", "south", "east"], size=rows)})
    eta = 0.9 * frame["Dose"] - 0.03 * (frame["Age"] - 45) + frame["Site"].map({"north": 0, "south": 0.7, "east": -0.4})
    frame["Grade"] = np.searchsorted([-1.2, 0.1, 1.4], eta.to_numpy() + rng.logistic(size=rows)) + 1
    return frame


def stages_frame():
    frame = pd.read_csv(DATA / "stages.csv")
    rng = np.random.default_rng(5)
    frame["Copy"] = 2 * frame["Treatment"]
    frame["Binary"] = frame["Stage"].eq("High").astype(int)
    # A predictor that orders the categories perfectly: the data are separated.
    frame["Perfect"] = frame["Stage"].map({"Low": 0.0, "Medium": 10.0, "High": 20.0}) + rng.uniform(0, 1, len(frame))
    return frame


def check_ordinal_logit(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_ordinal_logit(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_ordinal_logit(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "ordinal-logit"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    stages, trial = stages_frame(), trial_frame()
    path = directory / "ordinal-logit.alab"
    save_project(path, {STAGES: Dataset(stages.copy()), TRIAL: Dataset(trial.copy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "language": i18n.active_language(), "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        page = dialog.field_rows[field][1].master
        while page.master is not dialog.fields:
            page = page.master
        return str(page)

    def rejected(dialog, field, contains, shot_name=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert contains.lower() in message.lower(), message
        report.setdefault("field_errors", []).append(
            {"language": i18n.active_language(), "field": field, "message": message})
        assert dialog.fields.select() == page_of(dialog, field), field
        target = dialog.initial_focus
        assert target is not None and target.winfo_exists(), "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

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

    def pick(dialog, field, names):
        tools.select_columns(dialog, field, names)
        dialog.controls[field][1].event_generate("<<ListboxSelect>>")
        dialog.update()

    def order(dialog):
        return dialog.controls["Category order"][1].values()

    def arrange(dialog, wanted):
        """Move the categories with the Up and Down buttons until the list reads as wanted."""
        editor = dialog.controls["Category order"][1]
        for position, label in enumerate(wanted):
            while editor.values().index(label) > position:
                editor.listbox.selection_clear(0, "end")
                editor.listbox.selection_set(editor.values().index(label))
                editor.buttons["up"].invoke()
        assert editor.values() == list(wanted), editor.values()

    def table(index, name):
        return app.runs[index].result.tables[name]

    def bars(index):
        return sorted(patch_.get_gid() for patch_ in app.runs[index].result.figure.axes[0].patches
                      if str(patch_.get_gid()).startswith("ordinal-logit-profile"))

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def edit_with(index, action, initial_field=None):
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.show("result", index)
        app.edit_analysis(initial_field=initial_field)
        wait()

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

    def await_reopened(inspect, trigger):
        """Run trigger and let the recovered dialog be inspected (and then cancelled) while the app waits."""
        state = {"done": False}

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
                inspect(dialog)
            except Exception as error:
                errors.append(repr(error))
            finally:
                dialog.cancel()
            state["done"] = True

        root.after(25, recovered)
        trigger()
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(.02)
        assert not errors, errors

    # 1. English dialog on stages: a level outside 0 and 100 on its field, the order moved with Up and Down.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Variables", "Options", "Profiles"]
        assert controls["Confidence level (%)"][1].get() == "95.0" and controls["Show graph"][1].get() is False
        controls["Response"][1].set("Stage")
        pick(dialog, "Predictors", ["Treatment"])
        assert order(dialog) == ["High", "Low", "Medium"], order(dialog)
        arrange(dialog, ["Low", "Medium", "High"])
        controls["Confidence level (%)"][1].set("120")
        rejected(dialog, "Confidence level (%)", "greater than 0 and less than 100", "window-ordinal-logit-error.png")
        controls["Confidence level (%)"][1].set("90")
        reachable(dialog)
        for position, name in enumerate(("dialog", "options", "profiles")):
            dialog.fields.select(position)
            dialog.update()
            shot(dialog, f"window-ordinal-logit-{name}{suffix}.png")
        dialog.fields.select(0)

    main = analyse_with(english, STAGES)
    options = app.runs[main].options
    assert options["Response"] == "Stage" and options["Predictors"] == ["Treatment"], options
    assert options["Category order"] == ["Low", "Medium", "High"] and options["Confidence level (%)"] == 90.0, options
    assert options["Profiles"] == [] and options["Show graph"] is False and options["Categorical predictors"] == []
    assert list(app.runs[main].result.tables) == ["Coefficients", "Thresholds", "Model fit", "Fitted probabilities"]
    assert app.runs[main].result.figure is None
    coefficient = table(main, "Coefficients").loc["Treatment"]
    np.testing.assert_allclose(coefficient["Estimate"], EXPECTED["coeff"], rtol=1e-7)
    np.testing.assert_allclose(coefficient["SE"], EXPECTED["se"], rtol=5e-6)
    np.testing.assert_allclose(coefficient["p"], EXPECTED["p"], rtol=5e-5)
    from scipy.stats import norm
    half = norm.ppf(0.95) * EXPECTED["se"]
    np.testing.assert_allclose([coefficient["OR lower"], coefficient["OR upper"]],
                               np.exp(EXPECTED["coeff"] + np.array([-half, half])), rtol=5e-6)
    np.testing.assert_allclose(table(main, "Thresholds")["Estimate"], EXPECTED["thresholds"], rtol=1e-7)
    fit = table(main, "Model fit").iloc[0]
    assert (int(fit["N"]), int(fit["Incomplete rows"])) == (168, 0)
    np.testing.assert_allclose([fit["Log likelihood"], fit["AIC"]], [EXPECTED["ll"], EXPECTED["aic"]], rtol=1e-9)
    done("english dialog: level refused on its field, order moved with Up and Down, analytic oracle matched")
    app.show("result", main)
    app.result_tabs.select(0)
    shot(root, "window-ordinal-logit-results" + suffix + ".png")

    # 2. Reorder: the sign flips and the probabilities stay with their labels.
    before = {name: frame.copy() for name, frame in app.runs[main].result.tables.items()}

    def reverse(dialog):
        assert order(dialog) == ["Low", "Medium", "High"]
        arrange(dialog, ["High", "Medium", "Low"])

    edit_with(main, reverse, "Category order")
    assert app.runs[main].options["Category order"] == ["High", "Medium", "Low"]
    np.testing.assert_allclose(table(main, "Coefficients")["Estimate"], -before["Coefficients"]["Estimate"], rtol=1e-6)
    np.testing.assert_allclose(table(main, "Thresholds")["Estimate"].to_numpy(),
                               -before["Thresholds"]["Estimate"].to_numpy()[::-1], rtol=1e-6)
    assert list(table(main, "Thresholds")["Lower category"]) == ["High", "Medium"]
    for label in ("Low", "Medium", "High"):
        np.testing.assert_allclose(table(main, "Fitted probabilities")[f"P({label})"],
                                   before["Fitted probabilities"][f"P({label})"], atol=1e-7)
    edit_with(main, lambda dialog: arrange(dialog, ["Low", "Medium", "High"]), "Category order")
    for name, frame in before.items():
        pd.testing.assert_frame_equal(table(main, name), frame, rtol=1e-9, atol=1e-12)
    done("reversing the category order flips the sign, keeps the label probabilities and restores exactly")

    # 3. A defective design on its field (collinear), and separated data reopening the dialog after the worker.
    def collinear(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Response"][1].set("Stage")
        pick(dialog, "Predictors", ["Treatment", "Copy"])
        rejected(dialog, "Predictors", "collinear", "window-ordinal-logit-rank-error.png")
        pick(dialog, "Predictors", ["Treatment"])
        assert dialog.validate()  # the corrected recipe is valid; this dialog is only here to be refused once
        dialog.result, dialog.ok = None, dialog.cancel

    app.show("data", STAGES)
    tools.drive_dialog(tools.AnalysisDialog, collinear)
    app.choose_analysis()
    assert len(app.runs) == 1, "a refused dialog adds no analysis"
    separated = {"state": None}

    def inspect_separation(dialog):
        banner = dialog.error_label.cget("text") if dialog.error_label is not None else ""
        assert "separation" in banner.lower(), banner
        assert dialog.initial_field == "Predictors", dialog.initial_field
        assert dialog.fields.select() == page_of(dialog, "Predictors"), (dialog.fields.select(), page_of(dialog, "Predictors"))
        assert dialog.controls["Response"][1].get() == "Stage"
        box = dialog.controls["Predictors"][1]
        assert [box.get(i) for i in box.curselection()] == ["Perfect"], [box.get(i) for i in box.curselection()]
        assert order(dialog) == ["Low", "Medium", "High"], order(dialog)
        shot(dialog, "window-ordinal-logit-separation" + suffix + ".png")
        separated["state"] = True

    def separated_dialog(dialog):
        tools.pick_method(dialog, METHOD)
        dialog.controls["Response"][1].set("Stage")
        pick(dialog, "Predictors", ["Perfect"])
        arrange(dialog, ["Low", "Medium", "High"])

    # The dialog accepts the recipe: separation is known only after the fit, on the worker, which reopens the dialog.
    app.show("data", STAGES)
    tools.drive_dialog(tools.AnalysisDialog, separated_dialog)
    app.choose_analysis()
    await_reopened(inspect_separation, lambda: None)
    assert separated["state"] and len(app.runs) == 1, "no analysis is added for separated data"
    assert "No analysis was added" in app.status.get(), app.status.get()
    done("collinear predictors refused on their field; separated data reopen the dialog on Predictors, nothing added")

    # 4. Italian dialog on the trial: categorical predictor, two profiles (one extrapolated), graph.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        captions = [dialog.field_rows[name][0].cget("text") for name in controls]
        assert captions == ["Risposta", "Predittori", "Predittori categorici", "Ordine delle categorie",
                            "Livello di confidenza (%)", "Profili", "Mostra grafico"], captions
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Variabili", "Opzioni", "Profili"]
        editor = controls["Category order"][1]
        assert [button.cget("text") for button in editor.buttons.values()] == ["Su", "Giù", "Ripristina"]
        controls["Response"][1].set("Grade")
        pick(dialog, "Predictors", ["Dose", "Age", "Site"])
        pick(dialog, "Categorical predictors", ["Site"])
        assert order(dialog) == ["1", "2", "3", "4"], order(dialog)
        profiles = controls["Profiles"][1]
        assert profiles.predictors == ["Dose", "Age", "Site"] and profiles.categories == ["Site"]
        for name, dose, age, site in (("Typical", "0", "45", "south"), ("Outside", "50", "45", "east")):
            profiles.label.set(name)
            profiles.inputs["Dose"].set(dose)
            profiles.inputs["Age"].set(age)
            profiles.inputs["Site"].set(site)
            profiles.add()
        controls["Show graph"][1].set(True)
        controls["Confidence level (%)"][1].set("95")
        # An invalid level, in Italian, on its field with the keyboard there.
        controls["Confidence level (%)"][1].set("0")
        rejected(dialog, "Confidence level (%)", "livello di confidenza", "window-ordinal-logit-it-error.png")
        controls["Confidence level (%)"][1].set("95")
        reachable(dialog)
        for position, name in enumerate(("it", "it-options", "it-profiles")):
            dialog.fields.select(position)
            dialog.update()
            shot(dialog, f"window-ordinal-logit-{name}{suffix}.png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, TRIAL)
        assert app.runs[italian_index].options["Category order"] == ["1", "2", "3", "4"]
        assert app.runs[italian_index].options["Categorical predictors"] == ["Site"]
        assert app.runs[italian_index].options["Show graph"] is True
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-ordinal-logit-it-graph" + suffix + ".png")
        app.show("result", italian_index)
        app.result_tabs.select(0)
        root.update()
        shot(root, "window-ordinal-logit-it-results" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    recipe = dict(app.runs[italian_index].options)
    again = analyse(METHOD, app.tables[TRIAL].frame(mask_excluded=True), recipe)
    for name, frame in again.tables.items():
        pd.testing.assert_frame_equal(table(italian_index, name), frame, rtol=1e-9, atol=1e-12)
    profile = table(italian_index, "Profile probabilities")
    assert list(profile.columns) == ["Profile", "P(1)", "P(2)", "P(3)", "P(4)", "Note"], list(profile.columns)
    assert profile.loc[0, "Note"] == "" and "Dose = 50 is outside the observed range" in profile.loc[1, "Note"]
    assert list(table(italian_index, "Coefficients").index) == ["Dose", "Age", "Site [north]", "Site [south]"]
    assert table(italian_index, "Reference levels").loc["Site", "Reference"] == "east"
    assert bars(italian_index) == sorted(BAR.format(profile=p, category=c) for p in (1, 2) for c in (1, 2, 3, 4))
    axes = app.runs[italian_index].result.figure.axes[0]
    assert [text.get_text() for text in axes.get_legend().get_texts()] == ["1", "2", "3", "4"]
    done("italian dialog: captions, level refused on its field, categorical predictor, profiles, graph, canonical recipe")

    # 5. Edit a cell: a new category must be dealt with on Category order; the last valid result stays.
    app.show("data", TRIAL)
    grade_column = app.tables[TRIAL].raw.columns.get_loc("Grade")
    dose_column = app.tables[TRIAL].raw.columns.get_loc("Dose")
    kept_tables = {name: frame.copy() for name, frame in app.runs[italian_index].result.tables.items()}
    kept_options = dict(app.runs[italian_index].options)

    def inspect_new_level(dialog):
        banner = dialog.error_label.cget("text") if dialog.error_label is not None else ""
        assert "Category order" in banner and '"5"' in banner, banner
        assert dialog.initial_field == "Category order"
        assert dialog.fields.select() == page_of(dialog, "Category order")
        note = dialog.controls["Category order"][1].note.cget("text")
        assert "New" in note and '"5"' in note, note
        assert order(dialog) == ["1", "2", "3", "4"], "a stale order is never repaired silently"
        shot(dialog, "window-ordinal-logit-new-level" + suffix + ".png")

    await_reopened(inspect_new_level, lambda: app.edit_cell(0, grade_column, "5"))
    assert app.runs[italian_index].options == kept_options, "the recipe is kept"
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[italian_index].result.tables[name], frame)
    assert app.runs[italian_index].calculation_error and "Category order" in app.runs[italian_index].calculation_error
    app.show("result", italian_index)
    assert app.stale_calculation_note() is not None, "the retained result must be flagged"
    original = int(trial.loc[0, "Grade"])
    app.show("data", TRIAL)
    app.edit_cell(0, grade_column, str(original))
    wait()
    assert app.runs[italian_index].calculation_error is None
    assert app.stale_calculation_note(("result", italian_index)) is None
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[italian_index].result.tables[name], frame, rtol=1e-9, atol=1e-12)
    done("a new category keeps the recipe and the last result, reopens Category order, and the original value recovers")

    # Excluding a cell drops that row and keeps the physical numbering of the others.
    app.show("data", TRIAL)
    app.current_grid.select((4, dose_column))
    app.toggle_exclusion()
    wait()
    fit = table(italian_index, "Model fit").iloc[0]
    assert (int(fit["N"]), int(fit["Incomplete rows"])) == (299, 1), fit
    source = table(italian_index, "Fitted probabilities")["Source row"].tolist()
    assert source == [row for row in range(1, 301) if row != 5], source[:8]
    app.show("data", TRIAL)
    app.current_grid.select((4, dose_column))
    app.toggle_exclusion()
    wait()
    assert int(table(italian_index, "Model fit").iloc[0]["N"]) == 300
    done("an excluded cell removes its row; physical row numbers stay; undoing restores the fit")

    # 6. A style change never refits; Format Graph keeps literal text; the Inspector applies and cancels.
    fits = []
    real_fit = ol.fit_model

    def counted(prepared):
        fits.append(1)
        return real_fit(prepared)

    app.show("graph", italian_index)
    root.update()
    with patch.object(ol, "fit_model", counted):
        tools.drive_dialog(GraphFormatDialog,
                           lambda dialog: dialog.inputs["title"].set("Probabilities with $Dose$ and _text_"))
        app.format_graph()
        wait()
        app.show("graph", italian_index)
        root.update()
        app.toggle_inspector()
        root.update()
        panel = app.inspector
        assert panel is not None and panel.elements, "the Inspector must offer the drawn bars"
        panel.select_group(panel.elements[0]["key"])
        panel.vars["element:color"].set("#9b4174")
        widget = panel.fields["color"]["widget"]
        widget.focus_force()
        root.update()
        widget.event_generate("<Return>")
        root.update()
        assert panel.apply(), panel.errors
        confirmed = app.runs[italian_index].style
        panel.vars["element:color"].set("#117733")
        widget.event_generate("<Return>")
        root.update()
        panel.cancel()
        root.update()
        assert app.runs[italian_index].style == confirmed
        wait()
    assert not fits, "a style change must not fit the model again"
    axes = app.runs[italian_index].result.figure.axes[0]
    assert axes.get_title() == "Probabilities with $Dose$ and _text_"
    assert "#9b4174" in str(app.runs[italian_index].style)
    done("Format Graph and Inspector change the style without a new fit; literal title")

    # 7. Exports: CSV of each sheet, PNG, SVG and PDF of the figure, and a two-panel layout.
    app.show("result", italian_index)
    sheets = list(app.runs[italian_index].result.tables)
    for position, name in enumerate(sheets):
        app.result_tabs.select(position)
        target = out / f"ordinal-logit-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Fitted probabilities":
            assert list(exported.columns) == ["Source row", "Observed", "Predicted", "P(1)", "P(2)", "P(3)", "P(4)"]
        if name == "Coefficients":
            assert list(exported.columns) == ["Estimate", "SE", "p", "Odds ratio", "OR lower", "OR upper"]
    app.show("graph", italian_index)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"ordinal-logit.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "ordinal-logit.svg").read_text(encoding="utf-8")
    for profile_number in (1, 2):
        for category in (1, 2, 3, 4):
            assert f'id="{BAR.format(profile=profile_number, category=category)}"' in svg, (profile_number, category)
    assert svg.count("<path") >= 8 and "#9b4174" in svg.lower(), "bars are vector paths in the styled colour"
    assert "<image" not in svg, "the figure must stay vector"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "ordinal-logit.pdf")
    assert "Probabilities with" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Ordinal logit panels", 2, [app.runs[italian_index].reference,
                                                          app.runs[italian_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.read_bytes()[:4] == b"%PDF" and target.stat().st_size > 1000
    layout_svg = exports / "layout.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    assert "<svg" in layout_svg.read_text(encoding="utf-8")[:600]
    shot(root, "window-ordinal-logit-layout" + suffix + ".png")
    done("CSV of every sheet, PNG, SVG with stable ids, PDF and a two-panel layout in vector formats")

    # A binary logistic recipe of Multiple regression runs next to it and is not touched.
    stage_frame = app.tables[STAGES].frame(mask_excluded=True)
    legacy_options = {"Response": "Binary", "Predictors": ["Treatment"], "Categorical predictors": [],
                      "Family": "Logistic"}
    legacy = tools.Run("Multiple regression", STAGES, legacy_options)
    app.add_result(legacy, app.compute(legacy, stage_frame))
    legacy_before = {name: frame.copy() for name, frame in legacy.result.tables.items()}
    assert "Thresholds" not in legacy_before

    # 8. Save and reopen from the graph: canonical recipes, identical tables and the restyled figure.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, "Multiple regression")}
    assert len(expected_runs) >= 3, sorted(expected_runs)
    app.path = directory / "ordinal-logit-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD and run.options.get("Show graph"):
            app.open_sheet(("graph", position))
            wait()
        elif run.method in (METHOD, "Multiple regression"):
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9, atol=1e-12)
    for name, frame in legacy_before.items():
        pd.testing.assert_frame_equal(reopened[(STAGES, legacy.slot)].result.tables[name], frame, rtol=1e-12)
    key = next(k for k in expected_runs if k[0] == TRIAL)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    assert bars(position) == sorted(BAR.format(profile=p, category=c) for p in (1, 2) for c in (1, 2, 3, 4))
    shot(root, "window-ordinal-logit-reopened" + suffix + ".png")
    done("save and reopen from the graph; Multiple regression logistic results unchanged")

    # 9. Use Result as Data keeps the fitted probabilities.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(list(app.runs[position].result.tables).index("Fitted probabilities"))
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert {"Source row", "Observed", "Predicted", "P(1)", "P(4)"} <= set(frame.columns) and len(frame) == 300
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
