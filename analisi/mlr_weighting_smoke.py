"""Desktop smoke check for the fixed Gaussian weights of Multiple regression (0.70), driving the real dialog.

``tramastat.py --smoke`` calls :func:`check_mlr_weighting` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=mlr-weighting python tramastat.py --smoke DIR``.

Synthetic data only. Expected values are written here with NumPy as least squares on sqrt(weight)·(D, y),
independent of the statsmodels fit the application uses. The dialog is driven through its own widgets and
variables (no clicks by a person), and Windows is not exercised here.
"""
import traceback
import threading
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, mlr_weighting as mw
from .data import Dataset
from .workbench import analyse

TITLE, ZERO, LEGACY = "Weighted regression", "Zero response", "Unweighted history"
ROWS = {"X1": [-2., -1, 0, 1, 2, -2, -1, 0, 1, 2, np.nan], "X2": [0., 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        "Y": [4., 5.5, 8, 11, 11.5, 6.5, 6, 10, 9.5, 14, 999],
        "W": [1., .5, 2, 4, 1.5, 3, 2.5, .75, 5, 1, 0], "SD": [1., 2, .5, 1.5, 3, 2, 1, .75, 1.2, 2, 0]}
FRAME = pd.DataFrame(ROWS)
PROFILES = [{"name": "P1", "values": {"X1": 1.0, "X2": 0.5}, "weight": 3.0},
            {"name": "P2", "values": {"X1": 0.0, "X2": 0.0}, "weight": 0.8}]
LABELS = {"it": {"mode": "Varianza inversa (colonna SD)"}}


def reference(frame, column):
    """Closed-form WLS on the complete rows: coefficients, covariance, leverage, Cook and normalised weights."""
    rows = frame.dropna(subset=["X1", "X2", "Y", column])
    rows = rows[rows[column] > 0]
    w = 1.0 / rows["SD"].to_numpy(float) ** 2 if column == "SD" else rows[column].to_numpy(float)
    wn = w / w.max()
    d = np.column_stack([np.ones(len(rows)), rows["X1"], rows["X2"]])
    y = rows["Y"].to_numpy(float)
    root = np.sqrt(wn)
    beta = np.linalg.lstsq(root[:, None] * d, root * y, rcond=None)[0]
    r = y - d @ beta
    df = len(y) - 3
    s2 = float((root * r) @ (root * r)) / df
    q, _ = np.linalg.qr(root[:, None] * d)
    h = (q * q).sum(axis=1)
    cov = s2 * np.linalg.inv(d.T @ (wn[:, None] * d))
    cook = (root * r) ** 2 * h / (3 * s2 * (1 - h) ** 2)
    return dict(beta=beta, cov=cov, h=h, cook=cook, wn=wn, rows=rows.index.to_numpy(), s2=s2, w=w, df=df,
                press=r / (1 - h))


def check_mlr_weighting(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "mlr-weighting"
    out.mkdir(exist_ok=True)
    previous_geometry = root.geometry()
    root.update()
    zero = FRAME.copy()
    zero.loc[3, "Y"] = 0.0
    app.tables[TITLE] = Dataset(FRAME.copy())
    app.tables[ZERO] = Dataset(zero)
    app.tables[LEGACY] = Dataset(FRAME.copy())
    app.refresh_navigator()

    def shot(window, name):
        tools.capture(window, name)
        source = directory / name
        if source.exists():
            source.replace(out / name)

    def find_dialog(parent=None):
        for child in (parent or root).winfo_children():
            if isinstance(child, tools.AnalysisDialog):
                return child
            found = find_dialog(child)
            if found is not None:
                return found

    def drive(action, *, accept):
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
                if accept:
                    dialog.ok()
                else:
                    # Explicit validate() probes above can fill result. A user
                    # Cancel must discard that probe rather than submit a fit.
                    dialog.result = None
                    dialog.cancel()
            except Exception as error:
                errors.append(f"{error!r}\n{traceback.format_exc()}")
                try:
                    dialog.cancel()
                except Exception:
                    pass

        root.after(100, enter)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot_name=None, contains=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (contains or field) in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        target = dialog.field_rows[field][1]
        focus = target.focus_target() if hasattr(target, "focus_target") else None
        assert dialog.initial_focus is (focus or dialog.initial_focus), (dialog.initial_focus, focus)
        if shot_name:
            shot(dialog, shot_name)
        return message

    def prepare(dialog):
        tools.pick_method(dialog, "Multiple regression")
        dialog.controls["Response"][1].set("Y")
        tools.select_columns(dialog, "Predictors", {"X1", "X2"})
        tools.select_columns(dialog, "Categorical predictors", set())
        dialog.show_regression_fields()

    def add_profile(editor, record):
        editor.label.set(record["name"])
        for name, value in record["values"].items():
            editor.inputs[name].set(str(value))
        if editor.weight_enabled:
            editor.weight.set(str(record["weight"]).replace(".", ","))
        assert editor.add(), editor.note.cget("text")

    # 1. The English dialog: conditional fields, rejected input with focus, correction in the same dialog.
    def configure(dialog):
        prepare(dialog)
        mode = dialog.controls[mw.GAUSSIAN_WEIGHTING][1]
        assert mode.get() == mw.UNWEIGHTED
        assert placed(dialog, mw.GAUSSIAN_WEIGHTING)
        assert not any(placed(dialog, name) for name in (mw.EXPONENT, mw.SD_COLUMN, mw.WEIGHT_COLUMN,
                                                         mw.FUTURE_PRECISION))
        assert tuple(dialog.field_rows[mw.GAUSSIAN_WEIGHTING][1].cget("values")) == mw.MODES
        weighting_tab = dialog.field_rows[mw.GAUSSIAN_WEIGHTING][0].master
        assert dialog.field_rows[mw.SD_COLUMN][0].master is weighting_tab is dialog.field_rows["Family"][0].master
        for family in ("Poisson", "Logistic"):
            dialog.controls["Family"][1].set(family)
            dialog.update()
            assert not placed(dialog, mw.GAUSSIAN_WEIGHTING), family
            assert dialog.mlr_note.cget("text") == "", family
        dialog.controls["Family"][1].set("Linear")
        assert placed(dialog, mw.GAUSSIAN_WEIGHTING)
        dialog.fields.select(weighting_tab)
        mode.set(mw.ABS_Y_POWER)
        dialog.update()
        assert placed(dialog, mw.EXPONENT) and not placed(dialog, mw.SD_COLUMN)
        dialog.controls[mw.EXPONENT][1].set("abc")
        rejected(dialog, mw.EXPONENT, "window-mlrw-exponent-error.png")
        dialog.controls[mw.EXPONENT][1].set("1,3")
        assert dialog.validate() is True and dialog.result[1][mw.EXPONENT] == 1.3
        assert mw.SD_COLUMN not in dialog.result[1] and mw.WEIGHT_COLUMN not in dialog.result[1]
        mode.set(mw.INVERSE_VARIANCE)
        dialog.update()
        assert placed(dialog, mw.SD_COLUMN) and not placed(dialog, mw.EXPONENT)
        rejected(dialog, mw.SD_COLUMN, "window-mlrw-sd-error.png")
        dialog.controls[mw.SD_COLUMN][1].set("SD")
        shot(dialog, "window-mlrw-sd-column.png")
        # The prediction precision of the profiles appears with the first profile and only for a weighted fit.
        editor = dialog.controls["Linear profiles"][1]
        assert not placed(dialog, mw.FUTURE_PRECISION) and not editor.weight_enabled
        add_profile(editor, {"name": "P1", "values": {"X1": 1.0, "X2": 0.5}})
        dialog.update()
        assert placed(dialog, mw.FUTURE_PRECISION) and not editor.weight_enabled
        dialog.controls[mw.FUTURE_PRECISION][1].set(True)
        dialog.update()
        assert editor.weight_enabled and editor.weight_frame.winfo_manager()
        message = rejected(dialog, "Linear profiles", "window-mlrw-profile-weight-error.png", contains="P1")
        assert "weight" in message, message
        editor.profiles.clear()
        editor.refresh()
        for record in PROFILES:
            add_profile(editor, record)
        mode.set(mw.UNWEIGHTED)
        dialog.update()
        assert not placed(dialog, mw.FUTURE_PRECISION) and not editor.weight_enabled
        mode.set(mw.INVERSE_VARIANCE)
        dialog.update()
        assert placed(dialog, mw.FUTURE_PRECISION) and editor.weight_enabled
        dialog.controls["Linear diagnostics"][1].set(True)
        dialog.controls["Linear residual plot"][1].set("Residuals vs fitted")
        dialog.fields.select(dialog.field_rows["Linear profiles"][1].master)
        shot(dialog, "window-mlrw-profiles.png")
        dialog.fields.select(weighting_tab)
        shot(dialog, "window-mlrw-dialog.png")
        assert dialog.validate() is True
        options = dialog.result[1]
        assert options[mw.GAUSSIAN_WEIGHTING] == mw.INVERSE_VARIANCE and options[mw.SD_COLUMN] == "SD"
        assert options[mw.FUTURE_PRECISION] is True and options["Linear profiles"] == PROFILES
        assert mw.EXPONENT not in options and mw.WEIGHT_COLUMN not in options
        dialog.result = None

    app.show("data", TITLE)
    root.update()
    drive(configure, accept=True)
    fit_threads = []
    original_fit = mw.weighted_linear_fit
    def observed_fit(*args, **kwargs):
        fit_threads.append(threading.current_thread())
        return original_fit(*args, **kwargs)
    with patch.object(mw, "weighted_linear_fit", observed_fit):
        app.choose_analysis()
        wait()
    assert len(fit_threads) == 1 and fit_threads[0] is not threading.main_thread(), fit_threads
    assert not errors, errors
    index = len(app.runs) - 1
    run = app.runs[index]
    expected = reference(FRAME, "SD")
    names = list(run.result.tables)
    assert names == ["Coefficients", "Model", "Fitted values", "Linear weights", "Linear diagnostics",
                     "Linear model diagnostics", "Linear predictions"], names
    tables = run.result.tables
    np.testing.assert_allclose(tables["Coefficients"]["Estimate"], expected["beta"], rtol=2e-9, atol=2e-10)
    np.testing.assert_allclose(tables["Coefficients"]["SE"], np.sqrt(np.diag(expected["cov"])), rtol=2e-9)
    weights = tables["Linear weights"]
    assert weights["Source row"].tolist() == expected["rows"].tolist() == list(range(10))
    np.testing.assert_allclose(weights["Normalized weight"], expected["wn"], rtol=2e-9)
    np.testing.assert_allclose(weights["Weight"], expected["w"], rtol=2e-9)
    np.testing.assert_allclose(weights["Log weight"], np.log(expected["w"]), rtol=2e-9, atol=2e-10)
    diagnostics = tables["Linear diagnostics"]
    np.testing.assert_allclose(diagnostics["Leverage"], expected["h"], rtol=2e-9)
    np.testing.assert_allclose(diagnostics["Cook's distance"], expected["cook"], rtol=2e-9)
    assert tables["Model"].loc["Incomplete rows", "Value"] == 1
    np.testing.assert_allclose(tables["Linear model diagnostics"].loc["Weighted PRESS", "Value"],
                               float(expected["wn"] @ expected["press"] ** 2), rtol=2e-9)
    assert tables["Linear predictions"]["Prediction interval low"].notna().all()
    app.show("result", index)
    app.result_tabs.select(names.index("Linear weights"))
    root.update()
    shot(root, "window-mlrw-weights.png")
    app.result_tabs.select(names.index("Linear predictions"))
    root.update()
    shot(root, "window-mlrw-predictions.png")
    app.show("graph", index)
    root.update()
    shot(root, "window-mlrw-graph.png")
    assert app.runs[index].result.figure.axes[0].get_ylabel() == "Residual (raw units)"

    # 2. A weight of zero on an incomplete row never matters; an edited value is recalculated in place.
    app.show("data", TITLE)
    app.edit_cell(3, 4, "1")
    wait()
    after = reference(app.tables[TITLE].frame(mask_excluded=True), "SD")
    np.testing.assert_allclose(app.runs[index].result.tables["Coefficients"]["Estimate"], after["beta"], rtol=2e-9)
    assert not np.allclose(after["beta"], expected["beta"])
    app.show("data", TITLE)
    app.current_grid.select((1, 0))
    app.toggle_exclusion()
    wait()
    assert app.runs[index].result.tables["Linear weights"]["Source row"].tolist() == [0, 2, 3, 4, 5, 6, 7, 8, 9]
    app.toggle_exclusion()
    wait()
    assert app.runs[index].result.tables["Linear weights"]["Source row"].tolist() == list(range(10))

    # 3. Save and reopen with the graph opened first: the recipe is canonical and the tables are the same.
    saved = {name: frame.copy() for name, frame in app.runs[index].result.tables.items()}
    app.show("graph", index)
    app.path = directory / "mlr-weighting.alab"
    assert app.save()
    app.import_file(app.path)
    reopened = next(i for i, item in enumerate(app.runs) if item.method == "Multiple regression"
                    and item.options.get(mw.GAUSSIAN_WEIGHTING) == mw.INVERSE_VARIANCE)
    app.open_sheet(("graph", reopened))
    wait()
    again = app.runs[reopened]
    assert again.options[mw.SD_COLUMN] == "SD" and again.options[mw.FUTURE_PRECISION] is True
    assert again.options["Linear profiles"] == PROFILES and mw.EXPONENT not in again.options
    for name, frame in saved.items():
        pd.testing.assert_frame_equal(again.result.tables[name], frame, rtol=1e-9, atol=1e-12)
    index = reopened

    # 4. Use as data, CSV, SVG, PNG, PDF; the Inspector and Format Graph on the weighted residual graph.
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index("Linear weights"))
    app.use_result_as_data()
    sheet = app.tables["Linear weights"].raw
    assert list(sheet.columns) == ["Source row", "Observed", "Weight", "Normalized weight", "Log weight",
                                   "Relative log weight"], sheet.columns
    csv_path = out / "linear-weights.csv"
    app.show("result", index)
    app.result_tabs.select(list(app.runs[index].result.tables).index("Linear weights"))
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path, encoding="utf-8-sig")
    np.testing.assert_allclose(exported["Normalized weight"], after["wn"], rtol=2e-9)
    app.show("graph", index)
    for suffix in ("svg", "png", "pdf"):
        target = out / f"mlr-residuals.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (out / "mlr-residuals.svg").read_bytes()
    assert (out / "mlr-residuals.pdf").read_bytes().startswith(b"%PDF")
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the residual points"
    panel.select_group(panel.elements[0]["key"])
    widget = panel.fields["color"]["widget"]
    panel.vars["element:color"].set("#9b4174")
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[index].style), app.runs[index].style
    app.toggle_inspector()

    def format_graph(dialog):
        dialog.inputs["title"].set("Weighted residuals")

    tools.drive_dialog(tools.GraphFormatDialog, format_graph)
    app.format_graph()
    assert app.runs[index].result.figure.axes[0].get_title() == "Weighted residuals"

    # 5. A weight column and a zero response: the error names the field, the dialog corrects it and runs.
    app.show("data", ZERO)
    root.update()
    before = len(app.runs)

    def zero_response(dialog):
        prepare(dialog)
        dialog.controls[mw.GAUSSIAN_WEIGHTING][1].set(mw.ABS_Y)
        message = rejected(dialog, mw.GAUSSIAN_WEIGHTING, "window-mlrw-zero-error.png", contains="zero")
        assert "source row 3" in message, message
        dialog.controls[mw.GAUSSIAN_WEIGHTING][1].set(mw.ABS_Y_POWER)
        dialog.update()
        dialog.controls[mw.EXPONENT][1].set("0")
        shot(dialog, "window-mlrw-power-zero.png")
        assert dialog.validate() is True

    drive(zero_response, accept=True)
    app.choose_analysis()
    wait()
    assert len(app.runs) == before + 1 and not errors, errors
    flat = app.runs[-1].result.tables["Linear weights"]
    assert (flat["Normalized weight"] == 1).all() and (flat["Log weight"] == 0).all()
    app.show("data", TITLE)
    before = len(app.runs)

    def weight_column(dialog):
        prepare(dialog)
        dialog.controls[mw.GAUSSIAN_WEIGHTING][1].set(mw.FROM_COLUMN)
        dialog.update()
        assert placed(dialog, mw.WEIGHT_COLUMN) and not placed(dialog, mw.SD_COLUMN)
        dialog.controls[mw.WEIGHT_COLUMN][1].set("W")
        shot(dialog, "window-mlrw-weight-column.png")
        assert dialog.validate() is True

    drive(weight_column, accept=True)
    app.choose_analysis()
    wait()
    assert len(app.runs) == before + 1 and not errors, errors
    column = reference(FRAME, "W")
    np.testing.assert_allclose(app.runs[-1].result.tables["Coefficients"]["Estimate"], column["beta"], rtol=2e-9)
    assert "Linear diagnostics" not in app.runs[-1].result.tables
    assert app.runs[-1].result.tables["Linear weights"]["Weight"].tolist() == FRAME["W"].iloc[:10].tolist()

    # 6. A recipe saved before these keys existed and one with the choice off give the same sheets.
    legacy = {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": []}
    old = analyse("Multiple regression", app.tables[LEGACY].frame(mask_excluded=True), legacy)
    off = analyse("Multiple regression", app.tables[LEGACY].frame(mask_excluded=True),
                  {**legacy, mw.GAUSSIAN_WEIGHTING: mw.UNWEIGHTED, mw.SD_COLUMN: "garbage"})
    assert list(old.tables) == list(off.tables) == ["Coefficients", "Model", "Fitted values"]
    for name in old.tables:
        pd.testing.assert_frame_equal(old.tables[name], off.tables[name])

    # 7. Italian and English: the labels change, the recipe keeps the canonical names and values.
    app.show("result", index)
    recipe = dict(app.runs[index].options)

    def english(dialog):
        assert dialog.controls[mw.GAUSSIAN_WEIGHTING][1].get() == mw.INVERSE_VARIANCE
        assert dialog.choice_bindings[mw.GAUSSIAN_WEIGHTING].display.get() == "Inverse variance (SD column)"
        assert dialog.field_rows[mw.SD_COLUMN][0].cget("text") == "Gaussian SD column"

    def italian(dialog):
        weighting_tab = dialog.field_rows[mw.GAUSSIAN_WEIGHTING][0].master
        assert dialog.choice_bindings[mw.GAUSSIAN_WEIGHTING].display.get() == LABELS["it"]["mode"]
        assert dialog.field_rows[mw.SD_COLUMN][0].cget("text") == "Colonna SD gaussiana"
        assert dialog.field_rows[mw.FUTURE_PRECISION][0].cget("text") == "Intervalli di predizione pesati"
        dialog.fields.select(weighting_tab)
        dialog.update()
        shot(dialog, "window-mlrw-dialog-it.png")
        dialog.controls[mw.SD_COLUMN][1].set("")
        message = rejected(dialog, mw.SD_COLUMN, "window-mlrw-sd-error-it.png", contains="Colonna SD gaussiana")
        assert "Scegli una colonna" in message, message
        dialog.controls[mw.SD_COLUMN][1].set("SD")
        editor = dialog.controls["Linear profiles"][1]
        assert editor.weight_label.cget("text") == "Peso"
        dialog.fields.select(dialog.field_rows["Linear profiles"][1].master)
        shot(dialog, "window-mlrw-profiles-it.png")
        assert dialog.validate() is True
        assert dialog.result[1][mw.GAUSSIAN_WEIGHTING] == mw.INVERSE_VARIANCE
        assert dialog.result[1] == recipe, dialog.result[1]

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
    assert app.runs[index].options == recipe
    assert not errors, errors
    root.geometry(previous_geometry)
    root.update()
