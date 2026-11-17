"""Desktop smoke check for multifactor ANOVA residual diagnostics.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=anova-diagnostics``) calls
:func:`check_anova_diagnostics`. Sheet names and graph titles stay canonical English.
The dialog captions and the graph choice follow the active language.
"""
import threading
import traceback
from unittest.mock import patch

import pandas as pd
from matplotlib.collections import PathCollection
from matplotlib.colors import to_hex

from .anova_diagnostics import (
    ALPHA, ASSUMPTIONS, DIAGNOSTICS, GRAPH, GRAPH_QQ, GRAPH_RESIDUALS, QQ_LINE, SHEET,
)
from .data import Dataset, load_project, save_project
from .field_error import FieldError
from .graph_dialog import GraphFormatDialog
from .i18n import active_language, set_language, ui


TITLE = "Cells"
METHOD = "Multifactor ANOVA"
LEGACY = {
    "Response": "Y", "Factors": ["A", "B"], "Interaction order": 2,
    "Effect sizes": True, "Alpha": 0.05, "Compare marginal means by": "A",
}


def _frame():
    return pd.DataFrame({
        "A": ["a", "a", "a", "a", "b", "b", "b", "b"],
        "B": ["x", "x", "y", "y", "x", "x", "y", "y"],
        "Y": [1.0, 1.4, None, 2.4, 3.0, 3.3, 4.2, 4.8],
    })


