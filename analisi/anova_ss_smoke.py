"""Desktop smoke check for the sums of squares of the Multifactor ANOVA (Type I, II and III).

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=anova-ss-types``) calls :func:`check_anova_ss_types`.
Sheet names stay canonical English. The dialog captions follow the active language, and the recipe keeps
``Sums of squares`` and its value in the canonical English form whatever the language is. The tables are
compared with an independent statsmodels fit of the same model (Sum coding), never with Trama itself.
"""
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd

from .anova_diagnostics import DIAGNOSTICS
from .anova_ss import ERRORS, KEY, SHEETS
from .anova_terms import MODEL_TERMS, SELECTED, TERM_SELECTION, label
from .data import Dataset, load_project, save_project
from .field_error import FieldError
from .i18n import active_language, set_language, ui

TITLE = "Plates"
METHOD = "Multifactor ANOVA"
DOSE, GROUP, LOT = "Dose (mg)", "Group", "Lot 24"
FACTORS = [DOSE, GROUP, LOT]
PAIR = [DOSE, GROUP]
SELECTION = [[DOSE], [GROUP], [LOT], [DOSE, GROUP]]
LEGACY = {"Response": "Y", "Factors": PAIR, "Interaction order": 2}
ALIASES = {DOSE: "fa", GROUP: "fb", LOT: "fc"}
TYPES = {"Type I": 1, "Type II": 2, "Type III": 3}


def _frame():
    """Synthetic 2 × 3 study with unequal replicates and a two-level lot. Level names carry ``|``, ``:`` and spaces."""
    rng = np.random.default_rng(92)
    counts = {("Low", "Ctrl"): 5, ("Low", "Ctrl|Low"): 4, ("Low", "Drug: high"): 3,
              ("High", "Ctrl"): 3, ("High", "Ctrl|Low"): 5, ("High", "Drug: high"): 6}
    rows = []
    for (dose, group), count in counts.items():
        for index in range(count):
            lot = "Lot 1" if index % 3 else "Lot 1 bis"
            value = (10 + 3.0 * (dose == "High") + 2.0 * ("Ctrl", "Ctrl|Low", "Drug: high").index(group)
                     + 4.0 * (dose == "High") * (group == "Drug: high") + 1.5 * (lot == "Lot 1 bis") + rng.normal(0, 1.2))
            rows.append((dose, group, lot, value))
    return pd.DataFrame(rows, columns=[DOSE, GROUP, LOT, "Y"])


def reference(frame, factors, terms, kind):
    """Table of the model from statsmodels (Sum coding) as ``{label: (SS, df, F, p)}`` and ``(SSE, df)``."""
    from statsmodels.formula.api import ols
    from statsmodels.stats.anova import anova_lm
    data = frame.rename(columns=ALIASES).dropna(subset=["Y", *(ALIASES[name] for name in factors)])
    names = {tuple(term): ":".join(f"C({ALIASES[name]}, Sum)" for name in term) for term in terms}
    fitted = ols("Y ~ " + " + ".join(names.values()), data).fit()
    table = anova_lm(fitted, typ=TYPES[kind])
    rows = {label(term): tuple(float(table.loc[names[tuple(term)], column])
                               for column in ("sum_sq", "df", "F", "PR(>F)")) for term in terms}
    return rows, (float(fitted.ssr), int(fitted.df_resid))


