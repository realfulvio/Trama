"""Desktop smoke check for conditional (piecewise) equations, 0.81, on the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_piecewise_equations` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=piecewise-equations python tramastat.py --smoke DIR``; the window takes the
size of the screen (run it on a 1024×768 and on a 1600×1000 screen), and the theme is the one saved in the
isolated preferences (Standard or Modern). Every run goes through English and Italian.

Synthetic data only. Expected values come from the linear design of the hinge with a known threshold,
solved here with NumPy, independent of the optimizer and of the equation engine under test.
"""
import json
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from .custom_fit import CUSTOM_EQUATION
from .data import Dataset, save_project
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION
from .global_uncertainty import GID
from .pdf_bundle_smoke import read_pdf
from .presentation import Layout
from .workbench import analyse

SINGLE, GROUPS, LEGACY = "Hinge", "Hinge series", "Arithmetic recipe"
HINGE = "if(X<T, A+B*X, A+C*X)"
X = np.arange(-4., 5.)
Y = np.array([-2.1, -1.0, -0.1, 1.1, 2.0, 1.7, 1.2, 0.9, 0.4])
Y2 = np.array([-5.0, -3.4, -1.9, 0.2, 1.9, 2.9, 4.0, 5.1, 6.1])
SINGLE_FRAME = pd.DataFrame({"X": X, "Y": Y})
GROUP_FRAME = pd.concat([
    pd.concat([pd.DataFrame({"X": X, "Y": Y, "Group": "G1"}), pd.DataFrame({"X": X, "Y": Y2, "Group": "G2"})],
              ignore_index=True),
    pd.DataFrame({"QX": [-.5, .5], "QG": ["G1", "G2"]})], axis=1)
LEGACY_RECIPE = (CUSTOM_EQUATION, {
    "X": "X", "Y": "Y", "Group": None, "Equation": "A + B*X",
    "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                   {"name": "B", "start": .5, "lower": None, "upper": None, "fixed": False}],
    "Weighting": "Unweighted", "Confidence level (%)": 95.0, "Curve points": 50})
STEP = 60  # seconds allowed to any automatic wait of this check


def hinge_design(x, threshold):
    below = x < threshold
    return np.column_stack([np.ones(len(x)), np.where(below, x, 0.), np.where(below, 0., x)])


