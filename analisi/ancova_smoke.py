"""Desktop smoke check for ANCOVA with adjusted means (0.90).

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=ancova``) calls :func:`check_ancova`. Widgets are driven and
events are generated. This is not a native pointer session, and it does not prove a real Windows or DPI window.
The data are synthetic: the same three small tables as ``tests/data/ancova``.
"""
from copy import deepcopy
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
from tkinter import ttk

from . import ui_theme
from .ancova import ANCOVA
from .compare_lines import COMPARE_LINES
from .data import Dataset, save_project
from .i18n import active_language, set_language, ui
from .workbench import analyse

UNBALANCED, CROSSING, SEPARATED, TRACKED = "Unbalanced", "Crossing", "Separated", "Tracked"
MODEL, TESTS, MEANS, CONTRASTS, FITTED = ("ANCOVA model", "ANCOVA tests", "Adjusted means", "ANCOVA contrasts",
                                          "ANCOVA fitted")
SHEETS = [MODEL, TESTS, MEANS, CONTRASTS, FITTED]
NAN = np.nan


def _unbalanced():
    """Fifteen rows, twelve complete: a missing X, a missing Y and a missing group stay out of the fit."""
    return pd.DataFrame({
        "X": [0, 2, 1, 3, 4, 2, 3, 4, 4, 5, 5, 6, NAN, 2, 6],
        "Y": [4, 12, 6, 19, 17, 8, 12, 19, 12, 19, 23, 20, 20, NAN, 25],
        "Group": ["A", "B", "A", "C", "B", "A", "B", "C", "A", "B", "C", "B", "A", "C", None]}).astype(
            {"X": float, "Y": float})


