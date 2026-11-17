"""Desktop smoke for false-discovery control.

Widgets are driven and events are generated. This is not a native pointer session.
"""
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from unittest.mock import patch
import threading
import time

import pandas as pd

from . import fdr_control, operations
from .fdr_control import (
    BH, FAMILY_COLUMNS, FDR_METHOD, LEVEL, METHOD, P_COLUMNS, PLOT, SCOPE, SCOPE_EACH, SCOPE_POOL,
)
from .i18n import active_language, set_language, ui

TITLE = "Assays"
LEGACY = "Adjust a stack of p values"


def _frame():
    return pd.DataFrame({
        "Assay": ["A", "A", "A", "A", "B", "B", "B", "B"],
        "Visit": [1, 1, 2, 2, 1, 1, 2, 2],
        "Note": ["keep"] * 8,
        "p": [0.01, 0.03, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8],
        "P_A": [0.01, 0.03, 0.04, 0.20, 0.01, 0.50, None, 0.02],
        "P_B": [0.02, 0.04, 0.10, 0.30, 0.03, 0.40, 0.05, None],
    })


def _texts(widget):
    found = []
    try:
        if "text" in widget.keys():
            found.append(str(widget.cget("text")))
    except Exception:
        pass
    for child in widget.winfo_children():
        found.extend(_texts(child))
    return found


