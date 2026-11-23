"""Desktop smoke check for the Greenhouse–Geisser correction of two within-subject factors (0.93).

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=rm-two-way-sphericity``) calls
:func:`check_rm_two_way_sphericity`. It drives the real dialog of Repeated measures ANOVA: the choice and its
note, the field errors that keep the dialog open, the fractional degrees of freedom on the result sheet, the
``Sphericity`` sheet, an excluded cell, save and reopen, Use Result as Data, the Italian wording and the
saved one-way recipe. Sheet names and recipe values stay canonical English whatever the language is.

The window is 1600 × 1000 when the screen has room for it and 1024 × 768 otherwise; the compact dialog is
always checked at 1024 × 768 as well. The synthetic data are a 5 subjects × 3 visits × 3 conditions matrix.
"""
import os
import time
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats
from scipy.linalg import helmert

from .data import Dataset, load_project, save_project
from .i18n import active_language, set_language, ui
from .rm_sphericity import CANONICAL, FIELD, HF, LEGACY, LOWER, METHOD, NONE, SHEET

TITLE, ONE_WAY = "Visits", "Visits one-way"
VISIT, CONDITION = "Visit", "Condition"
# Rows are subjects, columns are visit 1 condition 1, 2, 3, visit 2 condition 1, ...
MATRIX = np.array([
    [33, 37, 39, 39, 40, 46, 42, 46, 49],
    [37, 36, 43, 37, 44, 45, 45, 47, 51],
    [41, 44, 43, 44, 45, 48, 47, 47, 54],
    [29, 34, 37, 32, 42, 43, 41, 40, 47],
    [38, 43, 45, 40, 45, 50, 50, 51, 53]], dtype=float)
# Greenhouse–Geisser epsilons of the matrix from an independent Helmert/Kronecker calculation (tests/).
EPSILON = {VISIT: 0.9794908417346871, CONDITION: 0.5676776912068693, f"{VISIT}:{CONDITION}": 0.6465819122309571}
CONTRAST_DIMENSION = {VISIT: 2, CONDITION: 2, f"{VISIT}:{CONDITION}": 4}
SUBJECTS = 5
INCOMPLETE = {"en": "has no measurement for Visit = Visit 1; Condition = Condition 2",
              "it": "non ha una misura per Visit = Visit 1; Condition = Condition 2"}
LEGACY_TWO_WAY = {"Response": "Response", "Factors": [VISIT, CONDITION], "Subject": "Participant", FIELD: NONE}
LEGACY_ONE_WAY = {"Response": "Response", "Factors": [VISIT], "Subject": "Participant", FIELD: LEGACY}
# Expected controls and tabs of the sibling ANOVA dialogs, including the integrated sums-of-squares choice.
SIBLINGS = {
    "One-way ANOVA": (
        [
            "Response", "Group", "Distribution", "Method", "Post-hoc", "Comparison family", "Control group",
            "Selected pairs", "Ratio direction", "Confidence level (%)", "Linear trend", "Trend group order",
            "Brown–Forsythe variance test", "Bartlett variance test", "Variance test alpha"
        ],
        ["Variables", "Options", "Diagnostics/Assumptions"]),
    "Multifactor ANOVA": (
        [
            "Response", "Factors", "Term selection", "Interaction order", "Sums of squares", "Model terms",
            "Compare marginal means by", "Cell comparison factors", "Within factors (simple effects)",
            "Control level(s), separated by |", "Families", "Reverse comparisons", "Correction",
            "Effect sizes", "Alpha", "ANOVA residual diagnostics", "ANOVA assumption tests", "ANOVA assumption tests included",
            "ANOVA diagnostic alpha", "ANOVA diagnostic graph", "ANOVA Q–Q reference line"
        ],
        ["Variables", "Model", "Options", "Effect sizes", "Diagnostics"]),
    "Mixed-effects model (REML)": (
        [
            "Input format", "Y", "Subject", "Within factors", "Between factors", "Measurement columns",
            "Row labels", "Repeat across", "Subject IDs", "Denominator method", "Post-hoc",
            "Comparison factor", "Condition on factors", "Comparison families"
        ],
        ["Variables", "Options"]),
}