def check_anova_diagnostics(root, app, directory, kit):
    from tkinter import filedialog, messagebox, ttk

    capture, pick, select = kit.capture, kit.pick_method, kit.select_columns
    wait = kit.wait_for_calculation
    previous_language = active_language()
    previous_scaling = float(root.tk.call("tk", "scaling"))
    previous_geometry = root.geometry()
    local_errors = []

    def find(kind, parent=None):
        for child in (parent or root).winfo_children():
            if isinstance(child, kind):
                return child
            found = find(kind, child)
            if found is not None:
                return found
        return None

    def drive(action, *, accept, kind=None):
        kind = kind or kit.AnalysisDialog

        def enter(tries=0):
            dialog = find(kind)
            if dialog is None or not dialog.winfo_viewable():
                if tries < 200:
                    root.after(40, lambda: enter(tries + 1))
                    return
                local_errors.append(f"{kind.__name__} did not open")
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

    def buttons(dialog):
        dialog.update_idletasks()
        found = []
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found.append(str(widget.cget("text")))
                    assert widget.winfo_ismapped() and widget.winfo_viewable(), widget.cget("text")
        assert ui("Run Analysis") in found and ui("Cancel") in found, found

    def reject(dialog, field, snippet):
        with patch.object(messagebox, "showerror") as shown:
            dialog.ok()
        assert shown.called, field
        assert snippet in shown.call_args.args[1], shown.call_args
        assert dialog.winfo_exists() and dialog.result is None
        dialog.update()
        assert str(dialog.fields.select()) == str(dialog.field_rows[field][1].master)
        assert dialog.focus_get() is dialog.field_rows[field][1], (field, dialog.focus_get())

    def observations(figure):
        return next(artist for artist in figure.axes[0].collections
                    if isinstance(artist, PathCollection) and artist.get_label() == "Observations")

    try:
        before = directory / "anova-diagnostics-before.alab"
        save_project(before, {TITLE: Dataset(_frame(), analyses=[(METHOD, dict(LEGACY))])})
        app.import_file(before)
        app.open_sheet(("result", 0))
        wait()
        legacy = app.runs[0]
        assert list(legacy.result.tables) == [
            "ANOVA (type III)", "Effect sizes", "Model fit", "Multiple comparisons"]
        assert legacy.result.figure is None
        assert DIAGNOSTICS not in legacy.options

        def configure(dialog):
            pick(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            select(dialog, "Factors", {"A", "B"})
            dialog.controls["Interaction order"][1].set("2")
            buttons(dialog)
            dialog.fields.select(dialog.field_rows[DIAGNOSTICS][0].master)
            capture(dialog, "window-anova-diag-fields-en.png")
            dialog.controls[DIAGNOSTICS][1].set(False)
            dialog.controls[GRAPH][1].set(GRAPH_RESIDUALS)
            dialog.show_anova_fields()
            reject(dialog, GRAPH, "Turn on ANOVA residual diagnostics")
            capture(dialog, "window-anova-diag-error-en.png")
            assert dialog.controls[GRAPH][1].get() == GRAPH_RESIDUALS
            dialog.controls[DIAGNOSTICS][1].set(True)
            dialog.controls[ASSUMPTIONS][1].set(True)
            dialog.show_anova_fields()
            dialog.controls[ALPHA][1].set("1")
            reject(dialog, ALPHA, "Alpha must be a finite number")
            assert dialog.controls[ALPHA][1].get() == "1"
            dialog.controls[ALPHA][1].set("0.05")
            dialog.controls[GRAPH][1].set(GRAPH_QQ)
            dialog.controls[QQ_LINE][1].set(False)
            dialog.controls[GRAPH][1].set(GRAPH_RESIDUALS)
            assert not dialog.field_rows[QQ_LINE][1].grid_info()
            assert dialog.validate() is True
            assert QQ_LINE not in dialog.result[1]
            dialog.result = None
            dialog.controls[GRAPH][1].set(GRAPH_QQ)
            assert dialog.controls[QQ_LINE][1].get() is True
            assert dialog.field_rows[QQ_LINE][1].grid_info()
            dialog.controls[ASSUMPTIONS][1].set(False)
            dialog.show_anova_fields()
            dialog.controls[ALPHA][1].set("nope")
            assert dialog.validate() is True
            assert ALPHA not in dialog.result[1]
            dialog.result = None
            dialog.controls[ASSUMPTIONS][1].set(True)
            dialog.show_anova_fields()
            dialog.controls[ALPHA][1].set("0.05")
            dialog.controls[GRAPH][1].set(GRAPH_QQ)
            dialog.controls[QQ_LINE][1].set(True)
            capture(dialog, "window-anova-diag-ready-en.png")
            buttons(dialog)

        drive(configure, accept=True)
        app.choose_analysis()
        assert not local_errors, local_errors
        wait()
        run = app.runs[1]
        assert run.options[DIAGNOSTICS] is True
        assert run.options[ASSUMPTIONS] is True
        assert run.options[ALPHA] == 0.05
        assert run.options[GRAPH] == GRAPH_QQ
        assert run.options[QQ_LINE] is True
        assert run.result.tables[SHEET]["Source row"].tolist() == [0, 1, 3, 4, 5, 6, 7]
        assert run.result.figure is not None
        app.show("result", 1)
        app.result_tabs.select(list(run.result.tables).index(SHEET))
        root.update()
        capture(root, "window-anova-diag-results-en.png")
        app.show("graph", 1)
        root.update()
        capture(root, "window-anova-diag-graph-en.png")
        before_sse = float((run.result.tables[SHEET]["Residual"] ** 2).sum())

        app.show("graph", 1)
        app.edit_cell(0, 2, "9.5")
        wait()
        edited = app.runs[1].result.tables[SHEET]
        assert edited["Source row"].tolist() == [0, 1, 3, 4, 5, 6, 7]
        assert float((edited["Residual"] ** 2).sum()) != before_sse
        app.show("data", TITLE)
        root.update()
        app.current_grid.select((4, 2))
        app.toggle_exclusion()
        wait()
        assert app.runs[1].result.tables[SHEET]["Source row"].tolist() == [0, 1, 3, 5, 6, 7]

        after = directory / "anova-diagnostics-after.alab"
        app.path = after
        assert app.save()
        app.import_file(after)
        # import_file lands on the data sheet. Let that navigator selection settle,
        # then open the graph before any later visit to the worksheet.
        root.update()
        app.open_sheet(("graph", 1))
        wait()
        assert app.selected == ("graph", 1), app.selected
        assert app.runs[1].options[GRAPH] == GRAPH_QQ
        assert app.runs[1].result.tables[SHEET]["Source row"].tolist() == [0, 1, 3, 5, 6, 7]
        reloaded = load_project(after)
        assert reloaded[TITLE].analyses[1][1][DIAGNOSTICS] is True
        assert reloaded[TITLE].analyses[1][1][GRAPH] == GRAPH_QQ

        app.show("result", 1)
        app.result_tabs.select(list(app.runs[1].result.tables).index(SHEET))
        before_tables = set(app.tables)
        app.use_result_as_data()
        created = set(app.tables) - before_tables
        assert len(created) == 1
        copied = app.tables[created.pop()].raw
        assert copied["Source row"].tolist() == [0, 1, 3, 5, 6, 7]
        app.show("result", 1)
        app.result_tabs.select(list(app.runs[1].result.tables).index(SHEET))
        csv_path = directory / "anova-diagnostics.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        assert pd.read_csv(csv_path)["Source row"].tolist() == [0, 1, 3, 5, 6, 7]

        app.show("graph", 1)
        for name, magic in (("anova-diagnostics.svg", b"<svg"), ("anova-diagnostics.png", b"\x89PNG"),
                            ("anova-diagnostics.pdf", b"%PDF")):
            target = directory / name
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            payload = target.read_bytes()
            assert payload.startswith(magic) or magic in payload[:400], name

        original_color = to_hex(observations(app.runs[1].result.figure).get_facecolor()[0])

        def format_cancel(dialog):
            dialog.notebook.select(2)
            names = list(dialog.series_selector.cget("values"))
            index = next(i for i, name in enumerate(names) if "Observations" in name)
            dialog.series_selector.current(index)
            dialog._select_series()
            dialog.series_fields["color"].set("#112233")

        drive(format_cancel, accept=False, kind=GraphFormatDialog)
        app.format_graph()
        assert not local_errors, local_errors
        assert to_hex(observations(app.runs[1].result.figure).get_facecolor()[0]) == original_color

        def format_apply(dialog):
            dialog.notebook.select(2)
            names = list(dialog.series_selector.cget("values"))
            index = next(i for i, name in enumerate(names) if "Observations" in name)
            dialog.series_selector.current(index)
            dialog._select_series()
            dialog.series_fields["color"].set("#112233")

        drive(format_apply, accept=True, kind=GraphFormatDialog)
        app.format_graph()
        assert not local_errors, local_errors
        assert to_hex(observations(app.runs[1].result.figure).get_facecolor()[0]) == "#112233"

        app.show("graph", 1)
        app.toggle_inspector()
        inspector = app.inspector
        assert inspector is not None
        root.update()
        inspector.select_group("scatter:1:Observations")
        inspector.vars["element:color"].set("#abcdef")
        inspector._now("element:color")
        inspector.cancel_button.invoke()
        root.update()
        assert to_hex(observations(app.runs[1].result.figure).get_facecolor()[0]) == "#112233"
        app.toggle_inspector()
        inspector = app.inspector
        inspector.select_group("scatter:1:Observations")
        inspector.vars["element:color"].set("#225533")
        inspector._now("element:color")
        assert inspector.apply()
        inspector.cancel_button.invoke()
        root.update()
        assert to_hex(observations(app.runs[1].result.figure).get_facecolor()[0]) == "#225533"

        runs_before_cancel = len(app.runs)

        def italian(dialog):
            pick(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            select(dialog, "Factors", {"A", "B"})
            dialog.controls["Interaction order"][1].set("2")
            assert dialog.fields.tab(dialog.field_rows[DIAGNOSTICS][0].master, "text") == "Diagnostica"
            assert dialog.field_rows[DIAGNOSTICS][0].cget("text") == "Diagnostica dei residui ANOVA"
            dialog.controls[DIAGNOSTICS][1].set(True)
            dialog.controls[GRAPH][1].set(GRAPH_QQ)
            assert dialog.controls[GRAPH][1].get() == GRAPH_QQ
            assert dialog.choice_bindings[GRAPH].combobox.get() == "Q–Q normale"
            dialog.controls[ASSUMPTIONS][1].set(True)
            dialog.show_anova_fields()
            dialog.controls[ALPHA][1].set("0,01")
            dialog.fields.select(dialog.field_rows[DIAGNOSTICS][0].master)
            capture(dialog, "window-anova-diag-fields-it.png")
            assert dialog.validate() is True
            assert dialog.result[1][ALPHA] == 0.01
            dialog.result = None
            dialog.controls[DIAGNOSTICS][1].set(False)
            dialog.controls[GRAPH][1].set(GRAPH_RESIDUALS)
            reject(dialog, GRAPH, "Attiva la diagnostica dei residui ANOVA")
            capture(dialog, "window-anova-diag-error-it.png")
            buttons(dialog)
            dialog.result = None

        set_language("it")
        drive(italian, accept=False)
        app.choose_analysis()
        assert not local_errors, local_errors
        assert len(app.runs) == runs_before_cancel
        app.show("result", 1)
        root.update()
        capture(root, "window-anova-diag-results-it.png")
        app.show("graph", 1)
        root.update()
        capture(root, "window-anova-diag-graph-it.png")
        set_language("en")

        def turn_off(dialog):
            dialog.controls[DIAGNOSTICS][1].set(False)
            dialog.controls[ASSUMPTIONS][1].set(False)
            dialog.controls[GRAPH][1].set("None")
            dialog.show_anova_fields()
            assert not dialog.field_rows[ALPHA][1].grid_info()
            assert not dialog.field_rows[QQ_LINE][1].grid_info()

        app.show("result", 1)
        drive(turn_off, accept=True)
        app.edit_analysis()
        assert not local_errors, local_errors
        wait()
        assert list(app.runs[1].result.tables) == ["ANOVA (type III)"]
        assert app.runs[1].result.figure is None
        assert app.runs[1].options[DIAGNOSTICS] is False
        assert app.runs[1].options[ASSUMPTIONS] is False
        assert app.runs[1].options[GRAPH] == "None"
        assert ALPHA not in app.runs[1].options and QQ_LINE not in app.runs[1].options

        if app.runs[0].result is None:
            app.open_sheet(("result", 0))
            wait()
        kept = app.runs[0]
        kept_tables = {name: frame.copy() for name, frame in kept.result.tables.items()}

        def candidate(dialog):
            dialog.controls[DIAGNOSTICS][1].set(True)
            dialog.controls[GRAPH][1].set(GRAPH_RESIDUALS)

        def recovered(dialog):
            assert dialog.error_label is not None and "Injected" in dialog.error_label.cget("text")
            assert str(dialog.fields.select()) == str(dialog.field_rows[GRAPH][1].master)
            assert dialog.controls[GRAPH][1].get() == GRAPH_RESIDUALS
            assert dialog.result is None

        app.show("result", 0)
        drive(candidate, accept=True)
        with patch("analisi.workbench.build_anova_diagnostics",
                   side_effect=FieldError(GRAPH, "Injected worker failure")):
            app.edit_analysis()
            state = when_open(recovered, accept=False)
            settle(state)
        assert app.runs[0] is kept
        for name, frame in kept_tables.items():
            pd.testing.assert_frame_equal(app.runs[0].result.tables[name], frame)
        assert "discarded" in app.status.get().casefold()

        source = app.tables[TITLE].frame(mask_excluded=True).copy()
        gate, entered = threading.Event(), threading.Event()
        from analisi import workbench as anova_workbench
        real_build = anova_workbench.build_anova_diagnostics

        def hold(*args, **kwargs):
            entered.set()
            gate.wait(15)
            return real_build(*args, **kwargs)

        def arm(dialog):
            dialog.controls[DIAGNOSTICS][1].set(True)
            dialog.controls[GRAPH][1].set(GRAPH_RESIDUALS)

        try:
            with patch("analisi.workbench.build_anova_diagnostics", side_effect=hold):
                drive(arm, accept=True)
                app.edit_analysis()
                assert entered.wait(10), "the worker did not reach the diagnostic build"
                assert app.pending is not None
                assert app.prepare_project_change() is False
                pd.testing.assert_frame_equal(app.tables[TITLE].frame(mask_excluded=True), source)
        finally:
            gate.set()
        wait()
        assert not local_errors, local_errors

        def dpi(dialog, shot):
            pick(dialog, METHOD)
            dialog.fields.select(dialog.field_rows[DIAGNOSTICS][0].master)
            buttons(dialog)
            dialog.update_idletasks()
            lines = [f"scaling {root.tk.call('tk', 'scaling')}"]
            for child in dialog.winfo_children():
                for widget in child.winfo_children():
                    if isinstance(widget, ttk.Button):
                        lines.append(
                            f"{widget.cget('text')} x={widget.winfo_rootx()} y={widget.winfo_rooty()} "
                            f"w={widget.winfo_width()} h={widget.winfo_height()} "
                            f"mapped={int(widget.winfo_ismapped())} viewable={int(widget.winfo_viewable())}")
            (directory / f"{shot}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            capture(dialog, shot)

        for factor, name in ((1.25, "window-anova-diag-dpi-125-emulato.png"),
                             (1.5, "window-anova-diag-dpi-150-emulato.png")):
            root.tk.call("tk", "scaling", factor)
            root.update_idletasks()
            drive(lambda dialog, shot=name: dpi(dialog, shot), accept=False)
            app.choose_analysis()
            assert not local_errors, local_errors
        assert len(app.runs) == runs_before_cancel
    finally:
        set_language(previous_language)
        root.tk.call("tk", "scaling", previous_scaling)
        root.geometry(previous_geometry)
        root.update_idletasks()
