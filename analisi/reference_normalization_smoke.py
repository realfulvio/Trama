"""Desktop smoke for Normalize to references, driving the real dialogs and the real window.

``tramastat.py --smoke`` calls :func:`check_reference_normalization`.
Alone: ``TRAMASTAT_SMOKE_ONLY=reference-normalization python tramastat.py --smoke DIR``.

The numbers below are fixed by hand from the formula ``M * (y - a) / (b - a)``. This module does not
call the engine to invent them. Names are synthetic.
"""
import math
import os
import sys
from pathlib import Path

import pandas as pd
from PIL import Image
from matplotlib.container import ErrorbarContainer

from . import i18n
from .data import Dataset, save_project
from .graph_language_smoke import drive_mapped_dialog
from .reference_normalization import (BLANK, CONSTANT, EACH, KEEP, LIMITS, MAXIMUM, METHOD, MINIMUM,
                                      NORMALIZED, PERCENTAGES, RAW, REFERENCES, ROW_MEANS, SD, SELECTED, SEM,
                                      SETTINGS, SOURCE_ROWS, SUMMARY, UNCERTAINTY_NOTE)
from .worksheet_series import series_columns

REPLICATES, SUMMARY_SHEET, LEGACY = "Replicates", "Summary", "Legacy"
Y_COLUMNS = ["A [1]", "A [2]", "B [1]", "B [2]"]
# Each replicate, minimum/maximum, percentages. a,b come from the row means.
EACH_A1 = [-100 / 9, 100 / 3, 100]
EACH_A2 = [100 / 9, 500 / 9, 100]
EACH_B1 = [-100 / 3, 0, 100]
EACH_B2 = [100 / 3, 200 / 3, 100]
ROW_A = [0, 400 / 9, 100]
ROW_B = [0, 100 / 3, 100]
# Selected rows "1,2-3" are rows 0,1,2 once. Mean of 1,5,10 is 16/3, not (1+5+5+10)/4.
SEL_A = [-1300 / 14, -100 / 14, 100]
SEL_B = [-80, -20, 100]
# After A [1] row 0 becomes 8. Row means of A are 5, 5, 10.
EDIT_A1 = [60, -20, 100]
EDIT_A2 = [-60, 20, 100]
EDIT_ROW_A = [0, 0, 100]
EDIT_SEL_A = [-50, -50, 100]
# After also excluding A [2] row 1. Row means of A are 5, 4, 10.
EXCL_A1 = [200 / 3, 0, 100]
EXCL_A2 = [-100 / 3, None, 100]
EXCL_ROW_A = [50 / 3, 0, 100]
EXCL_SEL_A = [-400 / 11, -700 / 11, 100]


def _missing(value):
    if value is None or isinstance(value, str):
        return value is None
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def same(got, expected, tol=1e-9):
    got, expected = list(got), list(expected)
    assert len(got) == len(expected), (got, expected)
    for index, (left, right) in enumerate(zip(got, expected)):
        if _missing(right):
            assert _missing(left), (index, left, right)
        elif isinstance(right, str):
            assert left == right, (index, left, right)
        else:
            assert not _missing(left), (index, left, right)
            assert math.isclose(float(left), float(right), rel_tol=0, abs_tol=tol), (index, left, right)


def _project_frame():
    replicates = pd.DataFrame({
        "Title": ["r1", "r2", "r3"],
        "X": [10.0, 20.0, 30.0],
        "A [1]": [0.0, 4.0, 10.0],
        "A [2]": [2.0, 6.0, 10.0],
        "B [1]": [10.0, 20.0, 50.0],
        "B [2]": [30.0, 40.0, 50.0],
    })
    # Duplicate labels: the result must keep the physical row, not a join on this index.
    replicates.attrs["worksheet_roles"] = {"x": ["X"], "y": [["A [1]", "A [2]"], ["B [1]", "B [2]"]]}
    summary = pd.DataFrame({
        "Mean": [10.0, 20.0], "Low": [8.0, 16.0], "High": [14.0, 22.0],
        "SD": [2.0, 4.0], "N": [4.0, 4.0], "SEM": [1.0, 2.0],
    })
    legacy = pd.DataFrame({"y": [0.0, 5.0, 10.0]})
    legacy_recipe = [("Normalize", {"Variables": ["y"], "Method": "Percent of range"})]
    return {
        REPLICATES: Dataset(replicates),
        SUMMARY_SHEET: Dataset(summary),
        LEGACY: Dataset(legacy, analyses=legacy_recipe),
    }


