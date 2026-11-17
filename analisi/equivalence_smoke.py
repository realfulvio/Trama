"""Desktop smoke check for the Equivalence test (TOST), driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_equivalence` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=equivalence python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/equivalence_071). Expected values are the frozen
numbers of the independent oracle (tests/equivalence_oracle.py), not computed by the module under test.
"""
import json
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .equivalence_workbench import EQUIVALENCE
from .graph_dialog import GraphFormatDialog

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "equivalence_071"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
SHEET, CONSTANT, FEW = "Equivalence data", "Constant data", "Few pairs"
SUMMARY = {"Difference": "difference", "SE": "se", "df": "df", "CI lower": "ci_lower", "CI upper": "ci_upper",
           "t lower": "t_lower", "p lower": "p_lower", "t upper": "t_upper", "p upper": "p_upper", "p TOST": "p_tost"}


def worksheet():
    """Response (8), First/Second (8 rows, the last pair incomplete), Control (15) and Treated (8) in one sheet."""
    one = pd.read_csv(FIXTURES / "one_sample.csv")
    paired = pd.read_csv(FIXTURES / "paired.csv")
    independent = pd.read_csv(FIXTURES / "independent.csv")
    frame = pd.DataFrame({"Response": one["Response"], "First": paired["First"], "Second": paired["Second"],
                          "Control": independent["First"], "Treated": independent["Second"]})
    return frame