def check_anova_ss_types(root, app, directory, kit):
    from tkinter import filedialog, messagebox, ttk

    capture, pick, select = kit.capture, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_language = active_language()
    previous_geometry = root.geometry()
    local_errors = []
    # The main flow runs in the language of the preferences; one Italian dialog follows in either case.
    start = previous_language if previous_language in ("en", "it") else "en"
    set_language(start)
    words = {"en": {"order": "Terms enter in this order", "numeric": "could not be computed reliably"},
             "it": {"order": "I termini entrano in quest’ordine", "numeric": "non si sono potute calcolare"}}[start]

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

    def panel_of(dialog):
        return dialog.anova_order

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
        assert dialog.winfo_rooty() + dialog.winfo_height() <= dialog.winfo_screenheight(), "the dialog does not fit"

    def reachable(dialog, widget):
        """The widget sits inside the visible part of the scrollable Model page."""
        dialog.update()
        canvas = dialog.field_rows[TERM_SELECTION][0].master._scroll_canvas
        top, bottom = canvas.winfo_rooty(), canvas.winfo_rooty() + canvas.winfo_height()
        assert top <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= bottom, (
            widget, widget.winfo_rooty(), top, bottom)

    def set_kind(dialog, kind):
        dialog.controls[KEY][1].set(kind)
        dialog.update()

    def configure_pair(dialog, kind, *, order=None, terms=None, extra=()):
        """Response Y, factors Dose and Group with A:B, one type, and optionally the order of the factors."""
        pick(dialog, METHOD)
        dialog.controls["Response"][1].set("Y")
        select(dialog, "Factors", set(PAIR))
        dialog.update()
        dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
        dialog.update()
        dialog.controls["Interaction order"][1].set("2")
        set_kind(dialog, kind)
        if order is not None:
            move_to(dialog, order)
        for name, value in extra:
            dialog.controls[name][1].set(value)
        dialog.show_anova_fields()

    def move_to(dialog, wanted):
        """Reorder the factors of the panel with its Up and Down buttons, as a user would."""
        panel = panel_of(dialog)
        for target, name in enumerate(wanted):
            while panel.ordered().index(name) > target:
                panel.listbox.selection_clear(0, "end")
                panel.listbox.selection_set(panel.ordered().index(name))
                panel.up.invoke()
                dialog.update()
        assert panel.ordered() == list(wanted), panel.ordered()

    def current_frame():
        return app.tables[TITLE].frame(mask_excluded=True).copy()

    def check_table(run, factors, terms, kind):
        """The first sheet of the run is the statsmodels table of the same model, with the type in its name."""
        assert list(run.result.tables)[0] == SHEETS[kind], list(run.result.tables)
        table = run.result.tables[SHEETS[kind]]
        expected, (sse, df) = reference(current_frame(), factors, terms, kind)
        assert list(table.index) == [*expected, "Residual"], list(table.index)
        for name, (ss, width, statistic, p) in expected.items():
            row = table.loc[name]
            assert np.isclose(row["SS"], ss, rtol=1e-8), (kind, name, row["SS"], ss)
            assert int(row["df"]) == int(width), (kind, name)
            assert np.isclose(row["F"], statistic, rtol=1e-8), (kind, name)
            assert np.isclose(row["p"], p, rtol=1e-7, atol=1e-12), (kind, name)
        assert np.isclose(table.loc["Residual", "SS"], sse, rtol=1e-9)
        assert int(table.loc["Residual", "df"]) == df
        return table

    def result_index(run, name):
        return list(run.result.tables).index(name)

    def fresh(dialog_action):
        """Run the dialog for a new analysis and return the run that was added."""
        runs = len(app.runs)
        drive(dialog_action, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        assert len(app.runs) == runs + 1
        return app.runs[-1]

    try:
        before = directory / "anova-ss-before.alab"
        save_project(before, {TITLE: Dataset(_frame(), analyses=[(METHOD, dict(LEGACY))])})
        app.import_file(before)
        app.open_sheet(("result", 0))
        wait()
        legacy = app.runs[0]
        assert list(legacy.result.tables) == ["ANOVA (type III)"], list(legacy.result.tables)
        assert KEY not in legacy.options
        legacy_table = legacy.result.tables["ANOVA (type III)"].copy()
        check_table(legacy, PAIR, [[DOSE], [GROUP], PAIR], "Type III")

        # --- A new analysis keeps the default: Type III, a recipe without the key and the legacy sheet, bit for bit.
        def keep_default(dialog):
            configure_pair(dialog, "Type III")
            assert dialog.controls[KEY][1].get() == "Type III"
            panel = panel_of(dialog)
            assert not panel.order.winfo_manager() or not panel.order.winfo_ismapped()
            assert panel.note.cget("text") == "" and panel.preview.cget("text") == ""

        run = fresh(keep_default)
        assert KEY not in run.options, run.options
        pd.testing.assert_frame_equal(run.result.tables["ANOVA (type III)"], legacy_table, check_exact=True)

        # --- Type I with the order of the factors in front of the user, then Dose and Group swapped.
        def type_one(dialog):
            configure_pair(dialog, "Type I")
            panel = panel_of(dialog)
            dialog.fields.select(model_page(dialog))
            dialog.update()
            assert dialog.field_rows[KEY][0].cget("text") == ui("Sums of squares")
            assert panel.order.winfo_ismapped() and panel.note.winfo_ismapped()
            assert panel.listbox.get(0, "end") == tuple(PAIR), panel.listbox.get(0, "end")
            assert words["order"] in panel.preview.cget("text")
            assert panel.preview.cget("text").endswith(f"{DOSE} → {GROUP} → {DOSE}:{GROUP}"), panel.preview.cget("text")
            for widget in (panel.up, panel.down, panel.preview):
                reachable(dialog, widget)
            buttons(dialog)
            capture(dialog, f"window-anova-ss-dialog-{start}.png")

        first = fresh(type_one)
        assert first.options[KEY] == "Type I" and first.options["Factors"] == PAIR, first.options
        table_one = check_table(first, PAIR, [[DOSE], [GROUP], PAIR], "Type I")
        app.show("result", len(app.runs) - 1)
        app.result_tabs.select(0)
        root.update()
        capture(root, f"window-anova-ss-type-one-{start}.png")

        def swapped(dialog):
            configure_pair(dialog, "Type I", order=[GROUP, DOSE])
            panel = panel_of(dialog)
            assert panel.listbox.get(0, "end") == (GROUP, DOSE)
            assert panel.preview.cget("text").endswith(f"{GROUP} → {DOSE} → {GROUP}:{DOSE}"), panel.preview.cget("text")
            # The term checkboxes of Selected terms follow the order of the factors too.
            picker = dialog.controls[MODEL_TERMS][1]
            assert [term for term in picker.available() if len(term) == 2] == [(GROUP, DOSE)], picker.available()
            dialog.fields.select(model_page(dialog))
            dialog.update()
            capture(dialog, f"window-anova-ss-order-{start}.png")

        second = fresh(swapped)
        assert second.options["Factors"] == [GROUP, DOSE], second.options
        reversed_table = check_table(second, [GROUP, DOSE], [[GROUP], [DOSE], [GROUP, DOSE]], "Type I")
        assert not np.isclose(table_one.loc[DOSE, "SS"], reversed_table.loc[DOSE, "SS"])
        assert not np.isclose(table_one.loc[GROUP, "SS"], reversed_table.loc[GROUP, "SS"])
        assert np.isclose(table_one.loc[f"{DOSE}:{GROUP}", "SS"], reversed_table.loc[f"{GROUP}:{DOSE}", "SS"])

        # The order is part of the recipe: reopening the analysis shows it again.
        def reopened_order(dialog):
            panel = panel_of(dialog)
            assert dialog.controls[KEY][1].get() == "Type I"
            assert panel.listbox.get(0, "end") == (GROUP, DOSE), panel.listbox.get(0, "end")
            assert dialog.anova_factors() == [GROUP, DOSE]

        app.show("result", len(app.runs) - 1)
        drive(reopened_order, accept=False)
        app.edit_analysis()
        assert not local_errors, local_errors

        # --- Type II is the same for either order of the factors once the names are mapped.
        def type_two(order):
            def action(dialog):
                configure_pair(dialog, "Type II", order=order)
                panel = panel_of(dialog)
                assert panel.note.cget("text") and panel.note.winfo_ismapped()
                assert not panel.order.winfo_ismapped()
            return action

        forward = fresh(type_two(PAIR))
        backward = fresh(type_two([GROUP, DOSE]))
        t_forward = check_table(forward, PAIR, [[DOSE], [GROUP], PAIR], "Type II")
        t_backward = check_table(backward, [GROUP, DOSE], [[GROUP], [DOSE], [GROUP, DOSE]], "Type II")
        for a, b in ((DOSE, DOSE), (GROUP, GROUP), (f"{DOSE}:{GROUP}", f"{GROUP}:{DOSE}")):
            assert np.allclose(t_forward.loc[a, ["SS", "df", "F", "p"]].to_numpy(float),
                               t_backward.loc[b, ["SS", "df", "F", "p"]].to_numpy(float), rtol=1e-9)
        app.show("result", len(app.runs) - 2)
        app.result_tabs.select(0)
        root.update()
        capture(root, f"window-anova-ss-type-two-{start}.png")

        # --- Selected terms A, B, C and A:B with a post-hoc, effect sizes and diagnostics: the type changes the
        # test (effect and p), never the estimates, the residuals or the comparisons.
        def selected(kind):
            def action(dialog):
                pick(dialog, METHOD)
                dialog.controls["Response"][1].set("Y")
                select(dialog, "Factors", set(FACTORS))
                dialog.update()
                dialog.controls["Factors"][1].event_generate("<<ListboxSelect>>")
                dialog.update()
                dialog.controls[TERM_SELECTION][1].set(SELECTED)
                set_kind(dialog, kind)
                picker = dialog.controls[MODEL_TERMS][1]
                picker.boxes[(DOSE, GROUP)].invoke()
                dialog.update()
                assert picker.values() == SELECTION, picker.values()
                if kind == "Type I":
                    assert panel_of(dialog).preview.cget("text").endswith(
                        f"{DOSE} → {GROUP} → {LOT} → {DOSE}:{GROUP}"), panel_of(dialog).preview.cget("text")
                dialog.controls["Effect sizes"][1].set(True)
                dialog.controls[DIAGNOSTICS][1].set(True)
                dialog.show_anova_fields()
                dialog.controls["Compare marginal means by"][1].set(DOSE)
            return action

        runs = {kind: fresh(selected(kind)) for kind in ("Type III", "Type I", "Type II")}
        for kind, chosen in runs.items():
            assert chosen.options[TERM_SELECTION] == SELECTED and chosen.options[MODEL_TERMS] == SELECTION
            assert (KEY in chosen.options) == (kind != "Type III"), chosen.options
            check_table(chosen, FACTORS, SELECTION, kind)
            assert list(chosen.result.tables)[:2] == [SHEETS[kind], "Model terms"], list(chosen.result.tables)
        base = runs["Type III"].result.tables
        for kind in ("Type I", "Type II"):
            tables = runs[kind].result.tables
            for name in tables:
                if name in (SHEETS[kind], "Effect sizes"):
                    continue
                pd.testing.assert_frame_equal(tables[name], base[name], obj=f"{kind}/{name}")
            effects = tables["Effect sizes"]
            anova = tables[SHEETS[kind]]
            for term in effects.index:
                assert np.isclose(effects.loc[term, "p"], anova.loc[term, "p"])
                ss = anova.loc[term, "SS"]
                assert np.isclose(effects.loc[term, "Partial eta squared"], ss / (ss + anova.loc["Residual", "SS"]))
            assert not np.allclose(effects["p"].to_numpy(float), base["Effect sizes"]["p"].to_numpy(float),
                                   rtol=1e-6, atol=0), (kind, effects["p"].tolist(), base["Effect sizes"]["p"].tolist())
        last = len(app.runs) - 1
        app.show("result", last)
        app.result_tabs.select(0)
        root.update()
        capture(root, f"window-anova-ss-selected-type-two-{start}.png")

        # --- A data edit and an exclusion refit the Type I analysis.
        keep = last - 1  # the Type I run of the selected-terms model
        app.show("result", keep)
        first_ss = app.runs[keep].result.tables["ANOVA (type I)"]["SS"].copy()
        app.edit_cell(0, 3, "16.5")
        wait()
        edited = app.runs[keep]
        assert not np.allclose(edited.result.tables["ANOVA (type I)"]["SS"], first_ss)
        check_table(edited, FACTORS, SELECTION, "Type I")
        app.show("data", TITLE)
        root.update()
        app.current_grid.select((1, 3))
        app.toggle_exclusion()
        wait()
        excluded = app.runs[keep]
        check_table(excluded, FACTORS, SELECTION, "Type I")
        assert excluded.result.tables["Model fit"].loc["N", "Value"] == len(current_frame().dropna())
        sums = excluded.result.tables["ANOVA (type I)"]["SS"].copy()

        # --- CSV of the ANOVA sheet and of Effect sizes.
        app.show("result", keep)
        app.result_tabs.select(result_index(excluded, "ANOVA (type I)"))
        csv_path = directory / "anova-ss-type-one.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        exported = pd.read_csv(csv_path)
        assert exported["Term"].tolist() == [*(label(term) for term in SELECTION), "Residual"], exported
        assert np.allclose(exported["SS"], sums.to_numpy())
        app.result_tabs.select(result_index(excluded, "Effect sizes"))
        effects_csv = directory / "anova-ss-effect-sizes.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(effects_csv)):
            app.export()
        assert pd.read_csv(effects_csv).iloc[:, 0].tolist() == [label(term) for term in SELECTION]

        # --- Save in Italian, reopen: the canonical recipe comes back and the same numbers are computed again.
        set_language("it")
        after = directory / "anova-ss-italian.alab"
        app.path = after
        assert app.save()
        stored = load_project(after)[TITLE].analyses
        assert stored[0][1].get(KEY) is None
        assert any(options.get(KEY) == "Type I" and options.get("Factors") == [GROUP, DOSE] for _, options in stored)
        assert any(options.get(KEY) == "Type II" for _, options in stored)
        set_language(start)
        app.import_file(after)
        root.update()
        app.open_sheet(("result", keep))
        wait()
        reopened = app.runs[keep]
        assert reopened.options[KEY] == "Type I" and reopened.options[TERM_SELECTION] == SELECTED
        assert list(reopened.result.tables)[0] == "ANOVA (type I)"
        assert np.allclose(reopened.result.tables["ANOVA (type I)"]["SS"], sums.to_numpy())

        # --- Use Result as Data copies the Type I sheet.
        app.show("result", keep)
        app.result_tabs.select(result_index(reopened, "ANOVA (type I)"))
        before_tables = set(app.tables)
        app.use_result_as_data()
        created = set(app.tables) - before_tables
        assert len(created) == 1
        copied = app.tables[created.pop()].raw
        names = copied["Term"].tolist() if "Term" in copied.columns else copied.iloc[:, 0].tolist()
        assert names == [*(label(term) for term in SELECTION), "Residual"], copied

        # --- Italian dialog: captions translate, the recipe stays canonical.
        def italian(dialog):
            configure_pair(dialog, "Type I")
            assert dialog.field_rows[KEY][0].cget("text") == "Somme dei quadrati"
            assert dialog.choice_bindings[KEY].combobox.get() == "Tipo I"
            assert dialog.controls[KEY][1].get() == "Type I"
            panel = panel_of(dialog)
            assert panel.caption.cget("text") == "Ordine dei fattori"
            assert panel.preview.cget("text").startswith("I termini entrano in quest’ordine"), panel.preview.cget("text")
            assert panel.up.cget("text") == "Su" and panel.down.cget("text") == "Giù"
            assert panel.note.cget("text").startswith("Il tipo I")
            dialog.fields.select(model_page(dialog))
            buttons(dialog)
            if start == "en":
                capture(dialog, "window-anova-ss-dialog-it.png")
            assert dialog.validate() is True
            assert dialog.result[1][KEY] == "Type I", dialog.result[1]
            dialog.result = None
            set_kind(dialog, "Type II")
            assert dialog.choice_bindings[KEY].combobox.get() == "Tipo II"
            assert panel.note.cget("text").startswith("Il tipo II")

        set_language("it")
        app.show("result", keep)  # Use Result as Data selected the copy; the dialog must see the plates
        drive(italian, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        set_language(start)

        # --- A model error does not crash: the dialog reopens on the Sums of squares field and the analysis stays.
        kept = app.runs[keep]
        kept_tables = {name: table.copy() for name, table in kept.result.tables.items()}

        def candidate(dialog):
            set_kind(dialog, "Type II")

        def recovered(dialog):
            assert dialog.error_label is not None
            assert words["numeric"] in dialog.error_label.cget("text"), dialog.error_label.cget("text")
            assert dialog.fields.tab(dialog.fields.select(), "text") == ui("Model")
            assert dialog.controls[KEY][1].get() == "Type II"
            assert dialog.result is None
            set_kind(dialog, "Type I")

        app.show("result", keep)
        drive(candidate, accept=True)
        with patch("analisi.anova_ss.anova_table", side_effect=FieldError(KEY, ERRORS["numeric"])):
            app.edit_analysis()
            state = when_open(recovered, accept=False)
            settle(state)
        assert app.runs[keep] is kept
        for name, table in kept_tables.items():
            pd.testing.assert_frame_equal(app.runs[keep].result.tables[name], table)
        assert "discarded" in app.status.get().casefold()

        # --- Correcting the type recovers the analysis on the same data.
        def correct(dialog):
            set_kind(dialog, "Type II")

        app.show("result", keep)
        drive(correct, accept=True)
        app.edit_analysis()
        assert not local_errors, local_errors
        wait()
        check_table(app.runs[keep], FACTORS, SELECTION, "Type II")
    finally:
        set_language(previous_language)
        root.geometry(previous_geometry)
        root.update_idletasks()