def _long(matrix=MATRIX):
    """The matrix as one row per measurement. ``Participant`` is clean; ``Subject`` has one mistyped label."""
    rows = [{"Subject": f"S{subject}", "Participant": f"P{subject}", VISIT: f"Visit {cell // 3 + 1}",
             CONDITION: f"Condition {cell % 3 + 1}", "Response": value}
            for subject, values in enumerate(matrix, start=1) for cell, value in enumerate(values)]
    frame = pd.DataFrame(rows)
    frame.loc[1, "Subject"] = "S6"   # a typo: S1 loses Visit 1 / Condition 2 and a sixth subject appears
    return frame


def _one_way():
    cube = MATRIX.reshape(SUBJECTS, 3, 3).mean(axis=2)
    return pd.DataFrame([{"Participant": f"P{subject}", VISIT: f"Visit {visit + 1}", "Response": value}
                         for subject, row in enumerate(cube, start=1) for visit, value in enumerate(row)])


def reference():
    """SS, F and the corrected p of every effect from plain numpy sums, with the frozen epsilons."""
    cube = MATRIX.reshape(SUBJECTS, 3, 3)
    n, a, b = cube.shape
    grand = cube.mean()
    subject, visit, cond = cube.mean(axis=(1, 2)), cube.mean(axis=(0, 2)), cube.mean(axis=(0, 1))
    cell, sv, sc = cube.mean(axis=0), cube.mean(axis=2), cube.mean(axis=1)
    ss = {VISIT: n * b * ((visit - grand) ** 2).sum(), CONDITION: n * a * ((cond - grand) ** 2).sum()}
    ss[f"{VISIT}:{CONDITION}"] = n * ((cell - visit[:, None] - cond[None, :] + grand) ** 2).sum()
    error = {VISIT: b * ((sv - subject[:, None] - visit[None, :] + grand) ** 2).sum(),
             CONDITION: a * ((sc - subject[:, None] - cond[None, :] + grand) ** 2).sum()}
    interaction = (cube - cell[None] - sv[:, :, None] - sc[:, None, :] + subject[:, None, None]
                   + visit[None, :, None] + cond[None, None, :] - grand)
    error[f"{VISIT}:{CONDITION}"] = (interaction ** 2).sum()
    dfs = {VISIT: a - 1, CONDITION: b - 1, f"{VISIT}:{CONDITION}": (a - 1) * (b - 1)}
    out = {}
    for term, df in dfs.items():
        statistic = (ss[term] / df) / (error[term] / ((n - 1) * df))
        epsilon = EPSILON[term]
        out[term] = {"SS": ss[term], "df": df, "F": statistic, "epsilon": epsilon,
                     "df1": df * epsilon, "df2": (n - 1) * df * epsilon,
                     "p": stats.f.sf(statistic, df * epsilon, (n - 1) * df * epsilon),
                     "uncorrected": stats.f.sf(statistic, df, (n - 1) * df)}
    return out


