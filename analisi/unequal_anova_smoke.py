"""GUI smoke for unequal-variance one-way ANOVA, Tamhane T2 and Dunnett T3.

Kept outside tramastat.py so dialog rewrites in parallel work do not collide.
``h`` carries the smoke helpers: app, root, directory, dialog_type, drive_dialog,
pick_method, wait, capture, save_project and Dataset.
"""
from tkinter import filedialog, messagebox
from unittest.mock import patch

import numpy as np
import pandas as pd

from .unequal_anova import CONTROL, DUNNETT, DUNNETT_T3, FAMILY, JOINT, LEVEL, PAIRS, TAMHANE, VERSUS_CONTROL
from .workbench import analyse

METHOD = "One-way ANOVA"
TITLE = "Unequal variances"
WELCH_ROW, BF_ROW = "Welch one-way ANOVA", "Brown–Forsythe one-way ANOVA"


def _notebook_page(dialog, widget):
    """Notebook tab that contains widget. One-way Options fields sit in a scrollable frame."""
    page = widget
    while page is not None and page.master is not dialog.fields:
        page = page.master
    return page


def _data():
    groups = {"A": [0., 2, 1, 3], "B": [6., 12, 8, 14, 10], "C": [1., 2, 3, 4, 5, 6]}
    rows = [(label, value) for label, values in groups.items() for value in values]
    frame = pd.DataFrame(rows, columns=["Group", "Y"])
    # Flat repeats Y with a constant group C, to show the per-group variance error.
    return frame.assign(Flat=np.where(frame.Group == "C", 3., frame.Y))


