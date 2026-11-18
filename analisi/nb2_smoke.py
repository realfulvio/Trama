"""Desktop smoke check for Negative binomial regression (NB2, 0.93), driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_nb2_regression` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=nb2-regression python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/nb2_regression). The expected numbers of the two saturated
groups are the frozen closed-form oracle of the package (expected.json), never computed by the module under test.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .data import Dataset, save_project
from .nb2_regression import FIGURE_TITLE, NB2

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "nb2_regression"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
COUNTS, BATCHES, HOURS, BOUNDARY = "NB2 counts", "NB2 batches", "NB2 batches (hours)", "NB2 boundary"
SHEETS = ["Coefficients", "Model fit", "Fitted values", "Reference levels"]


def _counts():
    return pd.read_csv(DATA / "counts.csv", keep_default_na=False).replace("", np.nan)


def check_nb2_regression(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_nb2_regression(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_nb2_regression(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "nb2-regression"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = (f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else "") + ("-modern" if ui_theme.is_modern() else "")
    batches = pd.read_csv(DATA / "batches.csv")
    path = directory / "nb2-regression.alab"
    save_project(path, {COUNTS: Dataset(_counts()), BATCHES: Dataset(batches),
                        HOURS: Dataset(batches.assign(Exposure=batches["Exposure"] * 24)),
                        BOUNDARY: Dataset(pd.read_csv(DATA / "poisson-boundary.csv"))})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "theme": "modern" if ui_theme.is_modern() else "standard",
              "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        if shot_name:
            dialog.update()
            shot(dialog, shot_name + suffix + ".png")
        return message

    def placed(dialog, name):
        """A hidden field is grid_remove()d: it has no geometry manager, whichever tab is showing."""
        return bool(dialog.field_rows[name][1].winfo_manager())

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
        """Run Analysis, Cancel and every tab lie inside the screen at the current size."""
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

    def table(index, name):
        return app.runs[index].result.tables[name]

    def choose(dialog, response="Count", predictors=("Treatment",), categories=(), exposure="Exposure"):
        dialog.controls["Response"][1].set(response)
        tools.select_columns(dialog, "Predictors", predictors)
        tools.select_columns(dialog, "Categorical predictors", categories)
        dialog.controls["Exposure"][1].set(exposure)

    def set_mode(dialog, shown):
        """Pick a mode through the combobox, as a user does, in the language of the dialog."""
        box = dialog.choice_bindings["Dispersion mode"].combobox
        box.set(shown)
        box.event_generate("<<ComboboxSelected>>")
        dialog.update()

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == NB2 and app.runs[index].title == title
        return index

    def assert_oracle(index, mode):
        want = EXPECTED[mode]
        coefficients = table(index, "Coefficients").loc[["Intercept", "Treatment"]]
        for column, key in (("Estimate", "beta"), ("SE", "se"), ("IRR", "irr"), ("IRR lower", "lower"),
                            ("IRR upper", "upper"), ("p", "p")):
            np.testing.assert_allclose(coefficients[column], want[key], rtol=2e-8, atol=2e-9, err_msg=column)
        fit = table(index, "Model fit").iloc[0]
        for column, key in (("Alpha", "alpha"), ("Log likelihood", "ll"), ("AIC", "aic")):
            np.testing.assert_allclose(fit[column], want[key], rtol=2e-8, err_msg=column)
        fitted = table(index, "Fitted values")
        for column, key in (("Fitted count", "mean"), ("Variance", "variance"), ("Pearson residual", "pearson")):
            np.testing.assert_allclose(fitted[column], want[key], rtol=2e-8, atol=2e-9, err_msg=column)
        assert fitted["Source row"].tolist() == list(range(1, 17))

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

    def recover(trigger, check):
        """Run ``trigger`` (it starts a calculation that fails on the worker) and inspect the reopened dialog."""
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
                assert dialog.error_label is not None, "no banner"
                check(dialog, dialog.error_label.cget("text"))
                dialog.cancel()
            except Exception as error:
                errors.append(repr(error))
                dialog.cancel()
            state["done"] = True

        # After the trigger: an edit opens (and closes) its own dialog first, the recovered one comes later.
        trigger()
        root.after(25, recovered)
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(.02)
        assert not errors, errors

    # 1. English dialog: pages, defaults, the hidden alpha and every invalid choice on its own field; Fixed oracle.
    def english(dialog):
        tools.pick_method(dialog, NB2)
        controls = dialog.controls
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        assert tabs == ["Variables", "Options"], tabs
        assert [dialog.field_rows[name][0].cget("text") for name in controls] == [
            "Response", "Predictors", "Categorical predictors", "Exposure", "Dispersion mode", "Dispersion alpha",
            "Confidence level (%)", "Residual plot"]
        assert controls["Dispersion mode"][1].get() == "Estimated ML" and controls["Dispersion alpha"][1].get() == "0.5"
        assert controls["Confidence level (%)"][1].get() == "95.0" and controls["Residual plot"][1].get() is False
        assert not placed(dialog, "Dispersion alpha"), "alpha is hidden under Estimated ML"
        choose(dialog, predictors=())
        rejected(dialog, "Predictors", "Select at least one column")
        choose(dialog, predictors=("Treatment", "Count"))
        rejected(dialog, "Predictors", "cannot also be a predictor")
        choose(dialog, categories=("Batch",))
        rejected(dialog, "Categorical predictors", "among the predictors", "window-nb2-error")
        choose(dialog, exposure="Treatment")
        rejected(dialog, "Exposure", "distinct from the response")
        choose(dialog)
        set_mode(dialog, "Fixed")
        assert placed(dialog, "Dispersion alpha") and controls["Dispersion mode"][1].get() == "Fixed"
        dialog.fields.select(0)
        controls["Dispersion alpha"][1].set("abc")
        rejected(dialog, "Dispersion alpha", "must be a number", "window-nb2-alpha-error")
        controls["Dispersion alpha"][1].set("0")
        rejected(dialog, "Dispersion alpha", "from 0.000001 to 1000")
        controls["Dispersion alpha"][1].set("0.5")
        controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "strictly between 0 and 100")
        controls["Confidence level (%)"][1].set("95")
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-nb2-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-nb2-options" + suffix + ".png")
        dialog.fields.select(0)

    fixed = analyse_with(english, COUNTS)
    options = app.runs[fixed].options
    assert options == {"Response": "Count", "Predictors": ["Treatment"], "Categorical predictors": [],
                       "Exposure": "Exposure", "Dispersion mode": "Fixed", "Dispersion alpha": 0.5,
                       "Confidence level (%)": 95.0, "Residual plot": False}, options
    assert list(app.runs[fixed].result.tables) == SHEETS[:3], list(app.runs[fixed].result.tables)
    assert app.runs[fixed].result.figure is None
    assert_oracle(fixed, "fixed")
    app.show("result", fixed)
    app.result_tabs.select(0)
    root.update()
    shot(root, "window-nb2-results" + suffix + ".png")
    done("english dialog, field errors, Fixed oracle")

    # 2. Edit to Estimated ML with the residual plot: the ML oracle, the observed-information covariance, the figure.
    def estimated(dialog):
        assert dialog.controls["Dispersion mode"][1].get() == "Fixed"
        set_mode(dialog, "Estimated ML")
        assert not placed(dialog, "Dispersion alpha")
        dialog.controls["Residual plot"][1].set(True)

    app.show("result", fixed)
    tools.drive_dialog(tools.AnalysisDialog, estimated)
    app.edit_analysis()
    wait()
    assert app.runs[fixed].options["Dispersion mode"] == "Estimated ML"
    assert app.runs[fixed].options["Residual plot"] is True
    assert_oracle(fixed, "estimated")
    assert table(fixed, "Model fit")["Covariance"].iloc[0].startswith("Observed information")
    figure = app.runs[fixed].result.figure
    assert figure is not None and figure.axes[0].get_title() == FIGURE_TITLE
    assert len(figure.axes[0].collections[0].get_offsets()) == 16
    app.show("graph", fixed)
    root.update()
    shot(root, "window-nb2-graph" + suffix + ".png")
    done("edit to Estimated ML: oracle, observed information, residual figure")

    # 3. The Poisson boundary: Fixed calculates, Estimated ML fails on the worker, the dialog reopens on its field
    #    and the last confirmed result stays.
    def boundary_fixed(dialog):
        tools.pick_method(dialog, NB2)
        choose(dialog)
        set_mode(dialog, "Fixed")
        dialog.controls["Dispersion alpha"][1].set("0.000001")

    boundary = analyse_with(boundary_fixed, BOUNDARY)
    kept_tables = {name: frame.copy() for name, frame in app.runs[boundary].result.tables.items()}
    kept_options = dict(app.runs[boundary].options)
    app.show("result", boundary)

    def poisson_banner(dialog, banner):
        assert "Poisson boundary" in banner and "Fixed" in banner, banner
        assert dialog.initial_field == "Dispersion mode"
        assert dialog.fields.select() == page_of(dialog, "Dispersion mode")
        assert dialog.controls["Dispersion mode"][1].get() == "Estimated ML"
        shot(dialog, "window-nb2-recovered" + suffix + ".png")

    def edit_to_ml():
        tools.drive_dialog(tools.AnalysisDialog, lambda dialog: set_mode(dialog, "Estimated ML"))
        app.edit_analysis()

    recover(edit_to_ml, poisson_banner)
    assert app.runs[boundary].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[boundary].result.tables[name], frame)
    done("Poisson boundary under Estimated ML reopens Dispersion mode and keeps the Fixed result")

    # 4. Categories and exposure: a change of exposure unit (hours instead of days) moves only the intercept.
    def categorical(dialog):
        tools.pick_method(dialog, NB2)
        choose(dialog, predictors=("Dose", "Batch"), categories=("Batch",))
        dialog.controls["Residual plot"][1].set(True)

    days = analyse_with(categorical, BATCHES)
    hours = analyse_with(categorical, HOURS)
    assert list(app.runs[days].result.tables) == SHEETS
    assert table(days, "Reference levels")["Reference"].to_dict() == {"Batch": "A"}
    a, b = table(days, "Coefficients"), table(hours, "Coefficients")
    assert list(a.index) == ["Intercept", "Dose", "Batch [B]", "Batch [C]"], list(a.index)
    np.testing.assert_allclose(b["Estimate"]["Intercept"], a["Estimate"]["Intercept"] - np.log(24), rtol=1e-7)
    np.testing.assert_allclose(b["Estimate"].iloc[1:], a["Estimate"].iloc[1:], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(b["SE"], a["SE"], rtol=1e-6)
    np.testing.assert_allclose(table(hours, "Model fit")["Alpha"], table(days, "Model fit")["Alpha"], rtol=1e-7)
    np.testing.assert_allclose(table(hours, "Fitted values")["Fitted count"],
                               table(days, "Fitted values")["Fitted count"], rtol=1e-7)
    done("categorical predictor and exposure unit change")

    # 5. Edit a cell and exclude a row: the run recalculates and keeps the physical source rows.
    app.show("data", BATCHES)
    count_column = app.tables[BATCHES].raw.columns.get_loc("Count")
    before = table(days, "Coefficients").copy()
    app.edit_cell(3, count_column, "12")
    wait()
    assert table(days, "Fitted values")["Observed"].iloc[3] == 12.0
    assert not table(days, "Coefficients").equals(before), "an edited count changes the estimates"
    app.show("data", BATCHES)
    app.current_grid.select((2, count_column))
    app.toggle_exclusion()
    wait()
    fitted = table(days, "Fitted values")
    fit = table(days, "Model fit").iloc[0]
    assert fit["N"] == 119 and fit["Incomplete rows"] == 1, fit
    assert 3 not in fitted["Source row"].tolist() and fitted["Source row"].tolist()[:3] == [1, 2, 4]
    done("edit and exclusion recalculation, physical source rows")

    # 6. A data edit that the model cannot use: the result stays, is flagged stale and the dialog names Response.
    kept_tables = {name: frame.copy() for name, frame in app.runs[days].result.tables.items()}

    def bad_count(dialog, banner):
        assert "Response" in banner and "whole counts" in banner and "row 5" in banner, banner
        assert dialog.initial_field == "Response"
        assert dialog.fields.select() == page_of(dialog, "Response")

    def edit_bad():
        app.show("data", BATCHES)
        app.edit_cell(4, count_column, "2.5")

    recover(edit_bad, bad_count)
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[days].result.tables[name], frame)
    assert app.runs[days].calculation_error and "whole counts" in app.runs[days].calculation_error
    app.show("result", days)
    assert app.stale_calculation_note() is not None, "the kept result must be flagged stale"
    app.show("data", BATCHES)
    app.edit_cell(4, count_column, "20")
    wait()
    assert app.runs[days].calculation_error is None and app.stale_calculation_note(("result", days)) is None
    done("an unusable count keeps the result, flags it stale, reopens Response and recovers")

    # 7. Italian: captions, choices, decimal comma and messages on their own fields; the recipe stays English.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, NB2)
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        assert tabs == ["Variabili", "Opzioni"], tabs
        captions = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
        assert captions == ["Risposta", "Predittori", "Predittori categorici", "Esposizione", "Dispersione",
                            "Alfa di dispersione", "Livello di confidenza (%)", "Grafico dei residui"], captions
        box = dialog.choice_bindings["Dispersion mode"].combobox
        assert list(box.cget("values")) == ["Stimata (ML)", "Fissa"] and box.get() == "Stimata (ML)"
        choose(dialog, predictors=("Dose", "Batch"))
        tools.select_columns(dialog, "Categorical predictors", ("Exposure",))
        rejected(dialog, "Categorical predictors", "vanno scelti fra i predittori", "window-nb2-it-error",
                 caption="I predittori categorici")
        tools.select_columns(dialog, "Categorical predictors", ("Batch",))
        set_mode(dialog, "Fissa")
        assert dialog.controls["Dispersion mode"][1].get() == "Fixed" and placed(dialog, "Dispersion alpha")
        dialog.controls["Dispersion alpha"][1].set("abc")
        rejected(dialog, "Dispersion alpha", "inserisci un numero", caption="Alfa di dispersione")
        dialog.controls["Dispersion alpha"][1].set("0,8")
        dialog.controls["Residual plot"][1].set(True)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-nb2-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-nb2-it-options" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, HOURS)
        assert app.runs[italian_index].options["Dispersion mode"] == "Fixed"
        assert app.runs[italian_index].options["Dispersion alpha"] == 0.8
        assert table(italian_index, "Model fit")["Alpha"].iloc[0] == 0.8
        app.show("result", italian_index)
        app.result_tabs.select(0)
        root.update()
        shot(root, "window-nb2-it-results" + suffix + ".png")
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-nb2-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    done("Italian dialog and messages, canonical recipe")

    # 8. Exports: CSV of each table, then PNG, SVG and PDF of the residual figure.
    app.show("result", days)
    for position, name in enumerate(SHEETS):
        app.result_tabs.select(position)
        target = out / f"nb2-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert list(exported.columns) == list(table(days, name).columns), name
        assert len(exported) == len(table(days, name)), name
        if name == "Fitted values":
            assert exported["Source row"].tolist() == table(days, name)["Source row"].tolist()
    app.show("graph", days)
    root.update()
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"nb2-residuals.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg_text = (exports / "nb2-residuals.svg").read_text(encoding="utf-8")
    assert "<image" not in svg_text and (svg_text.count("<use") >= 119 or svg_text.count("<path") >= 119), \
        "the markers stay vector elements"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "nb2-residuals.pdf")
    assert "Pearson residual" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    done("CSV, PNG, SVG and PDF exports")

    # 9. Save, reopen and open the results: canonical recipes, the same tables.
    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                for run in app.runs if run.method == NB2 and run.result is not None}
    assert len(expected) >= 4, sorted(expected)
    app.path = directory / "nb2-regression-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == NB2:
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    done("save and reopen")

    # 10. Use Result as Data keeps the source rows of the fitted table.
    position = next(i for i, run in enumerate(app.runs) if run.method == NB2 and run.title == BATCHES)
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(2)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert {"Source row", "Observed", "Fitted count", "Pearson residual"} <= set(frame.columns), frame.columns
    assert len(frame) == 119
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")

    # 11. A Poisson recipe of Multiple regression saved before this method keeps its tables.
    from .workbench import analyse
    legacy = analyse("Multiple regression", _counts(), {"Response": "Count", "Predictors": ["Treatment"],
                                                        "Categorical predictors": [], "Family": "Poisson",
                                                        "Exposure": "Exposure"})
    assert list(legacy.tables) == ["Coefficients", "Model", "Fitted values"], list(legacy.tables)
    # Saturated groups: the Poisson rates are the observed ones, 1.5 and 2.25 per unit of exposure.
    np.testing.assert_allclose(legacy.tables["Coefficients"]["Estimate"].to_numpy(float), [np.log(1.5)] * 2,
                               rtol=1e-7)
    done("legacy Poisson recipe unchanged")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
