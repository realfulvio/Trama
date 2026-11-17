"""Desktop smoke for Global fit custom equation.

Drives the real Analyze dialog and the real window. Expected numbers come from a joint
design matrix written here, or from the curve that generated the fixture, not from the
packet oracles.

Linux/Xvfb only. Windows: NON PROVATO.

The solver reports a normalised residual within ``max((64 eps) ** 2, tolerance ** 2) * N``
as exact zero so a perfect curve is not left with a solver leftover. That rule is relative,
so a response of size 1e-12 with a real residual is kept. Covariance comes from the SVD of
the column-scaled Jacobian. A coefficient on a bound suppresses the whole covariance.
"""
import os
import time
import traceback
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pypdfium2 as pdfium
from matplotlib.collections import PolyCollection
from pypdfium2 import raw

from . import i18n
from .data import Dataset
from .field_error import FieldError
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parents[1] / "tests" / "data" / "global_custom"
SHARED, LOCAL, BOUNDS = "Shared", "Original", "Fixed"
INCOMPLETE, DECAY, RATIONAL, LEGACY = "Incomplete", "Decay", "Rational", "Legacy curves"


def load_indexed(name):
    frame = pd.read_csv(DATA / name).set_index("source_row")
    return frame


def design_wls(frame):
    """One intercept column per series, in first-seen order, and one shared slope."""
    rows = frame.loc[frame["Group"].notna() & frame["X"].notna() & frame["Y"].notna()]
    labels = list(dict.fromkeys(str(value) for value in rows["Group"]))
    groups = np.array([str(value) for value in rows["Group"]])
    x = rows["X"].to_numpy(dtype=float)
    y = rows["Y"].to_numpy(dtype=float)
    design = np.zeros((len(rows), len(labels) + 1))
    for index, label in enumerate(labels):
        design[groups == label, index] = 1.0
    design[:, -1] = x
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    return labels, beta


def slope_with_fixed_intercepts(frame, intercepts):
    rows = frame.loc[frame["Group"].notna() & frame["X"].notna() & frame["Y"].notna()]
    groups = np.array([str(value) for value in rows["Group"]])
    x = rows["X"].to_numpy(dtype=float)
    y = rows["Y"].to_numpy(dtype=float)
    target = y - np.array([intercepts[group] for group in groups])
    return float(np.linalg.lstsq(x[:, None], target, rcond=None)[0][0])


def pdf_counts(path):
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        try:
            images = len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])))
            paths = len(list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH])))
        finally:
            page.close()
    return images, paths


