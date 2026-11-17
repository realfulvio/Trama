"""Desktop smoke check for Multifactor ANOVA with selected model terms (0.83).

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=anova-selected-terms``) calls
:func:`check_anova_selected_terms`. Sheet names stay canonical English. The dialog captions follow the
active language, and the recipe keeps ``Term selection`` and ``Model terms`` in their canonical form
(English choice, literal factor names) whatever the language is.
"""
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd

from .anova_terms import ERRORS, FULL, MODEL_TERMS, SELECTED, SHEET, TERM_SELECTION, label
from .data import Dataset, load_project, save_project
from .field_error import FieldError
from .i18n import active_language, set_language, ui

TITLE = "Plates"
METHOD = "Multifactor ANOVA"
DOSE, GROUP, LOT = "Dose (mg)", "Group", "Lot 24"
FACTORS = [DOSE, GROUP, LOT]
TERMS = [[DOSE], [GROUP], [LOT], [DOSE, LOT]]
LEGACY = {"Response": "Y", "Factors": FACTORS, "Interaction order": 2, "Effect sizes": True,
          "Alpha": 0.05, "Compare marginal means by": DOSE}
SELECTED_TABLES = ["ANOVA (type III)", SHEET, "Effect sizes", "Model fit", "Multiple comparisons"]
LEGACY_TABLES = ["ANOVA (type III)", "Effect sizes", "Model fit", "Multiple comparisons"]


def _frame():
    """Synthetic 2 × 2 × 3 plate study with three replicates and one missing response."""
    rng = np.random.default_rng(83)
    rows = [(dose, group, lot, 10 + 2.0 * i + 1.5 * j + 0.8 * k + 1.2 * i * (k == 2) + rng.normal(0, 0.7))
            for i, dose in enumerate(("Low", "High")) for j, group in enumerate(("Ctrl", "Drug"))
            for k, lot in enumerate(("Lot 1", "Lot 2", "Lot 3")) for _ in range(3)]
    frame = pd.DataFrame(rows, columns=[DOSE, GROUP, LOT, "Y"])
    frame.loc[4, "Y"] = np.nan
    return frame


def reference(frame, terms):
    """Type III table of the same model from statsmodels with Sum coding, for an independent check."""
    from statsmodels.formula.api import ols
    from statsmodels.stats.anova import anova_lm
    names = {DOSE: "fa", GROUP: "fb", LOT: "fc"}
    data = frame.rename(columns=names).dropna(subset=["Y", "fa", "fb", "fc"])
    formula = "Y ~ " + " + ".join(":".join(f"C({names[name]}, Sum)" for name in term) for term in terms)
    table = anova_lm(ols(formula, data).fit(), typ=3)
    return {label(term): table.loc[":".join(f"C({names[name]}, Sum)" for name in term)] for term in terms}, \
        table.loc["Residual"]


