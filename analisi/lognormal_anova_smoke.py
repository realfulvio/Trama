"""Desktop smoke for lognormal one-way ANOVA.

Drives the real Analyze dialog. The result has no figure. Screenshots are the
X root from ImageMagick ``import`` when ``TRAMASTAT_SMOKE_SCREENSHOTS`` is set.
"""
from pathlib import Path
import json
import time
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from .field_error import FieldError
from .i18n import active_language, set_language, ui
from . import lognormal_anova
from .lognormal_anova import DISTRIBUTION, LOGNORMAL, NORMAL, RATIO_DIRECTION, SECOND_OVER_FIRST, SUMMARY
from .trend_anova import TREND
from .unequal_anova import LEVEL

METHOD = "One-way ANOVA"
TITLE = "Counts"


def _frame():
    return pd.DataFrame({
        "Y": [1, 2, 4, 8, 16, 32, 64, 128, 256],
        "Group": ["A", "A", "A", "B", "B", "B", "C", "C", "C"],
    })


def check_lognormal_anova(root, app, directory, kit):
    directory = Path(directory)
    previous_language = active_language()
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    suffix = "-1600" if screen[0] >= 1600 else ""
    (directory / f"screen{suffix}.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
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

    def finish(holder):
        if "error" in holder:
            raise holder["error"]

    def page_of(dialog, field):
        page = dialog.field_rows[field][1]
        while page is not None and page.master is not dialog.fields:
            page = page.master
        return page

    def canvas_of(dialog, field):
        parent = dialog.field_rows[field][1].master
        while parent is not None and parent.winfo_class() != "Canvas":
            parent = parent.master
        return parent

    def on_screen(widget, canvas=None):
        root.update_idletasks()
        assert widget.winfo_ismapped() and widget.winfo_viewable(), widget
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        width, height = widget.winfo_width(), widget.winfo_height()
        assert width > 0 and height > 0
        assert 0 <= x and x + width <= root.winfo_screenwidth(), (x, width, root.winfo_screenwidth())
        assert 0 <= y and y + height <= root.winfo_screenheight(), (y, height, root.winfo_screenheight())
        if canvas is not None:
            left, top = canvas.winfo_rootx(), canvas.winfo_rooty()
            right, bottom = left + canvas.winfo_width(), top + canvas.winfo_height()
            assert left - 2 <= x and x + width <= right + 2, (x, width, left, right)
            assert top - 2 <= y and y + height <= bottom + 2, (y, height, top, bottom)

    def buttons(dialog):
        found = {}
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found[widget.cget("text")] = widget
        placed = {}
        for name in ("Run Analysis", "Cancel"):
            widget = found[ui(name)]
            on_screen(widget)
            placed[name] = {"x": widget.winfo_rootx(), "y": widget.winfo_rooty(),
                            "width": widget.winfo_width(), "height": widget.winfo_height()}
        return placed

    def reject(dialog, field, snippet):
        with patch.object(kit.messagebox, "showerror") as shown:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = shown.call_args.args[1]
        assert snippet in message, message
        assert dialog.fields.select() == str(page_of(dialog, field)), field
        on_screen(dialog.field_rows[field][1], canvas_of(dialog, field))
        dialog.result = None
        return message

    def shot(dialog, name):
        kit.capture(dialog, f"{name}{suffix}.png")

    def select_sheet(title):
        app.show("result", 0)
        tabs = app.result_tabs
        for index in range(tabs.index("end")):
            if tabs.tab(index, "text") == title:
                tabs.select(index)
                return
        raise AssertionError(title)

    def release_to_worker(dialog):
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
        before = directory / f"lognormal-anova-before{suffix}.alab"
        kit.save_project(before, {TITLE: kit.Dataset(_frame(), analyses=[(METHOD, dict(legacy))])})
        app.import_file(before)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        legacy_run = app.runs[0]
        assert DISTRIBUTION not in legacy_run.options
        assert SUMMARY not in legacy_run.result.tables
        assert legacy_run.result.figure is None
        legacy_f = float(legacy_run.result.tables["ANOVA"].iloc[0]["F"])

        def enable(dialog):
            dialog.fields.select(page_of(dialog, DISTRIBUTION))
            dialog.update_idletasks()
            assert dialog.controls[DISTRIBUTION][1].get() == NORMAL
            assert dialog.choice_bindings[DISTRIBUTION].display.get() == "Normal"
            assert not dialog.field_rows[RATIO_DIRECTION][1].winfo_ismapped()
            dialog.controls[RATIO_DIRECTION][1].set("garbage")
            dialog.controls["Post-hoc"][1].set("Tukey")
            dialog.update_idletasks()
            assert not dialog.field_rows[RATIO_DIRECTION][1].winfo_ismapped()
            assert not dialog.field_rows[LEVEL][1].winfo_ismapped()
            assert dialog.validate() is True
            assert dialog.result[1][DISTRIBUTION] == NORMAL
            assert RATIO_DIRECTION not in dialog.result[1]
            dialog.result = None
            dialog.controls[RATIO_DIRECTION][1].set(SECOND_OVER_FIRST)
            dialog.controls[DISTRIBUTION][1].set(LOGNORMAL)
            dialog.update_idletasks()
            assert dialog.field_rows[RATIO_DIRECTION][1].winfo_ismapped()
            assert dialog.field_rows[LEVEL][1].winfo_ismapped()
            assert "offset" in dialog.lognormal_note.cget("text")
            on_screen(dialog.field_rows[DISTRIBUTION][1], canvas_of(dialog, DISTRIBUTION))
            buttons(dialog)
            dialog.controls[LEVEL][1].set("0")
            reject(dialog, LEVEL, "strictly between 0 and 100")
            shot(dialog, "window-lognormal-anova-error-en")
            dialog.controls[LEVEL][1].set("95")
            dialog.controls[TREND][1].set(True)
            reject(dialog, TREND, "not available")
            dialog.controls[TREND][1].set(False)
            dialog.controls[RATIO_DIRECTION][1].set("garbage")
            reject(dialog, RATIO_DIRECTION, "First / Second")
            dialog.controls[RATIO_DIRECTION][1].set(SECOND_OVER_FIRST)
            dialog.controls["Response"][1].set("Y")
            dialog.controls["Group"][1].set("Group")
            dialog.controls["Method"][1].set("Ordinary")
            dialog.fields.select(page_of(dialog, DISTRIBUTION))
            placed = buttons(dialog)
            (directory / f"display{suffix}.json").write_text(json.dumps({
                "screen": f"{screen[0]}x{screen[1]}", "buttons": placed,
            }, indent=2), encoding="utf-8")
            shot(dialog, "window-lognormal-anova-ready-en")

        holder = drive(enable)
        app.edit_analysis()
        finish(holder)
        kit.wait_for_calculation()
        run = app.runs[0]
        assert run.options[DISTRIBUTION] == LOGNORMAL
        assert run.options[RATIO_DIRECTION] == SECOND_OVER_FIRST
        assert run.options[LEVEL] == 95
        assert run.result.figure is None
        anova = run.result.tables["ANOVA"]
        np.testing.assert_allclose(anova.iloc[0][["F", "p"]].astype(float), [27, 0.001])
        summary = run.result.tables[SUMMARY]
        assert summary["Group"].tolist() == ["A", "B", "C"]
        np.testing.assert_allclose(summary["Geometric mean"], [2, 16, 128])
        ratios = run.result.tables["Multiple comparisons"]
        assert ratios["Numerator"].tolist() == ["B", "C", "C"]
        assert ratios["Denominator"].tolist() == ["A", "A", "B"]
        np.testing.assert_allclose(ratios["Ratio"], [8, 64, 8])
        assert (ratios["Ratio CI low"] < ratios["Ratio"]).all()
        assert (ratios["Ratio"] < ratios["Ratio CI high"]).all()
        select_sheet(SUMMARY)
        shot(root, "window-lognormal-anova-results-en")
        assert float(anova.iloc[0]["F"]) != legacy_f

        app.edit_cell(0, 0, "1.5")
        kit.wait_for_calculation()
        changed = float(app.runs[0].result.tables["ANOVA"].iloc[0]["F"])
        assert changed != 27 and np.isfinite(changed)
        app.show("data", TITLE)
        app.current_grid.select((1, 0))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        assert app.runs[0].result.tables[SUMMARY]["N"].tolist() == [2, 3, 3]

        after = directory / f"lognormal-anova-after{suffix}.alab"
        snapshot = {name: frame.copy() for name, frame in app.runs[0].result.tables.items()}
        app.path = after
        assert app.save()
        stored = json.loads(after.read_text(encoding="utf-8"))
        recipe = stored["tables"][0]["analyses"][0][1]
        assert recipe[DISTRIBUTION] == "Lognormal"
        assert recipe[RATIO_DIRECTION] == "Second / First"
        assert "Lognormale" not in json.dumps(recipe)
        app.import_file(after)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        for name, frame in snapshot.items():
            pd.testing.assert_frame_equal(app.runs[0].result.tables[name], frame)

        select_sheet(SUMMARY)
        target = directory / f"lognormal-anova{suffix}.csv"
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target)
        assert exported["Group"].tolist() == ["A", "B", "C"]
        assert "Geometric mean" in exported.columns
        app.use_result_as_data()
        copied = app.tables[SUMMARY].raw
        assert copied["Group"].tolist() == ["A", "B", "C"]
        assert "Geometric mean" in copied.columns

        set_language("it")

        def italian(dialog):
            assert dialog.field_rows[DISTRIBUTION][0].cget("text") == "Distribuzione"
            assert dialog.field_rows[RATIO_DIRECTION][0].cget("text") == "Direzione del rapporto"
            assert dialog.controls[DISTRIBUTION][1].get() == LOGNORMAL
            assert dialog.choice_bindings[DISTRIBUTION].display.get() == "Lognormale"
            assert dialog.choice_bindings[RATIO_DIRECTION].display.get() == "Secondo / Primo"
            assert "offset" in dialog.lognormal_note.cget("text")
            dialog.controls[LEVEL][1].set("90,5")
            assert dialog.validate() is True
            assert dialog.result[1][LEVEL] == 90.5
            assert dialog.result[1][DISTRIBUTION] == "Lognormal"
            dialog.result = None
            dialog.controls[LEVEL][1].set("0")
            reject(dialog, LEVEL, "compreso tra 0 e 100")
            buttons(dialog)
            shot(dialog, "window-lognormal-anova-error-it")
            dialog.controls[LEVEL][1].set("95")
            shot(dialog, "window-lognormal-anova-fields-it")

        app.show("result", 0)
        holder = drive(italian, accept=False)
        app.edit_analysis()
        finish(holder)
        assert app.runs[0].options[LEVEL] == 95
        assert app.runs[0].options[DISTRIBUTION] == LOGNORMAL
        set_language("en")

        kept = {name: frame.copy() for name, frame in app.runs[0].result.tables.items()}
        calls = {"n": 0}
        real_analysis = lognormal_anova.analysis

        def fail_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise FieldError("Response", "Injected worker failure")
            return real_analysis(*args, **kwargs)

        def arm(dialog):
            dialog.controls[DISTRIBUTION][1].set(LOGNORMAL)
            dialog.controls["Post-hoc"][1].set("Tukey")
            release_to_worker(dialog)

        state = {"done": False}

        def watch_recovery(needle, tries=0):
            dialog = find()
            label = getattr(dialog, "error_label", None) if dialog is not None else None
            if label is None or needle not in label.cget("text"):
                if tries > 400:
                    state["error"] = TimeoutError(f"The dialog did not reopen with {needle!r}.")
                    state["done"] = True
                    return
                root.after(40, lambda: watch_recovery(needle, tries + 1))
                return
            try:
                assert dialog.winfo_exists()
                buttons(dialog)
                state["recovered"] = True
            except Exception as error:
                state["error"] = error
            close_dialog(dialog)
            state["done"] = True

        with patch("analisi.lognormal_anova.analysis", fail_once):
            holder = drive(arm)
            app.edit_analysis()
            finish(holder)
            root.after(40, lambda: watch_recovery("Injected"))
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

        state = {"done": False, "recovered": False}
        root.after(40, lambda: watch_recovery("strictly positive"))
        app.show("data", TITLE)
        app.edit_cell(0, 0, "0")
        deadline = time.monotonic() + 20
        while not state["done"] or app.pending is not None:
            if time.monotonic() > deadline:
                raise TimeoutError("The nonpositive edit did not reopen the dialog.")
            root.update()
            time.sleep(0.02)
        if state.get("error"):
            raise state["error"]
        assert state.get("recovered") is True
        for name, frame in kept.items():
            pd.testing.assert_frame_equal(app.runs[0].result.tables[name], frame)
        app.edit_cell(0, 0, "1.5")
        kit.wait_for_calculation()
        assert app.runs[0].result.figure is None
        assert np.isfinite(app.runs[0].result.tables["ANOVA"].iloc[0]["F"])
    finally:
        set_language(previous_language)
