"""Desktop smoke check for PCA component selection and parallel analysis.

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=pca-selection``) calls
:func:`check_pca_selection`.
"""
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.colors import to_hex
from tkinter import ttk

from .data import Dataset, save_project
from .i18n import active_language, set_language, ui
from .pca_graphs import GRAPH, SCREE, SETTINGS
from .pca_retention import (ALL, EIGENVALUE, PARALLEL, PERCENTILE, REFERENCE_GID, RETAINED, SAVE, SEED, SELECTION,
                            SELECTION_SHEET, SETTINGS_SHEET, SCORES_SHEET, SIMULATIONS, THRESHOLD, assess as real_assess)

REFERENCE_KEY = "line:1:95th percentile"
HISTORICAL = ["Explained variance", "Eigenvectors", "Scores"]


def check_pca_selection(root, app, directory, kit):
    capture, drive_dialog, pick, select = kit.capture, kit.drive_dialog, kit.pick_method, kit.select_columns
    wait, errors = kit.wait_for_calculation, kit.errors
    previous_geometry = root.geometry()
    language = active_language()
    root.geometry("1024x768+0+0")
    try:
        _check(root, app, directory, capture, drive_dialog, pick, select, wait, errors, kit)
    finally:
        set_language(language)
        root.geometry(previous_geometry)


def _shown(dialog, name):
    return bool(dialog.field_rows[name][1].grid_info())


def _button(dialog, text):
    pending = [dialog]
    while pending:
        widget = pending.pop()
        if isinstance(widget, ttk.Button) and widget.cget("text") == ui(text):
            return widget
        pending.extend(widget.winfo_children())
    raise AssertionError(text)


def _reachable(dialog, root, text):
    button = _button(dialog, text)
    dialog.update_idletasks()
    assert button.winfo_ismapped(), text
    bounds = root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()
    assert button.winfo_rootx() + button.winfo_width() <= bounds[0] + 1, text
    assert button.winfo_rooty() + button.winfo_height() <= bounds[1] + 1, text
    return button


def _reference(figure):
    return next(line for line in figure.axes[0].lines if line.get_gid() == REFERENCE_GID)


