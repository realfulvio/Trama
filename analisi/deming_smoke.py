"""Desktop smoke check for Deming regression with known SDs, several Y series and projections.

``tramastat.py --smoke`` calls :func:`check_deming_multiseries` with a kit that carries app, root, directory,
capture, pick_method, select_columns, drive_dialog(action), wait_for_calculation, errors, filedialog and
messagebox. Alone: ``TRAMASTAT_SMOKE_ONLY=deming-multiseries python tramastat.py --smoke DIR``.

The data are synthetic. The check goes through Analyze, corrects a field error inside the dialog, draws the
figure with projection segments, exports PNG, SVG, PDF and CSV, uses a result sheet as data, saves and reopens
the project, edits and excludes a cell, switches a series off and returns to the historical single recipe.
Further dialogs run in Italian and in the modern theme.
"""
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

from . import i18n, ui_theme
from .data import Dataset, save_project
from .deming import (KNOWN_SDS, PROJECTED_COLUMNS, PROJECTIONS, RATIO, RESIDUAL_COLUMN, SERIES_COLUMN, UNCERTAINTY,
                     X_SD, Y_SD, Y_SERIES)
from .exploration import deming as oracle
from .i18n import ui

METHOD = "Deming regression"
TITLE = "Deming series"
RATIO_SDS = (2.0, 1.0)
LAMBDA = (RATIO_SDS[1] / RATIO_SDS[0]) ** 2
LEGACY = {"X": "Dose", "Y": "A", "Y / X error variance": 1.0, "Parameter intervals": "None", "Identity line": False}


def _source():
    nan = np.nan
    return pd.DataFrame({"Dose": [0., 1, 2, 4, 7], "A": [4., 3, 7, 7, 15], "B $": [8., nan, 6, 3, 1],
                         "Sparse": [1., nan, 2, nan, nan]})


def check_deming_multiseries(kit):
    original_language = i18n.active_language()
    original_theme = "modern" if ui_theme.is_modern() else "standard"
    try:
        _run(kit)
    finally:
        i18n.set_language(original_language)
        ui_theme.configure(kit.root, original_theme)
        kit.root.update()