def _crossing():
    return pd.DataFrame({"X": [0., 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
                         "Y": [8., 20, 13, 14, 15, 16, 16, 14, 20, 6, 24, 7],
                         "Group": ["Red", "Blue"] * 6})


def _separated():
    """Two groups whose X ranges do not meet; four rows each, so one X can be excluded and the fit survives."""
    return pd.DataFrame({"X": [0., 1, 2, 1.5, 5, 6, 7, 6.5], "Y": [0., 1, 4, 2.2, 9, 11, 10, 10.4],
                         "Group": list("AAAABBBB")})


def _button(dialog, text):
    pending = [dialog]
    while pending:
        widget = pending.pop()
        if isinstance(widget, ttk.Button) and widget.cget("text") == ui(text):
            return widget
        pending.extend(widget.winfo_children())
    raise AssertionError(text)


def _shown(dialog, field):
    """The field is gridded. A control on another page of the notebook is never mapped, so mapping says nothing."""
    return dialog.field_rows[field][1].winfo_manager() == "grid"


def _reachable(dialog, root, text):
    """The button is mapped and inside the application window."""
    button = _button(dialog, text)
    dialog.update_idletasks()
    assert button.winfo_ismapped(), text
    bounds = root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()
    end = button.winfo_rootx() + button.winfo_width(), button.winfo_rooty() + button.winfo_height()
    assert end[0] <= bounds[0] + 1 and end[1] <= bounds[1] + 1, (text, end, bounds, dialog.geometry(), root.geometry())
    return button


def check_ancova(root, app, directory, kit):
    directory = Path(directory)
    previous_geometry = root.geometry()
    language = active_language()
    width = min(1024, root.winfo_screenwidth() - 32)
    height = min(768, root.winfo_screenheight() - 100)
    root.geometry(f"{width}x{height}+12+12")
    try:
        set_language("en")
        _check(root, app, directory, kit)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _check(root, app, directory, kit):
    capture, pick, wait, errors = kit.capture, kit.pick_method, kit.wait_for_calculation, kit.errors
    messagebox, filedialog = kit.messagebox, kit.filedialog
    suffix = "-modern" if ui_theme.is_modern() else ""
    started = time.monotonic()
    timings = {}

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
        """Run ``action(dialog)`` on the next analysis dialog, then confirm (or cancel) it."""
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

    def reject(dialog, field, fragment):
        """The dialog refuses, stays open, names the field, moves the focus to it and keeps what was typed."""
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert fragment in message, (fragment, message)
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

    def edit_dialog(action, *, accept=True):
        holder = drive(action, accept=accept)
        app.edit_analysis()
        finish(holder)
        wait()
        assert not errors, errors

    def masked(title):
        return app.tables[title].frame(mask_excluded=True)

    def same_as_engine(index, title):
        """The worker reproduces a direct call of the engine on the same masked table, sheet by sheet."""
        run = app.runs[index]
        expected = analyse(ANCOVA, masked(title), run.options)
        assert list(run.result.tables) == list(expected.tables), (list(run.result.tables), list(expected.tables))
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], table, obj=name)
        return run.result.tables

    def columns(dialog, response="Y", covariate="X", group="Group"):
        for field, name in (("Response", response), ("Covariate", covariate), ("Group", group)):
            dialog.controls[field][1].set(name)

    def commit(widget, variable, value):
        variable.set(value)
        widget.focus_force()
        root.update()
        widget.event_generate("<Return>")
        root.update()

    path = directory / "ancova.alab"
    crossing_sheet = Dataset(_crossing())
    crossing_sheet.analyses.append((COMPARE_LINES, {"Input": "Long table", "X": "X", "Y": "Y", "Group": "Group"}))
    save_project(path, {UNBALANCED: Dataset(_unbalanced()), CROSSING: crossing_sheet,
                        SEPARATED: Dataset(_separated())})
    app.import_file(path)
    assert [run.method for run in app.runs] == [COMPARE_LINES]
    legacy_before = None
    app.show("data", UNBALANCED)
    root.update()

    # 1. Defaults on the unbalanced table, from Group Comparison; the dialog keeps its place at 1024×768.
    def defaults(dialog):
        pick(dialog, ANCOVA)
        groups = dialog.methods.item(dialog.methods.parent(next(
            item for item, method in dialog.method_by_item.items() if method == ANCOVA)), "text")
        assert groups == ui("Group Comparison"), groups
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
            ui("Variables"), ui("Model"), ui("Comparisons")]
        columns(dialog)
        assert dialog.controls["Slope model"][1].get() == "Common"
        assert dialog.controls["Reference domain"][1].get() == "Common range"
        assert dialog.controls["Comparisons"][1].get() == "All pairs"
        assert dialog.controls["Adjustment"][1].get() == "Holm"
        assert dialog.controls["Graph"][1].get() == "Fitted lines"
        assert float(dialog.controls["Confidence level (%)"][1].get()) == 95.0
        assert dialog.controls["Reference X"][1].get() == ""
        dialog.update_idletasks()
        assert not _shown(dialog, "Control group") and _shown(dialog, "Adjustment")
        assert dialog.winfo_reqwidth() <= 1024 and dialog.winfo_reqheight() <= 768, (
            dialog.winfo_reqwidth(), dialog.winfo_reqheight())
        for text in ("Run Analysis", "Cancel"):
            _reachable(dialog, root, text)
        for tab in ("Variables", "Model", "Comparisons"):
            dialog.fields.select([i for i in range(dialog.fields.index("end"))
                                  if dialog.fields.tab(i, "text") == ui(tab)][0])
            dialog.update_idletasks()
            _reachable(dialog, root, "Run Analysis")
            if tab == "Model":
                shot(dialog, "window-ancova-dialog.png")
        dialog.fields.select(0)

    began = time.monotonic()
    run_dialog(defaults)
    index = len(app.runs) - 1
    run = app.runs[index]
    timings["first analysis"] = time.monotonic() - began
    assert run.method == ANCOVA and run.title == UNBALANCED
    assert set(run.options) <= {"Response", "Covariate", "Group", "Slope model", "Reference X", "Reference domain",
                                "Comparisons", "Adjustment", "Confidence level (%)", "Graph"}, run.options
    assert run.options["Reference X"] is None and run.options["Slope model"] == "Common"
    tables = same_as_engine(index, UNBALANCED)
    assert list(tables) == SHEETS
    model = tables[MODEL].iloc[0]
    assert (model["N"], model["Groups"], model["Residual df"]) == (12, 3, 8)
    assert np.isclose(model["Reference X"], 3.25) and np.isclose(model["RSS"], 8.2329317269, rtol=1e-9)
    assert (model["Common lower"], model["Common upper"]) == (3, 4)
    contrast = tables[CONTRASTS].iloc[0]
    assert (contrast["First"], contrast["Second"]) == ("A", "B")
    assert np.isclose(contrast["Difference"], -3.6746987952, rtol=1e-9)
    holm = tables[CONTRASTS]
    assert (holm["Adjusted p"] >= holm["p"] - 1e-15).all()
    app.show("result", index)
    root.update()
    shot(root, "window-ancova-results.png")
    app.result_tabs.select(SHEETS.index(MEANS))
    root.update()
    shot(root, "window-ancova-means.png")


    def facecolor(collection):
        from matplotlib.colors import to_hex
        return to_hex(np.atleast_2d(collection.get_facecolor())[0])

    def artist(figure, gid):
        found = [item for item in figure.axes[0].get_children() if item.get_gid() == gid]
        assert len(found) == 1, (gid, len(found), sorted({i.get_gid() for i in figure.axes[0].get_children() if i.get_gid()}))
        return found[0]

    # 1b. The Inspector styles a group; a second change is cancelled with Escape and leaves nothing behind.
    app.show("graph", index)
    root.update()
    initial = {key: facecolor(artist(run.result.figure, f"ancova:points:text:{key}")) for key in "ABC"}
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None
    names = [item["name"] for item in panel.elements]
    assert {"Scatter · A (1)", "Scatter · B (1)", "Scatter · C (1)"} <= set(names), names
    assert panel.select_group("scatter:1:A")
    commit(panel.fields["color"]["widget"], panel.vars["element:color"], "#9b4174")
    assert panel.apply() is True
    assert run.style["series"]["scatter:1:A"]["color"] == "#9b4174" and app.dirty
    assert facecolor(artist(run.result.figure, "ancova:points:text:A")) == "#9b4174"
    confirmed = deepcopy(run.style)
    assert panel.select_group("scatter:1:B")
    commit(panel.fields["color"]["widget"], panel.vars["element:color"], "#112233")
    assert facecolor(artist(run.result.figure, "ancova:points:text:B")) == "#112233"
    shot(root, "window-ancova-inspector.png")
    panel.fields["color"]["widget"].focus_force()
    root.update()
    panel.fields["color"]["widget"].event_generate("<Escape>")
    root.update()
    assert app.inspector is None
    assert facecolor(artist(run.result.figure, "ancova:points:text:B")) == initial["B"]
    assert facecolor(artist(run.result.figure, "ancova:points:text:A")) == "#9b4174"
    assert run.style == confirmed and app.runs[index].style == confirmed
    shot(root, "window-ancova-fitted-lines.png")

    # 1c. A Reference X outside the common range is refused on its own field; the typed value stays and is corrected.
    def reference_error(dialog):
        dialog.controls["Reference X"][1].set("2")
        message = reject(dialog, "Reference X", "is outside the common Covariate range 3 to 4")
        assert "Allow extrapolation" in message
        shot(dialog, "window-ancova-error-reference.png")
        assert dialog.controls["Reference X"][1].get() == "2"
        dialog.controls["Reference X"][1].set("3,25")

    edit_dialog(reference_error)
    run = app.runs[index]
    assert run.options["Reference X"] == 3.25 and isinstance(run.options["Reference X"], float)
    assert run.style == confirmed, run.style
    same = same_as_engine(index, UNBALANCED)
    assert np.isclose(same[MODEL].iloc[0]["Reference X"], 3.25)

    # 2. Crossing lines: separate slopes, against the control Blue, Reference X = 2, 90 % intervals.
    app.show("data", CROSSING)

    def crossing(dialog):
        pick(dialog, ANCOVA)
        columns(dialog)
        dialog.controls["Slope model"][1].set("By group")
        dialog.controls["Comparisons"][1].set("Against control")
        dialog.update_idletasks()
        control = dialog.field_rows["Control group"][1]
        assert _shown(dialog, "Control group") and _shown(dialog, "Adjustment")
        assert tuple(control["values"]) == ("Red", "Blue"), control["values"]
        reject(dialog, "Control group", "Choose the control group")
        dialog.controls["Control group"][1].set("Blue")
        dialog.controls["Reference X"][1].set("2")
        dialog.controls["Confidence level (%)"][1].set("90")
        dialog.controls["Adjustment"][1].set("None")

    run_dialog(crossing)
    cross = len(app.runs) - 1
    run = app.runs[cross]
    assert run.options["Control group"] == "Blue" and run.options["Confidence level (%)"] == 90.0
    tables = same_as_engine(cross, CROSSING)
    row = tables[CONTRASTS].iloc[0]
    assert (row["First"], row["Second"]) == ("Red", "Blue") and len(tables[CONTRASTS]) == 1
    assert np.isclose(row["Difference"], 43 / 105, rtol=1e-9) and row["Lower"] < 0 < row["Upper"]
    assert row["Adjusted p"] == row["p"]
    equal_slopes = tables[TESTS].set_index("Test").loc["Equal slopes"]
    assert np.isclose(equal_slopes["F"], 66.7146268657, rtol=1e-9) and (equal_slopes["Numerator df"],
                                                                         equal_slopes["Denominator df"]) == (1, 8)
    rss_at_two = tables[MODEL].iloc[0]["RSS"]

    app.show("graph", cross)
    edit_dialog(lambda dialog: dialog.controls["Reference X"][1].set("4"))
    run = app.runs[cross]
    assert run.options["Reference X"] == 4.0 and run.options["Control group"] == "Blue"
    tables = same_as_engine(cross, CROSSING)
    row = tables[CONTRASTS].iloc[0]
    assert np.isclose(row["Difference"], 1201 / 105, rtol=1e-9) and 0 < row["Lower"]
    assert np.isclose(tables[MODEL].iloc[0]["RSS"], rss_at_two, rtol=1e-12), "the fit is the same at any reference"
    assert np.isclose(tables[TESTS].set_index("Test").loc["Equal slopes", "F"], 66.7146268657, rtol=1e-9)

    # The three views, one numeric check in each.
    means = tables[MEANS]
    assert means["Group"].tolist() == ["Red", "Blue"] and (means["Reference X"] == 4).all()
    lines = artist(run.result.figure, "ancova:mean:text:Red")
    assert np.allclose(lines.get_offsets(), [[4, means.loc[0, "Mean"]]])
    shot(root, "window-ancova-fitted-reference-4.png")
    for view in ("Adjusted means", "Residuals"):
        edit_dialog(lambda dialog, view=view: dialog.controls["Graph"][1].set(view))
        run = app.runs[cross]
        assert run.options["Graph"] == view
        tables = same_as_engine(cross, CROSSING)
        figure = run.result.figure
        assert len(figure.axes) == 1
        app.show("graph", cross)
        root.update()
        if view == "Adjusted means":
            axes = figure.axes[0]
            assert [label.get_text() for label in axes.get_xticklabels()] == ["Red", "Blue"]
            for number, group in enumerate(("Red", "Blue")):
                point = artist(figure, f"ancova:mean:text:{group}")
                assert np.allclose(point.get_offsets(), [[number, tables[MEANS].loc[number, "Mean"]]]), group
            assert "ancova:warning" not in {item.get_gid() for item in axes.get_children()}
            shot(root, "window-ancova-adjusted-means.png")
        else:
            axes = figure.axes[0]
            points = np.concatenate([artist(figure, f"ancova:residuals:text:{group}").get_offsets()
                                     for group in ("Red", "Blue")])
            assert np.allclose(np.sort(points[:, 1]), np.sort(tables[FITTED]["Residual"].to_numpy()))
            assert abs(points[:, 1].sum()) < 1e-9 and np.allclose(artist(figure, "ancova:zero").get_ydata(), 0)
            shot(root, "window-ancova-residuals.png")

    # 3. Separated supports: the common range is empty, the opt-in extrapolates, and a bad recalculation stays visible.
    app.show("data", SEPARATED)

    def support(dialog):
        pick(dialog, ANCOVA)
        columns(dialog)
        dialog.controls["Comparisons"][1].set("None")
        dialog.update_idletasks()
        assert not _shown(dialog, "Adjustment") and not _shown(dialog, "Control group")
        message = reject(dialog, "Reference domain", "share no Covariate range")
        assert "Allow extrapolation" in message
        shot(dialog, "window-ancova-error-support.png")
        dialog.controls["Reference domain"][1].set("Allow extrapolation")
        dialog.controls["Reference X"][1].set("3")

    run_dialog(support)
    separated = len(app.runs) - 1
    run = app.runs[separated]
    assert run.options["Reference domain"] == "Allow extrapolation" and "Adjustment" not in run.options
    tables = same_as_engine(separated, SEPARATED)
    assert CONTRASTS not in tables and tables[MEANS]["Extrapolated"].tolist() == [True, True]
    assert tables[MODEL].iloc[0]["Common lower"] > tables[MODEL].iloc[0]["Common upper"]
    assert {"ancova:extension:text:A", "ancova:extension:text:B"} <= {
        item.get_gid() for item in run.result.figure.axes[0].get_children()}
    legend = [text.get_text() for text in run.result.figure.axes[0].get_legend().get_texts()]
    assert "Extrapolated to the reference" in legend, legend
    app.show("graph", separated)
    root.update()
    shot(root, "window-ancova-extrapolated-lines.png")
    app.show("graph", separated)
    edit_dialog(lambda dialog: dialog.controls["Graph"][1].set("Adjusted means"))
    run = app.runs[separated]
    note = artist(run.result.figure, "ancova:warning").get_text()
    assert note == "Extrapolated (open markers): A, B", note
    app.show("graph", separated)
    root.update()
    shot(root, "window-ancova-extrapolation-note.png")

    # An edit, an exclusion, then a calculation that cannot be done: the old result stays and says it is stale.
    app.show("data", SEPARATED)
    columns_of = list(app.tables[SEPARATED].raw.columns)
    x_column, y_column = columns_of.index("X"), columns_of.index("Y")
    means_before = app.runs[separated].result.tables[MEANS]["Mean"].to_numpy().copy()
    app.edit_cell(3, y_column, "3")
    wait()
    after = same_as_engine(separated, SEPARATED)
    assert after[FITTED].set_index("Source row").loc[3, "Observed"] == 3 and len(after[FITTED]) == 8
    assert not np.allclose(after[MEANS]["Mean"], means_before), "a changed Y changes the adjusted means"
    app.show("data", SEPARATED)
    app.current_grid.select((3, x_column))
    app.toggle_exclusion()
    wait()
    after = same_as_engine(separated, SEPARATED)
    assert 3 not in set(after[FITTED]["Source row"]) and after[MODEL].iloc[0]["N"] == 7
    kept = app.runs[separated].result
    assert app.runs[separated].calculation_error is None
    seen = {}

    def reopened(dialog):
        seen["field"] = dialog.focus_get() is dialog.field_rows["Group"][1]
        seen["banner"] = dialog.error
        seen["kept"] = (dialog.controls["Reference X"][1].get(), dialog.controls["Reference domain"][1].get(),
                        dialog.controls["Comparisons"][1].get())
        shot(dialog, "window-ancova-recovery.png")

    holder = drive(reopened, accept=False)
    app.show("data", SEPARATED)
    app.current_grid.select((0, x_column))
    app.toggle_exclusion()
    wait()
    finish(holder)
    wait()
    assert seen["field"], seen
    assert 'Group "A" has 2 complete observations' in seen["banner"] and "Group" in seen["banner"], seen
    assert seen["kept"] == ("3.0", "Allow extrapolation", "None"), seen
    stale = app.runs[separated]
    assert stale.result is kept and stale.calculation_error and "2 complete observations" in stale.calculation_error
    app.show("result", separated)
    root.update()
    note = app.stale_calculation_note()
    assert note and "2 complete observations" in note, note
    assert app.runs[separated].result.tables[MODEL].iloc[0]["N"] == 7
    shot(root, "window-ancova-stale.png")
    # The calculation is refused to leave the page unchanged: export asks for a current result.
    with patch.object(filedialog, "asksaveasfilename", return_value=str(directory / "stale.csv")):
        app.export()
    assert errors and "complete observations" in errors[-1], errors
    errors.clear()
    app.show("data", SEPARATED)
    app.current_grid.select((0, x_column))
    app.toggle_exclusion()
    wait()
    fixed = app.runs[separated]
    assert fixed.calculation_error is None and fixed.result is not kept
    assert same_as_engine(separated, SEPARATED)[MODEL].iloc[0]["N"] == 7
    app.show("result", separated)
    assert app.stale_calculation_note() is None
    assert not errors, errors
    timings["parts 1 to 3"] = time.monotonic() - started

    # 4. Save, reopen the graph first and the sheets after, export every format, reuse the means as data.
    app.show("data", UNBALANCED)
    assert app.save()
    app.import_file(app.path)
    assert sorted(run.method for run in app.runs) == sorted([COMPARE_LINES, ANCOVA, ANCOVA, ANCOVA])
    assert all(run.result is None for run in app.runs)
    where = {run.title: position for position, run in enumerate(app.runs) if run.method == ANCOVA}
    legacy_at = next(position for position, run in enumerate(app.runs) if run.method == COMPARE_LINES)
    assert set(where) == {UNBALANCED, CROSSING, SEPARATED}, where
    first, second, third = where[UNBALANCED], where[CROSSING], where[SEPARATED]
    saved_options = {position: deepcopy(app.runs[position].options) for position in (first, second, third)}
    assert saved_options[first]["Reference X"] == 3.25 and saved_options[second]["Control group"] == "Blue"
    assert saved_options[second]["Graph"] == "Residuals" and saved_options[third]["Graph"] == "Adjusted means"
    app.open_sheet(("graph", first))
    wait()
    reopened = app.runs[first]
    assert reopened.options == saved_options[first]
    assert reopened.style["series"]["scatter:1:A"]["color"] == "#9b4174" and "scatter:1:B" not in reopened.style["series"]
    assert facecolor(artist(reopened.result.figure, "ancova:points:text:A")) == "#9b4174"
    assert facecolor(artist(reopened.result.figure, "ancova:points:text:B")) == initial["B"]
    same_as_engine(first, UNBALANCED)
    root.update()
    shot(root, "window-ancova-reopened-graph.png")
    app.open_sheet(("result", first))
    wait()
    assert list(app.runs[first].result.tables) == SHEETS
    for position, title in ((second, CROSSING), (third, SEPARATED)):
        app.open_sheet(("result", position))
        wait()
        assert app.runs[position].options == saved_options[position]
        same_as_engine(position, title)
    assert app.runs[second].result.tables[MEANS]["Reference X"].tolist() == [4.0, 4.0]
    # The recipe that existed before ANCOVA still opens and gives its own sheets.
    app.open_sheet(("result", legacy_at))
    wait()
    legacy = app.runs[legacy_at].result.tables
    assert list(legacy) == ["Regression lines", "Line comparison", "Summary"], list(legacy)
    assert np.allclose(legacy["Regression lines"]["Slope"], [102 / 35, -2.6])

    app.show("graph", first)
    for extension, marker in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = directory / f"ancova.{extension}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, extension
        assert marker in target.read_bytes()[:400], extension
    app.show("result", first)
    app.result_tabs.select(SHEETS.index(MEANS))
    csv_path = directory / "ancova-adjusted-means.csv"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    exported = exported.drop(columns=[name for name in exported.columns if str(name).startswith("Unnamed")])
    assert exported["Group"].tolist() == ["A", "B", "C"]
    assert np.allclose(exported["Mean"], app.runs[first].result.tables[MEANS]["Mean"])
    before_tables = set(app.tables)
    app.result_tabs.select(SHEETS.index(MEANS))
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert added == {MEANS}, added
    reused = app.tables[MEANS].raw
    assert list(reused.columns) == list(app.runs[first].result.tables[MEANS].columns)
    assert reused["Group"].tolist() == ["A", "B", "C"]
    assert np.allclose(reused["Mean"].astype(float), app.runs[first].result.tables[MEANS]["Mean"])
    assert not errors, errors
    timings["part 4"] = time.monotonic() - started

    def large_screen(tag):
        """Screens that are large enough also show the 1600×1000 window, in the current language."""
        if not (root.winfo_screenwidth() >= 1680 and root.winfo_screenheight() >= 1050):
            print("ancova smoke: the 1600×1000 phase needs a screen of at least 1680×1050 and was skipped.")
            return
        root.geometry("1600x1000+0+0")
        root.update()
        for view, name in ((second, "residuals"), (third, "adjusted-means")):
            app.show("graph", view)
            root.update()
            shot(root, f"window-ancova-{name}-1600{tag}.png")

        def wide(dialog):
            pick(dialog, ANCOVA)
            columns(dialog)
            dialog.controls["Comparisons"][1].set("Against control")
            for tab in range(dialog.fields.index("end")):
                dialog.fields.select(tab)
                dialog.update_idletasks()
                for text in ("Run Analysis", "Cancel"):
                    _reachable(dialog, root, text)
            shot(dialog, f"window-ancova-dialog-1600{tag}.png")
            dialog.result = None

        holder = drive(wide, accept=False)
        app.show("data", CROSSING)
        app.choose_analysis()
        finish(holder)
        assert not errors, errors
        root.geometry("1024x768+0+0")
        root.update()

    large_screen("")

    # 5. Italian: captions, canonical recipe values, errors on their field, decimal comma and the three views.
    set_language("it")
    app.show("data", CROSSING)

    def italian(dialog):
        pick(dialog, ANCOVA)
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
            "Variabili", "Modello", "Confronti"]
        assert dialog.heading.cget("text") == "ANCOVA (medie aggiustate)"
        assert dialog.field_rows["Covariate"][0].cget("text") == "Covariata"
        assert dialog.field_rows["Reference X"][0].cget("text") == "X di riferimento"
        columns(dialog)
        slope = dialog.field_rows["Slope model"][1]
        assert list(slope["values"]) == ["Comune", "Per gruppo"], slope["values"]
        slope.set("Per gruppo")
        assert dialog.controls["Slope model"][1].get() == "By group"
        modes = dialog.field_rows["Comparisons"][1]
        assert list(modes["values"]) == ["Tutte le coppie", "Contro il controllo", "Nessuno"], modes["values"]
        modes.set("Contro il controllo")
        assert dialog.controls["Comparisons"][1].get() == "Against control"
        dialog.update_idletasks()
        assert _shown(dialog, "Control group")
        assert list(dialog.field_rows["Adjustment"][1]["values"]) == ["Holm", "Bonferroni", "Nessuno"]
        assert list(dialog.field_rows["Graph"][1]["values"]) == ["Rette adattate", "Medie aggiustate", "Residui"]
        message = reject(dialog, "Control group", "Scegli il gruppo di controllo")
        assert "Contro il controllo" in message
        dialog.controls["Control group"][1].set("Blue")
        dialog.controls["Reference X"][1].set("9")
        message = reject(dialog, "Reference X", "fuori dall’intervallo comune della covariata, da 0 a 5")
        assert message.startswith("X di riferimento: ") or "L’X di riferimento 9" in message, message
        shot(dialog, "window-ancova-error-it.png")
        assert dialog.controls["Reference X"][1].get() == "9"
        dialog.controls["Reference X"][1].set("2,5")
        dialog.field_rows["Graph"][1].set("Medie aggiustate")
        dialog.controls["Confidence level (%)"][1].set("99,5")
        dialog.fields.select(1)
        dialog.update_idletasks()
        _reachable(dialog, root, "Run Analysis")
        shot(dialog, "window-ancova-dialog-it.png")

    run_dialog(italian)
    italian_run = app.runs[-1]
    assert italian_run.options == {
        "Response": "Y", "Covariate": "X", "Group": "Group", "Slope model": "By group", "Reference X": 2.5,
        "Reference domain": "Common range", "Comparisons": "Against control", "Control group": "Blue",
        "Adjustment": "Holm", "Confidence level (%)": 99.5, "Graph": "Adjusted means"}, italian_run.options
    italian_tables = same_as_engine(len(app.runs) - 1, CROSSING)
    assert np.isclose(italian_tables[MODEL].iloc[0]["Reference X"], 2.5)
    app.show("graph", len(app.runs) - 1)
    root.update()
    axes = italian_run.result.figure.axes[0]
    assert axes.get_title() == "ANCOVA adjusted means", "the figure keeps the language of the engine's canonical text"
    assert axes.get_ylabel() == "Adjusted mean of Y" and [t.get_text() for t in axes.get_xticklabels()] == ["Red", "Blue"]
    shot(root, "window-ancova-adjusted-means-it.png")
    app.show("result", len(app.runs) - 1)
    app.result_tabs.select(SHEETS.index(TESTS))
    root.update()
    shot(root, "window-ancova-tests-it.png")
    # The stale indication is shown in the language of the interface.
    stale_run = app.runs[third]
    stale_run.calculation_error = 'Group "A" has 2 complete observations. Each group needs at least 3.'
    app.show("result", third)
    root.update()
    note = app.stale_calculation_note()
    assert note and "2 osservazioni complete" in note, note
    stale_run.calculation_error = None
    large_screen("-it")
    set_language("en")

    assert not errors, errors
    timings["total"] = time.monotonic() - started
    print(f"ancova smoke{suffix}: {timings['total']:.1f} s of driven work "
          f"(first analysis {timings['first analysis']:.2f} s, parts 1-3 {timings['parts 1 to 3']:.1f} s, "
          f"part 4 {timings['part 4'] - timings['parts 1 to 3']:.1f} s)")
