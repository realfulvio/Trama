"""Desktop smoke check for heat-map cell value label formatting, font, color and affixes.

``tramastat.py --smoke`` calls :func:`check_heat_map_cell_labels` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=heatmap-cell-labels python tramastat.py --smoke DIR``.

Synthetic data only: packaged fixtures from ``tests/data/heatmap_072`` and ``tests/data/heatmap_073``.
Outputs and screenshots go to ``DIR/heatmap-cell-labels``.
"""
import json
import shutil
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.collections import QuadMesh
from matplotlib.colors import to_rgba

from . import i18n
from .data import Dataset, save_project
from .heatmap import HEAT_MAP
from .heatmap_cell_labels import (
    CELL_LABEL_COLOR,
    CELL_LABEL_COLOR_MODE,
    CELL_LABEL_DECIMALS,
    CELL_LABEL_FONT_SIZE,
    CELL_LABEL_NUMBER_FORMAT,
    CELL_LABEL_PREFIX,
    CELL_LABEL_SUFFIX,
)

FIXTURES_072 = Path(__file__).resolve().parent.parent / "tests" / "data" / "heatmap_072"
FIXTURES_073 = Path(__file__).resolve().parent.parent / "tests" / "data" / "heatmap_073"
LEGACY = json.loads((FIXTURES_072 / "legacy-072.json").read_text(encoding="utf-8"))


