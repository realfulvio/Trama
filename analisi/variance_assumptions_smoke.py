"""Desktop smoke for ordinary one-way variance checks.

The ANOVA result has no figure. This smoke does not invent one. CSV export,
project reopen and Use Result as Data cover the sheets that do exist.
"""
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch
import json
import time

import pandas as pd

from .field_error import FieldError
from .i18n import active_language, set_language, ui
from .variance_assumptions import ALPHA, BARTLETT, BROWN, GROUPS, SHEET
from . import variance_assumptions

METHOD = "One-way ANOVA"
TITLE = "Cells"


def _frame():
    rows = [("A", 1.0), ("A", 2.0), ("A", 2.5), ("A", 3.0), ("A", 4.0), ("A", 5.0),
            ("B", 2.0), ("B", 2.4), ("B", 2.7), ("B", 3.1), ("B", 3.4), ("B", 3.8), ("B", 4.2),
            ("C", 0.0), ("C", 3.0), ("C", 5.0), ("C", 8.0), ("C", 11.0),
            ("A", None), (None, 12.0)]
    return pd.DataFrame(rows, columns=["Group", "Y"])


def check_variance_assumptions(root, app, directory, kit):
    directory = Path(directory)
    previous_language = active_language()
    previous_scaling = float(root.tk.call("tk", "scaling"))
    legacy = {"Response": "Y", "Group": "Group", "Method": "Ordinary", "Post-hoc": "None"}

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

        deadline = time.monotonic() + 8
        root.after(200, enter)
        return holder

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
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        assert str(dialog.controls[field][1].get()), field
        dialog.result = None
        return message

    def finish(holder):
        if "error" in holder:
            raise holder["error"]

    def release_to_worker(dialog):
        """Let Run Analysis succeed, then drop the cached fit so the worker runs it."""
        real = dialog.validate

        def wrapped():
            accepted = real()
            if accepted:
                dialog.processing_result = None
            return accepted

        dialog.validate = wrapped

    def close_dialog(dialog):
        try:
            dialog.result = None
            dialog.cancel()
        except Exception:
            pass

    try:
        before = directory / "variance-assumptions-before.alab"
        kit.save_project(before, {TITLE: kit.Dataset(_frame(), analyses=[(METHOD, dict(legacy))])})
        app.import_file(before)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        old = app.runs[0]
        assert BROWN not in old.options and BARTLETT not in old.options
        assert list(old.result.tables) == ["ANOVA"]
        assert old.result.figure is None

        def enable(dialog):
            kit.pick_method(dialog, METHOD)
            dialog.controls["Response"][1].set("Y")
            dialog.controls["Group"][1].set("Group")
            dialog.controls["Post-hoc"][1].set("None")
            dialog.controls["Method"][1].set("Ordinary")
            dialog.fields.select(dialog.field_rows[BROWN][0].master)
            buttons(dialog)
            kit.capture(dialog, "window-variance-fields-en.png")
            dialog.controls[BROWN][1].set(True)
            dialog.controls[ALPHA][1].set("1")
            reject(dialog, ALPHA, "finite number")
            assert dialog.controls[ALPHA][1].get() == "1"
            kit.capture(dialog, "window-variance-error-en.png")
            dialog.controls[ALPHA][1].set("0.05")
            dialog.controls[BARTLETT][1].set(True)
            dialog.controls["Method"][1].set("Welch")
            dialog.update_idletasks()
            assert not dialog.field_rows[BROWN][1].winfo_ismapped()
            dialog.controls[ALPHA][1].set("nope")
            assert dialog.validate() is True
            assert dialog.result[1][BROWN] is True and dialog.result[1][BARTLETT] is True
            assert ALPHA not in dialog.result[1]
            dialog.result = None
            dialog.controls["Method"][1].set("Ordinary")
            dialog.update_idletasks()
            assert dialog.controls[BROWN][1].get()
            assert dialog.controls[BARTLETT][1].get()
            assert dialog.controls[ALPHA][1].get() == "nope"
            dialog.controls[ALPHA][1].set("0.05")
            dialog.fields.select(dialog.field_rows[BROWN][0].master)
            buttons(dialog)
            kit.capture(dialog, "window-variance-ready-en.png")

        holder = drive(enable)
        app.edit_analysis()
        finish(holder)
        kit.wait_for_calculation()
        run = app.runs[0]
        assert run.options[BROWN] is True and run.options[BARTLETT] is True
        assert run.options[ALPHA] == 0.05
        assert run.options["Method"] == "Ordinary"
        assert [SHEET, GROUPS] == list(run.result.tables)[-2:]
        assert run.result.tables[GROUPS]["N"].tolist() == [6, 7, 5]
        assert run.result.figure is None
        statistic = float(run.result.tables[SHEET]["Statistic"].iloc[0])
        app.show("result", 0)
        app.result_tabs.select(1)
        kit.capture(root, "window-variance-results-en.png")

        app.edit_cell(0, 1, "9.5")
        kit.wait_for_calculation()
        changed = app.runs[0].result.tables
        assert float(changed[SHEET]["Statistic"].iloc[0]) != statistic
        assert changed[GROUPS]["N"].tolist() == [6, 7, 5]
        app.show("data", TITLE)
        app.current_grid.select((1, 1))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        excluded = app.runs[0].result.tables[GROUPS]
        assert excluded["N"].tolist() == [5, 7, 5]
        assert excluded["Group"].tolist() == ["A", "B", "C"]

        after = directory / "variance-assumptions-after.alab"
        snapshot = app.runs[0].result.tables[SHEET].copy()
        app.path = after
        assert app.save()
        app.import_file(after)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        reopened = app.runs[0]
        assert reopened.options[BROWN] is True and reopened.options["Method"] == "Ordinary"
        pd.testing.assert_frame_equal(reopened.result.tables[SHEET], snapshot)
        assert list(reopened.result.tables) == ["ANOVA", SHEET, GROUPS]

        app.show("result", 0)
        app.result_tabs.select(1)
        target = directory / "variance-assumptions.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target)
        assert exported["Test"].tolist()[0] == "Brown–Forsythe (median Levene)"
        app.use_result_as_data()
        assert "Statistic" in app.tables[SHEET].raw.columns
        app.show("result", 0)
        app.result_tabs.select(2)
        app.use_result_as_data()
        assert list(app.tables[GROUPS].raw.columns)[:3] == ["Group", "N", "Mean"]

        set_language("it")

        def italian(dialog):
            dialog.controls["Response"][1].set("Y")
            dialog.controls["Group"][1].set("Group")
            dialog.controls["Post-hoc"][1].set("None")
            dialog.controls["Method"][1].set("Ordinary")
            dialog.controls[BROWN][1].set(True)
            dialog.controls[BARTLETT][1].set(True)
            dialog.controls[ALPHA][1].set("0,01")
            dialog.fields.select(dialog.field_rows[BROWN][0].master)
            assert dialog.field_rows[BROWN][0].cget("text") == "Test di Brown–Forsythe sulle varianze"
            assert "mediana" in dialog.variance_note.cget("text")
            buttons(dialog)
            kit.capture(dialog, "window-variance-fields-it.png")
            assert dialog.validate() is True
            assert dialog.result[1][ALPHA] == 0.01
            assert dialog.result[1][BROWN] is True
            dialog.result = None
            dialog.controls[ALPHA][1].set("nope")
            reject(dialog, ALPHA, "compreso tra 0 e 1")
            kit.capture(dialog, "window-variance-error-it.png")
            buttons(dialog)

        app.show("result", 0)
        holder = drive(italian, accept=False)
        app.edit_analysis()
        finish(holder)
        assert app.runs[0].options[ALPHA] == 0.05
        app.show("result", 0)
        app.result_tabs.select(1)
        kit.capture(root, "window-variance-results-it.png")
        set_language("en")

        kept = {name: frame.copy() for name, frame in app.runs[0].result.tables.items()}
        calls = {"n": 0}
        real_sheets = variance_assumptions.sheets

        def fail_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise FieldError(ALPHA, "Injected worker failure")
            return real_sheets(*args, **kwargs)

        def arm(dialog):
            dialog.controls[BROWN][1].set(True)
            dialog.controls[ALPHA][1].set("0.05")
            release_to_worker(dialog)

        state = {"done": False}

        def watch_recovery(tries=0):
            dialog = find()
            label = getattr(dialog, "error_label", None) if dialog is not None else None
            if label is None or "Injected" not in label.cget("text"):
                if tries > 400:
                    state["error"] = TimeoutError("The worker field error did not reopen the dialog.")
                    state["done"] = True
                    return
                root.after(40, lambda: watch_recovery(tries + 1))
                return
            try:
                assert dialog.initial_focus == dialog.field_rows[ALPHA][1]
                state["recovered"] = True
            except Exception as error:
                state["error"] = error
            close_dialog(dialog)
            state["done"] = True

        with patch("analisi.variance_assumptions.sheets", fail_once):
            holder = drive(arm)
            app.edit_analysis()
            finish(holder)
            root.after(40, watch_recovery)
            deadline = time.monotonic() + 20
            while not state["done"] or app.pending is not None:
                if time.monotonic() > deadline:
                    raise TimeoutError("The worker recovery did not finish.")
                root.update()
                time.sleep(0.02)
        if state.get("error"):
            raise state["error"]
        assert state.get("recovered") is True
        for name, frame in kept.items():
            pd.testing.assert_frame_equal(app.runs[0].result.tables[name], frame)

        def turn_off(dialog):
            dialog.controls["Method"][1].set("Ordinary")
            dialog.controls[BROWN][1].set(False)
            dialog.controls[BARTLETT][1].set(False)
            assert not dialog.field_rows[ALPHA][1].winfo_ismapped()

        holder = drive(turn_off)
        app.edit_analysis()
        finish(holder)
        kit.wait_for_calculation()
        quiet = app.runs[0]
        assert quiet.options[BROWN] is False and quiet.options[BARTLETT] is False
        assert list(quiet.result.tables) == ["ANOVA"]
        assert quiet.result.figure is None

        state = {"worker": False}
        entered, gate = Event(), Event()

        def pause(*args, **kwargs):
            if not state["worker"]:
                state["worker"] = True
                return real_sheets(*args, **kwargs)
            entered.set()
            if not gate.wait(15):
                raise TimeoutError("The variance worker was not released.")
            return real_sheets(*args, **kwargs)

        def reenable(dialog):
            dialog.controls[BROWN][1].set(True)
            dialog.controls[BARTLETT][1].set(True)
            dialog.controls[ALPHA][1].set("0.05")
            release_to_worker(dialog)

        source = app.tables[TITLE].raw.copy()
        with patch("analisi.variance_assumptions.sheets", pause):
            holder = drive(reenable)
            app.edit_analysis()
            finish(holder)
            assert entered.wait(5)
            assert app.pending is not None
            assert app.prepare_project_change() is False
            pd.testing.assert_frame_equal(app.tables[TITLE].raw, source)
            assert app.runs[0].result is not None
            gate.set()
            kit.wait_for_calculation()
        assert app.runs[0].options[BROWN] is True
        assert SHEET in app.runs[0].result.tables

        def dpi(dialog, shot):
            kit.pick_method(dialog, METHOD)
            dialog.fields.select(dialog.field_rows[BROWN][0].master)
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
            buttons(dialog)
            kit.capture(dialog, f"{shot}.png")

        runs_before = len(app.runs)
        for factor, name in ((1.25, "window-variance-dpi-125-emulato"), (1.5, "window-variance-dpi-150-emulato")):
            root.tk.call("tk", "scaling", factor)
            holder = drive(lambda dialog, shot=name: dpi(dialog, shot), accept=False)
            app.choose_analysis()
            finish(holder)
        assert len(app.runs) == runs_before
        (directory / "display.json").write_text(json.dumps(
            {"width": root.winfo_screenwidth(), "height": root.winfo_screenheight()}) + "\n", encoding="utf-8")
    finally:
        set_language(previous_language)
        root.tk.call("tk", "scaling", previous_scaling)
