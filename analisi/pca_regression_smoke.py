"""Desktop smoke check for the principal component regression of the PCA dialog.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=pca-regression``) calls :func:`check_pca_regression`.
Widgets are driven and events are generated. This is not a native pointer session.
"""
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from tkinter import ttk

from . import pca_regression, ui_theme
from .data import Dataset, save_project
from .i18n import active_language, set_language, ui
from .pca_retention import FIXED, RETAINED, SELECTION
from .workbench import METHODS, analyse

METHOD = "Principal component analysis"
TITLE = "Acque"
SPARSE = "Poche risposte"
COND, TEMP, TURB = "Conducibilità µS", "Temperatura °C", "Torbidità"
RESP, BACKUP, SPARE = "Corrosione (€/anno)", "Riserva", "Alternativa"
PREDICTORS = [COND, TEMP, TURB]
ENABLE, RESPONSE, CONFIDENCE, PLOT = (pca_regression.ENABLE, pca_regression.RESPONSE,
                                     pca_regression.CONFIDENCE, pca_regression.PLOT)
COEF, SCORE_COEF, MODEL, FITTED = (pca_regression.COEFFICIENTS, pca_regression.SCORE_COEFFICIENTS,
                                   pca_regression.MODEL, pca_regression.FITTED)
OBSERVED, RESIDUALS, KEEP = pca_regression.OBSERVED, pca_regression.RESIDUALS, pca_regression.KEEP
HISTORICAL = ["Explained variance", "Eigenvectors", "Scores"]
NO_RESPONSE_ROW, NO_PREDICTOR_ROW = 5, 9
FITTED_COLUMNS = ["Source row", "Observed", "Fitted", "Residual", "Used in fit", "Mean lower", "Mean upper",
                  "Prediction lower", "Prediction upper"]


def _frame():
    """Synthetic water-quality table: one response observed almost everywhere, one never missing."""
    rng = np.random.default_rng(87)
    count = 16
    latent = rng.normal(size=count)
    turbidity = 3 + rng.normal(size=count)
    frame = pd.DataFrame({
        "Sito": [f"Sorgente {index + 1}" for index in range(count)],
        COND: 5 + 2 * latent + rng.normal(scale=.5, size=count),
        TEMP: 18 + 1.5 * latent + rng.normal(scale=.7, size=count),
        TURB: turbidity,
        RESP: 10 + 1.2 * latent + .5 * turbidity + rng.normal(scale=.4, size=count),
    }).round(3)
    frame[BACKUP] = (frame[RESP] + rng.normal(scale=.3, size=count)).round(3)
    frame.loc[NO_RESPONSE_ROW, RESP] = np.nan      # complete predictors, no response: fitted only
    frame.loc[NO_PREDICTOR_ROW, TEMP] = np.nan     # response observed, a predictor missing: left out
    return frame


def _sparse():
    """Complete predictors and only two observed responses: too few rows for one component plus intercept."""
    frame = _frame().iloc[:8].copy()
    frame.loc[:, RESP] = np.nan
    frame.loc[[1, 4], RESP] = [10.5, 12.25]
    frame[BACKUP] = _frame()[BACKUP].iloc[:8].to_numpy()
    frame[SPARE] = (frame[BACKUP] + .25).round(3)
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
    assert button.winfo_rootx() + button.winfo_width() <= bounds[0] + 1, text
    assert button.winfo_rooty() + button.winfo_height() <= bounds[1] + 1, text
    return button


