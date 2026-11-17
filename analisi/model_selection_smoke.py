"""Desktop smoke check for Compare models (AICc), kept apart from tramastat.py.

``tramastat.py --smoke`` calls :func:`check_model_selection` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=model-selection python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import model_selection as ms
from .data import Dataset, save_project

TABLE = "Saturation"
FRAME = pd.DataFrame({
    "Dose": [.5, 1, 2, 3, 4, 6, 8, 10, 12, 15],
    "Response": [2.15, 3.1333, 5.1, 6.18, 6.5467, 7.55, 7.84, 8.5333, 8.4914, 8.9235],
    "Note": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]})
LEGACY_TABLE = "Binding"
LEGACY = pd.read_csv(__import__("pathlib").Path(__file__).resolve().parents[1] / "tests" / "data"
                     / "model_selection" / "legacy-nested.csv")
LEGACY_OPTIONS = {"X": "X", "Y": "Y", "Group": None,
                  "Nested models": "One-site specific binding → One-site total binding", "Weighting": "Unweighted"}


def check_model_selection(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    path = directory / "model-selection.alab"
    legacy = Dataset(LEGACY.copy())
    legacy.analyses.append(("Compare nonlinear models", dict(LEGACY_OPTIONS)))
    save_project(path, {TABLE: Dataset(FRAME.copy()), LEGACY_TABLE: legacy})
    app.import_file(path)
    base = len(app.runs) - 1
    # The F test keeps its own method, sheet and values next to the new one.
    app.open_sheet(("result", base))
    wait()
    old = app.runs[base]
    assert old.method == "Compare nonlinear models" and list(old.result.tables) == ["Extra sum-of-squares F test"]
    assert old.result.tables["Extra sum-of-squares F test"].index.tolist() == ["All"]

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, shot=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert field in message, message
        # The error stays on its field: the tab that holds it is shown again.
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot:
            tools.capture(dialog, shot)
        return message

    app.show("data", TABLE)

    def choose(dialog):
        tools.pick_method(dialog, ms.COMPARE_MODELS)
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Data", "Models", "Output"]
        picker = dialog.controls[ms.MODELS_FIELD][1]
        assert picker.values() == ["Straight line", "Polynomial (order 2)"]
        assert dialog.controls[ms.SHOW_GRAPH][1].get() is True
        assert placed(dialog, "Group")
        dialog.controls["X"][1].set("Dose")
        dialog.controls["Y"][1].set("Response")
        # Two non-nested saturation models, picked one at a time from the catalog list.
        for _ in range(2):
            picker.listbox.selection_clear(0, "end")
            picker.listbox.selection_set(0)
            picker.remove()
        assert picker.values() == []
        picker.add_model("Michaelis–Menten")
        message = rejected(dialog, ms.MODELS_FIELD, "window-aicc-error.png")
        assert "at least 2" in message, message
        picker.add_model("Michaelis–Menten")
        assert "more than once" in rejected(dialog, ms.MODELS_FIELD)
        picker.listbox.selection_clear(0, "end")
        picker.listbox.selection_set(1)
        picker.remove()
        picker.add_model("One-phase association")
        picker.add_model("Straight line")
        picker.listbox.selection_clear(0, "end")
        picker.listbox.selection_set(2)
        picker.move(-1)
        picker.move(-1)
        assert picker.values() == ["Straight line", "Michaelis–Menten", "One-phase association"]
        picker.listbox.selection_clear(0, "end")
        picker.listbox.selection_set(0)
        picker.remove()
        assert picker.values() == ["Michaelis–Menten", "One-phase association"]
        dialog.fields.select(1)
        dialog.update()
        tools.capture(dialog, "window-aicc-options.png")

    tools.drive_dialog(tools.AnalysisDialog, choose)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.method == ms.COMPARE_MODELS
    assert run.options[ms.MODELS_FIELD] == ["Michaelis–Menten", "One-phase association"]
    assert list(run.result.tables) == [ms.RANKING, ms.PARAMETERS, ms.SUMMARY]
    ranking = run.result.tables[ms.RANKING]
    assert ranking["Model"].tolist() == ["Michaelis–Menten", "One-phase association"], ranking
    assert ranking["N"].tolist() == [10, 10] and ranking["K"].tolist() == [3, 4]
    assert abs(ranking["Akaike weight"].sum() - 1) < 1e-12
    assert run.result.tables[ms.SUMMARY]["Best model"].tolist() == ["Michaelis–Menten"]
    axes = run.result.figure.axes[0]
    assert [text.get_text() for text in axes.get_legend().get_texts()] == [
        "Observations", "Michaelis–Menten", "One-phase association"]
    app.show("graph", index)
    tools.capture(root, "window-aicc-graph.png")
    for suffix in ("png", "svg"):
        target = directory / f"model-selection.{suffix}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.show("graph", index)
            app.export()
        assert target.stat().st_size > 1000, target
    assert b"<svg" in (directory / "model-selection.svg").read_bytes()
    app.show("result", index)
    app.result_tabs.select(0)
    tools.capture(root, "window-aicc-ranking.png")
    csv = directory / "model-ranking.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv)):
        app.export()
    exported = pd.read_csv(csv, encoding="utf-8-sig")
    assert exported["Model"].tolist() == ranking["Model"].tolist() and "Akaike weight" in exported

    # Edit a cell, then exclude another: the ranking recalculates from the complete rows left.
    app.show("data", TABLE)
    columns = list(app.tables[TABLE].raw.columns)
    before = float(app.runs[index].result.tables[ms.RANKING]["RSS"].iloc[0])
    app.edit_cell(3, columns.index("Response"), "7.5")
    wait()
    after = app.runs[index].result.tables[ms.RANKING]
    assert abs(float(after["RSS"].iloc[0]) - before) > 1e-3
    app.show("data", TABLE)
    app.current_grid.select((9, columns.index("Response")))
    app.toggle_exclusion()
    wait()
    excluded = app.runs[index].result.tables[ms.RANKING]
    assert excluded["N"].tolist() == [9, 9], excluded
    app.show("result", index)
    tools.capture(root, "window-aicc-recalculated.png")

    # Cancelling an edit of the analysis keeps the earlier options and tables.
    def find(parent):
        for child in parent.winfo_children():
            if isinstance(child, tools.AnalysisDialog):
                return child
            found = find(child)
            if found is not None:
                return found
        return None

    def cancel_change():
        dialog = find(root)
        assert dialog is not None
        dialog.controls[ms.MODELS_FIELD][1].add_model("Straight line")
        dialog.cancel()

    snapshot = (dict(app.runs[index].options), app.runs[index].result.tables[ms.RANKING].copy())
    root.after(200, cancel_change)
    app.edit_analysis()
    wait()
    assert app.runs[index].options == snapshot[0]
    pd.testing.assert_frame_equal(app.runs[index].result.tables[ms.RANKING], snapshot[1])

    # Edit the analysis: a third model, graph off. The Graphs entry follows the option.
    def third(dialog):
        picker = dialog.controls[ms.MODELS_FIELD][1]
        assert picker.values() == ["Michaelis–Menten", "One-phase association"]
        picker.add_model("Straight line")
        dialog.controls[ms.SHOW_GRAPH][1].set(False)

    tools.drive_dialog(tools.AnalysisDialog, third)
    app.edit_analysis()
    wait()
    changed = app.runs[index]
    assert changed.options[ms.MODELS_FIELD][-1] == "Straight line" and changed.result.figure is None
    assert len(changed.result.tables[ms.RANKING]) == 3
    graphs = [name for section, rows, *_ in app.sheet_sections() if section == "Graphs" for name, _ in rows]
    assert changed.name not in graphs, graphs

    # Use Result as Data copies the ranking sheet into an editable table.
    app.show("result", index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    copied = app.tables[app.active_data].frame()
    assert list(copied.columns)[:3] == ["Group", "Model", "N"] and len(copied) == 3, list(copied.columns)

    # Save and reopen: options and every sheet come back identically (runs follow the table order).
    saved = [(dict(item.options), {k: t.copy() for k, t in item.result.tables.items()})
             for item in app.runs if item.method == ms.COMPARE_MODELS]
    assert len(saved) == 1
    assert app.save()
    app.import_file(app.path)
    for position in range(len(app.runs)):
        app.open_sheet(("result", position))
        wait()
    again = [item for item in app.runs if item.method == ms.COMPARE_MODELS]
    assert len(again) == 1
    assert again[0].options == saved[0][0]
    assert list(again[0].result.tables) == list(saved[0][1])
    for name, table in saved[0][1].items():
        pd.testing.assert_frame_equal(again[0].result.tables[name], table)
    assert again[0].result.figure is None
    legacy_runs = [item for item in app.runs if item.method == "Compare nonlinear models"]
    assert len(legacy_runs) == 1 and legacy_runs[0].result.tables["Extra sum-of-squares F test"].shape == (1, 8)