def _run(kit):
    app, root, wait, directory = kit.app, kit.root, kit.wait_for_calculation, kit.directory
    i18n.set_language("en")
    ui_theme.configure(root, "standard")
    path = directory / "deming-series.alab"
    source = _source()
    save_project(path, {TITLE: Dataset(source)})
    app.import_file(path)
    columns = list(source.columns)

    def tabs(dialog):
        return [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]

    def current_tab(dialog):
        return tabs(dialog)[dialog.fields.index(dialog.fields.select())]

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def buttons(dialog):
        """Run Analysis and Cancel are in view, inside the screen."""
        dialog.update_idletasks()
        found = []
        for child in dialog.winfo_children():
            for widget in child.winfo_children():
                if isinstance(widget, ttk.Button):
                    found.append(str(widget.cget("text")))
                    assert widget.winfo_ismapped() and widget.winfo_viewable(), widget.cget("text")
                    assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_screenheight(), widget
                    assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_screenwidth(), widget
        assert ui("Run Analysis") in found and ui("Cancel") in found, found
        assert dialog.winfo_rooty() + dialog.winfo_height() <= root.winfo_screenheight(), "the dialog is off screen"

    def rejected(dialog, field, text, page, shot=None):
        with patch.object(kit.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists() and dialog.result is None
        message = report.call_args.args[1]
        assert text in message, message
        assert current_tab(dialog) == page, (current_tab(dialog), page)
        entry = dialog.field_rows[field][1]
        # A list field keeps its focus on the listbox inside the row's frame.
        assert str(dialog.focus_get()).startswith(str(entry)), (dialog.focus_get(), entry)
        if shot:
            kit.capture(dialog, shot)
        return message

    def run_options(index):
        return app.runs[index].options

    def tables(index):
        return app.runs[index].result.tables

    def collections(figure):
        return [item for item in figure.axes[0].collections if isinstance(item, LineCollection)]

    # ---- 1. Analyze: two series, known SDs, projections, jackknife. A short series and a zero SD stay in the dialog.
    def configure(dialog):
        kit.pick_method(dialog, METHOD)
        assert dialog.method == METHOD
        assert tabs(dialog) == ["Variables", "Uncertainty", "Output"], tabs(dialog)
        dialog.controls["X"][1].set("Dose")
        dialog.controls["Y"][1].set("A")
        assert placed(dialog, RATIO) and not placed(dialog, X_SD) and not placed(dialog, Y_SD)
        kit.select_columns(dialog, "Y series", ["A", "B $", "Sparse"])
        rejected(dialog, "Y series", 'Series "Sparse"', "Variables", "window-deming-series-error.png")
        kit.select_columns(dialog, "Y series", ["A", "B $"])
        dialog.controls[UNCERTAINTY][1].set(KNOWN_SDS)
        dialog.update()
        assert not placed(dialog, RATIO) and placed(dialog, X_SD) and placed(dialog, Y_SD)
        dialog.controls[X_SD][1].set("2")
        dialog.controls[Y_SD][1].set("0")
        rejected(dialog, Y_SD, "Y error SD must be finite and greater than 0.", "Uncertainty",
                 "window-deming-sd-error.png")
        dialog.controls[Y_SD][1].set("1")
        dialog.focus_field(X_SD)
        buttons(dialog)
        kit.capture(dialog, "window-deming-uncertainty.png")
        dialog.controls[PROJECTIONS][1].set(True)
        dialog.controls["Parameter intervals"][1].set("Jackknife (t)")
        dialog.controls["Identity line"][1].set(True)
        dialog.update()
        assert placed(dialog, "Confidence level (%)")
        dialog.focus_field(PROJECTIONS)
        kit.capture(dialog, "window-deming-output.png")
        dialog.focus_field("X")
        kit.capture(dialog, "window-deming-variables.png")

    kit.drive_dialog(configure)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    options = run_options(index)
    assert options[Y_SERIES] == ["A", "B $"] and options[UNCERTAINTY] == KNOWN_SDS, options
    assert options[X_SD] == 2.0 and options[Y_SD] == 1.0 and options[PROJECTIONS] is True, options
    assert RATIO not in options, options
    result = app.runs[index].result
    assert list(result.tables) == [METHOD, "Data", "Pairs"], list(result.tables)
    report, pairs = result.tables[METHOD], result.tables["Pairs"]
    assert list(report[SERIES_COLUMN]) == ["A", "B $"] and list(report["N"]) == [5, 4], report
    np.testing.assert_allclose(report["Y / X measurement error variance"], LAMBDA)
    for name, row in zip(("A", "B $"), report.itertuples()):
        want, _ = oracle(source, "Dose", name, LAMBDA)
        np.testing.assert_allclose([row.Slope, row.Intercept], [want["Slope"], want["Intercept"]], rtol=1e-12)
    assert list(pairs.columns) == [SERIES_COLUMN, "Source row", "X", "Y", "Fitted Y", RESIDUAL_COLUMN,
                                   *PROJECTED_COLUMNS], list(pairs.columns)
    for name, row in zip(("A", "B $"), report.itertuples()):
        part = pairs[pairs[SERIES_COLUMN] == name]
        dx, dy = part["Projected X"] - part["X"], part["Projected Y"] - part["Y"]
        np.testing.assert_allclose(LAMBDA * dx + row.Slope * dy, 0, atol=1e-12)
        np.testing.assert_allclose(part["Projected Y"], row.Intercept + row.Slope * part["Projected X"], atol=1e-12)
    axis = result.figure.axes[0]
    segments = collections(result.figure)
    assert [len(item.get_segments()) for item in segments] == [5, 4], segments
    legend = axis.get_legend().get_texts()
    assert [text.get_text() for text in legend] == ["A", "B $", "Identity"], [text.get_text() for text in legend]
    assert all(not text.get_parse_math() for text in legend)
    app.show("graph", index)
    root.update()
    kit.capture(root, "window-deming-series.png")

    # ---- 2. Exports: figure as PNG, SVG and PDF; the Deming regression and Pairs sheets as CSV; Use Result as Data.
    for suffix in ("png", "svg", "pdf"):
        target = directory / f"deming-series.{suffix}"
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "deming-series.svg").read_bytes()
    assert (directory / "deming-series.pdf").read_bytes().startswith(b"%PDF")
    app.show("result", index)
    for sheet, name in ((METHOD, "deming-report.csv"), ("Pairs", "deming-pairs.csv")):
        app.result_tabs.select(list(result.tables).index(sheet))
        if sheet == METHOD:
            kit.capture(root, "window-deming-report.png")
        target = directory / name
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, encoding="utf-8-sig")
        assert list(exported.columns)[-len(result.tables[sheet].columns):] == list(result.tables[sheet].columns), (
            name, list(exported.columns))
        assert len(exported) == len(result.tables[sheet]), name
    app.result_tabs.select(list(result.tables).index("Pairs"))
    before = set(app.tables)
    app.use_result_as_data()
    copied = (set(app.tables) - before).pop()
    frame = app.tables[copied].frame()
    assert list(frame.columns) == list(pairs.columns) and len(frame) == len(pairs), list(frame.columns)
    assert list(frame[SERIES_COLUMN].unique()) == ["A", "B $"]

    # ---- 3. Save, reopen: the recipe and every sheet come back the same.
    app.show("data", TITLE)
    assert app.save(), "project save failed"
    app.import_file(path)
    index = next(i for i, run in enumerate(app.runs) if run.method == METHOD)
    app.open_sheet(("result", index))
    wait()
    assert run_options(index) == options, run_options(index)
    for name, want in result.tables.items():
        pd.testing.assert_frame_equal(tables(index)[name], want)

    # ---- 4. Edit a cell of A and exclude a cell of B: each series recalculates on its own.
    slope_b = float(tables(index)[METHOD]["Slope"][1])
    app.show("data", TITLE)
    root.update()
    app.edit_cell(0, columns.index("A"), "6")
    wait()
    edited = tables(index)[METHOD]
    assert abs(float(edited["Slope"][0]) - float(report["Slope"][0])) > 1e-3
    assert float(edited["Slope"][1]) == slope_b
    app.show("data", TITLE)
    root.update()
    app.current_grid.select((2, columns.index("B $")))
    app.toggle_exclusion()
    wait()
    after = tables(index)
    assert list(after[METHOD]["N"]) == [5, 3], after[METHOD]
    assert 2 not in after["Pairs"].loc[after["Pairs"][SERIES_COLUMN] == "B $", "Source row"].tolist()
    status = after[METHOD]["Interval status"]
    assert status[0] == "" and "at least 4" in status[1], list(status)
    assert len(collections(app.runs[index].result.figure)[1].get_segments()) == 3
    app.show("graph", index)
    root.update()
    kit.capture(root, "window-deming-series-edited.png")

    # ---- 5. Switch a series and the projections off by editing the recipe.
    def one_series(dialog):
        assert dialog.method == METHOD and tabs(dialog) == ["Variables", "Uncertainty", "Output"]
        assert dialog.controls[UNCERTAINTY][1].get() == KNOWN_SDS and placed(dialog, X_SD)
        selected = dialog.controls["Y series"][1].curselection()
        assert [dialog.controls["Y series"][1].get(i) for i in selected] == ["A", "B $"]
        kit.select_columns(dialog, "Y series", ["A"])
        dialog.controls[PROJECTIONS][1].set(False)

    app.show("result", index)
    kit.drive_dialog(one_series)
    app.edit_analysis()
    wait()
    options = run_options(index)
    assert options[Y_SERIES] == ["A"] and options[PROJECTIONS] is False, options
    only = tables(index)
    assert list(only[METHOD][SERIES_COLUMN]) == ["A"] and not set(PROJECTED_COLUMNS) & set(only["Pairs"].columns)
    assert not collections(app.runs[index].result.figure)

    # ---- 6. No extra series: the single-series report keeps the SDs and, with projections, the pair columns.
    def single(dialog):
        kit.select_columns(dialog, "Y series", [])
        dialog.controls[PROJECTIONS][1].set(True)

    app.show("result", index)
    kit.drive_dialog(single)
    app.edit_analysis()
    wait()
    options = run_options(index)
    assert options[Y_SERIES] == [] and options[PROJECTIONS] is True, options
    summary = tables(index)[METHOD]["Value"]
    assert float(summary["X error SD"]) == 2.0 and float(summary["Y error SD"]) == 1.0, summary
    assert list(tables(index)["Pairs"].columns)[-2:] == list(PROJECTED_COLUMNS)
    assert SERIES_COLUMN not in tables(index)["Pairs"]
    assert len(collections(app.runs[index].result.figure)) == 1
    assert app.save(), "project save failed"

    # ---- 7. The historical recipe through Analyze: nothing of 0.93 reaches the saved recipe.
    def historical(dialog):
        kit.pick_method(dialog, METHOD)
        dialog.controls["X"][1].set("Dose")
        dialog.controls["Y"][1].set("A")
        assert dialog.deming_visibility() == {RATIO: True, X_SD: False, Y_SD: False, "Confidence level (%)": False}

    app.show("data", TITLE)
    root.update()
    runs_before = len(app.runs)
    kit.drive_dialog(historical)
    app.choose_analysis()
    wait()
    assert len(app.runs) == runs_before + 1
    legacy = len(app.runs) - 1
    assert run_options(legacy) == LEGACY, run_options(legacy)
    assert list(tables(legacy)) == [METHOD, "Data", "Pairs"]
    assert list(tables(legacy)[METHOD].index) == ["N", "Slope", "Intercept", "Y / X measurement error variance"]
    want, _ = oracle(app.tables[TITLE].frame(mask_excluded=True), "Dose", "A", 1.0)
    np.testing.assert_allclose(tables(legacy)[METHOD]["Value"]["Slope"], want["Slope"], rtol=1e-12)
    assert list(tables(legacy)["Pairs"].columns) == ["Source row", "X", "Y", "Fitted Y", RESIDUAL_COLUMN]
    assert not collections(app.runs[legacy].result.figure)

    # ---- 8. Italian and the modern theme: captions, errors in the language, buttons in view, canonical recipes.
    def language_pass(language, theme):
        i18n.set_language(language)
        ui_theme.configure(root, theme)
        root.update()
        words = {"en": ("Variables", "Uncertainty", "Output", "Y error SD must be finite and greater than 0."),
                 "it": ("Variabili", "Incertezza", "Risultati",
                        "SD dell’errore Y: deve essere un numero finito maggiore di 0.")}[language]

        def configure_language(dialog):
            kit.pick_method(dialog, METHOD)
            assert tabs(dialog) == list(words[:3]), tabs(dialog)
            dialog.controls["X"][1].set("Dose")
            dialog.controls["Y"][1].set("A")
            kit.select_columns(dialog, "Y series", ["A", "B $"])
            dialog.controls[UNCERTAINTY][1].set(KNOWN_SDS)
            dialog.controls[X_SD][1].set("2")
            dialog.controls[Y_SD][1].set("0")
            dialog.update()
            with patch.object(kit.messagebox, "showerror") as report_error:
                assert dialog.validate() is False
            assert report_error.call_args.args[1] == words[3], report_error.call_args
            assert current_tab(dialog) == words[1], current_tab(dialog)
            assert dialog.focus_get() == dialog.field_rows[Y_SD][1], dialog.focus_get()
            buttons(dialog)
            dialog.controls[Y_SD][1].set("1")
            dialog.controls[PROJECTIONS][1].set(True)
            dialog.focus_field(X_SD)
            kit.capture(dialog, f"window-deming-{language}-{theme}.png")
            assert dialog.validate() is True
            recipe = dialog.result[1]
            assert recipe[UNCERTAINTY] == KNOWN_SDS and recipe[Y_SERIES] == ["A", "B $"], recipe
            assert recipe[X_SD] == 2.0 and recipe[Y_SD] == 1.0 and RATIO not in recipe, recipe

        app.show("data", TITLE)
        root.update()
        runs_before = len(app.runs)
        kit.drive_dialog(configure_language)
        app.choose_analysis()
        wait()
        assert len(app.runs) == runs_before + 1
        last = len(app.runs) - 1
        assert list(tables(last)[METHOD][SERIES_COLUMN]) == ["A", "B $"], tables(last)[METHOD]
        assert [len(item.get_segments()) for item in collections(app.runs[last].result.figure)] == [5, 3]
        app.show("graph", last)
        root.update()
        kit.capture(root, f"window-deming-series-{language}-{theme}.png")

    for language, theme in (("it", "standard"), ("en", "modern"), ("it", "modern")):
        language_pass(language, theme)
    ui_theme.configure(root, "standard")
    i18n.set_language("en")
    root.update()
