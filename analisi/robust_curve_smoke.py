"""Desktop smoke check for Robust curve fit (0.73), driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_robust_curve` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=robust-curve python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/robust_curve_073). The expected numbers are the frozen values of
the independent reference oracle (expected/results.json), never computed by the module under test.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, robust_curve
from .data import Dataset, save_project
from .field_error import FieldError
from .graph_dialog import GraphFormatDialog
from .graph_language_smoke import drive_mapped_dialog
from .presentation import Layout
from .robust_curve import ROBUST_CURVE
from .robust_curve_dialog import InitialParametersDialog

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "robust_curve_073"
CASES = {case["name"]: case for case in json.loads((DATA / "fixtures" / "cases.json").read_text(encoding="utf-8"))}
EXPECTED = json.loads((DATA / "expected" / "results.json").read_text(encoding="utf-8"))
SINGLE, GROUPS, FEW = "Robust single", "Robust groups", "Robust few"
LINE_Y = CASES["line-Cauchy-1.0"]["data"]["Y"]
LINE_X = CASES["line-Cauchy-1.0"]["data"]["X"]
START = {"Intercept": 2.0, "Slope": 3.0}


def groups_frame():
    """Two Y columns and a Group of two levels: four fits of nine pairs. Group B is Group A shifted by five."""
    x = LINE_X * 2
    y = LINE_Y + [value + 5 for value in LINE_Y]
    y2 = [value * 0.5 + 1 for value in y]
    y2[12] = None  # Y2 is missing in group B only: that fit has eight pairs, the others nine
    return pd.DataFrame({"X": x, "Y": y, "Y2": y2, "Group": ["A"] * 9 + ["$B$_x"] * 9})


def check_robust_curve(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "robust-curve"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    path = directory / "robust-curve.alab"
    save_project(path, {SINGLE: Dataset(pd.DataFrame({"X": LINE_X, "Y": LINE_Y})),
                        GROUPS: Dataset(groups_frame()),
                        FEW: Dataset(pd.DataFrame({"X": [0.0, 1.0, 2.0], "Y": [1.0, 2.0, 3.1]}))})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
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

    def table(index, name):
        return app.runs[index].result.tables[name]

    def parameters(index, series=None):
        frame = table(index, "Robust parameters")
        if series is not None:
            frame = frame[frame["Series"] == series]
        return frame["Estimate"].to_numpy(float)

    def assert_oracle(index, name):
        want = EXPECTED[name]
        np.testing.assert_allclose(parameters(index), want["parameters"], rtol=3e-5, atol=2e-7, err_msg=name)
        residuals = table(index, "Robust residuals")
        np.testing.assert_allclose(residuals["Influence weight"], want["weights"], rtol=3e-5, atol=2e-7, err_msg=name)
        np.testing.assert_allclose(residuals["Residual"], want["residuals"], rtol=3e-5, atol=2e-7, err_msg=name)
        assert residuals["Source row"].tolist() == want["source_rows"], name
        fit = table(index, "Robust fit").iloc[0]
        np.testing.assert_allclose(fit["Residual scale"], want["scale"], rtol=3e-5, atol=2e-7, err_msg=name)
        np.testing.assert_allclose(fit["Robust objective"], want["objective"], rtol=3e-5, atol=2e-7, err_msg=name)

    def pick_columns(dialog, x="X", ys=("Y",), group=""):
        dialog.controls["X"][1].set(x)
        tools.select_columns(dialog, "Y columns", ys)
        dialog.controls["Group"][1].set(group)

    def edit_start(dialog, values):
        """Open the table of starting values, type them and press Apply."""
        def fill(editor):
            for name, value in values.items():
                editor.variables[name].set(str(value))
        tools.drive_dialog(InitialParametersDialog, fill)
        dialog.field_rows["Initial parameters"][1].edit()

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == ROBUST_CURVE and app.runs[index].title == title
        return index

    # 1. English dialog: pages, defaults, the starting-value table, every invalid value on its own field.
    def english(dialog):
        tools.pick_method(dialog, ROBUST_CURVE)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Variables", "Loss and scale", "Output"], [
            dialog.fields.tab(i, "text") for i in range(3)]
        assert controls["Model"][1].get() == "Straight line" and controls["Loss"][1].get() == "Cauchy"
        assert controls["Scale method"][1].get() == "Fixed" and controls["Residual scale"][1].get() == "1.0"
        assert controls["Maximum evaluations"][1].get() == "20000" and controls["Low weight threshold"][1].get() == "0.25"
        assert controls["Compare ordinary fit"][1].get() is False and controls["Graph display"][1].get() == "Curve"
        assert dialog.field_rows["Initial parameters"][1].summary.cget("text") == "Catalog starting values"
        assert placed(dialog, "Residual scale")
        pick_columns(dialog)
        # Scale: zero, negative, text, not finite.
        controls["Residual scale"][1].set("0")
        rejected(dialog, "Residual scale", "greater than 0", "window-robust-error.png")
        controls["Residual scale"][1].set("abc")
        rejected(dialog, "Residual scale", "must be a number")
        controls["Residual scale"][1].set("inf")
        rejected(dialog, "Residual scale", "finite")
        controls["Residual scale"][1].set("1.0")
        controls["Maximum evaluations"][1].set("10")
        rejected(dialog, "Maximum evaluations", "from 50 to 100000")
        controls["Maximum evaluations"][1].set("1.5")
        rejected(dialog, "Maximum evaluations", "whole number")
        controls["Maximum evaluations"][1].set("20000")
        controls["Low weight threshold"][1].set("1")
        rejected(dialog, "Low weight threshold", "greater than 0 and less than 1")
        controls["Low weight threshold"][1].set("0.25")
        # Columns: Y must not repeat X, nothing selected is refused too.
        tools.select_columns(dialog, "Y columns", ())
        rejected(dialog, "Y columns", "Select at least one column")
        pick_columns(dialog, ys=("X",))
        rejected(dialog, "Y columns", "must be different")
        pick_columns(dialog)
        # A hidden residual scale is neither shown nor validated under Pilot MAD, even when it is garbage.
        controls["Scale method"][1].set("Pilot MAD")
        dialog.update()
        assert not placed(dialog, "Residual scale")
        controls["Residual scale"][1].set("garbage")
        assert dialog.validate() is True and dialog.result[1]["Scale method"] == "Pilot MAD"
        assert "Residual scale" not in dialog.result[1] or dialog.result[1]["Residual scale"] == 1.0
        controls["Scale method"][1].set("Fixed")
        dialog.update()
        assert placed(dialog, "Residual scale")
        controls["Residual scale"][1].set("1.0")
        # The starting values: catalog proposal first, then an empty entry keeps the table open, Reset returns to it.
        editor = dialog.field_rows["Initial parameters"][1]
        observed = {}

        def probe(table_dialog):
            assert set(table_dialog.variables) == {"Intercept", "Slope"}
            observed["catalog"] = {name: variable.get() for name, variable in table_dialog.variables.items()}
            assert all(value for value in observed["catalog"].values()), observed
            table_dialog.variables["Slope"].set("")
            with patch.object(tools.messagebox, "showerror") as banner:
                assert table_dialog.validate() is False
            assert table_dialog.winfo_exists() and "Slope" in banner.call_args.args[1], banner.call_args
            assert table_dialog.focus_get() is table_dialog.entries["Slope"] or table_dialog.initial_focus is (
                table_dialog.entries["Slope"])
            shot(table_dialog, "window-robust-initial-error" + suffix + ".png")
            table_dialog.variables["Slope"].set("abc")
            with patch.object(tools.messagebox, "showerror") as banner:
                assert table_dialog.validate() is False
            table_dialog.variables["Intercept"].set("2")
            table_dialog.variables["Slope"].set("3")
            shot(table_dialog, "window-robust-initial" + suffix + ".png")
            table_dialog.reset()
            assert {name: variable.get() for name, variable in table_dialog.variables.items()} == observed["catalog"]

        tools.drive_dialog(InitialParametersDialog, probe)
        editor.edit()
        assert editor.values() == {} and editor.summary.cget("text") == "Catalog starting values"
        def cancelled(table_dialog):
            table_dialog.variables["Intercept"].set("99")
            table_dialog.cancel()

        drive_mapped_dialog(root, InitialParametersDialog, cancelled, errors)
        editor.edit()
        assert editor.values() == {}, "Cancel keeps the previous state"
        edit_start(dialog, START)
        assert editor.values() == START and editor.summary.cget("text").startswith("Custom: Intercept = 2")
        # A model with other parameters returns the table to the catalog values.
        controls["Model"][1].set("One-phase decay")
        assert editor.values() == {}
        controls["Model"][1].set("Straight line")
        edit_start(dialog, START)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-robust-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-robust-loss" + suffix + ".png")
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-robust-output" + suffix + ".png")
        dialog.fields.select(0)

    index = analyse_with(english, SINGLE)
    single = index
    options = app.runs[index].options
    assert options["X"] == "X" and options["Y columns"] == ["Y"] and options["Initial parameters"] == START, options
    assert options["Model"] == "Straight line" and options["Loss"] == "Cauchy" and options["Residual scale"] == 1.0
    assert set(app.runs[index].result.tables) == {"Robust parameters", "Robust fit", "Robust residuals", "Robust curve"}
    assert_oracle(index, "line-Cauchy-1.0")
    assert len(table(index, "Robust curve")) == 201
    done("english dialog, oracle line-Cauchy-1.0")
    app.show("result", index)
    app.result_tabs.select(0)
    shot(root, "window-robust-results" + suffix + ".png")
    app.show("graph", index)
    root.update()
    figure = app.runs[index].result.figure
    assert len(figure.axes) == 1 and "Robust" in figure.axes[0].get_title()
    shot(root, "window-robust-graph" + suffix + ".png")

    # 2. Pilot MAD with an invalid hidden scale, from the packaged fixture; Curve, Residuals and Weights agree.
    pilot = CASES["pilot-mad"]["options"]

    def pilot_dialog(dialog):
        tools.pick_method(dialog, ROBUST_CURVE)
        pick_columns(dialog)
        dialog.controls["Scale method"][1].set("Pilot MAD")
        dialog.controls["Residual scale"][1].set("ignored-invalid")
        edit_start(dialog, pilot["Initial parameters"])

    pilot_index = analyse_with(pilot_dialog, SINGLE)
    assert_oracle(pilot_index, "pilot-mad")
    fit = table(pilot_index, "Robust fit").iloc[0]
    assert fit["Scale source"] == "Pilot MAD", fit
    before = parameters(pilot_index).copy()
    figures = {}
    for display, ylabel in (("Residuals", "Residual"), ("Weights", "weight"), ("Curve", "Y")):
        app.show("result", pilot_index)

        def settings(dialog, display=display):
            assert dialog.fields.select() == str(dialog.field_rows["Graph display"][1].master), "Graph settings opens Output"
            dialog.controls["Graph display"][1].set(display)

        tools.drive_dialog(tools.AnalysisDialog, settings)
        app.edit_analysis(initial_field="Graph display")
        wait()
        np.testing.assert_allclose(parameters(pilot_index), before, rtol=0, atol=0)
        app.show("graph", pilot_index)
        root.update()
        figures[display] = app.runs[pilot_index].result.figure.axes[0].get_ylabel()
        assert ylabel.lower() in figures[display].lower(), (display, figures[display])
    assert len(set(figures.values())) == 3, figures
    done("pilot MAD with invalid hidden scale; Curve/Residuals/Weights identical parameters")

    # 3. Two Y columns and a Group: four fits of nine pairs, each with its own sample and labels.
    def grouped(dialog):
        tools.pick_method(dialog, ROBUST_CURVE)
        pick_columns(dialog, ys=("Y", "Y2"), group="Group")
        edit_start(dialog, START)
        dialog.controls["Compare ordinary fit"][1].set(True)
        dialog.controls["Low weight threshold"][1].set("0.5")

    group_index = analyse_with(grouped, GROUPS)
    tables = app.runs[group_index].result.tables
    assert "Ordinary comparison" in tables
    summary = tables["Robust fit"]
    assert summary["N"].tolist() == [9, 9, 9, 8] and len(summary) == 4, summary
    assert sorted(summary["Series"].unique()) == ["Y", "Y2"]
    assert sorted(summary["Group"].astype(str).unique()) == ["$B$_x", "A"]
    residuals = tables["Robust residuals"]
    assert len(residuals) == 35 and residuals["Source row"].tolist()[:9] == list(range(9))
    assert residuals["Source row"].tolist()[9:18] == list(range(9, 18)), "group B keeps its original positions"
    y2_b = residuals[(residuals["Series"] == "Y2") & (residuals["Group"] == "$B$_x")]
    assert 12 not in y2_b["Source row"].tolist() and len(y2_b) == 8, "the missing cell leaves only its own fit"
    first = parameters(group_index)
    np.testing.assert_allclose(first[:2], EXPECTED["line-Cauchy-1.0"]["parameters"], rtol=3e-5, atol=2e-7)
    shifted = tables["Robust parameters"]
    row = shifted[(shifted["Series"] == "Y") & (shifted["Group"] == "$B$_x") & (shifted["Parameter"] == "Intercept")]
    np.testing.assert_allclose(row["Estimate"].iloc[0], EXPECTED["line-Cauchy-1.0"]["parameters"][0] + 5, rtol=1e-5)
    app.show("graph", group_index)
    root.update()
    legend = app.runs[group_index].result.figure.axes[0].get_legend()
    labels = [text.get_text() for text in legend.get_texts()]
    assert len(labels) >= 5 and len(set(labels)) == len(labels), labels
    assert any("$B$_x" in label for label in labels), "user names are literal"
    assert not any(text.get_parse_math() for text in legend.get_texts())
    done("two Y columns and a Group")

    # 4. Edit a cell and exclude a row: every dependent run recalculates and keeps the original source rows.
    app.show("data", SINGLE)
    outlier = LINE_X.index(6)
    app.edit_cell(outlier, 1, "20.0")
    wait()
    weights = table(single, "Robust residuals")["Influence weight"].to_numpy(float)
    assert weights[outlier] > 0.9, weights
    app.show("data", SINGLE)
    app.current_grid.select((2, 1))
    app.toggle_exclusion()
    wait()
    kept = table(single, "Robust residuals")
    assert kept["Source row"].tolist() == [0, 1, 3, 4, 5, 6, 7, 8] and table(single, "Robust fit")["N"].iloc[0] == 8, kept
    assert table(pilot_index, "Robust fit")["N"].iloc[0] == 8
    done("edit and exclusion recalculation")

    # 5. Italian: captions, choices, decimal comma and errors on their own fields.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, ROBUST_CURVE)
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in ("X", "Y columns", "Group", "Model", "Loss", "Scale method", "Residual scale",
                                 "Initial parameters", "Maximum evaluations", "Low weight threshold",
                                 "Compare ordinary fit", "Graph display")}
        assert captions["Residual scale"] == "Scala dei residui" and captions["Loss"] == "Perdita", captions
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Variabili", "Perdita e scala", "Risultati"]
        assert list(dialog.field_rows["Scale method"][1].cget("values")) == ["Fissa", "MAD pilota"]
        assert list(dialog.field_rows["Graph display"][1].cget("values")) == ["Curva", "Residui", "Pesi"]
        assert dialog.controls["Scale method"][1].get() == "Fixed"
        pick_columns(dialog)
        dialog.controls["Residual scale"][1].set("0")
        rejected(dialog, "Residual scale", "maggiore di 0", "window-robust-it-error.png", caption="Scala dei residui")
        dialog.controls["Residual scale"][1].set("1,0")
        edit_start(dialog, START)
        assert dialog.field_rows["Initial parameters"][1].summary.cget("text").startswith("Personalizzati")
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-robust-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-robust-it-loss" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, SINGLE)
        assert app.runs[italian_index].options["Residual scale"] == 1.0
        assert app.runs[italian_index].options["Scale method"] == "Fixed"
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-robust-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    done("Italian dialog")

    # 6. A worker error after validation reopens the dialog with every value, a banner and the field focused.
    app.show("result", single)
    kept_tables = {name: frame.copy() for name, frame in app.runs[single].result.tables.items()}
    kept_options = dict(app.runs[single].options)
    failure = FieldError("Maximum evaluations", "Series Y: the optimizer did not converge within 20000 evaluations. "
                                                "Increase Maximum evaluations or change the starting values.")

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

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
            banner = dialog.error_label.cget("text")
            assert "Maximum evaluations" in banner and "did not converge" in banner, banner
            assert dialog.initial_field == "Maximum evaluations"
            assert dialog.fields.select() == str(dialog.field_rows["Maximum evaluations"][1].master)
            assert dialog.controls["Residual scale"][1].get() == "1.0" and dialog.controls["Model"][1].get() == (
                "Straight line")
            assert dialog.field_rows["Initial parameters"][1].values() == START
            shot(dialog, "window-robust-recovered" + suffix + ".png")
            dialog.cancel()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    with patch.object(robust_curve, "_solve_fit", side_effect=failure):
        tools.drive_dialog(tools.AnalysisDialog, lambda dialog: dialog.controls["Loss"][1].set("Huber"))
        app.edit_analysis()
        root.after(25, recovered)
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "recovery did not finish"
            root.update()
            time.sleep(.02)
    assert not errors, errors
    assert app.runs[single].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[single].result.tables[name], frame)
    # The same edit with a healthy solver now succeeds and replaces the result.
    tools.drive_dialog(tools.AnalysisDialog, lambda dialog: dialog.controls["Loss"][1].set("Huber"))
    app.edit_analysis()
    wait()
    assert app.runs[single].options["Loss"] == "Huber" and app.runs[single].options["Initial parameters"] == START
    assert table(single, "Robust fit")["Loss"].iloc[0] == "Huber"
    done("worker error reopens the dialog and the retry succeeds")

    # 7. Inspector Apply and Format Graph on the curve figure; literal titles.
    app.show("graph", group_index)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn series"
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[group_index].style), app.runs[group_index].style
    confirmed = app.runs[group_index].style
    panel.vars["element:color"].set("#117733")
    widget.event_generate("<Return>")
    root.update()
    assert panel.has_draft
    panel.cancel()
    root.update()
    assert app.inspector is None and app.runs[group_index].style == confirmed, "Cancel restores the confirmed style"
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Fits with $weights$ and _text_"))
    app.format_graph()
    wait()
    assert app.runs[group_index].result.figure.axes[0].get_title() == "Fits with $weights$ and _text_"
    app.show("graph", group_index)
    root.update()
    done("Inspector and literal titles")

    # 8. Exports: CSV of each table, then PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", group_index)
    for position, name in enumerate(("Robust parameters", "Robust fit", "Robust residuals", "Robust curve",
                                     "Ordinary comparison")):
        app.result_tabs.select(position)
        target = out / f"robust-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Robust residuals":
            assert {"Source row", "Source index", "Influence weight", "Low weight"} <= set(exported.columns)
            assert exported["Source row"].tolist() == table(group_index, name)["Source row"].tolist()
        if name == "Robust curve":
            assert len(exported) == 4 * 201
    app.show("graph", group_index)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"robust.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    figure_title = app.runs[group_index].result.figure.axes[0].get_title()
    svg_text = (exports / "robust.svg").read_text(encoding="utf-8")
    assert svg_text.count("<path") >= 8 and ("Fits with" in svg_text or "<g id=" in svg_text)
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "robust.pdf")
    assert "Fits with" in pdf_text and "Influence" not in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    assert figure_title == "Fits with $weights$ and _text_"
    app.layouts.append(Layout("Robust panels", 2, [app.runs[group_index].reference, app.runs[single].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.read_bytes()[:4] == b"%PDF" and target.stat().st_size > 1000
    shot(root, "window-robust-layout" + suffix + ".png")
    done("CSV, PNG, SVG, PDF and layout exports")

    # 9. Save, reopen and open the graph before the worksheet: canonical recipes, the same tables.
    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                for run in app.runs if run.method == ROBUST_CURVE and run.result is not None}
    assert len(expected) >= 4, sorted(expected)
    app.path = directory / "robust-curve-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == ROBUST_CURVE:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    key = next(k for k in expected if k[0] == GROUPS)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    shot(root, "window-robust-reopened" + suffix + ".png")
    done("save and reopen from the graph")

    # 10. Use Result as Data keeps the source rows and the index of the residual table.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(2)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert {"Series", "Group", "Source row", "Source index", "Influence weight"} <= set(frame.columns), frame.columns
    assert len(frame) == 35
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")

    # 11. A recipe of another method saved before this one exists keeps working (no leakage of the new fields).
    from .workbench import analyse
    legacy = analyse("Nonlinear regression", pd.DataFrame({"X": LINE_X, "Y": LINE_Y}), {
        "X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line", "Weighting": "Unweighted"})
    assert "Robust parameters" not in legacy.tables
    done("legacy recipe unchanged")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