def check_equivalence(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "equivalence"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    path = directory / "equivalence.alab"
    data = worksheet()
    save_project(path, {SHEET: Dataset(data.copy()), CONSTANT: Dataset(pd.DataFrame({"Response": [.1, .1, .1, .1]})),
                        FEW: Dataset(pd.DataFrame({"First": [1.0, 1.2, 1.1], "Second": [1.05, 1.15, 1.12],
                                                      "Sparse": [1.0, np.nan, np.nan]}))})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

    def placed(dialog, name):
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

    def table(index, name):
        return app.runs[index].result.tables[name]

    def summary(index):
        return table(index, "Equivalence summary").iloc[0]

    def assert_oracle(index, name):
        row, expected = summary(index), EXPECTED[name]
        for column, key in SUMMARY.items():
            np.testing.assert_allclose(row[column], expected[key], rtol=1e-12, err_msg=(name, column))
        assert row["Conclusion"] == expected["conclusion"] and row["Status / Reason"] == "OK", row
        assert row["N first"] == expected["n_first"], row
        assert (row["N second"] is None) == (expected["n_second"] is None) and (
            expected["n_second"] is None or row["N second"] == expected["n_second"]), row

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == EQUIVALENCE and app.runs[index].title == title
        return index

    def margins(dialog, lower, upper, alpha="0.05"):
        dialog.controls["Lower margin"][1].set(lower)
        dialog.controls["Upper margin"][1].set(upper)
        dialog.controls["Alpha"][1].set(alpha)

    # 1. One-sample: defaults, hidden fields, every invalid value on its own field and in the same dialog.
    def one_sample_dialog(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Data", "Equivalence zone"]
        assert controls["Design"][1].get() == "One-sample" and controls["Alpha"][1].get() == "0.05"
        assert controls["Lower margin"][1].get() == "0.0" and controls["Upper margin"][1].get() == "0.0"
        assert placed(dialog, "Response") and placed(dialog, "Reference")
        assert not placed(dialog, "First") and not placed(dialog, "Second")
        controls["Response"][1].set("Response")
        # The margins are not proposed: the empty zone is refused until it is declared.
        rejected(dialog, "Lower margin", "below zero")
        controls["Lower margin"][1].set("-0,06")
        rejected(dialog, "Upper margin", "above zero")
        controls["Upper margin"][1].set("0,06")
        controls["Alpha"][1].set("0.7")
        rejected(dialog, "Alpha", "less than 0.5", "window-equivalence-error.png")
        controls["Alpha"][1].set("abc")
        rejected(dialog, "Alpha", "must be a number")
        controls["Alpha"][1].set("nan")
        rejected(dialog, "Alpha", "finite")
        controls["Alpha"][1].set("0.5")
        rejected(dialog, "Alpha", "less than 0.5")
        controls["Alpha"][1].set("0.05")
        controls["Lower margin"][1].set("0.06")           # inverted zone: the lower margin is the wrong one
        controls["Upper margin"][1].set("-0.06")
        rejected(dialog, "Lower margin", "below zero")
        controls["Lower margin"][1].set("-0.06")
        controls["Upper margin"][1].set("0.06")
        controls["Reference"][1].set("inf")
        rejected(dialog, "Reference", "finite")
        controls["Reference"][1].set("0")                 # zero is a valid reference
        # Corrected values stay in the same dialog; every tab fits the screen and Run is reachable.
        assert controls["Lower margin"][1].get() == "-0.06" and controls["Design"][1].get() == "One-sample"
        reachable(dialog)
        dialog.fields.select(0)
        shot(dialog, "window-equivalence-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-equivalence-zone" + suffix + ".png")
        dialog.fields.select(0)

    index = analyse_with(one_sample_dialog, SHEET)
    options = app.runs[index].options
    assert options == {"Design": "One-sample", "Response": "Response", "Reference": 0.0, "Lower margin": -0.06,
                       "Upper margin": 0.06, "Alpha": 0.05}, options
    assert_oracle(index, "one_sample")
    assert set(app.runs[index].result.tables) == {"Equivalence summary", "Equivalence tests", "Data used", "Settings"}
    row = summary(index)
    assert (row["First label"], row["Second label"], row["N second"]) == ("Response", "Reference (0)", None), row
    tests = table(index, "Equivalence tests")
    assert tests["Null rejected"].tolist() == ["Yes", "Yes"] and len(tests) == 2
    app.show("result", index)
    app.result_tabs.select(0)
    shot(root, "window-equivalence-result" + suffix + ".png")
    app.show("graph", index)
    root.update()
    axes = app.runs[index].result.figure.axes[0]
    assert "Equivalent" in axes.get_title() and "Sample − Reference" in axes.get_xlabel()
    gids = {child.get_gid() for child in axes.get_children() if child.get_gid()}
    assert {"tost:zone", "tost:lower", "tost:upper", "tost:zero", "tost:estimate"} <= gids, gids
    shot(root, "window-equivalence-graph" + suffix + ".png")
    one_sample_index = index

    # 2. All four designs: dynamic fields, hidden values neither validated nor saved; Paired with an incomplete pair.
    def paired_dialog(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        controls = dialog.controls
        for design, shown, hidden in (("One-sample", ("Response", "Reference"), ("First", "Second")),
                                      ("Paired", ("First", "Second"), ("Response", "Reference")),
                                      ("Student", ("First", "Second"), ("Response", "Reference")),
                                      ("Welch", ("First", "Second"), ("Response", "Reference")),
                                      ("Paired", ("First", "Second"), ("Response", "Reference"))):
            controls["Design"][1].set(design)
            dialog.update()
            assert all(placed(dialog, name) for name in shown), (design, shown)
            assert not any(placed(dialog, name) for name in hidden), (design, hidden)
        controls["First"][1].set("First")
        controls["Second"][1].set("Second")
        margins(dialog, "-0.08", "0.12")
        # An invalid hidden Reference does not stop a paired run.
        controls["Reference"][1].set("abc")
        assert dialog.validate() is True
        controls["Second"][1].set("First")
        rejected(dialog, "Second", "different columns")
        controls["Second"][1].set("Second")

    paired_index = analyse_with(paired_dialog, SHEET)
    options = app.runs[paired_index].options
    assert options == {"Design": "Paired", "First": "First", "Second": "Second", "Lower margin": -0.08,
                       "Upper margin": 0.12, "Alpha": 0.05}, options
    assert_oracle(paired_index, "paired")
    used = table(paired_index, "Data used")
    assert used["Source row"].tolist() == list(range(7)) and list(used.columns) == [
        "Source row", "First", "Second", "Difference"], used
    app.show("graph", paired_index)
    root.update()
    shot(root, "window-equivalence-paired" + suffix + ".png")

    # 3. Student: the Run button is reached and pressed from the keyboard.
    def student_dialog(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        controls = dialog.controls
        controls["Design"][1].set("Student")
        controls["First"][1].set("Control")
        controls["Second"][1].set("Treated")
        margins(dialog, "-0.12", "0.12")
        dialog.update()
        button = run_button(dialog)
        dialog.focus_force()
        button.focus_force()
        dialog.update()
        assert dialog.focus_get() is button, dialog.focus_get()
        dialog.ok = lambda *args: None     # the key press below runs the button's own command
        button.event_generate("<space>")
        dialog.update()

    student_index = analyse_with(student_dialog, SHEET)
    assert_oracle(student_index, "independent_student")
    assert (summary(student_index)["N first"], summary(student_index)["N second"]) == (15, 8)

    # 4. Edit a cell and exclude another: every run of the worksheet recalculates.
    app.show("data", SHEET)
    app.edit_cell(0, 1, "10.3")
    wait()
    first = list(data["First"])
    second = list(data["Second"])
    first[0] = 10.3
    want = pd.DataFrame({"First": first, "Second": second}).dropna()
    difference = want["First"] - want["Second"]
    np.testing.assert_allclose(summary(paired_index)["Difference"], difference.mean(), rtol=1e-12)
    np.testing.assert_allclose(summary(paired_index)["SE"], difference.std(ddof=1) / np.sqrt(len(difference)),
                               rtol=1e-12)
    app.show("data", SHEET)
    app.current_grid.select((3, 2))
    app.toggle_exclusion()
    wait()
    assert summary(paired_index)["N first"] == 6 and table(paired_index, "Data used")["Source row"].tolist() == [
        0, 1, 2, 4, 5, 6], table(paired_index, "Data used")
    kept = want.drop(index=3)
    np.testing.assert_allclose(summary(paired_index)["Difference"], (kept["First"] - kept["Second"]).mean(), rtol=1e-12)
    assert summary(one_sample_index)["N first"] == 8 and summary(student_index)["N second"] == 8
    app.show("graph", paired_index)
    root.update()

    # 5. Welch in Italian: translated captions, errors and choices; canonical values in the recipe.
    original_language = i18n.active_language()
    welch_recipe = {"Design": "Welch", "First": "Control", "Second": "Treated", "Lower margin": -0.12,
                    "Upper margin": 0.12, "Alpha": 0.05}

    def italian(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in ("Design", "Response", "Reference", "First", "Second", "Lower margin", "Upper margin",
                                 "Alpha")}
        assert captions == {"Design": "Disegno", "Response": "Risposta", "Reference": "Valore di riferimento",
                            "First": "Prima colonna", "Second": "Seconda colonna", "Lower margin": "Margine inferiore",
                            "Upper margin": "Margine superiore", "Alpha": "Alfa"}, captions
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Dati", "Zona di equivalenza"]
        design = dialog.field_rows["Design"][1]
        assert list(design.cget("values")) == ["Un campione", "Appaiato", "Student", "Welch"], design.cget("values")
        assert design.get() == "Un campione" and dialog.controls["Design"][1].get() == "One-sample"
        rejected(dialog, "Lower margin", "minore di zero", caption="Margine inferiore")
        design.set("Welch")
        dialog.update()
        assert dialog.controls["Design"][1].get() == "Welch" and placed(dialog, "First") and not placed(
            dialog, "Response")
        dialog.controls["First"][1].set("Control")
        dialog.controls["Second"][1].set("Treated")
        margins(dialog, "-0,12", "0,12", "0.7")
        rejected(dialog, "Alpha", "maggiore di 0", "window-equivalence-it-error.png", caption="Alfa")
        dialog.controls["Alpha"][1].set("0.05")
        dialog.controls["Second"][1].set("Control")
        rejected(dialog, "Second", "colonne diverse", caption="Seconda colonna")
        dialog.controls["Second"][1].set("Treated")
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-equivalence-it" + suffix + ".png")

    try:
        i18n.set_language("it")
        welch_index = analyse_with(italian, SHEET)
        assert app.runs[welch_index].options == welch_recipe, app.runs[welch_index].options
        assert_oracle(welch_index, "independent_welch")
        app.show("graph", welch_index)
        root.update()
        shot(root, "window-equivalence-it-graph" + suffix + ".png")
        i18n.set_language("en")

        def english_again(dialog):
            shown = [dialog.field_rows[name][1].get() for name in ("Design", "First", "Second")]
            assert shown == ["Welch", "Control", "Treated"], shown
            assert dialog.field_rows["Lower margin"][0].cget("text") == "Lower margin"

        app.show("result", welch_index)
        tools.drive_dialog(tools.AnalysisDialog, english_again)
        app.edit_analysis()
        wait()
        assert app.runs[welch_index].options == welch_recipe
    finally:
        i18n.set_language(original_language)

    # 6. Inference unavailable: constant data keep their counts, invent no p value and the figure claims nothing.
    def constant(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        dialog.controls["Response"][1].set("Response")
        margins(dialog, "-1", "1")

    constant_index = analyse_with(constant, CONSTANT)
    row = summary(constant_index)
    assert row["Conclusion"] == "Inference unavailable" and row["N first"] == 4 and np.isnan(row["p TOST"]), row
    assert "standard error is zero" in row["Status / Reason"]
    assert table(constant_index, "Equivalence tests")["Null rejected"].tolist() == ["Not available"] * 2
    app.show("result", constant_index)
    app.result_tabs.select(0)
    shot(root, "window-equivalence-unavailable" + suffix + ".png")
    app.show("graph", constant_index)
    root.update()
    unavailable = app.runs[constant_index].result.figure.axes[0]
    assert "Inference unavailable" in unavailable.get_title() and not [
        line for line in unavailable.lines if line.get_gid() == "tost:estimate"]
    shot(root, "window-equivalence-unavailable-graph" + suffix + ".png")

    # 7. A numeric error never replaces a previous valid result: a refused edit and a failed recalculation.
    def pairs_dialog(dialog):
        tools.pick_method(dialog, EQUIVALENCE)
        dialog.controls["Design"][1].set("Paired")
        dialog.controls["First"][1].set("First")
        dialog.controls["Second"][1].set("Second")
        margins(dialog, "-0.5", "0.5")

    few_index = analyse_with(pairs_dialog, FEW)
    before = app.runs[few_index].result
    before_summary = summary(few_index).copy()

    def bad_edit(dialog):
        dialog.controls["Lower margin"][1].set("0.5")
        rejected(dialog, "Lower margin", "below zero")
        dialog.controls["Lower margin"][1].set("-0.5")
        dialog.controls["Second"][1].set("Sparse")                 # only one complete pair: a data error
        rejected(dialog, "First", "two complete pairs")
        assert dialog.fields.select() == str(dialog.field_rows["First"][1].master)
        dialog.cancel()
        dialog.ok = lambda *args: None

    app.show("result", few_index)
    tools.drive_dialog(tools.AnalysisDialog, bad_edit)
    app.edit_analysis()
    wait()
    assert app.runs[few_index].result is before and app.runs[few_index].options["Lower margin"] == -0.5
    assert app.runs[few_index].options["Second"] == "Second" and summary(few_index).equals(before_summary)
    assert not errors, errors

    # 8. Inspector and Format Graph on the figure.
    app.show("graph", paired_index)
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
    assert "#9b4174" in str(app.runs[paired_index].style), app.runs[paired_index].style
    app.toggle_inspector()
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Equivalence of First and Second"))
    app.format_graph()
    wait()
    assert app.runs[paired_index].result.figure.axes[0].get_title() == "Equivalence of First and Second"
    app.show("graph", paired_index)
    root.update()

    # 9. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure.
    app.show("result", student_index)
    for position, name in enumerate(("Equivalence summary", "Equivalence tests", "Data used", "Settings")):
        app.result_tabs.select(position)
        target = out / f"equivalence-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Equivalence summary":
            assert exported.loc[0, "Conclusion"] == "Not demonstrated" and exported.loc[0, "N first"] == 15
            assert list(exported.columns)[-2:] == ["Conclusion", "Status / Reason"]
        if name == "Equivalence tests":
            assert exported["Null rejected"].tolist() == ["No", "No"]
    app.show("graph", student_index)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"equivalence.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension

    # 10. Save, reopen and open the graph before the worksheet: canonical recipes, same tables, same figure.
    def figure_state(run):
        axes = run.result.figure.axes[0]
        marks = {child.get_gid(): np.asarray(child.get_xdata(), float).tolist() for child in axes.lines
                 if child.get_gid()}
        return axes.get_title(), axes.get_xlabel(), tuple(round(v, 10) for v in axes.get_xlim()), marks

    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()},
                                        figure_state(run))
                for run in app.runs if run.method == EQUIVALENCE and run.result is not None}
    assert len(expected) == 6, sorted(expected)
    app.path = directory / "equivalence-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == EQUIVALENCE:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, tables, figure) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
        assert figure_state(reopened[key]) == figure, key
    key = next(k for k, v in expected.items() if v[0]["Design"] == "Paired" and k[0] == SHEET)
    reopened_index = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style) and reopened[key].options["Design"] == "Paired"
    assert "Reference" not in reopened[key].options and "Response" not in reopened[key].options
    app.show("graph", reopened_index)
    root.update()
    shot(root, "window-equivalence-reopened" + suffix + ".png")

    # 11. Use Result as Data from the new sheets keeps the source rows.
    before_tables = set(app.tables)
    for position in (0, 2):
        app.show("result", reopened_index)
        app.result_tabs.select(position)
        app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 2, created
    assert any(list(f.columns) == ["Source row", "First", "Second", "Difference"] and len(f) == 6
               for f in created.values()), {k: list(v.columns) for k, v in created.items()}
    assert any(list(f.columns)[:3] == ["Design", "First label", "Second label"] and len(f) == 1
               for f in created.values())
    wait()
    assert app.pending is None and not errors, errors