def check_rm_two_way_sphericity(root, app, directory, kit):
    from tkinter import filedialog, messagebox, ttk

    capture, pick, select = kit.capture, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_language = active_language()
    previous_geometry = root.geometry()
    local_errors = []
    start = previous_language if previous_language in ("en", "it") else "en"
    set_language(start)
    words = {"en": {"incomplete": INCOMPLETE["en"], "caption": "Sphericity correction"},
             "it": {"incomplete": INCOMPLETE["it"], "caption": "Correzione della sfericità"}}[start]
    expected = reference()
    screen_wide = root.winfo_screenwidth() >= 1680 and root.winfo_screenheight() >= 1050
    geometry = "1600x1000+0+0" if screen_wide else "1024x768+0+0"
    if not screen_wide:
        print("rm-two-way-sphericity: the 1600×1000 phase is skipped, the screen is smaller than 1680×1050 "
              f"({root.winfo_screenwidth()}×{root.winfo_screenheight()}); the flow runs at 1024×768.", flush=True)

    def find(kind, parent=None):
        for child in (parent or root).winfo_children():
            if isinstance(child, kind):
                return child
            found = find(kind, child)
            if found is not None:
                return found
        return None

    def drive(action, *, accept):
        def enter(tries=0):
            dialog = find(kit.AnalysisDialog)
            if dialog is None or not dialog.winfo_viewable():
                if tries < 200:
                    root.after(40, lambda: enter(tries + 1))
                    return
                local_errors.append("AnalysisDialog did not open")
                return
            try:
                dialog.update_idletasks()
                action(dialog)
                if dialog.winfo_exists():
                    dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                local_errors.append(f"{error!r}\n{traceback.format_exc()}")
                if dialog.winfo_exists():
                    try:
                        dialog.result = None
                        dialog.cancel()
                    except Exception:
                        pass

        root.after(80, enter)

    def when_open(action, *, accept):
        state = {"done": False}

        def enter(tries=0):
            dialog = find(kit.AnalysisDialog)
            if dialog is None:
                if tries > 1200:
                    local_errors.append("the recovered AnalysisDialog did not open")
                    state["done"] = True
                    return
                root.after(25, lambda: enter(tries + 1))
                return
            try:
                dialog.update()
                action(dialog)
                if dialog.winfo_exists():
                    dialog.ok() if accept else dialog.cancel()
            except Exception as error:
                local_errors.append(f"{error!r}\n{traceback.format_exc()}")
                if dialog.winfo_exists():
                    dialog.result = None
                    dialog.cancel()
            state["done"] = True

        root.after(25, enter)
        return state

    def settle(state):
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "the recovered analysis did not finish"
            root.update()
            time.sleep(0.02)
        assert not local_errors, local_errors

    def choose(dialog, subject, correction=None):
        pick(dialog, METHOD)
        dialog.controls["Response"][1].set("Response")
        select(dialog, "Factors", {VISIT, CONDITION})
        dialog.update()
        dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
        dialog.controls["Subject"][1].set(subject)
        if correction is not None:
            dialog.controls[FIELD][1].set(correction)
        dialog.update()

    def options_page(dialog):
        return dialog.field_rows[FIELD][0].master

    def buttons(dialog):
        """The dialog fits the screen and its Run Analysis and Cancel buttons are mapped."""
        dialog.update_idletasks()
        found = []
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found.append(str(widget.cget("text")))
                    assert widget.winfo_ismapped() and widget.winfo_viewable(), widget.cget("text")
        assert ui("Run Analysis") in found and ui("Cancel") in found, found
        assert dialog.winfo_rooty() + dialog.winfo_height() <= dialog.winfo_screenheight(), "the dialog is cut off"
        assert dialog.winfo_rootx() + dialog.winfo_width() <= dialog.winfo_screenwidth(), "the dialog is cut off"

    def reachable(dialog):
        """The choice and its note sit inside the visible part of the Options page."""
        dialog.fields.select(options_page(dialog))
        dialog.update()
        for widget in (dialog.field_rows[FIELD][1], dialog.sphericity_note):
            assert widget.winfo_viewable() and widget.winfo_ismapped(), widget
            assert widget.winfo_rooty() + widget.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height(), widget
        dialog.field_rows[FIELD][1].focus_force()
        dialog.update()
        assert dialog.focus_get() is dialog.field_rows[FIELD][1], dialog.focus_get()

    def reject(dialog, snippet, *, field="Subject"):
        with patch.object(messagebox, "showerror") as shown:
            dialog.ok()
        assert shown.called, snippet
        message = shown.call_args.args[1]
        assert snippet in message, message
        assert dialog.winfo_exists() and dialog.result is None
        dialog.update()
        assert dialog.fields.tab(dialog.fields.select(), "text") == ui("Variables")
        assert dialog.focus_get() is dialog.field_rows[field][1], (dialog.focus_get(), field)
        return message

    def result_grid(run_index, sheet):
        app.show("result", run_index)
        names = list(app.runs[run_index].result.tables)
        app.result_tabs.select(names.index(sheet))
        root.update()
        return app.result_tabs.nametowidget(app.result_tabs.select())

    def displayed(grid, column):
        """Text shown in one column of a result sheet, by row label."""
        position = list(grid.frame.columns).index(column)
        return {grid.cells.cell_text(row, 0): grid.cells.cell_text(row, position + 1)
                for row in range(len(grid.cells.frame))}

    def check_two_way(run, *, corrected):
        """SS, F, error strata, epsilon and p of the run against plain numpy sums and the frozen epsilons."""
        tables, subject = run.result.tables, run.options["Subject"]
        assert list(tables) == (["ANOVA", SHEET] if corrected else ["ANOVA"]), list(tables)
        anova = tables["ANOVA"]
        assert list(anova.index) == [subject, VISIT, f"{subject}:{VISIT}", CONDITION, f"{subject}:{CONDITION}",
                                     f"{VISIT}:{CONDITION}", f"{subject}:{VISIT}:{CONDITION}"], list(anova.index)
        for term, ref in expected.items():
            row = anova.loc[term]
            assert np.isclose(row["SS"], ref["SS"], rtol=1e-10), (term, row["SS"], ref["SS"])
            assert np.isclose(row["F"], ref["F"], rtol=1e-10), (term, row["F"], ref["F"])
            assert int(row["df"]) == ref["df"], term
            if corrected:
                assert np.isclose(row["GG ε"], ref["epsilon"], rtol=1e-12), (term, row["GG ε"])
                assert np.isclose(row["F df1"], ref["df1"], rtol=1e-12) and np.isclose(row["F df2"], ref["df2"],
                                                                                        rtol=1e-12), term
                assert np.isclose(row["p"], ref["p"], rtol=1e-9), (term, row["p"], ref["p"])
            else:
                assert "GG ε" not in anova.columns
                assert row["F df1"] == ref["df"] and row["F df2"] == (SUBJECTS - 1) * ref["df"], term
                assert np.isclose(row["p"], ref["uncorrected"], rtol=1e-9), (term, row["p"])
        if corrected:
            sheet = tables[SHEET].set_index("Term")
            assert list(sheet.index) == list(expected), list(sheet.index)
            for term, ref in expected.items():
                assert int(sheet.loc[term, "Contrast dimension"]) == CONTRAST_DIMENSION[term]
                assert np.isclose(sheet.loc[term, "Uncorrected p"], ref["uncorrected"], rtol=1e-9), term
                assert sheet.loc[term, "p"] >= sheet.loc[term, "Uncorrected p"] - 1e-15, term

    def sibling_dialog(method):
        """Control captions and tab names of another ANOVA dialog, opened in the same app."""
        found = []

        def inspect(dialog):
            pick(dialog, method)
            dialog.update()
            found.append((list(dialog.controls), [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]))
            assert FIELD not in dialog.controls and dialog.sphericity_note is None, method

        drive(inspect, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        return found[0]

    try:
        root.geometry("1024x768+0+0")
        root.update_idletasks()
        before = directory / "rm-sphericity-before.alab"
        save_project(before, {
            TITLE: Dataset(_long(), analyses=[(METHOD, dict(LEGACY_TWO_WAY))]),
            ONE_WAY: Dataset(_one_way(), analyses=[(METHOD, dict(LEGACY_ONE_WAY))])})
        app.import_file(before)

        # --- Saved recipes: no correction, and the one-way spelling of before the change. Same tables as ever.
        app.open_sheet(("result", 0))
        wait()
        legacy = app.runs[0]
        assert legacy.options == LEGACY_TWO_WAY
        check_two_way(legacy, corrected=False)
        legacy_two_way = legacy.result.tables["ANOVA"].copy()
        app.open_sheet(("result", 1))
        wait()
        one_way = app.runs[1]
        assert one_way.options == LEGACY_ONE_WAY
        assert list(one_way.result.tables) == ["ANOVA"] and "GG ε" in one_way.result.tables["ANOVA"].columns
        legacy_one_way = one_way.result.tables["ANOVA"].copy()
        scores = MATRIX.reshape(SUBJECTS, 3, 3).mean(axis=2) @ helmert(3).T
        covariance = np.cov(scores, rowvar=False, ddof=1)
        one_way_epsilon = np.trace(covariance) ** 2 / (2 * np.trace(covariance @ covariance))
        assert np.isclose(legacy_one_way.loc[VISIT, "GG ε"], one_way_epsilon, rtol=1e-12), legacy_one_way
        assert np.isclose(legacy_one_way.loc[VISIT, "p"], stats.f.sf(
            legacy_one_way.loc[VISIT, "F"], 2 * one_way_epsilon, 8 * one_way_epsilon), rtol=1e-9)

        # --- The sibling ANOVA dialogs do not change.
        app.show("data", TITLE)
        for method, (labels, tabs) in SIBLINGS.items():
            found = sibling_dialog(method)
            assert found == (labels, [ui(tab) for tab in tabs]), (method, found)

        # --- Compact dialog at 1024 × 768: the choice, its note and the buttons are reachable.
        def compact(dialog):
            pick(dialog, METHOD)
            assert dialog.controls[FIELD][1].get() == NONE
            assert dialog.choice_bindings[FIELD].values == (NONE, CANONICAL, HF, LOWER)
            assert dialog.sphericity_note.cget("text") and "omnibus" not in dialog.sphericity_note.cget("text")
            dialog.controls[FIELD][1].set(CANONICAL)
            dialog.update()
            assert "omnibus" in dialog.sphericity_note.cget("text"), dialog.sphericity_note.cget("text")
            for choice, phrase in ((HF, "Huynh–Feldt estimates"), (LOWER, "most conservative")):
                dialog.controls[FIELD][1].set(choice)
                dialog.update()
                assert phrase in dialog.sphericity_note.cget("text"), (choice, dialog.sphericity_note.cget("text"))
                reachable(dialog)
            reachable(dialog)
            buttons(dialog)
            capture(dialog, f"window-rm-sphericity-compact-{start}.png")

        app.show("data", TITLE)
        drive(compact, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        root.geometry(geometry)
        root.update_idletasks()

        # --- The dialog: a mistyped Subject label keeps the dialog open on that field; the same dialog then runs.
        def configure(dialog):
            choose(dialog, "Subject", CANONICAL)
            assert dialog.field_rows[FIELD][0].cget("text") == words["caption"]
            assert "omnibus" in dialog.sphericity_note.cget("text")
            dialog.fields.select(options_page(dialog))
            dialog.update()
            capture(dialog, f"window-rm-sphericity-fields-{start}.png")
            dialog.fields.select(0)
            dialog.update()
            message = reject(dialog, words["incomplete"])
            assert "9" in message and f"{VISIT} × {CONDITION}" in message, message
            assert [dialog.controls["Factors"][1].get(i) for i in dialog.controls["Factors"][1].curselection()] == [
                VISIT, CONDITION]
            assert dialog.controls["Response"][1].get() == "Response"
            assert dialog.controls[FIELD][1].get() == CANONICAL
            buttons(dialog)
            capture(dialog, f"window-rm-sphericity-error-{start}.png")
            dialog.controls["Subject"][1].set("Participant")
            dialog.update()
            assert dialog.validate() is True
            assert dialog.result[1] == {"Response": "Response", "Factors": [VISIT, CONDITION],
                                        "Subject": "Participant", FIELD: CANONICAL}, dialog.result
            assert list(dialog.processing_result.tables) == ["ANOVA", SHEET]
            dialog.result = None

        app.show("data", TITLE)
        runs_before = len(app.runs)
        drive(configure, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        assert len(app.runs) == runs_before + 1
        index = len(app.runs) - 1
        run = app.runs[index]
        assert run.options[FIELD] == CANONICAL and run.options["Subject"] == "Participant", run.options
        check_two_way(run, corrected=True)
        for term in ("Participant", f"Participant:{VISIT}", f"Participant:{CONDITION}",
                     f"Participant:{VISIT}:{CONDITION}"):
            assert pd.isna(run.result.tables["ANOVA"].loc[term, "F"]), term
        # The corrected run changes only the test: same SS, MS, F and strata as the saved no-correction recipe.
        for column in ("SS", "df", "MS", "F"):
            np.testing.assert_allclose(run.result.tables["ANOVA"][column].astype(float),
                                       legacy_two_way[column].astype(float), rtol=1e-12, equal_nan=True)
        # Three different epsilons, and fractional degrees of freedom on the grid.
        assert len({round(float(value), 6) for value in run.result.tables[SHEET]["GG ε"]}) == 3
        grid = result_grid(index, "ANOVA")
        df1 = displayed(grid, "F df1")
        assert abs(float(df1[VISIT]) - expected[VISIT]["df1"]) < 5e-3, df1
        assert abs(float(df1[CONDITION]) - expected[CONDITION]["df1"]) < 5e-3, df1
        assert float(df1[f"{VISIT}:{CONDITION}"]) != int(float(df1[f"{VISIT}:{CONDITION}"])), df1
        capture(root, f"window-rm-sphericity-anova-{start}.png")
        result_grid(index, SHEET)
        capture(root, f"window-rm-sphericity-sheet-{start}.png")
        sphericity_csv = directory / "rm-sphericity-sheet.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(sphericity_csv)):
            app.export()
        exported = pd.read_csv(sphericity_csv)
        assert set(app.runs[index].result.tables[SHEET].columns) <= set(exported.columns), exported.columns
        exported = exported[list(app.runs[index].result.tables[SHEET].columns)]
        assert exported["Term"].tolist() == list(expected), exported
        assert np.allclose(exported["GG ε"], [EPSILON[term] for term in expected], rtol=1e-12)
        pd.testing.assert_frame_equal(exported, app.runs[index].result.tables[SHEET].reset_index(drop=True),
                                      check_exact=False, rtol=1e-12)
        first_epsilon = exported["GG ε"].to_numpy().copy()

        # --- An excluded cell: the design is incomplete, so the run says so; restoring the cell restores the result.
        app.show("data", TITLE)
        root.update()
        response_column = list(app.tables[TITLE].raw.columns).index("Response")
        app.current_grid.select((4, response_column))
        app.toggle_exclusion()
        wait()
        assert app.runs[index].result is None, "an excluded cell leaves a design with a missing measurement"
        status = app.status.get()
        assert "attention" in status.casefold() or "attenzione" in status.casefold(), status
        app.current_grid.select((4, response_column))
        app.toggle_exclusion()
        wait()
        restored = app.runs[index]
        assert restored.result is not None
        check_two_way(restored, corrected=True)
        np.testing.assert_allclose(restored.result.tables[SHEET]["GG ε"].to_numpy(), first_epsilon, rtol=1e-12)

        # --- A data edit refits the corrected run with its own epsilon, then the original value comes back.
        original = float(app.tables[TITLE].raw.iat[8, response_column])
        app.edit_cell(8, response_column, f"{original + 6:.6f}")
        wait()
        edited = app.runs[index].result.tables[SHEET]
        assert not np.allclose(edited["GG ε"].to_numpy(), first_epsilon), edited
        app.edit_cell(8, response_column, f"{original:.6f}")
        wait()
        check_two_way(app.runs[index], corrected=True)

        # --- Save, reopen: the canonical recipe is stored and the same numbers come back, result opened first.
        after = directory / "rm-sphericity-after.alab"
        app.path = after
        assert app.save()
        stored = load_project(after)[TITLE].analyses
        assert stored[1][1][FIELD] == CANONICAL and stored[0][1][FIELD] == NONE
        assert load_project(after)[ONE_WAY].analyses[0][1][FIELD] == LEGACY
        app.import_file(after)
        root.update()
        # A reopened project lists the runs by worksheet, so the corrected run is found by its recipe.
        index = next(i for i, item in enumerate(app.runs) if item.title == TITLE and item.options[FIELD] == CANONICAL)
        assert app.runs[index].result is None, "a reopened project calculates a result when it is opened"
        app.open_sheet(("result", index))
        wait()
        reopened = app.runs[index]
        assert reopened.options[FIELD] == CANONICAL
        check_two_way(reopened, corrected=True)
        np.testing.assert_allclose(reopened.result.tables[SHEET]["GG ε"].to_numpy(), first_epsilon, rtol=1e-12)
        grid = result_grid(index, "ANOVA")
        capture(root, f"window-rm-sphericity-reopened-{start}.png")
        grid.cells.canvas.xview_moveto(1)       # the corrected degrees of freedom sit to the right of F at 1024 × 768
        root.update()
        capture(root, f"window-rm-sphericity-reopened-df-{start}.png")
        grid.cells.canvas.xview_moveto(0)

        # --- Use Result as Data copies the Sphericity sheet, equal to its CSV.
        result_grid(index, SHEET)
        before_tables = set(app.tables)
        app.use_result_as_data()
        created = set(app.tables) - before_tables
        assert len(created) == 1, created
        copied = app.tables[created.pop()].raw
        assert copied["Term"].tolist() == list(expected), copied
        np.testing.assert_allclose(copied["GG ε"].astype(float), exported["GG ε"], rtol=1e-12)
        np.testing.assert_allclose(copied["p"].astype(float), exported["p"], rtol=1e-12)

        # --- The saved one-way recipe is offered with its own label, runs unchanged, and keeps the old tables.
        def one_way_recipe(dialog):
            binding = dialog.choice_bindings[FIELD]
            assert binding.values == (NONE, CANONICAL, HF, LOWER, LEGACY), binding.values
            assert dialog.controls[FIELD][1].get() == LEGACY
            assert "one-way" in binding.labels[4] or "una via" in binding.labels[4], binding.labels
            assert dialog.validate() is True and dialog.result[1][FIELD] == LEGACY

        one_way_index = next(i for i, item in enumerate(app.runs) if item.title == ONE_WAY)
        app.show("result", one_way_index)
        drive(one_way_recipe, accept=True)
        app.edit_analysis()
        assert not local_errors, local_errors
        wait()
        assert app.runs[one_way_index].options[FIELD] == LEGACY
        pd.testing.assert_frame_equal(app.runs[one_way_index].result.tables["ANOVA"], legacy_one_way)

        # --- Cancel leaves the project as it was.
        runs_before, recipe_before = len(app.runs), dict(app.runs[index].options)

        def cancel(dialog):
            choose(dialog, "Participant", CANONICAL)
            buttons(dialog)

        app.show("result", index)
        drive(cancel, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        assert len(app.runs) == runs_before and app.runs[index].options == recipe_before

        # --- A recipe that cannot run reopens the dialog on its field, the same dialog runs it again.
        def recovery(language):
            recover = directory / f"rm-sphericity-recover-{language}.alab"
            save_project(recover, {TITLE: Dataset(_long(), analyses=[
                (METHOD, {"Response": "Response", "Factors": [VISIT, CONDITION], "Subject": "Subject",
                          FIELD: CANONICAL})])})
            set_language(language)
            app.import_file(recover)
            root.update()

            def recovered(dialog):
                assert dialog.error_label is not None
                text = dialog.error_label.cget("text")
                assert INCOMPLETE[language] in text, text
                assert text.startswith("Soggetto: Il soggetto S1") if language == "it" else text.startswith("Subject S1")
                assert dialog.focus_get() is dialog.field_rows["Subject"][1], dialog.focus_get()
                assert dialog.controls[FIELD][1].get() == CANONICAL
                capture(dialog, f"window-rm-sphericity-recovered-{language}.png")
                dialog.controls["Subject"][1].set("Participant")
                dialog.update()

            state = when_open(recovered, accept=True)
            app.open_sheet(("result", 0))
            settle(state)
            wait()
            assert app.runs[0].options["Subject"] == "Participant" and app.runs[0].result is not None
            check_two_way(app.runs[0], corrected=True)

        recovery(start)
        if start == "en":
            recovery("it")
            set_language(start)

        # --- Italian: captions, note and error translate; the recipe and the sheets stay canonical.
        def italian(dialog):
            choose(dialog, "Subject")
            assert dialog.field_rows[FIELD][0].cget("text") == "Correzione della sfericità"
            assert dialog.choice_bindings[FIELD].labels == ("Nessuno", CANONICAL, "Huynh–Feldt", "Limite inferiore"), \
                dialog.choice_bindings[FIELD].labels
            assert dialog.controls[FIELD][1].get() == NONE
            dialog.controls[FIELD][1].set(CANONICAL)
            dialog.update()
            assert dialog.choice_bindings[FIELD].combobox.get() == CANONICAL
            note = dialog.sphericity_note.cget("text")
            for phrase in ("Ogni effetto", "omnibus", "post-hoc", "Mauchly", "REML"):
                assert phrase in note, (phrase, note)
            dialog.controls[FIELD][1].set(HF)
            dialog.update()
            for phrase in ("Huynh–Feldt stima", "Mauchly", "disegno completo"):
                assert phrase in dialog.sphericity_note.cget("text"), (phrase, dialog.sphericity_note.cget("text"))
            dialog.controls[FIELD][1].set(CANONICAL)
            dialog.update()
            reachable(dialog)
            dialog.fields.select(0)
            dialog.update()
            message = reject(dialog, INCOMPLETE["it"])
            assert message.startswith("Soggetto: Il soggetto S1 non ha"), message
            assert "combinazioni" in message and "I disegni fra soggetti" in message, message
            buttons(dialog)
            dialog.controls["Subject"][1].set("Participant")
            dialog.update()
            assert dialog.validate() is True
            assert dialog.result[1][FIELD] == CANONICAL and dialog.result[1]["Subject"] == "Participant"
            if start == "en":
                dialog.fields.select(options_page(dialog))
                dialog.update()
                capture(dialog, "window-rm-sphericity-fields-it.png")
            dialog.result = None

        set_language("it")
        app.show("data", TITLE)
        runs_before = len(app.runs)
        drive(italian, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        assert len(app.runs) == runs_before + 1
        italian_run = app.runs[-1]
        assert italian_run.options[FIELD] == CANONICAL
        check_two_way(italian_run, corrected=True)
        app.show("result", len(app.runs) - 1)
        result_grid(len(app.runs) - 1, SHEET)
        capture(root, "window-rm-sphericity-sheet-it.png")
        saved = directory / "rm-sphericity-italian.alab"
        app.path = saved
        assert app.save()
        assert load_project(saved)[TITLE].analyses[-1][1][FIELD] == CANONICAL
        set_language(start)
    finally:
        set_language(previous_language)
        root.geometry(previous_geometry)
        root.update_idletasks()
        if os.environ.get("TRAMASTAT_SMOKE_ONLY") == "rm-two-way-sphericity":
            print("rm-two-way-sphericity: window", geometry,
                  f"screen {root.winfo_screenwidth()}x{root.winfo_screenheight()}", f"language {start}", flush=True)
    assert not local_errors, local_errors