def check_global_custom(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "global-custom"
    out.mkdir(exist_ok=True)
    previous_geometry = root.geometry()
    root.geometry("1024x768+0+0")
    root.update()
    shared = load_indexed("shared-linear.csv")
    shared["Note"] = "text"
    original = load_indexed("shared-linear.csv")
    app.tables[SHARED] = Dataset(shared)
    app.tables[LOCAL] = Dataset(original)
    app.tables[BOUNDS] = Dataset(original.copy())
    app.tables[INCOMPLETE] = Dataset(load_indexed("incomplete-series.csv"))
    app.tables[DECAY] = Dataset(load_indexed("decay.csv"))
    app.tables[RATIONAL] = Dataset(load_indexed("rational.csv"))
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
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                errors.append(f"{error!r}\n{traceback.format_exc()}")
                try:
                    dialog.cancel()
                except Exception:
                    pass

        root.after(100, enter)

    def when_open(action, *, accept):
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
                errors.append(f"{error!r}\n{traceback.format_exc()}")
                try:
                    dialog.cancel()
                except Exception:
                    pass
            state["done"] = True

        root.after(25, enter)
        return state

    def settle(state):
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(0.02)
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

    def buttons(dialog):
        found = []

        def walk(widget):
            if widget.winfo_class() == "TButton":
                found.append(widget)
            for child in widget.winfo_children():
                walk(child)

        walk(dialog)
        return found

    def on_screen(dialog):
        # The window manager centers a toplevel on the Xvfb screen. Pin it to the origin so the
        # 1024×768 check is the dialog's own box, the same limit the dialog test uses.
        dialog.geometry("+0+0")
        dialog.update()
        width, height = dialog.winfo_width(), dialog.winfo_height()
        origin = dialog.winfo_rootx(), dialog.winfo_rooty()
        assert width <= 1024 and height <= 768, (width, height)
        assert origin[0] >= 0 and origin[1] >= 0, origin
        assert origin[0] + width <= 1024, (origin, width, height)
        assert origin[1] + height <= 768, (origin, width, height)
        labels = {widget.cget("text"): widget for widget in buttons(dialog)}
        for name in ("Run Analysis", "Cancel"):
            widget = labels[i18n.ui(name)]
            assert widget.winfo_viewable(), name
            assert widget.winfo_rooty() + widget.winfo_height() <= 768, (
                name, widget.winfo_rooty(), widget.winfo_height())

    def set_equation(dialog, text):
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", text)

    def set_coefficient(table, name, scope, start):
        index = next(position for position, row in enumerate(table.rows) if row["name"] == name)
        table.tree.selection_set(str(index))
        table.tree.see(str(index))
        table.load_selection()
        table.scope.set(scope)
        table.variables["start"].set(str(start))

    def prepare(dialog, equation=None):
        tools.pick_method(dialog, GLOBAL_CUSTOM_EQUATION)
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Group"][1].set("Group")
        if equation:
            set_equation(dialog, equation)
        dialog.global_series.refresh_labels()

    def fit_new(title, action):
        app.show("data", title)
        root.update()
        before = len(app.runs)
        drive(action, accept=True)
        popup, item = menu_entry("Analyze", "Analyze data…")
        popup.invoke(item)
        wait()
        assert len(app.runs) == before + 1 and not errors, errors
        return before

    def table_of(run, name):
        return run.result.tables[name]

    def estimate(run, scope, group, name):
        frame = table_of(run, "Parameters")
        rows = frame[(frame["Scope"] == scope) & (frame["Parameter"] == name)]
        rows = rows[rows["Group"].isna()] if group is None else rows[rows["Group"] == group]
        return float(rows["Estimate"].iloc[0])

    def assert_joint(run, frame):
        labels, beta = design_wls(frame)
        np.testing.assert_allclose(estimate(run, "Shared", None, "B"), beta[-1], rtol=1e-6)
        for label, value in zip(labels, beta[:-1]):
            np.testing.assert_allclose(estimate(run, "Local", label, "A"), value, rtol=1e-6)
        return beta

    # 1. Real menu, wrong confidence, text SD, sharing, and the 1024×768 window.
    def first(dialog):
        prepare(dialog)
        assert [dialog.fields.tab(i, "text") for i in range(5)] == [
            "Variables", "Equation", "Parameters", "Series constraints", "Output"]
        assert dialog.controls["Equation"][1].values() == "A + B*X"
        rows = dialog.controls["Parameters"][1].values()
        assert [(row["name"], row["shared"], row["fixed"]) for row in rows] == [
            ("A", False, False), ("B", True, False)]
        assert dialog.global_series.labels == ["A", "B"]
        dialog.controls["Confidence level (%)"][1].set("0")
        rejected(dialog, "Confidence level (%)", contains="between 0 and 100")
        dialog.controls["Confidence level (%)"][1].set("95")
        dialog.controls["Weighting"][1].set("Inverse variance (column)")
        dialog.update()
        assert placed(dialog, "SD column")
        dialog.controls["SD column"][1].set("Note")
        rejected(dialog, "SD column", contains="Note")
        dialog.controls["Weighting"][1].set("Unweighted")
        dialog.update()
        assert not placed(dialog, "SD column")
        dialog.fields.select(2)
        dialog.update()
        on_screen(dialog)
        shot(dialog, "window-global-custom-dialog.png")

    index = fit_new(SHARED, first)
    run = app.runs[index]
    assert run.method == GLOBAL_CUSTOM_EQUATION
    assert run.options["SD column"] is None and run.options["Weighting"] == "Unweighted"
    assert run.options["Parameters"][1]["shared"] is True and run.options["Parameters"][0]["fixed"] is False
    beta = assert_joint(run, app.tables[SHARED].frame(mask_excluded=True))
    summary = table_of(run, "Global fit")
    assert int(summary.loc["Observations", "Value"]) == 12
    assert int(summary.loc["Free parameters", "Value"]) == 3
    axes = run.result.figure.axes[0]
    assert [text.get_text() for text in axes.get_legend().get_texts()] == ["A", "B"]
    assert not any(isinstance(item, PolyCollection) for item in axes.collections)
    app.show("graph", index)
    root.update()
    shot(root, "window-global-custom-graph.png")
    app.show("result", index)
    app.result_tabs.select(0)
    root.update()
    shot(root, "window-global-custom-parameters.png")

    # 8. Edit one Y. The shared slope must follow a fresh design matrix.
    app.show("data", SHARED)
    root.update()
    columns = list(app.tables[SHARED].raw.columns)
    app.edit_cell(0, columns.index("Y"), "0.2")
    wait()
    edited = assert_joint(app.runs[index], app.tables[SHARED].frame(mask_excluded=True))
    assert abs(edited[-1] - beta[-1]) > 1e-3

    # 9. Exclude one complete Y. Source row keeps the original index labels.
    before_rows = [int(value) for value in table_of(app.runs[index], "Residuals")["Source row"]]
    excluded = int(app.tables[SHARED].raw.index[2])
    app.show("data", SHARED)
    root.update()
    app.current_grid.select((2, columns.index("Y")))
    app.toggle_exclusion()
    wait()
    after_rows = [int(value) for value in table_of(app.runs[index], "Residuals")["Source row"]]
    assert excluded in before_rows and excluded not in after_rows
    assert after_rows == [value for value in before_rows if value != excluded]
    assert int(table_of(app.runs[index], "Global fit").loc["Observations", "Value"]) == 11
    assert_joint(app.runs[index], app.tables[SHARED].frame(mask_excluded=True))

    # 3. Local fixed intercepts on a fresh copy of the same XY.
    def local_fixed(dialog):
        prepare(dialog)
        editor = dialog.controls["Series constraints"][1]
        editor.select_series("A")
        editor.select_coefficient("A")
        editor.variables["fixed"].set("1")
        editor.select_series("B")
        editor.select_coefficient("A")
        editor.variables["fixed"].set("5")
        dialog.fields.select(dialog.field_rows["Series constraints"][1].master)
        dialog.update()
        on_screen(dialog)
        shot(dialog, "window-global-custom-local-fixed.png")

    local_index = fit_new(LOCAL, local_fixed)
    local_run = app.runs[local_index]
    frame = app.tables[LOCAL].frame(mask_excluded=True)
    expected_b = slope_with_fixed_intercepts(frame, {"A": 1.0, "B": 5.0})
    np.testing.assert_allclose(estimate(local_run, "Shared", None, "B"), expected_b, rtol=1e-6)
    np.testing.assert_allclose(estimate(local_run, "Fixed", "A", "A"), 1.0)
    np.testing.assert_allclose(estimate(local_run, "Fixed", "B", "A"), 5.0)

    # 4. Empty shared intersection, then an active upper bound at 1.5.
    def active_bound(dialog):
        prepare(dialog)
        editor = dialog.controls["Series constraints"][1]
        editor.select_series("A")
        editor.select_coefficient("B")
        editor.variables["lower"].set("3")
        editor.select_series("B")
        editor.select_coefficient("B")
        editor.variables["upper"].set("2")
        rejected(dialog, "Series constraints", "window-global-custom-bounds.png", contains="do not overlap")
        editor.clear_all()
        editor.select_series("A")
        editor.select_coefficient("B")
        editor.variables["upper"].set("1.7")
        editor.select_series("B")
        editor.select_coefficient("B")
        editor.variables["upper"].set("1.5")

    bound_index = fit_new(BOUNDS, active_bound)
    bound = app.runs[bound_index]
    parameters = table_of(bound, "Parameters")
    shared_b = parameters[(parameters["Scope"] == "Shared") & (parameters["Parameter"] == "B")].iloc[0]
    assert shared_b["Estimate"] == 1.5
    assert shared_b["Status"] == "At bound"
    locals_ = parameters[parameters["Scope"] == "Local"]
    assert list(locals_["Status"]) == ["Estimated", "Estimated"]
    assert locals_["SE"].isna().all() and locals_["CI low"].isna().all()
    assert table_of(bound, "Covariance").isna().to_numpy().all()

    # 5. Preview and Cancel must not replace the confirmed result.
    confirmed = app.runs[bound_index]
    confirmed_options = dict(confirmed.options)
    confirmed_tables = {name: frame.copy() for name, frame in confirmed.result.tables.items()}
    confirmed_figure = confirmed.result.figure

    def preview(dialog):
        dialog.controls["Curve points"][1].set("40")
        assert dialog.result is None

    app.show("result", bound_index)
    drive(preview, accept=False)
    app.edit_analysis()
    root.update()
    assert app.runs[bound_index] is confirmed
    assert confirmed.options == confirmed_options and confirmed.result.figure is confirmed_figure
    for name, frame in confirmed_tables.items():
        pd.testing.assert_frame_equal(confirmed.result.tables[name], frame)

    # 13. Residuals and Curve can be used as data.
    app.show("result", index)
    names = list(app.runs[index].result.tables)
    before_tables = set(app.tables)
    for sheet in ("Residuals", "Curve"):
        app.show("result", index)
        app.result_tabs.select(names.index(sheet))
        app.use_result_as_data()
    created = set(app.tables) - before_tables
    assert len(created) == 2, created
    frames = {name: app.tables[name].raw for name in created}
    assert any(list(frame.columns)[:2] == ["Source row", "Group"] for frame in frames.values())
    assert any(list(frame.columns) == ["Group", "X", "Predicted"] for frame in frames.values())

    # 14. CSV, SVG, PNG, and a two-panel layout PDF with paths and no images.
    csv_path = out / "parameters.csv"
    app.show("result", index)
    app.result_tabs.select(0)
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path, encoding="utf-8-sig")
    assert {"Scope", "Parameter", "Estimate", "SE", "Status"} <= set(exported.columns)
    app.show("graph", index)
    for suffix in ("svg", "png"):
        target = out / f"shared.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (out / "shared.svg").read_bytes()
    app.layouts.append(Layout("Global fit panels", 2, [app.runs[index].reference, local_run.reference]))
    app.show("layout", len(app.layouts) - 1)
    root.update()
    pdf_path = out / "panels.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(pdf_path)):
        app.export()
    images, paths = pdf_counts(pdf_path)
    assert images == 0 and paths > 0, (images, paths)

    # 10 and 11. One-pair series, all-fixed, decay and rational, on their own tables.
    def incomplete(dialog):
        prepare(dialog)
        dialog.controls["Curve points"][1].set("25")

    incomplete_index = fit_new(INCOMPLETE, incomplete)
    incomplete_run = app.runs[incomplete_index]
    assert int(table_of(incomplete_run, "Global fit").loc["Observations", "Value"]) == 7
    curve = table_of(incomplete_run, "Curve")
    series_b = curve[curve["Group"] == "B"]
    assert len(series_b) == 25 and series_b["X"].nunique() == 1

    def all_fixed(dialog):
        prepare(dialog)
        table = dialog.controls["Parameters"][1]
        set_coefficient(table, "A", "Fixed", 1)
        set_coefficient(table, "B", "Fixed", 2)

    fixed_index = fit_new(BOUNDS, all_fixed)
    fixed_run = app.runs[fixed_index]
    assert int(table_of(fixed_run, "Global fit").loc["Free parameters", "Value"]) == 0
    assert float(table_of(fixed_run, "Global fit").loc["Residual SS", "Value"]) > 1
    assert table_of(fixed_run, "Covariance").shape == (0, 0)
    assert table_of(fixed_run, "Parameters")["SE"].isna().all()
    assert list(table_of(fixed_run, "Parameters")["Status"]) == ["Fixed", "Fixed"]

    def decay(dialog):
        prepare(dialog, "C+A*exp(-K*X)")
        table = dialog.controls["Parameters"][1]
        table.tree.selection_set("1")
        table.load_selection()
        table.remove()
        table.from_equation()
        set_coefficient(table, "A", "Local", 10)
        set_coefficient(table, "K", "Shared", 0.4)
        set_coefficient(table, "C", "Fixed", 1)
        dialog.controls["Curve points"][1].set("31")

    decay_index = fit_new(DECAY, decay)
    decay_run = app.runs[decay_index]
    np.testing.assert_allclose(estimate(decay_run, "Shared", None, "K"), 0.4, rtol=1e-5)
    np.testing.assert_allclose(estimate(decay_run, "Local", "A", "A"), 10, rtol=1e-5)
    np.testing.assert_allclose(estimate(decay_run, "Local", "B", "A"), 20, rtol=1e-5)
    np.testing.assert_allclose(estimate(decay_run, "Fixed", None, "C"), 1)
    decay_curve = table_of(decay_run, "Curve")
    decay_x = app.tables[DECAY].frame()
    for label, amplitude in (("A", 10), ("B", 20)):
        part = decay_curve[decay_curve["Group"] == label]
        assert len(part) == 31
        used = decay_x.loc[decay_x["Group"] == label, "X"]
        assert part["X"].iloc[0] == float(used.min()) and part["X"].iloc[-1] == float(used.max())
        expected = 1 + amplitude * np.exp(-0.4 * part["X"].to_numpy())
        np.testing.assert_allclose(part["Predicted"], expected, rtol=1e-5, atol=1e-6)

    def rational(dialog):
        prepare(dialog, "C+V*X/(K+X)")
        table = dialog.controls["Parameters"][1]
        table.rows.clear()
        table.from_equation()
        set_coefficient(table, "C", "Fixed", 0.5)
        set_coefficient(table, "K", "Shared", 4)
        set_coefficient(table, "V", "Local", 5)
        dialog.controls["Curve points"][1].set("31")

    rational_index = fit_new(RATIONAL, rational)
    rational_run = app.runs[rational_index]
    np.testing.assert_allclose(estimate(rational_run, "Shared", None, "K"), 4, rtol=1e-5)
    np.testing.assert_allclose(estimate(rational_run, "Local", "A", "V"), 5, rtol=1e-5)
    np.testing.assert_allclose(estimate(rational_run, "Local", "B", "V"), 9, rtol=1e-5)
    np.testing.assert_allclose(estimate(rational_run, "Fixed", None, "C"), 0.5)
    rational_curve = table_of(rational_run, "Curve")
    rational_x = app.tables[RATIONAL].frame()
    for label, velocity in (("A", 5), ("B", 9)):
        part = rational_curve[rational_curve["Group"] == label]
        assert len(part) == 31
        used = rational_x.loc[rational_x["Group"] == label, "X"]
        assert part["X"].iloc[0] == float(used.min()) and part["X"].iloc[-1] == float(used.max())
        expected = 0.5 + velocity * part["X"].to_numpy() / (4 + part["X"].to_numpy())
        np.testing.assert_allclose(part["Predicted"], expected, rtol=1e-5, atol=1e-6)

    # 7. Save, reopen on the graph, Italian labels, canonical recipe.
    snapshots = {}
    for position, item in enumerate(app.runs):
        if item.method == GLOBAL_CUSTOM_EQUATION and item.result is not None:
            snapshots[(item.title, item.slot)] = dict(item.options)
    app.path = directory / "global-custom.alab"
    assert app.save()
    app.import_file(app.path)
    for position, item in enumerate(app.runs):
        if item.method == GLOBAL_CUSTOM_EQUATION:
            app.open_sheet(("graph", position))
            wait()
    for item in app.runs:
        if item.method != GLOBAL_CUSTOM_EQUATION or item.result is None:
            continue
        reloaded = app.tables[item.title].frame(mask_excluded=True)
        expected = analyse(item.method, reloaded, item.options)
        for name, frame in expected.tables.items():
            pd.testing.assert_frame_equal(item.result.tables[name], frame, rtol=1e-8, atol=1e-8)
        assert item.options == snapshots[(item.title, item.slot)]
        assert item.options["Weighting"] == "Unweighted"
        assert all(isinstance(row["shared"], bool) and isinstance(row["fixed"], bool)
                   for row in item.options["Parameters"])
    saved_options = dict(next(item.options for item in app.runs if item.title == SHARED))
    shared_index = next(position for position, item in enumerate(app.runs) if item.title == SHARED)

    def italian(dialog):
        assert [dialog.fields.tab(i, "text") for i in range(5)] == [
            "Variabili", "Equazione", "Coefficienti", "Vincoli di serie", "Risultati"]
        assert dialog.controls["Weighting"][1].get() == "Unweighted"
        assert dialog.choice_bindings["Weighting"].combobox.get() == "Senza pesi"
        table = dialog.controls["Parameters"][1]
        table.tree.selection_set("1")
        table.load_selection()
        assert table.scope.get() == "Shared"
        assert table.scope_binding.combobox.get() == "Condiviso"
        assert dialog.controls["Equation"][1].values() == saved_options["Equation"]
        assert dialog.result is None

    i18n.set_language("it")
    try:
        app.show("result", shared_index)
        drive(italian, accept=False)
        app.edit_analysis()
        root.update()
    finally:
        i18n.set_language("en")
    assert app.runs[shared_index].options == saved_options

    # 12. An injected worker failure reopens the typed candidate and Cancel keeps the result.
    kept = app.runs[shared_index]
    kept_options = dict(kept.options)
    kept_tables = {name: frame.copy() for name, frame in kept.result.tables.items()}
    kept_figure = kept.result.figure

    def candidate(dialog):
        dialog.controls["Confidence level (%)"][1].set("90")

    def recovered(dialog):
        assert dialog.error_label is not None and "Injected" in dialog.error_label.cget("text"), dialog.error
        assert dialog.fields.select() == str(dialog.field_rows["Parameters"][1].master)
        assert float(dialog.controls["Confidence level (%)"][1].get()) == 90
        assert dialog.result is None

    app.show("result", shared_index)
    drive(candidate, accept=True)
    with patch("analisi.global_custom_fit._solve", side_effect=FieldError("Parameters", "Injected worker failure")):
        app.edit_analysis()
        state = when_open(recovered, accept=False)
        settle(state)
    assert app.runs[shared_index] is kept and kept.options == kept_options
    assert kept.result.figure is kept_figure
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(kept.result.tables[name], frame)
    assert "discarded" in app.status.get(), app.status.get()

    # 15. The legacy project still runs both older methods, and the tree lists all three.
    app.import_file(DATA / "legacy-global-and-custom.alab")
    for position, item in enumerate(list(app.runs)):
        app.open_sheet(("result", position))
        wait()
        fresh = analyse(item.method, app.tables[item.title].frame(mask_excluded=True), item.options)
        for name, frame in fresh.tables.items():
            pd.testing.assert_frame_equal(app.runs[position].result.tables[name], frame, rtol=1e-8, atol=1e-8)
    assert {item.method for item in app.runs} == {"Fit custom equation", "Global nonlinear regression"}

    def tree(dialog):
        texts = []

        def walk(item=""):
            for child in dialog.methods.get_children(item):
                texts.append(dialog.methods.item(child, "text"))
                walk(child)

        walk()
        for name in ("Fit custom equation", "Global nonlinear regression", GLOBAL_CUSTOM_EQUATION):
            assert name in texts, texts
        assert dialog.result is None

    app.show("data", LEGACY)
    root.update()
    drive(tree, accept=False)
    popup, item = menu_entry("Analyze", "Analyze data…")
    popup.invoke(item)
    root.update()
    root.geometry(previous_geometry)
    root.update()
    assert not errors, errors
    assert i18n.active_language() == "en"
    assert app.pending is None