def check_unequal_anova(h):
    app, root, directory = h.app, h.root, h.directory
    data = _data()
    path = directory / "unequal-anova.alab"
    legacy = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "None"}
    # A recipe saved before 0.48.1 has no confidence level and opens as before.
    h.save_project(path, {TITLE: h.Dataset(data, analyses=[(METHOD, dict(legacy))])})
    app.import_file(path)
    app.open_sheet(("result", 0))
    h.wait()
    old = app.runs[0]
    assert LEVEL not in old.options
    assert old.result.tables["ANOVA"]["Method"].iloc[0] == "Ordinary one-way ANOVA"

    def invalid(dialog, field, words):
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert all(word in message for word in words), message
        assert dialog.fields.select() == str(_notebook_page(dialog, dialog.field_rows[field][1])), field
        dialog.result = None

    def configure(dialog):
        assert dialog.controls["Method"][1].get() == "Ordinary"
        assert not dialog.field_rows[LEVEL][1].grid_info()
        dialog.controls["Post-hoc"][1].set(TAMHANE)
        dialog.update()
        assert dialog.field_rows[LEVEL][1].grid_info() and dialog.controls[LEVEL][1].get() == "95.0"
        # Tamhane needs unequal variances: the error names Post-hoc and the dialog stays open.
        invalid(dialog, "Post-hoc", ("Post-hoc", TAMHANE))
        h.capture(dialog, "window-unequal-anova-posthoc-error.png")
        dialog.controls["Method"][1].set(JOINT)
        for text in ("100", "0", "abc", "nan"):
            dialog.controls[LEVEL][1].set(text)
            invalid(dialog, LEVEL, (LEVEL,))
            if text == "100":
                h.capture(dialog, "window-unequal-anova-level-error.png")
        dialog.controls[LEVEL][1].set("95")
        # A constant group is named with its field.
        dialog.controls["Response"][1].set("Flat")
        invalid(dialog, "Response", ("Group C", "zero variance", "Flat"))
        h.capture(dialog, "window-unequal-anova-variance-error.png")
        dialog.controls["Response"][1].set("Y")
        dialog.focus_field("Post-hoc")
        h.capture(dialog, "window-unequal-anova-options.png")

    app.show("result", 0)
    h.drive_dialog(h.dialog_type, configure)
    app.edit_analysis()
    h.wait()
    run = app.runs[0]
    assert run.options["Method"] == JOINT and run.options["Post-hoc"] == TAMHANE and run.options[LEVEL] == 95
    tables = run.result.tables
    report = tables["ANOVA"].set_index("Method")
    np.testing.assert_allclose(report.loc[WELCH_ROW, ["F", "F df2", "p"]].astype(float),
                               [13.87265332380859, 7.522026272909487, .0029937678909164205], rtol=1e-9)
    np.testing.assert_allclose(report.loc[BF_ROW, ["F", "F df2", "p"]].astype(float),
                               [18.744160177975527, 7.987949235106872, .0009619513866704031], rtol=1e-9)
    pairs = tables["Multiple comparisons"]
    np.testing.assert_allclose(pairs[["Difference", "Adjusted p", "CI low", "CI high"]].iloc[0].astype(float),
                               [-8.5, .006109005995430185, -13.748998409297613, -3.251001590702386], rtol=1e-9)
    app.show("result", 0)
    app.result_tabs.select(0)
    h.capture(root, "window-unequal-anova-omnibus.png")
    app.result_tabs.select(1)
    h.capture(root, "window-unequal-anova-tamhane.png")
    # Scroll to the simultaneous intervals on the right of the comparisons sheet.
    grid = app.result_tabs.nametowidget(app.result_tabs.select())
    grid.tree.xview_moveto(1)
    h.capture(root, "window-unequal-anova-tamhane-ci.png")
    grid.tree.xview_moveto(0)

    for sheet, name in ((0, "unequal-anova-omnibus.csv"), (1, "unequal-anova-tamhane.csv")):
        target = directory / name
        app.result_tabs.select(sheet)
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target)
        if sheet == 0:
            assert exported["Method"].tolist() == [WELCH_ROW, BF_ROW], exported
        else:
            assert {"CI low", "CI high", LEVEL, "Adjusted p"} <= set(exported.columns), exported.columns
            np.testing.assert_allclose(exported["CI low"], pairs["CI low"])

    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("result", 0))
    h.wait()
    reopened = app.runs[0]
    assert reopened.options["Method"] == JOINT and reopened.options[LEVEL] == 95
    for name in tables:
        pd.testing.assert_frame_equal(reopened.result.tables[name], tables[name])

    def expected(frame):
        return analyse(METHOD, frame, reopened.options).tables

    # Editing the source recalculates: A becomes 1, 2, 1, 3.
    app.show("data", TITLE)
    app.edit_cell(0, 1, "1")
    h.wait()
    edited = data.copy()
    edited.loc[0, "Y"] = 1.
    for name, table in expected(edited).items():
        pd.testing.assert_frame_equal(app.runs[0].result.tables[name], table)
    assert app.runs[0].result.tables["Multiple comparisons"]["Difference"].iloc[0] == -8.25
    # Excluding the last C value removes it from the comparisons.
    app.show("data", TITLE)
    app.current_grid.select((14, 1))
    app.toggle_exclusion()
    h.wait()
    masked = edited.copy()
    masked.loc[14, "Y"] = np.nan
    for name, table in expected(masked).items():
        pd.testing.assert_frame_equal(app.runs[0].result.tables[name], table)
    app.show("data", TITLE)
    app.current_grid.select((14, 1))
    app.toggle_exclusion()
    h.wait()

    # The Tamhane sheet becomes ordinary worksheet data.
    app.show("result", 0)
    app.result_tabs.select(1)
    app.use_result_as_data()
    sheet = app.tables["Multiple comparisons"].raw
    assert sheet["Comparison"].tolist() == ["A − B", "A − C", "B − C"], sheet.columns.tolist()
    assert {"CI low", "CI high", LEVEL} <= set(sheet.columns)

    # Reopen the saved source and choose a comparison family in the same dialog.
    app.import_file(path)
    app.open_sheet(("result", 0))
    h.wait()

    def choose_family(dialog):
        dialog.controls["Post-hoc"][1].set(DUNNETT_T3)
        dialog.controls[FAMILY][1].set(VERSUS_CONTROL)
        invalid(dialog, CONTROL, ("observed group",))
        assert tuple(dialog.field_rows[CONTROL][1].cget("values")) == ("A", "B", "C")
        dialog.controls[CONTROL][1].set("B")
        dialog.controls[FAMILY][1].set(PAIRS)
        invalid(dialog, PAIRS, ("at least one pair",))
        picker = dialog.controls[PAIRS][1]
        for a, b in [("C", "A"), ("A", "B")]:
            picker.first.set(a)
            picker.second.set(b)
            picker.add_pair()
        dialog.controls[LEVEL][1].set("90")
        h.capture(dialog, "window-dunnett-t3-selected-pairs.png")

    h.drive_dialog(h.dialog_type, choose_family)
    app.edit_analysis()
    h.wait()
    selected = app.runs[0]
    assert selected.options[FAMILY] == PAIRS and selected.options[PAIRS] == [["C", "A"], ["A", "B"]]
    result = selected.result.tables["Multiple comparisons"]
    assert result["Method"].tolist() == [DUNNETT_T3, DUNNETT_T3]
    np.testing.assert_allclose(result["Adjusted p"], [.14827841066699868, .0029889071931038925], rtol=1e-9)
    assert result["Distribution df"].tolist() == [8, 6]
    app.show("result", 0)
    app.result_tabs.select(1)
    h.capture(root, "window-dunnett-t3-results.png")
    target = directory / "dunnett-t3.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    np.testing.assert_allclose(pd.read_csv(target)["Adjusted p"], result["Adjusted p"], rtol=1e-9)
    assert app.save()
    app.import_file(path)
    app.open_sheet(("result", 0))
    h.wait()
    pd.testing.assert_frame_equal(app.runs[0].result.tables["Multiple comparisons"], result)

    def choose_dunnett(dialog):
        dialog.controls["Method"][1].set("Ordinary")
        dialog.controls["Post-hoc"][1].set(DUNNETT)
        assert not dialog.field_rows[FAMILY][1].grid_info()
        assert dialog.field_rows[CONTROL][1].grid_info()
        dialog.controls[CONTROL][1].set("B")
        h.capture(dialog, "window-dunnett-control.png")

    h.drive_dialog(h.dialog_type, choose_dunnett)
    app.edit_analysis()
    h.wait()
    ordinary = app.runs[0]
    assert FAMILY not in ordinary.options
    comparisons = ordinary.result.tables["Multiple comparisons"]
    assert comparisons[["First", "Second"]].values.tolist() == [["B", "A"], ["B", "C"]]
    assert comparisons["Method"].tolist() == [DUNNETT, DUNNETT]