def check_reference_normalization(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, LayoutDialog, GraphFormatDialog, capture, drive_dialog,
    pick_method, select_columns, wait_for_calculation, messagebox, filedialog and ``errors``."""
    wait, errors = tools.wait_for_calculation, tools.errors
    notes = []
    original_language = i18n.active_language()
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    wide = screen[0] >= 1600 and screen[1] >= 1000
    exports = directory / "exports"
    exports.mkdir(exist_ok=True)
    try:
        i18n.set_language("en")
        root.state("normal")
        client = (1024, 768)
        if sys.platform == "win32" and screen[1] <= 768:
            # Size this test viewport to the real work area: a 768px *client*
            # cannot fit alongside the native frame and taskbar on a 768px screen.
            import ctypes
            from ctypes import wintypes
            root.update()
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            outer, work = wintypes.RECT(), wintypes.RECT()
            assert user32.GetWindowRect(int(root.wm_frame(), 0), ctypes.byref(outer))
            assert user32.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)
            border_width = outer.right - outer.left - root.winfo_width()
            border_height = outer.bottom - outer.top - root.winfo_height()
            client = (min(1024, work.right - work.left - border_width),
                      min(768, work.bottom - work.top - border_height))
        root.geometry(f"{client[0]}x{client[1]}+0+0")
        root.update()
        assert (root.winfo_width(), root.winfo_height()) == client, client
        notes.append(f"screen {screen[0]}x{screen[1]}")
        notes.append(f"wide {wide}")
        tables = _project_frame()
        path = directory / "fixture.alab"
        save_project(path, tables)
        app.import_file(path)
        roles = app.tables[REPLICATES].raw.attrs["worksheet_roles"]
        assert roles == {"x": ["X"], "y": [["A [1]", "A [2]"], ["B [1]", "B [2]"]]}, roles
        # The project stores cells in physical order. A duplicate index is visible only until the next save.
        app.tables[REPLICATES].raw.index = pd.Index([4, 4, 9])

        def shot(window, name):
            # Screen grabs include whatever sits on top of the window. Keep this window above other apps.
            window.attributes("-topmost", True)
            window.lift()
            window.update()
            try:
                tools.capture(window, name)
            finally:
                window.attributes("-topmost", False)
            if (not (directory / name).exists() and sys.platform != "win32"
                    and not os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS")):
                return None
            image = Image.open(directory / name)
            assert image.size[0] >= 200 and image.size[1] >= 200, image.size
            notes.append(f"{name} {image.size[0]}x{image.size[1]}")
            return image

        def placed(dialog, name):
            return bool(dialog.field_rows[name][1].winfo_manager())

        def button(dialog, label):
            from tkinter import ttk

            def find(parent):
                for child in parent.winfo_children():
                    if isinstance(child, ttk.Button) and child.cget("text") == label:
                        return child
                    found = find(child)
                    if found is not None:
                        return found
            return find(dialog)

        def reachable(dialog, *, fit_small=False):
            dialog.update()
            run = button(dialog, i18n.ui("Run Analysis"))
            cancel = button(dialog, i18n.ui("Cancel"))
            assert run is not None and run.winfo_viewable()
            assert cancel is not None and cancel.winfo_viewable()
            assert run.winfo_rooty() + run.winfo_height() <= screen[1], (run.winfo_rooty(), screen)
            assert run.winfo_rootx() + run.winfo_width() <= screen[0]
            if fit_small:
                assert dialog.winfo_height() <= 768, dialog.winfo_height()
            for position in range(dialog.fields.index("end")):
                dialog.fields.select(position)
                dialog.update()
                assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1]

        def rejected(dialog, field, contains):
            from unittest.mock import patch

            with patch.object(tools.messagebox, "showerror") as report:
                assert dialog.validate() is False, field
            assert dialog.winfo_exists()
            message = report.call_args.args[1]
            assert contains in message, message
            assert dialog.fields.select() == str(dialog.field_rows[field][1].master), (field, message)
            return message

        def select_y(dialog):
            tools.select_columns(dialog, "Variables", Y_COLUMNS)

        def bind_xy(dialog):
            dialog.controls["X"][1].set("X")
            dialog.controls["Row titles"][1].set("Title")

        def run_on(title, action):
            app.show("data", title)
            tools.drive_dialog(tools.AnalysisDialog, action)
            app.choose_analysis()
            wait()
            assert not errors, errors
            return len(app.runs) - 1

        def sheet(index, name):
            return app.runs[index].result.tables[name]

        def assert_columns(index, columns, values):
            frame = sheet(index, NORMALIZED)
            assert list(frame.columns) == list(columns), list(frame.columns)
            for name, expected in values.items():
                same(frame[name].tolist(), expected)

        # 1. English dialog at 1024x768: errors stay open, hidden text is kept, then Each replicate runs.
        def each_dialog(dialog):
            tools.pick_method(dialog, METHOD)
            assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
                i18n.ui("Input"), i18n.ui("References"), i18n.ui("Output")]
            select_y(dialog)
            bind_xy(dialog)
            dialog.controls["Replicates"][1].set(EACH)
            dialog.update()
            assert "row means" in dialog.reference_replicate_note.cget("text")
            assert dialog.reference_replicate_note.winfo_manager()
            dialog.controls["Zero reference"][1].set(CONSTANT)
            dialog.controls["One reference"][1].set(CONSTANT)
            dialog.controls["Zero value"][1].set("2")
            dialog.controls["One value"][1].set("2")
            message = rejected(dialog, "One reference", "equal")
            assert "One reference" in message, message
            notes.append("error " + message)
            shot(dialog, "error.png")
            dialog.controls["Zero reference"][1].set(SELECTED)
            dialog.controls["Zero rows"][1].set("0")
            rejected(dialog, "Zero rows", "1,3-5")
            assert dialog.controls["Zero rows"][1].get() == "0"
            dialog.controls["Zero reference"][1].set(MINIMUM)
            dialog.update()
            assert not placed(dialog, "Zero rows")
            assert dialog.controls["Zero rows"][1].get() == "0"
            dialog.controls["One reference"][1].set("Sum")
            dialog.controls["Reference values in output"][1].set(BLANK)
            rejected(dialog, "Reference values in output", "sum or a mean")
            dialog.controls["Replicates"][1].set("Independent columns")
            dialog.update()
            assert not dialog.reference_replicate_note.winfo_manager()
            dialog.controls["Replicates"][1].set(EACH)
            dialog.controls["Zero reference"][1].set(MINIMUM)
            dialog.controls["One reference"][1].set(MAXIMUM)
            dialog.controls["Units"][1].set(PERCENTAGES)
            dialog.controls["Reference values in output"][1].set(KEEP)
            dialog.controls["Error lower"][1].set("nope")
            reachable(dialog, fit_small=True)
            dialog.fields.select(1)
            dialog.update()
            shot(dialog, "options-en.png")
            dialog.fields.select(0)
            assert dialog.validate() is True

        each_index = run_on(REPLICATES, each_dialog)
        each = app.runs[each_index]
        assert each.method == METHOD and each.options == {
            "Input": RAW, "Variables": Y_COLUMNS, "X": "X", "Row titles": "Title", "Replicates": EACH,
            "Zero reference": MINIMUM, "One reference": MAXIMUM, "Allow reversed references": False,
            "Units": PERCENTAGES, "Reference values in output": KEEP, "Graph results": True,
        }, each.options
        assert "nope" not in str(each.options)
        assert_columns(each_index, ["X", "Title", *Y_COLUMNS], {
            "X": [10, 20, 30], "Title": ["r1", "r2", "r3"],
            "A [1]": EACH_A1, "A [2]": EACH_A2, "B [1]": EACH_B1, "B [2]": EACH_B2,
        })
        references = sheet(each_index, REFERENCES)
        same(references["Zero reference"], [1, 20])
        same(references["One reference"], [10, 50])
        same(references["Scale factor"], [100 / 9, 100 / 30])
        assert references["Series"].tolist() == ["A", "B"]
        assert references["Zero source rows"].tolist() == ["0", "0"]
        assert sheet(each_index, SOURCE_ROWS)["Source index"].tolist() == [4, 4, 9]
        assert sheet(each_index, SOURCE_ROWS)["Source row"].tolist() == [0, 1, 2]
        note = sheet(each_index, SETTINGS)
        assert note.loc[note["Setting"] == "Note", "Value"].iloc[0] == UNCERTAINTY_NOTE
        assert app.runs[each_index].result.tables[NORMALIZED].attrs["worksheet_roles"]["y"] == [
            ["A [1]", "A [2]"], ["B [1]", "B [2]"]]
        assert list(app.tables[REPLICATES].raw["A [1]"]) == [0, 4, 10]
        app.show("result", each_index)
        root.update()
        assert (root.winfo_width(), root.winfo_height()) == client, (root.winfo_width(), root.winfo_height(), client)
        shot(root, "results.png")
        notes.append(f"client {root.winfo_width()}x{root.winfo_height()}")

        # 2. Italian dialog: comma decimal, translated error, recipe unchanged.
        snapshot = dict(each.options)
        i18n.set_language("it")

        def italian_dialog(dialog):
            assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
                "Dati in ingresso", "Riferimenti", "Risultati"]
            dialog.controls["Zero reference"][1].set(CONSTANT)
            dialog.controls["One reference"][1].set(CONSTANT)
            dialog.controls["Zero value"][1].set("2")
            dialog.controls["One value"][1].set("2")
            message = rejected(dialog, "One reference", "uguali")
            assert "Riferimento uno" in message, message
            dialog.controls["One reference"][1].set(MAXIMUM)
            dialog.controls["Zero value"][1].set("1,5")
            dialog.controls["Error lower"][1].set("nope")
            assert dialog.validate() is True
            assert dialog.result[1]["Zero value"] == 1.5
            assert "Error lower" not in dialog.result[1]
            reachable(dialog, fit_small=True)
            dialog.fields.select(1)
            dialog.update()
            assert dialog.controls["Zero value"][1].get() == "1,5"
            assert "medie di riga" in dialog.reference_replicate_note.cget("text")
            shot(dialog, "options-it.png")
            dialog.controls["Zero reference"][1].set(MINIMUM)
            assert dialog.controls["Zero reference"][1].get() == MINIMUM
            assert dialog.choice_bindings["Zero reference"].display.get() == "Minimo"
            assert dialog.controls["One reference"][1].get() == MAXIMUM

        app.show("result", each_index)
        tools.drive_dialog(tools.AnalysisDialog, italian_dialog)
        app.edit_analysis()
        wait()
        assert app.runs[each_index].options == snapshot, app.runs[each_index].options
        i18n.set_language("en")

        if wide:
            root.geometry("1600x1000+0+0")
            root.update()
            notes.append(f"client-wide {root.winfo_width()}x{root.winfo_height()}")

        def row_dialog(dialog, replicates, zero, rows=""):
            tools.pick_method(dialog, METHOD)
            select_y(dialog)
            bind_xy(dialog)
            dialog.controls["Replicates"][1].set(replicates)
            dialog.controls["Zero reference"][1].set(zero)
            dialog.controls["One reference"][1].set(MAXIMUM)
            if rows:
                dialog.controls["Zero rows"][1].set(rows)
            dialog.controls["Units"][1].set(PERCENTAGES)
            dialog.controls["Reference values in output"][1].set(KEEP)
            if wide:
                reachable(dialog)

        def row_means_dialog(dialog):
            row_dialog(dialog, ROW_MEANS, MINIMUM)

        def selected_dialog(dialog):
            row_dialog(dialog, ROW_MEANS, SELECTED, "1,2-3")

        def blank_dialog(dialog):
            tools.pick_method(dialog, METHOD)
            select_y(dialog)
            bind_xy(dialog)
            dialog.controls["Replicates"][1].set(EACH)
            dialog.controls["Zero reference"][1].set(MINIMUM)
            dialog.controls["One reference"][1].set(MAXIMUM)
            dialog.controls["Reference values in output"][1].set(BLANK)

        row_index = run_on(REPLICATES, row_means_dialog)
        assert_columns(row_index, ["X", "Title", "A", "B"], {
            "A": ROW_A, "B": ROW_B, "Title": ["r1", "r2", "r3"],
        })
        assert sheet(row_index, REFERENCES)["Series"].tolist() == ["A", "B"]
        selected_index = run_on(REPLICATES, selected_dialog)
        assert_columns(selected_index, ["X", "Title", "A", "B"], {"A": SEL_A, "B": SEL_B})
        selected_refs = sheet(selected_index, REFERENCES)
        same(selected_refs["Zero reference"], [16 / 3, 100 / 3])
        assert selected_refs["Zero reference"].tolist()[0] != 5.25
        assert selected_refs["Zero source rows"].tolist() == ["0,1,2", "0,1,2"]
        blank_index = run_on(REPLICATES, blank_dialog)
        assert_columns(blank_index, ["X", "Title", *Y_COLUMNS], {
            "X": [10, 20, 30], "Title": ["r1", "r2", "r3"],
            "A [1]": [None, EACH_A1[1], None], "A [2]": [None, EACH_A2[1], None],
            "B [1]": [None, EACH_B1[1], None], "B [2]": [None, EACH_B2[1], None],
        })

        def summary_dialog(dialog, error_format, lower, upper=None):
            tools.pick_method(dialog, METHOD)
            dialog.controls["Input"][1].set(SUMMARY)
            dialog.controls["Mean"][1].set("Mean")
            dialog.controls["Zero reference"][1].set(CONSTANT)
            dialog.controls["One reference"][1].set(CONSTANT)
            dialog.controls["Zero value"][1].set("20")
            dialog.controls["One value"][1].set("10")
            dialog.controls["Allow reversed references"][1].set(True)
            dialog.controls["Units"][1].set(PERCENTAGES)
            dialog.controls["Error format"][1].set(error_format)
            dialog.controls["Error lower"][1].set(lower)
            if upper:
                dialog.controls["Error upper"][1].set(upper)
            dialog.controls["N"][1].set("N")

        limits_index = run_on(SUMMARY_SHEET, lambda dialog: summary_dialog(dialog, LIMITS, "Low", "High"))
        assert_columns(limits_index, ["Mean", "Low", "High", "N"], {
            "Mean": [100, 0], "Low": [60, -20], "High": [120, 40], "N": [4, 4],
        })
        sd_index = run_on(SUMMARY_SHEET, lambda dialog: summary_dialog(dialog, SD, "SD"))
        assert_columns(sd_index, ["Mean", "SD", "N"], {"Mean": [100, 0], "SD": [20, 40], "N": [4, 4]})
        sem_index = run_on(SUMMARY_SHEET, lambda dialog: summary_dialog(dialog, SEM, "SEM"))
        assert_columns(sem_index, ["Mean", "SEM", "N"], {"Mean": [100, 0], "SEM": [10, 20], "N": [4, 4]})

        legacy_index = next(index for index, run in enumerate(app.runs)
                            if run.method == "Normalize" and run.title == LEGACY)
        app.show("result", legacy_index)
        app.recalculate(legacy_index)
        wait()
        assert list(app.runs[legacy_index].result.tables) == ["Normalized"]
        same(app.runs[legacy_index].result.tables["Normalized"]["y"], [0, 50, 100])

        def legacy_dialog(dialog):
            box = dialog.controls["Variables"][1]
            assert [box.get(i) for i in box.curselection()] == ["y"]
            assert dialog.controls["Method"][1].get() == "Percent of range"

        tools.drive_dialog(tools.AnalysisDialog, legacy_dialog)
        app.edit_analysis()
        wait()
        assert list(app.runs[legacy_index].result.tables) == ["Normalized"]
        same(app.runs[legacy_index].result.tables["Normalized"]["y"], [0, 50, 100])

        app.show("graph", limits_index)
        root.update()
        limits_axes = app.runs[limits_index].result.figure.axes[0]
        gids = {child.get_gid() for child in limits_axes.get_children()}
        assert {"tramastat-shape-reference-0", "tramastat-shape-reference-m"} <= gids, gids
        container = next(item for item in limits_axes.containers if isinstance(item, ErrorbarContainer))
        same(container.lines[0].get_ydata(), [100, 0])
        ends = {}
        for collection in container.lines[2]:
            for segment in collection.get_segments():
                if abs(float(segment[0, 0]) - float(segment[-1, 0])) > 1e-6:
                    continue
                key = round(float(segment[0, 0]), 6)
                ends.setdefault(key, []).extend(float(value) for value in segment[:, 1])
        assert math.isclose(min(ends[1.0]), 60) and math.isclose(max(ends[1.0]), 120), ends
        assert math.isclose(min(ends[2.0]), -20) and math.isclose(max(ends[2.0]), 40), ends
        shot(root, "graph.png")
        limits_svg = exports / "limits.svg"
        limits_png = exports / "limits.png"
        limits_pdf = exports / "limits.pdf"
        from unittest.mock import patch
        for target, marker in ((limits_svg, "tramastat-shape-reference-0"), (limits_png, b"\x89PNG"),
                               (limits_pdf, b"%PDF")):
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            payload = target.read_bytes()
            assert payload.startswith(marker) if isinstance(marker, bytes) else marker.encode() in payload, target.name
        assert "tramastat-shape-reference-m" in limits_svg.read_text(encoding="utf-8")

        app.toggle_inspector()
        root.update()
        inspector = app.inspector
        assert inspector is not None
        original_title = limits_axes.get_title()
        inspector.vars["title"].set("Not applied")
        inspector._now("title")
        assert limits_axes.get_title() == "Not applied"
        inspector.discard()
        assert limits_axes.get_title() == original_title
        assert not app.runs[limits_index].style
        inspector.vars["title"].set("Reference guides")
        inspector._now("title")
        assert inspector.apply() is True
        assert limits_axes.get_title() == "Reference guides"
        assert app.runs[limits_index].style.get("title") == "Reference guides"
        app.toggle_inspector()
        assert app.inspector is None

        def format_graph(dialog):
            dialog.inputs["title"].set("Normalized summary")
            dialog.grid_lines.set(True)

        tools.drive_dialog(tools.GraphFormatDialog, format_graph)
        app.format_graph()
        assert limits_axes.get_title() == "Normalized summary"

        def choose_panels(dialog):
            wanted = []
            for index, run in enumerate(dialog.runs):
                if run is app.runs[each_index] or run is app.runs[limits_index]:
                    wanted.append(index)
            assert len(wanted) == 2, [run.name for run in dialog.runs]
            dialog.name.set("Reference figure")
            dialog.list.selection_clear(0, "end")
            for index in wanted:
                dialog.list.selection_set(index)
            dialog.add_selected()

        app.show("graph", each_index)
        tools.drive_dialog(tools.LayoutDialog, choose_panels)
        app.new_layout()
        assert len(app.layout_figure.axes) == 2

        frozen_summary = {index: {name: frame.copy() for name, frame in app.runs[index].result.tables.items()}
                          for index in (limits_index, sd_index, sem_index)}
        frozen_legacy = app.runs[legacy_index].result.tables["Normalized"]["y"].tolist()

        # 3. Editing and excluding a source cell recalculates every replicate run and leaves the others.
        app.show("data", REPLICATES)
        app.edit_cell(0, 2, "8")
        wait()
        assert_columns(each_index, ["X", "Title", *Y_COLUMNS], {
            "A [1]": EDIT_A1, "A [2]": EDIT_A2, "B [1]": EACH_B1, "B [2]": EACH_B2,
        })
        assert_columns(row_index, ["X", "Title", "A", "B"], {"A": EDIT_ROW_A, "B": ROW_B})
        same(sheet(selected_index, REFERENCES)["Zero reference"], [20 / 3, 100 / 3])
        assert_columns(selected_index, ["X", "Title", "A", "B"], {"A": EDIT_SEL_A, "B": SEL_B})
        assert_columns(blank_index, ["X", "Title", *Y_COLUMNS], {
            "X": [10, 20, 30], "Title": ["r1", "r2", "r3"],
            "A [1]": [None, None, None], "A [2]": [None, None, None],
            "B [1]": [None, EACH_B1[1], None], "B [2]": [None, EACH_B2[1], None],
        })
        app.current_grid.active_cell = (1, 3)
        app.toggle_exclusion()
        wait()
        assert (1, 3) in app.tables[REPLICATES].excluded
        assert_columns(each_index, ["X", "Title", *Y_COLUMNS], {
            "A [1]": EXCL_A1, "A [2]": EXCL_A2, "B [1]": EACH_B1, "B [2]": EACH_B2,
        })
        assert_columns(row_index, ["X", "Title", "A", "B"], {"A": EXCL_ROW_A, "B": ROW_B})
        same(sheet(selected_index, REFERENCES)["Zero reference"], [19 / 3, 100 / 3])
        assert_columns(selected_index, ["X", "Title", "A", "B"], {"A": EXCL_SEL_A, "B": SEL_B})
        assert_columns(blank_index, ["X", "Title", *Y_COLUMNS], {
            "A [1]": [EXCL_A1[0], None, None], "A [2]": [EXCL_A2[0], None, None],
            "B [1]": [None, EACH_B1[1], None], "B [2]": [None, EACH_B2[1], None],
        })
        for index, frozen in frozen_summary.items():
            for name, frame in frozen.items():
                for column in frame.columns:
                    same(app.runs[index].result.tables[name][column], frame[column])
        same(app.runs[legacy_index].result.tables["Normalized"]["y"], frozen_legacy)

        app.show("result", each_index)
        app.result_tabs.select(0)
        exported = exports / "normalized.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(exported)):
            app.export()
        loaded = pd.read_csv(exported, index_col=0)
        assert list(loaded.columns) == list(sheet(each_index, NORMALIZED).columns)
        for column in loaded.columns:
            same(loaded[column].tolist(), sheet(each_index, NORMALIZED)[column].tolist())

        app.use_result_as_data()
        root.update()
        used_title = app.active_data
        used = app.tables[used_title].frame()
        groups = series_columns(used, [name for name in Y_COLUMNS if name in used.columns], recognize_replicates=True)
        assert groups == [["A [1]", "A [2]"], ["B [1]", "B [2]"]], groups
        kept_roles = app.tables[used_title].raw.attrs.get("worksheet_roles")
        notes.append("roles-after-use-result " + ("kept" if kept_roles else "dropped"))
        if kept_roles:
            assert kept_roles["y"] == [["A [1]", "A [2]"], ["B [1]", "B [2]"]]

        def reshape_dialog(dialog):
            tools.pick_method(dialog, "Reshape replicates")
            tools.select_columns(dialog, "Variables", Y_COLUMNS)
            dialog.controls["Row label"][1].set("Title")

        reshape_index = run_on(used_title, reshape_dialog)
        long = app.runs[reshape_index].result.tables["Long format"]
        assert set(long["Series"]) == {"A", "B"}
        assert set(long["Replicate"]) == {1, 2}

        before_runs = len(app.runs)

        def abandon(dialog):
            tools.pick_method(dialog, METHOD)
            dialog.cancel()

        app.show("data", REPLICATES)
        drive_mapped_dialog(root, tools.AnalysisDialog, abandon, errors)
        app.choose_analysis()
        assert len(app.runs) == before_runs
        assert not errors, errors

        # A failed summary edit keeps the previous result of this method, then Undo restores the cell.
        def minimum_summary(dialog):
            tools.pick_method(dialog, METHOD)
            dialog.controls["Input"][1].set(SUMMARY)
            dialog.controls["Mean"][1].set("Mean")
            dialog.controls["Zero reference"][1].set(MINIMUM)
            dialog.controls["One reference"][1].set(MAXIMUM)

        probe_index = run_on(SUMMARY_SHEET, minimum_summary)
        same(sheet(probe_index, NORMALIZED)["Mean"], [0, 100])
        preserved = sheet(probe_index, NORMALIZED)["Mean"].tolist()
        # The first upper limit is 14. A mean of 20 is rejected by Limits, so that run would
        # keep [100, 0] and could not show that the refresh ran. Raise the limit first.
        app.show("data", SUMMARY_SHEET)
        assert app.active_data == SUMMARY_SHEET
        columns = list(app.tables[SUMMARY_SHEET].raw.columns)
        app.edit_cell(0, columns.index("High"), "22")
        wait()
        same(app.tables[SUMMARY_SHEET].raw["High"], [22, 22])
        app.edit_cell(0, columns.index("Mean"), "20")
        wait()
        same(app.tables[SUMMARY_SHEET].raw["Mean"], [20, 20])
        same(app.runs[probe_index].result.tables[NORMALIZED]["Mean"], preserved)
        assert app.stale_calculation_note(("result", probe_index))
        same(app.runs[limits_index].result.tables[NORMALIZED]["Mean"], [0, 0])
        same(app.runs[sd_index].result.tables[NORMALIZED]["Mean"], [0, 0])
        same(app.runs[sd_index].result.tables[NORMALIZED]["SD"], [20, 40])
        assert "equal" in app.status.get(), app.status.get()
        assert not errors, errors
        app.apply_worksheet_history()
        wait()
        app.apply_worksheet_history()
        wait()
        same(app.tables[SUMMARY_SHEET].raw["Mean"], [10, 20])
        same(app.tables[SUMMARY_SHEET].raw["High"], [14, 22])
        same(app.runs[limits_index].result.tables[NORMALIZED]["Mean"], [100, 0])
        same(app.runs[limits_index].result.tables[NORMALIZED]["High"], [120, 40])
        same(app.runs[sd_index].result.tables[NORMALIZED]["Mean"], [100, 0])
        same(app.runs[sd_index].result.tables[NORMALIZED]["SD"], [20, 40])
        same(app.runs[sem_index].result.tables[NORMALIZED]["SEM"], [10, 20])
        same(app.runs[probe_index].result.tables[NORMALIZED]["Mean"], [0, 100])
        assert app.stale_calculation_note(("result", probe_index)) is None
        same(app.runs[legacy_index].result.tables["Normalized"]["y"], frozen_legacy)

        recipes = {title: [(method, dict(options)) for method, options in dataset.analyses]
                   for title, dataset in app.tables.items()}
        role_snapshot = dict(app.tables[REPLICATES].raw.attrs["worksheet_roles"])
        saved_results = {
            (run.title, run.slot, run.method): {name: frame.copy() for name, frame in run.result.tables.items()}
            for run in app.runs if run.result is not None
        }
        roundtrip = directory / "roundtrip.alab"
        app.path = roundtrip
        assert app.save()
        app.import_file(roundtrip)
        assert {title: [(method, dict(options)) for method, options in dataset.analyses]
                for title, dataset in app.tables.items()} == recipes
        assert app.tables[REPLICATES].raw.attrs["worksheet_roles"] == role_snapshot
        assert app.tables[REPLICATES].excluded == {(1, 3)}
        i18n.set_language("it")
        reopened = next(index for index, run in enumerate(app.runs)
                        if run.title == REPLICATES and run.options.get("Replicates") == EACH)
        app.show("result", reopened)
        if app.runs[reopened].result is None:
            app.recalculate(reopened)
            wait()

        def reopen_dialog(dialog):
            assert dialog.fields.tab(1, "text") == "Riferimenti"
            assert dialog.controls["Replicates"][1].get() == EACH
            assert dialog.controls["Zero reference"][1].get() == MINIMUM

        tools.drive_dialog(tools.AnalysisDialog, reopen_dialog)
        app.edit_analysis()
        wait()
        assert app.runs[reopened].options == snapshot
        i18n.set_language("en")
        for index, run in enumerate(app.runs):
            if run.result is None:
                app.show("result", index)
                app.recalculate(index)
                wait()
            expected = saved_results[run.title, run.slot, run.method]
            got = run.result.tables
            assert list(got) == list(expected), (run.title, run.method)
            for name in got:
                assert list(got[name].columns) == list(expected[name].columns)
                for column in got[name].columns:
                    if name == SOURCE_ROWS and column == "Source index" and list(expected[name][column]) == [4, 4, 9]:
                        # The project stores cells, not the pandas index. The duplicate labels become 0,1,2.
                        same(got[name][column], [0, 1, 2])
                    else:
                        same(got[name][column], expected[name][column])
        legacy = next(run for run in app.runs if run.method == "Normalize")
        assert list(legacy.result.tables) == ["Normalized"]
        same(legacy.result.tables["Normalized"]["y"], [0, 50, 100])
        assert limits_axes_title(app, "Summary", LIMITS) == "Normalized summary"
        app.show("layout", 0)
        app.recalculate_layout(0)
        wait()
        assert len(app.layout_figure.axes) == 2
        notes.append("source-index-after-reload 0,1,2")
        (directory / "reference-notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    finally:
        i18n.set_language(original_language)


def limits_axes_title(app, title, error_format):
    run = next(run for run in app.runs if run.title == title and run.options.get("Error format") == error_format)
    return run.result.figure.axes[0].get_title()