def check_pca_regression(root, app, directory, kit):
    directory = Path(directory)
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, kit)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _check(root, app, directory, kit):
    capture, pick, select, wait, errors = kit.capture, kit.pick_method, kit.select_columns, kit.wait_for_calculation, kit.errors
    messagebox, filedialog = kit.messagebox, kit.filedialog
    suffix = "-modern" if ui_theme.is_modern() else ""

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

    def reject(dialog, field, caption):
        """The dialog refuses, stays open, names the field and moves the focus to it."""
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert caption in message, message
        assert dialog.winfo_exists() and dialog.result is None
        assert dialog.focus_get() is dialog.field_rows[field][1], (field, dialog.focus_get())
        assert str(dialog.fields.select()) == str(dialog.field_rows[field][1].master), field
        return message

    def run_dialog(action, *, accept=True):
        holder = drive(action, accept=accept)
        app.choose_analysis()
        finish(holder)
        wait()
        assert not errors, errors

    def masked(title=TITLE):
        return app.tables[title].frame(mask_excluded=True)

    def tables_of(index):
        return app.runs[index].result.tables

    def same_as_engine(index, title=TITLE):
        """The worker reproduces a direct call of the engine on the same masked table, sheet by sheet."""
        run = app.runs[index]
        expected = analyse(METHOD, masked(title), run.options)
        assert list(run.result.tables) == list(expected.tables), (list(run.result.tables), list(expected.tables))
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], table, obj=name)
        return run.result.tables

    def check_back_transformation(tables):
        """Fitted values equal intercept + original-unit slopes · predictors, for every row with predictors."""
        coefficients = tables[COEF].set_index("Term")["Estimate"]
        fitted = tables[FITTED]
        rows = masked().loc[fitted["Source row"].to_numpy(), PREDICTORS].astype(float)
        by_hand = coefficients["Intercept"] + rows.to_numpy() @ coefficients[PREDICTORS].to_numpy()
        np.testing.assert_allclose(fitted["Fitted"].to_numpy(), by_hand, rtol=1e-9, atol=1e-9)

    def regression_options(dialog, response=RESP, plot=KEEP, level="90", count=1):
        select(dialog, "Variables", set(PREDICTORS))
        dialog.controls[ENABLE][1].set(True)
        dialog.controls[RESPONSE][1].set(response)
        dialog.controls[CONFIDENCE][1].set(level)
        dialog.controls[PLOT][1].set(plot)
        dialog.controls[SELECTION][1].set(FIXED)
        dialog.controls[RETAINED][1].set(str(count))
        dialog.update_idletasks()

    path = directory / "pca-regression.alab"
    save_project(path, {TITLE: Dataset(_frame()), SPARSE: Dataset(_sparse())})
    app.import_file(path)
    app.show("data", TITLE)
    root.update()

    # 1. PCR off: the base PCA sheets, with the controls shown but not used.
    def plain(dialog):
        pick(dialog, METHOD)
        select(dialog, "Variables", set(PREDICTORS))
        tab = dialog.field_rows[ENABLE][0].master
        assert dialog.fields.tab(tab, "text") == "Regression"
        assert dialog.field_rows[ENABLE][0].cget("text") == "Principal component regression"
        assert dialog.controls[ENABLE][1].get() is False
        for name in (RESPONSE, CONFIDENCE, PLOT):
            assert str(dialog.field_rows[name][1].cget("state")) == "disabled", name
        dialog.fields.select(tab)
        dialog.update_idletasks()
        shot(dialog, "window-pca-regression-off.png")

    run_dialog(plain)
    off = app.runs[-1]
    off_index = len(app.runs) - 1
    assert off.options[ENABLE] is False
    plain_options = {key: value for key, value in off.options.items() if key not in pca_regression.OPTION_NAMES}
    reference = analyse(METHOD, masked(), plain_options)
    assert list(off.result.tables) == list(reference.tables)
    assert not set(pca_regression.SHEETS) & set(off.result.tables)
    assert list(off.result.tables)[:3] == HISTORICAL
    for name, table in reference.tables.items():
        pd.testing.assert_frame_equal(off.result.tables[name], table, obj=name)
    assert off.result.figure.axes[0].get_xlabel().startswith("PC1"), off.result.figure.axes[0].get_xlabel()
    assert off.result.figure.axes[0].get_ylabel().startswith("PC2"), off.result.figure.axes[0].get_ylabel()

    # 2-3. Field errors keep the dialog open with the focus on the field; then a real regression on one component.
    def configure(dialog):
        pick(dialog, METHOD)
        select(dialog, "Variables", set(PREDICTORS))
        dialog.controls[ENABLE][1].set(True)
        dialog.update_idletasks()
        for name, state in ((RESPONSE, "readonly"), (CONFIDENCE, "normal"), (PLOT, "readonly")):
            assert str(dialog.field_rows[name][1].cget("state")) == state, name
        reject(dialog, RESPONSE, "PCR response")
        shot(dialog, "window-pca-regression-error-response.png")
        dialog.controls[RESPONSE][1].set(PREDICTORS[0])
        reject(dialog, RESPONSE, "PCR response")
        dialog.controls[RESPONSE][1].set(RESP)
        dialog.controls[CONFIDENCE][1].set("100")
        reject(dialog, CONFIDENCE, "PCR confidence")
        assert dialog.controls[CONFIDENCE][1].get() == "100"
        shot(dialog, "window-pca-regression-error-level.png")
        dialog.controls[CONFIDENCE][1].set("90")
        regression_options(dialog, plot=OBSERVED)
        dialog.fields.select(dialog.field_rows[ENABLE][0].master)
        dialog.update_idletasks()
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        _reachable(dialog, root, "Run Analysis")
        _reachable(dialog, root, "Cancel")
        shot(dialog, "window-pca-regression-dialog.png")
        assert dialog.validate() is True
        recipe = dialog.result[1]
        assert recipe[ENABLE] is True and recipe[RESPONSE] == RESP and recipe[CONFIDENCE] == 90.0
        assert recipe[PLOT] == OBSERVED and recipe[SELECTION] == FIXED and recipe[RETAINED] == 1
        dialog.result = None

    started = time.monotonic()
    run_dialog(configure)
    index = len(app.runs) - 1
    run = app.runs[index]
    tables = same_as_engine(index)
    assert list(tables)[:len(HISTORICAL)] == HISTORICAL
    assert list(tables)[-len(pca_regression.SHEETS):] == list(pca_regression.SHEETS)
    model = tables[MODEL].iloc[0]
    assert len(tables[MODEL]) == 1 and model["Components"] == 1 and model["Confidence (%)"] == 90.0
    count = int(masked()[PREDICTORS].notna().all(axis=1).sum())
    assert model["PCA rows"] == count and model["Regression rows"] == count - 1
    assert list(tables[FITTED].columns)[:len(FITTED_COLUMNS)] == FITTED_COLUMNS
    assert list(tables[COEF]["Term"]) == ["Intercept", *PREDICTORS]
    assert list(tables[SCORE_COEF]["Term"]) == ["Intercept", "PC1"]
    absent = tables[FITTED].set_index("Source row")
    assert NO_PREDICTOR_ROW not in absent.index
    assert absent.loc[NO_RESPONSE_ROW, "Used in fit"] == False  # noqa: E712 - numpy bool
    assert pd.isna(absent.loc[NO_RESPONSE_ROW, "Observed"]) and pd.isna(absent.loc[NO_RESPONSE_ROW, "Residual"])
    assert np.isfinite(absent.loc[NO_RESPONSE_ROW, ["Fitted", "Mean lower", "Prediction upper"]].to_numpy(float)).all()
    check_back_transformation(tables)
    assert run.options[ENABLE] is True and run.options[PLOT] == OBSERVED

    app.show("result", index)
    app.result_tabs.select(list(tables).index(COEF))
    root.update()
    shot(root, "window-pca-regression-coefficients.png")
    app.result_tabs.select(list(tables).index(MODEL))
    root.update()
    shot(root, "window-pca-regression-model.png")
    app.result_tabs.select(list(tables).index(FITTED))
    root.update()
    shot(root, "window-pca-regression-fitted.png")

    app.show("graph", index)
    root.update()
    axes = run.result.figure.axes[0]
    assert (axes.get_xlabel(), axes.get_ylabel()) == ("Fitted", "Observed")
    points = sum(len(item.get_offsets()) for item in axes.collections)
    assert points == count - 1, points  # only the rows used in the fit
    assert any(len(line.get_xdata()) == 2 and np.allclose(line.get_xdata(), line.get_ydata()) for line in axes.lines)
    shot(root, "window-pca-regression-graph-observed.png")

    # Residuals view through the edit dialog (the Run button stays reachable).
    def residuals(dialog):
        assert dialog.controls[ENABLE][1].get() is True and dialog.controls[RESPONSE][1].get() == RESP
        dialog.controls[PLOT][1].set(RESIDUALS)
        dialog.fields.select(dialog.field_rows[ENABLE][0].master)
        dialog.update_idletasks()
        _reachable(dialog, root, "Run Analysis")

    holder = drive(residuals)
    app.edit_analysis()
    finish(holder)
    wait()
    run = app.runs[index]
    same_as_engine(index)
    app.show("graph", index)
    root.update()
    axes = run.result.figure.axes[0]
    assert (axes.get_xlabel(), axes.get_ylabel()) == ("Fitted", "Residual")
    assert sum(len(item.get_offsets()) for item in axes.collections) == count - 1
    assert any(np.allclose(line.get_ydata(), 0) for line in axes.lines)
    shot(root, "window-pca-regression-graph-residuals.png")
    assert run.options[PLOT] == RESIDUALS and run.options[CONFIDENCE] == 90.0

    # 4. Masks: a response edit leaves the PCA alone; an excluded response and an excluded predictor do not.
    app.show("data", TITLE)
    pca_before = {name: tables_of(index)[name].copy() for name in HISTORICAL}
    fitted_before = tables_of(index)[FITTED].copy()
    column = lambda name: list(app.get_dataset().raw.columns).index(name)  # noqa: E731
    app.edit_cell(2, column(RESP), "15.5")
    wait()
    after = same_as_engine(index)
    for name in HISTORICAL:
        pd.testing.assert_frame_equal(after[name], pca_before[name], obj=name)
    assert not np.allclose(after[FITTED]["Fitted"], fitted_before["Fitted"])

    app.show("data", TITLE)
    app.current_grid.active_cell = (7, column(RESP))
    app.toggle_exclusion()
    wait()
    after = same_as_engine(index)
    model = after[MODEL].iloc[0]
    assert model["PCA rows"] == count and model["Regression rows"] == count - 2
    row = after[FITTED].set_index("Source row").loc[7]
    assert row["Used in fit"] == False and pd.isna(row["Observed"]) and np.isfinite(row["Fitted"])  # noqa: E712
    pd.testing.assert_frame_equal(after["Eigenvectors"], tables_of(index)["Eigenvectors"])
    for name in HISTORICAL:
        assert len(after[name]) > 0

    app.show("data", TITLE)
    app.current_grid.active_cell = (12, column(TURB))
    app.toggle_exclusion()
    wait()
    after = same_as_engine(index)
    model = after[MODEL].iloc[0]
    assert model["PCA rows"] == count - 1 and model["Regression rows"] == count - 3
    assert 12 not in set(after[FITTED]["Source row"])
    check_back_transformation(after)
    app.show("graph", index)
    root.update()
    shot(root, "window-pca-regression-masks.png")

    # A fit that cannot be estimated: the dialog refuses on the response field and keeps the parameters.
    app.show("data", SPARSE)
    seen = {}

    def refused(dialog):
        pick(dialog, METHOD)
        regression_options(dialog, response=RESP, plot=KEEP, level="90,5", count=1)
        seen["message"] = reject(dialog, RESPONSE, "PCR response")
        seen["kept"] = (dialog.controls[ENABLE][1].get(), dialog.controls[RESPONSE][1].get(),
                        dialog.controls[CONFIDENCE][1].get(), dialog.controls[SELECTION][1].get(),
                        dialog.controls[RETAINED][1].get())
        shot(dialog, "window-pca-regression-rank-error.png")
        dialog.controls[RESPONSE][1].set(BACKUP)

    before_runs = len(app.runs)
    run_dialog(refused)
    assert "more than 2 rows" in seen["message"], seen
    assert seen["kept"][:2] == (True, RESP) and seen["kept"][3] == FIXED and str(seen["kept"][4]) == "1", seen
    assert str(seen["kept"][2]) == "90,5", seen
    assert len(app.runs) == before_runs + 1
    sparse_index = len(app.runs) - 1
    corrected = app.runs[sparse_index]
    assert corrected.options[RESPONSE] == BACKUP and corrected.options[CONFIDENCE] == 90.5
    sparse_tables = same_as_engine(sparse_index, SPARSE)
    assert sparse_tables[MODEL].iloc[0]["Regression rows"] == sparse_tables[MODEL].iloc[0]["PCA rows"] == 8

    # The same failure first known on the worker (a data edit) reopens the dialog on the response field,
    # keeps the last good result as stale and lets the parameters be corrected.
    sparse_column = list(app.tables[SPARSE].raw.columns).index(BACKUP)
    for row in range(5):
        app.show("data", SPARSE)
        app.current_grid.active_cell = (row, sparse_column)
        app.toggle_exclusion()
        wait()
    assert app.runs[sparse_index].calculation_error is None
    assert app.runs[sparse_index].result.tables[MODEL].iloc[0]["Regression rows"] == 3
    kept_result = app.runs[sparse_index].result
    seen.clear()

    def reopened_on_worker(dialog):
        seen["focus"] = dialog.focus_get() is dialog.field_rows[RESPONSE][1]
        seen["banner"] = dialog.error
        seen["kept"] = (dialog.controls[ENABLE][1].get(), dialog.controls[RESPONSE][1].get(),
                        dialog.controls[CONFIDENCE][1].get(), dialog.controls[RETAINED][1].get())
        shot(dialog, "window-pca-regression-recovery.png")

    holder = drive(reopened_on_worker, accept=False)
    app.show("data", SPARSE)
    app.current_grid.active_cell = (5, sparse_column)
    app.toggle_exclusion()
    wait()
    finish(holder)
    wait()
    assert seen["focus"] and "PCR response" in seen["banner"] and "more than 2 rows" in seen["banner"], seen
    assert seen["kept"][:2] == (True, BACKUP) and str(seen["kept"][3]) == "1", seen
    assert app.runs[sparse_index].result is kept_result and app.runs[sparse_index].calculation_error
    app.show("result", sparse_index)
    assert app.stale_calculation_note()
    shot(root, "window-pca-regression-stale.png")

    def corrected_response(dialog):
        dialog.controls[RESPONSE][1].set(SPARE)

    holder = drive(corrected_response)
    app.edit_analysis()
    finish(holder)
    wait()
    fixed = app.runs[sparse_index]
    assert fixed.calculation_error is None and fixed.result is not kept_result
    assert fixed.options[RESPONSE] == SPARE and fixed.options[CONFIDENCE] == 90.5
    assert fixed.options[SELECTION] == FIXED and fixed.options[RETAINED] == 1
    assert same_as_engine(sparse_index, SPARSE)[MODEL].iloc[0]["Regression rows"] == 8
    assert not errors, errors

    # 5. Save, reopen from the graph, edit the options, export, and reuse the fitted values as data.
    app.show("data", TITLE)
    assert app.save()
    app.import_file(app.path)
    assert app.runs[index].result is None
    app.open_sheet(("graph", index))
    wait()
    reopened = app.runs[index]
    assert reopened.options[ENABLE] is True and reopened.options[RESPONSE] == RESP
    assert reopened.options[CONFIDENCE] == 90.0 and reopened.options[PLOT] == RESIDUALS
    same_as_engine(index)
    assert reopened.result.figure.axes[0].get_ylabel() == "Residual"
    root.update()
    shot(root, "window-pca-regression-reopen.png")

    def edited(dialog):
        dialog.controls[CONFIDENCE][1].set("95")
        dialog.controls[PLOT][1].set(OBSERVED)

    holder = drive(edited)
    app.edit_analysis()
    finish(holder)
    wait()
    again = app.runs[index]
    assert again.options[CONFIDENCE] == 95.0 and again.options[PLOT] == OBSERVED
    assert again.options[SELECTION] == FIXED and again.options[RESPONSE] == RESP
    same_as_engine(index)
    assert again.result.tables[MODEL].iloc[0]["Confidence (%)"] == 95.0
    wider = again.result.tables[FITTED]["Prediction upper"] - again.result.tables[FITTED]["Prediction lower"]
    assert np.isfinite(wider).all() and (wider > 0).all()

    app.show("graph", index)
    for extension in ("png", "svg"):
        target = directory / f"pca-regression.{extension}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, extension
    assert "<svg" in (directory / "pca-regression.svg").read_text(encoding="utf-8")
    assert (directory / "pca-regression.png").read_bytes().startswith(b"\x89PNG")
    sheets = list(app.runs[index].result.tables)
    app.show("result", index)
    app.result_tabs.select(sheets.index(FITTED))
    csv_path = directory / "pca-regression-fitted.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    # The application writes the row index of a result sheet as an unnamed first column.
    exported = exported.drop(columns=[name for name in exported.columns if str(name).startswith("Unnamed")])
    assert list(exported.columns)[:len(FITTED_COLUMNS)] == FITTED_COLUMNS, list(exported.columns)
    pd.testing.assert_series_equal(exported["Source row"], app.runs[index].result.tables[FITTED]["Source row"],
                                   check_dtype=False, check_names=False)

    before_tables = set(app.tables)
    app.result_tabs.select(sheets.index(FITTED))
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert added == {FITTED}, added
    reused = app.tables[FITTED].raw
    assert list(reused.columns) == list(app.runs[index].result.tables[FITTED].columns)
    assert reused["Source row"].tolist() == app.runs[index].result.tables[FITTED]["Source row"].tolist()

    # 6. Inspector: retitle and apply, then reopen the saved project.
    app.show("graph", index)
    root.update()
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector is not None
    inspector.vars["title"].set("Osservati e stimati")
    inspector._now("title")
    assert inspector.apply() is True
    app.toggle_inspector()
    assert app.runs[index].result.figure.axes[0].get_title() == "Osservati e stimati"
    assert app.runs[index].options[PLOT] == OBSERVED
    app.show("data", TITLE)
    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("graph", index))
    wait()
    assert app.runs[index].result.figure.axes[0].get_title() == "Osservati e stimati"
    root.update()
    shot(root, "window-pca-regression-inspector.png")

    # Italian: labels, canonical recipe values, errors and decimal comma.
    set_language("it")
    app.show("data", TITLE)

    def italian(dialog):
        pick(dialog, METHOD)
        select(dialog, "Variables", set(PREDICTORS))
        tab = dialog.field_rows[ENABLE][0].master
        assert dialog.fields.tab(tab, "text") == "Regressione"
        assert dialog.field_rows[ENABLE][0].cget("text") == "Regressione sulle componenti principali"
        assert dialog.field_rows[RESPONSE][0].cget("text") == "Risposta PCR"
        assert dialog.field_rows[CONFIDENCE][0].cget("text") == "Confidenza PCR (%)"
        assert dialog.field_rows[PLOT][0].cget("text") == "Grafico PCR"
        assert list(dialog.field_rows[PLOT][1].cget("values")) == [
            "Mantieni grafico PCA", "Osservati rispetto agli stimati", "Residui rispetto agli stimati"]
        dialog.controls[ENABLE][1].set(True)
        dialog.update_idletasks()
        reject(dialog, RESPONSE, "Risposta PCR")
        dialog.controls[RESPONSE][1].set(RESP)
        dialog.controls[CONFIDENCE][1].set("100")
        reject(dialog, CONFIDENCE, "Confidenza PCR")
        shot(dialog, "window-pca-regression-error-it.png")
        dialog.controls[CONFIDENCE][1].set("90,5")
        dialog.field_rows[PLOT][1].set("Residui rispetto agli stimati")
        dialog.controls[SELECTION][1].set(FIXED)
        dialog.controls[RETAINED][1].set("2")
        dialog.update_idletasks()
        _reachable(dialog, root, "Run Analysis")
        shot(dialog, "window-pca-regression-dialog-it.png")

    run_dialog(italian)
    it_index = len(app.runs) - 1
    italian_run = app.runs[it_index]
    assert italian_run.options[PLOT] == RESIDUALS and italian_run.options[CONFIDENCE] == 90.5
    assert italian_run.options[RESPONSE] == RESP
    assert set(italian_run.options) <= set(METHODS[METHOD]), set(italian_run.options) - set(METHODS[METHOD])
    same_as_engine(it_index)
    assert list(tables_of(it_index))[-len(pca_regression.SHEETS):] == list(pca_regression.SHEETS)
    assert tables_of(it_index)[MODEL].iloc[0]["Components"] == 2
    app.show("graph", it_index)
    root.update()
    shot(root, "window-pca-regression-graph-it.png")
    app.show("result", it_index)
    app.result_tabs.select(list(tables_of(it_index)).index(MODEL))
    root.update()
    shot(root, "window-pca-regression-model-it.png")
    set_language("en")

    if root.winfo_screenwidth() >= 1680 and root.winfo_screenheight() >= 1050:
        root.geometry("1600x1000+0+0")
        root.update()
        app.show("graph", index)
        root.update()
        shot(root, "window-pca-regression-1600.png")

        def wide(dialog):
            pick(dialog, METHOD)
            regression_options(dialog, plot=OBSERVED)
            dialog.fields.select(dialog.field_rows[ENABLE][0].master)
            dialog.update_idletasks()
            _reachable(dialog, root, "Run Analysis")
            shot(dialog, "window-pca-regression-dialog-1600.png")
            dialog.result = None

        holder = drive(wide, accept=False)
        app.show("data", TITLE)
        app.choose_analysis()
        finish(holder)
        assert not errors, errors
    else:
        # A real 1024×768 screen cannot show the 1600×1000 window. Run the check again on a larger screen for it.
        print("pca-regression smoke: the 1600×1000 phase needs a screen of at least 1680×1050 and was skipped.")
    assert not errors, errors
    print(f"pca-regression smoke{suffix}: {time.monotonic() - started:.1f} s of driven work")