def check_anova_selected_terms(root, app, directory, kit):
    from tkinter import filedialog, messagebox, ttk

    capture, pick, select = kit.capture, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_language = active_language()
    previous_geometry = root.geometry()
    local_errors = []
    # The main flow runs in the language of the preferences; one Italian dialog follows in either case.
    start = previous_language if previous_language in ("en", "it") else "en"
    set_language(start)
    words = {"en": {"hierarchy": "strong hierarchy", "rank": "cannot be identified"},
             "it": {"hierarchy": "gerarchia forte", "rank": "non è identificabile"}}[start]

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
        import time
        deadline = time.monotonic() + 60
        while not state["done"] or app.pending is not None:
            assert time.monotonic() < deadline, "ANOVA recovery did not finish"
            root.update()
            time.sleep(0.02)
        assert not local_errors, local_errors

    def picker_of(dialog):
        return dialog.controls[MODEL_TERMS][1]

    def model_page(dialog):
        page = dialog.field_rows[TERM_SELECTION][0].master
        while page.master is not dialog.fields:
            page = page.master
        return page

    def buttons(dialog):
        dialog.update_idletasks()
        found = []
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found.append(str(widget.cget("text")))
                    assert widget.winfo_ismapped() and widget.winfo_viewable(), widget.cget("text")
        assert ui("Run Analysis") in found and ui("Cancel") in found, found
        screen_bottom = dialog.winfo_screenheight()
        assert dialog.winfo_rooty() + dialog.winfo_height() <= screen_bottom, "the dialog does not fit the screen"

    def reachable(dialog, widget):
        """The widget sits inside the visible part of the scrollable Model page."""
        dialog.update()
        canvas = dialog.field_rows[TERM_SELECTION][0].master._scroll_canvas
        top, bottom = canvas.winfo_rooty(), canvas.winfo_rooty() + canvas.winfo_height()
        assert top <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= bottom, (
            widget, widget.winfo_rooty(), top, bottom)

    def reject(dialog, snippet):
        picker = picker_of(dialog)
        with patch.object(messagebox, "showerror") as shown:
            dialog.ok()
        assert shown.called, snippet
        assert snippet in shown.call_args.args[1], shown.call_args
        assert dialog.winfo_exists() and dialog.result is None
        dialog.update()
        assert dialog.fields.tab(dialog.fields.select(), "text") == ui("Model")
        assert dialog.focus_get() is picker.focus_target(), dialog.focus_get()

    def check_terms(run, terms, frame):
        """The ANOVA sheet of the run equals the statsmodels Type III table of the same model."""
        table = run.result.tables["ANOVA (type III)"]
        expected, residual = reference(frame, terms)
        assert list(table.index) == [*(label(term) for term in terms), "Residual"], list(table.index)
        for term in terms:
            row, ref = table.loc[label(term)], expected[label(term)]
            assert np.isclose(row["SS"], ref["sum_sq"], rtol=1e-8), (term, row["SS"], ref["sum_sq"])
            assert np.isclose(row["F"], ref["F"], rtol=1e-8), (term, row["F"], ref["F"])
            assert int(row["df"]) == int(ref["df"]), term
        assert np.isclose(table.loc["Residual", "SS"], residual["sum_sq"], rtol=1e-8)
        assert int(table.loc["Residual", "df"]) == int(residual["df"])

    def current_frame():
        return app.tables[TITLE].frame(mask_excluded=True).copy()

    def result_index(run, name):
        return list(run.result.tables).index(name)

    try:
        before = directory / "anova-terms-before.alab"
        save_project(before, {TITLE: Dataset(_frame(), analyses=[(METHOD, dict(LEGACY))])})
        app.import_file(before)
        app.open_sheet(("result", 0))
        wait()
        legacy = app.runs[0]
        assert list(legacy.result.tables) == LEGACY_TABLES, list(legacy.result.tables)
        assert TERM_SELECTION not in legacy.options and MODEL_TERMS not in legacy.options
        legacy_tables = {name: table.copy() for name, table in legacy.result.tables.items()}

        # --- Selected terms from the dialog: a term edited out, a missing prerequisite refused and restored.
        def configure(dialog):
            pick(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            select(dialog, "Factors", set(FACTORS))
            dialog.update()
            dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
            dialog.update()
            tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            assert tabs[:3] == [ui("Variables"), ui("Model"), ui("Options")], tabs
            picker = picker_of(dialog)
            assert dialog.controls[TERM_SELECTION][1].get() == FULL
            assert not any(frame.winfo_manager() for frame in picker.groups.values())
            assert dialog.field_rows["Interaction order"][1].winfo_manager()
            dialog.controls["Interaction order"][1].set("2")
            dialog.update()
            assert picker.values() == [[DOSE], [GROUP], [LOT], [DOSE, GROUP], [DOSE, LOT], [GROUP, LOT]]
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            assert all(frame.winfo_manager() for frame in picker.groups.values())
            assert not dialog.field_rows["Interaction order"][1].winfo_manager()
            assert len(picker.values()) == 6          # the model Full hierarchy would fit is the starting point
            dialog.fields.select(model_page(dialog))
            for term in ((DOSE, GROUP), (GROUP, LOT)):
                picker.boxes[term].invoke()           # the checkbutton command, as a click would run it
            dialog.update()
            assert picker.values() == TERMS, picker.values()
            assert f"Y = {DOSE} + {GROUP} + {LOT} + {DOSE}:{LOT}" in picker.summary.cget("text")
            assert picker.outside.cget("text") == ""
            capture(dialog, f"window-anova-terms-fields-{start}.png")
            picker.boxes[(DOSE,)].invoke()
            dialog.update()
            assert f"{DOSE}:{LOT}" in picker.problem.cget("text")
            assert "disabled" not in picker.add_button.state()
            reject(dialog, words["hierarchy"])
            capture(dialog, f"window-anova-terms-error-{start}.png")
            picker.add_button.invoke()
            dialog.update()
            assert picker.values() == TERMS and picker.problem.cget("text") == ""
            assert "disabled" in picker.add_button.state()
            picker.add_button.focus_force()
            reachable(dialog, picker.add_button)
            buttons(dialog)
            dialog.controls["Effect sizes"][1].set(True)
            dialog.show_anova_fields()
            dialog.controls["Compare marginal means by"][1].set(DOSE)
            dialog.fields.select(model_page(dialog))
            capture(dialog, f"window-anova-terms-ready-{start}.png")

        drive(configure, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        run = app.runs[1]
        assert run.options[TERM_SELECTION] == SELECTED
        assert run.options[MODEL_TERMS] == TERMS, run.options[MODEL_TERMS]
        assert list(run.result.tables) == SELECTED_TABLES, list(run.result.tables)
        terms_sheet = run.result.tables[SHEET]
        assert list(terms_sheet.index) == [label(term) for term in TERMS]
        assert terms_sheet["df"].tolist() == [1, 1, 2, 2]
        check_terms(run, TERMS, current_frame())
        assert list(run.result.tables["Effect sizes"].index) == [label(term) for term in TERMS]
        assert run.result.tables["Multiple comparisons"].index.tolist() == ["High − Low"]
        app.show("result", 1)
        app.result_tabs.select(result_index(run, "ANOVA (type III)"))
        root.update()
        capture(root, f"window-anova-terms-anova-{start}.png")
        app.result_tabs.select(result_index(run, SHEET))
        root.update()
        capture(root, f"window-anova-terms-sheet-{start}.png")
        first_ss = run.result.tables["ANOVA (type III)"]["SS"].copy()

        # --- Full hierarchy from the dialog is the legacy analysis: same tables, a recipe without the new keys.
        def full(dialog):
            pick(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            select(dialog, "Factors", set(FACTORS))
            dialog.update()
            dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
            dialog.controls["Interaction order"][1].set("2")
            dialog.controls["Effect sizes"][1].set(True)
            dialog.show_anova_fields()
            dialog.controls["Compare marginal means by"][1].set(DOSE)
            assert dialog.controls[TERM_SELECTION][1].get() == FULL

        drive(full, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        again = app.runs[2]
        assert TERM_SELECTION not in again.options and MODEL_TERMS not in again.options, again.options
        assert list(again.result.tables) == LEGACY_TABLES
        for name, table in legacy_tables.items():
            pd.testing.assert_frame_equal(again.result.tables[name], table)

        # --- A data edit and an exclusion refit the same selection.
        app.show("result", 1)
        app.edit_cell(0, 3, "16.5")
        wait()
        edited = app.runs[1]
        assert not np.allclose(edited.result.tables["ANOVA (type III)"]["SS"], first_ss)
        check_terms(edited, TERMS, current_frame())
        app.show("data", TITLE)
        root.update()
        app.current_grid.select((1, 3))
        app.toggle_exclusion()
        wait()
        excluded = app.runs[1]
        assert int(excluded.result.tables["ANOVA (type III)"].loc["Residual", "df"]) == 27
        assert excluded.result.tables["Model fit"].loc["N", "Value"] == 34
        check_terms(excluded, TERMS, current_frame())
        sums = excluded.result.tables["ANOVA (type III)"]["SS"].copy()

        # --- CSV of the new sheet and of the ANOVA table.
        app.show("result", 1)
        app.result_tabs.select(result_index(excluded, SHEET))
        csv_path = directory / "anova-terms-model-terms.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        exported = pd.read_csv(csv_path)
        assert exported["Term"].tolist() == [label(term) for term in TERMS], exported
        assert exported["Effect"].tolist() == ["Main effect"] * 3 + ["Two-way interaction"]
        app.result_tabs.select(result_index(excluded, "ANOVA (type III)"))
        anova_csv = directory / "anova-terms-anova.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(anova_csv)):
            app.export()
        assert np.allclose(pd.read_csv(anova_csv)["SS"], sums.to_numpy())

        # --- Save, reopen: the canonical recipe comes back and the same numbers are computed again.
        after = directory / "anova-terms-after.alab"
        app.path = after
        assert app.save()
        app.import_file(after)
        root.update()
        app.open_sheet(("result", 1))
        wait()
        reopened = app.runs[1]
        assert reopened.options[TERM_SELECTION] == SELECTED and reopened.options[MODEL_TERMS] == TERMS
        assert np.allclose(reopened.result.tables["ANOVA (type III)"]["SS"], sums.to_numpy())
        stored = load_project(after)[TITLE].analyses
        assert stored[1][1][TERM_SELECTION] == SELECTED and stored[1][1][MODEL_TERMS] == TERMS
        assert TERM_SELECTION not in stored[0][1] and TERM_SELECTION not in stored[2][1]

        # --- Use Result as Data copies the new sheet.
        app.show("result", 1)
        app.result_tabs.select(result_index(reopened, SHEET))
        before_tables = set(app.tables)
        app.use_result_as_data()
        created = set(app.tables) - before_tables
        assert len(created) == 1
        copied = app.tables[created.pop()].raw
        assert [label(term) for term in TERMS] == (copied["Term"].tolist() if "Term" in copied.columns
                                                   else copied.iloc[:, 0].tolist()), copied

        # --- Cancel leaves the project as it was.
        runs_before = len(app.runs)
        recipe_before = dict(app.runs[1].options)

        def cancel(dialog):
            pick(dialog, METHOD)
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            picker_of(dialog).clear()
            buttons(dialog)

        app.show("result", 1)
        drive(cancel, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        assert len(app.runs) == runs_before and app.runs[1].options == recipe_before

        # --- Italian: captions translate, the recipe stays canonical.
        def italian(dialog):
            pick(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            select(dialog, "Factors", set(FACTORS))
            dialog.update()
            dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
            dialog.update()
            assert dialog.fields.tab(1, "text") == "Modello"
            assert dialog.field_rows[TERM_SELECTION][0].cget("text") == "Selezione dei termini"
            assert dialog.field_rows[MODEL_TERMS][0].cget("text") == "Termini del modello"
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()
            assert dialog.controls[TERM_SELECTION][1].get() == SELECTED
            assert dialog.choice_bindings[TERM_SELECTION].combobox.get() == "Termini scelti"
            picker = picker_of(dialog)
            assert [frame.cget("text") for frame in picker.groups.values()] == [
                "Effetti principali", "Interazioni a due fattori", "Interazioni a tre fattori"]
            assert picker.all_button.cget("text") == "Seleziona tutto"
            assert picker.add_button.cget("text") == "Aggiungi i termini richiesti"
            dialog.fields.select(model_page(dialog))
            picker.boxes[(DOSE, LOT)].invoke()
            picker.boxes[(DOSE,)].invoke()
            dialog.update()
            assert f"{DOSE}:{LOT} richiede {DOSE}" in picker.problem.cget("text"), picker.problem.cget("text")
            if start == "en":
                capture(dialog, "window-anova-terms-error-it.png")
            with patch.object(messagebox, "showerror") as shown:
                dialog.ok()
            assert "gerarchia forte" in shown.call_args.args[1], shown.call_args
            assert dialog.focus_get() is picker.focus_target()
            picker.add_button.invoke()
            dialog.update()
            buttons(dialog)
            if start == "en":
                capture(dialog, "window-anova-terms-fields-it.png")
            assert dialog.validate() is True
            assert dialog.result[1][TERM_SELECTION] == SELECTED
            assert dialog.result[1][MODEL_TERMS] == TERMS, dialog.result[1][MODEL_TERMS]
            dialog.result = None

        set_language("it")
        runs_before = len(app.runs)
        drive(italian, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        assert len(app.runs) == runs_before + 1
        italian_run = app.runs[-1]
        assert italian_run.options[TERM_SELECTION] == SELECTED
        assert italian_run.options[MODEL_TERMS] == TERMS, italian_run.options[MODEL_TERMS]
        assert list(italian_run.result.tables)[:2] == ["ANOVA (type III)", SHEET]
        app.show("result", len(app.runs) - 1)
        root.update()
        capture(root, f"window-anova-terms-results-it.png")
        saved = directory / "anova-terms-italian.alab"
        app.path = saved
        assert app.save()
        stored = load_project(saved)[TITLE].analyses[-1][1]
        assert stored[TERM_SELECTION] == SELECTED and stored[MODEL_TERMS] == TERMS
        set_language(start)

        # --- Back to Full hierarchy by editing the recipe: the sheet and the terms disappear.
        def back_to_full(dialog):
            dialog.controls[TERM_SELECTION][1].set(FULL)
            dialog.controls["Interaction order"][1].set("2")
            dialog.update()
            assert not any(frame.winfo_manager() for frame in picker_of(dialog).groups.values())

        app.show("result", 1)
        drive(back_to_full, accept=True)
        app.edit_analysis()
        assert not local_errors, local_errors
        wait()
        restored = app.runs[1]
        assert restored.options[TERM_SELECTION] == FULL and MODEL_TERMS not in restored.options
        assert SHEET not in restored.result.tables
        assert restored.result.tables["ANOVA (type III)"].index.tolist()[:6] == [
            DOSE, GROUP, LOT, f"{DOSE}:{GROUP}", f"{DOSE}:{LOT}", f"{GROUP}:{LOT}"]

        # --- An unidentifiable model reopens the dialog on Model terms and keeps the confirmed analysis.
        kept = app.runs[1]
        kept_tables = {name: table.copy() for name, table in kept.result.tables.items()}

        def candidate(dialog):
            dialog.controls[TERM_SELECTION][1].set(SELECTED)
            dialog.update()

        def recovered(dialog):
            assert dialog.error_label is not None
            assert words["rank"] in dialog.error_label.cget("text"), dialog.error_label.cget("text")
            assert dialog.fields.tab(dialog.fields.select(), "text") == ui("Model")
            assert dialog.controls[TERM_SELECTION][1].get() == SELECTED
            assert dialog.result is None

        app.show("result", 1)
        drive(candidate, accept=True)
        with patch("analisi.workbench.anova_terms_table", side_effect=FieldError(MODEL_TERMS, ERRORS["rank"])):
            app.edit_analysis()
            state = when_open(recovered, accept=False)
            settle(state)
        assert app.runs[1] is kept
        for name, table in kept_tables.items():
            pd.testing.assert_frame_equal(app.runs[1].result.tables[name], table)
        assert "discarded" in app.status.get().casefold()
    finally:
        set_language(previous_language)
        root.geometry(previous_geometry)
        root.update_idletasks()