def _check(root, app, directory, capture, drive_dialog, pick, select, wait, errors, kit):
    messagebox, filedialog = kit.messagebox, kit.filedialog
    analysis, format_graph = kit.AnalysisDialog, kit.GraphFormatDialog

    def drive(action):
        drive_dialog(analysis, action)

    path = directory / "pca-selection.alab"
    title = "Components"
    frame = pd.DataFrame({
        "A": [1.4142135623730951, -1.4142135623730951, 0.7071067811865476, -0.7071067811865476, 0.0, 0.0, np.nan],
        "B": [1.4142135623730951, -1.4142135623730951, -0.7071067811865476, 0.7071067811865476, 0.0, 0.0, 9.0],
        "Label": ["città A", "città B", "gruppo $C", "gruppo <D>", "centro", "centro", "incompleta"],
    })
    save_project(path, {title: Dataset(frame)})
    app.import_file(path)

    def italian(dialog):
        pick(dialog, "Principal component analysis")
        assert dialog.field_rows[SELECTION][0].cget("text") == "Selezione"
        tab = dialog.field_rows[SELECTION][0].master
        assert dialog.fields.tab(tab, "text") == "Selezione"
        binding = dialog.choice_bindings[SELECTION]
        assert dialog.controls[SELECTION][1].get() == ALL
        assert binding.display.get() == "Tutte"
        dialog.controls[SELECTION][1].set(PARALLEL)
        dialog.update_idletasks()
        assert dialog.controls[SELECTION][1].get() == PARALLEL
        assert binding.display.get() == "Analisi parallela"
        assert _shown(dialog, SIMULATIONS) and not _shown(dialog, RETAINED)
        dialog.ok = dialog.cancel

    set_language("it")
    drive(italian)
    app.choose_analysis()
    assert not errors, errors
    set_language("en")

    def configure(dialog):
        pick(dialog, "Principal component analysis")
        select(dialog, "Variables", {"A", "B"})
        dialog.controls["Standardize"][1].set(False)
        dialog.controls[GRAPH][1].set(SCREE)
        dialog.controls[SELECTION][1].set("Fixed number")
        dialog.update_idletasks()
        assert _shown(dialog, RETAINED) and not _shown(dialog, SIMULATIONS)
        dialog.controls[RETAINED][1].set("100")
        with patch.object(messagebox, "showerror") as shown:
            assert dialog.validate() is False
        assert dialog.winfo_exists() and dialog.result is None
        assert "Retained components" in shown.call_args.args[1], shown.call_args
        assert dialog.controls[RETAINED][1].get() == "100"
        assert dialog.focus_get() is dialog.field_rows[RETAINED][1]
        assert str(dialog.fields.select()) == str(dialog.field_rows[RETAINED][1].master)
        capture(dialog, "window-pca-selection-error.png")
        dialog.controls[RETAINED][1].set("2")
        assert dialog.validate() is True
        dialog.result = None
        dialog.controls[SELECTION][1].set(PARALLEL)
        dialog.controls[SIMULATIONS][1].set("10")
        dialog.controls[SEED][1].set("42")
        dialog.controls[PERCENTILE][1].set("95")
        dialog.controls[SAVE][1].set(True)
        dialog.update_idletasks()
        assert dialog.field_rows[SELECTION][0].cget("text") == "Selection"
        assert _shown(dialog, SEED) and not _shown(dialog, RETAINED)
        dialog.fields.select(dialog.field_rows[SELECTION][0].master)
        dialog.update_idletasks()
        assert dialog.winfo_reqwidth() <= 1024, dialog.winfo_reqwidth()
        assert dialog.winfo_reqheight() <= 768, dialog.winfo_reqheight()
        _reachable(dialog, root, "Run Analysis")
        _reachable(dialog, root, "Cancel")
        capture(dialog, "window-pca-selection-dialog.png")
        assert dialog.validate() is True
        assert dialog.result[1][SELECTION] == PARALLEL
        assert dialog.result[1][SEED] == 42
        dialog.result = None

    seen = {}

    def on_worker(frame, options, parts, eigenvectors, scores):
        if options.get(SELECTION) == PARALLEL:
            seen["id"] = threading.get_ident()
            time.sleep(1.2)
        return real_assess(frame, options, parts, eigenvectors, scores)

    with patch("analisi.pca_retention.assess", side_effect=on_worker):
        drive(configure)
        app.choose_analysis()
        deadline = time.monotonic() + 8
        while app.pending is None or "id" not in seen:
            if time.monotonic() > deadline:
                raise TimeoutError("parallel analysis did not reach the worker")
            root.update()
            time.sleep(0.02)
        assert seen["id"] != threading.get_ident()
        worker = next(thread for thread in threading.enumerate() if thread.ident == seen["id"])
        assert worker.name.startswith("Trama")
        app.choose_analysis()
        assert any("Wait for the current analysis" in item for item in errors), errors
        errors.clear()
        wait()
    assert not errors, errors

    run = app.runs[0]
    tables = run.result.tables
    assert list(tables)[:3] == HISTORICAL
    assert list(tables)[-5:] == [SELECTION_SHEET, SETTINGS_SHEET, SCORES_SHEET, "Selected loadings", "Parallel eigenvalues"]
    np.testing.assert_allclose(tables["Explained variance"]["Eigenvalue"], [1.6, 0.4])
    assert len(tables["Explained variance"]) == 2
    assert tables[SCORES_SHEET]["Source row"].tolist() == [0, 1, 2, 3, 4, 5]
    assert tables["Parallel eigenvalues"]["Simulation"].tolist() == list(range(1, 11))
    assert run.options[SELECTION] == PARALLEL and run.options[SEED] == 42
    assert "Selezione" not in run.options.values()
    assert "Criterion" not in tables[SETTINGS].index
    observed, reference = run.result.figure.axes[0].lines
    assert observed.get_label().startswith("_")
    assert reference.get_gid() == REFERENCE_GID
    assert "95" in reference.get_label()
    assert run.result.figure.axes[0].get_legend() is not None

    app.show("result", 0)
    app.result_tabs.select(list(tables).index(SELECTION_SHEET))
    root.update()
    capture(root, "window-pca-selection-result.png")
    app.show("graph", 0)
    root.update()
    capture(root, "window-pca-selection-graph.png")

    for suffix in ("png", "svg", "pdf"):
        app.show("graph", 0)
        target = directory / f"pca-selection.{suffix}"
        with patch.object(filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, suffix
    svg = (directory / "pca-selection.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and REFERENCE_GID in svg and "95" in svg
    assert (directory / "pca-selection.pdf").read_bytes().startswith(b"%PDF")
    csv_path = directory / "pca-selection-scores.csv"
    app.show("result", 0)
    app.result_tabs.select(list(app.runs[0].result.tables).index(SCORES_SHEET))
    with patch.object(filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path)
    assert exported["Source row"].tolist() == [0, 1, 2, 3, 4, 5]

    app.show("graph", 0)
    root.update()
    original = to_hex(_reference(app.runs[0].result.figure).get_color())
    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector is not None
    window_bottom = root.winfo_rooty() + root.winfo_height()
    for button in (inspector.apply_button, inspector.cancel_button):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= window_bottom + 1
    keys = [item["key"] for item in inspector.elements]
    assert inspector.select_group(REFERENCE_KEY), keys
    inspector.vars["element:color"].set("#176676")
    inspector._now("element:color")
    assert to_hex(_reference(app.runs[0].result.figure).get_color()) == "#176676"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert to_hex(_reference(app.runs[0].result.figure).get_color()) == original

    app.toggle_inspector()
    root.update()
    inspector = app.inspector
    assert inspector.select_group(REFERENCE_KEY)
    inspector.vars["element:color"].set("#176676")
    inspector._now("element:color")
    assert inspector.apply()
    assert to_hex(_reference(app.runs[0].result.figure).get_color()) == "#176676"
    inspector.cancel_button.invoke()
    root.update()
    assert to_hex(_reference(app.runs[0].result.figure).get_color()) == "#176676"

    def retitle(dialog):
        dialog.inputs["title"].set("Parallel scree")
        capture(dialog, "window-pca-selection-format.png")

    drive_dialog(format_graph, retitle)
    app.format_graph()
    assert app.runs[0].result.figure.axes[0].get_title() == "Parallel scree"

    before_tables = set(app.tables)
    app.show("result", 0)
    app.result_tabs.select(list(app.runs[0].result.tables).index(SCORES_SHEET))
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert added == {SCORES_SHEET}
    assert app.tables[SCORES_SHEET].raw["Source row"].tolist() == [0, 1, 2, 3, 4, 5]

    before = app.runs[0].result.tables["Explained variance"]["Eigenvalue"].to_numpy().copy()
    app.show("data", title)
    app.edit_cell(0, 0, "3")
    wait()
    assert not np.allclose(app.runs[0].result.tables["Explained variance"]["Eigenvalue"], before)
    app.show("data", title)
    app.current_grid.active_cell = (1, 0)
    app.toggle_exclusion()
    wait()
    assert app.runs[0].result.tables[SCORES_SHEET]["Source row"].tolist() == [0, 2, 3, 4, 5]
    assert app.runs[0].options[SELECTION] == PARALLEL
    assert app.save()
    app.import_file(app.path)
    assert app.runs[0].result is None
    app.open_sheet(("graph", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.result is not None
    assert reopened.options[SELECTION] == PARALLEL and reopened.options[SEED] == 42
    assert reopened.result.figure.axes[0].get_title() == "Parallel scree"
    assert _reference(reopened.result.figure).get_gid() == REFERENCE_GID
    assert reopened.result.tables[SCORES_SHEET]["Source row"].tolist() == [0, 2, 3, 4, 5]
    root.update()
    capture(root, "window-pca-selection-reopen.png")

    if root.winfo_screenwidth() >= 1680 and root.winfo_screenheight() >= 1050:
        root.geometry("1600x1000+0+0")
        root.update()
        capture(root, "window-pca-selection-1600.png")

        def wide(dialog):
            pick(dialog, "Principal component analysis")
            dialog.fields.select(dialog.field_rows[SELECTION][0].master)
            dialog.update_idletasks()
            _reachable(dialog, root, "Run Analysis")
            capture(dialog, "window-pca-selection-dialog-1600.png")
            dialog.ok = dialog.cancel

        drive(wide)
        app.show("data", title)
        app.choose_analysis()
        assert not errors, errors
    elif kit.screenshots:
        raise RuntimeError("The 1600×1000 view needs a screen of at least 1680×1050.")

    def zero(dialog):
        dialog.controls[SELECTION][1].set(THRESHOLD)
        dialog.controls[EIGENVALUE][1].set("100")
        dialog.update_idletasks()
        assert _shown(dialog, EIGENVALUE) and not _shown(dialog, SIMULATIONS)
        assert dialog.validate() is True
        dialog.result = None

    drive(zero)
    app.show("graph", 0)
    app.edit_analysis()
    wait()
    zeroed = app.runs[0]
    assert zeroed.options[SELECTION] == THRESHOLD and zeroed.options[EIGENVALUE] == 100
    assert list(zeroed.result.tables[SCORES_SHEET].columns) == ["Source row"]
    assert list(zeroed.result.tables["Selected loadings"].columns) == ["Variable"]
    assert "Parallel eigenvalues" not in zeroed.result.tables
    assert all(line.get_gid() != REFERENCE_GID for line in zeroed.result.figure.axes[0].lines)
    app.show("result", 0)
    app.result_tabs.select(list(zeroed.result.tables).index(SCORES_SHEET))
    root.update()
    capture(root, "window-pca-selection-zero.png")
    before_tables = set(app.tables)
    app.use_result_as_data()
    added = set(app.tables) - before_tables
    assert len(added) == 1
    assert list(app.tables[added.pop()].raw.columns) == ["Source row"]

    def hidden(dialog):
        pick(dialog, "Principal component analysis")
        select(dialog, "Variables", {"A", "B"})
        dialog.controls["Standardize"][1].set(False)
        dialog.controls[GRAPH][1].set(SCREE)
        dialog.controls[SELECTION][1].set(PARALLEL)
        dialog.controls[SIMULATIONS][1].set("nope")
        dialog.controls[SEED][1].set("nope")
        dialog.controls[PERCENTILE][1].set("nope")
        dialog.controls[SELECTION][1].set(ALL)
        dialog.update_idletasks()
        assert not _shown(dialog, SIMULATIONS)
        assert dialog.validate() is True
        options = dialog.result[1]
        assert options[SELECTION] == ALL
        assert SIMULATIONS not in options and SEED not in options and PERCENTILE not in options
        dialog.result = None

    drive(hidden)
    app.show("data", title)
    app.choose_analysis()
    wait()
    plain = app.runs[-1]
    assert plain.options[SELECTION] == ALL
    assert SELECTION_SHEET not in plain.result.tables
    assert list(plain.result.tables)[:3] == HISTORICAL

    legacy_path = directory / "pca-selection-legacy.alab"
    legacy = Dataset(frame.copy())
    legacy.analyses.append(("Principal component analysis", {"Variables": ["A", "B"], "Standardize": True}))
    save_project(legacy_path, {"Legacy": legacy})
    app.import_file(legacy_path)
    assert app.runs[0].result is None
    app.open_sheet(("graph", 0))
    wait()
    old = app.runs[0]
    assert SELECTION not in old.options
    assert list(old.result.tables) == HISTORICAL
    assert old.result.figure.axes[0].get_xlabel() == "PC1"
    assert old.result.figure.axes[0].get_ylabel() == "PC2"
    np.testing.assert_allclose(old.result.tables["Explained variance"]["Eigenvalue"], [1.6, 0.4])