def hinge_ols(x, y, threshold=0.):
    """(A, B, C) and their standard errors for Y = A + B*X below the threshold and A + C*X above it."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    design = hinge_design(x, threshold)
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ beta
    covariance = np.linalg.inv(design.T @ design) * float(resid @ resid) / (len(x) - 3)
    return beta, np.sqrt(np.diag(covariance))


def joint_ols(frame, threshold=0.):
    """Shared A, local B and C per series, in first-seen order: (A, {series: (B, C)})."""
    labels = list(dict.fromkeys(frame["Group"]))
    x, y = frame["X"].to_numpy(float), frame["Y"].to_numpy(float)
    columns = [np.ones(len(x))]
    for label in labels:
        mine = (frame["Group"] == label).to_numpy()
        columns += [np.where(mine & (x < threshold), x, 0.), np.where(mine & (x >= threshold), x, 0.)]
    beta = np.linalg.lstsq(np.column_stack(columns), y, rcond=None)[0]
    return beta[0], {label: (beta[1 + 2 * i], beta[2 + 2 * i]) for i, label in enumerate(labels)}


def check_piecewise_equations(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, capture, pick_method, wait_for_calculation, messagebox, filedialog
    and the shared ``errors`` list."""
    errors = tools.errors
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    theme = "modern" if ui_theme.is_modern() else "standard"
    suffix = f"-{theme}-{width}x{height}"
    out = directory / "piecewise-equations"
    out.mkdir(exist_ok=True)
    notes = []
    root.deiconify()
    root.geometry(f"{width}x{height}+0+0")
    root.update()

    def note(text):
        notes.append(text)
        (out / "checks.json").write_text(json.dumps({"theme": theme, "screen": [width, height], "checks": notes},
                                                    indent=2, ensure_ascii=False), encoding="utf-8")

    def wait(phase):
        """tools.wait_for_calculation with a deadline that names the phase."""
        deadline = time.monotonic() + STEP
        while app.pending is not None:
            assert time.monotonic() < deadline, f"timeout waiting for the calculation: {phase}"
            root.update()
            time.sleep(.02)
        tools.wait_for_calculation()
        assert not errors, (phase, errors)

    def shot(window, name):
        name = name.replace(".png", suffix + ".png")
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
        state = {"done": False}

        def enter(tries=0):
            dialog = find_dialog()
            if dialog is None or not dialog.winfo_viewable():
                if tries < 250:
                    root.after(40, lambda: enter(tries + 1))
                    return
                errors.append("AnalysisDialog did not open")
                state["done"] = True
                return
            try:
                dialog.update_idletasks()
                action(dialog)
                dialog.ok() if accept else dialog.cancel()
            except Exception as error:  # the smoke reports, then closes the dialog it opened
                errors.append(f"{type(error).__name__}: {error}")
                dialog.cancel()
            state["done"] = True

        root.after(100, enter)
        return state

    def settle(state, phase):
        deadline = time.monotonic() + STEP
        while not state["done"]:
            assert time.monotonic() < deadline, f"timeout: the dialog of {phase} did not close"
            root.update()
            time.sleep(.02)
        assert find_dialog() is None, f"a dialog stayed open after {phase}"

    def menu_entry(menu_label, entry_label):
        bar = root.nametowidget(root.cget("menu"))
        for position in range(bar.index("end") + 1):
            if bar.type(position) == "cascade" and bar.entrycget(position, "label") == i18n.ui(menu_label):
                popup = root.nametowidget(bar.entrycget(position, "menu"))
                for item in range(popup.index("end") + 1):
                    if popup.type(item) == "command" and popup.entrycget(item, "label") == i18n.ui(entry_label):
                        return popup, item
        raise AssertionError(f"menu entry {menu_label} / {entry_label} not found")

    def within(widget, ancestor):
        while widget is not None:
            if str(widget) == str(ancestor):
                return True
            widget = widget.master
        return False

    def rejected(dialog, field, contains):
        """validate() refuses, the dialog stays open on the page of the field, the field has the focus."""
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert contains in message, message
        page = dialog.field_rows[field][1]
        while page.master is not dialog.fields:
            page = page.master
        assert dialog.fields.select() == str(page), field
        dialog.update()
        focus = dialog.focus_get()
        assert focus is not None and within(focus, dialog.field_rows[field][1]), (field, focus)
        return message

    def buttons(widget, found=None):
        found = [] if found is None else found
        if widget.winfo_class() == "TButton":
            found.append(widget)
        for child in widget.winfo_children():
            buttons(child, found)
        return found

    def on_screen(dialog, phase):
        """The dialog fits the screen; Run Analysis, Cancel and the field message stay reachable."""
        dialog.geometry("+0+0")
        dialog.update()
        box = dialog.winfo_width(), dialog.winfo_height()
        assert box[0] <= width and box[1] <= height, (phase, box)
        labels = {widget.cget("text"): widget for widget in buttons(dialog)}
        for name in ("Run Analysis", "Cancel"):
            widget = labels[i18n.ui(name)]
            assert widget.winfo_viewable(), (phase, name)
            assert widget.winfo_rooty() + widget.winfo_height() <= height, (phase, name)
        message = dialog.controls["Equation"][1].message
        if message.cget("text"):
            assert message.winfo_viewable() and message.winfo_rooty() + message.winfo_height() <= height, phase

    def syntax_box(dialog):
        return dialog.field_rows["Equation syntax"][1]

    def choose_by_keyboard(dialog, key, expected):
        """Open the Equation syntax list from the keyboard, move with an arrow key and confirm with Return."""
        box = syntax_box(dialog)
        box.focus_force()
        dialog.update()
        assert dialog.focus_get() is box, dialog.focus_get()
        box.event_generate("<Down>")
        dialog.update()
        popdown = box.tk.eval(f"ttk::combobox::PopdownWindow {box}")
        assert box.tk.eval(f"winfo ismapped {popdown}") == "1", "the syntax list did not open"
        listbox = popdown + ".f.l"
        box.tk.eval(f"event generate {listbox} <{key}>")
        box.tk.eval(f"event generate {listbox} <Return>")
        dialog.update()
        assert box.tk.eval(f"winfo ismapped {popdown}") == "0", "the syntax list stayed open"
        assert dialog.controls["Equation syntax"][1].get() == expected, dialog.controls["Equation syntax"][1].get()
        assert dialog.focus_get() is box

    def set_equation(dialog, text):
        box = dialog.controls["Equation"][1].box
        box.delete("1.0", "end")
        box.insert("1.0", text)

    def select_row(table, name):
        index = next(position for position, row in enumerate(table.rows) if row["name"] == name)
        table.tree.selection_set(str(index))
        table.tree.see(str(index))
        table.load_selection()
        return table

    def guide_shown(dialog):
        dialog.update()
        return bool(dialog.controls["Equation"][1].conditional.winfo_ismapped())

    def fit_new(title, action, phase):
        app.show("data", title)
        root.update()
        before = len(app.runs)
        state = drive(action, accept=True)
        popup, item = menu_entry("Analyze", "Analyze data…")
        popup.invoke(item)
        settle(state, phase)
        wait(phase)
        assert len(app.runs) == before + 1, phase
        return before

    def edit(action, index, *, accept, phase):
        app.show("result", index)
        state = drive(action, accept=accept)
        app.edit_analysis()
        settle(state, phase)
        wait(phase)

    def tables(index):
        return app.runs[index].result.tables

    def check_single(index, x, y, threshold=0.):
        beta, se = hinge_ols(x, y, threshold)
        parameters = tables(index)["Parameters: All"]
        np.testing.assert_allclose(parameters.loc[["A", "B", "C"], "Estimate"], beta, rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(parameters.loc[["A", "B", "C"], "SE"], se, rtol=1e-5)
        assert parameters.loc["T", "Status"] == "Fixed" and parameters.loc["T", "Estimate"] == threshold
        curve = tables(index)["Curve: All"]
        assert list(curve.columns) == ["X", "Predicted", "Branch"], list(curve.columns)
        expected = np.where(curve["X"] < threshold, beta[0] + beta[1] * curve["X"], beta[0] + beta[2] * curve["X"])
        np.testing.assert_allclose(curve["Predicted"], expected, rtol=1e-6, atol=1e-8)
        line = app.runs[index].result.figure.axes[0].lines[0]
        xs, ys = np.asarray(line.get_xdata(), float), np.asarray(line.get_ydata(), float)
        gaps = np.flatnonzero(np.isnan(ys))
        assert len(gaps) == 1 and xs[gaps[0] - 1] < threshold <= xs[gaps[0] + 1], (threshold, xs[gaps])
        return beta

    def start_dialog_en(dialog):
        tools.pick_method(dialog, CUSTOM_EQUATION)
        dialog.controls["X"][1].set("X")
        dialog.controls["Y"][1].set("Y")
        dialog.fields.select(1)
        dialog.update()
        editor = dialog.controls["Equation"][1]
        assert dialog.controls["Equation syntax"][1].get() == "Arithmetic" and not guide_shown(dialog)
        # The hinge in Arithmetic: the check names the missing syntax, the dialog stays open on Equation.
        set_equation(dialog, HINGE)
        editor.check()
        assert "Conditional equation syntax" in editor.message.cget("text"), editor.message.cget("text")
        on_screen(dialog, "Arithmetic error on Equation")
        rejected(dialog, "Equation", "Conditional equation syntax")
        shot(dialog, "window-piecewise-arithmetic-error.png")
        # Keyboard: Equation syntax → Conditional. The equation and the coefficient rows are not rewritten.
        rows_before = [row["name"] for row in dialog.controls["Parameters"][1].rows]
        choose_by_keyboard(dialog, "Down", "Conditional")
        assert editor.values() == HINGE and guide_shown(dialog)
        assert [row["name"] for row in dialog.controls["Parameters"][1].rows] == rows_before
        table = dialog.controls["Parameters"][1]
        table.from_equation()
        # Names in order of appearance after the rows already listed; if and X are not coefficients.
        assert [row["name"] for row in table.rows] == ["A", "B", "T", "C"], [row["name"] for row in table.rows]
        # A free threshold is refused before any fit, with Parameters focused.
        rejected(dialog, "Parameters", "must be Fixed")
        dialog.fields.select(2)
        shot(dialog, "window-piecewise-free-threshold.png")
        select_row(table, "T")
        table.variables["start"].set("0")
        table.fixed.set(True)
        table.store()
        dialog.fields.select(1)
        dialog.update()
        editor.check()
        assert "valid" in editor.message.cget("text"), editor.message.cget("text")
        on_screen(dialog, "Conditional guide on Equation")
        shot(dialog, "window-piecewise-equation.png")
        assert dialog.validate() is True

    # 0. Project with a hinge, two series with query rows, and a recipe saved before 0.81.
    first_path = directory / "piecewise-equations.alab"
    legacy = Dataset(SINGLE_FRAME.copy())
    legacy.analyses.append((LEGACY_RECIPE[0], dict(LEGACY_RECIPE[1])))
    save_project(first_path, {SINGLE: Dataset(SINGLE_FRAME.copy()), GROUPS: Dataset(GROUP_FRAME.copy()),
                              LEGACY: legacy})
    app.import_file(first_path)
    root.update()

    # 1. New Fit custom equation from the Analyze menu: syntax by keyboard, errors focused, known threshold.
    index = fit_new(SINGLE, start_dialog_en, "single conditional fit")
    run = app.runs[index]
    assert run.options["Equation syntax"] == "Conditional" and run.options["Equation"] == HINGE
    assert [(p["name"], p["fixed"]) for p in run.options["Parameters"]] == [
        ("A", False), ("B", False), ("T", True), ("C", False)]
    beta = check_single(index, X, Y)
    fit = tables(index)["Fit: All"]["Value"]
    assert fit["Equation syntax"] == "Conditional" and "T = 0" in fit["Conditions"], fit
    note(f"single fit: A,B,C = {np.round(beta, 6).tolist()} match the hinge design; T fixed; one break at X = 0")
    app.show("graph", index)
    root.update()
    shot(root, "window-piecewise-graph.png")

    # 2. Graph exports, Curve CSV with Branch, Use Result as Data.
    for kind in ("png", "svg", "pdf"):
        target = out / f"piecewise-graph{suffix}.{kind}"
        app.show("graph", index)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    svg = (out / f"piecewise-graph{suffix}.svg").read_text(encoding="utf-8")
    assert "<image" not in svg and svg.count("<path") > 5
    [(_, pdf_text, pdf_images)] = read_pdf(out / f"piecewise-graph{suffix}.pdf")
    assert pdf_images == 0 and "Y" in pdf_text, (pdf_images, pdf_text)
    app.show("result", index)
    app.result_tabs.select(list(tables(index)).index("Curve: All"))
    root.update()
    csv = out / f"piecewise-curve{suffix}.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = pd.read_csv(csv, encoding="utf-8-sig")
    assert list(exported.columns)[-1] == "Branch" and set(exported["Branch"]) == set(tables(index)["Curve: All"]["Branch"])
    before_tables = set(app.tables)
    app.use_result_as_data()
    created = set(app.tables) - before_tables
    assert len(created) == 1, created
    assert list(app.tables[created.pop()].raw.columns) == ["X", "Predicted", "Branch"]
    note("graph PNG/SVG/PDF (vector, no image); Curve CSV and Use Result as Data keep the Branch column")

    # 3. Edit one Y, exclude one row: estimates, curve and break recalculated.
    app.show("data", SINGLE)
    columns = list(app.tables[SINGLE].raw.columns)
    app.edit_cell(2, columns.index("Y"), "0.4")
    wait("edit one Y")
    changed = Y.copy()
    changed[2] = .4
    check_single(index, X, changed)
    app.show("data", SINGLE)
    app.current_grid.select((6, columns.index("Y")))
    app.toggle_exclusion()
    wait("exclude one row")
    keep = [i for i in range(len(X)) if i != 6]
    check_single(index, X[keep], changed[keep])
    assert tables(index)["Fit: All"]["Value"]["Skipped rows"] == 1
    assert tables(index)["Residuals: All"].index.tolist() == keep
    note("edit Y[2] and exclude row 6: estimates, curve and break follow the data")

    # 4. Cancel a new threshold: nothing changes. Apply it: the break moves to the new known threshold.
    confirmed = app.runs[index]
    kept = {name: frame.copy() for name, frame in confirmed.result.tables.items()}
    kept_options = dict(confirmed.options)

    def threshold(value):
        def action(dialog):
            table = dialog.controls["Parameters"][1]
            select_row(table, "T")
            table.variables["start"].set(value)
            table.store()
        return action

    edit(threshold("1"), index, accept=False, phase="cancel a new threshold")
    assert app.runs[index] is confirmed and confirmed.options == kept_options
    for name, frame in kept.items():
        pd.testing.assert_frame_equal(confirmed.result.tables[name], frame)
    edit(threshold("1"), index, accept=True, phase="apply a new threshold")
    check_single(index, X[keep], changed[keep], threshold=1.)
    note("Cancel keeps the confirmed result; Apply with T = 1 moves the break to X = 1")

    # 5. Global fit: a shared threshold that is free is refused; fixed, bands and predictions follow the branches.
    def global_dialog(dialog):
        tools.pick_method(dialog, GLOBAL_CUSTOM_EQUATION)
        for name, value in (("X", "X"), ("Y", "Y"), ("Group", "Group")):
            dialog.controls[name][1].set(value)
        dialog.global_series.refresh_labels()
        dialog.fields.select(1)
        dialog.update()
        choose_by_keyboard(dialog, "Down", "Conditional")
        set_equation(dialog, HINGE)
        table = dialog.controls["Parameters"][1]
        table.from_equation()
        for name, scope in (("A", "Shared"), ("B", "Local"), ("C", "Local"), ("T", "Shared")):
            select_row(table, name)
            table.scope.set(scope)
        select_row(table, "T")
        table.variables["start"].set("0")
        dialog.global_series.refresh_labels()
        for name, value in (("Curve band", "Confidence"), ("Predict responses", True), ("Query X", "QX"),
                            ("Query group", "QG"), ("Query interval", "Confidence")):
            dialog.controls[name][1].set(value)
        dialog.update_idletasks()
        rejected(dialog, "Parameters", "shared coefficient cannot be a threshold")
        select_row(table, "T")
        table.scope.set("Fixed")
        dialog.fields.select(1)
        dialog.update()
        on_screen(dialog, "global Equation page")
        shot(dialog, "window-piecewise-global-equation.png")
        assert dialog.validate() is True

    global_index = fit_new(GROUPS, global_dialog, "global conditional fit")
    global_run = app.runs[global_index]
    assert global_run.options["Equation syntax"] == "Conditional"
    frame = GROUP_FRAME.dropna(subset=["X", "Y"])
    shared_a, local = joint_ols(frame)
    parameters = tables(global_index)["Parameters"]
    np.testing.assert_allclose(parameters.loc[(parameters.Scope == "Shared") & (parameters.Parameter == "A"),
                                              "Estimate"], [shared_a], rtol=1e-6)
    for label, (b, c) in local.items():
        rows = parameters[(parameters.Scope == "Local") & (parameters.Group == label)].set_index("Parameter")
        np.testing.assert_allclose(rows.loc[["B", "C"], "Estimate"], [b, c], rtol=1e-6, atol=1e-9)
    bands = tables(global_index)["Curve bands"]
    pd.testing.assert_series_equal(bands["Branch"].reset_index(drop=True),
                                   tables(global_index)["Curve"]["Branch"].reset_index(drop=True))
    axes = global_run.result.figure.axes[0]
    polygons = [path for collection in axes.collections if str(collection.get_gid() or "").startswith(GID)
                for path in collection.get_paths()]
    assert len(polygons) == 4, len(polygons)  # two series, two branches each: no band across the threshold
    for path in polygons:
        xs = path.vertices[:, 0]
        assert (xs < 0).all() or (xs >= 0).all(), xs
    predictions = tables(global_index)["Predictions"]
    assert predictions["Status"].tolist() == ["OK", "OK"], predictions
    np.testing.assert_allclose(predictions["Predicted"], [shared_a - .5 * local["G1"][0], shared_a + .5 * local["G2"][1]],
                               rtol=1e-6)
    app.show("graph", global_index)
    root.update()
    shot(root, "window-piecewise-global-graph.png")
    note("global fit: shared A and local B, C match the joint design; 4 band pieces; predictions by branch")

    # 6. Two-panel layout in PNG/SVG/PDF; no selection or preview object in the files.
    app.layouts.append(Layout("Piecewise panels", 2, [app.runs[index].reference, global_run.reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-piecewise-layout.png")
    for kind in ("png", "svg", "pdf"):
        target = out / f"piecewise-layout{suffix}.{kind}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, target
    layout_svg = (out / f"piecewise-layout{suffix}.svg").read_text(encoding="utf-8")
    # The layout prefixes the ids of each panel; the second panel holds the two band groups.
    assert "<image" not in layout_svg and layout_svg.count(f'id="panel2-{GID}') == 2, layout_svg.count(GID)
    for word in ("selection", "preview", "handle"):
        assert word not in layout_svg.lower(), word
    [(_, layout_text, layout_images)] = read_pdf(out / f"piecewise-layout{suffix}.pdf")
    assert layout_images == 0 and "G1" in layout_text and "G2" in layout_text, (layout_images, layout_text)
    note("two-panel layout PNG/SVG/PDF: vector, both band groups, no selection or preview object")

    # 7. Save, reopen: the graph first, then the parameters. The legacy recipe stays Arithmetic and identical.
    expected = {(r.title, r.slot): (dict(r.options), {k: v.copy() for k, v in r.result.tables.items()}, r.style)
                for r in app.runs if r.method in (CUSTOM_EQUATION, GLOBAL_CUSTOM_EQUATION) and r.result is not None}
    assert len(expected) == 2, sorted(expected)
    app.path = directory / f"piecewise-saved{suffix}.alab"
    assert app.save()
    payload = app.path.read_bytes()
    assert b"Conditional" in payload and b"trama-global-band" not in payload
    app.import_file(app.path)
    for position, item in enumerate(app.runs):
        if (item.title, item.slot) in expected:
            app.open_sheet(("graph", position))
            wait("reopen graph first")
            app.open_sheet(("result", position))
            wait("then parameters")
    reopened = {(r.title, r.slot): r for r in app.runs}
    for key, (options, frames, style) in expected.items():
        assert reopened[key].options == options and reopened[key].style == style, key
        for name, frame in frames.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    legacy_index = next(i for i, r in enumerate(app.runs) if r.title == LEGACY)
    app.open_sheet(("result", legacy_index))
    wait("legacy recipe")
    assert "Equation syntax" not in app.runs[legacy_index].options
    expected_legacy = analyse(LEGACY_RECIPE[0], SINGLE_FRAME, LEGACY_RECIPE[1])
    for name, frame in expected_legacy.tables.items():
        pd.testing.assert_frame_equal(app.runs[legacy_index].result.tables[name], frame)
    assert "Branch" not in app.runs[legacy_index].result.tables["Curve: All"]

    def legacy_dialog(dialog):
        dialog.fields.select(1)
        assert dialog.controls["Equation syntax"][1].get() == "Arithmetic" and not guide_shown(dialog)
        assert dialog.validate() is True and "Equation syntax" not in dialog.result[1], dialog.result[1]

    legacy_options = dict(app.runs[legacy_index].options)
    edit(legacy_dialog, legacy_index, accept=False, phase="legacy dialog")
    assert app.runs[legacy_index].options == legacy_options
    note("save/reopen graph-first then parameters: options, style and tables equal; legacy recipe unchanged")

    # 8. Italian: labels change, the recipe does not. Keyboard back to Arithmetic and errors on the right field.
    position = next(i for i, r in enumerate(app.runs) if (r.title, r.slot) in expected and
                    r.method == CUSTOM_EQUATION)
    recipe = dict(app.runs[position].options)

    def italian(dialog):
        assert [dialog.fields.tab(i, "text") for i in range(4)] == ["Variabili", "Equazione", "Coefficienti",
                                                                    "Risultati"]
        dialog.fields.select(1)
        dialog.update()
        assert syntax_box(dialog).get() == "Condizionale" and guide_shown(dialog)
        guide = dialog.controls["Equation"][1].conditional.winfo_children()[0].cget("text")
        assert guide.startswith("Condizionale:"), guide
        on_screen(dialog, "Italian Equation page")
        shot(dialog, "window-piecewise-equation-it.png")
        choose_by_keyboard(dialog, "Up", "Arithmetic")
        assert syntax_box(dialog).get() == "Aritmetica" and not guide_shown(dialog)
        assert dialog.controls["Equation"][1].values() == recipe["Equation"]
        rejected(dialog, "Equation", "sintassi Condizionale")
        choose_by_keyboard(dialog, "Down", "Conditional")
        table = dialog.controls["Parameters"][1]
        select_row(table, "T")
        table.fixed.set(False)
        table.store()
        message = rejected(dialog, "Parameters", "deve essere Fisso")
        assert "must be" not in message, message
        shot(dialog, "window-piecewise-free-threshold-it.png")
        table.fixed.set(True)
        table.store()
        assert dialog.validate() is True
        assert dialog.result[1] == recipe, dialog.result[1]

    i18n.set_language("it")
    try:
        edit(italian, position, accept=False, phase="Italian dialog")
    finally:
        i18n.set_language("en")
    assert app.runs[position].options == recipe
    note("Italian: tabs, choice labels, guide and errors translated; keyboard choice; recipe unchanged")

    # Leave the application idle and the main window mapped for the checks that follow.
    wait("end")
    root.deiconify()
    root.update()
    assert root.winfo_ismapped() and app.pending is None and find_dialog() is None and not errors, errors
    note("PASS")