def check_heat_map_cell_labels(root, app, directory, tools):
    """Exercise legacy preservation, 1024x768 & 1600x1000 dialog validation/focus, swatch/picker,
    EN/IT round-trip, Long categories, edit/exclusion/Undo, Use Result as Data, Format Graph,
    Inspector Apply/Cancel, CSV/PNG/SVG/PDF export, 2-panel layout, and .alab reopen (graph first)."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "heatmap-cell-labels"
    out.mkdir(exist_ok=True)
    original_geometry = root.geometry()
    original_language = i18n.active_language()

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def focus_target(widget):
        return widget.focus_target() if hasattr(widget, "focus_target") else (
            widget.winfo_children()[0] if isinstance(widget, ttk.Frame) and widget.winfo_children() else widget)

    def run_button(dialog):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == i18n.ui("Run Analysis"):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog, max_w, max_h):
        dialog.update()
        button = run_button(dialog)
        assert button is not None and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= max_h, (button.winfo_rooty(), max_h)
        assert button.winfo_rootx() + button.winfo_width() <= max_w, (button.winfo_rootx(), max_w)
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= max_h
            assert dialog.winfo_rootx() + dialog.winfo_width() <= max_w

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        assert dialog.focus_get() is focus_target(dialog.field_rows[field][1]), dialog.focus_get()
        if shot_name:
            shot(dialog, shot_name)
        return message

    def mesh(index):
        figure = app.runs[index].result.figure
        found = next(c for ax in figure.axes for c in ax.collections if isinstance(c, QuadMesh))
        found.update_scalarmappable()
        return found

    def cell_texts(index):
        axes = app.runs[index].result.figure.axes[0]
        return sorted((round(float(t.get_position()[0]), 8), round(float(t.get_position()[1]), 8), t.get_text())
                      for t in axes.texts)

    def find_run(title, number=0):
        return [i for i, run in enumerate(app.runs) if run.title == title][number]

    def edit(index, action):
        app.show("graph", index)
        root.update()
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.edit_analysis(initial_field="Show cell values")
        wait()

    try:
        # 1. Legacy project without new keys: unchanged QuadMesh RGBA and no new keys added.
        legacy_path = directory / "heatmap-cell-labels-legacy.alab"
        shutil.copy(FIXTURES_072 / "legacy-072.alab", legacy_path)
        app.import_file(legacy_path)
        legacy_idx = find_run("Numeric", 0)
        app.open_sheet(("graph", legacy_idx))
        wait()
        np.testing.assert_allclose(mesh(legacy_idx).get_facecolors(), LEGACY["matrix"]["rgba"], rtol=1e-12, atol=1e-12)
        for key in (CELL_LABEL_NUMBER_FORMAT, CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE,
                    CELL_LABEL_COLOR_MODE, CELL_LABEL_COLOR, CELL_LABEL_PREFIX, CELL_LABEL_SUFFIX):
            assert key not in app.runs[legacy_idx].options

        # 2. Synthetic matrix + categories project.
        matrix_df = pd.read_csv(FIXTURES_073 / "matrix.csv")
        cat_df = pd.read_csv(FIXTURES_073 / "categories.csv", dtype=str)
        project_path = directory / "heatmap-cell-labels-work.alab"
        matrix_opts = {"Input format": "Matrix", "Variables": ["A", "B", "C"], "Row labels": "Row",
                       "Show cell values": False}
        cat_opts = {"Input format": "Long categories", "X categories": "Col", "Y categories": "Row",
                    "Values": "Value", "Show cell values": True, "Mark missing cells": True}
        save_project(project_path, {
            "Matrix": Dataset(matrix_df, analyses=[(HEAT_MAP, matrix_opts)]),
            "Categories": Dataset(cat_df, analyses=[(HEAT_MAP, cat_opts)]),
        })
        app.import_file(project_path)
        mat_idx = find_run("Matrix", 0)
        cat_idx = find_run("Categories", 0)
        app.open_sheet(("graph", mat_idx))
        wait()
        baseline_rgba = mesh(mat_idx).get_facecolors().copy()

        # 3. 1024x768 main window: visibility, validation/focus, swatch, Fixed + custom style, export CSV/PNG/SVG/PDF.
        root.geometry("1024x768+0+0")
        root.update()
        # Resizing the main window does not change the screen used for dialog placement.
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()

        def configure_fixed_en(dialog):
            controls = dialog.controls
            assert not placed(dialog, CELL_LABEL_NUMBER_FORMAT)
            assert not placed(dialog, CELL_LABEL_COLOR)
            controls["Show cell values"][1].set(True)
            dialog.update()
            assert placed(dialog, CELL_LABEL_NUMBER_FORMAT)
            assert not placed(dialog, CELL_LABEL_DECIMALS)
            assert placed(dialog, CELL_LABEL_FONT_SIZE)
            assert placed(dialog, CELL_LABEL_COLOR_MODE)
            assert not placed(dialog, CELL_LABEL_COLOR)
            assert placed(dialog, CELL_LABEL_PREFIX)
            assert placed(dialog, CELL_LABEL_SUFFIX)

            controls[CELL_LABEL_NUMBER_FORMAT][1].set("Fixed")
            controls[CELL_LABEL_COLOR_MODE][1].set("Custom")
            dialog.update()
            assert placed(dialog, CELL_LABEL_DECIMALS)
            assert placed(dialog, CELL_LABEL_COLOR)

            controls[CELL_LABEL_DECIMALS][1].set("2.5")
            rejected(dialog, CELL_LABEL_DECIMALS, "whole number from 0 to 8")
            controls[CELL_LABEL_DECIMALS][1].set("2")

            controls[CELL_LABEL_FONT_SIZE][1].set("nan")
            rejected(dialog, CELL_LABEL_FONT_SIZE, "6 to 36")
            controls[CELL_LABEL_FONT_SIZE][1].set("12,5")

            controls[CELL_LABEL_COLOR][1].set("nonsense")
            rejected(dialog, CELL_LABEL_COLOR, "valid color")
            controls[CELL_LABEL_COLOR][1].set("#ff3300")

            controls[CELL_LABEL_PREFIX][1].set("a" * 81)
            rejected(dialog, CELL_LABEL_PREFIX, "80")
            controls[CELL_LABEL_PREFIX][1].set("$x$_")
            controls[CELL_LABEL_SUFFIX][1].set(" %")
            reachable(dialog, screen_w, screen_h)
            dialog.fields.select(dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][1].master)
            dialog.update()
            shot(dialog, "window-heatmap-cell-labels-dialog-1024.png")

        edit(mat_idx, configure_fixed_en)
        np.testing.assert_allclose(mesh(mat_idx).get_facecolors(), baseline_rgba, rtol=0, atol=0)
        texts = app.runs[mat_idx].result.figure.axes[0].texts
        assert (0.5, 0.5, "$x$_1.23 %") in cell_texts(mat_idx)
        assert (1.5, 0.5, "$x$_0.00 %") in cell_texts(mat_idx)
        assert all(not t.get_parse_math() and abs(t.get_fontsize() - 12.5) < 1e-9
                   and np.allclose(to_rgba(t.get_color()), to_rgba("#ff3300")) for t in texts)
        app.show("graph", mat_idx)
        root.update()
        shot(root, "window-heatmap-cell-labels-fixed-en.png")

        for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
            target = out / f"heatmap-cell-labels-fixed.{extension}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            content = target.read_bytes()
            assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000
        assert "$x$_1.23 %" in (out / "heatmap-cell-labels-fixed.svg").read_text(encoding="utf-8")

        app.show("result", mat_idx)
        root.update()
        csv_target = out / "heatmap-cell-labels-data.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_target)):
            app.export()
        assert csv_target.stat().st_size > 10

        # 4. Long categories: numeric label controls hidden, literal category text + missing unaffixed.
        app.open_sheet(("graph", cat_idx))
        wait()

        def configure_categories(dialog):
            assert not placed(dialog, CELL_LABEL_NUMBER_FORMAT)
            assert not placed(dialog, CELL_LABEL_DECIMALS)
            assert placed(dialog, CELL_LABEL_FONT_SIZE)
            dialog.controls[CELL_LABEL_FONT_SIZE][1].set("11")
            dialog.controls[CELL_LABEL_COLOR_MODE][1].set("Custom")
            dialog.update()
            dialog.controls[CELL_LABEL_COLOR][1].set("navy")
            dialog.controls[CELL_LABEL_PREFIX][1].set("[")
            dialog.controls[CELL_LABEL_SUFFIX][1].set("]")
            reachable(dialog, screen_w, screen_h)

        edit(cat_idx, configure_categories)
        assert cell_texts(cat_idx) == [(0.5, 0.5, "[$p$_A]"), (0.5, 1.5, "[alpha]"), (1.5, 0.5, "[1]"), (1.5, 1.5, "×")]
        app.show("graph", cat_idx)
        root.update()
        shot(root, "window-heatmap-cell-labels-categories.png")

        # 5. Italian UI & error, canonical English recipe preserved across IT -> EN.
        if root.winfo_screenwidth() >= 1600 and root.winfo_screenheight() >= 1000:
            root.geometry("1600x1000+0+0")
            root.update()
        it_w = min(root.winfo_width(), root.winfo_screenwidth())
        it_h = min(root.winfo_height(), root.winfo_screenheight())
        i18n.set_language("it")

        def configure_italian(dialog):
            assert dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][0].cget("text") == "Formato numerico etichette"
            assert dialog.field_rows[CELL_LABEL_DECIMALS][0].cget("text") == "Decimali etichette"
            assert dialog.field_rows[CELL_LABEL_FONT_SIZE][0].cget("text") == "Dimensione font etichette"
            assert dialog.field_rows[CELL_LABEL_COLOR_MODE][0].cget("text") == "Modalità colore etichette"
            assert dialog.field_rows[CELL_LABEL_COLOR][0].cget("text") == "Colore etichette"
            assert dialog.field_rows[CELL_LABEL_PREFIX][0].cget("text") == "Prefisso etichette"
            assert dialog.field_rows[CELL_LABEL_SUFFIX][0].cget("text") == "Suffisso etichette"
            combo = dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][1]
            assert list(combo.cget("values")) == ["Automatico", "Decimali fissi", "Scientifico"]
            combo.set("Scientifico")
            combo.event_generate("<<ComboboxSelected>>")
            dialog.update()
            dialog.controls[CELL_LABEL_DECIMALS][1].set("2,5")
            rejected(dialog, CELL_LABEL_DECIMALS, "numero intero da 0 a 8",
                     "window-heatmap-cell-labels-it-error.png", caption="Decimali etichette")
            dialog.controls[CELL_LABEL_DECIMALS][1].set("3")
            dialog.controls[CELL_LABEL_FONT_SIZE][1].set("11,5")
            reachable(dialog, it_w, it_h)
            dialog.fields.select(dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][1].master)
            dialog.update()
            shot(dialog, "window-heatmap-cell-labels-it-dialog.png")

        edit(mat_idx, configure_italian)
        it_recipe = dict(app.runs[mat_idx].options)
        assert it_recipe[CELL_LABEL_NUMBER_FORMAT] == "Scientific"
        assert it_recipe[CELL_LABEL_DECIMALS] == 3
        assert it_recipe[CELL_LABEL_FONT_SIZE] == 11.5
        assert it_recipe[CELL_LABEL_COLOR_MODE] == "Custom"
        app.show("graph", mat_idx)
        root.update()
        shot(root, "window-heatmap-cell-labels-scientific-it.png")
        i18n.set_language("en")

        def verify_english_roundtrip(dialog):
            assert dialog.field_rows[CELL_LABEL_NUMBER_FORMAT][1].get() == "Scientific"
            assert dialog.controls[CELL_LABEL_DECIMALS][1].get() == "3"
            assert dialog.controls[CELL_LABEL_FONT_SIZE][1].get() == "11.5"

        edit(mat_idx, verify_english_roundtrip)
        assert app.runs[mat_idx].options == it_recipe

        # 6. Source edit, exclusion, Undo, Use Result as Data, Format Graph, Inspector Apply/Cancel.
        app.show("data", "Matrix")
        app.edit_cell(0, 1, "9.0")
        wait()
        assert (0.5, 0.5, "$x$_9.000e+00 %") in cell_texts(mat_idx)
        app.show("data", "Matrix")
        app.current_grid.select((0, 1))
        app.toggle_exclusion()
        wait()
        assert not any(pos == (0.5, 0.5) for *pos, _ in cell_texts(mat_idx))
        app.show("data", "Matrix")
        app.apply_worksheet_history()
        wait()
        app.show("data", "Matrix")
        app.apply_worksheet_history()
        wait()
        assert (0.5, 0.5, "$x$_1.234e+00 %") in cell_texts(mat_idx)

        app.show("result", mat_idx)
        root.update()
        tables_before = len(app.tables)
        app.use_result_as_data()
        assert len(app.tables) == tables_before + 1

        app.show("graph", mat_idx)
        root.update()

        def apply_format(dialog):
            dialog.inputs["title"].set("Styled Heat Map")

        tools.drive_dialog(tools.GraphFormatDialog, apply_format)
        app.format_graph()
        assert app.runs[mat_idx].result.figure.axes[0].get_title() == "Styled Heat Map"
        assert app.runs[mat_idx].options == it_recipe

        app.toggle_inspector()
        root.update()
        panel = app.inspector
        assert panel is not None
        panel.vars["title"].set("Inspector Draft")
        panel._now("title")
        panel.cancel()
        root.update()
        assert app.runs[mat_idx].result.figure.axes[0].get_title() == "Styled Heat Map"

        app.toggle_inspector()
        root.update()
        panel = app.inspector
        panel.vars["title"].set("Inspector Applied")
        panel._now("title")
        panel.apply()
        root.update()
        assert app.runs[mat_idx].result.figure.axes[0].get_title() == "Inspector Applied"
        assert app.runs[mat_idx].options == it_recipe
        assert (0.5, 0.5, "$x$_1.234e+00 %") in cell_texts(mat_idx)
        app.toggle_inspector()
        app.inspector_wanted = False
        root.update()

        # 7. Two-panel layout export & .alab save/reopen (graph first).
        def compose(dialog):
            dialog.name.set("Cell labels layout")
            dialog.columns.set("2")
            dialog.list.selection_clear(0, "end")
            for number, item in enumerate(dialog.runs):
                if app.runs.index(item) in {mat_idx, cat_idx}:
                    dialog.list.selection_set(number)
            dialog.add_selected()

        tools.drive_dialog(tools.LayoutDialog, compose)
        app.new_layout()
        root.update()
        layout_idx = next(i for i, item in enumerate(app.layouts) if item.name == "Cell labels layout")
        app.show("layout", layout_idx)
        root.update()
        for ext in ("svg", "pdf"):
            target = out / f"heatmap-cell-labels-layout.{ext}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, ext
        ET.parse(out / "heatmap-cell-labels-layout.svg")

        saved_options = dict(app.runs[mat_idx].options)
        saved_texts = cell_texts(mat_idx)
        app.path = directory / "heatmap-cell-labels-saved.alab"
        assert app.save()
        app.import_file(app.path)
        reopened = find_run("Matrix", 0)
        app.open_sheet(("graph", reopened))
        wait()
        assert app.runs[reopened].options == saved_options
        assert cell_texts(reopened) == saved_texts
        assert not errors, errors
    finally:
        i18n.set_language(original_language)
        if app.inspector is not None:
            app.toggle_inspector()
        app.inspector_wanted = False
        if original_geometry:
            root.geometry(original_geometry)
            root.update()
