"""Desktop smoke for Compare two variances.

Widgets are driven and events are generated. This is not a manual pointer
session and it is not a Windows run. Themes are chosen by the process that
launches Trama; this module does not switch Standard and Modern in one process.
"""
import json
import math
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch
import time

import pandas as pd

from .grid_data import paste_block
from .i18n import active_language, set_language, ui
from .presentation import Layout
from .variance_ratio import (
    FIRST, GRAPH, GRAPH_VARIANCE, LEVEL, METHOD, SECOND, SHEET, SHOW,
)


TITLE = "Samples"
GROUPS = "Groups"
FLAT = "Flat"


def _samples():
    return pd.DataFrame({"A": [0.0, 2.0, 4.0], "B": [0.0, 1.0, 2.0]})


def _groups():
    return pd.DataFrame({
        "Y": [0.0, 2.0, 4.0, 0.0, 1.0, 2.0],
        "G": ["A", "A", "A", "B", "B", "B"],
        "P": [1.0, math.exp(2), math.exp(4), None, None, None],
        "Q": [1.0, math.exp(1), math.exp(2), None, None, None],
    })


def _flat():
    return pd.DataFrame({"Y": [1.0, 1.0, 1.0, 0.0, 1.0, 2.0], "G": ["A", "A", "A", "B", "B", "B"]})