def check_fdr_control(root, app, directory, kit):
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
            def unexpected(_title, message, **_kwargs):
                raise AssertionError(message)

            try:
                dialog.update_idletasks()
                with patch.object(messagebox, "showerror", side_effect=unexpected):
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
        dialog.result = None
        return message

    def finish(holder):
        if "error" in holder:
            raise holder["error"]

    def sections(title):
        return next(items for name, items, *_rest in app.sheet_sections() if name == title)

    try:
        before = directory / "fdr-control-before.alab"
        legacy_options = {"p value": "p", "Correction": "Holm"}
        kit.save_project(before, {TITLE: kit.Dataset(_frame(), analyses=[(LEGACY, dict(legacy_options))])})
        app.import_file(before)
        root.update()
        app.open_sheet(("result", 0))
        kit.wait_for_calculation()
        legacy = app.runs[0]
        assert list(legacy.result.tables) == ["Adjusted p values"]
        assert legacy.result.figure is None
        pd.testing.assert_frame_equal(
            legacy.result.tables["Adjusted p values"],
            operations.adjust_p(app.tables[TITLE].frame(mask_excluded=True), "p", "holm"))
        legacy_snapshot = legacy.result.tables["Adjusted p values"].copy()
        assert len(app.runs) == 1

        dirty = app.dirty
        cancelled = drive(lambda dialog: kit.pick_method(dialog, METHOD), accept=False)
        app.choose_analysis()
        finish(cancelled)
        assert len(app.runs) == 1 and app.dirty is dirty
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Adjusted p values"], legacy_snapshot)

        seen = {}
        real_adjust = fdr_control.adjust_family

        def spy(values, method, q):
            seen["id"] = threading.get_ident()
            seen["name"] = threading.current_thread().name
            return real_adjust(values, method, q)

        def configure(dialog):
            kit.pick_method(dialog, METHOD)
            buttons(dialog)
            kit.capture(dialog, "window-fdr-fields-en.png")
            assert "does not test independence" in "\n".join(_texts(dialog))
            kit.select_columns(dialog, P_COLUMNS, ["Note"])
            reject(dialog, P_COLUMNS, "not a finite p")
            kit.capture(dialog, "window-fdr-error-en.png")
            kit.select_columns(dialog, P_COLUMNS, ["P_A", "P_B"])
            kit.select_columns(dialog, FAMILY_COLUMNS, ["Assay", "Visit"])
            dialog.controls[SCOPE][1].set(SCOPE_EACH)
            dialog.controls[FDR_METHOD][1].set(BH)
            dialog.controls[LEVEL][1].set("0")
            reject(dialog, LEVEL, "strictly between 0 and 100")
            dialog.controls[LEVEL][1].set("5")
            dialog.controls[PLOT][1].set(True)
            buttons(dialog)
            kit.capture(dialog, "window-fdr-ready-en.png")
            assert dialog.validate() is True
            assert dialog.processing_result is None
            dialog.result = None

        with patch("analisi.fdr_control.adjust_family", side_effect=spy):
            holder = drive(configure)
            app.choose_analysis()
            finish(holder)
            kit.wait_for_calculation()
        assert seen["id"] != threading.get_ident()
        assert seen["name"].startswith("Trama")
        assert not app.errors if hasattr(app, "errors") else True

        run = next(item for item in app.runs if item.method == METHOD)
        assert run.options[P_COLUMNS] == ["P_A", "P_B"]
        assert run.options[FAMILY_COLUMNS] == ["Assay", "Visit"]
        assert run.options[SCOPE] == SCOPE_EACH
        assert run.options[FDR_METHOD] == BH
        assert run.options[LEVEL] == 5.0
        assert run.options[PLOT] is True
        expected = fdr_control.analysis(app.tables[TITLE].frame(mask_excluded=True), run.options)
        for name in ("FDR results", "FDR families", "Settings"):
            pd.testing.assert_frame_equal(run.result.tables[name], expected.tables[name])
        assert run.result.figure is not None
        assert len([axis for axis in run.result.figure.axes if axis.get_visible()]) == 8
        pd.testing.assert_frame_equal(app.runs[0].result.tables["Adjusted p values"], legacy_snapshot)
        assert app.runs[0].result.figure is None

        index = app.runs.index(run)
        app.show("result", index)
        app.result_tabs.select(0)
        kit.capture(root, "window-fdr-results-en.png")
        csv_path = directory / "fdr-results.csv"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
            app.export()
        exported = pd.read_csv(csv_path)
        assert [int(value) for value in exported["Source row"].tolist()[:2]] == [1, 2]
        assert "True" in csv_path.read_text(encoding="utf-8")
        app.use_result_as_data()
        assert "Source row" in app.tables["FDR results"].raw.columns

        app.show("graph", index)
        root.update()
        kit.capture(root, "window-fdr-graph-en.png")
        for suffix in ("png", "svg", "pdf"):
            app.show("graph", index)
            target = directory / f"fdr-control.{suffix}"
            with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, suffix
        svg = (directory / "fdr-control.svg").read_text(encoding="utf-8")
        assert 'id="fdr-threshold-0"' in svg and 'id="fdr-discovery-0"' in svg
        assert "<image" not in svg
        assert (directory / "fdr-control.pdf").read_bytes().startswith(b"%PDF")

        before_edit = run.result.tables["FDR results"]["Adjusted p"].copy()
        app.show("data", TITLE)
        app.edit_cell(0, 4, "0.99")
        kit.wait_for_calculation()
        edited = next(item for item in app.runs if item.method == METHOD)
        assert not edited.result.tables["FDR results"]["Adjusted p"].equals(before_edit)
        missing_before = int((edited.result.tables["FDR results"]["Status"] == "Missing p").sum())
        app.show("data", TITLE)
        app.current_grid.select((0, 4))
        app.toggle_exclusion()
        kit.wait_for_calculation()
        excluded = next(item for item in app.runs if item.method == METHOD)
        after_rows = excluded.result.tables["FDR results"]
        masked = after_rows[(after_rows["Source row"] == 1) & (after_rows["Variable"] == "P_A")].iloc[0]
        assert masked["Status"] == "Missing p"
        assert pd.isna(masked["Adjusted p"])
        assert int((after_rows["Status"] == "Missing p").sum()) == missing_before + 1

        after = directory / "fdr-control-after.alab"
        app.path = after
        assert app.save()
        app.import_file(after)
        root.update()
        fdr_index = next(i for i, item in enumerate(app.runs) if item.method == METHOD)
        assert app.runs[fdr_index].result is None
        assert ("graph", fdr_index) in [ref for _name, ref in sections("Graphs")]
        app.open_sheet(("graph", fdr_index))
        kit.wait_for_calculation()
        reopened = app.runs[fdr_index]
        assert reopened.result.figure is not None
        assert reopened.options[FDR_METHOD] == BH and reopened.options[PLOT] is True
        assert all(isinstance(key, str) and key.isascii() for key in reopened.options)
        legacy_index = next(i for i, item in enumerate(app.runs) if item.method == LEGACY)
        assert app.runs[legacy_index].result is None
        app.open_sheet(("result", legacy_index))
        kit.wait_for_calculation()
        legacy_again = app.runs[legacy_index]
        assert list(legacy_again.result.tables) == ["Adjusted p values"]
        assert legacy_again.result.figure is None
        pd.testing.assert_frame_equal(legacy_again.result.tables["Adjusted p values"], legacy_snapshot)
        app.show("graph", fdr_index)
        root.update()

        set_language("it")
        each_rows = len(reopened.result.tables["FDR families"])

        def italian(dialog):
            assert dialog.field_rows[P_COLUMNS][0].cget("text") == "Colonne dei valori p"
            assert dialog.field_rows[LEVEL][0].cget("text") == "FDR desiderato (%)"
            assert any("non verifica" in text for text in _texts(dialog))
            buttons(dialog)
            kit.capture(dialog, "window-fdr-fields-it.png")
            dialog.controls[LEVEL][1].set("0")
            reject(dialog, LEVEL, "compreso tra 0 e 100")
            kit.capture(dialog, "window-fdr-error-it.png")
            dialog.controls[LEVEL][1].set("5,0")
            dialog.controls[SCOPE][1].set(SCOPE_POOL)
            buttons(dialog)
            kit.capture(dialog, "window-fdr-ready-it.png")

        holder = drive(italian)
        app.edit_analysis()
        finish(holder)
        kit.wait_for_calculation()
        pooled = next(item for item in app.runs if item.method == METHOD)
        assert pooled.options[SCOPE] == SCOPE_POOL
        assert pooled.options[LEVEL] == 5.0
        assert list(pooled.options) == list(reopened.options)
        families = pooled.result.tables["FDR families"]
        assert len(families) < each_rows
        assert families["Variable"].tolist() == ["Pooled"] * len(families)
        assert "FDR results" in pooled.result.tables
        app.show("result", app.runs.index(pooled))
        kit.capture(root, "window-fdr-results-it.png")
        app.show("graph", app.runs.index(pooled))
        kit.capture(root, "window-fdr-graph-it.png")
        assert "Soglia" in pooled.result.figure.legends[0].get_texts()[0].get_text()

        # Retained results describe the previous data until a successful
        # recalculation. Cancelling recovery must not make them exportable.
        kept = pooled.result
        app.show('data', TITLE)
        holder = drive(lambda d: kit.capture(d, 'window-fdr-recovery-it.png'), accept=False)
        app.edit_cell(1, 4, '2')
        kit.wait_for_calculation()
        finish(holder)
        assert pooled.result is kept and pooled.calculation_error
        app.show('result', app.runs.index(pooled))
        assert app.stale_calculation_note()
        kit.capture(root, 'window-fdr-stale-it.png')
        with patch.object(app, 'error') as error, patch.object(filedialog, 'asksaveasfilename') as chooser:
            app.export()
            app.use_result_as_data()
        assert error.call_count == 2 and not chooser.called
        app.show('data', TITLE)
        app.edit_cell(1, 4, '.03')
        kit.wait_for_calculation()
        assert pooled.result is not kept and pooled.calculation_error is None
    finally:
        set_language(previous_language)