def check_variance_ratio(root, app, directory, kit):
    directory = Path(directory)
    previous_language = active_language()

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
        holder = {}

        def enter():
            dialog = find()
            if dialog is None or not dialog.winfo_viewable():
                if time.monotonic() < deadline:
                    root.after(40, enter)
                    return
                holder["error"] = TimeoutError("The analysis dialog did not open.")
                return
            try:
                dialog.update_idletasks()
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

        deadline = time.monotonic() + 20
        root.after(200, enter)
        return holder

    def finish(holder):
        if "error" in holder:
            raise holder["error"]

    def buttons(dialog):
        dialog.update_idletasks()
        found = {}
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found[widget.cget("text")] = widget
        height, width = root.winfo_screenheight(), root.winfo_screenwidth()
        for name in ("Run Analysis", "Cancel"):
            widget = found[ui(name)]
            assert widget.winfo_ismapped() and widget.winfo_viewable(), name
            assert 0 <= widget.winfo_rootx() and widget.winfo_rootx() + widget.winfo_width() <= width, name
            assert 0 <= widget.winfo_rooty() and widget.winfo_rooty() + widget.winfo_height() <= height, name

    def reject(dialog, field, snippet):
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        message = shown.call_args.args[1]
        assert snippet in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), (field, message)
        dialog.result = None
        return message

    def close_dialog(dialog):
        try:
            dialog.result = None
            dialog.cancel()
        except Exception:
            pass

    def show_option(dialog, field):
        """Map the notebook page that holds a control. A gridded widget on another page is not mapped."""
        dialog.fields.select(dialog.field_rows[field][0].master)
        dialog.update_idletasks()

    try:
        project = directory / "variance-ratio-before.alab"
        kit.save_project(project, {
            TITLE: kit.Dataset(_samples()),
            GROUPS: kit.Dataset(_groups()),
            FLAT: kit.Dataset(_flat()),
        })
        app.import_file(project)
        root.update()
        app.show("data", TITLE)
        runs_before = len(app.runs)

        def cancel(dialog):
            kit.pick_method(dialog, METHOD)
            dialog.controls[FIRST][1].set("A")
            dialog.controls[SECOND][1].set("B")
            dialog.controls[LEVEL][1].set("95")
            buttons(dialog)

        holder = drive(cancel, accept=False)
        app.choose_analysis()
        finish(holder)
        assert len(app.runs) == runs_before

        def enable(dialog):
            kit.pick_method(dialog, METHOD)
            dialog.controls[FIRST][1].set("A")
            dialog.controls[SECOND][1].set("A")
            buttons(dialog)
            kit.capture(dialog, "window-variance-ratio-fields-en.png")
            reject(dialog, SECOND, "different")
            kit.capture(dialog, "window-variance-ratio-error-en.png")
            dialog.controls[SECOND][1].set("B")
            dialog.controls[LEVEL][1].set("100")
            reject(dialog, LEVEL, "less than 100")
            dialog.controls[LEVEL][1].set("95")
            dialog.controls["Distribution"][1].set("Lognormal")
            reject(dialog, FIRST, "strictly positive")
            dialog.controls["Distribution"][1].set("Normal")
            dialog.controls[GRAPH][1].set(GRAPH_VARIANCE)
            assert "does not choose" in dialog.variance_ratio_note.cget("text")
            buttons(dialog)
            kit.capture(dialog, "window-variance-ratio-ready-en.png")

        holder = drive(enable)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        run = app.runs[0]
        assert run.method == METHOD and run.options[GRAPH] == GRAPH_VARIANCE
        assert abs(float(run.result.tables[SHEET].at["p", "Value"]) - 0.4) < 1e-9
        assert abs(float(run.result.tables[SHEET].at["Variance ratio", "Value"]) - 4) < 1e-9
        assert run.result.figure is not None
        app.show("result", 0)
        kit.capture(root, "window-variance-ratio-results-en.png")
        app.show("graph", 0)
        root.update()
        kit.capture(root, "window-variance-ratio-graph-en.png")

        app.show("data", TITLE)
        app.edit_cell(1, 1, "3")
        kit.wait_for_calculation()
        changed = float(app.runs[0].result.tables[SHEET].at["Variance ratio", "Value"])
        assert changed != 4
        app.edit_cell(1, 1, "1")
        kit.wait_for_calculation()
        assert abs(float(app.runs[0].result.tables[SHEET].at["p", "Value"]) - 0.4) < 1e-9

        # One paste makes the first sample constant while this is the only analysis of the table.
        # Cancel must keep the last successful result. A second analysis on the same sheet would
        # schedule another recovery dialog after this one closes.
        kept = app.runs[0].result.tables[SHEET].at["p", "Value"]
        state = {"done": False, "quiet": 0}

        def watch(tries=0):
            dialog = find()
            label = getattr(dialog, "error_label", None) if dialog is not None else None
            text = label.cget("text") if label is not None else ""
            if dialog is not None and "zero variance" in text:
                try:
                    assert dialog.initial_focus == dialog.field_rows[FIRST][1]
                    buttons(dialog)
                    if not state.get("shot"):
                        kit.capture(dialog, "window-variance-ratio-reopen-en.png")
                        state["shot"] = True
                    state["recovered"] = True
                except Exception as error:
                    state["error"] = error
                    close_dialog(dialog)
                    state["done"] = True
                    return
                close_dialog(dialog)
                state["quiet"] = 0
                root.after(40, lambda: watch(tries + 1))
                return
            if state.get("recovered") and dialog is None and app.pending is None:
                state["quiet"] += 1
                if state["quiet"] >= 8:
                    state["done"] = True
                    return
            if tries > 500:
                state["error"] = TimeoutError("The constant sample did not reopen the dialog.")
                state["done"] = True
                return
            root.after(40, lambda: watch(tries + 1))

        dataset = app.get_dataset()
        before = app.worksheet_state(dataset)
        paste_block(dataset, 1, 0, [["0"], ["0"]])
        app.finish_worksheet_edit(dataset, before, "Edit cells")
        root.after(40, watch)
        deadline = time.monotonic() + 20
        while not state["done"]:
            if time.monotonic() > deadline:
                raise TimeoutError("The worker recovery did not finish.")
            root.update()
            time.sleep(0.02)
        if state.get("error"):
            raise state["error"]
        assert state.get("recovered") is True
        assert app.runs[0].result.tables[SHEET].at["p", "Value"] == kept
        app.edit_cell(1, 0, "2")
        kit.wait_for_calculation()
        app.edit_cell(2, 0, "4")
        kit.wait_for_calculation()
        assert abs(float(app.runs[0].result.tables[SHEET].at["p", "Value"]) - 0.4) < 1e-9

        app.show("data", GROUPS)

        def t_test(dialog):
            kit.pick_method(dialog, "t-test")
            dialog.controls["Response"][1].set("Y")
            dialog.controls["Group"][1].set("G")
            dialog.controls["Design"][1].set("Paired")
            show_option(dialog, SHOW)
            assert not dialog.field_rows[SHOW][1].winfo_ismapped()
            dialog.controls["Design"][1].set("Welch")
            show_option(dialog, SHOW)
            assert dialog.field_rows[SHOW][1].winfo_ismapped()
            assert "does not choose" in dialog.variance_ratio_note.cget("text")
            dialog.controls[SHOW][1].set(True)
            buttons(dialog)
            kit.capture(dialog, "window-variance-ratio-ttest-en.png")

        holder = drive(t_test)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        compared = app.runs[1]
        assert compared.options[SHOW] is True
        assert abs(float(compared.result.tables[SHEET].at["p", "Value"]) - 0.4) < 1e-9
        assert "t" in compared.result.tables["t-test"].index

        def lognormal(dialog):
            kit.pick_method(dialog, "Lognormal t-test")
            dialog.controls["Design"][1].set("Welch")
            dialog.controls["First"][1].set("P")
            dialog.controls["Second"][1].set("Q")
            dialog.controls["Graph"][1].set("None")
            show_option(dialog, SHOW)
            assert dialog.field_rows[SHOW][1].winfo_ismapped()
            dialog.controls[SHOW][1].set(True)
            buttons(dialog)

        holder = drive(lognormal)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        logged = app.runs[2]
        assert abs(float(logged.result.tables[SHEET].at["Variance ratio", "Value"]) - 4) < 1e-9
        assert "t" in logged.result.tables["Lognormal test"].columns

        app.show("data", FLAT)

        def flat(dialog):
            kit.pick_method(dialog, "t-test")
            dialog.controls["Design"][1].set("Student")
            dialog.controls["Response"][1].set("Y")
            dialog.controls["Group"][1].set("G")
            dialog.controls[SHOW][1].set(True)

        holder = drive(flat)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        explained = app.runs[3]
        assert "t" in explained.result.tables["t-test"].index
        assert "zero variance" in explained.result.tables[SHEET].at["Reason", "Value"]

        set_language("it")
        app.show("data", TITLE)

        def italian(dialog):
            kit.pick_method(dialog, METHOD)
            dialog.controls[FIRST][1].set("A")
            dialog.controls[SECOND][1].set("B")
            dialog.controls[LEVEL][1].set("95,0")
            dialog.controls["Distribution"][1].set("Normal")
            dialog.controls[GRAPH][1].set(GRAPH_VARIANCE)
            assert dialog.field_rows[FIRST][0].cget("text") == "Prima variabile"
            assert dialog.controls["Distribution"][1].get() == "Normal"
            assert "Normale" in dialog.field_rows["Distribution"][1].get()
            assert "non sceglie" in dialog.variance_ratio_note.cget("text")
            buttons(dialog)
            kit.capture(dialog, "window-variance-ratio-fields-it.png")
            dialog.controls[LEVEL][1].set("100")
            reject(dialog, LEVEL, "minore di 100")
            kit.capture(dialog, "window-variance-ratio-error-it.png")
            dialog.controls[LEVEL][1].set("95,0")

        holder = drive(italian)
        app.choose_analysis()
        finish(holder)
        kit.wait_for_calculation()
        italian_run = app.runs[4]
        assert italian_run.options[LEVEL] == 95.0
        assert "Confronta due varianze" in italian_run.result.figure.axes[0].get_title()
        app.show("graph", 4)
        root.update()
        kit.capture(root, "window-variance-ratio-graph-it.png")
        set_language("en")

        app.show("data", TITLE)
        app.current_grid.select((0, 0))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        excluded = app.runs[0].result.tables[SHEET]
        # Exclusion is one cell. The other sample keeps its three observations.
        assert int(excluded.at["N first", "Value"]) == 2
        assert int(excluded.at["N second", "Value"]) == 3

        saved = directory / "variance-ratio-after.alab"
        app.path = saved
        assert app.save()
        app.import_file(saved)
        root.update()
        sections = {name: items for name, items, *_rest in app.sheet_sections()}
        assert any(ref[0] == "graph" for _name, ref in sections["Graphs"])
        app.open_sheet(("graph", 0))
        kit.wait_for_calculation()
        assert app.runs[0].result.figure is not None
        assert abs(float(app.runs[0].result.tables[SHEET].at["Variance ratio", "Value"]) - 4) > 1e-9

        app.show("result", 0)
        app.result_tabs.select(0)
        csv_path = directory / "variance-ratio.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        exported = csv_path.read_text(encoding="utf-8-sig")
        header = exported.splitlines()[0]
        assert header.split(",")[1] == "Value"
        assert "Variance ratio" in exported
        app.use_result_as_data()
        assert "Variance ratio" in set(app.tables[SHEET].raw["Label"])

        app.show("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = directory / f"variance-ratio.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 500, suffix
        assert b"<svg" in (directory / "variance-ratio.svg").read_bytes()
        assert (directory / "variance-ratio.pdf").read_bytes().startswith(b"%PDF")

        app.layouts.append(Layout("Variance layout", 1, [app.runs[0].reference]))
        app.refresh_navigator()
        app.show("layout", 0)
        root.update()
        layout_pdf = directory / "variance-layout.pdf"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(layout_pdf)):
            app.export()
        assert layout_pdf.read_bytes().startswith(b"%PDF")
        kit.capture(root, "window-variance-ratio-layout.png")

        (directory / "display.json").write_text(json.dumps({
            "width": root.winfo_screenwidth(),
            "height": root.winfo_screenheight(),
            "scaling": float(root.tk.call("tk", "scaling")),
            "widget_driven": True,
        }) + "\n", encoding="utf-8")
    finally:
        set_language(previous_language)
